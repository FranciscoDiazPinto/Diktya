"""HU009/HU010/HU012/HU013: verificación, rollback, compensación, conciliación y trazas.

Todas las pruebas usan controladores simulados: ninguna llamada sale a la red.
"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.agents.incidents import incident_reporter
from app.agents.models import AgentEvent
from app.auth.models import AuthAuditEvent
from app.changes.csv_service import utc_now
from app.changes.models import VlanReservation, WifiWriteLease
from app.changes.ssid_executor import WriteUncertain
from app.changes.ssid_schemas import SsidConfirm, SsidProposal
from app.core.config import Settings
from app.core.errors import AccessDenied, Conflict, ServiceUnavailable
from app.tickets.models import Ticket
from tests.test_ssid_plans import execution_service, ssid_setup  # noqa: F401
from tests.test_ssid_vlan_change import _confirm, _preview, _service


def vlan_writer(*, update=None, verify=True, observed=None):
    """Controlador simulado: `observed` es la red que informa una lectura posterior."""
    verification = AsyncMock(side_effect=verify) if isinstance(verify, list) else AsyncMock(return_value=verify)
    reading = AsyncMock(side_effect=observed) if isinstance(observed, Exception) else AsyncMock(return_value=observed)
    return SimpleNamespace(update_vlan=AsyncMock(side_effect=update), verify_vlan=verification, read_network=reading)


def ready(db_session, x, writer):
    service = _service(db_session, x)
    plan = _preview(service, x)
    _confirm(service, x, plan)
    service.settings = Settings(_env_file=None, unifi_inventory_mode='api', unifi_write_enabled=True,
                                unifi_api_contract='10.6.106')
    service.writer = writer
    service.incidents = incident_reporter(service.settings, 'changes')
    return service, plan


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def actions(db):
    return list(db.scalars(select(AuthAuditEvent.action).where(AuthAuditEvent.action.like('wifi.ssid_vlan_change.%'))
                           .order_by(AuthAuditEvent.id)))


def test_unverified_vlan_change_is_rolled_back_and_escalated(db_session, ssid_setup):
    writer = vlan_writer(verify=[False, False, True], observed='network-30')
    service, plan = ready(db_session, ssid_setup, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'rolled_back' and result['executed'] is False
    # Segunda escritura: restaurar exactamente la red previa aprobada.
    assert writer.update_vlan.await_args_list[1].args[:4] == ('demo-site', 'ssid-123', 'network-30', 'network-20')
    assert count(db_session, WifiWriteLease) == 0
    ticket = db_session.scalar(select(Ticket))
    assert ticket.incident_type == 'verification_failed' and ticket.criticality == 'alta'
    assert actions(db_session) == ['wifi.ssid_vlan_change.requested', 'wifi.ssid_vlan_change.confirmed',
                                   'wifi.ssid_vlan_change.started', 'wifi.ssid_vlan_change.rolled_back']
    assert db_session.scalar(select(AgentEvent.agent_id)) == 'changes'


def test_failed_rollback_keeps_lock_and_opens_critical_ticket(db_session, ssid_setup):
    writer = vlan_writer(verify=[False, False, False], observed='network-30')
    service, plan = ready(db_session, ssid_setup, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'rollback_failed' and result['needs_reconciliation'] is True
    assert count(db_session, WifiWriteLease) == 1
    ticket = db_session.scalar(select(Ticket))
    assert ticket.incident_type == 'rollback_failed' and ticket.criticality == 'critica'
    with pytest.raises(Conflict):
        asyncio.run(service.execute_vlan_change(plan['id']))


def test_write_that_was_not_applied_fails_without_restoring(db_session, ssid_setup):
    writer = vlan_writer(update=WriteUncertain(), observed='network-20')
    service, plan = ready(db_session, ssid_setup, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'failed'
    assert writer.update_vlan.await_count == 1  # nunca se repite la escritura ambigua
    assert count(db_session, WifiWriteLease) == 0 and count(db_session, Ticket) == 0


def test_ambiguous_write_that_did_apply_is_recognised_instead_of_reverted(db_session, ssid_setup):
    writer = vlan_writer(update=WriteUncertain(), verify=True, observed='network-30')
    service, plan = ready(db_session, ssid_setup, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'completed' and writer.update_vlan.await_count == 1
    assert count(db_session, WifiWriteLease) == 0 and count(db_session, Ticket) == 0


def test_third_party_change_is_never_overwritten(db_session, ssid_setup):
    writer = vlan_writer(verify=False, observed='network-99')
    service, plan = ready(db_session, ssid_setup, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'uncertain' and writer.update_vlan.await_count == 1
    assert count(db_session, WifiWriteLease) == 1
    assert db_session.scalar(select(Ticket.incident_type)) == 'verification_failed'


@pytest.mark.parametrize('observed,expected', [('network-30', 'completed'), ('network-20', 'failed')])
def test_reconciliation_only_reads_and_releases_the_lock(db_session, ssid_setup, observed, expected):
    writer = vlan_writer(update=WriteUncertain(), observed=ServiceUnavailable('sin lectura'))
    service, plan = ready(db_session, ssid_setup, writer)
    assert asyncio.run(service.execute_vlan_change(plan['id']))['status'] == 'uncertain'
    writer.read_network = AsyncMock(return_value=observed)
    result = asyncio.run(service.reconcile_vlan_change(plan['id']))
    assert result['status'] == expected and writer.update_vlan.await_count == 1
    assert count(db_session, WifiWriteLease) == 0
    with pytest.raises(Conflict):
        asyncio.run(service.reconcile_vlan_change(plan['id']))


def test_vlan_plan_listing_and_cancellation_are_private(client, db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    assert plan['impact'] and plan['target_vlan'] == 30
    assert [p['id'] for p in service.list_vlan_changes(x.tech)] == [plan['id']]
    assert client.get('/api/v1/changes/ssid-vlan-change-plans', headers=x.headers).json()[0]['id'] == plan['id']
    assert client.get('/api/v1/changes/ssid-vlan-change-plans', headers=x.admin).json() == []
    assert client.get(f"/api/v1/changes/ssid-vlan-change-plans/{plan['id']}", headers=x.admin).status_code == 404
    cancelled = client.post(f"/api/v1/changes/ssid-vlan-change-plans/{plan['id']}/cancel", headers=x.headers)
    assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
    assert client.post(f"/api/v1/changes/ssid-vlan-change-plans/{plan['id']}/cancel", headers=x.headers).status_code == 409


def test_reconcile_endpoint_is_reserved_to_administrators(client, db_session, ssid_setup):
    x = ssid_setup
    plan = _preview(_service(db_session, x), x)
    assert client.post(f"/api/v1/changes/reconcile/vlan/{plan['id']}", headers=x.headers).status_code == 403
    # Un plan que no está detenido no se concilia.
    assert client.post(f"/api/v1/changes/reconcile/vlan/{plan['id']}", headers=x.admin).status_code == 409


# ----------------------------------------------------------------- creación de SSID


def run_creation(db_session, x, writer):
    service = execution_service(db_session, x, writer)
    service.incidents = incident_reporter(service.settings, 'changes')

    async def run():
        plan = await service.prepare(x.tech, SsidProposal(**x.proposal))
        await service.confirm(x.tech, plan.id, SsidConfirm(revision=plan.revision, row_numbers=[1]))
        return await service.execute(plan.id)
    return service, asyncio.run(run())


def creator(**extra):
    async def create(site, proposal, authorize):
        authorize()
        return 'created-by-plan'
    return SimpleNamespace(profile=lambda _: {}, create=AsyncMock(side_effect=create), **extra)


def test_unverified_ssid_is_deleted_only_if_created_by_the_job(client, db_session, ssid_setup):
    writer = creator(verify=AsyncMock(return_value=False), delete_created=AsyncMock(return_value=True))
    _, result = run_creation(db_session, ssid_setup, writer)
    assert result.status == 'failed'
    assert result.execution_results[0]['status'] == 'rolled_back'
    writer.delete_created.assert_awaited_once_with('demo-site', 'created-by-plan', 'Clientes-Feria')
    assert count(db_session, WifiWriteLease) == 0
    assert db_session.scalar(select(Ticket.incident_type)) == 'verification_failed'


def test_failed_compensation_keeps_the_ssid_locked(client, db_session, ssid_setup):
    writer = creator(verify=AsyncMock(return_value=False), delete_created=AsyncMock(return_value=False))
    _, result = run_creation(db_session, ssid_setup, writer)
    assert result.status == 'uncertain' and result.execution_results[0]['status'] == 'rollback_failed'
    assert count(db_session, WifiWriteLease) == 1
    assert db_session.scalar(select(Ticket.criticality)) == 'critica'


def test_rejection_before_writing_is_a_clean_failure(client, db_session, ssid_setup):
    writer = SimpleNamespace(profile=lambda _: {}, verify=AsyncMock(),
                             create=AsyncMock(side_effect=ServiceUnavailable('versión distinta')))
    _, result = run_creation(db_session, ssid_setup, writer)
    assert result.status == 'failed' and result.execution_results[0]['status'] == 'failed'
    assert count(db_session, WifiWriteLease) == 0 and count(db_session, Ticket) == 0


def test_verified_ssid_marks_its_vlan_reservation_as_assigned(client, db_session, ssid_setup):
    x = ssid_setup
    now = utc_now()
    db_session.add(VlanReservation(parent_interface='igc1', tag=20, interface_name='vlan0.20', event_name='Feria',
                                   purpose='Clientes', ssid='Clientes-Feria', status='reserved',
                                   requested_by_id=x.tech.id, created_at=now, expires_at=now + timedelta(hours=1)))
    db_session.commit()
    _, result = run_creation(db_session, x, creator(verify=AsyncMock(return_value=True)))
    assert result.status == 'completed'
    reservation = db_session.scalar(select(VlanReservation))
    db_session.refresh(reservation)
    assert reservation.status == 'assigned' and reservation.assigned_at is not None and reservation.expires_at is None


def test_reconciling_an_uncertain_creation_uses_the_inventory(client, db_session, ssid_setup):
    writer = SimpleNamespace(profile=lambda _: {}, create=AsyncMock(side_effect=WriteUncertain()), verify=AsyncMock(return_value=True))
    service, result = run_creation(db_session, ssid_setup, writer)
    assert result.status == 'uncertain'
    plan_id = result.id
    service.inventory.read.return_value = {'ssids': [{'id': 'remote-1', 'ssid': 'Clientes-Feria'}]}
    reconciled = asyncio.run(service.reconcile(plan_id))
    assert reconciled.status == 'completed'
    assert reconciled.execution_results == [{'ssid': 'Clientes-Feria', 'status': 'verified_configuration', 'external_id': 'remote-1'}]
    assert count(db_session, WifiWriteLease) == 0 and writer.create.await_count == 1


def test_reconciling_an_absent_ssid_closes_the_plan_as_failed(client, db_session, ssid_setup):
    writer = SimpleNamespace(profile=lambda _: {}, create=AsyncMock(side_effect=WriteUncertain()), verify=AsyncMock())
    service, result = run_creation(db_session, ssid_setup, writer)
    service.inventory.read.return_value = {'ssids': []}
    assert asyncio.run(service.reconcile(result.id)).status == 'failed'
    assert count(db_session, WifiWriteLease) == 0


# ------------------------------------------------------------------- reservas HU009


def test_expired_reservation_frees_the_vlan_and_conflicts_explain_the_owner(client, db_session, admin_user, login):
    _, headers = login('admin@example.com', 'admin-password')
    body = {'parent_interface': 'igc1', 'tag': 20, 'event_name': 'Feria', 'purpose': 'Clientes', 'ssid': 'Feria'}
    created = client.post('/api/v1/changes/vlan-reservations', headers=headers, json=body)
    assert created.status_code == 201 and created.json()['expires_at'] is not None
    conflict = client.post('/api/v1/changes/vlan-reservations', headers=headers, json=body)
    assert conflict.status_code == 409
    assert '«Feria»' in conflict.json()['detail'] and 'igc1.30' in conflict.json()['detail']
    row = db_session.get(VlanReservation, created.json()['id'])
    row.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()
    assert client.get('/api/v1/changes/vlan-reservations', headers=headers).json() == []
    db_session.refresh(row)
    assert row.status == 'released' and row.released_by_id is None  # liberada por el sistema
    assert client.post('/api/v1/changes/vlan-reservations', headers=headers, json=body).status_code == 201


def test_technician_reads_only_own_audit_trail(client, db_session, ssid_setup):
    x = ssid_setup
    _preview(_service(db_session, x), x)
    assert client.get('/api/v1/audit', headers=x.headers).status_code == 403
    own = client.get('/api/v1/audit/mine', headers=x.headers)
    assert own.status_code == 200
    items = own.json()['items']
    assert items and {item['actor_id'] for item in items} == {x.tech.id}
    assert 'wifi.ssid_vlan_change.requested' in {item['action'] for item in items}
    # El filtro de actor no puede ampliarse desde el navegador.
    other = client.get('/api/v1/audit/mine?actor_id=1', headers=x.headers)
    assert {item['actor_id'] for item in other.json()['items']} == {x.tech.id}


# ------------------------------------------------------------- chat: solo propuestas


def test_chat_tools_propose_changes_without_persisting_or_executing(client, db_session, ssid_setup):
    from app.auth.roles import effective_permissions
    from app.changes.models import DeviceRestartPlan, SsidVlanChangePlan
    from app.changes.restart_service import DeviceRestartService
    from app.chat.tools import ChatToolPermissionError, invoke_tool, openrouter_tool_definitions
    x = ssid_setup
    service = _service(db_session, x)
    service.scope_ssids = AsyncMock(return_value=[{'id': 'ssid-123', 'ssid': 'WiFi-Invitados'}])
    restarts = DeviceRestartService(db_session, x.settings, writer=SimpleNamespace())
    permissions = effective_permissions(x.tech)
    names = {tool['function']['name'] for tool in openrouter_tool_definitions(permissions)}
    assert {'get_scope_ssids', 'prepare_vlan_change', 'prepare_device_restart'} <= names
    assert 'get_access_points' not in names  # el técnico no tiene monitoreo global
    assert not any('execute' in name or 'confirm' in name or 'reconcile' in name for name in names)

    def call(name, arguments, **extra):
        return asyncio.run(invoke_tool(name, arguments, None, permissions, ssid_context=(service, x.tech),
                                       restart_service=restarts, **extra))

    assert call('get_scope_ssids', {'scope_id': x.scope}) == {'data': [{'id': 'ssid-123', 'ssid': 'WiFi-Invitados'}]}
    vlan = call('prepare_vlan_change', {'scope_id': x.scope, 'broadcast_id': 'ssid-123', 'network_id': 'network-30',
                                        'purpose': 'Migración'})
    assert vlan['status'] == 'awaiting_confirmation' and vlan['target_vlan'] == 30
    restart = call('prepare_device_restart', {'scope_id': x.scope, 'device_id': 'demo-ap-1', 'purpose': 'Sin respuesta'})
    assert restart['proposal']['device_id'] == 'demo-ap-1'
    # Un equipo fuera del ámbito no se propone ni se revela.
    foreign = call('prepare_device_restart', {'scope_id': x.scope, 'device_id': 'gateway-1', 'purpose': 'x'})
    assert foreign['status'] == 'unavailable'
    assert count(db_session, SsidVlanChangePlan) == 0 and count(db_session, DeviceRestartPlan) == 0
    with pytest.raises(ChatToolPermissionError):
        call('get_access_points', {}, access_points=lambda: {'data': []})


def test_access_point_overview_reports_state_without_addresses(db_session):
    from datetime import datetime, timezone
    from app.monitoring.inventory import access_point_overview
    from app.monitoring.models import MonitoredDevice, SourceState
    now = datetime.now(timezone.utc)
    db_session.add_all([
        SourceState(source='mock', status='ok', last_success_at=now, consecutive_failures=0),
        MonitoredDevice(source='mock', external_id='ap1', name='AP Hall', device_type='ap', state='offline',
                        mac_address='aa:bb:cc:dd:ee:ff', ip_address='10.0.0.5', last_seen_at=now),
        MonitoredDevice(source='mock', external_id='sw1', name='Switch', device_type='switch', state='online',
                        last_seen_at=now)])
    db_session.commit()
    overview = access_point_overview(db_session, Settings(_env_file=None, monitoring_provider='mock', unifi_enabled=False))
    assert overview['total'] == 1 and overview['data'][0]['name'] == 'AP Hall' and overview['data'][0]['state'] == 'offline'
    assert '10.0.0.5' not in str(overview) and 'aa:bb' not in str(overview)

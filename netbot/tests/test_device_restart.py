"""HU011: reinicio confirmado, exclusión, mantenimiento, espera de retorno y escalamiento."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.agents.incidents import incident_reporter
from app.auth.models import AuthAuditEvent, User
from app.changes.csv_service import utc_now
from app.changes.models import DeviceRestartPlan, WifiWriteLease
from app.changes.restart_service import DeviceRestartService
from app.changes.ssid_executor import UniFiSsidWriter, WriteUncertain
from app.changes.ssid_schemas import DeviceRestartProposal, PlanRevision
from app.core.config import Settings
from app.core.errors import AccessDenied, Conflict, NotFound
from app.monitoring.maintenance import devices_in_maintenance
from app.monitoring.models import MaintenanceWindow
from app.tickets.models import Ticket
from tests.test_ssid_plans import ssid_setup  # noqa: F401

SETTINGS = dict(unifi_inventory_mode='api', unifi_write_enabled=True, unifi_api_contract='10.6.106',
                device_restart_timeout_seconds=30, device_restart_poll_seconds=5)


def device(state='ONLINE', uptime=5000, access_point=True, name='AP Hall'):
    return {'id': 'demo-ap-1', 'name': name, 'state': state, 'access_point': access_point, 'uptime_seconds': uptime}


class Clock:
    """Tiempo simulado: cada espera avanza el reloj sin dormir."""

    def __init__(self):
        self.now = 0.0

    async def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


def service(db_session, states, *, restart=None, clients=7):
    clock = Clock()
    writer = SimpleNamespace(device=AsyncMock(side_effect=states), connected_clients=AsyncMock(return_value=clients),
                             restart=AsyncMock(side_effect=restart))
    settings = Settings(_env_file=None, **SETTINGS)
    return DeviceRestartService(db_session, settings, writer=writer, incidents=incident_reporter(settings, 'changes'),
                                sleep=clock.sleep, monotonic=clock.monotonic), writer


def approve(svc, actor, scope, device_id='demo-ap-1'):
    plan = asyncio.run(svc.propose(actor, DeviceRestartProposal(scope_id=scope, device_id=device_id, purpose='AP sin respuesta')))
    return svc.confirm(actor, plan['id'], PlanRevision(revision=plan['revision']))


def admin(db_session):
    return db_session.scalar(select(User).where(User.email == 'admin@example.com'))


def test_restart_requires_confirmation_then_waits_for_the_device_to_return(db_session, ssid_setup):
    x = ssid_setup
    svc, writer = service(db_session, [device(), device(), device('OFFLINE', None), device('ONLINE', 12)])
    plan = asyncio.run(svc.propose(x.tech, DeviceRestartProposal(scope_id=x.scope, device_id='demo-ap-1', purpose='Sin respuesta')))
    assert plan['status'] == 'preview' and plan['requires_confirmation'] is True
    assert '7 cliente(s)' in plan['impact'] and plan['device_state'] == 'ONLINE'
    # Sin confirmación explícita el worker no reinicia nada.
    with pytest.raises(Conflict):
        asyncio.run(svc.execute(plan['id']))
    writer.restart.assert_not_awaited()
    with pytest.raises(Conflict):
        svc.confirm(x.tech, plan['id'], PlanRevision(revision='0' * 64))
    svc.confirm(x.tech, plan['id'], PlanRevision(revision=plan['revision']))
    result = asyncio.run(svc.execute(plan['id']))
    assert result['status'] == 'completed' and result['execution_results'][0]['status'] == 'returned_online'
    assert writer.restart.await_count == 1
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 0
    window = db_session.scalar(select(MaintenanceWindow))
    assert window.external_id == 'demo-ap-1' and window.closed_at is not None
    logged = list(db_session.scalars(select(AuthAuditEvent.action).where(AuthAuditEvent.action.like('device.restart.%'))
                                     .order_by(AuthAuditEvent.id)))
    assert logged == ['device.restart.requested', 'device.restart.confirmed', 'device.restart.started',
                      'device.restart.completed']
    with pytest.raises(Conflict):  # una aprobación, una sola ejecución
        asyncio.run(svc.execute(plan['id']))


def test_device_that_does_not_return_fails_and_opens_a_ticket(db_session, ssid_setup):
    x = ssid_setup
    svc, _ = service(db_session, [device(), device()] + [device('OFFLINE', None)] * 10)
    plan = approve(svc, x.tech, x.scope)
    result = asyncio.run(svc.execute(plan['id']))
    assert result['status'] == 'failed' and result['execution_results'][0]['status'] == 'did_not_return'
    ticket = db_session.scalar(select(Ticket))
    assert ticket.incident_type == 'restart_failed' and 'no volvió en línea' in ticket.summary
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 0
    assert devices_in_maintenance(db_session, 'unifi', utc_now()) == set()


def test_online_without_evidence_of_restart_is_reported_as_unconfirmed(db_session, ssid_setup):
    x = ssid_setup
    svc, _ = service(db_session, [device(uptime=None)] * 12)
    plan = approve(svc, x.tech, x.scope)
    result = asyncio.run(svc.execute(plan['id']))
    assert result['status'] == 'completed'
    assert result['execution_results'][0]['status'] == 'online_restart_unconfirmed'


def test_ambiguous_restart_keeps_the_device_locked_until_reconciled(db_session, ssid_setup):
    x = ssid_setup
    svc, writer = service(db_session, [device(), device(), device(), device('OFFLINE'), device()], restart=WriteUncertain())
    plan = approve(svc, x.tech, x.scope)
    result = asyncio.run(svc.execute(plan['id']))
    assert result['status'] == 'uncertain' and result['needs_reconciliation'] is True
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 1
    # No se permite otro reinicio del mismo equipo mientras haya uno sin resolver.
    with pytest.raises(Conflict):
        asyncio.run(svc.propose(x.tech, DeviceRestartProposal(scope_id=x.scope, device_id='demo-ap-1', purpose='Otro')))
    with pytest.raises(Conflict):
        asyncio.run(svc.reconcile(plan['id']))  # sigue fuera de línea
    assert asyncio.run(svc.reconcile(plan['id']))['status'] == 'completed'
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 0
    assert writer.restart.await_count == 1


def test_technician_cannot_restart_critical_or_foreign_devices(db_session, ssid_setup):
    x = ssid_setup
    svc, writer = service(db_session, [device(access_point=False, name='Gateway')] * 4)
    with pytest.raises(NotFound):
        asyncio.run(svc.propose(x.tech, DeviceRestartProposal(scope_id=x.scope, device_id='gateway-1', purpose='x')))
    writer.device.assert_not_awaited()
    # Un equipo del ámbito que no se acredita como AP se trata como crítico.
    with pytest.raises(AccessDenied):
        asyncio.run(svc.propose(x.tech, DeviceRestartProposal(scope_id=x.scope, device_id='demo-ap-1', purpose='x')))
    plan = asyncio.run(svc.propose(admin(db_session), DeviceRestartProposal(scope_id=x.scope, device_id='gateway-1', purpose='Mantención')))
    assert plan['access_point'] is False and 'crítico' in plan['impact']
    assert db_session.scalar(select(func.count()).select_from(DeviceRestartPlan)) == 1


def test_revoked_scope_blocks_a_confirmed_restart(db_session, ssid_setup):
    from app.changes.models import WifiScopeGrant
    x = ssid_setup
    svc, writer = service(db_session, [device()] * 4)
    plan = approve(svc, x.tech, x.scope)
    db_session.delete(db_session.get(WifiScopeGrant, (x.scope, x.tech.id)))
    db_session.commit()
    with pytest.raises(NotFound):
        asyncio.run(svc.execute(plan['id']))
    writer.restart.assert_not_awaited()


def test_restart_api_is_denied_to_viewers_and_private_to_its_owner(client, db_session, ssid_setup, viewer_user, login):
    x = ssid_setup
    _, viewer = login('viewer@example.com', 'viewer-password')
    body = {'scope_id': x.scope, 'device_id': 'demo-ap-1', 'purpose': 'Prueba'}
    assert client.post('/api/v1/changes/device-restart-plans', headers=viewer, json=body).status_code == 403
    # El inventario simulado nunca prepara reinicios sobre equipos.
    assert client.post('/api/v1/changes/device-restart-plans', headers=x.headers, json=body).status_code == 409
    assert client.get('/api/v1/changes/device-restart-plans', headers=x.headers).json() == []
    assert client.post('/api/v1/changes/device-restart-plans', headers=x.headers,
                       json={**body, 'force': True}).status_code == 422


def test_writer_sends_one_official_restart_action_with_the_write_key():
    import httpx
    import json
    seen = []

    def respond(request):
        seen.append((request.method, request.url.raw_path.decode(), request.headers['x-api-key']))
        if request.url.path.endswith('/info'):
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        assert json.loads(request.content) == {'action': 'RESTART'}
        return httpx.Response(200)
    settings = Settings(_env_file=None, unifi_inventory_mode='api', unifi_write_enabled=True, unifi_api_contract='10.6.106',
                        unifi_api_base_url='https://controller.example.test/proxy/network/integration/v1',
                        unifi_api_key='read-key', unifi_write_api_key='write-key')
    authorized = []
    asyncio.run(UniFiSsidWriter(settings, httpx.MockTransport(respond)).restart('site 1', 'ap/1', lambda: authorized.append(1)))
    assert authorized == [1]
    assert seen[-1] == ('POST', '/proxy/network/integration/v1/sites/site%201/devices/ap%2F1/actions', 'write-key')


def test_writer_reads_device_state_and_counts_clients_without_guessing():
    import httpx

    def respond(request):
        path = request.url.path
        if path.endswith('/statistics/latest'):
            return httpx.Response(200, json={'uptimeSec': 90, 'interfaces': {}})
        if path.endswith('/clients'):
            return httpx.Response(200, json={'offset': 0, 'limit': 200, 'count': 3, 'totalCount': 3, 'data': [
                {'id': 'c1', 'uplinkDeviceId': 'ap1'}, {'id': 'c2', 'uplinkDeviceId': 'other'}, {'id': 'c3', 'uplinkDeviceId': 'ap1'}]})
        return httpx.Response(200, json={'id': 'ap1', 'name': 'AP Hall', 'state': 'ONLINE', 'features': {'accessPoint': {}}})
    settings = Settings(_env_file=None, unifi_inventory_mode='api',
                        unifi_api_base_url='https://controller.example.test/proxy/network/integration/v1', unifi_api_key='k')
    writer = UniFiSsidWriter(settings, httpx.MockTransport(respond))
    assert asyncio.run(writer.device('site1', 'ap1')) == {'id': 'ap1', 'name': 'AP Hall', 'state': 'ONLINE',
                                                         'access_point': True, 'uptime_seconds': 90}
    assert asyncio.run(writer.connected_clients('site1', 'ap1')) == 2
    broken = UniFiSsidWriter(settings, httpx.MockTransport(lambda request: httpx.Response(500)))
    assert asyncio.run(broken.connected_clients('site1', 'ap1')) is None  # desconocido, no cero

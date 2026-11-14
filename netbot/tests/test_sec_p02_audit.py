"""Auditoría 2026-11: la tabla inmutable no crece sin cuenta y lo privilegiado deja rastro."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.auth.models import AuthAuditEvent, Role, User
from app.auth.security import hash_password
from app.core.config import Settings, get_settings
from app.chat.guest import sessions
from app.chat.guest_router import get_recovery_mailer
from app.main import app
from app.networks.models import Network, NetworkRecipient
from app.networks.support_models import NetworkSupportConfig
from tests.test_email_recovery import approve, raw_token, recovery_email, send  # noqa: F401
from tests.test_ssid_plans import execution_service, ssid_setup  # noqa: F401


def rows(db, action=None):
    query = select(AuthAuditEvent)
    return list(db.scalars(query.where(AuthAuditEvent.action == action) if action else query))


def test_anonymous_denials_are_sampled(client, db_session):
    assert [client.get('/auth/me').status_code for _ in range(50)] == [401] * 50
    assert len(rows(db_session, 'access.denied')) == 5


def test_denials_of_a_known_identity_are_always_recorded(client, db_session, viewer_user, login):
    _, headers = login(viewer_user.email, 'viewer-password')
    for _ in range(12):
        assert client.get('/admin/users', headers=headers).status_code == 403
    assert len(rows(db_session, 'access.denied')) == 12


def test_audit_identifies_the_origin_without_storing_the_address(client, db_session, admin_user, login):
    login(admin_user.email, 'admin-password')
    event = rows(db_session, 'auth.login.succeeded')[0]
    assert len(event.details['peer']) == 32
    assert 'testclient' not in json.dumps(event.details)


def test_network_inventory_and_assignments_are_audited(client, db_session, admin_user, viewer_user, login):
    _, headers = login(admin_user.email, 'admin-password')
    network = client.post('/admin/networks', headers=headers, json={'name': 'Feria', 'site': 's', 'event_name': 'e',
                                                                    'external_id': 'x', 'ssid': 'Feria'}).json()
    client.put(f"/admin/networks/{network['id']}/users/{viewer_user.id}", headers=headers)
    client.delete(f"/admin/networks/{network['id']}/users/{viewer_user.id}", headers=headers)
    assert rows(db_session, 'network.created')[0].details['network_id'] == network['id']
    assert [e.target_id for e in rows(db_session, 'network.assigned')] == [viewer_user.id]
    assert [e.actor_id for e in rows(db_session, 'network.unassigned')] == [admin_user.id]


def test_wifi_scope_changes_are_audited(client, db_session, admin_user, viewer_user, login):
    _, headers = login(admin_user.email, 'admin-password')
    response = client.post('/api/v1/changes/wifi-scopes', headers=headers, json={
        'name': 'S', 'site_id': 'demo-site', 'event_name': 'e', 'ap_ids': ['a'], 'security_profiles': ['p'],
        'networks': [{'id': 'n', 'parent_interface': 'igc1', 'tag': 20}], 'user_ids': [viewer_user.id]})
    assert response.status_code == 201
    assert rows(db_session, 'wifi.scope.saved')[0].details['user_ids'] == [viewer_user.id]


def test_credential_disclosure_by_email_is_audited_without_the_address(client, recovery_email, db_session):
    send(client, recovery_email)
    assert approve(client, raw_token(recovery_email)).status_code == 200
    event = rows(db_session, 'wifi.recovery.revealed')[0]
    assert event.details['network_ids'] == [recovery_email[0].id] and event.source == 'guest'
    assert rows(db_session, 'wifi.recovery.requested')
    assert 'expositor@example.com' not in json.dumps([e.details for e in rows(db_session)])


def run_plan(db_session, x, writer):
    from app.changes.ssid_schemas import SsidConfirm, SsidProposal
    service = execution_service(db_session, x, writer)
    async def run():
        plan = await service.prepare(x.tech, SsidProposal(**x.proposal))
        await service.confirm(x.tech, plan.id, SsidConfirm(revision=plan.revision, row_numbers=[1]))
        return plan.id, (await service.execute(plan.id)).status
    return asyncio.run(run())


def test_ssid_plan_lifecycle_leaves_a_trace_with_its_actor(client, db_session, ssid_setup):
    async def create(site, proposal, authorize):
        authorize()
        return 'creado'
    writer = SimpleNamespace(profile=lambda _: {}, create=AsyncMock(side_effect=create), verify=AsyncMock(return_value=True))
    plan_id, status = run_plan(db_session, ssid_setup, writer)
    assert status == 'completed'
    for action in ('ssid.plan.prepared', 'ssid.plan.confirmed', 'ssid.plan.claimed', 'ssid.plan.executed'):
        event = rows(db_session, action)[0]
        assert event.actor_id == ssid_setup.tech.id and event.details['plan_id'] == plan_id
    executed = rows(db_session, 'ssid.plan.executed')[0]
    assert executed.source == 'worker' and executed.outcome == 'success' and executed.details['status'] == 'completed'


def test_uncertain_execution_is_recorded_as_a_failure(client, db_session, ssid_setup):
    from app.changes.ssid_executor import WriteUncertain
    writer = SimpleNamespace(profile=lambda _: {}, create=AsyncMock(side_effect=WriteUncertain()), verify=AsyncMock())
    _, status = run_plan(db_session, ssid_setup, writer)
    assert status == 'uncertain'
    event = rows(db_session, 'ssid.plan.executed')[0]
    assert event.outcome == 'failure' and event.details['status'] == 'uncertain'
    assert 'test-only-password' not in json.dumps(event.details)

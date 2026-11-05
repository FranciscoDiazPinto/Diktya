import csv
import io
from datetime import datetime, timezone

import pytest
from app.audit import service
from app.audit.schemas import AuditFilters
from app.auth.models import AuthAuditEvent, Role, User
from app.core.errors import AccessDenied, Unauthenticated, InvalidInput
from app.networks.support_models import SupportAudit
from app.networks.models import Network
from app.tickets.models import Ticket, TicketEvent

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def seed(db, actor):
    network = Network(name='Demo', site='lab', event_name='Demo', external_id='demo', ssid='Demo', vlan_tag=50)
    db.add(network); db.flush()
    ticket = Ticket(network_id=network.id, created_by_id=actor.id, request_key='audit-demo', summary='private', description='secret body')
    db.add(ticket); db.flush()
    db.add_all([
        AuthAuditEvent(actor_id=actor.id, target_id=actor.id, action='auth.login', outcome='success', source='http', details={'password': 'DO-NOT-EXPORT'}, created_at=NOW),
        SupportAudit(actor_id=actor.id, network_id=network.id, action='wifi.revealed', created_at=NOW),
        TicketEvent(ticket_id=ticket.id, actor_id=None, kind='status', status='open', note='DO-NOT-EXPORT', created_at=NOW),
    ])
    db.commit()


def test_admin_page_filters_and_csv(client, db_session, admin_user, login):
    seed(db_session, admin_user)
    _, headers = login(admin_user.email, 'admin-password')
    response = client.get('/api/v1/audit', headers=headers)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page['total'] >= 4
    assert {'auth', 'support', 'tickets'} <= {e['source'] for e in page['items']}
    assert all(e['occurred_at'].endswith('Z') for e in page['items'])
    assert 'DO-NOT-EXPORT' not in response.text
    assert response.headers['cache-control'] == 'no-store, private'
    params = {'source': 'support', 'actor_id': admin_user.id, 'action': 'wifi.revealed', 'outcome': 'success',
              'since': '2026-11-05T08:59:59-03:00', 'until': '2026-11-05T09:00:01-03:00'}
    filtered = client.get('/api/v1/audit', headers=headers, params=params)
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()['total'] == 1
    exported = client.get('/api/v1/audit/export', headers=headers, params=params)
    assert exported.status_code == 200, exported.text
    records = list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    assert len(records) == 1 and records[0]['action'] == 'wifi.revealed'
    assert 'DO-NOT-EXPORT' not in exported.text
    assert exported.headers['cache-control'] == 'no-store, private'
    paged = client.get('/api/v1/audit?limit=1&offset=1', headers=headers).json()
    assert len(paged['items']) == 1 and paged['offset'] == 1


@pytest.mark.parametrize('path', ['/api/v1/audit', '/api/v1/audit/export'])
def test_no_global_access_for_other_roles(client, db_session, viewer_user, login, path):
    assert client.get(path).status_code == 401
    _, headers = login(viewer_user.email, 'viewer-password')
    assert client.get(path, headers=headers).status_code == 403
    with pytest.raises(AccessDenied):
        service.list_entries(db_session, viewer_user, AuditFilters())
    with pytest.raises(AccessDenied):
        service.export_csv(db_session, viewer_user, AuditFilters())


@pytest.mark.parametrize('params', [{'source': 'unknown'}, {'since': '2026-11-05T12:00:00'},
    {'since': '2026-11-06T12:00:00Z', 'until': '2026-11-05T12:00:00Z'}, {'limit': 101}, {'offset': -1}])
def test_bad_filters(client, admin_user, login, params):
    _, headers = login(admin_user.email, 'admin-password')
    assert client.get('/api/v1/audit', headers=headers, params=params).status_code == 422


def test_csv_formula_guard_and_export_limit(db_session, admin_user, monkeypatch):
    db_session.add(AuthAuditEvent(actor_id=admin_user.id, action=' =HYPERLINK("bad")', outcome='success', source='http', details={}, created_at=NOW))
    db_session.commit()
    text = service.export_csv(db_session, admin_user, AuditFilters())
    assert list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))[0]['action'].startswith("' =")
    monkeypatch.setattr(service, 'EXPORT_LIMIT', 0)
    with pytest.raises(InvalidInput, match='5000'):
        service.export_csv(db_session, admin_user, AuditFilters())


@pytest.mark.parametrize('role_name', ['cliente', 'tecnico', 'operador'])
def test_scoped_roles_cannot_read_global_history(client, db_session, login, role_name):
    from app.auth.security import hash_password
    role = db_session.query(Role).filter_by(name=role_name).one()
    user = User(email=f'{role_name}@example.com', hashed_password=hash_password('demo-password'), roles=[role])
    db_session.add(user); db_session.commit()
    _, headers = login(user.email, 'demo-password')
    for path in ['/api/v1/audit', '/api/v1/audit/export']:
        assert client.get(path, headers=headers).status_code == 403


def test_plan_snapshots_are_not_execution_events(db_session, admin_user):
    from app.changes.models import WifiScope, SsidPlan, CsvImport, VlanReservation
    scope = WifiScope(name='Lab', site_id='lab', resources={})
    db_session.add(scope); db_session.flush()
    db_session.add_all([
        SsidPlan(id='plan', owner_id=admin_user.id, scope_id=scope.id, status='uncertain', source='panel', fingerprint='demo', revision='demo', rows=[{'password': 'DO-NOT-EXPORT'}], selection=[], execution_results=[{'secret': 'DO-NOT-EXPORT'}], created_at=NOW, expires_at=NOW, confirmed_at=NOW),
        CsvImport(id='csv', owner_id=admin_user.id, filename='DO-NOT-EXPORT', status='confirmed', source='panel', source_context='demo', rows=[], results=[], created_at=NOW, expires_at=NOW, confirmed_at=NOW),
        VlanReservation(parent_interface='lab', tag=50, interface_name='vlan50', event_name='demo', purpose='DO-NOT-EXPORT', ssid='private', status='released', requested_by_id=admin_user.id, created_at=NOW, released_by_id=admin_user.id, released_at=NOW),
    ])
    db_session.commit()
    page = service.list_entries(db_session, admin_user, AuditFilters())
    assert page.total == 8
    assert {e.source for e in page.items} == {'ssid', 'csv', 'reservations'}
    assert [(e.action, e.outcome) for e in page.items if e.source == 'ssid' and e.snapshot] == [('ssid_plan.snapshot', 'uncertain')]
    assert any(e.action == 'ssid_plan.confirmed' and e.outcome == 'confirmed' for e in page.items)
    assert 'DO-NOT-EXPORT' not in page.model_dump_json()
    db_session.expire(admin_user)
    admin_user.is_active = False
    db_session.commit()
    with pytest.raises(Unauthenticated):
        service.export_csv(db_session, admin_user, AuditFilters())

"""Regresiones para los límites de confianza encontrados en la auditoría."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth import service
from app.core.config import Settings
from app.core.database import engine
from app.core.errors import Unauthenticated
from app.core.request_security import SharedRequestLimits
from app.monitoring.models import MonitoredDevice
from app.auth.schemas import LoginRequest


@pytest.mark.parametrize('overrides', [
    {'jwt_secret_key': 'change-me-in-production'},
    {'jwt_secret_key': 'short'},
    {'unifi_base_url': 'http://controller.invalid'},
    {'opnsense_base_url': 'http://firewall.invalid'},
    {'unifi_api_base_url': 'http://controller.invalid'},
    {'unifi_verify_tls': False}, {'opnsense_verify_tls': False},
    {'cors_origins': 'null'}, {'cors_origins': '*'},
])
def test_production_refuses_unsafe_configuration(overrides):
    values = {'environment': 'production', 'jwt_secret_key': 'test-only-' + 'a' * 64}
    values.update(overrides)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_runtime_foreign_keys_reject_orphan_session(db_session):
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
    with pytest.raises(IntegrityError):
        db_session.execute(text("INSERT INTO refresh_tokens (token_hash,user_id,expires_at) VALUES ('orphan',99999,'2099-01-01')"))
    db_session.rollback()


def test_rate_limits_shared_between_workers_and_expire(tmp_path):
    clock = [0]
    path = tmp_path / 'rates.db'
    workers = [SharedRequestLimits(path, 'synthetic-secret', clock=lambda: clock[0]) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: workers[i % 2].admit('login', 'one-peer', 5, 20), range(12)))
    assert sum(results) == 5
    assert workers[1].admit('login', 'another-peer', 5, 20)
    assert b'one-peer' not in path.read_bytes()
    clock[0] = 60
    assert workers[0].admit('login', 'one-peer', 5, 20)


def test_public_login_throttles_before_password_work(client, monkeypatch):
    calls = []
    monkeypatch.setattr(service, 'verify_password', lambda *args: calls.append(1) or False)
    for _ in range(10):
        assert client.post('/auth/login', json={'email': 'missing@example.com', 'password': 'x'}).status_code == 401
    response = client.post('/auth/login', json={'email': 'different@example.com', 'password': 'x'},
                           headers={'X-Forwarded-For': '203.0.113.9', 'Origin': 'http://localhost:5173'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '60'
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert len(calls) == 10


def test_password_changed_during_verification_cannot_issue_token(db_session, admin_user, monkeypatch):
    original = service.verify_password
    def verify_then_change(password, encoded):
        result = original(password, encoded)
        admin_user.hashed_password = hash_password('replacement-password')
        db_session.commit()
        return result
    monkeypatch.setattr(service, 'verify_password', verify_then_change)
    with pytest.raises(Unauthenticated):
        service.login(LoginRequest(email=admin_user.email, password='admin-password'), db_session)


def test_technician_cannot_enumerate_global_devices_via_tickets(client, db_session, login):
    role = db_session.scalar(select(Role).where(Role.name == 'tecnico'))
    user = User(email='limited-tech@example.com', hashed_password=hash_password('synthetic-password'), roles=[role])
    device = MonitoredDevice(source='unifi', external_id='foreign-ap', name='Private inventory',
                             device_type='ap', state='online', last_seen_at=datetime.now(timezone.utc))
    db_session.add_all([user, device]); db_session.commit()
    _, headers = login(user.email, 'synthetic-password')
    response = client.post('/api/v1/tickets/manual', headers=headers, json={
        'summary': 'Synthetic incident', 'description': 'Scope test',
        'device_id': device.id, 'request_key': str(uuid4())})
    assert response.status_code == 403
    assert device.name not in response.text


def test_authentication_rejects_oversized_body_before_password_verification(client, monkeypatch):
    calls = []
    monkeypatch.setattr(service, 'verify_password', lambda *args: calls.append(1) or False)
    response = client.post('/auth/login', content=b'{' + b'x' * 65536,
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert calls == []

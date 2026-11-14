"""Auditoría 2026-11: el bloqueo por correo conocido no deja fuera al titular de la cuenta."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.models import AuthAuditEvent
from app.main import app


def attempt(client, password, email='admin@example.com'):
    return client.post('/auth/login', json={'email': email, 'password': password})


def peer(client, address):
    other = TestClient(app, client=(address, 50000))
    other.__enter__()
    return other


def test_third_party_lock_does_not_block_the_known_origin(client, db_session, admin_user):
    assert attempt(client, 'admin-password').status_code == 200
    attacker = peer(client, '203.0.113.50')
    assert [attempt(attacker, 'x').status_code for _ in range(5)] == [401] * 5
    db_session.refresh(admin_user)
    assert admin_user.login_locked_until is not None
    assert attempt(attacker, 'admin-password').status_code == 401, 'otro origen sigue bloqueado'
    assert attempt(client, 'admin-password').status_code == 200, 'el titular conserva su acceso'


def test_failure_from_known_origin_withdraws_the_exception(client, db_session, admin_user):
    assert attempt(client, 'admin-password').status_code == 200
    attacker = peer(client, '203.0.113.51')
    for _ in range(5):
        attempt(attacker, 'x')
    assert attempt(client, 'wrong-password').status_code == 401
    assert attempt(client, 'admin-password').status_code == 401
    db_session.refresh(admin_user)
    assert admin_user.last_login_peer is None


def test_lock_remains_absolute_without_a_known_origin(client, db_session, admin_user):
    for _ in range(5):
        attempt(client, 'x')
    assert attempt(client, 'admin-password').status_code == 401


def test_admin_can_unlock_and_the_action_is_audited(client, db_session, admin_user, viewer_user, login):
    _, headers = login(admin_user.email, 'admin-password')
    for _ in range(5):
        attempt(client, 'x', viewer_user.email)
    assert attempt(client, 'viewer-password', viewer_user.email).status_code == 401
    response = client.post(f'/admin/users/{viewer_user.id}/unlock', headers=headers)
    assert response.status_code == 200
    assert attempt(client, 'viewer-password', viewer_user.email).status_code == 200
    assert db_session.scalar(select(AuthAuditEvent).where(AuthAuditEvent.action == 'user.unlocked')).target_id == viewer_user.id


def test_only_user_managers_can_unlock(client, admin_user, viewer_user, login):
    _, headers = login(viewer_user.email, 'viewer-password')
    assert client.post(f'/admin/users/{admin_user.id}/unlock', headers=headers).status_code == 403


def test_resetting_the_password_clears_a_lock(client, db_session, admin_user, viewer_user, login):
    _, headers = login(admin_user.email, 'admin-password')
    viewer_user.failed_login_attempts, viewer_user.login_locked_until = 5, datetime(2099, 1, 1, tzinfo=timezone.utc)
    db_session.commit()
    assert client.patch(f'/admin/users/{viewer_user.id}', headers=headers, json={'password': 'nueva-clave-segura-1'}).status_code == 200
    db_session.refresh(viewer_user)
    assert viewer_user.login_locked_until is None

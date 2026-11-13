"""Auditoría 2026-11: reutilización de refresh, vida absoluta de sesión y purga."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.auth import service
from app.auth.models import AuthAuditEvent, RefreshToken
from app.networks.email_recovery import purge_expired
from app.networks.support_models import WifiEmailRecovery


@pytest.fixture()
def clock(monkeypatch):
    current = {'now': datetime.now(timezone.utc)}
    monkeypatch.setattr(service, '_login_now', lambda: current['now'])
    return current


def tokens_of(client, user, password):
    return client.post('/auth/login', json={'email': user.email, 'password': password}).json()


def refresh(client, token):
    return client.post('/auth/refresh', json={'refresh_token': token})


def test_reuse_after_grace_closes_every_session_of_the_account(client, db_session, viewer_user, clock):
    stolen = tokens_of(client, viewer_user, 'viewer-password')
    attacker = refresh(client, stolen['refresh_token']).json()
    clock['now'] += timedelta(seconds=11)
    assert refresh(client, stolen['refresh_token']).status_code == 401
    assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + attacker['access_token']}).status_code == 401
    assert refresh(client, attacker['refresh_token']).status_code == 401
    event = db_session.scalar(select(AuthAuditEvent).where(AuthAuditEvent.action == 'auth.refresh.reuse_detected'))
    assert event.target_id == viewer_user.id and event.outcome == 'denied'


def test_immediate_retry_from_the_same_client_does_not_close_the_session(client, viewer_user, clock):
    first = tokens_of(client, viewer_user, 'viewer-password')
    fresh = refresh(client, first['refresh_token']).json()
    assert refresh(client, first['refresh_token']).status_code == 401
    assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + fresh['access_token']}).status_code == 200


def test_rotation_cannot_extend_a_session_past_its_absolute_limit(client, db_session, viewer_user, clock):
    token = tokens_of(client, viewer_user, 'viewer-password')['refresh_token']
    for _ in range(4):
        clock['now'] += timedelta(days=6)
        row = db_session.scalar(select(RefreshToken).order_by(RefreshToken.id.desc()))
        row.expires_at = clock['now'] + timedelta(days=7)
        db_session.commit()
        response = refresh(client, token)
        assert response.status_code == 200
        token = response.json()['refresh_token']
    clock['now'] += timedelta(days=7)
    row = db_session.scalar(select(RefreshToken).order_by(RefreshToken.id.desc()))
    row.expires_at = clock['now'] + timedelta(days=7)
    db_session.commit()
    assert refresh(client, token).status_code == 401


def test_expired_sessions_are_purged_but_recent_ones_remain(db_session, viewer_user):
    now = datetime.now(timezone.utc)
    db_session.add_all([RefreshToken(token_hash='a' * 64, user_id=viewer_user.id, expires_at=now - timedelta(days=2)),
                        RefreshToken(token_hash='b' * 64, user_id=viewer_user.id, expires_at=now - timedelta(hours=1))])
    db_session.commit()
    assert service.purge_expired_sessions(db_session, now) == 1
    assert db_session.scalar(select(func.count()).select_from(RefreshToken)) == 1


def test_expired_recovery_links_do_not_retain_the_address(db_session):
    now = datetime.now(timezone.utc)
    db_session.add(WifiEmailRecovery(id='x', token_hash='c' * 64, email='a@example.com', network_ids=[], expires_at=now))
    db_session.commit()
    assert purge_expired(db_session, now) == 1

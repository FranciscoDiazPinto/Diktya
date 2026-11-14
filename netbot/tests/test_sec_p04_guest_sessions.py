"""Auditoría 2026-11: un origen no monopoliza el cupo de atenciones de invitados."""
import pytest

from app.chat.guest import MAX_LIFETIME, MAX_SESSIONS_PER_PEER, TTL, GuestSessions
from app.core.errors import NotFound, RateLimited


def test_activity_cannot_keep_a_session_alive_forever():
    clock = [0.0]
    store = GuestSessions(clock=lambda: clock[0])
    token = store.create('peer')
    while clock[0] < MAX_LIFETIME - TTL:
        clock[0] += TTL - 1
        store.touch(token)
    clock[0] = MAX_LIFETIME + 1
    with pytest.raises(NotFound):
        store.get(token)


def test_one_origin_cannot_take_every_slot():
    clock = [0.0]
    store = GuestSessions(clock=lambda: clock[0])
    for _ in range(MAX_SESSIONS_PER_PEER):
        store.create('attacker')
    with pytest.raises(RateLimited):
        store.create('attacker')
    assert store.create('visitor')


def test_http_session_records_its_origin(client):
    from app.chat.guest import sessions
    sessions.clear()
    token = client.post('/api/v1/guest/sessions').json()['token']
    assert sessions.sessions[token].peer == 'testclient'
    sessions.clear()

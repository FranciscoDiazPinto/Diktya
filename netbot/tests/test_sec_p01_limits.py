"""Auditoría 2026-11: topes de cuerpo, cuotas por frontera y presupuesto del LLM."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.keys import derive_key
from app.core.request_security import SMALL_BODY_BYTES, SharedRequestLimits, client_peer, request_policy

JSON = {'Content-Type': 'application/json'}


@pytest.mark.parametrize('path', ['/auth/logout', '/admin/users', '/api/v1/tickets', '/api/v1/changes/ssid-plans'])
def test_anonymous_oversized_json_is_rejected_before_being_buffered(client, path):
    assert client.post(path, content=b'{"x":"' + b'a' * 400_000 + b'"}', headers=JSON).status_code == 413


def test_declared_length_rejects_without_reading_the_body(client):
    headers = {**JSON, 'Content-Length': str(10 * 1024 * 1024 * 1024)}
    assert client.post('/admin/users', content=b'{}', headers=headers).status_code == 413


def test_chunked_body_without_length_is_also_bounded(client):
    def chunks():
        for _ in range(40):
            yield b'a' * 16384
    assert client.post('/auth/logout', content=chunks(), headers=JSON).status_code == 413


def test_guests_cannot_consume_the_authenticated_chat_quota(client):
    token = client.post('/api/v1/guest/sessions').json()['token']
    guest = {'X-Guest-Session': token}
    codes = [client.post('/api/v1/guest/messages', headers=guest, json={'message': 'hola'}).status_code for _ in range(11)]
    assert codes[-1] == 429
    assert client.post('/api/v1/chat/messages', json={'message': 'estado'}).status_code == 401


def test_session_keepalive_and_qr_have_their_own_quota():
    assert request_policy('POST', '/api/v1/guest/session/activity')[0] == 'guest-touch'
    assert request_policy('POST', '/api/v1/guest/networks/7/access')[0] == 'guest-qr'
    assert request_policy('POST', '/auth/logout')[0] == 'auth-logout'
    assert request_policy('GET', '/auth/logout') is None


def test_login_flood_does_not_affect_session_renewal(tmp_path):
    limits = SharedRequestLimits(tmp_path / 'r.db', 'k', clock=lambda: 0)
    assert request_policy('POST', '/auth/login')[0] != request_policy('POST', '/auth/refresh')[0]
    assert all(limits.admit('auth-login', f'peer-{i}', 10, 5) for i in range(5))
    assert not limits.admit('auth-login', 'other', 10, 5)
    assert limits.admit('auth-refresh', 'other', 10, 5)


def test_daily_budget_is_shared_and_resets_next_day(tmp_path):
    clock = [0]
    limits = SharedRequestLimits(tmp_path / 'r.db', 'k', clock=lambda: clock[0])
    assert [limits.spend('chat-guest', 2) for _ in range(3)] == [True, True, False]
    assert limits.spend('chat-user', 2)
    clock[0] = 86400
    assert limits.spend('chat-guest', 2)


def test_llm_budget_stops_anonymous_spending_from_any_origin(client, monkeypatch):
    limits = client.app.middleware_stack
    while not hasattr(limits, 'budgets'):
        limits = limits.app
    monkeypatch.setitem(limits.budgets, 'chat-guest', 1)
    monkeypatch.setattr(limits.limits, 'spend', lambda group, limit: False)
    token = client.post('/api/v1/guest/sessions').json()['token']
    response = client.post('/api/v1/guest/messages', headers={'X-Guest-Session': token}, json={'message': 'hola'})
    assert response.status_code == 429 and 'cupo diario' in response.json()['detail']


@pytest.mark.parametrize('host,expected', [
    ('203.0.113.7', '203.0.113.7'), ('::ffff:203.0.113.7', '203.0.113.7'),
    ('2001:db8:1:2:aaaa::1', '2001:db8:1:2::'), ('2001:db8:1:2:bbbb::9', '2001:db8:1:2::'), ('testclient', 'testclient'),
])
def test_ipv6_clients_share_quota_per_prefix(host, expected):
    assert client_peer({'client': (host, 1)}) == expected


def test_each_purpose_gets_a_distinct_key():
    assert derive_key('root', 'rate-limit') != derive_key('root', 'audit-subject')
    assert 'root' not in derive_key('root', 'rate-limit')


def test_small_body_routes_keep_the_tighter_limit(client):
    assert client.post('/api/v1/guest/recovery/email', content=b'x' * (SMALL_BODY_BYTES + 1), headers=JSON).status_code == 413


def test_counters_withstand_concurrent_requests_without_rejecting_users(tmp_path):
    limits = SharedRequestLimits(tmp_path / 'r.db', 'k')
    with ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(lambda i: limits.admit('g', f'p{i % 7}', 10**6, 10**7), range(600)))
    assert all(results)

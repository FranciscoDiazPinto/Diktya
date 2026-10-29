"""Aislamiento de invitados, vencimiento y entrega pública explícita del QR."""
import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from app.main import app
from app.core.config import Settings, get_settings
from app.core.errors import NotFound, Conflict, RateLimited
from app.chat.guest import GuestSessions, TTL, sessions
from app.chat.guest_router import get_guest_provider
from app.chat.provider import ProviderCompletion, ProviderToolCall, ChatProviderError
from app.chat.models import Conversation
from app.networks.models import Network
from app.networks.support_models import NetworkSupportConfig
from app.networks.support_schemas import WifiCredential
from app.networks.wifi_qr import wifi_payload


@pytest.fixture(autouse=True)
def clean_guests():
    sessions.clear()
    yield
    sessions.clear()


def test_guest_history_is_private_and_expires_without_database():
    clock = [0]
    store = GuestSessions(clock=lambda: clock[0])
    a, b = store.create(), store.create()
    provider = SimpleNamespace(complete=AsyncMock(return_value=ProviderCompletion(content='Te ayudo.')))
    settings = Settings(_env_file=None)
    asyncio.run(store.answer(a, 'Necesito ayuda', provider, settings))
    asyncio.run(store.answer(a, '¿Y después?', provider, settings))
    assert provider.complete.call_args.kwargs['messages'][1]['content'] == 'Necesito ayuda'
    assert provider.complete.call_args.kwargs['tools'] == []
    assert store.get(b).history == []
    old = store.get(a)
    clock[0] = TTL
    store.purge()
    assert old.history == []
    assert not store.sessions
    with pytest.raises(NotFound):
        store.get(a)


def test_deleted_guest_cannot_be_resurrected_by_late_provider():
    store = GuestSessions()
    token = store.create()
    async def respond(**kwargs):
        store.delete(token)
        return ProviderCompletion(content='Respuesta tardía')
    provider = SimpleNamespace(complete=respond)
    with pytest.raises(NotFound):
        asyncio.run(store.answer(token, 'Hola', provider, Settings(_env_file=None)))
    assert not store.sessions


def test_guests_cannot_execute_provider_tools():
    store = GuestSessions()
    token = store.create()
    provider = SimpleNamespace(complete=AsyncMock(return_value=ProviderCompletion(
        content='No', tool_calls=(ProviderToolCall('x', 'get_system', {}),))))
    with pytest.raises(ChatProviderError):
        asyncio.run(store.answer(token, 'Muestra todo', provider, Settings(_env_file=None)))
    assert not store.get(token).history
    store.get(token).busy = True
    with pytest.raises(Conflict):
        asyncio.run(store.answer(token, 'Otro', provider, Settings(_env_file=None)))


def test_public_chat_accepts_no_history_or_account_and_does_not_persist(client, db_session):
    provider = SimpleNamespace(complete=AsyncMock(return_value=ProviderCompletion(content='Revisa el Wi-Fi.')))
    app.dependency_overrides[get_guest_provider] = lambda: provider
    created = client.post('/api/v1/guest/sessions')
    assert created.status_code == 201
    assert 'no-store' in created.headers['cache-control']
    headers = {'X-Guest-Session': created.json()['token']}
    path = '/api/v1/guest/messages'
    assert client.post(path, json={'message': 'Hola'}).status_code == 422
    assert client.post(path, headers=headers, json={'message': 'Hola', 'history': []}).status_code == 422
    response = client.post(path, headers=headers, json={'message': 'No conecta'})
    assert response.status_code == 200
    assert response.json()['expires_in'] == 60
    assert db_session.scalar(select(func.count()).select_from(Conversation)) == 0
    assert client.get('/api/v1/chat/conversations', headers=headers).status_code == 401
    assert client.get('/api/v1/monitoring/system', headers=headers).status_code == 401
    assert client.delete('/api/v1/guest/session', headers=headers).status_code == 204
    assert client.post(path, headers=headers, json={'message': 'Hola'}).status_code == 404


def test_only_explicit_guest_networks_reveal_qr_and_never_to_model(client, db_session):
    public = Network(name='Invitados', site='sitio', external_id='guest', event_name='evento', ssid='Guest;SSID', vlan_tag=20)
    private = Network(name='Privada', site='sitio', external_id='private', event_name='evento', ssid='Private', vlan_tag=30)
    db_session.add_all([public, private]); db_session.flush()
    db_session.add(NetworkSupportConfig(network_id=public.id, credential_ref='public'))
    db_session.commit()
    settings = Settings(_env_file=None, guest_wifi_network_ids=[public.id], wifi_access_credentials_json=json.dumps({
        'public': {'site':'sitio','external_id':'guest','ssid':'Guest;SSID','security':'open','passphrase':None}
    }))
    app.dependency_overrides[get_settings] = lambda: settings
    token = client.post('/api/v1/guest/sessions').json()['token']
    headers = {'X-Guest-Session': token}
    listed = client.get('/api/v1/guest/networks', headers=headers).json()
    assert listed == [{'id':public.id,'name':'Invitados','ssid':'Guest;SSID'}]
    assert client.post(f'/api/v1/guest/networks/{private.id}/access', headers=headers).status_code == 404
    response = client.post(f'/api/v1/guest/networks/{public.id}/access', headers=headers)
    assert response.status_code == 200
    assert 'no-store' in response.headers['cache-control']
    assert set(response.json()) == {'ssid','qr_data_url'}
    svg = base64.b64decode(response.json()['qr_data_url'].split(',')[1])
    assert b'<svg' in svg and b'<path' in svg
    assert sessions.get(token).history == []
    settings.guest_wifi_network_ids = []
    assert client.post(f'/api/v1/guest/networks/{public.id}/access', headers=headers).status_code == 404


def test_wifi_qr_escapes_reserved_characters_and_security():
    credential = WifiCredential(site='s', external_id='a', ssid='A;B:C,D"E\\F', security='wpa2-personal', passphrase='test;only:secret')
    assert wifi_payload(credential) == 'WIFI:T:WPA;S:A\\;B\\:C\\,D\\"E\\\\F;P:test\\;only\\:secret;;'
    credential.security = 'wpa3-personal'
    assert wifi_payload(credential).startswith('WIFI:T:SAE;')
    credential.security = 'open'; credential.passphrase = None
    assert 'T:nopass;' in wifi_payload(credential)


def test_public_session_admission_is_limited_and_recovers_after_one_minute():
    clock = [0]
    store = GuestSessions(clock=lambda: clock[0])
    for _ in range(60):
        store.create()
    with pytest.raises(RateLimited):
        store.create()
    clock[0] = 60
    assert store.create()
    assert len(store.sessions) == 1


def test_guest_history_stays_bounded_even_with_large_provider_output():
    store = GuestSessions()
    token = store.create()
    settings = Settings(_env_file=None, chat_max_history_turns=2, chat_max_history_chars=50)
    provider = SimpleNamespace(complete=AsyncMock(return_value=ProviderCompletion(content='x' * 100)))
    asyncio.run(store.answer(token, 'Consulta', provider, settings))
    assert store.get(token).history == []

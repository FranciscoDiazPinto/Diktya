"""Recuperación por destinatario, separada del portal abierto y del LLM."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.main import app
from app.core.config import Settings, get_settings
from app.core.errors import AccessDenied
from app.chat.guest import sessions, GuestSessions
from app.networks.models import Network, NetworkRecipient
from app.networks.support_models import NetworkSupportConfig
from app.networks.recipients import normalize_contact, RecipientsWrite, replace_recipients


@pytest.fixture()
def recovery(client, db_session):
    sessions.clear()
    networks = [Network(name=f'Red {i}', site='test', external_id=f'n{i}', event_name='test', ssid=f'SSID-{i}', vlan_tag=i) for i in (1, 2, 3)]
    db_session.add_all(networks); db_session.flush()
    db_session.add_all([NetworkSupportConfig(network_id=n.id, credential_ref=f'n{i}') for i, n in enumerate(networks, 1)])
    db_session.add_all([
        NetworkRecipient(network_id=networks[0].id, email='client@example.com', phone='+56912345678'),
        NetworkRecipient(network_id=networks[1].id, email='other@example.com'),
    ])
    db_session.commit()
    credentials = {f'n{i}': {'site':'test', 'external_id':f'n{i}', 'ssid':f'SSID-{i}', 'security':'wpa2-personal', 'passphrase':'test-only-network-password'} for i in (1,2,3)}
    # Incluye una red de cliente a propósito: no debe publicarse sin identificar.
    settings = Settings(_env_file=None, guest_wifi_network_ids=[networks[0].id], wifi_access_credentials_json=json.dumps(credentials))
    app.dependency_overrides[get_settings] = lambda: settings
    token = client.post('/api/v1/guest/sessions').json()['token']
    headers = {'X-Guest-Session':token}
    yield networks, headers, token
    sessions.clear()


def test_private_network_never_released_without_matching_contact(client, recovery):
    networks, headers, _ = recovery
    assert client.get('/api/v1/guest/networks', headers=headers).json() == []
    assert client.post(f'/api/v1/guest/networks/{networks[0].id}/access', headers=headers).status_code == 404
    response = client.post('/api/v1/guest/identify', headers=headers, json={'contact':'unknown@example.com'})
    assert response.status_code == 403
    assert 'SSID' not in response.text and 'unknown@example.com' not in response.text
    assert client.post(f'/api/v1/guest/networks/{networks[0].id}/access', headers=headers).status_code == 404


@pytest.mark.parametrize('contact', [' CLIENT@EXAMPLE.COM ', '+56 (9) 1234-5678', '0056912345678'])
def test_email_or_phone_reveals_only_matching_network(client, recovery, contact):
    networks, headers, token = recovery
    response = client.post('/api/v1/guest/identify', headers=headers, json={'contact':contact})
    assert response.status_code == 200
    assert [n['id'] for n in response.json()] == [networks[0].id]
    assert 'no-store' in response.headers['cache-control']
    access = client.post(f'/api/v1/guest/networks/{networks[0].id}/access', headers=headers)
    assert access.status_code == 200 and access.json()['qr_data_url'].startswith('data:image/svg+xml;base64,')
    assert client.post(f'/api/v1/guest/networks/{networks[1].id}/access', headers=headers).status_code == 404
    assert sessions.get(token).history == []


def test_failed_reidentification_revokes_previous_match(client, recovery):
    networks, headers, token = recovery
    client.post('/api/v1/guest/identify', headers=headers, json={'contact':'client@example.com'})
    assert client.post('/api/v1/guest/identify', headers=headers, json={'contact':'no-match@example.com'}).status_code == 403
    assert sessions.get(token).contact is None
    assert client.post(f'/api/v1/guest/networks/{networks[0].id}/access', headers=headers).status_code == 404


def test_qr_rechecks_contact_assignment_and_new_sessions_do_not_inherit_it(client, recovery, db_session):
    networks, headers, token = recovery
    client.post('/api/v1/guest/identify', headers=headers, json={'contact':'client@example.com'})
    row = db_session.query(NetworkRecipient).filter_by(email='client@example.com').one()
    db_session.delete(row); db_session.commit()
    assert client.post(f'/api/v1/guest/networks/{networks[0].id}/access', headers=headers).status_code == 404
    old_session = sessions.get(token)
    client.delete('/api/v1/guest/session', headers=headers)
    assert old_session.contact is None
    new_token = client.post('/api/v1/guest/sessions').json()['token']
    assert sessions.get(new_token).contact is None


def test_recovery_attempts_are_limited(client, recovery):
    _, headers, _ = recovery
    for _ in range(5):
        assert client.post('/api/v1/guest/identify', headers=headers, json={'contact':'missing@example.com'}).status_code == 403
    assert client.post('/api/v1/guest/identify', headers=headers, json={'contact':'client@example.com'}).status_code == 429


def test_contacts_are_never_forwarded_to_provider_or_saved_in_guest_chat():
    store = GuestSessions()
    token = store.create()
    provider = SimpleNamespace(complete=AsyncMock())
    for message in ['Mi correo es client@example.com', 'Mi telefono es +56 9 1234 5678']:
        answer = asyncio.run(store.answer(token, message, provider, Settings(_env_file=None)))
        assert 'formulario' in answer
    provider.complete.assert_not_awaited()
    assert store.get(token).history == []


def test_admin_registers_recipients_without_creating_accounts(client, db_session, admin_user, viewer_user, login):
    network = Network(name='Privada', site='test', external_id='p', event_name='test', ssid='Private', vlan_tag=20)
    db_session.add(network); db_session.commit()
    path = f'/admin/networks/{network.id}/recipients'
    payload = {'recipients':[{'email':'CLIENT@EXAMPLE.COM', 'phone':'+56 9 1234 5678'}]}
    assert client.put(path, json=payload).status_code == 401
    with pytest.raises(AccessDenied):
        replace_recipients(db_session, viewer_user, network.id, RecipientsWrite(**payload))
    _, headers = login('admin@example.com', 'admin-password')
    result = client.put(path, headers=headers, json=payload)
    assert result.status_code == 200
    assert result.json() == [{'email':'client@example.com', 'phone':'+56912345678'}]
    assert client.get(path, headers=headers).json() == result.json()
    assert client.put(path, headers=headers, json={'recipients':[{}]}).status_code == 422
    assert client.put(path, headers=headers, json={'recipients':[]}).json() == []

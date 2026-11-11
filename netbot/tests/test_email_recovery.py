"""Posesión por correo, enlaces de un uso y exclusión de redes internas."""
import json
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.main import app
from app.core.config import Settings, get_settings
from app.chat.guest import sessions
from app.chat.guest_router import get_recovery_mailer
from app.networks.models import Network, NetworkRecipient
from app.networks.support_models import NetworkSupportConfig, WifiEmailRecovery
from app.networks.email_recovery import now_utc

BASE = '/api/v1/guest'
ORIGIN = 'https://demo.example.com'


@pytest.fixture()
def recovery_email(client, db_session):
    sessions.clear()
    sent = []
    n = Network(name='Expositores',ssid='ExpoDemo',site='test',external_id='expo',event_name='demo',vlan_tag=20)
    db_session.add(n); db_session.flush()
    cfg = NetworkSupportConfig(network_id=n.id,credential_ref='demo-expo',guest_recovery_purpose='expositor')
    recipient = NetworkRecipient(network_id=n.id,email='expositor@example.com')
    db_session.add_all([cfg, recipient]); db_session.commit()
    settings = Settings(_env_file=None,guest_email_recovery_enabled=True,
                        guest_email_recovery_public_url=ORIGIN,
                        wifi_access_credentials_json=json.dumps({'demo-expo':{'site':'test','external_id':'expo',
                        'ssid':'ExpoDemo','security':'wpa2-personal','passphrase':'synthetic-test-password'}}))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_recovery_mailer] = lambda: lambda *args: sent.append(args)
    session = client.post(BASE+'/sessions').json()['token']
    headers = {'X-Guest-Session':session}
    yield n,cfg,recipient,settings,sent,headers
    sessions.clear()


def send(client, fixture, email='expositor@example.com'):
    return client.post(BASE+'/recovery/email',json={'email':email},headers=fixture[-1])


def raw_token(fixture):
    return fixture[4][-1][2].split('#')[-1]


def approve(client, token, origin=ORIGIN):
    return client.post(BASE+'/recovery/approve',json={'token':token},headers={'Origin':origin})


def test_generic_email_request_does_not_enumerate_contacts(client, recovery_email):
    known = send(client,recovery_email)
    unknown = send(client,recovery_email,'missing@example.com')
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(recovery_email[4]) == 1
    assert 'token' not in known.json()
    assert client.post(BASE+'/recovery/email',json={'email':'expositor@example.com'}).status_code == 422
    assert send(client,recovery_email,'+56912345678').status_code == 422


def test_explicit_confirmation_returns_qr_once_and_get_does_not_consume(client, db_session, recovery_email):
    assert send(client,recovery_email).status_code == 202
    token = raw_token(recovery_email)
    row = db_session.scalar(select(WifiEmailRecovery))
    assert token != row.token_hash and token not in row.token_hash
    page = client.get(BASE+'/recovery/approve')
    assert page.status_code == 200 and page.headers['cache-control'].startswith('no-store')
    assert row.consumed_at is None
    assert "style-src 'self'" in page.headers['content-security-policy']
    styles = client.get(BASE+'/recovery/approval.css')
    assert styles.status_code == 200
    assert styles.headers['content-type'].startswith('text/css')
    assert 'no-store' in styles.headers['cache-control']
    assert approve(client,token, 'https://foreign.example.com').status_code == 403
    result = approve(client,token)
    assert result.status_code == 200
    assert result.json()[0]['ssid'] == 'ExpoDemo'
    assert result.json()[0]['qr_data_url'].startswith('data:image/')
    assert approve(client,token).status_code == 404
    db_session.expire_all()
    assert row.email == '' and row.network_ids == []


@pytest.mark.parametrize('name,purpose', [
    ('Administración','expositor'),('Marketing','expositor'),('Servicios','expositor'),
    ('Expositores','administracion'),('Expositores','marketing'),('Expositores','servicios'),
    ('Expositores','disabled'),
])
def test_internal_and_unclassified_networks_never_receive_links(client,db_session,recovery_email,name,purpose):
    network,cfg,*_ = recovery_email
    network.name = name; cfg.guest_recovery_purpose = purpose; db_session.commit()
    assert send(client,recovery_email).status_code == 202
    assert recovery_email[4] == []


@pytest.mark.parametrize('change',['classification','recipient','expired'])
def test_outstanding_links_revalidate_policy_and_expiration(client,db_session,recovery_email,change):
    send(client,recovery_email); token = raw_token(recovery_email)
    if change == 'classification': recovery_email[1].guest_recovery_purpose = 'servicios'
    elif change == 'recipient': db_session.delete(recovery_email[2])
    else: db_session.scalar(select(WifiEmailRecovery)).expires_at = now_utc()-timedelta(seconds=1)
    db_session.commit()
    assert approve(client,token).status_code == 404


def test_missing_mailer_fails_closed_without_revealing_contact(client,recovery_email):
    app.dependency_overrides[get_recovery_mailer] = lambda: None
    assert send(client,recovery_email).status_code == 503
    assert send(client,recovery_email,'missing@example.com').status_code == 503


def test_internal_network_excluded_even_if_published_as_open_portal(client,db_session,recovery_email):
    network,cfg,_,settings,_,headers = recovery_email
    cfg.guest_recovery_purpose = 'marketing'
    settings.guest_wifi_network_ids = [network.id]
    settings.wifi_access_credentials_json = json.dumps({'demo-expo':{'site':'test','external_id':'expo','ssid':'ExpoDemo','security':'open'}})
    db_session.commit()
    assert client.get(BASE+'/networks',headers=headers).json() == []
    assert client.post(BASE+f'/networks/{network.id}/access',headers=headers).status_code == 404


def test_only_admin_can_enable_expositor_recovery(client,db_session,recovery_email,admin_user,viewer_user,login):
    network = recovery_email[0]
    url = f'/admin/networks/{network.id}/recovery-policy'
    _,viewer = login(viewer_user.email,'viewer-password')
    assert client.patch(url,headers=viewer,json={'purpose':'expositor'}).status_code == 403
    _,admin = login(admin_user.email,'admin-password')
    assert client.patch(url,headers=admin,json={'purpose':'expositor'}).status_code == 200
    network.name = 'Administración'; db_session.commit()
    assert client.patch(url,headers=admin,json={'purpose':'expositor'}).status_code == 400


def test_same_link_cannot_be_consumed_concurrently(tmp_path,recovery_email):
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.core.errors import NotFound
    from app.networks.email_recovery import approve_and_reveal
    engine = create_engine(f'sqlite:///{tmp_path / "concurrent.db"}')
    Base.metadata.create_all(engine)
    raw = 'synthetic-token-for-test-' + 'a'*20
    with Session(engine) as db:
        db.add(Network(id=1,name='Expositores',ssid='ExpoDemo',site='test',external_id='expo',event_name='demo',vlan_tag=20)); db.flush()
        db.add_all([NetworkSupportConfig(network_id=1,credential_ref='demo-expo',guest_recovery_purpose='expositor'),
                    NetworkRecipient(network_id=1,email='expositor@example.com'),
                    WifiEmailRecovery(id='synthetic',token_hash=hashlib.sha256(raw.encode()).hexdigest(),email='expositor@example.com',network_ids=[1],expires_at=now_utc()+timedelta(minutes=5))])
        db.commit()
    def attempt(_):
        with Session(engine) as db:
            try: return bool(approve_and_reveal(db,recovery_email[3],raw))
            except NotFound: return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,range(2))) == [False,True]
    engine.dispose()

"""Workspace authorization, replay resistance and real offline signature checks."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import jwt
import pytest
from pydantic import ValidationError, SecretStr
from sqlalchemy import select, func

from app.auth import google_login
from app.auth.models import User, Role, GoogleIdentity, GoogleLoginChallenge, RefreshToken, AuthAuditEvent
from app.auth.schemas import GoogleLoginRequest
from app.core.config import settings, Settings
from app.core.errors import ServiceUnavailable, Unauthenticated

CLIENT_ID = '123-test.apps.googleusercontent.com'


@pytest.fixture
def google_enabled(monkeypatch):
    monkeypatch.setattr(settings, 'google_login_enabled', True)
    monkeypatch.setattr(settings, 'google_client_id', CLIENT_ID)
    monkeypatch.setattr(settings, 'google_allowed_domains', ['example.com'])


def claims_for(challenge_nonce, **overrides):
    return {'iss': 'https://accounts.google.com', 'aud': CLIENT_ID, 'sub': 'google-stable-user-1',
            'email': 'admin@example.com', 'email_verified': True, 'hd': 'example.com', 'nonce': challenge_nonce,
            **overrides}


def prepare(client, monkeypatch, **overrides):
    challenge = client.post('/auth/google/challenge')
    assert challenge.status_code == 200
    challenge = challenge.json()
    claims = claims_for(challenge['nonce'], **overrides)
    monkeypatch.setattr(google_login, 'verify_google_credential', lambda credential: claims)
    return {'credential': 'synthetic-id-token', 'challenge_token': challenge['challenge_token']}, claims


def test_disabled_is_public_but_does_not_issue_challenges_or_sessions(client):
    assert client.get('/auth/google/config').json() == {'enabled': False, 'client_id': None}
    assert client.post('/auth/google/challenge').status_code == 503
    assert client.post('/auth/google', json={'credential': 'x', 'challenge_token': 'x'*43}).status_code == 503


def test_preapproved_login_binds_subject_and_uses_normal_netbot_sessions(client, db_session, admin_user, monkeypatch, google_enabled):
    data, _ = prepare(client, monkeypatch)
    result = client.post('/auth/google', json=data)
    assert result.status_code == 200
    assert 'no-store' in result.headers['cache-control']
    tokens = result.json()
    assert tokens['access_token'] != data['credential']
    headers = {'Authorization': 'Bearer '+tokens['access_token']}
    assert client.get('/auth/me', headers=headers).json()['id'] == admin_user.id
    assert db_session.get(GoogleIdentity, admin_user.id).subject == 'google-stable-user-1'
    assert client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(GoogleLoginChallenge)) == 0
    audit = json.dumps([e.details for e in db_session.scalars(select(AuthAuditEvent))])
    assert data['credential'] not in audit and data['challenge_token'] not in audit


@pytest.mark.parametrize('overrides', [
    {'hd': None}, {'hd': 'other.example.com'}, {'email': 'admin@elsewhere.example'},
    {'email_verified': False}, {'email_verified': 'true'}, {'aud': 'other-client'},
    {'iss': 'https://attacker.example'}, {'azp': 'other-client'}, {'nonce': 'wrong'},
    {'sub': ''}, {'sub': 'x'*256}, {'email': 'not-an-email'},
])
def test_rejects_identity_claim_mismatches(client, db_session, admin_user, monkeypatch, google_enabled, overrides):
    data, _ = prepare(client, monkeypatch, **overrides)
    result = client.post('/auth/google', json=data)
    assert result.status_code == 401
    assert db_session.get(GoogleIdentity, admin_user.id) is None
    assert db_session.scalar(select(func.count()).select_from(RefreshToken)) == 0


@pytest.mark.parametrize('account', ['unknown', 'inactive', 'customer', 'legacy_mixed_customer'])
def test_domain_membership_does_not_provision_or_authorize_accounts(client, db_session, admin_user, monkeypatch, google_enabled, account):
    if account == 'inactive': admin_user.is_active = False
    if account == 'customer': admin_user.roles = [db_session.scalar(select(Role).where(Role.name == 'cliente'))]
    if account == 'legacy_mixed_customer':
        admin_user.roles.append(db_session.scalar(select(Role).where(Role.name == 'cliente')))
    db_session.commit()
    data, _ = prepare(client, monkeypatch, **({'email': 'missing@example.com'} if account == 'unknown' else {}))
    assert client.post('/auth/google', json=data).status_code == 401
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


def test_google_roles_cannot_escalate_local_permissions(client, db_session, viewer_user, monkeypatch, google_enabled):
    data, _ = prepare(client, monkeypatch, email=viewer_user.email, roles=['admin'])
    result = client.post('/auth/google', json=data)
    assert result.status_code == 200
    person = client.get('/auth/me', headers={'Authorization': 'Bearer '+result.json()['access_token']}).json()
    assert person['roles'] == ['visor']
    assert 'users:manage' not in person['permissions']


def test_replay_and_expired_challenges_never_create_another_session(client, db_session, admin_user, monkeypatch, google_enabled):
    data, _ = prepare(client, monkeypatch)
    assert client.post('/auth/google', json=data).status_code == 200
    sessions = db_session.scalar(select(func.count()).select_from(RefreshToken))
    assert client.post('/auth/google', json=data).status_code == 401
    assert db_session.scalar(select(func.count()).select_from(RefreshToken)) == sessions
    expired, _ = prepare(client, monkeypatch)
    row = db_session.get(GoogleLoginChallenge, hashlib.sha256(expired['challenge_token'].encode()).hexdigest())
    row.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    db_session.commit()
    assert client.post('/auth/google', json=expired).status_code == 401


def test_failed_verification_also_consumes_challenge(client, db_session, admin_user, monkeypatch, google_enabled):
    data, _ = prepare(client, monkeypatch)
    def invalid(_): raise Unauthenticated('invalid')
    monkeypatch.setattr(google_login, 'verify_google_credential', invalid)
    assert client.post('/auth/google', json=data).status_code == 401
    assert db_session.get(GoogleLoginChallenge, hashlib.sha256(data['challenge_token'].encode()).hexdigest()) is None


def test_bound_email_cannot_switch_google_subject(client, db_session, admin_user, monkeypatch, google_enabled):
    data, _ = prepare(client, monkeypatch)
    assert client.post('/auth/google', json=data).status_code == 200
    different, _ = prepare(client, monkeypatch, sub='recycled-email-new-google-user')
    assert client.post('/auth/google', json=different).status_code == 401
    assert db_session.get(GoogleIdentity, admin_user.id).subject == 'google-stable-user-1'
    same, _ = prepare(client, monkeypatch)
    assert client.post('/auth/google', json=same).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(GoogleIdentity)) == 1


def test_rechecks_account_after_provider_wait(client, db_session, admin_user, monkeypatch, google_enabled):
    data, claims = prepare(client, monkeypatch)
    def verify(_):
        admin_user.is_active = False
        db_session.commit()
        return claims
    monkeypatch.setattr(google_login, 'verify_google_credential', verify)
    assert client.post('/auth/google', json=data).status_code == 401


def test_service_has_the_same_checks_when_called_without_http(db_session, admin_user, monkeypatch, google_enabled):
    challenge = google_login.challenge(db_session)
    monkeypatch.setattr(google_login, 'verify_google_credential', lambda _: claims_for(challenge.nonce, hd='evil.example'))
    with pytest.raises(Unauthenticated):
        google_login.login(GoogleLoginRequest(credential='synthetic', challenge_token=challenge.challenge_token), db_session)


def test_challenge_is_bounded_unpredictable_and_only_hashes_are_stored(client, db_session, google_enabled):
    a = client.post('/auth/google/challenge'); b = client.post('/auth/google/challenge')
    assert a.status_code == b.status_code == 200
    assert a.json()['nonce'] != b.json()['nonce']
    assert a.json()['challenge_token'] != b.json()['challenge_token']
    row = db_session.get(GoogleLoginChallenge, hashlib.sha256(a.json()['challenge_token'].encode()).hexdigest())
    assert row.nonce_hash == hashlib.sha256(a.json()['nonce'].encode()).hexdigest()
    assert 'no-store' in a.headers['cache-control']
    for _ in range(8): assert client.post('/auth/google/challenge').status_code == 200
    assert client.post('/auth/google/challenge').status_code == 429


def test_unrecognized_fields_cannot_supply_identity_roles_or_domains(client, google_enabled):
    result = client.post('/auth/google', json={'credential': 'x', 'challenge_token': 'x'*43, 'roles': ['admin']})
    assert result.status_code == 422


def test_config_requires_exact_domains_and_client_id():
    options = {'_env_file': None, 'environment': 'test', 'google_login_enabled': True, 'google_client_id': CLIENT_ID}
    with pytest.raises(ValidationError): Settings(**options)
    for domain in ['*.example.com', '@example.com', 'https://example.com', 'example.com/path']:
        with pytest.raises(ValidationError): Settings(**options, google_allowed_domains=[domain])
    assert Settings(**options, google_allowed_domains=[' Example.COM ']).google_allowed_domains == ['example.com']


@pytest.fixture
def signed_credential(monkeypatch, google_enabled):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Offline Google test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .sign(key, hashes.SHA256()))
    payload = json.dumps({'test-key': cert.public_bytes(serialization.Encoding.PEM).decode()}).encode()
    monkeypatch.setattr(google_login._GoogleRequest, '__call__', lambda self,*a,**kw: google_login._GoogleResponse(200,payload,{}))
    def sign(**overrides):
        claims = claims_for('nonce', iat=int(now.timestamp()), exp=int(now.timestamp())+60)
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test-key'})
    return sign


def test_official_verifier_checks_a_real_offline_rsa_signature(signed_credential):
    assert google_login.verify_google_credential(signed_credential())['sub'] == 'google-stable-user-1'


@pytest.mark.parametrize('kind', ['audience', 'issuer', 'expired', 'tampered'])
def test_official_verifier_rejects_invalid_signed_tokens(signed_credential, kind):
    if kind == 'audience': token = signed_credential(aud='other-client')
    elif kind == 'issuer': token = signed_credential(iss='https://evil.example')
    elif kind == 'expired': token = signed_credential(exp=int(datetime.now(timezone.utc).timestamp())-1)
    else:
        token = signed_credential(); a,b,c=token.split('.'); token=a+'.'+b+'.'+('a' if c[0]!='a' else 'b')+c[1:]
    with pytest.raises(Unauthenticated): google_login.verify_google_credential(token)


def test_concurrent_consumers_can_create_only_one_session(tmp_path, monkeypatch, google_enabled):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    engine = create_engine(f'sqlite:///{tmp_path / "google-race.db"}')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        role = Role(name='admin', description='Test')
        db.add(User(email='admin@example.com', hashed_password='unused-synthetic', roles=[role])); db.commit()
        challenge = google_login.challenge(db)
    monkeypatch.setattr(google_login, 'verify_google_credential', lambda _: claims_for(challenge.nonce))
    data = GoogleLoginRequest(credential='synthetic', challenge_token=challenge.challenge_token)
    barrier = Barrier(2)
    def consume():
        with sessions() as db:
            barrier.wait(timeout=5)
            try: google_login.login(data, db); return 'success'
            except Unauthenticated: return 'denied'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: consume(), range(2)))
        assert sorted(outcomes) == ['denied', 'success']
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(RefreshToken)) == 1
    finally:
        engine.dispose()

"""Google sign-in for pre-provisioned Workspace staff. No HTTP framework here."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

import httpx
from google.auth.exceptions import GoogleAuthError, TransportError
from google.oauth2 import id_token
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Unauthenticated, ServiceUnavailable
from .audit import bind_request, record_event
from .models import GoogleIdentity, GoogleLoginChallenge, User
from .schemas import GoogleChallengeRead, GoogleLoginConfig, GoogleLoginRequest, TokenResponse
from . import service

CHALLENGE_SECONDS = 300
STAFF_ROLES = frozenset({'admin', 'tecnico', 'operador', 'visor'})
_CERTS_URL = 'https://www.googleapis.com/oauth2/v1/certs'
_DENIED = 'No fue posible autorizar esta cuenta de Google.'


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def configuration() -> GoogleLoginConfig:
    return GoogleLoginConfig(enabled=settings.google_login_enabled,
                             client_id=settings.google_client_id if settings.google_login_enabled else None)


def _require_enabled() -> None:
    if not settings.google_login_enabled or not settings.google_client_id or not settings.google_allowed_domains:
        raise ServiceUnavailable('El acceso con Google no está habilitado.')


def challenge(db: Session) -> GoogleChallengeRead:
    _require_enabled()
    now = datetime.now(timezone.utc)
    token, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.execute(delete(GoogleLoginChallenge).where(GoogleLoginChallenge.expires_at <= now),
               execution_options={'synchronize_session': False})
    db.add(GoogleLoginChallenge(token_hash=_digest(token), nonce_hash=_digest(nonce),
                                expires_at=now + timedelta(seconds=CHALLENGE_SECONDS)))
    db.commit()
    return GoogleChallengeRead(challenge_token=token, nonce=nonce, expires_in=CHALLENGE_SECONDS)


@dataclass
class _GoogleResponse:
    status: int
    data: bytes
    headers: dict


class _GoogleRequest:
    """Official google-auth transport contract, using the existing HTTP client."""
    def __call__(self, url, method='GET', body=None, headers=None, timeout=None, **kwargs):
        if url != _CERTS_URL or method != 'GET':
            raise TransportError('Unexpected Google verification resource')
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', _CERTS_URL, headers=headers) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 1_048_576:
                            raise TransportError('Invalid verification response')
                        chunks.append(chunk)
                    return _GoogleResponse(response.status_code, b''.join(chunks), dict(response.headers))
        except httpx.HTTPError as exc:
            raise TransportError('Google verification unavailable') from exc


def verify_google_credential(credential: str) -> dict:
    try:
        # The official library validates signature, issuer, audience and expiry.
        return id_token.verify_oauth2_token(credential, _GoogleRequest(), audience=settings.google_client_id)
    except TransportError as exc:
        raise ServiceUnavailable('Google no está disponible. Inténtalo nuevamente.') from exc
    except (GoogleAuthError, ValueError, TypeError, KeyError) as exc:
        raise Unauthenticated(_DENIED) from exc


def _deny(db: Session, reason: str) -> None:
    record_event(db, 'auth.google.failed', outcome='denied', details={'reason': reason})
    db.commit()
    raise Unauthenticated(_DENIED)


def login(data: GoogleLoginRequest, db: Session) -> TokenResponse:
    _require_enabled()
    bind_request(db)
    now = datetime.now(timezone.utc)
    # Atomic consume, before the external wait. No transaction/administrative lock
    # is held while fetching Google signing keys. Failed attempts need a new nonce.
    token_hash = _digest(data.challenge_token.get_secret_value())
    nonce_hash = db.scalar(
        delete(GoogleLoginChallenge).where(
            GoogleLoginChallenge.token_hash == token_hash,
            GoogleLoginChallenge.expires_at > now,
        ).returning(GoogleLoginChallenge.nonce_hash),
        execution_options={'synchronize_session': 'fetch'},
    )
    if nonce_hash is None:
        _deny(db, 'challenge')
    db.commit()
    try:
        claims = verify_google_credential(data.credential.get_secret_value())
    except Unauthenticated:
        _deny(db, 'credential')
    # Recheck the server's policy after waiting on the provider.
    _require_enabled()
    domain = claims.get('hd')
    subject = claims.get('sub')
    nonce = claims.get('nonce')
    email = claims.get('email')
    if (claims.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}
        or claims.get('aud') != settings.google_client_id
        or claims.get('azp', settings.google_client_id) != settings.google_client_id
        or claims.get('email_verified') is not True
        or not isinstance(domain, str) or domain.lower() not in settings.google_allowed_domains
        or not isinstance(subject, str) or not 1 <= len(subject) <= 255
        or not isinstance(nonce, str) or not hmac.compare_digest(_digest(nonce), nonce_hash)
        or not isinstance(email, str) or '@' not in email
        or email.rsplit('@', 1)[1].lower() != domain.lower()):
        _deny(db, 'identity')
    # Serialize with user administration and reread active status and roles after
    # verification. The first validated Workspace login binds only an existing user.
    service._lock_administration(db)
    identity = db.scalar(select(GoogleIdentity).where(GoogleIdentity.subject == subject))
    user = db.get(User, identity.user_id) if identity else db.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active or not STAFF_ROLES.intersection(role.name for role in user.roles):
        _deny(db, 'account')
    binding = db.get(GoogleIdentity, user.id)
    if (binding and binding.subject != subject) or (identity and user.email.lower() != email.lower()):
        _deny(db, 'binding')
    if binding is None:
        db.add(GoogleIdentity(user_id=user.id, subject=subject))
        record_event(db, 'auth.google.linked', actor_id=user.id)
    tokens = service._tokens(user, db)
    record_event(db, 'auth.google.succeeded', actor_id=user.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _deny(db, 'binding')
    return tokens

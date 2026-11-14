import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.errors import ServiceUnavailable

password_hash = PasswordHash.recommended()
# Argon2 usa decenas de MiB por verificación: acotar la concurrencia acota memoria y CPU.
_ARGON2_SLOTS = threading.BoundedSemaphore(4)


def _argon2_slot():
    if not _ARGON2_SLOTS.acquire(timeout=10):
        raise ServiceUnavailable("La autenticación está ocupada. Inténtalo en unos segundos.")


def hash_password(password: str) -> str:
    _argon2_slot()
    try:
        return password_hash.hash(password)
    finally:
        _ARGON2_SLOTS.release()


def verify_password(password: str, hashed: str) -> bool:
    _argon2_slot()
    try:
        return password_hash.verify(password, hashed)
    finally:
        _ARGON2_SLOTS.release()


def create_access_token(user_id: int, roles: list[str], *, session_id: str | None = None) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "roles": roles, "type": "access", "sid": session_id, "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return raw, hashlib.sha256(raw.encode()).hexdigest(), expires


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"require": ["exp", "sub", "type", "sid"]})
    if payload.get("type") != "access" or not payload.get("sub") or not isinstance(payload.get("sid"), str) or len(payload["sid"]) != 64:
        raise jwt.InvalidTokenError("Invalid access token")
    return payload

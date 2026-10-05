import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: int, roles: list[str]) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "roles": roles, "type": "access", "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return raw, hashlib.sha256(raw.encode()).hexdigest(), expires


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access" or not payload.get("sub"):
        raise jwt.InvalidTokenError("Invalid access token")
    return payload

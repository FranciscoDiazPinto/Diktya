from __future__ import annotations
from typing import Optional

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db

from .models import User, RefreshToken
from .audit import bind_request, queue_denial
from .access import require_user_permission
from sqlalchemy import select
from datetime import datetime, timezone
from .permissions import Permission
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    bind_request(db)
    if not credentials:
        queue_denial(reason="missing_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (ValueError, jwt.PyJWTError):
        queue_denial(reason="invalid_or_expired_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        queue_denial(reason="inactive_or_unknown_user")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or unknown user")
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == payload["sid"], RefreshToken.user_id == user.id))
    now = datetime.now(timezone.utc)
    expires = token.expires_at.replace(tzinfo=timezone.utc) if token and token.expires_at.tzinfo is None else (token.expires_at if token else None)
    if token is None or token.revoked_at is not None or expires <= now:
        queue_denial(reason="revoked_or_expired_session")
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    bind_request(db, user.id)
    return user


def require_permission(permission: str) -> Callable:
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        try:
            required = Permission(permission)
        except ValueError:
            queue_denial(user.id, permission)
            raise HTTPException(status_code=403, detail="Insufficient permissions") from None
        require_user_permission(db, user, required)
        return user
    dependency.required_permission = Permission(permission)
    return dependency

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db

from .dependencies import get_current_user, require_permission
from .models import RefreshToken, Role, User
from .schemas import LoginRequest, RefreshRequest, RoleCreate, RoleRead, TokenResponse, UserCreate, UserRead, UserUpdate
from .security import create_access_token, create_refresh_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/admin", tags=["administration"])


def _user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active,
        roles=[role.name for role in user.roles], created_at=user.created_at,
    )


def _tokens(user: User, db: Session) -> TokenResponse:
    raw, token_hash, expires = create_refresh_token()
    db.add(RefreshToken(token_hash=token_hash, user_id=user.id, expires_at=expires))
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, [r.name for r in user.roles]), refresh_token=raw)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not user.is_active or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _tokens(user, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(data.refresh_token.encode()).hexdigest()))
    now = datetime.now(timezone.utc)
    expires_at = token.expires_at.replace(tzinfo=timezone.utc) if token and token.expires_at.tzinfo is None else (token.expires_at if token else None)
    if not token or token.revoked_at or expires_at <= now or not token.user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    token.revoked_at = now
    return _tokens(token.user, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshRequest, db: Session = Depends(get_db)) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(data.refresh_token.encode()).hexdigest()))
    if token and not token.revoked_at:
        token.revoked_at = datetime.now(timezone.utc)
        db.commit()


@router.get("/me", response_model=UserRead)
def current_user(user: User = Depends(get_current_user)) -> UserRead:
    return _user_read(user)


@admin_router.get("/users", response_model=list[UserRead], dependencies=[Depends(require_permission("users:read"))])
def list_users(db: Session = Depends(get_db)) -> list[UserRead]:
    return [_user_read(user) for user in db.scalars(select(User).order_by(User.id)).all()]


@admin_router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("users:manage"))])
def create_user(data: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise HTTPException(status_code=409, detail="Email already registered")
    roles = db.scalars(select(Role).where(Role.name.in_(data.roles))).all()
    if len(roles) != len(set(data.roles)):
        raise HTTPException(status_code=400, detail="Unknown role")
    user = User(email=data.email.lower(), full_name=data.full_name, hashed_password=hash_password(data.password), roles=list(roles))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_read(user)


@admin_router.patch("/users/{user_id}", response_model=UserRead, dependencies=[Depends(require_permission("users:manage"))])
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)) -> UserRead:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.roles is not None:
        roles = db.scalars(select(Role).where(Role.name.in_(data.roles))).all()
        if len(roles) != len(set(data.roles)):
            raise HTTPException(status_code=400, detail="Unknown role")
        user.roles = list(roles)
    db.commit()
    db.refresh(user)
    return _user_read(user)


@admin_router.get("/roles", response_model=list[RoleRead], dependencies=[Depends(require_permission("roles:manage"))])
def list_roles(db: Session = Depends(get_db)) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.name)).all())


@admin_router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("roles:manage"))])
def create_role(data: RoleCreate, db: Session = Depends(get_db)) -> Role:
    if db.scalar(select(Role).where(Role.name == data.name)):
        raise HTTPException(status_code=409, detail="Role already exists")
    role = Role(name=data.name, description=data.description)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role

"""Casos de uso de autenticación y administración de usuarios."""
import hashlib
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.errors import Unauthenticated, NotFound, Conflict, InvalidInput
from .models import RefreshToken, Role, User
from .roles import effective_permissions
from .access import require_user_permission
from .permissions import Permission
from .schemas import LoginRequest, RefreshRequest, RoleCreate, TokenResponse, UserCreate, UserRead, UserUpdate, RoleRead
from .security import create_access_token, create_refresh_token, hash_password, verify_password

def user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active,
        roles=[role.name for role in user.roles], permissions=sorted(p.value for p in effective_permissions(user)), created_at=user.created_at,
    )


def _tokens(user: User, db: Session) -> TokenResponse:
    raw, token_hash, expires = create_refresh_token()
    db.add(RefreshToken(token_hash=token_hash, user_id=user.id, expires_at=expires))
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, [r.name for r in user.roles]), refresh_token=raw)


def login(data: LoginRequest, db: Session) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not user.is_active or not verify_password(data.password, user.hashed_password):
        raise Unauthenticated("Invalid credentials")
    return _tokens(user, db)


def refresh(data: RefreshRequest, db: Session) -> TokenResponse:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(data.refresh_token.encode()).hexdigest()))
    now = datetime.now(timezone.utc)
    expires_at = token.expires_at.replace(tzinfo=timezone.utc) if token and token.expires_at.tzinfo is None else (token.expires_at if token else None)
    if not token or token.revoked_at or expires_at <= now or not token.user.is_active:
        raise Unauthenticated("Invalid refresh token")
    token.revoked_at = now
    return _tokens(token.user, db)


def logout(data: RefreshRequest, db: Session) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(data.refresh_token.encode()).hexdigest()))
    if token and not token.revoked_at:
        token.revoked_at = datetime.now(timezone.utc)
        db.commit()


def list_users(db: Session, actor: User) -> list[UserRead]:
    require_user_permission(db, actor, Permission.USERS_READ)
    return [user_read(user) for user in db.scalars(select(User).order_by(User.id)).all()]


def create_user(data: UserCreate, db: Session, actor: User) -> UserRead:
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise Conflict("Email already registered")
    roles = db.scalars(select(Role).where(Role.name.in_(data.roles))).all()
    if len(roles) != len(set(data.roles)):
        raise InvalidInput("Unknown role")
    user = User(email=data.email.lower(), full_name=data.full_name, hashed_password=hash_password(data.password), roles=list(roles))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_read(user)


def update_user(user_id: int, data: UserUpdate, db: Session, actor: User) -> UserRead:
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    user = db.get(User, user_id)
    if not user:
        raise NotFound("User not found")
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.roles is not None:
        roles = db.scalars(select(Role).where(Role.name.in_(data.roles))).all()
        if len(roles) != len(set(data.roles)):
            raise InvalidInput("Unknown role")
        user.roles = list(roles)
    db.commit()
    db.refresh(user)
    return user_read(user)


def list_roles(db: Session, actor: User) -> list[RoleRead]:
    require_user_permission(db, actor, Permission.ROLES_MANAGE)
    return [RoleRead.model_validate(role) for role in db.scalars(select(Role).order_by(Role.name)).all()]


def create_role(data: RoleCreate, db: Session, actor: User) -> RoleRead:
    require_user_permission(db, actor, Permission.ROLES_MANAGE)
    if db.scalar(select(Role).where(Role.name == data.name)):
        raise Conflict("Role already exists")
    role = Role(name=data.name, description=data.description)
    db.add(role)
    db.commit()
    db.refresh(role)
    return RoleRead.model_validate(role)




def user_exists(db: Session, user_id: int) -> bool:
    """Consulta interna mínima para casos de uso ya autorizados, sin exponer ORM."""
    return db.get(User, user_id) is not None


def execution_actor(db: Session, user_id: int) -> User:
    """Identidad vigente del solicitante de un trabajo ya persistido; no recibe roles externos."""
    actor = db.get(User, user_id)
    if actor is None:
        raise NotFound('Solicitante no encontrado.')
    return actor

"""Casos de uso de autenticación y administración de usuarios."""
import hashlib
import hmac
from datetime import datetime, timezone
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.errors import Unauthenticated, NotFound, Conflict, InvalidInput
from .models import RefreshToken, Role, User, AuthAuditEvent, user_roles
from .audit import record_event, bind_request
from app.core.config import settings

from .roles import effective_permissions
from .access import require_user_permission
from .permissions import Permission
from .schemas import LoginRequest, RefreshRequest, RoleCreate, TokenResponse, UserCreate, UserRead, UserUpdate, RoleRead
from .security import create_access_token, create_refresh_token, hash_password, verify_password

_DUMMY_PASSWORD_HASH = hash_password("netbot-login-timing-placeholder")

def user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active,
        roles=[role.name for role in user.roles], permissions=sorted(p.value for p in effective_permissions(user)), created_at=user.created_at,
    )


def _tokens(user: User, db: Session) -> TokenResponse:
    raw, token_hash, expires = create_refresh_token()
    db.add(RefreshToken(token_hash=token_hash, user_id=user.id, expires_at=expires))
    return TokenResponse(access_token=create_access_token(user.id, [r.name for r in user.roles], session_id=token_hash), refresh_token=raw)


def _fingerprint(email: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), email.lower().encode(), hashlib.sha256).hexdigest()


def login(data: LoginRequest, db: Session) -> TokenResponse:
    bind_request(db)
    _lock_administration(db)
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    valid_password = verify_password(data.password, user.hashed_password if user else _DUMMY_PASSWORD_HASH)
    if not user or not user.is_active or not valid_password:
        record_event(db, "auth.login.failed", outcome="failure", details={"subject_fingerprint": _fingerprint(data.email)})
        db.commit()
        raise Unauthenticated("Invalid credentials")
    tokens = _tokens(user, db)
    record_event(db, "auth.login.succeeded", actor_id=user.id)
    db.commit()
    return tokens


def refresh(data: RefreshRequest, db: Session) -> TokenResponse:
    bind_request(db)
    _lock_administration(db)
    token_hash = hashlib.sha256(data.refresh_token.encode()).hexdigest()
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    now = datetime.now(timezone.utc)
    expires_at = token.expires_at.replace(tzinfo=timezone.utc) if token and token.expires_at.tzinfo is None else (token.expires_at if token else None)
    if not token or token.revoked_at or expires_at <= now or not token.user.is_active:
        record_event(db, "auth.refresh.failed", outcome="failure")
        db.commit()
        raise Unauthenticated("Invalid refresh token")
    actor = token.user
    claimed = db.execute(update(RefreshToken).where(RefreshToken.id == token.id,
        RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now).values(revoked_at=now),
        execution_options={"synchronize_session": False})
    if claimed.rowcount != 1:
        db.rollback()
        record_event(db, "auth.refresh.failed", outcome="failure")
        db.commit()
        raise Unauthenticated("Invalid refresh token")
    fresh = _tokens(actor, db)
    record_event(db, "auth.refresh.succeeded", actor_id=actor.id)
    db.commit()
    return fresh


def logout(data: RefreshRequest, db: Session) -> None:
    bind_request(db)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(data.refresh_token.encode()).hexdigest()))
    if token and not token.revoked_at:
        token.revoked_at = datetime.now(timezone.utc)
        record_event(db, "auth.logout", actor_id=token.user_id)
        db.commit()


def _lock_administration(db: Session) -> None:
    # UPDATE serializa también SQLite (SELECT FOR UPDATE se ignora en SQLite).
    # El mismo registro se bloquea antes de cualquier cambio de identidad/roles.
    db.execute(update(Role).where(Role.name == "admin").values(description=Role.description))
    db.expire_all()


def _ensure_admin_remains(db: Session, user: User, active: bool, roles: list[Role]) -> None:
    if user.is_active and any(r.name == "admin" for r in user.roles) and (not active or not any(r.name == "admin" for r in roles)):
        others = db.scalar(select(func.count()).select_from(User).join(user_roles).join(Role).where(
            User.is_active.is_(True), Role.name == "admin", User.id != user.id))
        if not others:
            raise Conflict("Debe permanecer al menos un administrador activo.")


def _roles(db: Session, names: list[str]) -> list[Role]:
    roles = list(db.scalars(select(Role).where(Role.name.in_(names))))
    if len(roles) != len(set(names)):
        raise InvalidInput("Unknown role", field="roles")
    return roles


def _revoke_sessions(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


def list_users(db: Session, actor: User) -> list[UserRead]:
    require_user_permission(db, actor, Permission.USERS_READ)
    return [user_read(user) for user in db.scalars(select(User).order_by(User.id)).all()]


def create_user(data: UserCreate, db: Session, actor: User) -> UserRead:
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    _lock_administration(db)
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    return _create_user(data, db, actor.id)


def _create_user(data: UserCreate, db: Session, actor_id, *, source="http") -> UserRead:
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise Conflict("Email already registered", field="email")
    if "admin" not in data.roles and not db.scalar(select(User.id).join(user_roles).join(Role).where(User.is_active.is_(True), Role.name == "admin").limit(1)):
        raise Conflict("El primer usuario debe ser un administrador activo.")
    user = User(email=data.email.lower(), full_name=data.full_name,
                hashed_password=hash_password(data.password), roles=_roles(db, data.roles))
    db.add(user)
    try:
        db.flush()
        record_event(db, "user.created", actor_id=actor_id, target_id=user.id,
                     details={"roles": sorted(data.roles)}, source=source)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("Email already registered", field="email") from None
    return user_read(user)


def update_user(user_id: int, data: UserUpdate, db: Session, actor: User) -> UserRead:
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    _lock_administration(db)
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    return _update_user(user_id, data, db, actor.id)


def _update_user(user_id: int, data: UserUpdate, db: Session, actor_id, *, source="http") -> UserRead:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("User not found")
    roles = _roles(db, data.roles) if data.roles is not None else user.roles
    active = data.is_active if data.is_active is not None else user.is_active
    _ensure_admin_remains(db, user, active, roles)
    changed = []
    old_roles = sorted(r.name for r in user.roles)
    new_roles = sorted(r.name for r in roles)
    if data.full_name is not None and data.full_name != user.full_name:
        user.full_name = data.full_name
        changed.append("full_name")
    if active != user.is_active:
        user.is_active = active
        changed.append("is_active")
        record_event(db, "user.activated" if active else "user.deactivated", actor_id=actor_id, target_id=user.id, source=source)
    if old_roles != new_roles:
        user.roles = list(roles)
        changed.append("roles")
        record_event(db, "user.roles_changed", actor_id=actor_id, target_id=user.id,
                     details={"before": old_roles, "after": new_roles}, source=source)
    if data.password is not None:
        user.hashed_password = hash_password(data.password)
        changed.append("password")
        record_event(db, "user.password_changed", actor_id=actor_id, target_id=user.id, source=source)
    if changed:
        if set(changed) & {"is_active", "roles", "password"}:
            _revoke_sessions(db, user.id)
        record_event(db, "user.updated", actor_id=actor_id, target_id=user.id, details={"fields": changed}, source=source)
    db.commit()
    db.refresh(user)
    return user_read(user)


def provision_user(data: UserCreate, db: Session) -> UserRead:
    """Entrada administrativa local exclusiva de CLI; exige acceso al servidor."""
    _lock_administration(db)
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None:
        return _create_user(data, db, None, source="cli")
    return _update_user(user.id, UserUpdate(full_name=data.full_name, password=data.password,
                        roles=data.roles, is_active=True), db, None, source="cli")


def list_roles(db: Session, actor: User) -> list[RoleRead]:
    require_user_permission(db, actor, Permission.ROLES_MANAGE)
    return [RoleRead.model_validate(role) for role in db.scalars(select(Role).order_by(Role.name)).all()]


def create_role(data: RoleCreate, db: Session, actor: User) -> RoleRead:
    require_user_permission(db, actor, Permission.ROLES_MANAGE)
    _lock_administration(db)
    require_user_permission(db, actor, Permission.ROLES_MANAGE)
    if db.scalar(select(Role).where(Role.name == data.name)):
        raise Conflict("Role already exists")
    role = Role(name=data.name, description=data.description)
    db.add(role)
    record_event(db, "role.created", actor_id=actor.id, details={"name": data.name})
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


def list_audit(db: Session, actor: User, *, limit=50, offset=0) -> list[AuthAuditEvent]:
    require_user_permission(db, actor, Permission.AUTH_AUDIT_READ)
    return list(db.scalars(select(AuthAuditEvent).order_by(AuthAuditEvent.id.desc()).limit(limit).offset(offset)))

"""Casos de uso de autenticación y administración de usuarios."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select, update, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.errors import Unauthenticated, NotFound, Conflict, InvalidInput
from .models import RefreshToken, Role, User, AuthAuditEvent, user_roles
from .audit import current_peer, record_event, bind_request
from app.core.config import settings
from app.core.keys import derive_key

from .roles import effective_permissions
from .access import require_user_permission
from .permissions import Permission
from .schemas import LoginRequest, PasswordChange, RefreshRequest, RoleCreate, TokenResponse, UserCreate, UserRead, UserUpdate, RoleRead
from .security import create_access_token, create_refresh_token, hash_password, verify_password

_DUMMY_PASSWORD_HASH = hash_password("netbot-login-timing-placeholder")
_LOGIN_FAILURE_LIMIT = 5
_LOGIN_LOCK_DURATION = timedelta(minutes=15)
# Dos envíos casi simultáneos del mismo cliente no son un robo de sesión.
_REFRESH_REUSE_GRACE = timedelta(seconds=10)


def _login_now() -> datetime:
    return datetime.now(timezone.utc)

def user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active,
        roles=[role.name for role in user.roles], permissions=sorted(p.value for p in effective_permissions(user)), created_at=user.created_at,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _tokens(user: User, db: Session, started_at: datetime | None = None) -> TokenResponse:
    raw, token_hash, expires = create_refresh_token()
    started_at = started_at or datetime.now(timezone.utc)
    db.add(RefreshToken(token_hash=token_hash, user_id=user.id, expires_at=expires, session_started_at=started_at))
    return TokenResponse(access_token=create_access_token(user.id, [r.name for r in user.roles], session_id=token_hash), refresh_token=raw)


def _fingerprint(email: str) -> str:
    key = derive_key(settings.jwt_secret_key, 'audit-subject')
    return hmac.new(key.encode(), email.lower().encode(), hashlib.sha256).hexdigest()


def login(data: LoginRequest, db: Session) -> TokenResponse:
    bind_request(db)
    # El hash costoso no debe mantener el bloqueo global de administración.
    initial = db.scalar(select(User).where(User.email == data.email.lower()))
    initial_id = initial.id if initial else None
    password_hash = initial.hashed_password if initial else _DUMMY_PASSWORD_HASH
    db.rollback()  # liberar la transacción de lectura antes de Argon2
    valid_password = verify_password(data.password, password_hash)
    _lock_administration(db)
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    # Una modificación concurrente de cuenta/contraseña invalida el resultado previo.
    valid_password = bool(valid_password and user and user.id == initial_id
                          and user.hashed_password == password_hash)
    now = _login_now()
    locked_until = user.login_locked_until if user else None
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    locked = locked_until is not None and now < locked_until
    # Terceros pueden bloquear una cuenta conociendo solo su correo: el último origen
    # legítimo conserva el acceso con la clave correcta. Un fallo desde él retira la excepción.
    peer = current_peer()
    known_origin = bool(locked and peer and user and user.last_login_peer == peer)
    if known_origin and not valid_password:
        user.last_login_peer = None
    if user and locked_until is not None and not locked:
        user.failed_login_attempts = 0
        user.login_locked_until = None
    if not user or not user.is_active or not valid_password or (locked and not known_origin):
        if user and user.is_active and not locked:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= _LOGIN_FAILURE_LIMIT:
                user.login_locked_until = now + _LOGIN_LOCK_DURATION
                record_event(db, "auth.login.locked", target_id=user.id, outcome="denied")
        record_event(db, "auth.login.failed", outcome="failure", details={"subject_fingerprint": _fingerprint(data.email)})
        db.commit()
        raise Unauthenticated("Invalid credentials")
    user.failed_login_attempts = 0
    user.login_locked_until = None
    user.last_login_peer = peer or user.last_login_peer
    tokens = _tokens(user, db)
    record_event(db, "auth.login.succeeded", actor_id=user.id)
    db.commit()
    return tokens


def refresh(data: RefreshRequest, db: Session) -> TokenResponse:
    bind_request(db)
    _lock_administration(db)
    token_hash = hashlib.sha256(data.refresh_token.encode()).hexdigest()
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    now = _login_now()
    if token and token.revoked_at and now - _utc(token.revoked_at) > _REFRESH_REUSE_GRACE:
        # Un token ya usado reaparece: alguien tiene una copia. No se sabe cuál de las dos
        # partes es la legítima, así que se cierran todas las sesiones de la cuenta.
        _revoke_sessions(db, token.user_id)
        record_event(db, "auth.refresh.reuse_detected", target_id=token.user_id, outcome="denied")
        db.commit()
        raise Unauthenticated("Invalid refresh token")
    expires_at = _utc(token.expires_at) if token else None
    started_at = _utc(token.session_started_at or token.created_at) if token else None
    limit = timedelta(days=settings.session_absolute_days)
    if not token or token.revoked_at or expires_at <= now or now - started_at >= limit or not token.user.is_active:
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
    fresh = _tokens(actor, db, started_at)
    record_event(db, "auth.refresh.succeeded", actor_id=actor.id)
    db.commit()
    return fresh


def purge_expired_sessions(db: Session, now: datetime) -> int:
    """Conserva un día los tokens vencidos para distinguir reutilización de token inválido."""
    result = db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1)))
    return result.rowcount or 0


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
        user.failed_login_attempts = 0
        user.login_locked_until = None
        changed.append("password")
        record_event(db, "user.password_changed", actor_id=actor_id, target_id=user.id, source=source)
    if changed:
        if set(changed) & {"is_active", "roles", "password"}:
            _revoke_sessions(db, user.id)
        record_event(db, "user.updated", actor_id=actor_id, target_id=user.id, details={"fields": changed}, source=source)
    db.commit()
    db.refresh(user)
    return user_read(user)


def change_own_password(data: PasswordChange, db: Session, actor: User) -> None:
    """Cambio propio: exige la clave vigente y cierra todas las sesiones de la cuenta."""
    bind_request(db, actor.id)
    current_hash = actor.hashed_password
    user_id = actor.id
    db.rollback()
    valid = verify_password(data.current_password, current_hash)
    new_hash = hash_password(data.new_password)
    _lock_administration(db)
    user = db.get(User, user_id)
    if not user or not user.is_active or user.hashed_password != current_hash or not valid:
        record_event(db, "user.password_change_failed", actor_id=user_id, target_id=user_id, outcome="failure")
        db.commit()
        raise Unauthenticated("Invalid credentials")
    user.hashed_password = new_hash
    _revoke_sessions(db, user_id)
    record_event(db, "user.password_changed", actor_id=user_id, target_id=user_id)
    db.commit()


def unlock_user(user_id: int, db: Session, actor: User) -> UserRead:
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    _lock_administration(db)
    require_user_permission(db, actor, Permission.USERS_MANAGE)
    user = db.get(User, user_id)
    if not user:
        raise NotFound("User not found")
    user.failed_login_attempts = 0
    user.login_locked_until = None
    record_event(db, "user.unlocked", actor_id=actor.id, target_id=user.id)
    db.commit()
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

def active_staff(db: Session) -> list[dict]:
    """Contactos del equipo técnico: contrato para notificar sin exponer el modelo User."""
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all()
    staff = []
    for user in users:
        roles = {role.name for role in user.roles}
        if roles & {"admin", "tecnico", "operador"}:
            staff.append({"id": user.id, "email": user.email, "admin": "admin" in roles})
    return staff

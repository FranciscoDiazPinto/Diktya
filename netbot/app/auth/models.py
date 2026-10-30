from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Table, Column, func, JSON, event, DDL
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(160))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class AuthAuditEvent(Base):
    __tablename__ = "auth_audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    target_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@event.listens_for(AuthAuditEvent, "before_update")
@event.listens_for(AuthAuditEvent, "before_delete")
def _immutable_audit(mapper, connection, target):
    raise ValueError("La auditoría es de solo inserción.")


# También protegen operaciones SQL directas; Alembic instala los mismos triggers.
for action in ("UPDATE", "DELETE"):
    event.listen(AuthAuditEvent.__table__, "after_create", DDL(
        f"CREATE TRIGGER auth_audit_no_{action.lower()} BEFORE {action} ON auth_audit_events "
        "BEGIN SELECT RAISE(ABORT, 'auth audit is append only'); END"
    ).execute_if(dialect="sqlite"))
event.listen(AuthAuditEvent.__table__, "after_create", DDL(
    "CREATE TRIGGER auth_users_no_audited_delete BEFORE DELETE ON users "
    "WHEN EXISTS (SELECT 1 FROM auth_audit_events WHERE actor_id=OLD.id OR target_id=OLD.id) "
    "BEGIN SELECT RAISE(ABORT, 'audited users cannot be deleted'); END"
).execute_if(dialect="sqlite"))

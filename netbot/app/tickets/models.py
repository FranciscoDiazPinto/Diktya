from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("created_by_id", "request_key", name="uq_ticket_owner_request"),
        CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_ticket_status"),
        CheckConstraint("criticality IN ('baja', 'media', 'alta', 'critica')", name="ck_ticket_criticality"),
        # Un incidente tiene un solo ticket sin cerrar.
        Index("uq_ticket_active_incident", "incident_key", unique=True,
              sqlite_where=text("status <> 'closed'"), postgresql_where=text("status <> 'closed'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    # Los tickets de infraestructura no pertenecen a una red ni a un solicitante.
    network_id: Mapped[int | None] = mapped_column(ForeignKey("networks.id"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    request_key: Mapped[str | None] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    version: Mapped[int] = mapped_column(default=0)
    network_snapshot: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(16), default="customer")
    criticality: Mapped[str] = mapped_column(String(8), default="media", index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    incident_key: Mapped[str | None] = mapped_column(String(255))
    incident_type: Mapped[str | None] = mapped_column(String(40))
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_alerts.id", ondelete="SET NULL"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_devices.id", ondelete="SET NULL"))
    device_name: Mapped[str | None] = mapped_column(String(255))
    evidence: Mapped[dict | None] = mapped_column(JSON)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    resolution: Mapped[str | None] = mapped_column(String(1000))
    attention_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    escalations: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None = sistema
    kind: Mapped[str] = mapped_column(String(16), default="status")
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Una entrega por usuario y canal: registra envío, intentos y lectura."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel IN ('in_app', 'email')", name="ck_notification_channel"),
        CheckConstraint("status IN ('pending', 'sent', 'failed', 'cancelled')", name="ck_notification_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(8))
    event: Mapped[str] = mapped_column(String(16))
    criticality: Mapped[str] = mapped_column(String(8))
    highlighted: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

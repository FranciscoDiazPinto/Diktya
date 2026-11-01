"""Tablas de monitoreo: último inventario conocido, alertas y planos."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UtcDateTime(TypeDecorator):
    """Siempre con zona: SQLite la pierde y PostgreSQL la conserva."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class SourceState(Base):
    """Estado de cada integración, para el health check."""

    __tablename__ = "monitoring_sources"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="unavailable")
    version: Mapped[str | None] = mapped_column(String(120))
    last_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error_kind: Mapped[str | None] = mapped_column(String(32))
    last_error_message: Mapped[str | None] = mapped_column(String(255))


class MonitoredDevice(Base):
    __tablename__ = "monitoring_devices"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_monitoring_device"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(255))
    device_type: Mapped[str] = mapped_column(String(16), index=True)
    model: Mapped[str | None] = mapped_column(String(120))
    mac_address: Mapped[str | None] = mapped_column(String(17))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), index=True)
    last_online_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    missing_since: Mapped[datetime | None] = mapped_column(UtcDateTime)


class MonitoredVlan(Base):
    __tablename__ = "monitoring_vlans"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_monitoring_vlan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(160))
    name: Mapped[str | None] = mapped_column(String(255))
    tag: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    missing_since: Mapped[datetime | None] = mapped_column(UtcDateTime)


class MonitoredSsid(Base):
    __tablename__ = "monitoring_ssids"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_monitoring_ssid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean)
    security: Mapped[str | None] = mapped_column(String(40))
    vlan_tag: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    missing_since: Mapped[datetime | None] = mapped_column(UtcDateTime)


class DeviceAvailability(Base):
    """Tiempo observado por hora. Lo no observado no suma: un silencio no es una caída."""

    __tablename__ = "monitoring_availability"
    __table_args__ = (UniqueConstraint("device_id", "bucket_start", name="uq_monitoring_availability"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("monitoring_devices.id", ondelete="CASCADE"))
    bucket_start: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    online_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    observed_seconds: Mapped[float] = mapped_column(Float, default=0.0)


class MonitoringAlert(Base):
    __tablename__ = "monitoring_alerts"
    __table_args__ = (
        # Una condición activa, una alerta, también ante escrituras concurrentes.
        Index("uq_monitoring_alert_active", "dedup_key", unique=True,
              sqlite_where=text("resolved_at IS NULL"), postgresql_where=text("resolved_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16))
    severity_rank: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_devices.id", ondelete="SET NULL"), index=True)
    device_name: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, index=True)


class CoveragePlan(Base):
    __tablename__ = "monitoring_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(32))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class DevicePlacement(Base):
    """Ubicación relativa (0–1) en un plano. Un AP está en un solo plano."""

    __tablename__ = "monitoring_placements"
    __table_args__ = (UniqueConstraint("device_id", name="uq_monitoring_placement_device"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("monitoring_plans.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("monitoring_devices.id", ondelete="CASCADE"))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)

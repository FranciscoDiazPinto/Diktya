from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text, JSON, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VlanReservation(Base):
    __tablename__ = "vlan_reservations"
    __table_args__ = (
        Index("uq_active_vlan_reservation", "parent_interface", "tag", unique=True,
              sqlite_where=text("status = 'reserved'"), postgresql_where=text("status = 'reserved'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_interface: Mapped[str] = mapped_column(String(64), nullable=False)
    tag: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(160))
    interface_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    ssid: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CsvImport(Base):
    __tablename__ = "csv_imports"
    __table_args__ = (CheckConstraint("status IN ('preview', 'confirmed', 'cancelled')", name="ck_csv_import_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="preview")
    source: Mapped[str] = mapped_column(String(32))
    source_context: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WifiScope(Base):
    __tablename__ = "wifi_scopes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    site_id: Mapped[str] = mapped_column(String(160))
    resources: Mapped[dict] = mapped_column(JSON)


class WifiScopeGrant(Base):
    __tablename__ = "wifi_scope_grants"
    scope_id: Mapped[int] = mapped_column(ForeignKey("wifi_scopes.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class SsidPlan(Base):
    __tablename__ = "ssid_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    scope_id: Mapped[int] = mapped_column(ForeignKey("wifi_scopes.id"))
    status: Mapped[str] = mapped_column(String(16), default="preview")
    source: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    selection: Mapped[list] = mapped_column(JSON, default=list)
    execution_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WifiWriteLease(Base):
    __tablename__ = "wifi_write_leases"
    resource_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("ssid_plans.id"), index=True)

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NetworkSupportConfig(Base):
    __tablename__ = "network_support_config"

    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"), primary_key=True)
    guest_recovery_purpose: Mapped[str] = mapped_column(String(24), default="disabled", server_default="disabled")
    credential_ref: Mapped[str | None] = mapped_column(String(160))
    monitoring_interface_id: Mapped[str | None] = mapped_column(String(160))
    unifi_site_id: Mapped[str | None] = mapped_column(String(160))
    unifi_ap_ids: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")


class SupportAudit(Base):
    __tablename__ = "support_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WifiEmailRecovery(Base):
    __tablename__ = "wifi_email_recoveries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    network_ids: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

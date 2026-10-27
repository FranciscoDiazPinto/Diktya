from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NetworkSupportConfig(Base):
    __tablename__ = "network_support_config"

    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"), primary_key=True)
    credential_ref: Mapped[str | None] = mapped_column(String(160))
    monitoring_interface_id: Mapped[str | None] = mapped_column(String(160))


class SupportAudit(Base):
    __tablename__ = "support_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

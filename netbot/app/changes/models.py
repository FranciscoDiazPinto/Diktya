from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
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

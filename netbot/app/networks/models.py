from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Network(Base):
    __tablename__ = "networks"
    __table_args__ = (UniqueConstraint("site", "external_id", name="uq_network_site_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    site: Mapped[str] = mapped_column(String(160))
    event_name: Mapped[str] = mapped_column(String(160))
    external_id: Mapped[str] = mapped_column(String(160))
    ssid: Mapped[str] = mapped_column(String(64))
    vlan_tag: Mapped[int | None]


class NetworkAssignment(Base):
    __tablename__ = "network_assignments"

    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)


class NetworkRecipient(Base):
    """Contacto que recibió credenciales para una red; no es un usuario de Netbot."""
    __tablename__ = "network_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(16), index=True)

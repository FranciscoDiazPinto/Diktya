from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.access import require_user_permission
from app.auth.permissions import Permission
from app.monitoring.schemas import MonitoringStatus
from app.monitoring.service import MonitoringService

from .models import VlanReservation
from .schemas import AvailableVlan, VlanReservationCreate, VlanReservationRead

ACTIVE = ("reserved", "assigned")


class InventoryUnavailable(Exception): pass
class ReservationNotFound(Exception): pass
class ReservationAlreadyReleased(Exception): pass


class VlanConflict(Exception):
    """La VLAN no existe o ya está tomada; informa quién la reservó y qué queda libre."""

    def __init__(self, taken_by: str | None = None, alternatives: list[str] | None = None):
        self.taken_by, self.alternatives = taken_by, alternatives or []
        super().__init__("VLAN no disponible")

    @property
    def detail(self) -> str:
        message = (f"La VLAN ya está reservada para «{self.taken_by}»." if self.taken_by
                   else "La VLAN ya no está disponible.")
        if self.alternatives:
            message += " Alternativas libres: " + ", ".join(self.alternatives) + "."
        return message


def build_reservation(data, item, actor_id: int, now: datetime, ttl_hours: float | None = None) -> VlanReservation:
    """Construye una reserva; el caso de uso llamante controla flush/commit."""
    return VlanReservation(parent_interface=item.parent_interface, tag=item.tag,
                           description=item.description, interface_name=item.interface_name,
                           event_name=data.event_name, purpose=data.purpose, ssid=data.ssid,
                           status="reserved", requested_by_id=actor_id, created_at=now,
                           expires_at=now + timedelta(hours=ttl_hours) if ttl_hours else None)


def expire_due(db: Session, now: datetime) -> int:
    """Libera reservas vencidas sin asignar. No confirma: el llamante posee la transacción."""
    result = db.execute(update(VlanReservation).where(
        VlanReservation.status == "reserved", VlanReservation.expires_at.is_not(None),
        VlanReservation.expires_at <= now).values(status="released", released_at=now, released_by_id=None),
        execution_options={"synchronize_session": False})
    return result.rowcount or 0


def mark_assigned(db: Session, parent_interface: str, tag: int, now: datetime) -> bool:
    """La reserva pasa a asignada cuando el cambio que la usa se verificó. No confirma."""
    result = db.execute(update(VlanReservation).where(
        VlanReservation.status == "reserved", VlanReservation.parent_interface == parent_interface,
        VlanReservation.tag == tag).values(status="assigned", assigned_at=now, expires_at=None),
        execution_options={"synchronize_session": False})
    return bool(result.rowcount)


class VlanReservationService:
    def __init__(self, monitoring_service: MonitoringService, db_session: Session, ttl_hours: float | None = None):
        self.monitoring = monitoring_service
        self.db = db_session
        self.ttl_hours = ttl_hours

    def _active(self) -> dict[tuple[str, int], str]:
        expire_due(self.db, datetime.now(timezone.utc))
        return {(parent, tag): event for parent, tag, event in self.db.execute(
            select(VlanReservation.parent_interface, VlanReservation.tag, VlanReservation.event_name)
            .where(VlanReservation.status.in_(ACTIVE))).all()}

    async def available_vlans(self) -> list[AvailableVlan]:
        inventory = await self.monitoring.get_vlan_inventory()
        if inventory.status != MonitoringStatus.OK or inventory.stale or inventory.data is None:
            raise InventoryUnavailable
        reserved = self._active()
        self.db.commit()  # vencimientos aplicados durante la consulta
        return [AvailableVlan(**item.model_dump()) for item in inventory.data
                if (item.parent_interface, item.tag) not in reserved]

    async def create(self, data: VlanReservationCreate, actor: User) -> VlanReservationRead:
        require_user_permission(self.db, actor, Permission.VLAN_RESERVE)
        inventory = await self.monitoring.get_vlan_inventory()
        require_user_permission(self.db, actor, Permission.VLAN_RESERVE)
        if inventory.data is None or inventory.status != MonitoringStatus.OK or inventory.stale:
            raise InventoryUnavailable
        key = (data.parent_interface, data.tag)
        item = next((v for v in inventory.data if (v.parent_interface, v.tag) == key), None)
        active = self._active()
        if item is None or key in active:
            free = [f"{v.parent_interface}.{v.tag}" for v in inventory.data
                    if (v.parent_interface, v.tag) not in active][:5]
            self.db.commit()
            raise VlanConflict(active.get(key), free)
        row = build_reservation(data, item, actor.id, datetime.now(timezone.utc), self.ttl_hours)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise VlanConflict() from None
        self.db.refresh(row)
        return VlanReservationRead.from_model(row)

    def list_active(self) -> list[VlanReservationRead]:
        if expire_due(self.db, datetime.now(timezone.utc)):
            self.db.commit()
        rows = self.db.scalars(select(VlanReservation).where(VlanReservation.status.in_(ACTIVE))
                               .order_by(VlanReservation.created_at)).all()
        return [VlanReservationRead.from_model(row) for row in rows]

    def release(self, reservation_id: int, actor: User) -> VlanReservationRead:
        require_user_permission(self.db, actor, Permission.VLAN_RESERVE)
        row = self.db.get(VlanReservation, reservation_id)
        if row is None:
            raise ReservationNotFound
        if row.status not in ACTIVE:
            raise ReservationAlreadyReleased
        row.status = "released"
        row.released_by_id = actor.id
        row.released_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return VlanReservationRead.from_model(row)

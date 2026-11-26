from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.access import require_user_permission
from app.auth.audit import record_event
from app.auth.permissions import Permission
from app.core.errors import Conflict
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
    rows = db.execute(update(VlanReservation).where(
        VlanReservation.status == "reserved", VlanReservation.expires_at.is_not(None),
        VlanReservation.expires_at <= now, VlanReservation.held_by_plan_id.is_(None)).values(status="released", released_at=now, released_by_id=None)
        .returning(VlanReservation.id, VlanReservation.requested_by_id),
        execution_options={"synchronize_session": "fetch"}).all()
    for reservation_id, requester_id in rows:
        record_event(db, 'vlan.reservation.expired', target_id=requester_id,
                     source='system', details={'reservation_id': reservation_id})
    return len(rows)



def find_reserved_vlan(
    db: Session, *, parent_interface: str, tag: int, event_name: str,
    ssid: str, actor_id: int, now: datetime, lock: bool = False,
) -> int | None:
    """Identifica una reserva vigente del actor para la operación exacta."""
    conditions = (
        VlanReservation.status == "reserved",
        VlanReservation.parent_interface == parent_interface,
        VlanReservation.tag == tag,
        VlanReservation.event_name == event_name,
        VlanReservation.ssid == ssid,
        VlanReservation.requested_by_id == actor_id,
        VlanReservation.held_by_plan_id.is_(None),
        or_(VlanReservation.expires_at.is_(None), VlanReservation.expires_at > now),
    )
    if lock:
        return db.scalar(update(VlanReservation).where(*conditions).values(
            status=VlanReservation.status,
        ).returning(VlanReservation.id), execution_options={'synchronize_session': False})
    return db.scalar(select(VlanReservation.id).where(*conditions))


def vlan_has_pending_reservation(db: Session, parent_interface: str, tag: int, now: datetime) -> bool:
    return db.scalar(select(VlanReservation.id).where(
        VlanReservation.status == 'reserved',
        VlanReservation.parent_interface == parent_interface,
        VlanReservation.tag == tag,
        or_(VlanReservation.held_by_plan_id.is_not(None), VlanReservation.expires_at.is_(None),
            VlanReservation.expires_at > now),
    )) is not None


def active_vlan_keys(db: Session, now: datetime) -> set[tuple[str, int]]:
    """Consulta ocupación sin liberar reservas ni cambiar la transacción."""
    rows = db.execute(select(VlanReservation.parent_interface, VlanReservation.tag).where(
        VlanReservation.status.in_(ACTIVE),
        or_(VlanReservation.status == 'assigned', VlanReservation.held_by_plan_id.is_not(None),
            VlanReservation.expires_at.is_(None), VlanReservation.expires_at > now),
    ))
    return {(parent, tag) for parent, tag in rows}


def hold_reservation(db: Session, reservation_id: int, plan_id: str, now: datetime) -> None:
    changed = db.execute(update(VlanReservation).where(
        VlanReservation.id == reservation_id, VlanReservation.status == 'reserved',
        VlanReservation.held_by_plan_id.is_(None),
        or_(VlanReservation.expires_at.is_(None), VlanReservation.expires_at > now),
    ).values(held_by_plan_id=plan_id))
    if changed.rowcount != 1:
        raise Conflict('La reserva confirmada ya no está vigente o pertenece a un cambio activo.')


def clear_reservation_hold(db: Session, reservation_id: int, plan_id: str) -> None:
    db.execute(update(VlanReservation).where(
        VlanReservation.id == reservation_id, VlanReservation.held_by_plan_id == plan_id,
    ).values(held_by_plan_id=None))


def mark_assigned(db: Session, reservation_id: int, now: datetime, *, plan_id: str | None = None) -> bool:
    """Asigna la reserva exacta y libera el bloqueo propio en la misma operación."""
    result = db.execute(update(VlanReservation).where(
        VlanReservation.id == reservation_id,
        VlanReservation.status == "reserved",
        VlanReservation.held_by_plan_id == plan_id,
    ).values(status="assigned", assigned_at=now, expires_at=None, held_by_plan_id=None))
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

    def list_my_expired(self, actor: User, limit: int, offset: int) -> list[VlanReservationRead]:
        require_user_permission(self.db, actor, Permission.VLAN_RESERVE)
        if expire_due(self.db, datetime.now(timezone.utc)):
            self.db.commit()
        rows = self.db.scalars(select(VlanReservation).where(
            VlanReservation.requested_by_id == actor.id,
            VlanReservation.status == 'released',
            VlanReservation.released_by_id.is_(None),
            VlanReservation.expires_at <= VlanReservation.released_at,
        ).order_by(VlanReservation.released_at.desc(), VlanReservation.id.desc()).limit(limit).offset(offset))
        return [VlanReservationRead.from_model(row) for row in rows]

    def release(self, reservation_id: int, actor: User) -> VlanReservationRead:
        require_user_permission(self.db, actor, Permission.VLAN_RESERVE)
        row = self.db.get(VlanReservation, reservation_id)
        if row is None:
            raise ReservationNotFound
        if row.status not in ACTIVE:
            raise ReservationAlreadyReleased
        changed = self.db.execute(update(VlanReservation).where(
            VlanReservation.id == reservation_id, VlanReservation.status.in_(ACTIVE),
            VlanReservation.held_by_plan_id.is_(None),
        ).values(status="released", released_by_id=actor.id, released_at=datetime.now(timezone.utc)))
        if changed.rowcount != 1:
            raise Conflict('La reserva cambió o está protegida por una ejecución o conciliación.')
        self.db.commit()
        self.db.refresh(row)
        return VlanReservationRead.from_model(row)

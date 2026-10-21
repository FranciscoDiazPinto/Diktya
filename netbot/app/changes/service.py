from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.monitoring.schemas import MonitoringStatus
from app.monitoring.service import MonitoringService

from .models import VlanReservation
from .schemas import AvailableVlan, VlanReservationCreate, VlanReservationRead


class InventoryUnavailable(Exception): pass
class VlanConflict(Exception): pass
class ReservationNotFound(Exception): pass
class ReservationAlreadyReleased(Exception): pass


class VlanReservationService:
    def __init__(self, monitoring_service: MonitoringService, db_session: Session):
        self.monitoring = monitoring_service
        self.db = db_session

    def _active_keys(self):
        return set(self.db.execute(select(VlanReservation.parent_interface, VlanReservation.tag)
                                   .where(VlanReservation.status == "reserved")).all())

    async def available_vlans(self) -> list[AvailableVlan]:
        inventory = await self.monitoring.get_vlan_inventory()
        if inventory.status == MonitoringStatus.UNAVAILABLE or inventory.data is None:
            raise InventoryUnavailable
        reserved = self._active_keys()
        return [AvailableVlan(**item.model_dump()) for item in inventory.data
                if (item.parent_interface, item.tag) not in reserved]

    async def create(self, data: VlanReservationCreate, actor: User) -> VlanReservationRead:
        inventory = await self.monitoring.get_vlan_inventory()
        if inventory.data is None or inventory.status == MonitoringStatus.UNAVAILABLE:
            raise InventoryUnavailable
        item = next((v for v in inventory.data if
                     (v.parent_interface, v.tag) == (data.parent_interface, data.tag)), None)
        if item is None or (data.parent_interface, data.tag) in self._active_keys():
            raise VlanConflict
        row = VlanReservation(parent_interface=item.parent_interface, tag=item.tag,
                              description=item.description, interface_name=item.interface_name,
                              event_name=data.event_name, purpose=data.purpose, ssid=data.ssid,
                              status="reserved", requested_by_id=actor.id,
                              created_at=datetime.now(timezone.utc))
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise VlanConflict from None
        self.db.refresh(row)
        return VlanReservationRead.from_model(row)

    def list_active(self) -> list[VlanReservationRead]:
        rows = self.db.scalars(select(VlanReservation).where(VlanReservation.status == "reserved")
                               .order_by(VlanReservation.created_at)).all()
        return [VlanReservationRead.from_model(row) for row in rows]

    def release(self, reservation_id: int, actor: User) -> VlanReservationRead:
        row = self.db.get(VlanReservation, reservation_id)
        if row is None:
            raise ReservationNotFound
        if row.status != "reserved":
            raise ReservationAlreadyReleased
        row.status = "released"
        row.released_by_id = actor.id
        row.released_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return VlanReservationRead.from_model(row)

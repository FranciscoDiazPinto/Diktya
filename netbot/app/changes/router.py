from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from app.monitoring.dependencies import MonitoringServiceDep

from .schemas import AvailableVlan, VlanReservationCreate, VlanReservationRead
from .service import (InventoryUnavailable, ReservationAlreadyReleased, ReservationNotFound, VlanConflict,
                      VlanReservationService)

router = APIRouter(prefix="/changes", tags=["changes"])

def _service(monitoring: MonitoringServiceDep, db: Session) -> VlanReservationService:
    return VlanReservationService(monitoring, db)

@router.get("/vlan-options", response_model=list[AvailableVlan])
async def vlan_options(monitoring: MonitoringServiceDep,
                       _user: User = Depends(require_permission(Permission.MONITORING_READ.value)),
                       db: Session = Depends(get_db)):
    try:
        return await _service(monitoring, db).available_vlans()
    except InventoryUnavailable:
        raise HTTPException(status_code=503, detail="Inventario VLAN no disponible.") from None

@router.get("/vlan-reservations", response_model=list[VlanReservationRead])
def list_reservations(monitoring: MonitoringServiceDep,
                      _user: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                      db: Session = Depends(get_db)):
    return _service(monitoring, db).list_active()

@router.post("/vlan-reservations", response_model=VlanReservationRead, status_code=201)
async def create_reservation(payload: VlanReservationCreate, monitoring: MonitoringServiceDep,
                             user: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                             db: Session = Depends(get_db)):
    try:
        return await _service(monitoring, db).create(payload, user)
    except InventoryUnavailable:
        raise HTTPException(status_code=503, detail="Inventario VLAN no disponible.") from None
    except VlanConflict:
        raise HTTPException(status_code=409, detail="La VLAN ya no está disponible.") from None

@router.post("/vlan-reservations/{reservation_id}/release", response_model=VlanReservationRead)
def release_reservation(reservation_id: int, monitoring: MonitoringServiceDep,
                        user: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                        db: Session = Depends(get_db)):
    try:
        return _service(monitoring, db).release(reservation_id, user)
    except ReservationNotFound:
        raise HTTPException(status_code=404, detail="Reserva activa no encontrada.") from None
    except ReservationAlreadyReleased:
        raise HTTPException(status_code=409, detail="La reserva ya fue liberada.") from None

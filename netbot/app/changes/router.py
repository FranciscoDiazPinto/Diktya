from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from app.monitoring.dependencies import MonitoringServiceDep
from app.core.config import Settings, get_settings

from .schemas import AvailableVlan, VlanReservationCreate, VlanReservationRead
from .service import (InventoryUnavailable, ReservationAlreadyReleased, ReservationNotFound, VlanConflict,
                      VlanReservationService)

from .csv_service import CsvImportService
from .csv_schemas import CsvImportRead, CsvImportSummary, CsvConfirm, CsvLimits
from .dependencies import get_csv_service, read_csv_body

router = APIRouter(prefix="/changes", tags=["changes"])


@router.get("/csv-imports/options", response_model=CsvLimits)
def csv_options(_actor: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                settings: Settings = Depends(get_settings)):
    return CsvLimits(max_bytes=settings.csv_max_bytes, max_rows=settings.csv_max_rows,
                     ttl_seconds=settings.csv_preview_ttl_seconds)


@router.get("/csv-imports", response_model=list[CsvImportSummary])
def csv_imports(actor: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                service: CsvImportService = Depends(get_csv_service),
                limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return service.list_imports(actor, limit, offset)


@router.post("/csv-imports", response_model=CsvImportRead, status_code=201,
             openapi_extra={"requestBody": {"required": True, "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}})
async def upload_csv(actor: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                      service: CsvImportService = Depends(get_csv_service),
                      filename: str = Query(default="import.csv", min_length=1, max_length=160),
                      content: bytes = Depends(read_csv_body)):
    return await service.preview(content, filename, actor)


@router.get("/csv-imports/{import_id}", response_model=CsvImportRead)
def csv_import(import_id: UUID, actor: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                service: CsvImportService = Depends(get_csv_service)):
    return service.get(str(import_id), actor)


@router.post("/csv-imports/{import_id}/confirm", response_model=CsvImportRead)
async def confirm_csv(import_id: UUID, payload: CsvConfirm,
                       actor: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                       service: CsvImportService = Depends(get_csv_service)):
    return await service.confirm(str(import_id), payload, actor)


@router.post("/csv-imports/{import_id}/cancel", response_model=CsvImportRead)
def cancel_csv(import_id: UUID, actor: User = Depends(require_permission(Permission.VLAN_RESERVE.value)),
                service: CsvImportService = Depends(get_csv_service)):
    return service.cancel(str(import_id), actor)

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

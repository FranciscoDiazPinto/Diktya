"""Endpoints de monitoreo del dashboard.

Todas las respuestas usan el mismo envoltorio (`MonitoringResponse`). Si no se pudo
obtener ningún dato de un recurso, responden HTTP 503 con el mismo formato
(`status="unavailable"`, `data=null` e `issues` con el detalle); si hubo datos
parciales responden 200 con `status="degraded"`. Como cada recurso es un endpoint
independiente, la caída de uno no afecta a los demás.

Inventario, alertas y planos se leen de la base: conservan el último dato conocido y lo
marcan con `stale` cuando la fuente deja de responder.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings, get_settings
from app.core.database import get_db

from . import inventory, plans
from .dependencies import MonitoringServiceDep, read_plan_body, require_monitoring_read
from .schemas import (
    AccessPointPage,
    AlertRead,
    DeviceDetail,
    DeviceRead,
    DeviceState,
    DeviceType,
    DhcpLease,
    FirewallAction,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    InterfaceTrafficHistory,
    InventorySummary,
    MonitoringResponse,
    MonitoringStatus,
    Page,
    PlacementWrite,
    PlanDetail,
    PlanRead,
    SourceHealth,
    SsidRead,
    SystemMetrics,
    VlanRead,
)

router = APIRouter(
    prefix="/monitoring",
    tags=["monitoring"],
    dependencies=[Depends(require_monitoring_read)],
)


def _finalize(response: Response, result: MonitoringResponse) -> MonitoringResponse:
    response.headers["Cache-Control"] = "private, no-store"
    if result.status == MonitoringStatus.UNAVAILABLE:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


_UNAVAILABLE = {503: {"description": "Fuente de monitoreo no disponible (sin datos)."}}


@router.get("/system", response_model=MonitoringResponse[SystemMetrics], responses=_UNAVAILABLE)
async def get_system(response: Response, service: MonitoringServiceDep):
    return _finalize(response, await service.get_system())


@router.get(
    "/interfaces", response_model=MonitoringResponse[list[InterfaceMetrics]], responses=_UNAVAILABLE
)
async def get_interfaces(response: Response, service: MonitoringServiceDep):
    return _finalize(response, await service.get_interfaces())


@router.get(
    "/interfaces/traffic",
    response_model=MonitoringResponse[list[InterfaceTrafficHistory]],
    responses=_UNAVAILABLE,
)
async def get_interface_traffic(
    response: Response,
    service: MonitoringServiceDep,
    window: Annotated[
        int, Query(ge=10, le=3600, description="Segundos de historial a devolver.")
    ] = 300,
):
    """Velocidad (bytes/s) por interfaz, calculada a partir de muestras periódicas."""
    return _finalize(response, await service.get_traffic_history(window))


@router.get("/clients", response_model=MonitoringResponse[list[DhcpLease]], responses=_UNAVAILABLE)
async def get_clients(response: Response, service: MonitoringServiceDep):
    return _finalize(response, await service.get_clients())


@router.get(
    "/firewall/stats", response_model=MonitoringResponse[FirewallStatistics], responses=_UNAVAILABLE
)
async def get_firewall_stats(response: Response, service: MonitoringServiceDep):
    return _finalize(response, await service.get_firewall_stats())


@router.get(
    "/firewall/events",
    response_model=MonitoringResponse[list[FirewallEvent]],
    responses=_UNAVAILABLE,
)
async def get_firewall_events(
    response: Response,
    service: MonitoringServiceDep,
    limit: Annotated[
        int, Query(ge=1, le=500, description="Máximo de eventos (más recientes primero).")
    ] = 100,
    action: Annotated[
        FirewallAction | None, Query(description="Filtra por acción: block o pass.")
    ] = None,
):
    return _finalize(response, await service.get_firewall_events(limit=limit, action=action))


# --------------------------------------------------------------------------- #
# Inventario persistido
# --------------------------------------------------------------------------- #

DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
require_plan_manage = require_permission(Permission.NETWORKS_MANAGE.value)


@router.get("/health", response_model=list[SourceHealth])
def get_health(db: DbDep, settings: SettingsDep):
    """Estado de cada integración según su último ciclo de recolección."""
    return inventory.source_health(db, settings)


@router.get("/summary", response_model=InventorySummary)
def get_summary(db: DbDep, settings: SettingsDep):
    return inventory.summary(db, settings)


@router.get("/devices", response_model=Page[DeviceRead])
def get_devices(db: DbDep, settings: SettingsDep, state: DeviceState | None = None,
                type: DeviceType | None = None, limit: Limit = 50, offset: Offset = 0):
    return inventory.list_devices(db, settings, state=state, device_type=type, limit=limit, offset=offset)


@router.get("/devices/{device_id}", response_model=DeviceDetail)
def get_device(device_id: int, db: DbDep, settings: SettingsDep):
    return inventory.get_device(db, settings, device_id)


@router.get("/vlans", response_model=Page[VlanRead])
def get_vlans(db: DbDep, settings: SettingsDep, limit: Limit = 100, offset: Offset = 0):
    return inventory.list_vlans(db, settings, limit=limit, offset=offset)


@router.get("/ssids", response_model=Page[SsidRead])
def get_ssids(db: DbDep, settings: SettingsDep, limit: Limit = 100, offset: Offset = 0):
    return inventory.list_ssids(db, settings, limit=limit, offset=offset)


@router.get("/alerts", response_model=Page[AlertRead])
def get_alerts(db: DbDep, settings: SettingsDep, active: bool = True, limit: Limit = 50, offset: Offset = 0):
    """Mayor severidad primero."""
    return inventory.list_alerts(db, settings, active=active, limit=limit, offset=offset)


@router.get("/plans", response_model=list[PlanRead])
def get_plans(db: DbDep):
    return plans.list_plans(db)


@router.post("/plans", response_model=PlanRead, status_code=201, openapi_extra={"requestBody": {
    "required": True, "content": {"image/png": {"schema": {"type": "string", "format": "binary"}},
                                  "image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}})
def post_plan(db: DbDep, settings: SettingsDep, name: Annotated[str, Query(min_length=1, max_length=120)],
              actor: User = Depends(require_plan_manage), content: bytes = Depends(read_plan_body)):
    return plans.create_plan(db, actor, settings, name, content)


@router.get("/plans/{plan_id}", response_model=PlanDetail)
def get_plan(plan_id: int, db: DbDep, settings: SettingsDep):
    return plans.plan_detail(db, settings, plan_id)


@router.get("/plans/{plan_id}/image", response_class=Response)
def get_plan_image(plan_id: int, db: DbDep):
    content, content_type = plans.plan_image(db, plan_id)
    return Response(content, media_type=content_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int, db: DbDep, actor: User = Depends(require_plan_manage)):
    plans.delete_plan(db, actor, plan_id)


@router.put("/plans/{plan_id}/placements/{device_id}", status_code=204)
def put_placement(plan_id: int, device_id: int, position: PlacementWrite, db: DbDep, settings: SettingsDep,
                  actor: User = Depends(require_plan_manage)):
    plans.place_device(db, actor, settings, plan_id, device_id, position)


@router.delete("/plans/{plan_id}/placements/{device_id}", status_code=204)
def delete_placement(plan_id: int, device_id: int, db: DbDep, actor: User = Depends(require_plan_manage)):
    plans.remove_placement(db, actor, plan_id, device_id)


@router.get("/access-points", response_model=MonitoringResponse[AccessPointPage], responses=_UNAVAILABLE)
async def get_access_points(response: Response, service: MonitoringServiceDep,
                            limit: int = Query(default=50,ge=1,le=100), offset: int = Query(default=0,ge=0)):
    return _finalize(response, await service.get_access_point_page(limit,offset))

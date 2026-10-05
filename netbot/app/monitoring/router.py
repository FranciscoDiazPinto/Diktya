"""Endpoints internos de monitoreo, pensados para el futuro dashboard.

Todas las respuestas usan el mismo envoltorio (`MonitoringResponse`). Si no se pudo
obtener ningún dato de un recurso, responden HTTP 503 con el mismo formato
(`status="unavailable"`, `data=null` e `issues` con el detalle); si hubo datos
parciales responden 200 con `status="degraded"`. Como cada recurso es un endpoint
independiente, la caída de uno no afecta a los demás.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from .dependencies import MonitoringServiceDep, require_monitoring_read
from .schemas import (
    DhcpLease,
    FirewallAction,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    MonitoringResponse,
    MonitoringStatus,
    SystemMetrics,
)

router = APIRouter(
    prefix="/monitoring",
    tags=["monitoring"],
    dependencies=[Depends(require_monitoring_read)],
)


def _finalize(response: Response, result: MonitoringResponse) -> MonitoringResponse:
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

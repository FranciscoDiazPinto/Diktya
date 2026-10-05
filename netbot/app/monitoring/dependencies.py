"""Dependencias de FastAPI del módulo de monitoreo."""

from typing import Annotated

from fastapi import Depends, Request

from .service import MonitoringService


def get_monitoring_service(request: Request) -> MonitoringService:
    service = getattr(request.app.state, "monitoring_service", None)
    if service is None:
        raise RuntimeError("MonitoringService no inicializado (revise el lifespan de la app).")
    return service


async def require_monitoring_read() -> None:
    """Punto de integración con la Épica 001 (autenticación y roles).

    TODO(Épica 001): exigir `Permission.MONITORING_READ` (app.auth.permissions) sobre el
    usuario autenticado. Mientras no exista autenticación, los endpoints de monitoreo
    NO están protegidos: no exponer este servicio fuera de la red local de desarrollo.
    """
    return None


MonitoringServiceDep = Annotated[MonitoringService, Depends(get_monitoring_service)]

"""Dependencias de FastAPI del módulo de monitoreo."""

from typing import Annotated

from fastapi import Depends, Request

from app.auth.dependencies import require_permission
from app.auth.permissions import Permission

from .service import MonitoringService


def get_monitoring_service(request: Request) -> MonitoringService:
    service = getattr(request.app.state, "monitoring_service", None)
    if service is None:
        raise RuntimeError("MonitoringService no inicializado (revise el lifespan de la app).")
    return service


# Los endpoints de monitoreo exigen un usuario autenticado con `monitoring:read`
# (roles admin, operador y visor).
require_monitoring_read = require_permission(Permission.MONITORING_READ.value)


MonitoringServiceDep = Annotated[MonitoringService, Depends(get_monitoring_service)]

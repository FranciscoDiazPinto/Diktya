"""Dependencias de FastAPI del módulo de monitoreo."""

from typing import Annotated

from fastapi import Depends, Request

from app.auth.dependencies import require_permission
from app.auth.permissions import Permission
from app.core.config import Settings, get_settings
from app.core.errors import InvalidInput, PayloadTooLarge

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


async def read_plan_body(request: Request, settings: Settings = Depends(get_settings)) -> bytes:
    """Cuerpo crudo con límite efectivo aunque falte o mienta Content-Length."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"image/png", "image/jpeg"}:
        raise InvalidInput("Envía la imagen PNG o JPEG como cuerpo crudo.")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > settings.monitoring_plan_max_bytes:
            raise PayloadTooLarge("La imagen supera el tamaño máximo permitido.")
        content.extend(chunk)
    return bytes(content)

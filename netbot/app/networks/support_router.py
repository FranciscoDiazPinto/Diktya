from fastapi import APIRouter, Depends, Response, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.monitoring.dependencies import MonitoringServiceDep
from .diagnostics import network_status
from .credentials import reveal_wifi
from . import configuration
from .support_schemas import SupportConfigWrite, NetworkStatus, WifiAccessRead, SupportAuditRead

router = APIRouter(prefix="/networks", tags=["network support"])
admin_router = APIRouter(prefix="/admin/networks", tags=["network support configuration"])


@admin_router.get("/{network_id}/support", response_model=SupportConfigWrite)
def read_support_config(network_id: int, user: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return configuration.read_support_config(network_id, user, db)


@admin_router.get("/{network_id}/support-audit", response_model=list[SupportAuditRead])
def read_support_audit(network_id: int, user: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)),
                       db: Session = Depends(get_db), limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return configuration.read_support_audit(network_id, user, db, limit, offset)


@admin_router.put("/{network_id}/support", response_model=SupportConfigWrite)
def configure_support(network_id: int, payload: SupportConfigWrite,
                      user: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return configuration.configure_support(network_id, payload, user, db)


@router.get("/{network_id}/status", response_model=NetworkStatus)
async def read_network_status(network_id: int, monitoring: MonitoringServiceDep,
                              user: User = Depends(require_permission(Permission.NETWORKS_READ_OWN.value)),
                              db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return await network_status(db, user, network_id, monitoring, settings)


@router.post("/{network_id}/access", response_model=WifiAccessRead)
def read_wifi_access(network_id: int, response: Response,
                     user: User = Depends(require_permission(Permission.WIFI_ACCESS_READ_OWN.value)),
                     db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return reveal_wifi(db, user, network_id, settings)

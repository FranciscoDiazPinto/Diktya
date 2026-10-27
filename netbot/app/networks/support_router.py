from fastapi import APIRouter, Depends, Response, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.monitoring.dependencies import MonitoringServiceDep
from .access import require_network
from .support import network_status, reveal_wifi
from .support_models import NetworkSupportConfig, SupportAudit
from .support_schemas import SupportConfigWrite, NetworkStatus, WifiAccessRead, SupportAuditRead

router = APIRouter(prefix="/networks", tags=["network support"])
admin_router = APIRouter(prefix="/admin/networks", tags=["network support configuration"])


@admin_router.get("/{network_id}/support", response_model=SupportConfigWrite)
def read_support_config(network_id: int, user: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    require_network(db, user, network_id)
    return db.get(NetworkSupportConfig, network_id) or SupportConfigWrite()


@admin_router.get("/{network_id}/support-audit", response_model=list[SupportAuditRead])
def read_support_audit(network_id: int, user: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)),
                       db: Session = Depends(get_db), limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    require_network(db, user, network_id)
    return db.scalars(select(SupportAudit).where(SupportAudit.network_id == network_id)
                      .order_by(SupportAudit.id.desc()).limit(limit).offset(offset)).all()


@admin_router.put("/{network_id}/support", response_model=SupportConfigWrite)
def configure_support(network_id: int, payload: SupportConfigWrite,
                      user: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    require_network(db, user, network_id)
    config = db.get(NetworkSupportConfig, network_id)
    if config is None:
        config = NetworkSupportConfig(network_id=network_id)
        db.add(config)
    config.credential_ref = payload.credential_ref
    config.monitoring_interface_id = payload.monitoring_interface_id
    db.add(SupportAudit(actor_id=user.id, network_id=network_id, action="network_support.updated"))
    db.commit()
    return config


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
    try:
        return reveal_wifi(db, user, network_id, settings)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store, private", "Pragma": "no-cache"}
        raise

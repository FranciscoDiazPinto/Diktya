from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db

from . import orchestrator

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/status")
def status(db: Session = Depends(get_db),
           actor: User = Depends(require_permission(Permission.MONITORING_READ.value))):
    """Última ejecución, errores y estado de cada agente en segundo plano."""
    return orchestrator.agent_status(db, actor)


@router.get("/events")
def events(correlation_id: str | None = Query(None, min_length=1, max_length=64),
           agent_id: str | None = Query(None, min_length=1, max_length=32),
           limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
           db: Session = Depends(get_db),
           actor: User = Depends(require_permission(Permission.AUDIT_READ.value))):
    return orchestrator.agent_events(db, actor, correlation_id=correlation_id, agent_id=agent_id,
                                     limit=limit, offset=offset)

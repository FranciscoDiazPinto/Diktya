from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.core.database import get_db
from . import service
from .schemas import AuditFilters, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])
NO_STORE = {"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"}


@router.get("", response_model=AuditPage)
def list_audit(response: Response, filters: Annotated[AuditFilters, Query()],
               limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), actor: User = Depends(require_permission("audit:read"))):
    response.headers.update(NO_STORE)
    return service.list_entries(db, actor, filters, limit=limit, offset=offset)


@router.get("/export")
def export_audit(filters: Annotated[AuditFilters, Query()], db: Session = Depends(get_db),
                 actor: User = Depends(require_permission("audit:read"))):
    content = service.export_csv(db, actor, filters)
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={**NO_STORE, "Content-Disposition": 'attachment; filename="netbot-auditoria.csv"'})

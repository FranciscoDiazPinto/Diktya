from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from app.core.config import Settings, get_settings
from app.monitoring.dependencies import MonitoringServiceDep
from .schemas import TicketCreate, TicketRead, TicketDetail, TicketUpdate, TicketState
from . import service

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketRead])
def list_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                 network_id: int | None = Query(default=None, gt=0), status: TicketState | None = None):
    return service.list_tickets(db, user, limit=limit, offset=offset, network_id=network_id, status=status)


@router.get("/{ticket_id}", response_model=TicketDetail)
def read_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.ticket_detail(db, user, ticket_id)


@router.post("", response_model=TicketRead, status_code=201)
async def open_ticket(payload: TicketCreate, monitoring: MonitoringServiceDep,
                      user: User = Depends(require_permission(Permission.TICKETS_CREATE_OWN.value)),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return await service.create_ticket(db, user, payload, monitoring, settings)


@router.patch("/{ticket_id}", response_model=TicketRead)
def change_ticket(ticket_id: int, payload: TicketUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_ticket(db, user, ticket_id, payload)

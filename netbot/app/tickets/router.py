from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from app.core.config import Settings, get_settings
from app.monitoring.dependencies import MonitoringServiceDep
from .models import Ticket, TicketEvent
from .schemas import TicketCreate, TicketRead, TicketDetail, TicketEventRead, TicketUpdate, TicketState
from .service import ticket_query, get_ticket, create_ticket, update_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketRead])
def list_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                 network_id: int | None = Query(default=None, gt=0), status: TicketState | None = None):
    query = ticket_query(db, user)
    if network_id is not None:
        query = query.where(Ticket.network_id == network_id)
    if status is not None:
        query = query.where(Ticket.status == status)
    return db.scalars(query.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(limit).offset(offset)).all()


@router.get("/{ticket_id}", response_model=TicketDetail)
def read_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = get_ticket(db, user, ticket_id)
    events = db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id).order_by(TicketEvent.id)).all()
    return TicketDetail(**TicketRead.model_validate(ticket).model_dump(),
                        events=[TicketEventRead.model_validate(e) for e in events])


@router.post("", response_model=TicketRead, status_code=201)
async def open_ticket(payload: TicketCreate, monitoring: MonitoringServiceDep,
                      user: User = Depends(require_permission(Permission.TICKETS_CREATE_OWN.value)),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return await create_ticket(db, user, payload, monitoring, settings)


@router.patch("/{ticket_id}", response_model=TicketRead)
def change_ticket(ticket_id: int, payload: TicketUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return update_ticket(db, user, ticket_id, payload)

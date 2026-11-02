from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from app.core.config import Settings, get_settings
from app.monitoring.dependencies import MonitoringServiceDep
from .schemas import (Criticality, NotificationPage, NotificationRead, TicketAssign, TicketComment, TicketCreate,
                      TicketCriticalityUpdate, TicketDetail, TicketManualCreate, TicketRead, TicketState, TicketUpdate)
from . import notifications, service

router = APIRouter(prefix="/tickets", tags=["tickets"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[TicketRead])
def list_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                 network_id: int | None = Query(default=None, gt=0), status: TicketState | None = None,
                 criticality: Criticality | None = None, assignee_id: int | None = Query(default=None, gt=0)):
    return service.list_tickets(db, user, limit=limit, offset=offset, network_id=network_id, status=status,
                                criticality=criticality, assignee_id=assignee_id)


@router.get("/{ticket_id}", response_model=TicketDetail)
def read_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.ticket_detail(db, user, ticket_id)


@router.post("", response_model=TicketRead, status_code=201)
async def open_ticket(payload: TicketCreate, monitoring: MonitoringServiceDep,
                      user: User = Depends(require_permission(Permission.TICKETS_CREATE_OWN.value)),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return await service.create_ticket(db, user, payload, monitoring, settings)


@router.post("/manual", response_model=TicketRead, status_code=201)
async def open_manual_ticket(payload: TicketManualCreate, monitoring: MonitoringServiceDep,
                             user: User = Depends(get_current_user), db: Session = Depends(get_db),
                             settings: Settings = Depends(get_settings)):
    return await service.create_manual_ticket(db, user, payload, monitoring, settings)


@router.patch("/{ticket_id}", response_model=TicketRead)
def change_ticket(ticket_id: int, payload: TicketUpdate, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return service.update_ticket(db, user, ticket_id, payload, settings)


@router.post("/{ticket_id}/assign", response_model=TicketRead)
def assign_ticket(ticket_id: int, payload: TicketAssign, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return service.assign_ticket(db, user, ticket_id, payload)


@router.post("/{ticket_id}/comments", response_model=TicketDetail, status_code=201)
def comment_ticket(ticket_id: int, payload: TicketComment, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    return service.comment_ticket(db, user, ticket_id, payload)


@router.patch("/{ticket_id}/criticality", response_model=TicketRead)
def change_criticality(ticket_id: int, payload: TicketCriticalityUpdate, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return service.set_criticality(db, user, ticket_id, payload, settings)


@notifications_router.get("", response_model=NotificationPage)
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                       limit: int = Query(default=30, ge=1, le=100)):
    return notifications.list_for_user(db, user, limit)


@notifications_router.post("/{notification_id}/read", response_model=NotificationRead)
def read_notification(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return notifications.mark_read(db, user, notification_id)

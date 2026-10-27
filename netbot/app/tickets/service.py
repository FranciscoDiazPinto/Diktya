from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.core.config import Settings
from app.monitoring.service import MonitoringService
from app.networks.access import accessible_networks
from app.networks.support import authorize, network_status
from app.networks.support_models import SupportAudit
from .models import Ticket, TicketEvent
from .schemas import TicketCreate, TicketUpdate


def ticket_query(db: Session, user: User):
    db.expire_all()
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario inactivo.")
    permissions = effective_permissions(user)
    query = select(Ticket)
    if Permission.TICKETS_READ in permissions:
        return query
    if Permission.TICKETS_READ_OWN not in permissions and Permission.TICKETS_READ_ASSIGNED not in permissions:
        raise HTTPException(status_code=403, detail="Permiso insuficiente para consultar tickets.")
    query = query.where(Ticket.network_id.in_([n.id for n in accessible_networks(db, user)]))
    if Permission.TICKETS_READ_ASSIGNED not in permissions:
        query = query.where(Ticket.created_by_id == user.id)
    return query


def get_ticket(db: Session, user: User, ticket_id: int) -> Ticket:
    ticket = db.scalar(ticket_query(db, user).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return ticket


def _same_request(ticket: Ticket, payload: TicketCreate) -> Ticket:
    if (ticket.network_id, ticket.summary, ticket.description) != (payload.network_id, payload.summary, payload.description):
        raise HTTPException(status_code=409, detail="La clave de solicitud ya se utilizó con otros datos.")
    return ticket


async def create_ticket(db: Session, user: User, payload: TicketCreate,
                        monitoring: MonitoringService, settings: Settings) -> Ticket:
    authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
    existing = db.scalar(select(Ticket).where(Ticket.created_by_id == user.id, Ticket.request_key == str(payload.request_key)))
    if existing:
        return _same_request(existing, payload)
    snapshot = await network_status(db, user, payload.network_id, monitoring, settings)
    authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
    ticket = Ticket(network_id=payload.network_id, created_by_id=user.id, request_key=str(payload.request_key),
                    summary=payload.summary, description=payload.description, network_snapshot=snapshot.model_dump(mode="json"))
    db.add(ticket)
    try:
        db.flush()
        db.add(TicketEvent(ticket_id=ticket.id, actor_id=user.id, status="open", note="Ticket creado por el solicitante."))
        db.add(SupportAudit(actor_id=user.id, network_id=payload.network_id, action="ticket.created"))
        db.commit()
    except IntegrityError:
        db.rollback()
        authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
        existing = db.scalar(select(Ticket).where(Ticket.created_by_id == user.id, Ticket.request_key == str(payload.request_key)))
        if existing:
            return _same_request(existing, payload)
        raise HTTPException(status_code=409, detail="No se pudo guardar el ticket. Reintenta la misma solicitud.") from None
    db.refresh(ticket)
    return ticket


TRANSITIONS = {
    "open": {"in_progress", "resolved"},
    "in_progress": {"open", "resolved"},
    "resolved": {"in_progress", "closed"},
    "closed": {"open"},
}


def update_ticket(db: Session, user: User, ticket_id: int, payload: TicketUpdate) -> Ticket:
    ticket = get_ticket(db, user, ticket_id)
    permissions = effective_permissions(user)
    if Permission.TICKETS_MANAGE not in permissions:
        authorize(db, user, Permission.TICKETS_MANAGE_ASSIGNED, ticket.network_id)
    if payload.version != ticket.version:
        raise HTTPException(status_code=409, detail="El ticket cambió; vuelve a cargarlo.")
    if payload.status not in TRANSITIONS[ticket.status]:
        raise HTTPException(status_code=409, detail="Transición de estado no permitida.")
    result = db.execute(update(Ticket).where(Ticket.id == ticket_id, Ticket.version == payload.version)
                        .values(status=payload.status, version=payload.version + 1, updated_at=datetime.now(timezone.utc)),
                        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El ticket cambió; vuelve a cargarlo.")
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=user.id, status=payload.status, note=payload.note))
    db.add(SupportAudit(actor_id=user.id, network_id=ticket.network_id, action="ticket.status_changed"))
    db.commit()
    db.refresh(ticket)
    return ticket

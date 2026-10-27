from app.core.errors import Unauthenticated, AccessDenied, NotFound, Conflict
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.core.config import Settings
from app.monitoring.service import MonitoringService
from app.networks.access import accessible_network_ids
from app.networks.access import authorize
from app.networks.diagnostics import network_status
from app.networks.audit import record_audit
from .models import Ticket, TicketEvent
from .schemas import TicketCreate, TicketUpdate, TicketRead, TicketDetail, TicketEventRead


def _ticket_query(db: Session, user: User):
    db.expire_all()
    if not user.is_active:
        raise Unauthenticated("Usuario inactivo.")
    permissions = effective_permissions(user)
    query = select(Ticket)
    if Permission.TICKETS_READ in permissions:
        return query
    if Permission.TICKETS_READ_OWN not in permissions and Permission.TICKETS_READ_ASSIGNED not in permissions:
        raise AccessDenied("Permiso insuficiente para consultar tickets.")
    query = query.where(Ticket.network_id.in_(accessible_network_ids(db, user)))
    if Permission.TICKETS_READ_ASSIGNED not in permissions:
        query = query.where(Ticket.created_by_id == user.id)
    return query


def _get_ticket(db: Session, user: User, ticket_id: int) -> Ticket:
    ticket = db.scalar(_ticket_query(db, user).where(Ticket.id == ticket_id))
    if ticket is None:
        raise NotFound("Ticket no encontrado.")
    return ticket


def _same_request(ticket: Ticket, payload: TicketCreate) -> Ticket:
    if (ticket.network_id, ticket.summary, ticket.description) != (payload.network_id, payload.summary, payload.description):
        raise Conflict("La clave de solicitud ya se utilizó con otros datos.")
    return ticket


async def create_ticket(db: Session, user: User, payload: TicketCreate,
                        monitoring: MonitoringService, settings: Settings) -> TicketRead:
    authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
    existing = db.scalar(select(Ticket).where(Ticket.created_by_id == user.id, Ticket.request_key == str(payload.request_key)))
    if existing:
        return TicketRead.model_validate(_same_request(existing, payload))
    snapshot = await network_status(db, user, payload.network_id, monitoring, settings)
    authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
    ticket = Ticket(network_id=payload.network_id, created_by_id=user.id, request_key=str(payload.request_key),
                    summary=payload.summary, description=payload.description, network_snapshot=snapshot.model_dump(mode="json"))
    db.add(ticket)
    try:
        db.flush()
        db.add(TicketEvent(ticket_id=ticket.id, actor_id=user.id, status="open", note="Ticket creado por el solicitante."))
        record_audit(db, user.id, payload.network_id, "ticket.created")
        db.commit()
    except IntegrityError:
        db.rollback()
        authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
        existing = db.scalar(select(Ticket).where(Ticket.created_by_id == user.id, Ticket.request_key == str(payload.request_key)))
        if existing:
            return TicketRead.model_validate(_same_request(existing, payload))
        raise Conflict("No se pudo guardar el ticket. Reintenta la misma solicitud.") from None
    db.refresh(ticket)
    return TicketRead.model_validate(ticket)


TRANSITIONS = {
    "open": {"in_progress", "resolved"},
    "in_progress": {"open", "resolved"},
    "resolved": {"in_progress", "closed"},
    "closed": {"open"},
}


def update_ticket(db: Session, user: User, ticket_id: int, payload: TicketUpdate) -> TicketRead:
    ticket = _get_ticket(db, user, ticket_id)
    permissions = effective_permissions(user)
    if Permission.TICKETS_MANAGE not in permissions:
        authorize(db, user, Permission.TICKETS_MANAGE_ASSIGNED, ticket.network_id)
    if payload.version != ticket.version:
        raise Conflict("El ticket cambió; vuelve a cargarlo.")
    if payload.status not in TRANSITIONS[ticket.status]:
        raise Conflict("Transición de estado no permitida.")
    result = db.execute(update(Ticket).where(Ticket.id == ticket_id, Ticket.version == payload.version)
                        .values(status=payload.status, version=payload.version + 1, updated_at=datetime.now(timezone.utc)),
                        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("El ticket cambió; vuelve a cargarlo.")
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=user.id, status=payload.status, note=payload.note))
    record_audit(db, user.id, ticket.network_id, "ticket.status_changed")
    db.commit()
    db.refresh(ticket)
    return TicketRead.model_validate(ticket)


def list_tickets(db: Session, user: User, *, limit: int = 50, offset: int = 0,
                 network_id: int | None = None, status: str | None = None) -> list[TicketRead]:
    query = _ticket_query(db, user)
    if network_id is not None:
        query = query.where(Ticket.network_id == network_id)
    if status is not None:
        query = query.where(Ticket.status == status)
    rows = db.scalars(query.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(limit).offset(offset)).all()
    return [TicketRead.model_validate(row) for row in rows]


def ticket_detail(db: Session, user: User, ticket_id: int) -> TicketDetail:
    ticket = _get_ticket(db, user, ticket_id)
    events = db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.id)).all()
    return TicketDetail(**TicketRead.model_validate(ticket).model_dump(),
                        events=[TicketEventRead.model_validate(event) for event in events])


def list_ticket_summaries(db: Session, user: User, network_ids: set[int]) -> list[dict]:
    """Contrato del chat: autorizar primero y devolver datos mínimos, nunca ORM."""
    rows = db.scalars(_ticket_query(db, user).where(Ticket.network_id.in_(network_ids))
                      .order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(5)).all()
    return [TicketRead.model_validate(row).model_dump(mode="json", include={
        "id", "network_id", "summary", "status", "version", "updated_at"
    }) for row in rows]

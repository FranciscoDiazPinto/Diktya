from app.core.errors import Unauthenticated, AccessDenied, NotFound, Conflict, RateLimited
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.access import require_user_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.core.config import Settings
from app.core.errors import InvalidInput
from app.monitoring.alerts import device_brief
from app.monitoring.service import MonitoringService
from app.networks.access import accessible_network_ids
from app.networks.access import authorize
from app.networks.diagnostics import network_status
from app.networks.audit import record_audit
from .criticality import attention_due
from .models import Notification, Ticket, TicketEvent
from .notifications import enqueue
from .schemas import (DeliveryRead, TicketAssign, TicketComment, TicketCreate, TicketCriticalityUpdate, TicketDetail,
                      TicketEventRead, TicketManualCreate, TicketRead, TicketUpdate)


def _ticket_query(db: Session, user: User):
    db.expire_all()
    if not user.is_active:
        raise Unauthenticated("Usuario inactivo.")
    permissions = effective_permissions(user)
    query = select(Ticket)
    if Permission.TICKETS_READ in permissions:
        return query
    conditions = []
    if Permission.TICKETS_READ_OWN in permissions or Permission.TICKETS_READ_ASSIGNED in permissions:
        scoped = Ticket.network_id.in_(accessible_network_ids(db, user))
        if Permission.TICKETS_READ_ASSIGNED not in permissions:
            scoped = scoped & (Ticket.created_by_id == user.id)
        conditions.append(scoped)
    # Infraestructura: el equipo técnico la gestiona y el supervisor la consulta.
    if Permission.TICKETS_READ_ASSIGNED in permissions or Permission.MONITORING_READ in permissions:
        conditions.append(Ticket.network_id.is_(None))
    if not conditions:
        raise AccessDenied("Permiso insuficiente para consultar tickets.")
    return query.where(or_(*conditions))


def _require_manage(db: Session, user: User, ticket: Ticket) -> None:
    permissions = effective_permissions(user)
    if Permission.TICKETS_MANAGE in permissions:
        return
    if ticket.network_id is None:
        require_user_permission(db, user, Permission.TICKETS_MANAGE_ASSIGNED)
    else:
        authorize(db, user, Permission.TICKETS_MANAGE_ASSIGNED, ticket.network_id)


def _apply(db: Session, ticket: Ticket, version: int, **values) -> None:
    """Escritura con control de versión; un cambio ajeno entre medio la rechaza."""
    try:
        result = db.execute(update(Ticket).where(Ticket.id == ticket.id, Ticket.version == version)
                            .values(version=version + 1, updated_at=datetime.now(timezone.utc), **values),
                            execution_options={"synchronize_session": False})
    except IntegrityError:
        db.rollback()
        raise Conflict("Ya existe otro ticket abierto para este incidente.") from None
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("El ticket cambió; vuelve a cargarlo.")


def _get_ticket(db: Session, user: User, ticket_id: int) -> Ticket:
    ticket = db.scalar(_ticket_query(db, user).where(Ticket.id == ticket_id))
    if ticket is None:
        raise NotFound("Ticket no encontrado.")
    return ticket


def _same_request(ticket: Ticket, payload: TicketCreate | TicketManualCreate) -> Ticket:
    if (ticket.network_id, ticket.summary, ticket.description) != (payload.network_id, payload.summary, payload.description):
        raise Conflict("La clave de solicitud ya se utilizó con otros datos.")
    return ticket


def _enforce_creation_quota(db: Session, user: User, settings: Settings) -> None:
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent = db.scalar(select(func.count()).select_from(Ticket).where(Ticket.created_by_id == user.id, Ticket.created_at >= since))
    if recent >= settings.ticket_create_limit_per_10min:
        raise RateLimited("Demasiados tickets en poco tiempo. Espera unos minutos.")


async def create_ticket(db: Session, user: User, payload: TicketCreate,
                        monitoring: MonitoringService, settings: Settings) -> TicketRead:
    authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
    existing = db.scalar(select(Ticket).where(Ticket.created_by_id == user.id, Ticket.request_key == str(payload.request_key)))
    if existing:
        return TicketRead.model_validate(_same_request(existing, payload))
    _enforce_creation_quota(db, user, settings)
    snapshot = await network_status(db, user, payload.network_id, monitoring, settings)
    authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
    now = datetime.now(timezone.utc)
    ticket = Ticket(network_id=payload.network_id, created_by_id=user.id, request_key=str(payload.request_key),
                    summary=payload.summary, description=payload.description, network_snapshot=snapshot.model_dump(mode="json"),
                    criticality="media", attention_due_at=attention_due("media", now, settings))
    db.add(ticket)
    try:
        db.flush()
        db.add(TicketEvent(ticket_id=ticket.id, actor_id=user.id, status="open", note="Ticket creado por el solicitante."))
        record_audit(db, user.id, payload.network_id, "ticket.created")
        enqueue(db, ticket, "created", settings, now)
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


async def create_manual_ticket(db: Session, user: User, payload: TicketManualCreate,
                               monitoring: MonitoringService, settings: Settings) -> TicketRead:
    permissions = effective_permissions(user)
    if Permission.TICKETS_MANAGE not in permissions:
        require_user_permission(db, user, Permission.TICKETS_MANAGE_ASSIGNED)
    key = str(payload.request_key)
    # La idempotencia no entrega un ticket que la cuenta ya no puede consultar.
    existing = db.scalar(_ticket_query(db, user).where(Ticket.created_by_id == user.id, Ticket.request_key == key))
    if existing:
        return TicketRead.model_validate(_same_request(existing, payload))
    _enforce_creation_quota(db, user, settings)
    snapshot = None
    if payload.network_id is not None:
        authorize(db, user, Permission.TICKETS_CREATE_OWN, payload.network_id)
        snapshot = (await network_status(db, user, payload.network_id, monitoring, settings)).model_dump(mode="json")
    if payload.device_id is not None:
        require_user_permission(db, user, Permission.MONITORING_READ)
    device = device_brief(db, payload.device_id) if payload.device_id else None
    if payload.device_id and device is None:
        raise InvalidInput("El dispositivo indicado no existe en el inventario.")
    now = datetime.now(timezone.utc)
    ticket = Ticket(network_id=payload.network_id, created_by_id=user.id, request_key=key, summary=payload.summary,
                    description=payload.description, network_snapshot=snapshot, source="manual",
                    criticality=payload.criticality, device_id=payload.device_id,
                    device_name=device[0] if device else None,
                    attention_due_at=attention_due(payload.criticality, now, settings))
    db.add(ticket)
    try:
        db.flush()
        db.add(TicketEvent(ticket_id=ticket.id, actor_id=user.id, status="open", note="Ticket creado por el equipo técnico."))
        if ticket.network_id is not None:
            record_audit(db, user.id, ticket.network_id, "ticket.created")
        enqueue(db, ticket, "created", settings, now)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("No se pudo guardar el ticket. Reintenta la misma solicitud.") from None
    db.refresh(ticket)
    return TicketRead.model_validate(ticket)


TRANSITIONS = {
    "open": {"in_progress", "resolved"},
    "in_progress": {"open", "resolved"},
    "resolved": {"in_progress", "closed"},
    "closed": {"open"},
}
MIN_RESOLUTION_CHARS = 5


def update_ticket(db: Session, user: User, ticket_id: int, payload: TicketUpdate, settings: Settings) -> TicketRead:
    ticket = _get_ticket(db, user, ticket_id)
    _require_manage(db, user, ticket)
    if payload.version != ticket.version:
        raise Conflict("El ticket cambió; vuelve a cargarlo.")
    if payload.status not in TRANSITIONS[ticket.status]:
        raise Conflict("Transición de estado no permitida.")
    values: dict = {"status": payload.status}
    if payload.status in {"resolved", "closed"}:
        if payload.status == "closed" and len(payload.note) < MIN_RESOLUTION_CHARS:
            raise InvalidInput("Indica el motivo de resolución para cerrar el ticket.")
        values["resolution"] = payload.note
    elif payload.status == "open":
        values["attention_due_at"] = attention_due(ticket.criticality, datetime.now(timezone.utc), settings)
        values["resolution"] = None
    _apply(db, ticket, payload.version, **values)
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=user.id, status=payload.status, note=payload.note))
    if ticket.network_id is not None:
        record_audit(db, user.id, ticket.network_id, "ticket.status_changed")
    db.commit()
    db.refresh(ticket)
    return TicketRead.model_validate(ticket)


def assign_ticket(db: Session, user: User, ticket_id: int, payload: TicketAssign) -> TicketRead:
    """Autoasignación: un técnico toma el ticket para sí."""
    ticket = _get_ticket(db, user, ticket_id)
    _require_manage(db, user, ticket)
    if ticket.status == "closed":
        raise Conflict("Un ticket cerrado no se puede asignar.")
    _apply(db, ticket, payload.version, assignee_id=user.id)
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=user.id, kind="assignment", status=ticket.status,
                       note="Ticket asignado a un técnico."))
    db.commit()
    db.refresh(ticket)
    return TicketRead.model_validate(ticket)


def comment_ticket(db: Session, user: User, ticket_id: int, payload: TicketComment) -> TicketDetail:
    ticket = _get_ticket(db, user, ticket_id)
    _require_manage(db, user, ticket)
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=user.id, kind="comment", status=ticket.status, note=payload.note))
    db.commit()
    return ticket_detail(db, user, ticket_id)


def set_criticality(db: Session, user: User, ticket_id: int, payload: TicketCriticalityUpdate,
                    settings: Settings) -> TicketRead:
    ticket = _get_ticket(db, user, ticket_id)
    _require_manage(db, user, ticket)
    now = datetime.now(timezone.utc)
    _apply(db, ticket, payload.version, criticality=payload.criticality, needs_review=False,
           attention_due_at=attention_due(payload.criticality, now, settings))
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=user.id, kind="criticality", status=ticket.status,
                       note=f"Criticidad ajustada a {payload.criticality}: {payload.note}"[:1000]))
    db.commit()
    db.refresh(ticket)
    return TicketRead.model_validate(ticket)


def list_tickets(db: Session, user: User, *, limit: int = 50, offset: int = 0, network_id: int | None = None,
                 status: str | None = None, criticality: str | None = None,
                 assignee_id: int | None = None) -> list[TicketRead]:
    query = _ticket_query(db, user)
    if criticality is not None:
        query = query.where(Ticket.criticality == criticality)
    if assignee_id is not None:
        query = query.where(Ticket.assignee_id == assignee_id)
    if network_id is not None:
        query = query.where(Ticket.network_id == network_id)
    if status is not None:
        query = query.where(Ticket.status == status)
    rows = db.scalars(query.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(limit).offset(offset)).all()
    return [TicketRead.model_validate(row) for row in rows]


def ticket_detail(db: Session, user: User, ticket_id: int) -> TicketDetail:
    ticket = _get_ticket(db, user, ticket_id)
    events = db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.id)).all()
    permissions = effective_permissions(user)
    deliveries = []
    if Permission.TICKETS_MANAGE in permissions or Permission.TICKETS_MANAGE_ASSIGNED in permissions:
        rows = db.scalars(select(Notification).where(Notification.ticket_id == ticket_id).order_by(Notification.id))
        deliveries = [DeliveryRead.model_validate(row) for row in rows]
    return TicketDetail(**TicketRead.model_validate(ticket).model_dump(), deliveries=deliveries,
                        events=[TicketEventRead.model_validate(event) for event in events])


def list_ticket_summaries(db: Session, user: User, network_ids: set[int]) -> list[dict]:
    """Contrato del chat: autorizar primero y devolver datos mínimos, nunca ORM."""
    rows = db.scalars(_ticket_query(db, user).where(Ticket.network_id.in_(network_ids))
                      .order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(5)).all()
    return [TicketRead.model_validate(row).model_dump(mode="json", include={
        "id", "network_id", "summary", "status", "version", "updated_at"
    }) for row in rows]

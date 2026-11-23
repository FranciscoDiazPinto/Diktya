"""Ámbito de lectura compartido por tickets y avisos internos."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.core.errors import AccessDenied, Unauthenticated
from app.networks.access import accessible_network_ids

from .models import Ticket


def visible_tickets(db: Session, user: User):
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

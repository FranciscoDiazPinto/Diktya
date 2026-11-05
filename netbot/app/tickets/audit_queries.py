"""Lectura pública de transiciones; excluye notas, evidencias y conversaciones."""
from sqlalchemy import literal
from app.core.audit import audit_projection
from .models import TicketEvent as Event


def audit_queries():
    return [audit_projection("tickets", Event.id, Event.created_at, Event.actor_id,
                             literal("ticket.") + Event.kind, Event.status, "ticket", Event.ticket_id)]

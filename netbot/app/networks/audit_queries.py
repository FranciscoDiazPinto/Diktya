"""Lectura pública de eventos de soporte, sin contactos ni credenciales."""
from app.core.audit import audit_projection
from .support_models import SupportAudit as Event


def audit_queries():
    return [audit_projection("support", Event.id, Event.created_at, Event.actor_id,
                             Event.action, "success", "network", Event.network_id)]

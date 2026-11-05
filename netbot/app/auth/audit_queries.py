"""Lectura pública de metadatos de identidad, sin details ni tokens."""
from app.core.audit import audit_projection
from .models import AuthAuditEvent as Event


def audit_queries():
    return [audit_projection("auth", Event.id, Event.created_at, Event.actor_id,
                             Event.action, Event.outcome, "user", Event.target_id)]

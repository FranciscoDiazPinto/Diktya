"""Proyección mínima común; cada dominio sigue siendo dueño de sus consultas."""
from sqlalchemy import String, cast, literal, select


def audit_projection(source, event_id, occurred_at, actor_id, action, outcome, resource_type, resource_id, *, snapshot=False):
    def value(item):
        return literal(item) if isinstance(item, str) else item
    return select(
        literal(source).label("source"), cast(event_id, String).label("event_id"),
        occurred_at.label("occurred_at"), actor_id.label("actor_id"),
        value(action).label("action"), value(outcome).label("outcome"),
        literal(resource_type).label("resource_type"), cast(resource_id, String).label("resource_id"),
        literal(snapshot).label("snapshot"),
    )

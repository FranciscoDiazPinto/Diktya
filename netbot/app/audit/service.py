"""Consulta unificada de proyecciones públicas; sin acceso a tablas ajenas."""
import csv
from io import StringIO
from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session
from app.auth.access import require_user_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.audit_queries import audit_queries as auth_queries
from app.networks.audit_queries import audit_queries as support_queries
from app.tickets.audit_queries import audit_queries as ticket_queries
from app.changes.audit_queries import audit_queries as change_queries
from app.core.errors import InvalidInput
from .schemas import AuditEntry, AuditFilters, AuditPage

EXPORT_LIMIT = 5000


def _query(filters):
    entries = union_all(*auth_queries(), *support_queries(), *ticket_queries(), *change_queries()).subquery()
    conditions = []
    for field in ("actor_id", "source", "action", "outcome"):
        value = getattr(filters, field)
        if value is not None:
            conditions.append(getattr(entries.c, field) == value)
    if filters.since:
        conditions.append(entries.c.occurred_at >= filters.since)
    if filters.until:
        conditions.append(entries.c.occurred_at <= filters.until)
    return select(entries).where(*conditions).order_by(
        entries.c.occurred_at.desc(), entries.c.source, entries.c.event_id, entries.c.action)


def list_entries(db: Session, actor: User, filters: AuditFilters, *, limit=50, offset=0) -> AuditPage:
    require_user_permission(db, actor, Permission.AUDIT_READ)
    if not 1 <= limit <= 100 or offset < 0:
        raise InvalidInput("Paginación inválida.")
    query = _query(filters)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = [AuditEntry.model_validate(dict(row)) for row in db.execute(query.limit(limit).offset(offset)).mappings()]
    return AuditPage(items=items, total=total, limit=limit, offset=offset)


def _safe_cell(value):
    text = "" if value is None else str(value)
    # Neutraliza fórmulas incluso si comienzan después de espacios o controles.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def export_csv(db: Session, actor: User, filters: AuditFilters) -> str:
    require_user_permission(db, actor, Permission.AUDIT_READ)
    rows = db.execute(_query(filters).limit(EXPORT_LIMIT + 1)).mappings().all()
    if len(rows) > EXPORT_LIMIT:
        raise InvalidInput("La exportación supera 5000 registros. Reduce el rango de fechas o agrega filtros.")
    output = StringIO(newline="")
    writer = csv.writer(output)
    fields = list(AuditEntry.model_fields)
    writer.writerow(fields)
    for row in rows:
        entry = AuditEntry.model_validate(dict(row)).model_dump(mode="json")
        writer.writerow([_safe_cell(entry[field]) for field in fields])
    return "\ufeff" + output.getvalue()

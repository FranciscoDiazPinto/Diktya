"""Cola durable de trabajos: contrato público para el agente de cambios.

Los planes confirmados viven en las tablas de este módulo; el worker solo recibe
identificadores y nunca consulta estas tablas directamente.
"""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.audit import record_event

from .models import DeviceRestartPlan, SsidPlan, SsidVlanChangePlan

KINDS = {"ssid": SsidPlan, "vlan": SsidVlanChangePlan, "restart": DeviceRestartPlan}


def confirmed_ids(db: Session, kind: str, limit: int = 20) -> list[str]:
    """Aprobaciones pendientes de ejecución, la más antigua primero."""
    model = KINDS[kind]
    return list(db.scalars(select(model.id).where(model.status == "confirmed",
                                                 model.expires_at > datetime.now(timezone.utc))
                           .order_by(model.confirmed_at).limit(limit)))


def interrupted_ids(db: Session, kind: str, before: datetime, limit: int = 20) -> list[str]:
    """Trabajos que quedaron `executing` tras una interrupción del worker."""
    model = KINDS[kind]
    return list(db.scalars(select(model.id).where(model.status == "executing", model.execution_started_at < before)
                           .limit(limit)))


def expire_approvals(db: Session, now: datetime) -> int:
    """Retira aprobaciones vencidas de la cola, sin tocar trabajos ya iniciados."""
    count = 0
    for kind, model in KINDS.items():
        rows = db.execute(update(model).where(model.status == 'confirmed', model.expires_at <= now)
                          .values(status='expired').returning(model.id, model.owner_id),
                          execution_options={'synchronize_session': False}).all()
        for plan_id, owner in rows:
            record_event(db, 'change.approval.expired', actor_id=owner, source='worker',
                         details={'kind': kind, 'plan_id': plan_id})
        count += len(rows)
    return count


def reject_approval(db: Session, kind: str, plan_id: str, reason: str) -> None:
    """Solo un rechazo definitivo y previo a ejecutar invalida la aprobación."""
    model = KINDS[kind]
    owner = db.scalar(update(model).where(model.id == plan_id, model.status == 'confirmed')
                      .values(status='rejected').returning(model.owner_id),
                      execution_options={'synchronize_session': False})
    if owner is not None:
        record_event(db, 'change.approval.rejected', actor_id=owner, source='worker', outcome='denied',
                     details={'kind': kind, 'plan_id': plan_id, 'reason': reason})

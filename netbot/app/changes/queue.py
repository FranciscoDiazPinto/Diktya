"""Cola durable de trabajos: contrato público para el agente de cambios.

Los planes confirmados viven en las tablas de este módulo; el worker solo recibe
identificadores y nunca consulta estas tablas directamente.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DeviceRestartPlan, SsidPlan, SsidVlanChangePlan

KINDS = {"ssid": SsidPlan, "vlan": SsidVlanChangePlan, "restart": DeviceRestartPlan}


def confirmed_ids(db: Session, kind: str, limit: int = 20) -> list[str]:
    """Aprobaciones pendientes de ejecución, la más antigua primero."""
    model = KINDS[kind]
    return list(db.scalars(select(model.id).where(model.status == "confirmed")
                           .order_by(model.confirmed_at).limit(limit)))


def interrupted_ids(db: Session, kind: str, before: datetime, limit: int = 20) -> list[str]:
    """Trabajos que quedaron `executing` tras una interrupción del worker."""
    model = KINDS[kind]
    return list(db.scalars(select(model.id).where(model.status == "executing", model.confirmed_at < before)
                           .limit(limit)))

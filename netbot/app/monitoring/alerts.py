"""Ciclo de vida de alertas: una condición activa, una alerta.

Cada ciclo informa las condiciones vigentes de las categorías que pudo evaluar: las que
siguen se actualizan sin duplicarse, las nuevas se crean y las que desaparecieron se
resuelven solas. Lo no observado no resuelve nada: una fuente caída no "normaliza" un AP.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MonitoredDevice, MonitoringAlert
from .schemas import AlertSeverity

SEVERITY_RANK = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1}


@dataclass(frozen=True, slots=True)
class AlertCondition:
    key: str
    category: str
    severity: AlertSeverity
    message: str
    device_id: int | None = None
    device_name: str | None = None


def device_conditions(db: Session, source: str) -> list[AlertCondition]:
    conditions = []
    for row in db.scalars(select(MonitoredDevice).where(MonitoredDevice.source == source)):
        key = f"device:{row.id}"
        if row.missing_since is not None:
            conditions.append(AlertCondition(f"{key}:missing", "device", AlertSeverity.WARNING,
                                             f"{row.name} dejó de aparecer en el inventario de {source}.",
                                             row.id, row.name))
        elif row.state == "offline":
            conditions.append(AlertCondition(f"{key}:offline", "device", AlertSeverity.CRITICAL,
                                             f"{row.name} está fuera de línea.", row.id, row.name))
        elif row.state == "degraded":
            conditions.append(AlertCondition(f"{key}:degraded", "device", AlertSeverity.WARNING,
                                             f"{row.name} perdió parte de su conexión.", row.id, row.name))
    return conditions


def sync_alerts(db: Session, *, source: str, categories: set[str], conditions: list[AlertCondition],
                now: datetime) -> None:
    """Aplica el resultado de un ciclo. No confirma: el dueño es el colector."""
    active = {
        alert.dedup_key: alert
        for alert in db.scalars(select(MonitoringAlert).where(
            MonitoringAlert.source == source,
            MonitoringAlert.category.in_(categories),
            MonitoringAlert.resolved_at.is_(None),
        ))
    }
    for condition in conditions:
        alert = active.pop(condition.key, None)
        if alert is None:
            alert = MonitoringAlert(dedup_key=condition.key, source=source, category=condition.category,
                                    detected_at=now)
            db.add(alert)
        alert.severity = condition.severity.value
        alert.severity_rank = SEVERITY_RANK[condition.severity]
        alert.message = condition.message
        alert.device_id = condition.device_id
        alert.device_name = condition.device_name
        alert.last_seen_at = now
    for alert in active.values():
        alert.resolved_at = now


@dataclass(frozen=True, slots=True)
class Incident:
    """Contrato público hacia tickets. La Épica 004 puede construirlo sin `alert_id`."""

    key: str
    incident_type: str
    message: str
    detected_at: datetime
    source: str
    severity: str = AlertSeverity.WARNING.value
    alert_id: int | None = None
    device_id: int | None = None
    device_name: str | None = None
    device_type: str | None = None


def active_incidents(db: Session, sources: list[str]) -> list[Incident]:
    rows = db.execute(
        select(MonitoringAlert, MonitoredDevice.device_type)
        .outerjoin(MonitoredDevice, MonitoredDevice.id == MonitoringAlert.device_id)
        .where(MonitoringAlert.resolved_at.is_(None), MonitoringAlert.source.in_(sources))
        .order_by(MonitoringAlert.id)
    ).all()
    return [
        Incident(key=alert.dedup_key, incident_type=f"{alert.category}_{alert.dedup_key.rsplit(':', 1)[-1]}",
                 message=alert.message, detected_at=alert.detected_at, source=alert.source,
                 severity=alert.severity, alert_id=alert.id, device_id=alert.device_id,
                 device_name=alert.device_name, device_type=device_type)
        for alert, device_type in rows
    ]


def unresolved_keys(db: Session, keys: Iterable[str]) -> set[str]:
    return set(db.scalars(select(MonitoringAlert.dedup_key).where(
        MonitoringAlert.dedup_key.in_(list(keys)), MonitoringAlert.resolved_at.is_(None))))


def device_brief(db: Session, device_id: int) -> tuple[str, str] | None:
    """(nombre, tipo) del dispositivo, para asociarlo a un ticket manual."""
    row = db.get(MonitoredDevice, device_id)
    return (row.name, row.device_type) if row else None

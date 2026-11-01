"""Ciclo de vida de alertas: una condición activa, una alerta.

Cada ciclo informa las condiciones vigentes de las categorías que pudo evaluar: las que
siguen se actualizan sin duplicarse, las nuevas se crean y las que desaparecieron se
resuelven solas. Lo no observado no resuelve nada: una fuente caída no "normaliza" un AP.
"""

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

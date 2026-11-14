"""Ciclo de vida de alertas: una condición activa, una alerta.

Cada ciclo informa las condiciones vigentes de las categorías que pudo evaluar: las que
siguen se actualizan sin duplicarse, las nuevas se crean y las que desaparecieron se
resuelven solas. Lo no observado no resuelve nada: una fuente caída no "normaliza" un AP.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .maintenance import devices_in_maintenance
from .models import MonitoredDevice, MonitoredSsid, MonitoredVlan, MonitoringAlert
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


def device_conditions(db: Session, source: str, now: datetime | None = None) -> list[AlertCondition]:
    """Un equipo en mantenimiento declarado no alerta por su caída esperada."""
    maintenance = devices_in_maintenance(db, source, now) if now is not None else set()
    conditions = []
    for row in db.scalars(select(MonitoredDevice).where(MonitoredDevice.source == source)):
        if row.external_id in maintenance:
            continue
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


def inactive_conditions(db: Session, source: str, category: str, now: datetime,
                        window: timedelta) -> list[AlertCondition]:
    """VLAN o SSID que dejó de estar activo de forma inesperada.

    Se alerta la transición (desapareció del inventario o pasó a deshabilitado), acotada a
    una ventana: una baja deliberada no debe quedar como alerta permanente.
    """
    model, label = (MonitoredSsid, "El SSID") if category == "ssid" else (MonitoredVlan, "La VLAN")
    conditions = []
    for row in db.scalars(select(model).where(model.source == source)):
        name = row.name or (f"tag {row.tag}" if category == "vlan" else row.external_id)
        if row.missing_since is not None:
            if now - row.missing_since <= window:
                conditions.append(AlertCondition(f"{category}:{row.id}:missing", category, AlertSeverity.WARNING,
                                                 f"{label} {name} dejó de aparecer en el inventario de {source}."))
        elif row.disabled_since is not None and now - row.disabled_since <= window:
            conditions.append(AlertCondition(f"{category}:{row.id}:disabled", category, AlertSeverity.WARNING,
                                             f"{label} {name} quedó deshabilitado en {source}."))
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

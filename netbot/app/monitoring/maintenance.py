"""Ventanas de mantenimiento: contrato público para los trabajos que reinician equipos.

Quien abre la ventana es dueño de la transacción. Una ventana siempre vence: si el
trabajo que la abrió se interrumpe, la supresión de alertas termina sola.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MaintenanceWindow


def open_window(db: Session, *, source: str, external_id: str, until: datetime, reason: str,
                now: datetime) -> None:
    """No confirma. Reemplaza una ventana vigente del mismo equipo en vez de acumularlas."""
    close_window(db, source=source, external_id=external_id, now=now)
    db.add(MaintenanceWindow(source=source, external_id=external_id, reason=reason[:160],
                             starts_at=now, ends_at=until))


def close_window(db: Session, *, source: str, external_id: str, now: datetime) -> None:
    """No confirma. Cerrar una ventana inexistente no es un error."""
    for window in db.scalars(select(MaintenanceWindow).where(
            MaintenanceWindow.source == source, MaintenanceWindow.external_id == external_id,
            MaintenanceWindow.closed_at.is_(None))):
        window.closed_at = now


def devices_in_maintenance(db: Session, source: str, now: datetime) -> set[str]:
    return set(db.scalars(select(MaintenanceWindow.external_id).where(
        MaintenanceWindow.source == source, MaintenanceWindow.closed_at.is_(None),
        MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at > now)))

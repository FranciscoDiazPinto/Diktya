"""Puente de incidentes: cualquier agente escala hacia tickets por un único contrato.

Cambios no importa tickets: recibe este puerto por inyección. El ticket y la traza del
agente se agregan a la transacción de quien reporta, de modo que el resultado del trabajo
y su escalamiento se confirman juntos o no se confirman.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.monitoring.alerts import Incident
from app.tickets.agent import open_incident

from .events import Event, record

_SEVERITY = {"rollback_failed": "critical", "agent_failed": "critical"}


def incident_reporter(settings: Settings, agent_id: str):
    """Devuelve el puerto (db, tipo, clave, mensaje) -> None para el agente indicado."""

    def report(db: Session, incident_type: str, key: str, message: str) -> None:
        now = datetime.now(timezone.utc)
        open_incident(db, Incident(key=key[:255], incident_type=incident_type, message=message, detected_at=now,
                                   source=agent_id, severity=_SEVERITY.get(incident_type, "warning")),
                      settings, now)
        record(db, Event(agent_id=agent_id, event_type=f"incident.{incident_type}", correlation_id=key,
                         outcome="failure", resource_type="incident", resource_id=key, detail=message))

    return report

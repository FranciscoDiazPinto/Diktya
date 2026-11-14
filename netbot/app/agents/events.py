"""Contrato de eventos entre agentes (versión 1).

Un evento identifica al agente emisor y se correlaciona con la conversación, el cambio o
el incidente que lo originó. No transporta secretos, cuerpos externos ni contactos: solo
identificadores y un detalle breve redactado por el servidor.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentEvent

SCHEMA_VERSION = 1
AGENTS = ("orchestrator", "monitoring", "tickets", "changes", "housekeeping", "chat")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Event:
    agent_id: str
    event_type: str
    correlation_id: str
    outcome: str = "success"
    resource_type: str | None = None
    resource_id: str | None = None
    detail: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.agent_id not in AGENTS:
            raise ValueError(f"Agente desconocido: {self.agent_id}")


def record(db: Session, event: Event) -> bool:
    """Agrega la traza a la transacción del llamante. Deduplica por event_id."""
    if db.scalar(select(AgentEvent.id).where(AgentEvent.event_id == event.event_id)) is not None:
        return False
    db.add(AgentEvent(
        event_id=event.event_id, correlation_id=event.correlation_id[:64], agent_id=event.agent_id,
        event_type=event.event_type[:64], resource_type=event.resource_type,
        resource_id=event.resource_id[:160] if event.resource_id else None, outcome=event.outcome[:16],
        detail=event.detail[:255] if event.detail else None, occurred_at=event.occurred_at))
    return True

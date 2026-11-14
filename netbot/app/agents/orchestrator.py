"""Orquestador: registra agentes, ejecuta sus ciclos aislados y deja trazabilidad.

Cada agente corre en su propia tarea. Una excepción se registra, se reintenta en el ciclo
siguiente y nunca detiene a los demás ni al backend. Tras varios fallos seguidos se abre
un incidente sin depender del agente caído. El estado se persiste para que el dashboard
lo muestre aunque el agente corra en otro proceso (p. ej. el worker de cambios).
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.access import require_user_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings

from .events import Event, record
from .incidents import incident_reporter
from .models import AgentEvent, AgentState

logger = logging.getLogger("netbot.agents")

FAILURES_BEFORE_INCIDENT = 3
STATE_WRITE_SECONDS = 10  # un ciclo sano no escribe en la base más seguido que esto
STALLED_INTERVALS = 4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass
class _Registration:
    agent_id: str
    cycle: Callable[[], Awaitable[None]]
    interval: float
    initial_delay: float = 0.0
    failures: int = 0
    last_write: datetime | None = None


class Orchestrator:
    def __init__(self, session_factory: Callable[[], Session], settings: Settings, *,
                 clock: Callable[[], datetime] = _utcnow) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self._agents: dict[str, _Registration] = {}
        self._tasks: list[asyncio.Task] = []
        self._report = incident_reporter(settings, "orchestrator")

    def register(self, agent_id: str, cycle: Callable[[], Awaitable[None]], interval: float, *,
                 initial_delay: float = 0.0) -> None:
        """Enruta el trabajo periódico de `agent_id` a su ciclo. Un agente, un registro."""
        if agent_id in self._agents:
            raise ValueError(f"Agente ya registrado: {agent_id}")
        self._agents[agent_id] = _Registration(agent_id, cycle, interval, initial_delay)

    @property
    def agents(self) -> list[str]:
        return list(self._agents)

    async def run_once(self, agent_id: str) -> bool:
        """Ejecuta un ciclo aislado. Devuelve si terminó sin error."""
        registration = self._agents[agent_id]
        error = None
        try:
            await registration.cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # la falla de un agente no se propaga a los demás
            error = type(exc).__name__
            logger.exception("Falló el ciclo del agente %s", agent_id)
        try:
            self._persist(registration, error)
        except Exception:  # sin base tampoco se detiene el resto
            logger.exception("No se pudo registrar el estado del agente %s", agent_id)
        return error is None

    def _persist(self, registration: _Registration, error: str | None) -> None:
        now = self._clock()
        previous_failures = registration.failures
        registration.failures = previous_failures + 1 if error else 0
        changed = bool(error) or previous_failures > 0
        due = registration.last_write is None or (now - registration.last_write).total_seconds() >= STATE_WRITE_SECONDS
        if not changed and not due:
            return
        with self._session_factory() as db:
            state = db.get(AgentState, registration.agent_id)
            if state is None:
                state = AgentState(agent_id=registration.agent_id, runs=0, consecutive_failures=0)
                db.add(state)
            state.interval_seconds = max(1, round(registration.interval))
            state.runs = (state.runs or 0) + 1
            state.last_run_at = now
            state.consecutive_failures = registration.failures
            if error:
                state.status, state.last_error_at, state.last_error = "failed", now, error[:160]
                if registration.failures in (1, FAILURES_BEFORE_INCIDENT):
                    record(db, Event(agent_id="orchestrator", event_type="agent.cycle_failed",
                                     correlation_id=f"agent:{registration.agent_id}", outcome="failure",
                                     resource_type="agent", resource_id=registration.agent_id, detail=error))
                if registration.failures == FAILURES_BEFORE_INCIDENT:
                    self._report(db, "agent_failed", f"agent:{registration.agent_id}:failed",
                                 f"El agente {registration.agent_id} falló {FAILURES_BEFORE_INCIDENT} ciclos seguidos.")
            else:
                state.status, state.last_success_at = "ok", now
                if previous_failures:
                    record(db, Event(agent_id="orchestrator", event_type="agent.recovered",
                                     correlation_id=f"agent:{registration.agent_id}", resource_type="agent",
                                     resource_id=registration.agent_id))
            db.commit()
        registration.last_write = now

    async def _loop(self, registration: _Registration) -> None:
        await asyncio.sleep(registration.initial_delay)
        while True:
            await self.run_once(registration.agent_id)
            await asyncio.sleep(registration.interval)

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._loop(r), name=f"agent:{r.agent_id}") for r in self._agents.values()]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        try:
            with self._session_factory() as db:
                for agent_id in self._agents:
                    state = db.get(AgentState, agent_id)
                    if state is not None:
                        state.status = "stopped"
                db.commit()
        except Exception:
            logger.exception("No se pudo registrar la detención de los agentes")


# --------------------------------------------------------------------------- lecturas


def agent_status(db: Session, actor: User, *, now: datetime | None = None) -> list[dict]:
    """Estado de los agentes para el dashboard. `stalled` = dejó de informar ciclos."""
    require_user_permission(db, actor, Permission.MONITORING_READ)
    now = now or _utcnow()
    result = []
    for state in db.scalars(select(AgentState).order_by(AgentState.agent_id)):
        last_run = _aware(state.last_run_at)
        status = state.status
        if status in ("ok", "failed") and last_run is not None and \
                (now - last_run).total_seconds() > max(state.interval_seconds, STATE_WRITE_SECONDS) * STALLED_INTERVALS:
            status = "stalled"
        result.append({"agent_id": state.agent_id, "status": status, "interval_seconds": state.interval_seconds,
                       "runs": state.runs, "consecutive_failures": state.consecutive_failures,
                       "last_run_at": last_run, "last_success_at": _aware(state.last_success_at),
                       "last_error_at": _aware(state.last_error_at), "last_error": state.last_error})
    return result


def agent_events(db: Session, actor: User, *, correlation_id: str | None = None, agent_id: str | None = None,
                 limit: int = 50, offset: int = 0) -> list[dict]:
    """Trazas por agente. Solo administración: describen incidentes y trabajos de toda la red."""
    require_user_permission(db, actor, Permission.AUDIT_READ)
    statement = select(AgentEvent).order_by(AgentEvent.occurred_at.desc(), AgentEvent.id.desc())
    if correlation_id:
        statement = statement.where(AgentEvent.correlation_id == correlation_id)
    if agent_id:
        statement = statement.where(AgentEvent.agent_id == agent_id)
    return [{"event_id": e.event_id, "correlation_id": e.correlation_id, "agent_id": e.agent_id,
             "event_type": e.event_type, "resource_type": e.resource_type, "resource_id": e.resource_id,
             "outcome": e.outcome, "detail": e.detail, "occurred_at": _aware(e.occurred_at)}
            for e in db.scalars(statement.limit(limit).offset(offset))]

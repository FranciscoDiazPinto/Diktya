"""Agente de tickets: convierte alertas en tickets, los sigue y entrega los correos.

Tarea en memoria de una instancia, no una cola durable. Cada paso es independiente: un
fallo se registra y el ciclo siguiente continúa. Los correos pendientes persisten en la
base, así que sobreviven a un reinicio.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import active_staff
from app.core.config import Settings
from app.monitoring.alerts import Incident, active_incidents, unresolved_keys
from app.monitoring.inventory import configured_sources

from .criticality import attention_due, attention_minutes, classify, criticality_rules, raised
from .models import Ticket, TicketEvent
from .notifications import Mailer, due_emails, enqueue, register_attempt

logger = logging.getLogger("netbot.tickets.agent")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _system_event(db: Session, ticket: Ticket, kind: str, note: str) -> None:
    db.add(TicketEvent(ticket_id=ticket.id, actor_id=None, kind=kind, status=ticket.status, note=note[:1000]))


def open_incident(db: Session, incident: Incident, settings: Settings, now: datetime, *, affected: int = 1) -> Ticket:
    """Punto de entrada de cualquier incidente. Idempotente: un incidente, un ticket sin cerrar.

    No confirma: el dueño es quien llama. La Épica 004 puede usarlo para verificación o
    rollback fallidos sin depender de una alerta de monitoreo.
    """
    ticket = db.scalar(select(Ticket).where(Ticket.incident_key == incident.key, Ticket.status != "closed"))
    if ticket is not None:
        if incident.alert_id is not None and ticket.alert_id != incident.alert_id:
            ticket.alert_id = incident.alert_id
            ticket.version += 1
            if ticket.status == "resolved":
                ticket.status, ticket.resolution = "open", None
                ticket.attention_due_at = attention_due(ticket.criticality, now, settings)
                _system_event(db, ticket, "incident", f"El incidente volvió a ocurrir: {incident.message}")
                enqueue(db, ticket, "reopened", settings, now)
            else:
                _system_event(db, ticket, "incident", f"Nuevo evento del incidente: {incident.message}")
        return ticket

    level, review = classify(incident.incident_type, device_type=incident.device_type, affected=affected,
                             settings=settings)
    ticket = Ticket(
        source="incident", summary=incident.message[:160], description=incident.message,
        criticality=level, needs_review=review, incident_key=incident.key, incident_type=incident.incident_type,
        alert_id=incident.alert_id, device_id=incident.device_id, device_name=incident.device_name,
        attention_due_at=attention_due(level, now, settings),
        evidence={"alert_id": incident.alert_id, "source": incident.source, "severity": incident.severity,
                  "detected_at": incident.detected_at.isoformat(), "simulated": incident.source == "mock"},
    )
    db.add(ticket)
    db.flush()
    _system_event(db, ticket, "status", "Ticket creado automáticamente desde un incidente."
                  + (" Clasificación no concluyente: requiere revisión manual." if review else ""))
    enqueue(db, ticket, "created", settings, now)
    return ticket


class TicketAgent:
    def __init__(self, session_factory: Callable[[], Session], settings: Settings, mailer: Mailer | None,
                 *, clock: Callable[[], datetime] = _utcnow) -> None:
        criticality_rules(settings), attention_minutes(settings)  # configuración inválida: falla al arrancar
        self._session_factory = session_factory
        self._settings = settings
        self._mailer = mailer
        self._clock = clock

    async def run_forever(self) -> None:
        while True:
            await self.run_cycle()
            await asyncio.sleep(self._settings.ticket_agent_interval_seconds)

    async def run_cycle(self) -> None:
        for step in (self.sync_incidents, self.escalate_overdue, self.deliver_emails):
            try:
                await step()
            except Exception:  # un paso caído no detiene a los demás ni al backend
                logger.exception("Falló el paso %s del agente de tickets", step.__name__)

    async def sync_incidents(self) -> None:
        now = self._clock()
        with self._session_factory() as db:
            incidents = active_incidents(db, configured_sources(self._settings))
            for incident in incidents:
                affected = sum(1 for item in incidents if item.incident_type == incident.incident_type)
                try:
                    with db.begin_nested():
                        open_incident(db, incident, self._settings, now, affected=affected)
                except IntegrityError:
                    logger.info("Incidente %s ya tiene ticket", incident.key)
            tracked = db.scalars(select(Ticket).where(
                Ticket.source == "incident", Ticket.alert_id.isnot(None),
                Ticket.status.in_(("open", "in_progress")))).all()
            active = unresolved_keys(db, [ticket.incident_key for ticket in tracked])
            for ticket in tracked:
                if ticket.incident_key not in active:
                    ticket.status = "resolved"
                    ticket.resolution = "La condición que originó el incidente se normalizó."
                    ticket.version += 1
                    _system_event(db, ticket, "status", f"{ticket.resolution} Pendiente de cierre por un técnico.")
                    enqueue(db, ticket, "resolved", self._settings, now)
            db.commit()

    async def escalate_overdue(self) -> None:
        now = self._clock()
        with self._session_factory() as db:
            overdue = db.scalars(select(Ticket).where(Ticket.status == "open", Ticket.assignee_id.is_(None),
                                                      Ticket.attention_due_at.isnot(None))).all()
            for ticket in overdue:
                if _aware(ticket.attention_due_at) > now:
                    continue
                previous, ticket.criticality = ticket.criticality, raised(ticket.criticality)
                ticket.escalations += 1
                ticket.version += 1
                ticket.attention_due_at = attention_due(ticket.criticality, now, self._settings)
                note = "Superó el tiempo máximo sin atención; se reenvió la notificación."
                if ticket.criticality != previous:
                    note += f" Criticidad escalada de {previous} a {ticket.criticality}."
                _system_event(db, ticket, "escalation", note)
                enqueue(db, ticket, "escalated", self._settings, now)
            db.commit()

    async def deliver_emails(self) -> None:
        if self._mailer is None:
            return
        now = self._clock()
        with self._session_factory() as db:
            contacts = {person["id"]: person["email"] for person in active_staff(db)}
            for row in due_emails(db, now):
                email = contacts.get(row.user_id)
                if email is None:  # desactivado o sin rol desde que se encoló
                    row.status = "cancelled"
                    db.commit()
                    continue
                error = None
                try:
                    await asyncio.to_thread(self._mailer, email, row.title, row.body)
                except Exception as exc:  # incluye errores SMTP y de red
                    error = exc
                    logger.warning("Falló el correo de la notificación %s (%s)", row.id, type(exc).__name__)
                register_attempt(row, error, self._settings, self._clock())
                db.commit()

"""Ciclo de vida y tarea de muestreo de esta instancia; no es una cola durable."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from fastapi import FastAPI
from app.bootstrap import initialize_database
from app.core.config import get_settings
from app.agents.orchestrator import Orchestrator
from app.auth.service import purge_expired_sessions
from app.changes.service import expire_due as expire_vlan_reservations
from app.core.database import SessionLocal
from app.chat.guest import expire_guest_sessions, sessions
from app.networks.email_recovery import purge_expired as purge_wifi_recoveries
from app.monitoring.factory import build_monitoring_service, build_unifi_source
from app.monitoring.inventory import InventoryCollector
from app.tickets.agent import TicketAgent
from app.tickets.notifications import build_mailer
from app.monitoring.service import MonitoringService

logger = logging.getLogger("netbot")

async def sample_traffic_forever(service: MonitoringService, interval: float) -> None:
    while True:
        try:
            await service.sample_traffic()
        except Exception:
            logger.exception("Falló el muestreo de tráfico")
        await asyncio.sleep(interval)


def purge_expired_data() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        purge_expired_sessions(db, now)
        purge_wifi_recoveries(db, now)
        expire_vlan_reservations(db, now)
        db.commit()


async def housekeeping_cycle() -> None:
    await asyncio.to_thread(purge_expired_data)


def build_orchestrator(settings, collector: InventoryCollector | None, ticket_agent: TicketAgent | None) -> Orchestrator:
    """Enruta cada trabajo periódico a su agente. El worker de cambios corre en su propio proceso."""
    orchestrator = Orchestrator(SessionLocal, settings)
    if collector is not None:
        orchestrator.register("monitoring", collector.run_cycle, 1.0)
    if ticket_agent is not None:
        orchestrator.register("tickets", ticket_agent.run_cycle, settings.ticket_agent_interval_seconds)
    # La limpieza no compite con el arranque: su primer ciclo espera un intervalo.
    orchestrator.register("housekeeping", housekeeping_cycle, 300.0, initial_delay=300.0)
    return orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    settings = get_settings()
    service = build_monitoring_service(settings)
    app.state.monitoring_service = service
    sampler = asyncio.create_task(
        sample_traffic_forever(service, settings.monitoring_sample_interval_seconds)
    )
    guest_expiry = asyncio.create_task(expire_guest_sessions())
    unifi = build_unifi_source(settings)
    collector = None
    if settings.monitoring_collector_enabled:
        sources = [service.provider, *([unifi] if unifi else [])]
        collector = InventoryCollector(sources, SessionLocal, settings)
    ticket_agent = TicketAgent(SessionLocal, settings, build_mailer(settings)) if settings.ticket_agent_enabled else None
    orchestrator = build_orchestrator(settings, collector, ticket_agent)
    orchestrator.start()
    try:
        yield
    finally:
        await orchestrator.stop()
        if unifi:
            await unifi.aclose()
        guest_expiry.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await guest_expiry
        sessions.clear()
        sampler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler
        await service.aclose()

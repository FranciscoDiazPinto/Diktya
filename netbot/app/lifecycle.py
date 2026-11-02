"""Ciclo de vida y tarea de muestreo de esta instancia; no es una cola durable."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI
from app.bootstrap import initialize_database
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.chat.guest import expire_guest_sessions, sessions
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
        collector = asyncio.create_task(InventoryCollector(sources, SessionLocal, settings).run_forever())
    ticket_agent = None
    if settings.ticket_agent_enabled:
        ticket_agent = asyncio.create_task(TicketAgent(SessionLocal, settings, build_mailer(settings)).run_forever())
    try:
        yield
    finally:
        if ticket_agent:
            ticket_agent.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticket_agent
        if collector:
            collector.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await collector
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

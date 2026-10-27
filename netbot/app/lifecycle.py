"""Ciclo de vida y tarea de muestreo de esta instancia; no es una cola durable."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI
from app.bootstrap import initialize_database
from app.core.config import get_settings
from app.monitoring.factory import build_monitoring_service
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
    service = build_monitoring_service(get_settings())
    app.state.monitoring_service = service
    sampler = asyncio.create_task(
        sample_traffic_forever(service, get_settings().monitoring_sample_interval_seconds)
    )
    try:
        yield
    finally:
        sampler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler
        await service.aclose()

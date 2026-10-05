from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.monitoring.factory import build_monitoring_service
from app.monitoring.router import router as monitoring_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    service = build_monitoring_service(get_settings())
    app.state.monitoring_service = service
    try:
        yield
    finally:
        await service.aclose()


app = FastAPI(title="Netbot", version="0.1.0", lifespan=lifespan)
app.include_router(monitoring_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.auth.models import Role, User
from app.auth.routes import admin_router, router
from app.auth.roles import DEFAULT_ROLES
from app.auth.security import hash_password
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine

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
app.include_router(router)
app.include_router(admin_router)


@app.on_event("startup")
def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for role_name, role_definition in DEFAULT_ROLES.items():
            if not db.scalar(select(Role).where(Role.name == role_name.value)):
                db.add(Role(name=role_name.value, description=role_definition.description))
        db.commit()
        if settings.admin_email and settings.admin_password and not db.scalar(
            select(User).where(User.email == settings.admin_email.lower())
        ):
            admin_role = db.scalar(select(Role).where(Role.name == "admin"))
            db.add(User(email=settings.admin_email.lower(), hashed_password=hash_password(settings.admin_password), roles=[admin_role]))
            db.commit()
    finally:
        db.close()


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}

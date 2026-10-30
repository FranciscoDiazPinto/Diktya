"""Registro HTTP: los dominios no importan este módulo de composición."""
from fastapi import FastAPI
from app.changes.router import router as changes_router
from app.auth.routes import admin_router, router
from app.chat.router import router as chat_router
from app.chat.guest_router import router as guest_router
from app.networks.router import router as networks_router, admin_router as networks_admin_router
from app.networks.support_router import router as support_router, admin_router as support_admin_router
from app.tickets.router import router as tickets_router
from app.monitoring.router import router as monitoring_router

def register_routes(app: FastAPI) -> None:
    app.include_router(monitoring_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(guest_router, prefix="/api/v1")
    app.include_router(networks_router, prefix="/api/v1")
    app.include_router(networks_admin_router)
    app.include_router(support_router, prefix="/api/v1")
    app.include_router(support_admin_router)
    app.include_router(tickets_router, prefix="/api/v1")
    app.include_router(changes_router, prefix="/api/v1")
    app.include_router(router)
    app.include_router(admin_router)

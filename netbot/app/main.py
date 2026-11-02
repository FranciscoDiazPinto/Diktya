"""Punto de entrada HTTP. No contiene reglas de negocio ni preparación de tablas."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.http_errors import register_error_handlers
from app.lifecycle import lifespan
from app.routes import register_routes
from app.auth.audit import AuthAuditMiddleware
from app.core.request_security import RequestSecurityMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Netbot", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestSecurityMiddleware, path=settings.security_rate_limit_path, secret=settings.jwt_secret_key)
    app.add_middleware(CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(AuthAuditMiddleware)
    register_error_handlers(app)
    register_routes(app)

    @app.get("/health", tags=["health"])
    def health_check():
        return {"status": "ok"}
    return app


app = create_app()

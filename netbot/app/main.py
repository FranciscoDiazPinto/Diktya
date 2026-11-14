"""Punto de entrada HTTP. No contiene reglas de negocio ni preparación de tablas."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.http_errors import register_error_handlers
from app.lifecycle import lifespan
from app.routes import register_routes
from app.auth.audit import AuthAuditMiddleware
from app.core.keys import derive_key
from app.core.request_security import RequestSecurityMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    # El contrato completo de la API no se publica en producción.
    public_docs = settings.environment != "production"
    app = FastAPI(title="Netbot", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs" if public_docs else None, redoc_url="/redoc" if public_docs else None,
                  openapi_url="/openapi.json" if public_docs else None)
    app.add_middleware(RequestSecurityMiddleware, path=settings.security_rate_limit_path,
        secret=derive_key(settings.jwt_secret_key, 'rate-limit'), json_limit=settings.max_json_body_bytes,
        upload_limits={'/api/v1/changes/csv-imports': settings.csv_max_bytes + 1024,
                       '/api/v1/changes/ssid-plans/csv': settings.csv_max_bytes * 3,
                       '/api/v1/monitoring/plans': settings.monitoring_plan_max_bytes + 1024},
        budgets={'chat-guest': settings.guest_llm_daily_budget, 'chat-user': settings.chat_llm_daily_budget})
    app.add_middleware(CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
        allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Guest-Session"])
    app.add_middleware(AuthAuditMiddleware, path=settings.security_rate_limit_path,
                       secret=derive_key(settings.jwt_secret_key, 'rate-limit'))
    register_error_handlers(app)
    register_routes(app)

    @app.get("/health", tags=["health"])
    def health_check():
        return {"status": "ok"}
    return app


app = create_app()

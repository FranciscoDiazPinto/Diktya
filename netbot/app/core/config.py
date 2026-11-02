"""Configuración de la aplicación a partir de variables de entorno."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    app_name: str = "Netbot"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./netbot.db"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Monitoreo (Épica 002) ---
    # Fuente real por defecto. "mock" solo se usa si se pide de forma explícita.
    monitoring_provider: Literal["mock", "opnsense"] = "opnsense"
    monitoring_cache_ttl_seconds: float = Field(5.0, ge=0, le=60)
    monitoring_stale_retention_seconds: float = Field(300.0, ge=0, le=86400)
    monitoring_mock_scenario: Literal["healthy", "degraded", "outage"] = "healthy"
    firewall_log_fetch_limit: int = Field(500, ge=1, le=5000)
    # Muestreo de tráfico en segundo plano para el gráfico del dashboard.
    monitoring_sample_interval_seconds: float = Field(5.0, gt=0)
    monitoring_history_seconds: float = Field(3600.0, gt=0)
    # Ciclo que persiste inventario, alertas y disponibilidad.
    monitoring_collector_enabled: bool = True
    monitoring_inventory_interval_seconds: float = Field(30.0, ge=1)
    monitoring_inventory_max_age_seconds: float = Field(60.0, gt=0)
    monitoring_retry_max_seconds: float = Field(300.0, ge=1)
    monitoring_source_failure_threshold: int = Field(2, ge=1)
    monitoring_availability_window_hours: int = Field(24, ge=1, le=720)
    monitoring_plan_max_bytes: int = Field(5_242_880, ge=1024, le=20_971_520)

    # Redes cuyo acceso se publica deliberadamente sin cuenta. Vacío = ninguna.
    guest_wifi_network_ids: list[int] = Field(default_factory=list)

    # Aprovisionamiento independiente del inventario de solo lectura.
    unifi_inventory_mode: Literal["disabled", "mock", "api"] = "disabled"
    unifi_api_base_url: str | None = None
    unifi_write_enabled: bool = False
    unifi_api_contract: str | None = None
    ssid_security_profiles_json: SecretStr | None = None

    # --- Chatbot ---
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str | None = None
    openrouter_timeout_seconds: float = Field(20.0, gt=0)
    chat_max_message_chars: int = Field(2000, ge=1)
    chat_max_history_chars: int = Field(8000, ge=0)
    chat_max_history_turns: int = Field(8, ge=0)
    chat_max_tool_rounds: int = Field(3, ge=1)
    chat_max_output_tokens: int = Field(600, ge=1)

    # Secretos Wi-Fi fuera de la BD y del contexto LLM. Claves por referencia opaca.
    wifi_access_credentials_json: SecretStr | None = None
    # Sitio que sirve la instancia actual de monitoreo OPNsense/mock.
    monitoring_site_id: str | None = None
    network_status_max_age_seconds: float = Field(60.0, gt=0)

    # --- Tickets y notificaciones (Épica 005) ---
    ticket_agent_enabled: bool = True
    ticket_agent_interval_seconds: float = Field(15.0, ge=1)
    # JSON {"tipo_de_incidente": "baja|media|alta|critica"} que sustituye reglas por defecto.
    ticket_criticality_rules_json: Optional[str] = None
    # Dispositivos afectados a la vez desde los que se sube un nivel de criticidad.
    ticket_mass_incident_devices: int = Field(3, ge=2)
    # JSON {"critica": 15, ...}: minutos máximos sin atención por criticidad.
    ticket_attention_minutes_json: Optional[str] = None
    notification_email_max_attempts: int = Field(5, ge=1, le=20)
    notification_email_retry_seconds: float = Field(60.0, ge=1)
    public_app_url: str = "http://localhost:5173"
    # Correo: sin SMTP_HOST solo se notifica dentro de la aplicación.
    smtp_host: Optional[str] = None
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_username: Optional[str] = None
    smtp_password: Optional[SecretStr] = None
    smtp_from: Optional[str] = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(10.0, gt=0)

    csv_max_bytes: int = Field(1_048_576, ge=1024, le=10_485_760)
    csv_max_rows: int = Field(500, ge=1, le=1000)
    csv_preview_ttl_seconds: int = Field(900, ge=30, le=86400)
    csv_inventory_max_age_seconds: float = Field(60.0, gt=0, le=3600)

    # --- OPNsense ---
    # Se acepta OPNSENSE_BASE_URL (nombre actual de .env.example) y OPNSENSE_API_URL.
    opnsense_base_url: Optional[str] = Field(
        None, validation_alias=AliasChoices("OPNSENSE_BASE_URL", "OPNSENSE_API_URL")
    )
    opnsense_api_key: Optional[SecretStr] = None
    opnsense_api_secret: Optional[SecretStr] = None
    opnsense_verify_tls: bool = True
    opnsense_ca_bundle: Optional[str] = None
    opnsense_timeout_seconds: float = Field(5.0, gt=0)
    opnsense_connect_timeout_seconds: float = Field(3.0, gt=0)
    opnsense_dhcp_backend: Literal["dnsmasq", "kea"] = "dnsmasq"
    # El log de pf entrega hora local sin zona: hay que declarar la del firewall.
    opnsense_timezone: str = "UTC"

    # --- UniFi Network (API oficial, solo lectura) ---
    unifi_enabled: bool = True
    unifi_transport: Literal["direct", "connector"] = "direct"
    unifi_base_url: Optional[str] = None  # direct: https://<consola>
    unifi_console_id: Optional[str] = None  # connector: ID en Site Manager
    unifi_api_key: Optional[SecretStr] = None
    unifi_site: Optional[str] = None  # UUID o internalReference; opcional con un solo sitio
    unifi_verify_tls: bool = True
    unifi_ca_bundle: Optional[str] = None
    unifi_timeout_seconds: float = Field(10.0, gt=0)
    unifi_connect_timeout_seconds: float = Field(3.0, gt=0)

    @field_validator(
        "opnsense_base_url",
        "opnsense_api_key",
        "opnsense_api_secret",
        "opnsense_ca_bundle",
        "unifi_base_url",
        "unifi_console_id",
        "unifi_api_key",
        "unifi_site",
        "unifi_ca_bundle",
        "ticket_criticality_rules_json",
        "ticket_attention_minutes_json",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        "openrouter_api_key",
        "openrouter_model",
        "wifi_access_credentials_json",
        "monitoring_site_id",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        # .env.example deja estas variables vacías ("VAR=").
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("opnsense_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("OPNSENSE_TIMEZONE debe ser una zona IANA válida") from exc
        return value

    @model_validator(mode="after")
    def _check_integration_urls(self) -> "Settings":
        """Sin credenciales la API arranca e informa la fuente como no configurada; una URL
        mal escrita, en cambio, es un error que conviene detener al inicio."""
        for name, url in (("OPNSENSE_BASE_URL", self.opnsense_base_url), ("UNIFI_BASE_URL", self.unifi_base_url)):
            if url is not None and not url.lower().startswith(("http://", "https://")):
                raise ValueError(f"{name} debe empezar con http:// o https://")
        return self

    # SQLite compartido por workers en este equipo, separado de datos de negocio.
    security_rate_limit_path: str = "netbot-rate-limits.db"

    @model_validator(mode="after")
    def _production_security(self) -> "Settings":
        if self.environment.lower() in {"production", "prod"}:
            if len(self.jwt_secret_key) < 64 or self.jwt_secret_key == "change-me-in-production":
                raise ValueError("JWT_SECRET_KEY requiere al menos 64 caracteres aleatorios")
            if not self.unifi_verify_tls or not self.opnsense_verify_tls:
                raise ValueError("Producción requiere verificación TLS")
            for url in (self.unifi_base_url, self.opnsense_base_url, self.unifi_api_base_url):
                if url and urlsplit(url).scheme.lower() != "https":
                    raise ValueError("Producción requiere HTTPS para las integraciones")
            for origin in self.cors_origins.split(","):
                if origin.strip() in {"null", "*"}:
                    raise ValueError("CORS requiere orígenes explícitos en producción")
        return self

    @property
    def opnsense_missing(self) -> list[str]:
        return [name for name, value in (
            ("OPNSENSE_BASE_URL", self.opnsense_base_url),
            ("OPNSENSE_API_KEY", self.opnsense_api_key),
            ("OPNSENSE_API_SECRET", self.opnsense_api_secret),
        ) if value is None]

    @property
    def unifi_missing(self) -> list[str]:
        target = ("UNIFI_CONSOLE_ID", self.unifi_console_id) if self.unifi_transport == "connector" \
            else ("UNIFI_BASE_URL", self.unifi_base_url)
        return [name for name, value in (target, ("UNIFI_API_KEY", self.unifi_api_key)) if value is None]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

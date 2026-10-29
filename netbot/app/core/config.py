"""Configuración de la aplicación a partir de variables de entorno."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Netbot"
    environment: str = "development"
    database_url: str = "sqlite:///./netbot.db"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,null"

    # --- Monitoreo (Épica 002) ---
    # "mock" es el valor por defecto: el entorno local no tiene hardware de red.
    monitoring_provider: Literal["mock", "opnsense"] = "mock"
    monitoring_cache_ttl_seconds: float = Field(5.0, ge=0)
    monitoring_mock_scenario: Literal["healthy", "degraded", "outage"] = "healthy"
    firewall_log_fetch_limit: int = Field(500, ge=1, le=5000)
    # Muestreo de tráfico en segundo plano para el gráfico del dashboard.
    monitoring_sample_interval_seconds: float = Field(5.0, gt=0)
    monitoring_history_seconds: float = Field(3600.0, gt=0)

    # Redes cuyo acceso se publica deliberadamente sin cuenta. Vacío = ninguna.
    guest_wifi_network_ids: list[int] = Field(default_factory=list)

    # Inventario oficial UniFi: URL completa hasta /integration/v1, sin secretos en MD.
    unifi_inventory_mode: Literal["disabled", "mock", "api"] = "disabled"
    unifi_api_base_url: str | None = None
    unifi_api_key: SecretStr | None = None
    unifi_ca_bundle: str | None = None
    unifi_write_enabled: bool = False
    unifi_api_contract: str | None = None
    ssid_security_profiles_json: SecretStr | None = None
    unifi_timeout_seconds: float = Field(10.0, gt=0, le=60)

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

    @field_validator(
        "opnsense_base_url",
        "opnsense_api_key",
        "opnsense_api_secret",
        "opnsense_ca_bundle",
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

    @model_validator(mode="after")
    def _require_opnsense_credentials(self) -> "Settings":
        if self.monitoring_provider != "opnsense":
            return self
        missing = [
            name
            for name, value in (
                ("OPNSENSE_BASE_URL", self.opnsense_base_url),
                ("OPNSENSE_API_KEY", self.opnsense_api_key),
                ("OPNSENSE_API_SECRET", self.opnsense_api_secret),
            )
            if value is None
        ]
        if missing:
            raise ValueError("MONITORING_PROVIDER=opnsense requiere definir: " + ", ".join(missing))
        if not self.opnsense_base_url.lower().startswith(("http://", "https://")):  # type: ignore[union-attr]
            raise ValueError("OPNSENSE_BASE_URL debe empezar con http:// o https://")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

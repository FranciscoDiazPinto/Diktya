"""Configuración de la aplicación a partir de variables de entorno."""

from functools import lru_cache
from typing import Literal

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
    admin_email: str | None = None
    admin_password: str | None = None

    # --- Monitoreo (Épica 002) ---
    # "mock" es el valor por defecto: el entorno local no tiene hardware de red.
    monitoring_provider: Literal["mock", "opnsense"] = "mock"
    monitoring_cache_ttl_seconds: float = Field(5.0, ge=0)
    monitoring_mock_scenario: Literal["healthy", "degraded", "outage"] = "healthy"
    firewall_log_fetch_limit: int = Field(500, ge=1, le=5000)

    # --- OPNsense ---
    # Se acepta OPNSENSE_BASE_URL (nombre actual de .env.example) y OPNSENSE_API_URL.
    opnsense_base_url: str | None = Field(
        None, validation_alias=AliasChoices("OPNSENSE_BASE_URL", "OPNSENSE_API_URL")
    )
    opnsense_api_key: SecretStr | None = None
    opnsense_api_secret: SecretStr | None = None
    opnsense_verify_tls: bool = True
    opnsense_ca_bundle: str | None = None
    opnsense_timeout_seconds: float = Field(5.0, gt=0)
    opnsense_connect_timeout_seconds: float = Field(3.0, gt=0)
    opnsense_dhcp_backend: Literal["dnsmasq", "kea"] = "dnsmasq"

    @field_validator(
        "opnsense_base_url",
        "opnsense_api_key",
        "opnsense_api_secret",
        "opnsense_ca_bundle",
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

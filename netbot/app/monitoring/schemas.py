"""Modelos internos normalizados del módulo de monitoreo.

Todos los payloads externos (OPNsense u otros) se convierten a estos modelos en
la capa de adaptadores. Ningún JSON crudo de OPNsense sale hacia los endpoints.
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, field_validator

T = TypeVar("T")


class NetbotModel(BaseModel):
    model_config = ConfigDict(frozen=True)


# --------------------------------------------------------------------------- #
# Envoltorio de respuesta y diagnóstico de la recolección
# --------------------------------------------------------------------------- #


class IssueKind(StrEnum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_SUPPORTED = "not_supported"
    TIMEOUT = "timeout"
    TLS = "tls"
    CONNECTION = "connection"
    SERVER_ERROR = "server_error"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class MonitoringStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"  # hay datos, pero falló algún componente no opcional
    UNAVAILABLE = "unavailable"  # no se pudo obtener ningún dato


class CollectionIssue(NetbotModel):
    """Incidente ocurrido al recolectar un componente (sin datos sensibles)."""

    component: str
    kind: IssueKind
    message: str
    optional: bool = False


class MonitoringResponse(NetbotModel, Generic[T]):
    status: MonitoringStatus
    source: str = Field(description="Proveedor que originó los datos: 'opnsense' o 'mock'.")
    collected_at: datetime
    data: T | None = None
    issues: list[CollectionIssue] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Sistema
# --------------------------------------------------------------------------- #


class MemoryMetrics(NetbotModel):
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    used_percent: float = Field(ge=0, le=100)


class TemperatureMetrics(NetbotModel):
    available: bool = False
    value_celsius: float | None = None


class SystemMetrics(NetbotModel):
    hostname: str | None = None
    version: str | None = None
    uptime_seconds: int | None = Field(None, ge=0)
    reference_time: datetime | None = Field(
        None, description="Hora del firewall, solo si se puede interpretar sin ambigüedad."
    )
    cpu_percent: float | None = Field(None, ge=0, le=100)
    memory: MemoryMetrics | None = None
    temperature: TemperatureMetrics = Field(default_factory=TemperatureMetrics)


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #


class LinkStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class InterfaceTraffic(NetbotModel):
    """Contadores ACUMULADOS desde el arranque (no son velocidad instantánea)."""

    bytes_in: int | None = Field(None, ge=0)
    bytes_out: int | None = Field(None, ge=0)
    packets_in: int | None = Field(None, ge=0)
    packets_out: int | None = Field(None, ge=0)
    errors_in: int | None = Field(None, ge=0)
    errors_out: int | None = Field(None, ge=0)
    collisions: int | None = Field(None, ge=0)


class InterfaceMetrics(NetbotModel):
    interface_id: str = Field(description="Identificador lógico (p. ej. 'wan', 'lan', 'opt1').")
    name: str = Field(description="Dispositivo del sistema (p. ej. 'igc0', 'igc1.20').")
    description: str | None = Field(None, description="Descripción configurada (p. ej. 'WAN').")
    status: LinkStatus = LinkStatus.UNKNOWN
    ip_addresses: list[str] = Field(default_factory=list)
    traffic: InterfaceTraffic | None = None


# --------------------------------------------------------------------------- #
# DHCP / clientes
# --------------------------------------------------------------------------- #

_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


class DhcpLease(NetbotModel):
    ip_address: IPvAnyAddress
    mac_address: str
    hostname: str | None = None
    interface: str | None = None
    expires_at: datetime | None = Field(
        None, description="Nulo si la concesión no expira (p. ej. reserva estática)."
    )
    active: bool

    @field_validator("mac_address")
    @classmethod
    def _normalize_mac(cls, value: str) -> str:
        digits = re.sub(r"[:\-.\s]", "", value).lower()
        if not _MAC_RE.match(digits):
            raise ValueError(f"MAC inválida: {value!r}")
        return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


# --------------------------------------------------------------------------- #
# Firewall
# --------------------------------------------------------------------------- #


class FirewallAction(StrEnum):
    BLOCK = "block"
    PASS = "pass"


class FirewallEvent(NetbotModel):
    timestamp: datetime
    action: FirewallAction
    interface: str | None = None
    source_ip: IPvAnyAddress
    source_port: int | None = Field(None, ge=0, le=65535)
    destination_ip: IPvAnyAddress
    destination_port: int | None = Field(None, ge=0, le=65535)
    protocol: str | None = None
    rule_id: str | None = None


class StateTableStats(NetbotModel):
    current_entries: int | None = Field(None, ge=0)
    searches: int | None = Field(None, ge=0)
    inserts: int | None = Field(None, ge=0)
    removals: int | None = Field(None, ge=0)


class FirewallStatistics(NetbotModel):
    pf_enabled: bool | None = None
    states: StateTableStats | None = None
    counters: dict[str, int] = Field(
        default_factory=dict, description="Contadores acumulados de pf (match, fragment, ...)."
    )
    packets_passed: int | None = Field(None, ge=0)
    packets_blocked: int | None = Field(None, ge=0)

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
    RATE_LIMIT = "rate_limit"
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
    source: str = Field(description="Proveedor que originó los datos: 'opnsense', 'unifi' o 'mock'.")
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


class VlanInventoryItem(NetbotModel):
    """VLAN ya creada en OPNsense, normalizada para el inventario de NetBot."""

    parent_interface: str = Field(min_length=1)
    tag: int = Field(ge=1, le=4094)
    description: str | None = None
    interface_name: str = Field(min_length=1)

class TrafficRatePoint(NetbotModel):
    """Velocidad media entre dos lecturas consecutivas de los contadores."""

    timestamp: datetime
    bytes_in_per_second: float = Field(ge=0)
    bytes_out_per_second: float = Field(ge=0)


class InterfaceTrafficHistory(NetbotModel):
    interface_id: str
    points: list[TrafficRatePoint] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# DHCP / clientes
# --------------------------------------------------------------------------- #

_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


def normalize_mac(value: str) -> str:
    digits = re.sub(r"[:\-.\s]", "", value).lower()
    if not _MAC_RE.match(digits):
        raise ValueError(f"MAC inválida: {value!r}")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


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
        return normalize_mac(value)


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


# --------------------------------------------------------------------------- #
# Inventario normalizado (HU-004)
# --------------------------------------------------------------------------- #


class DeviceType(StrEnum):
    ACCESS_POINT = "ap"
    SWITCH = "switch"
    GATEWAY = "gateway"
    FIREWALL = "firewall"
    UNKNOWN = "unknown"  # la fuente no permite clasificarlo: no se infiere


class DeviceState(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"  # adopción, actualización o preparación
    UNKNOWN = "unknown"


class InventoryDevice(NetbotModel):
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    device_type: DeviceType = DeviceType.UNKNOWN
    model: str | None = None
    mac_address: str | None = None
    ip_address: str | None = None
    state: DeviceState = DeviceState.UNKNOWN


class InventoryVlan(NetbotModel):
    external_id: str = Field(min_length=1)
    name: str | None = None
    tag: int = Field(ge=1, le=4094)
    enabled: bool | None = None


class InventorySsid(NetbotModel):
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool
    security: str | None = Field(None, description="Solo el tipo; nunca claves.")
    vlan_tag: int | None = Field(None, description="Nulo si la referencia no se pudo resolver.")


class InventorySnapshot(NetbotModel):
    """Una lectura. `None` en una colección significa "no se obtuvo" o "no aplica a la
    fuente": nunca debe interpretarse como lista vacía."""

    version: str | None = None
    devices: list[InventoryDevice] | None = None
    vlans: list[InventoryVlan] | None = None
    ssids: list[InventorySsid] | None = None


# --------------------------------------------------------------------------- #
# Lecturas de la API (salen de la base: último dato conocido)
# --------------------------------------------------------------------------- #


class OrmModel(NetbotModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class SourceHealth(OrmModel):
    source: str
    status: MonitoringStatus
    version: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    next_attempt_at: datetime | None = None
    consecutive_failures: int = 0
    last_error_kind: str | None = None
    last_error_message: str | None = None
    stale: bool = False


class DeviceRead(OrmModel):
    id: int
    source: str
    name: str
    device_type: DeviceType
    model: str | None
    mac_address: str | None
    ip_address: str | None
    state: DeviceState
    last_online_at: datetime | None = Field(description="Última vez observado en línea.")
    last_seen_at: datetime = Field(description="Última lectura válida de la fuente.")
    missing_since: datetime | None
    stale: bool = False


class VlanRead(OrmModel):
    source: str
    name: str | None
    tag: int
    enabled: bool | None
    stale: bool = False


class SsidRead(OrmModel):
    source: str
    name: str
    enabled: bool
    security: str | None
    vlan_tag: int | None
    stale: bool = False


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"


class AlertRead(OrmModel):
    id: int
    severity: AlertSeverity
    source: str
    device_id: int | None
    device_name: str | None
    message: str
    detected_at: datetime
    resolved_at: datetime | None


class DeviceDetail(DeviceRead):
    alerts: list[AlertRead] = Field(default_factory=list)


class Page(NetbotModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class InventorySummary(NetbotModel):
    access_points_total: int
    access_points_online: int
    access_points_offline: int
    vlans_active: int
    ssids_active: int
    availability_percent: float | None = Field(
        description="Tiempo en línea sobre tiempo observado; nulo sin observaciones."
    )
    availability_window_hours: int
    active_alerts: int
    last_update_at: datetime | None
    stale: bool
    sources: list[SourceHealth]


class PlanRead(OrmModel):
    id: int
    name: str
    content_type: str
    width: int
    height: int


class PlacedAccessPoint(NetbotModel):
    device_id: int
    name: str
    state: DeviceState
    x: float
    y: float


class UnplacedAccessPoint(NetbotModel):
    device_id: int
    name: str
    state: DeviceState


class PlanDetail(PlanRead):
    placed: list[PlacedAccessPoint] = Field(default_factory=list)
    unplaced: list[UnplacedAccessPoint] = Field(
        default_factory=list, description="APs sin ubicación en ningún plano («sin ubicar»)."
    )


class PlacementWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

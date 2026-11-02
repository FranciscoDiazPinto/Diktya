"""Contratos abstractos que desacoplan NetBot de cualquier fuente de datos concreta."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar, Protocol

from ..exceptions import MonitoringError, ProviderNotSupportedError
from ..schemas import (
    AccessPointMetrics,
    CollectionIssue,
    DhcpLease,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    InventorySnapshot,
    IssueKind,
    SystemMetrics,
    VlanInventoryItem,
)

T = TypeVar("T")

logger = logging.getLogger("netbot.monitoring.collect")


@dataclass(slots=True)
class CollectionResult(Generic[T]):
    """Resultado de una recolección: datos (posiblemente parciales) + incidentes.

    `data` es None solo cuando no se obtuvo nada utilizable.
    """

    data: T | None
    issues: list[CollectionIssue] = field(default_factory=list)


@dataclass(slots=True)
class Outcome:
    value: Any = None
    issue: CollectionIssue | None = None

    @property
    def ok(self) -> bool:
        return self.issue is None


async def collect(component: str, call: Awaitable[Any], *, optional: bool = False) -> Outcome:
    """Ejecuta una llamada y la convierte en valor o incidente; nunca lanza (salvo cancelación)."""
    try:
        return Outcome(value=await call)
    except ProviderNotSupportedError as exc:
        # 404 en un recurso opcional es esperable (hardware/versión): no es una alarma.
        level = logging.INFO if optional else logging.WARNING
        logger.log(level, "Componente %s no soportado: %s", component, exc.detail)
        return Outcome(issue=CollectionIssue(
            component=component, kind=exc.kind, message=exc.public_message, optional=optional))
    except MonitoringError as exc:
        logger.warning("Fallo al recolectar %s (%s): %s", component, exc.kind.value, exc.detail)
        return Outcome(issue=CollectionIssue(
            component=component, kind=exc.kind, message=exc.public_message, optional=optional))
    except Exception:  # un bug de parseo no debe tumbar el dashboard
        logger.exception("Error inesperado al recolectar %s", component)
        return Outcome(issue=CollectionIssue(
            component=component, kind=IssueKind.UNKNOWN,
            message="Error interno al procesar la respuesta de la fuente.", optional=optional))


def issues_of(*outcomes: Outcome) -> list[CollectionIssue]:
    return [o.issue for o in outcomes if o.issue is not None]


class DhcpLeaseProvider(ABC):
    """Fuente de concesiones DHCP (Dnsmasq, Kea o simulada)."""

    @abstractmethod
    async def get_leases(self) -> list[DhcpLease]:
        """Devuelve las concesiones normalizadas. Lanza MonitoringError si falla."""


class InfrastructureSource(ABC):
    """Interfaz común de las integraciones. De solo lectura: no hay métodos de escritura."""

    source: ClassVar[str]

    @abstractmethod
    async def collect_inventory(self) -> CollectionResult[InventorySnapshot]: ...

    async def aclose(self) -> None:
        """Libera recursos (conexiones HTTP, etc.)."""
        return None


class NetworkMonitoringProvider(InfrastructureSource):
    """Fuente de métricas de red. Los métodos nunca lanzan por fallos de la fuente:
    degradan a datos parciales o `data=None` e informan los incidentes."""

    @abstractmethod
    async def get_system_metrics(self) -> CollectionResult[SystemMetrics]: ...

    @abstractmethod
    async def get_interface_metrics(self) -> CollectionResult[list[InterfaceMetrics]]: ...

    @abstractmethod
    async def get_clients(self) -> CollectionResult[list[DhcpLease]]: ...

    @abstractmethod
    async def get_vlan_inventory(self) -> CollectionResult[list[VlanInventoryItem]]: ...

    @abstractmethod
    async def get_firewall_statistics(self) -> CollectionResult[FirewallStatistics]: ...

    @abstractmethod
    async def get_firewall_events(self, limit: int) -> CollectionResult[list[FirewallEvent]]: ...


class AccessPointMonitoringProvider(Protocol):
    source: str
    async def collect(self) -> CollectionResult[list[AccessPointMetrics]]: ...
    async def aclose(self) -> None: ...

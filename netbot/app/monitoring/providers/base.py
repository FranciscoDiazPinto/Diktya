"""Contratos abstractos que desacoplan NetBot de cualquier fuente de datos concreta."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Generic, TypeVar

from ..schemas import (
    CollectionIssue,
    DhcpLease,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    SystemMetrics,
)

T = TypeVar("T")


@dataclass(slots=True)
class CollectionResult(Generic[T]):
    """Resultado de una recolección: datos (posiblemente parciales) + incidentes.

    `data` es None solo cuando no se obtuvo nada utilizable.
    """

    data: T | None
    issues: list[CollectionIssue] = field(default_factory=list)


class DhcpLeaseProvider(ABC):
    """Fuente de concesiones DHCP (Dnsmasq, Kea o simulada)."""

    @abstractmethod
    async def get_leases(self) -> list[DhcpLease]:
        """Devuelve las concesiones normalizadas. Lanza MonitoringError si falla."""


class NetworkMonitoringProvider(ABC):
    """Fuente de métricas de red. Los métodos nunca lanzan por fallos de la fuente:
    degradan a datos parciales o `data=None` e informan los incidentes."""

    source: ClassVar[str]

    @abstractmethod
    async def get_system_metrics(self) -> CollectionResult[SystemMetrics]: ...

    @abstractmethod
    async def get_interface_metrics(self) -> CollectionResult[list[InterfaceMetrics]]: ...

    @abstractmethod
    async def get_clients(self) -> CollectionResult[list[DhcpLease]]: ...

    @abstractmethod
    async def get_firewall_statistics(self) -> CollectionResult[FirewallStatistics]: ...

    @abstractmethod
    async def get_firewall_events(self, limit: int) -> CollectionResult[list[FirewallEvent]]: ...

    async def aclose(self) -> None:
        """Libera recursos (conexiones HTTP, etc.)."""
        return None

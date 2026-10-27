"""Servicio de monitoreo: orquesta la recolección, agrega el estado y cachea.

- Calcula el estado del envoltorio: ok / degraded (falló algo no opcional) /
  unavailable (sin datos).
- Caché con TTL corto y "single-flight" por recurso: varios clientes del dashboard
  que consultan a la vez generan una sola ronda de llamadas al firewall.
- Historial de tráfico en memoria: `sample_traffic()` (llamado en segundo plano)
  guarda los contadores acumulados de cada interfaz y `get_traffic_history()` los
  convierte en velocidades (bytes/s) entre lecturas consecutivas.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar

from .providers.base import CollectionResult, NetworkMonitoringProvider
from .schemas import (
    CollectionIssue,
    DhcpLease,
    FirewallAction,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    InterfaceTrafficHistory,
    IssueKind,
    MonitoringResponse,
    MonitoringStatus,
    SystemMetrics,
    TrafficRatePoint,
)

logger = logging.getLogger("netbot.monitoring.service")

T = TypeVar("T")


@dataclass(slots=True)
class _TrafficSample:
    collected_at: datetime
    counters: dict[str, tuple[int, int]]  # interface_id -> (bytes_in, bytes_out)


@dataclass(slots=True)
class _CacheEntry:
    response: MonitoringResponse
    expires_at: float


class MonitoringService:
    def __init__(
        self,
        provider: NetworkMonitoringProvider,
        *,
        cache_ttl_seconds: float = 5.0,
        firewall_log_fetch_limit: int = 500,
        history_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._ttl = cache_ttl_seconds
        self._fetch_limit = firewall_log_fetch_limit
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._history_seconds = history_seconds
        self._samples: deque[_TrafficSample] = deque()

    async def aclose(self) -> None:
        await self._provider.aclose()

    # ------------------------------------------------------------------ #

    async def get_system(self) -> MonitoringResponse[SystemMetrics]:
        return await self._cached("system", self._provider.get_system_metrics)

    async def get_interfaces(self) -> MonitoringResponse[list[InterfaceMetrics]]:
        return await self._cached("interfaces", self._provider.get_interface_metrics)

    async def get_clients(self) -> MonitoringResponse[list[DhcpLease]]:
        return await self._cached("clients", self._provider.get_clients)

    async def get_firewall_stats(self) -> MonitoringResponse[FirewallStatistics]:
        return await self._cached("firewall.stats", self._provider.get_firewall_statistics)

    async def get_firewall_events(
        self, limit: int = 100, action: FirewallAction | None = None
    ) -> MonitoringResponse[list[FirewallEvent]]:
        # Se cachea la lectura completa y se filtra/recorta después: así `action`
        # y `limit` no multiplican las consultas al firewall.
        full = await self._cached(
            "firewall.events", lambda: self._provider.get_firewall_events(self._fetch_limit)
        )
        if full.data is None:
            return full
        events = [e for e in full.data if action is None or e.action == action]
        return full.model_copy(update={"data": events[:limit]})

    # ------------------------------------------------------------------ #
    # Historial de tráfico

    async def sample_traffic(self) -> None:
        """Guarda una lectura de los contadores (si es nueva) y descarta las antiguas."""
        response = await self.get_interfaces()
        if not response.data:
            return
        counters = {
            i.interface_id: (i.traffic.bytes_in, i.traffic.bytes_out)
            for i in response.data
            if i.traffic and i.traffic.bytes_in is not None and i.traffic.bytes_out is not None
        }
        if self._samples and response.collected_at <= self._samples[-1].collected_at:
            return  # lectura servida desde la caché: ya está registrada
        self._samples.append(_TrafficSample(response.collected_at, counters))
        cutoff = response.collected_at.timestamp() - self._history_seconds
        while self._samples and self._samples[0].collected_at.timestamp() < cutoff:
            self._samples.popleft()

    async def get_traffic_history(
        self, window_seconds: float = 300
    ) -> MonitoringResponse[list[InterfaceTrafficHistory]]:
        if not self._samples:
            await self.sample_traffic()
        if not self._samples:
            interfaces = await self.get_interfaces()
            return interfaces.model_copy(update={"data": None})

        cutoff = self._samples[-1].collected_at.timestamp() - window_seconds
        samples = [s for s in self._samples if s.collected_at.timestamp() >= cutoff]
        series: dict[str, list[TrafficRatePoint]] = {
            interface_id: [] for interface_id in self._samples[-1].counters
        }
        for before, after in zip(samples, samples[1:]):
            seconds = (after.collected_at - before.collected_at).total_seconds()
            for interface_id, (bytes_in, bytes_out) in after.counters.items():
                previous = before.counters.get(interface_id)
                if previous is None or seconds <= 0:
                    continue
                rate_in = (bytes_in - previous[0]) / seconds
                rate_out = (bytes_out - previous[1]) / seconds
                if rate_in < 0 or rate_out < 0:  # contador reiniciado (reboot)
                    continue
                series.setdefault(interface_id, []).append(
                    TrafficRatePoint(
                        timestamp=after.collected_at,
                        bytes_in_per_second=rate_in,
                        bytes_out_per_second=rate_out,
                    )
                )
        return MonitoringResponse(
            status=MonitoringStatus.OK,
            source=self._provider.source,
            collected_at=self._samples[-1].collected_at,
            data=[
                InterfaceTrafficHistory(interface_id=interface_id, points=points)
                for interface_id, points in series.items()
            ],
        )

    # ------------------------------------------------------------------ #

    async def _cached(
        self, key: str, loader: Callable[[], Awaitable[CollectionResult[T]]]
    ) -> MonitoringResponse[T]:
        if (hit := self._fresh(key)) is not None:
            return hit
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if (hit := self._fresh(key)) is not None:  # otro request ya lo renovó
                return hit
            response = await self._collect(key, loader)
            if self._ttl > 0:
                self._cache[key] = _CacheEntry(response, self._clock() + self._ttl)
            return response

    def _fresh(self, key: str) -> MonitoringResponse | None:
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > self._clock():
            return entry.response
        return None

    async def _collect(
        self, key: str, loader: Callable[[], Awaitable[CollectionResult[T]]]
    ) -> MonitoringResponse[T]:
        collected_at = datetime.now(timezone.utc)
        try:
            result = await loader()
        except Exception:  # un bug del proveedor no debe convertirse en un 500 opaco
            logger.exception("El proveedor falló de forma inesperada en %s", key)
            result = CollectionResult(
                data=None,
                issues=[
                    CollectionIssue(
                        component=key,
                        kind=IssueKind.UNKNOWN,
                        message="Error interno inesperado en la recolección.",
                    )
                ],
            )
        return MonitoringResponse(
            status=self._status(result),
            source=self._provider.source,
            collected_at=collected_at,
            data=result.data,
            issues=result.issues,
        )

    @staticmethod
    def _status(result: CollectionResult) -> MonitoringStatus:
        if result.data is None:
            return MonitoringStatus.UNAVAILABLE
        if any(not issue.optional for issue in result.issues):
            return MonitoringStatus.DEGRADED
        return MonitoringStatus.OK

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

from .providers.base import CollectionResult, NetworkMonitoringProvider, AccessPointMonitoringProvider
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
    VlanInventoryItem,
    TrafficRatePoint,
    AccessPointMetrics, AccessPointPage,
)

logger = logging.getLogger("netbot.monitoring.service")

T = TypeVar("T")


@dataclass(slots=True)
class _TrafficSample:
    collected_at: datetime
    counters: dict[str, tuple[int, int]]  # interface_id -> (bytes_in, bytes_out)
    acquired_at: float


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
        stale_retention_seconds: float = 300.0,
        access_points_provider: AccessPointMonitoringProvider | None = None,
    ) -> None:
        self._provider = provider
        self._access_points = access_points_provider
        self._stale_retention = stale_retention_seconds
        self._last_known: dict[str, tuple[MonitoringResponse, float]] = {}
        self._ttl = cache_ttl_seconds
        self._fetch_limit = firewall_log_fetch_limit
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._history_seconds = history_seconds
        self._samples: deque[_TrafficSample] = deque()

    async def aclose(self) -> None:
        await self._provider.aclose()
        if self._access_points is not None:
            await self._access_points.aclose()

    # ------------------------------------------------------------------ #

    async def get_system(self) -> MonitoringResponse[SystemMetrics]:
        return await self._cached("system", self._provider.get_system_metrics)

    async def get_interfaces(self) -> MonitoringResponse[list[InterfaceMetrics]]:
        return await self._cached("interfaces", self._provider.get_interface_metrics)

    async def get_clients(self) -> MonitoringResponse[list[DhcpLease]]:
        return await self._cached("clients", self._provider.get_clients)

    async def get_vlan_inventory(self) -> MonitoringResponse[list[VlanInventoryItem]]:
        return await self._cached("vlans", self._provider.get_vlan_inventory)

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

    async def get_access_points(self) -> MonitoringResponse[list[AccessPointMetrics]]:
        if self._access_points is None:
            return MonitoringResponse(status=MonitoringStatus.UNAVAILABLE,source="unifi",collected_at=datetime.now(timezone.utc),
                issues=[CollectionIssue(component="unifi",kind=IssueKind.CONFIGURATION,message="Monitoreo UniFi no configurado.")])
        return await self._cached("unifi.access_points", self._access_points.collect, source=self._access_points.source)

    async def get_access_point_page(self, limit=50, offset=0) -> MonitoringResponse[AccessPointPage]:
        response = await self.get_access_points()
        page = None if response.data is None else AccessPointPage(items=response.data[offset:offset+limit],
            total_count=len(response.data),offset=offset,limit=limit)
        return response.model_copy(update={"data":page})

    # ------------------------------------------------------------------ #
    # Historial de tráfico

    async def sample_traffic(self) -> None:
        """Guarda una lectura de los contadores (si es nueva) y descarta las antiguas."""
        response = await self.get_interfaces()
        self._append_traffic_sample(response)

    def _append_traffic_sample(self, response) -> None:
        if not response.data or response.stale:
            return
        counters = {
            i.interface_id: (i.traffic.bytes_in, i.traffic.bytes_out)
            for i in response.data
            if i.traffic and i.traffic.bytes_in is not None and i.traffic.bytes_out is not None
        }
        if self._samples and response.collected_at <= self._samples[-1].collected_at:
            return  # lectura servida desde la caché: ya está registrada
        self._samples.append(_TrafficSample(response.collected_at, counters, self._clock()))
        cutoff = response.collected_at.timestamp() - self._history_seconds
        while self._samples and self._samples[0].collected_at.timestamp() < cutoff:
            self._samples.popleft()

    async def get_traffic_history(
        self, window_seconds: float = 300
    ) -> MonitoringResponse[list[InterfaceTrafficHistory]]:
        interfaces = await self.get_interfaces()
        self._append_traffic_sample(interfaces)
        if not self._samples:
            return interfaces.model_copy(update={"data": None})
        stale = interfaces.stale or interfaces.data is None
        age = self._clock() - self._samples[-1].acquired_at
        if stale and (self._stale_retention <= 0 or age > self._stale_retention):
            return interfaces.model_copy(update={"data": None, "status":MonitoringStatus.UNAVAILABLE, "stale":False})

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
            status=MonitoringStatus.DEGRADED if stale else interfaces.status,
            source=self._provider.source,
            collected_at=self._samples[-1].collected_at,
            stale=stale, last_attempt_at=interfaces.last_attempt_at,
            issues=interfaces.issues,
            data=[
                InterfaceTrafficHistory(interface_id=interface_id, points=points)
                for interface_id, points in series.items()
            ],
        )

    # ------------------------------------------------------------------ #

    async def _cached(
        self, key: str, loader: Callable[[], Awaitable[CollectionResult[T]]], *, source: str | None = None
    ) -> MonitoringResponse[T]:
        if (hit := self._fresh(key)) is not None:
            return hit
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if (hit := self._fresh(key)) is not None:  # otro request ya lo renovó
                return hit
            response = await self._collect(key, loader, source=source)
            if response.data is not None:
                self._last_known[key] = (response, self._clock())
            elif (previous := self._last_known.get(key)) is not None:
                known, saved_at = previous
                if self._stale_retention > 0 and self._clock() - saved_at <= self._stale_retention:
                    response = known.model_copy(update={"status":MonitoringStatus.DEGRADED, "stale":True,
                        "last_attempt_at":response.collected_at, "issues":response.issues})
                else:
                    self._last_known.pop(key, None)
            if self._ttl > 0:
                self._cache[key] = _CacheEntry(response, self._clock() + self._ttl)
            return response

    def _fresh(self, key: str) -> MonitoringResponse | None:
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > self._clock():
            if not entry.response.stale:
                return entry.response
            previous = self._last_known.get(key)
            if previous and self._stale_retention > 0 and self._clock()-previous[1] <= self._stale_retention:
                return entry.response
            self._cache.pop(key, None)
        return None

    async def _collect(
        self, key: str, loader: Callable[[], Awaitable[CollectionResult[T]]], *, source: str | None = None
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
            source=source or self._provider.source,
            collected_at=collected_at,
            last_attempt_at=collected_at,
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

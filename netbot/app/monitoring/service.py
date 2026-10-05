"""Servicio de monitoreo: orquesta la recolección, agrega el estado y cachea.

- Calcula el estado del envoltorio: ok / degraded (falló algo no opcional) /
  unavailable (sin datos).
- Caché con TTL corto y "single-flight" por recurso: varios clientes del dashboard
  que consultan a la vez generan una sola ronda de llamadas al firewall.
"""

import asyncio
import logging
import time
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
    IssueKind,
    MonitoringResponse,
    MonitoringStatus,
    SystemMetrics,
)

logger = logging.getLogger("netbot.monitoring.service")

T = TypeVar("T")


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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._ttl = cache_ttl_seconds
        self._fetch_limit = firewall_log_fetch_limit
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

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

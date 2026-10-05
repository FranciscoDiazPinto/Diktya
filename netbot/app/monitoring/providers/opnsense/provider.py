"""Adaptador de monitoreo basado en la API REST de OPNsense.

Cada sección del dashboard se arma con varias llamadas independientes que se
ejecutan en paralelo. Si una falla (endpoint opcional, versión antigua, timeout...)
se registra el incidente y esa parte queda nula/`unavailable`; el resto sigue.
"""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, ClassVar

from ...exceptions import MonitoringError, ProviderNotSupportedError
from ...schemas import (
    CollectionIssue,
    DhcpLease,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    IssueKind,
    SystemMetrics,
    TemperatureMetrics,
)
from ..base import CollectionResult, DhcpLeaseProvider, NetworkMonitoringProvider
from .client import OPNsenseClient
from .mappers import (
    build_interfaces,
    parse_cpu_percent,
    parse_firewall_events,
    parse_firewall_statistics,
    parse_memory,
    parse_reference_time,
    parse_system_information,
    parse_temperature,
    parse_uptime_seconds,
)

logger = logging.getLogger("netbot.monitoring.opnsense.provider")

PATH_CPU_STREAM = "/api/diagnostics/cpu_usage/stream"
PATH_SYSTEM_RESOURCES = "/api/diagnostics/system/system_resources"
PATH_SYSTEM_INFORMATION = "/api/diagnostics/system/system_information"
PATH_SYSTEM_TIME = "/api/diagnostics/system/system_time"
PATH_SYSTEM_TEMPERATURE = "/api/diagnostics/system/system_temperature"
PATH_INTERFACES_INFO = "/api/interfaces/overview/interfaces_info"
PATH_INTERFACE_STATISTICS = "/api/diagnostics/interface/get_interface_statistics"
PATH_TRAFFIC_INTERFACE = "/api/diagnostics/traffic/interface"
PATH_FIREWALL_STATS = "/api/diagnostics/firewall/stats"
# pf_statistics exige una sección; "info" equivale a `pfctl -si` (estados y contadores).
PATH_PF_STATISTICS = "/api/diagnostics/firewall/pf_statistics/info"
PATH_FIREWALL_LOG = "/api/diagnostics/firewall/log"


@dataclass(slots=True)
class _Outcome:
    value: Any = None
    issue: CollectionIssue | None = None

    @property
    def ok(self) -> bool:
        return self.issue is None


async def _collect(component: str, call: Awaitable[Any], *, optional: bool = False) -> _Outcome:
    """Ejecuta una llamada y la convierte en valor o incidente; nunca lanza (salvo cancelación)."""
    try:
        return _Outcome(value=await call)
    except ProviderNotSupportedError as exc:
        # 404 en un recurso opcional es esperable (hardware/versión): no es una alarma.
        level = logging.INFO if optional else logging.WARNING
        logger.log(level, "Componente %s no soportado: %s", component, exc.detail)
        return _Outcome(
            issue=CollectionIssue(
                component=component, kind=exc.kind, message=exc.public_message, optional=optional
            )
        )
    except MonitoringError as exc:
        logger.warning("Fallo al recolectar %s (%s): %s", component, exc.kind.value, exc.detail)
        return _Outcome(
            issue=CollectionIssue(
                component=component, kind=exc.kind, message=exc.public_message, optional=optional
            )
        )
    except Exception:  # un bug de parseo no debe tumbar el dashboard
        logger.exception("Error inesperado al recolectar %s", component)
        return _Outcome(
            issue=CollectionIssue(
                component=component,
                kind=IssueKind.UNKNOWN,
                message="Error interno al procesar la respuesta de OPNsense.",
                optional=optional,
            )
        )


def _issues(*outcomes: _Outcome) -> list[CollectionIssue]:
    return [o.issue for o in outcomes if o.issue is not None]


class OPNsenseMonitoringProvider(NetworkMonitoringProvider):
    source: ClassVar[str] = "opnsense"

    def __init__(self, client: OPNsenseClient, dhcp: DhcpLeaseProvider) -> None:
        self._client = client
        self._dhcp = dhcp

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #

    async def get_system_metrics(self) -> CollectionResult[SystemMetrics]:
        c = self._client
        cpu, resources, info, clock, temperature = await asyncio.gather(
            _collect("system.cpu", c.stream_first_json_event(PATH_CPU_STREAM)),
            _collect("system.memory", c.get_json(PATH_SYSTEM_RESOURCES)),
            _collect("system.information", c.get_json(PATH_SYSTEM_INFORMATION)),
            _collect("system.time", c.get_json(PATH_SYSTEM_TIME)),
            _collect("system.temperature", c.get_json(PATH_SYSTEM_TEMPERATURE), optional=True),
        )
        issues = _issues(cpu, resources, info, clock, temperature)
        if not any(o.ok for o in (cpu, resources, info, clock)):
            return CollectionResult(data=None, issues=issues)

        hostname, version = parse_system_information(info.value) if info.ok else (None, None)
        data = SystemMetrics(
            hostname=hostname,
            version=version,
            uptime_seconds=parse_uptime_seconds(clock.value) if clock.ok else None,
            reference_time=parse_reference_time(clock.value) if clock.ok else None,
            cpu_percent=parse_cpu_percent(cpu.value) if cpu.ok else None,
            memory=parse_memory(resources.value) if resources.ok else None,
            temperature=parse_temperature(temperature.value)
            if temperature.ok
            else TemperatureMetrics(available=False),
        )
        return CollectionResult(data=data, issues=issues)

    async def get_interface_metrics(self) -> CollectionResult[list[InterfaceMetrics]]:
        c = self._client
        info, stats, traffic = await asyncio.gather(
            _collect("interfaces.info", c.get_json(PATH_INTERFACES_INFO)),
            # Respaldo de contadores e IPs: su ausencia no degrada la sección.
            _collect("interfaces.statistics", c.get_json(PATH_INTERFACE_STATISTICS), optional=True),
            _collect("interfaces.traffic", c.get_json(PATH_TRAFFIC_INTERFACE)),
        )
        issues = _issues(info, stats, traffic)
        if not any(o.ok for o in (info, stats, traffic)):
            return CollectionResult(data=None, issues=issues)
        interfaces = build_interfaces(
            info.value if info.ok else None,
            stats.value if stats.ok else None,
            traffic.value if traffic.ok else None,
        )
        return CollectionResult(data=interfaces, issues=issues)

    async def get_clients(self) -> CollectionResult[list[DhcpLease]]:
        outcome = await _collect("clients.dhcp", self._dhcp.get_leases())
        return CollectionResult(data=outcome.value, issues=_issues(outcome))

    async def get_firewall_statistics(self) -> CollectionResult[FirewallStatistics]:
        c = self._client
        stats, pf = await asyncio.gather(
            _collect("firewall.stats", c.get_json(PATH_FIREWALL_STATS)),
            _collect("firewall.pf_statistics", c.get_json(PATH_PF_STATISTICS)),
        )
        issues = _issues(stats, pf)
        if not (stats.ok or pf.ok):
            return CollectionResult(data=None, issues=issues)
        data = parse_firewall_statistics(
            stats.value if stats.ok else None, pf.value if pf.ok else None
        )
        return CollectionResult(data=data, issues=issues)

    async def get_firewall_events(self, limit: int) -> CollectionResult[list[FirewallEvent]]:
        outcome = await _collect(
            "firewall.log", self._client.get_json(PATH_FIREWALL_LOG, params={"limit": limit})
        )
        if not outcome.ok:
            return CollectionResult(data=None, issues=_issues(outcome))
        return CollectionResult(data=parse_firewall_events(outcome.value, limit), issues=[])

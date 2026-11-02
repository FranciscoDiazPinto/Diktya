"""Adaptador de monitoreo basado en la API REST de OPNsense.

Cada sección del dashboard se arma con varias llamadas independientes que se
ejecutan en paralelo. Si una falla (endpoint opcional, versión antigua, timeout...)
se registra el incidente y esa parte queda nula/`unavailable`; el resto sigue.
"""

import asyncio
import logging
from datetime import tzinfo
from typing import ClassVar

from ...exceptions import ProviderInvalidResponseError
from ...schemas import (
    DeviceState,
    DeviceType,
    DhcpLease,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    InventoryDevice,
    InventorySnapshot,
    InventoryVlan,
    SystemMetrics,
    TemperatureMetrics,
    VlanInventoryItem,
)
from ..base import CollectionResult, DhcpLeaseProvider, NetworkMonitoringProvider
from ..base import collect as _collect, issues_of as _issues
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
    parse_vlan_inventory,
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
# pf_statistics exige una sección; "info" equivale a `pfctl -si` (estados y contadores) e
# "interfaces" a `pfctl -vvsI`, la única con paquetes pass/block por interfaz.
PATH_PF_STATISTICS = "/api/diagnostics/firewall/pf_statistics/info"
PATH_PF_INTERFACES = "/api/diagnostics/firewall/pf_statistics/interfaces"
PATH_FIREWALL_LOG = "/api/diagnostics/firewall/log"
PATH_VLAN_SEARCH = "/api/interfaces/vlan_settings/search_item"


class OPNsenseMonitoringProvider(NetworkMonitoringProvider):
    source: ClassVar[str] = "opnsense"

    def __init__(
        self, client: OPNsenseClient, dhcp: DhcpLeaseProvider, *, log_timezone: tzinfo | None = None
    ) -> None:
        self._client = client
        self._dhcp = dhcp
        self._log_timezone = log_timezone

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

    async def get_vlan_inventory(self) -> CollectionResult[list[VlanInventoryItem]]:
        async def load() -> list[VlanInventoryItem]:
            payload = await self._client.get_json(PATH_VLAN_SEARCH)
            try:
                return parse_vlan_inventory(payload)
            except ValueError as exc:
                raise ProviderInvalidResponseError(str(exc)) from exc

        outcome = await _collect("vlans.inventory", load())
        return CollectionResult(data=outcome.value, issues=_issues(outcome))

    async def get_firewall_statistics(self) -> CollectionResult[FirewallStatistics]:
        c = self._client
        stats, pf = await asyncio.gather(
            _collect("firewall.pf_interfaces", c.get_json(PATH_PF_INTERFACES)),
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
        events = parse_firewall_events(outcome.value, limit, default_tz=self._log_timezone)
        return CollectionResult(data=events, issues=[])

    async def collect_inventory(self) -> CollectionResult[InventorySnapshot]:
        system, vlans = await asyncio.gather(self.get_system_metrics(), self.get_vlan_inventory())
        issues = [*system.issues, *vlans.issues]
        if system.data is None and vlans.data is None:
            return CollectionResult(data=None, issues=issues)
        return CollectionResult(
            data=InventorySnapshot(
                version=system.data.version if system.data else None,
                devices=None if system.data is None else [
                    InventoryDevice(
                        # La instancia es única y el hostname se puede renombrar: no sirve de ID.
                        external_id="firewall",
                        name=system.data.hostname or "OPNsense",
                        device_type=DeviceType.FIREWALL,
                        model="OPNsense",
                        state=DeviceState.ONLINE,  # acaba de responder a la API
                    )
                ],
                vlans=None if vlans.data is None else [
                    InventoryVlan(
                        external_id=f"{item.parent_interface}:{item.tag}",
                        name=item.description,
                        tag=item.tag,
                    )
                    for item in vlans.data
                ],
            ),
            issues=issues,
        )

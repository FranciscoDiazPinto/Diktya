"""Proveedor simulado para desarrollo local sin hardware de red.

Genera datos sintéticos coherentes entre sí:
- La topología (WAN + LAN + 2 VLAN de evento) es única y la comparten interfaces,
  concesiones DHCP y eventos de firewall.
- Los contadores de tráfico son acumulados y monótonos crecientes.
- El uptime avanza con el reloj real.
- Los datos son deterministas para un instante dado (semilla configurable).

Escenarios (MONITORING_MOCK_SCENARIO):
- healthy:  todo disponible.
- degraded: sin sensor de temperatura, estadísticas de firewall fallando y una VLAN caída.
- outage:   toda la fuente caída (los endpoints responden 503).
"""

import hashlib
import ipaddress
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar, Literal

from ..exceptions import (
    MonitoringError,
    ProviderConnectionError,
    ProviderNotSupportedError,
    ProviderServerError,
)
from ..schemas import (
    CollectionIssue,
    DhcpLease,
    FirewallAction,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    InterfaceTraffic,
    LinkStatus,
    MemoryMetrics,
    StateTableStats,
    SystemMetrics,
    TemperatureMetrics,
)
from .base import CollectionResult, DhcpLeaseProvider, NetworkMonitoringProvider

MockScenario = Literal["healthy", "degraded", "outage"]


@dataclass(frozen=True)
class _MockInterface:
    interface_id: str
    device: str
    description: str
    address: str  # IP/prefijo del firewall en esa red
    rate_in: int  # bytes/s recibidos por el firewall en esa interfaz
    rate_out: int  # bytes/s transmitidos

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_interface(self.address).network


WAN = _MockInterface("wan", "igc0", "WAN", "203.0.113.10/24", 2_400_000, 600_000)
LAN = _MockInterface("lan", "igc1", "LAN", "192.168.1.1/24", 20_000, 25_000)
ATTENDEES = _MockInterface("opt1", "igc1.20", "ASISTENTES", "10.20.0.1/22", 500_000, 1_900_000)
STAFF = _MockInterface("opt2", "igc1.30", "STAFF", "10.30.0.1/24", 80_000, 300_000)
TOPOLOGY: tuple[_MockInterface, ...] = (WAN, LAN, ATTENDEES, STAFF)

_AVG_PACKET_BYTES = 900
_TOTAL_MEMORY = 8 * 1024**3


def _rng(*parts: object) -> random.Random:
    # Semilla textual: determinista entre procesos (no depende de PYTHONHASHSEED).
    return random.Random(":".join(str(p) for p in parts))


def _cumulative(rate: float, elapsed: float, phase: float) -> int:
    """Acumulado monótono: la derivada es rate*(1 + 0.5*sin(..)) >= 0.5*rate."""
    return int(rate * elapsed + rate * 30 * (1 - math.cos(elapsed / 60 + phase)))


def _rule_id(label: str) -> str:
    return hashlib.md5(label.encode(), usedforsecurity=False).hexdigest()


class MockDhcpLeaseProvider(DhcpLeaseProvider):
    """Concesiones DHCP simuladas, ubicadas dentro de las subredes de la topología."""

    def __init__(self, *, seed: int = 42, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._templates = self._build_templates(seed)

    @staticmethod
    def _build_templates(seed: int) -> list[dict]:
        rng = _rng(seed, "leases")
        names = [
            "iPhone",
            "Galaxy-S23",
            "Pixel-8",
            "MacBook-Pro",
            "LAPTOP",
            "android",
            "iPad",
            "Xiaomi-13",
        ]

        def mac() -> str:
            # Bit "localmente administrado" activo: MAC aleatoria, como las de móviles modernos.
            first = rng.choice([0x02, 0x06, 0x0A, 0x0E, 0x12, 0x16, 0x1A, 0x1E])
            return ":".join(f"{b:02x}" for b in [first] + [rng.randrange(256) for _ in range(5)])

        def device_name() -> str | None:
            if rng.random() < 0.15:
                return None
            return f"{rng.choice(names)}-{rng.randrange(0x1000, 0xFFFF):x}"

        templates: list[dict] = []
        plan = [(ATTENDEES, 70, 3600, 11), (STAFF, 12, 28800, 20), (LAN, 6, 86400, 10)]
        for interface, count, lease_seconds, first_host in plan:
            for index in range(count):
                host = interface.network.network_address + first_host + index
                name = f"uap-{index + 1}" if interface is LAN else device_name()
                templates.append(
                    {
                        "ip": str(host),
                        "mac": mac(),
                        "hostname": name,
                        "interface": interface.device,
                        "lease_seconds": lease_seconds,
                        "phase": rng.randrange(lease_seconds),
                        "stale": False,
                    }
                )
        # Algunas concesiones ya vencidas (active=False) para ejercitar ese caso.
        for index in range(5):
            host = ATTENDEES.network.network_address + 400 + index
            templates.append(
                {
                    "ip": str(host),
                    "mac": mac(),
                    "hostname": device_name(),
                    "interface": ATTENDEES.device,
                    "lease_seconds": 3600,
                    "phase": rng.randrange(600, 7200),
                    "stale": True,
                }
            )
        return templates

    async def get_leases(self) -> list[DhcpLease]:
        now = self._clock()
        leases: list[DhcpLease] = []
        for t in self._templates:
            if t["stale"]:
                expires = now - t["phase"]
            else:
                elapsed = (now - t["phase"]) % t["lease_seconds"]
                expires = now + (t["lease_seconds"] - elapsed)
            expires_at = datetime.fromtimestamp(expires, tz=timezone.utc)
            leases.append(
                DhcpLease(
                    ip_address=t["ip"],
                    mac_address=t["mac"],
                    hostname=t["hostname"],
                    interface=t["interface"],
                    expires_at=expires_at,
                    active=expires > now,
                )
            )
        return leases


class MockMonitoringProvider(NetworkMonitoringProvider):
    source: ClassVar[str] = "mock"

    def __init__(
        self,
        dhcp: DhcpLeaseProvider | None = None,
        *,
        scenario: MockScenario = "healthy",
        seed: int = 42,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._scenario = scenario
        self._seed = seed
        self._clock = clock
        self._dhcp = dhcp or MockDhcpLeaseProvider(seed=seed, clock=clock)
        # Simula un firewall encendido hace ~2 días y 3 horas.
        self._boot = clock() - (2 * 86400 + 3 * 3600 + 17 * 60)

    # ------------------------------------------------------------------ #

    def _outage(self, component: str) -> CollectionResult:
        error = ProviderConnectionError("mock: escenario outage")
        return CollectionResult(
            data=None,
            issues=[
                CollectionIssue(component=component, kind=error.kind, message=error.public_message)
            ],
        )

    @staticmethod
    def _issue(
        component: str, error: MonitoringError, *, optional: bool = False
    ) -> CollectionIssue:
        return CollectionIssue(
            component=component, kind=error.kind, message=error.public_message, optional=optional
        )

    # ------------------------------------------------------------------ #

    async def get_system_metrics(self) -> CollectionResult[SystemMetrics]:
        if self._scenario == "outage":
            return self._outage("system")
        now = self._clock()
        elapsed = now - self._boot
        noise = _rng(self._seed, "cpu", int(now) // 3).uniform(-2.0, 2.0)
        cpu = min(max(18 + 10 * math.sin(now / 45) + 6 * math.sin(now / 11 + 1) + noise, 1.0), 95.0)

        used = int(_TOTAL_MEMORY * (0.34 + 0.04 * math.sin(now / 300)))
        memory = MemoryMetrics(
            total_bytes=_TOTAL_MEMORY,
            used_bytes=used,
            free_bytes=_TOTAL_MEMORY - used,
            used_percent=round(used / _TOTAL_MEMORY * 100, 1),
        )

        issues: list[CollectionIssue] = []
        if self._scenario == "degraded":
            temperature = TemperatureMetrics(available=False)
            issues.append(
                self._issue("system.temperature", ProviderNotSupportedError(), optional=True)
            )
        else:
            celsius = (
                41
                + 4 * math.sin(now / 120)
                + _rng(self._seed, "temp", int(now) // 5).uniform(-0.5, 0.5)
            )
            temperature = TemperatureMetrics(available=True, value_celsius=round(celsius, 1))

        return CollectionResult(
            data=SystemMetrics(
                hostname="netbot-fw.evento.local",
                version="OPNsense 25.1.9-amd64",
                uptime_seconds=int(elapsed),
                reference_time=datetime.fromtimestamp(now, tz=timezone.utc),
                cpu_percent=round(cpu, 1),
                memory=memory,
                temperature=temperature,
            ),
            issues=issues,
        )

    async def get_interface_metrics(self) -> CollectionResult[list[InterfaceMetrics]]:
        if self._scenario == "outage":
            return self._outage("interfaces")
        elapsed = self._clock() - self._boot
        interfaces: list[InterfaceMetrics] = []
        for index, spec in enumerate(TOPOLOGY):
            bytes_in = _cumulative(spec.rate_in, elapsed, index)
            bytes_out = _cumulative(spec.rate_out, elapsed, index + 0.5)
            down = self._scenario == "degraded" and spec is STAFF
            interfaces.append(
                InterfaceMetrics(
                    interface_id=spec.interface_id,
                    name=spec.device,
                    description=spec.description,
                    status=LinkStatus.DOWN if down else LinkStatus.UP,
                    ip_addresses=[spec.address],
                    traffic=InterfaceTraffic(
                        bytes_in=bytes_in,
                        bytes_out=bytes_out,
                        packets_in=bytes_in // _AVG_PACKET_BYTES,
                        packets_out=bytes_out // _AVG_PACKET_BYTES,
                        errors_in=int(elapsed // 40_000) if spec is WAN else 0,
                        errors_out=0,
                        collisions=0,
                    ),
                )
            )
        return CollectionResult(data=interfaces, issues=[])

    async def get_clients(self) -> CollectionResult[list[DhcpLease]]:
        if self._scenario == "outage":
            return self._outage("clients.dhcp")
        return CollectionResult(data=await self._dhcp.get_leases(), issues=[])

    async def get_firewall_statistics(self) -> CollectionResult[FirewallStatistics]:
        if self._scenario == "outage":
            return self._outage("firewall")
        if self._scenario == "degraded":
            return CollectionResult(
                data=None,
                issues=[
                    self._issue("firewall.stats", ProviderServerError()),
                    self._issue("firewall.pf_statistics", ProviderServerError()),
                ],
            )
        now = self._clock()
        elapsed = now - self._boot
        current = int(
            1800
            + 700 * math.sin(now / 90)
            + _rng(self._seed, "states", int(now) // 4).uniform(-60, 60)
        )
        inserts = int(12 * elapsed)
        wan_packets = (
            _cumulative(WAN.rate_in, elapsed, 0) + _cumulative(WAN.rate_out, elapsed, 0.5)
        ) // _AVG_PACKET_BYTES
        blocked = int(wan_packets * 0.012)
        return CollectionResult(
            data=FirewallStatistics(
                pf_enabled=True,
                states=StateTableStats(
                    current_entries=current,
                    searches=int(95 * elapsed),
                    inserts=inserts,
                    removals=max(inserts - current, 0),
                ),
                counters={
                    "match": int(14 * elapsed),
                    "bad-offset": 0,
                    "fragment": int(elapsed // 3000),
                    "short": 0,
                    "normalize": 0,
                    "memory": 0,
                },
                packets_passed=wan_packets - blocked,
                packets_blocked=blocked,
            ),
            issues=[],
        )

    async def get_firewall_events(self, limit: int) -> CollectionResult[list[FirewallEvent]]:
        if self._scenario == "outage":
            return self._outage("firewall.log")
        step = 4  # segundos por "ranura"; cada ranura produce a lo sumo un evento estable
        base_slot = int(self._clock()) // step
        events: list[FirewallEvent] = []
        for k in range(limit * 3):
            if len(events) >= limit:
                break
            slot = base_slot - k
            event = self._event_for_slot(slot, slot * step)
            if event:
                events.append(event)
        return CollectionResult(data=events, issues=[])

    def _event_for_slot(self, slot: int, epoch: int) -> FirewallEvent | None:
        rng = _rng(self._seed, "fw", slot)
        if rng.random() > 0.75:
            return None
        timestamp = datetime.fromtimestamp(epoch + rng.random() * 3, tz=timezone.utc)
        wan_ip = WAN.address.split("/")[0]

        if rng.random() < 0.55:  # intento entrante bloqueado en la WAN
            scanner = f"198.51.100.{rng.randrange(1, 255)}"
            proto, port = rng.choice(
                [
                    ("tcp", 22),
                    ("tcp", 23),
                    ("tcp", 445),
                    ("tcp", 3389),
                    ("tcp", 8080),
                    ("udp", 5060),
                    ("udp", 1900),
                ]
            )
            return FirewallEvent(
                timestamp=timestamp,
                action=FirewallAction.BLOCK,
                interface=WAN.device,
                source_ip=scanner,
                source_port=rng.randrange(1024, 65535),
                destination_ip=wan_ip,
                destination_port=port,
                protocol=proto,
                rule_id=_rule_id("default deny / state violation rule"),
            )

        spec = rng.choices([ATTENDEES, STAFF], weights=[8, 2])[0]
        host_offset = rng.randrange(11, 81) if spec is ATTENDEES else rng.randrange(20, 32)
        client = spec.network.network_address + host_offset
        proto, port, destination = rng.choice(
            [
                ("tcp", 443, "198.51.100.20"),
                ("tcp", 443, "192.0.2.44"),
                ("tcp", 80, "192.0.2.80"),
                ("udp", 53, "1.1.1.1"),
                ("udp", 53, "8.8.8.8"),
            ]
        )
        return FirewallEvent(
            timestamp=timestamp,
            action=FirewallAction.PASS,
            interface=spec.device,
            source_ip=str(client),
            source_port=rng.randrange(1024, 65535),
            destination_ip=destination,
            destination_port=port,
            protocol=proto,
            rule_id=_rule_id(f"allow {spec.description} to internet"),
        )

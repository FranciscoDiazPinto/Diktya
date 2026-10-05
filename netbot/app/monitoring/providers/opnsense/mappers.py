"""Conversión de payloads de OPNsense a los modelos internos de NetBot.

Este es el ÚNICO módulo que conoce el formato de las respuestas de OPNsense. Todas
las funciones son puras (sin I/O) y tolerantes: ante campos ausentes devuelven
None/valores por defecto en lugar de lanzar, de modo que una diferencia de versión
no tumbe la recolección.
"""

import ipaddress
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ...schemas import (
    DhcpLease,
    FirewallAction,
    FirewallEvent,
    FirewallStatistics,
    InterfaceMetrics,
    InterfaceTraffic,
    LinkStatus,
    MemoryMetrics,
    StateTableStats,
    TemperatureMetrics,
)

logger = logging.getLogger("netbot.monitoring.opnsense.mappers")


# --------------------------------------------------------------------------- #
# Utilidades de conversión
# --------------------------------------------------------------------------- #


def to_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return int(float(text))
    return None


def to_counter(value: Any) -> int | None:
    """Como to_int, pero un contador negativo se considera dato inválido."""
    number = to_int(value)
    return number if number is not None and number >= 0 else None


def to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group())
    return None


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and text != "*" else None


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    """Normaliza las formas habituales de listados de OPNsense a una lista de dicts:
    lista directa, grid `{"rows": [...]}` o dict de dicts."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        if payload and all(isinstance(v, dict) for v in payload.values()):
            return list(payload.values())
    return []


def _valid_ip(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    candidate = text.strip().split("%", 1)[0]  # quita zona IPv6 (fe80::1%igc0)
    try:
        ipaddress.ip_interface(candidate)
    except ValueError:
        return None
    return candidate


# --------------------------------------------------------------------------- #
# Sistema
# --------------------------------------------------------------------------- #


def parse_cpu_percent(payload: Any) -> float | None:
    """Evento de /api/diagnostics/cpu_usage/stream: {"total": 12, "idle": 88, ...}."""
    if not isinstance(payload, dict):
        return None
    value = to_float(payload.get("total"))
    if value is None:
        idle = to_float(payload.get("idle"))
        value = None if idle is None else 100.0 - idle
    if value is None:
        return None
    return round(min(max(value, 0.0), 100.0), 1)


def parse_memory(payload: Any) -> MemoryMetrics | None:
    """/api/diagnostics/system/system_resources -> {"memory": {"total": B, "used": B}}."""
    if not isinstance(payload, dict):
        return None
    memory = payload.get("memory", payload)
    if not isinstance(memory, dict):
        return None
    total = to_counter(memory.get("total"))
    used = to_counter(memory.get("used"))
    if not total or used is None:
        return None
    used = min(used, total)
    return MemoryMetrics(
        total_bytes=total,
        used_bytes=used,
        free_bytes=total - used,
        used_percent=round(used / total * 100, 1),
    )


def parse_system_information(payload: Any) -> tuple[str | None, str | None]:
    """/api/diagnostics/system/system_information -> (hostname, versión de OPNsense)."""
    if not isinstance(payload, dict):
        return None, None
    hostname = _clean_str(payload.get("name"))
    versions = payload.get("versions")
    version: str | None = None
    if isinstance(versions, str):
        version = _clean_str(versions)
    elif isinstance(versions, list):
        texts = [t for t in (_clean_str(v) for v in versions) if t]
        version = next((t for t in texts if t.lower().startswith("opnsense")), None) or (
            texts[0] if texts else None
        )
    return hostname, version


_UPTIME_RE = re.compile(
    r"^\s*(?:(?P<days>\d+)\s+days?,?\s*)?(?:(?P<h>\d+):(?P<m>\d{1,2})(?::(?P<s>\d{1,2}))?)?\s*$"
)
_TZ_TOKEN_RE = re.compile(r"\b[A-Z]{2,5}\b(?=\s+\d{4}\s*$)")


def _parse_unix_date(text: Any) -> tuple[datetime, str | None] | None:
    """Parsea fechas estilo `date(1)`: 'Sat Oct  4 12:00:00 UTC 2026'.

    Devuelve (fecha naive, abreviatura de zona o None). Las abreviaturas distintas de
    UTC/GMT son ambiguas, por eso no se convierten a una zona.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = " ".join(text.split())
    tz_match = _TZ_TOKEN_RE.search(cleaned)
    tz = tz_match.group() if tz_match else None
    if tz_match:
        cleaned = " ".join(_TZ_TOKEN_RE.sub("", cleaned).split())
    try:
        return datetime.strptime(cleaned, "%a %b %d %H:%M:%S %Y"), tz
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=None), "UTC" if parsed.tzinfo else None


def parse_uptime_seconds(payload: Any) -> int | None:
    """/api/diagnostics/system/system_time.

    Primero intenta el campo `uptime` ('1 day, 02:03:04'); si no es interpretable,
    calcula `datetime - boottime`.
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get("uptime")
    number = to_int(raw)
    if number is not None and number >= 0:
        return number
    if isinstance(raw, str):
        match = _UPTIME_RE.match(raw)
        if match and any(match.group(g) for g in ("days", "h")):
            days = int(match.group("days") or 0)
            hours = int(match.group("h") or 0)
            minutes = int(match.group("m") or 0)
            seconds = int(match.group("s") or 0)
            return days * 86400 + hours * 3600 + minutes * 60 + seconds
    now = _parse_unix_date(payload.get("datetime"))
    boot = _parse_unix_date(payload.get("boottime"))
    if now and boot:
        delta = (now[0] - boot[0]).total_seconds()
        if delta >= 0:
            return int(delta)
    return None


def parse_reference_time(payload: Any) -> datetime | None:
    """Hora del firewall, solo si es UTC/GMT (otras abreviaturas son ambiguas)."""
    if not isinstance(payload, dict):
        return None
    parsed = _parse_unix_date(payload.get("datetime"))
    if parsed and parsed[1] in {"UTC", "GMT"}:
        return parsed[0].replace(tzinfo=timezone.utc)
    return None


def parse_temperature(payload: Any) -> TemperatureMetrics:
    """/api/diagnostics/system/system_temperature -> lista de sensores (puede estar vacía)."""
    sensors: list[Any]
    if isinstance(payload, list):
        sensors = payload
    elif isinstance(payload, dict):
        values = list(payload.values())
        sensors = values if values and all(isinstance(v, dict) for v in values) else [payload]
    else:
        return TemperatureMetrics(available=False)

    readings: list[tuple[bool, float]] = []
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue
        celsius = to_float(sensor.get("temperature"))
        if celsius is None:
            continue
        is_cpu = (
            str(sensor.get("type", "")).lower() == "cpu"
            or "cpu" in str(sensor.get("device", "")).lower()
        )
        readings.append((is_cpu, celsius))
    if not readings:
        return TemperatureMetrics(available=False)
    cpu_values = [c for is_cpu, c in readings if is_cpu]
    chosen = max(cpu_values) if cpu_values else max(c for _, c in readings)
    return TemperatureMetrics(available=True, value_celsius=round(chosen, 1))


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #

_UP = {"up", "active", "associated", "running"}
_DOWN = {"down", "no carrier", "inactive"}


def _map_status(raw: Any) -> LinkStatus | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip().lower()
    if text in _UP:
        return LinkStatus.UP
    if text in _DOWN:
        return LinkStatus.DOWN
    return None


def _map_link_state(raw: Any) -> LinkStatus | None:
    """`link state` de ifinfo (FreeBSD): 0 desconocido, 1 caído, 2 activo."""
    state = to_int(raw)
    return {1: LinkStatus.DOWN, 2: LinkStatus.UP}.get(state) if state is not None else None


def _collect_ips(row: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def add(candidate: Any, prefix: Any = None) -> None:
        if isinstance(candidate, dict):
            add(
                candidate.get("ipaddr") or candidate.get("address") or candidate.get("ip"),
                candidate.get("subnetbits") or candidate.get("prefix"),
            )
            return
        if isinstance(candidate, list):
            for item in candidate:
                add(item)
            return
        text = _valid_ip(candidate)
        if text is None:
            return
        if "/" not in text and to_int(prefix) is not None:
            text = f"{text}/{to_int(prefix)}"
        if text not in found:
            found.append(text)

    for key in ("ipv4", "ipv6", "addr4", "addr6", "ipaddr", "ipaddrv6"):
        if key in row:
            add(row[key])
    return found


@dataclass
class _Record:
    interface_id: str | None = None
    device: str | None = None
    description: str | None = None
    status: LinkStatus | None = None
    ips: list[str] = field(default_factory=list)
    traffic: InterfaceTraffic | None = None
    fallback_traffic: InterfaceTraffic | None = None


class _Registry:
    def __init__(self) -> None:
        self.records: list[_Record] = []
        self._by_device: dict[str, _Record] = {}
        self._by_id: dict[str, _Record] = {}

    def find(self, device: str | None, identifier: str | None) -> _Record:
        record = (device and self._by_device.get(device)) or (
            identifier and self._by_id.get(identifier)
        )
        if not record:
            record = _Record()
            self.records.append(record)
        if device and not record.device:
            record.device = device
        if identifier and not record.interface_id:
            record.interface_id = identifier
        if record.device:
            self._by_device[record.device] = record
        if record.interface_id:
            self._by_id[record.interface_id] = record
        return record


def _traffic_or_none(**counters: int | None) -> InterfaceTraffic | None:
    if all(v is None for v in counters.values()):
        return None
    return InterfaceTraffic(**counters)


def _device_from_statistics_key(key: str) -> str | None:
    match = re.search(r"\(([^()\s]+)\)\s*$", key)
    return match.group(1) if match else None


def build_interfaces(
    info_payload: Any, statistics_payload: Any, traffic_payload: Any
) -> list[InterfaceMetrics]:
    """Une las tres fuentes por dispositivo. Cualquiera puede ser None (falló).

    Prioridad: identidad/estado/IPs <- interfaces_info; contadores <- traffic/interface,
    con get_interface_statistics como respaldo.
    """
    registry = _Registry()

    for row in extract_rows(info_payload):
        record = registry.find(
            _clean_str(row.get("device")) or _clean_str(row.get("name")),
            _clean_str(row.get("identifier")) or _clean_str(row.get("id")),
        )
        record.description = record.description or _clean_str(
            row.get("description") or row.get("descr")
        )
        record.status = record.status or _map_status(row.get("status"))
        for ip in _collect_ips(row):
            if ip not in record.ips:
                record.ips.append(ip)

    if isinstance(traffic_payload, dict):
        entries = traffic_payload.get("interfaces", traffic_payload)
        for key, entry in entries.items() if isinstance(entries, dict) else []:
            if not isinstance(entry, dict):
                continue
            record = registry.find(_clean_str(entry.get("device")), str(key))
            record.traffic = _traffic_or_none(
                bytes_in=to_counter(entry.get("bytes received")),
                bytes_out=to_counter(entry.get("bytes transmitted")),
                packets_in=to_counter(entry.get("packets received")),
                packets_out=to_counter(entry.get("packets transmitted")),
                errors_in=to_counter(entry.get("input errors")),
                errors_out=to_counter(entry.get("output errors")),
                collisions=to_counter(entry.get("collisions")),
            )
            record.status = record.status or _map_link_state(entry.get("link state"))
            name = _clean_str(entry.get("name"))
            if name and name != record.device:
                record.description = record.description or name

    if isinstance(statistics_payload, dict):
        entries = statistics_payload.get("statistics", statistics_payload)
        for key, entry in entries.items() if isinstance(entries, dict) else []:
            if not isinstance(entry, dict):
                continue
            device = (
                _clean_str(entry.get("device"))
                or _clean_str(entry.get("name"))
                or _device_from_statistics_key(str(key))
            )
            if not device:
                continue
            record = registry.find(device, None)
            record.fallback_traffic = record.fallback_traffic or _traffic_or_none(
                bytes_in=to_counter(entry.get("received-bytes")),
                bytes_out=to_counter(entry.get("sent-bytes")),
                packets_in=to_counter(entry.get("received-packets")),
                packets_out=to_counter(entry.get("sent-packets")),
                errors_in=to_counter(entry.get("received-errors")),
                errors_out=to_counter(entry.get("send-errors")),
                collisions=to_counter(entry.get("collisions")),
            )
            ip = _valid_ip(entry.get("address"))
            if ip and ip not in record.ips:
                record.ips.append(ip)

    result: list[InterfaceMetrics] = []
    for record in registry.records:
        interface_id = record.interface_id or record.device
        name = record.device or record.interface_id
        if not interface_id or not name:
            continue
        result.append(
            InterfaceMetrics(
                interface_id=interface_id,
                name=name,
                description=record.description,
                status=record.status or LinkStatus.UNKNOWN,
                ip_addresses=record.ips,
                traffic=record.traffic or record.fallback_traffic,
            )
        )
    return result


# --------------------------------------------------------------------------- #
# DHCP
# --------------------------------------------------------------------------- #


def _epoch_to_datetime(value: Any) -> datetime | None:
    seconds = to_int(value)
    if not seconds or seconds <= 0:  # 0 = concesión sin expiración
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_dhcp_lease(row: dict[str, Any], *, now: datetime, kea: bool = False) -> DhcpLease | None:
    """Fila de /api/dnsmasq/leases/search o /api/kea/leases4/search."""
    ip = _valid_ip(row.get("address"))
    mac = row.get("hwaddr") or row.get("mac")
    if ip is None or not isinstance(mac, str):
        return None
    expires_at = _epoch_to_datetime(row.get("expire"))
    active = expires_at is None or expires_at > now
    if kea:
        # Kea: state 0 = default (vigente); 1 = declined; 2 = expired-reclaimed.
        state = to_int(row.get("state"))
        if state not in (None, 0):
            active = False
    try:
        return DhcpLease(
            ip_address=ip.split("/", 1)[0],
            mac_address=mac,
            hostname=_clean_str(row.get("hostname")),
            interface=_clean_str(row.get("if")) or _clean_str(row.get("if_descr")),
            expires_at=expires_at,
            active=active,
        )
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Firewall
# --------------------------------------------------------------------------- #

_BLOCK_ACTIONS = {"block", "drop", "reject"}
_PROTO_NUMBERS = {"1": "icmp", "6": "tcp", "17": "udp", "58": "ipv6-icmp"}


def _parse_event_time(raw: dict[str, Any]) -> datetime | None:
    value = raw.get("__timestamp__") or raw.get("timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def parse_firewall_event(raw: dict[str, Any]) -> FirewallEvent | None:
    action_text = str(raw.get("action", "")).strip().lower()
    if action_text in _BLOCK_ACTIONS:
        action = FirewallAction.BLOCK
    elif action_text == "pass":
        action = FirewallAction.PASS
    else:
        return None  # rdr/nat/match: fuera del modelo block|pass
    timestamp = _parse_event_time(raw)
    source = _valid_ip(raw.get("src"))
    destination = _valid_ip(raw.get("dst"))
    if timestamp is None or source is None or destination is None:
        return None
    protocol = _clean_str(raw.get("protoname")) or _clean_str(str(raw.get("proto", "")))
    if protocol:
        protocol = _PROTO_NUMBERS.get(protocol, protocol).lower()
    rule = raw.get("rid") or raw.get("label") or raw.get("rulenr")
    try:
        return FirewallEvent(
            timestamp=timestamp,
            action=action,
            interface=_clean_str(raw.get("interface")) or _clean_str(raw.get("interface_name")),
            source_ip=source.split("/", 1)[0],
            source_port=to_int(raw.get("srcport")),
            destination_ip=destination.split("/", 1)[0],
            destination_port=to_int(raw.get("dstport")),
            protocol=protocol,
            rule_id=str(rule) if rule not in (None, "") else None,
        )
    except ValueError:
        return None


def parse_firewall_events(payload: Any, limit: int) -> list[FirewallEvent]:
    """/api/diagnostics/firewall/log -> eventos más recientes primero, máximo `limit`."""
    events: list[FirewallEvent] = []
    skipped = 0
    for raw in extract_rows(payload):
        event = parse_firewall_event(raw)
        if event is None:
            skipped += 1
        else:
            events.append(event)
    if skipped:
        logger.debug(
            "Eventos de firewall omitidos (acción fuera de modelo o malformados): %d", skipped
        )
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[:limit]


def _sum_numeric_leaves(node: Any, wanted: Iterable[str], path: str = "") -> int | None:
    """Suma hojas numéricas cuya ruta contiene todos los fragmentos de `wanted`."""
    wanted = tuple(wanted)
    total: int | None = None
    if isinstance(node, dict):
        for key, child in node.items():
            sub = _sum_numeric_leaves(child, wanted, f"{path}/{key}".lower())
            if sub is not None:
                total = (total or 0) + sub
    elif isinstance(node, list):
        for child in node:
            sub = _sum_numeric_leaves(child, wanted, path)
            if sub is not None:
                total = (total or 0) + sub
    else:
        number = to_counter(node)
        if number is not None and all(w in path for w in wanted):
            return number
    return total


def parse_pf_info(payload: Any) -> tuple[bool | None, StateTableStats | None, dict[str, int]]:
    """/api/diagnostics/firewall/pf_statistics/info (equivalente a `pfctl -si`)."""
    if not isinstance(payload, dict):
        return None, None, {}
    info = payload.get("info", payload)
    if not isinstance(info, dict):
        return None, None, {}

    status = info.get("status")
    enabled = None if not isinstance(status, str) else status.strip().lower() == "enabled"

    states: StateTableStats | None = None
    table = info.get("state-table")
    if isinstance(table, dict):
        states = _state_table(table)

    counters: dict[str, int] = {}
    raw_counters = info.get("counters")
    if isinstance(raw_counters, dict):
        for key, value in raw_counters.items():
            number = to_counter(value)
            if number is not None:
                counters[str(key)] = number
    return enabled, states, counters


def _state_table(table: dict[str, Any]) -> StateTableStats | None:
    stats = StateTableStats(
        current_entries=to_counter(table.get("current entries")),
        searches=to_counter(table.get("searches")),
        inserts=to_counter(table.get("inserts")),
        removals=to_counter(table.get("removals")),
    )
    return stats if any(v is not None for v in stats.model_dump().values()) else None


def parse_firewall_statistics(stats_payload: Any, pf_payload: Any) -> FirewallStatistics:
    enabled, states, counters = parse_pf_info(pf_payload)
    return FirewallStatistics(
        pf_enabled=enabled,
        states=states,
        counters=counters,
        packets_passed=_sum_numeric_leaves(stats_payload, ("pass", "packets")),
        packets_blocked=_sum_numeric_leaves(stats_payload, ("block", "packets")),
    )

from datetime import datetime, timezone

import pytest

from app.monitoring.providers.opnsense import mappers as m
from app.monitoring.schemas import FirewallAction, LinkStatus

from . import fixtures as fx


def test_cpu_percent_uses_total_then_idle():
    assert m.parse_cpu_percent(fx.CPU_EVENT) == 14.0
    assert m.parse_cpu_percent({"idle": 80}) == 20.0
    assert m.parse_cpu_percent({"total": 250}) == 100.0
    assert m.parse_cpu_percent("nope") is None


def test_memory_from_string_and_int_bytes():
    memory = m.parse_memory(fx.SYSTEM_RESOURCES)
    assert memory.total_bytes == 8589934592
    assert memory.used_bytes == 2147483648
    assert memory.free_bytes == 8589934592 - 2147483648
    assert memory.used_percent == 25.0


def test_memory_invalid_returns_none():
    assert m.parse_memory({"memory": {"total": 0, "used": 0}}) is None
    assert m.parse_memory({}) is None
    assert m.parse_memory(None) is None


def test_system_information():
    assert m.parse_system_information(fx.SYSTEM_INFORMATION) == (
        "fw-evento.localdomain",
        "OPNsense 25.1.9-amd64",
    )
    assert m.parse_system_information([]) == (None, None)


@pytest.mark.parametrize(
    ("uptime", "expected"),
    [
        ("2 days, 03:04:05", 2 * 86400 + 3 * 3600 + 4 * 60 + 5),
        ("1 day, 00:00:01", 86401),
        ("03:04:05", 3 * 3600 + 4 * 60 + 5),
        ("5 days", 5 * 86400),
        (3600, 3600),
    ],
)
def test_uptime_from_uptime_field(uptime, expected):
    assert m.parse_uptime_seconds({"uptime": uptime}) == expected


def test_uptime_falls_back_to_datetime_minus_boottime():
    payload = {
        "uptime": "unparseable",
        "datetime": "Sun Oct  4 12:00:00 CEST 2026",
        "boottime": "Sun Oct  4 10:00:00 CEST 2026",
    }
    assert m.parse_uptime_seconds(payload) == 7200
    assert m.parse_uptime_seconds({"uptime": "??"}) is None


def test_reference_time_only_when_utc():
    assert m.parse_reference_time(fx.SYSTEM_TIME) == datetime(
        2026, 10, 4, 12, 0, tzinfo=timezone.utc
    )
    assert m.parse_reference_time({"datetime": "Sun Oct  4 12:00:00 CEST 2026"}) is None


def test_temperature_prefers_hottest_cpu_sensor():
    temperature = m.parse_temperature(fx.SYSTEM_TEMPERATURE)
    assert temperature.available is True
    assert temperature.value_celsius == 51.5


@pytest.mark.parametrize("payload", [[], {}, None, "n/a", [{"temperature": "n/a"}]])
def test_temperature_unavailable(payload):
    temperature = m.parse_temperature(payload)
    assert temperature.available is False
    assert temperature.value_celsius is None


def test_build_interfaces_merges_the_three_sources_by_device():
    interfaces = {
        i.interface_id: i
        for i in m.build_interfaces(
            fx.INTERFACES_INFO, fx.INTERFACE_STATISTICS, fx.TRAFFIC_INTERFACE
        )
    }
    assert set(interfaces) == {"wan", "lan", "opt1"}

    wan = interfaces["wan"]
    assert (wan.name, wan.description, wan.status) == ("igc0", "WAN", LinkStatus.UP)
    assert "203.0.113.10/24" in wan.ip_addresses
    assert not any("%" in ip for ip in wan.ip_addresses)  # zona IPv6 removida
    assert wan.traffic.bytes_in == 1_000_000
    assert wan.traffic.bytes_out == 250_000
    assert wan.traffic.errors_in == 3

    # Sin entrada en traffic: los contadores salen del respaldo get_interface_statistics.
    opt1 = interfaces["opt1"]
    assert opt1.status == LinkStatus.DOWN  # "no carrier"
    assert opt1.traffic.bytes_in == 1000
    assert "10.20.0.1" in opt1.ip_addresses


def test_build_interfaces_survives_missing_sources():
    only_traffic = m.build_interfaces(None, None, fx.TRAFFIC_INTERFACE)
    assert {i.interface_id for i in only_traffic} == {"wan", "lan"}
    assert only_traffic[0].status == LinkStatus.UP  # desde `link state`
    assert m.build_interfaces(None, None, None) == []
    assert m.build_interfaces("garbage", 5, []) == []


def test_dhcp_lease_parsing():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    rows = fx.DNSMASQ_LEASES["rows"]
    active = m.parse_dhcp_lease(rows[0], now=now)
    assert str(active.ip_address) == "10.20.0.20"
    assert active.mac_address == "02:11:22:33:44:55"
    assert active.interface == "igc1.20"
    assert active.active is True

    expired = m.parse_dhcp_lease(rows[1], now=now)
    assert expired.active is False
    assert expired.hostname is None  # "*" => sin hostname

    static = m.parse_dhcp_lease(rows[2], now=now)
    assert static.expires_at is None and static.active is True
    assert static.mac_address == "aa:bb:cc:dd:ee:ff"

    assert m.parse_dhcp_lease(rows[3], now=now) is None  # MAC inválida


def test_kea_state_controls_activity():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    ok, declined = (m.parse_dhcp_lease(r, now=now, kea=True) for r in fx.KEA_LEASES["rows"])
    assert ok.active is True
    assert declined.active is False


def test_firewall_events_normalized_sorted_and_filtered():
    events = m.parse_firewall_events(fx.FIREWALL_LOG, limit=10)
    # Se omiten: acción "rdr" y la fila con timestamp inválido.
    assert len(events) == 3
    assert [e.timestamp for e in events] == sorted((e.timestamp for e in events), reverse=True)

    block = next(e for e in events if e.rule_id == "abc123")
    assert block.action == FirewallAction.BLOCK
    assert (block.source_port, block.destination_port, block.protocol) == (40000, 22, "tcp")

    ipv6 = next(e for e in events if e.rule_id == "ipv6-rule")
    assert ipv6.protocol == "ipv6-icmp"
    assert ipv6.source_port is None

    assert len(m.parse_firewall_events(fx.FIREWALL_LOG, limit=1)) == 1


def test_firewall_statistics():
    stats = m.parse_firewall_statistics(fx.FIREWALL_STATS, fx.PF_INFO)
    assert stats.pf_enabled is True
    assert stats.states.current_entries == 1523
    assert stats.counters["match"] == 50000
    assert stats.packets_passed == 1000 + 900 + 500 + 450
    assert stats.packets_blocked == 40 + 2 + 1


def test_firewall_statistics_with_unknown_shapes_yields_nulls():
    stats = m.parse_firewall_statistics("weird", None)
    assert stats.pf_enabled is None and stats.states is None
    assert stats.packets_passed is None and stats.packets_blocked is None

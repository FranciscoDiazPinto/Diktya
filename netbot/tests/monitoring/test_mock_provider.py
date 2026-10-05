import ipaddress

from app.monitoring.providers.mock import TOPOLOGY, MockMonitoringProvider
from app.monitoring.schemas import FirewallAction, LinkStatus


class Clock:
    def __init__(self, now=1_790_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


async def test_healthy_scenario_has_no_issues():
    provider = MockMonitoringProvider(clock=Clock())
    for method in (
        "get_system_metrics",
        "get_interface_metrics",
        "get_clients",
        "get_firewall_statistics",
    ):
        result = await getattr(provider, method)()
        assert result.data is not None and result.issues == [], method
    assert (await provider.get_firewall_events(10)).data


async def test_system_metrics_are_realistic_and_uptime_advances():
    clock = Clock()
    provider = MockMonitoringProvider(clock=clock)
    first = (await provider.get_system_metrics()).data
    clock.now += 60
    second = (await provider.get_system_metrics()).data
    assert second.uptime_seconds - first.uptime_seconds == 60
    assert 0 < first.cpu_percent < 100
    assert first.memory.used_bytes + first.memory.free_bytes == first.memory.total_bytes
    assert first.temperature.available and 20 < first.temperature.value_celsius < 90


async def test_traffic_counters_are_cumulative_and_monotonic():
    clock = Clock()
    provider = MockMonitoringProvider(clock=clock)
    previous = {i.interface_id: i.traffic for i in (await provider.get_interface_metrics()).data}
    for _ in range(50):
        clock.now += 7
        current = {i.interface_id: i.traffic for i in (await provider.get_interface_metrics()).data}
        for key, traffic in current.items():
            for counter in ("bytes_in", "bytes_out", "packets_in", "packets_out"):
                assert getattr(traffic, counter) >= getattr(previous[key], counter), (key, counter)
        previous = current


async def test_leases_fall_inside_the_topology_subnets_and_include_expired_ones():
    provider = MockMonitoringProvider(clock=Clock())
    leases = (await provider.get_clients()).data
    networks = {spec.device: spec.network for spec in TOPOLOGY}
    for lease in leases:
        assert lease.interface in networks
        assert ipaddress.ip_address(lease.ip_address) in networks[lease.interface]
    assert len({str(lease.ip_address) for lease in leases}) == len(leases)
    assert {True, False} == {lease.active for lease in leases}
    assert all(lease.expires_at is not None for lease in leases)


async def test_events_are_coherent_with_topology_and_stable_between_calls():
    provider = MockMonitoringProvider(clock=Clock())
    events = (await provider.get_firewall_events(200)).data
    devices = {spec.device for spec in TOPOLOGY}
    assert len(events) == 200
    assert all(e.interface in devices for e in events)
    assert [e.timestamp for e in events] == sorted((e.timestamp for e in events), reverse=True)
    assert {FirewallAction.BLOCK, FirewallAction.PASS} == {e.action for e in events}
    assert events == (await provider.get_firewall_events(200)).data
    for e in events:
        if e.action == FirewallAction.BLOCK:
            assert e.interface == "igc0" and str(e.destination_ip) == "203.0.113.10"


async def test_degraded_scenario_exercises_partial_failures():
    provider = MockMonitoringProvider(scenario="degraded", clock=Clock())
    system = await provider.get_system_metrics()
    assert system.data.temperature.available is False
    assert [i.optional for i in system.issues] == [True]
    interfaces = (await provider.get_interface_metrics()).data
    assert any(i.status == LinkStatus.DOWN for i in interfaces)
    stats = await provider.get_firewall_statistics()
    assert stats.data is None and stats.issues


async def test_outage_scenario_returns_no_data_everywhere():
    provider = MockMonitoringProvider(scenario="outage", clock=Clock())
    results = [
        await provider.get_system_metrics(),
        await provider.get_interface_metrics(),
        await provider.get_clients(),
        await provider.get_firewall_statistics(),
        await provider.get_firewall_events(5),
    ]
    assert all(r.data is None and r.issues for r in results)

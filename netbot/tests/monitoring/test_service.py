import asyncio
from datetime import datetime, timezone

from app.monitoring.providers.base import CollectionResult, NetworkMonitoringProvider
from app.monitoring.schemas import (
    CollectionIssue,
    FirewallAction,
    FirewallEvent,
    IssueKind,
    MonitoringStatus,
    SystemMetrics,
)
from app.monitoring.service import MonitoringService


def issue(optional: bool) -> CollectionIssue:
    return CollectionIssue(component="x", kind=IssueKind.TIMEOUT, message="m", optional=optional)


class StubProvider(NetworkMonitoringProvider):
    source = "stub"

    def __init__(self, result=None, *, raises: Exception | None = None, delay: float = 0.0):
        self.result = result if result is not None else CollectionResult(SystemMetrics())
        self.raises = raises
        self.delay = delay
        self.calls = 0

    async def get_system_metrics(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        return self.result

    async def get_interface_metrics(self):
        raise NotImplementedError

    async def get_clients(self):
        raise NotImplementedError

    async def get_firewall_statistics(self):
        raise NotImplementedError

    async def get_firewall_events(self, limit):
        self.calls += 1
        base = datetime(2026, 10, 4, tzinfo=timezone.utc)
        events = [
            FirewallEvent(
                timestamp=base.replace(second=i),
                action=FirewallAction.BLOCK if i % 2 else FirewallAction.PASS,
                source_ip="1.1.1.1",
                destination_ip="2.2.2.2",
            )
            for i in range(10)
        ]
        return CollectionResult(events[::-1][:limit])


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def test_status_ok_degraded_unavailable():
    ok = await MonitoringService(
        StubProvider(CollectionResult(SystemMetrics(), [issue(True)]))
    ).get_system()
    assert ok.status == MonitoringStatus.OK  # un incidente opcional no degrada

    degraded = await MonitoringService(
        StubProvider(CollectionResult(SystemMetrics(), [issue(False)]))
    ).get_system()
    assert degraded.status == MonitoringStatus.DEGRADED

    down = await MonitoringService(
        StubProvider(CollectionResult(None, [issue(False)]))
    ).get_system()
    assert down.status == MonitoringStatus.UNAVAILABLE and down.data is None
    assert down.source == "stub"


async def test_unexpected_provider_exception_becomes_unavailable_not_a_crash():
    response = await MonitoringService(StubProvider(raises=RuntimeError("bug"))).get_system()
    assert response.status == MonitoringStatus.UNAVAILABLE
    assert response.issues[0].kind == IssueKind.UNKNOWN
    assert "bug" not in response.issues[0].message


async def test_cache_hit_and_expiry():
    clock = FakeClock()
    provider = StubProvider()
    service = MonitoringService(provider, cache_ttl_seconds=5, clock=clock)
    first = await service.get_system()
    await service.get_system()
    assert provider.calls == 1
    clock.now += 5.1
    second = await service.get_system()
    assert provider.calls == 2
    assert second.collected_at >= first.collected_at


async def test_ttl_zero_disables_cache():
    provider = StubProvider()
    service = MonitoringService(provider, cache_ttl_seconds=0)
    await service.get_system()
    await service.get_system()
    assert provider.calls == 2


async def test_concurrent_requests_share_a_single_collection():
    provider = StubProvider(delay=0.05)
    service = MonitoringService(provider, cache_ttl_seconds=5)
    await asyncio.gather(*(service.get_system() for _ in range(8)))
    assert provider.calls == 1


async def test_events_filter_and_limit_reuse_one_fetch():
    provider = StubProvider()
    service = MonitoringService(provider, cache_ttl_seconds=5, firewall_log_fetch_limit=10)
    everything = await service.get_firewall_events(limit=100)
    blocks = await service.get_firewall_events(limit=3, action=FirewallAction.BLOCK)
    assert len(everything.data) == 10
    assert len(blocks.data) == 3 and all(e.action == FirewallAction.BLOCK for e in blocks.data)
    assert provider.calls == 1

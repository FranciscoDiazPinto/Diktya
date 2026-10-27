from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring.providers.base import CollectionResult
from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.schemas import InterfaceMetrics, InterfaceTraffic, MonitoringStatus
from app.monitoring.service import MonitoringService


class CounterProvider(MockMonitoringProvider):
    """Devuelve una interfaz cuyos contadores fija la prueba."""

    def __init__(self):
        super().__init__()
        self.bytes_in = 0
        self.bytes_out = 0

    async def get_interface_metrics(self):
        return CollectionResult(
            data=[
                InterfaceMetrics(
                    interface_id="wan",
                    name="igc0",
                    traffic=InterfaceTraffic(bytes_in=self.bytes_in, bytes_out=self.bytes_out),
                )
            ]
        )


@pytest.fixture()
def clock(monkeypatch):
    now = {"t": datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)}

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now["t"]

    monkeypatch.setattr("app.monitoring.service.datetime", FakeDatetime)
    return now


async def take(service, provider, clock, seconds, bytes_in, bytes_out):
    clock["t"] += timedelta(seconds=seconds)
    provider.bytes_in, provider.bytes_out = bytes_in, bytes_out
    await service.sample_traffic()


async def test_rates_are_deltas_between_samples(clock):
    provider = CounterProvider()
    service = MonitoringService(provider, cache_ttl_seconds=0)
    await take(service, provider, clock, 0, 1000, 500)
    await take(service, provider, clock, 5, 6000, 1500)
    await take(service, provider, clock, 5, 16000, 2000)

    response = await service.get_traffic_history(300)
    assert response.status == MonitoringStatus.OK
    [wan] = response.data
    assert [(p.bytes_in_per_second, p.bytes_out_per_second) for p in wan.points] == [
        (1000, 200),
        (2000, 100),
    ]


async def test_counter_reset_is_skipped_and_window_applies(clock):
    provider = CounterProvider()
    service = MonitoringService(provider, cache_ttl_seconds=0)
    await take(service, provider, clock, 0, 1000, 1000)
    await take(service, provider, clock, 100, 2000, 2000)
    await take(service, provider, clock, 5, 10, 10)  # reinicio del firewall
    await take(service, provider, clock, 5, 60, 60)

    full = (await service.get_traffic_history(3600)).data[0].points
    assert [p.bytes_in_per_second for p in full] == [10, 10]
    recent = (await service.get_traffic_history(10)).data[0].points
    assert [p.bytes_in_per_second for p in recent] == [10]


async def test_old_samples_are_discarded(clock):
    provider = CounterProvider()
    service = MonitoringService(provider, cache_ttl_seconds=0, history_seconds=60)
    for _ in range(30):
        await take(service, provider, clock, 5, provider.bytes_in + 100, 0)
    assert len(service._samples) <= 13


async def test_history_is_unavailable_when_the_source_is_down():
    service = MonitoringService(MockMonitoringProvider(scenario="outage"), cache_ttl_seconds=0)
    response = await service.get_traffic_history()
    assert response.status == MonitoringStatus.UNAVAILABLE and response.data is None

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.providers.noc import NocTelemetry
from app.monitoring.schemas import CollectionIssue, IssueKind
from app.monitoring.service import MonitoringService


@pytest.mark.asyncio
async def test_noc_traffic_reports_observation_time_and_filters_cached_window(monkeypatch):
    source = NocTelemetry(SecretStr("dbname=unused"))
    now = datetime.now(timezone.utc)
    reader = AsyncMock(return_value=([
        (b"wan", now, 8, 4, True),
        (b"wan", now - timedelta(seconds=30), 0, 1, True),
        (b"wan", now - timedelta(minutes=5), 2, 3, False),
    ], None))
    monkeypatch.setattr(source, "_query", reader)
    service = MonitoringService(MockMonitoringProvider(), noc=source)

    recent = await service.get_traffic_history(60)
    short = await service.get_traffic_history(10)
    assert recent.source == "noc"
    assert recent.collected_at == now
    assert len(recent.data[0].points) == 2
    assert short.data[0].points[0].bytes_in_per_second == 1_000_000
    assert len(short.data[0].points) == 1
    assert reader.await_count == 1
    assert (await service.get_system()).source == "mock"


@pytest.mark.asyncio
async def test_noc_firewall_preserves_partial_data_and_does_not_invent_totals(monkeypatch):
    source = NocTelemetry(SecretStr("dbname=unused"))
    now = datetime.now(timezone.utc)
    issue = CollectionIssue(component="noc.firewall.states", kind=IssueKind.PERMISSION, message="Sin permiso")

    async def read(component, query):
        if component.endswith(".states"):
            return [], issue
        return [(now, 17)], None

    monkeypatch.setattr(source, "_query", read)
    result = await MonitoringService(MockMonitoringProvider(), noc=source).get_firewall_stats()
    assert result.source == "noc" and result.status == "degraded"
    assert result.data.logged_blocked_packets_5m == 17
    assert result.data.packets_blocked is None
    assert result.data.packets_passed is None
    assert result.issues == [issue]

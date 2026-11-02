from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring.providers.base import CollectionResult
from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.schemas import CollectionIssue, IssueKind, MonitoringStatus, SystemMetrics
from app.monitoring.service import MonitoringService
from app.changes.service import VlanReservationService, InventoryUnavailable


class Clock:
    now=0
    def __call__(self):return self.now


class Flaky(MockMonitoringProvider):
    fail=False
    async def get_system_metrics(self):
        return CollectionResult(None,[CollectionIssue(component='system',kind=IssueKind.CONNECTION,message='Sin conexión')]) if self.fail else CollectionResult(SystemMetrics(hostname='previous'))
    async def get_interface_metrics(self):
        return CollectionResult(None) if self.fail else await super().get_interface_metrics()
    async def get_vlan_inventory(self):
        return CollectionResult(None) if self.fail else await super().get_vlan_inventory()


async def test_last_known_data_keeps_original_timestamp_expires_and_recovers():
    clock=Clock();provider=Flaky()
    service=MonitoringService(provider,cache_ttl_seconds=0,clock=clock,stale_retention_seconds=10)
    first=await service.get_system();provider.fail=True;clock.now=5
    old=await service.get_system()
    assert old.stale and old.status==MonitoringStatus.DEGRADED
    assert old.collected_at==first.collected_at and old.last_attempt_at>=first.collected_at
    assert old.data.hostname=='previous' and old.issues[0].kind==IssueKind.CONNECTION
    clock.now=11
    gone=await service.get_system()
    assert gone.status==MonitoringStatus.UNAVAILABLE and gone.data is None and not gone.stale
    provider.fail=False
    recovered=await service.get_system()
    assert recovered.status==MonitoringStatus.OK and not recovered.stale


async def test_stale_retention_zero_does_not_retain_data():
    provider=Flaky();service=MonitoringService(provider,cache_ttl_seconds=0,stale_retention_seconds=0)
    await service.get_system();provider.fail=True
    assert (await service.get_system()).data is None


async def test_outage_after_samples_does_not_publish_fresh_history_or_append_samples():
    provider=Flaky();service=MonitoringService(provider,cache_ttl_seconds=0)
    await service.sample_traffic();count=len(service._samples)
    provider.fail=True
    history=await service.get_traffic_history()
    assert history.stale and history.status==MonitoringStatus.DEGRADED
    assert history.collected_at==service._samples[-1].collected_at
    assert len(service._samples)==count


async def test_known_vlan_inventory_is_not_usable_for_changes_during_outage(db_session):
    provider=Flaky();monitoring=MonitoringService(provider,cache_ttl_seconds=0)
    reservations=VlanReservationService(monitoring,db_session)
    assert await reservations.available_vlans()
    provider.fail=True
    with pytest.raises(InventoryUnavailable):await reservations.available_vlans()


async def test_access_point_page_preserves_stale_metadata_and_has_exact_total():
    from app.monitoring.providers.access_points import AccessPointAdapter
    from app.monitoring.schemas import InventorySnapshot, InventoryDevice, DeviceType
    class Source:
        fail = False
        async def collect_inventory(self):
            if self.fail: return CollectionResult(None)
            return CollectionResult(InventorySnapshot(site_id='demo-site', devices=[
                InventoryDevice(external_id=f'demo-ap-{n}',name=f'AP {n}',device_type=DeviceType.ACCESS_POINT)
                for n in range(1,4)]))
    provider=Source()
    service=MonitoringService(MockMonitoringProvider(),cache_ttl_seconds=0,access_points_provider=AccessPointAdapter(provider))
    page=await service.get_access_point_page(limit=1,offset=1)
    assert page.data.total_count==3 and page.data.items[0].id=='demo-ap-2'
    provider.fail=True
    old=await service.get_access_point_page(limit=1,offset=2)
    assert old.stale and old.data.total_count==3 and old.data.items[0].id=='demo-ap-3'


async def test_cache_hit_never_extends_stale_retention_past_its_limit():
    clock=Clock();provider=Flaky()
    service=MonitoringService(provider,cache_ttl_seconds=5,clock=clock,stale_retention_seconds=10)
    await service.get_system();provider.fail=True;clock.now=6
    assert (await service.get_system()).stale
    clock.now=10.5
    expired=await service.get_system()
    assert expired.status==MonitoringStatus.UNAVAILABLE and expired.data is None

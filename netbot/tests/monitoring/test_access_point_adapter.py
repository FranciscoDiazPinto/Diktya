"""El detalle por red reutiliza el contrato de inventario de Itamar."""
import pytest
from app.monitoring.providers.access_points import AccessPointAdapter
from app.monitoring.providers.base import CollectionResult
from app.monitoring.schemas import DeviceState, DeviceType, InventoryDevice, InventorySnapshot, IssueKind


class Source:
    async def collect_inventory(self):
        return self.result

    async def aclose(self):
        self.closed = True


async def test_scoped_adapter_keeps_site_and_only_explicit_access_points():
    source = Source()
    source.result = CollectionResult(InventorySnapshot(site_id='site-one', devices=[
        InventoryDevice(external_id='ap', name='AP', device_type=DeviceType.ACCESS_POINT, state=DeviceState.MAINTENANCE),
        InventoryDevice(external_id='sw', name='Switch', device_type=DeviceType.SWITCH),
        InventoryDevice(external_id='unknown', name='Unknown'),
    ]))
    adapter = AccessPointAdapter(source)
    result = await adapter.collect()
    assert len(result.data) == 1
    ap = result.data[0]
    assert (ap.id, ap.site_id, ap.state.value) == ('ap', 'site-one', 'transitioning')
    assert not ap.telemetry_available and ap.cpu_percent is None and ap.last_heartbeat_at is None
    await adapter.aclose()
    assert source.closed


@pytest.mark.parametrize('snapshot', [InventorySnapshot(devices=[]), InventorySnapshot(site_id='one')])
async def test_unresolved_site_or_missing_devices_never_becomes_healthy_empty_inventory(snapshot):
    source = Source()
    source.result = CollectionResult(snapshot)
    result = await AccessPointAdapter(source).collect()
    assert result.data is None


async def test_disabled_integration_stays_unconfigured_without_mock_fallback():
    result = await AccessPointAdapter(None).collect()
    assert result.data is None and result.issues[0].kind == IssueKind.NOT_CONFIGURED

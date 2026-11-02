"""Colector: persistencia, datos desactualizados, reintentos, alertas y disponibilidad."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.model_registry import register_models
from app.monitoring import inventory
from app.monitoring.inventory import InventoryCollector
from app.monitoring.models import MonitoringAlert, SourceState
from app.monitoring.providers.base import CollectionResult, InfrastructureSource
from app.monitoring.schemas import (
    CollectionIssue, DeviceState, DeviceType, InventoryDevice, InventorySnapshot, InventorySsid, InventoryVlan,
    IssueKind, MonitoringStatus,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class Source(InfrastructureSource):
    source = "mock"

    def __init__(self):
        self.result = None

    async def collect_inventory(self):
        return self.result


def snapshot(state=DeviceState.ONLINE, **extra):
    data = dict(
        devices=[InventoryDevice(external_id="ap1", name="AP Hall", device_type=DeviceType.ACCESS_POINT, state=state)],
        vlans=[InventoryVlan(external_id="v20", name="Invitados", tag=20)],
        ssids=[InventorySsid(external_id="s1", name="Feria", enabled=True, vlan_tag=20)],
    )
    data.update(extra)
    return CollectionResult(InventorySnapshot(**data))


DOWN = CollectionResult(None, [CollectionIssue(component="x", kind=IssueKind.TIMEOUT, message="Sin respuesta")])


@pytest.fixture()
def lab(monkeypatch):
    register_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(_env_file=None, monitoring_inventory_interval_seconds=30, monitoring_retry_max_seconds=120,
                        monitoring_inventory_max_age_seconds=60, monitoring_source_failure_threshold=2)
    clock = {"now": T0}
    monkeypatch.setattr(inventory, "_utcnow", lambda: clock["now"])
    source = Source()
    collector = InventoryCollector([source], factory, settings, clock=lambda: clock["now"])

    class Lab:
        pass

    lab = Lab()
    lab.source, lab.collector, lab.settings, lab.db, lab.clock = source, collector, settings, factory(), clock

    async def cycle(result, advance=30):
        source.result = result
        clock["now"] += timedelta(seconds=advance)
        await collector.run_cycle()
        lab.db.expire_all()

    lab.cycle = cycle
    lab.alerts = lambda: inventory.list_alerts(lab.db, settings).items
    yield lab
    lab.db.close()


async def test_inventory_is_stored_and_updated(lab):
    await lab.cycle(snapshot())
    page = inventory.list_devices(lab.db, lab.settings)
    assert page.total == 1 and page.items[0].name == "AP Hall"
    assert inventory.list_vlans(lab.db, lab.settings).items[0].tag == 20
    assert inventory.list_ssids(lab.db, lab.settings).items[0].name == "Feria"
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))
    assert inventory.list_devices(lab.db, lab.settings).total == 1
    assert inventory.list_devices(lab.db, lab.settings).items[0].state == DeviceState.OFFLINE
    assert inventory.summary(lab.db, lab.settings).access_points_offline == 1


async def test_device_filters_and_pagination(lab):
    devices = [InventoryDevice(external_id=f"d{i}", name=f"D{i}", device_type=DeviceType.ACCESS_POINT,
                               state=DeviceState.OFFLINE if i == 2 else DeviceState.ONLINE) for i in range(3)]
    devices.append(InventoryDevice(external_id="sw", name="SW", device_type=DeviceType.SWITCH, state=DeviceState.ONLINE))
    await lab.cycle(snapshot(devices=devices))
    assert inventory.list_devices(lab.db, lab.settings, state=DeviceState.OFFLINE).total == 1
    assert inventory.list_devices(lab.db, lab.settings, device_type=DeviceType.SWITCH).total == 1
    page = inventory.list_devices(lab.db, lab.settings, limit=2, offset=0)
    assert (page.total, len(page.items), page.items[0].state) == (4, 2, DeviceState.OFFLINE)


async def test_unavailable_source_keeps_last_data_marked_stale(lab, monkeypatch):
    await lab.cycle(snapshot())
    await lab.cycle(DOWN)
    later = T0 + timedelta(seconds=600)
    monkeypatch.setattr(inventory, "_utcnow", lambda: later)
    device = inventory.list_devices(lab.db, lab.settings).items[0]
    assert device.name == "AP Hall" and device.stale is True
    summary = inventory.summary(lab.db, lab.settings)
    assert summary.stale is True
    assert summary.sources[0].status == MonitoringStatus.UNAVAILABLE
    assert summary.sources[0].last_error_message == "Sin respuesta"


async def test_partial_collection_does_not_mark_sections_as_missing(lab):
    await lab.cycle(snapshot())
    await lab.cycle(snapshot(vlans=None, ssids=None))
    assert inventory.list_vlans(lab.db, lab.settings).total == 1
    assert inventory.list_ssids(lab.db, lab.settings).total == 1


async def test_retries_back_off_progressively_and_recover(lab):
    delays = []
    for _ in range(4):
        await lab.cycle(DOWN, advance=delays[-1] if delays else 30)
        state = lab.db.get(SourceState, "mock")
        delays.append((state.next_attempt_at - state.last_attempt_at).total_seconds())
    assert delays == [30, 60, 120, 120]  # con tope
    lab.source.result = snapshot()
    lab.clock["now"] += timedelta(seconds=10)
    await lab.collector.run_cycle()
    lab.db.expire_all()
    assert lab.db.get(SourceState, "mock").consecutive_failures == 4  # aún esperando: no reintenta antes
    await lab.cycle(snapshot(), advance=120)
    state = lab.db.get(SourceState, "mock")
    assert state.consecutive_failures == 0 and state.status == "ok" and state.last_error_message is None


async def test_unexpected_provider_bug_does_not_stop_the_cycle(lab):
    async def explode():
        raise RuntimeError("bug")

    lab.source.collect_inventory = explode
    await lab.cycle(None)
    assert lab.db.get(SourceState, "mock").status == "unavailable"


async def test_alert_lifecycle_creation_dedup_and_auto_resolution(lab):
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))
    alerts = lab.alerts()
    assert len(alerts) == 1
    assert (alerts[0].severity, alerts[0].device_name) == ("critical", "AP Hall")
    detected = alerts[0].detected_at
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))
    assert lab.alerts()[0].detected_at == detected
    await lab.cycle(snapshot())
    assert lab.alerts() == []
    resolved = inventory.list_alerts(lab.db, lab.settings, active=False).items
    assert len(resolved) == 1 and resolved[0].resolved_at is not None
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))  # una nueva caída es otra alerta
    assert lab.db.scalar(select(func.count()).select_from(MonitoringAlert)) == 2


async def test_source_outage_neither_resolves_device_alerts_nor_alerts_on_first_failure(lab):
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))
    await lab.cycle(DOWN)
    assert [a.category if hasattr(a, "category") else a.message for a in lab.alerts()] == ["AP Hall está fuera de línea."]
    await lab.cycle(DOWN)
    assert len(lab.alerts()) == 2
    await lab.cycle(snapshot(state=DeviceState.OFFLINE), advance=60)
    assert [a.message for a in lab.alerts()] == ["AP Hall está fuera de línea."]


async def test_alerts_are_listed_by_severity_and_missing_devices_alert(lab):
    other = InventoryDevice(external_id="ap2", name="AP Sur", device_type=DeviceType.ACCESS_POINT, state=DeviceState.DEGRADED)
    base = snapshot(state=DeviceState.OFFLINE)
    await lab.cycle(snapshot(devices=[*base.data.devices, other]))
    assert [a.severity for a in lab.alerts()] == ["critical", "warning"]
    await lab.cycle(snapshot(devices=[other]))
    assert any("dejó de aparecer" in a.message for a in lab.alerts())


async def test_availability_counts_only_observed_time(lab):
    await lab.cycle(snapshot())
    assert inventory.summary(lab.db, lab.settings).availability_percent is None
    await lab.cycle(snapshot())
    await lab.cycle(snapshot(state=DeviceState.OFFLINE))
    assert inventory.summary(lab.db, lab.settings).availability_percent == 50.0
    await lab.cycle(snapshot(), advance=3600)  # un silencio largo no suma ni como caída ni como línea
    assert inventory.summary(lab.db, lab.settings).availability_percent == 50.0


async def test_unconfigured_source_never_raises_a_lost_connection_alert(lab):
    missing = CollectionResult(None, [CollectionIssue(component="mock", kind=IssueKind.NOT_CONFIGURED,
                                                      message="Falta configurar: X")])
    await lab.cycle(missing)
    await lab.cycle(missing, advance=60)
    await lab.cycle(missing, advance=120)
    assert lab.alerts() == []
    health = inventory.source_health(lab.db, lab.settings)[0]
    assert health.status == MonitoringStatus.UNAVAILABLE and health.last_error_kind == "not_configured"


def test_source_never_collected_is_reported(lab):
    health = inventory.source_health(lab.db, lab.settings)
    assert health[0].status == MonitoringStatus.UNAVAILABLE and health[0].stale is True

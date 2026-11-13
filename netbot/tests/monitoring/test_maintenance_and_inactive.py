"""HU017: mantenimiento declarado y SSID/VLAN que dejan de estar activos."""
import asyncio
from datetime import timedelta

from app.monitoring import maintenance
from app.monitoring.schemas import DeviceState, InventorySsid, InventoryVlan
from tests.monitoring.test_inventory import lab, snapshot  # noqa: F401


def keys(lab):
    return sorted(alert.message for alert in lab.alerts())


def test_declared_maintenance_suppresses_only_the_expected_outage(lab):
    asyncio.run(lab.cycle(snapshot()))
    now = lab.clock["now"]
    maintenance.open_window(lab.db, source="mock", external_id="ap1", until=now + timedelta(minutes=2),
                            reason="Reinicio confirmado", now=now)
    lab.db.commit()
    asyncio.run(lab.cycle(snapshot(DeviceState.OFFLINE)))
    assert lab.alerts() == []  # caída esperada durante el reinicio
    # La ventana vence sola: si el equipo sigue caído, la alerta aparece.
    asyncio.run(lab.cycle(snapshot(DeviceState.OFFLINE), advance=180))
    assert keys(lab) == ["AP Hall está fuera de línea."]


def test_closing_the_window_restores_alerting_immediately(lab):
    asyncio.run(lab.cycle(snapshot()))
    now = lab.clock["now"]
    maintenance.open_window(lab.db, source="mock", external_id="ap1", until=now + timedelta(hours=1), reason="x", now=now)
    maintenance.close_window(lab.db, source="mock", external_id="ap1", now=now)
    lab.db.commit()
    asyncio.run(lab.cycle(snapshot(DeviceState.OFFLINE)))
    assert keys(lab) == ["AP Hall está fuera de línea."]


def test_ssid_and_vlan_that_become_inactive_raise_alerts_that_resolve(lab):
    asyncio.run(lab.cycle(snapshot()))
    assert lab.alerts() == []
    disabled = snapshot(ssids=[InventorySsid(external_id="s1", name="Feria", enabled=False, vlan_tag=20)], vlans=[])
    asyncio.run(lab.cycle(disabled))
    assert keys(lab) == ["El SSID Feria quedó deshabilitado en mock.",
                         "La VLAN Invitados dejó de aparecer en el inventario de mock."]
    asyncio.run(lab.cycle(snapshot()))
    assert lab.alerts() == []


def test_inactive_alert_is_bounded_and_never_raised_for_resources_born_disabled(lab):
    born_disabled = snapshot(ssids=[InventorySsid(external_id="s9", name="Reserva", enabled=False, vlan_tag=20)])
    asyncio.run(lab.cycle(born_disabled))
    assert lab.alerts() == []  # nunca estuvo activo: no es una caída inesperada
    asyncio.run(lab.cycle(snapshot(ssids=[])))
    assert keys(lab) == ["El SSID Reserva dejó de aparecer en el inventario de mock."]
    # Una baja deliberada no queda como alerta permanente.
    asyncio.run(lab.cycle(snapshot(ssids=[]), advance=int(timedelta(hours=25).total_seconds())))
    assert lab.alerts() == []

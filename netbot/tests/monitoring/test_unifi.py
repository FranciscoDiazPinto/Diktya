"""Adaptador UniFi contra respuestas con la forma del OpenAPI oficial 10.6.106."""

import httpx
import pytest
from pydantic import SecretStr

from app.monitoring.exceptions import ProviderInvalidResponseError
from app.monitoring.providers.unifi import UnifiClient, UnifiMonitoringProvider, unifi_base_url
from app.monitoring.schemas import DeviceState, DeviceType, IssueKind

SITE = "11111111-1111-4111-8111-111111111111"
ROOT = "/proxy/network/integration/v1"
NET_DEFAULT, NET_GUEST = "n-default", "n-guest"


def page(items, offset=0, limit=200):
    chunk = items[offset:offset + limit]
    return {"offset": offset, "limit": limit, "count": len(chunk), "totalCount": len(items), "data": chunk}


DEVICES = [
    {"id": "d-ap", "name": "AP Hall", "model": "U7-Pro", "macAddress": "AA:BB:CC:00:00:01", "ipAddress": "10.0.0.2",
     "state": "ONLINE", "supported": True, "firmwareUpdatable": False, "features": ["accessPoint"], "interfaces": ["radios"]},
    {"id": "d-sw", "name": "Core", "model": "USW", "macAddress": "aa:bb:cc:00:00:02", "ipAddress": "10.0.0.3",
     "state": "ISOLATED", "supported": True, "firmwareUpdatable": False, "features": ["switching"], "interfaces": ["ports"]},
    {"id": "d-gw", "name": "GW", "model": "X", "macAddress": "bad", "ipAddress": "10.0.0.1",
     "state": "UPDATING", "supported": True, "firmwareUpdatable": False, "features": ["gateway"], "interfaces": []},
    {"id": "d-new", "name": "?", "model": "Y", "macAddress": "aa:bb:cc:00:00:04", "ipAddress": "10.0.0.4",
     "state": "U5G_INCORRECT_TOPOLOGY", "supported": True, "firmwareUpdatable": False, "features": [], "interfaces": []},
]
NETWORKS = [
    {"id": NET_DEFAULT, "name": "Default", "vlanId": 1, "default": True, "enabled": True, "management": "GATEWAY", "metadata": {"origin": "SYSTEM_DEFINED"}},
    {"id": NET_GUEST, "name": "Invitados", "vlanId": 20, "default": False, "enabled": False, "management": "GATEWAY", "metadata": {"origin": "USER_DEFINED"}},
]
BROADCASTS = [
    {"id": "w-1", "name": "Feria", "type": "STANDARD", "enabled": True, "metadata": {"origin": "USER_DEFINED"},
     "securityConfiguration": {"type": "WPA2_PERSONAL"}, "network": {"type": "SPECIFIC", "networkId": NET_GUEST}, "broadcastingFrequenciesGHz": [2.4, 5]},
    {"id": "w-2", "name": "Nativa", "type": "STANDARD", "enabled": True, "metadata": {"origin": "USER_DEFINED"},
     "securityConfiguration": {"type": "OPEN"}, "broadcastingFrequenciesGHz": [5]},
    {"id": "w-3", "name": "Rota", "type": "IOT_OPTIMIZED", "enabled": False, "metadata": {"origin": "USER_DEFINED"},
     "securityConfiguration": {"type": "WPA3_PERSONAL"}, "network": {"type": "SPECIFIC", "networkId": "no-existe"}},
]


def build(overrides=None, site="default"):
    overrides = overrides or {}
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path.removeprefix(ROOT)
        if path in overrides:
            value = overrides[path]
            return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
        offset = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", 25))
        routes = {"/sites": [{"id": SITE, "internalReference": "default", "name": "Recinto"}],
                  f"/sites/{SITE}/devices": DEVICES, f"/sites/{SITE}/networks": NETWORKS,
                  f"/sites/{SITE}/wifi/broadcasts": BROADCASTS}
        if path == "/info":
            return httpx.Response(200, json={"applicationVersion": "10.6.106"})
        return httpx.Response(200, json=page(routes[path], offset, limit))

    client = UnifiClient("https://console.test", SecretStr("secret-key"), transport=httpx.MockTransport(handler))
    return UnifiMonitoringProvider(client, site=site), seen


async def test_inventory_normalizes_devices_vlans_and_ssids():
    provider, seen = build()
    result = await provider.collect_inventory()
    assert result.issues == []
    snapshot = result.data
    assert snapshot.version == "10.6.106"
    by_id = {d.external_id: d for d in snapshot.devices}
    assert (by_id["d-ap"].device_type, by_id["d-ap"].state) == (DeviceType.ACCESS_POINT, DeviceState.ONLINE)
    assert by_id["d-ap"].mac_address == "aa:bb:cc:00:00:01"
    assert (by_id["d-sw"].device_type, by_id["d-sw"].state) == (DeviceType.SWITCH, DeviceState.DEGRADED)
    assert (by_id["d-gw"].device_type, by_id["d-gw"].state) == (DeviceType.GATEWAY, DeviceState.MAINTENANCE)
    assert by_id["d-gw"].mac_address is None
    assert (by_id["d-new"].device_type, by_id["d-new"].state) == (DeviceType.UNKNOWN, DeviceState.UNKNOWN)
    assert {v.tag: v.enabled for v in snapshot.vlans} == {1: True, 20: False}
    ssids = {s.name: s for s in snapshot.ssids}
    assert ssids["Feria"].vlan_tag == 20 and ssids["Feria"].security == "WPA2_PERSONAL"
    assert ssids["Nativa"].vlan_tag == 1  # sin referencia usa la red por defecto
    assert ssids["Rota"].vlan_tag is None  # referencia rota: desconocida, no la de defecto
    assert all(r.method == "GET" for r in seen)
    assert all(r.headers["x-api-key"] == "secret-key" for r in seen)


async def test_every_page_is_read():
    many = [{**DEVICES[0], "id": f"d-{i}"} for i in range(450)]
    provider, seen = build()

    def handler(request):
        path = request.url.path.removeprefix(ROOT)
        offset = int(request.url.params.get("offset", 0))
        if path == "/sites":
            return httpx.Response(200, json=page([{"id": SITE, "internalReference": "default", "name": "R"}]))
        if path.endswith("/devices"):
            return httpx.Response(200, json=page(many, offset, 200))
        return httpx.Response(200, json=page([] if path != "/info" else [], offset))

    client = UnifiClient("https://c.test", SecretStr("k"), transport=httpx.MockTransport(handler))
    result = await UnifiMonitoringProvider(client).collect_inventory()
    assert len(result.data.devices) == 450


@pytest.mark.parametrize("payload", [
    {"data": []},  # sin totalCount
    {"data": "x", "totalCount": 1},
    {"data": [], "totalCount": 3},  # promete más de lo que entrega: no se trunca en silencio
])
async def test_incoherent_listing_is_rejected(payload):
    client = UnifiClient("https://c.test", SecretStr("k"), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    with pytest.raises(ProviderInvalidResponseError):
        await client.get_all("/sites")


@pytest.mark.parametrize("status, kind", [(401, IssueKind.AUTHENTICATION), (403, IssueKind.PERMISSION),
                                          (404, IssueKind.NOT_SUPPORTED), (429, IssueKind.RATE_LIMIT),
                                          (500, IssueKind.SERVER_ERROR), (302, IssueKind.INVALID_RESPONSE)])
async def test_http_errors_are_typed_and_never_leak_the_key(status, kind):
    provider, _ = build({"/sites": httpx.Response(status)})
    result = await provider.collect_inventory()
    assert result.data is None
    assert result.issues[0].kind == kind
    assert "secret-key" not in repr(result)


async def test_timeout_is_reported_without_raising():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = UnifiClient("https://c.test", SecretStr("k"), transport=httpx.MockTransport(handler))
    result = await UnifiMonitoringProvider(client).collect_inventory()
    assert result.data is None and result.issues[0].kind == IssueKind.TIMEOUT


async def test_failed_section_stays_none_and_does_not_look_empty():
    provider, _ = build({f"/sites/{SITE}/networks": httpx.Response(500)})
    result = await provider.collect_inventory()
    assert result.data.vlans is None and len(result.data.devices) == 4
    assert all(s.vlan_tag is None for s in result.data.ssids)
    assert [i.component for i in result.issues] == ["unifi.networks"]


async def test_unknown_site_is_a_configuration_issue():
    provider, _ = build(site="otro")
    result = await provider.collect_inventory()
    assert result.data is None and result.issues[0].kind == IssueKind.CONFIGURATION


def test_transport_urls_follow_the_official_servers():
    assert unifi_base_url(transport="direct", base_url="https://c.test/", console_id=None) == "https://c.test"
    assert unifi_base_url(transport="connector", base_url=None, console_id="abc") == \
        "https://api.ui.com/v1/connector/consoles/abc"

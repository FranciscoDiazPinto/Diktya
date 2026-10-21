import httpx
from pydantic import SecretStr

from app.monitoring.providers.opnsense import (
    DnsmasqLeaseProvider,
    OPNsenseClient,
    OPNsenseMonitoringProvider,
)
from app.monitoring.providers.opnsense import provider as paths
from app.monitoring.schemas import IssueKind


def make_provider(outcome):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        return httpx.Response(200, json=outcome)

    client = OPNsenseClient(
        "https://fw.test",
        SecretStr("api-key"),
        SecretStr("api-secret"),
        transport=httpx.MockTransport(handler),
    )
    return OPNsenseMonitoringProvider(client, DnsmasqLeaseProvider(client)), requests


async def test_opnsense_vlan_inventory_uses_fixed_read_endpoint():
    provider, requests = make_provider({"rows": [
        {"if": "igc1", "tag": "20", "descr": "Evento", "vlanif": "vlan01"}
    ]})

    result = await provider.get_vlan_inventory()

    assert [item.model_dump() for item in result.data] == [{
        "parent_interface": "igc1", "tag": 20,
        "description": "Evento", "interface_name": "vlan01",
    }]
    assert result.issues == []
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == paths.PATH_VLAN_SEARCH


async def test_opnsense_vlan_inventory_fails_closed_on_malformed_data():
    provider, _ = make_provider({"unexpected": []})

    result = await provider.get_vlan_inventory()

    assert result.data is None
    assert result.issues[0].kind == IssueKind.INVALID_RESPONSE


async def test_opnsense_vlan_inventory_sanitizes_auth_failure():
    provider, _ = make_provider(httpx.Response(401, text="api-secret must not leak"))

    result = await provider.get_vlan_inventory()

    assert result.data is None
    assert result.issues[0].kind == IssueKind.AUTHENTICATION
    assert "api-secret" not in result.issues[0].message

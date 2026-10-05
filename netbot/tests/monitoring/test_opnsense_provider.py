import httpx
import pytest
from pydantic import SecretStr

from app.monitoring.providers.opnsense import (
    DnsmasqLeaseProvider,
    KeaLeaseProvider,
    OPNsenseClient,
    OPNsenseMonitoringProvider,
)
from app.monitoring.providers.opnsense import provider as paths
from app.monitoring.schemas import IssueKind

from . import fixtures as fx

HAPPY_ROUTES = {
    paths.PATH_CPU_STREAM: httpx.Response(200, content=fx.CPU_SSE),
    paths.PATH_SYSTEM_RESOURCES: fx.SYSTEM_RESOURCES,
    paths.PATH_SYSTEM_INFORMATION: fx.SYSTEM_INFORMATION,
    paths.PATH_SYSTEM_TIME: fx.SYSTEM_TIME,
    paths.PATH_SYSTEM_TEMPERATURE: fx.SYSTEM_TEMPERATURE,
    paths.PATH_INTERFACES_INFO: fx.INTERFACES_INFO,
    paths.PATH_INTERFACE_STATISTICS: fx.INTERFACE_STATISTICS,
    paths.PATH_TRAFFIC_INTERFACE: fx.TRAFFIC_INTERFACE,
    paths.PATH_FIREWALL_STATS: fx.FIREWALL_STATS,
    paths.PATH_PF_STATISTICS: fx.PF_INFO,
    paths.PATH_FIREWALL_LOG: fx.FIREWALL_LOG,
    "/api/dnsmasq/leases/search": fx.DNSMASQ_LEASES,
    "/api/kea/leases4/search": fx.KEA_LEASES,
}


def build(overrides: dict | None = None, *, kea: bool = False):
    routes = {**HAPPY_ROUTES, **(overrides or {})}

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = routes[request.url.path]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        return httpx.Response(200, json=outcome)

    client = OPNsenseClient(
        "https://fw.test",
        SecretStr("k"),
        SecretStr("s"),
        transport=httpx.MockTransport(handler),
    )
    dhcp = KeaLeaseProvider(client) if kea else DnsmasqLeaseProvider(client)
    return OPNsenseMonitoringProvider(client, dhcp)


async def test_system_metrics_happy_path():
    result = await build().get_system_metrics()
    assert result.issues == []
    data = result.data
    assert data.hostname == "fw-evento.localdomain"
    assert data.version == "OPNsense 25.1.9-amd64"
    assert data.cpu_percent == 14.0
    assert data.uptime_seconds == 2 * 86400 + 3 * 3600 + 4 * 60 + 5
    assert data.memory.used_percent == 25.0
    assert data.temperature.available is True and data.temperature.value_celsius == 51.5


async def test_missing_temperature_endpoint_is_optional_and_not_fatal():
    result = await build({paths.PATH_SYSTEM_TEMPERATURE: httpx.Response(404)}).get_system_metrics()
    assert result.data.temperature.available is False
    assert result.data.cpu_percent == 14.0  # el resto sigue intacto
    [issue] = result.issues
    assert (issue.component, issue.kind, issue.optional) == (
        "system.temperature",
        IssueKind.NOT_SUPPORTED,
        True,
    )


async def test_failing_required_endpoint_degrades_but_keeps_the_rest():
    result = await build({paths.PATH_SYSTEM_RESOURCES: httpx.Response(500)}).get_system_metrics()
    assert result.data.memory is None
    assert result.data.cpu_percent == 14.0 and result.data.hostname
    [issue] = result.issues
    assert issue.kind == IssueKind.SERVER_ERROR and issue.optional is False


async def test_cpu_timeout_does_not_break_the_system_collection():
    result = await build({paths.PATH_CPU_STREAM: httpx.ReadTimeout("slow")}).get_system_metrics()
    assert result.data.cpu_percent is None and result.data.memory is not None
    assert result.issues[0].kind == IssueKind.TIMEOUT


async def test_everything_down_yields_no_data_and_one_issue_per_component():
    down = httpx.ConnectError("refused")
    overrides = {
        p: down
        for p in (
            paths.PATH_SYSTEM_RESOURCES,
            paths.PATH_SYSTEM_INFORMATION,
            paths.PATH_SYSTEM_TIME,
            paths.PATH_SYSTEM_TEMPERATURE,
            paths.PATH_CPU_STREAM,
        )
    }
    result = await build(overrides).get_system_metrics()
    assert result.data is None
    assert {i.kind for i in result.issues} == {IssueKind.CONNECTION}
    assert len(result.issues) == 5


async def test_garbage_payload_does_not_raise():
    result = await build(
        {paths.PATH_SYSTEM_RESOURCES: "garbage", paths.PATH_SYSTEM_TIME: []}
    ).get_system_metrics()
    assert result.data.memory is None and result.data.uptime_seconds is None


async def test_interfaces_merge_and_statistics_failure_is_optional():
    result = await build(
        {paths.PATH_INTERFACE_STATISTICS: httpx.Response(404)}
    ).get_interface_metrics()
    assert {i.interface_id for i in result.data} == {"wan", "lan", "opt1"}
    assert [i.optional for i in result.issues] == [True]


async def test_interfaces_total_failure():
    boom = httpx.ConnectError("refused")
    overrides = {
        p: boom
        for p in (
            paths.PATH_INTERFACES_INFO,
            paths.PATH_INTERFACE_STATISTICS,
            paths.PATH_TRAFFIC_INTERFACE,
        )
    }
    result = await build(overrides).get_interface_metrics()
    assert result.data is None and len(result.issues) == 3


@pytest.mark.parametrize(("kea", "expected"), [(False, 3), (True, 2)])
async def test_clients_from_dnsmasq_or_kea(kea, expected):
    result = await build(kea=kea).get_clients()
    assert len(result.data) == expected  # dnsmasq descarta la fila con MAC inválida
    assert result.issues == []


async def test_clients_auth_failure_is_reported():
    result = await build({"/api/dnsmasq/leases/search": httpx.Response(401)}).get_clients()
    assert result.data is None
    assert result.issues[0].kind == IssueKind.AUTHENTICATION


async def test_firewall_events_and_limit():
    result = await build().get_firewall_events(limit=2)
    assert len(result.data) == 2
    assert result.data[0].timestamp > result.data[1].timestamp


async def test_firewall_stats_partial_failure_degrades():
    result = await build({paths.PATH_FIREWALL_STATS: httpx.Response(404)}).get_firewall_statistics()
    assert result.data.states.current_entries == 1523
    assert result.data.packets_passed is None
    assert result.issues[0].optional is False


async def test_issue_messages_never_leak_urls_or_credentials():
    result = await build({paths.PATH_SYSTEM_RESOURCES: httpx.Response(401)}).get_system_metrics()
    text = " ".join(i.message for i in result.issues)
    assert "fw.test" not in text and "/api/" not in text

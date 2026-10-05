import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.router import router
from app.monitoring.service import MonitoringService

BASE = "/api/v1/monitoring"


def make_client(scenario="healthy") -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.monitoring_service = MonitoringService(
        MockMonitoringProvider(scenario=scenario), cache_ttl_seconds=0
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    ["/system", "/interfaces", "/clients", "/firewall/stats", "/firewall/events"],
)
def test_all_endpoints_respond_with_the_common_envelope(path):
    response = make_client().get(BASE + path)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["source"] == "mock"
    assert body["issues"] == []
    assert body["collected_at"]
    assert body["data"] is not None


def test_system_payload_shape():
    data = make_client().get(BASE + "/system").json()["data"]
    assert set(data) >= {"hostname", "uptime_seconds", "cpu_percent", "memory", "temperature"}
    assert set(data["memory"]) == {"total_bytes", "used_bytes", "free_bytes", "used_percent"}
    assert set(data["temperature"]) == {"available", "value_celsius"}


def test_interfaces_and_clients_shape():
    client = make_client()
    interface = client.get(BASE + "/interfaces").json()["data"][0]
    assert set(interface) == {
        "interface_id",
        "name",
        "description",
        "status",
        "ip_addresses",
        "traffic",
    }
    assert interface["status"] in {"up", "down", "unknown"}
    lease = client.get(BASE + "/clients").json()["data"][0]
    assert set(lease) == {
        "ip_address",
        "mac_address",
        "hostname",
        "interface",
        "expires_at",
        "active",
    }


def test_events_limit_and_action_filter():
    client = make_client()
    events = client.get(BASE + "/firewall/events", params={"limit": 7, "action": "block"}).json()[
        "data"
    ]
    assert len(events) == 7 and all(e["action"] == "block" for e in events)
    event = events[0]
    assert set(event) == {
        "timestamp",
        "action",
        "interface",
        "source_ip",
        "source_port",
        "destination_ip",
        "destination_port",
        "protocol",
        "rule_id",
    }


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"action": "drop"}])
def test_events_query_validation(params):
    assert make_client().get(BASE + "/firewall/events", params=params).status_code == 422


def test_degraded_scenario_returns_200_with_issues():
    client = make_client("degraded")
    system = client.get(BASE + "/system")
    assert system.status_code == 200
    body = system.json()
    assert body["status"] == "ok"  # el único incidente (temperatura) es opcional
    assert body["data"]["temperature"]["available"] is False
    assert body["issues"][0]["optional"] is True

    stats = client.get(BASE + "/firewall/stats")
    assert stats.status_code == 503  # sin ningún dato
    assert stats.json()["status"] == "unavailable"


def test_outage_returns_503_with_the_same_envelope_on_every_endpoint():
    client = make_client("outage")
    for path in ("/system", "/interfaces", "/clients", "/firewall/stats", "/firewall/events"):
        response = client.get(BASE + path)
        assert response.status_code == 503, path
        body = response.json()
        assert body["status"] == "unavailable" and body["data"] is None
        assert body["issues"] and body["issues"][0]["kind"] == "connection"


def test_responses_do_not_leak_raw_opnsense_keys():
    client = make_client()
    text = " ".join(
        json.dumps(client.get(BASE + p).json())
        for p in ("/system", "/interfaces", "/clients", "/firewall/stats", "/firewall/events")
    )
    for raw_key in (
        "bytes received",
        "received-bytes",
        "hwaddr",
        "__timestamp__",
        "srcport",
        "protoname",
    ):
        assert raw_key not in text

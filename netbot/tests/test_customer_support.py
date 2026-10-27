import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.errors import NotFound
from app.auth.roles import effective_permissions
from app.chat.models import ChatMessage
from app.chat.provider import ProviderCompletion, ProviderToolCall
from app.chat.router import get_chat_service
from app.chat.service import ChatService
from app.chat.support import CustomerSupport
from app.core.config import Settings, get_settings
from app.main import app
from app.monitoring.dependencies import get_monitoring_service
from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.schemas import MonitoringResponse, MonitoringStatus, InterfaceMetrics, LinkStatus
from app.monitoring.service import MonitoringService
from app.networks.models import NetworkAssignment
from app.networks.support_models import NetworkSupportConfig, SupportAudit
from app.tickets.models import Ticket, TicketEvent
from tests.test_scoped_chat import scoped  # noqa: F401 -- reuse authenticated fixtures

TEST_PASSPHRASE = "test-only-wifi-access"


@pytest.fixture
def support_env(scoped, db_session):
    users, headers, networks, _ = scoped
    secrets = {
        "access-a": {"site": "sitio", "external_id": "A", "ssid": "SSID-A", "security": "wpa2-personal", "passphrase": TEST_PASSPHRASE},
        "access-b": {"site": "sitio", "external_id": "B", "ssid": "SSID-B", "security": "wpa3-personal", "passphrase": "test-only-access-B"},
    }
    settings = Settings(_env_file=None, monitoring_site_id="sitio", wifi_access_credentials_json=json.dumps(secrets))
    for network, ref, interface_id in zip(networks, ["access-a", "access-b"], ["opt1", "opt2"]):
        db_session.add(NetworkSupportConfig(network_id=network.id, credential_ref=ref, monitoring_interface_id=interface_id))
    db_session.commit()
    monitoring = MonitoringService(MockMonitoringProvider(), cache_ttl_seconds=0)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_monitoring_service] = lambda: monitoring
    return users, headers, networks, settings, monitoring


def open_ticket(client, headers, network_id, key=None, **extra):
    return client.post("/api/v1/tickets", headers=headers, json={
        "network_id": network_id, "summary": "No puedo conectarme", "description": "La red no aparece en mi equipo.",
        "request_key": key or str(uuid4()), **extra,
    })


def test_access_is_scoped_uncached_and_audited_without_storing_secrets(client, db_session, support_env):
    users, headers, networks, _, _ = support_env
    own = client.post(f"/api/v1/networks/{networks[0].id}/access", headers=headers["a"])
    assert own.status_code == 200, own.text
    assert own.json()["passphrase"] == TEST_PASSPHRASE
    assert own.headers["cache-control"] == "no-store, private"
    assert own.headers["pragma"] == "no-cache"
    audit = db_session.scalar(select(SupportAudit))
    assert (audit.actor_id, audit.network_id, audit.action) == (users["a"].id, networks[0].id, "wifi_access.revealed")
    assert db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert client.post(f"/api/v1/networks/{networks[1].id}/access", headers=headers["a"]).status_code == 404
    assert client.post(f"/api/v1/networks/{networks[0].id}/access").status_code == 401
    assert TEST_PASSPHRASE not in client.get("/api/v1/networks", headers=headers["a"]).text


@pytest.mark.parametrize("value", ["not-json", "null", "[]", '{"access-a":{"passphrase":"test-only-wifi-access","security":"bad"}}'])
def test_bad_secret_configuration_fails_closed_without_exposing_values(client, support_env, value):
    _, headers, networks, settings, _ = support_env
    broken = settings.model_copy(update={"wifi_access_credentials_json": None})
    from pydantic import SecretStr
    broken.wifi_access_credentials_json = SecretStr(value)
    app.dependency_overrides[get_settings] = lambda: broken
    response = client.post(f"/api/v1/networks/{networks[0].id}/access", headers=headers["a"])
    assert response.status_code == 503
    assert TEST_PASSPHRASE not in response.text
    assert "no-store" in response.headers["cache-control"]


def test_secret_reference_cannot_deliver_another_networks_credentials(client, db_session, support_env):
    _, headers, networks, _, _ = support_env
    db_session.get(NetworkSupportConfig, networks[0].id).credential_ref = "access-b"
    db_session.commit()
    response = client.post(f"/api/v1/networks/{networks[0].id}/access", headers=headers["a"])
    assert response.status_code == 503
    assert "test-only-access-B" not in response.text


def test_only_admin_can_configure_support_and_cannot_upload_plaintext_password(client, support_env):
    _, headers, networks, _, _ = support_env
    path = f"/admin/networks/{networks[0].id}/support"
    payload = {"credential_ref": "access-a", "monitoring_interface_id": "opt1"}
    assert client.put(path, json=payload, headers=headers["tech"]).status_code == 403
    assert client.put(path, json=payload, headers=headers["admin"]).status_code == 200
    assert client.put(path, json={**payload, "passphrase": TEST_PASSPHRASE}, headers=headers["admin"]).status_code == 422
    assert client.get(path, headers=headers["admin"]).json() == payload
    assert client.get(path, headers=headers["a"]).status_code == 403


def test_admin_can_inspect_audit_without_secret_values(client, support_env):
    _, headers, networks, _, _ = support_env
    client.post(f"/api/v1/networks/{networks[0].id}/access", headers=headers["a"])
    path = f"/admin/networks/{networks[0].id}/support-audit"
    response = client.get(path, headers=headers["admin"])
    assert response.status_code == 200
    assert response.json()[0]["action"] == "wifi_access.revealed"
    assert TEST_PASSPHRASE not in response.text
    assert client.get(path, headers=headers["a"]).status_code == 403


def test_open_wifi_network_never_returns_a_password(client, support_env):
    _, headers, networks, settings, _ = support_env
    from pydantic import SecretStr
    settings.wifi_access_credentials_json = SecretStr(json.dumps({
        "access-a": {"site": "sitio", "external_id": "A", "ssid": "SSID-A", "security": "open"},
    }))
    response = client.post(f"/api/v1/networks/{networks[0].id}/access", headers=headers["a"])
    assert response.status_code == 200
    assert response.json()["passphrase"] is None


def test_active_interface_is_partial_and_never_claims_wifi_or_internet(client, support_env):
    _, headers, networks, _, _ = support_env
    response = client.get(f"/api/v1/networks/{networks[0].id}/status", headers=headers["a"])
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "partially_verified"
    assert data["interface_status"] == "up"
    assert data["wifi_status"] == data["internet_status"] == "unverified"
    assert data["simulated"] is True
    assert "10.20." not in response.text and "SSID-B" not in response.text
    assert client.get(f"/api/v1/networks/{networks[1].id}/status", headers=headers["a"]).status_code == 404


@pytest.mark.parametrize("scenario, expected", [("degraded", "issue_detected"), ("outage", "unknown")])
def test_down_interface_and_missing_telemetry_are_different(client, support_env, scenario, expected):
    _, headers, networks, _, _ = support_env
    app.dependency_overrides[get_monitoring_service] = lambda: MonitoringService(MockMonitoringProvider(scenario=scenario), cache_ttl_seconds=0)
    data = client.get(f"/api/v1/networks/{networks[1].id}/status", headers=headers["b"]).json()
    assert data["state"] == expected
    assert data["interface_status"] == ("down" if scenario == "degraded" else "unknown")


@pytest.mark.parametrize("reason", ["missing_mapping", "other_site", "stale", "duplicate", "incomplete", "wrong_source"])
def test_ambiguous_or_stale_telemetry_never_becomes_a_positive_diagnosis(client, db_session, support_env, reason):
    _, headers, networks, _, _ = support_env
    if reason == "missing_mapping":
        db_session.get(NetworkSupportConfig, networks[0].id).monitoring_interface_id = None
    if reason == "other_site":
        networks[0].site = "otro-sitio"
    db_session.commit()

    class Telemetry:
        async def get_interfaces(self):
            assert reason not in {"missing_mapping", "other_site"}
            interface = InterfaceMetrics(interface_id="opt1", name="private-device", status=LinkStatus.UP)
            return MonitoringResponse(status=MonitoringStatus.DEGRADED if reason == "incomplete" else MonitoringStatus.OK,
                                      source="opnsense" if reason == "wrong_source" else "mock",
                                      collected_at=datetime.now(timezone.utc) - timedelta(seconds=120 if reason == "stale" else 0),
                                      data=[interface, interface] if reason == "duplicate" else [interface])

    app.dependency_overrides[get_monitoring_service] = Telemetry
    response = client.get(f"/api/v1/networks/{networks[0].id}/status", headers=headers["a"])
    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    assert "private-device" not in response.text


def test_ticket_creation_retries_are_idempotent_and_payload_mismatch_is_rejected(client, db_session, support_env):
    users, headers, networks, _, _ = support_env
    key = str(uuid4())
    first = open_ticket(client, headers["a"], networks[0].id, key)
    assert first.status_code == 201, first.text
    again = open_ticket(client, headers["a"], networks[0].id, key)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert first.json()["created_by_id"] == users["a"].id
    assert first.json()["network_snapshot"]["state"] == "partially_verified"
    assert db_session.scalar(select(func.count()).select_from(Ticket)) == 1
    assert db_session.scalar(select(func.count()).select_from(TicketEvent)) == 1
    assert open_ticket(client, headers["a"], networks[0].id, key, summary="Otra solicitud").status_code == 409
    assert open_ticket(client, headers["a"], networks[1].id).status_code == 404
    assert open_ticket(client, headers["a"], networks[0].id, created_by_id=users["b"].id).status_code == 422


def test_customer_cannot_read_other_customers_ticket_even_on_shared_network(client, db_session, support_env):
    users, headers, networks, _, _ = support_env
    ticket = open_ticket(client, headers["a"], networks[0].id).json()
    db_session.add(NetworkAssignment(user_id=users["b"].id, network_id=networks[0].id))
    db_session.commit()
    assert client.get("/api/v1/tickets", headers=headers["b"]).json() == []
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=headers["b"]).status_code == 404
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=headers["tech"]).status_code == 200
    foreign = open_ticket(client, headers["b"], networks[1].id).json()
    assert client.get(f"/api/v1/tickets/{foreign['id']}", headers=headers["tech"]).status_code == 404
    assert client.patch(f"/api/v1/tickets/{foreign['id']}", json={"status": "in_progress", "version": 0, "note": "Revisando"}, headers=headers["tech"]).status_code == 404


def test_technician_can_manage_assigned_tickets_with_version_and_public_history(client, support_env):
    _, headers, networks, _, _ = support_env
    ticket = open_ticket(client, headers["a"], networks[0].id).json()
    path = f"/api/v1/tickets/{ticket['id']}"
    payload = {"status": "in_progress", "version": 0, "note": "Estamos revisando la conectividad."}
    assert client.patch(path, json=payload, headers=headers["a"]).status_code == 403
    assert client.patch(path, json={**payload, "status": "closed"}, headers=headers["tech"]).status_code == 409
    changed = client.patch(path, json=payload, headers=headers["tech"])
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 1
    assert client.patch(path, json=payload, headers=headers["tech"]).status_code == 409
    details = client.get(path, headers=headers["a"]).json()
    assert [e["status"] for e in details["events"]] == ["open", "in_progress"]
    assert details["events"][-1]["note"] == payload["note"]


def test_revocation_removes_access_to_credentials_status_and_tickets(client, db_session, support_env):
    users, headers, networks, _, _ = support_env
    ticket = open_ticket(client, headers["a"], networks[0].id).json()
    db_session.delete(db_session.get(NetworkAssignment, (networks[0].id, users["a"].id)))
    db_session.commit()
    assert client.post(f"/api/v1/networks/{networks[0].id}/access", headers=headers["a"]).status_code == 404
    assert client.get(f"/api/v1/networks/{networks[0].id}/status", headers=headers["a"]).status_code == 404
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=headers["a"]).status_code == 404
    assert client.get("/api/v1/tickets", headers=headers["a"]).json() == []


def test_no_telemetry_does_not_prevent_reporting_a_problem(client, db_session, support_env):
    _, headers, networks, _, _ = support_env
    db_session.get(NetworkSupportConfig, networks[0].id).monitoring_interface_id = None
    db_session.commit()
    response = open_ticket(client, headers["a"], networks[0].id)
    assert response.status_code == 201
    assert response.json()["network_snapshot"]["state"] == "unknown"


def test_revocation_while_collecting_status_prevents_ticket_creation(client, db_session, support_env):
    users, headers, networks, _, monitoring = support_env

    class RevokingSource:
        async def get_interfaces(self):
            data = await monitoring.get_interfaces()
            db_session.delete(db_session.get(NetworkAssignment, (networks[0].id, users["a"].id)))
            db_session.commit()
            return data

    app.dependency_overrides[get_monitoring_service] = RevokingSource
    assert open_ticket(client, headers["a"], networks[0].id).status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Ticket)) == 0


def test_chat_prepares_actions_without_saving_ticket_or_exposing_password(client, db_session, support_env):
    users, headers, networks, settings, monitoring = support_env

    class Provider:
        def __init__(self):
            self.requests = []

        async def complete(self, **kwargs):
            self.requests.append(json.dumps(kwargs, ensure_ascii=False))
            if len(self.requests) == 1:
                return ProviderCompletion(content=None, tool_calls=(
                    ProviderToolCall(id="wifi", name="offer_wifi_access", arguments={"network_id": networks[0].id}),
                    ProviderToolCall(id="ticket", name="prepare_support_ticket", arguments={"network_id": networks[0].id, "summary": "No aparece la red", "description": "Solicito revisión técnica."}),
                ))
            return ProviderCompletion(content="Puedes ver tu acceso y confirmar la solicitud de soporte con los botones.")

    provider = Provider()
    service = ChatService(settings=settings, provider=provider, monitoring_service=monitoring,
                          customer_support=CustomerSupport(db_session, users["a"], monitoring, settings))
    app.dependency_overrides[get_chat_service] = lambda: service
    response = client.post("/api/v1/chat/messages", json={"message": "Necesito mi acceso y abrir un ticket."}, headers=headers["a"])
    assert response.status_code == 200, response.text
    assert response.json()["wifi_access_action"] == {"network_id": networks[0].id, "ssid": "SSID-A"}
    assert response.json()["ticket_proposal"]["network_id"] == networks[0].id
    assert db_session.scalar(select(func.count()).select_from(Ticket)) == 0
    assert TEST_PASSPHRASE not in "".join(provider.requests)
    assert TEST_PASSPHRASE not in response.text
    assert TEST_PASSPHRASE not in "".join(db_session.scalars(select(ChatMessage.content)).all())


@pytest.mark.parametrize("own_network", [True, False])
def test_default_chat_factory_binds_support_to_authenticated_user(client, support_env, monkeypatch, own_network):
    from app.chat import router as chat_router
    _, headers, networks, settings, _ = support_env
    network_id = networks[1 if own_network else 0].id

    class Provider:
        def __init__(self):
            self.called = False

        async def complete(self, **kwargs):
            if self.called:
                return ProviderCompletion(content="Usa el botón para ver el acceso.")
            self.called = True
            return ProviderCompletion(content=None, tool_calls=(
                ProviderToolCall(id="access", name="offer_wifi_access", arguments={"network_id": network_id}),
            ))

    app.dependency_overrides.pop(get_chat_service)
    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "OpenRouterProvider", lambda _: Provider())
    response = client.post("/api/v1/chat/messages", json={"message": "Dame el acceso"}, headers=headers["b"])
    assert response.status_code == (200 if own_network else 404), response.text
    if own_network:
        assert response.json()["wifi_access_action"]["ssid"] == "SSID-B"
        assert "test-only-access-B" not in response.text


@pytest.mark.asyncio
async def test_ticket_tool_filters_owner_and_conversation_scope(client, db_session, support_env):
    users, headers, networks, settings, monitoring = support_env
    ticket_a = open_ticket(client, headers["a"], networks[0].id).json()
    open_ticket(client, headers["b"], networks[1].id)
    support = CustomerSupport(db_session, users["admin"], monitoring, settings)
    result = await support.invoke("list_support_tickets", {}, {networks[0].id})
    assert [ticket["id"] for ticket in result["data"]] == [ticket_a["id"]]
    db_session.add(NetworkAssignment(user_id=users["b"].id, network_id=networks[0].id))
    db_session.commit()
    support = CustomerSupport(db_session, users["b"], monitoring, settings)
    result = await support.invoke("list_support_tickets", {}, {networks[0].id})
    assert result["data"] == []


@pytest.mark.asyncio
async def test_chat_tools_cannot_leave_selected_network_or_use_model_chosen_owner(db_session, support_env):
    users, _, networks, settings, monitoring = support_env
    from app.chat.tools import invoke_tool, ChatToolError

    support = CustomerSupport(db_session, users["admin"], monitoring, settings)
    allowed = [{"id": networks[0].id}]
    with pytest.raises(NotFound) as error:
        await invoke_tool("get_network_status", {"network_id": networks[1].id}, monitoring,
                          effective_permissions(users["admin"]), networks=allowed, customer_support=support)
    assert error.value.detail == "Red no disponible en esta conversación."
    with pytest.raises(ChatToolError):
        await invoke_tool("offer_wifi_access", {"network_id": networks[0].id, "user_id": users["b"].id}, monitoring,
                          effective_permissions(users["admin"]), networks=allowed, customer_support=support)

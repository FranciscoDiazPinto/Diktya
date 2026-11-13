import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.changes.models import SsidVlanChangePlan, WifiScopeGrant
from app.changes.ssid_schemas import SsidVlanChangeConfirm, SsidVlanChangeProposal
from app.changes.ssid_service import SsidPlanService
from app.changes.wifi_inventory import WifiInventory
from app.changes.csv_service import utc_now
from app.core.errors import Conflict, NotFound, ServiceUnavailable
from tests.test_ssid_plans import ssid_setup


def _service(db_session, x):
    service = SsidPlanService(db_session, x.settings, monitoring=None)
    service.options = AsyncMock(return_value=(
        {"simulated": False, "networks": [{"id": "network-30", "tag": 30}]},
        [{"id": "ssid-123", "ssid": "WiFi-Invitados"}],
        "fingerprint-test",
    ))
    service.inventory.read_broadcast = AsyncMock(return_value={
        "id": "ssid-123", "ssid": "WiFi-Invitados", "network_id": "network-20",
    })
    return service


def _preview(service, x):
    return asyncio.run(service.propose_vlan_change(x.tech, SsidVlanChangeProposal(
        scope_id=x.scope, broadcast_id="ssid-123", network_id="network-30",
        purpose="Migración de VLAN",
    )))


def _confirm(service, x, plan, revision=None):
    return asyncio.run(service.confirm_vlan_change(
        x.tech, plan["id"], SsidVlanChangeConfirm(
            revision=plan["revision"] if revision is None else revision,
        ),
    ))


def test_vlan_change_proposal_valid():
    proposal = SsidVlanChangeProposal(
        scope_id=1, broadcast_id="ssid-123", network_id="network-30",
        purpose="Cambiar la VLAN del evento",
    )
    assert proposal.scope_id == 1
    assert proposal.broadcast_id == "ssid-123"
    assert proposal.network_id == "network-30"


def test_vlan_change_rejects_invalid_scope():
    with pytest.raises(ValidationError):
        SsidVlanChangeProposal(scope_id=0, broadcast_id="ssid-123", network_id="network-30", purpose="Prueba")


def test_vlan_change_rejects_empty_network():
    with pytest.raises(ValidationError):
        SsidVlanChangeProposal(scope_id=1, broadcast_id="ssid-123", network_id="", purpose="Prueba")


def test_vlan_change_rejects_extra_fields():
    with pytest.raises(ValidationError):
        SsidVlanChangeProposal(scope_id=1, broadcast_id="ssid-123", network_id="network-30", purpose="Prueba", confirmed=True)


def test_vlan_change_confirmation_schema_requires_sha256_revision():
    SsidVlanChangeConfirm(revision="a" * 64)
    for invalid in ("", "a" * 63, "g" * 64, "A" * 64):
        with pytest.raises(ValidationError):
            SsidVlanChangeConfirm(revision=invalid)
    with pytest.raises(ValidationError):
        SsidVlanChangeConfirm(revision="a" * 64, execute=True)


def _inventory(handler):
    settings = SimpleNamespace(
        unifi_inventory_mode="api", unifi_api_base_url="https://unifi.example.test/",
        unifi_api_key=SimpleNamespace(get_secret_value=lambda: "test-api-key"),
        unifi_ca_bundle=None, unifi_timeout_seconds=5,
    )
    return WifiInventory(settings, transport=httpx.MockTransport(handler))


def test_read_broadcast_returns_current_network():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path.endswith("/sites/demo-site/wifi/broadcasts/ssid-123")
        return httpx.Response(200, json={
            "id": "ssid-123", "name": "WiFi-Invitados",
            "network": {"type": "SPECIFIC", "networkId": "network-20"},
        })
    result = asyncio.run(_inventory(handler).read_broadcast("demo-site", "ssid-123"))
    assert result["ssid"] == "WiFi-Invitados"
    assert result["network_id"] == "network-20"
    assert result["network_type"] == "SPECIFIC"
    assert result["simulated"] is False


def test_read_broadcast_rejects_native_network():
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={
            "id": "ssid-123", "name": "WiFi-Invitados", "network": {"type": "NATIVE"},
        })
    with pytest.raises(ServiceUnavailable):
        asyncio.run(_inventory(handler).read_broadcast("demo-site", "ssid-123"))


def test_vlan_change_preview_valid(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    result = _preview(service, x)
    assert result["status"] == "preview"
    assert result["current_network_id"] == "network-20"
    assert result["target_network_id"] == "network-30"
    assert result["target_vlan"] == 30
    assert result["requires_confirmation"] is True
    assert result["executed"] is False


def test_vlan_change_preview_rejects_unauthorized_network(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    service.options.return_value = (
        {"simulated": False, "networks": []},
        [{"id": "ssid-123", "ssid": "WiFi-Invitados"}], "fingerprint-test",
    )
    with pytest.raises(Conflict):
        asyncio.run(service.propose_vlan_change(x.tech, SsidVlanChangeProposal(
            scope_id=x.scope, broadcast_id="ssid-123", network_id="network-999",
            purpose="Migración de VLAN",
        )))
    service.inventory.read_broadcast.assert_not_awaited()


def test_vlan_change_preview_is_persisted(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    result = _preview(service, x)
    assert result["status"] == "preview"
    assert result["executed"] is False
    assert result["requires_confirmation"] is True
    assert result["id"] and result["revision"]
    saved = db_session.get(SsidVlanChangePlan, result["id"])
    assert saved is not None
    assert saved.owner_id == x.tech.id
    assert saved.scope_id == x.scope
    assert saved.broadcast_id == "ssid-123"
    assert saved.current_network_id == "network-20"
    assert saved.target_network_id == "network-30"
    assert saved.status == "preview"
    assert saved.revision == result["revision"]
    assert saved.expires_at > saved.created_at
    assert saved.confirmed_at is None
    service.inventory.read_broadcast.assert_awaited_once()


def test_vlan_change_confirm_success_and_no_unifi_write(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    result = _confirm(service, x, plan)
    assert result["status"] == "confirmed"
    assert result["executed"] is False
    assert result["requires_confirmation"] is False
    assert result["confirmed_at"] is not None
    saved = db_session.get(SsidVlanChangePlan, plan["id"])
    assert saved.status == "confirmed"
    assert saved.confirmed_at is not None
    assert service.inventory.read_broadcast.await_count == 2


def test_vlan_change_confirm_is_idempotent(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    first = _confirm(service, x, plan)
    second = _confirm(service, x, plan)
    assert first == second
    assert second["status"] == "confirmed"
    assert service.options.await_count == 2  # propuesta + primera confirmación


def test_vlan_change_confirm_rejects_wrong_revision(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    with pytest.raises(Conflict):
        _confirm(service, x, plan, revision="0" * 64 if plan["revision"] != "0" * 64 else "1" * 64)
    assert db_session.get(SsidVlanChangePlan, plan["id"]).status == "preview"


def test_vlan_change_confirm_rejects_expired_plan(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    saved = db_session.get(SsidVlanChangePlan, plan["id"])
    saved.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(Conflict):
        _confirm(service, x, plan)
    assert saved.status == "preview"


def test_vlan_change_confirm_rejects_changed_fingerprint(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    options, existing, _ = service.options.return_value
    service.options.return_value = (options, existing, "fingerprint-changed")
    with pytest.raises(Conflict):
        _confirm(service, x, plan)
    assert db_session.get(SsidVlanChangePlan, plan["id"]).status == "preview"


def test_vlan_change_confirm_rejects_changed_current_vlan(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    service.inventory.read_broadcast.return_value = {
        "id": "ssid-123", "ssid": "WiFi-Invitados", "network_id": "network-40",
    }
    with pytest.raises(Conflict):
        _confirm(service, x, plan)
    assert db_session.get(SsidVlanChangePlan, plan["id"]).status == "preview"


def test_vlan_change_confirm_rejects_removed_target_network(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    _, existing, fingerprint = service.options.return_value
    service.options.return_value = ({"simulated": False, "networks": []}, existing, fingerprint)
    with pytest.raises(Conflict):
        _confirm(service, x, plan)


def test_vlan_change_confirm_rejects_revoked_scope(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    grant = db_session.get(WifiScopeGrant, (x.scope, x.tech.id))
    db_session.delete(grant)
    db_session.commit()
    with pytest.raises(NotFound):
        _confirm(service, x, plan)
    assert db_session.get(SsidVlanChangePlan, plan["id"]).status == "preview"


def test_vlan_change_confirm_rejects_other_owner(db_session, ssid_setup):
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    with pytest.raises(NotFound):
        asyncio.run(service.confirm_vlan_change(
            _other_owner(db_session, x),
            plan["id"], SsidVlanChangeConfirm(revision=plan["revision"]),
        ))


def _other_owner(db_session, x):
    from app.auth.models import User, Role
    from sqlalchemy import select
    from app.auth.security import hash_password
    role = db_session.scalar(select(Role).where(Role.name == 'tecnico'))
    other = User(email='other-h10@example.com', hashed_password=hash_password('test-password'), roles=[role])
    db_session.add(other)
    db_session.commit()
    return other

# H10: ejecución segura con controlador simulado; ninguna llamada sale a la red.

def _ready_executor(db_session, ssid_setup, writer):
    from app.core.config import Settings
    from app.changes.models import SsidVlanChangePlan
    x = ssid_setup
    service = _service(db_session, x)
    plan = _preview(service, x)
    _confirm(service, x, plan)
    service.settings = Settings(
        _env_file=None, unifi_inventory_mode='api', unifi_write_enabled=True,
        unifi_api_contract='10.6.106',
    )
    service.writer = writer
    return service, plan


def test_h10_execution_success_is_audited_and_releases_lock(db_session, ssid_setup):
    from sqlalchemy import select, func
    from app.changes.models import WifiWriteLease
    from app.auth.models import AuthAuditEvent
    x = ssid_setup
    writer = SimpleNamespace(update_vlan=AsyncMock(), verify_vlan=AsyncMock(return_value=True))
    service, plan = _ready_executor(db_session, x, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'completed' and result['executed'] is True
    assert writer.update_vlan.await_count == 1 and writer.verify_vlan.await_count == 1
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuthAuditEvent).where(
        AuthAuditEvent.action == 'wifi.ssid_vlan_change.completed')) == 1
    with pytest.raises(Conflict):
        asyncio.run(service.execute_vlan_change(plan['id']))
    assert writer.update_vlan.await_count == 1


def test_h10_uncertain_retains_lock_and_never_retries(db_session, ssid_setup):
    from sqlalchemy import select, func
    from app.changes.models import WifiWriteLease
    from app.changes.ssid_executor import WriteUncertain
    x = ssid_setup
    writer = SimpleNamespace(update_vlan=AsyncMock(side_effect=WriteUncertain()), verify_vlan=AsyncMock())
    service, plan = _ready_executor(db_session, x, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'uncertain' and result['executed'] is False
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 1
    with pytest.raises(Conflict):
        asyncio.run(service.execute_vlan_change(plan['id']))
    assert writer.update_vlan.await_count == 1


def test_h10_verify_failure_keeps_lock(db_session, ssid_setup):
    from sqlalchemy import select, func
    from app.changes.models import WifiWriteLease
    x = ssid_setup
    writer = SimpleNamespace(update_vlan=AsyncMock(), verify_vlan=AsyncMock(return_value=False))
    service, plan = _ready_executor(db_session, x, writer)
    result = asyncio.run(service.execute_vlan_change(plan['id']))
    assert result['status'] == 'uncertain'
    assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 1


def test_h10_blocks_stale_vlan_before_write(db_session, ssid_setup):
    x = ssid_setup
    writer = SimpleNamespace(update_vlan=AsyncMock(), verify_vlan=AsyncMock())
    service, plan = _ready_executor(db_session, x, writer)
    service.inventory.read_broadcast.return_value = {
        'id': 'ssid-123', 'ssid': 'WiFi-Invitados', 'network_id': 'network-40',
    }
    with pytest.raises(Conflict):
        asyncio.run(service.execute_vlan_change(plan['id']))
    writer.update_vlan.assert_not_awaited()


def _writer_settings(**extra):
    from app.core.config import Settings
    return Settings(_env_file=None, unifi_inventory_mode='api',
        unifi_write_enabled=True, unifi_api_contract='10.6.106',
        unifi_api_base_url='https://controller.example.test/proxy/network/integration/v1',
        unifi_api_key='test-only-key', **extra)


def _broadcast(network_id, passphrase='test-only-passphrase'):
    return {'id': 'ssid-123', 'type': 'STANDARD', 'name': 'WiFi-Invitados', 'enabled': True,
            'metadata': {'origin': 'USER_DEFINED'},
            'network': {'type': 'SPECIFIC', 'networkId': network_id},
            'broadcastingDeviceFilter': {'type': 'DEVICES', 'deviceIds': ['ap-1']},
            'securityConfiguration': {'type': 'WPA2_PERSONAL', 'passphrase': passphrase},
            'clientIsolationEnabled': True, 'hideName': False}


def test_h10_writer_replaces_with_official_put_preserving_configuration():
    """El contrato 10.6.106 no ofrece PATCH: PUT completo que solo cambia la red."""
    import json
    from app.changes.ssid_executor import UniFiSsidWriter
    requests, state = [], {'network': 'network-20'}
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/info'):
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        if request.method == 'PUT':
            body = json.loads(request.content)
            expected = _broadcast('network-30')
            del expected['id'], expected['metadata']  # solo lectura en el contrato
            assert body == expected
            state['network'] = body['network']['networkId']
            return httpx.Response(200, json=_broadcast(state['network']))
        assert request.method == 'GET'
        return httpx.Response(200, json=_broadcast(state['network']))
    writer = UniFiSsidWriter(_writer_settings(unifi_write_api_key='write-only-key'), httpx.MockTransport(handler))
    authorized = []
    asyncio.run(writer.update_vlan('demo-site', 'ssid-123', 'network-20',
                                   'network-30', lambda: authorized.append(True)))
    assert asyncio.run(writer.verify_vlan('demo-site', 'ssid-123',
                                         'WiFi-Invitados', 'network-30'))
    assert asyncio.run(writer.read_network('demo-site', 'ssid-123')) == 'network-30'
    assert authorized == [True]
    assert [r.method for r in requests].count('PUT') == 1
    # La clave de escritura es exclusiva del ejecutor y nunca se mezcla con la de lectura.
    assert {r.headers['x-api-key'] for r in requests} == {'write-only-key'}


@pytest.mark.parametrize('passphrase', ['********', '', None])
def test_h10_writer_never_replaces_a_masked_passphrase(passphrase):
    from app.changes.ssid_executor import UniFiSsidWriter
    seen = []
    def handler(request):
        seen.append(request.method)
        if request.url.path.endswith('/info'):
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        return httpx.Response(200, json=_broadcast('network-20', passphrase))
    writer = UniFiSsidWriter(_writer_settings(), httpx.MockTransport(handler))
    with pytest.raises(ServiceUnavailable):
        asyncio.run(writer.update_vlan('demo-site', 'ssid-123', 'network-20', 'network-30', lambda: None))
    assert 'PUT' not in seen


def test_h10_writer_never_writes_if_version_differs():
    from app.core.config import Settings
    from app.changes.ssid_executor import UniFiSsidWriter
    seen = []
    def handler(request):
        seen.append(request.method)
        return httpx.Response(200, json={'applicationVersion': 'other-version'})
    settings = Settings(_env_file=None, unifi_inventory_mode='api',
        unifi_write_enabled=True, unifi_api_contract='10.6.106',
        unifi_api_base_url='https://controller.example.test/proxy/network/integration/v1',
        unifi_api_key='test-only-key')
    writer = UniFiSsidWriter(settings, httpx.MockTransport(handler))
    with pytest.raises(ServiceUnavailable):
        asyncio.run(writer.update_vlan('demo-site', 'ssid-123', 'network-20',
                                       'network-30', lambda: None))
    assert seen == ['GET']


def test_h10_existing_creation_lease_blocks_vlan_change(db_session, ssid_setup):
    from app.changes.models import WifiWriteLease, SsidPlan
    from app.changes.ssid_service import digest
    x = ssid_setup
    writer = SimpleNamespace(update_vlan=AsyncMock(), verify_vlan=AsyncMock())
    service, plan = _ready_executor(db_session, x, writer)
    # Simular una operación de creación que ya reservó el mismo SSID.
    from uuid import uuid4
    now = utc_now()
    other = SsidPlan(id=str(uuid4()), owner_id=x.tech.id, scope_id=x.scope,
        status='executing', source='unifi', fingerprint='f'*64, revision='r'*64,
        rows=[], selection=[], execution_results=[], created_at=now,
        expires_at=now+timedelta(minutes=5), confirmed_at=now)
    db_session.add(other)
    db_session.flush()
    db_session.add(WifiWriteLease(
        resource_key=digest(['demo-site', 'wifi-invitados']), plan_id=other.id))
    db_session.commit()
    with pytest.raises(Conflict):
        asyncio.run(service.execute_vlan_change(plan['id']))
    writer.update_vlan.assert_not_awaited()


def test_h10_disabled_write_never_calls_writer(db_session, ssid_setup):
    x = ssid_setup
    writer = SimpleNamespace(update_vlan=AsyncMock(), verify_vlan=AsyncMock())
    service, plan = _ready_executor(db_session, x, writer)
    from app.core.config import Settings
    service.settings = Settings(_env_file=None, unifi_inventory_mode='api',
                                unifi_write_enabled=False, unifi_api_contract='10.6.106')
    with pytest.raises(ServiceUnavailable):
        asyncio.run(service.execute_vlan_change(plan['id']))
    writer.update_vlan.assert_not_awaited()

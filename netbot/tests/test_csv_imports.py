from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import event, func, select, update

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.changes.csv_parser import parse_csv
from app.changes.csv_schemas import CsvConfirm
from app.changes.csv_service import CsvImportService
from app.changes.dependencies import read_csv_body
from app.changes.models import CsvImport, VlanReservation
from app.changes.schemas import VlanReservationCreate
from app.changes.service import VlanReservationService
from app.core.config import Settings, get_settings
from app.core.errors import AccessDenied, Conflict, InvalidInput, PayloadTooLarge
from app.main import app
from app.monitoring.dependencies import get_monitoring_service
from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.service import MonitoringService

HEADER = "parent_interface,tag,event_name,purpose,ssid\n"
GOOD = (HEADER + "igc1,20,Feria,Invitados,Evento-A\nigc1,30,Feria,Tecnicos,Evento-B\n").encode()
BASE = "/api/v1/changes/csv-imports"


def parse(text, **limits):
    return parse_csv(text.encode() if isinstance(text, str) else text,
                     max_bytes=limits.get("max_bytes", 1048576), max_rows=limits.get("max_rows", 500))


@pytest.mark.parametrize("delimiter", [",", ";"])
def test_parser_supports_bom_crlf_quotes_and_empty_lines(delimiter):
    text = (HEADER + 'igc1,20,Feria,"Invitados, con acceso",Evento-A\n\n').replace(",", delimiter) if delimiter == ";" else HEADER + 'igc1,20,Feria,"Invitados, con acceso",Evento-A\n\n'
    rows = parse(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode())
    assert len(rows) == 1 and not rows[0].errors
    assert rows[0].row_number == 2 and rows[0].data.tag == 20


def test_row_errors_do_not_discard_valid_rows_and_do_not_echo_inputs():
    rows = parse(HEADER + "igc1,bad,Feria,Privado,Evento-A\nigc1,30,Feria,Tecnicos,Evento-B\nigc1,40,extra,columna,SSID,sobrante\n")
    assert rows[0].errors and rows[0].data is None
    assert rows[1].data.tag == 30 and not rows[1].errors
    assert rows[2].errors
    assert "Privado" not in " ".join(rows[0].errors)


def test_duplicate_vlan_and_ssid_are_marked_on_every_affected_row():
    rows = parse(HEADER + "igc1,020,Feria,P,A\nigc1,20,Feria,P,B\nigc1,30,Feria,P,B\n")
    assert all(row.errors for row in rows)
    assert "VLAN" in " ".join(rows[0].errors)
    assert "SSID" in " ".join(rows[2].errors)


@pytest.mark.parametrize("text", ["", HEADER, HEADER.replace("purpose", "password") + "igc1,20,Feria,secret,A\n",
                                       HEADER.replace("purpose", "ssid"), HEADER + 'igc1,20,Feria,"sin cerrar,A\n'])
def test_invalid_structure_and_secret_columns_are_rejected(text):
    with pytest.raises(InvalidInput):
        parse(text)


def test_size_encoding_row_limit_and_ssid_byte_limit():
    with pytest.raises(InvalidInput): parse(b"\xff\xfeinvalid")
    with pytest.raises(PayloadTooLarge): parse(GOOD, max_bytes=10)
    with pytest.raises(PayloadTooLarge): parse(GOOD, max_rows=1)
    assert parse(HEADER + "igc1,20,Feria,P," + "á" * 17 + "\n")[0].errors
    assert not parse(HEADER + "igc1,20,Feria,P," + "á" * 16 + "\n")[0].errors


def test_multiline_fields_preserve_starting_line_numbers():
    rows = parse(HEADER + 'igc1,20,Feria,"Dos\nlineas",A\nigc1,30,Feria,P,B\n')
    assert [row.row_number for row in rows] == [2, 4]


@pytest.fixture
def csv_env(client, db_session, admin_user, login):
    settings = Settings(_env_file=None)
    monitoring = MonitoringService(MockMonitoringProvider(), cache_ttl_seconds=0)
    app.dependency_overrides[get_monitoring_service] = lambda: monitoring
    app.dependency_overrides[get_settings] = lambda: settings
    _, headers = login(admin_user.email, "admin-password")
    return admin_user, headers, settings, monitoring


def upload(client, headers, content=GOOD, filename="reservas.csv"):
    return client.post(BASE, params={"filename": filename}, content=content,
                       headers={**headers, "Content-Type": "text/csv"})


def confirm(client, headers, import_id, rows=(2, 3)):
    return client.post(f"{BASE}/{import_id}/confirm", json={"row_numbers": list(rows)}, headers=headers)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_preview_does_not_reserve_and_confirm_is_atomic_idempotent(client, db_session, csv_env):
    _, headers, _, _ = csv_env
    response = upload(client, headers)
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["valid_count"] == 2 and preview["simulated"] is True
    assert count(db_session, VlanReservation) == 0
    assert preview["expires_at"].endswith("Z")
    result = confirm(client, headers, preview["id"])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "confirmed"
    assert len(result.json()["results"]) == 2 and count(db_session, VlanReservation) == 2
    retry = confirm(client, headers, preview["id"])
    assert [r["reservation"]["id"] for r in retry.json()["results"]] == [r["reservation"]["id"] for r in result.json()["results"]]
    assert count(db_session, VlanReservation) == 2
    assert confirm(client, headers, preview["id"], (2,)).status_code == 409


def test_confirm_valid_subset_ignores_only_unselected_invalid_rows(client, db_session, csv_env):
    _, headers, _, _ = csv_env
    content = (HEADER + "igc1,0,Feria,P,A\nigc1,30,Feria,P,B\n").encode()
    preview = upload(client, headers, content).json()
    assert preview["invalid_count"] == 1
    assert confirm(client, headers, preview["id"], (2, 3)).status_code == 409
    assert count(db_session, VlanReservation) == 0
    result = confirm(client, headers, preview["id"], (3,))
    assert result.status_code == 200
    assert [r["reservation"]["tag"] for r in result.json()["results"]] == [30]


def test_cannot_tamper_with_payload_or_select_nonexistent_rows(client, db_session, csv_env):
    _, headers, _, _ = csv_env
    preview = upload(client, headers).json()
    for rows in [[], [1], [2, 2]]:
        assert confirm(client, headers, preview["id"], rows).status_code == 422
    assert confirm(client, headers, preview["id"], (99,)).status_code == 409
    assert client.post(f"{BASE}/{preview['id']}/confirm", json={"row_numbers": [2], "rows": [{"tag": 99}]}, headers=headers).status_code == 422
    assert count(db_session, VlanReservation) == 0


@pytest.mark.parametrize("role_name", ["cliente", "tecnico", "operador", "visor"])
def test_scoped_roles_cannot_upload_or_inspect_global_csv(client, db_session, csv_env, login, role_name):
    _, admin_headers, _, _ = csv_env
    preview = upload(client, admin_headers).json()
    user = User(email=f"{role_name}@example.com", hashed_password=hash_password("password"),
                roles=[db_session.scalar(select(Role).where(Role.name == role_name))])
    db_session.add(user); db_session.commit()
    _, headers = login(user.email, "password")
    assert upload(client, headers).status_code == 403
    assert client.get(BASE, headers=headers).status_code == 403
    assert client.get(f"{BASE}/{preview['id']}", headers=headers).status_code == 403
    assert confirm(client, headers, preview["id"]).status_code == 403
    assert client.post(f"{BASE}/{preview['id']}/cancel", headers=headers).status_code == 403
    assert upload(client, {}).status_code == 401


def test_another_admin_cannot_read_or_confirm_someone_elses_preview(client, db_session, csv_env, login):
    _, headers, _, _ = csv_env
    preview = upload(client, headers).json()
    role = db_session.scalar(select(Role).where(Role.name == "admin"))
    other = User(email="other-admin@example.com", hashed_password=hash_password("password"), roles=[role])
    db_session.add(other); db_session.commit()
    _, other_headers = login(other.email, "password")
    assert client.get(BASE, headers=other_headers).json() == []
    assert client.get(f"{BASE}/{preview['id']}", headers=other_headers).status_code == 404
    assert confirm(client, other_headers, preview["id"]).status_code == 404
    assert client.post(f"{BASE}/{preview['id']}/cancel", headers=other_headers).status_code == 404
    assert client.get(f"{BASE}/{uuid4()}", headers=other_headers).status_code == 404


def test_expiration_cancellation_and_source_changes_prevent_confirmation(client, db_session, csv_env, monkeypatch):
    _, headers, settings, _ = csv_env
    first = upload(client, headers).json()
    result = client.post(f"{BASE}/{first['id']}/cancel", headers=headers)
    assert result.status_code == 200 and result.json()["status"] == "cancelled"
    assert confirm(client, headers, first["id"]).status_code == 409
    assert client.post(f"{BASE}/{first['id']}/cancel", headers=headers).status_code == 200
    second = upload(client, headers).json()
    db_session.get(CsvImport, second["id"]).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert client.get(f"{BASE}/{second['id']}", headers=headers).json()["status"] == "expired"
    assert confirm(client, headers, second["id"]).status_code == 409
    third = upload(client, headers).json()
    settings.monitoring_site_id = "changed-site"
    assert confirm(client, headers, third["id"]).status_code == 409
    assert count(db_session, VlanReservation) == 0


def test_new_conflict_after_preview_does_not_partially_save_selection(client, db_session, csv_env):
    actor, headers, _, monitoring = csv_env
    preview = upload(client, headers).json()
    # Otra operación ocupa la segunda VLAN después de haber generado la vista previa.
    other = VlanReservation(parent_interface="igc1", tag=30, description="", interface_name="vlan02", event_name="Otro",
                            purpose="P", ssid="Otro", status="reserved", requested_by_id=actor.id, created_at=datetime.now(timezone.utc))
    db_session.add(other); db_session.commit()
    assert confirm(client, headers, preview["id"]).status_code == 409
    assert count(db_session, VlanReservation) == 1
    assert db_session.get(CsvImport, preview["id"]).status == "preview"
    assert upload(client, headers).json()["invalid_count"] == 1


def test_integrity_failure_rolls_back_batch_and_all_reservations(client, db_session, csv_env):
    actor, headers, _, _ = csv_env
    preview = upload(client, headers).json()

    def collide(session, *_):
        if any(isinstance(obj, VlanReservation) for obj in session.new):
            session.add(VlanReservation(parent_interface="igc1", tag=30, interface_name="vlan02", event_name="Concurrente",
                                        purpose="P", ssid="X", status="reserved", requested_by_id=actor.id,
                                        created_at=datetime.now(timezone.utc)))

    event.listen(db_session, "before_flush", collide)
    try:
        response = confirm(client, headers, preview["id"])
    finally:
        event.remove(db_session, "before_flush", collide)
    assert response.status_code == 409
    assert count(db_session, VlanReservation) == 0
    assert db_session.get(CsvImport, preview["id"]).status == "preview"


def test_confirmed_retry_does_not_need_inventory(client, db_session, csv_env):
    _, headers, _, _ = csv_env
    preview = upload(client, headers).json()
    assert confirm(client, headers, preview["id"]).status_code == 200
    app.dependency_overrides[get_monitoring_service] = lambda: MonitoringService(MockMonitoringProvider(scenario="outage"))
    assert confirm(client, headers, preview["id"]).status_code == 200
    assert count(db_session, VlanReservation) == 2


def test_inventory_outage_prevents_preview_but_field_errors_remain_reviewable(client, db_session, csv_env):
    _, headers, _, _ = csv_env
    app.dependency_overrides[get_monitoring_service] = lambda: MonitoringService(MockMonitoringProvider(scenario="outage"))
    assert upload(client, headers).status_code == 503
    assert count(db_session, CsvImport) == 0
    invalid = (HEADER + "igc1,0,Feria,P,A\n").encode()
    result = upload(client, headers, invalid)
    assert result.status_code == 201 and result.json()["valid_count"] == 0


def test_revocation_during_inventory_read_cannot_commit_a_batch(client, db_session, csv_env):
    actor, headers, _, monitoring = csv_env
    preview = upload(client, headers).json()

    class RevokingMonitor:
        async def get_vlan_inventory(self):
            result = await monitoring.get_vlan_inventory()
            actor.is_active = False
            db_session.commit()
            return result

    app.dependency_overrides[get_monitoring_service] = RevokingMonitor
    assert confirm(client, headers, preview["id"]).status_code == 401
    assert count(db_session, VlanReservation) == 0


def test_cancellation_during_inventory_read_wins_without_reservations(client, db_session, csv_env):
    _, headers, _, monitoring = csv_env
    preview = upload(client, headers).json()

    class CancellingMonitor:
        async def get_vlan_inventory(self):
            result = await monitoring.get_vlan_inventory()
            db_session.execute(update(CsvImport).where(CsvImport.id == preview["id"]).values(status="cancelled"))
            db_session.commit()
            return result

    app.dependency_overrides[get_monitoring_service] = CancellingMonitor
    assert confirm(client, headers, preview["id"]).status_code == 409
    assert count(db_session, VlanReservation) == 0


def test_upload_limits_and_format_fail_without_creating_imports(client, db_session, csv_env):
    _, headers, settings, _ = csv_env
    settings.csv_max_bytes = 1024
    assert upload(client, headers, GOOD * 20).status_code == 413
    assert upload(client, headers, filename="bad.txt").status_code == 400
    assert client.post(BASE, json={"csv": "file"}, headers=headers).status_code == 400
    assert upload(client, headers, (HEADER.replace("ssid", "password") + "igc1,20,Feria,P,secret\n").encode()).status_code == 400
    assert count(db_session, CsvImport) == 0


@pytest.mark.asyncio
async def test_stream_size_limit_applies_without_content_length():
    chunks = iter([b"a" * 700, b"b" * 700])
    async def receive():
        chunk = next(chunks)
        return {"type": "http.request", "body": chunk, "more_body": True}
    request = Request({"type": "http", "headers": [(b"content-type", b"text/csv")]}, receive)
    with pytest.raises(PayloadTooLarge):
        await read_csv_body(request, Settings(_env_file=None, csv_max_bytes=1024))


@pytest.mark.asyncio
async def test_direct_service_enforces_permission_before_parsing(db_session, viewer_user):
    service = CsvImportService(db_session, MonitoringService(MockMonitoringProvider()), Settings(_env_file=None))
    with pytest.raises(AccessDenied):
        await service.preview(b"bad file", "bad.csv", viewer_user)

"""API de inventario y planos: permisos, paginación y validación de imágenes."""

import struct

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.monitoring.inventory import persist_snapshot
from app.monitoring.models import MonitoredDevice
from app.monitoring.plans import sniff_image
from app.monitoring.schemas import DeviceState, DeviceType, InventoryDevice, InventorySnapshot
from datetime import datetime, timezone

import pytest

from app.core.errors import InvalidInput

BASE = "/api/v1/monitoring"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 800, 600) + b"\x08\x06\x00\x00\x00"
JPEG = b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xc0\x00\x11\x08" + struct.pack(">HH", 300, 400) + b"\x03" + b"\x00" * 9


@pytest.fixture()
def admin(client, admin_user, login):
    return login("admin@example.com", "admin-password")[1]


@pytest.fixture()
def viewer(client, viewer_user, login):
    return login("viewer@example.com", "viewer-password")[1]


def seed(db):
    persist_snapshot(db, "mock", InventorySnapshot(devices=[
        InventoryDevice(external_id="ap1", name="AP Hall", device_type=DeviceType.ACCESS_POINT, state=DeviceState.ONLINE),
        InventoryDevice(external_id="ap2", name="AP Sur", device_type=DeviceType.ACCESS_POINT, state=DeviceState.OFFLINE),
        InventoryDevice(external_id="sw", name="Switch", device_type=DeviceType.SWITCH, state=DeviceState.ONLINE),
    ]), datetime.now(timezone.utc), 30)
    db.commit()
    return {d.external_id: d.id for d in db.query(MonitoredDevice)}


def upload(client, headers, content=PNG, content_type="image/png", name="Hall"):
    return client.post(f"{BASE}/plans", params={"name": name}, content=content,
                       headers={**headers, "Content-Type": content_type})


def test_inventory_requires_monitoring_permission(client, db_session, login):
    assert client.get(f"{BASE}/devices").status_code == 401
    role = db_session.query(Role).filter_by(name="cliente").one()
    db_session.add(User(email="c@example.com", hashed_password=hash_password("cliente-pass"), roles=[role]))
    db_session.commit()
    headers = login("c@example.com", "cliente-pass")[1]
    for path in ("/devices", "/summary", "/alerts", "/health", "/plans"):
        assert client.get(BASE + path, headers=headers).status_code == 403


def test_viewer_reads_paginated_filtered_devices_and_summary(client, db_session, viewer):
    seed(db_session)
    page = client.get(f"{BASE}/devices", params={"limit": 2}, headers=viewer).json()
    assert (page["total"], len(page["items"]), page["items"][0]["name"]) == (3, 2, "AP Sur")
    only = client.get(f"{BASE}/devices", params={"type": "switch"}, headers=viewer).json()
    assert [d["name"] for d in only["items"]] == ["Switch"]
    assert client.get(f"{BASE}/devices", params={"limit": 999}, headers=viewer).status_code == 422
    summary = client.get(f"{BASE}/summary", headers=viewer).json()
    assert (summary["access_points_online"], summary["access_points_offline"]) == (1, 1)


def test_health_never_exposes_credentials(client, viewer):
    rows = client.get(f"{BASE}/health", headers=viewer).json()
    assert [r["source"] for r in rows] == ["mock"]
    assert rows[0]["status"] == "unavailable"


def test_plan_upload_placement_and_unplaced_listing(client, db_session, admin, viewer):
    ids = seed(db_session)
    created = upload(client, admin)
    assert created.status_code == 201
    plan = created.json()
    assert (plan["width"], plan["height"], plan["content_type"]) == (800, 600, "image/png")

    detail = client.get(f"{BASE}/plans/{plan['id']}", headers=viewer).json()
    assert {a["name"] for a in detail["unplaced"]} == {"AP Hall", "AP Sur"}  # sin ubicar, no omitidos

    url = f"{BASE}/plans/{plan['id']}/placements/{ids['ap2']}"
    assert client.put(url, json={"x": 0.25, "y": 0.5}, headers=admin).status_code == 204
    detail = client.get(f"{BASE}/plans/{plan['id']}", headers=viewer).json()
    assert detail["placed"][0]["state"] == "offline" and detail["placed"][0]["x"] == 0.25
    assert [a["name"] for a in detail["unplaced"]] == ["AP Hall"]

    image = client.get(f"{BASE}/plans/{plan['id']}/image", headers=viewer)
    assert image.content == PNG and image.headers["x-content-type-options"] == "nosniff"

    assert client.delete(url, headers=admin).status_code == 204
    assert client.delete(f"{BASE}/plans/{plan['id']}", headers=admin).status_code == 204
    assert client.get(f"{BASE}/plans/{plan['id']}", headers=viewer).status_code == 404


def test_only_managers_change_plans(client, db_session, admin, viewer):
    ids = seed(db_session)
    assert upload(client, viewer).status_code == 403
    plan = upload(client, admin).json()
    url = f"{BASE}/plans/{plan['id']}/placements/{ids['ap1']}"
    assert client.put(url, json={"x": 0.1, "y": 0.1}, headers=viewer).status_code == 403
    assert client.delete(f"{BASE}/plans/{plan['id']}", headers=viewer).status_code == 403


def test_placement_validation(client, db_session, admin):
    ids = seed(db_session)
    plan = upload(client, admin).json()
    base = f"{BASE}/plans/{plan['id']}/placements"
    assert client.put(f"{base}/{ids['ap1']}", json={"x": 1.5, "y": 0}, headers=admin).status_code == 422
    assert client.put(f"{base}/{ids['sw']}", json={"x": 0, "y": 0}, headers=admin).status_code == 400
    assert client.put(f"{base}/99999", json={"x": 0, "y": 0}, headers=admin).status_code == 404


def test_plan_upload_validates_format_and_size(client, admin):
    assert upload(client, admin, b"<svg xmlns='http://www.w3.org/2000/svg'/>").status_code == 400
    assert upload(client, admin, b"<svg/>", "image/svg+xml").status_code == 400
    assert upload(client, admin, PNG + b"\x00" * 5_242_880).status_code == 413


def test_sniff_reads_real_dimensions():
    assert sniff_image(PNG) == ("image/png", 800, 600)
    assert sniff_image(JPEG) == ("image/jpeg", 400, 300)
    with pytest.raises(InvalidInput):
        sniff_image(b"\xff\xd8\xff")

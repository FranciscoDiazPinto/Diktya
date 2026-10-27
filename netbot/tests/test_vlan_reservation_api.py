from app.auth.models import Role, User
from app.auth.security import hash_password
from app.main import app
from app.monitoring.dependencies import get_monitoring_service
from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.service import MonitoringService


def test_viewer_can_read_options_but_cannot_reserve(client, viewer_user, login):
    app.dependency_overrides[get_monitoring_service] = lambda: MonitoringService(MockMonitoringProvider())
    _, headers = login(viewer_user.email, "viewer-password")
    assert client.get("/api/v1/changes/vlan-options", headers=headers).status_code == 200
    assert client.get("/api/v1/changes/vlan-reservations", headers=headers).status_code == 403
    assert client.post("/api/v1/changes/vlan-reservations", json={
        "parent_interface": "igc1", "tag": 20, "event_name": "Evento",
        "purpose": "Prueba", "ssid": "SSID",
    }, headers=headers).status_code == 403


def test_admin_can_create_and_release_reservation(client, db_session, login):
    role = db_session.query(Role).filter_by(name="admin").one()
    user = User(email="operator-reserve@example.com", hashed_password=hash_password("pass"), roles=[role])
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_monitoring_service] = lambda: MonitoringService(MockMonitoringProvider())
    _, headers = login(user.email, "pass")
    response = client.post("/api/v1/changes/vlan-reservations", json={
        "parent_interface": "igc1", "tag": 20, "event_name": "Evento",
        "purpose": "Prueba", "ssid": "SSID",
    }, headers=headers)
    assert response.status_code == 201, response.text
    reservation_id = response.json()["id"]
    assert response.json()["requested_by_id"] == user.id
    released = client.post(f"/api/v1/changes/vlan-reservations/{reservation_id}/release", headers=headers)
    assert released.status_code == 200
    assert released.json()["status"] == "released"

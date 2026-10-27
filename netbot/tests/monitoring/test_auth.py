import pytest

BASE = "/api/v1/monitoring"
PATHS = ["/system", "/interfaces", "/clients", "/firewall/stats", "/firewall/events"]


@pytest.mark.parametrize("path", PATHS)
def test_monitoring_requires_authentication(client, path):
    assert client.get(BASE + path).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_viewer_can_read_monitoring(client, viewer_user, login, path):
    _, headers = login("viewer@example.com", "viewer-password")
    response = client.get(BASE + path, headers=headers)
    assert response.status_code == 200
    assert response.json()["source"] == "mock"


def test_user_without_roles_is_forbidden(client, db_session, login):
    from app.auth.models import User
    from app.auth.security import hash_password

    db_session.add(User(email="norole@example.com", hashed_password=hash_password("norole-password"), roles=[]))
    db_session.commit()
    _, headers = login("norole@example.com", "norole-password")
    assert client.get(BASE + "/system", headers=headers).status_code == 403

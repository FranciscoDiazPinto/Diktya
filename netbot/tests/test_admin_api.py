def test_admin_endpoints_require_the_declared_permission(client, login, admin_user, viewer_user):
    _, viewer_headers = login(viewer_user.email, "viewer-password")
    assert client.get("/admin/users", headers=viewer_headers).status_code == 403
    assert client.get("/admin/roles", headers=viewer_headers).status_code == 403

    _, admin_headers = login(admin_user.email, "admin-password")
    assert client.get("/admin/users", headers=admin_headers).status_code == 200
    assert client.get("/admin/roles", headers=admin_headers).status_code == 200


def test_admin_can_manage_users_and_roles(client, login, admin_user):
    _, headers = login(admin_user.email, "admin-password")

    created_role = client.post(
        "/admin/roles",
        headers=headers,
        json={"name": "auditor", "description": "Read-only audit role"},
    )
    assert created_role.status_code == 201
    assert created_role.json()["name"] == "auditor"

    created_user = client.post(
        "/admin/users",
        headers=headers,
        json={
            "email": "new-user@example.com",
            "password": "new-password",
            "full_name": "New User",
            "roles": ["visor"],
        },
    )
    assert created_user.status_code == 201
    assert created_user.json()["roles"] == ["visor"]

    updated = client.patch(
        f"/admin/users/{created_user.json()['id']}",
        headers=headers,
        json={"full_name": "Updated User", "roles": ["operador"]},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Updated User"
    assert updated.json()["roles"] == ["operador"]


def test_role_policy_grants_operator_only_declared_permissions(client, login, db_session):
    from app.auth.models import Role, User
    from app.auth.permissions import Permission
    from app.auth.roles import RoleName, has_permission
    from app.auth.security import hash_password

    role = db_session.query(Role).filter_by(name="operador").one()
    user = User(email="operator@example.com", hashed_password=hash_password("operator-password"), roles=[role])
    db_session.add(user)
    db_session.commit()
    _, headers = login(user.email, "operator-password")

    assert has_permission({RoleName.OPERADOR}, Permission.MONITORING_READ)
    assert not has_permission({RoleName.OPERADOR}, Permission.USERS_MANAGE)
    assert client.get("/admin/users", headers=headers).status_code == 403

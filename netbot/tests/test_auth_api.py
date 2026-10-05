def test_login_refresh_logout_and_current_user(client, db_session, admin_user):
    login = client.post(
        "/auth/login",
        json={"email": "ADMIN@example.com", "password": "admin-password"},
    )
    assert login.status_code == 200
    tokens = login.json()
    assert tokens["token_type"] == "bearer"

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["roles"] == ["admin"]

    refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

    # Rotation revokes the old refresh token.
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": refreshed.json()["refresh_token"]}).status_code == 401


def test_login_rejects_bad_credentials(client, admin_user):
    response = client.post("/auth/login", json={"email": admin_user.email, "password": "not-it"})
    assert response.status_code == 401


def test_current_user_requires_bearer_token(client):
    assert client.get("/auth/me").status_code == 401

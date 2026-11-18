"""Authentication, session and permission tests."""

from __future__ import annotations

from tests.conftest import PASSWORD, login


def test_login_sets_secure_session_cookie_and_returns_permissions(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@test.local"
    assert body["role_level"] == 1
    assert "users.manage" in body["permissions"]
    assert "inventory.write" in body["permissions"]
    set_cookie = response.headers.get("set-cookie", "")
    assert "aurora_session=" in set_cookie
    assert "HttpOnly" in set_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role_code"] == "admin"


def test_login_with_wrong_password_fails(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "wrong-password-1"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/v1/products").status_code == 401


def test_worker_cannot_create_products(worker_client):
    response = worker_client.post("/api/v1/products", json={"name": "No permitido"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_worker_cannot_manage_users(worker_client):
    assert worker_client.get("/api/v1/users").status_code == 403


def test_auditor_is_read_only(auditor_client):
    assert auditor_client.get("/api/v1/audit").status_code == 200
    assert auditor_client.get("/api/v1/products").status_code == 200
    response = auditor_client.post("/api/v1/warehouses", json={"code": "ALM-99", "name": "X"})
    assert response.status_code == 403


def test_admin_cannot_demote_themselves(admin_client, users):
    user_id = users["admin"].id
    response = admin_client.patch(f"/api/v1/users/{user_id}", json={"role_level": 4})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "self_modification_blocked"


def test_logout_revokes_session(admin_client):
    assert admin_client.get("/api/v1/auth/me").status_code == 200
    assert admin_client.post("/api/v1/auth/logout").status_code == 200
    assert admin_client.get("/api/v1/auth/me").status_code == 401


def test_password_change_rotates_session(admin_client):
    response = admin_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NuevaClave2026"},
    )
    assert response.status_code == 200, response.text
    # The rotated cookie keeps the user authenticated.
    assert admin_client.get("/api/v1/auth/me").status_code == 200
    # Old password no longer works.
    other = admin_client
    logout = other.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert (
        other.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.local", "password": PASSWORD},
        ).status_code
        == 401
    )
    assert (
        other.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.local", "password": "NuevaClave2026"},
        ).status_code
        == 200
    )


def test_login_rate_limiting(client, users):
    for _ in range(8):
        client.post(
            "/api/v1/auth/login",
            json={"email": "auditor@test.local", "password": "bad-password-1"},
        )
    response = client.post(
        "/api/v1/auth/login", json={"email": "auditor@test.local", "password": PASSWORD}
    )
    assert response.status_code == 429


def test_sessions_can_be_revoked_all(admin_client):
    assert admin_client.post("/api/v1/auth/logout-all").status_code == 200
    assert admin_client.get("/api/v1/auth/me").status_code == 401


def test_manager_has_logistics_permissions_but_not_user_management(client, users):
    manager = login(client, "manager@test.local")
    me = manager.get("/api/v1/auth/me").json()
    assert me["role_level"] == 2
    assert "movements.write" in me["permissions"]
    assert "users.manage" not in me["permissions"]
    assert manager.get("/api/v1/users").status_code == 403


def test_roles_catalog_and_system_info(admin_client, worker_client):
    """El catálogo de roles debe serializar identificadores numéricos y niveles 1-5."""
    roles = admin_client.get("/api/v1/roles")
    assert roles.status_code == 200, roles.text
    body = roles.json()
    assert len(body) >= 5
    assert all(isinstance(role["id"], int) for role in body)
    assert {role["level"] for role in body} >= {1, 2, 3, 4, 5}

    info = admin_client.get("/api/v1/system/info")
    assert info.status_code == 200, info.text
    payload = info.json()
    assert payload["phase"]
    assert payload["implemented"] and payload["pending"]

    assert worker_client.get("/api/v1/roles").status_code == 403

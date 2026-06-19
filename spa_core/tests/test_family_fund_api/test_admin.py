"""Tests for admin routes: user CRUD, system status, sessions, force-refresh."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from spa_core.family_fund.api.routes import admin as admin_module

from .conftest import TEST_PASSWORDS, auth_header


@pytest.fixture(autouse=True)
def _patch_admin_users_path(users_file):
    original = admin_module._USERS_PATH
    admin_module.set_users_path(users_file)
    yield
    admin_module.set_users_path(original)


# ── GET /admin/users ─────────────────────────────────────────────────────────

class TestListUsers:
    def test_owner_can_list(self, client: TestClient, owner_token: str):
        r = client.get("/admin/users", headers=auth_header(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 4
        usernames = [u["username"] for u in data]
        assert "owner" in usernames
        assert "investor" in usernames

    def test_admin_can_list(self, client: TestClient, admin_token: str):
        r = client.get("/admin/users", headers=auth_header(admin_token))
        assert r.status_code == 200
        assert len(r.json()) == 4

    def test_investor_forbidden(self, client: TestClient, investor_token: str):
        r = client.get("/admin/users", headers=auth_header(investor_token))
        assert r.status_code == 403

    def test_readonly_forbidden(self, client: TestClient, readonly_token: str):
        r = client.get("/admin/users", headers=auth_header(readonly_token))
        assert r.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient):
        r = client.get("/admin/users")
        assert r.status_code in (401, 403)

    def test_no_password_hash_in_response(self, client: TestClient, owner_token: str):
        r = client.get("/admin/users", headers=auth_header(owner_token))
        for u in r.json():
            assert "password_hash" not in u
            assert "password" not in u


# ── POST /admin/users ────────────────────────────────────────────────────────

class TestCreateUser:
    def test_create_investor(self, client: TestClient, owner_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "new_investor",
                "email": "new@example.com",
                "password": "secure-pass-123",
                "role": "investor",
                "display_name": "New Investor",
            },
            headers=auth_header(owner_token),
        )
        assert r.status_code == 201
        data = r.json()
        assert data["username"] == "new_investor"
        assert data["email"] == "new@example.com"
        assert data["role"] == "investor"
        assert data["is_active"] is True
        assert data["display_name"] == "New Investor"

    def test_create_duplicate_username_fails(self, client: TestClient, owner_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "owner",
                "email": "other@example.com",
                "password": "pass123456",
            },
            headers=auth_header(owner_token),
        )
        assert r.status_code == 409

    def test_create_duplicate_email_fails(self, client: TestClient, owner_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "unique_user",
                "email": "yuriycooleshov@gmail.com",
                "password": "pass123456",
            },
            headers=auth_header(owner_token),
        )
        assert r.status_code == 409

    def test_admin_cannot_create_owner(self, client: TestClient, admin_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "new_owner",
                "email": "newowner@example.com",
                "password": "pass123456",
                "role": "owner",
            },
            headers=auth_header(admin_token),
        )
        assert r.status_code == 403

    def test_owner_can_create_owner(self, client: TestClient, owner_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "second_owner",
                "email": "second@example.com",
                "password": "pass123456",
                "role": "owner",
            },
            headers=auth_header(owner_token),
        )
        assert r.status_code == 201
        assert r.json()["role"] == "owner"

    def test_invalid_role_rejected(self, client: TestClient, owner_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "bad_role",
                "email": "bad@example.com",
                "password": "pass123456",
                "role": "superadmin",
            },
            headers=auth_header(owner_token),
        )
        assert r.status_code == 422

    def test_short_password_rejected(self, client: TestClient, owner_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "short_pw",
                "email": "short@example.com",
                "password": "12345",
            },
            headers=auth_header(owner_token),
        )
        assert r.status_code == 422

    def test_investor_cannot_create(self, client: TestClient, investor_token: str):
        r = client.post(
            "/admin/users",
            json={
                "username": "x",
                "email": "x@x.com",
                "password": "pass123456",
            },
            headers=auth_header(investor_token),
        )
        assert r.status_code == 403


# ── PUT /admin/users/{user_id} ──────────────────────────────────────────────

class TestUpdateUser:
    def test_update_role(self, client: TestClient, owner_token: str):
        r = client.put(
            "/admin/users/investor",
            json={"role": "admin"},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_update_email(self, client: TestClient, owner_token: str):
        r = client.put(
            "/admin/users/investor",
            json={"email": "new_investor@earn-defi.com"},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200
        assert r.json()["email"] == "new_investor@earn-defi.com"

    def test_update_display_name(self, client: TestClient, owner_token: str):
        r = client.put(
            "/admin/users/investor",
            json={"display_name": "Test Investor"},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200
        assert r.json()["display_name"] == "Test Investor"

    def test_user_not_found(self, client: TestClient, owner_token: str):
        r = client.put(
            "/admin/users/nonexistent",
            json={"role": "admin"},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 404

    def test_duplicate_email_rejected(self, client: TestClient, owner_token: str):
        r = client.put(
            "/admin/users/investor",
            json={"email": "admin@earn-defi.com"},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 409

    def test_admin_cannot_modify_owner(self, client: TestClient, admin_token: str):
        r = client.put(
            "/admin/users/owner",
            json={"role": "admin"},
            headers=auth_header(admin_token),
        )
        assert r.status_code == 403

    def test_admin_cannot_assign_owner_role(self, client: TestClient, admin_token: str):
        r = client.put(
            "/admin/users/investor",
            json={"role": "owner"},
            headers=auth_header(admin_token),
        )
        assert r.status_code == 403


# ── DELETE /admin/users/{user_id} ────────────────────────────────────────────

class TestDeactivateUser:
    def test_deactivate_user(self, client: TestClient, owner_token: str):
        r = client.delete(
            "/admin/users/readonly",
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    def test_cannot_deactivate_self(self, client: TestClient, owner_token: str):
        r = client.delete(
            "/admin/users/owner",
            headers=auth_header(owner_token),
        )
        assert r.status_code == 400

    def test_deactivate_nonexistent(self, client: TestClient, owner_token: str):
        r = client.delete(
            "/admin/users/nobody",
            headers=auth_header(owner_token),
        )
        assert r.status_code == 404


# ── GET /admin/system ────────────────────────────────────────────────────────

class TestSystemStatus:
    def test_returns_system_info(self, client: TestClient, owner_token: str):
        r = client.get("/admin/system", headers=auth_header(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert "cycle_health" in data
        assert "kanban_done_count" in data
        assert "sprint_current" in data
        assert "golive_status" in data
        assert "data_freshness" in data

    def test_admin_can_access(self, client: TestClient, admin_token: str):
        r = client.get("/admin/system", headers=auth_header(admin_token))
        assert r.status_code == 200

    def test_investor_forbidden(self, client: TestClient, investor_token: str):
        r = client.get("/admin/system", headers=auth_header(investor_token))
        assert r.status_code == 403


# ── GET /admin/sessions ──────────────────────────────────────────────────────

class TestSessionStats:
    def test_returns_stats(self, client: TestClient, owner_token: str):
        r = client.get("/admin/sessions", headers=auth_header(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert "revoked_tokens" in data
        assert isinstance(data["revoked_tokens"], int)

    def test_admin_can_access(self, client: TestClient, admin_token: str):
        r = client.get("/admin/sessions", headers=auth_header(admin_token))
        assert r.status_code == 200


# ── POST /admin/force-refresh ────────────────────────────────────────────────

class TestForceRefresh:
    def test_owner_can_force_refresh(self, client: TestClient, owner_token: str):
        r = client.post("/admin/force-refresh", headers=auth_header(owner_token))
        assert r.status_code == 200
        assert "invalidated" in r.json()

    def test_admin_cannot_force_refresh(self, client: TestClient, admin_token: str):
        r = client.post("/admin/force-refresh", headers=auth_header(admin_token))
        assert r.status_code == 403

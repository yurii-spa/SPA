"""Tests for /users/me profile endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.family_fund.api.routes import users as users_module

from .conftest import auth_header


@pytest.fixture(autouse=True)
def _patch_users_path(users_file):
    original = users_module._USERS_PATH
    users_module.set_users_path(users_file)
    yield
    users_module.set_users_path(original)


# ── GET /users/me ────────────────────────────────────────────────────────────

class TestGetProfile:
    def test_owner_profile(self, client: TestClient, owner_token: str):
        r = client.get("/users/me", headers=auth_header(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "owner"
        assert data["email"] == "yuriycooleshov@gmail.com"
        assert data["role"] == "owner"

    def test_investor_profile(self, client: TestClient, investor_token: str):
        r = client.get("/users/me", headers=auth_header(investor_token))
        assert r.status_code == 200
        assert r.json()["role"] == "investor"

    def test_readonly_profile(self, client: TestClient, readonly_token: str):
        r = client.get("/users/me", headers=auth_header(readonly_token))
        assert r.status_code == 200
        assert r.json()["role"] == "readonly"

    def test_no_password_in_response(self, client: TestClient, owner_token: str):
        r = client.get("/users/me", headers=auth_header(owner_token))
        data = r.json()
        assert "password_hash" not in data
        assert "password" not in data

    def test_unauthenticated(self, client: TestClient):
        r = client.get("/users/me")
        assert r.status_code in (401, 403)

    def test_profile_has_expected_fields(self, client: TestClient, owner_token: str):
        r = client.get("/users/me", headers=auth_header(owner_token))
        data = r.json()
        assert "username" in data
        assert "email" in data
        assert "role" in data
        assert "is_active" in data


# ── PUT /users/me ────────────────────────────────────────────────────────────

class TestUpdateProfile:
    def test_update_display_name(self, client: TestClient, owner_token: str):
        r = client.put(
            "/users/me",
            json={"display_name": "Yurii K."},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200
        assert r.json()["display_name"] == "Yurii K."

    def test_update_telegram(self, client: TestClient, owner_token: str):
        r = client.put(
            "/users/me",
            json={"telegram_handle": "@yurii_spa"},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200
        assert r.json()["telegram_handle"] == "@yurii_spa"

    def test_update_both_fields(self, client: TestClient, investor_token: str):
        r = client.put(
            "/users/me",
            json={"display_name": "Test Investor", "telegram_handle": "@tinv"},
            headers=auth_header(investor_token),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["display_name"] == "Test Investor"
        assert data["telegram_handle"] == "@tinv"

    def test_empty_update_ok(self, client: TestClient, owner_token: str):
        r = client.put(
            "/users/me",
            json={},
            headers=auth_header(owner_token),
        )
        assert r.status_code == 200

    def test_cannot_change_role(self, client: TestClient, investor_token: str):
        r = client.put(
            "/users/me",
            json={"display_name": "X"},
            headers=auth_header(investor_token),
        )
        assert r.status_code == 200
        assert r.json()["role"] == "investor"

    def test_unauthenticated_rejected(self, client: TestClient):
        r = client.put("/users/me", json={"display_name": "Hacker"})
        assert r.status_code in (401, 403)

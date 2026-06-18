"""Тесты auth: login/refresh/logout, JWT, blacklist, rate limit, password hashing."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from spa_core.family_fund.api import auth
from spa_core.family_fund.api.auth import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    authenticate,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    revoke_token,
    verify_password,
)
from spa_core.family_fund.api.models import UserRole

from .conftest import TEST_PASSWORDS, auth_header


# ── Password hashing ──────────────────────────────────────────────────────────
class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        h = hash_password("hunter2!")
        assert verify_password("hunter2!", h)

    def test_wrong_password_fails(self):
        h = hash_password("hunter2!")
        assert not verify_password("wrong", h)

    def test_hash_is_not_plaintext(self):
        h = hash_password("hunter2!")
        assert "hunter2!" not in h

    def test_two_hashes_differ_salt(self):
        assert hash_password("same") != hash_password("same")

    def test_empty_stored_hash_rejected(self):
        assert not verify_password("x", "")

    def test_pbkdf2_fallback_roundtrip(self):
        # Принудительно проверяем pbkdf2-ветку
        with patch.object(auth, "_HAS_BCRYPT", False):
            h = hash_password("pbkdf2pass")
            assert h.startswith("pbkdf2_sha256$")
            assert verify_password("pbkdf2pass", h)
            assert not verify_password("nope", h)


# ── JWT encode/decode ─────────────────────────────────────────────────────────
class TestJWT:
    def test_access_token_decodes(self):
        tok = create_access_token("u1", UserRole.INVESTOR)
        payload = decode_token(tok)
        assert payload["sub"] == "u1"
        assert payload["role"] == "investor"
        assert payload["type"] == "access"
        assert "jti" in payload

    def test_refresh_token_has_no_role(self):
        tok = create_refresh_token("u1")
        payload = decode_token(tok)
        assert payload["type"] == "refresh"
        assert "role" not in payload

    def test_access_ttl(self):
        tok = create_access_token("u1", UserRole.OWNER)
        payload = decode_token(tok)
        assert payload["exp"] - payload["iat"] == ACCESS_TOKEN_TTL

    def test_refresh_ttl(self):
        tok = create_refresh_token("u1")
        payload = decode_token(tok)
        assert payload["exp"] - payload["iat"] == REFRESH_TOKEN_TTL

    def test_malformed_token_rejected(self):
        with pytest.raises(ValueError):
            decode_token("not.a.valid.jwt")

    def test_two_parts_rejected(self):
        with pytest.raises(ValueError):
            decode_token("only.two")

    def test_tampered_signature_rejected(self):
        tok = create_access_token("u1", UserRole.INVESTOR)
        head, payload, _sig = tok.split(".")
        with pytest.raises(ValueError):
            decode_token(f"{head}.{payload}.deadbeef")

    def test_tampered_payload_rejected(self):
        tok = create_access_token("u1", UserRole.INVESTOR)
        head, _payload, sig = tok.split(".")
        import base64
        import json

        forged = base64.urlsafe_b64encode(
            json.dumps({"sub": "admin", "role": "owner"}).encode()
        ).rstrip(b"=").decode()
        with pytest.raises(ValueError):
            decode_token(f"{head}.{forged}.{sig}")

    def test_expired_token_rejected(self):
        with patch("spa_core.family_fund.api.auth.time") as mt:
            mt.time.return_value = time.time() - 10000
            old = create_access_token("u1", UserRole.INVESTOR)
        with pytest.raises(ValueError):
            decode_token(old)

    def test_unique_jti(self):
        a = decode_token(create_access_token("u1", UserRole.INVESTOR))
        b = decode_token(create_access_token("u1", UserRole.INVESTOR))
        assert a["jti"] != b["jti"]


# ── Revocation / blacklist ────────────────────────────────────────────────────
class TestRevocation:
    def test_revoked_token_rejected(self):
        tok = create_access_token("u1", UserRole.INVESTOR)
        assert decode_token(tok)["sub"] == "u1"
        revoke_token(tok)
        with pytest.raises(ValueError):
            decode_token(tok)

    def test_revoke_invalid_token_noop(self):
        # не должно бросать
        revoke_token("garbage.token.value")

    def test_clear_revoked(self):
        tok = create_access_token("u1", UserRole.INVESTOR)
        revoke_token(tok)
        auth.clear_revoked()
        # после очистки blacklist токен снова валиден (не истёк)
        assert decode_token(tok)["sub"] == "u1"


# ── authenticate() ────────────────────────────────────────────────────────────
class TestAuthenticate:
    def test_authenticate_by_username(self, users_file):
        u = authenticate("owner", TEST_PASSWORDS["owner"])
        assert u is not None
        assert u["role"] == "owner"

    def test_authenticate_by_email(self, users_file):
        u = authenticate("yuriycooleshov@gmail.com", TEST_PASSWORDS["owner"])
        assert u is not None
        assert u["username"] == "owner"

    def test_authenticate_wrong_password(self, users_file):
        assert authenticate("owner", "wrong") is None

    def test_authenticate_unknown_user(self, users_file):
        assert authenticate("ghost", "x") is None


# ── /auth/login endpoint ──────────────────────────────────────────────────────
class TestLoginEndpoint:
    def test_login_ok(self, client: TestClient):
        r = client.post(
            "/auth/login",
            data={"username": "owner", "password": TEST_PASSWORDS["owner"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["role"] == "owner"
        assert body["expires_in"] == ACCESS_TOKEN_TTL
        assert body["access_token"]

    def test_login_sets_refresh_cookie(self, client: TestClient):
        r = client.post(
            "/auth/login",
            data={"username": "owner", "password": TEST_PASSWORDS["owner"]},
        )
        assert "refresh_token" in r.cookies
        set_cookie = r.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()

    def test_login_by_email(self, client: TestClient):
        r = client.post(
            "/auth/login",
            data={
                "username": "yuriycooleshov@gmail.com",
                "password": TEST_PASSWORDS["owner"],
            },
        )
        assert r.status_code == 200

    def test_login_wrong_password(self, client: TestClient):
        r = client.post(
            "/auth/login", data={"username": "owner", "password": "nope"}
        )
        assert r.status_code == 401

    def test_login_unknown_user(self, client: TestClient):
        r = client.post(
            "/auth/login", data={"username": "ghost", "password": "x"}
        )
        assert r.status_code == 401

    def test_login_access_token_works(self, client: TestClient):
        r = client.post(
            "/auth/login",
            data={"username": "investor", "password": TEST_PASSWORDS["investor"]},
        )
        token = r.json()["access_token"]
        r2 = client.get("/portfolio", headers=auth_header(token))
        assert r2.status_code == 200


# ── /auth/refresh ─────────────────────────────────────────────────────────────
class TestRefreshEndpoint:
    def test_refresh_issues_new_token(self, client: TestClient):
        client.post(
            "/auth/login",
            data={"username": "admin", "password": TEST_PASSWORDS["admin"]},
        )
        r = client.post("/auth/refresh")
        assert r.status_code == 200
        assert r.json()["access_token"]
        assert r.json()["role"] == "admin"

    def test_refresh_without_cookie_401(self, client: TestClient):
        r = client.post("/auth/refresh")
        assert r.status_code == 401

    def test_refresh_rotates_token(self, client: TestClient):
        client.post(
            "/auth/login",
            data={"username": "admin", "password": TEST_PASSWORDS["admin"]},
        )
        old_refresh = client.cookies.get("refresh_token")
        r = client.post("/auth/refresh")
        assert r.status_code == 200
        # старый refresh теперь revoked — повторное использование запрещено
        r2 = client.post("/auth/refresh", cookies={"refresh_token": old_refresh})
        assert r2.status_code == 401

    def test_access_token_cannot_refresh(self, client: TestClient):
        login = client.post(
            "/auth/login",
            data={"username": "admin", "password": TEST_PASSWORDS["admin"]},
        )
        access = login.json()["access_token"]
        r = client.post("/auth/refresh", cookies={"refresh_token": access})
        assert r.status_code == 401


# ── /auth/logout ──────────────────────────────────────────────────────────────
class TestLogoutEndpoint:
    def test_logout_revokes_access(self, client: TestClient):
        login = client.post(
            "/auth/login",
            data={"username": "owner", "password": TEST_PASSWORDS["owner"]},
        )
        token = login.json()["access_token"]
        # работает до logout
        assert client.get("/portfolio", headers=auth_header(token)).status_code == 200
        r = client.post("/auth/logout", headers=auth_header(token))
        assert r.status_code == 204
        # после logout — 401
        assert client.get("/portfolio", headers=auth_header(token)).status_code == 401

    def test_logout_requires_auth(self, client: TestClient):
        r = client.post("/auth/logout")
        assert r.status_code == 401


# ── Rate limiting ─────────────────────────────────────────────────────────────
class TestAuthRateLimit:
    def test_login_rate_limited_after_5(self, client: TestClient):
        codes = []
        for _ in range(6):
            r = client.post(
                "/auth/login", data={"username": "x", "password": "y"}
            )
            codes.append(r.status_code)
        assert codes[-1] == 429

    def test_rate_limit_headers(self, client: TestClient):
        for _ in range(6):
            r = client.post(
                "/auth/login", data={"username": "x", "password": "y"}
            )
        assert "Retry-After" in r.headers
        assert "X-RateLimit-Limit" in r.headers

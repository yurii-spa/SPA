"""
spa_core/tests/test_academy_api.py

Integration tests for the Academy FastAPI sub-application (stage 3).

Exercises create_academy_app end-to-end via Starlette's TestClient against a
throwaway tmp-file DB — NO network, NO real data/ dir. Covers the health probe,
the invite-gated register/login/logout/me flow (cookie + CSRF), and a couple of
the security middlewares (rate limit + seed-phrase guard) at the HTTP boundary.

Requires argon2-cffi + fastapi[testclient] (httpx). SPA_ACADEMY_DEV=1 is forced
so the session cookie is non-Secure and survives the http:// TestClient.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import invites
from spa_core.academy.api.app import create_academy_app


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    # Leave rate limiting at its default (ON) — the rate-limit test relies on it.
    monkeypatch.delenv("SPA_ACADEMY_RATE_LIMIT", raising=False)
    monkeypatch.delenv("SPA_TRUST_PROXY", raising=False)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "academy_api.db"
    d = AcademyDB(db_path=str(p))
    d.run_migrations()
    return str(p)


@pytest.fixture()
def db(db_path):
    return AcademyDB(db_path=db_path)


@pytest.fixture()
def client(db_path):
    return TestClient(create_academy_app(db_path=db_path))


@pytest.fixture()
def invite(db):
    return invites.create_invite(db, max_uses=5)


def _register(client, invite, email="alice@example.com", password="password123"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "invite_code": invite},
    )


# ── health ──────────────────────────────────────────────────────────────────


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── register ────────────────────────────────────────────────────────────────


def test_register_without_invite_rejected(client):
    r = client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert r.status_code in (400, 422)


def test_register_with_invite_sets_cookie(client, invite):
    r = _register(client, invite)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["csrf_token"]
    assert body["user"]["email"] == "alice@example.com"
    assert "academy_session" in r.headers.get("set-cookie", "")


def test_register_duplicate_email_conflict(client, invite):
    assert _register(client, invite).status_code == 200
    # Fresh client so the first session cookie doesn't matter; same email.
    r = _register(client, invite, email="alice@example.com")
    assert r.status_code == 409


# ── login ───────────────────────────────────────────────────────────────────


def test_login_correct_credentials(client, invite):
    _register(client, invite)
    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["csrf_token"]
    assert "academy_session" in r.headers.get("set-cookie", "")


def test_login_wrong_password_unified_401(client, invite):
    _register(client, invite)
    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "not-the-password"},
    )
    assert r.status_code == 401


# ── me ──────────────────────────────────────────────────────────────────────


def test_me_with_cookie(client, invite):
    _register(client, invite)  # client jar now holds the session cookie
    r = client.get("/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["wallets"] == []
    # progress_summary spans lessons 0..8, all not_started for a fresh user.
    assert body["progress_summary"]["0"] == "not_started"
    assert len(body["progress_summary"]) == 9


def test_me_without_cookie_401(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


# ── logout (+ CSRF) ──────────────────────────────────────────────────────────


def test_logout_with_csrf(client, invite):
    reg = _register(client, invite)
    csrf = reg.json()["csrf_token"]
    r = client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    # Session revoked → /auth/me now unauthenticated.
    assert client.get("/auth/me").status_code == 401


def test_logout_without_csrf_403(client, invite):
    _register(client, invite)
    r = client.post("/auth/logout")
    assert r.status_code == 403


# ── security middlewares at the HTTP boundary ───────────────────────────────


def test_login_rate_limit_trips_on_sixth(client):
    last = None
    for i in range(6):
        last = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": f"password{i:03d}"},
        )
    assert last.status_code == 429
    assert last.headers.get("retry-after") is not None


def test_seed_phrase_rejected(client):
    words = (
        "abandon ability able about above absent absorb abstract absurd "
        "abuse access accident"
    )
    r = client.post("/verify/submit", json={"note": words})
    assert r.status_code == 400
    assert r.json()["error"] == "SEED_PHRASE_REJECTED"


def test_private_key_rejected(client):
    r = client.post("/verify/submit", json={"note": "0x" + "a" * 64})
    assert r.status_code == 400
    assert r.json()["error"] == "SEED_PHRASE_REJECTED"


def test_tx_hash_field_allowed(client):
    # A legit top-level tx_hash must pass the guard (route then 404s — not 400).
    r = client.post("/verify/submit", json={"tx_hash": "0x" + "a" * 64})
    assert r.status_code != 400

"""
spa_core/tests/test_academy_ratelimit.py

Focused tests for the Academy per-scope rate limiter (AcademyRateLimit).

Verifies the login bucket (5 / 900s per IP + per email) trips on the 6th
attempt with a Retry-After header, and that a 429 writes an ``action=lockout``
audit row. Tmp-file DB, NO network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.api.app import create_academy_app


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    monkeypatch.delenv("SPA_ACADEMY_RATE_LIMIT", raising=False)
    monkeypatch.delenv("SPA_TRUST_PROXY", raising=False)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "academy_ratelimit.db"
    d = AcademyDB(db_path=str(p))
    d.run_migrations()
    return str(p)


@pytest.fixture()
def db(db_path):
    return AcademyDB(db_path=db_path)


@pytest.fixture()
def client(db_path):
    return TestClient(create_academy_app(db_path=db_path))


def _hammer_login(client, n=6, email="target@example.com"):
    out = []
    for i in range(n):
        out.append(
            client.post(
                "/auth/login",
                json={"email": email, "password": f"password{i:03d}"},
            )
        )
    return out


def test_sixth_login_is_429_with_retry_after(client):
    responses = _hammer_login(client, n=6)
    assert responses[-1].status_code == 429
    assert responses[-1].headers.get("retry-after") is not None
    # None of the first five should have been throttled.
    for r in responses[:5]:
        assert r.status_code != 429


def test_lockout_event_recorded(client, db):
    _hammer_login(client, n=6)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE action = 'lockout'"
        ).fetchone()
    assert row["c"] >= 1


def test_disable_flag_lets_traffic_through(monkeypatch, client):
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")
    responses = _hammer_login(client, n=8)
    # With the limiter disabled, no request is a 429 (all unified 401s instead).
    assert all(r.status_code != 429 for r in responses)

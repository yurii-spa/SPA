"""Tests for /api/swarm/* (block-6 surface) — verbatim serve, advisory stamps, fail-closed."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from spa_core.api import server  # noqa: E402
from spa_core.api.routers import swarm as swarm_router  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


ENDPOINTS = ["/api/swarm/guardian", "/api/swarm/regime", "/api/swarm/blend",
             "/api/swarm/brain", "/api/swarm/health"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_endpoint_never_500_and_always_stamped(client, path):
    r = client.get(path)
    assert r.status_code == 200
    doc = r.json()
    # advisory stamps are AUTHORITATIVE regardless of artifact availability/content
    assert doc["advisory"] is True
    assert doc["outside_riskpolicy"] is True
    assert doc["live_eligible"] is False
    assert "never moves capital" in doc["note"]
    assert isinstance(doc["available"], bool)


def test_missing_artifact_fail_closed_envelope(client, monkeypatch):
    monkeypatch.setattr(swarm_router, "read_state", lambda *a, **k: {})
    r = client.get("/api/swarm/blend")
    doc = r.json()
    assert r.status_code == 200
    assert doc["available"] is False
    assert "not produced yet" in doc["unavailable_reason"]


def test_artifact_served_verbatim_with_stamps_forced(client, monkeypatch):
    fake = {"regime": "GREEN", "symbols": {"ETH": {"regime": "GREEN"}},
            "as_of_utc": "2026-07-11T12:00:00+00:00",
            # a producer bug tries to claim live-eligibility — the surface must override:
            "live_eligible": True, "advisory": False}
    monkeypatch.setattr(swarm_router, "read_state", lambda *a, **k: json.loads(json.dumps(fake)))
    doc = client.get("/api/swarm/regime").json()
    assert doc["available"] is True
    assert doc["regime"] == "GREEN"                      # verbatim payload
    assert doc["advisory"] is True and doc["live_eligible"] is False  # stamps forced

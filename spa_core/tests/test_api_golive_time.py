"""ADR-554 DQ-4: /api/v1/golive keeps the checker's own timestamp; request time travels as `served_at`.

Before, the route overwrote `timestamp` with the request time, so a days-old golive_status.json read as
fresh to every API reader (the class of invariant #17: an absent observation presented as a current one)."""
# FROZEN-DATE-OK: the literal is the checker's recorded time — the subject of the test, not a freshness window
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402

CHECKED_AT = "2026-09-01T08:00:00+00:00"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def test_golive_keeps_the_checkers_time_and_adds_served_at(client):
    c, tmp = client
    (tmp / "golive_status.json").write_text(json.dumps({"timestamp": CHECKED_AT, "passed": 29, "total": 29}))
    body = c.get("/api/v1/golive").json()
    assert body["timestamp"] == CHECKED_AT          # the observation time, not the request time
    assert body["served_at"] and body["served_at"] != CHECKED_AT
    assert body["source"] == "file"


def test_golive_without_a_recorded_time_says_so(client):
    c, tmp = client
    (tmp / "golive_status.json").write_text(json.dumps({"passed": 29, "total": 29}))
    body = c.get("/api/v1/golive").json()
    assert body["timestamp"] is None and body["served_at"]

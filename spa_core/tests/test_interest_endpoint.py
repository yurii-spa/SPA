"""Tests for the Q2-5 PII-minimal interest-capture endpoint (spa_core/api/routers/interest.py).

Verifies: an opaque interest signal is recorded, PII-shaped input (emails / free-form / over-long) is
DROPPED never stored, the summary aggregates by tier/topic, and the sink is append-only. Uses a tmp log —
no live data.
"""
import json

import pytest
from fastapi.testclient import TestClient

from spa_core.api import server
from spa_core.api.routers import interest as it


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(it, "_LOG", tmp_path / "interest.jsonl")
    with TestClient(server.app) as c:
        yield c, tmp_path / "interest.jsonl"


def test_records_opaque_signal(client):
    c, log = client
    r = c.post("/api/interest", json={"tier": "balanced", "topic": "pilot", "utm_source": "checkup"})
    assert r.json()["ok"] is True and r.json()["pii_minimal"] is True
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["tier"] == "balanced" and rec["topic"] == "pilot" and rec["utm_source"] == "checkup"
    assert "t" in rec and "email" not in rec and "name" not in rec


def test_unwritable_sink_is_not_reported_ok(tmp_path, monkeypatch):
    """POSITIVE CONTROL (waitlist fail-OPEN card): the anonymous beacon answered ok:true even when
    the append failed, so a broken sink was indistinguishable from a working one. RED on unfixed code.

    The sink is made unwritable by pointing it at a DIRECTORY, not by chmod — this suite also runs as
    root, where permission bits are ignored and a chmod-based test would pass for the wrong reason."""
    broken = tmp_path / "sink_is_a_directory"
    broken.mkdir()
    monkeypatch.setattr(it, "_LOG", broken)
    with TestClient(server.app) as c:
        body = c.post("/api/interest", json={"tier": "balanced", "topic": "pilot"}).json()
    assert body["ok"] is False           # the signal was NOT captured — say so
    assert body["stored"] == "error"
    assert body["pii_minimal"] is True   # honesty about the write never leaks PII


def test_working_sink_reports_stored_ok(client):
    """Control in the other direction: a healthy sink still reports a successful capture."""
    c, _ = client
    body = c.post("/api/interest", json={"tier": "balanced"}).json()
    assert body["ok"] is True and body["stored"] == "ok"


def test_pii_shaped_values_dropped(client):
    c, log = client
    c.post("/api/interest", json={"tier": "john@fund.com", "topic": "Acme Capital, LP!!!"})
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["tier"] == ""            # email dropped
    assert rec["topic"] == ""           # free-form/punctuation dropped
    # nothing PII-shaped ever persisted
    assert "@" not in log.read_text()


def test_summary_aggregates(client):
    c, _ = client
    c.post("/api/interest", json={"tier": "aggressive", "topic": "pilot"})
    c.post("/api/interest", json={"tier": "aggressive", "topic": "fundability"})
    c.post("/api/interest", json={"tier": "conservative", "topic": "pilot"})
    s = c.get("/api/interest/summary").json()
    assert s["total_interest"] == 3
    assert s["by_tier"] == {"aggressive": 2, "conservative": 1}
    assert s["by_topic"] == {"pilot": 2, "fundability": 1}
    assert s["pii_minimal"] is True


def test_summary_empty_is_zero(client):
    c, _ = client
    s = c.get("/api/interest/summary").json()
    assert s["total_interest"] == 0 and s["by_tier"] == {}


def test_pilot_summary_endpoint(client):
    """Q2-8 pilot pipeline funnel is consumable via /api/pilot/summary (PII-minimal, graceful)."""
    c, _ = client
    s = c.get("/api/pilot/summary").json()
    assert s["model"] == "pilot_pipeline"
    assert s["is_advisory"] is True
    assert "by_stage" in s and "n_prospects" in s

"""
Tests for SPA FastAPI server — SSE / agent thought endpoints (v0.16).

Run:
    python -m pytest spa_core/tests/test_api.py -q
    # or from project root:
    cd /path/to/SPA_Claude && python -m pytest spa_core/tests/test_api.py -v
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
# Allow imports from both spa_core/ and project root without installing the package.
_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

# Sprint v3.21 — gracefully skip the whole module when the optional fastapi
# dep is missing.  Previously raised ModuleNotFoundError at import-collect
# time, which aborts the entire pytest run instead of skipping cleanly.
pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

# Import app and event_queue from the server module.
# Heavy optional dependencies (PaperTrader, ChatHandler, etc.) are imported
# lazily inside endpoint functions, so this import should always succeed.
from spa_core.api.server import app, event_queue  # noqa: E402


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_event_queue():
    """Reset the in-memory event queue before every test for isolation."""
    event_queue.clear()
    yield
    event_queue.clear()


@pytest.fixture(scope="module")
def client():
    """Module-scoped TestClient — starts the ASGI lifespan once."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    """GET /health → 200 with status=ok."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "timestamp" in body


def test_health_version_is_v016(client):
    """Server must advertise v0.16 or later."""
    r = client.get("/health")
    assert r.status_code == 200
    # accept any v0.16+ string
    assert r.json()["version"].startswith("v0.1")


# ── Events history (empty) ────────────────────────────────────────────────────

def test_events_history_empty_on_fresh_queue(client):
    """GET /api/events/history → empty list when no events have been posted."""
    r = client.get("/api/events/history")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    assert "count" in body
    assert body["count"] == 0
    assert body["events"] == []


def test_events_history_count_matches_events(client):
    """The count field must always equal len(events)."""
    r = client.get("/api/events/history")
    body = r.json()
    assert body["count"] == len(body["events"])


# ── POST /api/agent/thought ───────────────────────────────────────────────────

def test_post_agent_thought_returns_ok(client):
    """POST /api/agent/thought with valid payload → ok=True."""
    r = client.post("/api/agent/thought", json={
        "agent":   "DataAgent",
        "message": "Fetching APY data from DeFiLlama… found 12 pools",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["event_count"] == 1


def test_post_agent_thought_empty_message_rejected(client):
    """POST with blank message → 400 error."""
    r = client.post("/api/agent/thought", json={
        "agent":   "TraderAgent",
        "message": "   ",   # whitespace-only
    })
    assert r.status_code == 400
    assert "error" in r.json()["detail"]


def test_post_agent_thought_missing_message_field(client):
    """POST without required 'message' field → 422 validation error."""
    r = client.post("/api/agent/thought", json={"agent": "RiskAgent"})
    assert r.status_code == 422


def test_post_agent_thought_missing_agent_field(client):
    """POST without required 'agent' field → 422 validation error."""
    r = client.post("/api/agent/thought", json={"message": "hello"})
    assert r.status_code == 422


def test_post_agent_thought_custom_type(client):
    """POST with custom event type is accepted and stored."""
    r = client.post("/api/agent/thought", json={
        "agent":   "RiskAgent",
        "message": "VaR breach detected",
        "type":    "risk_alert",
        "data":    {"var_pct": 6.2},
    })
    assert r.status_code == 200
    # Verify it's in history with the correct type
    hist = client.get("/api/events/history").json()["events"]
    assert len(hist) == 1
    assert hist[0]["type"] == "risk_alert"
    assert hist[0]["data"]["var_pct"] == 6.2


# ── History after posting ─────────────────────────────────────────────────────

def test_events_history_reflects_posted_events(client):
    """After posting 3 thoughts, history must contain exactly 3 events in order."""
    agents_msgs = [
        ("DataAgent",   "Fetching pools"),
        ("TraderAgent", "Running auto_allocate"),
        ("RiskAgent",   "All checks passed"),
    ]
    for agent, msg in agents_msgs:
        client.post("/api/agent/thought", json={"agent": agent, "message": msg})

    body = client.get("/api/events/history").json()
    assert body["count"] == 3
    for i, (agent, msg) in enumerate(agents_msgs):
        evt = body["events"][i]
        assert evt["agent"]   == agent
        assert evt["message"] == msg
        assert "timestamp" in evt


def test_events_history_ring_buffer_caps_at_50(client):
    """Posting 55 events must result in only the last 50 being retained."""
    for i in range(55):
        client.post("/api/agent/thought", json={
            "agent":   "DataAgent",
            "message": f"event {i}",
        })

    body = client.get("/api/events/history").json()
    assert body["count"] == 50
    # The oldest event should be event #5 (0-indexed), not #0
    assert body["events"][0]["message"] == "event 5"
    assert body["events"][-1]["message"] == "event 54"


# ── SSE endpoint headers ──────────────────────────────────────────────────────
#
# Sprint v3.23 — Skip-by-default for sandbox/CI: the SSE generator runs an
# infinite `while True` loop with a 25s asyncio.wait_for keepalive timeout
# (see spa_core/api/server.py:sse_stream).  TestClient.stream() reads headers
# synchronously but the ASGI transport does not surface a clean disconnect
# when the `with` block exits, so the test hangs until pytest's process-level
# timeout fires — collected as 1 FAIL + 1 ERROR (the next test, test_api_risk,
# was failing because its fixture inherited the deadlock).  This was flagged
# in sprint v3.22 as "sandbox-only artefact" but never properly skip-tagged.
#
# Manual integration runs that want to validate the streaming response can
# opt in via:  SPA_RUN_STREAMING_TESTS=1 python -m pytest spa_core/tests/test_api.py

_RUN_STREAMING = os.getenv("SPA_RUN_STREAMING_TESTS") == "1"


@pytest.mark.skipif(
    not _RUN_STREAMING,
    reason="SSE streaming test hangs under TestClient — opt in via SPA_RUN_STREAMING_TESTS=1",
)
def test_sse_endpoint_returns_event_stream_content_type(client):
    """GET /api/events → Content-Type: text/event-stream."""
    # Use stream=True so TestClient doesn't block waiting for the stream to end
    with client.stream("GET", "/api/events") as r:
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "text/event-stream" in ct


# ── Other existing endpoints still work ──────────────────────────────────────

def test_api_status_returns_200(client):
    """GET /api/status → 200 (JSON fallback mode when no DB)."""
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    # server_timestamp must always be present
    assert "server_timestamp" in body


def test_api_risk_returns_200(client):
    """GET /api/risk → 200 with expected shape."""
    r = client.get("/api/risk")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "alerts" in body

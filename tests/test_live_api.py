"""
Tests for the /api/live/* low-latency dashboard endpoints (live-api-v1).

These endpoints let the public dashboard (earn-defi.com) poll the Mac mini
directly through the Cloudflare tunnel (api.earn-defi.com) every ~15s instead
of waiting ~60min for the GitHub-pushed JSON snapshot.

Contract under test:
    * /api/live/ping       → {"ok": true, ...}
    * /api/live/agents     → agent_health.json data, or {"status": "no_data"}
    * /api/live/portfolio  → bundle of available portfolio files (+ _fetched_at)
    * /api/live/system     → bundle of available system files (+ _fetched_at)
    * /api/live/data/<f>   → verbatim data/<f>.json, traversal-safe
    * never 5xx on missing/corrupt files (graceful degradation)
    * CORS headers present for earn-defi.com origin
"""
from __future__ import annotations

import importlib
import json

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh app instance bound to an isolated temp data dir."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    import spa_core.api.server as server
    importlib.reload(server)
    assert server._DATA_DIR == tmp_path
    with TestClient(server.app) as c:
        c._data_dir = tmp_path  # type: ignore[attr-defined]
        yield c


def _write(client, name, obj):
    (client._data_dir / name).write_text(json.dumps(obj), encoding="utf-8")


# ─── ping ────────────────────────────────────────────────────────────────────

def test_ping_ok(client):
    r = client.get("/api/live/ping")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == "live-api-v1"
    assert isinstance(body["ts"], (int, float))


def test_ping_no_files_needed(client):
    # ping must work with a completely empty data dir
    assert client.get("/api/live/ping").json()["ok"] is True


# ─── agents ──────────────────────────────────────────────────────────────────

def test_agents_no_data_when_missing(client):
    r = client.get("/api/live/agents")
    assert r.status_code == 200
    assert r.json()["status"] == "no_data"


def test_agents_returns_data_when_present(client):
    _write(client, "agent_health.json",
           {"overall_status": "OK", "total_agents": 5, "healthy_count": 5})
    r = client.get("/api/live/agents")
    assert r.status_code == 200
    body = r.json()
    assert body["overall_status"] == "OK"
    assert body["total_agents"] == 5
    assert "_fetched_at" in body


def test_agents_corrupt_json_degrades_not_500(client):
    (client._data_dir / "agent_health.json").write_text("{not valid json", encoding="utf-8")
    r = client.get("/api/live/agents")
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_agents_list_payload_wrapped(client):
    _write(client, "agent_health.json", [{"a": 1}, {"b": 2}])
    body = client.get("/api/live/agents").json()
    assert body["data"] == [{"a": 1}, {"b": 2}]
    assert "_fetched_at" in body


# ─── portfolio ───────────────────────────────────────────────────────────────

def test_portfolio_empty_dir(client):
    r = client.get("/api/live/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert "_fetched_at" in body
    # no portfolio files → only the timestamp key
    assert set(body.keys()) == {"_fetched_at"}


def test_portfolio_partial_files(client):
    _write(client, "equity_curve_daily.json", [{"day": 1, "v": 100000}])
    # pnl_history.json + portfolio_state.json intentionally absent
    r = client.get("/api/live/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert body["equity_curve_daily"] == [{"day": 1, "v": 100000}]
    assert "pnl_history" not in body
    assert "portfolio_state" not in body
    assert "_fetched_at" in body


def test_portfolio_corrupt_file_isolated(client):
    _write(client, "equity_curve_daily.json", [{"day": 1}])
    (client._data_dir / "pnl_history.json").write_text("broken{", encoding="utf-8")
    r = client.get("/api/live/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert body["equity_curve_daily"] == [{"day": 1}]
    assert "_error" in body["pnl_history"]


# ─── system ──────────────────────────────────────────────────────────────────

def test_system_empty_dir(client):
    r = client.get("/api/live/system")
    assert r.status_code == 200
    assert set(r.json().keys()) == {"_fetched_at"}


def test_system_with_health(client):
    _write(client, "system_health.json", {"overall": "OK", "domains": 7})
    body = client.get("/api/live/system").json()
    assert body["system_health"] == {"overall": "OK", "domains": 7}
    assert "_fetched_at" in body


def test_system_includes_golive(client):
    _write(client, "golive_status.json", {"ready": False, "pass": 26})
    body = client.get("/api/live/system").json()
    assert body["golive_status"]["pass"] == 26


# ─── data passthrough ────────────────────────────────────────────────────────

def test_data_file_served_verbatim(client):
    payload = {"hello": "world", "n": [1, 2, 3]}
    _write(client, "system_health.json", payload)
    r = client.get("/api/live/data/system_health.json")
    assert r.status_code == 200
    assert r.json() == payload


def test_data_file_missing_404(client):
    r = client.get("/api/live/data/does_not_exist.json")
    assert r.status_code == 404


def test_data_file_rejects_non_json(client):
    r = client.get("/api/live/data/secrets.txt")
    assert r.status_code == 400


def test_data_file_rejects_traversal(client):
    # encoded slash / parent refs must never escape the data dir
    for bad in ["..%2f..%2fetc%2fpasswd", "%2e%2e%2fconfig.json"]:
        r = client.get(f"/api/live/data/{bad}")
        assert r.status_code in (400, 404)


def test_data_file_corrupt_502(client):
    (client._data_dir / "system_health.json").write_text("not json{", encoding="utf-8")
    r = client.get("/api/live/data/system_health.json")
    assert r.status_code == 502


# ─── CORS ────────────────────────────────────────────────────────────────────

def test_cors_allows_earn_defi(client):
    r = client.get("/api/live/ping", headers={"Origin": "https://earn-defi.com"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://earn-defi.com"


def test_cors_allows_www_earn_defi(client):
    r = client.get("/api/live/ping", headers={"Origin": "https://www.earn-defi.com"})
    assert r.headers.get("access-control-allow-origin") == "https://www.earn-defi.com"


def test_cors_allows_localhost(client):
    r = client.get("/api/live/ping", headers={"Origin": "http://localhost:8080"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8080"


def test_cors_preflight_get(client):
    r = client.options(
        "/api/live/portfolio",
        headers={
            "Origin": "https://earn-defi.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "https://earn-defi.com"


def test_cors_disallows_unknown_origin(client):
    r = client.get("/api/live/ping", headers={"Origin": "https://evil.example.com"})
    # FastAPI omits the allow-origin header for disallowed origins
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"


# ─── read-only guarantee ─────────────────────────────────────────────────────

def test_live_endpoints_are_get_only(client):
    for path in ["/api/live/ping", "/api/live/agents",
                 "/api/live/portfolio", "/api/live/system"]:
        assert client.post(path).status_code == 405

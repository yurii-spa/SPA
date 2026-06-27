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


# ─── health (track-accrual freshness, P4-2) ───────────────────────────────────

def _equity_with_bar(date, evidenced=True):
    return {"daily": [{"date": date, "close_equity": 100000.0,
                       "open_equity": 100000.0,
                       "evidenced": evidenced,
                       "source": "cycle" if evidenced else "backfill"}]}


def test_health_always_200(client):
    # empty dir → still 200, but degraded (no track to read = fail-closed)
    r = client.get("/api/live/health")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "live-api-v1"
    assert body["status"] == "degraded"
    assert body["track_fresh"] is False


def test_health_fresh_track_is_ok(client):
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    _write(client, "equity_curve_daily.json", _equity_with_bar(today))
    body = client.get("/api/live/health").json()
    assert body["status"] == "ok"
    assert body["track_fresh"] is True
    assert body["track"]["last_evidenced_date"] == today


def test_health_stale_track_is_degraded(client):
    # evidenced bar dated after the anchor but old → degraded (still 200)
    _write(client, "equity_curve_daily.json", _equity_with_bar("2026-06-11"))
    r = client.get("/api/live/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["track_fresh"] is False
    assert body["track"]["age_hours"] > body["track"]["sla_hours"]


def test_health_fail_closed_corrupt_track(client):
    (client._data_dir / "equity_curve_daily.json").write_text("{broken", encoding="utf-8")
    body = client.get("/api/live/health").json()
    assert body["status"] == "degraded"
    assert body["track_fresh"] is False


# ─── fleet (agent_health.json summary + snapshot-age staleness) ───────────────

def _fleet_snapshot(ts, ok=45, warn=2, crit=0, total=47, overall="WARNING", agents=None):
    if agents is None:
        agents = [
            {"label": "com.spa.agent_health", "status": "OK", "issue": ""},
            {"label": "com.spa.daily_cycle", "status": "WARNING",
             "issue": "log missing (never ran?)"},
            {"label": "com.spa.weekly_backup", "status": "WARNING",
             "issue": "log missing (never ran?)"},
        ]
    return {
        "timestamp": ts, "overall_status": overall,
        "healthy_count": ok, "warning_count": warn, "critical_count": crit,
        "total_agents": total, "agents": agents,
    }


def _iso(minutes_ago):
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(minutes=minutes_ago)).isoformat()


def test_fleet_missing_is_honest_unavailable(client):
    r = client.get("/api/live/fleet")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["stale"] is True
    # must NOT fabricate counts
    assert "healthy" not in body


def test_fleet_fresh_snapshot_not_stale(client):
    _write(client, "agent_health.json", _fleet_snapshot(_iso(5.0)))
    body = client.get("/api/live/fleet").json()
    assert body["available"] is True
    assert body["stale"] is False
    assert body["healthy"] == 45
    assert body["warning"] == 2
    assert body["critical"] == 0
    assert body["total"] == 47
    assert body["overall_status"] == "WARNING"
    assert body["snapshot_age_min"] is not None and body["snapshot_age_min"] < 35
    # only the warn/crit agents are surfaced (the OK one is filtered out)
    names = {a["name"] for a in body["agents"]}
    assert names == {"com.spa.daily_cycle", "com.spa.weekly_backup"}
    assert all(a["reason"] for a in body["agents"])


def test_fleet_old_snapshot_is_stale(client):
    # snapshot older than the 35-min threshold → stale:true (counts still echoed)
    _write(client, "agent_health.json", _fleet_snapshot(_iso(90.0)))
    body = client.get("/api/live/fleet").json()
    assert body["available"] is True
    assert body["stale"] is True
    assert body["snapshot_age_min"] > 35
    assert body["healthy"] == 45  # last-known still echoed, but flagged stale


def test_fleet_unparseable_timestamp_fail_closed_stale(client):
    _write(client, "agent_health.json", _fleet_snapshot("not-a-timestamp"))
    body = client.get("/api/live/fleet").json()
    assert body["available"] is True
    assert body["stale"] is True
    assert body["snapshot_age_min"] is None


def test_fleet_corrupt_json_honest_unavailable(client):
    (client._data_dir / "agent_health.json").write_text("{broken", encoding="utf-8")
    r = client.get("/api/live/fleet")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["stale"] is True


def test_fleet_critical_agents_surfaced(client):
    agents = [
        {"label": "com.spa.daily_cycle", "status": "CRITICAL", "issue": "dead"},
        {"label": "com.spa.ok_one", "status": "OK", "issue": ""},
    ]
    _write(client, "agent_health.json",
           _fleet_snapshot(_iso(2.0), ok=1, warn=0, crit=1, total=2,
                           overall="CRITICAL", agents=agents))
    body = client.get("/api/live/fleet").json()
    assert body["overall_status"] == "CRITICAL"
    assert len(body["agents"]) == 1
    assert body["agents"][0]["name"] == "com.spa.daily_cycle"
    assert body["agents"][0]["status"] == "CRITICAL"


# ─── safety (two-tier kill/de-risk state, D3-T3 / ADR-034) ────────────────────

def _iso_now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def test_safety_clear_when_no_state_files(client):
    # no derisk_status / kill_switch files at all → CLEAR, available, not stale
    r = client.get("/api/live/safety")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["state"] == "CLEAR"
    assert body["kill_active"] is False
    assert body["derisk_active"] is False
    assert body["stale"] is False


def test_safety_soft_derisk_active(client):
    _write(client, "derisk_status.json", {
        "generated_at": _iso_now(), "active": True, "tier": "SOFT_DERISK",
        "reason": "drawdown 8.00% ≥ 5.0% soft de-risk",
        "policy": "halt_new_allocations_no_increase_hold_reduce_only",
    })
    body = client.get("/api/live/safety").json()
    assert body["state"] == "SOFT_DERISK"
    assert body["derisk_active"] is True
    assert body["kill_active"] is False
    assert body["tier"] == "SOFT_DERISK"
    assert "8.00%" in body["reason"]
    assert body["stale"] is False


def test_safety_hard_kill_via_active_file(client):
    _write(client, "kill_switch_active.json", {
        "activated_at": _iso_now(), "reason": "drawdown 16.00% > 15.0% threshold",
        "source": "kill_switch_checker",
    })
    body = client.get("/api/live/safety").json()
    assert body["state"] == "HARD_KILL"
    assert body["kill_active"] is True
    assert body["derisk_active"] is False
    assert "16.00%" in body["reason"]


def test_safety_hard_kill_via_status_triggered(client):
    # no active-marker file, but status verdict says triggered → still HARD_KILL
    _write(client, "kill_switch_status.json", {
        "generated_at": _iso_now(), "triggered": True,
        "reason": "manual trigger active", "allocation": {"cash": 1.0},
    })
    body = client.get("/api/live/safety").json()
    assert body["state"] == "HARD_KILL"
    assert body["kill_active"] is True


def test_safety_kill_active_false_is_not_kill(client):
    # explicit deactivation marker must NOT read as an active kill
    _write(client, "kill_switch_active.json",
           {"active": False, "reason": "deactivated"})
    body = client.get("/api/live/safety").json()
    assert body["state"] == "CLEAR"
    assert body["kill_active"] is False


def test_safety_hard_kill_wins_over_soft(client):
    # both active → HARD kill is reported (higher severity)
    _write(client, "derisk_status.json",
           {"generated_at": _iso_now(), "active": True, "tier": "SOFT_DERISK"})
    _write(client, "kill_switch_active.json",
           {"activated_at": _iso_now(), "reason": "drawdown 20%"})
    body = client.get("/api/live/safety").json()
    assert body["state"] == "HARD_KILL"


def test_safety_stale_derisk_flagged(client):
    import datetime as _dt
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat()
    _write(client, "derisk_status.json",
           {"generated_at": old, "active": True, "tier": "SOFT_DERISK",
            "reason": "drawdown 7%"})
    body = client.get("/api/live/safety").json()
    assert body["state"] == "SOFT_DERISK"   # last-known still echoed
    assert body["stale"] is True            # but flagged stale


def test_safety_corrupt_derisk_is_unknown_not_clear(client):
    (client._data_dir / "derisk_status.json").write_text("{broken", encoding="utf-8")
    r = client.get("/api/live/safety")
    assert r.status_code == 200
    body = r.json()
    # fail-CLOSED: an unreadable state is UNKNOWN, never silently CLEAR
    assert body["state"] == "UNKNOWN"
    assert body["stale"] is True


def test_safety_inactive_derisk_is_clear(client):
    _write(client, "derisk_status.json",
           {"generated_at": _iso_now(), "active": False, "tier": "NONE"})
    body = client.get("/api/live/safety").json()
    assert body["state"] == "CLEAR"
    assert body["derisk_active"] is False
    assert body["stale"] is False


def test_safety_is_get_only(client):
    assert client.post("/api/live/safety").status_code == 405


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
    for path in ["/api/live/ping", "/api/live/agents", "/api/live/fleet",
                 "/api/live/safety", "/api/live/portfolio", "/api/live/system"]:
        assert client.post(path).status_code == 405

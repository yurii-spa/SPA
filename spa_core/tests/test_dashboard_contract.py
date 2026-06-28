"""Dashboard DATA-CONTRACT property tests (Sprint "Proof That Doesn't Rot", WS4 §4.3).

Replaces the retired brittle index.html string-match dashboard tests with CONTRACT tests on the
JSON the dashboard actually consumes. The single live dashboard is
``landing/src/components/DashboardLive.jsx``; it reads a FIXED set of endpoints + fields
(enumerated in its ``poll()`` and derived-state blocks). These tests assert — decoupled from any
HTML/JS blob — that those keys/shapes/ranges are present and well-typed, so a BACKEND FIELD RENAME
that would silently blank the dashboard FAILS HERE instead of in production.

Endpoints + fields the dashboard depends on (DashboardLive.jsx):
  /api/ssot/facts   → real_track_days|track_days, go_live_target, evidenced_anchor,
                      golive_passed, golive_total, current_equity, apy_today_pct, daily_yield_usd,
                      total_return_pct, regime, nav, nav_reconciliation_ok
  /api/live/fleet   → available, overall_status, healthy, warning, critical, total, stale
  /api/live/safety  → available, state, (label|reason), stale
  /api/live/status  → paper_trading_status.market_regime
  /api/v1/golive    → criteria: [{name, status}]
  /api/rates-desk/surface       → quotes[]
  /api/rates-desk/opportunities → opportunities[], n_opportunities
  /api/rates-desk/decisions     → decisions[], counts, n_decisions
  /api/rates-desk/track         → days, current_equity, daily_series[{date,equity,nav,net_apy_pct}],
                                  is_advisory
  /api/rates-desk/exit-nav      → schedule[], is_advisory, flagged
  /api/rates-desk/refusals      → chain.verified, decisions[], counts

The contract is asserted on BOTH a populated state dir (real fields present + typed) AND an empty
state dir (graceful fail-closed shape still carries the keys the dashboard reads, so a dead backend
shows "—"/offline for THAT section, never a crash). Field RENAMES are the regression target.

Run:  python3 -m pytest spa_core/tests/test_dashboard_contract.py -p no:randomly -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in (str(_SPA_CORE), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


# ─── fixtures ─────────────────────────────────────────────────────────────────
def _redirect_data_dir(monkeypatch, tmp_path):
    """Redirect BOTH the router data-dir (server._DATA_DIR) AND the SSOT module's own _DATA_DIR
    (which /api/ssot/facts → key_facts() reads independently) to the hermetic tmp dir."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    import spa_core.governance.ssot as _ssot
    monkeypatch.setattr(_ssot, "_DATA_DIR", tmp_path, raising=False)


@pytest.fixture()
def empty_client(tmp_path, monkeypatch):
    """TestClient over a hermetic, EMPTY data dir (no state files)."""
    _redirect_data_dir(monkeypatch, tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


@pytest.fixture()
def populated_client(tmp_path, monkeypatch):
    """TestClient over a data dir populated with canonical-shape state files."""
    _redirect_data_dir(monkeypatch, tmp_path)

    (tmp_path / "paper_trading_status.json").write_text(json.dumps({
        "days_running": 7, "real_track_days": 7, "paper_start_date": "2026-06-22",
        "current_equity": 100190.22, "total_return_pct": 0.19, "apy_today_pct": 3.6,
        "daily_yield_usd": 9.91, "market_regime": "VOLATILE",
    }))
    (tmp_path / "golive_status.json").write_text(json.dumps({
        "passed": 27, "total": 29, "ready": False,
        "evidenced_anchor": "2026-06-22", "target_date": "2026-07-21",
        "criteria": [
            {"name": "min_track_days_30", "status": "PENDING"},
            {"name": "nav_reconciles", "status": "PASS"},
        ],
    }))
    (tmp_path / "tier1_nav_proof.json").write_text(json.dumps({
        "computed_nav_usd": 100190.22, "reconciliation_ok": True,
    }))
    (tmp_path / "agent_health.json").write_text(json.dumps({
        "overall_status": "OK", "healthy_count": 51, "warning_count": 0,
        "critical_count": 0, "total_agents": 51,
        "timestamp": "2099-01-01T00:00:00+00:00", "agents": [],
    }))
    (tmp_path / "current_positions.json").write_text(json.dumps({"positions": []}))

    # rates-desk live surface + a valid 1-row paper track
    rd = tmp_path / "rates_desk"
    rd.mkdir()
    (rd / "rate_surface.json").write_text(json.dumps({
        "generated_at": "2026-06-25T00:00:00+00:00", "as_of": "2026-06-25", "mode": "live",
        "hedge_available": {"susde": False}, "underlying_risk": {},
        "quotes": [{"underlying": "susde", "venue": "pendle_pt", "quoted_rate": "0.09",
                    "tvl_usd": "5000000", "market_id": "m1"}],
    }))
    paper = rd / "paper"
    paper.mkdir()
    (paper / "status.json").write_text(json.dumps({
        "sleeve": {"id": "rates_desk_fixed_carry", "name": "FixedCarry", "net_apy_pct": 5.0},
        "gap": None,
    }))
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps({
        "id": "rates_desk_fixed_carry",
        "series": [{"date": "2026-06-22", "equity_usd": 100000.0, "net_apy_pct": 5.0},
                   {"date": "2026-06-23", "equity_usd": 100015.0, "net_apy_pct": 5.1}],
    }))

    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


# ─── contract helpers ─────────────────────────────────────────────────────────
def _require_keys(obj, keys, ctx=""):
    assert isinstance(obj, dict), f"{ctx}: expected dict, got {type(obj).__name__}"
    missing = [k for k in keys if k not in obj]
    assert not missing, f"{ctx}: dashboard-required keys MISSING (rename regression?): {missing}"


def _num_or_none(v):
    return v is None or isinstance(v, (int, float)) and not isinstance(v, bool)


# ══════════════════════════════════════════════════════════════════════════════
# /api/ssot/facts — the SSOT headline (decides global live/offline + overview)
# ══════════════════════════════════════════════════════════════════════════════
SSOT_FIELDS = (
    "track_days", "real_track_days", "go_live_target", "evidenced_anchor",
    "golive_passed", "golive_total", "current_equity", "apy_today_pct",
    "daily_yield_usd", "total_return_pct", "regime", "nav", "nav_reconciliation_ok",
)


class TestSsotFactsContract:
    def test_populated_carries_all_dashboard_fields(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/ssot/facts").json()
        _require_keys(d, SSOT_FIELDS, "/api/ssot/facts")
        # types the dashboard's fmtUsd/fmtPct helpers assume (number-or-null).
        for k in ("current_equity", "apy_today_pct", "daily_yield_usd", "total_return_pct",
                  "nav", "golive_passed", "golive_total", "real_track_days", "track_days"):
            assert _num_or_none(d[k]), f"/api/ssot/facts.{k} not number|null: {d[k]!r}"
        assert d["real_track_days"] == 7 and d["golive_passed"] == 27
        assert d["evidenced_anchor"] == "2026-06-22"
        assert d["regime"] == "VOLATILE"
        assert d["nav_reconciliation_ok"] is True

    def test_empty_still_carries_keys_as_none(self, empty_client):
        """Empty backend → the SSOT fields still EXIST (as None) so the dashboard renders '—',
        never KeyError-blanks. A rename would drop the key and fail this."""
        c, _ = empty_client
        d = c.get("/api/ssot/facts").json()
        # key_facts always returns the full envelope; values degrade to None.
        _require_keys(d, SSOT_FIELDS, "/api/ssot/facts (empty)")
        for k in SSOT_FIELDS:
            assert _num_or_none(d[k]) or d[k] is None or isinstance(d[k], (str, bool)), \
                f"{k}={d[k]!r}"


# ══════════════════════════════════════════════════════════════════════════════
# /api/live/fleet + /api/live/safety + /api/live/status
# ══════════════════════════════════════════════════════════════════════════════
class TestLiveFleetContract:
    def test_populated_fleet_shape(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/live/fleet").json()
        _require_keys(d, ("available", "overall_status", "healthy", "warning", "critical",
                          "total", "stale"), "/api/live/fleet")
        assert d["available"] is True
        for k in ("healthy", "warning", "critical", "total"):
            assert _num_or_none(d[k]), f"fleet.{k}={d[k]!r}"
        assert isinstance(d["stale"], bool)

    def test_empty_fleet_fail_closed_available_false(self, empty_client):
        c, _ = empty_client
        d = c.get("/api/live/fleet").json()
        # The dashboard guards `fleet.available !== false`; the key MUST exist.
        _require_keys(d, ("available", "stale"), "/api/live/fleet (empty)")
        assert d["available"] is False and d["stale"] is True


class TestLiveSafetyContract:
    def test_safety_shape_and_state_enum(self, empty_client):
        c, _ = empty_client
        d = c.get("/api/live/safety").json()
        _require_keys(d, ("available", "state", "stale"), "/api/live/safety")
        # The dashboard maps state → tone; it must be one of the known enum values.
        assert d["state"] in ("HARD_KILL", "SOFT_DERISK", "CLEAR", "UNKNOWN"), d["state"]
        # CLEAR is the honest empty-dir state (no kill/derisk files present).
        assert d["state"] == "CLEAR"

    def test_safety_carries_reason_or_label(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/live/safety").json()
        assert ("label" in d) or ("reason" in d), "safety must carry label|reason for the UI"


class TestLiveStatusContract:
    def test_status_paper_trading_regime_path(self, populated_client):
        """The dashboard reads status.paper_trading_status.market_regime as a regime fallback."""
        c, _ = populated_client
        d = c.get("/api/live/status").json()
        assert "paper_trading_status" in d, "/api/live/status missing paper_trading_status"
        pts = d["paper_trading_status"]
        assert isinstance(pts, dict) and "market_regime" in pts
        assert pts["market_regime"] == "VOLATILE"


# ══════════════════════════════════════════════════════════════════════════════
# /api/v1/golive — criteria list (the go-live checklist panel)
# ══════════════════════════════════════════════════════════════════════════════
class TestGoliveCriteriaContract:
    def test_criteria_array_of_name_status(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/v1/golive").json()
        assert isinstance(d.get("criteria"), list), "/api/v1/golive.criteria must be a list"
        for row in d["criteria"]:
            _require_keys(row, ("name", "status"), "/api/v1/golive.criteria[]")
            assert isinstance(row["name"], str)
            # the dashboard upcases status and matches PASS / FAIL / else→PENDING.
            assert isinstance(row["status"], str)


# ══════════════════════════════════════════════════════════════════════════════
# /api/rates-desk/* — the research-desks panels
# ══════════════════════════════════════════════════════════════════════════════
class TestRatesDeskContract:
    def test_surface_quotes_array(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/rates-desk/surface").json()
        assert isinstance(d.get("quotes"), list), "surface.quotes must be a list"
        assert len(d["quotes"]) >= 1

    def test_opportunities_shape(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/rates-desk/opportunities").json()
        _require_keys(d, ("opportunities", "n_opportunities"), "rates-desk/opportunities")
        assert isinstance(d["opportunities"], list)

    def test_decisions_counts_shape(self, empty_client):
        c, _ = empty_client
        d = c.get("/api/rates-desk/decisions").json()
        _require_keys(d, ("decisions", "counts", "n_decisions"), "rates-desk/decisions")
        assert isinstance(d["decisions"], list)
        _require_keys(d["counts"], ("ENTRY", "REFUSAL"), "decisions.counts")

    def test_track_daily_series_shape(self, populated_client):
        c, _ = populated_client
        d = c.get("/api/rates-desk/track").json()
        _require_keys(d, ("days", "current_equity", "daily_series", "is_advisory"),
                      "rates-desk/track")
        assert d["is_advisory"] is True
        assert isinstance(d["daily_series"], list) and len(d["daily_series"]) == 2
        for pt in d["daily_series"]:
            _require_keys(pt, ("date", "equity", "nav", "net_apy_pct"), "track.daily_series[]")
            assert _num_or_none(pt["equity"]) and _num_or_none(pt["nav"])
        assert d["current_equity"] == 100015.0

    def test_track_empty_fail_closed(self, empty_client):
        c, _ = empty_client
        d = c.get("/api/rates-desk/track").json()
        _require_keys(d, ("days", "daily_series", "is_advisory"), "rates-desk/track (empty)")
        assert d["days"] == 0 and d["daily_series"] == [] and d["is_advisory"] is True

    def test_exit_nav_schedule_shape(self, empty_client):
        c, _ = empty_client
        d = c.get("/api/rates-desk/exit-nav").json()
        _require_keys(d, ("schedule", "is_advisory", "flagged"), "rates-desk/exit-nav")
        assert isinstance(d["schedule"], list)
        assert d["is_advisory"] is True and d["flagged"] is True  # empty → flagged

    def test_refusals_chain_and_decisions_shape(self, empty_client):
        c, _ = empty_client
        d = c.get("/api/rates-desk/refusals").json()
        _require_keys(d, ("chain", "decisions", "counts"), "rates-desk/refusals")
        _require_keys(d["chain"], ("verified",), "refusals.chain")
        assert isinstance(d["chain"]["verified"], bool)
        assert isinstance(d["decisions"], list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-p", "no:randomly", "-q"]))

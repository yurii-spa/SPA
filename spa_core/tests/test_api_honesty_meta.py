"""
test_api_honesty_meta.py — honesty-labeling contract for the SPA API.

Honesty audit: no consumer (direct API / third party / cached page) may see a bare
backtest / assumed / annualized number as if it were a realized track record. The
server attaches an ADDITIVE `meta` envelope (and per-field labels) to the audited
endpoints. These tests assert:

  • the meta / label fields are present on each audited endpoint,
  • is_backtest=true (and is_realized=false) where applicable,
  • existing fields the site consumes are STILL present (backward-compat),
  • assumed-yield sleeves (engine_b/c) are labeled yield_basis="assumed", live feeds
    "live_feed", and the misleading paper_apy carries apy_source="backtest_derived".

Hermetic: the server's _DATA_DIR is redirected to a tmp dir per test so we control
the served files. Read-only, deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with the server data dir redirected to a hermetic tmp dir."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def _write(data_dir: Path, name: str, payload) -> None:
    p = data_dir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _assert_backtest_meta(meta: dict) -> None:
    assert isinstance(meta, dict)
    assert meta.get("is_backtest") is True
    assert meta.get("is_realized") is False
    assert meta.get("basis")
    assert meta.get("period")
    assert "not realized" in meta.get("disclaimer", "").lower() \
        or "not a track record" in meta.get("disclaimer", "").lower()


# ── /api/strategy-lab ──────────────────────────────────────────────────────────
def test_strategy_lab_meta_and_yield_basis(client):
    c, data_dir = client
    _write(data_dir, "strategy_lab_backtest.json", {
        "manifest": {
            "rwa_floor_apy_pct": 3.37, "window_start": "2024-06-05",
            "window_end": "2026-06-24", "generated_at": "2026-06-26T00:00:00+00:00",
        },
        "kills": {},
        "strategies": {
            "engine_b": {"id": "engine_b", "name": "Engine B", "mandate": "stable",
                         "metrics": {"net_apy_pct": 8.33, "sharpe": 1.2}},
            "engine_c": {"id": "engine_c", "name": "Engine C", "mandate": "stable",
                         "metrics": {"net_apy_pct": 8.87, "sharpe": 1.1}},
            "rwa_floor": {"id": "rwa_floor", "name": "RWA floor", "mandate": "stable",
                          "metrics": {"net_apy_pct": 3.43}},
            "eth_lst_neutral": {"id": "eth_lst_neutral", "name": "ETH LST neutral",
                                "mandate": "neutral", "metrics": {"net_apy_pct": 0.0}},
        },
    })
    r = c.get("/api/strategy-lab")
    assert r.status_code == 200
    d = r.json()
    # backward-compat: site reads these top-level fields verbatim
    assert "strategies" in d and "rwa_floor_pct" in d
    assert d["rwa_floor_pct"] == 3.37
    _assert_backtest_meta(d["meta"])
    by_id = {s["id"]: s for s in d["strategies"]}
    # existing per-sleeve fields preserved
    assert by_id["engine_b"]["net_apy_pct"] == 8.33
    # assumed-yield labels
    assert by_id["engine_b"]["yield_basis"] == "assumed"
    assert by_id["engine_c"]["yield_basis"] == "assumed"
    assert by_id["rwa_floor"]["yield_basis"] == "live_feed"
    # default for a live/realized sleeve
    assert by_id["eth_lst_neutral"]["yield_basis"] == "realized"


def test_strategy_lab_empty_still_has_meta(client):
    c, _ = client
    r = c.get("/api/strategy-lab")
    assert r.status_code == 200
    d = r.json()
    assert d["strategies"] == []
    _assert_backtest_meta(d["meta"])


# ── /api/strategy-lab/promotion ────────────────────────────────────────────────
def test_strategy_lab_promotion_meta(client):
    c, data_dir = client
    _write(data_dir, "strategy_lab_promotion.json", {
        "generated_at": "2026-06-26T00:00:00+00:00",
        "model": "strategy_lab_promotion", "rwa_floor_pct": 3.37,
        "n_sleeves": 2, "stage_counts": {"PAPER_CANDIDATE": 1},
        "sleeves": [{"id": "engine_b", "stage": "PAPER_CANDIDATE"}],
    })
    r = c.get("/api/strategy-lab/promotion")
    assert r.status_code == 200
    d = r.json()
    # backward-compat
    assert d["n_sleeves"] == 2 and d["model"] == "strategy_lab_promotion"
    assert d["sleeves"][0]["id"] == "engine_b"
    _assert_backtest_meta(d["meta"])


def test_strategy_lab_promotion_empty_has_meta(client):
    c, _ = client
    d = c.get("/api/strategy-lab/promotion").json()
    _assert_backtest_meta(d["meta"])


# ── /api/strategy-lab/promotion → rates_desk section (REPORTING ONLY, advisory) ──
def _write_rates_desk_promotion(data_dir: Path) -> None:
    """Hermetic rates-desk promotion mapping + backtest (for the BasisHedge proxy)."""
    _write(data_dir, "rates_desk/rates_desk_promotion.json", {
        "generated_at": "2026-06-26T00:00:00+00:00",
        "model": "rates_desk_promotion",
        "rwa_floor_pct": 3.4,
        "pipeline": "RESEARCH -> BACKTEST -> WALK-FORWARD -> PAPER -> CANARY -> FULL",
        "n_sleeves": 4,
        "stage_counts": {"PAPER_CANDIDATE": 3, "BLOCKED-NO-HEDGE": 1},
        "sleeves": [
            {"id": "rates_desk_fixed_carry", "shape": "fixed_carry",
             "stage": "PAPER_CANDIDATE", "net_apy_pct": 6.0901, "beats_floor": True},
            {"id": "rates_desk_levered_carry", "shape": "levered_carry",
             "stage": "PAPER_CANDIDATE", "net_apy_pct": 4.9571, "beats_floor": True},
            {"id": "rates_desk_rate_matrix", "shape": "rate_matrix",
             "stage": "PAPER_CANDIDATE", "net_apy_pct": 6.0863, "beats_floor": True},
            {"id": "rates_desk_basis_hedge", "shape": "basis_hedge",
             "stage": "BLOCKED-NO-HEDGE", "net_apy_pct": 3.4, "beats_floor": False,
             "hedge_available": False},
        ],
    })
    _write(data_dir, "rates_desk/rates_backtest.json", {
        "sleeves": {
            "basis_hedge": {
                "blocked_no_hedge": True,
                "backtest_proxy": {
                    "net_apy_pct": 4.9886, "mean_apy_pct": 4.9886,
                    "beats_floor": True, "deflated_sharpe": 1.0, "carry_days": 748,
                    "hedge_rate_source": "5-venue median perp funding",
                    "live_eligible": False,
                    "label": "BACKTEST-ONLY (funding proxy) · live-BLOCKED until Boros permissionless",
                },
            },
        },
    })


def test_promotion_carries_rates_desk_section_with_honest_stages(client):
    c, data_dir = client
    _write_rates_desk_promotion(data_dir)
    d = c.get("/api/strategy-lab/promotion").json()
    rd = d.get("rates_desk")
    assert isinstance(rd, dict), "rates_desk section must be present"
    # clearly separated — NOT merged into the live-pipeline sleeves list
    assert "rates_desk" in d
    # four sleeves with their honest stages
    assert rd["n_sleeves"] == 4
    by_shape = {s["shape"]: s for s in rd["sleeves"]}
    assert by_shape["fixed_carry"]["stage"] == "PAPER_CANDIDATE"
    assert by_shape["levered_carry"]["stage"] == "PAPER_CANDIDATE"
    assert by_shape["rate_matrix"]["stage"] == "PAPER_CANDIDATE"
    assert by_shape["basis_hedge"]["stage"] == "BLOCKED-NO-HEDGE"
    # honest net APYs (FixedCarry 6.09 / LeveredCarry 4.96 / RateMatrix 6.09)
    assert round(by_shape["fixed_carry"]["net_apy_pct"], 2) == 6.09
    assert round(by_shape["levered_carry"]["net_apy_pct"], 2) == 4.96
    assert round(by_shape["rate_matrix"]["net_apy_pct"], 2) == 6.09
    # BasisHedge backtest-proxy (~4.99%) surfaced research-only + live-blocked
    proxy = by_shape["basis_hedge"]["backtest_proxy"]
    assert round(proxy["net_apy_pct"], 2) == 4.99
    assert proxy["live_eligible"] is False
    assert proxy["research_only"] is True


def test_rates_desk_sleeves_flagged_advisory_and_live_blocked(client):
    """HARD SEPARATION: every rates-desk sleeve is advisory + never live-eligible, and the
    section is NOT appended to the live-pipeline sleeves list."""
    c, data_dir = client
    # also write a lab promotion file so raw["sleeves"] (the live pipeline list) is populated
    _write(data_dir, "strategy_lab_promotion.json", {
        "generated_at": "2026-06-26T00:00:00+00:00", "model": "strategy_lab_promotion",
        "rwa_floor_pct": 3.4, "n_sleeves": 1, "stage_counts": {"PAPER_CANDIDATE": 1},
        "sleeves": [{"id": "engine_b", "stage": "PAPER_CANDIDATE"}],
    })
    _write_rates_desk_promotion(data_dir)
    d = c.get("/api/strategy-lab/promotion").json()
    rd = d["rates_desk"]
    # section-level advisory flags
    assert rd["advisory"] is True
    assert rd["live_eligible"] is False
    # per-sleeve advisory + live-blocked, regardless of on-disk stage
    for s in rd["sleeves"]:
        assert s["is_advisory"] is True
        assert s["live_eligible"] is False
    # the rates-desk sleeve ids are ABSENT from the live-pipeline sleeves list
    live_ids = {s["id"] for s in d["sleeves"]}
    rates_ids = {s["id"] for s in rd["sleeves"]}
    assert rates_ids.isdisjoint(live_ids)
    assert live_ids == {"engine_b"}


def test_rates_desk_section_graceful_offline(client):
    """No rates-desk files → empty, advisory, never-live section (fail-closed, not an error)."""
    c, _ = client
    d = c.get("/api/strategy-lab/promotion").json()
    rd = d["rates_desk"]
    assert rd["n_sleeves"] == 0
    assert rd["sleeves"] == []
    assert rd["advisory"] is True
    assert rd["live_eligible"] is False


# ── /api/tier1/packages ────────────────────────────────────────────────────────
def test_tier1_packages_meta(client):
    c, data_dir = client
    _write(data_dir, "tier1_packages.json", {
        "generated_at": "2026-06-26T00:00:00+00:00", "model": "tier1_packages",
        "packages": {"Balanced": {"net_apy_pct": 5.0}},
    })
    r = c.get("/api/tier1/packages")
    assert r.status_code == 200
    d = r.json()
    assert "packages" in d and d["packages"]["Balanced"]["net_apy_pct"] == 5.0
    _assert_backtest_meta(d["meta"])


def test_tier1_packages_default_has_meta(client):
    c, _ = client
    d = c.get("/api/tier1/packages").json()
    _assert_backtest_meta(d["meta"])


# ── /api/tier1/nav ─────────────────────────────────────────────────────────────
def test_tier1_nav_track_basis_pointer(client):
    c, data_dir = client
    _write(data_dir, "tier1_nav_proof.json", {
        "generated_at": "2026-06-26T00:00:00+00:00",
        "computed_nav_usd": 100180.31, "reconciliation_ok": True,
    })
    r = c.get("/api/tier1/nav")
    assert r.status_code == 200
    d = r.json()
    # backward-compat: headline NAV preserved unchanged
    assert d["computed_nav_usd"] == 100180.31
    meta = d["meta"]
    assert meta["track_basis"] == "paper, advisory"
    assert meta["is_realized"] is False
    assert "/track-record" in meta["evidence_note"]


# ── /api/tournament ────────────────────────────────────────────────────────────
def test_tournament_meta_and_paper_apy_label(client):
    c, data_dir = client
    _write(data_dir, "mass_tournament_results.json",
           {"leaderboard": [{"strategy_id": "S1", "sharpe": 2.0}], "strategies_tested": 60})
    _write(data_dir, "strategy_tournament.json", {
        "shadow_active_strategies": [
            {"rank": 1, "strategy_id": "S1", "paper_apy": 4.2, "sharpe": 2.0},
        ],
        "ranked_strategies": [
            {"rank": 1, "strategy_id": "S1", "paper_apy": 4.2},
        ],
    })
    r = c.get("/api/tournament")
    assert r.status_code == 200
    d = r.json()
    # backward-compat
    assert d["live"] is True
    assert d["mass_results"]["strategies_tested"] == 60
    _assert_backtest_meta(d["meta"])
    "deterministic backtest" in d["meta"]["basis"]
    # paper_apy preserved AND labeled
    row = d["tournament"]["shadow_active_strategies"][0]
    assert row["paper_apy"] == 4.2
    assert row["apy_source"] == "backtest_derived"
    assert d["tournament"]["ranked_strategies"][0]["apy_source"] == "backtest_derived"


def test_tournament_status_meta(client):
    c, data_dir = client
    _write(data_dir, "mass_tournament_results.json", {
        "leaderboard": [{"strategy_id": "S1", "paper_apy": 4.2, "sharpe": 2.0}],
        "strategies_tested": 60, "strategies_skipped": 3,
    })
    _write(data_dir, "strategy_tournament.json",
           {"shadow_active_strategies": [{"strategy_id": "S1"}]})
    r = c.get("/api/tournament/status")
    assert r.status_code == 200
    d = r.json()
    # backward-compat
    assert d["total_backtested"] == 60
    assert d["paper_phase_count"] == 1
    _assert_backtest_meta(d["meta"])
    assert d["top3"][0]["apy_source"] == "backtest_derived"


# ── /api/rates-desk/* ──────────────────────────────────────────────────────────
def test_rates_desk_surface_meta(client):
    c, data_dir = client
    _write(data_dir, "rates_desk/rate_surface.json", {
        "generated_at": "2026-06-26T00:00:00+00:00", "as_of": "2026-06-25",
        "mode": "live", "hedge_available": {}, "quotes": [], "underlying_risk": {},
    })
    d = c.get("/api/rates-desk/surface").json()
    assert d["as_of"] == "2026-06-25"  # backward-compat
    _assert_backtest_meta(d["meta"])
    assert "Pendle PT" in d["meta"]["basis"]


def test_rates_desk_surface_empty_has_meta(client):
    c, _ = client
    d = c.get("/api/rates-desk/surface").json()
    _assert_backtest_meta(d["meta"])


def test_rates_desk_opportunities_empty_has_meta(client):
    c, _ = client
    d = c.get("/api/rates-desk/opportunities").json()
    # backward-compat shape preserved
    assert d["n_opportunities"] == 0 and d["opportunities"] == []
    _assert_backtest_meta(d["meta"])


def test_rates_desk_track_meta(client):
    c, data_dir = client
    paper = data_dir / "rates_desk" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps({
        "id": "rates_desk_fixed_carry",
        "series": [{"date": "2026-06-20", "equity_usd": 100000.0, "net_apy_pct": 4.0},
                   {"date": "2026-06-21", "equity_usd": 100050.0, "net_apy_pct": 4.0}],
    }), encoding="utf-8")
    (paper / "status.json").write_text(json.dumps({
        "sleeve": {"id": "rates_desk_fixed_carry", "name": "Fixed Carry",
                   "equity_usd": 100050.0, "net_apy_pct": 4.0},
    }), encoding="utf-8")
    d = c.get("/api/rates-desk/track").json()
    # backward-compat: existing fields intact
    assert d["is_advisory"] is True
    assert d["days"] == 2
    assert d["sleeve_id"] == "rates_desk_fixed_carry"
    _assert_backtest_meta(d["meta"])
    assert "Pendle PT" in d["meta"]["basis"]


# ── apy_today_pct annualized label ─────────────────────────────────────────────
def test_portfolio_apy_today_annualized_label(client, monkeypatch):
    c, data_dir = client
    # Force the paper_trading_status.json fallback (no live PaperTrader DB) so the
    # assembled apy fields + label are exercised deterministically.
    monkeypatch.setattr(server, "_get_live_portfolio", lambda: None)
    _write(data_dir, "paper_trading_status.json", {
        "current_equity": 100180.31, "total_return_pct": 0.18,
        "apy_today_pct": 3.6, "days_running": 16, "current_positions": {},
    })
    d = c.get("/api/portfolio").json()
    # backward-compat: existing apy_pct preserved
    assert d["apy_pct"] == 3.6
    assert d["apy_today_pct_annualized"] == 3.6
    assert "annualized" in d["apy_today_pct_note"]


def test_portfolio_live_path_apy_label(client):
    """When the live PaperTrader path is used, the annualized note is still attached."""
    c, _ = client
    d = c.get("/api/portfolio").json()
    # Either path must carry the honesty note.
    assert "annualized" in d.get("apy_today_pct_note", "")


def test_health_public_apy_annualized_label(client):
    c, data_dir = client
    _write(data_dir, "paper_trading_status.json", {
        "days_running": 16, "apy_today_pct": 3.6, "current_equity": 100180.31,
    })
    # Canonical track-days = EVIDENCED count from golive_checker, NOT the padded
    # days_running. With golive_status present, track_days mirrors real_track_days.
    _write(data_dir, "golive_status.json", {"real_track_days": 5, "passed": 27, "total": 29})
    d = c.get("/api/health-public").json()
    # track_days is now the honest evidenced count, not the padded days_running.
    assert d["track_days"] == 5
    assert d["real_track_days"] == 5
    # Raw padded value retained for transparency only.
    assert d["days_running_raw"] == 16
    assert d["ytd_apy_pct"] == 3.6
    assert "annualized" in d["ytd_apy_pct_note"]
    assert d["apy_today_pct_annualized"] == 3.6

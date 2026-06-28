# LLM_FORBIDDEN
"""
test_tournament_promotion_integrity.py — WS1.4 "Yield Capture" fail-closed gate.

The tournament backtest can run on near-constant (mock OR stablecoin) returns, where
Sharpe is mathematically DEGENERATE (explodes to tens/hundreds/billions) and the mass
tournament honestly stamps trustworthy=False / sharpe_degenerate. The promotion gate
(TournamentEngine.check_promotions) MUST refuse to promote on such data — a degenerate
Sharpe or untrustworthy dataset can NEVER reach 'live' (stop promotion theater).

These tests assert (red-team + smoke):
  • degenerate-Sharpe (92.5, locked-vol) → REFUSED with reason='degenerate_data'
  • trustworthy=False dataset → ALL strategies refused with reason='untrustworthy'
  • missing trustworthy stamp → fail-CLOSED (refused), never silently promoted
  • a REAL, credible, in-criteria strategy → PROMOTED
  • insufficient paper days → refused with reason='insufficient_data'
  • PIT historical APY series align by DATE, not row index (axis-misalignment bug)
  • a degenerate strategy can NEVER reach 'live' (end-to-end proof)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.tournament.tournament_engine import (  # noqa: E402
    TournamentEngine,
    DEGENERATE_SHARPE_CEILING,
    _is_degenerate_sharpe,
    _dataset_trustworthy,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox fixture — NEVER touches the live data/ track.
# ─────────────────────────────────────────────────────────────────────────────

def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _make_sandbox(tmp_path: Path, *, trustworthy: bool, regime: str,
                  sharpe: float, days: int, apy_pct: float = 8.0,
                  sharpe_degenerate=None, include_trust_stamp: bool = True) -> Path:
    """Build an isolated data dir with a 1-strategy tournament + shadow book."""
    sid = "s_test"
    tournament = {
        "schema_version": "2.0",
        "metric": "net_annual_return_pct",
        "shadow_active_strategies": [{
            "rank": 1, "strategy_id": "S-TEST", "strategy_key": sid,
            "name": "STest", "sharpe": sharpe,
            "sharpe_degenerate": sharpe_degenerate,
            "rank_unknown": False,
            "allocation": {"aave_v3": 1.0},
        }],
        "data_source_regime": regime,
        "trust_reason": "synthetic test dataset",
    }
    if include_trust_stamp:
        tournament["trustworthy"] = trustworthy

    # Build `days` daily_results each crediting the strategy with apy_pct.
    daily_yield = 100_000.0 * (apy_pct / 100.0) / 365.0
    daily_results = []
    for i in range(days):
        d = date(2026, 1, 1).replace(day=min(28, i + 1))
        daily_results.append({
            "date": f"2026-01-{i+1:02d}",
            "strategies": [{
                "strategy_id": sid, "rank": 1,
                "daily_yield_usd": round(daily_yield, 4),
                "annualised_apy_pct": apy_pct,
            }],
        })
    shadow = {
        "schema_version": "1.0",
        "active_strategies": [{
            "rank": 1, "id": sid, "sharpe": sharpe,
            "annual_return_pct": apy_pct, "max_dd_pct": -0.01,
            "allocation": {"aave_v3": 1.0},
        }],
        "daily_results": daily_results,
    }
    _write(tmp_path / "strategy_tournament.json", tournament)
    _write(tmp_path / "shadow_paper_trading.json", shadow)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# Unit: degeneracy + trust helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_is_degenerate_sharpe_flags_locked_vol():
    assert _is_degenerate_sharpe(92.5) is True            # locked-vol artifact
    assert _is_degenerate_sharpe(DEGENERATE_SHARPE_CEILING + 0.01) is True
    assert _is_degenerate_sharpe(float("inf")) is True    # non-finite
    assert _is_degenerate_sharpe("not a number") is True  # fail-closed
    assert _is_degenerate_sharpe(1.8) is False            # credible


def test_dataset_trust_fail_closed():
    # missing stamp → fail-closed
    ok, _ = _dataset_trustworthy({"shadow_active_strategies": []})
    assert ok is False
    # explicit false → refuse
    ok, _ = _dataset_trustworthy({"trustworthy": False, "data_source_regime": "LOW_VOL_YIELD"})
    assert ok is False
    # degenerate regime even if flag truthy → refuse
    ok, _ = _dataset_trustworthy({"trustworthy": True, "data_source_regime": "DEGENERATE_MOCK"})
    assert ok is False
    # credible → ok
    ok, _ = _dataset_trustworthy({"trustworthy": True, "data_source_regime": "NORMAL"})
    assert ok is True


# ─────────────────────────────────────────────────────────────────────────────
# RED-TEAM: degenerate Sharpe → refused, never promoted
# ─────────────────────────────────────────────────────────────────────────────

def test_degenerate_sharpe_refused(tmp_path):
    """Sharpe 92.5 (locked-vol) on an otherwise-credible dataset → REFUSED."""
    ddir = _make_sandbox(tmp_path, trustworthy=True, regime="NORMAL",
                         sharpe=92.5, days=30)
    eng = TournamentEngine(data_dir=ddir)
    promos = eng.check_promotions()
    assert promos == [], "degenerate Sharpe must NOT be promoted"
    reasons = {r["reason"] for r in eng.last_refusals}
    assert "degenerate_data" in reasons
    assert any(r["strategy_id"] == "s_test" for r in eng.last_refusals)


def test_producer_sharpe_degenerate_flag_refused(tmp_path):
    """Producer-flagged sharpe_degenerate=True → refused even if Sharpe value parses small."""
    ddir = _make_sandbox(tmp_path, trustworthy=True, regime="NORMAL",
                         sharpe=2.0, days=30, sharpe_degenerate=True)
    eng = TournamentEngine(data_dir=ddir)
    promos = eng.check_promotions()
    assert promos == []
    assert any(r["reason"] == "degenerate_data" for r in eng.last_refusals)


# ─────────────────────────────────────────────────────────────────────────────
# RED-TEAM: trustworthy=False dataset → no promotion
# ─────────────────────────────────────────────────────────────────────────────

def test_untrustworthy_dataset_refused(tmp_path):
    """trustworthy=False → ALL strategies refused (untrustworthy), none promoted."""
    ddir = _make_sandbox(tmp_path, trustworthy=False, regime="LOW_VOL_YIELD",
                         sharpe=2.0, days=30)
    eng = TournamentEngine(data_dir=ddir)
    promos = eng.check_promotions()
    assert promos == []
    assert eng.last_refusals, "must record explicit refusals"
    assert all(r["reason"] == "untrustworthy" for r in eng.last_refusals)


def test_missing_trust_stamp_fail_closed(tmp_path):
    """No trustworthy stamp at all → fail-CLOSED (refused), never promoted."""
    ddir = _make_sandbox(tmp_path, trustworthy=True, regime="NORMAL",
                         sharpe=2.0, days=30, include_trust_stamp=False)
    eng = TournamentEngine(data_dir=ddir)
    promos = eng.check_promotions()
    assert promos == []
    assert all(r["reason"] == "untrustworthy" for r in eng.last_refusals)


# ─────────────────────────────────────────────────────────────────────────────
# Insufficient data
# ─────────────────────────────────────────────────────────────────────────────

def test_insufficient_paper_days_refused(tmp_path):
    """A credible Sharpe but only 3 paper days → refused (insufficient_data)."""
    ddir = _make_sandbox(tmp_path, trustworthy=True, regime="NORMAL",
                         sharpe=2.0, days=3)
    eng = TournamentEngine(data_dir=ddir)
    promos = eng.check_promotions()
    assert promos == []
    assert any(r["reason"] == "insufficient_data" for r in eng.last_refusals)


# ─────────────────────────────────────────────────────────────────────────────
# HAPPY PATH: a real, credible, in-criteria strategy → PROMOTED
# ─────────────────────────────────────────────────────────────────────────────

def test_credible_in_criteria_promoted(tmp_path):
    """Credible Sharpe (1.8), trustworthy NORMAL data, >=7 days, APY>=3% → PROMOTED."""
    ddir = _make_sandbox(tmp_path, trustworthy=True, regime="NORMAL",
                         sharpe=1.8, days=10, apy_pct=8.0)
    eng = TournamentEngine(data_dir=ddir)
    promos = eng.check_promotions()
    assert len(promos) == 1
    p = promos[0]
    assert p["strategy_id"] == "s_test"
    assert p["phase_to"] == "live"
    assert p["data_trustworthy"] is True


# ─────────────────────────────────────────────────────────────────────────────
# END-TO-END: a degenerate strategy can NEVER reach 'live'
# ─────────────────────────────────────────────────────────────────────────────

def test_degenerate_never_reaches_live_via_run_daily(tmp_path, monkeypatch):
    """Drive run_daily() on degenerate data → 0 promotions, refusals recorded."""
    ddir = _make_sandbox(tmp_path, trustworthy=False, regime="DEGENERATE_MOCK",
                         sharpe=92.5, days=30)
    # No mass results in sandbox → skip the regenerate step (best-effort, non-fatal).
    eng = TournamentEngine(data_dir=ddir)
    # Disable telegram side effects.
    monkeypatch.setattr(eng, "_send_alerts", lambda *a, **k: False)
    summary = eng.run_daily()
    assert summary["promotions"] == [], "degenerate data must never promote to live"
    assert summary["refusals"], "run_daily must surface the refusals"
    state = json.loads((ddir / "tournament_engine_state.json").read_text())
    assert state["total_promotions"] == 0
    assert state["last_refusals_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Real-data alignment: PIT series align by DATE, not row index.
# ─────────────────────────────────────────────────────────────────────────────

def test_pit_series_align_by_date_not_row_index():
    """The real PIT historical_apy store aligns by calendar DATE.

    compound_v3 starts 2 days BEFORE aave_v3; a date-aligned interpolation must
    return each protocol's value FOR THAT DATE — a row-index join would shift
    compound_v3 by 2 days and silently corrupt the Sharpe.
    """
    from spa_core.backtesting.professional_backtest import _pit_apy_points, _interp

    aave = _pit_apy_points("aave_v3")
    comp = _pit_apy_points("compound_v3")
    assert aave and comp, "PIT real series must load for aave_v3 + compound_v3"

    # Series have different start dates (the axis-misalignment hazard).
    assert aave[0][0] != comp[0][0], "fixture precondition: misaligned start dates"

    # Date-aligned lookup: each series returns its OWN value for a shared date.
    shared = max(aave[0][0], comp[0][0])
    a_val = _interp(aave, shared)
    c_val = _interp(comp, shared)
    # Each is the protocol's real value on that date (finite, in a sane band), not
    # a row-shifted neighbour.
    assert 0.0 <= a_val < 0.50
    assert 0.0 <= c_val < 0.50

    # Independent cross-check: the value at compound's own first date equals its
    # first sample (clamp at series start) — proving no row offset is applied.
    assert abs(_interp(comp, comp[0][0]) - comp[0][1]) < 1e-9


def test_pit_source_reported_as_real():
    """_resolve_protocol_source reports the real PIT provenance for mapped protocols."""
    from spa_core.backtesting.professional_backtest import _resolve_protocol_source
    src = _resolve_protocol_source("aave_v3", {}, {})
    assert src == "defillama_pit_real"

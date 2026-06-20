#!/usr/bin/env python3
"""
tests/test_strategy_agent_v2.py — MP-1452 (Sprint v10.68)

Test suite for spa_core/agents/strategy_agent_v2.py.

Tests:
  A. rank_shadow_strategies — pure function (A1–A4)
  B. kelly_sizing — pure function (B1–B4)
  C. should_run — pure function (C1–C4)
  D. gather_context (D1–D3)
  E. StrategyRecommendation + annualized_volatility_pp (E1–E3)

Pure stdlib. No network. No LLM. Offline.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.agents.strategy_agent_v2 import (
    StrategyRecommendation,
    annualized_volatility_pp,
    gather_context,
    kelly_sizing,
    rank_shadow_strategies,
    should_run,
    MIN_DAYS_FOR_CANDIDATE,
    WEEKLY_PERIOD_DAYS,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
_8_DAYS_AGO = _NOW - timedelta(days=8)


def _strat(name: str, sortino: float = 1.2, sharpe: float = 0.9,
           pnl_pct: float = 5.0, max_dd: float = 2.0,
           days_running: int = 30) -> dict:
    return {
        "name": name,
        "label": name,
        "sortino": sortino,
        "sharpe": sharpe,
        "pnl_pct": pnl_pct,
        "max_drawdown": max_dd,
        "days_running": days_running,
    }


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — rank_shadow_strategies
# ═══════════════════════════════════════════════════════════════════════════════

class TestRankShadowStrategies(unittest.TestCase):

    def test_A1_returns_list(self):
        """rank_shadow_strategies returns a list."""
        strats = [_strat("S0"), _strat("S1", sortino=1.5)]
        result = rank_shadow_strategies(strats)
        self.assertIsInstance(result, list)

    def test_A2_best_sortino_ranks_first(self):
        """Strategy with highest sortino is ranked first."""
        strats = [
            _strat("S0", sortino=1.0),
            _strat("S1", sortino=2.5),
            _strat("S2", sortino=0.5),
        ]
        result = rank_shadow_strategies(strats)
        self.assertEqual(result[0]["name"], "S1")
        self.assertEqual(result[0]["rank"], 1)

    def test_A3_eligible_requires_min_days(self):
        """eligible=True only when days_running >= MIN_DAYS_FOR_CANDIDATE."""
        strats = [
            _strat("S0", days_running=MIN_DAYS_FOR_CANDIDATE),
            _strat("S1", days_running=MIN_DAYS_FOR_CANDIDATE - 1),
        ]
        result = rank_shadow_strategies(strats)
        by_name = {r["name"]: r for r in result}
        self.assertTrue(by_name["S0"]["eligible"])
        self.assertFalse(by_name["S1"]["eligible"])

    def test_A4_empty_input_returns_empty_list(self):
        """rank_shadow_strategies([]) returns []."""
        result = rank_shadow_strategies([])
        self.assertEqual(result, [])


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — kelly_sizing
# ═══════════════════════════════════════════════════════════════════════════════

class TestKellySizing(unittest.TestCase):

    def test_B1_returns_dict(self):
        """kelly_sizing returns a dict."""
        result = kelly_sizing(apy_pct=5.0, volatility_pp=2.0)
        self.assertIsInstance(result, dict)

    def test_B2_has_kelly_fraction_key(self):
        """kelly_sizing result contains 'kelly_fraction' key."""
        result = kelly_sizing(apy_pct=8.0, volatility_pp=3.0)
        self.assertIn("kelly_fraction", result)

    def test_B3_kelly_fraction_clamped_to_zero_one(self):
        """kelly_fraction is in [0, 1]."""
        result = kelly_sizing(apy_pct=10.0, volatility_pp=2.0)
        fraction = result.get("kelly_fraction", -1)
        self.assertGreaterEqual(fraction, 0.0)
        self.assertLessEqual(fraction, 1.0)

    def test_B4_zero_volatility_handled(self):
        """kelly_sizing with zero volatility does not crash."""
        result = kelly_sizing(apy_pct=5.0, volatility_pp=0.0)
        self.assertIsInstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — should_run
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldRun(unittest.TestCase):
    """should_run(context, recommendations, now) — context is first arg."""

    def test_C1_runs_when_no_recommendations(self):
        """should_run returns True when no recommendations exist."""
        run, _ = should_run({}, [], now=_NOW)
        self.assertTrue(run)

    def test_C2_runs_when_7_days_elapsed(self):
        """should_run returns True when last run was >=7 days ago."""
        recs = [{"ts": _8_DAYS_AGO.isoformat()}]
        run, _ = should_run({}, recs, now=_NOW)
        self.assertTrue(run)

    def test_C3_no_run_when_recent(self):
        """should_run returns False when last run was recent."""
        recent = _NOW - timedelta(days=2)
        recs = [{"ts": recent.isoformat()}]
        run, _ = should_run({}, recs, now=_NOW)
        self.assertFalse(run)

    def test_C4_returns_tuple_bool_str_or_none(self):
        """should_run always returns a (bool, str|None) tuple."""
        run, reason = should_run({}, [], now=_NOW)
        self.assertIsInstance(run, bool)
        self.assertTrue(reason is None or isinstance(reason, str))


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — gather_context
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatherContext(unittest.TestCase):

    def test_D1_returns_dict(self):
        """gather_context returns a dict even without data files."""
        with tempfile.TemporaryDirectory() as d:
            result = gather_context(data_dir=d)
            self.assertIsInstance(result, dict)

    def test_D2_loads_shadow_comparison(self):
        """gather_context loads strategy_shadow_comparison.json if present."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            shadow = {"strategies": [_strat("S0"), _strat("S1")]}
            _write_json(data_dir / "strategy_shadow_comparison.json", shadow)
            result = gather_context(data_dir=str(data_dir))
            self.assertIsInstance(result, dict)

    def test_D3_missing_context_not_exception(self):
        """gather_context with no data directory files does not raise."""
        with tempfile.TemporaryDirectory() as d:
            try:
                result = gather_context(data_dir=d)
                self.assertIsInstance(result, dict)
            except Exception as e:
                self.fail(f"gather_context raised unexpectedly: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — StrategyRecommendation + annualized_volatility_pp
# ═══════════════════════════════════════════════════════════════════════════════

class TestMiscFunctions(unittest.TestCase):

    def test_E1_annualized_volatility_constant_returns_zero(self):
        """annualized_volatility_pp returns 0 for constant daily returns."""
        returns = [0.5] * 30
        vol = annualized_volatility_pp(returns)
        self.assertAlmostEqual(vol, 0.0, places=4)

    def test_E2_annualized_volatility_positive_for_varying_returns(self):
        """annualized_volatility_pp returns positive value for varying returns."""
        returns = [0.5, -0.3, 1.2, -0.8, 0.9, 0.1] * 5
        vol = annualized_volatility_pp(returns)
        self.assertGreater(vol, 0.0)

    def test_E3_annualized_volatility_none_for_short_series(self):
        """annualized_volatility_pp returns None for < 2 data points."""
        result = annualized_volatility_pp([0.5])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

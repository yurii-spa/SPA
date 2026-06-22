"""Tests for spa_core/agents/strategy_agent_v2.py (MP-1472 — Atomic Batch 9).

unittest, no network, no external deps. Covers pure/deterministic functions
and the append_recommendation atomic-write path.

Run::
    python3 -m unittest spa_core.tests.test_strategy_agent_v2 -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import spa_core.agents.strategy_agent_v2 as sa

NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────── _num ────────────────────────────────────────────

class TestNum(unittest.TestCase):
    def test_int_passes(self):
        self.assertEqual(sa._num(5), 5.0)

    def test_float_passes(self):
        self.assertAlmostEqual(sa._num(3.14), 3.14)

    def test_bool_returns_none(self):
        self.assertIsNone(sa._num(True))
        self.assertIsNone(sa._num(False))

    def test_none_returns_none(self):
        self.assertIsNone(sa._num(None))

    def test_nan_returns_none(self):
        self.assertIsNone(sa._num(float("nan")))

    def test_inf_returns_none(self):
        self.assertIsNone(sa._num(float("inf")))

    def test_string_number_passes(self):
        # numeric string should parse to float
        result = sa._num("2.5")
        self.assertAlmostEqual(result, 2.5)

    def test_garbage_string_returns_none(self):
        self.assertIsNone(sa._num("abc"))


# ───────────────── annualized_volatility_pp ──────────────────────────────────

class TestAnnualizedVol(unittest.TestCase):
    def test_single_point_returns_none(self):
        self.assertIsNone(sa.annualized_volatility_pp([1.0]))

    def test_empty_returns_none(self):
        self.assertIsNone(sa.annualized_volatility_pp([]))

    def test_known_value(self):
        # stdev([1.0, -1.0]) = 1.4142...; * sqrt(365) ≈ 27.0
        result = sa.annualized_volatility_pp([1.0, -1.0])
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_non_numeric_skipped(self):
        # None values are stripped; if fewer than 2 remain → None
        self.assertIsNone(sa.annualized_volatility_pp([None, None]))

    def test_all_same_returns_zero(self):
        result = sa.annualized_volatility_pp([1.0, 1.0, 1.0, 1.0])
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.0)


# ──────────────────── rank_shadow_strategies ─────────────────────────────────

class TestRankShadowStrategies(unittest.TestCase):
    def _strat(self, name, sortino=1.0, sharpe=1.0, pnl=1.0, dd=0.5, days=30):
        return {
            "name": name,
            "label": name,
            "sortino": sortino,
            "sharpe": sharpe,
            "pnl_pct": pnl,
            "max_drawdown": dd,
            "days_running": days,
        }

    def test_empty_list_returns_empty(self):
        self.assertEqual(sa.rank_shadow_strategies([]), [])

    def test_best_sortino_ranks_first(self):
        strats = [
            self._strat("S1", sortino=0.5),
            self._strat("S2", sortino=2.0),
        ]
        ranked = sa.rank_shadow_strategies(strats)
        self.assertEqual(ranked[0]["name"], "S2")
        self.assertEqual(ranked[0]["rank"], 1)

    def test_eligible_flag_set_correctly(self):
        strats = [
            self._strat("S0", days=5),   # below MIN_DAYS default (7)
            self._strat("S1", days=30),  # above
        ]
        ranked = sa.rank_shadow_strategies(strats, min_days=7)
        by_name = {r["name"]: r for r in ranked}
        self.assertFalse(by_name["S0"]["eligible"])
        self.assertTrue(by_name["S1"]["eligible"])

    def test_non_dict_entries_skipped(self):
        ranked = sa.rank_shadow_strategies(["garbage", None, 42])
        self.assertEqual(ranked, [])

    def test_none_sortino_ranks_last(self):
        strats = [
            self._strat("S1", sortino=None),
            self._strat("S2", sortino=0.1),
        ]
        ranked = sa.rank_shadow_strategies(strats)
        self.assertEqual(ranked[-1]["name"], "S1")


# ─────────────────────────── kelly_sizing ────────────────────────────────────

class TestKellySizing(unittest.TestCase):
    def test_none_apy_gives_zero_fraction(self):
        result = sa.kelly_sizing(None, 5.0)
        self.assertEqual(result["kelly_fraction"], 0.0)
        self.assertEqual(result["source"], "insufficient_data")

    def test_none_vol_gives_zero_fraction(self):
        result = sa.kelly_sizing(10.0, None)
        self.assertEqual(result["kelly_fraction"], 0.0)

    def test_zero_vol_gives_zero_fraction(self):
        result = sa.kelly_sizing(10.0, 0.0)
        self.assertEqual(result["kelly_fraction"], 0.0)

    def test_half_kelly_is_half_of_kelly(self):
        result = sa.kelly_sizing(20.0, 5.0, kelly_fn=lambda *a, **kw: 0.4)
        self.assertAlmostEqual(result["half_kelly"], 0.2, places=5)

    def test_fraction_capped_at_one(self):
        # Huge APY relative to vol → fraction >1 → clamped to 1.0
        result = sa.kelly_sizing(1000.0, 0.001)
        self.assertLessEqual(result["kelly_fraction"], 1.0)

    def test_explicit_kelly_fn_used(self):
        """Custom kelly_fn should override stdlib formula."""
        custom_fn = mock.Mock(return_value=0.3)
        result = sa.kelly_sizing(10.0, 5.0, kelly_fn=custom_fn)
        custom_fn.assert_called_once()
        self.assertAlmostEqual(result["kelly_fraction"], 0.3, places=5)


# ─────────────────────────── should_run ──────────────────────────────────────

class TestShouldRun(unittest.TestCase):
    def test_no_recommendations_triggers_weekly(self):
        run, trigger = sa.should_run({}, [], NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, sa.TRIGGER_WEEKLY)

    def test_recent_recommendation_no_trigger(self):
        recent_ts = (NOW - timedelta(days=3)).isoformat()
        recs = [{"ts": recent_ts}]
        run, trigger = sa.should_run({}, recs, NOW)
        self.assertFalse(run)
        self.assertIsNone(trigger)

    def test_stale_recommendation_triggers_weekly(self):
        old_ts = (NOW - timedelta(days=8)).isoformat()
        recs = [{"ts": old_ts}]
        run, trigger = sa.should_run({}, recs, NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, sa.TRIGGER_WEEKLY)

    def test_corrupt_ts_triggers_weekly(self):
        recs = [{"ts": "not-a-date"}]
        run, trigger = sa.should_run({}, recs, NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, sa.TRIGGER_WEEKLY)


# ─────────────── append_recommendation — atomic write (MP-1472) ──────────────

class TestAppendRecommendationAtomicWrite(unittest.TestCase):
    def _make_rec(self, strategy="S1") -> dict:
        return {
            "ts": NOW.isoformat(),
            "trigger": sa.TRIGGER_WEEKLY,
            "recommendation": "recommend_strategy",
            "strategy": strategy,
            "advisory_only": True,
            "reasoning": "test",
            "kelly": {},
            "ranking": [],
        }

    def test_creates_file_on_first_call(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "strategy_recommendations.json"
            rec = self._make_rec()
            sa.append_recommendation(rec, path=str(path))
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertIn("recommendations", data)
            self.assertEqual(len(data["recommendations"]), 1)

    def test_appends_on_second_call(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "strategy_recommendations.json"
            sa.append_recommendation(self._make_rec("S1"), path=str(path))
            sa.append_recommendation(self._make_rec("S2"), path=str(path))
            data = json.loads(path.read_text())
            self.assertEqual(len(data["recommendations"]), 2)

    def test_no_leftover_tmp_files(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "strategy_recommendations.json"
            sa.append_recommendation(self._make_rec(), path=str(path))
            leftovers = [f for f in os.listdir(td) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_advisory_only_flag_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "strategy_recommendations.json"
            sa.append_recommendation(self._make_rec(), path=str(path))
            data = json.loads(path.read_text())
            self.assertTrue(data.get("advisory_only"))


if __name__ == "__main__":
    unittest.main()

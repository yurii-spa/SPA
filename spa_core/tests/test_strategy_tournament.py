"""Unit tests for spa_core.analytics.strategy_tournament (MP-628).

Pure stdlib unittest.  File-saving tests use tempfile.mkdtemp() so the
real data/strategy_tournament.json is never clobbered.

Run:
    python3 -m pytest spa_core/tests/test_strategy_tournament.py -v --tb=short
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.strategy_tournament import (
    ADVISORY,
    MEDALS,
    RING_BUFFER_MAX,
    SCHEMA_VERSION,
    VALID_METRICS,
    StrategyScore,
    StrategyTournament,
    _DEFAULT_NAMES,
    _max_drawdown_from_equity,
    _mean,
    _pnl_pct_to_apy,
    _safe_float,
    _safe_int,
    _stdev,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tournament(tmp_dir: str) -> StrategyTournament:
    return StrategyTournament(data_dir=tmp_dir)


def _write_json(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_shadow(strategies: list) -> dict:
    return {
        "updated_at": "2026-06-13T06:00:00+00:00",
        "real_equity_usd": 100_050.0,
        "strategies": strategies,
    }


def _simple_shadow_strategies(n: int = 6) -> list:
    """Return *n* simple strategy dicts with varied pnl_pct."""
    return [
        {
            "name": f"S{i}",
            "label": f"S{i}",
            "equity": 100_000.0 + (i + 1) * 10,
            "pnl_usd": (i + 1) * 10,
            "pnl_pct": (i + 1) * 0.01,
            "days_running": 3,
            "sharpe": None,
            "max_drawdown": 0.0,
            "rank": i + 1,
        }
        for i in range(n)
    ]


# ===========================================================================
# 1. StrategyScore dataclass
# ===========================================================================

class TestStrategyScoreDataclass(unittest.TestCase):

    def test_default_rank_is_zero(self):
        s = StrategyScore("S0", "Name", 5.0, 1.0, 0.01, 3)
        self.assertEqual(s.rank, 0)

    def test_default_medal_is_empty(self):
        s = StrategyScore("S0", "Name", 5.0, 1.0, 0.01, 3)
        self.assertEqual(s.medal, "")

    def test_to_dict_contains_all_fields(self):
        s = StrategyScore("S1", "Name", 6.0, 1.2, 0.02, 5, rank=2, medal="🥈")
        d = s.to_dict()
        for key in ("strategy_id", "name", "paper_apy", "sharpe",
                    "max_drawdown", "days_active", "rank", "medal"):
            self.assertIn(key, d)

    def test_to_dict_values(self):
        s = StrategyScore("S2", "X", 7.0, 1.5, 0.03, 10, rank=1, medal="🥇")
        d = s.to_dict()
        self.assertEqual(d["strategy_id"], "S2")
        self.assertEqual(d["paper_apy"], 7.0)
        self.assertEqual(d["medal"], "🥇")

    def test_fields_are_mutable(self):
        s = StrategyScore("S0", "Name", 5.0, 1.0, 0.01, 3)
        s.rank = 1
        s.medal = "🥇"
        self.assertEqual(s.rank, 1)
        self.assertEqual(s.medal, "🥇")


# ===========================================================================
# 2. Helper: _safe_float / _safe_int
# ===========================================================================

class TestSafeFloat(unittest.TestCase):

    def test_normal_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_integer_input(self):
        self.assertAlmostEqual(_safe_float(5), 5.0)

    def test_string_number(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_none_returns_default(self):
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_invalid_string(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_nan_returns_default(self):
        self.assertEqual(_safe_float(float("nan")), 0.0)

    def test_inf_returns_default(self):
        self.assertEqual(_safe_float(float("inf")), 0.0)


class TestSafeInt(unittest.TestCase):

    def test_integer_passthrough(self):
        self.assertEqual(_safe_int(7), 7)

    def test_float_truncated(self):
        self.assertEqual(_safe_int(4.9), 4)

    def test_string_number(self):
        self.assertEqual(_safe_int("10"), 10)

    def test_none_returns_default(self):
        self.assertEqual(_safe_int(None, -1), -1)

    def test_invalid_string(self):
        self.assertEqual(_safe_int("xyz"), 0)


# ===========================================================================
# 3. Helper: _mean / _stdev
# ===========================================================================

class TestMeanStdev(unittest.TestCase):

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([5.0]), 5.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_stdev_empty(self):
        self.assertEqual(_stdev([]), 0.0)

    def test_stdev_single(self):
        self.assertEqual(_stdev([3.0]), 0.0)

    def test_stdev_identical_values(self):
        self.assertEqual(_stdev([4.0, 4.0, 4.0]), 0.0)

    def test_stdev_known_value(self):
        # stdev([2, 4, 4, 4, 5, 5, 7, 9], ddof=1) ≈ 2.138
        result = _stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        self.assertAlmostEqual(result, 2.1380899, places=4)


# ===========================================================================
# 4. Helper: _pnl_pct_to_apy
# ===========================================================================

class TestPnlPctToApy(unittest.TestCase):

    def test_zero_days_returns_zero(self):
        self.assertEqual(_pnl_pct_to_apy(5.0, 0), 0.0)

    def test_negative_days_returns_zero(self):
        self.assertEqual(_pnl_pct_to_apy(5.0, -1), 0.0)

    def test_full_year(self):
        # 10% over 365 days → 10% APY
        self.assertAlmostEqual(_pnl_pct_to_apy(10.0, 365), 10.0, places=4)

    def test_partial_year(self):
        # 1% over 30 days → 12.1667% APY
        apy = _pnl_pct_to_apy(1.0, 30)
        self.assertAlmostEqual(apy, 365 / 30, places=4)


# ===========================================================================
# 5. Helper: _max_drawdown_from_equity
# ===========================================================================

class TestMaxDrawdownFromEquity(unittest.TestCase):

    def test_empty_series(self):
        self.assertEqual(_max_drawdown_from_equity([]), 0.0)

    def test_single_value(self):
        self.assertEqual(_max_drawdown_from_equity([100.0]), 0.0)

    def test_monotonically_rising(self):
        self.assertEqual(_max_drawdown_from_equity([100.0, 110.0, 120.0]), 0.0)

    def test_simple_drawdown(self):
        # Peak 120, trough 90 → dd = 30/120 = 0.25
        dd = _max_drawdown_from_equity([100.0, 120.0, 90.0])
        self.assertAlmostEqual(dd, 0.25, places=6)

    def test_multiple_drawdowns_takes_max(self):
        # After 100→80 (dd=0.2) and then 110→70 (dd=0.363...)
        dd = _max_drawdown_from_equity([100.0, 80.0, 110.0, 70.0])
        self.assertAlmostEqual(dd, 0.3636, places=3)


# ===========================================================================
# 6. compute_sharpe
# ===========================================================================

class TestComputeSharpe(unittest.TestCase):

    def _t(self) -> StrategyTournament:
        return StrategyTournament(data_dir="data/")

    def test_empty_returns_zero(self):
        t = self._t()
        self.assertEqual(t.compute_sharpe([]), 0.0)

    def test_single_return_zero(self):
        t = self._t()
        self.assertEqual(t.compute_sharpe([0.001]), 0.0)

    def test_zero_stdev_returns_zero(self):
        t = self._t()
        self.assertEqual(t.compute_sharpe([0.001, 0.001, 0.001]), 0.0)

    def test_positive_returns_positive_sharpe(self):
        t = self._t()
        returns = [0.001] * 20 + [0.002] * 20
        sharpe = t.compute_sharpe(returns, rf_rate=0.0)
        self.assertGreater(sharpe, 0.0)

    def test_rf_rate_reduces_sharpe(self):
        t = self._t()
        returns = [0.0002] * 100
        # With rf=0.0 returns are all positive, sharpe is 0 (stdev=0)
        # Let's use varied returns
        returns2 = [0.001 * (i % 3 + 1) for i in range(30)]
        s0 = t.compute_sharpe(returns2, rf_rate=0.0)
        s1 = t.compute_sharpe(returns2, rf_rate=0.1)
        self.assertGreater(s0, s1)

    def test_sharpe_annualised(self):
        # Build deterministic daily returns with known Sharpe
        import math as _math
        # daily mean excess = 0.001, daily stdev = 0.001 (ddof=1)
        # annualised sharpe ≈ 1.0 * sqrt(365)
        t = self._t()
        # alternating to get stdev>0
        returns = [0.0001 + (0.002 if i % 2 else 0.0) for i in range(100)]
        sharpe = t.compute_sharpe(returns, rf_rate=0.0)
        self.assertIsInstance(sharpe, float)
        self.assertTrue(_math.isfinite(sharpe))


# ===========================================================================
# 7. _load_scores: file loading with temp files
# ===========================================================================

class TestLoadScores(unittest.TestCase):

    def test_load_from_shadow_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            _write_json(path, _make_shadow(_simple_shadow_strategies(4)))
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertEqual(len(scores), 4)
            ids = {s.strategy_id for s in scores}
            self.assertIn("S0", ids)

    def test_load_shadow_names_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            _write_json(path, _make_shadow(_simple_shadow_strategies(1)))
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertEqual(scores[0].name, _DEFAULT_NAMES["S0"])

    def test_load_shadow_apy_computed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            # pnl_pct=1.0 over 100 days → apy = 365%
            _write_json(path, _make_shadow([{
                "name": "S0", "pnl_pct": 1.0, "days_running": 100,
                "sharpe": None, "max_drawdown": 0.0
            }]))
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertAlmostEqual(scores[0].paper_apy, 3.65, places=2)

    def test_fallback_to_pnl_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pnl_history.json")
            _write_json(path, [
                {"total_capital_usd": 100_000.0},
                {"total_capital_usd": 100_500.0},
            ])
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertGreater(len(scores), 0)

    def test_fallback_to_defaults_when_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertEqual(len(scores), 20)  # S0–S19

    def test_corrupted_shadow_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            with open(path, "w") as f:
                f.write("NOT JSON {{{")
            t = _make_tournament(tmp)
            scores = t._load_scores()
            # Falls back to pnl_history then defaults
            self.assertGreater(len(scores), 0)

    def test_empty_strategies_list_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            _write_json(path, _make_shadow([]))
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertEqual(len(scores), 20)  # defaults

    def test_pnl_history_single_entry_falls_back(self):
        """Single entry in pnl_history → needs ≥2 → falls back to defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pnl_history.json")
            _write_json(path, [{"total_capital_usd": 100_000.0}])
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertEqual(len(scores), 20)


# ===========================================================================
# 8. rank_strategies
# ===========================================================================

class TestRankStrategies(unittest.TestCase):

    def _ranked(self, n: int = 6, tmp=None) -> list[StrategyScore]:
        if tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            _write_json(path, _make_shadow(_simple_shadow_strategies(n)))
            t = _make_tournament(tmp)
        else:
            t = StrategyTournament.__new__(StrategyTournament)
            t.data_dir = Path("data/")
            t._output_path = t.data_dir / "strategy_tournament.json"
        return t.rank_strategies(scores=t._generate_defaults())

    def test_rank_1_is_highest_apy(self):
        ranked = self._ranked()
        for i in range(len(ranked) - 1):
            self.assertGreaterEqual(ranked[i].paper_apy, ranked[i + 1].paper_apy)

    def test_rank_numbers_sequential(self):
        ranked = self._ranked()
        for i, s in enumerate(ranked):
            self.assertEqual(s.rank, i + 1)

    def test_medals_top_3(self):
        ranked = self._ranked()
        self.assertEqual(ranked[0].medal, "🥇")
        self.assertEqual(ranked[1].medal, "🥈")
        self.assertEqual(ranked[2].medal, "🥉")

    def test_rank_4_and_beyond_no_medal(self):
        ranked = self._ranked()
        for s in ranked[3:]:
            self.assertEqual(s.medal, "")

    def test_rank_by_sharpe(self):
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        scores = [
            StrategyScore("A", "A", 5.0, 2.0, 0.01, 3),
            StrategyScore("B", "B", 3.0, 3.5, 0.01, 3),
            StrategyScore("C", "C", 8.0, 0.5, 0.01, 3),
        ]
        ranked = t.rank_strategies(metric="sharpe", scores=scores)
        self.assertEqual(ranked[0].strategy_id, "B")  # highest sharpe

    def test_rank_by_drawdown_ascending(self):
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        scores = [
            StrategyScore("A", "A", 5.0, 1.0, 0.05, 3),
            StrategyScore("B", "B", 5.0, 1.0, 0.01, 3),
            StrategyScore("C", "C", 5.0, 1.0, 0.10, 3),
        ]
        ranked = t.rank_strategies(metric="max_drawdown", scores=scores)
        # lowest drawdown = best
        self.assertEqual(ranked[0].strategy_id, "B")
        self.assertEqual(ranked[-1].strategy_id, "C")

    def test_invalid_metric_raises(self):
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        with self.assertRaises(ValueError):
            t.rank_strategies(metric="nonexistent_metric")

    def test_returns_list(self):
        ranked = self._ranked()
        self.assertIsInstance(ranked, list)

    def test_single_strategy_gets_gold(self):
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        scores = [StrategyScore("S0", "Solo", 5.0, 1.0, 0.0, 3)]
        ranked = t.rank_strategies(scores=scores)
        self.assertEqual(ranked[0].rank, 1)
        self.assertEqual(ranked[0].medal, "🥇")


# ===========================================================================
# 9. get_top_n
# ===========================================================================

class TestGetTopN(unittest.TestCase):

    def _t_with_defaults(self) -> StrategyTournament:
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        return t

    def test_top_3_default(self):
        t = self._t_with_defaults()
        top = t.get_top_n(n=3, scores=t._generate_defaults())
        self.assertEqual(len(top), 3)

    def test_top_1_is_rank_1(self):
        t = self._t_with_defaults()
        top = t.get_top_n(n=1, scores=t._generate_defaults())
        self.assertEqual(top[0].rank, 1)

    def test_top_n_larger_than_list(self):
        t = self._t_with_defaults()
        scores = [StrategyScore(f"S{i}", "X", float(i), 0.0, 0.0, 1) for i in range(2)]
        top = t.get_top_n(n=10, scores=scores)
        self.assertEqual(len(top), 2)

    def test_top_0_returns_empty(self):
        t = self._t_with_defaults()
        top = t.get_top_n(n=0, scores=t._generate_defaults())
        self.assertEqual(len(top), 0)


# ===========================================================================
# 10. generate_leaderboard_report
# ===========================================================================

class TestGenerateLeaderboardReport(unittest.TestCase):

    def test_report_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            for key in ("schema_version", "generated_at", "metric",
                        "total_strategies", "ranked_strategies",
                        "top_3", "winner", "advisory"):
                self.assertIn(key, report)

    def test_advisory_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            self.assertEqual(report["advisory"], ADVISORY)

    def test_total_strategies_matches_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            self.assertEqual(
                report["total_strategies"],
                len(report["ranked_strategies"])
            )

    def test_top_3_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            # top_3 has at most 3 entries
            self.assertLessEqual(len(report["top_3"]), 3)

    def test_winner_is_rank_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            self.assertIsNotNone(report["winner"])
            self.assertEqual(report["winner"]["rank"], 1)

    def test_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            self.assertEqual(report["schema_version"], SCHEMA_VERSION)

    def test_metric_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report(metric="sharpe")
            self.assertEqual(report["metric"], "sharpe")

    def test_generated_at_is_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            report = t.generate_leaderboard_report()
            from datetime import datetime
            # Should parse without exception
            datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))


# ===========================================================================
# 11. save_report (atomic write + ring-buffer)
# ===========================================================================

class TestSaveReport(unittest.TestCase):

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            path = t.save_report()
            self.assertTrue(os.path.exists(path))

    def test_save_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            path = t.save_report()
            self.assertIsInstance(path, str)
            self.assertTrue(path.endswith("strategy_tournament.json"))

    def test_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            path = t.save_report()
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIsInstance(data, dict)

    def test_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            t.save_report()
            tmp_files = [
                f for f in os.listdir(tmp) if f.endswith(".tmp")
            ]
            self.assertEqual(tmp_files, [])

    def test_ring_buffer_caps_at_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            # Build a fake report with 150 strategies
            big_report = {
                "schema_version": "1.0",
                "generated_at": "2026-01-01T00:00:00+00:00",
                "metric": "paper_apy",
                "total_strategies": 150,
                "ranked_strategies": [
                    {"strategy_id": f"S{i}", "rank": i + 1}
                    for i in range(150)
                ],
                "top_3": [],
                "winner": None,
                "advisory": ADVISORY,
            }
            path = t.save_report(big_report)
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertLessEqual(
                len(saved["ranked_strategies"]), RING_BUFFER_MAX
            )

    def test_save_none_generates_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            path = t.save_report(None)
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("ranked_strategies", data)

    def test_overwrite_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            t.save_report()
            t.save_report()  # second write should not raise
            path = str(t._output_path)
            self.assertTrue(os.path.exists(path))


# ===========================================================================
# 12. Medal assignment
# ===========================================================================

class TestMedalAssignment(unittest.TestCase):

    def _ranked_n(self, n: int) -> list[StrategyScore]:
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        scores = [
            StrategyScore(f"S{i}", f"Name{i}", float(n - i), 1.0, 0.0, 1)
            for i in range(n)
        ]
        return t.rank_strategies(scores=scores)

    def test_exactly_3_strategies_all_get_medals(self):
        ranked = self._ranked_n(3)
        medals = [s.medal for s in ranked]
        self.assertEqual(medals, ["🥇", "🥈", "🥉"])

    def test_2_strategies_only_gold_silver(self):
        ranked = self._ranked_n(2)
        self.assertEqual(ranked[0].medal, "🥇")
        self.assertEqual(ranked[1].medal, "🥈")

    def test_1_strategy_gold_only(self):
        ranked = self._ranked_n(1)
        self.assertEqual(ranked[0].medal, "🥇")

    def test_5_strategies_4_and_5_no_medal(self):
        ranked = self._ranked_n(5)
        self.assertEqual(ranked[3].medal, "")
        self.assertEqual(ranked[4].medal, "")


# ===========================================================================
# 13. Constants / module-level
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_advisory_nonempty_string(self):
        self.assertIsInstance(ADVISORY, str)
        self.assertGreater(len(ADVISORY), 0)

    def test_schema_version_format(self):
        self.assertIsInstance(SCHEMA_VERSION, str)
        self.assertRegex(SCHEMA_VERSION, r"^\d+\.\d+$")

    def test_valid_metrics_tuple(self):
        self.assertIn("paper_apy", VALID_METRICS)
        self.assertIn("sharpe", VALID_METRICS)
        self.assertIn("max_drawdown", VALID_METRICS)
        self.assertIn("days_active", VALID_METRICS)

    def test_ring_buffer_max_is_100(self):
        self.assertEqual(RING_BUFFER_MAX, 100)

    def test_medals_tuple_has_three(self):
        self.assertEqual(len(MEDALS), 3)

    def test_default_names_covers_s0_to_s19(self):
        for i in range(20):
            self.assertIn(f"S{i}", _DEFAULT_NAMES)


# ===========================================================================
# 14. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_shadow_with_missing_pnl_pct(self):
        """Strategy with no pnl_pct should default to 0.0 APY."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            _write_json(path, _make_shadow([{
                "name": "S0",
                # no pnl_pct field
                "days_running": 5,
                "sharpe": None,
                "max_drawdown": 0.0,
            }]))
            t = _make_tournament(tmp)
            scores = t._load_scores()
            self.assertEqual(scores[0].paper_apy, 0.0)

    def test_shadow_with_zero_days(self):
        """days_running=0 should not cause division by zero."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy_shadow_comparison.json")
            _write_json(path, _make_shadow([{
                "name": "S1", "pnl_pct": 0.05,
                "days_running": 0, "sharpe": None, "max_drawdown": 0.0,
            }]))
            t = _make_tournament(tmp)
            scores = t._load_scores()
            # Should not raise; APY is 0 (days=0)
            self.assertGreaterEqual(len(scores), 1)

    def test_rank_strategies_does_not_mutate_input(self):
        """rank_strategies should assign rank/medal but not reorder the original list."""
        t = StrategyTournament.__new__(StrategyTournament)
        t.data_dir = Path("data/")
        t._output_path = t.data_dir / "strategy_tournament.json"
        original = [
            StrategyScore("A", "A", 5.0, 1.0, 0.01, 3),
            StrategyScore("B", "B", 9.0, 1.2, 0.01, 3),
        ]
        first_id_before = original[0].strategy_id
        t.rank_strategies(scores=original)
        # Original list order should be preserved (it's sorted into a new list)
        self.assertEqual(original[0].strategy_id, first_id_before)

    def test_pnl_history_with_zero_initial_capital(self):
        """pnl_history with equity[0]==0 should not raise ZeroDivisionError."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pnl_history.json")
            _write_json(path, [
                {"total_capital_usd": 0.0},
                {"total_capital_usd": 1000.0},
            ])
            t = _make_tournament(tmp)
            # Should not raise
            scores = t._load_scores()
            self.assertGreater(len(scores), 0)

    def test_large_strategy_list_truncated_in_report(self):
        """Reports with >100 ranked strategies are capped by ring-buffer."""
        with tempfile.TemporaryDirectory() as tmp:
            t = _make_tournament(tmp)
            # Feed 110 strategies
            scores = [
                StrategyScore(f"X{i}", f"Name{i}", float(110 - i), 1.0, 0.0, 1)
                for i in range(110)
            ]
            ranked = t.rank_strategies(scores=scores)
            report = t.generate_leaderboard_report.__func__(t)  # normal call
            report["ranked_strategies"] = [s.to_dict() for s in ranked]
            path = t.save_report(report)
            with open(path, "r") as fh:
                saved = json.load(fh)
            self.assertLessEqual(len(saved["ranked_strategies"]), RING_BUFFER_MAX)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for spa_core.strategies.backtester (Sprint C / v3.91).

Stdlib unittest only. ``run_strategy_screening`` is exercised with write=False
so no test ever touches data/strategy_screening.json.
"""
from __future__ import annotations

import unittest

from spa_core.strategies.backtester import (
    StrategyBacktester,
    BacktestResult,
    generate_synthetic_history,
    run_strategy_screening,
    _normalize_snapshot,
    SYNTHETIC_APY_MIN,
    SYNTHETIC_APY_MAX,
)
from spa_core.strategies import STRATEGY_REGISTRY
from spa_core.strategies.baseline import BaselineStrategy


def _history(n=10):
    return generate_synthetic_history(n_steps=n)


class TestSyntheticHistory(unittest.TestCase):
    def test_synthetic_history_shape(self):
        hist = generate_synthetic_history(n_steps=30)
        self.assertEqual(len(hist), 30)
        first = hist[0]
        self.assertIn("ts", first)
        self.assertIn("adapters", first)
        self.assertIsInstance(first["adapters"], dict)
        for pool_id, fields in first["adapters"].items():
            self.assertIn("apy", fields)
            self.assertIsInstance(fields["apy"], float)

    def test_reproducible_with_seed(self):
        a = generate_synthetic_history(n_steps=15)
        b = generate_synthetic_history(n_steps=15)
        self.assertEqual(a, b)

    def test_apy_within_bounds(self):
        hist = generate_synthetic_history(n_steps=50)
        for snap in hist:
            for fields in snap["adapters"].values():
                self.assertGreaterEqual(fields["apy"], SYNTHETIC_APY_MIN)
                self.assertLessEqual(fields["apy"], SYNTHETIC_APY_MAX)

    def test_timestamps_monotonic(self):
        hist = generate_synthetic_history(n_steps=10)
        ts = [s["ts"] for s in hist]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(len(set(ts)), len(ts))

    def test_custom_pools(self):
        hist = generate_synthetic_history(n_steps=5, pools={"aave_v3": 4.0})
        self.assertEqual(set(hist[0]["adapters"].keys()), {"aave_v3"})


class TestNormalizeSnapshot(unittest.TestCase):
    def test_compact_to_orchestrator_shape(self):
        snap = {"ts": 1.0, "adapters": {"morpho_blue": {"apy": 8.3, "tvl": 1e6}}}
        norm = _normalize_snapshot(snap)
        self.assertIsInstance(norm["adapters"], list)
        ad = norm["adapters"][0]
        self.assertEqual(ad["protocol"], "morpho_blue")
        self.assertEqual(ad["apy_pct"], 8.3)
        self.assertEqual(ad["status"], "ok")
        self.assertEqual(ad["tier"], "T2")

    def test_list_passthrough(self):
        snap = {"run_ts": 1.0, "adapters": [{"protocol": "x", "apy_pct": 5.0}]}
        self.assertIs(_normalize_snapshot(snap), snap)


class TestBacktestRun(unittest.TestCase):
    def test_backtest_runs_without_error(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(10))
        self.assertIsInstance(res, BacktestResult)

    def test_result_structure(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(12))
        d = res.to_dict()
        for key in (
            "strategy_name",
            "equity_curve",
            "final_equity",
            "total_return_pct",
            "sortino",
            "sharpe_with_ci",
            "max_drawdown_pct",
            "n_rebalances",
            "passed_screening",
            "screening_notes",
        ):
            self.assertIn(key, d)

    def test_equity_curve_length_matches_steps(self):
        bt = StrategyBacktester()
        hist = _history(8)
        res = bt.run(BaselineStrategy(), hist)
        self.assertEqual(len(res.equity_curve), len(hist))
        for pt in res.equity_curve:
            self.assertIn("ts", pt)
            self.assertIn("equity", pt)
            self.assertIn("pnl_pct", pt)

    def test_sortino_computed_correctly(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(20))
        self.assertIn("value", res.sortino)
        self.assertIn("confidence", res.sortino)
        self.assertIn("n", res.sortino)

    def test_positive_apy_grows_equity(self):
        # All pools have positive APY -> equity should rise above starting capital.
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(30))
        self.assertGreater(res.final_equity, 100_000.0)
        self.assertGreater(res.total_return_pct, 0.0)

    def test_n_rebalances_counted(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(10))
        self.assertEqual(res.n_rebalances, 10)

    def test_empty_history_passes_by_insufficient_data(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), [])
        self.assertTrue(res.passed_screening)
        self.assertEqual(res.final_equity, 100_000.0)

    def test_short_history_passes_screening(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(3))  # <5 -> insufficient
        self.assertTrue(res.passed_screening)
        self.assertTrue(any("insufficient" in n for n in res.screening_notes))

    def test_max_drawdown_non_negative(self):
        bt = StrategyBacktester()
        res = bt.run(BaselineStrategy(), _history(20))
        self.assertGreaterEqual(res.max_drawdown_pct, 0.0)


class TestScreeningTable(unittest.TestCase):
    def test_run_strategy_screening_structure(self):
        doc = run_strategy_screening(n_steps=20, write=False)
        self.assertIn("strategies", doc)
        self.assertEqual(doc["n_strategies"], len(STRATEGY_REGISTRY))
        self.assertEqual(doc["passed"] + doc["failed"], doc["n_strategies"])
        for name, row in doc["strategies"].items():
            self.assertIn("sortino", row)
            self.assertIn("total_return_pct", row)
            self.assertIn("max_drawdown_pct", row)
            self.assertIn("passed_screening", row)

    def test_all_six_strategies_present(self):
        doc = run_strategy_screening(n_steps=15, write=False)
        self.assertEqual(len(doc["strategies"]), 6)

    def test_screening_no_write_leaves_no_file(self):
        # write=False must not raise and must return a fully-formed doc.
        doc = run_strategy_screening(n_steps=10, write=False)
        self.assertIsInstance(doc, dict)
        self.assertIn("schema_version", doc)


if __name__ == "__main__":
    unittest.main()

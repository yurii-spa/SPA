#!/usr/bin/env python3
"""Tests for spa_core.analytics.portfolio_optimizer (MP-1249). Pure stdlib / unittest."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics import portfolio_optimizer as po


def _make_series(data_dir: Path, overrides=None):
    """Create a historical_apy/ dir with constant-APY 365-day series per protocol."""
    overrides = overrides or {}
    base = {
        "aave_v3_usdc": 3.1,
        "compound_v3_usdc": 3.3,
        "yearn_v3_usdc": 3.5,
        "morpho_blue_usdc": 6.0,
        "sky_susds": 4.0,
    }
    base.update(overrides)
    hdir = data_dir / "historical_apy"
    hdir.mkdir(parents=True, exist_ok=True)
    for fname, apy in base.items():
        records = [{"date": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}", "apy": apy}
                   for i in range(365)]
        (hdir / f"{fname}.json").write_text(json.dumps(records), encoding="utf-8")


class HelperMathTests(unittest.TestCase):
    def test_mean_basic(self):
        self.assertAlmostEqual(po._mean([1.0, 2.0, 3.0]), 2.0)

    def test_mean_empty(self):
        self.assertEqual(po._mean([]), 0.0)

    def test_std_zero_for_constant(self):
        self.assertEqual(po._std([5.0, 5.0, 5.0]), 0.0)

    def test_std_single_element(self):
        self.assertEqual(po._std([5.0]), 0.0)

    def test_std_known_value(self):
        # sample std of [2,4,4,4,5,5,7,9] == 2.138...
        self.assertAlmostEqual(po._std([2, 4, 4, 4, 5, 5, 7, 9]), 2.13809, places=4)

    def test_frange_inclusive(self):
        self.assertEqual(po._frange(0, 20, 5), [0, 5, 10, 15, 20])

    def test_frange_bounds(self):
        self.assertEqual(po._frange(10, 60, 5)[0], 10)
        self.assertEqual(po._frange(10, 60, 5)[-1], 60)


class StructuralTests(unittest.TestCase):
    def test_universe_length(self):
        self.assertEqual(len(po.UNIVERSE), 5)
        self.assertEqual(len(po.KEYS), 5)

    def test_tier_categorization(self):
        self.assertEqual(po.TIER["aave"], "T1")
        self.assertEqual(po.TIER["compound"], "T1")
        self.assertEqual(po.TIER["sky"], "T1")  # stable treated as T1
        self.assertEqual(po.TIER["yearn"], "T2")
        self.assertEqual(po.TIER["morpho"], "T2")

    def test_key_to_file_maps_all(self):
        for k in po.KEYS:
            self.assertIn(k, po.KEY_TO_FILE)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        # constant series: aave=4% everywhere etc.
        self.series = {k: [4.0] * 365 for k in po.KEYS}

    def test_daily_returns_constant(self):
        w = {k: (1.0 if k == "aave" else 0.0) for k in po.KEYS}
        rets = po.daily_returns(w, self.series)
        self.assertEqual(len(rets), 365)
        self.assertAlmostEqual(rets[0], 4.0 / 100.0 / 365.0)

    def test_max_drawdown_zero_for_positive_yield(self):
        w = {k: 0.2 for k in po.KEYS}
        m = po.portfolio_metrics(w, self.series)
        self.assertEqual(m["max_drawdown_pct"], 0.0)

    def test_cagr_close_to_apy_for_constant(self):
        w = {k: 0.2 for k in po.KEYS}
        m = po.portfolio_metrics(w, self.series)
        # 4% simple daily compounding ~ 4.08% CAGR
        self.assertTrue(3.9 < m["cagr_pct"] < 4.2)

    def test_expected_apy_weighted_mean(self):
        series = {"aave": [2.0] * 10, "compound": [6.0] * 10,
                  "sky": [0.0] * 10, "yearn": [0.0] * 10, "morpho": [0.0] * 10}
        w = {"aave": 0.5, "compound": 0.5, "sky": 0.0, "yearn": 0.0, "morpho": 0.0}
        m = po.portfolio_metrics(w, series)
        self.assertAlmostEqual(m["expected_apy_pct"], 4.0, places=3)

    def test_sharpe_zero_when_no_variance(self):
        w = {k: 0.2 for k in po.KEYS}
        m = po.portfolio_metrics(w, self.series)
        self.assertEqual(m["sharpe_daily"], 0.0)

    def test_blended_score_formula(self):
        m = {"_cagr": 0.04, "_sharpe": 2.0, "_max_dd": 0.0}
        self.assertAlmostEqual(po.blended_score(m), 0.5 * 0.04 + 0.3 * 2.0 + 0.2 * 1.0)


class GridSearchTests(unittest.TestCase):
    def setUp(self):
        self.series = {
            "aave": [3.1] * 365, "compound": [3.3] * 365, "sky": [4.0] * 365,
            "yearn": [3.5] * 365, "morpho": [6.0] * 365,
        }
        self.results = po.grid_search(self.series, step=5)

    def test_produces_results(self):
        self.assertGreater(len(self.results), 0)

    def test_all_weights_sum_to_100(self):
        for p in self.results:
            self.assertEqual(sum(p["weights_pct"].values()), 100)

    def test_all_weights_sum_to_one(self):
        for p in self.results:
            self.assertAlmostEqual(sum(p["weights"].values()), 1.0, places=9)

    def test_t2_per_protocol_cap(self):
        for p in self.results:
            self.assertLessEqual(p["weights_pct"]["yearn"], po.T2_PER_CAP_PCT)
            self.assertLessEqual(p["weights_pct"]["morpho"], po.T2_PER_CAP_PCT)

    def test_t2_total_cap(self):
        for p in self.results:
            self.assertLessEqual(p["weights_pct"]["yearn"] + p["weights_pct"]["morpho"],
                                 po.T2_TOTAL_CAP_PCT)

    def test_bounds_respected(self):
        for p in self.results:
            for k in po.KEYS:
                lo, hi = po.BOUNDS[k]
                self.assertGreaterEqual(p["weights_pct"][k], lo)
                self.assertLessEqual(p["weights_pct"][k], hi)

    def test_invalid_step_raises(self):
        with self.assertRaises(ValueError):
            po.grid_search(self.series, step=0)

    def test_optimal_prefers_morpho_max(self):
        # morpho has the highest APY → best blended portfolio should max it at 20%
        by_blended = sorted(self.results, key=lambda p: p["score"], reverse=True)
        self.assertEqual(by_blended[0]["weights_pct"]["morpho"], 20)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        _make_series(self.data_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_series_aligned_length(self):
        series = po.load_series(self.data_dir)
        lengths = {len(v) for v in series.values()}
        self.assertEqual(lengths, {365})

    def test_load_series_missing_file_raises(self):
        (self.data_dir / "historical_apy" / "aave_v3_usdc.json").unlink()
        with self.assertRaises(ValueError):
            po.load_series(self.data_dir)

    def test_optimize_document_shape(self):
        doc = po.optimize(self.data_dir, step=5, run_date="2026-06-21")
        for key in ("best_by_return", "best_by_sharpe", "best_blended",
                    "top_10", "run_date", "universe"):
            self.assertIn(key, doc)
        self.assertEqual(doc["run_date"], "2026-06-21")
        self.assertEqual(doc["universe"], po.UNIVERSE)

    def test_top_10_sorted_and_capped(self):
        doc = po.optimize(self.data_dir, step=5)
        self.assertLessEqual(len(doc["top_10"]), 10)
        scores = [p["score"] for p in doc["top_10"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_best_by_return_has_max_cagr(self):
        doc = po.optimize(self.data_dir, step=5)
        all_results = po.grid_search(po.load_series(self.data_dir), step=5)
        max_cagr = max(p["metrics"]["cagr_pct"] for p in all_results)
        self.assertEqual(doc["best_by_return"]["metrics"]["cagr_pct"], max_cagr)

    def test_atomic_write_and_reload(self):
        doc = po.optimize(self.data_dir, step=5)
        out = self.data_dir / "optimizer_results.json"
        po._atomic_write(out, doc)
        self.assertTrue(out.exists())
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(reloaded["universe"], po.UNIVERSE)

    def test_comparison_present_with_positions(self):
        positions = {"positions": {
            "aave_v3": 5000.0, "compound_v3": 5000.0, "yearn_v3": 1000.0,
            "morpho_blue": 1000.0, "spark_susds": 3000.0, "unmapped_proto": 9999.0,
        }}
        (self.data_dir / "current_positions.json").write_text(json.dumps(positions))
        doc = po.optimize(self.data_dir, step=5)
        cmp = doc["comparison_vs_current"]
        self.assertIsNotNone(cmp)
        self.assertIn("apy_difference_pct", cmp)
        # unmapped position must be excluded → weights sum ~100
        self.assertAlmostEqual(sum(cmp["current_weights_pct"].values()), 100.0, places=1)

    def test_comparison_none_without_positions(self):
        doc = po.optimize(self.data_dir, step=5)
        self.assertIsNone(doc["comparison_vs_current"])

    def test_cli_check_exit_zero(self):
        rc = po.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_cli_run_writes_file(self):
        rc = po.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / "optimizer_results.json").exists())

    def test_cli_bad_data_dir_exit_zero(self):
        rc = po.main(["--check", "--data-dir", "/nonexistent/path/xyz"])
        self.assertEqual(rc, 0)  # never traceback


if __name__ == "__main__":
    unittest.main()

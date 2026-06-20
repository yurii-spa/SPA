"""
tests/test_monte_carlo.py

MP-1496 (v11.12) — 30 unit tests for MonteCarloSimulator.

Covers:
  1. Instantiation & defaults                          (3 tests)
  2. simulate(): return structure & required keys      (7 tests)
  3. simulate(): statistical correctness               (7 tests)
  4. _verdict() logic                                  (4 tests)
  5. Reproducibility (seed)                            (3 tests)
  6. Edge cases (1 sim, 1 day, zero std)               (4 tests)
  7. to_dict & output path                             (2 tests)

Compatible with stdlib unittest and pytest.
"""

import os
import sys
import tempfile
import json
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.monte_carlo import MonteCarloSimulator


# ── helpers ───────────────────────────────────────────────────────────────────

def _sim(strategy_id="S0", mean=0.0004, std=0.008, n_days=252, n_sims=200, seed=42, base_dir=None):
    mc = MonteCarloSimulator(base_dir=base_dir or tempfile.mkdtemp())
    return mc.simulate(strategy_id, mean, std, n_days=n_days, n_sims=n_sims, seed=seed)


class TestInstantiation(unittest.TestCase):
    """TC-MC-01..03: __init__ sets correct defaults."""

    def test_01_n_simulations_default(self):
        mc = MonteCarloSimulator()
        self.assertEqual(mc.N_SIMULATIONS, 1000)

    def test_02_data_dict_empty_results(self):
        mc = MonteCarloSimulator()
        self.assertEqual(mc._data["results"], {})

    def test_03_simulations_run_starts_at_zero(self):
        mc = MonteCarloSimulator()
        self.assertEqual(mc._data["simulations_run"], 0)


class TestSimulateStructure(unittest.TestCase):
    """TC-MC-04..10: simulate() return structure."""

    def setUp(self):
        self.result = _sim()

    def test_04_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_05_has_strategy_key(self):
        self.assertIn("strategy", self.result)
        self.assertEqual(self.result["strategy"], "S0")

    def test_06_has_percentile_keys(self):
        for key in ("p5", "p25", "p50", "p75", "p95"):
            self.assertIn(key, self.result)

    def test_07_has_probability_keys(self):
        self.assertIn("prob_profitable", self.result)
        self.assertIn("prob_drawdown_20pct", self.result)

    def test_08_has_verdict(self):
        self.assertIn("verdict", self.result)

    def test_09_simulations_count_correct(self):
        self.assertEqual(self.result["simulations"], 200)

    def test_10_n_days_correct(self):
        self.assertEqual(self.result["n_days"], 252)


class TestSimulateStatistics(unittest.TestCase):
    """TC-MC-11..17: statistical correctness."""

    def test_11_percentiles_ordered(self):
        r = _sim(mean=0.0005, std=0.005, n_sims=500, seed=0)
        self.assertLessEqual(r["p5"], r["p25"])
        self.assertLessEqual(r["p25"], r["p50"])
        self.assertLessEqual(r["p50"], r["p75"])
        self.assertLessEqual(r["p75"], r["p95"])

    def test_12_prob_profitable_between_0_and_1(self):
        r = _sim()
        self.assertGreaterEqual(r["prob_profitable"], 0.0)
        self.assertLessEqual(r["prob_profitable"], 1.0)

    def test_13_prob_drawdown_between_0_and_1(self):
        r = _sim()
        self.assertGreaterEqual(r["prob_drawdown_20pct"], 0.0)
        self.assertLessEqual(r["prob_drawdown_20pct"], 1.0)

    def test_14_positive_drift_high_prob_profitable(self):
        # Large positive mean → most paths end above 1.0
        r = _sim(mean=0.003, std=0.001, n_sims=500, seed=1)
        self.assertGreater(r["prob_profitable"], 0.90)

    def test_15_negative_drift_low_prob_profitable(self):
        # Large negative mean → most paths end below 1.0
        r = _sim(mean=-0.005, std=0.001, n_sims=500, seed=2)
        self.assertLess(r["prob_profitable"], 0.10)

    def test_16_p50_near_1_for_zero_drift(self):
        # Zero drift, many sims → median ≈ 1.0 (log-normal bias makes it slightly < 1)
        r = _sim(mean=0.0, std=0.005, n_sims=2000, seed=3)
        self.assertGreater(r["p50"], 0.6)
        self.assertLess(r["p50"], 1.4)

    def test_17_cagr_positive_for_positive_drift(self):
        r = _sim(mean=0.002, std=0.001, n_sims=200, seed=4)
        self.assertGreater(r["cagr_estimate"], 0)


class TestVerdict(unittest.TestCase):
    """TC-MC-18..21: _verdict() logic."""

    def test_18_robust_verdict(self):
        v = MonteCarloSimulator._verdict(0.80, 0.05)
        self.assertEqual(v, "ROBUST")

    def test_19_moderate_verdict_by_profit_prob(self):
        v = MonteCarloSimulator._verdict(0.60, 0.15)
        self.assertEqual(v, "MODERATE")

    def test_20_risky_verdict_low_profit(self):
        v = MonteCarloSimulator._verdict(0.40, 0.05)
        self.assertEqual(v, "RISKY")

    def test_21_risky_verdict_high_drawdown(self):
        # High profit but also high drawdown → not ROBUST
        v = MonteCarloSimulator._verdict(0.75, 0.35)
        # prob_profitable >= 0.70 but prob_drawdown_20 >= 0.10 → MODERATE
        self.assertEqual(v, "MODERATE")


class TestReproducibility(unittest.TestCase):
    """TC-MC-22..24: same seed → same results."""

    def test_22_same_seed_same_p50(self):
        r1 = _sim(seed=99)
        r2 = _sim(seed=99)
        self.assertEqual(r1["p50"], r2["p50"])

    def test_23_different_seeds_may_differ(self):
        r1 = _sim(seed=10)
        r2 = _sim(seed=20)
        # Not guaranteed but extremely likely with 200 sims
        self.assertNotEqual(r1["p50"], r2["p50"])

    def test_24_seed_none_still_runs(self):
        mc = MonteCarloSimulator(base_dir=tempfile.mkdtemp())
        result = mc.simulate("S1", 0.0004, 0.008, n_sims=50, seed=None)
        self.assertIn("p50", result)


class TestEdgeCases(unittest.TestCase):
    """TC-MC-25..28: edge cases."""

    def test_25_single_simulation(self):
        r = _sim(n_sims=1, seed=5)
        self.assertEqual(r["simulations"], 1)
        self.assertIn("p50", r)

    def test_26_single_day(self):
        r = _sim(n_days=1, n_sims=100, seed=6)
        self.assertEqual(r["n_days"], 1)
        self.assertIn("prob_profitable", r)

    def test_27_zero_std_all_paths_identical(self):
        # std=0 → all paths end at same value; p5 == p95
        r = _sim(mean=0.001, std=0.0, n_sims=50, seed=7)
        self.assertAlmostEqual(r["p5"], r["p95"], places=5)

    def test_28_simulations_run_accumulates(self):
        mc = MonteCarloSimulator(base_dir=tempfile.mkdtemp())
        mc.simulate("S0", 0.0004, 0.008, n_sims=100, seed=1)
        mc.simulate("S1", 0.0003, 0.007, n_sims=150, seed=2)
        self.assertEqual(mc._data["simulations_run"], 250)


class TestToDictAndOutput(unittest.TestCase):
    """TC-MC-29..30: to_dict & file output."""

    def test_29_to_dict_returns_dict(self):
        mc = MonteCarloSimulator()
        self.assertIsInstance(mc.to_dict(), dict)

    def test_30_simulate_writes_json_file(self):
        tmpdir = tempfile.mkdtemp()
        mc = MonteCarloSimulator(base_dir=tmpdir)
        mc.simulate("S3", 0.0004, 0.008, n_sims=50, seed=8)
        out_path = os.path.join(tmpdir, mc.OUTPUT_PATH)
        self.assertTrue(os.path.exists(out_path))
        with open(out_path) as f:
            data = json.load(f)
        self.assertIn("results", data)


if __name__ == "__main__":
    unittest.main()

"""Tests for LiquidityStressSimulator.analyze() — BaseAnalytics contract (MP-649).

These tests focus on the concrete analyze() implementation added to make the
class instantiable (it was abstract → silently swallowed by the cycle's
analytics pipeline as a "failed" module). conftest.py puts the repo root on
sys.path.
"""
from __future__ import annotations

import unittest

from spa_core.base import BaseAnalytics
from spa_core.analytics.liquidity_stress_simulator import (
    AdapterLiquidity,
    LiquidityStressSimulator,
    SCENARIOS,
    _build_demo_adapters,
)


class TestInstantiable(unittest.TestCase):
    """The whole point: the class must no longer be abstract."""

    def test_can_instantiate(self):
        # Previously raised TypeError: abstract method 'analyze'.
        sim = LiquidityStressSimulator()
        self.assertIsInstance(sim, LiquidityStressSimulator)

    def test_is_baseanalytics_subclass(self):
        self.assertTrue(issubclass(LiquidityStressSimulator, BaseAnalytics))

    def test_analyze_is_concrete(self):
        self.assertNotIn("analyze", LiquidityStressSimulator.__abstractmethods__)

    def test_module_name_set(self):
        self.assertEqual(
            LiquidityStressSimulator.MODULE_NAME, "liquidity_stress_simulator"
        )


class TestAnalyzeEnvelope(unittest.TestCase):
    """analyze() must return the required {module_id, status, timestamp, result}."""

    def setUp(self):
        self.sim = LiquidityStressSimulator()
        self.out = self.sim.analyze()

    def test_returns_dict(self):
        self.assertIsInstance(self.out, dict)

    def test_has_required_keys(self):
        for key in ("module_id", "status", "timestamp", "result"):
            self.assertIn(key, self.out)

    def test_module_id_value(self):
        self.assertEqual(self.out["module_id"], "liquidity_stress_simulator")

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.out["timestamp"], float)
        self.assertGreater(self.out["timestamp"], 0)

    def test_status_is_valid_verdict(self):
        self.assertIn(self.out["status"], ("SAFE", "WATCH", "CRITICAL"))

    def test_result_is_dict(self):
        self.assertIsInstance(self.out["result"], dict)

    def test_result_has_scenarios(self):
        self.assertIn("scenarios", self.out["result"])
        self.assertEqual(
            set(self.out["result"]["scenarios"].keys()), set(SCENARIOS.keys())
        )

    def test_result_has_tvl_ratios(self):
        self.assertIn("tvl_ratios", self.out["result"])
        self.assertIsInstance(self.out["result"]["tvl_ratios"], dict)

    def test_result_has_worst_coverage(self):
        wc = self.out["result"]["worst_coverage_ratio"]
        self.assertIsInstance(wc, float)
        self.assertGreaterEqual(wc, 0.0)

    def test_adapters_analyzed_count(self):
        self.assertEqual(
            self.out["result"]["adapters_analyzed"], len(_build_demo_adapters())
        )


class TestAnalyzeBehavior(unittest.TestCase):
    def setUp(self):
        self.sim = LiquidityStressSimulator()

    def test_single_scenario(self):
        out = self.sim.analyze(scenario="SEVERE")
        self.assertEqual(list(out["result"]["scenarios"].keys()), ["SEVERE"])

    def test_unknown_scenario_falls_back_to_moderate(self):
        out = self.sim.analyze(scenario="NONSENSE")
        self.assertEqual(list(out["result"]["scenarios"].keys()), ["MODERATE"])

    def test_explicit_adapters_respected(self):
        adapters = [AdapterLiquidity("solo", 10_000, "T1", 0, 1_000_000, 0.10)]
        out = self.sim.analyze(adapters=adapters)
        self.assertEqual(out["result"]["adapters_analyzed"], 1)
        self.assertIn("solo", out["result"]["tvl_ratios"])

    def test_all_locked_is_critical(self):
        # No liquid capital → 0 coverage → CRITICAL.
        adapters = [AdapterLiquidity("lock", 10_000, "T2", 30, 1_000_000, 0.01)]
        out = self.sim.analyze(adapters=adapters)
        self.assertEqual(out["status"], "CRITICAL")
        self.assertEqual(out["result"]["worst_coverage_ratio"], 0.0)

    def test_fully_liquid_higher_coverage_than_locked(self):
        liquid = self.sim.analyze(
            adapters=[AdapterLiquidity("liq", 10_000, "T1", 0, 1_000_000, 0.10)]
        )
        locked = self.sim.analyze(
            adapters=[AdapterLiquidity("lck", 10_000, "T1", 30, 1_000_000, 0.10)]
        )
        self.assertGreater(
            liquid["result"]["worst_coverage_ratio"],
            locked["result"]["worst_coverage_ratio"],
        )

    def test_tvl_ratio_computed(self):
        adapters = [AdapterLiquidity("a", 50_000, "T1", 0, 1_000_000, 0.10)]
        out = self.sim.analyze(adapters=adapters)
        self.assertAlmostEqual(out["result"]["tvl_ratios"]["a"], 0.05, places=6)

    def test_zero_tvl_adapter_excluded_from_ratios(self):
        adapters = [AdapterLiquidity("zt", 10_000, "T1", 0, 0.0, 0.10)]
        out = self.sim.analyze(adapters=adapters)
        self.assertNotIn("zt", out["result"]["tvl_ratios"])

    def test_empty_adapters_does_not_crash(self):
        out = self.sim.analyze(adapters=[])
        self.assertEqual(out["result"]["adapters_analyzed"], 0)
        self.assertIn(out["status"], ("SAFE", "WATCH", "CRITICAL"))

    def test_json_serializable(self):
        import json

        json.dumps(self.sim.analyze())  # must not raise

    def test_severe_lower_coverage_than_mild(self):
        out = self.sim.analyze()
        mild = out["result"]["scenarios"]["MILD"]["coverage_ratio"]
        severe = out["result"]["scenarios"]["SEVERE"]["coverage_ratio"]
        self.assertGreater(mild, severe)

    def test_scenario_payload_fields(self):
        out = self.sim.analyze(scenario="MODERATE")
        payload = out["result"]["scenarios"]["MODERATE"]
        for f in ("verdict", "coverage_ratio", "withdrawable_stress", "total_deployed"):
            self.assertIn(f, payload)


if __name__ == "__main__":
    unittest.main()

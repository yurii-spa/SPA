"""Tests for spa_core.paper_trading.rebalance_trigger smart triggers
(MP-1577 / Improvement 2).

Focuses on the new APY-spread (RT-05) rule and the smart USD-based helpers,
plus regression coverage that the existing RT-01 drift trigger still fires.

20 unit tests across:
  - TestRT05ApySpread      (7)
  - TestUsdToWeights       (4)
  - TestSmartRebalance     (5)
  - TestEvaluateFromState  (4)

Run:
  python3 -m unittest spa_core.tests.test_rebalance_trigger -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.paper_trading.rebalance_trigger import (
    RebalanceTrigger,
    evaluate_from_state,
    smart_rebalance_check,
    usd_to_weights,
)


class TestRT05ApySpread(unittest.TestCase):
    def setUp(self):
        self.t = RebalanceTrigger()

    def test_spread_above_threshold_triggers(self):
        r = self.t.check_rt05_apy_spread(4.0, {"morpho": 6.0})
        self.assertTrue(r["triggered"])
        self.assertAlmostEqual(r["spread_pct"], 2.0, places=4)
        self.assertEqual(r["best_protocol"], "morpho")

    def test_spread_below_threshold_no_trigger(self):
        r = self.t.check_rt05_apy_spread(4.0, {"morpho": 5.0})
        self.assertFalse(r["triggered"])
        self.assertAlmostEqual(r["spread_pct"], 1.0, places=4)

    def test_exact_threshold_not_triggered(self):
        # strictly greater-than: spread of exactly 1.5 should NOT fire
        r = self.t.check_rt05_apy_spread(4.0, {"x": 5.5})
        self.assertFalse(r["triggered"])

    def test_list_of_apys(self):
        r = self.t.check_rt05_apy_spread(3.0, [3.1, 5.2, 4.0])
        self.assertTrue(r["triggered"])
        self.assertAlmostEqual(r["best_apy_pct"], 5.2, places=4)

    def test_best_below_current_zero_spread(self):
        r = self.t.check_rt05_apy_spread(8.0, {"a": 4.0, "b": 5.0})
        self.assertFalse(r["triggered"])
        self.assertEqual(r["spread_pct"], 0.0)

    def test_none_current_treated_as_zero(self):
        r = self.t.check_rt05_apy_spread(None, [2.0])
        self.assertTrue(r["triggered"])  # 2.0 - 0.0 = 2.0 > 1.5

    def test_garbage_available_no_crash(self):
        r = self.t.check_rt05_apy_spread(4.0, {"a": "bad", "b": None})
        self.assertFalse(r["triggered"])
        self.assertEqual(r["best_apy_pct"], 4.0)


class TestUsdToWeights(unittest.TestCase):
    def test_basic(self):
        w = usd_to_weights({"a": 25, "b": 75})
        self.assertAlmostEqual(w["a"], 0.25, places=6)
        self.assertAlmostEqual(w["b"], 0.75, places=6)

    def test_empty(self):
        self.assertEqual(usd_to_weights({}), {})

    def test_skips_nonpositive_and_nonnumeric(self):
        w = usd_to_weights({"a": 100, "b": 0, "c": -5, "d": "x"})
        self.assertEqual(set(w), {"a"})
        self.assertAlmostEqual(w["a"], 1.0, places=6)

    def test_invalid_input_type(self):
        self.assertEqual(usd_to_weights(None), {})


class TestSmartRebalance(unittest.TestCase):
    def test_apy_spread_fires_rt05(self):
        out = smart_rebalance_check(
            current_positions={"aave_v3": 50000, "compound_v3": 50000},
            target_positions={"aave_v3": 50000, "compound_v3": 50000},
            current_apy_pct=4.0,
            available_apys={"morpho": 7.0},
        )
        self.assertTrue(out["should_rebalance"])
        self.assertIn("RT-05", out["triggered"])

    def test_drift_fires_rt01(self):
        out = smart_rebalance_check(
            current_positions={"aave_v3": 80000, "compound_v3": 20000},
            target_positions={"aave_v3": 50000, "compound_v3": 50000},
            current_apy_pct=4.0,
            available_apys={"aave_v3": 4.1},
        )
        self.assertTrue(out["should_rebalance"])
        self.assertIn("RT-01", out["triggered"])

    def test_no_trigger_when_aligned(self):
        out = smart_rebalance_check(
            current_positions={"aave_v3": 50000, "compound_v3": 50000},
            target_positions={"aave_v3": 50000, "compound_v3": 50000},
            current_apy_pct=5.0,
            available_apys={"aave_v3": 5.1},
        )
        self.assertFalse(out["should_rebalance"])
        self.assertEqual(out["triggered"], [])

    def test_both_drift_and_spread(self):
        out = smart_rebalance_check(
            current_positions={"aave_v3": 90000, "compound_v3": 10000},
            target_positions={"aave_v3": 50000, "compound_v3": 50000},
            current_apy_pct=3.0,
            available_apys={"morpho": 9.0},
        )
        self.assertIn("RT-01", out["triggered"])
        self.assertIn("RT-05", out["triggered"])

    def test_empty_positions_safe(self):
        out = smart_rebalance_check(
            current_positions={},
            target_positions={},
            current_apy_pct=None,
            available_apys=None,
        )
        self.assertFalse(out["should_rebalance"])


class TestEvaluateFromState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)

    def _w(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_missing_files_no_crash(self):
        out = evaluate_from_state(str(self.dir))
        self.assertIn("should_rebalance", out)
        self.assertFalse(out["should_rebalance"])

    def test_apy_spread_from_snapshot(self):
        self._w("paper_trading_status.json",
                {"current_positions": {"aave_v3": 100000}, "apy_today_pct": 3.0})
        self._w("adapter_snapshot.json",
                {"protocols": [{"name": "morpho", "apy": 8.0}]})
        out = evaluate_from_state(str(self.dir))
        self.assertTrue(out["should_rebalance"])
        self.assertIn("RT-05", out["triggered"])

    def test_drift_from_target_file(self):
        self._w("paper_trading_status.json",
                {"current_positions": {"aave_v3": 90000, "compound_v3": 10000},
                 "apy_today_pct": 4.0})
        self._w("target_allocation.json",
                {"target_positions": {"aave_v3": 50000, "compound_v3": 50000}})
        out = evaluate_from_state(str(self.dir))
        self.assertIn("RT-01", out["triggered"])

    def test_aligned_state_no_trigger(self):
        self._w("paper_trading_status.json",
                {"current_positions": {"aave_v3": 50000, "compound_v3": 50000},
                 "apy_today_pct": 5.0})
        self._w("adapter_snapshot.json",
                {"protocols": [{"name": "aave_v3", "apy": 5.1}]})
        out = evaluate_from_state(str(self.dir))
        self.assertFalse(out["should_rebalance"])


if __name__ == "__main__":
    unittest.main()

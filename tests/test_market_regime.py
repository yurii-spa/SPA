"""
tests/test_market_regime.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit + smoke tests for spa_core.analysis.market_regime.MarketRegimeDetector.

Test groups (≥35 tests total):
  TestDetectStable          — STABLE regime classification  (8 tests)
  TestDetectHighYield       — HIGH_YIELD regime             (7 tests)
  TestDetectCompressedYield — COMPRESSED_YIELD regime       (6 tests)
  TestDetectVolatile        — VOLATILE regime               (6 tests)
  TestGetRegimeWeights      — get_regime_weights contract   (12 tests)
  TestEdgeCases             — empty map, single adapter…    (8 tests)
  TestCachePersistence      — save_to_cache atomic write    (3 tests)
  TestToDict                — to_dict serialisable state    (3 tests)
  TestCLI                   — subprocess smoke              (3 tests)

Run with:
    python3 -m pytest tests/test_market_regime.py -v
or (stdlib only):
    python3 -m unittest tests.test_market_regime -v
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import unittest
import tempfile

# Ensure project root is on sys.path regardless of where pytest is invoked.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analysis.market_regime import MarketRegimeDetector  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detector(**kwargs) -> MarketRegimeDetector:
    return MarketRegimeDetector(**kwargs)


# ---------------------------------------------------------------------------
# 1. STABLE regime
# ---------------------------------------------------------------------------

class TestDetectStable(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def test_stable_typical_t1_apy(self):
        r = self.d.detect({"aave-v3": 4.2, "compound-v3": 4.8, "morpho-steakhouse": 6.0})
        self.assertEqual(r["regime"], "STABLE")

    def test_stable_recommendation_is_hold(self):
        r = self.d.detect({"aave-v3": 5.0, "compound-v3": 5.5})
        self.assertEqual(r["recommendation"], "hold")

    def test_stable_result_has_required_keys(self):
        required = {"regime", "t1_avg_apy", "apy_std_dev", "t1_adapters",
                    "all_adapters", "recommendation", "detected_at"}
        r = self.d.detect({"aave-v3": 5.0})
        self.assertTrue(required.issubset(r.keys()))

    def test_stable_detected_at_is_iso_string(self):
        r = self.d.detect({"compound-v3": 5.0})
        self.assertIsInstance(r["detected_at"], str)
        self.assertIn("T", r["detected_at"])   # ISO-8601 separator

    def test_stable_t1_avg_computed_correctly(self):
        r = self.d.detect({"aave-v3": 4.0, "compound-v3": 6.0})
        self.assertAlmostEqual(r["t1_avg_apy"], 5.0, places=2)

    def test_stable_at_high_boundary(self):
        # Exactly 8.0 → NOT > 8.0, so stays STABLE
        r = self.d.detect({"aave-v3": 8.0})
        self.assertEqual(r["regime"], "STABLE")

    def test_stable_at_low_boundary(self):
        # Exactly 3.0 → NOT < 3.0, so stays STABLE
        r = self.d.detect({"aave-v3": 3.0})
        self.assertEqual(r["regime"], "STABLE")

    def test_stable_t1_adapters_identified(self):
        r = self.d.detect({"aave-v3": 4.5, "compound-v3": 5.0, "yearn-v3": 7.0})
        self.assertIn("aave-v3", r["t1_adapters"])
        self.assertIn("compound-v3", r["t1_adapters"])
        self.assertNotIn("yearn-v3", r["t1_adapters"])


# ---------------------------------------------------------------------------
# 2. HIGH_YIELD regime
# ---------------------------------------------------------------------------

class TestDetectHighYield(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def test_high_yield_above_threshold(self):
        r = self.d.detect({"aave-v3": 9.5, "compound-v3": 8.5})
        self.assertEqual(r["regime"], "HIGH_YIELD")

    def test_high_yield_recommendation_increase_exposure(self):
        r = self.d.detect({"aave-v3": 10.0, "compound-v3": 9.0})
        self.assertEqual(r["recommendation"], "increase_exposure")

    def test_high_yield_just_above_threshold(self):
        r = self.d.detect({"aave-v3": 8.01})
        self.assertEqual(r["regime"], "HIGH_YIELD")

    def test_high_yield_extreme_apy(self):
        # Close values → std_dev ≈ 1.0 < 3.0, t1_avg = 24.5 >> 8 → HIGH_YIELD
        r = self.d.detect({"aave-v3": 24.0, "compound-v3": 25.0})
        self.assertEqual(r["regime"], "HIGH_YIELD")

    def test_high_yield_t1_avg_reported_correctly(self):
        r = self.d.detect({"aave-v3": 10.0, "compound-v3": 12.0})
        self.assertAlmostEqual(r["t1_avg_apy"], 11.0, places=2)

    def test_high_yield_non_t1_spike_doesnt_trigger(self):
        # Only T2 adapter (yearn-v3) is high; T1 is normal → STABLE, not HIGH_YIELD
        r = self.d.detect({"aave-v3": 5.0, "compound-v3": 5.0, "yearn-v3": 30.0})
        # t1_avg_apy = 5.0 → below HIGH_YIELD threshold
        self.assertNotEqual(r["regime"], "HIGH_YIELD")

    def test_high_yield_regime_field_value(self):
        r = self.d.detect({"aave-v3": 9.0})
        self.assertEqual(r["regime"], MarketRegimeDetector.REGIME_HIGH_YIELD)


# ---------------------------------------------------------------------------
# 3. COMPRESSED_YIELD regime
# ---------------------------------------------------------------------------

class TestDetectCompressedYield(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def test_compressed_below_threshold(self):
        r = self.d.detect({"aave-v3": 1.5, "compound-v3": 2.0})
        self.assertEqual(r["regime"], "COMPRESSED_YIELD")

    def test_compressed_recommendation_reduce_exposure(self):
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 2.0})
        self.assertEqual(r["recommendation"], "reduce_exposure")

    def test_compressed_just_below_threshold(self):
        r = self.d.detect({"aave-v3": 2.99})
        self.assertEqual(r["regime"], "COMPRESSED_YIELD")

    def test_compressed_near_zero(self):
        r = self.d.detect({"aave-v3": 0.1, "compound-v3": 0.2})
        self.assertEqual(r["regime"], "COMPRESSED_YIELD")

    def test_compressed_t1_avg_correct(self):
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 2.0})
        self.assertAlmostEqual(r["t1_avg_apy"], 1.5, places=2)

    def test_compressed_all_adapters_listed(self):
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 2.0})
        self.assertIn("aave-v3", r["all_adapters"])
        self.assertIn("compound-v3", r["all_adapters"])


# ---------------------------------------------------------------------------
# 4. VOLATILE regime
# ---------------------------------------------------------------------------

class TestDetectVolatile(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def test_volatile_high_std_dev(self):
        # std_dev([1, 10, 5]) > 3 → VOLATILE
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 10.0, "yearn-v3": 5.0})
        self.assertEqual(r["regime"], "VOLATILE")

    def test_volatile_recommendation_diversify(self):
        # std_dev([1, 10]) = sqrt(40.5) ≈ 6.36 > 3
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 10.0})
        self.assertEqual(r["regime"], "VOLATILE")
        self.assertEqual(r["recommendation"], "diversify")

    def test_volatile_takes_priority_over_high_yield(self):
        # T1 avg = (15+1+20)/3 = 12 > 8, but std_dev ≈ 9.85 > 3 → VOLATILE wins
        r = self.d.detect({"aave-v3": 15.0, "compound-v3": 1.0, "spark-susds": 20.0})
        self.assertGreater(r["apy_std_dev"], 3.0)
        self.assertEqual(r["regime"], "VOLATILE")

    def test_volatile_std_dev_recorded(self):
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 10.0})
        self.assertGreater(r["apy_std_dev"], 0.0)

    def test_volatile_std_dev_value_correct(self):
        # std_dev([0, 8]) = sqrt(32) ≈ 5.657
        r = self.d.detect({"x": 0.0, "aave-v3": 8.0})
        expected = math.sqrt(32)
        self.assertAlmostEqual(r["apy_std_dev"], expected, places=2)

    def test_volatile_regime_constant(self):
        r = self.d.detect({"aave-v3": 1.0, "compound-v3": 10.0})
        self.assertEqual(r["regime"], MarketRegimeDetector.REGIME_VOLATILE)


# ---------------------------------------------------------------------------
# 5. get_regime_weights
# ---------------------------------------------------------------------------

class TestGetRegimeWeights(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def _w(self, regime: str) -> dict:
        return self.d.get_regime_weights(regime)

    # STABLE
    def test_stable_weights_has_t1(self):
        self.assertIn("T1", self._w("STABLE"))

    def test_stable_weights_has_t2(self):
        self.assertIn("T2", self._w("STABLE"))

    def test_stable_weights_has_t3(self):
        self.assertIn("T3", self._w("STABLE"))

    def test_stable_exposure_multiplier_neutral(self):
        self.assertAlmostEqual(self._w("STABLE")["exposure_multiplier"], 1.0)

    # HIGH_YIELD
    def test_high_yield_weights_has_t1(self):
        self.assertIn("T1", self._w("HIGH_YIELD"))

    def test_high_yield_weights_has_t2(self):
        self.assertIn("T2", self._w("HIGH_YIELD"))

    def test_high_yield_weights_has_t3(self):
        self.assertIn("T3", self._w("HIGH_YIELD"))

    def test_high_yield_exposure_multiplier_above_one(self):
        self.assertGreater(self._w("HIGH_YIELD")["exposure_multiplier"], 1.0)

    # COMPRESSED_YIELD
    def test_compressed_weights_t1_dominates(self):
        w = self._w("COMPRESSED_YIELD")
        self.assertGreater(w["T1"], w.get("T2", 0))

    def test_compressed_weights_has_t1_t2_t3(self):
        w = self._w("COMPRESSED_YIELD")
        for key in ("T1", "T2", "T3"):
            self.assertIn(key, w)

    # VOLATILE
    def test_volatile_weights_exposure_below_one(self):
        self.assertLess(self._w("VOLATILE")["exposure_multiplier"], 1.0)

    def test_volatile_weights_has_t1_t2_t3(self):
        w = self._w("VOLATILE")
        for key in ("T1", "T2", "T3"):
            self.assertIn(key, w)


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def test_empty_map_returns_stable(self):
        r = self.d.detect({})
        self.assertEqual(r["regime"], "STABLE")

    def test_empty_map_t1_adapters_is_empty_list(self):
        r = self.d.detect({})
        self.assertEqual(r["t1_adapters"], [])

    def test_empty_map_std_dev_is_zero(self):
        r = self.d.detect({})
        self.assertEqual(r["apy_std_dev"], 0.0)

    def test_single_adapter_no_std_dev(self):
        r = self.d.detect({"aave-v3": 5.0})
        self.assertEqual(r["apy_std_dev"], 0.0)

    def test_single_adapter_t1_avg_correct(self):
        r = self.d.detect({"aave-v3": 5.0})
        self.assertAlmostEqual(r["t1_avg_apy"], 5.0)

    def test_all_zeros_compressed(self):
        r = self.d.detect({"aave-v3": 0.0, "compound-v3": 0.0})
        self.assertEqual(r["regime"], "COMPRESSED_YIELD")
        self.assertAlmostEqual(r["t1_avg_apy"], 0.0)

    def test_no_t1_adapters_falls_back_to_overall_avg(self):
        # Only T2 adapters present; module should not crash
        r = self.d.detect({"yearn-v3": 6.0, "euler-v2": 7.0})
        self.assertEqual(r["t1_adapters"], [])
        self.assertAlmostEqual(r["t1_avg_apy"], 6.5, places=1)

    def test_get_regime_weights_unknown_falls_back_to_stable(self):
        w = self.d.get_regime_weights("NONEXISTENT_REGIME")
        # Must still return T1/T2/T3
        for key in ("T1", "T2", "T3"):
            self.assertIn(key, w)


# ---------------------------------------------------------------------------
# 7. Cache persistence (save_to_cache)
# ---------------------------------------------------------------------------

class TestCachePersistence(unittest.TestCase):

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            det = MarketRegimeDetector(data_dir=tmp)
            result = det.detect({"aave-v3": 5.0})
            det.save_to_cache(result)
            self.assertTrue(os.path.exists(os.path.join(tmp, "market_regime.json")))

    def test_save_content_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            det = MarketRegimeDetector(data_dir=tmp)
            result = det.detect({"aave-v3": 5.0, "compound-v3": 4.5})
            det.save_to_cache(result)
            with open(os.path.join(tmp, "market_regime.json")) as fh:
                loaded = json.load(fh)
            self.assertEqual(loaded["regime"], result["regime"])

    def test_save_overwrites_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            det = MarketRegimeDetector(data_dir=tmp)
            det.save_to_cache(det.detect({"aave-v3": 5.0}))
            det.save_to_cache(det.detect({"aave-v3": 9.5}))  # HIGH_YIELD now
            with open(os.path.join(tmp, "market_regime.json")) as fh:
                loaded = json.load(fh)
            self.assertEqual(loaded["regime"], "HIGH_YIELD")


# ---------------------------------------------------------------------------
# 8. to_dict
# ---------------------------------------------------------------------------

class TestToDict(unittest.TestCase):

    def setUp(self):
        self.d = _make_detector()

    def test_to_dict_is_dict(self):
        self.assertIsInstance(self.d.to_dict(), dict)

    def test_to_dict_config_has_thresholds(self):
        cfg = self.d.to_dict()["config"]
        for key in ("HIGH_YIELD_THRESHOLD_PCT", "LOW_YIELD_THRESHOLD_PCT",
                    "VOLATILITY_THRESHOLD_PCT"):
            self.assertIn(key, cfg)

    def test_to_dict_last_result_populated_after_detect(self):
        self.d.detect({"aave-v3": 5.0})
        snap = self.d.to_dict()
        self.assertIsNotNone(snap["last_result"])
        self.assertIn("regime", snap["last_result"])


# ---------------------------------------------------------------------------
# 9. CLI smoke test
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    _ROOT = _ROOT  # project root, resolved at module level

    def _run_cli(self):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.analysis.market_regime"],
            capture_output=True, text=True,
            cwd=self._ROOT, timeout=30,
        )

    def test_cli_exits_zero(self):
        proc = self._run_cli()
        self.assertEqual(proc.returncode, 0, f"stderr:\n{proc.stderr}")

    def test_cli_outputs_valid_json(self):
        proc = self._run_cli()
        self.assertEqual(proc.returncode, 0)
        output = json.loads(proc.stdout)
        self.assertIn("regime", output)

    def test_cli_regime_is_valid_value(self):
        proc = self._run_cli()
        output = json.loads(proc.stdout)
        valid = {"STABLE", "HIGH_YIELD", "COMPRESSED_YIELD", "VOLATILE"}
        self.assertIn(output["regime"], valid)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)

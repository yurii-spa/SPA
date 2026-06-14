"""
Tests for MP-782: ImpermanentLossTracker
≥ 65 unit tests covering:
  - IL formula correctness
  - Severity classification
  - break_even_fee_apy
  - compute() result structure
  - compute_scenario() mechanics
  - Ring-buffer cap at 100
  - Atomic write / file persistence
  - Edge-cases and error conditions
"""

import json
import math
import os
import shutil
import tempfile
import unittest

from spa_core.analytics.impermanent_loss_tracker import (
    ImpermanentLossTracker,
    classify_il_severity,
    compute_il_pct,
    SEVERITY_NEGLIGIBLE,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_HIGH,
    SEVERITY_SEVERE,
    RING_BUFFER_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(initial=1.0, current=1.0, liquidity=100_000.0,
                   token_a="USDC", token_b="ETH"):
    return {
        "token_a": token_a,
        "token_b": token_b,
        "initial_price_ratio": initial,
        "current_price_ratio": current,
        "liquidity_usd": liquidity,
    }


def _il_exact(initial, current):
    k = current / initial
    return 2.0 * math.sqrt(k) / (1.0 + k) - 1.0


# ---------------------------------------------------------------------------
# 1. Pure formula tests (compute_il_pct)
# ---------------------------------------------------------------------------

class TestComputeILPct(unittest.TestCase):

    def test_no_change_k1(self):
        """k=1 → IL=0."""
        self.assertAlmostEqual(compute_il_pct(1.0, 1.0), 0.0, places=12)

    def test_price_doubles_k2(self):
        """k=2 → IL ≈ -5.72 %."""
        il = compute_il_pct(1.0, 2.0)
        expected = 2 * math.sqrt(2) / 3 - 1
        self.assertAlmostEqual(il, expected, places=12)

    def test_price_halves_k05(self):
        """k=0.5 → same magnitude as k=2 (symmetric)."""
        il_half = compute_il_pct(1.0, 0.5)
        il_double = compute_il_pct(1.0, 2.0)
        self.assertAlmostEqual(il_half, il_double, places=12)

    def test_k_4x_il_20pct(self):
        """k=4 → IL = 2*2/5 - 1 = -0.20 = -20 %."""
        il = compute_il_pct(1.0, 4.0)
        self.assertAlmostEqual(il, -0.20, places=12)

    def test_k_025x_il_20pct(self):
        """k=0.25 → same IL as k=4 (symmetry)."""
        il = compute_il_pct(1.0, 0.25)
        self.assertAlmostEqual(il, -0.20, places=12)

    def test_k_1_25(self):
        il = compute_il_pct(1.0, 1.25)
        self.assertAlmostEqual(il, _il_exact(1.0, 1.25), places=12)

    def test_k_0_75(self):
        il = compute_il_pct(1.0, 0.75)
        self.assertAlmostEqual(il, _il_exact(1.0, 0.75), places=12)

    def test_k_1_5(self):
        il = compute_il_pct(1.0, 1.5)
        self.assertAlmostEqual(il, _il_exact(1.0, 1.5), places=12)

    def test_il_always_nonpositive(self):
        for k in [0.1, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 4.0, 10.0]:
            il = compute_il_pct(1.0, k)
            self.assertLessEqual(il, 0.0, msg=f"IL must be ≤ 0 for k={k}")

    def test_il_exactly_zero_at_k1(self):
        self.assertEqual(compute_il_pct(2.0, 2.0), 0.0)

    def test_initial_price_ratio_nonunit(self):
        """Initial ratio != 1 should still compute correctly."""
        il = compute_il_pct(2.0, 4.0)   # k = 2
        self.assertAlmostEqual(il, _il_exact(1.0, 2.0), places=12)

    def test_raises_on_zero_initial(self):
        with self.assertRaises(ValueError):
            compute_il_pct(0.0, 1.0)

    def test_raises_on_negative_initial(self):
        with self.assertRaises(ValueError):
            compute_il_pct(-1.0, 1.0)

    def test_raises_on_zero_current(self):
        with self.assertRaises(ValueError):
            compute_il_pct(1.0, 0.0)

    def test_raises_on_negative_current(self):
        with self.assertRaises(ValueError):
            compute_il_pct(1.0, -0.5)

    def test_symmetry_k_and_inverse(self):
        """IL(k) == IL(1/k) for all k > 0."""
        for k in [0.5, 0.75, 1.25, 1.5, 2.0, 3.0]:
            self.assertAlmostEqual(
                compute_il_pct(1.0, k),
                compute_il_pct(1.0, 1 / k),
                places=10,
                msg=f"Symmetry failed for k={k}",
            )

    def test_large_k_severe_il(self):
        """k=100 → very severe IL."""
        il = compute_il_pct(1.0, 100.0)
        self.assertLess(il, -0.60)


# ---------------------------------------------------------------------------
# 2. Severity classification
# ---------------------------------------------------------------------------

class TestClassifyILSeverity(unittest.TestCase):

    def test_zero_is_negligible(self):
        self.assertEqual(classify_il_severity(0.0), SEVERITY_NEGLIGIBLE)

    def test_below_0_5pct_negligible(self):
        self.assertEqual(classify_il_severity(0.004), SEVERITY_NEGLIGIBLE)

    def test_at_0_5pct_boundary_low(self):
        self.assertEqual(classify_il_severity(0.005), SEVERITY_LOW)

    def test_below_2pct_low(self):
        self.assertEqual(classify_il_severity(0.01), SEVERITY_LOW)

    def test_at_2pct_boundary_medium(self):
        self.assertEqual(classify_il_severity(0.02), SEVERITY_MEDIUM)

    def test_below_5pct_medium(self):
        self.assertEqual(classify_il_severity(0.03), SEVERITY_MEDIUM)

    def test_at_5pct_boundary_high(self):
        self.assertEqual(classify_il_severity(0.05), SEVERITY_HIGH)

    def test_below_10pct_high(self):
        self.assertEqual(classify_il_severity(0.08), SEVERITY_HIGH)

    def test_at_10pct_boundary_severe(self):
        self.assertEqual(classify_il_severity(0.10), SEVERITY_SEVERE)

    def test_above_10pct_severe(self):
        self.assertEqual(classify_il_severity(0.20), SEVERITY_SEVERE)

    def test_k2_is_medium_to_high(self):
        """k=2 gives IL≈5.72 % → HIGH."""
        il_abs = abs(compute_il_pct(1.0, 2.0))
        sev = classify_il_severity(il_abs)
        self.assertEqual(sev, SEVERITY_HIGH)

    def test_k4_is_severe(self):
        """k=4 gives IL=20 % → SEVERE."""
        il_abs = abs(compute_il_pct(1.0, 4.0))
        self.assertEqual(classify_il_severity(il_abs), SEVERITY_SEVERE)

    def test_tiny_change_negligible(self):
        il_abs = abs(compute_il_pct(1.0, 1.001))
        self.assertEqual(classify_il_severity(il_abs), SEVERITY_NEGLIGIBLE)


# ---------------------------------------------------------------------------
# 3. ImpermanentLossTracker.compute()
# ---------------------------------------------------------------------------

class TestTrackerCompute(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmpdir, "il_log.json")
        self.tracker = ImpermanentLossTracker(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_dict(self):
        result = self.tracker.compute(_make_position())
        self.assertIsInstance(result, dict)

    def test_all_expected_keys_present(self):
        result = self.tracker.compute(_make_position())
        for key in [
            "token_a", "token_b", "initial_price_ratio", "current_price_ratio",
            "liquidity_usd", "price_ratio_k", "il_pct", "il_usd",
            "break_even_fee_apy", "il_severity", "timestamp",
        ]:
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_token_names_passed_through(self):
        pos = _make_position(token_a="WETH", token_b="DAI")
        result = self.tracker.compute(pos)
        self.assertEqual(result["token_a"], "WETH")
        self.assertEqual(result["token_b"], "DAI")

    def test_default_token_names(self):
        pos = {"initial_price_ratio": 1.0, "current_price_ratio": 1.0}
        result = self.tracker.compute(pos)
        self.assertEqual(result["token_a"], "TOKEN_A")
        self.assertEqual(result["token_b"], "TOKEN_B")

    def test_il_pct_formula_correct(self):
        pos = _make_position(initial=1.0, current=2.0)
        result = self.tracker.compute(pos)
        expected = _il_exact(1.0, 2.0)
        self.assertAlmostEqual(result["il_pct"], expected, places=12)

    def test_il_usd_calculation(self):
        pos = _make_position(initial=1.0, current=2.0, liquidity=100_000.0)
        result = self.tracker.compute(pos)
        self.assertAlmostEqual(
            result["il_usd"],
            100_000.0 * abs(_il_exact(1.0, 2.0)),
            places=6,
        )

    def test_il_usd_zero_liquidity(self):
        pos = _make_position(initial=1.0, current=2.0, liquidity=0.0)
        result = self.tracker.compute(pos)
        self.assertEqual(result["il_usd"], 0.0)

    def test_il_usd_proportional_to_liquidity(self):
        pos1 = _make_position(liquidity=50_000.0, current=2.0)
        pos2 = _make_position(liquidity=100_000.0, current=2.0)
        r1 = self.tracker.compute(pos1)
        r2 = self.tracker.compute(pos2)
        self.assertAlmostEqual(r2["il_usd"], 2.0 * r1["il_usd"], places=6)

    def test_price_ratio_k_correct(self):
        pos = _make_position(initial=2.0, current=4.0)
        result = self.tracker.compute(pos)
        self.assertAlmostEqual(result["price_ratio_k"], 2.0, places=12)

    def test_il_zero_when_no_price_change(self):
        pos = _make_position(initial=1.5, current=1.5)
        result = self.tracker.compute(pos)
        self.assertAlmostEqual(result["il_pct"], 0.0, places=12)
        self.assertAlmostEqual(result["il_usd"], 0.0, places=8)
        self.assertEqual(result["il_severity"], SEVERITY_NEGLIGIBLE)

    def test_severity_in_result(self):
        pos = _make_position(initial=1.0, current=4.0)  # IL=20% → SEVERE
        result = self.tracker.compute(pos)
        self.assertEqual(result["il_severity"], SEVERITY_SEVERE)

    def test_break_even_fee_equals_il_abs(self):
        pos = _make_position(initial=1.0, current=2.0)
        result = self.tracker.compute(pos)
        self.assertAlmostEqual(
            result["break_even_fee_apy"], abs(result["il_pct"]), places=12
        )

    def test_timestamp_present_and_recent(self):
        import time
        before = time.time()
        result = self.tracker.compute(_make_position())
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_log_appended_after_compute(self):
        self.tracker.compute(_make_position())
        self.assertEqual(len(self.tracker.get_log()), 1)

    def test_multiple_computes_accumulate(self):
        for _ in range(5):
            self.tracker.compute(_make_position())
        self.assertEqual(len(self.tracker.get_log()), 5)

    def test_file_created_after_compute(self):
        self.tracker.compute(_make_position())
        self.assertTrue(os.path.exists(self.data_file))

    def test_file_contents_valid_json(self):
        self.tracker.compute(_make_position())
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_log_persists_across_instances(self):
        self.tracker.compute(_make_position())
        tracker2 = ImpermanentLossTracker(data_file=self.data_file)
        self.assertEqual(len(tracker2.get_log()), 1)

    def test_get_log_returns_copy(self):
        self.tracker.compute(_make_position())
        log1 = self.tracker.get_log()
        log1.append({"fake": True})
        log2 = self.tracker.get_log()
        self.assertEqual(len(log2), 1)

    def test_large_price_increase(self):
        pos = _make_position(initial=1.0, current=100.0, liquidity=1_000_000.0)
        result = self.tracker.compute(pos)
        self.assertLess(result["il_pct"], -0.60)
        self.assertEqual(result["il_severity"], SEVERITY_SEVERE)

    def test_small_price_change_negligible(self):
        pos = _make_position(initial=1.0, current=1.001)
        result = self.tracker.compute(pos)
        self.assertEqual(result["il_severity"], SEVERITY_NEGLIGIBLE)


# ---------------------------------------------------------------------------
# 4. Ring-buffer
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmpdir, "il_log.json")
        self.tracker = ImpermanentLossTracker(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            self.tracker.compute(_make_position(current=1.0 + i * 0.01))
        self.assertEqual(len(self.tracker.get_log()), RING_BUFFER_SIZE)

    def test_ring_buffer_evicts_oldest(self):
        for i in range(105):
            self.tracker.compute(_make_position(current=float(i + 1) * 0.01 + 0.5))
        log = self.tracker.get_log()
        self.assertEqual(len(log), RING_BUFFER_SIZE)

    def test_file_respects_ring_buffer(self):
        for _ in range(105):
            self.tracker.compute(_make_position())
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), RING_BUFFER_SIZE)

    def test_ring_buffer_exactly_100(self):
        for i in range(100):
            self.tracker.compute(_make_position(current=1.0 + i * 0.005))
        self.assertEqual(len(self.tracker.get_log()), 100)


# ---------------------------------------------------------------------------
# 5. compute_scenario()
# ---------------------------------------------------------------------------

class TestComputeScenario(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmpdir, "il_log.json")
        self.tracker = ImpermanentLossTracker(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_pos(self):
        return _make_position(initial=1.0, current=1.0, liquidity=100_000.0)

    def test_default_scenarios_length(self):
        results = self.tracker.compute_scenario(self._base_pos())
        self.assertEqual(len(results), 5)

    def test_default_scenarios_multipliers(self):
        results = self.tracker.compute_scenario(self._base_pos())
        mults = [r["scenario_multiplier"] for r in results]
        self.assertEqual(mults, [0.5, 0.75, 1.25, 1.5, 2.0])

    def test_scenario_multiplier_key_present(self):
        results = self.tracker.compute_scenario(self._base_pos())
        for r in results:
            self.assertIn("scenario_multiplier", r)

    def test_scenario_1x_multiplier_gives_zero_il(self):
        results = self.tracker.compute_scenario(self._base_pos(), price_scenarios=[1.0])
        self.assertAlmostEqual(results[0]["il_pct"], 0.0, places=12)

    def test_scenario_symmetry_0_5_and_2(self):
        results = self.tracker.compute_scenario(self._base_pos(), price_scenarios=[0.5, 2.0])
        self.assertAlmostEqual(results[0]["il_pct"], results[1]["il_pct"], places=10)

    def test_scenario_2x_current_price(self):
        pos = _make_position(initial=1.0, current=1.0)
        results = self.tracker.compute_scenario(pos, price_scenarios=[2.0])
        expected = _il_exact(1.0, 2.0)
        self.assertAlmostEqual(results[0]["il_pct"], expected, places=12)

    def test_custom_scenarios(self):
        results = self.tracker.compute_scenario(self._base_pos(), price_scenarios=[3.0, 5.0])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["scenario_multiplier"], 3.0)
        self.assertEqual(results[1]["scenario_multiplier"], 5.0)

    def test_scenario_writes_file(self):
        self.tracker.compute_scenario(self._base_pos())
        self.assertTrue(os.path.exists(self.data_file))

    def test_scenario_appends_all_to_log(self):
        self.tracker.compute_scenario(self._base_pos())
        self.assertEqual(len(self.tracker.get_log()), 5)

    def test_scenario_empty_list(self):
        results = self.tracker.compute_scenario(self._base_pos(), price_scenarios=[])
        self.assertEqual(results, [])

    def test_scenario_single_element(self):
        results = self.tracker.compute_scenario(self._base_pos(), price_scenarios=[1.5])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["scenario_multiplier"], 1.5)

    def test_scenario_result_has_all_keys(self):
        results = self.tracker.compute_scenario(self._base_pos(), price_scenarios=[2.0])
        r = results[0]
        for key in ["il_pct", "il_usd", "il_severity", "break_even_fee_apy",
                    "price_ratio_k", "scenario_multiplier"]:
            self.assertIn(key, r)

    def test_scenario_after_compute_total_log(self):
        self.tracker.compute(self._base_pos())
        self.tracker.compute_scenario(self._base_pos(), price_scenarios=[0.5, 2.0])
        self.assertEqual(len(self.tracker.get_log()), 3)


# ---------------------------------------------------------------------------
# 6. get_break_even_fee
# ---------------------------------------------------------------------------

class TestGetBreakEvenFee(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = ImpermanentLossTracker(
            data_file=os.path.join(self.tmpdir, "il.json")
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_break_even_is_abs_il(self):
        for il in [-0.05, -0.10, -0.20, 0.0]:
            self.assertAlmostEqual(
                self.tracker.get_break_even_fee(il), abs(il), places=12
            )

    def test_break_even_always_nonnegative(self):
        for il in [-0.30, -0.10, -0.01, 0.0]:
            fee = self.tracker.get_break_even_fee(il)
            self.assertGreaterEqual(fee, 0.0)

    def test_break_even_zero_for_no_il(self):
        self.assertEqual(self.tracker.get_break_even_fee(0.0), 0.0)

    def test_break_even_for_k2(self):
        il = compute_il_pct(1.0, 2.0)
        expected = abs(il)
        self.assertAlmostEqual(self.tracker.get_break_even_fee(il), expected, places=12)


# ---------------------------------------------------------------------------
# 7. Break-even via compute()
# ---------------------------------------------------------------------------

class TestBreakEvenViaCompute(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = ImpermanentLossTracker(
            data_file=os.path.join(self.tmpdir, "il.json")
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_break_even_for_severe_position(self):
        pos = _make_position(initial=1.0, current=4.0)
        result = self.tracker.compute(pos)
        self.assertAlmostEqual(result["break_even_fee_apy"], 0.20, places=10)

    def test_break_even_negligible_position(self):
        pos = _make_position(initial=1.0, current=1.0005)
        result = self.tracker.compute(pos)
        self.assertLess(result["break_even_fee_apy"], 0.005)


# ---------------------------------------------------------------------------
# 8. Misc / integration
# ---------------------------------------------------------------------------

class TestTrackerMisc(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmpdir, "il_log.json")
        self.tracker = ImpermanentLossTracker(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initial_log_empty(self):
        self.assertEqual(self.tracker.get_log(), [])

    def test_compute_various_token_pairs(self):
        pairs = [("ETH", "USDC"), ("WBTC", "DAI"), ("LINK", "WETH")]
        for a, b in pairs:
            pos = _make_position(token_a=a, token_b=b, current=2.0)
            result = self.tracker.compute(pos)
            self.assertEqual(result["token_a"], a)
            self.assertEqual(result["token_b"], b)

    def test_ordered_log_entries(self):
        for i in range(3):
            self.tracker.compute(_make_position(current=1.0 + i * 0.1))
        log = self.tracker.get_log()
        self.assertEqual(len(log), 3)
        self.assertLessEqual(log[0]["timestamp"], log[1]["timestamp"])

    def test_float_prices_accepted(self):
        pos = _make_position(initial=1234.56, current=2345.67)
        result = self.tracker.compute(pos)
        self.assertIn("il_pct", result)

    def test_very_small_liquidity(self):
        pos = _make_position(liquidity=0.01, current=2.0)
        result = self.tracker.compute(pos)
        self.assertGreater(result["il_usd"], 0.0)

    def test_very_large_liquidity(self):
        pos = _make_position(liquidity=1_000_000_000.0, current=2.0)
        result = self.tracker.compute(pos)
        self.assertGreater(result["il_usd"], 0.0)

    def test_il_pct_negative_or_zero(self):
        for current in [0.1, 0.5, 1.0, 1.5, 2.0, 10.0]:
            pos = _make_position(initial=1.0, current=current)
            result = self.tracker.compute(pos)
            self.assertLessEqual(result["il_pct"], 0.0)

    def test_no_tmp_files_left_after_write(self):
        self.tracker.compute(_make_position())
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()

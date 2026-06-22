"""
Tests for MP-1098: DeFiProtocolLiquidityBootstrappingPoolAnalyzer
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_liquidity_bootstrapping_pool_analyzer
Target: ≥ 110 tests
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_liquidity_bootstrapping_pool_analyzer import (
    DeFiProtocolLiquidityBootstrappingPoolAnalyzer,
    _atomic_write,
    _load_log,
    _append_log,
    _validate_inputs,
    _compute_progress_pct,
    _compute_current_weight_pct,
    _compute_price_vs_fair_value_pct,
    _compute_volume_to_liquidity_ratio,
    _compute_lbp_label,
    _compute_opportunity_score,
    _analyze,
    LABEL_WAIT_FOR_LOWER,
    LABEL_APPROACHING_FV,
    LABEL_NEAR_FAIR_VALUE,
    LABEL_BELOW_FV_BUY,
    LABEL_PANIC_SELL_OPPORTUNITY,
)

# ── Shared helper ─────────────────────────────────────────────────────────────

def _default_kwargs(**overrides):
    """Return a complete set of valid keyword arguments."""
    base = dict(
        start_weight_token_pct=96.0,
        end_weight_token_pct=50.0,
        start_price_usd=10.0,
        current_price_usd=7.0,
        fair_value_estimate_usd=5.0,
        elapsed_hours=24.0,
        total_duration_hours=72.0,
        total_liquidity_usd=500_000.0,
        volume_24h_usd=50_000.0,
        protocol_name="TestDAO",
    )
    base.update(overrides)
    return base


# ── 1. Label constants ────────────────────────────────────────────────────────

class TestLabelConstants(unittest.TestCase):

    def test_wait_for_lower_value(self):
        self.assertEqual(LABEL_WAIT_FOR_LOWER, "WAIT_FOR_LOWER")

    def test_approaching_fv_value(self):
        self.assertEqual(LABEL_APPROACHING_FV, "APPROACHING_FV")

    def test_near_fair_value_value(self):
        self.assertEqual(LABEL_NEAR_FAIR_VALUE, "NEAR_FAIR_VALUE")

    def test_below_fv_buy_value(self):
        self.assertEqual(LABEL_BELOW_FV_BUY, "BELOW_FV_BUY")

    def test_panic_sell_opportunity_value(self):
        self.assertEqual(LABEL_PANIC_SELL_OPPORTUNITY, "PANIC_SELL_OPPORTUNITY")

    def test_all_labels_are_strings(self):
        for label in [
            LABEL_WAIT_FOR_LOWER,
            LABEL_APPROACHING_FV,
            LABEL_NEAR_FAIR_VALUE,
            LABEL_BELOW_FV_BUY,
            LABEL_PANIC_SELL_OPPORTUNITY,
        ]:
            self.assertIsInstance(label, str)

    def test_all_labels_are_unique(self):
        labels = [
            LABEL_WAIT_FOR_LOWER,
            LABEL_APPROACHING_FV,
            LABEL_NEAR_FAIR_VALUE,
            LABEL_BELOW_FV_BUY,
            LABEL_PANIC_SELL_OPPORTUNITY,
        ]
        self.assertEqual(len(labels), len(set(labels)))


# ── 2. _compute_progress_pct ──────────────────────────────────────────────────

class TestComputeProgressPct(unittest.TestCase):

    def test_halfway(self):
        self.assertAlmostEqual(_compute_progress_pct(36.0, 72.0), 50.0, places=8)

    def test_zero_elapsed(self):
        self.assertAlmostEqual(_compute_progress_pct(0.0, 72.0), 0.0, places=8)

    def test_full_elapsed(self):
        self.assertAlmostEqual(_compute_progress_pct(72.0, 72.0), 100.0, places=8)

    def test_over_elapsed_clamped_to_100(self):
        self.assertAlmostEqual(_compute_progress_pct(100.0, 72.0), 100.0, places=8)

    def test_quarter_elapsed(self):
        self.assertAlmostEqual(_compute_progress_pct(18.0, 72.0), 25.0, places=8)

    def test_three_quarters_elapsed(self):
        self.assertAlmostEqual(_compute_progress_pct(54.0, 72.0), 75.0, places=8)

    def test_small_duration(self):
        self.assertAlmostEqual(_compute_progress_pct(1.0, 2.0), 50.0, places=8)

    def test_result_always_between_0_and_100(self):
        for elapsed, total in [(0, 10), (5, 10), (10, 10), (20, 10)]:
            result = _compute_progress_pct(elapsed, total)
            self.assertGreaterEqual(result, 0.0)
            self.assertLessEqual(result, 100.0)


# ── 3. _compute_current_weight_pct ────────────────────────────────────────────

class TestComputeCurrentWeightPct(unittest.TestCase):

    def test_at_start(self):
        self.assertAlmostEqual(
            _compute_current_weight_pct(96.0, 50.0, 0.0), 96.0, places=8
        )

    def test_at_end(self):
        self.assertAlmostEqual(
            _compute_current_weight_pct(96.0, 50.0, 100.0), 50.0, places=8
        )

    def test_at_midpoint(self):
        self.assertAlmostEqual(
            _compute_current_weight_pct(96.0, 50.0, 50.0), 73.0, places=8
        )

    def test_at_quarter(self):
        # 96 + (50-96)*0.25 = 96 - 11.5 = 84.5
        self.assertAlmostEqual(
            _compute_current_weight_pct(96.0, 50.0, 25.0), 84.5, places=8
        )

    def test_increasing_weights(self):
        # Start lower, end higher (unusual but valid input)
        self.assertAlmostEqual(
            _compute_current_weight_pct(20.0, 80.0, 50.0), 50.0, places=8
        )

    def test_equal_weights(self):
        self.assertAlmostEqual(
            _compute_current_weight_pct(50.0, 50.0, 75.0), 50.0, places=8
        )

    def test_full_range_monotone_decreasing(self):
        """Weight should monotonically decrease from start to end for typical LBP."""
        start, end = 96.0, 50.0
        weights = [
            _compute_current_weight_pct(start, end, p) for p in range(0, 101, 10)
        ]
        for i in range(len(weights) - 1):
            self.assertGreaterEqual(weights[i], weights[i + 1])


# ── 4. _compute_price_vs_fair_value_pct ──────────────────────────────────────

class TestComputePriceVsFairValuePct(unittest.TestCase):

    def test_at_fair_value(self):
        self.assertAlmostEqual(
            _compute_price_vs_fair_value_pct(5.0, 5.0), 0.0, places=8
        )

    def test_double_fair_value(self):
        # (10-5)/5 * 100 = 100%
        self.assertAlmostEqual(
            _compute_price_vs_fair_value_pct(10.0, 5.0), 100.0, places=8
        )

    def test_half_fair_value(self):
        # (2.5-5)/5 * 100 = -50%
        self.assertAlmostEqual(
            _compute_price_vs_fair_value_pct(2.5, 5.0), -50.0, places=8
        )

    def test_30_pct_above(self):
        self.assertAlmostEqual(
            _compute_price_vs_fair_value_pct(6.5, 5.0), 30.0, places=6
        )

    def test_30_pct_below(self):
        self.assertAlmostEqual(
            _compute_price_vs_fair_value_pct(3.5, 5.0), -30.0, places=6
        )

    def test_positive_when_above_fv(self):
        result = _compute_price_vs_fair_value_pct(8.0, 5.0)
        self.assertGreater(result, 0.0)

    def test_negative_when_below_fv(self):
        result = _compute_price_vs_fair_value_pct(3.0, 5.0)
        self.assertLess(result, 0.0)

    def test_zero_price(self):
        result = _compute_price_vs_fair_value_pct(0.0, 5.0)
        self.assertAlmostEqual(result, -100.0, places=8)


# ── 5. _compute_volume_to_liquidity_ratio ────────────────────────────────────

class TestComputeVolumeToLiquidityRatio(unittest.TestCase):

    def test_normal_ratio(self):
        self.assertAlmostEqual(
            _compute_volume_to_liquidity_ratio(50_000.0, 500_000.0), 0.1, places=8
        )

    def test_equal(self):
        self.assertAlmostEqual(
            _compute_volume_to_liquidity_ratio(100.0, 100.0), 1.0, places=8
        )

    def test_zero_volume(self):
        self.assertAlmostEqual(
            _compute_volume_to_liquidity_ratio(0.0, 500_000.0), 0.0, places=8
        )

    def test_zero_liquidity(self):
        result = _compute_volume_to_liquidity_ratio(50_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=8)

    def test_volume_greater_than_liquidity(self):
        result = _compute_volume_to_liquidity_ratio(1_000_000.0, 500_000.0)
        self.assertAlmostEqual(result, 2.0, places=8)

    def test_small_values(self):
        self.assertAlmostEqual(
            _compute_volume_to_liquidity_ratio(1.0, 4.0), 0.25, places=8
        )

    def test_both_zero(self):
        result = _compute_volume_to_liquidity_ratio(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=8)


# ── 6. _compute_lbp_label ─────────────────────────────────────────────────────

class TestComputeLbpLabel(unittest.TestCase):

    def test_far_above_fv_wait(self):
        self.assertEqual(_compute_lbp_label(50.0), LABEL_WAIT_FOR_LOWER)

    def test_just_above_30_wait(self):
        self.assertEqual(_compute_lbp_label(30.1), LABEL_WAIT_FOR_LOWER)

    def test_exactly_30_approaching(self):
        # > 30 → WAIT; boundary at exactly 30 → APPROACHING_FV
        self.assertEqual(_compute_lbp_label(30.0), LABEL_APPROACHING_FV)

    def test_20_pct_above_approaching(self):
        self.assertEqual(_compute_lbp_label(20.0), LABEL_APPROACHING_FV)

    def test_just_above_10_approaching(self):
        self.assertEqual(_compute_lbp_label(10.1), LABEL_APPROACHING_FV)

    def test_exactly_10_near_fv(self):
        self.assertEqual(_compute_lbp_label(10.0), LABEL_NEAR_FAIR_VALUE)

    def test_at_fv(self):
        self.assertEqual(_compute_lbp_label(0.0), LABEL_NEAR_FAIR_VALUE)

    def test_slightly_below_fv(self):
        self.assertEqual(_compute_lbp_label(-5.0), LABEL_NEAR_FAIR_VALUE)

    def test_exactly_minus_10_near_fv(self):
        self.assertEqual(_compute_lbp_label(-10.0), LABEL_NEAR_FAIR_VALUE)

    def test_just_below_minus_10_below_fv(self):
        self.assertEqual(_compute_lbp_label(-10.1), LABEL_BELOW_FV_BUY)

    def test_minus_20_below_fv(self):
        self.assertEqual(_compute_lbp_label(-20.0), LABEL_BELOW_FV_BUY)

    def test_exactly_minus_30_below_fv(self):
        self.assertEqual(_compute_lbp_label(-30.0), LABEL_BELOW_FV_BUY)

    def test_just_below_minus_30_panic(self):
        self.assertEqual(_compute_lbp_label(-30.1), LABEL_PANIC_SELL_OPPORTUNITY)

    def test_far_below_fv_panic(self):
        self.assertEqual(_compute_lbp_label(-80.0), LABEL_PANIC_SELL_OPPORTUNITY)


# ── 7. _compute_opportunity_score ────────────────────────────────────────────

class TestComputeOpportunityScore(unittest.TestCase):

    def test_score_is_int(self):
        score = _compute_opportunity_score(0.0, 50.0, 0.1)
        self.assertIsInstance(score, int)

    def test_score_range(self):
        """Score must always be in [0, 100]."""
        for pct in [-50.0, -30.0, -10.0, 0.0, 10.0, 30.0, 50.0]:
            for prog in [0.0, 25.0, 50.0, 75.0, 100.0]:
                for vl in [0.0, 0.1, 0.5, 1.0, 3.0]:
                    score = _compute_opportunity_score(pct, prog, vl)
                    self.assertGreaterEqual(score, 0)
                    self.assertLessEqual(score, 100)

    def test_below_fv_scores_higher_than_above(self):
        score_below = _compute_opportunity_score(-30.0, 50.0, 0.2)
        score_above = _compute_opportunity_score(30.0, 50.0, 0.2)
        self.assertGreater(score_below, score_above)

    def test_more_progress_higher_score_all_else_equal(self):
        score_early = _compute_opportunity_score(0.0, 10.0, 0.1)
        score_late = _compute_opportunity_score(0.0, 90.0, 0.1)
        self.assertGreater(score_late, score_early)

    def test_low_volume_liquidity_moderate_score(self):
        # vol/liq < 0.05 → 5 pts
        s_low = _compute_opportunity_score(0.0, 50.0, 0.01)
        # vol/liq 0.1–0.5 → 15 pts
        s_good = _compute_opportunity_score(0.0, 50.0, 0.2)
        self.assertGreater(s_good, s_low)

    def test_high_vl_ratio_lower_than_moderate(self):
        s_high = _compute_opportunity_score(0.0, 50.0, 5.0)
        s_moderate = _compute_opportunity_score(0.0, 50.0, 0.2)
        self.assertGreater(s_moderate, s_high)

    def test_extreme_below_fv_high_score(self):
        score = _compute_opportunity_score(-50.0, 100.0, 0.3)
        self.assertGreater(score, 60)

    def test_extreme_above_fv_low_score(self):
        score = _compute_opportunity_score(50.0, 0.0, 5.0)
        self.assertLess(score, 30)


# ── 8. _validate_inputs ──────────────────────────────────────────────────────

class TestValidateInputs(unittest.TestCase):

    def _call(self, **overrides):
        kwargs = _default_kwargs(**overrides)
        _validate_inputs(**kwargs)

    def test_valid_inputs_no_error(self):
        self._call()  # should not raise

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            self._call(protocol_name="")

    def test_whitespace_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            self._call(protocol_name="   ")

    def test_start_weight_zero_raises(self):
        with self.assertRaises(ValueError):
            self._call(start_weight_token_pct=0.0)

    def test_start_weight_above_100_raises(self):
        with self.assertRaises(ValueError):
            self._call(start_weight_token_pct=101.0)

    def test_end_weight_zero_raises(self):
        with self.assertRaises(ValueError):
            self._call(end_weight_token_pct=0.0)

    def test_end_weight_above_100_raises(self):
        with self.assertRaises(ValueError):
            self._call(end_weight_token_pct=100.1)

    def test_start_price_zero_raises(self):
        with self.assertRaises(ValueError):
            self._call(start_price_usd=0.0)

    def test_start_price_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(start_price_usd=-1.0)

    def test_current_price_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(current_price_usd=-0.01)

    def test_fair_value_zero_raises(self):
        with self.assertRaises(ValueError):
            self._call(fair_value_estimate_usd=0.0)

    def test_fair_value_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(fair_value_estimate_usd=-5.0)

    def test_elapsed_hours_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(elapsed_hours=-1.0)

    def test_total_duration_zero_raises(self):
        with self.assertRaises(ValueError):
            self._call(total_duration_hours=0.0)

    def test_total_duration_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(total_duration_hours=-10.0)

    def test_total_liquidity_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(total_liquidity_usd=-1.0)

    def test_volume_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(volume_24h_usd=-100.0)

    def test_current_price_zero_ok(self):
        self._call(current_price_usd=0.0)  # edge: token crashed, still valid

    def test_elapsed_zero_ok(self):
        self._call(elapsed_hours=0.0)

    def test_liquidity_zero_ok(self):
        self._call(total_liquidity_usd=0.0)

    def test_volume_zero_ok(self):
        self._call(volume_24h_usd=0.0)

    def test_start_weight_100_ok(self):
        self._call(start_weight_token_pct=100.0)

    def test_end_weight_100_ok(self):
        self._call(end_weight_token_pct=100.0)


# ── 9. _analyze core function ─────────────────────────────────────────────────

class TestAnalyzeFunction(unittest.TestCase):

    def _call(self, **overrides):
        return _analyze(**_default_kwargs(**overrides))

    def test_returns_dict(self):
        self.assertIsInstance(self._call(), dict)

    def test_all_output_keys_present(self):
        result = self._call()
        for key in [
            "protocol_name", "timestamp",
            "start_weight_token_pct", "end_weight_token_pct",
            "start_price_usd", "current_price_usd", "fair_value_estimate_usd",
            "elapsed_hours", "total_duration_hours",
            "total_liquidity_usd", "volume_24h_usd",
            "progress_pct", "current_weight_pct",
            "price_vs_fair_value_pct", "volume_to_liquidity_ratio",
            "lbp_opportunity_score", "lbp_label",
        ]:
            self.assertIn(key, result)

    def test_protocol_name_echoed(self):
        result = self._call(protocol_name="AlphaProtocol")
        self.assertEqual(result["protocol_name"], "AlphaProtocol")

    def test_progress_pct_halfway(self):
        result = self._call(elapsed_hours=36.0, total_duration_hours=72.0)
        self.assertAlmostEqual(result["progress_pct"], 50.0, places=4)

    def test_progress_pct_clamped(self):
        result = self._call(elapsed_hours=200.0, total_duration_hours=72.0)
        self.assertAlmostEqual(result["progress_pct"], 100.0, places=4)

    def test_current_weight_at_start(self):
        result = self._call(elapsed_hours=0.0)
        self.assertAlmostEqual(
            result["current_weight_pct"],
            result["start_weight_token_pct"],
            places=4,
        )

    def test_current_weight_at_end(self):
        result = self._call(elapsed_hours=72.0)
        self.assertAlmostEqual(
            result["current_weight_pct"],
            result["end_weight_token_pct"],
            places=4,
        )

    def test_price_vs_fv_positive_when_above(self):
        result = self._call(current_price_usd=8.0, fair_value_estimate_usd=5.0)
        self.assertGreater(result["price_vs_fair_value_pct"], 0.0)

    def test_price_vs_fv_negative_when_below(self):
        result = self._call(current_price_usd=3.0, fair_value_estimate_usd=5.0)
        self.assertLess(result["price_vs_fair_value_pct"], 0.0)

    def test_price_vs_fv_zero_at_fair_value(self):
        result = self._call(current_price_usd=5.0, fair_value_estimate_usd=5.0)
        self.assertAlmostEqual(result["price_vs_fair_value_pct"], 0.0, places=6)

    def test_volume_to_liquidity_ratio_computed(self):
        result = self._call(volume_24h_usd=100_000.0, total_liquidity_usd=500_000.0)
        self.assertAlmostEqual(result["volume_to_liquidity_ratio"], 0.2, places=6)

    def test_lbp_label_wait_for_lower(self):
        # current = 50% above FV
        result = self._call(current_price_usd=7.5, fair_value_estimate_usd=5.0)
        self.assertEqual(result["lbp_label"], LABEL_WAIT_FOR_LOWER)

    def test_lbp_label_approaching_fv(self):
        # current = 20% above FV
        result = self._call(current_price_usd=6.0, fair_value_estimate_usd=5.0)
        self.assertEqual(result["lbp_label"], LABEL_APPROACHING_FV)

    def test_lbp_label_near_fair_value(self):
        result = self._call(current_price_usd=5.0, fair_value_estimate_usd=5.0)
        self.assertEqual(result["lbp_label"], LABEL_NEAR_FAIR_VALUE)

    def test_lbp_label_below_fv_buy(self):
        # -20% below FV
        result = self._call(current_price_usd=4.0, fair_value_estimate_usd=5.0)
        self.assertEqual(result["lbp_label"], LABEL_BELOW_FV_BUY)

    def test_lbp_label_panic_sell(self):
        # -40% below FV
        result = self._call(current_price_usd=3.0, fair_value_estimate_usd=5.0)
        self.assertEqual(result["lbp_label"], LABEL_PANIC_SELL_OPPORTUNITY)

    def test_opportunity_score_int(self):
        result = self._call()
        self.assertIsInstance(result["lbp_opportunity_score"], int)

    def test_opportunity_score_range(self):
        result = self._call()
        self.assertGreaterEqual(result["lbp_opportunity_score"], 0)
        self.assertLessEqual(result["lbp_opportunity_score"], 100)

    def test_timestamp_present(self):
        result = self._call()
        self.assertIn("T", result["timestamp"])
        self.assertIn("Z", result["timestamp"])

    def test_invalid_raises_from_analyze(self):
        kwargs = _default_kwargs(protocol_name="")
        with self.assertRaises(ValueError):
            _analyze(**kwargs)


# ── 10. Atomic I/O helpers ────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"key": "value"})
            self.assertTrue(os.path.exists(path))

    def test_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [1, 2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"a": 1})
            _atomic_write(path, {"b": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, {"b": 2})

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "dir", "test.json")
            _atomic_write(path, {"x": 42})
            self.assertTrue(os.path.exists(path))

    def test_unicode_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"emoji": "🚀", "text": "Привіт"})
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["emoji"], "🚀")


class TestLoadLog(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nonexistent.json")
            self.assertEqual(_load_log(path), [])

    def test_valid_list_returned(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_write(path, [{"a": 1}, {"b": 2}])
            result = _load_log(path)
            self.assertEqual(result, [{"a": 1}, {"b": 2}])

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as f:
                f.write("NOT JSON {{{")
            self.assertEqual(_load_log(path), [])

    def test_non_list_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_write(path, {"not": "a list"})
            self.assertEqual(_load_log(path), [])

    def test_empty_list_returned(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_write(path, [])
            self.assertEqual(_load_log(path), [])


class TestAppendLog(unittest.TestCase):

    def test_append_to_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(path, {"x": 1})
            self.assertEqual(_load_log(path), [{"x": 1}])

    def test_append_multiple(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(path, {"a": 1})
            _append_log(path, {"b": 2})
            result = _load_log(path)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0], {"a": 1})
            self.assertEqual(result[1], {"b": 2})

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for i in range(110):
                _append_log(path, {"i": i})
            result = _load_log(path)
            self.assertEqual(len(result), 100)
            # Oldest should be removed; last entry is 109
            self.assertEqual(result[-1]["i"], 109)
            self.assertEqual(result[0]["i"], 10)

    def test_ring_buffer_keeps_newest(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for i in range(105):
                _append_log(path, {"seq": i})
            result = _load_log(path)
            seqs = [r["seq"] for r in result]
            self.assertEqual(seqs, list(range(5, 105)))


# ── 11. Class-level integration tests ─────────────────────────────────────────

class TestDeFiProtocolLiquidityBootstrappingPoolAnalyzer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "lbp_log.json")
        self.analyzer = DeFiProtocolLiquidityBootstrappingPoolAnalyzer(
            data_file=self.log_path
        )

    def _run(self, **overrides):
        kwargs = _default_kwargs(**overrides)
        return self.analyzer.analyze(**kwargs)

    def test_analyze_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_analyze_writes_to_log(self):
        self._run()
        self.assertTrue(os.path.exists(self.log_path))

    def test_analyze_log_has_one_entry(self):
        self._run()
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 1)

    def test_analyze_multiple_entries_appended(self):
        self._run()
        self._run()
        self._run()
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 3)

    def test_write_log_false_no_file(self):
        kwargs = _default_kwargs()
        self.analyzer.analyze(**kwargs, write_log=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_result_contains_lbp_label(self):
        result = self._run()
        self.assertIn(
            result["lbp_label"],
            [
                LABEL_WAIT_FOR_LOWER,
                LABEL_APPROACHING_FV,
                LABEL_NEAR_FAIR_VALUE,
                LABEL_BELOW_FV_BUY,
                LABEL_PANIC_SELL_OPPORTUNITY,
            ],
        )

    def test_lbp_full_lifecycle_labels(self):
        """Simulate a typical LBP: price drops from 3x FV to 0.5x FV."""
        scenarios = [
            (15.0, 5.0, LABEL_WAIT_FOR_LOWER),   # 200% above FV
            (6.5, 5.0, LABEL_APPROACHING_FV),      # 30% above FV
            (5.0, 5.0, LABEL_NEAR_FAIR_VALUE),     # at FV
            (4.0, 5.0, LABEL_BELOW_FV_BUY),        # 20% below FV
            (3.0, 5.0, LABEL_PANIC_SELL_OPPORTUNITY),  # 40% below FV
        ]
        for current, fv, expected_label in scenarios:
            with self.subTest(current=current, fv=fv):
                result = self.analyzer.analyze(
                    **_default_kwargs(
                        current_price_usd=current,
                        fair_value_estimate_usd=fv,
                        write_log=False,
                    )
                )
                self.assertEqual(result["lbp_label"], expected_label)

    def test_ring_buffer_enforced_via_class(self):
        for i in range(105):
            self._run(protocol_name=f"Proto{i}")
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 100)

    def test_default_data_file_path(self):
        a = DeFiProtocolLiquidityBootstrappingPoolAnalyzer()
        self.assertIn("liquidity_bootstrapping_pool_log.json", a.data_file)

    def test_custom_data_file_path(self):
        custom = os.path.join(self.tmpdir, "custom.json")
        a = DeFiProtocolLiquidityBootstrappingPoolAnalyzer(data_file=custom)
        a.analyze(**_default_kwargs())
        self.assertTrue(os.path.exists(custom))

    def test_raises_on_invalid_input(self):
        with self.assertRaises(ValueError):
            self._run(start_price_usd=0.0)

    def test_elapsed_at_zero_progress(self):
        result = self._run(elapsed_hours=0.0)
        self.assertAlmostEqual(result["progress_pct"], 0.0, places=4)

    def test_elapsed_beyond_duration_clamped(self):
        result = self._run(elapsed_hours=1000.0, total_duration_hours=72.0)
        self.assertAlmostEqual(result["progress_pct"], 100.0, places=4)

    def test_score_is_int_type(self):
        result = self._run()
        self.assertIsInstance(result["lbp_opportunity_score"], int)

    def test_vlr_zero_when_liquidity_zero(self):
        result = self._run(total_liquidity_usd=0.0, volume_24h_usd=50_000.0)
        self.assertAlmostEqual(result["volume_to_liquidity_ratio"], 0.0, places=6)

    def test_log_entry_has_required_fields(self):
        self._run()
        log = _load_log(self.log_path)
        entry = log[0]
        for key in [
            "protocol_name", "timestamp", "progress_pct", "current_weight_pct",
            "price_vs_fair_value_pct", "volume_to_liquidity_ratio",
            "lbp_opportunity_score", "lbp_label",
        ]:
            self.assertIn(key, entry)

    def test_consistent_results_same_input(self):
        """Same inputs should produce same outputs (except timestamp)."""
        r1 = self.analyzer.analyze(**_default_kwargs(), write_log=False)
        r2 = self.analyzer.analyze(**_default_kwargs(), write_log=False)
        for key in [
            "progress_pct", "current_weight_pct", "price_vs_fair_value_pct",
            "volume_to_liquidity_ratio", "lbp_opportunity_score", "lbp_label",
        ]:
            self.assertEqual(r1[key], r2[key])

    def test_price_at_exact_30_pct_boundary(self):
        # price_vs_fv_pct = 30.0 → APPROACHING_FV (not WAIT_FOR_LOWER)
        result = self._run(
            current_price_usd=6.5,
            fair_value_estimate_usd=5.0,
        )
        # 6.5/5 - 1 = 0.30 → 30%
        self.assertAlmostEqual(result["price_vs_fair_value_pct"], 30.0, places=4)
        self.assertEqual(result["lbp_label"], LABEL_APPROACHING_FV)

    def test_high_vl_ratio_scenario(self):
        result = self._run(volume_24h_usd=2_000_000.0, total_liquidity_usd=100_000.0)
        # VL ratio = 20; score should still be in range
        self.assertGreaterEqual(result["lbp_opportunity_score"], 0)
        self.assertLessEqual(result["lbp_opportunity_score"], 100)

    def test_weight_decreasing_during_lbp(self):
        """Token weight should decrease from start to end of LBP."""
        r_start = self._run(elapsed_hours=0.0, write_log=False)
        r_mid = self._run(elapsed_hours=36.0, write_log=False)
        r_end = self._run(elapsed_hours=72.0, write_log=False)
        self.assertGreater(r_start["current_weight_pct"], r_mid["current_weight_pct"])
        self.assertGreater(r_mid["current_weight_pct"], r_end["current_weight_pct"])

    def test_increasing_weight_lbp_unusual_but_valid(self):
        """LBPs that increase weight are unusual but the math should still work."""
        result = self._run(
            start_weight_token_pct=20.0,
            end_weight_token_pct=80.0,
            elapsed_hours=36.0,
            write_log=False,
        )
        self.assertAlmostEqual(result["current_weight_pct"], 50.0, places=4)


# ── 12. Edge and boundary integration tests ───────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "edge_log.json")
        self.analyzer = DeFiProtocolLiquidityBootstrappingPoolAnalyzer(
            data_file=self.log_path
        )

    def test_zero_current_price_panic(self):
        result = self.analyzer.analyze(**_default_kwargs(current_price_usd=0.0))
        # 0 vs FV of 5 → -100% → PANIC_SELL_OPPORTUNITY
        self.assertEqual(result["lbp_label"], LABEL_PANIC_SELL_OPPORTUNITY)

    def test_very_small_fair_value(self):
        result = self.analyzer.analyze(
            **_default_kwargs(
                current_price_usd=0.002,
                fair_value_estimate_usd=0.001,
                start_price_usd=0.01,
            )
        )
        self.assertAlmostEqual(result["price_vs_fair_value_pct"], 100.0, places=4)

    def test_equal_start_end_weight(self):
        result = self.analyzer.analyze(
            **_default_kwargs(
                start_weight_token_pct=50.0,
                end_weight_token_pct=50.0,
                elapsed_hours=36.0,
            )
        )
        self.assertAlmostEqual(result["current_weight_pct"], 50.0, places=4)

    def test_exactly_at_minus_10_boundary(self):
        # price_vs_fv = -10% → NEAR_FAIR_VALUE
        result = self.analyzer.analyze(
            **_default_kwargs(
                current_price_usd=4.5,
                fair_value_estimate_usd=5.0,
            )
        )
        self.assertAlmostEqual(result["price_vs_fair_value_pct"], -10.0, places=4)
        self.assertEqual(result["lbp_label"], LABEL_NEAR_FAIR_VALUE)

    def test_json_serializable_result(self):
        result = self.analyzer.analyze(**_default_kwargs())
        # Should not raise
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)

    def test_large_liquidity_values(self):
        result = self.analyzer.analyze(
            **_default_kwargs(
                total_liquidity_usd=1_000_000_000.0,
                volume_24h_usd=500_000_000.0,
            )
        )
        self.assertAlmostEqual(result["volume_to_liquidity_ratio"], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()

"""
Tests for MP-1201: DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_leveraged_carry_spread_compression_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_leveraged_carry_spread_compression_analyzer import (  # noqa: E501
    DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_borrow_rates,
    _pstdev,
    _derive_leverage,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    STABLE_FRACTION,
    MILD_FRACTION,
    HEAVY_FRACTION,
    HIGH_LEVERAGE,
    NO_LEVERAGE_MAX,
    HIGH_CV,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Loop",
    base_yield_apr_pct=8.0,
    leverage=3.0,
    borrow_rate_samples=None,
    borrow_rate_snapshot_pct=None,
    borrow_rate_realized_pct=None,
    net_apr_headline_pct=None,
    total_exposure_usd=None,
    equity_usd=None,
):
    pos = {"vault": vault}
    if base_yield_apr_pct is not None:
        pos["base_yield_apr_pct"] = base_yield_apr_pct
    if leverage is not None:
        pos["leverage"] = leverage
    if borrow_rate_samples is not None:
        pos["borrow_rate_samples"] = borrow_rate_samples
    if borrow_rate_snapshot_pct is not None:
        pos["borrow_rate_snapshot_pct"] = borrow_rate_snapshot_pct
    if borrow_rate_realized_pct is not None:
        pos["borrow_rate_realized_pct"] = borrow_rate_realized_pct
    if net_apr_headline_pct is not None:
        pos["net_apr_headline_pct"] = net_apr_headline_pct
    if total_exposure_usd is not None:
        pos["total_exposure_usd"] = total_exposure_usd
    if equity_usd is not None:
        pos["equity_usd"] = equity_usd
    return pos


def A():
    return DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid_str(self):
        self.assertEqual(_f("3.5"), 3.5)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)

    def test_f_none_custom_default(self):
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_str(self):
        self.assertEqual(_f("abc"), 0.0)

    def test_f_negative_float(self):
        self.assertEqual(_f(-3.7), -3.7)

    def test_f_int(self):
        self.assertEqual(_f(5), 5.0)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1.0, 0.0, 1.0), 0.0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(2.0, 0.0, 1.0), 1.0)

    def test_clamp_mid(self):
        self.assertEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_safe_div_ok(self):
        self.assertAlmostEqual(_safe_div(6.0, 3.0, None), 2.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(6.0, 0.0, None))

    def test_safe_div_neg_den(self):
        self.assertIsNone(_safe_div(6.0, -2.0, None))

    def test_coerce_num_bool(self):
        self.assertIsNone(_coerce_num(True))

    def test_coerce_num_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_coerce_num_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_coerce_num_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))

    def test_coerce_num_str(self):
        self.assertEqual(_coerce_num("2.5"), 2.5)

    def test_coerce_num_empty_str(self):
        self.assertIsNone(_coerce_num("   "))

    def test_coerce_num_bad_str(self):
        self.assertIsNone(_coerce_num("xyz"))

    def test_coerce_num_int(self):
        self.assertEqual(_coerce_num(4), 4.0)

    def test_coerce_borrow_rates_skips_negative(self):
        self.assertEqual(_coerce_borrow_rates([2.0, -1.0, 3.0]), [2.0, 3.0])

    def test_coerce_borrow_rates_skips_nonnumeric(self):
        self.assertEqual(_coerce_borrow_rates([2.0, "x", None, 3.0]), [2.0, 3.0])

    def test_coerce_borrow_rates_skips_bool(self):
        self.assertEqual(_coerce_borrow_rates([True, 2.0]), [2.0])

    def test_coerce_borrow_rates_empty(self):
        self.assertEqual(_coerce_borrow_rates([]), [])

    def test_coerce_borrow_rates_none(self):
        self.assertEqual(_coerce_borrow_rates(None), [])

    def test_coerce_borrow_rates_zero_allowed(self):
        self.assertEqual(_coerce_borrow_rates([0.0, 1.0]), [0.0, 1.0])

    def test_coerce_borrow_rates_preserves_order(self):
        self.assertEqual(_coerce_borrow_rates([3.0, 1.0, 2.0]), [3.0, 1.0, 2.0])

    def test_pstdev_short(self):
        self.assertEqual(_pstdev([1.0]), 0.0)

    def test_pstdev_constant(self):
        self.assertEqual(_pstdev([2.0, 2.0, 2.0]), 0.0)

    def test_pstdev_values(self):
        self.assertTrue(_pstdev([1.0, 3.0]) > 0.0)

    def test_grade_a(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_score(75), "B")

    def test_grade_c(self):
        self.assertEqual(_grade_from_score(60), "C")

    def test_grade_d(self):
        self.assertEqual(_grade_from_score(45), "D")

    def test_grade_f(self):
        self.assertEqual(_grade_from_score(10), "F")

    def test_build_default_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)


# ── leverage derivation ─────────────────────────────────────────────────────────

class TestDeriveLeverage(unittest.TestCase):
    def test_explicit_leverage(self):
        self.assertAlmostEqual(_derive_leverage({"leverage": 3.0}), 3.0)

    def test_leverage_factor_alias(self):
        self.assertAlmostEqual(_derive_leverage({"leverage_factor": 2.5}), 2.5)

    def test_leverage_below_one_invalid(self):
        self.assertIsNone(_derive_leverage({"leverage": 0.5}))

    def test_leverage_nan_invalid(self):
        self.assertIsNone(_derive_leverage({"leverage": float("nan")}))

    def test_derive_from_exposure_equity(self):
        lev = _derive_leverage(
            {"total_exposure_usd": 300.0, "equity_usd": 100.0})
        self.assertAlmostEqual(lev, 3.0)

    def test_derive_equity_zero(self):
        self.assertIsNone(
            _derive_leverage({"total_exposure_usd": 300.0, "equity_usd": 0.0}))

    def test_derive_exposure_below_equity(self):
        self.assertIsNone(
            _derive_leverage({"total_exposure_usd": 50.0, "equity_usd": 100.0}))

    def test_no_leverage_info(self):
        self.assertIsNone(_derive_leverage({}))

    def test_explicit_preferred_over_derived(self):
        lev = _derive_leverage(
            {"leverage": 2.0, "total_exposure_usd": 300.0, "equity_usd": 100.0})
        self.assertAlmostEqual(lev, 2.0)

    def test_leverage_exactly_one(self):
        self.assertAlmostEqual(_derive_leverage({"leverage": 1.0}), 1.0)


# ── classification & realization ────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_stable_spread(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.05, 1.95, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertEqual(r["classification"], "STABLE_SPREAD")
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")
        finite_check(self, r)

    def test_mild_compression(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=7.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.5, 3.0, 3.2, 2.8],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn(
            r["classification"], ("MILD_COMPRESSION", "HEAVY_COMPRESSION"))
        finite_check(self, r)

    def test_severe_compression_inverted(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=6.0, leverage=4.0,
            borrow_rate_samples=[6.0, 9.0, 11.0, 12.0, 10.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertEqual(r["classification"], "SEVERE_COMPRESSION")
        self.assertTrue(r["carry_inverted"])
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")
        finite_check(self, r)

    def test_realization_ratio_decreases_with_borrow(self):
        low = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        high = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 5.0, 6.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertGreater(low["realization_ratio"], high["realization_ratio"])

    def test_compression_amplified_by_leverage(self):
        # Same borrow rise, higher leverage → more compression.
        lo_lev = A()._analyze_one(make_pos(
            base_yield_apr_pct=10.0, leverage=2.0,
            borrow_rate_samples=[2.0, 4.0],
            borrow_rate_snapshot_pct=2.0))
        hi_lev = A()._analyze_one(make_pos(
            base_yield_apr_pct=10.0, leverage=5.0,
            borrow_rate_samples=[2.0, 4.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertGreater(
            hi_lev["spread_compression_pct"], lo_lev["spread_compression_pct"])

    def test_net_realized_formula(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[4.0, 6.0],  # mean 5.0
            borrow_rate_snapshot_pct=2.0))
        # net_realized = 8*3 - 5*2 = 14
        self.assertAlmostEqual(r["net_apr_realized_pct"], 14.0, places=3)
        # net_headline = 8*3 - 2*2 = 20
        self.assertAlmostEqual(r["net_apr_headline_pct"], 20.0, places=3)
        self.assertAlmostEqual(r["spread_compression_pct"], 6.0, places=3)

    def test_default_snapshot_is_min(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 4.0, 6.0],
            borrow_rate_snapshot_pct=None))
        # snapshot defaults to min(samples) = 2.0
        self.assertAlmostEqual(r["borrow_rate_headline_pct"], 2.0, places=3)

    def test_spread_from_snapshot_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 4.0, 6.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn("SPREAD_FROM_SNAPSHOT", r["flags"])

    def test_no_compression_stable_no_snapshot_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertNotIn("SPREAD_FROM_SNAPSHOT", r["flags"])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_high_leverage_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=4.0,
            borrow_rate_samples=[2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn("HIGH_LEVERAGE_AMPLIFICATION", r["flags"])

    def test_no_leverage_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=1.0,
            borrow_rate_samples=[2.0, 5.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn("NO_LEVERAGE", r["flags"])
        # With L=1, amplification=0 → no compression regardless of borrow.
        self.assertAlmostEqual(r["spread_compression_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "STABLE_SPREAD")

    def test_carry_inverted_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=5.0, leverage=4.0,
            borrow_rate_samples=[8.0, 9.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn("CARRY_INVERTED", r["flags"])
        self.assertTrue(r["net_apr_realized_pct"] < 0)

    def test_borrow_exceeds_base_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=5.0, leverage=3.0,
            borrow_rate_samples=[4.0, 6.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn("BORROW_EXCEEDS_BASE", r["flags"])

    def test_volatile_borrow_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[1.0, 8.0, 1.0, 8.0],
            borrow_rate_snapshot_pct=1.0))
        self.assertIn("VOLATILE_BORROW", r["flags"])

    def test_classification_in_flags(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn(r["classification"], r["flags"])

    def test_stable_spread_carry_flag(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertIn("STABLE_SPREAD_CARRY", r["flags"])


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_realized(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=9.0, leverage=2.5,
            borrow_rate_realized_pct=5.0,
            borrow_rate_snapshot_pct=2.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_samples"])
        self.assertIn("COMPRESSION_FROM_OVERRIDE", r["flags"])
        finite_check(self, r)

    def test_override_no_snapshot_no_compression(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=9.0, leverage=2.5,
            borrow_rate_realized_pct=5.0,
            borrow_rate_snapshot_pct=None))
        # snapshot falls back to realized → no compression
        self.assertAlmostEqual(r["spread_compression_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "STABLE_SPREAD")

    def test_override_volatility_none(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=9.0, leverage=2.5,
            borrow_rate_realized_pct=5.0,
            borrow_rate_snapshot_pct=2.0))
        self.assertIsNone(r["borrow_rate_volatility_pct"])
        self.assertIsNone(r["coefficient_of_variation"])

    def test_single_sample_needs_override(self):
        # 1 sample (< MIN_SAMPLES) and no override → INSUFFICIENT.
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=9.0, leverage=2.5,
            borrow_rate_samples=[3.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_single_sample_with_override(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=9.0, leverage=2.5,
            borrow_rate_samples=[3.0],
            borrow_rate_realized_pct=4.0,
            borrow_rate_snapshot_pct=2.0))
        self.assertTrue(r["used_override"])


# ── headline override ─────────────────────────────────────────────────────────

class TestHeadlineOverride(unittest.TestCase):
    def test_net_headline_override_used(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[5.0, 5.0],
            borrow_rate_snapshot_pct=2.0,
            net_apr_headline_pct=25.0))
        self.assertAlmostEqual(r["net_apr_headline_pct"], 25.0, places=3)

    def test_net_headline_nonpositive_insufficient(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[5.0, 5.0],
            borrow_rate_snapshot_pct=2.0,
            net_apr_headline_pct=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


# ── insufficient data ────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_no_base_yield(self):
        r = A()._analyze_one(make_pos(base_yield_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_base_yield(self):
        r = A()._analyze_one(make_pos(base_yield_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_base_yield(self):
        r = A()._analyze_one(make_pos(base_yield_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_leverage_info(self):
        p = {"vault": "X", "base_yield_apr_pct": 8.0,
             "borrow_rate_samples": [2.0, 2.0]}
        r = A()._analyze_one(p)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_samples_no_override(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(base_yield_apr_pct=None))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["realization_ratio"])

    def test_nonpositive_computed_headline_insufficient(self):
        # base*L - snapshot*(L-1) <= 0 with high snapshot.
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=2.0, leverage=5.0,
            borrow_rate_samples=[10.0, 10.0],
            borrow_rate_snapshot_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_stable_high_score(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertGreaterEqual(r["score"], 85)

    def test_inverted_low_score(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=5.0, leverage=4.0,
            borrow_rate_samples=[8.0, 9.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_borrow(self):
        a = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 2.5],
            borrow_rate_snapshot_pct=2.0))
        b = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, 6.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertGreater(a["score"], b["score"])


# ── portfolio / aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def test_portfolio_shape(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), len(_demo_positions()))

    def test_aggregate_fields(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        for key in (
            "most_stable_vault", "most_compressed_vault", "avg_score",
            "carry_inverted_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["most_stable_vault"])
        self.assertEqual(agg["avg_score"], 0.0)

    def test_aggregate_inverted_count(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertGreaterEqual(agg["carry_inverted_count"], 1)

    def test_most_stable_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["most_stable_vault"], best["token"])


# ── finite / robustness ─────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_all_demo_finite(self):
        for p in _demo_positions():
            finite_check(self, A()._analyze_one(p))

    def test_dirty_samples_filtered(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=3.0,
            borrow_rate_samples=[2.0, "bad", None, -1.0, 3.0, float("nan")],
            borrow_rate_snapshot_pct=2.0))
        self.assertEqual(r["sample_count"], 2)
        finite_check(self, r)

    def test_token_field_alias(self):
        r = A()._analyze_one({
            "token": "T1", "base_yield_apr_pct": 8.0, "leverage": 3.0,
            "borrow_rate_samples": [2.0, 2.0], "borrow_rate_snapshot_pct": 2.0})
        self.assertEqual(r["token"], "T1")

    def test_unknown_token(self):
        r = A()._analyze_one({"base_yield_apr_pct": 8.0, "leverage": 3.0,
                              "borrow_rate_samples": [2.0, 2.0]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_realization_ratio_bounds(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=5.0, leverage=4.0,
            borrow_rate_samples=[9.0, 9.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertGreaterEqual(r["realization_ratio"], 0.0)
        self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_compression_fraction_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["compression_fraction"] is not None:
                self.assertGreaterEqual(r["compression_fraction"], 0.0)
                self.assertLessEqual(r["compression_fraction"], 1.0)

    def test_derive_leverage_in_analyze(self):
        r = A()._analyze_one(make_pos(
            base_yield_apr_pct=8.0, leverage=None,
            total_exposure_usd=300.0, equity_usd=100.0,
            borrow_rate_samples=[2.0, 2.0],
            borrow_rate_snapshot_pct=2.0))
        self.assertAlmostEqual(r["leverage_factor"], 3.0, places=3)


# ── logging ─────────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(5):
                A().analyze_portfolio(
                    _demo_positions(),
                    cfg={"log_path": path, "log_cap": 3}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{ not json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_analyze_single_write_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(
                _demo_positions()[0], cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_leveraged_carry_spread_compression_analyzer",
            names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_leveraged_carry_spread_compression_analyzer")
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer")


# ── constants sanity ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_thresholds_ordered(self):
        self.assertLess(STABLE_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, HEAVY_FRACTION)

    def test_min_samples(self):
        self.assertEqual(MIN_SAMPLES, 2)

    def test_high_leverage(self):
        self.assertGreater(HIGH_LEVERAGE, NO_LEVERAGE_MAX)

    def test_high_cv_positive(self):
        self.assertGreater(HIGH_CV, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

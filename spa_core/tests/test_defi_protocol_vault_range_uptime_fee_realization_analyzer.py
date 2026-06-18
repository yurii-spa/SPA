"""
Tests for MP-1198: DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_range_uptime_fee_realization_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_range_uptime_fee_realization_analyzer import (  # noqa: E501
    DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_in_range,
    _longest_false_streak,
    _range_flips,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    FULL_UPTIME_OOR,
    MINOR_DRIFT_OOR,
    MODERATE_DRIFT_OOR,
    LOW_UPTIME,
    PERSISTENT_STREAK_FRAC,
    HIGH_CHURN_RATIO,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    headline_fee_apr_pct=40.0,
    range_status_samples=None,
    time_in_range_fraction=None,
):
    pos = {
        "vault": vault,
        "headline_fee_apr_pct": headline_fee_apr_pct,
    }
    if range_status_samples is not None:
        pos["range_status_samples"] = range_status_samples
    if time_in_range_fraction is not None:
        pos["time_in_range_fraction"] = time_in_range_fraction
    return pos


def A():
    return DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer()


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

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_unit_high(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)

    def test_clamp_unit_low(self):
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_binary(self):
        self.assertAlmostEqual(_mean([1.0, 0.0, 1.0, 1.0]), 0.75)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 4.0, None), 2.5)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10.0, 0.0, None))

    def test_safe_div_negative_den(self):
        self.assertIsNone(_safe_div(10.0, -1.0, None))

    def test_grade_a(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_score(72), "B")

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
        cfg = _build_default_cfg({"log_cap": 7})
        self.assertEqual(cfg["log_cap"], 7)


# ── _coerce_in_range tests ─────────────────────────────────────────────────────

class TestCoerceInRange(unittest.TestCase):
    def test_bool_true(self):
        self.assertIs(_coerce_in_range(True), True)

    def test_bool_false(self):
        self.assertIs(_coerce_in_range(False), False)

    def test_int_positive(self):
        self.assertIs(_coerce_in_range(1), True)

    def test_int_zero(self):
        self.assertIs(_coerce_in_range(0), False)

    def test_float_positive(self):
        self.assertIs(_coerce_in_range(0.5), True)

    def test_float_negative(self):
        self.assertIs(_coerce_in_range(-2.0), False)

    def test_float_nan(self):
        self.assertIsNone(_coerce_in_range(float("nan")))

    def test_float_inf(self):
        self.assertIsNone(_coerce_in_range(float("inf")))

    def test_str_in(self):
        self.assertIs(_coerce_in_range("in"), True)

    def test_str_in_range(self):
        self.assertIs(_coerce_in_range("in_range"), True)

    def test_str_active_caps(self):
        self.assertIs(_coerce_in_range("ACTIVE"), True)

    def test_str_out(self):
        self.assertIs(_coerce_in_range("out"), False)

    def test_str_inactive(self):
        self.assertIs(_coerce_in_range("inactive"), False)

    def test_str_zero(self):
        self.assertIs(_coerce_in_range("0"), False)

    def test_str_one(self):
        self.assertIs(_coerce_in_range("1"), True)

    def test_str_whitespace(self):
        self.assertIs(_coerce_in_range("  in  "), True)

    def test_str_garbage(self):
        self.assertIsNone(_coerce_in_range("maybe"))

    def test_none(self):
        self.assertIsNone(_coerce_in_range(None))

    def test_dict(self):
        self.assertIsNone(_coerce_in_range({}))


# ── streak / flip helper tests ─────────────────────────────────────────────────

class TestStreakFlips(unittest.TestCase):
    def test_longest_streak_none(self):
        self.assertEqual(_longest_false_streak([True, True, True]), 0)

    def test_longest_streak_all_false(self):
        self.assertEqual(_longest_false_streak([False, False, False]), 3)

    def test_longest_streak_mixed(self):
        self.assertEqual(
            _longest_false_streak([True, False, False, True, False]), 2)

    def test_longest_streak_trailing(self):
        self.assertEqual(
            _longest_false_streak([True, False, False, False]), 3)

    def test_longest_streak_empty(self):
        self.assertEqual(_longest_false_streak([]), 0)

    def test_flips_none(self):
        self.assertEqual(_range_flips([True, True, True]), 0)

    def test_flips_one(self):
        self.assertEqual(_range_flips([True, False]), 1)

    def test_flips_alternating(self):
        self.assertEqual(
            _range_flips([True, False, True, False, True]), 4)

    def test_flips_single(self):
        self.assertEqual(_range_flips([True]), 0)

    def test_flips_empty(self):
        self.assertEqual(_range_flips([]), 0)


# ── realisation math tests ──────────────────────────────────────────────────────

class TestRealizationMath(unittest.TestCase):
    def test_full_uptime_realised_equals_headline(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=18.0,
            range_status_samples=[True] * 10))
        self.assertAlmostEqual(r["time_in_range_fraction"], 1.0)
        self.assertAlmostEqual(r["realized_fee_apr_pct"], 18.0)
        self.assertAlmostEqual(r["fee_uptime_drag_pct"], 0.0)
        self.assertEqual(r["classification"], "FULL_UPTIME")

    def test_half_uptime_halves_realised(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=60.0,
            range_status_samples=[True, False, True, False]))
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.5)
        self.assertAlmostEqual(r["realized_fee_apr_pct"], 30.0)
        self.assertAlmostEqual(r["fee_uptime_drag_pct"], 30.0)

    def test_realization_ratio_equals_uptime(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=50.0,
            range_status_samples=[1, 1, 1, 0]))
        self.assertAlmostEqual(r["realization_ratio"], 0.75)
        self.assertAlmostEqual(r["realized_fee_apr_pct"], 37.5)

    def test_out_of_range_fraction_complements(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 1, 1, 1, 0]))
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.8)
        self.assertAlmostEqual(r["out_of_range_fraction"], 0.2)

    def test_drag_plus_realised_equals_headline(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=42.0,
            range_status_samples=[1, 0, 1, 0, 1, 0, 1]))
        self.assertAlmostEqual(
            r["realized_fee_apr_pct"] + r["fee_uptime_drag_pct"],
            r["headline_fee_apr_pct"])

    def test_string_samples_parsed(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=40.0,
            range_status_samples=["in", "in", "out", "in"]))
        self.assertEqual(r["sample_count"], 4)
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.75)

    def test_non_interpretable_samples_skipped(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=["in", "maybe", None, "out", {}]))
        # only "in" and "out" are interpretable
        self.assertEqual(r["sample_count"], 2)
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.5)

    def test_longest_streak_reported(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 0, 0, 1, 1]))
        self.assertEqual(r["longest_out_of_range_streak"], 3)

    def test_range_flips_reported(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 1, 0]))
        self.assertEqual(r["range_flips"], 3)

    def test_churn_ratio(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 1, 0, 1]))
        # 4 flips over 4 adjacent pairs → 1.0
        self.assertAlmostEqual(r["churn_ratio"], 1.0)

    def test_currently_out_of_range_last_sample(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 1, 1, 0]))
        self.assertTrue(r["currently_out_of_range"])

    def test_currently_in_range_last_sample(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[0, 0, 1, 1]))
        self.assertFalse(r["currently_out_of_range"])


# ── classification tests ────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_full_uptime(self):
        r = A()._analyze_one(make_pos(range_status_samples=[True] * 50))
        self.assertEqual(r["classification"], "FULL_UPTIME")

    def test_minor_drift(self):
        # 1/12 out ≈ 0.083 → MINOR_DRIFT
        r = A()._analyze_one(make_pos(
            range_status_samples=[1] * 11 + [0]))
        self.assertEqual(r["classification"], "MINOR_DRIFT")

    def test_moderate_drift(self):
        # 2/10 out = 0.2 → MODERATE_DRIFT
        r = A()._analyze_one(make_pos(
            range_status_samples=[1] * 8 + [0, 0]))
        self.assertEqual(r["classification"], "MODERATE_DRIFT")

    def test_severe_drift(self):
        # 5/10 out = 0.5 → SEVERE_DRIFT
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0]))
        self.assertEqual(r["classification"], "SEVERE_DRIFT")

    def test_boundary_full_uptime_within(self):
        # 1/100 out = 0.01 ≤ FULL_UPTIME_OOR (0.02) → FULL_UPTIME
        samples = [1] * 99 + [0]
        r = A()._analyze_one(make_pos(range_status_samples=samples))
        self.assertLessEqual(r["out_of_range_fraction"], FULL_UPTIME_OOR)
        self.assertEqual(r["classification"], "FULL_UPTIME")

    def test_score_monotonic_in_uptime(self):
        hi = A()._analyze_one(make_pos(range_status_samples=[1] * 9 + [0]))
        lo = A()._analyze_one(make_pos(range_status_samples=[1] * 3 + [0] * 7))
        self.assertGreater(hi["score"], lo["score"])

    def test_full_uptime_high_score(self):
        r = A()._analyze_one(make_pos(range_status_samples=[True] * 20))
        self.assertGreaterEqual(r["score"], 99.0)

    def test_recommendation_trust(self):
        r = A()._analyze_one(make_pos(range_status_samples=[True] * 20))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_recommendation_avoid_severe(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flag tests ──────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_full_uptime_flag(self):
        r = A()._analyze_one(make_pos(range_status_samples=[True] * 20))
        self.assertIn("FULL_UPTIME", r["flags"])

    def test_currently_out_flag(self):
        r = A()._analyze_one(make_pos(range_status_samples=[1, 1, 1, 0]))
        self.assertIn("CURRENTLY_OUT_OF_RANGE", r["flags"])

    def test_persistent_out_flag(self):
        # 6/8 out, longest streak 6 ≥ ceil(0.5*8)=4 → persistent
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 1, 0, 0, 0, 0, 0, 0]))
        self.assertIn("PERSISTENTLY_OUT_OF_RANGE", r["flags"])

    def test_low_uptime_flag(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 0, 0]))
        self.assertIn("NARROW_BAND_LOW_UPTIME", r["flags"])

    def test_churn_flag(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[1, 0, 1, 0, 1, 0]))
        self.assertIn("FREQUENT_REBALANCE_CHURN", r["flags"])

    def test_no_churn_flag_when_stable(self):
        r = A()._analyze_one(make_pos(range_status_samples=[1] * 9 + [0]))
        self.assertNotIn("FREQUENT_REBALANCE_CHURN", r["flags"])

    def test_override_flag(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=None, time_in_range_fraction=0.7))
        self.assertIn("UPTIME_FROM_OVERRIDE", r["flags"])


# ── override path tests ─────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_uptime_used(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=25.0,
            range_status_samples=None,
            time_in_range_fraction=0.8))
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.8)
        self.assertAlmostEqual(r["realized_fee_apr_pct"], 20.0)
        self.assertFalse(r["uptime_from_samples"])
        self.assertEqual(r["sample_count"], 0)

    def test_override_clamped_high(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=None, time_in_range_fraction=1.4))
        self.assertAlmostEqual(r["time_in_range_fraction"], 1.0)

    def test_override_clamped_low(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=None, time_in_range_fraction=-0.3))
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.0)

    def test_override_nan_insufficient(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=None,
            time_in_range_fraction=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_samples_take_precedence_over_override(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[True, True, True, True],
            time_in_range_fraction=0.1))
        # samples present → override ignored
        self.assertAlmostEqual(r["time_in_range_fraction"], 1.0)
        self.assertTrue(r["uptime_from_samples"])

    def test_single_sample_falls_back_to_override(self):
        # one sample < MIN_SAMPLES → use override if present
        r = A()._analyze_one(make_pos(
            range_status_samples=[True],
            time_in_range_fraction=0.6))
        self.assertFalse(r["uptime_from_samples"])
        self.assertAlmostEqual(r["time_in_range_fraction"], 0.6)


# ── insufficient-data tests ─────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_no_samples_no_override(self):
        r = A()._analyze_one(make_pos(range_status_samples=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_zero_headline(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=0.0,
            range_status_samples=[True] * 10))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=-5.0,
            range_status_samples=[True] * 10))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A()._analyze_one(make_pos(
            headline_fee_apr_pct=float("nan"),
            range_status_samples=[True] * 10))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_uninterpretable_samples(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=["maybe", None, {}, "huh"]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_nulls(self):
        r = A()._analyze_one(make_pos(range_status_samples=None))
        self.assertIsNone(r["realized_fee_apr_pct"])
        self.assertIsNone(r["time_in_range_fraction"])
        self.assertIsNone(r["churn_ratio"])


# ── portfolio / aggregate tests ─────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def test_portfolio_structure(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), 5)

    def test_aggregate_picks_best_worst(self):
        positions = [
            make_pos(vault="GOOD", range_status_samples=[True] * 20),
            make_pos(vault="BAD",
                     range_status_samples=[1, 0, 0, 0, 0, 0, 0, 0]),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["most_honest_vault"], "GOOD")
        self.assertEqual(agg["least_honest_vault"], "BAD")

    def test_aggregate_all_insufficient(self):
        positions = [
            make_pos(vault="X", range_status_samples=None),
            make_pos(vault="Y", headline_fee_apr_pct=0.0,
                     range_status_samples=[True] * 5),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["most_honest_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_severe_count(self):
        positions = [
            make_pos(vault="A", range_status_samples=[1, 0, 0, 0, 0, 0]),
            make_pos(vault="B", range_status_samples=[0, 0, 1, 0, 0, 0]),
            make_pos(vault="C", range_status_samples=[True] * 10),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["severe_count"], 2)

    def test_analyze_single_public(self):
        r = A().analyze(make_pos(range_status_samples=[True] * 10))
        self.assertEqual(r["classification"], "FULL_UPTIME")


# ── finiteness / sentinel tests ─────────────────────────────────────────────────

class TestFiniteness(unittest.TestCase):
    def test_all_demo_finite(self):
        out = A().analyze_portfolio(_demo_positions())
        for r in out["positions"]:
            finite_check(self, r)

    def test_no_inf_nan_in_severe(self):
        r = A()._analyze_one(make_pos(
            range_status_samples=[0, 0, 0, 0, 0, 1]))
        finite_check(self, r)

    def test_grade_present(self):
        r = A()._analyze_one(make_pos(range_status_samples=[True] * 10))
        self.assertIn(r["grade"], ("A", "B", "C", "D", "F"))


# ── logging tests ────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(
                _demo_positions(), cfg=cfg, write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                log = json.load(fh)
            self.assertEqual(len(log), 1)
            self.assertIn("aggregate", log[0])
            self.assertIn("snapshots", log[0])

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio(
                    _demo_positions(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                log = json.load(fh)
            self.assertEqual(len(log), 3)

    def test_log_recovers_from_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("{ not json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(
                _demo_positions(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                log = json.load(fh)
            self.assertEqual(len(log), 1)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(
                _demo_positions(), cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_no_log_when_write_false(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(_demo_positions(), cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))


# ── demo / structural tests ──────────────────────────────────────────────────────

class TestDemoStructure(unittest.TestCase):
    def test_demo_has_five(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications_present(self):
        out = A().analyze_portfolio(_demo_positions())
        classes = {r["classification"] for r in out["positions"]}
        self.assertIn("FULL_UPTIME", classes)
        self.assertIn("SEVERE_DRIFT", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_required_keys_present(self):
        r = A()._analyze_one(make_pos(range_status_samples=[True] * 10))
        for key in (
            "token", "headline_fee_apr_pct", "realized_fee_apr_pct",
            "fee_uptime_drag_pct", "time_in_range_fraction",
            "out_of_range_fraction", "realization_ratio",
            "longest_out_of_range_streak", "range_flips", "churn_ratio",
            "sample_count", "uptime_from_samples", "currently_out_of_range",
            "persistent_out_of_range", "low_uptime",
            "frequent_rebalance_churn", "score", "classification",
            "recommendation", "grade", "flags",
        ):
            self.assertIn(key, r)

    def test_token_fallback(self):
        r = A()._analyze_one({"headline_fee_apr_pct": 10.0,
                              "range_status_samples": [True, True, True]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_constants_sane(self):
        self.assertEqual(MIN_SAMPLES, 2)
        self.assertLess(FULL_UPTIME_OOR, MINOR_DRIFT_OOR)
        self.assertLess(MINOR_DRIFT_OOR, MODERATE_DRIFT_OOR)
        self.assertEqual(LOW_UPTIME, 0.50)
        self.assertEqual(PERSISTENT_STREAK_FRAC, 0.50)
        self.assertEqual(HIGH_CHURN_RATIO, 0.40)


if __name__ == "__main__":
    unittest.main()

"""
Tests for MP-1210: DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_management_fee_on_idle_capital_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_management_fee_on_idle_capital_analyzer import (  # noqa: E501
    DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_signed,
    _coerce_count,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    MOSTLY_IDLE_FRACTION,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_apr_pct=None,
    idle_fraction=None,
    management_fee_pct=None,
    aum_usd=None,
    management_fee_on_idle_pct=None,
    fee_charged_apr_pct=None,
):
    pos = {"vault": vault}
    if gross_apr_pct is not None:
        pos["gross_apr_pct"] = gross_apr_pct
    if idle_fraction is not None:
        pos["idle_fraction"] = idle_fraction
    if management_fee_pct is not None:
        pos["management_fee_pct"] = management_fee_pct
    if aum_usd is not None:
        pos["aum_usd"] = aum_usd
    if management_fee_on_idle_pct is not None:
        pos["management_fee_on_idle_pct"] = management_fee_on_idle_pct
    if fee_charged_apr_pct is not None:
        pos["fee_charged_apr_pct"] = fee_charged_apr_pct
    return pos


def _all_floats_finite(obj):
    """Recursively assert every float in a result structure is finite."""
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_all_floats_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_floats_finite(v) for v in obj)
    return True


# ── helper tests ────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 3.0), 3.0)
        self.assertEqual(_f("x", 1.0), 1.0)
        self.assertEqual(_f("2.5"), 2.5)
        self.assertEqual(_f(4), 4.0)

    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 1), 1)
        self.assertEqual(_clamp(-5, 0, 1), 0)
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    def test_mean(self):
        self.assertEqual(_mean([]), 0.0)
        self.assertEqual(_mean([2, 4]), 3.0)

    def test_safe_div(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)
        self.assertIsNone(_safe_div(10, 0, None))
        self.assertIsNone(_safe_div(10, -1, None))

    def test_coerce_num(self):
        self.assertEqual(_coerce_num(3), 3.0)
        self.assertEqual(_coerce_num("3.5"), 3.5)
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))
        self.assertIsNone(_coerce_num(None))
        self.assertIsNone(_coerce_num("abc"))
        self.assertIsNone(_coerce_num(""))
        self.assertIsNone(_coerce_num(float("nan")))
        self.assertIsNone(_coerce_num(float("inf")))

    def test_coerce_signed(self):
        self.assertEqual(_coerce_signed(-5), -5.0)
        self.assertEqual(_coerce_signed("-2.5"), -2.5)
        self.assertIsNone(_coerce_signed(None))

    def test_coerce_count(self):
        self.assertEqual(_coerce_count(3), 3)
        self.assertEqual(_coerce_count("4"), 4)
        self.assertEqual(_coerce_count(0), 0)
        self.assertIsNone(_coerce_count(-1))
        self.assertIsNone(_coerce_count(None))
        self.assertIsNone(_coerce_count("x"))

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)
        cfg2 = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg2["log_cap"], 5)

    def test_grade_from_score(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(75), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(10), "F")

    def test_thresholds_ordered(self):
        self.assertLess(CLEAN_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)
        self.assertGreater(EPS, 0.0)
        self.assertEqual(MOSTLY_IDLE_FRACTION, 0.50)


# ── main path classification ──────────────────────────────────────────────────

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_clean_fully_deployed(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=12.0, idle_fraction=0.0, management_fee_pct=1.0))
        self.assertEqual(r["classification"], "CLEAN_DEPLOYED")
        self.assertIn("CLEAN_FULLY_DEPLOYED", r["flags"])
        self.assertEqual(r["idle_fee_apr_pct"], 0.0)
        self.assertEqual(r["idle_fee_yield_share"], 0.0)
        self.assertGreaterEqual(r["score"], 85.0)
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["recommendation"], "TRUST_FEE_BASE")

    def test_mild_idle_fee(self):
        # gross 10, idle 0.10, fee 2 → deployed 0.9, effective 9,
        # idle_fee=2*0.1=0.2, share=0.2/9≈0.0222 → CLEAN; push idle higher.
        # gross 10, idle 0.40, fee 2 → effective 6, idle_fee 0.8, share=0.1333 → MILD
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.40, management_fee_pct=2.0))
        self.assertEqual(r["classification"], "MILD_IDLE_FEE")
        self.assertGreater(r["idle_fee_yield_share"], CLEAN_FRACTION)
        self.assertLessEqual(r["idle_fee_yield_share"], MILD_FRACTION)
        self.assertEqual(r["recommendation"], "MINOR_IDLE_FEE")

    def test_moderate_idle_fee(self):
        # gross 6, idle 0.40, fee 2 → effective 3.6, idle_fee 0.8,
        # share = 0.8/3.6 ≈ 0.2222 → MODERATE.
        r = self.an.analyze(make_pos(
            gross_apr_pct=6.0, idle_fraction=0.40, management_fee_pct=2.0))
        self.assertEqual(r["classification"], "MODERATE_IDLE_FEE")
        self.assertGreater(r["idle_fee_yield_share"], MILD_FRACTION)
        self.assertLessEqual(r["idle_fee_yield_share"], MODERATE_FRACTION)
        self.assertIn("FEE_ON_IDLE_CAPITAL", r["flags"])
        self.assertEqual(r["recommendation"], "DEMAND_DEPLOYED_ONLY_FEE")

    def test_severe_idle_fee_high_share(self):
        # gross 5, idle 0.40, fee 2 → effective 3, idle_fee 0.8,
        # share = 0.8/3 ≈ 0.2667; need >0.5: gross 3, idle 0.40, fee 2 →
        # effective 1.8, idle_fee 0.8, share = 0.444 ... use gross 2.5, fee 2.
        r = self.an.analyze(make_pos(
            gross_apr_pct=2.5, idle_fraction=0.40, management_fee_pct=2.0))
        # effective = 2.5*0.6 = 1.5, idle_fee = 0.8, share = 0.8/1.5 ≈ 0.533
        self.assertEqual(r["classification"], "SEVERE_IDLE_FEE")
        self.assertGreater(r["idle_fee_yield_share"], MODERATE_FRACTION)

    def test_severe_net_negative(self):
        # gross 4, idle 0.70, fee 3 → effective 1.2, fee_charged 3 →
        # net = 1.2 - 3 = -1.8 → net negative.
        r = self.an.analyze(make_pos(
            gross_apr_pct=4.0, idle_fraction=0.70, management_fee_pct=3.0))
        self.assertEqual(r["classification"], "SEVERE_IDLE_FEE")
        self.assertTrue(r["net_is_negative"])
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])
        self.assertIn("MOSTLY_IDLE", r["flags"])

    def test_mostly_idle_flag(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.55, management_fee_pct=1.0))
        self.assertIn("MOSTLY_IDLE", r["flags"])

    def test_not_mostly_idle(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.30, management_fee_pct=1.0))
        self.assertNotIn("MOSTLY_IDLE", r["flags"])

    def test_idle_fraction_clamped(self):
        # idle 1.5 clamps to 1.0 → deployed 0, effective 0.
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=1.5, management_fee_pct=2.0))
        self.assertEqual(r["idle_fraction"], 1.0)
        self.assertEqual(r["deployed_fraction"], 0.0)
        self.assertEqual(r["effective_gross_apr_pct"], 0.0)

    def test_idle_fraction_negative_clamped(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=-0.5, management_fee_pct=2.0))
        self.assertEqual(r["idle_fraction"], 0.0)
        self.assertEqual(r["deployed_fraction"], 1.0)


# ── math correctness ──────────────────────────────────────────────────────────

class TestMath(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_metric_geometry(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=6.0, idle_fraction=0.40, management_fee_pct=2.0))
        # deployed 0.6
        self.assertAlmostEqual(r["deployed_fraction"], 0.6)
        self.assertAlmostEqual(r["effective_gross_apr_pct"], 3.6)  # 6*0.6
        self.assertAlmostEqual(r["fee_charged_apr_pct"], 2.0)      # full AUM
        self.assertAlmostEqual(r["fair_fee_apr_pct"], 1.2)         # 2*0.6
        self.assertAlmostEqual(r["idle_fee_apr_pct"], 0.8)         # 2*0.4
        self.assertAlmostEqual(r["overstatement_pct"], 0.8)
        # net_charged = 3.6 - 2 = 1.6 ; net_fair = 3.6 - 1.2 = 2.4
        self.assertAlmostEqual(r["net_apr_charged_pct"], 1.6)
        self.assertAlmostEqual(r["net_apr_fair_pct"], 2.4)
        self.assertAlmostEqual(
            r["yield_realization_ratio"], 1.6 / 2.4, places=4)

    def test_idle_fee_equals_fee_times_idle_frac(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.30, management_fee_pct=2.0))
        self.assertAlmostEqual(r["idle_fee_apr_pct"], 2.0 * 0.30, places=6)

    def test_score_formula(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=6.0, idle_fraction=0.40, management_fee_pct=2.0))
        rr = r["yield_realization_ratio"]
        share = r["idle_fee_yield_share"]
        expected = 70.0 * rr + 30.0 * (1.0 - share)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_clean_score_max(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.0, management_fee_pct=2.0))
        self.assertEqual(r["yield_realization_ratio"], 1.0)
        self.assertEqual(r["idle_fee_yield_share"], 0.0)
        self.assertEqual(r["score"], 100.0)

    def test_fee_negative_clamped(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.30, management_fee_pct=-2.0))
        self.assertEqual(r["management_fee_pct"], 0.0)
        self.assertEqual(r["fee_charged_apr_pct"], 0.0)
        self.assertEqual(r["idle_fee_apr_pct"], 0.0)

    def test_aum_usd_reporting(self):
        # idle_fee_apr 0.8% on 10M AUM → 80_000 USD.
        r = self.an.analyze(make_pos(
            gross_apr_pct=6.0, idle_fraction=0.40, management_fee_pct=2.0,
            aum_usd=10_000_000.0))
        self.assertEqual(r["aum_usd"], 10_000_000.0)
        self.assertAlmostEqual(r["idle_fee_usd"], 80_000.0, places=2)

    def test_aum_usd_none_when_invalid(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=6.0, idle_fraction=0.40, management_fee_pct=2.0,
            aum_usd=0.0))
        self.assertIsNone(r["aum_usd"])
        self.assertIsNone(r["idle_fee_usd"])


# ── override path ─────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_override_basic(self):
        # gap 4, fee_charged 5, gross 20 → share = 4/20 = 0.2 → MILD.
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=4.0,
            fee_charged_apr_pct=5.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        self.assertAlmostEqual(r["idle_fee_yield_share"], 4.0 / 20.0, places=4)
        self.assertEqual(r["classification"], "MILD_IDLE_FEE")

    def test_override_geometry_none(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=4.0,
            fee_charged_apr_pct=5.0))
        self.assertIsNone(r["management_fee_pct"])
        self.assertIsNone(r["idle_fraction"])
        self.assertIsNone(r["deployed_fraction"])
        self.assertIsNone(r["effective_gross_apr_pct"])
        self.assertIsNone(r["net_apr_charged_pct"])
        self.assertIsNone(r["net_apr_fair_pct"])

    def test_override_geometry_flags_suppressed(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=4.0,
            fee_charged_apr_pct=5.0))
        self.assertNotIn("FEE_ON_IDLE_CAPITAL", r["flags"])
        self.assertNotIn("MOSTLY_IDLE", r["flags"])
        self.assertNotIn("NET_NEGATIVE_AFTER_FEE", r["flags"])
        self.assertNotIn("CLEAN_FULLY_DEPLOYED", r["flags"])

    def test_override_negative_gap_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=-4.0,
            fee_charged_apr_pct=5.0))
        self.assertAlmostEqual(r["idle_fee_apr_pct"], 4.0, places=4)

    def test_override_gap_capped_at_fee_charged(self):
        # gap > fee_charged → capped at fee_charged.
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=99.0,
            fee_charged_apr_pct=5.0))
        self.assertEqual(r["idle_fee_apr_pct"], 5.0)
        self.assertEqual(r["fair_fee_apr_pct"], 0.0)

    def test_override_realization_anchor(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=3.0,
            fee_charged_apr_pct=5.0))
        share = r["idle_fee_yield_share"]
        self.assertAlmostEqual(
            r["yield_realization_ratio"], 1.0 - share, places=4)

    def test_override_requires_positive_fee_charged(self):
        # fee_charged = 0 → not override → falls to main path (needs idle+fee).
        r = self.an.analyze(make_pos(
            gross_apr_pct=20.0, management_fee_on_idle_pct=3.0,
            fee_charged_apr_pct=0.0, idle_fraction=0.20,
            management_fee_pct=2.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_missing_gross(self):
        r = self.an.analyze(make_pos(idle_fraction=0.30, management_fee_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_zero_gross(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=0.0, idle_fraction=0.30, management_fee_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=-5.0, idle_fraction=0.30, management_fee_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=float("nan"), idle_fraction=0.30,
            management_fee_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_non_finite_idle(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=float("inf"),
            management_fee_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_idle(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, management_fee_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_invalid_fee_main_path(self):
        # gross + idle present, no valid fee, no override → INSUFFICIENT_DATA.
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.30,
            management_fee_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_fee_main_path(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.30))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_none(self):
        r = self.an.analyze(make_pos(gross_apr_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        for k in ("net_apr_charged_pct", "fee_charged_apr_pct",
                  "idle_fee_apr_pct", "yield_realization_ratio"):
            self.assertIsNone(r[k])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_classification_always_in_flags(self):
        for idle in (0.0, 0.40, 0.70):
            r = self.an.analyze(make_pos(
                gross_apr_pct=6.0, idle_fraction=idle, management_fee_pct=2.0))
            self.assertIn(r["classification"], r["flags"])

    def test_fee_on_idle_capital_flag(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.30, management_fee_pct=2.0))
        self.assertIn("FEE_ON_IDLE_CAPITAL", r["flags"])

    def test_no_idle_fee_flag_when_fully_deployed(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=10.0, idle_fraction=0.0, management_fee_pct=2.0))
        self.assertNotIn("FEE_ON_IDLE_CAPITAL", r["flags"])


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_portfolio_structure(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), 5)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 5)
        self.assertIn("cleanest_vault", agg)
        self.assertIn("worst_idle_fee_vault", agg)

    def test_aggregate_cleanest_and_worst(self):
        positions = [
            make_pos(vault="Clean", gross_apr_pct=10.0, idle_fraction=0.0,
                     management_fee_pct=1.0),
            make_pos(vault="Bad", gross_apr_pct=4.0, idle_fraction=0.70,
                     management_fee_pct=3.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(agg["worst_idle_fee_vault"], "Bad")

    def test_aggregate_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_idle_fee_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_net_negative_count(self):
        positions = [
            make_pos(vault="A", gross_apr_pct=4.0, idle_fraction=0.70,
                     management_fee_pct=3.0),
            make_pos(vault="B", gross_apr_pct=10.0, idle_fraction=0.0,
                     management_fee_pct=1.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)


# ── ring-buffer log ───────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertIn("aggregate", data[0])
            self.assertIn("snapshots", data[0])

    def test_log_ring_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(5):
                self.an.analyze_portfolio(
                    [make_pos(gross_apr_pct=10.0, idle_fraction=0.30,
                              management_fee_pct=2.0)],
                    cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("not json{{{")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze_portfolio(
                [make_pos(gross_apr_pct=10.0, idle_fraction=0.30,
                          management_fee_pct=2.0)],
                cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_apr_pct=10.0, idle_fraction=0.30,
                                     management_fee_pct=2.0),
                            cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_apr_pct=10.0, idle_fraction=0.30,
                                     management_fee_pct=2.0),
                            cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))


# ── invariants / finiteness ───────────────────────────────────────────────────

class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_all_floats_finite(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(out))

    def test_score_bounds_random_grid(self):
        for g in (1.0, 4.0, 12.0, 30.0, 100.0):
            for idle in (0.0, 0.1, 0.5, 0.9, 1.0):
                for fee in (0.0, 1.0, 2.0, 5.0, 10.0):
                    r = self.an.analyze(make_pos(
                        gross_apr_pct=g, idle_fraction=idle,
                        management_fee_pct=fee))
                    self.assertGreaterEqual(r["score"], 0.0)
                    self.assertLessEqual(r["score"], 100.0)
                    self.assertGreaterEqual(r["idle_fee_yield_share"], 0.0)
                    self.assertLessEqual(r["idle_fee_yield_share"], 1.0)
                    self.assertGreaterEqual(r["yield_realization_ratio"], 0.0)
                    self.assertLessEqual(r["yield_realization_ratio"], 1.0)

    def test_score_monotone_with_idle(self):
        # holding gross & fee fixed, MORE idle → LOWER score (monotone
        # non-increasing): more dead capital, fee bites harder.
        prev = 101.0
        for idle in (0.0, 0.10, 0.25, 0.40, 0.55):
            r = self.an.analyze(make_pos(
                gross_apr_pct=10.0, idle_fraction=idle, management_fee_pct=2.0))
            self.assertLessEqual(r["score"], prev + 1e-9)
            prev = r["score"]

    def test_share_monotone_with_idle(self):
        # MORE idle → larger idle_fee_yield_share (monotone non-decreasing).
        prev = -1.0
        for idle in (0.0, 0.10, 0.25, 0.40, 0.55):
            r = self.an.analyze(make_pos(
                gross_apr_pct=10.0, idle_fraction=idle, management_fee_pct=2.0))
            self.assertGreaterEqual(r["idle_fee_yield_share"], prev - 1e-9)
            prev = r["idle_fee_yield_share"]

    def test_token_fallback(self):
        r = self.an.analyze({"token": "TKN", "gross_apr_pct": 10.0,
                             "idle_fraction": 0.0, "management_fee_pct": 1.0})
        self.assertEqual(r["token"], "TKN")

    def test_unknown_token(self):
        r = self.an.analyze({"gross_apr_pct": 10.0, "idle_fraction": 0.0,
                             "management_fee_pct": 1.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_string_numeric_inputs(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct="6", idle_fraction="0.40", management_fee_pct="2"))
        self.assertEqual(r["classification"], "MODERATE_IDLE_FEE")

    def test_result_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_apr_pct=6.0, idle_fraction=0.40, management_fee_pct=2.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications(self):
        out = self.an.analyze_portfolio(_demo_positions())
        classes = {p["token"]: p["classification"] for p in out["positions"]}
        self.assertEqual(
            classes["USDC-Vault-CleanDeployed"], "CLEAN_DEPLOYED")
        self.assertEqual(
            classes["stETH-Vault-LargeIdleBuffer"], "MODERATE_IDLE_FEE")
        self.assertEqual(
            classes["GOV-Vault-MostlyIdle"], "SEVERE_IDLE_FEE")
        self.assertEqual(
            classes["LST-Vault-OverrideGap"], "MILD_IDLE_FEE")
        self.assertEqual(
            classes["MYSTERY-Vault-NoData"], "INSUFFICIENT_DATA")

    def test_demo_json_serialisable(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertIsInstance(s, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)

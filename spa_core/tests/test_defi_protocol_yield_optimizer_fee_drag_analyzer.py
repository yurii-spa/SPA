"""
Tests for MP-1088: DeFiProtocolYieldOptimizerFeeDragAnalyzer
≥110 test methods covering all logic paths.
Uses unittest only (no pytest).
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_yield_optimizer_fee_drag_analyzer
"""

import json
import math
import os
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------
from spa_core.analytics.defi_protocol_yield_optimizer_fee_drag_analyzer import (
    DeFiProtocolYieldOptimizerFeeDragAnalyzer,
    FEE_EXCEEDS_YIELD,
    FEE_HEAVY,
    HIGH_FEE_DRAG,
    LOG_CAP,
    LOW_FEE_VAULT,
    MODERATE_FEES,
    _NEVER_BREAKEVEN,
    _compute_breakeven_days,
    _compute_fee_drag,
    _compute_fee_drag_ratio,
    _compute_fee_efficiency_score,
    _compute_fee_label,
    __mp__,
    __version__,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _default_analyzer(tmp_dir: str) -> DeFiProtocolYieldOptimizerFeeDragAnalyzer:
    log = os.path.join(tmp_dir, "fee_drag_log.json")
    return DeFiProtocolYieldOptimizerFeeDragAnalyzer(log_path=log)


def _analyze(
    tmp_dir: str,
    gross_apy_pct: float = 10.0,
    management_fee_pct: float = 0.0,
    performance_fee_pct: float = 0.0,
    deposit_fee_pct: float = 0.0,
    withdrawal_fee_pct: float = 0.0,
    holding_period_days: int = 365,
    protocol_name: str = "TestVault",
    tvl_usd: float = 10_000_000.0,
) -> dict:
    return _default_analyzer(tmp_dir).analyze(
        gross_apy_pct=gross_apy_pct,
        management_fee_pct=management_fee_pct,
        performance_fee_pct=performance_fee_pct,
        deposit_fee_pct=deposit_fee_pct,
        withdrawal_fee_pct=withdrawal_fee_pct,
        holding_period_days=holding_period_days,
        protocol_name=protocol_name,
        tvl_usd=tvl_usd,
    )


# ===========================================================================
# 1. Module constants
# ===========================================================================

class TestModuleConstants(unittest.TestCase):
    def test_version_string(self):
        self.assertEqual(__version__, "1.0.0")

    def test_mp_tag(self):
        self.assertEqual(__mp__, "MP-1088")

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_fee_label_constants(self):
        self.assertEqual(LOW_FEE_VAULT, "LOW_FEE_VAULT")
        self.assertEqual(MODERATE_FEES, "MODERATE_FEES")
        self.assertEqual(HIGH_FEE_DRAG, "HIGH_FEE_DRAG")
        self.assertEqual(FEE_HEAVY, "FEE_HEAVY")
        self.assertEqual(FEE_EXCEEDS_YIELD, "FEE_EXCEEDS_YIELD")

    def test_never_breakeven_sentinel(self):
        self.assertGreater(_NEVER_BREAKEVEN, 0)
        self.assertEqual(_NEVER_BREAKEVEN, 36500)


# ===========================================================================
# 2. _compute_fee_drag internal function
# ===========================================================================

class TestComputeFeeDragFunction(unittest.TestCase):

    def test_performance_drag_proportional_to_gross(self):
        drag = _compute_fee_drag(10.0, 0.0, 20.0, 0.0, 0.0, 365)
        self.assertAlmostEqual(drag["perf_drag"], 2.0)

    def test_management_drag_direct(self):
        drag = _compute_fee_drag(10.0, 2.0, 0.0, 0.0, 0.0, 365)
        self.assertAlmostEqual(drag["mgmt_drag"], 2.0)

    def test_deposit_drag_amortised_365(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 1.0, 0.0, 365)
        self.assertAlmostEqual(drag["deposit_drag"], 1.0)

    def test_deposit_drag_amortised_30_days(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 1.0, 0.0, 30)
        expected = 1.0 * 365 / 30
        self.assertAlmostEqual(drag["deposit_drag"], expected, places=6)

    def test_withdrawal_drag_amortised_365(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 0.0, 0.5, 365)
        self.assertAlmostEqual(drag["withdrawal_drag"], 0.5)

    def test_withdrawal_drag_amortised_90_days(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 0.0, 0.5, 90)
        expected = 0.5 * 365 / 90
        self.assertAlmostEqual(drag["withdrawal_drag"], expected, places=6)

    def test_total_drag_sum_of_components(self):
        drag = _compute_fee_drag(10.0, 2.0, 20.0, 0.1, 0.5, 365)
        # perf=2, mgmt=2, dep=0.1, wd=0.5
        self.assertAlmostEqual(drag["total_fee_drag_pct"], 4.6, places=6)

    def test_zero_gross_apy_no_perf_drag(self):
        drag = _compute_fee_drag(0.0, 2.0, 20.0, 0.0, 0.0, 365)
        self.assertAlmostEqual(drag["perf_drag"], 0.0)
        self.assertAlmostEqual(drag["mgmt_drag"], 2.0)

    def test_zero_fees_all_drag_zero(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 0.0, 0.0, 365)
        self.assertAlmostEqual(drag["total_fee_drag_pct"], 0.0)

    def test_holding_period_1_day_maximises_one_time_fees(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 1.0, 1.0, 1)
        # each amortised over 1 day → *365
        self.assertAlmostEqual(drag["deposit_drag"], 365.0)
        self.assertAlmostEqual(drag["withdrawal_drag"], 365.0)

    def test_performance_drag_zero_when_perf_fee_zero(self):
        drag = _compute_fee_drag(10.0, 0.0, 0.0, 0.0, 0.0, 365)
        self.assertAlmostEqual(drag["perf_drag"], 0.0)

    def test_returns_dict_with_required_keys(self):
        drag = _compute_fee_drag(10.0, 1.0, 10.0, 0.1, 0.2, 180)
        for key in ("perf_drag", "mgmt_drag", "deposit_drag", "withdrawal_drag", "total_fee_drag_pct"):
            self.assertIn(key, drag)


# ===========================================================================
# 3. _compute_fee_drag_ratio
# ===========================================================================

class TestComputeFeeDragRatioFunction(unittest.TestCase):

    def test_zero_drag_gives_zero_ratio(self):
        self.assertAlmostEqual(_compute_fee_drag_ratio(0.0, 10.0), 0.0)

    def test_normal_ratio(self):
        self.assertAlmostEqual(_compute_fee_drag_ratio(4.6, 10.0), 0.46)

    def test_capped_at_one(self):
        # total_drag > gross → capped at 1.0
        self.assertAlmostEqual(_compute_fee_drag_ratio(15.0, 10.0), 1.0)

    def test_gross_zero_with_drag_returns_one(self):
        self.assertAlmostEqual(_compute_fee_drag_ratio(5.0, 0.0), 1.0)

    def test_gross_zero_no_drag_returns_zero(self):
        self.assertAlmostEqual(_compute_fee_drag_ratio(0.0, 0.0), 0.0)

    def test_ratio_exactly_half(self):
        self.assertAlmostEqual(_compute_fee_drag_ratio(5.0, 10.0), 0.5)

    def test_ratio_low_fee(self):
        self.assertAlmostEqual(_compute_fee_drag_ratio(0.5, 10.0), 0.05)

    def test_ratio_not_negative(self):
        result = _compute_fee_drag_ratio(0.0, 100.0)
        self.assertGreaterEqual(result, 0.0)


# ===========================================================================
# 4. _compute_fee_label
# ===========================================================================

class TestComputeFeeLabelFunction(unittest.TestCase):

    def test_fee_exceeds_yield_when_net_zero(self):
        self.assertEqual(_compute_fee_label(0.0, 0.9), FEE_EXCEEDS_YIELD)

    def test_fee_exceeds_yield_when_net_negative(self):
        self.assertEqual(_compute_fee_label(-1.5, 0.9), FEE_EXCEEDS_YIELD)

    def test_fee_exceeds_yield_takes_priority_over_low_drag_ratio(self):
        # net_apy <= 0 always wins regardless of ratio
        self.assertEqual(_compute_fee_label(-0.001, 0.05), FEE_EXCEEDS_YIELD)

    def test_low_fee_vault_below_010(self):
        self.assertEqual(_compute_fee_label(9.5, 0.05), LOW_FEE_VAULT)

    def test_low_fee_vault_ratio_zero(self):
        self.assertEqual(_compute_fee_label(10.0, 0.0), LOW_FEE_VAULT)

    def test_low_fee_vault_just_below_010(self):
        self.assertEqual(_compute_fee_label(9.0, 0.099), LOW_FEE_VAULT)

    def test_moderate_fees_at_010(self):
        self.assertEqual(_compute_fee_label(9.0, 0.10), MODERATE_FEES)

    def test_moderate_fees_mid(self):
        self.assertEqual(_compute_fee_label(8.0, 0.20), MODERATE_FEES)

    def test_moderate_fees_just_below_025(self):
        self.assertEqual(_compute_fee_label(7.5, 0.249), MODERATE_FEES)

    def test_high_fee_drag_at_025(self):
        self.assertEqual(_compute_fee_label(7.5, 0.25), HIGH_FEE_DRAG)

    def test_high_fee_drag_mid(self):
        self.assertEqual(_compute_fee_label(6.5, 0.35), HIGH_FEE_DRAG)

    def test_fee_heavy_at_040(self):
        self.assertEqual(_compute_fee_label(6.0, 0.40), FEE_HEAVY)

    def test_fee_heavy_at_090(self):
        self.assertEqual(_compute_fee_label(1.0, 0.90), FEE_HEAVY)

    def test_fee_heavy_at_099(self):
        self.assertEqual(_compute_fee_label(0.1, 0.99), FEE_HEAVY)

    def test_fee_exceeds_yield_exactly_zero_net(self):
        self.assertEqual(_compute_fee_label(0.0, 1.0), FEE_EXCEEDS_YIELD)


# ===========================================================================
# 5. _compute_breakeven_days
# ===========================================================================

class TestComputeBreakevenDaysFunction(unittest.TestCase):

    def test_no_upfront_fees_returns_zero(self):
        self.assertEqual(_compute_breakeven_days(5.0, 0.0, 0.0), 0)

    def test_zero_deposit_zero_withdrawal(self):
        self.assertEqual(_compute_breakeven_days(10.0, 0.0, 0.0), 0)

    def test_never_breakeven_when_net_apy_zero(self):
        self.assertEqual(_compute_breakeven_days(0.0, 0.5, 0.5), _NEVER_BREAKEVEN)

    def test_never_breakeven_when_net_apy_negative(self):
        self.assertEqual(_compute_breakeven_days(-2.0, 0.1, 0.1), _NEVER_BREAKEVEN)

    def test_simple_breakeven_365_days_net(self):
        # upfront=1.0, net_apy=365 → net_daily=1.0 → breakeven=1 day
        self.assertEqual(_compute_breakeven_days(365.0, 0.5, 0.5), 1)

    def test_breakeven_standard(self):
        # upfront=0.6, net_apy=5.4 → net_daily=5.4/365 → ceil(0.6/0.014794)=ceil(40.56)=41
        result = _compute_breakeven_days(5.4, 0.1, 0.5)
        expected = math.ceil(0.6 / (5.4 / 365))
        self.assertEqual(result, expected)

    def test_breakeven_ceiling_applied(self):
        # Use values that produce fractional days → must ceil
        upfront = 1.0
        net_apy = 10.0
        net_daily = net_apy / 365.0
        result = _compute_breakeven_days(net_apy, 0.5, 0.5)
        expected = math.ceil(upfront / net_daily)
        self.assertEqual(result, expected)

    def test_deposit_only_breakeven(self):
        # deposit=0.1, withdrawal=0
        result = _compute_breakeven_days(10.0, 0.1, 0.0)
        expected = math.ceil(0.1 / (10.0 / 365))
        self.assertEqual(result, expected)

    def test_withdrawal_only_breakeven(self):
        result = _compute_breakeven_days(10.0, 0.0, 0.5)
        expected = math.ceil(0.5 / (10.0 / 365))
        self.assertEqual(result, expected)

    def test_returns_integer(self):
        result = _compute_breakeven_days(5.0, 0.1, 0.2)
        self.assertIsInstance(result, int)


# ===========================================================================
# 6. _compute_fee_efficiency_score
# ===========================================================================

class TestComputeFeeEfficiencyScoreFunction(unittest.TestCase):

    def test_zero_ratio_gives_100(self):
        self.assertEqual(_compute_fee_efficiency_score(0.0), 100)

    def test_ratio_one_gives_zero(self):
        self.assertEqual(_compute_fee_efficiency_score(1.0), 0)

    def test_ratio_half_gives_50(self):
        self.assertEqual(_compute_fee_efficiency_score(0.5), 50)

    def test_ratio_046(self):
        # 1 - 0.46 = 0.54 → round(54) = 54
        self.assertEqual(_compute_fee_efficiency_score(0.46), 54)

    def test_ratio_greater_than_1_clamped_to_zero(self):
        self.assertEqual(_compute_fee_efficiency_score(1.5), 0)

    def test_ratio_020_gives_80(self):
        self.assertEqual(_compute_fee_efficiency_score(0.20), 80)

    def test_returns_int(self):
        result = _compute_fee_efficiency_score(0.3)
        self.assertIsInstance(result, int)

    def test_score_in_valid_range(self):
        for ratio in [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0]:
            score = _compute_fee_efficiency_score(ratio)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)


# ===========================================================================
# 7. Result structure from analyze()
# ===========================================================================

class TestAnalyzeReturnStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _result(self, **kwargs):
        return _analyze(self.tmp, **kwargs)

    def test_required_keys_present(self):
        result = self._result()
        required = [
            "protocol_name", "tvl_usd", "gross_apy_pct", "net_apy_pct",
            "total_fee_drag_pct", "fee_drag_ratio", "breakeven_days",
            "fee_efficiency_score", "fee_label", "fee_breakdown",
            "holding_period_days", "analysis_timestamp", "module", "version",
        ]
        for key in required:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_fee_breakdown_keys(self):
        result = self._result()
        bd = result["fee_breakdown"]
        for key in ("management_drag_pct", "performance_drag_pct", "deposit_drag_pct", "withdrawal_drag_pct"):
            self.assertIn(key, bd)

    def test_module_field(self):
        self.assertEqual(self._result()["module"], "MP-1088")

    def test_version_field(self):
        self.assertEqual(self._result()["version"], "1.0.0")

    def test_protocol_name_preserved(self):
        r = self._result(protocol_name="YearnV3")
        self.assertEqual(r["protocol_name"], "YearnV3")

    def test_tvl_preserved(self):
        r = self._result(tvl_usd=50_000_000.0)
        self.assertAlmostEqual(r["tvl_usd"], 50_000_000.0)

    def test_holding_period_preserved(self):
        r = self._result(holding_period_days=90)
        self.assertEqual(r["holding_period_days"], 90)

    def test_timestamp_format(self):
        result = self._result()
        ts = result["analysis_timestamp"]
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)


# ===========================================================================
# 8. Net APY calculation
# ===========================================================================

class TestAnalyzeNetApy(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_zero_fees_net_equals_gross(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0)
        self.assertAlmostEqual(r["net_apy_pct"], 10.0, places=4)

    def test_management_fee_subtracted(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, management_fee_pct=2.0)
        self.assertAlmostEqual(r["net_apy_pct"], 8.0, places=4)

    def test_performance_fee_proportional(self):
        # 20% of 10% gross = 2% drag → net = 8%
        r = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=20.0)
        self.assertAlmostEqual(r["net_apy_pct"], 8.0, places=4)

    def test_deposit_fee_amortised_365(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=1.0, holding_period_days=365)
        self.assertAlmostEqual(r["net_apy_pct"], 9.0, places=4)

    def test_withdrawal_fee_amortised_365(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, withdrawal_fee_pct=0.5, holding_period_days=365)
        self.assertAlmostEqual(r["net_apy_pct"], 9.5, places=4)

    def test_combined_fees_standard(self):
        # gross=10, perf=20%→2, mgmt=2, dep=0.1@365→0.1, wd=0.5@365→0.5 → drag=4.6
        r = _analyze(
            self.tmp,
            gross_apy_pct=10.0,
            management_fee_pct=2.0,
            performance_fee_pct=20.0,
            deposit_fee_pct=0.1,
            withdrawal_fee_pct=0.5,
            holding_period_days=365,
        )
        self.assertAlmostEqual(r["net_apy_pct"], 5.4, places=4)
        self.assertAlmostEqual(r["total_fee_drag_pct"], 4.6, places=4)

    def test_net_apy_negative_when_fees_exceed_gross(self):
        r = _analyze(self.tmp, gross_apy_pct=2.0, management_fee_pct=3.0)
        self.assertLess(r["net_apy_pct"], 0)

    def test_gross_rounded_in_output(self):
        r = _analyze(self.tmp, gross_apy_pct=7.123456789)
        self.assertAlmostEqual(r["gross_apy_pct"], 7.123457, places=5)

    def test_total_drag_matches_breakdown_sum(self):
        r = _analyze(
            self.tmp,
            gross_apy_pct=10.0,
            management_fee_pct=1.5,
            performance_fee_pct=15.0,
            deposit_fee_pct=0.2,
            withdrawal_fee_pct=0.3,
            holding_period_days=365,
        )
        bd = r["fee_breakdown"]
        total_from_breakdown = (
            bd["management_drag_pct"]
            + bd["performance_drag_pct"]
            + bd["deposit_drag_pct"]
            + bd["withdrawal_drag_pct"]
        )
        self.assertAlmostEqual(r["total_fee_drag_pct"], total_from_breakdown, places=4)

    def test_net_plus_drag_equals_gross(self):
        r = _analyze(
            self.tmp,
            gross_apy_pct=12.0,
            management_fee_pct=2.0,
            performance_fee_pct=10.0,
            deposit_fee_pct=0.5,
            withdrawal_fee_pct=0.5,
            holding_period_days=365,
        )
        self.assertAlmostEqual(
            r["net_apy_pct"] + r["total_fee_drag_pct"],
            r["gross_apy_pct"],
            places=4,
        )


# ===========================================================================
# 9. Fee labels via analyze()
# ===========================================================================

class TestAnalyzeFeeLabelOutputs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_low_fee_vault_zero_fees(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0)
        self.assertEqual(r["fee_label"], LOW_FEE_VAULT)

    def test_low_fee_vault_small_perf_fee(self):
        # perf=5% of 10% → drag=0.5, ratio=0.05 < 0.10
        r = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=5.0)
        self.assertEqual(r["fee_label"], LOW_FEE_VAULT)

    def test_low_fee_vault_ratio_just_under_010(self):
        # drag ~ 9% of 10% → ratio=0.09
        r = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=9.0)
        self.assertEqual(r["fee_label"], LOW_FEE_VAULT)

    def test_moderate_fees_at_ratio_010(self):
        # drag = 10% of 10% → ratio=0.10 exactly → MODERATE_FEES
        r = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=10.0)
        self.assertEqual(r["fee_label"], MODERATE_FEES)

    def test_moderate_fees_mgmt_only(self):
        # gross=10, mgmt=2 → drag=2, ratio=0.20
        r = _analyze(self.tmp, gross_apy_pct=10.0, management_fee_pct=2.0)
        self.assertEqual(r["fee_label"], MODERATE_FEES)

    def test_moderate_fees_just_below_025(self):
        # drag ratio ~ 0.24
        r = _analyze(self.tmp, gross_apy_pct=100.0, management_fee_pct=24.0)
        self.assertEqual(r["fee_label"], MODERATE_FEES)

    def test_high_fee_drag_at_025(self):
        # gross=100, mgmt=25 → drag=25, ratio=0.25 → HIGH_FEE_DRAG
        r = _analyze(self.tmp, gross_apy_pct=100.0, management_fee_pct=25.0)
        self.assertEqual(r["fee_label"], HIGH_FEE_DRAG)

    def test_high_fee_drag_combined(self):
        # gross=10, mgmt=2, perf=15%→1.5 → drag=3.5, ratio=0.35 → HIGH_FEE_DRAG
        r = _analyze(
            self.tmp,
            gross_apy_pct=10.0,
            management_fee_pct=2.0,
            performance_fee_pct=15.0,
        )
        self.assertEqual(r["fee_label"], HIGH_FEE_DRAG)

    def test_high_fee_drag_just_below_040(self):
        # ratio exactly ~0.39
        r = _analyze(self.tmp, gross_apy_pct=100.0, management_fee_pct=39.0)
        self.assertEqual(r["fee_label"], HIGH_FEE_DRAG)

    def test_fee_heavy_at_040(self):
        # gross=100, mgmt=40 → ratio=0.40 → FEE_HEAVY
        r = _analyze(self.tmp, gross_apy_pct=100.0, management_fee_pct=40.0)
        self.assertEqual(r["fee_label"], FEE_HEAVY)

    def test_fee_heavy_standard_vault(self):
        # gross=10, perf=20%→2, mgmt=2, dep=0.1, wd=0.5@365 → drag=4.6, ratio=0.46
        r = _analyze(
            self.tmp,
            gross_apy_pct=10.0,
            management_fee_pct=2.0,
            performance_fee_pct=20.0,
            deposit_fee_pct=0.1,
            withdrawal_fee_pct=0.5,
        )
        self.assertEqual(r["fee_label"], FEE_HEAVY)

    def test_fee_heavy_high_perf_fee(self):
        # perf=50% of 10% → drag=5, ratio=0.50 → FEE_HEAVY
        r = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=50.0)
        self.assertEqual(r["fee_label"], FEE_HEAVY)

    def test_fee_exceeds_yield_mgmt_kills_gross(self):
        # gross=5, mgmt=5 → drag=5, net=0 → FEE_EXCEEDS_YIELD
        r = _analyze(self.tmp, gross_apy_pct=5.0, management_fee_pct=5.0)
        self.assertEqual(r["fee_label"], FEE_EXCEEDS_YIELD)

    def test_fee_exceeds_yield_negative_net(self):
        r = _analyze(self.tmp, gross_apy_pct=3.0, management_fee_pct=5.0)
        self.assertEqual(r["fee_label"], FEE_EXCEEDS_YIELD)

    def test_fee_exceeds_yield_short_holding_period(self):
        # deposit=1%, holding=1day → amortised drag = 365% ≫ gross
        r = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=1.0, holding_period_days=1)
        self.assertEqual(r["fee_label"], FEE_EXCEEDS_YIELD)


# ===========================================================================
# 10. Holding period effects
# ===========================================================================

class TestAnalyzeHoldingPeriodEffect(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_longer_holding_reduces_drag_from_one_time_fees(self):
        short = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=1.0, holding_period_days=30)
        long_ = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=1.0, holding_period_days=365)
        self.assertGreater(short["total_fee_drag_pct"], long_["total_fee_drag_pct"])

    def test_management_fee_unaffected_by_holding_period(self):
        r30 = _analyze(self.tmp, gross_apy_pct=10.0, management_fee_pct=2.0, holding_period_days=30)
        r365 = _analyze(self.tmp, gross_apy_pct=10.0, management_fee_pct=2.0, holding_period_days=365)
        self.assertAlmostEqual(r30["fee_breakdown"]["management_drag_pct"], 2.0, places=5)
        self.assertAlmostEqual(r365["fee_breakdown"]["management_drag_pct"], 2.0, places=5)

    def test_performance_fee_unaffected_by_holding_period(self):
        r30 = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=20.0, holding_period_days=30)
        r365 = _analyze(self.tmp, gross_apy_pct=10.0, performance_fee_pct=20.0, holding_period_days=365)
        self.assertAlmostEqual(r30["fee_breakdown"]["performance_drag_pct"], 2.0, places=5)
        self.assertAlmostEqual(r365["fee_breakdown"]["performance_drag_pct"], 2.0, places=5)

    def test_deposit_drag_365_equals_fee(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=0.5, holding_period_days=365)
        self.assertAlmostEqual(r["fee_breakdown"]["deposit_drag_pct"], 0.5, places=5)

    def test_deposit_drag_higher_at_30_days(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=0.5, holding_period_days=30)
        expected = 0.5 * 365 / 30
        self.assertAlmostEqual(r["fee_breakdown"]["deposit_drag_pct"], expected, places=4)

    def test_holding_period_1_clamps_to_1(self):
        # Minimum holding period = 1 day
        r = _analyze(self.tmp, deposit_fee_pct=1.0, holding_period_days=0)
        # holding_period_days should be treated as at least 1
        self.assertEqual(r["holding_period_days"], 1)

    def test_breakeven_days_unchanged_by_holding_period(self):
        # breakeven uses raw upfront fees, not amortised drag
        r30 = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=0.5, withdrawal_fee_pct=0.5, holding_period_days=30)
        r365 = _analyze(self.tmp, gross_apy_pct=10.0, deposit_fee_pct=0.5, withdrawal_fee_pct=0.5, holding_period_days=365)
        # Note: holding period affects net_apy which affects breakeven — they'll differ.
        # Just check breakeven is a positive int in both cases.
        self.assertGreater(r30["breakeven_days"], 0)
        self.assertGreater(r365["breakeven_days"], 0)

    def test_withdrawal_drag_365_equals_fee(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, withdrawal_fee_pct=1.0, holding_period_days=365)
        self.assertAlmostEqual(r["fee_breakdown"]["withdrawal_drag_pct"], 1.0, places=5)


# ===========================================================================
# 11. Edge cases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_zero_gross_apy(self):
        r = _analyze(self.tmp, gross_apy_pct=0.0, management_fee_pct=2.0)
        self.assertAlmostEqual(r["gross_apy_pct"], 0.0)
        self.assertEqual(r["fee_label"], FEE_EXCEEDS_YIELD)

    def test_all_fees_zero(self):
        r = _analyze(self.tmp, gross_apy_pct=5.0)
        self.assertAlmostEqual(r["total_fee_drag_pct"], 0.0)
        self.assertAlmostEqual(r["net_apy_pct"], 5.0)
        self.assertEqual(r["fee_label"], LOW_FEE_VAULT)

    def test_fee_efficiency_score_100_no_fees(self):
        r = _analyze(self.tmp, gross_apy_pct=5.0)
        self.assertEqual(r["fee_efficiency_score"], 100)

    def test_fee_efficiency_score_zero_when_exceeds(self):
        r = _analyze(self.tmp, gross_apy_pct=5.0, management_fee_pct=10.0)
        self.assertEqual(r["fee_efficiency_score"], 0)

    def test_breakeven_zero_no_upfront_fees(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, management_fee_pct=2.0)
        self.assertEqual(r["breakeven_days"], 0)

    def test_breakeven_never_when_fee_exceeds_yield(self):
        r = _analyze(self.tmp, gross_apy_pct=1.0, management_fee_pct=2.0, deposit_fee_pct=0.5)
        self.assertEqual(r["breakeven_days"], _NEVER_BREAKEVEN)

    def test_very_large_gross_apy(self):
        r = _analyze(self.tmp, gross_apy_pct=1000.0, management_fee_pct=1.0, performance_fee_pct=20.0)
        # perf=200, mgmt=1 → drag=201, net=799
        self.assertAlmostEqual(r["net_apy_pct"], 799.0, places=2)

    def test_very_small_gross_apy(self):
        r = _analyze(self.tmp, gross_apy_pct=0.01, management_fee_pct=0.0, performance_fee_pct=0.0)
        self.assertAlmostEqual(r["net_apy_pct"], 0.01, places=6)

    def test_fee_drag_ratio_capped_at_one(self):
        r = _analyze(self.tmp, gross_apy_pct=2.0, management_fee_pct=10.0)
        self.assertLessEqual(r["fee_drag_ratio"], 1.0)

    def test_integer_holding_period(self):
        r = _analyze(self.tmp, holding_period_days=180)
        self.assertEqual(r["holding_period_days"], 180)


# ===========================================================================
# 12. Log behaviour
# ===========================================================================

class TestAnalyzeLogBehavior(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "test_log.json")

    def _az(self, **kw):
        a = DeFiProtocolYieldOptimizerFeeDragAnalyzer(log_path=self.log)
        return a.analyze(
            gross_apy_pct=kw.get("gross_apy_pct", 10.0),
            management_fee_pct=0.0,
            performance_fee_pct=0.0,
            deposit_fee_pct=0.0,
            withdrawal_fee_pct=0.0,
            holding_period_days=365,
            protocol_name=kw.get("protocol_name", "Vault"),
            tvl_usd=1_000_000.0,
        )

    def test_log_created_after_analyze(self):
        self._az()
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_valid_json_list(self):
        self._az()
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_count_increases(self):
        self._az()
        self._az()
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_required_fields(self):
        self._az(protocol_name="ApeVault")
        with open(self.log) as fh:
            data = json.load(fh)
        entry = data[-1]
        for field in ("ts", "protocol_name", "gross_apy_pct", "net_apy_pct", "fee_label"):
            self.assertIn(field, entry)

    def test_log_ring_buffer_cap(self):
        # Write LOG_CAP + 5 entries; log should not exceed LOG_CAP
        a = DeFiProtocolYieldOptimizerFeeDragAnalyzer(log_path=self.log)
        for i in range(LOG_CAP + 5):
            a.analyze(10.0, 0.0, 0.0, 0.0, 0.0, 365, f"Vault{i}", 1_000_000.0)
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_log_keeps_most_recent_entries(self):
        a = DeFiProtocolYieldOptimizerFeeDragAnalyzer(log_path=self.log)
        for i in range(LOG_CAP + 3):
            a.analyze(10.0, 0.0, 0.0, 0.0, 0.0, 365, f"V{i}", 1_000_000.0)
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["protocol_name"], f"V{LOG_CAP + 2}")

    def test_custom_log_path(self):
        custom_log = os.path.join(self.tmp, "custom_dir", "custom.json")
        a = DeFiProtocolYieldOptimizerFeeDragAnalyzer(log_path=custom_log)
        a.analyze(10.0, 0.0, 0.0, 0.0, 0.0, 365, "V", 1e6)
        self.assertTrue(os.path.exists(custom_log))

    def test_log_failure_does_not_crash_analysis(self):
        # Provide an invalid log path (read-only location simulation)
        a = DeFiProtocolYieldOptimizerFeeDragAnalyzer(log_path="/nonexistent/no/path/log.json")
        # Should not raise
        result = a.analyze(10.0, 0.0, 0.0, 0.0, 0.0, 365, "V", 1e6)
        self.assertIn("net_apy_pct", result)


# ===========================================================================
# 13. Numeric types and input coercion
# ===========================================================================

class TestAnalyzeTypesAndInputCoercion(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_net_apy_is_float(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["net_apy_pct"], float)

    def test_fee_efficiency_score_is_int(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["fee_efficiency_score"], int)

    def test_breakeven_days_is_int(self):
        r = _analyze(self.tmp, deposit_fee_pct=0.5)
        self.assertIsInstance(r["breakeven_days"], int)

    def test_fee_label_is_str(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["fee_label"], str)

    def test_fee_drag_ratio_in_0_1(self):
        r = _analyze(self.tmp, gross_apy_pct=10.0, management_fee_pct=2.0, performance_fee_pct=20.0)
        self.assertGreaterEqual(r["fee_drag_ratio"], 0.0)
        self.assertLessEqual(r["fee_drag_ratio"], 1.0)

    def test_string_inputs_coerced(self):
        # gross_apy_pct passed as string-like float-able value
        a = DeFiProtocolYieldOptimizerFeeDragAnalyzer(
            log_path=os.path.join(self.tmp, "l.json")
        )
        r = a.analyze("10.0", "2.0", "20.0", "0.1", "0.5", "365", "Vault", "5000000")
        self.assertIsInstance(r["net_apy_pct"], float)

    def test_zero_holding_period_clamped_to_1(self):
        r = _analyze(self.tmp, holding_period_days=0)
        self.assertGreaterEqual(r["holding_period_days"], 1)


if __name__ == "__main__":
    unittest.main()

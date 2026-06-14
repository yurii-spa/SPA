"""
Tests for MP-674 StakingRewardsOptimizer.
≥65 unittest cases. Pure stdlib (unittest only).
Run: python3 -m unittest spa_core.tests.test_staking_rewards_optimizer -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.staking_rewards_optimizer import (
    CANDIDATE_FREQS,
    MAX_ENTRIES,
    StakingOptimizationReport,
    StakingPosition,
    StakingRewardsOptimizer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(**kwargs) -> StakingPosition:
    """Build a StakingPosition with sensible defaults, override via kwargs."""
    defaults = dict(
        position_id="test-pos",
        protocol="TestProtocol",
        token="TKN",
        staked_amount_usd=10_000.0,
        base_apy_pct=10.0,
        compound_frequency=12,
        gas_cost_per_compound_usd=5.0,
        lock_up_days=0,
        slash_risk_pct=1.0,
        validator_uptime_pct=99.0,
    )
    defaults.update(kwargs)
    return StakingPosition(**defaults)


OPT = StakingRewardsOptimizer()


# ===========================================================================
# 1. _net_apy_for_freq
# ===========================================================================

class TestNetApyForFreq(unittest.TestCase):

    def test_freq1_no_gas_equals_base_apy(self):
        """freq=1, no gas: compounded = (1+0.1)^1 - 1 = 10.0%"""
        result = OPT._net_apy_for_freq(10.0, 1, 0.0, 10_000.0)
        self.assertAlmostEqual(result, 10.0, places=3)

    def test_freq12_compounding_beats_simple(self):
        """Monthly compounding should exceed 10% raw."""
        result = OPT._net_apy_for_freq(10.0, 12, 0.0, 10_000.0)
        self.assertGreater(result, 10.0)

    def test_freq365_highest_no_gas(self):
        """Daily compounding (no gas) > monthly compounding."""
        daily = OPT._net_apy_for_freq(10.0, 365, 0.0, 10_000.0)
        monthly = OPT._net_apy_for_freq(10.0, 12, 0.0, 10_000.0)
        self.assertGreater(daily, monthly)

    def test_high_gas_kills_net_apy(self):
        """Gas cost > staked amount forces deeply negative APY."""
        result = OPT._net_apy_for_freq(5.0, 365, 100.0, 1_000.0)
        self.assertLess(result, 0.0)

    def test_zero_gas_positive_apy(self):
        """Zero gas, positive base APY → positive net APY."""
        result = OPT._net_apy_for_freq(8.0, 26, 0.0, 50_000.0)
        self.assertGreater(result, 0.0)

    def test_return_rounded_to_4dp(self):
        """Result should have at most 4 decimal places."""
        result = OPT._net_apy_for_freq(7.5, 4, 2.0, 5_000.0)
        # Verify rounding by comparing string representation
        self.assertEqual(result, round(result, 4))

    def test_small_gas_minimal_drag(self):
        """$1 gas on $1M position: drag negligible."""
        result = OPT._net_apy_for_freq(10.0, 12, 1.0, 1_000_000.0)
        # Monthly compounded = ~10.47%, gas drag = 12/1M*100 = 0.0012%
        self.assertAlmostEqual(result, 10.47, delta=0.05)

    def test_zero_base_apy_no_gain(self):
        """0% base APY → only gas drag → negative net APY if gas > 0."""
        result = OPT._net_apy_for_freq(0.0, 12, 10.0, 10_000.0)
        self.assertLess(result, 0.0)

    def test_zero_base_apy_zero_gas_zero_return(self):
        """0% base APY + 0 gas → 0.0%"""
        result = OPT._net_apy_for_freq(0.0, 1, 0.0, 10_000.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_freq52_no_gas_higher_than_monthly(self):
        """Weekly > monthly when no gas."""
        weekly = OPT._net_apy_for_freq(10.0, 52, 0.0, 10_000.0)
        monthly = OPT._net_apy_for_freq(10.0, 12, 0.0, 10_000.0)
        self.assertGreater(weekly, monthly)

    def test_gas_exactly_1pct_position_annual(self):
        """Gas=$100/compound, freq=1, position=$10k: annual drag = 1%."""
        # compounded = 10%, gas drag = 100/10000*100 = 1%
        result = OPT._net_apy_for_freq(10.0, 1, 100.0, 10_000.0)
        self.assertAlmostEqual(result, 9.0, places=3)

    def test_staked_amount_zero_no_gas_drag(self):
        """If staked_amount=0, gas drag is treated as 0 (avoid div by zero)."""
        # Should not raise
        result = OPT._net_apy_for_freq(10.0, 12, 10.0, 0.0)
        # With staked=0, gas_drag=0, so result = compounded apy
        self.assertAlmostEqual(result, OPT._net_apy_for_freq(10.0, 12, 0.0, 0.0), places=4)

    def test_very_high_apy_compounding(self):
        """30% APY compounded 365x should be much higher than 30%."""
        daily = OPT._net_apy_for_freq(30.0, 365, 0.0, 100_000.0)
        self.assertGreater(daily, 34.0)  # e ≈ 34.98%

    def test_negative_net_apy_when_gas_exceeds_yield(self):
        """Gas $50 * 52 = $2600 on $10k position → -26% drag vs ~5% yield → negative."""
        result = OPT._net_apy_for_freq(5.0, 52, 50.0, 10_000.0)
        self.assertLess(result, 0.0)


# ===========================================================================
# 2. _optimal_freq
# ===========================================================================

class TestOptimalFreq(unittest.TestCase):

    def test_zero_gas_returns_365(self):
        """No gas cost → maximum compounding (daily) is always best."""
        freq = OPT._optimal_freq(10.0, 0.0, 10_000.0)
        self.assertEqual(freq, 365)

    def test_high_gas_returns_low_freq(self):
        """$500 per compound on $10k → very high gas → freq=1 optimal."""
        freq = OPT._optimal_freq(10.0, 500.0, 10_000.0)
        self.assertEqual(freq, 1)

    def test_staked_amount_zero_returns_1(self):
        """Edge case: staked_amount=0 → return 1."""
        freq = OPT._optimal_freq(10.0, 5.0, 0.0)
        self.assertEqual(freq, 1)

    def test_optimal_in_candidate_list(self):
        """Result must always be one of CANDIDATE_FREQS."""
        for gas in [0.0, 1.0, 10.0, 100.0]:
            freq = OPT._optimal_freq(8.0, gas, 10_000.0)
            self.assertIn(freq, CANDIDATE_FREQS)

    def test_moderate_gas_medium_freq(self):
        """$25 gas on $50k → compounding a few times/year optimal."""
        freq = OPT._optimal_freq(5.0, 25.0, 50_000.0)
        # At $25/compound, annual gas at freq=365: $9125 = 18.25% drag. At freq=12: $300 = 0.6%
        self.assertLess(freq, 365)

    def test_zero_base_apy_no_gas(self):
        """0% base APY + 0 gas → any freq gives 0%, first candidate (1) returned."""
        # All freqs give 0.0, so best_freq stays at 1
        freq = OPT._optimal_freq(0.0, 0.0, 10_000.0)
        self.assertEqual(freq, 1)

    def test_high_apy_low_gas_returns_high_freq(self):
        """High APY + negligible gas → daily compounding wins."""
        freq = OPT._optimal_freq(20.0, 0.01, 100_000.0)
        self.assertEqual(freq, 365)

    def test_gas_equals_zero_returns_high_freq(self):
        """With zero gas, a high compounding frequency is always optimal (>= 52x/yr)."""
        for apy in [1.0, 5.0, 15.0, 30.0]:
            freq = OPT._optimal_freq(apy, 0.0, 10_000.0)
            self.assertGreaterEqual(freq, 52,
                f"Expected high-freq for APY={apy}%, got {freq}")


# ===========================================================================
# 3. _liquidity_penalty
# ===========================================================================

class TestLiquidityPenalty(unittest.TestCase):

    def test_zero_lockup_is_none(self):
        self.assertEqual(OPT._liquidity_penalty(0), "NONE")

    def test_1_day_is_low(self):
        self.assertEqual(OPT._liquidity_penalty(1), "LOW")

    def test_7_days_is_low(self):
        self.assertEqual(OPT._liquidity_penalty(7), "LOW")

    def test_8_days_is_medium(self):
        self.assertEqual(OPT._liquidity_penalty(8), "MEDIUM")

    def test_30_days_is_medium(self):
        self.assertEqual(OPT._liquidity_penalty(30), "MEDIUM")

    def test_31_days_is_high(self):
        self.assertEqual(OPT._liquidity_penalty(31), "HIGH")

    def test_90_days_is_high(self):
        self.assertEqual(OPT._liquidity_penalty(90), "HIGH")

    def test_365_days_is_high(self):
        self.assertEqual(OPT._liquidity_penalty(365), "HIGH")


# ===========================================================================
# 4. _recommendation
# ===========================================================================

class TestRecommendation(unittest.TestCase):

    def test_negative_uptime_adjusted_returns_unstake(self):
        self.assertEqual(OPT._recommendation(12, 12, -0.1), "UNSTAKE")

    def test_zero_uptime_adjusted_returns_unstake(self):
        # 0 is not negative
        result = OPT._recommendation(12, 12, 0.0)
        self.assertNotEqual(result, "UNSTAKE")

    def test_optimal_much_higher_than_current_increase(self):
        """optimal=52, current=12 → 52 > 12*1.5=18 → INCREASE_FREQUENCY"""
        self.assertEqual(OPT._recommendation(52, 12, 5.0), "INCREASE_FREQUENCY")

    def test_optimal_much_lower_than_current_decrease(self):
        """optimal=1, current=52 → 1 < 52*0.5=26 → DECREASE_FREQUENCY"""
        self.assertEqual(OPT._recommendation(1, 52, 5.0), "DECREASE_FREQUENCY")

    def test_close_to_current_returns_optimal(self):
        """optimal=12, current=12 → OPTIMAL"""
        self.assertEqual(OPT._recommendation(12, 12, 5.0), "OPTIMAL")

    def test_slightly_above_current_is_optimal(self):
        """optimal=14 (not in candidates, but test logic), current=12:
        14 < 12*1.5=18 → OPTIMAL"""
        self.assertEqual(OPT._recommendation(14, 12, 5.0), "OPTIMAL")

    def test_exactly_15x_boundary_increase(self):
        """optimal=18, current=12 → 18 == 12*1.5 → NOT > 1.5x → OPTIMAL"""
        self.assertEqual(OPT._recommendation(18, 12, 5.0), "OPTIMAL")

    def test_just_above_15x_increase(self):
        """optimal=19, current=12 → 19 > 18 → INCREASE_FREQUENCY"""
        self.assertEqual(OPT._recommendation(19, 12, 5.0), "INCREASE_FREQUENCY")

    def test_zero_compound_frequency_no_crash(self):
        """compound_frequency=0 edge case: should not crash."""
        result = OPT._recommendation(12, 0, 5.0)
        self.assertIn(result, ["INCREASE_FREQUENCY", "DECREASE_FREQUENCY", "OPTIMAL", "UNSTAKE"])


# ===========================================================================
# 5. _compound_schedule
# ===========================================================================

class TestCompoundSchedule(unittest.TestCase):

    def test_freq1_yearly(self):
        self.assertEqual(OPT._compound_schedule(1), "Compound yearly")

    def test_freq365_daily(self):
        self.assertEqual(OPT._compound_schedule(365), "Compound daily")

    def test_freq12_30_days(self):
        # 365 // 12 = 30
        self.assertEqual(OPT._compound_schedule(12), "Compound every 30 days")

    def test_freq4_91_days(self):
        # 365 // 4 = 91
        self.assertEqual(OPT._compound_schedule(4), "Compound every 91 days")

    def test_freq52_7_days(self):
        # 365 // 52 = 7
        self.assertEqual(OPT._compound_schedule(52), "Compound every 7 days")

    def test_freq26_14_days(self):
        # 365 // 26 = 14
        self.assertEqual(OPT._compound_schedule(26), "Compound every 14 days")

    def test_freq2_182_days(self):
        # 365 // 2 = 182
        self.assertEqual(OPT._compound_schedule(2), "Compound every 182 days")

    def test_freq7_52_days(self):
        # 365 // 7 = 52
        self.assertEqual(OPT._compound_schedule(7), "Compound every 52 days")


# ===========================================================================
# 6. _warnings
# ===========================================================================

class TestWarnings(unittest.TestCase):

    def _no_warn_pos(self, **kwargs) -> StakingPosition:
        defaults = dict(
            position_id="w",
            protocol="P",
            token="T",
            staked_amount_usd=100_000.0,
            base_apy_pct=5.0,
            compound_frequency=12,
            gas_cost_per_compound_usd=5.0,
            lock_up_days=0,
            slash_risk_pct=1.0,
            validator_uptime_pct=99.0,
        )
        defaults.update(kwargs)
        return StakingPosition(**defaults)

    def test_no_warnings_clean_position(self):
        pos = self._no_warn_pos()
        self.assertEqual(OPT._warnings(pos), [])

    def test_slash_risk_above_5_triggers_warning(self):
        pos = self._no_warn_pos(slash_risk_pct=6.0)
        warns = OPT._warnings(pos)
        self.assertTrue(any("slash" in w.lower() for w in warns))

    def test_slash_risk_exactly_5_no_warning(self):
        pos = self._no_warn_pos(slash_risk_pct=5.0)
        warns = OPT._warnings(pos)
        self.assertFalse(any("slash" in w.lower() for w in warns))

    def test_slash_risk_very_high(self):
        pos = self._no_warn_pos(slash_risk_pct=20.0)
        warns = OPT._warnings(pos)
        self.assertTrue(any("slash" in w.lower() for w in warns))
        # Should show the numeric value
        self.assertTrue(any("20.0%" in w for w in warns))

    def test_uptime_below_95_triggers_warning(self):
        pos = self._no_warn_pos(validator_uptime_pct=94.9)
        warns = OPT._warnings(pos)
        self.assertTrue(any("uptime" in w.lower() for w in warns))

    def test_uptime_exactly_95_no_warning(self):
        pos = self._no_warn_pos(validator_uptime_pct=95.0)
        warns = OPT._warnings(pos)
        self.assertFalse(any("uptime" in w.lower() for w in warns))

    def test_lockup_above_30_triggers_warning(self):
        pos = self._no_warn_pos(lock_up_days=31)
        warns = OPT._warnings(pos)
        self.assertTrue(any("locked" in w.lower() for w in warns))

    def test_lockup_exactly_30_no_warning(self):
        pos = self._no_warn_pos(lock_up_days=30)
        warns = OPT._warnings(pos)
        self.assertFalse(any("locked" in w.lower() for w in warns))

    def test_gas_above_1pct_position_triggers_warning(self):
        # gas=$200 on $10k → 2% > 1%
        pos = self._no_warn_pos(staked_amount_usd=10_000.0, gas_cost_per_compound_usd=200.0)
        warns = OPT._warnings(pos)
        self.assertTrue(any("gas" in w.lower() for w in warns))

    def test_gas_exactly_1pct_no_warning(self):
        # gas=$100 on $10k = 1%, not >1%
        pos = self._no_warn_pos(staked_amount_usd=10_000.0, gas_cost_per_compound_usd=100.0)
        warns = OPT._warnings(pos)
        self.assertFalse(any("gas" in w.lower() for w in warns))

    def test_multiple_warnings_combined(self):
        pos = self._no_warn_pos(
            slash_risk_pct=10.0,
            validator_uptime_pct=90.0,
            lock_up_days=90,
        )
        warns = OPT._warnings(pos)
        self.assertGreaterEqual(len(warns), 3)


# ===========================================================================
# 7. analyze (integration)
# ===========================================================================

class TestAnalyze(unittest.TestCase):

    def _standard_pos(self) -> StakingPosition:
        return _pos(
            position_id="eth-stake-001",
            base_apy_pct=5.0,
            compound_frequency=12,
            gas_cost_per_compound_usd=10.0,
            staked_amount_usd=50_000.0,
            slash_risk_pct=0.5,
            validator_uptime_pct=99.5,
            lock_up_days=0,
        )

    def test_returns_report_type(self):
        report = OPT.analyze(self._standard_pos())
        self.assertIsInstance(report, StakingOptimizationReport)

    def test_position_id_preserved(self):
        report = OPT.analyze(self._standard_pos())
        self.assertEqual(report.position_id, "eth-stake-001")

    def test_optimal_freq_in_candidates(self):
        report = OPT.analyze(self._standard_pos())
        self.assertIn(report.optimal_compound_freq, CANDIDATE_FREQS)

    def test_current_net_apy_is_float(self):
        report = OPT.analyze(self._standard_pos())
        self.assertIsInstance(report.current_net_apy_pct, float)

    def test_optimal_net_apy_geq_current(self):
        """Optimal should never be worse than current (by definition of optimization)."""
        report = OPT.analyze(self._standard_pos())
        self.assertGreaterEqual(report.optimal_net_apy_pct, report.current_net_apy_pct - 0.0001)

    def test_apy_improvement_computed_correctly(self):
        report = OPT.analyze(self._standard_pos())
        expected = round(report.optimal_net_apy_pct - report.current_net_apy_pct, 4)
        self.assertAlmostEqual(report.apy_improvement_pct, expected, places=4)

    def test_slash_adjusted_lower_than_optimal(self):
        pos = _pos(slash_risk_pct=5.0, base_apy_pct=10.0, gas_cost_per_compound_usd=0.0, staked_amount_usd=100_000.0)
        report = OPT.analyze(pos)
        self.assertLess(report.slash_adjusted_apy_pct, report.optimal_net_apy_pct)

    def test_uptime_adjusted_lower_than_slash_adjusted(self):
        pos = _pos(validator_uptime_pct=90.0, slash_risk_pct=1.0, base_apy_pct=10.0, gas_cost_per_compound_usd=0.0, staked_amount_usd=100_000.0)
        report = OPT.analyze(pos)
        self.assertLess(report.uptime_adjusted_apy_pct, report.slash_adjusted_apy_pct)

    def test_liquidity_penalty_none_for_liquid(self):
        pos = _pos(lock_up_days=0)
        report = OPT.analyze(pos)
        self.assertEqual(report.liquidity_penalty, "NONE")

    def test_liquidity_penalty_high_for_long_lockup(self):
        pos = _pos(lock_up_days=180)
        report = OPT.analyze(pos)
        self.assertEqual(report.liquidity_penalty, "HIGH")

    def test_recommendation_is_valid_string(self):
        report = OPT.analyze(self._standard_pos())
        self.assertIn(report.recommendation, [
            "INCREASE_FREQUENCY", "DECREASE_FREQUENCY", "OPTIMAL", "UNSTAKE"
        ])

    def test_compound_schedule_not_empty(self):
        report = OPT.analyze(self._standard_pos())
        self.assertGreater(len(report.compound_schedule), 0)

    def test_warnings_is_list(self):
        report = OPT.analyze(self._standard_pos())
        self.assertIsInstance(report.warnings, list)

    def test_unstake_when_net_apy_negative(self):
        """Heavy gas drives optimal_net_apy < 0 → UNSTAKE regardless of uptime."""
        # gas=$200/compound, staked=$1000, even at freq=1: drag = 200/1000*100 = 20% > 1% APY
        pos = _pos(
            base_apy_pct=1.0,
            gas_cost_per_compound_usd=200.0,
            staked_amount_usd=1_000.0,
            slash_risk_pct=0.0,
            validator_uptime_pct=100.0,
            compound_frequency=1,
        )
        report = OPT.analyze(pos)
        self.assertEqual(report.recommendation, "UNSTAKE")

    def test_high_slash_risk_reduces_apy(self):
        pos_low_slash = _pos(slash_risk_pct=0.0, base_apy_pct=10.0, gas_cost_per_compound_usd=0.0, staked_amount_usd=100_000.0)
        pos_high_slash = _pos(slash_risk_pct=50.0, base_apy_pct=10.0, gas_cost_per_compound_usd=0.0, staked_amount_usd=100_000.0)
        r_low = OPT.analyze(pos_low_slash)
        r_high = OPT.analyze(pos_high_slash)
        self.assertGreater(r_low.slash_adjusted_apy_pct, r_high.slash_adjusted_apy_pct)


# ===========================================================================
# 8. analyze_batch
# ===========================================================================

class TestAnalyzeBatch(unittest.TestCase):

    def test_empty_list_returns_empty(self):
        result = OPT.analyze_batch([])
        self.assertEqual(result, [])

    def test_single_position(self):
        result = OPT.analyze_batch([_pos(position_id="p1")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].position_id, "p1")

    def test_multiple_positions(self):
        positions = [_pos(position_id=f"pos-{i}") for i in range(5)]
        results = OPT.analyze_batch(positions)
        self.assertEqual(len(results), 5)
        ids = [r.position_id for r in results]
        self.assertEqual(ids, [f"pos-{i}" for i in range(5)])

    def test_all_reports_have_recommendations(self):
        positions = [
            _pos(position_id="a", compound_frequency=1, gas_cost_per_compound_usd=0.0),
            _pos(position_id="b", compound_frequency=365, gas_cost_per_compound_usd=50.0),
        ]
        results = OPT.analyze_batch(positions)
        for r in results:
            self.assertIn(r.recommendation, [
                "INCREASE_FREQUENCY", "DECREASE_FREQUENCY", "OPTIMAL", "UNSTAKE"
            ])


# ===========================================================================
# 9. save_results / load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "test_staking_log.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_history_missing_file_returns_empty(self):
        result = OPT.load_history(self.data_file)
        self.assertEqual(result, [])

    def test_save_creates_file(self):
        report = OPT.analyze(_pos(position_id="save-test"))
        OPT.save_results([report], self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_saved_file_is_valid_json(self):
        report = OPT.analyze(_pos())
        OPT.save_results([report], self.data_file)
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_saved_entry_has_required_fields(self):
        report = OPT.analyze(_pos(position_id="field-check"))
        OPT.save_results([report], self.data_file)
        data = json.loads(self.data_file.read_text())
        entry = data[0]
        self.assertIn("timestamp", entry)
        self.assertIn("position_id", entry)
        self.assertIn("recommendation", entry)
        self.assertIn("compound_schedule", entry)

    def test_load_after_save_round_trips(self):
        report = OPT.analyze(_pos(position_id="rt-test"))
        OPT.save_results([report], self.data_file)
        loaded = OPT.load_history(self.data_file)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["position_id"], "rt-test")

    def test_ring_buffer_keeps_last_max_entries(self):
        # Save MAX_ENTRIES + 10 reports one by one
        for i in range(MAX_ENTRIES + 10):
            report = OPT.analyze(_pos(position_id=f"rb-{i}"))
            OPT.save_results([report], self.data_file)
        loaded = OPT.load_history(self.data_file)
        self.assertLessEqual(len(loaded), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest_entries(self):
        """After overfilling, the newest entries should be present."""
        for i in range(MAX_ENTRIES + 5):
            report = OPT.analyze(_pos(position_id=f"rb-{i}"))
            OPT.save_results([report], self.data_file)
        loaded = OPT.load_history(self.data_file)
        last_id = loaded[-1]["position_id"]
        self.assertEqual(last_id, f"rb-{MAX_ENTRIES + 4}")

    def test_atomic_write_no_tmp_file_remaining(self):
        report = OPT.analyze(_pos())
        OPT.save_results([report], self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_corrupt_json_returns_empty(self):
        self.data_file.write_text("not-valid-json")
        result = OPT.load_history(self.data_file)
        self.assertEqual(result, [])

    def test_save_batch_results(self):
        positions = [_pos(position_id=f"batch-{i}") for i in range(3)]
        reports = OPT.analyze_batch(positions)
        OPT.save_results(reports, self.data_file)
        loaded = OPT.load_history(self.data_file)
        self.assertEqual(len(loaded), 3)


if __name__ == "__main__":
    unittest.main()

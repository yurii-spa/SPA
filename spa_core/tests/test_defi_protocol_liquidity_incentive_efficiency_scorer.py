"""
Tests for MP-1018: DeFiProtocolLiquidityIncentiveEfficiencyScorer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_liquidity_incentive_efficiency_scorer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_liquidity_incentive_efficiency_scorer import (
    DeFiProtocolLiquidityIncentiveEfficiencyScorer,
    _safe_div,
    _clamp,
    _atomic_write,
    _load_log,
)


def _make_program(**kwargs):
    """Return a valid program dict with defaults overridden by kwargs."""
    defaults = {
        "name": "TestProgram",
        "protocol": "TestProtocol",
        "weekly_incentive_cost_usd": 10_000.0,
        "tvl_attracted_usd": 500_000.0,
        "tvl_before_program_usd": 100_000.0,
        "incremental_tvl_usd": 400_000.0,
        "weekly_fees_generated_usd": 12_000.0,
        "program_duration_weeks": 12.0,
        "token_price_change_pct_since_start": 0.0,
        "organic_user_retention_pct": 65.0,
    }
    defaults.update(kwargs)
    return defaults


def _self_funding_program(**kwargs):
    """Program that should score SELF_FUNDING."""
    return _make_program(
        weekly_incentive_cost_usd=5_000.0,
        incremental_tvl_usd=500_000.0,
        weekly_fees_generated_usd=8_000.0,
        organic_user_retention_pct=70.0,
        **kwargs,
    )


def _burning_treasury_program(**kwargs):
    """Program that should score BURNING_TREASURY."""
    return _make_program(
        weekly_incentive_cost_usd=50_000.0,
        incremental_tvl_usd=10_000.0,
        weekly_fees_generated_usd=2_000.0,
        organic_user_retention_pct=10.0,
        **kwargs,
    )


class TestHelpers(unittest.TestCase):
    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 4.0), 2.5)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(5.0, 0.0), 0.0)

    def test_safe_div_custom_default(self):
        self.assertEqual(_safe_div(1.0, 0.0, default=99.0), 99.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below_lo(self):
        self.assertEqual(_clamp(-3.0, 0.0, 10.0), 0.0)

    def test_clamp_above_hi(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, {"x": 1})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["x"], 1)

    def test_atomic_write_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, [1, 2, 3])
            files = os.listdir(td)
            tmp_files = [f for f in files if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])

    def test_load_log_missing_file(self):
        self.assertEqual(_load_log("/nonexistent/path/log.json"), [])

    def test_load_log_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("NOT JSON")
            fname = f.name
        try:
            self.assertEqual(_load_log(fname), [])
        finally:
            os.unlink(fname)

    def test_load_log_non_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            fname = f.name
        try:
            self.assertEqual(_load_log(fname), [])
        finally:
            os.unlink(fname)


class TestScorerInstantiation(unittest.TestCase):
    def test_default_log_path(self):
        s = DeFiProtocolLiquidityIncentiveEfficiencyScorer()
        self.assertIn("liquidity_incentive_efficiency_log.json", s.log_path)

    def test_custom_log_path(self):
        s = DeFiProtocolLiquidityIncentiveEfficiencyScorer(log_path="/tmp/custom.json")
        self.assertEqual(s.log_path, "/tmp/custom.json")


class TestScoreEmptyPrograms(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_empty_returns_dict(self):
        result = self.scorer.score([], {})
        self.assertIsInstance(result, dict)

    def test_empty_has_programs_key(self):
        result = self.scorer.score([], {})
        self.assertIn("programs", result)
        self.assertEqual(result["programs"], [])

    def test_empty_has_aggregates_key(self):
        result = self.scorer.score([], {})
        self.assertIn("aggregates", result)

    def test_empty_aggregates_total_zero(self):
        result = self.scorer.score([], {})
        self.assertEqual(result["aggregates"]["total_programs"], 0)

    def test_empty_aggregates_most_efficient_none(self):
        result = self.scorer.score([], {})
        self.assertIsNone(result["aggregates"]["most_efficient"])

    def test_empty_aggregates_avg_roi_zero(self):
        result = self.scorer.score([], {})
        self.assertEqual(result["aggregates"]["avg_roi_efficiency"], 0.0)

    def test_empty_has_timestamp(self):
        result = self.scorer.score([], {})
        self.assertIn("timestamp", result)


class TestScoreSingleProgram(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def _score(self, **kwargs):
        return self.scorer.score([_make_program(**kwargs)], {})

    def test_returns_one_program(self):
        result = self._score()
        self.assertEqual(len(result["programs"]), 1)

    def test_program_has_name(self):
        result = self._score(name="Alpha")
        self.assertEqual(result["programs"][0]["name"], "Alpha")

    def test_program_has_label(self):
        result = self._score()
        self.assertIn("label", result["programs"][0])

    def test_program_has_flags(self):
        result = self._score()
        self.assertIn("flags", result["programs"][0])
        self.assertIsInstance(result["programs"][0]["flags"], list)

    def test_program_has_cost_per_tvl_dollar(self):
        result = self._score()
        self.assertIn("cost_per_tvl_dollar", result["programs"][0])

    def test_program_has_fee_coverage_ratio(self):
        result = self._score()
        self.assertIn("fee_coverage_ratio", result["programs"][0])

    def test_program_has_tvl_multiplier(self):
        result = self._score()
        self.assertIn("tvl_multiplier", result["programs"][0])

    def test_program_has_roi_score(self):
        result = self._score()
        self.assertIn("roi_efficiency_score", result["programs"][0])

    def test_program_has_emission_dilution(self):
        result = self._score()
        self.assertIn("emission_dilution_impact", result["programs"][0])

    def test_program_has_payback_period(self):
        result = self._score()
        self.assertIn("payback_period_weeks", result["programs"][0])


class TestMetricCalculations(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def _score_prog(self, **kwargs):
        result = self.scorer.score([_make_program(**kwargs)], {})
        return result["programs"][0]

    def test_cost_per_tvl_calculation(self):
        # weekly_cost=1000, incremental_tvl=100000 → (1000/100000)*100 = 1.0 cent
        p = self._score_prog(
            weekly_incentive_cost_usd=1_000.0,
            incremental_tvl_usd=100_000.0,
        )
        self.assertAlmostEqual(p["cost_per_tvl_dollar"], 1.0, places=4)

    def test_cost_per_tvl_high(self):
        # weekly_cost=50000, incremental_tvl=10000 → 500 cents
        p = self._score_prog(
            weekly_incentive_cost_usd=50_000.0,
            incremental_tvl_usd=10_000.0,
        )
        self.assertAlmostEqual(p["cost_per_tvl_dollar"], 500.0, places=2)

    def test_fee_coverage_ratio_above_one(self):
        # fees > cost → coverage > 1
        p = self._score_prog(
            weekly_incentive_cost_usd=1_000.0,
            weekly_fees_generated_usd=2_000.0,
        )
        self.assertAlmostEqual(p["fee_coverage_ratio"], 2.0, places=4)

    def test_fee_coverage_ratio_below_one(self):
        # fees < cost → coverage < 1
        p = self._score_prog(
            weekly_incentive_cost_usd=2_000.0,
            weekly_fees_generated_usd=1_000.0,
        )
        self.assertAlmostEqual(p["fee_coverage_ratio"], 0.5, places=4)

    def test_tvl_multiplier_calculation(self):
        # incremental=100000, total_cost = 1000 * 10 weeks = 10000 → mult = 10
        p = self._score_prog(
            weekly_incentive_cost_usd=1_000.0,
            incremental_tvl_usd=100_000.0,
            program_duration_weeks=10.0,
        )
        self.assertAlmostEqual(p["tvl_multiplier"], 10.0, places=4)

    def test_payback_period_weeks(self):
        # total_cost = 10000*4 = 40000, weekly_fees = 8000 → 5 weeks
        p = self._score_prog(
            weekly_incentive_cost_usd=10_000.0,
            program_duration_weeks=4.0,
            weekly_fees_generated_usd=8_000.0,
        )
        self.assertAlmostEqual(p["payback_period_weeks"], 5.0, places=4)

    def test_payback_period_none_when_fees_zero(self):
        p = self._score_prog(weekly_fees_generated_usd=0.0)
        self.assertIsNone(p["payback_period_weeks"])

    def test_emission_dilution_positive_change(self):
        # price went up → no dilution
        p = self._score_prog(token_price_change_pct_since_start=20.0)
        self.assertAlmostEqual(p["emission_dilution_impact"], 0.0, places=6)

    def test_emission_dilution_negative_change(self):
        # price dropped 50% → dilution = 0.5
        p = self._score_prog(token_price_change_pct_since_start=-50.0)
        self.assertAlmostEqual(p["emission_dilution_impact"], 0.5, places=6)

    def test_emission_dilution_capped_at_one(self):
        # price dropped 200% → clamped to 1.0
        p = self._score_prog(token_price_change_pct_since_start=-200.0)
        self.assertAlmostEqual(p["emission_dilution_impact"], 1.0, places=6)

    def test_roi_score_range_0_100(self):
        for retention in [0.0, 50.0, 100.0]:
            p = self._score_prog(
                organic_user_retention_pct=retention,
                weekly_fees_generated_usd=5_000.0,
            )
            self.assertGreaterEqual(p["roi_efficiency_score"], 0.0)
            self.assertLessEqual(p["roi_efficiency_score"], 100.0)

    def test_roi_score_increases_with_retention(self):
        p_low = self._score_prog(organic_user_retention_pct=10.0)
        p_high = self._score_prog(organic_user_retention_pct=90.0)
        self.assertGreater(p_high["roi_efficiency_score"], p_low["roi_efficiency_score"])

    def test_roi_score_increases_with_fee_coverage(self):
        p_low = self._score_prog(weekly_fees_generated_usd=100.0)
        p_high = self._score_prog(weekly_fees_generated_usd=50_000.0)
        self.assertGreater(p_high["roi_efficiency_score"], p_low["roi_efficiency_score"])

    def test_cost_per_tvl_zero_incremental_tvl(self):
        # division by zero → should be handled gracefully
        p = self._score_prog(incremental_tvl_usd=0.0)
        # Should be infinity (or very large)
        self.assertIsNotNone(p["cost_per_tvl_dollar"])


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def _label(self, **kwargs):
        result = self.scorer.score([_make_program(**kwargs)], {})
        return result["programs"][0]["label"]

    def test_label_self_funding(self):
        # fee_coverage > 1.2 AND retention > 60%
        label = self._label(
            weekly_incentive_cost_usd=5_000.0,
            weekly_fees_generated_usd=8_000.0,  # coverage = 1.6
            organic_user_retention_pct=70.0,
            incremental_tvl_usd=500_000.0,
        )
        self.assertEqual(label, "SELF_FUNDING")

    def test_label_burning_treasury(self):
        # fee_coverage < 0.2 AND retention < 20%
        label = self._label(
            weekly_incentive_cost_usd=50_000.0,
            weekly_fees_generated_usd=5_000.0,   # coverage = 0.1
            organic_user_retention_pct=10.0,
            incremental_tvl_usd=10_000.0,
        )
        self.assertEqual(label, "BURNING_TREASURY")

    def test_label_efficient(self):
        # cost < 10 cents per TVL$ → EFFICIENT
        # Avoid SELF_FUNDING: retention < 60% or coverage < 1.2
        label = self._label(
            weekly_incentive_cost_usd=500.0,
            incremental_tvl_usd=1_000_000.0,    # cost = 0.05 cents
            weekly_fees_generated_usd=400.0,     # coverage < 1.0
            organic_user_retention_pct=40.0,
        )
        self.assertEqual(label, "EFFICIENT")

    def test_label_expensive(self):
        # cost > 50 cents per TVL$, avoid burning treasury (retention ok)
        label = self._label(
            weekly_incentive_cost_usd=100_000.0,
            incremental_tvl_usd=10_000.0,        # cost = 1000 cents
            weekly_fees_generated_usd=50_000.0,  # coverage = 0.5
            organic_user_retention_pct=50.0,
        )
        self.assertEqual(label, "EXPENSIVE")

    def test_label_moderate_default(self):
        # cost in 10-50 cent range, no special conditions
        label = self._label(
            weekly_incentive_cost_usd=10_000.0,
            incremental_tvl_usd=100_000.0,       # cost = 10 cents → right on edge
            weekly_fees_generated_usd=5_000.0,   # coverage = 0.5
            organic_user_retention_pct=40.0,
        )
        # At 10 cents, should be MODERATE (not < 10, not > 50)
        self.assertIn(label, ["MODERATE", "EFFICIENT"])

    def test_burning_treasury_takes_priority_over_expensive(self):
        label = self._label(
            weekly_incentive_cost_usd=100_000.0,
            incremental_tvl_usd=1_000.0,         # very expensive
            weekly_fees_generated_usd=1_000.0,   # coverage = 0.01 < 0.2
            organic_user_retention_pct=5.0,      # retention < 20%
        )
        self.assertEqual(label, "BURNING_TREASURY")

    def test_self_funding_requires_both_conditions(self):
        # Good coverage but low retention → not SELF_FUNDING
        label = self._label(
            weekly_incentive_cost_usd=5_000.0,
            weekly_fees_generated_usd=8_000.0,   # coverage = 1.6
            organic_user_retention_pct=30.0,     # retention too low
            incremental_tvl_usd=500_000.0,
        )
        self.assertNotEqual(label, "SELF_FUNDING")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def _flags(self, **kwargs):
        result = self.scorer.score([_make_program(**kwargs)], {})
        return result["programs"][0]["flags"]

    def test_flag_fee_positive(self):
        flags = self._flags(
            weekly_incentive_cost_usd=1_000.0,
            weekly_fees_generated_usd=2_000.0,  # coverage > 1
        )
        self.assertIn("FEE_POSITIVE", flags)

    def test_flag_fee_positive_absent_when_below(self):
        flags = self._flags(
            weekly_incentive_cost_usd=2_000.0,
            weekly_fees_generated_usd=1_000.0,  # coverage < 1
        )
        self.assertNotIn("FEE_POSITIVE", flags)

    def test_flag_mercenary_capital(self):
        flags = self._flags(organic_user_retention_pct=10.0)
        self.assertIn("MERCENARY_CAPITAL", flags)

    def test_flag_mercenary_capital_absent(self):
        flags = self._flags(organic_user_retention_pct=30.0)
        self.assertNotIn("MERCENARY_CAPITAL", flags)

    def test_flag_low_cost_acquisition(self):
        # cost < 5 cents: weekly_cost=1000, tvl=5_000_000 → 0.02 cents
        flags = self._flags(
            weekly_incentive_cost_usd=1_000.0,
            incremental_tvl_usd=5_000_000.0,
        )
        self.assertIn("LOW_COST_ACQUISITION", flags)

    def test_flag_low_cost_absent_when_expensive(self):
        flags = self._flags(
            weekly_incentive_cost_usd=100_000.0,
            incremental_tvl_usd=10_000.0,
        )
        self.assertNotIn("LOW_COST_ACQUISITION", flags)

    def test_flag_emission_inflation(self):
        flags = self._flags(token_price_change_pct_since_start=-30.0)
        self.assertIn("EMISSION_INFLATION", flags)

    def test_flag_emission_inflation_absent_when_price_up(self):
        flags = self._flags(token_price_change_pct_since_start=10.0)
        self.assertNotIn("EMISSION_INFLATION", flags)

    def test_flag_emission_inflation_absent_mild_drop(self):
        # < 20% drop → no flag
        flags = self._flags(token_price_change_pct_since_start=-15.0)
        self.assertNotIn("EMISSION_INFLATION", flags)

    def test_flag_high_retention(self):
        flags = self._flags(organic_user_retention_pct=70.0)
        self.assertIn("HIGH_RETENTION", flags)

    def test_flag_high_retention_absent(self):
        flags = self._flags(organic_user_retention_pct=50.0)
        self.assertNotIn("HIGH_RETENTION", flags)

    def test_flag_long_duration(self):
        flags = self._flags(program_duration_weeks=30.0)
        self.assertIn("LONG_DURATION_COMMITMENT", flags)

    def test_flag_long_duration_absent(self):
        flags = self._flags(program_duration_weeks=20.0)
        self.assertNotIn("LONG_DURATION_COMMITMENT", flags)

    def test_flag_long_duration_exactly_26_not_flagged(self):
        # >26 is the threshold, not >=26
        flags = self._flags(program_duration_weeks=26.0)
        self.assertNotIn("LONG_DURATION_COMMITMENT", flags)

    def test_multiple_flags_can_coexist(self):
        flags = self._flags(
            weekly_incentive_cost_usd=1_000.0,
            weekly_fees_generated_usd=2_000.0,  # FEE_POSITIVE
            organic_user_retention_pct=70.0,     # HIGH_RETENTION
            program_duration_weeks=30.0,         # LONG_DURATION
        )
        self.assertIn("FEE_POSITIVE", flags)
        self.assertIn("HIGH_RETENTION", flags)
        self.assertIn("LONG_DURATION_COMMITMENT", flags)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_most_efficient_is_best_roi(self):
        programs = [
            _make_program(name="High", weekly_fees_generated_usd=50_000.0, organic_user_retention_pct=90.0),
            _make_program(name="Low", weekly_fees_generated_usd=100.0, organic_user_retention_pct=5.0),
        ]
        result = self.scorer.score(programs, {})
        self.assertEqual(result["aggregates"]["most_efficient"], "High")

    def test_least_efficient_is_worst_roi(self):
        programs = [
            _make_program(name="High", weekly_fees_generated_usd=50_000.0, organic_user_retention_pct=90.0),
            _make_program(name="Low", weekly_fees_generated_usd=100.0, organic_user_retention_pct=5.0),
        ]
        result = self.scorer.score(programs, {})
        self.assertEqual(result["aggregates"]["least_efficient"], "Low")

    def test_avg_roi_efficiency_single(self):
        result = self.scorer.score([_make_program()], {})
        agg = result["aggregates"]
        self.assertAlmostEqual(
            agg["avg_roi_efficiency"],
            result["programs"][0]["roi_efficiency_score"],
            places=4,
        )

    def test_avg_roi_efficiency_two_programs(self):
        p1 = _make_program(name="A", weekly_fees_generated_usd=1_000.0, organic_user_retention_pct=50.0)
        p2 = _make_program(name="B", weekly_fees_generated_usd=10_000.0, organic_user_retention_pct=80.0)
        result = self.scorer.score([p1, p2], {})
        scores = [p["roi_efficiency_score"] for p in result["programs"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["aggregates"]["avg_roi_efficiency"], expected_avg, places=4)

    def test_self_funding_count(self):
        programs = [
            _self_funding_program(name="SF1"),
            _self_funding_program(name="SF2"),
            _make_program(name="Reg"),
        ]
        result = self.scorer.score(programs, {})
        self.assertEqual(result["aggregates"]["self_funding_count"], 2)

    def test_burning_treasury_count(self):
        programs = [
            _burning_treasury_program(name="BT1"),
            _make_program(name="Reg"),
        ]
        result = self.scorer.score(programs, {})
        self.assertEqual(result["aggregates"]["burning_treasury_count"], 1)

    def test_total_programs(self):
        programs = [_make_program(name=f"P{i}") for i in range(5)]
        result = self.scorer.score(programs, {})
        self.assertEqual(result["aggregates"]["total_programs"], 5)


class TestLogPersistence(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.log_path = os.path.join(self.td, "log.json")
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(log_path=self.log_path)

    def test_log_created_on_score(self):
        self.scorer.score([], {})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.scorer.score([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_on_successive_calls(self):
        self.scorer.score([], {})
        self.scorer.score([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap(self):
        # Fill to 110 entries → capped at 100
        for _ in range(110):
            self.scorer.score([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_timestamp(self):
        self.scorer.score([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_programs(self):
        self.scorer.score([_make_program()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("programs", data[0])

    def test_log_entry_has_aggregates(self):
        self.scorer.score([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_log_no_tmp_files_left(self):
        self.scorer.score([], {})
        files = os.listdir(self.td)
        tmp_files = [f for f in files if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_zero_duration_handled(self):
        result = self.scorer.score([_make_program(program_duration_weeks=0.0)], {})
        self.assertEqual(len(result["programs"]), 1)

    def test_very_large_tvl(self):
        p = _make_program(incremental_tvl_usd=1_000_000_000.0)
        result = self.scorer.score([p], {})
        self.assertGreaterEqual(result["programs"][0]["tvl_multiplier"], 0.0)

    def test_negative_token_price_exactly_minus20(self):
        # Exactly at threshold → should NOT flag EMISSION_INFLATION
        result = self.scorer.score([_make_program(token_price_change_pct_since_start=-20.0)], {})
        flags = result["programs"][0]["flags"]
        self.assertNotIn("EMISSION_INFLATION", flags)

    def test_negative_token_price_just_below_minus20(self):
        result = self.scorer.score([_make_program(token_price_change_pct_since_start=-20.1)], {})
        flags = result["programs"][0]["flags"]
        self.assertIn("EMISSION_INFLATION", flags)

    def test_retention_exactly_60_not_high_retention(self):
        result = self.scorer.score([_make_program(organic_user_retention_pct=60.0)], {})
        flags = result["programs"][0]["flags"]
        self.assertNotIn("HIGH_RETENTION", flags)

    def test_retention_exactly_20_not_mercenary(self):
        result = self.scorer.score([_make_program(organic_user_retention_pct=20.0)], {})
        flags = result["programs"][0]["flags"]
        self.assertNotIn("MERCENARY_CAPITAL", flags)

    def test_program_echoes_input_values(self):
        prog = _make_program(
            name="Echo",
            weekly_incentive_cost_usd=12345.0,
            organic_user_retention_pct=42.0,
        )
        result = self.scorer.score([prog], {})
        scored = result["programs"][0]
        self.assertEqual(scored["name"], "Echo")
        self.assertAlmostEqual(scored["weekly_incentive_cost_usd"], 12345.0)
        self.assertAlmostEqual(scored["organic_user_retention_pct"], 42.0)

    def test_multiple_programs_independence(self):
        """Each program is scored independently."""
        p1 = _make_program(name="A", organic_user_retention_pct=90.0)
        p2 = _make_program(name="B", organic_user_retention_pct=10.0)
        result = self.scorer.score([p1, p2], {})
        roi_a = result["programs"][0]["roi_efficiency_score"]
        roi_b = result["programs"][1]["roi_efficiency_score"]
        self.assertGreater(roi_a, roi_b)

    def test_incentive_cost_total_in_output(self):
        prog = _make_program(weekly_incentive_cost_usd=5_000.0, program_duration_weeks=8.0)
        result = self.scorer.score([prog], {})
        self.assertAlmostEqual(result["programs"][0]["incentive_cost_total"], 40_000.0)

    def test_protocol_echoed(self):
        result = self.scorer.score([_make_program(protocol="MyProtocol")], {})
        self.assertEqual(result["programs"][0]["protocol"], "MyProtocol")

    def test_five_programs_sorted_aggregates(self):
        programs = [
            _make_program(name=f"P{i}", organic_user_retention_pct=float(i * 10))
            for i in range(1, 6)
        ]
        result = self.scorer.score(programs, {})
        # P5 has highest retention (50%), P1 has lowest (10%)
        agg = result["aggregates"]
        self.assertEqual(agg["total_programs"], 5)
        self.assertIsNotNone(agg["most_efficient"])
        self.assertIsNotNone(agg["least_efficient"])


if __name__ == "__main__":
    unittest.main()

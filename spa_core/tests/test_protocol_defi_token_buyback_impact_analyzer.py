"""
Tests for MP-1001: ProtocolDeFiTokenBuybackImpactAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_token_buyback_impact_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_token_buyback_impact_analyzer import (
    ProtocolDeFiTokenBuybackImpactAnalyzer,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_program(**overrides) -> dict:
    """Return a minimal valid buyback program dict, with optional overrides."""
    base = {
        "name": "TestBuyback",
        "protocol": "TestProtocol",
        "weekly_buyback_usd": 100_000,
        "buyback_source": "protocol_revenue",
        "token_circulating_supply_usd": 10_000_000,    # market cap
        "token_daily_volume_usd": 5_000_000,
        "token_fdv_usd": 50_000_000,
        "buyback_mechanism": "burn",
        "price_impact_estimate_pct": 0.05,
        "buyback_consistency_score": 85.0,
        "revenue_coverage_ratio": 0.5,
        "burn_pct": 100.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Annualized buyback calculation
# ---------------------------------------------------------------------------

class TestAnnualizedBuyback(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _run(self, prog):
        return self.ana._analyze_program(prog)

    def test_basic_annualized(self):
        prog = make_program(weekly_buyback_usd=100_000)
        result = self._run(prog)
        self.assertAlmostEqual(result["annualized_buyback_usd"], 5_200_000.0, places=0)

    def test_zero_weekly(self):
        prog = make_program(weekly_buyback_usd=0)
        result = self._run(prog)
        self.assertEqual(result["annualized_buyback_usd"], 0.0)

    def test_large_weekly(self):
        prog = make_program(weekly_buyback_usd=1_000_000)
        result = self._run(prog)
        self.assertAlmostEqual(result["annualized_buyback_usd"], 52_000_000.0, places=0)

    def test_fractional_weekly(self):
        prog = make_program(weekly_buyback_usd=7_692.31)
        result = self._run(prog)
        self.assertAlmostEqual(result["annualized_buyback_usd"], 7_692.31 * 52, places=1)

    def test_annualized_key_present(self):
        result = self._run(make_program())
        self.assertIn("annualized_buyback_usd", result)


# ---------------------------------------------------------------------------
# 2. Buyback yield calculation
# ---------------------------------------------------------------------------

class TestBuybackYield(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _run(self, prog):
        return self.ana._analyze_program(prog)

    def test_basic_yield(self):
        prog = make_program(
            weekly_buyback_usd=100_000,
            token_circulating_supply_usd=10_000_000,
        )
        result = self._run(prog)
        # annualized=5_200_000 / 10_000_000 * 100 = 52%
        self.assertAlmostEqual(result["buyback_yield_pct"], 52.0, places=1)

    def test_small_yield(self):
        prog = make_program(
            weekly_buyback_usd=1_000,
            token_circulating_supply_usd=100_000_000,
        )
        result = self._run(prog)
        # 52_000 / 100_000_000 * 100 = 0.052%
        self.assertAlmostEqual(result["buyback_yield_pct"], 0.052, places=3)

    def test_high_yield(self):
        prog = make_program(
            weekly_buyback_usd=500_000,
            token_circulating_supply_usd=1_000_000,
        )
        result = self._run(prog)
        # 26_000_000 / 1_000_000 * 100 = 2600%
        self.assertAlmostEqual(result["buyback_yield_pct"], 2600.0, places=0)

    def test_zero_weekly_zero_yield(self):
        prog = make_program(weekly_buyback_usd=0)
        result = self._run(prog)
        self.assertEqual(result["buyback_yield_pct"], 0.0)

    def test_yield_key_present(self):
        result = self._run(make_program())
        self.assertIn("buyback_yield_pct", result)

    def test_yield_non_negative(self):
        result = self._run(make_program())
        self.assertGreaterEqual(result["buyback_yield_pct"], 0.0)

    def test_yield_scales_with_weekly(self):
        p1 = make_program(weekly_buyback_usd=50_000)
        p2 = make_program(weekly_buyback_usd=100_000)
        r1 = self._run(p1)
        r2 = self._run(p2)
        self.assertLess(r1["buyback_yield_pct"], r2["buyback_yield_pct"])


# ---------------------------------------------------------------------------
# 3. Buyback to volume ratio
# ---------------------------------------------------------------------------

class TestBuybackToVolumeRatio(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _run(self, prog):
        return self.ana._analyze_program(prog)

    def test_basic_ratio(self):
        prog = make_program(
            weekly_buyback_usd=100_000,
            token_daily_volume_usd=1_000_000,
        )
        result = self._run(prog)
        # 100_000 / (1_000_000 * 7) * 100 = 100_000/7_000_000*100 ≈ 1.4286%
        self.assertAlmostEqual(result["buyback_to_volume_ratio"], 1.4286, places=3)

    def test_zero_volume_handled(self):
        prog = make_program(weekly_buyback_usd=100_000, token_daily_volume_usd=0)
        result = self._run(prog)
        # daily_volume clamped to 1
        self.assertGreater(result["buyback_to_volume_ratio"], 0.0)

    def test_high_ratio(self):
        prog = make_program(
            weekly_buyback_usd=700_000,
            token_daily_volume_usd=1_000_000,
        )
        result = self._run(prog)
        # 700_000 / 7_000_000 * 100 = 10%
        self.assertAlmostEqual(result["buyback_to_volume_ratio"], 10.0, places=2)

    def test_ratio_key_present(self):
        result = self._run(make_program())
        self.assertIn("buyback_to_volume_ratio", result)

    def test_ratio_zero_when_no_buyback(self):
        prog = make_program(weekly_buyback_usd=0)
        result = self._run(prog)
        self.assertEqual(result["buyback_to_volume_ratio"], 0.0)


# ---------------------------------------------------------------------------
# 4. Supply reduction rate
# ---------------------------------------------------------------------------

class TestSupplyReductionRate(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _run(self, prog):
        return self.ana._analyze_program(prog)

    def test_basic_supply_reduction(self):
        prog = make_program(
            weekly_buyback_usd=100_000,
            token_circulating_supply_usd=10_000_000,
            burn_pct=100.0,
        )
        result = self._run(prog)
        # annual_burned = 5_200_000 * 1.0 = 5_200_000
        # reduction = 5_200_000 / 10_000_000 * 100 = 52%
        self.assertAlmostEqual(result["supply_reduction_rate_pct"], 52.0, places=1)

    def test_partial_burn(self):
        prog = make_program(
            weekly_buyback_usd=100_000,
            token_circulating_supply_usd=10_000_000,
            burn_pct=50.0,
        )
        result = self._run(prog)
        # 5_200_000 * 0.5 / 10_000_000 * 100 = 26%
        self.assertAlmostEqual(result["supply_reduction_rate_pct"], 26.0, places=1)

    def test_zero_burn_pct(self):
        prog = make_program(burn_pct=0.0)
        result = self._run(prog)
        self.assertEqual(result["supply_reduction_rate_pct"], 0.0)

    def test_supply_reduction_key_present(self):
        result = self._run(make_program())
        self.assertIn("supply_reduction_rate_pct", result)

    def test_non_negative_supply_reduction(self):
        result = self._run(make_program())
        self.assertGreaterEqual(result["supply_reduction_rate_pct"], 0.0)


# ---------------------------------------------------------------------------
# 5. Sustainability score
# ---------------------------------------------------------------------------

class TestSustainabilityScore(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _score(self, source, coverage=0.5, burn_pct=0.0):
        return self.ana._compute_sustainability_score(source, coverage, burn_pct)

    def test_revenue_sustainable_low_coverage(self):
        # coverage <= 1 → base 90
        score = self._score("protocol_revenue", 0.5)
        self.assertGreaterEqual(score, 85)

    def test_revenue_over_coverage_penalty(self):
        # coverage > 1 reduces score
        s_low = self._score("protocol_revenue", 0.5)
        s_high = self._score("protocol_revenue", 2.0)
        self.assertGreater(s_low, s_high)

    def test_external_score(self):
        score = self._score("external")
        self.assertGreaterEqual(score, 55)
        self.assertLessEqual(score, 70)

    def test_treasury_score(self):
        score = self._score("treasury")
        self.assertGreaterEqual(score, 30)
        self.assertLessEqual(score, 50)

    def test_inflation_score_low(self):
        score = self._score("inflation")
        self.assertLess(score, 25)

    def test_burn_bonus_adds_to_score(self):
        s_no_burn = self._score("protocol_revenue", 0.5, 0.0)
        s_burn = self._score("protocol_revenue", 0.5, 100.0)
        self.assertGreater(s_burn, s_no_burn)

    def test_score_capped_at_100(self):
        score = self._score("protocol_revenue", 0.1, 100.0)
        self.assertLessEqual(score, 100)

    def test_score_at_least_zero(self):
        score = self._score("inflation", 5.0, 0.0)
        self.assertGreaterEqual(score, 0)

    def test_score_is_integer(self):
        score = self._score("protocol_revenue")
        self.assertIsInstance(score, int)

    def test_unknown_source_defaults(self):
        score = self._score("unknown_source")
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


# ---------------------------------------------------------------------------
# 6. Label determination
# ---------------------------------------------------------------------------

class TestDetermineLabel(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _label(self, source, yield_pct, burn_pct, mechanism):
        return self.ana._determine_label(source, yield_pct, burn_pct, mechanism)

    def test_highly_accretive(self):
        label = self._label("protocol_revenue", 10.0, 90.0, "burn")
        self.assertEqual(label, "HIGHLY_ACCRETIVE")

    def test_highly_accretive_exactly_at_threshold(self):
        # yield > 5 (not >=), burn > 80 (not >=)
        label = self._label("protocol_revenue", 5.01, 80.01, "burn")
        self.assertEqual(label, "HIGHLY_ACCRETIVE")

    def test_not_highly_accretive_below_yield(self):
        label = self._label("protocol_revenue", 4.9, 90.0, "burn")
        self.assertNotEqual(label, "HIGHLY_ACCRETIVE")

    def test_not_highly_accretive_burn_below_80(self):
        label = self._label("protocol_revenue", 10.0, 79.9, "burn")
        self.assertNotEqual(label, "HIGHLY_ACCRETIVE")

    def test_not_highly_accretive_wrong_source(self):
        label = self._label("external", 10.0, 90.0, "burn")
        self.assertNotEqual(label, "HIGHLY_ACCRETIVE")

    def test_inflationary_offset(self):
        label = self._label("inflation", 50.0, 100.0, "burn")
        self.assertEqual(label, "INFLATIONARY_OFFSET")

    def test_inflationary_offset_overrides_yield(self):
        # Even with high yield, inflation source → INFLATIONARY_OFFSET
        label = self._label("inflation", 20.0, 90.0, "burn")
        self.assertEqual(label, "INFLATIONARY_OFFSET")

    def test_unsustainable_treasury(self):
        label = self._label("treasury", 10.0, 100.0, "burn")
        self.assertEqual(label, "UNSUSTAINABLE")

    def test_unsustainable_zero_yield(self):
        label = self._label("treasury", 0.0, 0.0, "market_buy")
        self.assertEqual(label, "UNSUSTAINABLE")

    def test_accretive_external_high_yield(self):
        label = self._label("external", 5.0, 50.0, "burn")
        self.assertEqual(label, "ACCRETIVE")

    def test_accretive_revenue_moderate_yield(self):
        label = self._label("protocol_revenue", 3.0, 50.0, "burn")
        self.assertEqual(label, "ACCRETIVE")

    def test_neutral_low_yield(self):
        label = self._label("protocol_revenue", 0.5, 100.0, "burn")
        self.assertEqual(label, "NEUTRAL")

    def test_neutral_non_burn_mechanism(self):
        label = self._label("protocol_revenue", 1.5, 0.0, "stake_distribute")
        self.assertEqual(label, "NEUTRAL")

    def test_neutral_default_low_activity(self):
        label = self._label("external", 0.1, 10.0, "treasury_hold")
        self.assertEqual(label, "NEUTRAL")


# ---------------------------------------------------------------------------
# 7. Flag computation
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def setUp(self):
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer()

    def _flags(self, **kw):
        defaults = dict(
            source="protocol_revenue",
            supply_reduction_rate_pct=0.5,
            buyback_to_volume_ratio=1.0,
            consistency=50.0,
        )
        defaults.update(kw)
        return self.ana._compute_flags(**defaults)

    def test_no_flags_baseline(self):
        f = self._flags()
        # no DEFLATIONARY_PRESSURE, no REVENUE_FUNDED? Actually source=protocol_revenue → REVENUE_FUNDED
        self.assertIn("REVENUE_FUNDED", f)

    def test_deflationary_pressure(self):
        f = self._flags(supply_reduction_rate_pct=2.5)
        self.assertIn("DEFLATIONARY_PRESSURE", f)

    def test_no_deflationary_at_2(self):
        f = self._flags(supply_reduction_rate_pct=2.0)
        self.assertNotIn("DEFLATIONARY_PRESSURE", f)

    def test_revenue_funded_flag(self):
        f = self._flags(source="protocol_revenue")
        self.assertIn("REVENUE_FUNDED", f)

    def test_no_revenue_funded_for_treasury(self):
        f = self._flags(source="treasury")
        self.assertNotIn("REVENUE_FUNDED", f)

    def test_treasury_drawdown_flag(self):
        f = self._flags(source="treasury")
        self.assertIn("TREASURY_DRAWDOWN", f)

    def test_no_treasury_drawdown_for_revenue(self):
        f = self._flags(source="protocol_revenue")
        self.assertNotIn("TREASURY_DRAWDOWN", f)

    def test_meaningful_buy_pressure(self):
        f = self._flags(buyback_to_volume_ratio=6.0)
        self.assertIn("MEANINGFUL_BUY_PRESSURE", f)

    def test_no_meaningful_at_5(self):
        f = self._flags(buyback_to_volume_ratio=5.0)
        self.assertNotIn("MEANINGFUL_BUY_PRESSURE", f)

    def test_inflation_funded_buyback(self):
        f = self._flags(source="inflation")
        self.assertIn("INFLATION_FUNDED_BUYBACK", f)

    def test_no_inflation_for_revenue(self):
        f = self._flags(source="protocol_revenue")
        self.assertNotIn("INFLATION_FUNDED_BUYBACK", f)

    def test_consistent_program(self):
        f = self._flags(consistency=85.0)
        self.assertIn("CONSISTENT_PROGRAM", f)

    def test_no_consistent_at_80(self):
        f = self._flags(consistency=80.0)
        self.assertNotIn("CONSISTENT_PROGRAM", f)

    def test_multiple_flags(self):
        f = self._flags(
            source="protocol_revenue",
            supply_reduction_rate_pct=3.0,
            buyback_to_volume_ratio=10.0,
            consistency=90.0,
        )
        self.assertIn("DEFLATIONARY_PRESSURE", f)
        self.assertIn("REVENUE_FUNDED", f)
        self.assertIn("MEANINGFUL_BUY_PRESSURE", f)
        self.assertIn("CONSISTENT_PROGRAM", f)

    def test_flags_is_list(self):
        self.assertIsInstance(self._flags(), list)


# ---------------------------------------------------------------------------
# 8. Analyze — basic API
# ---------------------------------------------------------------------------

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def test_returns_dict(self):
        result = self.ana.analyze([make_program()], {"log_enabled": False})
        self.assertIsInstance(result, dict)

    def test_required_top_level_keys(self):
        result = self.ana.analyze([make_program()], {"log_enabled": False})
        for key in ("timestamp", "module", "mp", "program_count", "programs", "aggregates"):
            self.assertIn(key, result)

    def test_module_name(self):
        result = self.ana.analyze([make_program()], {"log_enabled": False})
        self.assertEqual(result["module"], "ProtocolDeFiTokenBuybackImpactAnalyzer")

    def test_mp_number(self):
        result = self.ana.analyze([make_program()], {"log_enabled": False})
        self.assertEqual(result["mp"], "MP-1001")

    def test_program_count(self):
        result = self.ana.analyze(
            [make_program(), make_program(name="B")], {"log_enabled": False}
        )
        self.assertEqual(result["program_count"], 2)

    def test_empty_programs(self):
        result = self.ana.analyze([], {"log_enabled": False})
        self.assertEqual(result["program_count"], 0)
        self.assertEqual(result["programs"], [])

    def test_raises_on_non_list(self):
        with self.assertRaises(TypeError):
            self.ana.analyze("not_a_list", {})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.ana.analyze([], "not_a_dict")

    def test_program_result_fields(self):
        result = self.ana.analyze([make_program()], {"log_enabled": False})
        prog = result["programs"][0]
        for field in (
            "name", "protocol", "weekly_buyback_usd", "buyback_source",
            "annualized_buyback_usd", "buyback_yield_pct",
            "buyback_to_volume_ratio", "supply_reduction_rate_pct",
            "sustainability_score", "label", "flags",
        ):
            self.assertIn(field, prog)

    def test_single_program_label_valid(self):
        result = self.ana.analyze([make_program()], {"log_enabled": False})
        label = result["programs"][0]["label"]
        self.assertIn(label, {
            "HIGHLY_ACCRETIVE", "ACCRETIVE", "NEUTRAL",
            "INFLATIONARY_OFFSET", "UNSUSTAINABLE",
        })


# ---------------------------------------------------------------------------
# 9. Multiple programs
# ---------------------------------------------------------------------------

class TestMultiplePrograms(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def _run(self, programs):
        return self.ana.analyze(programs, {"log_enabled": False})

    def test_three_programs(self):
        programs = [
            make_program(name="A"),
            make_program(name="B", weekly_buyback_usd=200_000),
            make_program(name="C", buyback_source="treasury"),
        ]
        result = self._run(programs)
        self.assertEqual(result["program_count"], 3)

    def test_programs_list_length(self):
        programs = [make_program(name=f"P{i}") for i in range(5)]
        result = self._run(programs)
        self.assertEqual(len(result["programs"]), 5)

    def test_each_program_has_label(self):
        programs = [make_program(name=f"P{i}") for i in range(3)]
        result = self._run(programs)
        for p in result["programs"]:
            self.assertIn(p["label"], {
                "HIGHLY_ACCRETIVE", "ACCRETIVE", "NEUTRAL",
                "INFLATIONARY_OFFSET", "UNSUSTAINABLE",
            })

    def test_each_program_has_flags_list(self):
        programs = [make_program(name=f"P{i}") for i in range(3)]
        result = self._run(programs)
        for p in result["programs"]:
            self.assertIsInstance(p["flags"], list)

    def test_mixed_sources(self):
        programs = [
            make_program(name="Revenue", buyback_source="protocol_revenue",
                         weekly_buyback_usd=500_000,
                         token_circulating_supply_usd=5_000_000, burn_pct=95.0),
            make_program(name="Inflation", buyback_source="inflation"),
            make_program(name="Treasury", buyback_source="treasury"),
        ]
        result = self._run(programs)
        labels = {p["name"]: p["label"] for p in result["programs"]}
        self.assertEqual(labels["Inflation"], "INFLATIONARY_OFFSET")
        self.assertEqual(labels["Treasury"], "UNSUSTAINABLE")

    def test_total_weekly_in_aggregates(self):
        programs = [
            make_program(name="A", weekly_buyback_usd=100_000),
            make_program(name="B", weekly_buyback_usd=200_000),
        ]
        result = self._run(programs)
        self.assertAlmostEqual(
            result["aggregates"]["total_weekly_buyback_usd"], 300_000.0, places=0
        )


# ---------------------------------------------------------------------------
# 10. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def _run(self, programs):
        return self.ana.analyze(programs, {"log_enabled": False})["aggregates"]

    def test_empty_aggregates(self):
        agg = self._run([])
        self.assertIsNone(agg["most_accretive"])
        self.assertIsNone(agg["least_accretive"])
        self.assertEqual(agg["total_weekly_buyback_usd"], 0.0)
        self.assertEqual(agg["highly_accretive_count"], 0)
        self.assertEqual(agg["unsustainable_count"], 0)

    def test_most_accretive_single(self):
        agg = self._run([make_program(name="Solo")])
        self.assertEqual(agg["most_accretive"], "Solo")

    def test_least_accretive_single(self):
        agg = self._run([make_program(name="Solo")])
        self.assertEqual(agg["least_accretive"], "Solo")

    def test_most_accretive_highest_yield(self):
        programs = [
            make_program(name="High", weekly_buyback_usd=500_000,
                         token_circulating_supply_usd=1_000_000),
            make_program(name="Low", weekly_buyback_usd=1_000,
                         token_circulating_supply_usd=100_000_000),
        ]
        agg = self._run(programs)
        self.assertEqual(agg["most_accretive"], "High")

    def test_least_accretive_lowest_yield(self):
        programs = [
            make_program(name="High", weekly_buyback_usd=500_000,
                         token_circulating_supply_usd=1_000_000),
            make_program(name="Low", weekly_buyback_usd=1_000,
                         token_circulating_supply_usd=100_000_000),
        ]
        agg = self._run(programs)
        self.assertEqual(agg["least_accretive"], "Low")

    def test_total_weekly_buyback(self):
        programs = [
            make_program(name="A", weekly_buyback_usd=100_000),
            make_program(name="B", weekly_buyback_usd=50_000),
            make_program(name="C", weekly_buyback_usd=25_000),
        ]
        agg = self._run(programs)
        self.assertAlmostEqual(agg["total_weekly_buyback_usd"], 175_000.0, places=0)

    def test_highly_accretive_count(self):
        programs = [
            make_program(name="HA1", buyback_source="protocol_revenue",
                         weekly_buyback_usd=500_000,
                         token_circulating_supply_usd=1_000_000, burn_pct=90.0),
            make_program(name="HA2", buyback_source="protocol_revenue",
                         weekly_buyback_usd=500_000,
                         token_circulating_supply_usd=1_000_000, burn_pct=90.0),
            make_program(name="Other", buyback_source="treasury"),
        ]
        agg = self._run(programs)
        self.assertEqual(agg["highly_accretive_count"], 2)

    def test_unsustainable_count(self):
        programs = [
            make_program(name="T1", buyback_source="treasury"),
            make_program(name="T2", buyback_source="treasury"),
            make_program(name="R1", buyback_source="protocol_revenue"),
        ]
        agg = self._run(programs)
        self.assertEqual(agg["unsustainable_count"], 2)

    def test_aggregate_keys(self):
        agg = self._run([make_program()])
        for k in ("most_accretive", "least_accretive", "total_weekly_buyback_usd",
                  "highly_accretive_count", "unsustainable_count"):
            self.assertIn(k, agg)


# ---------------------------------------------------------------------------
# 11. Ring-buffer log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)
        self.log_path = os.path.join(self.tmp, "token_buyback_log.json")

    def _run(self, programs=None, enabled=True):
        programs = programs or [make_program()]
        return self.ana.analyze(programs, {"log_enabled": enabled})

    def test_log_created_when_enabled(self):
        self._run()
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_grows_with_calls(self):
        self._run()
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_log_entry_timestamp(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("timestamp", log[0])

    def test_log_entry_program_count(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("program_count", log[0])

    def test_log_entry_aggregates(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("aggregates", log[0])

    def test_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 5):
            self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), LOG_CAP)

    def test_no_log_when_disabled(self):
        self._run(enabled=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_atomic_no_tmp_remaining(self):
        self._run()
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_log_program_count_correct(self):
        programs = [make_program(name=f"P{i}") for i in range(4)]
        self._run(programs)
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(log[0]["program_count"], 4)


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def _run(self, prog):
        return self.ana.analyze([prog], {"log_enabled": False})["programs"][0]

    def test_zero_market_cap_uses_default(self):
        prog = make_program(token_circulating_supply_usd=0)
        result = self._run(prog)
        # Should not raise
        self.assertGreaterEqual(result["buyback_yield_pct"], 0.0)

    def test_negative_market_cap_treated_as_one(self):
        prog = make_program(token_circulating_supply_usd=-1_000_000)
        result = self._run(prog)
        self.assertGreaterEqual(result["buyback_yield_pct"], 0.0)

    def test_missing_optional_fields(self):
        prog = {"name": "Minimal", "weekly_buyback_usd": 10_000}
        result = self._run(prog)
        self.assertIn("label", result)

    def test_extra_fields_ignored(self):
        prog = make_program(extra="ignored")
        result = self._run(prog)
        self.assertIn("label", result)

    def test_100pct_burn_and_revenue(self):
        prog = make_program(
            buyback_source="protocol_revenue", burn_pct=100.0,
            weekly_buyback_usd=1_000_000,
            token_circulating_supply_usd=5_000_000,
        )
        result = self._run(prog)
        self.assertEqual(result["label"], "HIGHLY_ACCRETIVE")

    def test_names_preserved(self):
        prog = make_program(name="SpecialBuyback", protocol="SpecialDEX")
        result = self._run(prog)
        self.assertEqual(result["name"], "SpecialBuyback")
        self.assertEqual(result["protocol"], "SpecialDEX")

    def test_revenue_funded_flag_for_revenue_source(self):
        prog = make_program(buyback_source="protocol_revenue")
        result = self._run(prog)
        self.assertIn("REVENUE_FUNDED", result["flags"])

    def test_inflation_funded_flag(self):
        prog = make_program(buyback_source="inflation")
        result = self._run(prog)
        self.assertIn("INFLATION_FUNDED_BUYBACK", result["flags"])


# ---------------------------------------------------------------------------
# 13. Config handling
# ---------------------------------------------------------------------------

class TestConfigHandling(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def test_log_enabled_by_default(self):
        log_path = os.path.join(self.tmp, "token_buyback_log.json")
        self.ana.analyze([make_program()], {})
        self.assertTrue(os.path.exists(log_path))

    def test_log_disabled(self):
        log_path = os.path.join(self.tmp, "token_buyback_log.json")
        self.ana.analyze([make_program()], {"log_enabled": False})
        self.assertFalse(os.path.exists(log_path))

    def test_custom_data_dir(self):
        import tempfile as tf
        tmp2 = tf.mkdtemp()
        self.ana.analyze([make_program()], {"data_dir": tmp2})
        log_path = os.path.join(tmp2, "token_buyback_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_empty_config_ok(self):
        result = self.ana.analyze([make_program()], {})
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# 14. Label integration / scenario tests
# ---------------------------------------------------------------------------

class TestLabelScenarios(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def _label(self, prog):
        return self.ana.analyze([prog], {"log_enabled": False})["programs"][0]["label"]

    def test_scenario_highly_accretive(self):
        prog = make_program(
            buyback_source="protocol_revenue",
            weekly_buyback_usd=500_000,
            token_circulating_supply_usd=1_000_000,
            burn_pct=95.0,
        )
        self.assertEqual(self._label(prog), "HIGHLY_ACCRETIVE")

    def test_scenario_accretive(self):
        prog = make_program(
            buyback_source="protocol_revenue",
            weekly_buyback_usd=50_000,
            token_circulating_supply_usd=10_000_000,
            burn_pct=50.0,
        )
        # yield = 50_000*52/10_000_000*100 = 26% → HIGHLY_ACCRETIVE if burn>80
        # burn=50 so NOT highly_accretive → ACCRETIVE (yield>2%)
        self.assertEqual(self._label(prog), "ACCRETIVE")

    def test_scenario_neutral_low_yield(self):
        prog = make_program(
            buyback_source="protocol_revenue",
            weekly_buyback_usd=100,
            token_circulating_supply_usd=100_000_000,
            burn_pct=50.0,
        )
        # yield = 100*52/100_000_000*100 = 0.052% → NEUTRAL
        self.assertEqual(self._label(prog), "NEUTRAL")

    def test_scenario_inflationary_offset(self):
        prog = make_program(buyback_source="inflation", weekly_buyback_usd=1_000_000)
        self.assertEqual(self._label(prog), "INFLATIONARY_OFFSET")

    def test_scenario_unsustainable(self):
        prog = make_program(buyback_source="treasury", weekly_buyback_usd=100_000)
        self.assertEqual(self._label(prog), "UNSUSTAINABLE")

    def test_scenario_external_accretive(self):
        prog = make_program(
            buyback_source="external",
            weekly_buyback_usd=200_000,
            token_circulating_supply_usd=1_000_000,
        )
        # yield = 200_000*52/1_000_000*100 = 1040% → ACCRETIVE
        self.assertEqual(self._label(prog), "ACCRETIVE")


# ---------------------------------------------------------------------------
# 15. Misc / coverage
# ---------------------------------------------------------------------------

class TestMisc(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = ProtocolDeFiTokenBuybackImpactAnalyzer(data_dir=self.tmp)

    def test_log_cap_constant(self):
        self.assertEqual(LOG_CAP, 100)

    def test_result_has_correct_weekly(self):
        prog = make_program(weekly_buyback_usd=77_777)
        result = self.ana.analyze([prog], {"log_enabled": False})
        self.assertAlmostEqual(
            result["programs"][0]["weekly_buyback_usd"], 77_777.0, places=0
        )

    def test_deflationary_flag_triggered(self):
        prog = make_program(
            weekly_buyback_usd=1_000_000,
            token_circulating_supply_usd=5_000_000,
            burn_pct=100.0,
        )
        result = self.ana.analyze([prog], {"log_enabled": False})
        self.assertIn("DEFLATIONARY_PRESSURE", result["programs"][0]["flags"])

    def test_consistent_flag_triggered(self):
        prog = make_program(buyback_consistency_score=95.0)
        result = self.ana.analyze([prog], {"log_enabled": False})
        self.assertIn("CONSISTENT_PROGRAM", result["programs"][0]["flags"])

    def test_meaningful_buy_pressure_flag(self):
        prog = make_program(
            weekly_buyback_usd=500_000,
            token_daily_volume_usd=100_000,  # weekly = 700_000 → ratio=71%
        )
        result = self.ana.analyze([prog], {"log_enabled": False})
        self.assertIn("MEANINGFUL_BUY_PRESSURE", result["programs"][0]["flags"])

    def test_treasury_drawdown_flag_in_result(self):
        prog = make_program(buyback_source="treasury")
        result = self.ana.analyze([prog], {"log_enabled": False})
        self.assertIn("TREASURY_DRAWDOWN", result["programs"][0]["flags"])


if __name__ == "__main__":
    unittest.main()

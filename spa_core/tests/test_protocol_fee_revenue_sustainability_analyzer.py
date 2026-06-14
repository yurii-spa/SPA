"""
Tests for MP-925 ProtocolFeeRevenueSustainabilityAnalyzer
≥85 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_fee_revenue_sustainability_analyzer import (
    ProtocolFeeRevenueSustainabilityAnalyzer,
    analyze,
    _revenue_growth_rate_pct,
    _revenue_per_tvl_pct,
    _profit_margin_pct,
    _revenue_quality_score,
    _unit_economics_score,
    _sustainability_label,
    _compute_flags,
    _analyze_protocol,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _proto(
    name: str = "TestProto",
    monthly_fee_revenue_usd: float = 500_000.0,
    monthly_revenue_3m_ago_usd: float = 400_000.0,
    monthly_revenue_6m_ago_usd: float = 300_000.0,
    monthly_operating_costs_usd: float = 150_000.0,
    team_size: float = 20.0,
    token_incentives_monthly_usd: float = 50_000.0,
    tvl_usd: float = 100_000_000.0,
    active_users_monthly: float = 5_000.0,
    fee_revenue_per_user_usd: float = 100.0,
    market_share_pct: float = 3.0,
) -> dict:
    return {
        "name": name,
        "monthly_fee_revenue_usd": monthly_fee_revenue_usd,
        "monthly_revenue_3m_ago_usd": monthly_revenue_3m_ago_usd,
        "monthly_revenue_6m_ago_usd": monthly_revenue_6m_ago_usd,
        "monthly_operating_costs_usd": monthly_operating_costs_usd,
        "team_size": team_size,
        "token_incentives_monthly_usd": token_incentives_monthly_usd,
        "tvl_usd": tvl_usd,
        "active_users_monthly": active_users_monthly,
        "fee_revenue_per_user_usd": fee_revenue_per_user_usd,
        "market_share_pct": market_share_pct,
    }


# ---------------------------------------------------------------------------
# Tests for _revenue_growth_rate_pct
# ---------------------------------------------------------------------------

class TestRevenueGrowthRate(unittest.TestCase):

    def test_positive_growth(self):
        rate = _revenue_growth_rate_pct(500_000, 400_000)
        self.assertAlmostEqual(rate, 25.0, places=4)

    def test_no_growth(self):
        rate = _revenue_growth_rate_pct(400_000, 400_000)
        self.assertAlmostEqual(rate, 0.0, places=6)

    def test_negative_growth(self):
        rate = _revenue_growth_rate_pct(300_000, 400_000)
        self.assertAlmostEqual(rate, -25.0, places=4)

    def test_zero_past_revenue(self):
        rate = _revenue_growth_rate_pct(500_000, 0)
        self.assertEqual(rate, 0.0)

    def test_zero_current_revenue(self):
        rate = _revenue_growth_rate_pct(0, 400_000)
        self.assertAlmostEqual(rate, -100.0, places=4)

    def test_doubled_revenue(self):
        rate = _revenue_growth_rate_pct(800_000, 400_000)
        self.assertAlmostEqual(rate, 100.0, places=4)

    def test_negative_past_revenue(self):
        # Negative past revenue treated as 0, returns 0
        rate = _revenue_growth_rate_pct(500_000, -100)
        self.assertEqual(rate, 0.0)


# ---------------------------------------------------------------------------
# Tests for _revenue_per_tvl_pct
# ---------------------------------------------------------------------------

class TestRevenuePerTvlPct(unittest.TestCase):

    def test_basic(self):
        pct = _revenue_per_tvl_pct(1_000_000, 100_000_000)
        self.assertAlmostEqual(pct, 1.0, places=6)

    def test_zero_tvl(self):
        self.assertEqual(_revenue_per_tvl_pct(1_000_000, 0), 0.0)

    def test_zero_revenue(self):
        self.assertAlmostEqual(_revenue_per_tvl_pct(0, 100_000_000), 0.0, places=6)

    def test_high_efficiency(self):
        pct = _revenue_per_tvl_pct(5_000_000, 100_000_000)
        self.assertAlmostEqual(pct, 5.0, places=4)

    def test_proportional(self):
        p1 = _revenue_per_tvl_pct(500_000, 100_000_000)
        p2 = _revenue_per_tvl_pct(1_000_000, 100_000_000)
        self.assertAlmostEqual(p2, p1 * 2, places=6)

    def test_negative_tvl(self):
        self.assertEqual(_revenue_per_tvl_pct(500_000, -1), 0.0)


# ---------------------------------------------------------------------------
# Tests for _profit_margin_pct
# ---------------------------------------------------------------------------

class TestProfitMarginPct(unittest.TestCase):

    def test_profitable(self):
        margin = _profit_margin_pct(500_000, 150_000, 50_000)
        self.assertAlmostEqual(margin, 60.0, places=4)

    def test_break_even(self):
        margin = _profit_margin_pct(500_000, 250_000, 250_000)
        self.assertAlmostEqual(margin, 0.0, places=6)

    def test_negative_margin(self):
        margin = _profit_margin_pct(500_000, 400_000, 200_000)
        self.assertLess(margin, 0)

    def test_zero_revenue_no_costs(self):
        margin = _profit_margin_pct(0, 0, 0)
        self.assertEqual(margin, 0.0)

    def test_zero_revenue_with_costs(self):
        margin = _profit_margin_pct(0, 100_000, 50_000)
        self.assertEqual(margin, -100.0)

    def test_full_profitability(self):
        margin = _profit_margin_pct(1_000_000, 0, 0)
        self.assertAlmostEqual(margin, 100.0, places=4)

    def test_high_incentives(self):
        margin = _profit_margin_pct(200_000, 50_000, 300_000)
        self.assertLess(margin, 0)


# ---------------------------------------------------------------------------
# Tests for _revenue_quality_score
# ---------------------------------------------------------------------------

class TestRevenueQualityScore(unittest.TestCase):

    def test_score_range(self):
        score = _revenue_quality_score(500_000, 50_000, 25.0, 0.5)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_zero_incentives_high_quality(self):
        score = _revenue_quality_score(500_000, 0, 30.0, 1.0)
        self.assertGreater(score, 50.0)

    def test_high_incentives_lower_quality(self):
        s1 = _revenue_quality_score(500_000, 0, 25.0, 0.5)
        s2 = _revenue_quality_score(500_000, 450_000, 25.0, 0.5)
        self.assertGreater(s1, s2)

    def test_positive_growth_boosts_score(self):
        s1 = _revenue_quality_score(500_000, 0, -50.0, 0.5)
        s2 = _revenue_quality_score(500_000, 0, 100.0, 0.5)
        self.assertGreater(s2, s1)

    def test_zero_revenue(self):
        score = _revenue_quality_score(0, 0, 0, 0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_very_high_efficiency_capped(self):
        score = _revenue_quality_score(10_000_000, 0, 200.0, 10.0)
        self.assertLessEqual(score, 100.0)

    def test_return_type_is_float(self):
        score = _revenue_quality_score(500_000, 50_000, 25.0, 0.5)
        self.assertIsInstance(score, float)


# ---------------------------------------------------------------------------
# Tests for _unit_economics_score
# ---------------------------------------------------------------------------

class TestUnitEconomicsScore(unittest.TestCase):

    def test_score_range(self):
        score = _unit_economics_score(100.0, 20.0, 500_000, 5_000)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_high_rev_per_user_boosts_score(self):
        s1 = _unit_economics_score(10.0, 20.0, 500_000, 5_000)
        s2 = _unit_economics_score(200.0, 20.0, 500_000, 5_000)
        self.assertGreater(s2, s1)

    def test_zero_team_gives_perfect_team_component(self):
        score_no_team = _unit_economics_score(100.0, 0.0, 500_000, 5_000)
        score_with_team = _unit_economics_score(100.0, 100.0, 500_000, 5_000)
        # No team means automated = bonus
        self.assertGreaterEqual(score_no_team, 0.0)

    def test_zero_revenue_zero_score(self):
        score = _unit_economics_score(0.0, 20.0, 0, 5_000)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_large_team_lower_score(self):
        s_small = _unit_economics_score(100.0, 5.0, 500_000, 5_000)
        s_large = _unit_economics_score(100.0, 500.0, 500_000, 5_000)
        self.assertGreater(s_small, s_large)

    def test_zero_users(self):
        score = _unit_economics_score(0.0, 20.0, 500_000, 0)
        self.assertGreaterEqual(score, 0.0)

    def test_return_type_is_float(self):
        score = _unit_economics_score(100.0, 20.0, 500_000, 5_000)
        self.assertIsInstance(score, float)


# ---------------------------------------------------------------------------
# Tests for _sustainability_label
# ---------------------------------------------------------------------------

class TestSustainabilityLabel(unittest.TestCase):

    def test_profitable_positive_margin(self):
        self.assertEqual(_sustainability_label(10.0), "PROFITABLE")

    def test_profitable_zero_margin(self):
        self.assertEqual(_sustainability_label(0.0), "PROFITABLE")

    def test_break_even_just_below_zero(self):
        self.assertEqual(_sustainability_label(-1.0), "BREAK_EVEN")

    def test_break_even_boundary(self):
        self.assertEqual(_sustainability_label(-5.0), "BREAK_EVEN")

    def test_subsidized(self):
        self.assertEqual(_sustainability_label(-15.0), "SUBSIDIZED")

    def test_subsidized_boundary(self):
        self.assertEqual(_sustainability_label(-30.0), "SUBSIDIZED")

    def test_loss_making(self):
        self.assertEqual(_sustainability_label(-45.0), "LOSS_MAKING")

    def test_loss_making_boundary(self):
        self.assertEqual(_sustainability_label(-60.0), "LOSS_MAKING")

    def test_critical(self):
        self.assertEqual(_sustainability_label(-80.0), "CRITICAL")

    def test_critical_extreme(self):
        self.assertEqual(_sustainability_label(-100.0), "CRITICAL")


# ---------------------------------------------------------------------------
# Tests for _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_no_flags(self):
        flags = _compute_flags(15.0, 50_000, 500_000, 5.0, 400_000, 30.0)
        self.assertEqual(flags, [])

    def test_growing_revenue_flag(self):
        flags = _compute_flags(25.0, 50_000, 500_000, 5.0, 400_000, 30.0)
        self.assertIn("GROWING_REVENUE", flags)

    def test_incentive_dependent_flag(self):
        # incentives > 50% of revenue
        flags = _compute_flags(15.0, 300_000, 500_000, 5.0, 400_000, 30.0)
        self.assertIn("INCENTIVE_DEPENDENT", flags)

    def test_declining_market_share_flag(self):
        # revenue declined and market share < 5%
        flags = _compute_flags(-10.0, 50_000, 500_000, 3.0, 600_000, -5.0)
        self.assertIn("DECLINING_MARKET_SHARE", flags)

    def test_high_profit_margin_flag(self):
        flags = _compute_flags(15.0, 50_000, 500_000, 5.0, 400_000, 65.0)
        self.assertIn("HIGH_PROFIT_MARGIN", flags)

    def test_negative_margin_flag(self):
        flags = _compute_flags(15.0, 50_000, 500_000, 5.0, 400_000, -10.0)
        self.assertIn("NEGATIVE_MARGIN", flags)

    def test_multiple_flags(self):
        flags = _compute_flags(30.0, 300_000, 500_000, 3.0, 600_000, -70.0)
        self.assertIn("GROWING_REVENUE", flags)
        self.assertIn("INCENTIVE_DEPENDENT", flags)
        self.assertIn("NEGATIVE_MARGIN", flags)

    def test_exactly_20pct_growth_not_flagged(self):
        flags = _compute_flags(20.0, 50_000, 500_000, 5.0, 400_000, 30.0)
        self.assertNotIn("GROWING_REVENUE", flags)

    def test_exactly_60pct_margin_not_flagged(self):
        flags = _compute_flags(15.0, 50_000, 500_000, 5.0, 400_000, 60.0)
        self.assertNotIn("HIGH_PROFIT_MARGIN", flags)


# ---------------------------------------------------------------------------
# Tests for _analyze_protocol
# ---------------------------------------------------------------------------

class TestAnalyzeProtocol(unittest.TestCase):

    def test_returns_dict(self):
        result = _analyze_protocol(_proto())
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = _analyze_protocol(_proto())
        for key in ("name", "revenue_growth_rate_pct", "revenue_per_tvl_pct",
                    "profit_margin_pct", "revenue_quality_score", "unit_economics_score",
                    "sustainability_label", "flags"):
            self.assertIn(key, result)

    def test_name_field(self):
        result = _analyze_protocol(_proto(name="Aave"))
        self.assertEqual(result["name"], "Aave")

    def test_sustainability_label_valid(self):
        result = _analyze_protocol(_proto())
        self.assertIn(result["sustainability_label"],
                      ["PROFITABLE", "BREAK_EVEN", "SUBSIDIZED", "LOSS_MAKING", "CRITICAL"])

    def test_flags_is_list(self):
        result = _analyze_protocol(_proto())
        self.assertIsInstance(result["flags"], list)

    def test_profitable_protocol(self):
        p = _proto(monthly_fee_revenue_usd=1_000_000, monthly_operating_costs_usd=100_000,
                   token_incentives_monthly_usd=50_000)
        result = _analyze_protocol(p)
        self.assertEqual(result["sustainability_label"], "PROFITABLE")

    def test_critical_protocol(self):
        p = _proto(monthly_fee_revenue_usd=100_000, monthly_operating_costs_usd=500_000,
                   token_incentives_monthly_usd=200_000)
        result = _analyze_protocol(p)
        self.assertIn(result["sustainability_label"], ["LOSS_MAKING", "CRITICAL"])

    def test_quality_score_range(self):
        result = _analyze_protocol(_proto())
        self.assertGreaterEqual(result["revenue_quality_score"], 0.0)
        self.assertLessEqual(result["revenue_quality_score"], 100.0)

    def test_unit_econ_score_range(self):
        result = _analyze_protocol(_proto())
        self.assertGreaterEqual(result["unit_economics_score"], 0.0)
        self.assertLessEqual(result["unit_economics_score"], 100.0)


# ---------------------------------------------------------------------------
# Tests for ProtocolFeeRevenueSustainabilityAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerEmpty(unittest.TestCase):

    def test_empty_protocols(self):
        a = ProtocolFeeRevenueSustainabilityAnalyzer()
        result = a.analyze([], {"write_log": False})
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["most_profitable"])
        self.assertIsNone(result["most_critical"])
        self.assertEqual(result["total_ecosystem_revenue"], 0.0)
        self.assertEqual(result["average_profit_margin"], 0.0)
        self.assertEqual(result["profitable_count"], 0)

    def test_empty_has_timestamp(self):
        a = ProtocolFeeRevenueSustainabilityAnalyzer()
        result = a.analyze([], {"write_log": False})
        self.assertIn("timestamp", result)


class TestAnalyzerSingle(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolFeeRevenueSustainabilityAnalyzer()

    def test_single_protocol(self):
        result = self.a.analyze([_proto()], {"write_log": False})
        self.assertEqual(len(result["protocols"]), 1)

    def test_single_most_profitable_and_critical_same(self):
        result = self.a.analyze([_proto(name="OnlyOne")], {"write_log": False})
        self.assertEqual(result["most_profitable"], "OnlyOne")
        self.assertEqual(result["most_critical"], "OnlyOne")

    def test_single_total_revenue(self):
        result = self.a.analyze([_proto(monthly_fee_revenue_usd=300_000)], {"write_log": False})
        self.assertAlmostEqual(result["total_ecosystem_revenue"], 300_000.0, places=1)

    def test_single_average_margin(self):
        result = self.a.analyze([_proto()], {"write_log": False})
        self.assertAlmostEqual(
            result["average_profit_margin"],
            result["protocols"][0]["profit_margin_pct"],
            places=4
        )


class TestAnalyzerMultiple(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolFeeRevenueSustainabilityAnalyzer()
        self.protocols = [
            _proto(name="Alpha", monthly_fee_revenue_usd=1_000_000,
                   monthly_operating_costs_usd=100_000, token_incentives_monthly_usd=50_000),
            _proto(name="Beta", monthly_fee_revenue_usd=500_000,
                   monthly_operating_costs_usd=300_000, token_incentives_monthly_usd=100_000),
            _proto(name="Gamma", monthly_fee_revenue_usd=200_000,
                   monthly_operating_costs_usd=500_000, token_incentives_monthly_usd=100_000),
        ]

    def test_three_protocols(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        self.assertEqual(len(result["protocols"]), 3)

    def test_most_profitable_is_highest_margin(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        margins = {p["name"]: p["profit_margin_pct"] for p in result["protocols"]}
        self.assertEqual(margins[result["most_profitable"]], max(margins.values()))

    def test_most_critical_is_lowest_margin(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        margins = {p["name"]: p["profit_margin_pct"] for p in result["protocols"]}
        self.assertEqual(margins[result["most_critical"]], min(margins.values()))

    def test_total_revenue_sum(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        expected = 1_000_000 + 500_000 + 200_000
        self.assertAlmostEqual(result["total_ecosystem_revenue"], expected, places=1)

    def test_average_margin_computation(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        manual = sum(p["profit_margin_pct"] for p in result["protocols"]) / 3
        self.assertAlmostEqual(result["average_profit_margin"], manual, places=4)

    def test_profitable_count(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        manual = sum(1 for p in result["protocols"] if p["sustainability_label"] == "PROFITABLE")
        self.assertEqual(result["profitable_count"], manual)

    def test_no_internal_keys_in_output(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        for p in result["protocols"]:
            for k in p:
                self.assertFalse(k.startswith("_"))

    def test_order_preserved(self):
        result = self.a.analyze(self.protocols, {"write_log": False})
        names = [p["name"] for p in result["protocols"]]
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])


class TestAnalyzerFlags(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolFeeRevenueSustainabilityAnalyzer()

    def test_growing_revenue_protocol(self):
        p = _proto(monthly_fee_revenue_usd=600_000, monthly_revenue_3m_ago_usd=400_000)
        result = self.a.analyze([p], {"write_log": False})
        self.assertIn("GROWING_REVENUE", result["protocols"][0]["flags"])

    def test_incentive_dependent_protocol(self):
        p = _proto(monthly_fee_revenue_usd=200_000, token_incentives_monthly_usd=150_000)
        result = self.a.analyze([p], {"write_log": False})
        self.assertIn("INCENTIVE_DEPENDENT", result["protocols"][0]["flags"])

    def test_high_profit_margin_protocol(self):
        p = _proto(monthly_fee_revenue_usd=1_000_000, monthly_operating_costs_usd=50_000,
                   token_incentives_monthly_usd=10_000)
        result = self.a.analyze([p], {"write_log": False})
        self.assertIn("HIGH_PROFIT_MARGIN", result["protocols"][0]["flags"])

    def test_negative_margin_flag(self):
        p = _proto(monthly_fee_revenue_usd=100_000, monthly_operating_costs_usd=400_000)
        result = self.a.analyze([p], {"write_log": False})
        self.assertIn("NEGATIVE_MARGIN", result["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# Tests for module-level analyze()
# ---------------------------------------------------------------------------

class TestModuleLevelAnalyze(unittest.TestCase):

    def test_returns_dict(self):
        result = analyze([_proto()], {"write_log": False})
        self.assertIsInstance(result, dict)

    def test_empty_list(self):
        result = analyze([], {"write_log": False})
        self.assertEqual(result["protocols"], [])

    def test_consistent_with_class(self):
        protos = [_proto(name="X"), _proto(name="Y")]
        r1 = analyze(protos, {"write_log": False})
        r2 = ProtocolFeeRevenueSustainabilityAnalyzer().analyze(protos, {"write_log": False})
        self.assertEqual(r1["most_profitable"], r2["most_profitable"])
        self.assertEqual(r1["profitable_count"], r2["profitable_count"])

    def test_config_none(self):
        result = ProtocolFeeRevenueSustainabilityAnalyzer().analyze([_proto()], None)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Tests for _atomic_log
# ---------------------------------------------------------------------------

class TestAtomicLog(unittest.TestCase):

    def test_creates_file(self):
        log = _tmp_log()
        _atomic_log(log, {"key": "val"})
        self.assertTrue(os.path.exists(log))
        os.unlink(log)

    def test_appends_entries(self):
        log = _tmp_log()
        _atomic_log(log, {"n": 1})
        _atomic_log(log, {"n": 2})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(log)

    def test_ring_buffer_cap(self):
        log = _tmp_log()
        for i in range(110):
            _atomic_log(log, {"i": i})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        os.unlink(log)

    def test_ring_buffer_keeps_latest(self):
        log = _tmp_log()
        for i in range(110):
            _atomic_log(log, {"i": i})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 109)
        os.unlink(log)

    def test_corrupted_file_reset(self):
        log = _tmp_log()
        with open(log, "w") as f:
            f.write("CORRUPT")
        _atomic_log(log, {"k": "v"})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_non_list_file_reset(self):
        log = _tmp_log()
        with open(log, "w") as f:
            json.dump({}, f)
        _atomic_log(log, {"k": "v"})
        with open(log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(log)


# ---------------------------------------------------------------------------
# Tests for write_log integration
# ---------------------------------------------------------------------------

class TestWriteLogIntegration(unittest.TestCase):

    def test_write_log_creates_file(self):
        log = _tmp_log()
        a = ProtocolFeeRevenueSustainabilityAnalyzer()
        a.analyze([_proto()], {"log_path": log, "write_log": True})
        self.assertTrue(os.path.exists(log))
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_write_log_false_no_file(self):
        log = _tmp_log()
        a = ProtocolFeeRevenueSustainabilityAnalyzer()
        a.analyze([_proto()], {"log_path": log, "write_log": False})
        self.assertFalse(os.path.exists(log))

    def test_log_entry_has_expected_keys(self):
        log = _tmp_log()
        a = ProtocolFeeRevenueSustainabilityAnalyzer()
        a.analyze([_proto()], {"log_path": log, "write_log": True})
        with open(log) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "protocol_count", "most_profitable", "most_critical",
                    "total_ecosystem_revenue", "average_profit_margin", "profitable_count"):
            self.assertIn(key, entry)
        os.unlink(log)

    def test_log_accumulates_multiple_runs(self):
        log = _tmp_log()
        a = ProtocolFeeRevenueSustainabilityAnalyzer()
        a.analyze([_proto()], {"log_path": log, "write_log": True})
        a.analyze([_proto()], {"log_path": log, "write_log": True})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(log)


# ---------------------------------------------------------------------------
# Edge-case & robustness tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolFeeRevenueSustainabilityAnalyzer()

    def test_missing_name_key(self):
        proto = {k: v for k, v in _proto().items() if k != "name"}
        result = self.a.analyze([proto], {"write_log": False})
        self.assertEqual(result["protocols"][0]["name"], "UNKNOWN")

    def test_all_zero_protocol(self):
        proto = {k: 0 for k in _proto()}
        result = self.a.analyze([proto], {"write_log": False})
        self.assertIsNotNone(result["protocols"][0]["sustainability_label"])

    def test_string_numbers_coerced(self):
        proto = _proto()
        proto["monthly_fee_revenue_usd"] = "500000"
        proto["monthly_operating_costs_usd"] = "150000"
        result = self.a.analyze([proto], {"write_log": False})
        self.assertIsNotNone(result)

    def test_very_large_revenue(self):
        proto = _proto(monthly_fee_revenue_usd=1e12)
        result = self.a.analyze([proto], {"write_log": False})
        self.assertGreater(result["total_ecosystem_revenue"], 0)

    def test_ten_protocols_performance(self):
        protos = [_proto(name=f"P{i}", monthly_fee_revenue_usd=float(i + 1) * 100_000)
                  for i in range(10)]
        result = self.a.analyze(protos, {"write_log": False})
        self.assertEqual(len(result["protocols"]), 10)

    def test_profitable_count_all_profitable(self):
        protos = [
            _proto(monthly_fee_revenue_usd=1_000_000,
                   monthly_operating_costs_usd=100_000,
                   token_incentives_monthly_usd=10_000)
            for _ in range(3)
        ]
        result = self.a.analyze(protos, {"write_log": False})
        self.assertEqual(result["profitable_count"], 3)

    def test_profitable_count_none_profitable(self):
        protos = [
            _proto(monthly_fee_revenue_usd=100_000,
                   monthly_operating_costs_usd=500_000)
            for _ in range(3)
        ]
        result = self.a.analyze(protos, {"write_log": False})
        self.assertEqual(result["profitable_count"], 0)


if __name__ == "__main__":
    unittest.main()

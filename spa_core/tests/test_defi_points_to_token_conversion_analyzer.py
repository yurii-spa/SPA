"""
Tests for MP-924 DeFiPointsToTokenConversionAnalyzer
≥80 unittest tests — pure stdlib, no third-party dependencies.
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

from spa_core.analytics.defi_points_to_token_conversion_analyzer import (
    DeFiPointsToTokenConversionAnalyzer,
    analyze,
    _implied_value_per_point,
    _implied_apy_pct,
    _dilution_risk_score,
    _comparison_premium_pct,
    _value_label,
    _compute_flags,
    _analyze_program,
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


def _prog(
    protocol: str = "TestProto",
    points_earned_per_dollar_tvl: float = 0.1,
    total_points_issued: float = 1_000_000.0,
    expected_token_allocation_pct: float = 10.0,
    token_fdv_usd: float = 500_000_000.0,
    airdrop_date_days_from_now: float = 90.0,
    eligible_users_count: float = 50_000.0,
    similar_protocol_airdrop_usd: float = 0.00005,
) -> dict:
    return {
        "protocol": protocol,
        "points_earned_per_dollar_tvl": points_earned_per_dollar_tvl,
        "total_points_issued": total_points_issued,
        "expected_token_allocation_pct": expected_token_allocation_pct,
        "token_fdv_usd": token_fdv_usd,
        "airdrop_date_days_from_now": airdrop_date_days_from_now,
        "eligible_users_count": eligible_users_count,
        "similar_protocol_airdrop_usd": similar_protocol_airdrop_usd,
    }


# ---------------------------------------------------------------------------
# Tests for _implied_value_per_point
# ---------------------------------------------------------------------------

class TestImpliedValuePerPoint(unittest.TestCase):

    def test_basic_calculation(self):
        # 10% of $500M FDV / 1M points = $50 per point
        val = _implied_value_per_point(1_000_000, 10.0, 500_000_000)
        self.assertAlmostEqual(val, 50.0, places=4)

    def test_zero_total_points(self):
        self.assertEqual(_implied_value_per_point(0, 10.0, 1e8), 0.0)

    def test_zero_fdv(self):
        self.assertEqual(_implied_value_per_point(1_000_000, 10.0, 0), 0.0)

    def test_zero_allocation(self):
        val = _implied_value_per_point(1_000_000, 0.0, 500_000_000)
        self.assertEqual(val, 0.0)

    def test_negative_allocation_clipped(self):
        val = _implied_value_per_point(1_000_000, -5.0, 500_000_000)
        self.assertEqual(val, 0.0)

    def test_100pct_allocation(self):
        val = _implied_value_per_point(1_000_000, 100.0, 1_000_000)
        self.assertAlmostEqual(val, 1.0, places=6)

    def test_small_fdv(self):
        val = _implied_value_per_point(1000, 5.0, 10_000)
        self.assertAlmostEqual(val, 0.5, places=6)

    def test_large_points(self):
        val = _implied_value_per_point(1e12, 10.0, 1e9)
        self.assertGreater(val, 0)

    def test_negative_fdv_clipped(self):
        val = _implied_value_per_point(1_000_000, 10.0, -100)
        self.assertEqual(val, 0.0)


# ---------------------------------------------------------------------------
# Tests for _implied_apy_pct
# ---------------------------------------------------------------------------

class TestImpliedApyPct(unittest.TestCase):

    def test_basic_apy(self):
        # val_per_point=50, points_per_dollar=0.1, 365 days
        # formula: val_per_point * ppd * DAYS_PER_YEAR * 100
        # = 50 * 0.1 * 365 * 100 = 182500%
        apy = _implied_apy_pct(50.0, 0.1, 365.0)
        self.assertAlmostEqual(apy, 50.0 * 0.1 * 365.0 * 100.0, places=2)

    def test_zero_points_per_dollar(self):
        self.assertEqual(_implied_apy_pct(50.0, 0.0, 90.0), 0.0)

    def test_zero_airdrop_days(self):
        self.assertEqual(_implied_apy_pct(50.0, 0.1, 0.0), 0.0)

    def test_negative_value_clipped(self):
        apy = _implied_apy_pct(-10.0, 0.1, 90.0)
        self.assertEqual(apy, 0.0)

    def test_zero_value_per_point(self):
        apy = _implied_apy_pct(0.0, 0.1, 90.0)
        self.assertEqual(apy, 0.0)

    def test_one_day(self):
        apy = _implied_apy_pct(1.0, 1.0, 1.0)
        self.assertAlmostEqual(apy, 365.0 * 100.0, places=2)

    def test_very_small_value(self):
        apy = _implied_apy_pct(0.0001, 0.001, 30.0)
        self.assertGreaterEqual(apy, 0.0)

    def test_proportional_to_points_rate(self):
        apy1 = _implied_apy_pct(1.0, 0.1, 90.0)
        apy2 = _implied_apy_pct(1.0, 0.2, 90.0)
        self.assertAlmostEqual(apy2, apy1 * 2, places=4)


# ---------------------------------------------------------------------------
# Tests for _dilution_risk_score
# ---------------------------------------------------------------------------

class TestDilutionRiskScore(unittest.TestCase):

    def test_zero_users(self):
        self.assertEqual(_dilution_risk_score(0), 0.0)

    def test_one_user(self):
        score = _dilution_risk_score(1)
        self.assertEqual(score, 0.0)

    def test_million_users(self):
        score = _dilution_risk_score(1_000_000)
        self.assertAlmostEqual(score, 6.0 / 7.0 * 100.0, places=1)

    def test_ten_million_users(self):
        score = _dilution_risk_score(10_000_000)
        self.assertAlmostEqual(score, 100.0, places=1)

    def test_monotonic_increasing(self):
        scores = [_dilution_risk_score(10 ** i) for i in range(1, 8)]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_capped_at_100(self):
        score = _dilution_risk_score(1e15)
        self.assertLessEqual(score, 100.0)

    def test_negative_users_treated_as_zero(self):
        score = _dilution_risk_score(-100)
        self.assertEqual(score, 0.0)

    def test_hundred_thousand_users(self):
        score = _dilution_risk_score(100_000)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 100.0)


# ---------------------------------------------------------------------------
# Tests for _comparison_premium_pct
# ---------------------------------------------------------------------------

class TestComparisonPremiumPct(unittest.TestCase):

    def test_zero_similar_airdrop(self):
        self.assertEqual(_comparison_premium_pct(50.0, 0.0, 10_000), 0.0)

    def test_zero_users(self):
        self.assertEqual(_comparison_premium_pct(50.0, 40.0, 0.0), 0.0)

    def test_premium_above_peer(self):
        prem = _comparison_premium_pct(60.0, 40.0, 10_000)
        self.assertAlmostEqual(prem, 50.0, places=4)

    def test_discount_below_peer(self):
        prem = _comparison_premium_pct(20.0, 40.0, 10_000)
        self.assertAlmostEqual(prem, -50.0, places=4)

    def test_at_par(self):
        prem = _comparison_premium_pct(40.0, 40.0, 10_000)
        self.assertAlmostEqual(prem, 0.0, places=6)

    def test_negative_peer_treated_as_zero(self):
        prem = _comparison_premium_pct(50.0, -10.0, 10_000)
        self.assertEqual(prem, 0.0)


# ---------------------------------------------------------------------------
# Tests for _value_label
# ---------------------------------------------------------------------------

class TestValueLabel(unittest.TestCase):

    def test_exceptional(self):
        self.assertEqual(_value_label(51.0), "EXCEPTIONAL")

    def test_exceptional_boundary(self):
        self.assertEqual(_value_label(50.0), "EXCEPTIONAL")

    def test_good(self):
        self.assertEqual(_value_label(25.0), "GOOD")

    def test_good_boundary(self):
        self.assertEqual(_value_label(20.0), "GOOD")

    def test_fair(self):
        self.assertEqual(_value_label(10.0), "FAIR")

    def test_fair_boundary(self):
        self.assertEqual(_value_label(5.0), "FAIR")

    def test_poor(self):
        self.assertEqual(_value_label(2.0), "POOR")

    def test_poor_boundary(self):
        self.assertEqual(_value_label(1.0), "POOR")

    def test_likely_worthless(self):
        self.assertEqual(_value_label(0.5), "LIKELY_WORTHLESS")

    def test_zero_apy(self):
        self.assertEqual(_value_label(0.0), "LIKELY_WORTHLESS")

    def test_negative_apy(self):
        self.assertEqual(_value_label(-5.0), "LIKELY_WORTHLESS")

    def test_high_exceptional(self):
        self.assertEqual(_value_label(200.0), "EXCEPTIONAL")


# ---------------------------------------------------------------------------
# Tests for _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_no_flags(self):
        flags = _compute_flags(
            eligible_users_count=50_000,
            airdrop_date_days=90,
            comparison_premium_pct=10.0,
            expected_token_allocation_pct=10.0,
            points_earned_per_dollar_tvl=0.1,
        )
        self.assertEqual(flags, [])

    def test_high_dilution_flag(self):
        flags = _compute_flags(1_500_000, 90, 10.0, 10.0, 0.1)
        self.assertIn("HIGH_DILUTION", flags)

    def test_delayed_airdrop_flag(self):
        flags = _compute_flags(50_000, 200, 10.0, 10.0, 0.1)
        self.assertIn("DELAYED_AIRDROP", flags)

    def test_better_than_peers_flag(self):
        flags = _compute_flags(50_000, 90, 60.0, 10.0, 0.1)
        self.assertIn("BETTER_THAN_PEERS", flags)

    def test_unannounced_allocation_flag(self):
        flags = _compute_flags(50_000, 90, 10.0, 0.0, 0.1)
        self.assertIn("UNANNOUNCED_ALLOCATION", flags)

    def test_farm_saturation_flag(self):
        flags = _compute_flags(50_000, 90, 10.0, 10.0, 0.0005)
        self.assertIn("FARM_SATURATION", flags)

    def test_multiple_flags(self):
        flags = _compute_flags(2_000_000, 200, 60.0, 0.0, 0.0005)
        self.assertIn("HIGH_DILUTION", flags)
        self.assertIn("DELAYED_AIRDROP", flags)
        self.assertIn("BETTER_THAN_PEERS", flags)
        self.assertIn("UNANNOUNCED_ALLOCATION", flags)
        self.assertIn("FARM_SATURATION", flags)

    def test_exactly_1m_users_not_high_dilution(self):
        flags = _compute_flags(1_000_000, 90, 10.0, 10.0, 0.1)
        # exactly 1M is NOT > 1M threshold
        self.assertNotIn("HIGH_DILUTION", flags)

    def test_exactly_180d_not_delayed(self):
        flags = _compute_flags(50_000, 180, 10.0, 10.0, 0.1)
        self.assertNotIn("DELAYED_AIRDROP", flags)

    def test_farm_saturation_zero_not_flagged(self):
        """Zero points_per_dollar is not FARM_SATURATION (0 < threshold not satisfied if ==0)."""
        flags = _compute_flags(50_000, 90, 10.0, 10.0, 0.0)
        self.assertNotIn("FARM_SATURATION", flags)


# ---------------------------------------------------------------------------
# Tests for _analyze_program
# ---------------------------------------------------------------------------

class TestAnalyzeProgram(unittest.TestCase):

    def test_returns_dict(self):
        result = _analyze_program(_prog())
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = _analyze_program(_prog())
        for key in ("protocol", "implied_value_per_point_usd", "implied_apy_pct",
                    "dilution_risk_score", "comparison_premium_pct", "total_points_value_usd",
                    "value_label", "flags"):
            self.assertIn(key, result)

    def test_protocol_name(self):
        result = _analyze_program(_prog(protocol="Uniswap"))
        self.assertEqual(result["protocol"], "Uniswap")

    def test_value_per_point_positive(self):
        result = _analyze_program(_prog())
        self.assertGreater(result["implied_value_per_point_usd"], 0)

    def test_apy_positive(self):
        result = _analyze_program(_prog())
        self.assertGreater(result["implied_apy_pct"], 0)

    def test_flags_is_list(self):
        result = _analyze_program(_prog())
        self.assertIsInstance(result["flags"], list)

    def test_total_value_positive(self):
        result = _analyze_program(_prog())
        self.assertGreater(result["total_points_value_usd"], 0)

    def test_value_label_valid(self):
        result = _analyze_program(_prog())
        self.assertIn(result["value_label"],
                      ["EXCEPTIONAL", "GOOD", "FAIR", "POOR", "LIKELY_WORTHLESS"])

    def test_zero_fdv_gives_worthless(self):
        p = _prog(token_fdv_usd=0)
        result = _analyze_program(p)
        self.assertEqual(result["value_label"], "LIKELY_WORTHLESS")


# ---------------------------------------------------------------------------
# Tests for DeFiPointsToTokenConversionAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerEmpty(unittest.TestCase):

    def test_empty_programs(self):
        a = DeFiPointsToTokenConversionAnalyzer()
        result = a.analyze([], {"write_log": False})
        self.assertEqual(result["programs"], [])
        self.assertIsNone(result["best_program"])
        self.assertIsNone(result["worst_program"])
        self.assertEqual(result["average_implied_apy"], 0.0)
        self.assertEqual(result["total_points_value_usd"], 0.0)
        self.assertEqual(result["exceptional_count"], 0)

    def test_empty_has_timestamp(self):
        a = DeFiPointsToTokenConversionAnalyzer()
        result = a.analyze([], {"write_log": False})
        self.assertIn("timestamp", result)


class TestAnalyzerSingleProgram(unittest.TestCase):

    def setUp(self):
        self.a = DeFiPointsToTokenConversionAnalyzer()

    def test_single_program(self):
        result = self.a.analyze([_prog()], {"write_log": False})
        self.assertEqual(len(result["programs"]), 1)

    def test_single_best_and_worst_same(self):
        result = self.a.analyze([_prog(protocol="Only")], {"write_log": False})
        self.assertEqual(result["best_program"], "Only")
        self.assertEqual(result["worst_program"], "Only")

    def test_single_average_apy(self):
        prog = _prog()
        result = self.a.analyze([prog], {"write_log": False})
        self.assertAlmostEqual(
            result["average_implied_apy"],
            result["programs"][0]["implied_apy_pct"],
            places=4
        )

    def test_single_total_value(self):
        result = self.a.analyze([_prog()], {"write_log": False})
        self.assertAlmostEqual(
            result["total_points_value_usd"],
            result["programs"][0]["total_points_value_usd"],
            places=2
        )


class TestAnalyzerMultiplePrograms(unittest.TestCase):

    def setUp(self):
        self.a = DeFiPointsToTokenConversionAnalyzer()
        self.programs = [
            _prog(protocol="Alpha", token_fdv_usd=1_000_000_000, expected_token_allocation_pct=20.0),
            _prog(protocol="Beta", token_fdv_usd=100_000_000, expected_token_allocation_pct=5.0),
            _prog(protocol="Gamma", token_fdv_usd=50_000_000, expected_token_allocation_pct=2.0),
        ]

    def test_three_programs(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        self.assertEqual(len(result["programs"]), 3)

    def test_best_program_highest_apy(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        apys = {p["protocol"]: p["implied_apy_pct"] for p in result["programs"]}
        best = result["best_program"]
        self.assertEqual(apys[best], max(apys.values()))

    def test_worst_program_lowest_apy(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        apys = {p["protocol"]: p["implied_apy_pct"] for p in result["programs"]}
        worst = result["worst_program"]
        self.assertEqual(apys[worst], min(apys.values()))

    def test_average_apy_computation(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        manual_avg = sum(p["implied_apy_pct"] for p in result["programs"]) / 3
        self.assertAlmostEqual(result["average_implied_apy"], manual_avg, places=4)

    def test_total_value_sum(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        manual_total = sum(p["total_points_value_usd"] for p in result["programs"])
        self.assertAlmostEqual(result["total_points_value_usd"], manual_total, places=1)

    def test_exceptional_count(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        manual = sum(1 for p in result["programs"] if p["value_label"] == "EXCEPTIONAL")
        self.assertEqual(result["exceptional_count"], manual)

    def test_timestamp_present(self):
        result = self.a.analyze(self.programs, {"write_log": False})
        self.assertIn("timestamp", result)


class TestAnalyzerHighDilutionProgram(unittest.TestCase):

    def test_high_dilution_flag_propagated(self):
        a = DeFiPointsToTokenConversionAnalyzer()
        prog = _prog(eligible_users_count=2_000_000)
        result = a.analyze([prog], {"write_log": False})
        self.assertIn("HIGH_DILUTION", result["programs"][0]["flags"])

    def test_delayed_airdrop_flag(self):
        a = DeFiPointsToTokenConversionAnalyzer()
        prog = _prog(airdrop_date_days_from_now=200)
        result = a.analyze([prog], {"write_log": False})
        self.assertIn("DELAYED_AIRDROP", result["programs"][0]["flags"])

    def test_unannounced_allocation(self):
        a = DeFiPointsToTokenConversionAnalyzer()
        prog = _prog(expected_token_allocation_pct=0.0)
        result = a.analyze([prog], {"write_log": False})
        self.assertIn("UNANNOUNCED_ALLOCATION", result["programs"][0]["flags"])


# ---------------------------------------------------------------------------
# Tests for module-level analyze()
# ---------------------------------------------------------------------------

class TestModuleLevelAnalyze(unittest.TestCase):

    def test_module_analyze_returns_dict(self):
        result = analyze([_prog()], {"write_log": False})
        self.assertIsInstance(result, dict)

    def test_module_analyze_empty(self):
        result = analyze([], {"write_log": False})
        self.assertEqual(result["programs"], [])

    def test_module_analyze_consistent_with_class(self):
        progs = [_prog(protocol="X"), _prog(protocol="Y")]
        r1 = analyze(progs, {"write_log": False})
        r2 = DeFiPointsToTokenConversionAnalyzer().analyze(progs, {"write_log": False})
        self.assertEqual(r1["best_program"], r2["best_program"])
        self.assertEqual(r1["exceptional_count"], r2["exceptional_count"])


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

    def test_existing_non_list_file_is_reset(self):
        log = _tmp_log()
        with open(log, "w") as f:
            f.write("{}")
        _atomic_log(log, {"k": "v"})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_corrupted_file_is_reset(self):
        log = _tmp_log()
        with open(log, "w") as f:
            f.write("NOT JSON!!!")
        _atomic_log(log, {"k": "v"})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)


# ---------------------------------------------------------------------------
# Tests for write_log integration
# ---------------------------------------------------------------------------

class TestWriteLogIntegration(unittest.TestCase):

    def test_write_log_creates_file(self):
        log = _tmp_log()
        a = DeFiPointsToTokenConversionAnalyzer()
        a.analyze([_prog()], {"log_path": log, "write_log": True})
        self.assertTrue(os.path.exists(log))
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_write_log_false_no_file(self):
        log = _tmp_log()
        a = DeFiPointsToTokenConversionAnalyzer()
        a.analyze([_prog()], {"log_path": log, "write_log": False})
        self.assertFalse(os.path.exists(log))

    def test_log_entry_has_expected_keys(self):
        log = _tmp_log()
        a = DeFiPointsToTokenConversionAnalyzer()
        a.analyze([_prog()], {"log_path": log, "write_log": True})
        with open(log) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "program_count", "best_program",
                    "average_implied_apy", "total_points_value_usd", "exceptional_count"):
            self.assertIn(key, entry)
        os.unlink(log)


# ---------------------------------------------------------------------------
# Edge-case & robustness tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.a = DeFiPointsToTokenConversionAnalyzer()

    def test_missing_protocol_key(self):
        prog = {k: v for k, v in _prog().items() if k != "protocol"}
        result = self.a.analyze([prog], {"write_log": False})
        self.assertEqual(result["programs"][0]["protocol"], "UNKNOWN")

    def test_all_zero_program(self):
        prog = {k: 0 for k in _prog()}
        result = self.a.analyze([prog], {"write_log": False})
        self.assertEqual(result["programs"][0]["implied_apy_pct"], 0.0)

    def test_very_large_fdv(self):
        prog = _prog(token_fdv_usd=1e15)
        result = self.a.analyze([prog], {"write_log": False})
        self.assertGreater(result["programs"][0]["implied_value_per_point_usd"], 0)

    def test_string_numbers_coerced(self):
        prog = _prog()
        prog["token_fdv_usd"] = "500000000"
        prog["total_points_issued"] = "1000000"
        # float() conversion should handle these
        result = self.a.analyze([prog], {"write_log": False})
        self.assertGreater(result["programs"][0]["implied_apy_pct"], 0)

    def test_ten_programs_performance(self):
        progs = [_prog(protocol=f"P{i}", token_fdv_usd=float(i + 1) * 1e8) for i in range(10)]
        result = self.a.analyze(progs, {"write_log": False})
        self.assertEqual(len(result["programs"]), 10)

    def test_config_none_defaults(self):
        result = DeFiPointsToTokenConversionAnalyzer().analyze([_prog()], None)
        self.assertIsNotNone(result)

    def test_programs_preserve_order(self):
        protocols = ["Alpha", "Beta", "Gamma"]
        progs = [_prog(protocol=p) for p in protocols]
        result = self.a.analyze(progs, {"write_log": False})
        returned = [p["protocol"] for p in result["programs"]]
        self.assertEqual(returned, protocols)


if __name__ == "__main__":
    unittest.main()

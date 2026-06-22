"""
Tests for MP-879 DeFiPointsProgramAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_points_program_analyzer -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_points_program_analyzer import (
    analyze,
    analyze_and_log,
    init_log,
    _airdrop_probability,
    _LOG_FILE,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _active_easy_program(**overrides):
    base = {
        "protocol": "ProtocolA",
        "points_per_usd_per_day": 10.0,
        "total_points_issued": 1_000_000.0,
        "expected_airdrop_token_supply_pct": 10.0,
        "token_fdv_estimate_usd": 100_000_000.0,
        "days_remaining": 30,
        "capital_usd": 10_000.0,
        "holding_days": 30,
        "program_status": "ACTIVE",
        "qualification_difficulty": "EASY",
    }
    base.update(overrides)
    return base


def _rumored_program(**overrides):
    base = {
        "protocol": "RumoredProtocol",
        "points_per_usd_per_day": 5.0,
        "total_points_issued": 500_000.0,
        "expected_airdrop_token_supply_pct": 5.0,
        "token_fdv_estimate_usd": 50_000_000.0,
        "days_remaining": 0,
        "capital_usd": 5_000.0,
        "holding_days": 15,
        "program_status": "RUMORED",
        "qualification_difficulty": "MODERATE",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):
    def test_empty_returns_correct_structure(self):
        result = analyze([])
        self.assertEqual(result["programs"], [])
        self.assertIsNone(result["best_program"])
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["average_implied_apy_pct"], 0.0)

    def test_empty_has_timestamp(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_empty_none_config(self):
        result = analyze([], config=None)
        self.assertEqual(result["programs"], [])

    def test_empty_explicit_config(self):
        result = analyze([], config={"risk_discount_pct": 50})
        self.assertEqual(result["average_implied_apy_pct"], 0.0)


# ---------------------------------------------------------------------------
# 2. Single program — points calculation
# ---------------------------------------------------------------------------

class TestSingleProgramPoints(unittest.TestCase):
    def setUp(self):
        self.p = _active_easy_program()
        self.result = analyze([self.p])
        self.prog = self.result["programs"][0]

    def test_your_points_formula(self):
        # 10_000 * 10 * 30 = 3_000_000
        expected = 10_000.0 * 10.0 * 30.0
        self.assertAlmostEqual(self.prog["your_points"], expected, places=4)

    def test_your_share_pct(self):
        # 3_000_000 / 1_000_000 * 100 = 300.0
        self.assertAlmostEqual(self.prog["your_share_of_total_pct"], 300.0, places=4)

    def test_gross_airdrop_value(self):
        # share=3.0 * (10/100) * 100_000_000 = 3_000_000
        # actual formula: your_share/100 * airdrop_supply_pct/100 * fdv
        expected = (300.0 / 100.0) * (10.0 / 100.0) * 100_000_000.0
        self.assertAlmostEqual(self.prog["gross_airdrop_value_usd"], expected, places=2)

    def test_discounted_value_default_70pct(self):
        gross = self.prog["gross_airdrop_value_usd"]
        expected = gross * 0.30  # 1 - 0.70
        self.assertAlmostEqual(self.prog["discounted_airdrop_value_usd"], expected, places=2)

    def test_implied_daily_yield(self):
        discounted = self.prog["discounted_airdrop_value_usd"]
        expected_daily = discounted / 10_000.0 / 30.0 * 100.0
        self.assertAlmostEqual(self.prog["implied_daily_yield_pct"], expected_daily, places=6)

    def test_implied_apy(self):
        daily = self.prog["implied_daily_yield_pct"]
        self.assertAlmostEqual(self.prog["implied_apy_pct"], daily * 365.0, places=6)

    def test_protocol_name_preserved(self):
        self.assertEqual(self.prog["protocol"], "ProtocolA")

    def test_program_status_uppercase(self):
        self.assertEqual(self.prog["program_status"], "ACTIVE")

    def test_single_program_efficiency_100(self):
        self.assertEqual(self.prog["efficiency_score"], 100)


# ---------------------------------------------------------------------------
# 3. Airdrop probability labels
# ---------------------------------------------------------------------------

class TestAirdropProbability(unittest.TestCase):
    def test_active_easy_days_remaining_high(self):
        label = _airdrop_probability("ACTIVE", "EASY", 10)
        self.assertEqual(label, "HIGH")

    def test_active_moderate_days_remaining_high(self):
        label = _airdrop_probability("ACTIVE", "MODERATE", 5)
        self.assertEqual(label, "HIGH")

    def test_active_easy_no_days_moderate(self):
        label = _airdrop_probability("ACTIVE", "EASY", 0)
        self.assertEqual(label, "MODERATE")

    def test_active_hard_with_days_moderate(self):
        label = _airdrop_probability("ACTIVE", "HARD", 20)
        self.assertEqual(label, "MODERATE")

    def test_active_whale_only_moderate(self):
        label = _airdrop_probability("ACTIVE", "WHALE_ONLY", 10)
        self.assertEqual(label, "MODERATE")

    def test_announced_low(self):
        label = _airdrop_probability("ANNOUNCED", "EASY", 10)
        self.assertEqual(label, "LOW")

    def test_ended_low(self):
        label = _airdrop_probability("ENDED", "MODERATE", 0)
        self.assertEqual(label, "LOW")

    def test_rumored_speculative(self):
        label = _airdrop_probability("RUMORED", "EASY", 30)
        self.assertEqual(label, "SPECULATIVE")

    def test_unknown_status_speculative(self):
        label = _airdrop_probability("UNKNOWN", "EASY", 10)
        self.assertEqual(label, "SPECULATIVE")


# ---------------------------------------------------------------------------
# 4. Edge cases: zero capital, zero holding_days, zero total_points
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_zero_capital_points_zero(self):
        p = _active_easy_program(capital_usd=0.0)
        result = analyze([p])
        prog = result["programs"][0]
        self.assertEqual(prog["your_points"], 0.0)
        self.assertEqual(prog["implied_daily_yield_pct"], 0.0)
        self.assertEqual(prog["implied_apy_pct"], 0.0)

    def test_zero_holding_days_points_zero(self):
        p = _active_easy_program(holding_days=0)
        result = analyze([p])
        prog = result["programs"][0]
        self.assertEqual(prog["your_points"], 0.0)

    def test_zero_total_points_share_zero(self):
        p = _active_easy_program(total_points_issued=0.0)
        result = analyze([p])
        prog = result["programs"][0]
        self.assertEqual(prog["your_share_of_total_pct"], 0.0)
        self.assertEqual(prog["gross_airdrop_value_usd"], 0.0)

    def test_zero_capital_efficiency_zero(self):
        p = _active_easy_program(capital_usd=0.0)
        result = analyze([p])
        # single program with zero apy → efficiency = 0
        self.assertEqual(result["programs"][0]["efficiency_score"], 0)

    def test_zero_fdv_gross_zero(self):
        p = _active_easy_program(token_fdv_estimate_usd=0.0)
        result = analyze([p])
        self.assertEqual(result["programs"][0]["gross_airdrop_value_usd"], 0.0)

    def test_internal_capital_usd_stripped(self):
        p = _active_easy_program()
        result = analyze([p])
        for prog in result["programs"]:
            self.assertNotIn("_capital_usd", prog)


# ---------------------------------------------------------------------------
# 5. Custom risk_discount_pct
# ---------------------------------------------------------------------------

class TestCustomDiscount(unittest.TestCase):
    def test_zero_discount_full_value(self):
        p = _active_easy_program()
        result = analyze([p], config={"risk_discount_pct": 0.0})
        prog = result["programs"][0]
        self.assertAlmostEqual(
            prog["discounted_airdrop_value_usd"],
            prog["gross_airdrop_value_usd"],
            places=4,
        )

    def test_100_discount_zero_value(self):
        p = _active_easy_program()
        result = analyze([p], config={"risk_discount_pct": 100.0})
        prog = result["programs"][0]
        self.assertAlmostEqual(prog["discounted_airdrop_value_usd"], 0.0, places=4)

    def test_50_discount_half_value(self):
        p = _active_easy_program()
        result = analyze([p], config={"risk_discount_pct": 50.0})
        prog = result["programs"][0]
        expected = prog["gross_airdrop_value_usd"] * 0.5
        self.assertAlmostEqual(prog["discounted_airdrop_value_usd"], expected, places=4)


# ---------------------------------------------------------------------------
# 6. Multiple programs — efficiency scoring
# ---------------------------------------------------------------------------

class TestMultiplePrograms(unittest.TestCase):
    def setUp(self):
        self.programs = [
            _active_easy_program(
                protocol="Alpha",
                capital_usd=10000.0,
                points_per_usd_per_day=10.0,
                total_points_issued=1_000_000.0,
                holding_days=30,
                days_remaining=30,
            ),
            _active_easy_program(
                protocol="Beta",
                capital_usd=5000.0,
                points_per_usd_per_day=5.0,
                total_points_issued=1_000_000.0,
                holding_days=30,
                days_remaining=30,
            ),
        ]
        self.result = analyze(self.programs)

    def test_two_programs_returned(self):
        self.assertEqual(len(self.result["programs"]), 2)

    def test_highest_apy_gets_score_100(self):
        progs_by_name = {p["protocol"]: p for p in self.result["programs"]}
        # Alpha has more points → higher APY → score 100
        self.assertEqual(progs_by_name["Alpha"]["efficiency_score"], 100)

    def test_lower_apy_score_less_than_100(self):
        progs_by_name = {p["protocol"]: p for p in self.result["programs"]}
        self.assertLess(progs_by_name["Beta"]["efficiency_score"], 100)

    def test_efficiency_score_bounded_0_100(self):
        for prog in self.result["programs"]:
            self.assertGreaterEqual(prog["efficiency_score"], 0)
            self.assertLessEqual(prog["efficiency_score"], 100)

    def test_active_count(self):
        self.assertEqual(self.result["active_count"], 2)

    def test_best_program_is_highest_apy_active(self):
        progs_by_name = {p["protocol"]: p for p in self.result["programs"]}
        alpha_apy = progs_by_name["Alpha"]["implied_apy_pct"]
        beta_apy = progs_by_name["Beta"]["implied_apy_pct"]
        if alpha_apy >= beta_apy:
            self.assertEqual(self.result["best_program"], "Alpha")
        else:
            self.assertEqual(self.result["best_program"], "Beta")

    def test_average_apy_is_mean(self):
        apys = [p["implied_apy_pct"] for p in self.result["programs"]]
        expected_avg = sum(apys) / len(apys)
        self.assertAlmostEqual(self.result["average_implied_apy_pct"], expected_avg, places=6)


# ---------------------------------------------------------------------------
# 7. best_program — only ACTIVE programs
# ---------------------------------------------------------------------------

class TestBestProgram(unittest.TestCase):
    def test_best_is_none_when_no_active(self):
        programs = [
            _active_easy_program(protocol="P1", program_status="ENDED"),
            _rumored_program(protocol="P2"),
        ]
        result = analyze(programs)
        self.assertIsNone(result["best_program"])

    def test_best_is_active_highest_apy(self):
        programs = [
            _active_easy_program(
                protocol="HighAPY",
                capital_usd=50000.0,
                points_per_usd_per_day=20.0,
                total_points_issued=500_000.0,
                days_remaining=10,
            ),
            _active_easy_program(
                protocol="LowAPY",
                capital_usd=1000.0,
                points_per_usd_per_day=1.0,
                total_points_issued=10_000_000.0,
                days_remaining=10,
            ),
        ]
        result = analyze(programs)
        self.assertEqual(result["best_program"], "HighAPY")

    def test_ended_program_not_best(self):
        programs = [
            _active_easy_program(
                protocol="ActiveSmall",
                capital_usd=100.0,
                points_per_usd_per_day=1.0,
                total_points_issued=1_000_000.0,
            ),
            _active_easy_program(
                protocol="EndedBig",
                program_status="ENDED",
                capital_usd=100000.0,
                points_per_usd_per_day=100.0,
                total_points_issued=100_000.0,
            ),
        ]
        result = analyze(programs)
        # EndedBig is not ACTIVE, so not eligible for best_program
        self.assertEqual(result["best_program"], "ActiveSmall")


# ---------------------------------------------------------------------------
# 8. Recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_high_high_apy_deploy_message(self):
        p = _active_easy_program(
            capital_usd=50000.0,
            points_per_usd_per_day=100.0,
            total_points_issued=100_000.0,
            expected_airdrop_token_supply_pct=20.0,
            token_fdv_estimate_usd=500_000_000.0,
        )
        result = analyze([p])
        rec = result["programs"][0]["recommendation"]
        self.assertIn("Deploy", rec)
        self.assertIn("High probability", rec)
        self.assertIn("implied APY", rec)

    def test_high_low_apy_moderate_returns(self):
        # Create a HIGH label but low APY (< 20%)
        # Make implied_apy very small by large total_points
        p = _active_easy_program(
            capital_usd=1000.0,
            points_per_usd_per_day=1.0,
            total_points_issued=1_000_000_000.0,  # very large dilution
            expected_airdrop_token_supply_pct=1.0,
            token_fdv_estimate_usd=10_000_000.0,
            days_remaining=5,
        )
        result = analyze([p])
        prog = result["programs"][0]
        if prog["airdrop_probability_label"] == "HIGH" and prog["implied_apy_pct"] < 20:
            rec = prog["recommendation"]
            self.assertIn("Moderate returns", rec)

    def test_moderate_recommendation(self):
        p = _active_easy_program(
            program_status="ACTIVE",
            qualification_difficulty="HARD",
            days_remaining=10,
        )
        result = analyze([p])
        prog = result["programs"][0]
        self.assertEqual(prog["airdrop_probability_label"], "MODERATE")
        self.assertIn("Possible airdrop", prog["recommendation"])

    def test_low_recommendation(self):
        p = _active_easy_program(program_status="ANNOUNCED")
        result = analyze([p])
        rec = result["programs"][0]["recommendation"]
        self.assertIn("Lower certainty", rec)

    def test_speculative_recommendation(self):
        p = _rumored_program()
        result = analyze([p])
        rec = result["programs"][0]["recommendation"]
        self.assertIn("Rumored only", rec)

    def test_ended_low_label_and_recommendation(self):
        p = _active_easy_program(program_status="ENDED")
        result = analyze([p])
        prog = result["programs"][0]
        self.assertEqual(prog["airdrop_probability_label"], "LOW")
        self.assertIn("Speculative position", prog["recommendation"])


# ---------------------------------------------------------------------------
# 9. All statuses and difficulties
# ---------------------------------------------------------------------------

class TestAllStatusesAndDifficulties(unittest.TestCase):
    def _make(self, status, diff, days=10):
        return _active_easy_program(
            program_status=status,
            qualification_difficulty=diff,
            days_remaining=days,
        )

    def test_active_easy_high(self):
        r = analyze([self._make("ACTIVE", "EASY", 10)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "HIGH")

    def test_active_moderate_high(self):
        r = analyze([self._make("ACTIVE", "MODERATE", 10)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "HIGH")

    def test_active_hard_moderate(self):
        r = analyze([self._make("ACTIVE", "HARD", 10)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "MODERATE")

    def test_active_whale_only_moderate(self):
        r = analyze([self._make("ACTIVE", "WHALE_ONLY", 10)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "MODERATE")

    def test_active_easy_zero_days_moderate(self):
        r = analyze([self._make("ACTIVE", "EASY", 0)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "MODERATE")

    def test_announced_low(self):
        r = analyze([self._make("ANNOUNCED", "EASY", 10)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "LOW")

    def test_ended_low(self):
        r = analyze([self._make("ENDED", "EASY", 0)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "LOW")

    def test_rumored_speculative(self):
        r = analyze([self._make("RUMORED", "EASY", 30)])
        self.assertEqual(r["programs"][0]["airdrop_probability_label"], "SPECULATIVE")


# ---------------------------------------------------------------------------
# 10. All-zero APY: efficiency scores all 0
# ---------------------------------------------------------------------------

class TestAllZeroAPY(unittest.TestCase):
    def test_all_zero_efficiency_all_zero(self):
        programs = [
            _active_easy_program(protocol="A", capital_usd=0.0),
            _active_easy_program(protocol="B", capital_usd=0.0),
        ]
        result = analyze(programs)
        for p in result["programs"]:
            self.assertEqual(p["efficiency_score"], 0)

    def test_all_zero_average_apy_zero(self):
        programs = [
            _active_easy_program(protocol="A", capital_usd=0.0),
            _active_easy_program(protocol="B", capital_usd=0.0),
        ]
        result = analyze(programs)
        self.assertAlmostEqual(result["average_implied_apy_pct"], 0.0, places=6)


# ---------------------------------------------------------------------------
# 11. Mixing statuses — active_count and best_program
# ---------------------------------------------------------------------------

class TestMixedStatuses(unittest.TestCase):
    def setUp(self):
        self.programs = [
            _active_easy_program(protocol="Act1", program_status="ACTIVE", days_remaining=10),
            _active_easy_program(protocol="End1", program_status="ENDED", days_remaining=0),
            _rumored_program(protocol="Rum1"),
            _active_easy_program(protocol="Ann1", program_status="ANNOUNCED", days_remaining=0),
        ]
        self.result = analyze(self.programs)

    def test_active_count_one(self):
        self.assertEqual(self.result["active_count"], 1)

    def test_best_program_is_only_active(self):
        self.assertEqual(self.result["best_program"], "Act1")

    def test_all_four_programs_returned(self):
        self.assertEqual(len(self.result["programs"]), 4)


# ---------------------------------------------------------------------------
# 12. Log file operations
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_log_creates_empty_file(self):
        init_log(data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        self.assertTrue(os.path.exists(log_path))
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_init_log_does_not_overwrite_existing(self):
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path, "w") as f:
            json.dump([{"existing": True}], f)
        init_log(data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"existing": True}])

    def test_analyze_and_log_creates_file(self):
        analyze_and_log([_active_easy_program()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        self.assertTrue(os.path.exists(log_path))

    def test_analyze_and_log_appends(self):
        for _ in range(3):
            analyze_and_log([_active_easy_program()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_caps_at_100(self):
        for _ in range(_RING_BUFFER_MAX + 5):
            analyze_and_log([_active_easy_program()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _RING_BUFFER_MAX)

    def test_log_entry_has_timestamp(self):
        analyze_and_log([_active_easy_program()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_programs(self):
        analyze_and_log([_active_easy_program()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("programs", data[0])

    def test_log_recovery_from_corrupt_file(self):
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path, "w") as f:
            f.write("not valid json{{}")
        # Should not raise; starts fresh
        analyze_and_log([_active_easy_program()], data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 13. Return structure completeness
# ---------------------------------------------------------------------------

class TestReturnStructure(unittest.TestCase):
    TOP_KEYS = {"programs", "best_program", "active_count", "average_implied_apy_pct", "timestamp"}
    PROG_KEYS = {
        "protocol", "program_status", "your_points", "your_share_of_total_pct",
        "gross_airdrop_value_usd", "discounted_airdrop_value_usd",
        "implied_daily_yield_pct", "implied_apy_pct",
        "airdrop_probability_label", "efficiency_score", "recommendation",
    }

    def test_top_level_keys_present(self):
        result = analyze([_active_easy_program()])
        self.assertEqual(set(result.keys()), self.TOP_KEYS)

    def test_program_keys_present(self):
        result = analyze([_active_easy_program()])
        prog = result["programs"][0]
        for key in self.PROG_KEYS:
            self.assertIn(key, prog, msg=f"Missing key: {key}")

    def test_no_internal_keys_leaked(self):
        result = analyze([_active_easy_program()])
        prog = result["programs"][0]
        self.assertNotIn("_capital_usd", prog)

    def test_timestamp_is_float(self):
        result = analyze([_active_easy_program()])
        self.assertIsInstance(result["timestamp"], float)

    def test_active_count_is_int(self):
        result = analyze([_active_easy_program()])
        self.assertIsInstance(result["active_count"], int)

    def test_average_apy_is_float(self):
        result = analyze([_active_easy_program()])
        self.assertIsInstance(result["average_implied_apy_pct"], float)

    def test_best_program_is_str_or_none(self):
        result = analyze([_active_easy_program()])
        bp = result["best_program"]
        self.assertTrue(bp is None or isinstance(bp, str))

    def test_efficiency_score_int(self):
        result = analyze([_active_easy_program()])
        self.assertIsInstance(result["programs"][0]["efficiency_score"], int)

    def test_recommendation_is_str(self):
        result = analyze([_active_easy_program()])
        self.assertIsInstance(result["programs"][0]["recommendation"], str)


# ---------------------------------------------------------------------------
# 14. Numeric accuracy and boundary conditions
# ---------------------------------------------------------------------------

class TestNumerics(unittest.TestCase):
    def test_high_apy_above_20_triggers_deploy_message(self):
        """Verify the recommendation threshold for HIGH + apy >= 20."""
        p = _active_easy_program(
            capital_usd=10000.0,
            points_per_usd_per_day=100.0,
            total_points_issued=100_000.0,
            expected_airdrop_token_supply_pct=10.0,
            token_fdv_estimate_usd=1_000_000_000.0,
        )
        result = analyze([p], config={"risk_discount_pct": 70.0})
        prog = result["programs"][0]
        self.assertGreater(prog["implied_apy_pct"], 20.0)
        self.assertIn("Deploy", prog["recommendation"])

    def test_share_greater_than_100_pct_works(self):
        """When capital earns more points than total issued (edge), share > 100%."""
        p = _active_easy_program(
            capital_usd=100_000.0,
            points_per_usd_per_day=100.0,
            total_points_issued=1_000.0,  # tiny total
        )
        result = analyze([p])
        prog = result["programs"][0]
        self.assertGreater(prog["your_share_of_total_pct"], 100.0)

    def test_varying_risk_discounts(self):
        for disc in [0, 25, 50, 75, 99, 100]:
            r = analyze([_active_easy_program()], config={"risk_discount_pct": disc})
            self.assertGreaterEqual(r["programs"][0]["discounted_airdrop_value_usd"], 0.0)

    def test_multiple_programs_relative_efficiency(self):
        programs = [
            _active_easy_program(
                protocol="Small",
                capital_usd=1000.0,
                points_per_usd_per_day=1.0,
                total_points_issued=1_000_000.0,
            ),
            _active_easy_program(
                protocol="Large",
                capital_usd=100_000.0,
                points_per_usd_per_day=10.0,
                total_points_issued=1_000_000.0,
            ),
        ]
        result = analyze(programs)
        progs = {p["protocol"]: p for p in result["programs"]}
        # Large has much higher APY → score 100
        self.assertEqual(progs["Large"]["efficiency_score"], 100)
        self.assertLess(progs["Small"]["efficiency_score"], 100)

    def test_apy_365x_daily(self):
        """implied_apy_pct must equal implied_daily_yield_pct * 365."""
        p = _active_easy_program()
        result = analyze([p])
        prog = result["programs"][0]
        self.assertAlmostEqual(
            prog["implied_apy_pct"],
            prog["implied_daily_yield_pct"] * 365.0,
            places=8,
        )


# ---------------------------------------------------------------------------
# 15. Miscellaneous
# ---------------------------------------------------------------------------

class TestMiscellaneous(unittest.TestCase):
    def test_program_status_lowercased_normalized(self):
        p = _active_easy_program(program_status="active")
        result = analyze([p])
        self.assertEqual(result["programs"][0]["program_status"], "ACTIVE")

    def test_config_none_uses_defaults(self):
        p = _active_easy_program()
        r_none = analyze([p], config=None)
        r_explicit = analyze([p], config={"risk_discount_pct": 70.0})
        self.assertAlmostEqual(
            r_none["programs"][0]["discounted_airdrop_value_usd"],
            r_explicit["programs"][0]["discounted_airdrop_value_usd"],
            places=4,
        )

    def test_three_programs_average_apy(self):
        programs = [_active_easy_program(protocol=f"P{i}") for i in range(3)]
        result = analyze(programs)
        apys = [p["implied_apy_pct"] for p in result["programs"]]
        self.assertAlmostEqual(
            result["average_implied_apy_pct"],
            sum(apys) / 3,
            places=6,
        )

    def test_large_fdv_no_overflow(self):
        p = _active_easy_program(token_fdv_estimate_usd=1e15)
        result = analyze([p])
        self.assertIsInstance(result["programs"][0]["gross_airdrop_value_usd"], float)

    def test_very_small_points_per_usd(self):
        p = _active_easy_program(points_per_usd_per_day=1e-10)
        result = analyze([p])
        self.assertAlmostEqual(result["programs"][0]["your_points"], 10_000.0 * 1e-10 * 30.0)

    def test_best_program_none_when_all_ended(self):
        programs = [
            _active_easy_program(protocol="X", program_status="ENDED"),
            _active_easy_program(protocol="Y", program_status="ANNOUNCED"),
        ]
        result = analyze(programs)
        self.assertIsNone(result["best_program"])

    def test_all_active_count_matches(self):
        programs = [
            _active_easy_program(protocol=f"A{i}", program_status="ACTIVE", days_remaining=10)
            for i in range(5)
        ]
        result = analyze(programs)
        self.assertEqual(result["active_count"], 5)

    def test_announced_zero_active(self):
        programs = [_active_easy_program(program_status="ANNOUNCED")]
        result = analyze(programs)
        self.assertEqual(result["active_count"], 0)


if __name__ == "__main__":
    unittest.main()

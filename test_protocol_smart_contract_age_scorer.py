"""
Tests for MP-866 ProtocolSmartContractAgeScorer
Run with: python3 -m unittest spa_core.tests.test_protocol_smart_contract_age_scorer
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_smart_contract_age_scorer import (
    analyze,
    log_result,
    _age_score,
    _tvl_stress_score,
    _incident_score,
    _stability_score_full,
    _safety_grade,
    _battle_test_label,
    _complexity_risk,
)


def _make_contract(
    protocol="TestProto",
    age_days=730,
    peak_tvl=100_000_000.0,
    current_tvl=50_000_000.0,
    exploit_count=0,
    exploit_loss=0.0,
    upgrade_count=0,
    last_upgrade=999,
    formal=False,
    loc=2000,
):
    return {
        "protocol": protocol,
        "contract_age_days": age_days,
        "peak_tvl_usd": peak_tvl,
        "current_tvl_usd": current_tvl,
        "exploit_count": exploit_count,
        "exploit_total_loss_usd": exploit_loss,
        "upgrade_count": upgrade_count,
        "last_upgrade_days_ago": last_upgrade,
        "formal_verification": formal,
        "lines_of_code": loc,
    }


class TestAgeScore(unittest.TestCase):

    def test_4_years_returns_25(self):
        self.assertEqual(_age_score(1460), 25)

    def test_above_4_years_returns_25(self):
        self.assertEqual(_age_score(2000), 25)

    def test_2_years_returns_20(self):
        self.assertEqual(_age_score(730), 20)

    def test_between_2_and_4_years_returns_20(self):
        self.assertEqual(_age_score(1000), 20)

    def test_1_year_returns_15(self):
        self.assertEqual(_age_score(365), 15)

    def test_between_1_and_2_years_returns_15(self):
        self.assertEqual(_age_score(500), 15)

    def test_180_days_returns_10(self):
        self.assertEqual(_age_score(180), 10)

    def test_between_180_and_365_returns_10(self):
        self.assertEqual(_age_score(270), 10)

    def test_90_days_returns_5(self):
        self.assertEqual(_age_score(90), 5)

    def test_between_90_and_180_returns_5(self):
        self.assertEqual(_age_score(120), 5)

    def test_below_90_returns_0(self):
        self.assertEqual(_age_score(89), 0)

    def test_zero_returns_0(self):
        self.assertEqual(_age_score(0), 0)


class TestTVLStressScore(unittest.TestCase):

    def test_1_billion_returns_25(self):
        self.assertEqual(_tvl_stress_score(1_000_000_000), 25)

    def test_above_1_billion_returns_25(self):
        self.assertEqual(_tvl_stress_score(5_000_000_000), 25)

    def test_100_million_returns_20(self):
        self.assertEqual(_tvl_stress_score(100_000_000), 20)

    def test_between_100m_and_1b_returns_20(self):
        self.assertEqual(_tvl_stress_score(500_000_000), 20)

    def test_10_million_returns_15(self):
        self.assertEqual(_tvl_stress_score(10_000_000), 15)

    def test_between_10m_and_100m_returns_15(self):
        self.assertEqual(_tvl_stress_score(50_000_000), 15)

    def test_1_million_returns_8(self):
        self.assertEqual(_tvl_stress_score(1_000_000), 8)

    def test_between_1m_and_10m_returns_8(self):
        self.assertEqual(_tvl_stress_score(5_000_000), 8)

    def test_100k_returns_3(self):
        self.assertEqual(_tvl_stress_score(100_000), 3)

    def test_between_100k_and_1m_returns_3(self):
        self.assertEqual(_tvl_stress_score(500_000), 3)

    def test_below_100k_returns_0(self):
        self.assertEqual(_tvl_stress_score(99_999), 0)

    def test_zero_returns_0(self):
        self.assertEqual(_tvl_stress_score(0), 0)


class TestIncidentScore(unittest.TestCase):

    def test_no_exploits_returns_25(self):
        self.assertEqual(_incident_score(0, 0.0), 25)

    def test_one_exploit_small_loss_returns_15(self):
        self.assertEqual(_incident_score(1, 0.005), 15)

    def test_one_exploit_larger_loss_returns_10(self):
        self.assertEqual(_incident_score(1, 0.05), 10)

    def test_two_exploits_returns_5(self):
        self.assertEqual(_incident_score(2, 0.0), 5)

    def test_three_exploits_returns_0(self):
        self.assertEqual(_incident_score(3, 0.0), 0)

    def test_four_exploits_returns_0(self):
        self.assertEqual(_incident_score(4, 0.0), 0)

    def test_loss_ratio_50pct_penalty_applied(self):
        # exploit_count=0 → raw=25, loss>=0.5 → -10 = 15
        self.assertEqual(_incident_score(0, 0.5), 15)

    def test_loss_ratio_25pct_penalty_applied(self):
        # exploit_count=0 → raw=25, loss>=0.25 → -5 = 20
        self.assertEqual(_incident_score(0, 0.25), 20)

    def test_penalty_does_not_go_negative(self):
        # exploit_count=3 → raw=0, loss>=0.5 → -10 → min=0
        self.assertEqual(_incident_score(3, 0.9), 0)

    def test_two_exploits_with_50pct_loss(self):
        # raw=5, -10 → 0
        self.assertEqual(_incident_score(2, 0.6), 0)


class TestStabilityScore(unittest.TestCase):

    def test_no_upgrades_returns_25(self):
        self.assertEqual(_stability_score_full(0, 999), 25)

    def test_one_upgrade_old_returns_20(self):
        self.assertEqual(_stability_score_full(1, 365), 20)

    def test_one_upgrade_recent_returns_15(self):
        # upgrade_count=1 but last upgrade 200 days ago, not >= 365 → next bracket
        # upgrade_count=1 ≤ 3 and last >= 180 → 15
        self.assertEqual(_stability_score_full(1, 200), 15)

    def test_three_upgrades_old_returns_15(self):
        self.assertEqual(_stability_score_full(3, 200), 15)

    def test_five_upgrades_returns_10(self):
        self.assertEqual(_stability_score_full(5, 100), 10)

    def test_ten_upgrades_returns_5(self):
        self.assertEqual(_stability_score_full(10, 60), 5)

    def test_eleven_upgrades_returns_0(self):
        self.assertEqual(_stability_score_full(11, 60), 0)

    def test_recent_upgrade_returns_0(self):
        # last_upgrade_days_ago < 30 → 0
        self.assertEqual(_stability_score_full(1, 10), 0)

    def test_fresh_upgrade_any_count_returns_0(self):
        self.assertEqual(_stability_score_full(2, 5), 0)


class TestSafetyGrade(unittest.TestCase):

    def test_90_plus_is_A_plus(self):
        self.assertEqual(_safety_grade(90), "A+")
        self.assertEqual(_safety_grade(100), "A+")

    def test_80_to_89_is_A(self):
        self.assertEqual(_safety_grade(80), "A")
        self.assertEqual(_safety_grade(89), "A")

    def test_65_to_79_is_B(self):
        self.assertEqual(_safety_grade(65), "B")
        self.assertEqual(_safety_grade(79), "B")

    def test_50_to_64_is_C(self):
        self.assertEqual(_safety_grade(50), "C")
        self.assertEqual(_safety_grade(64), "C")

    def test_30_to_49_is_D(self):
        self.assertEqual(_safety_grade(30), "D")
        self.assertEqual(_safety_grade(49), "D")

    def test_below_30_is_F(self):
        self.assertEqual(_safety_grade(0), "F")
        self.assertEqual(_safety_grade(29), "F")


class TestBattleTestLabel(unittest.TestCase):

    def test_80_plus_is_BATTLE_TESTED(self):
        self.assertEqual(_battle_test_label(80), "BATTLE_TESTED")
        self.assertEqual(_battle_test_label(100), "BATTLE_TESTED")

    def test_60_to_79_is_PROVEN(self):
        self.assertEqual(_battle_test_label(60), "PROVEN")
        self.assertEqual(_battle_test_label(79), "PROVEN")

    def test_40_to_59_is_MATURING(self):
        self.assertEqual(_battle_test_label(40), "MATURING")
        self.assertEqual(_battle_test_label(59), "MATURING")

    def test_20_to_39_is_YOUNG(self):
        self.assertEqual(_battle_test_label(20), "YOUNG")
        self.assertEqual(_battle_test_label(39), "YOUNG")

    def test_below_20_is_UNPROVEN(self):
        self.assertEqual(_battle_test_label(0), "UNPROVEN")
        self.assertEqual(_battle_test_label(19), "UNPROVEN")


class TestComplexityRisk(unittest.TestCase):

    def test_10000_lines_is_HIGH(self):
        self.assertEqual(_complexity_risk(10000), "HIGH")

    def test_above_10000_is_HIGH(self):
        self.assertEqual(_complexity_risk(20000), "HIGH")

    def test_3000_lines_is_MEDIUM(self):
        self.assertEqual(_complexity_risk(3000), "MEDIUM")

    def test_between_3000_and_9999_is_MEDIUM(self):
        self.assertEqual(_complexity_risk(5000), "MEDIUM")

    def test_below_3000_is_LOW(self):
        self.assertEqual(_complexity_risk(2999), "LOW")

    def test_zero_is_LOW(self):
        self.assertEqual(_complexity_risk(0), "LOW")


class TestEmpty(unittest.TestCase):

    def test_empty_contracts(self):
        result = analyze([])
        self.assertEqual(result["contracts"], [])
        self.assertIsNone(result["safest_protocol"])
        self.assertIsNone(result["riskiest_protocol"])
        self.assertEqual(result["battle_tested_count"], 0)
        self.assertAlmostEqual(result["average_score"], 0.0)

    def test_empty_has_timestamp(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestAnalyzeSingleContract(unittest.TestCase):

    def test_perfect_contract_max_score(self):
        # age=2000→25, tvl=2e9→25, exploits=0→25, upgrades=0→25 = 100
        c = _make_contract(age_days=2000, peak_tvl=2e9, exploit_count=0, upgrade_count=0, loc=500)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["battle_test_score"], 100)

    def test_brand_new_contract_low_score(self):
        # age=30→0, tvl=50000→0, exploit=3→0, upgrade=20+last=5→0 = 0
        c = _make_contract(age_days=30, peak_tvl=50000.0, exploit_count=3, upgrade_count=20, last_upgrade=5)
        result = analyze([c])
        score = result["contracts"][0]["battle_test_score"]
        self.assertLess(score, 10)

    def test_formal_verification_adds_5(self):
        c_no = _make_contract(age_days=730, peak_tvl=100_000_000.0, formal=False)
        c_yes = _make_contract(age_days=730, peak_tvl=100_000_000.0, formal=True)
        r_no = analyze([c_no])["contracts"][0]["battle_test_score"]
        r_yes = analyze([c_yes])["contracts"][0]["battle_test_score"]
        self.assertEqual(r_yes, min(100, r_no + 5))

    def test_exploit_loss_ratio_computed(self):
        c = _make_contract(peak_tvl=1_000_000.0, exploit_loss=250_000.0)
        result = analyze([c])
        self.assertAlmostEqual(result["contracts"][0]["exploit_loss_ratio"], 0.25)

    def test_exploit_loss_ratio_zero_when_no_peak_tvl(self):
        c = _make_contract(peak_tvl=0.0, exploit_loss=100_000.0)
        result = analyze([c])
        self.assertAlmostEqual(result["contracts"][0]["exploit_loss_ratio"], 0.0)

    def test_is_heavily_audited_true(self):
        c = _make_contract(formal=True)
        result = analyze([c])
        self.assertTrue(result["contracts"][0]["is_heavily_audited"])

    def test_is_heavily_audited_false(self):
        c = _make_contract(formal=False)
        result = analyze([c])
        self.assertFalse(result["contracts"][0]["is_heavily_audited"])

    def test_complexity_risk_high(self):
        c = _make_contract(loc=15000)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["complexity_risk"], "HIGH")

    def test_complexity_risk_medium(self):
        c = _make_contract(loc=5000)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["complexity_risk"], "MEDIUM")

    def test_complexity_risk_low(self):
        c = _make_contract(loc=1000)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["complexity_risk"], "LOW")

    def test_summary_contains_protocol_name(self):
        c = _make_contract(protocol="Aave V3")
        result = analyze([c])
        self.assertIn("Aave V3", result["contracts"][0]["summary"])

    def test_summary_contains_age(self):
        c = _make_contract(age_days=730)
        result = analyze([c])
        self.assertIn("730", result["contracts"][0]["summary"])

    def test_summary_contains_exploit_count(self):
        c = _make_contract(exploit_count=2)
        result = analyze([c])
        self.assertIn("2 exploits", result["contracts"][0]["summary"])

    def test_summary_contains_upgrade_count(self):
        c = _make_contract(upgrade_count=3)
        result = analyze([c])
        self.assertIn("3 upgrades", result["contracts"][0]["summary"])


class TestAnalyzeMultipleContracts(unittest.TestCase):

    def test_safest_protocol_identified(self):
        c1 = _make_contract(protocol="Safe", age_days=2000, peak_tvl=2e9, upgrade_count=0)
        c2 = _make_contract(protocol="Risky", age_days=30, peak_tvl=50000.0, upgrade_count=15)
        result = analyze([c1, c2])
        self.assertEqual(result["safest_protocol"], "Safe")

    def test_riskiest_protocol_identified(self):
        c1 = _make_contract(protocol="Safe", age_days=2000, peak_tvl=2e9, upgrade_count=0)
        c2 = _make_contract(protocol="Risky", age_days=30, peak_tvl=50000.0, upgrade_count=15)
        result = analyze([c1, c2])
        self.assertEqual(result["riskiest_protocol"], "Risky")

    def test_battle_tested_count(self):
        c1 = _make_contract(protocol="A", age_days=2000, peak_tvl=2e9)  # high score → BATTLE_TESTED
        c2 = _make_contract(protocol="B", age_days=30, peak_tvl=50000.0)  # low score → UNPROVEN
        result = analyze([c1, c2])
        self.assertGreaterEqual(result["battle_tested_count"], 1)
        self.assertLessEqual(result["battle_tested_count"], 2)

    def test_average_score_computed(self):
        c1 = _make_contract(protocol="A", age_days=2000, peak_tvl=2e9, upgrade_count=0, exploit_count=0)
        c2 = _make_contract(protocol="B", age_days=30, peak_tvl=50000.0, upgrade_count=15, exploit_count=3)
        result = analyze([c1, c2])
        scores = [c["battle_test_score"] for c in result["contracts"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_score"], expected_avg)

    def test_single_contract_is_safest_and_riskiest(self):
        c = _make_contract(protocol="Solo")
        result = analyze([c])
        self.assertEqual(result["safest_protocol"], "Solo")
        self.assertEqual(result["riskiest_protocol"], "Solo")

    def test_three_contracts_average_score(self):
        contracts = [
            _make_contract(protocol="A"),
            _make_contract(protocol="B"),
            _make_contract(protocol="C"),
        ]
        result = analyze(contracts)
        scores = [c["battle_test_score"] for c in result["contracts"]]
        self.assertAlmostEqual(result["average_score"], sum(scores) / 3)


class TestOutputKeys(unittest.TestCase):

    def test_contract_output_keys(self):
        c = _make_contract()
        result = analyze([c])
        p = result["contracts"][0]
        expected = [
            "protocol", "battle_test_score", "safety_grade",
            "age_score", "tvl_stress_score", "incident_score", "stability_score",
            "exploit_loss_ratio", "is_heavily_audited", "complexity_risk",
            "battle_test_label", "summary",
        ]
        for k in expected:
            self.assertIn(k, p, f"Missing key: {k}")

    def test_top_level_keys(self):
        result = analyze([_make_contract()])
        for k in ["contracts", "safest_protocol", "riskiest_protocol", "battle_tested_count", "average_score", "timestamp"]:
            self.assertIn(k, result)

    def test_battle_test_score_is_int(self):
        result = analyze([_make_contract()])
        self.assertIsInstance(result["contracts"][0]["battle_test_score"], int)

    def test_safety_grade_valid_values(self):
        grades = {"A+", "A", "B", "C", "D", "F"}
        result = analyze([_make_contract()])
        self.assertIn(result["contracts"][0]["safety_grade"], grades)

    def test_battle_test_label_valid_values(self):
        labels = {"BATTLE_TESTED", "PROVEN", "MATURING", "YOUNG", "UNPROVEN"}
        result = analyze([_make_contract()])
        self.assertIn(result["contracts"][0]["battle_test_label"], labels)

    def test_complexity_risk_valid_values(self):
        risks = {"LOW", "MEDIUM", "HIGH"}
        result = analyze([_make_contract()])
        self.assertIn(result["contracts"][0]["complexity_risk"], risks)


class TestScoreCap(unittest.TestCase):

    def test_score_never_exceeds_100(self):
        c = _make_contract(age_days=5000, peak_tvl=50e9, exploit_count=0, upgrade_count=0, formal=True)
        result = analyze([c])
        self.assertLessEqual(result["contracts"][0]["battle_test_score"], 100)

    def test_score_never_below_zero(self):
        c = _make_contract(age_days=0, peak_tvl=0.0, exploit_count=10, upgrade_count=100, last_upgrade=0, formal=False)
        result = analyze([c])
        self.assertGreaterEqual(result["contracts"][0]["battle_test_score"], 0)

    def test_formal_verification_bonus_respects_cap(self):
        # Score = 100 already → bonus shouldn't push above 100
        c = _make_contract(age_days=5000, peak_tvl=50e9, exploit_count=0, upgrade_count=0, formal=True)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["battle_test_score"], 100)


class TestLogResult(unittest.TestCase):

    def test_creates_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            result = analyze([_make_contract()])
            log_result(result, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            log_result(analyze([_make_contract()]), log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            for _ in range(105):
                log_result(analyze([_make_contract()]), log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 100)

    def test_appends_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            log_result(analyze([_make_contract(protocol="A")]), log_path=path)
            log_result(analyze([_make_contract(protocol="B")]), log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_atomic_write_on_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            with open(path, "w") as f:
                f.write("{bad json}")
            log_result(analyze([_make_contract()]), log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)


class TestSubScoreIntegration(unittest.TestCase):

    def test_age_score_in_output(self):
        c = _make_contract(age_days=730)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["age_score"], 20)

    def test_tvl_score_in_output(self):
        c = _make_contract(peak_tvl=100_000_000.0)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["tvl_stress_score"], 20)

    def test_incident_score_in_output_no_exploits(self):
        c = _make_contract(exploit_count=0)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["incident_score"], 25)

    def test_stability_score_in_output_no_upgrades(self):
        c = _make_contract(upgrade_count=0)
        result = analyze([c])
        self.assertEqual(result["contracts"][0]["stability_score"], 25)

    def test_total_score_equals_sum_of_subscores(self):
        c = _make_contract(age_days=730, peak_tvl=100_000_000.0, exploit_count=0, upgrade_count=0, formal=False)
        result = analyze([c])
        p = result["contracts"][0]
        expected = min(100, p["age_score"] + p["tvl_stress_score"] + p["incident_score"] + p["stability_score"])
        self.assertEqual(p["battle_test_score"], expected)

    def test_battle_tested_count_zero_when_all_young(self):
        contracts = [
            _make_contract(protocol="A", age_days=10, peak_tvl=1000.0, exploit_count=5, upgrade_count=20, last_upgrade=5),
            _make_contract(protocol="B", age_days=5, peak_tvl=500.0, exploit_count=3, upgrade_count=15, last_upgrade=2),
        ]
        result = analyze(contracts)
        for c in result["contracts"]:
            self.assertNotIn(c["battle_test_label"], ("BATTLE_TESTED", "PROVEN"))


if __name__ == "__main__":
    unittest.main()

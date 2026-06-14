"""
Tests for MP-670: YieldFarmingRiskAssessor
Run: python3 -m unittest spa_core.tests.test_yield_farming_risk_assessor -v
≥ 65 tests covering all helpers and integration paths.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_farming_risk_assessor import (
    YieldFarmProfile,
    YieldFarmRiskReport,
    YieldFarmingRiskAssessor,
    _il_risk,
    _sc_risk,
    _inflation_risk,
    _composite_risk,
    _risk_grade,
    _real_apy_estimate,
    _recommendation,
    _build_warnings,
    MAX_ENTRIES,
)


def _make_profile(**kwargs) -> YieldFarmProfile:
    """Build a safe-default profile, overridable by kwargs."""
    defaults = dict(
        farm_id="test-farm",
        protocol="TestProtocol",
        pool_type="STABLE_STABLE",
        tvl_usd=100_000_000,
        apy_base_pct=4.0,
        apy_reward_pct=2.0,
        reward_token_inflation_pct=20.0,
        audit_count=3,
        protocol_age_days=400,
        has_time_lock=True,
        rug_pull_risk_score=0.05,
    )
    defaults.update(kwargs)
    return YieldFarmProfile(**defaults)


class TestILRisk(unittest.TestCase):
    """_il_risk baseline per pool type."""

    def test_stable_stable_baseline(self):
        self.assertAlmostEqual(_il_risk("STABLE_STABLE"), 0.02)

    def test_stable_volatile_baseline(self):
        self.assertAlmostEqual(_il_risk("STABLE_VOLATILE"), 0.30)

    def test_volatile_volatile_baseline(self):
        self.assertAlmostEqual(_il_risk("VOLATILE_VOLATILE"), 0.65)

    def test_unknown_pool_type_fallback(self):
        # Unknown type falls back to 0.65 (volatile default)
        self.assertAlmostEqual(_il_risk("EXOTIC_POOL"), 0.65)

    def test_stable_stable_is_lowest(self):
        self.assertLess(_il_risk("STABLE_STABLE"), _il_risk("STABLE_VOLATILE"))

    def test_stable_volatile_less_than_volatile(self):
        self.assertLess(_il_risk("STABLE_VOLATILE"), _il_risk("VOLATILE_VOLATILE"))

    def test_volatile_volatile_is_highest(self):
        self.assertEqual(_il_risk("VOLATILE_VOLATILE"), 0.65)

    def test_stable_stable_near_zero(self):
        self.assertLess(_il_risk("STABLE_STABLE"), 0.05)


class TestSCRisk(unittest.TestCase):
    """_sc_risk clamped [0.05, 0.90] with audit / timelock / age reductions."""

    def test_no_audits_no_timelock_new_protocol(self):
        # base=0.5, no reductions → 0.5
        risk = _sc_risk(0, False, 100)
        self.assertAlmostEqual(risk, 0.5)

    def test_one_audit_reduces_by_01(self):
        risk = _sc_risk(1, False, 100)
        self.assertAlmostEqual(risk, 0.4)

    def test_two_audits_reduces_by_02(self):
        risk = _sc_risk(2, False, 100)
        self.assertAlmostEqual(risk, 0.3)

    def test_three_audits_capped_at_03(self):
        # min(0.3, 0.1*3) = 0.3
        risk_3 = _sc_risk(3, False, 100)
        risk_5 = _sc_risk(5, False, 100)
        self.assertAlmostEqual(risk_3, 0.2)
        self.assertAlmostEqual(risk_5, 0.2)  # capped same

    def test_audit_cap_at_3_is_enforced(self):
        # 10 audits should give same reduction as 3
        self.assertAlmostEqual(_sc_risk(10, False, 100), _sc_risk(3, False, 100))

    def test_timelock_reduces_by_01(self):
        without = _sc_risk(0, False, 100)
        with_ = _sc_risk(0, True, 100)
        self.assertAlmostEqual(with_, without - 0.1)

    def test_old_protocol_reduces_by_01(self):
        young = _sc_risk(0, False, 100)
        old = _sc_risk(0, False, 500)
        self.assertAlmostEqual(old, young - 0.1)

    def test_all_factors_combined_near_min(self):
        # 3 audits (-0.3) + timelock (-0.1) + old (-0.1) = 0.5-0.5=0.0 → clamped 0.05
        risk = _sc_risk(3, True, 500)
        self.assertAlmostEqual(risk, 0.05)

    def test_clamp_lower_bound(self):
        # Even with many reductions, floor is 0.05
        risk = _sc_risk(100, True, 10000)
        self.assertGreaterEqual(risk, 0.05)

    def test_clamp_upper_bound(self):
        # Base is 0.5 so never hits 0.90, but verify clamp logic
        risk = _sc_risk(0, False, 1)
        self.assertLessEqual(risk, 0.90)

    def test_upper_clamp_explicit(self):
        # Patch: if somehow base > 0.90, clamp holds. (We pass negative audit_count indirectly via formula)
        # Verify clamp rule by checking result is always <= 0.90
        for ac in range(0, 6):
            for tl in (True, False):
                for age in (10, 200, 500):
                    self.assertLessEqual(_sc_risk(ac, tl, age), 0.90)

    def test_result_is_float(self):
        self.assertIsInstance(_sc_risk(2, True, 400), float)


class TestInflationRisk(unittest.TestCase):
    """_inflation_risk: 0 when no rewards, escalates with inflation + reward share."""

    def test_zero_reward_apy_returns_zero(self):
        self.assertEqual(_inflation_risk(0.0, 4.0, 50.0), 0.0)

    def test_zero_reward_apy_regardless_of_inflation(self):
        self.assertEqual(_inflation_risk(0.0, 0.0, 200.0), 0.0)

    def test_low_inflation_low_risk(self):
        # 5% inflation, small reward share
        risk = _inflation_risk(1.0, 10.0, 5.0)
        self.assertLess(risk, 0.30)

    def test_high_inflation_high_reward_share_near_one(self):
        # 200% inflation, almost all APY from rewards
        risk = _inflation_risk(50.0, 0.1, 200.0)
        self.assertGreater(risk, 0.70)

    def test_100pct_inflation_and_all_reward(self):
        risk = _inflation_risk(100.0, 0.001, 100.0)
        self.assertLessEqual(risk, 1.0)

    def test_capped_at_1(self):
        risk = _inflation_risk(500.0, 0.001, 500.0)
        self.assertLessEqual(risk, 1.0)

    def test_moderate_inflation_moderate_risk(self):
        risk = _inflation_risk(10.0, 5.0, 40.0)
        self.assertGreater(risk, 0.0)
        self.assertLess(risk, 1.0)

    def test_reward_share_term_works(self):
        # Higher reward share → higher inflation risk, all else equal
        low_share = _inflation_risk(1.0, 100.0, 50.0)
        high_share = _inflation_risk(99.0, 1.0, 50.0)
        self.assertGreater(high_share, low_share)

    def test_result_in_0_1(self):
        for reward_pct in [0.0, 1.0, 10.0, 100.0]:
            risk = _inflation_risk(reward_pct, 5.0, 50.0)
            self.assertGreaterEqual(risk, 0.0)
            self.assertLessEqual(risk, 1.0)


class TestCompositeRisk(unittest.TestCase):
    """_composite_risk weighted formula."""

    def test_weights_sum_to_one(self):
        # il=1, sc=1, inf=1, rug=1 → 0.30+0.30+0.25+0.15=1.0
        self.assertAlmostEqual(_composite_risk(1.0, 1.0, 1.0, 1.0), 1.0)

    def test_all_zero_returns_zero(self):
        self.assertAlmostEqual(_composite_risk(0.0, 0.0, 0.0, 0.0), 0.0)

    def test_il_weight_03(self):
        # Only IL=1, others=0
        self.assertAlmostEqual(_composite_risk(1.0, 0.0, 0.0, 0.0), 0.30)

    def test_sc_weight_03(self):
        self.assertAlmostEqual(_composite_risk(0.0, 1.0, 0.0, 0.0), 0.30)

    def test_inflation_weight_025(self):
        self.assertAlmostEqual(_composite_risk(0.0, 0.0, 1.0, 0.0), 0.25)

    def test_rug_weight_015(self):
        self.assertAlmostEqual(_composite_risk(0.0, 0.0, 0.0, 1.0), 0.15)

    def test_known_combination(self):
        # il=0.02, sc=0.1, inf=0.1, rug=0.05
        expected = 0.02*0.30 + 0.1*0.30 + 0.1*0.25 + 0.05*0.15
        self.assertAlmostEqual(_composite_risk(0.02, 0.1, 0.1, 0.05), expected, places=10)


class TestRiskGrade(unittest.TestCase):
    """_risk_grade thresholds A/B/C/D/F."""

    def test_grade_a_below_020(self):
        self.assertEqual(_risk_grade(0.0), "A")
        self.assertEqual(_risk_grade(0.19), "A")

    def test_grade_b_below_035(self):
        self.assertEqual(_risk_grade(0.20), "B")
        self.assertEqual(_risk_grade(0.34), "B")

    def test_grade_c_below_050(self):
        self.assertEqual(_risk_grade(0.35), "C")
        self.assertEqual(_risk_grade(0.49), "C")

    def test_grade_d_below_065(self):
        self.assertEqual(_risk_grade(0.50), "D")
        self.assertEqual(_risk_grade(0.64), "D")

    def test_grade_f_at_065_and_above(self):
        self.assertEqual(_risk_grade(0.65), "F")
        self.assertEqual(_risk_grade(1.0), "F")

    def test_boundary_020_is_b(self):
        self.assertEqual(_risk_grade(0.20), "B")

    def test_boundary_035_is_c(self):
        self.assertEqual(_risk_grade(0.35), "C")

    def test_boundary_050_is_d(self):
        self.assertEqual(_risk_grade(0.50), "D")

    def test_boundary_065_is_f(self):
        self.assertEqual(_risk_grade(0.65), "F")


class TestRealAPYEstimate(unittest.TestCase):
    """_real_apy_estimate adjusts base APY and reward APY."""

    def test_no_reward_stable_pool(self):
        # base=4%, reward=0%, il=0.02, inflation=0
        result = _real_apy_estimate(4.0, 0.0, 0.02, 0.0)
        expected = 4.0 * (1 - 0.02 * 0.5)
        self.assertAlmostEqual(result, expected)

    def test_with_reward_no_inflation(self):
        result = _real_apy_estimate(4.0, 2.0, 0.02, 0.0)
        expected = 4.0 * (1 - 0.02 * 0.5) + 2.0 * (1 - 0.0 * 0.6)
        self.assertAlmostEqual(result, expected)

    def test_high_il_reduces_base(self):
        low_il = _real_apy_estimate(10.0, 0.0, 0.1, 0.0)
        high_il = _real_apy_estimate(10.0, 0.0, 0.6, 0.0)
        self.assertGreater(low_il, high_il)

    def test_high_inflation_reduces_reward(self):
        low_inf = _real_apy_estimate(5.0, 20.0, 0.02, 0.1)
        high_inf = _real_apy_estimate(5.0, 20.0, 0.02, 0.9)
        self.assertGreater(low_inf, high_inf)

    def test_zero_base_zero_reward(self):
        result = _real_apy_estimate(0.0, 0.0, 0.5, 0.5)
        self.assertAlmostEqual(result, 0.0)


class TestRecommendation(unittest.TestCase):
    """_recommendation maps grade → action."""

    def test_grade_a_is_farm(self):
        self.assertEqual(_recommendation("A"), "FARM")

    def test_grade_b_is_farm(self):
        self.assertEqual(_recommendation("B"), "FARM")

    def test_grade_c_is_monitor(self):
        self.assertEqual(_recommendation("C"), "MONITOR")

    def test_grade_d_is_reduce(self):
        self.assertEqual(_recommendation("D"), "REDUCE")

    def test_grade_f_is_exit(self):
        self.assertEqual(_recommendation("F"), "EXIT")


class TestWarnings(unittest.TestCase):
    """_build_warnings flags triggered by thresholds."""

    def test_inflation_warning_above_05(self):
        warns = _build_warnings(0.6, 0.02, 0.05, 0.3)
        self.assertTrue(any("inflation" in w.lower() for w in warns))

    def test_no_inflation_warning_below_05(self):
        warns = _build_warnings(0.4, 0.02, 0.05, 0.3)
        self.assertFalse(any("inflation" in w.lower() for w in warns))

    def test_il_warning_above_05(self):
        warns = _build_warnings(0.1, 0.6, 0.05, 0.3)
        self.assertTrue(any("IL" in w or "il" in w.lower() for w in warns))

    def test_no_il_warning_below_05(self):
        warns = _build_warnings(0.1, 0.3, 0.05, 0.3)
        self.assertFalse(any("IL" in w or "il" in w.lower() for w in warns))

    def test_rug_warning_above_03(self):
        warns = _build_warnings(0.1, 0.02, 0.4, 0.3)
        self.assertTrue(any("rug" in w.lower() or "🚨" in w for w in warns))

    def test_no_rug_warning_at_03(self):
        warns = _build_warnings(0.1, 0.02, 0.3, 0.3)
        self.assertFalse(any("rug" in w.lower() or "🚨" in w for w in warns))

    def test_sc_warning_above_06(self):
        warns = _build_warnings(0.1, 0.02, 0.1, 0.7)
        self.assertTrue(any("audit" in w.lower() for w in warns))

    def test_no_sc_warning_below_06(self):
        warns = _build_warnings(0.1, 0.02, 0.1, 0.5)
        self.assertFalse(any("audit" in w.lower() for w in warns))

    def test_no_warnings_when_safe(self):
        warns = _build_warnings(0.0, 0.02, 0.0, 0.3)
        self.assertEqual(warns, [])

    def test_all_warnings_triggered(self):
        warns = _build_warnings(0.9, 0.9, 0.9, 0.9)
        self.assertEqual(len(warns), 4)


class TestAssessIntegration(unittest.TestCase):
    """Integration tests for YieldFarmingRiskAssessor.assess()."""

    def setUp(self):
        self.assessor = YieldFarmingRiskAssessor()

    def test_stable_well_audited_gets_grade_a_or_b(self):
        profile = _make_profile(
            pool_type="STABLE_STABLE",
            apy_reward_pct=0.0,
            reward_token_inflation_pct=0.0,
            audit_count=5,
            protocol_age_days=900,
            has_time_lock=True,
            rug_pull_risk_score=0.01,
        )
        report = self.assessor.assess(profile)
        self.assertIn(report.risk_grade, ("A", "B"))

    def test_stable_well_audited_recommendation_farm(self):
        profile = _make_profile(
            pool_type="STABLE_STABLE",
            apy_reward_pct=0.0,
            reward_token_inflation_pct=0.0,
            audit_count=5,
            protocol_age_days=900,
            has_time_lock=True,
            rug_pull_risk_score=0.01,
        )
        report = self.assessor.assess(profile)
        self.assertEqual(report.recommendation, "FARM")

    def test_volatile_no_audit_high_inflation_grade_d_or_f(self):
        profile = _make_profile(
            pool_type="VOLATILE_VOLATILE",
            apy_base_pct=0.5,
            apy_reward_pct=200.0,
            reward_token_inflation_pct=200.0,
            audit_count=0,
            protocol_age_days=20,
            has_time_lock=False,
            rug_pull_risk_score=0.7,
        )
        report = self.assessor.assess(profile)
        self.assertIn(report.risk_grade, ("D", "F"))

    def test_volatile_no_audit_high_inflation_recommendation_reduce_or_exit(self):
        profile = _make_profile(
            pool_type="VOLATILE_VOLATILE",
            apy_base_pct=0.5,
            apy_reward_pct=200.0,
            reward_token_inflation_pct=200.0,
            audit_count=0,
            protocol_age_days=20,
            has_time_lock=False,
            rug_pull_risk_score=0.7,
        )
        report = self.assessor.assess(profile)
        self.assertIn(report.recommendation, ("REDUCE", "EXIT"))

    def test_report_fields_populated(self):
        report = self.assessor.assess(_make_profile())
        self.assertIsInstance(report.farm_id, str)
        self.assertIsInstance(report.il_risk, float)
        self.assertIsInstance(report.smart_contract_risk, float)
        self.assertIsInstance(report.inflation_risk, float)
        self.assertIsInstance(report.rug_risk, float)
        self.assertIsInstance(report.composite_risk, float)
        self.assertIsInstance(report.risk_grade, str)
        self.assertIsInstance(report.real_apy_estimate_pct, float)
        self.assertIsInstance(report.recommendation, str)
        self.assertIsInstance(report.warnings, list)

    def test_risk_grade_valid_values(self):
        report = self.assessor.assess(_make_profile())
        self.assertIn(report.risk_grade, ("A", "B", "C", "D", "F"))

    def test_recommendation_valid_values(self):
        report = self.assessor.assess(_make_profile())
        self.assertIn(report.recommendation, ("FARM", "MONITOR", "REDUCE", "EXIT"))

    def test_rug_risk_clamped(self):
        profile = _make_profile(rug_pull_risk_score=2.5)
        report = self.assessor.assess(profile)
        self.assertLessEqual(report.rug_risk, 1.0)

    def test_rug_risk_clamped_negative(self):
        profile = _make_profile(rug_pull_risk_score=-0.5)
        report = self.assessor.assess(profile)
        self.assertGreaterEqual(report.rug_risk, 0.0)

    def test_composite_in_range(self):
        report = self.assessor.assess(_make_profile())
        self.assertGreaterEqual(report.composite_risk, 0.0)
        self.assertLessEqual(report.composite_risk, 1.0)

    def test_farm_id_preserved(self):
        profile = _make_profile(farm_id="my-unique-farm-123")
        report = self.assessor.assess(profile)
        self.assertEqual(report.farm_id, "my-unique-farm-123")

    def test_pool_type_preserved(self):
        profile = _make_profile(pool_type="STABLE_VOLATILE")
        report = self.assessor.assess(profile)
        self.assertEqual(report.pool_type, "STABLE_VOLATILE")

    def test_stable_volatile_il_risk(self):
        profile = _make_profile(pool_type="STABLE_VOLATILE")
        report = self.assessor.assess(profile)
        self.assertAlmostEqual(report.il_risk, 0.30)


class TestAssessBatch(unittest.TestCase):
    """assess_batch()."""

    def setUp(self):
        self.assessor = YieldFarmingRiskAssessor()

    def test_empty_batch_returns_empty(self):
        self.assertEqual(self.assessor.assess_batch([]), [])

    def test_batch_length_matches_input(self):
        profiles = [_make_profile(farm_id=f"farm-{i}") for i in range(5)]
        reports = self.assessor.assess_batch(profiles)
        self.assertEqual(len(reports), 5)

    def test_batch_preserves_order(self):
        profiles = [_make_profile(farm_id=f"farm-{i}") for i in range(3)]
        reports = self.assessor.assess_batch(profiles)
        for i, r in enumerate(reports):
            self.assertEqual(r.farm_id, f"farm-{i}")


class TestPersistence(unittest.TestCase):
    """save_results / load_history atomic writes + ring-buffer."""

    def setUp(self):
        self.assessor = YieldFarmingRiskAssessor()
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "test_yield_risk.json"

    def _make_report(self, farm_id="test-farm") -> YieldFarmRiskReport:
        profile = _make_profile(farm_id=farm_id)
        return self.assessor.assess(profile)

    def test_save_creates_file(self):
        reports = [self._make_report()]
        self.assessor.save_results(reports, self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_writes_valid_json(self):
        reports = [self._make_report()]
        self.assessor.save_results(reports, self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_entry_has_expected_keys(self):
        reports = [self._make_report()]
        self.assessor.save_results(reports, self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("ts", "farm_id", "risk_grade", "recommendation", "composite_risk"):
            self.assertIn(key, entry)

    def test_save_appends_on_second_call(self):
        self.assessor.save_results([self._make_report("farm-1")], self.data_file)
        self.assessor.save_results([self._make_report("farm-2")], self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max_entries(self):
        # Write MAX_ENTRIES+10 entries one by one and verify cap
        for i in range(MAX_ENTRIES + 10):
            self.assessor.save_results([self._make_report(f"farm-{i}")], self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        # Write MAX_ENTRIES+5 entries; last 5 should be the "latest"
        n = MAX_ENTRIES + 5
        for i in range(n):
            self.assessor.save_results([self._make_report(f"farm-{i}")], self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        # The last entry's farm_id should be the last one written
        self.assertEqual(data[-1]["farm_id"], f"farm-{n - 1}")

    def test_atomic_write_no_tmp_left(self):
        reports = [self._make_report()]
        self.assessor.save_results(reports, self.data_file)
        tmp = str(self.data_file) + ".tmp"
        self.assertFalse(os.path.exists(tmp))

    def test_load_history_missing_file_returns_empty(self):
        missing = Path(self.tmp_dir) / "does_not_exist.json"
        result = self.assessor.load_history(missing)
        self.assertEqual(result, [])

    def test_load_history_after_save(self):
        reports = [self._make_report("load-test")]
        self.assessor.save_results(reports, self.data_file)
        history = self.assessor.load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["farm_id"], "load-test")

    def test_load_history_corrupt_file_returns_empty(self):
        with open(self.data_file, "w") as f:
            f.write("not valid json {{{{")
        result = self.assessor.load_history(self.data_file)
        self.assertEqual(result, [])

    def test_save_batch_multiple_reports(self):
        reports = [self._make_report(f"f{i}") for i in range(5)]
        self.assessor.save_results(reports, self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

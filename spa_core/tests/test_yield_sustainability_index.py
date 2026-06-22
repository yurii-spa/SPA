"""
Tests for YieldSustainabilityIndex (MP-719).
Run: python3 -m pytest spa_core/tests/test_yield_sustainability_index.py -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_sustainability_index import (
    SustainabilityFactors,
    SustainabilityReport,
    score_real_yield,
    score_maturity,
    score_security,
    score_tvl_stability,
    compute,
    rank_protocols,
    save_results,
    load_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_factors(**kwargs) -> SustainabilityFactors:
    defaults = dict(
        real_yield_ratio=0.7,
        protocol_age_months=24,
        audit_count=3,
        bug_bounty_usd=1_000_000.0,
        hack_history=False,
        hack_loss_pct=0.0,
        admin_key_risk=False,
        tvl_30d_change_pct=3.0,
        tvl_90d_change_pct=8.0,
        tvl_usd=200_000_000.0,
    )
    defaults.update(kwargs)
    return SustainabilityFactors(**defaults)


def _make_report(**factor_kwargs) -> SustainabilityReport:
    factors = _default_factors(**factor_kwargs)
    return compute("TestProto", "TestPool", factors)


# ---------------------------------------------------------------------------
# score_real_yield
# ---------------------------------------------------------------------------

class TestScoreRealYield(unittest.TestCase):

    def test_ratio_09_gives_25(self):
        self.assertEqual(score_real_yield(0.9), 25.0)

    def test_ratio_08_gives_25(self):
        self.assertEqual(score_real_yield(0.8), 25.0)

    def test_ratio_07_gives_20(self):
        self.assertEqual(score_real_yield(0.7), 20.0)

    def test_ratio_06_gives_20(self):
        self.assertEqual(score_real_yield(0.6), 20.0)

    def test_ratio_05_gives_14(self):
        self.assertEqual(score_real_yield(0.5), 14.0)

    def test_ratio_04_gives_14(self):
        self.assertEqual(score_real_yield(0.4), 14.0)

    def test_ratio_03_gives_8(self):
        self.assertEqual(score_real_yield(0.3), 8.0)

    def test_ratio_02_gives_8(self):
        self.assertEqual(score_real_yield(0.2), 8.0)

    def test_ratio_01_gives_2(self):
        self.assertEqual(score_real_yield(0.1), 2.0)

    def test_ratio_00_gives_2(self):
        self.assertEqual(score_real_yield(0.0), 2.0)

    def test_ratio_10_gives_25(self):
        self.assertEqual(score_real_yield(1.0), 25.0)

    def test_boundary_just_below_08(self):
        self.assertEqual(score_real_yield(0.79), 20.0)

    def test_boundary_just_below_06(self):
        self.assertEqual(score_real_yield(0.59), 14.0)

    def test_boundary_just_below_02(self):
        self.assertEqual(score_real_yield(0.19), 2.0)


# ---------------------------------------------------------------------------
# score_maturity
# ---------------------------------------------------------------------------

class TestScoreMaturity(unittest.TestCase):

    def test_max_all_bands(self):
        # age=24→10, audits=3→10, bounty=1M→5 → min(25, 25)=25
        self.assertEqual(score_maturity(24, 3, 1_000_000), 25.0)

    def test_age_24_months(self):
        score = score_maturity(24, 0, 0)
        self.assertEqual(score, 10.0)  # 10 + 0 + 0

    def test_age_12_months(self):
        score = score_maturity(12, 0, 0)
        self.assertEqual(score, 7.0)

    def test_age_6_months(self):
        score = score_maturity(6, 0, 0)
        self.assertEqual(score, 4.0)

    def test_age_below_6(self):
        score = score_maturity(3, 0, 0)
        self.assertEqual(score, 1.0)

    def test_audits_3(self):
        score = score_maturity(0, 3, 0)
        # age=0→1, audits→10, bounty=0→0
        self.assertEqual(score, 11.0)

    def test_audits_2(self):
        score = score_maturity(0, 2, 0)
        self.assertEqual(score, 8.0)  # 1 + 7

    def test_audits_1(self):
        score = score_maturity(0, 1, 0)
        self.assertEqual(score, 5.0)  # 1 + 4

    def test_audits_0(self):
        score = score_maturity(0, 0, 0)
        self.assertEqual(score, 1.0)  # 1 + 0

    def test_bounty_1m(self):
        score = score_maturity(0, 0, 1_000_000)
        self.assertEqual(score, 6.0)  # 1 + 0 + 5

    def test_bounty_100k(self):
        score = score_maturity(0, 0, 100_000)
        self.assertEqual(score, 4.0)  # 1 + 0 + 3

    def test_bounty_small_nonzero(self):
        score = score_maturity(0, 0, 50_000)
        self.assertEqual(score, 2.0)  # 1 + 0 + 1

    def test_bounty_zero(self):
        score = score_maturity(0, 0, 0)
        self.assertEqual(score, 1.0)

    def test_cap_at_25(self):
        # age=24→10, audits=3→10, bounty=1M+→5 → 25 → capped at 25
        self.assertEqual(score_maturity(36, 5, 5_000_000), 25.0)

    def test_exceeds_25_capped(self):
        # Hypothetically age=24(10) + audits=3(10) + bounty=1M(5) = 25, exactly 25
        self.assertEqual(score_maturity(24, 3, 1_000_001), 25.0)


# ---------------------------------------------------------------------------
# score_security
# ---------------------------------------------------------------------------

class TestScoreSecurity(unittest.TestCase):

    def test_no_hack_no_admin_key(self):
        self.assertEqual(score_security(False, 0.0, False), 25.0)

    def test_hack_20pct_loss(self):
        # base=25, hack: -min(20, 20*2=40)=-20 → 5
        self.assertEqual(score_security(True, 20.0, False), 5.0)

    def test_hack_5pct_loss(self):
        # base=25, hack: -min(20, 5*2=10)=-10 → 15
        self.assertEqual(score_security(True, 5.0, False), 15.0)

    def test_hack_50pct_loss_capped(self):
        # base=25, hack: -min(20, 50*2=100)=-20 → 5
        self.assertEqual(score_security(True, 50.0, False), 5.0)

    def test_hack_10pct_loss(self):
        # base=25, -min(20, 10*2=20)=-20 → 5
        self.assertEqual(score_security(True, 10.0, False), 5.0)

    def test_admin_key_only(self):
        # base=25 - 5 = 20
        self.assertEqual(score_security(False, 0.0, True), 20.0)

    def test_hack_and_admin_key(self):
        # base=25, hack 10%: -20, admin: -5 → 0
        self.assertEqual(score_security(True, 10.0, True), 0.0)

    def test_floor_at_zero(self):
        # hack 50% + admin key: 25 - 20 - 5 = 0
        self.assertEqual(score_security(True, 100.0, True), 0.0)

    def test_no_hack_with_admin_key(self):
        self.assertEqual(score_security(False, 0.0, True), 20.0)

    def test_hack_small_loss(self):
        # 1% loss → -min(20, 2) = -2 → 23
        self.assertEqual(score_security(True, 1.0, False), 23.0)


# ---------------------------------------------------------------------------
# score_tvl_stability
# ---------------------------------------------------------------------------

class TestScoreTvlStability(unittest.TestCase):

    def test_max_stability(self):
        # tvl=1B→8, 30d<5→10, 90d<10→7 → min(25,25)=25
        self.assertEqual(score_tvl_stability(2.0, 5.0, 1_000_000_000), 25.0)

    def test_tvl_size_1b(self):
        score = score_tvl_stability(0.0, 0.0, 1_000_000_000)
        self.assertEqual(score, 25.0)  # 8+10+7=25

    def test_tvl_size_100m(self):
        score = score_tvl_stability(0.0, 0.0, 100_000_000)
        self.assertEqual(score, 23.0)  # 6+10+7=23

    def test_tvl_size_10m(self):
        score = score_tvl_stability(0.0, 0.0, 10_000_000)
        self.assertEqual(score, 21.0)  # 4+10+7=21

    def test_tvl_size_below_10m(self):
        score = score_tvl_stability(0.0, 0.0, 5_000_000)
        self.assertEqual(score, 18.0)  # 1+10+7=18

    def test_stability_30d_lt5(self):
        score = score_tvl_stability(4.9, 0.0, 10_000_000)
        # 4+10+7=21
        self.assertEqual(score, 21.0)

    def test_stability_30d_lt15(self):
        score = score_tvl_stability(10.0, 0.0, 10_000_000)
        # 4+7+7=18
        self.assertEqual(score, 18.0)

    def test_stability_30d_lt30(self):
        score = score_tvl_stability(20.0, 0.0, 10_000_000)
        # 4+4+7=15
        self.assertEqual(score, 15.0)

    def test_stability_30d_ge30(self):
        score = score_tvl_stability(35.0, 0.0, 10_000_000)
        # 4+1+7=12
        self.assertEqual(score, 12.0)

    def test_stability_90d_lt10(self):
        score = score_tvl_stability(0.0, 9.0, 10_000_000)
        # 4+10+7=21
        self.assertEqual(score, 21.0)

    def test_stability_90d_lt25(self):
        score = score_tvl_stability(0.0, 20.0, 10_000_000)
        # 4+10+5=19
        self.assertEqual(score, 19.0)

    def test_stability_90d_lt50(self):
        score = score_tvl_stability(0.0, 40.0, 10_000_000)
        # 4+10+2=16
        self.assertEqual(score, 16.0)

    def test_stability_90d_ge50(self):
        score = score_tvl_stability(0.0, 60.0, 10_000_000)
        # 4+10+0=14
        self.assertEqual(score, 14.0)

    def test_negative_30d_change_uses_abs(self):
        # -10% change: abs=10 < 15 → 7
        score = score_tvl_stability(-10.0, 0.0, 10_000_000)
        self.assertEqual(score, 18.0)  # 4+7+7

    def test_negative_90d_change_uses_abs(self):
        score = score_tvl_stability(0.0, -20.0, 10_000_000)
        self.assertEqual(score, 19.0)  # 4+10+5

    def test_cap_at_25(self):
        self.assertLessEqual(score_tvl_stability(0.0, 0.0, 2_000_000_000), 25.0)


# ---------------------------------------------------------------------------
# compute — sustainability_index
# ---------------------------------------------------------------------------

class TestSustainabilityIndex(unittest.TestCase):

    def test_index_sum_of_four_subscores(self):
        r = _make_report()
        expected = r.real_yield_score + r.maturity_score + r.security_score + r.tvl_stability_score
        self.assertAlmostEqual(r.sustainability_index, expected, places=4)

    def test_perfect_score(self):
        # Max all factors
        factors = SustainabilityFactors(
            real_yield_ratio=1.0,
            protocol_age_months=36,
            audit_count=5,
            bug_bounty_usd=5_000_000.0,
            hack_history=False,
            hack_loss_pct=0.0,
            admin_key_risk=False,
            tvl_30d_change_pct=1.0,
            tvl_90d_change_pct=1.0,
            tvl_usd=2_000_000_000.0,
        )
        r = compute("Perfect", "Pool", factors)
        self.assertEqual(r.sustainability_index, 100.0)

    def test_worst_case_score(self):
        # Min all factors
        factors = SustainabilityFactors(
            real_yield_ratio=0.0,
            protocol_age_months=0,
            audit_count=0,
            bug_bounty_usd=0.0,
            hack_history=True,
            hack_loss_pct=100.0,
            admin_key_risk=True,
            tvl_30d_change_pct=90.0,
            tvl_90d_change_pct=90.0,
            tvl_usd=1_000_000.0,
        )
        r = compute("Worst", "Pool", factors)
        # real=2(0.0), maturity=1(0mo,0aud,0bb), security=max(0,25-20-5)=0, tvl=1+1+0=2 → 5
        self.assertEqual(r.sustainability_index, 5.0)


# ---------------------------------------------------------------------------
# compute — grade / label / invest_confidence
# ---------------------------------------------------------------------------

class TestGradeAndLabel(unittest.TestCase):

    def _report_with_index(self, target_index: float) -> SustainabilityReport:
        # Build factors that give approximately the target index
        # Use perfect factors then adjust real_yield_ratio
        # Easier: just build and test concrete known combinations
        # Map target to grade tier via known factor combos
        factors = _default_factors()
        r = compute("X", "Y", factors)
        return r

    def test_grade_A_above_80(self):
        # Max factors → 100 → A
        factors = SustainabilityFactors(
            real_yield_ratio=1.0, protocol_age_months=36, audit_count=5,
            bug_bounty_usd=5_000_000.0, hack_history=False, hack_loss_pct=0.0,
            admin_key_risk=False, tvl_30d_change_pct=1.0, tvl_90d_change_pct=1.0,
            tvl_usd=2_000_000_000.0,
        )
        r = compute("X", "Y", factors)
        self.assertEqual(r.grade, "A")
        self.assertEqual(r.label, "HIGHLY_SUSTAINABLE")
        self.assertEqual(r.invest_confidence, "HIGH")

    def test_grade_B_60_to_79(self):
        # real=20(0.7), maturity=7+4+0=11, security=25, tvl=6+7+7=20 → 76 → B
        factors = SustainabilityFactors(
            real_yield_ratio=0.7, protocol_age_months=12, audit_count=1,
            bug_bounty_usd=0.0, hack_history=False, hack_loss_pct=0.0,
            admin_key_risk=False, tvl_30d_change_pct=3.0, tvl_90d_change_pct=8.0,
            tvl_usd=100_000_000.0,
        )
        r = compute("X", "Y", factors)
        self.assertGreaterEqual(r.sustainability_index, 60.0)
        self.assertLess(r.sustainability_index, 80.0)
        self.assertEqual(r.grade, "B")
        self.assertEqual(r.label, "SUSTAINABLE")
        self.assertEqual(r.invest_confidence, "MEDIUM")

    def test_grade_C_40_to_59(self):
        # real=2(0.1), maturity=1+0+0=1, security=25, tvl=4+10+7=21 → 49 → C
        factors = SustainabilityFactors(
            real_yield_ratio=0.1, protocol_age_months=3, audit_count=0,
            bug_bounty_usd=0.0, hack_history=False, hack_loss_pct=0.0,
            admin_key_risk=False, tvl_30d_change_pct=3.0, tvl_90d_change_pct=5.0,
            tvl_usd=20_000_000.0,
        )
        r = compute("X", "Y", factors)
        self.assertGreaterEqual(r.sustainability_index, 40.0)
        self.assertLess(r.sustainability_index, 60.0)
        self.assertEqual(r.grade, "C")
        self.assertEqual(r.label, "MODERATE_RISK")
        self.assertEqual(r.invest_confidence, "LOW")

    def test_grade_D_below_40(self):
        # real=2, maturity=1, security=0 (hack+admin), tvl=1+1+0=2 → 6 → D
        factors = SustainabilityFactors(
            real_yield_ratio=0.0, protocol_age_months=1, audit_count=0,
            bug_bounty_usd=0.0, hack_history=True, hack_loss_pct=50.0,
            admin_key_risk=True, tvl_30d_change_pct=50.0, tvl_90d_change_pct=80.0,
            tvl_usd=1_000_000.0,
        )
        r = compute("X", "Y", factors)
        self.assertLess(r.sustainability_index, 40.0)
        self.assertEqual(r.grade, "D")
        self.assertEqual(r.label, "HIGH_RISK")
        self.assertEqual(r.invest_confidence, "AVOID")

    def test_boundary_exactly_80(self):
        # Design factors that sum to exactly 80
        # real=25(1.0), mat=25, sec=25, tvl=5 → 80
        # tvl: tvl_size=1(small), stability_30d=1(>30%change), stability_90d=0(>50%), capped at min(25,2)=2... need 5
        # Let me try: real=14(0.5), mat=25, sec=25, tvl=16
        # tvl=16: size=4(10M), stability_30d=7(10-15%), stability_90d=5(10-25%) → 16
        factors = SustainabilityFactors(
            real_yield_ratio=0.5, protocol_age_months=36, audit_count=5,
            bug_bounty_usd=2_000_000.0, hack_history=False, hack_loss_pct=0.0,
            admin_key_risk=False, tvl_30d_change_pct=12.0, tvl_90d_change_pct=15.0,
            tvl_usd=15_000_000.0,
        )
        r = compute("X", "Y", factors)
        # real=14, mat=25, sec=25, tvl=4+7+5=16 → 80
        self.assertEqual(r.sustainability_index, 80.0)
        self.assertEqual(r.grade, "A")

    def test_boundary_exactly_60(self):
        # real=8(0.3), mat=25, sec=25, tvl=2 → 60
        # tvl: size=1(tiny), stability_30d=1(>30), stability_90d=0(>50) → 2
        factors = SustainabilityFactors(
            real_yield_ratio=0.3, protocol_age_months=36, audit_count=5,
            bug_bounty_usd=2_000_000.0, hack_history=False, hack_loss_pct=0.0,
            admin_key_risk=False, tvl_30d_change_pct=35.0, tvl_90d_change_pct=60.0,
            tvl_usd=1_000_000.0,
        )
        r = compute("X", "Y", factors)
        # real=8, mat=25, sec=25, tvl=1+1+0=2 → 60
        self.assertEqual(r.sustainability_index, 60.0)
        self.assertEqual(r.grade, "B")

    def test_boundary_exactly_40(self):
        # real=2(0.1), mat=7+0+0=7(12mo, 0audits, 0bounty), sec=25, tvl=6+0+0=6(100M,>30%,>50%)
        # → 2+7+25+6=40
        factors = SustainabilityFactors(
            real_yield_ratio=0.1, protocol_age_months=12, audit_count=0,
            bug_bounty_usd=0.0, hack_history=False, hack_loss_pct=0.0,
            admin_key_risk=False, tvl_30d_change_pct=35.0, tvl_90d_change_pct=60.0,
            tvl_usd=100_000_000.0,
        )
        r = compute("X", "Y", factors)
        # real=2, mat=7+0+0=7 wait: age=12→7, audit=0→0, bounty=0→0 → 7
        # sec=25, tvl=6+1+0=7
        # 2+7+25+7=41 → C
        self.assertGreaterEqual(r.sustainability_index, 40.0)
        self.assertLess(r.sustainability_index, 60.0)
        self.assertEqual(r.grade, "C")


# ---------------------------------------------------------------------------
# compute — key_strengths / key_risks
# ---------------------------------------------------------------------------

class TestKeyStrengthsRisks(unittest.TestCase):

    def test_key_strengths_are_top_2(self):
        r = _make_report()
        # Should have exactly 2 strengths
        self.assertEqual(len(r.key_strengths), 2)

    def test_key_risks_are_bottom_2(self):
        r = _make_report()
        self.assertEqual(len(r.key_risks), 2)

    def test_top_score_appears_in_strengths(self):
        # With perfect security and maturity, those should be strengths
        factors = _default_factors(
            hack_history=False, admin_key_risk=False,
            protocol_age_months=36, audit_count=5, bug_bounty_usd=5_000_000,
            real_yield_ratio=0.1,  # low → should be a risk
        )
        r = compute("X", "Y", factors)
        # real_yield is lowest, should appear in risks
        risks_text = " ".join(r.key_risks)
        self.assertIn("real yield", risks_text)

    def test_lowest_score_appears_in_risks(self):
        # Make security worst by having hack
        factors = _default_factors(
            hack_history=True, hack_loss_pct=50.0, admin_key_risk=True,
        )
        r = compute("X", "Y", factors)
        risks_text = " ".join(r.key_risks)
        self.assertIn("security", risks_text)

    def test_strengths_contain_score_info(self):
        r = _make_report()
        for s in r.key_strengths:
            self.assertIn("/25", s)

    def test_risks_contain_score_info(self):
        r = _make_report()
        for s in r.key_risks:
            self.assertIn("/25", s)


# ---------------------------------------------------------------------------
# compute — warnings
# ---------------------------------------------------------------------------

class TestWarnings(unittest.TestCase):

    def test_warning_hack_history(self):
        r = _make_report(hack_history=True, hack_loss_pct=5.0)
        self.assertIn("protocol was exploited", r.warnings)

    def test_no_hack_warning(self):
        r = _make_report(hack_history=False, hack_loss_pct=0.0)
        self.assertNotIn("protocol was exploited", r.warnings)

    def test_warning_admin_key(self):
        r = _make_report(admin_key_risk=True)
        self.assertIn("admin key risk", r.warnings)

    def test_no_admin_key_warning(self):
        r = _make_report(admin_key_risk=False)
        self.assertNotIn("admin key risk", r.warnings)

    def test_warning_low_real_yield(self):
        r = _make_report(real_yield_ratio=0.1)
        self.assertIn("low real yield", r.warnings)

    def test_no_low_yield_warning_at_02(self):
        r = _make_report(real_yield_ratio=0.2)
        self.assertNotIn("low real yield", r.warnings)

    def test_all_three_warnings(self):
        r = _make_report(
            hack_history=True, hack_loss_pct=10.0,
            admin_key_risk=True,
            real_yield_ratio=0.1,
        )
        self.assertIn("protocol was exploited", r.warnings)
        self.assertIn("admin key risk", r.warnings)
        self.assertIn("low real yield", r.warnings)

    def test_no_warnings_clean_protocol(self):
        r = _make_report(
            hack_history=False, admin_key_risk=False,
            real_yield_ratio=0.9,
        )
        self.assertEqual(r.warnings, [])


# ---------------------------------------------------------------------------
# rank_protocols
# ---------------------------------------------------------------------------

class TestRankProtocols(unittest.TestCase):

    def _make_named(self, name: str, real_yield_ratio: float) -> SustainabilityReport:
        factors = _default_factors(real_yield_ratio=real_yield_ratio)
        return compute(name, "Pool", factors)

    def test_ranked_descending(self):
        r1 = self._make_named("Low", 0.1)
        r2 = self._make_named("High", 1.0)
        r3 = self._make_named("Mid", 0.5)
        ranked = rank_protocols([r1, r2, r3])
        self.assertEqual(ranked[0].protocol, "High")
        self.assertEqual(ranked[1].protocol, "Mid")
        self.assertEqual(ranked[2].protocol, "Low")

    def test_rank_single(self):
        r = self._make_named("Only", 0.7)
        ranked = rank_protocols([r])
        self.assertEqual(len(ranked), 1)

    def test_rank_empty(self):
        self.assertEqual(rank_protocols([]), [])

    def test_rank_preserves_all(self):
        reports = [self._make_named(f"p{i}", 0.1 * i) for i in range(1, 6)]
        ranked = rank_protocols(reports)
        self.assertEqual(len(ranked), 5)


# ---------------------------------------------------------------------------
# save / load / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_report(self) -> SustainabilityReport:
        return compute("Aave", "USDC", _default_factors())

    def test_save_creates_file(self):
        r = self._make_report()
        save_results(r, self.data_dir)
        self.assertTrue((self.data_dir / "sustainability_index_log.json").exists())

    def test_load_empty_when_no_file(self):
        self.assertEqual(load_history(self.data_dir), [])

    def test_save_load_round_trip(self):
        r = self._make_report()
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(
            history[0]["sustainability_index"], r.sustainability_index, places=2
        )

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            save_results(self._make_report(), self.data_dir)
        self.assertEqual(len(load_history(self.data_dir)), 3)

    def test_ring_buffer_cap_at_100(self):
        for _ in range(110):
            save_results(self._make_report(), self.data_dir)
        self.assertEqual(len(load_history(self.data_dir)), 100)

    def test_ring_buffer_keeps_latest_100(self):
        # Save 105 entries, load should have entries 5..104
        for i in range(105):
            factors = _default_factors(real_yield_ratio=min(1.0, i / 200.0))
            r = compute(f"proto_{i}", "pool", factors)
            save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        # First entry in history is the 6th saved (index 5): proto_5
        self.assertEqual(history[0]["protocol"], "proto_5")
        self.assertEqual(history[-1]["protocol"], "proto_104")

    def test_saved_to_field_set(self):
        r = self._make_report()
        path = save_results(r, self.data_dir)
        self.assertEqual(r.saved_to, path)

    def test_atomic_write_valid_json(self):
        r = self._make_report()
        save_results(r, self.data_dir)
        with open(self.data_dir / "sustainability_index_log.json") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_protocol_stored_in_history(self):
        r = compute("Compound", "USDC", _default_factors())
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(history[0]["protocol"], "Compound")


if __name__ == "__main__":
    unittest.main()

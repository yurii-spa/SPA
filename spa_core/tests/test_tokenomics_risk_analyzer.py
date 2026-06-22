"""Tests for TokenomicsRiskAnalyzer (MP-701).

≥ 65 test methods covering:
- inflation_risk thresholds (0, 2, 5, 10, 20, 50, >50)
- unlimited supply bonus (+10)
- concentration_risk formula
- vesting_cliff_risk with/without upcoming cliffs
- overall_risk weighted average
- risk_label four tiers
- warnings for each threshold
- no warnings for clean tokenomics
- compare_tokens ranking
- save/load round-trip
- ring-buffer cap at 100
- edge cases (zero supply, 100% concentration, cliff=0)
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.tokenomics_risk_analyzer import (
    MAX_ENTRIES,
    W_CONCENTRATION,
    W_INFLATION,
    W_VESTING,
    TokenomicsRiskAnalyzer,
    VestingSchedule,
    _report_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _analyzer(tmp_dir: str) -> TokenomicsRiskAnalyzer:
    return TokenomicsRiskAnalyzer(data_dir=tmp_dir)


def _sched(category="team", total_pct=20.0, cliff=12, vest=48, unlocked=0.0):
    return VestingSchedule(
        category=category,
        total_pct=total_pct,
        cliff_months=cliff,
        vesting_months=vest,
        unlocked_pct=unlocked,
    )


def _analyze(
    analyzer,
    symbol="TKN",
    circ=500_000_000.0,
    total=1_000_000_000.0,
    max_supply=1_000_000_000.0,
    inflation=5.0,
    top10=40.0,
    team=15.0,
    investor=20.0,
    schedules=None,
    current_month=0,
):
    return analyzer.analyze(
        token_symbol=symbol,
        circulating_supply=circ,
        total_supply=total,
        max_supply=max_supply,
        inflation_rate_annual=inflation,
        top10_holders_pct=top10,
        team_allocation_pct=team,
        investor_allocation_pct=investor,
        schedules=schedules or [],
        current_month=current_month,
    )


# ---------------------------------------------------------------------------
# 1. inflation_risk thresholds
# ---------------------------------------------------------------------------

class TestInflationRisk(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_zero_inflation_score_zero(self):
        self.assertEqual(self.a._inflation_risk(0.0, 1e9), 0.0)

    def test_inflation_1_score_10(self):
        self.assertEqual(self.a._inflation_risk(1.0, 1e9), 10.0)

    def test_inflation_2_score_10(self):
        self.assertEqual(self.a._inflation_risk(2.0, 1e9), 10.0)

    def test_inflation_3_score_25(self):
        self.assertEqual(self.a._inflation_risk(3.0, 1e9), 25.0)

    def test_inflation_5_score_25(self):
        self.assertEqual(self.a._inflation_risk(5.0, 1e9), 25.0)

    def test_inflation_7_score_45(self):
        self.assertEqual(self.a._inflation_risk(7.0, 1e9), 45.0)

    def test_inflation_10_score_45(self):
        self.assertEqual(self.a._inflation_risk(10.0, 1e9), 45.0)

    def test_inflation_15_score_65(self):
        self.assertEqual(self.a._inflation_risk(15.0, 1e9), 65.0)

    def test_inflation_20_score_65(self):
        self.assertEqual(self.a._inflation_risk(20.0, 1e9), 65.0)

    def test_inflation_30_score_80(self):
        self.assertEqual(self.a._inflation_risk(30.0, 1e9), 80.0)

    def test_inflation_50_score_80(self):
        self.assertEqual(self.a._inflation_risk(50.0, 1e9), 80.0)

    def test_inflation_60_score_95(self):
        self.assertEqual(self.a._inflation_risk(60.0, 1e9), 95.0)

    def test_inflation_100_score_95(self):
        self.assertEqual(self.a._inflation_risk(100.0, 1e9), 95.0)

    def test_unlimited_supply_adds_10(self):
        base = self.a._inflation_risk(5.0, 1e9)      # 25
        unlimited = self.a._inflation_risk(5.0, 0.0)  # 35
        self.assertAlmostEqual(unlimited, base + 10.0)

    def test_unlimited_capped_at_100(self):
        # 95 + 10 = 105 → capped at 100
        score = self.a._inflation_risk(60.0, 0.0)
        self.assertEqual(score, 100.0)

    def test_zero_inflation_unlimited_adds_10(self):
        score = self.a._inflation_risk(0.0, 0.0)
        self.assertEqual(score, 10.0)


# ---------------------------------------------------------------------------
# 2. concentration_risk formula
# ---------------------------------------------------------------------------

class TestConcentrationRisk(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_formula_low_concentration(self):
        # (30 + 10 + 15) / 3 * 1.2 = 55 / 3 * 1.2 = 22.0
        score = self.a._concentration_risk(30.0, 10.0, 15.0)
        self.assertAlmostEqual(score, (30 + 10 + 15) / 3.0 * 1.2, places=4)

    def test_formula_high_concentration(self):
        score = self.a._concentration_risk(80.0, 30.0, 40.0)
        expected = min(100.0, (80 + 30 + 40) / 3.0 * 1.2)
        self.assertAlmostEqual(score, expected, places=4)

    def test_100_pct_concentration_capped_100(self):
        score = self.a._concentration_risk(100.0, 100.0, 100.0)
        self.assertEqual(score, 100.0)

    def test_zero_concentration_zero_score(self):
        score = self.a._concentration_risk(0.0, 0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_moderate_concentration(self):
        score = self.a._concentration_risk(50.0, 20.0, 25.0)
        expected = min(100.0, (50 + 20 + 25) / 3.0 * 1.2)
        self.assertAlmostEqual(score, expected, places=4)


# ---------------------------------------------------------------------------
# 3. vesting_cliff_risk
# ---------------------------------------------------------------------------

class TestVestingCliffRisk(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_no_schedules_zero_risk(self):
        score = self.a._vesting_cliff_risk(0.0, 0.0)
        self.assertEqual(score, 0.0)

    def test_formula(self):
        # upcoming=10, largest=20 → 10*2 + 20*1.5 = 50
        score = self.a._vesting_cliff_risk(10.0, 20.0)
        self.assertAlmostEqual(score, 50.0)

    def test_capped_at_100(self):
        score = self.a._vesting_cliff_risk(50.0, 50.0)
        self.assertLessEqual(score, 100.0)

    def test_upcoming_unlocks_computed_from_schedules(self):
        # cliff_months=1, current_month=0 → 0 <= 0 < 1+3=3 → YES
        sched = _sched(total_pct=15.0, cliff=1)
        upcoming = self.a._compute_upcoming_unlocks([sched], current_month=0)
        self.assertAlmostEqual(upcoming, 15.0)

    def test_upcoming_no_cliff_in_window(self):
        # cliff_months=12, current_month=0 → 12 <= 0 is False
        sched = _sched(total_pct=15.0, cliff=12)
        upcoming = self.a._compute_upcoming_unlocks([sched], current_month=0)
        self.assertAlmostEqual(upcoming, 0.0)

    def test_cliff_zero_immediate_unlock_high_risk(self):
        # cliff=0, current_month=0 → 0 <= 0 < 3 → included
        sched = _sched(total_pct=30.0, cliff=0)
        report = _analyze(self.a, schedules=[sched], current_month=0)
        self.assertGreater(report.vesting_cliff_risk, 0.0)

    def test_largest_cliff_correct(self):
        s1 = _sched(total_pct=10.0)
        s2 = _sched(total_pct=25.0, category="investors")
        largest = self.a._compute_largest_cliff([s1, s2])
        self.assertAlmostEqual(largest, 25.0)

    def test_largest_cliff_empty_schedules(self):
        largest = self.a._compute_largest_cliff([])
        self.assertEqual(largest, 0.0)

    def test_multiple_schedules_sum_upcoming(self):
        s1 = _sched(total_pct=10.0, cliff=0)
        s2 = _sched(total_pct=8.0, cliff=1, category="investors")
        upcoming = self.a._compute_upcoming_unlocks([s1, s2], current_month=0)
        self.assertAlmostEqual(upcoming, 18.0)


# ---------------------------------------------------------------------------
# 4. overall_risk weighted average
# ---------------------------------------------------------------------------

class TestOverallRisk(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_weighted_average_formula(self):
        ir, cr, vr = 40.0, 60.0, 50.0
        expected = ir * W_INFLATION + cr * W_CONCENTRATION + vr * W_VESTING
        actual = self.a._overall_risk(ir, cr, vr)
        self.assertAlmostEqual(actual, expected, places=4)

    def test_all_zero_overall_zero(self):
        self.assertAlmostEqual(self.a._overall_risk(0, 0, 0), 0.0)

    def test_all_100_overall_100(self):
        self.assertAlmostEqual(self.a._overall_risk(100, 100, 100), 100.0)

    def test_weights_sum_to_1(self):
        self.assertAlmostEqual(W_INFLATION + W_CONCENTRATION + W_VESTING, 1.0, places=4)

    def test_overall_stored_in_report(self):
        report = _analyze(self.a, inflation=5.0, top10=40.0, team=15.0, investor=20.0)
        ir = self.a._inflation_risk(5.0, 1e9)
        cr = self.a._concentration_risk(40.0, 15.0, 20.0)
        vr = self.a._vesting_cliff_risk(0.0, 0.0)
        expected = ir * W_INFLATION + cr * W_CONCENTRATION + vr * W_VESTING
        self.assertAlmostEqual(report.overall_risk, round(expected, 4), places=3)


# ---------------------------------------------------------------------------
# 5. risk_label four tiers
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_low_label(self):
        self.assertEqual(self.a._risk_label(10.0), "LOW")

    def test_low_boundary(self):
        self.assertEqual(self.a._risk_label(24.9), "LOW")

    def test_medium_label(self):
        self.assertEqual(self.a._risk_label(25.0), "MEDIUM")

    def test_medium_boundary(self):
        self.assertEqual(self.a._risk_label(49.9), "MEDIUM")

    def test_high_label(self):
        self.assertEqual(self.a._risk_label(50.0), "HIGH")

    def test_high_boundary(self):
        self.assertEqual(self.a._risk_label(69.9), "HIGH")

    def test_critical_label(self):
        self.assertEqual(self.a._risk_label(70.0), "CRITICAL")

    def test_critical_high_value(self):
        self.assertEqual(self.a._risk_label(100.0), "CRITICAL")


# ---------------------------------------------------------------------------
# 6. warnings
# ---------------------------------------------------------------------------

class TestWarnings(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_no_warnings_clean_token(self):
        report = _analyze(self.a, inflation=3.0, top10=30.0, team=10.0, investor=20.0)
        self.assertEqual(len(report.warnings), 0)

    def test_inflation_warning_triggered(self):
        report = _analyze(self.a, inflation=25.0)
        self.assertTrue(any("INFLATION" in w for w in report.warnings))

    def test_top10_warning_triggered(self):
        report = _analyze(self.a, top10=70.0)
        self.assertTrue(any("CONCENTRATION" in w for w in report.warnings))

    def test_team_warning_triggered(self):
        report = _analyze(self.a, team=25.0)
        self.assertTrue(any("TEAM" in w for w in report.warnings))

    def test_investor_warning_triggered(self):
        report = _analyze(self.a, investor=35.0)
        self.assertTrue(any("INVESTOR" in w for w in report.warnings))

    def test_cliff_unlock_warning_triggered(self):
        sched = _sched(total_pct=15.0, cliff=0)
        report = _analyze(self.a, schedules=[sched], current_month=0)
        self.assertTrue(any("CLIFF" in w for w in report.warnings))

    def test_multiple_warnings_accumulated(self):
        sched = _sched(total_pct=15.0, cliff=0)
        report = _analyze(
            self.a, inflation=30.0, top10=70.0, team=25.0,
            investor=35.0, schedules=[sched], current_month=0
        )
        self.assertGreaterEqual(len(report.warnings), 4)

    def test_exactly_at_inflation_threshold_no_warning(self):
        # exactly 20.0 is NOT > 20 → no warning
        report = _analyze(self.a, inflation=20.0)
        self.assertFalse(any("INFLATION" in w for w in report.warnings))

    def test_warnings_are_strings(self):
        report = _analyze(self.a, inflation=25.0, top10=70.0)
        for w in report.warnings:
            self.assertIsInstance(w, str)


# ---------------------------------------------------------------------------
# 7. compare_tokens
# ---------------------------------------------------------------------------

class TestCompareTokens(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def _make_reports(self):
        r1 = _analyze(self.a, symbol="AAA", inflation=2.0, top10=20.0, team=10.0, investor=15.0)
        r2 = _analyze(self.a, symbol="BBB", inflation=25.0, top10=70.0, team=25.0, investor=35.0)
        r3 = _analyze(self.a, symbol="CCC", inflation=8.0, top10=45.0, team=15.0, investor=20.0)
        return [r1, r2, r3]

    def test_compare_returns_dict(self):
        result = self.a.compare_tokens(self._make_reports())
        self.assertIsInstance(result, dict)

    def test_all_tokens_present(self):
        result = self.a.compare_tokens(self._make_reports())
        for sym in ("AAA", "BBB", "CCC"):
            self.assertIn(sym, result)

    def test_safest_ranked_first(self):
        result = self.a.compare_tokens(self._make_reports())
        self.assertEqual(result["AAA"]["rank"], 1)

    def test_riskiest_ranked_last(self):
        result = self.a.compare_tokens(self._make_reports())
        self.assertEqual(result["BBB"]["rank"], 3)

    def test_ranks_are_sequential(self):
        result = self.a.compare_tokens(self._make_reports())
        ranks = sorted(v["rank"] for v in result.values())
        self.assertEqual(ranks, [1, 2, 3])

    def test_overall_risk_in_result(self):
        result = self.a.compare_tokens(self._make_reports())
        for val in result.values():
            self.assertIn("overall_risk", val)

    def test_risk_label_in_result(self):
        result = self.a.compare_tokens(self._make_reports())
        for val in result.values():
            self.assertIn("risk_label", val)

    def test_single_token_rank_one(self):
        r = _analyze(self.a, symbol="SOLO")
        result = self.a.compare_tokens([r])
        self.assertEqual(result["SOLO"]["rank"], 1)

    def test_empty_list(self):
        result = self.a.compare_tokens([])
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# 8. save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_empty_history(self):
        self.assertEqual(self.a.load_history(), [])

    def test_save_and_load_one(self):
        report = _analyze(self.a)
        self.a.save_results(report)
        history = self.a.load_history()
        self.assertEqual(len(history), 1)

    def test_saved_entry_has_timestamp(self):
        report = _analyze(self.a)
        self.a.save_results(report)
        entry = self.a.load_history()[0]
        self.assertIn("timestamp", entry)

    def test_saved_entry_symbol(self):
        report = _analyze(self.a, symbol="MTKN")
        self.a.save_results(report)
        entry = self.a.load_history()[0]
        self.assertEqual(entry["token_symbol"], "MTKN")

    def test_multiple_saves_accumulate(self):
        for sym in ["A", "B", "C"]:
            self.a.save_results(_analyze(self.a, symbol=sym))
        self.assertEqual(len(self.a.load_history()), 3)

    def test_log_file_is_valid_json(self):
        self.a.save_results(_analyze(self.a))
        raw = Path(self.tmp, "tokenomics_risk_log.json").read_text()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, list)

    def test_saved_entry_has_risk_label(self):
        report = _analyze(self.a)
        self.a.save_results(report)
        entry = self.a.load_history()[0]
        self.assertIn("risk_label", entry)

    def test_saved_entry_has_warnings(self):
        report = _analyze(self.a)
        self.a.save_results(report)
        entry = self.a.load_history()[0]
        self.assertIn("warnings", entry)


# ---------------------------------------------------------------------------
# 9. ring-buffer cap
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_cap_at_max_entries(self):
        for i in range(MAX_ENTRIES + 15):
            self.a.save_results(_analyze(self.a, symbol=f"T{i}"))
        self.assertEqual(len(self.a.load_history()), MAX_ENTRIES)

    def test_latest_kept(self):
        for i in range(MAX_ENTRIES + 5):
            self.a.save_results(_analyze(self.a, symbol=f"T{i:04d}"))
        history = self.a.load_history()
        last_symbol = history[-1]["token_symbol"]
        self.assertEqual(last_symbol, f"T{MAX_ENTRIES + 4:04d}")


# ---------------------------------------------------------------------------
# 10. edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _analyzer(self.tmp)

    def test_zero_supply_no_crash(self):
        report = _analyze(self.a, circ=0.0, total=0.0)
        self.assertIsNotNone(report)

    def test_100_pct_top10_concentration(self):
        report = _analyze(self.a, top10=100.0, team=100.0, investor=100.0)
        self.assertAlmostEqual(report.concentration_risk, 100.0)

    def test_report_to_dict_has_all_keys(self):
        report = _analyze(self.a)
        d = _report_to_dict(report)
        for key in ("token_symbol", "circulating_supply", "total_supply", "max_supply",
                    "inflation_rate_annual", "top10_holders_pct", "team_allocation_pct",
                    "investor_allocation_pct", "schedules", "upcoming_unlocks_pct",
                    "largest_cliff_pct", "inflation_risk", "concentration_risk",
                    "vesting_cliff_risk", "overall_risk", "risk_label", "warnings",
                    "saved_to"):
            self.assertIn(key, d)

    def test_vesting_schedule_attributes(self):
        s = _sched()
        self.assertEqual(s.category, "team")
        self.assertEqual(s.cliff_months, 12)

    def test_cliff_0_immediate_unlock_included(self):
        s = _sched(total_pct=20.0, cliff=0)
        upcoming = self.a._compute_upcoming_unlocks([s], current_month=0)
        self.assertAlmostEqual(upcoming, 20.0)

    def test_inflation_risk_result_in_report(self):
        report = _analyze(self.a, inflation=5.0)
        self.assertAlmostEqual(report.inflation_risk, 25.0)

    def test_risk_label_present_in_report(self):
        report = _analyze(self.a)
        self.assertIn(report.risk_label, ("LOW", "MEDIUM", "HIGH", "CRITICAL"))


if __name__ == "__main__":
    unittest.main()

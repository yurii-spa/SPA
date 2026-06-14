"""
Tests for MP-874 ProtocolPonziRiskScreener.
Run: python3 -m unittest spa_core.tests.test_protocol_ponzi_risk_screener -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_ponzi_risk_screener import (
    analyze,
    _yield_coverage_ratio,
    _emission_dependency_pct,
    _new_deposit_reliance,
    _sustainability_score,
    _emission_risk_score,
    _structural_risk_score,
    _ponzi_risk_score,
    _classify,
    _warning_signals,
    _recommendation,
    init_log,
    LOG_PATH,
    LOG_MAX_ENTRIES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    advertised_apy=8.0,
    verified_fee_apy=7.5,
    emission_apy=0.5,
    new_deposits=1_000_000,
    tvl=50_000_000,
    yield_paid=333_000,
    fee_revenue=350_000,
    team_alloc=5.0,
    tvl_change=2.0,
):
    return {
        "name": name,
        "advertised_apy_pct": advertised_apy,
        "verified_fee_revenue_apy_pct": verified_fee_apy,
        "token_emission_apy_pct": emission_apy,
        "new_deposits_30d_usd": new_deposits,
        "total_tvl_usd": tvl,
        "yield_paid_30d_usd": yield_paid,
        "fee_revenue_30d_usd": fee_revenue,
        "team_allocation_pct": team_alloc,
        "tvl_change_30d_pct": tvl_change,
    }


def _ponzi_proto(name="Scam"):
    """A protocol that should score very high Ponzi risk."""
    return _proto(
        name=name,
        advertised_apy=300.0,
        verified_fee_apy=0.5,
        emission_apy=299.5,
        new_deposits=10_000_000,
        tvl=5_000_000,
        yield_paid=1_000_000,
        fee_revenue=5_000,
        team_alloc=40.0,
        tvl_change=-35.0,
    )


# ===========================================================================
# Unit tests — helper functions
# ===========================================================================

class TestYieldCoverageRatio(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(_yield_coverage_ratio(100, 200), 0.5)

    def test_zero_yield_paid(self):
        self.assertAlmostEqual(_yield_coverage_ratio(100, 0), 0.0)

    def test_negative_yield_paid(self):
        self.assertAlmostEqual(_yield_coverage_ratio(100, -1), 0.0)

    def test_equal(self):
        self.assertAlmostEqual(_yield_coverage_ratio(100, 100), 1.0)

    def test_over_coverage(self):
        self.assertAlmostEqual(_yield_coverage_ratio(300, 200), 1.5)


class TestEmissionDependencyPct(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(_emission_dependency_pct(8.0, 10.0), 80.0)

    def test_zero_advertised(self):
        self.assertAlmostEqual(_emission_dependency_pct(5.0, 0.0), 0.0)

    def test_zero_emission(self):
        self.assertAlmostEqual(_emission_dependency_pct(0.0, 10.0), 0.0)

    def test_full_dependency(self):
        self.assertAlmostEqual(_emission_dependency_pct(10.0, 10.0), 100.0)

    def test_partial(self):
        self.assertAlmostEqual(_emission_dependency_pct(3.0, 10.0), 30.0)


class TestNewDepositReliance(unittest.TestCase):
    def test_normal(self):
        # 1_000_000 / (100_000 * 12) = 0.833...
        self.assertAlmostEqual(_new_deposit_reliance(1_000_000, 100_000), 1_000_000 / 1_200_000)

    def test_zero_yield(self):
        self.assertAlmostEqual(_new_deposit_reliance(1_000_000, 0), 0.0)

    def test_zero_deposits(self):
        self.assertAlmostEqual(_new_deposit_reliance(0, 100_000), 0.0)

    def test_high_reliance(self):
        # deposits = 3x annual yield → reliance = 3/(12) = 0.25? No: reliance = new_deposits / (yield_paid*12)
        # new_deposits=3_600_000, yield_paid=100_000 → reliance = 3_600_000/1_200_000 = 3
        self.assertAlmostEqual(_new_deposit_reliance(3_600_000, 100_000), 3.0)


class TestSustainabilityScore(unittest.TestCase):
    def test_zero_yield_paid_returns_40(self):
        self.assertEqual(_sustainability_score(0.0, 0), 40)

    def test_negative_yield_paid_returns_40(self):
        self.assertEqual(_sustainability_score(0.0, -1), 40)

    def test_ratio_above_1_5(self):
        self.assertEqual(_sustainability_score(1.6, 1000), 40)

    def test_ratio_exactly_1_5(self):
        self.assertEqual(_sustainability_score(1.5, 1000), 40)

    def test_ratio_exactly_1(self):
        self.assertEqual(_sustainability_score(1.0, 1000), 30)

    def test_ratio_above_0_75(self):
        self.assertEqual(_sustainability_score(0.8, 1000), 20)

    def test_ratio_exactly_0_75(self):
        self.assertEqual(_sustainability_score(0.75, 1000), 20)

    def test_ratio_above_0_5(self):
        self.assertEqual(_sustainability_score(0.6, 1000), 10)

    def test_ratio_exactly_0_5(self):
        self.assertEqual(_sustainability_score(0.5, 1000), 10)

    def test_ratio_above_0_25(self):
        self.assertEqual(_sustainability_score(0.3, 1000), 5)

    def test_ratio_exactly_0_25(self):
        self.assertEqual(_sustainability_score(0.25, 1000), 5)

    def test_ratio_below_0_25(self):
        self.assertEqual(_sustainability_score(0.1, 1000), 0)

    def test_ratio_zero(self):
        self.assertEqual(_sustainability_score(0.0, 1000), 0)


class TestEmissionRiskScore(unittest.TestCase):
    def test_below_20(self):
        self.assertEqual(_emission_risk_score(10.0), 0)

    def test_exactly_20(self):
        self.assertEqual(_emission_risk_score(20.0), 8)

    def test_between_20_40(self):
        self.assertEqual(_emission_risk_score(30.0), 8)

    def test_exactly_40(self):
        self.assertEqual(_emission_risk_score(40.0), 16)

    def test_between_40_60(self):
        self.assertEqual(_emission_risk_score(55.0), 16)

    def test_exactly_60(self):
        self.assertEqual(_emission_risk_score(60.0), 24)

    def test_between_60_80(self):
        self.assertEqual(_emission_risk_score(70.0), 24)

    def test_exactly_80(self):
        self.assertEqual(_emission_risk_score(80.0), 30)

    def test_above_80(self):
        self.assertEqual(_emission_risk_score(99.9), 30)

    def test_zero(self):
        self.assertEqual(_emission_risk_score(0.0), 0)


class TestStructuralRiskScore(unittest.TestCase):
    def test_all_zero(self):
        self.assertEqual(_structural_risk_score(0.0, 0.0, 0.0), 0)

    def test_team_below_10(self):
        self.assertEqual(_structural_risk_score(5.0, 0.0, 0.0), 0)

    def test_team_exactly_10(self):
        self.assertEqual(_structural_risk_score(10.0, 0.0, 0.0), 5)

    def test_team_above_10(self):
        self.assertEqual(_structural_risk_score(15.0, 0.0, 0.0), 5)

    def test_team_exactly_20(self):
        self.assertEqual(_structural_risk_score(20.0, 0.0, 0.0), 10)

    def test_team_exactly_30(self):
        self.assertEqual(_structural_risk_score(30.0, 0.0, 0.0), 15)

    def test_team_above_30(self):
        self.assertEqual(_structural_risk_score(50.0, 0.0, 0.0), 15)

    def test_tvl_decline_triggers_plus10(self):
        self.assertEqual(_structural_risk_score(0.0, -21.0, 0.0), 10)

    def test_tvl_exactly_minus_20_no_trigger(self):
        # tvl_change < -20 triggers, exactly -20 does not
        self.assertEqual(_structural_risk_score(0.0, -20.0, 0.0), 0)

    def test_reliance_above_2(self):
        self.assertEqual(_structural_risk_score(0.0, 0.0, 2.0), 5)

    def test_reliance_below_2(self):
        self.assertEqual(_structural_risk_score(0.0, 0.0, 1.9), 0)

    def test_cap_at_30(self):
        # max possible: 15 + 10 + 5 = 30
        result = _structural_risk_score(40.0, -30.0, 3.0)
        self.assertEqual(result, 30)

    def test_combined(self):
        # team=20 → +10; tvl=-25 → +10; reliance=2.5 → +5 = 25
        self.assertEqual(_structural_risk_score(20.0, -25.0, 2.5), 25)


class TestPonziRiskScore(unittest.TestCase):
    def test_zero_risk(self):
        # emission=0, structural=0, sustainability=40 → 0+0+(40-40)=0
        self.assertEqual(_ponzi_risk_score(0, 0, 40), 0)

    def test_max_risk(self):
        # emission=30, structural=30, sustainability=0 → 30+30+40=100
        self.assertEqual(_ponzi_risk_score(30, 30, 0), 100)

    def test_capped_at_100(self):
        self.assertEqual(_ponzi_risk_score(30, 30, 0), 100)

    def test_moderate(self):
        # emission=16, structural=10, sustainability=20 → 16+10+20=46
        self.assertEqual(_ponzi_risk_score(16, 10, 20), 46)

    def test_formula(self):
        em, st, sus = 24, 15, 5
        expected = min(100, em + st + (40 - sus))
        self.assertEqual(_ponzi_risk_score(em, st, sus), expected)


class TestClassify(unittest.TestCase):
    def test_legitimate(self):
        self.assertEqual(_classify(0), "LEGITIMATE")
        self.assertEqual(_classify(19), "LEGITIMATE")

    def test_watch(self):
        self.assertEqual(_classify(20), "WATCH")
        self.assertEqual(_classify(39), "WATCH")

    def test_yield_inflated(self):
        self.assertEqual(_classify(40), "YIELD_INFLATED")
        self.assertEqual(_classify(59), "YIELD_INFLATED")

    def test_ponzi_risk(self):
        self.assertEqual(_classify(60), "PONZI_RISK")
        self.assertEqual(_classify(79), "PONZI_RISK")

    def test_exit_scam_risk(self):
        self.assertEqual(_classify(80), "EXIT_SCAM_RISK")
        self.assertEqual(_classify(100), "EXIT_SCAM_RISK")


class TestWarningSignals(unittest.TestCase):
    def test_no_signals(self):
        signals = _warning_signals(10.0, 1.5, 100, 5.0, 5.0, 0.5, 5.0)
        self.assertEqual(signals, ["No Ponzi risk signals detected"])

    def test_emission_above_80(self):
        signals = _warning_signals(85.0, 1.5, 100, 5.0, 5.0, 0.5, 5.0)
        self.assertTrue(any("80%" in s for s in signals))

    def test_yield_coverage_below_0_3(self):
        signals = _warning_signals(10.0, 0.2, 100, 5.0, 5.0, 0.5, 5.0)
        self.assertTrue(any("30%" in s for s in signals))

    def test_yield_coverage_zero_yield_no_signal(self):
        # yield_paid_30d=0 → no "covers <30%" signal
        signals = _warning_signals(10.0, 0.0, 0, 5.0, 5.0, 0.5, 5.0)
        self.assertFalse(any("30%" in s for s in signals))

    def test_team_allocation_above_25(self):
        signals = _warning_signals(10.0, 1.5, 100, 30.0, 5.0, 0.5, 5.0)
        self.assertTrue(any("Team takes" in s for s in signals))

    def test_tvl_decline_below_minus25(self):
        signals = _warning_signals(10.0, 1.5, 100, 5.0, -30.0, 0.5, 5.0)
        self.assertTrue(any("capital fleeing" in s for s in signals))

    def test_tvl_exactly_minus_25_triggers(self):
        signals = _warning_signals(10.0, 1.5, 100, 5.0, -25.0, 0.5, 5.0)
        self.assertTrue(any("capital fleeing" in s for s in signals))

    def test_deposit_reliance_above_1_5(self):
        signals = _warning_signals(10.0, 1.5, 100, 5.0, 5.0, 2.0, 5.0)
        self.assertTrue(any("Ponzi structure" in s for s in signals))

    def test_advertised_apy_above_50(self):
        signals = _warning_signals(10.0, 1.5, 100, 5.0, 5.0, 0.5, 60.0)
        self.assertTrue(any("Unsustainable" in s for s in signals))

    def test_multiple_signals(self):
        signals = _warning_signals(90.0, 0.1, 100, 35.0, -30.0, 3.0, 200.0)
        self.assertGreater(len(signals), 1)


class TestRecommendation(unittest.TestCase):
    def test_exit_scam(self):
        rec = _recommendation("EXIT_SCAM_RISK", "BadProto", 90.0, 0.5, 0.05)
        self.assertIn("IMMEDIATE EXIT", rec)
        self.assertIn("BadProto", rec)

    def test_ponzi_risk(self):
        rec = _recommendation("PONZI_RISK", "BadProto", 85.0, 0.5, 0.1)
        self.assertIn("HIGH RISK", rec)
        self.assertIn("85%", rec)

    def test_yield_inflated(self):
        rec = _recommendation("YIELD_INFLATED", "MidProto", 60.0, 3.5, 0.4)
        self.assertIn("3.5%", rec)

    def test_watch(self):
        rec = _recommendation("WATCH", "WatchProto", 30.0, 5.0, 0.8)
        self.assertIn("WatchProto", rec)
        self.assertIn("Monitor", rec)

    def test_legitimate(self):
        rec = _recommendation("LEGITIMATE", "GoodProto", 5.0, 7.5, 1.25)
        self.assertIn("GoodProto", rec)
        self.assertIn("1.25x", rec)


# ===========================================================================
# Integration tests — analyze()
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_highest_risk_none(self):
        self.assertIsNone(self.result["highest_risk"])

    def test_safest_none(self):
        self.assertIsNone(self.result["safest"])

    def test_ponzi_list_empty(self):
        self.assertEqual(self.result["ponzi_risk_protocols"], [])

    def test_average_score_zero(self):
        self.assertAlmostEqual(self.result["average_ponzi_score"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)


class TestAnalyzeLegitimateProtocol(unittest.TestCase):
    """Good protocol: fee revenue >> yield paid, low emissions, low team alloc."""

    def setUp(self):
        self.result = analyze([_proto()])
        self.p = self.result["protocols"][0]

    def test_classification_legitimate(self):
        self.assertEqual(self.p["risk_classification"], "LEGITIMATE")

    def test_ponzi_score_low(self):
        self.assertLess(self.p["ponzi_risk_score"], 20)

    def test_yield_coverage_above_1(self):
        self.assertGreater(self.p["yield_coverage_ratio"], 1.0)

    def test_no_ponzi_protocols(self):
        self.assertEqual(self.result["ponzi_risk_protocols"], [])

    def test_warning_signals_none(self):
        self.assertIn("No Ponzi risk signals detected", self.p["warning_signals"])


class TestAnalyzePonziProtocol(unittest.TestCase):
    """Protocol with all Ponzi characteristics."""

    def setUp(self):
        self.result = analyze([_ponzi_proto()])
        self.p = self.result["protocols"][0]

    def test_high_ponzi_score(self):
        self.assertGreater(self.p["ponzi_risk_score"], 59)

    def test_classification_ponzi_or_exit(self):
        self.assertIn(
            self.p["risk_classification"],
            ["PONZI_RISK", "EXIT_SCAM_RISK"],
        )

    def test_emission_dependency_high(self):
        self.assertGreater(self.p["emission_dependency_pct"], 79)

    def test_in_ponzi_protocols_list(self):
        self.assertIn("Scam", self.result["ponzi_risk_protocols"])

    def test_warning_signals_not_empty(self):
        signals = self.p["warning_signals"]
        self.assertFalse(signals == ["No Ponzi risk signals detected"])

    def test_recommendation_contains_risk(self):
        rec = self.p["recommendation"]
        self.assertTrue(
            "EXIT" in rec or "HIGH RISK" in rec,
            f"Unexpected recommendation: {rec}",
        )


class TestAnalyzeMultipleProtocols(unittest.TestCase):
    """One legit, one Ponzi → highest/safest correctly identified."""

    def setUp(self):
        self.result = analyze([
            _proto(name="Good"),
            _ponzi_proto(name="Bad"),
        ])

    def test_highest_risk_is_bad(self):
        self.assertEqual(self.result["highest_risk"], "Bad")

    def test_safest_is_good(self):
        self.assertEqual(self.result["safest"], "Good")

    def test_ponzi_list_contains_bad(self):
        self.assertIn("Bad", self.result["ponzi_risk_protocols"])

    def test_ponzi_list_excludes_good(self):
        self.assertNotIn("Good", self.result["ponzi_risk_protocols"])

    def test_average_score_between_extremes(self):
        scores = [p["ponzi_risk_score"] for p in self.result["protocols"]]
        avg = sum(scores) / len(scores)
        self.assertAlmostEqual(self.result["average_ponzi_score"], avg, places=4)


class TestAnalyzeOutputKeys(unittest.TestCase):
    def test_top_level_keys(self):
        result = analyze([_proto()])
        for key in [
            "protocols",
            "highest_risk",
            "safest",
            "ponzi_risk_protocols",
            "average_ponzi_score",
            "timestamp",
        ]:
            self.assertIn(key, result)

    def test_protocol_level_keys(self):
        result = analyze([_proto()])
        p = result["protocols"][0]
        for key in [
            "name",
            "ponzi_risk_score",
            "risk_classification",
            "yield_coverage_ratio",
            "emission_dependency_pct",
            "new_deposit_reliance_pct",
            "sustainability_score",
            "emission_risk_score",
            "structural_risk_score",
            "warning_signals",
            "recommendation",
        ]:
            self.assertIn(key, p, f"Key '{key}' missing from protocol result")


class TestAnalyzeZeroYieldPaid(unittest.TestCase):
    """Protocol that pays no yield — sustainability should be 40."""

    def setUp(self):
        p = _proto(yield_paid=0, fee_revenue=100_000, emission_apy=0, advertised_apy=5.0)
        self.result = analyze([p])
        self.p = self.result["protocols"][0]

    def test_sustainability_40(self):
        self.assertEqual(self.p["sustainability_score"], 40)

    def test_yield_coverage_zero(self):
        self.assertAlmostEqual(self.p["yield_coverage_ratio"], 0.0)

    def test_new_deposit_reliance_zero(self):
        self.assertAlmostEqual(self.p["new_deposit_reliance_pct"], 0.0)


class TestAnalyzeHighAdvertisedAPY(unittest.TestCase):
    """APY >= 50% triggers unsustainable warning."""

    def setUp(self):
        p = _proto(advertised_apy=100.0, emission_apy=95.0, verified_fee_apy=5.0)
        self.result = analyze([p])
        self.p = self.result["protocols"][0]

    def test_unsustainable_signal(self):
        signals = self.p["warning_signals"]
        self.assertTrue(any("Unsustainable" in s for s in signals))

    def test_emission_dependency_high(self):
        self.assertAlmostEqual(self.p["emission_dependency_pct"], 95.0, places=1)


class TestAnalyzeTeamAllocationHigh(unittest.TestCase):
    """Team takes 35% → structural risk, warning signal."""

    def setUp(self):
        p = _proto(team_alloc=35.0)
        self.result = analyze([p])
        self.p = self.result["protocols"][0]

    def test_structural_includes_team(self):
        self.assertGreaterEqual(self.p["structural_risk_score"], 15)

    def test_team_warning_signal(self):
        signals = self.p["warning_signals"]
        self.assertTrue(any("Team takes" in s for s in signals))


class TestAnalyzeTVLFleeing(unittest.TestCase):
    """TVL declining >25% → structural risk."""

    def setUp(self):
        p = _proto(tvl_change=-30.0)
        self.result = analyze([p])
        self.p = self.result["protocols"][0]

    def test_structural_includes_tvl(self):
        self.assertGreaterEqual(self.p["structural_risk_score"], 10)

    def test_tvl_warning_signal(self):
        signals = self.p["warning_signals"]
        self.assertTrue(any("capital fleeing" in s for s in signals))


class TestAnalyzeSustainabilityLevels(unittest.TestCase):
    """Verify sustainability score thresholds via full analyze()."""

    def _score_for_ratio(self, ratio):
        """Set yield and fee_revenue to produce the desired coverage ratio."""
        p = _proto(yield_paid=100_000, fee_revenue=ratio * 100_000)
        result = analyze([p])
        return result["protocols"][0]["sustainability_score"]

    def test_high_coverage(self):
        self.assertEqual(self._score_for_ratio(1.6), 40)

    def test_break_even(self):
        self.assertEqual(self._score_for_ratio(1.0), 30)

    def test_partial_coverage_0_75(self):
        self.assertEqual(self._score_for_ratio(0.75), 20)

    def test_partial_coverage_0_5(self):
        self.assertEqual(self._score_for_ratio(0.5), 10)

    def test_partial_coverage_0_25(self):
        self.assertEqual(self._score_for_ratio(0.25), 5)

    def test_very_low_coverage(self):
        self.assertEqual(self._score_for_ratio(0.1), 0)


class TestAnalyzePonziRiskScore(unittest.TestCase):
    """Score range and capping."""

    def test_score_between_0_and_100(self):
        for p in [_proto(), _ponzi_proto()]:
            result = analyze([p])
            score = result["protocols"][0]["ponzi_risk_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_legitimate_low_score(self):
        result = analyze([_proto()])
        self.assertLess(result["protocols"][0]["ponzi_risk_score"], 20)

    def test_ponzi_high_score(self):
        result = analyze([_ponzi_proto()])
        self.assertGreaterEqual(result["protocols"][0]["ponzi_risk_score"], 60)


class TestAnalyzeTimestamp(unittest.TestCase):
    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestAnalyzeNamePassthrough(unittest.TestCase):
    def test_name_preserved(self):
        result = analyze([_proto(name="MyProtocol")])
        self.assertEqual(result["protocols"][0]["name"], "MyProtocol")


class TestAnalyzeThreeProtocols(unittest.TestCase):
    def setUp(self):
        self.result = analyze([
            _proto(name="A"),
            _proto(name="B", team_alloc=35.0, tvl_change=-30.0),
            _ponzi_proto(name="C"),
        ])

    def test_three_protocols(self):
        self.assertEqual(len(self.result["protocols"]), 3)

    def test_highest_risk_is_c(self):
        self.assertEqual(self.result["highest_risk"], "C")

    def test_safest_is_a(self):
        self.assertEqual(self.result["safest"], "A")


class TestAnalyzeWatchClassification(unittest.TestCase):
    """Protocol with score 20-39 → WATCH."""

    def test_watch_classification(self):
        # emission 40-59% → score=16, sustainability=30 → (40-30)=10 → total 16+0+10=26 → WATCH
        p = _proto(
            advertised_apy=10.0,
            emission_apy=5.0,   # 50% → emission_risk=16
            yield_paid=100_000,
            fee_revenue=100_000,  # ratio=1.0 → sustainability=30
            team_alloc=5.0,
            tvl_change=0.0,
        )
        result = analyze([p])
        score = result["protocols"][0]["ponzi_risk_score"]
        classification = result["protocols"][0]["risk_classification"]
        # emission_dependency = 5/10*100=50% → emission_risk=16
        # sustainability_score = 30 → (40-30)=10
        # structural = 0
        # total = 16+0+10=26 → WATCH
        self.assertEqual(classification, "WATCH")


class TestAnalyzeYieldInflatedClassification(unittest.TestCase):
    """Score 40-59 → YIELD_INFLATED."""

    def test_yield_inflated_classification(self):
        # emission_dep=70% → emission_risk=24; sustainability=5 → (40-5)=35; struct=0 → 24+35=59
        p = _proto(
            advertised_apy=10.0,
            emission_apy=7.0,   # 70% → emission_risk=24
            yield_paid=100_000,
            fee_revenue=25_000,  # ratio=0.25 → sustainability=5
            team_alloc=5.0,
            tvl_change=0.0,
        )
        result = analyze([p])
        classification = result["protocols"][0]["risk_classification"]
        score = result["protocols"][0]["ponzi_risk_score"]
        self.assertIn(classification, ["YIELD_INFLATED", "PONZI_RISK"])


# ===========================================================================
# Log management tests
# ===========================================================================

class TestInitLog(unittest.TestCase):
    def test_creates_file(self):
        import spa_core.analytics.protocol_ponzi_risk_screener as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_log.json")
            try:
                mod.init_log()
                self.assertTrue(os.path.exists(mod.LOG_PATH))
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertEqual(data, [])
            finally:
                mod.LOG_PATH = orig

    def test_does_not_overwrite_existing(self):
        import spa_core.analytics.protocol_ponzi_risk_screener as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            log_path = os.path.join(tmpdir, "test_log.json")
            mod.LOG_PATH = log_path
            try:
                with open(log_path, "w") as f:
                    json.dump([{"existing": True}], f)
                mod.init_log()
                with open(log_path) as f:
                    data = json.load(f)
                self.assertEqual(data, [{"existing": True}])
            finally:
                mod.LOG_PATH = orig


class TestAppendLog(unittest.TestCase):
    def _run_with_tmp_log(self, fn):
        import spa_core.analytics.protocol_ponzi_risk_screener as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_log.json")
            try:
                fn(mod)
            finally:
                mod.LOG_PATH = orig

    def test_log_appends_entries(self):
        def check(mod):
            analyze([])
            analyze([])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
        self._run_with_tmp_log(check)

    def test_ring_buffer_100(self):
        def check(mod):
            for _ in range(105):
                analyze([])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)
        self._run_with_tmp_log(check)

    def test_entry_has_timestamp(self):
        def check(mod):
            analyze([_proto()])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[-1])
        self._run_with_tmp_log(check)

    def test_log_valid_json(self):
        def check(mod):
            analyze([_proto()])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        self._run_with_tmp_log(check)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_empty_no_error(self):
        self.assertIsNotNone(analyze([]))

    def test_zero_all_values(self):
        p = _proto(
            advertised_apy=0, verified_fee_apy=0, emission_apy=0,
            new_deposits=0, tvl=0, yield_paid=0, fee_revenue=0,
            team_alloc=0, tvl_change=0
        )
        result = analyze([p])
        self.assertIsNotNone(result)

    def test_very_high_apy(self):
        p = _proto(advertised_apy=10000.0, emission_apy=9999.0)
        result = analyze([p])
        self.assertLessEqual(result["protocols"][0]["ponzi_risk_score"], 100)

    def test_negative_tvl_change_big(self):
        p = _proto(tvl_change=-99.9)
        result = analyze([p])
        score = result["protocols"][0]["structural_risk_score"]
        self.assertGreaterEqual(score, 10)

    def test_config_none(self):
        self.assertIsNotNone(analyze([_proto()], config=None))

    def test_config_empty(self):
        self.assertIsNotNone(analyze([_proto()], config={}))

    def test_ponzi_risk_score_int_type(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["protocols"][0]["ponzi_risk_score"], int)

    def test_warning_signals_list_type(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["protocols"][0]["warning_signals"], list)

    def test_ponzi_protocols_list_type(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["ponzi_risk_protocols"], list)

    def test_same_protocol_twice(self):
        result = analyze([_proto(name="X"), _proto(name="X")])
        self.assertEqual(len(result["protocols"]), 2)


if __name__ == "__main__":
    unittest.main()

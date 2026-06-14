"""
Unit tests for MP-854: ProtocolNetworkEffectScorer
Run: python3 -m unittest spa_core/tests/test_protocol_network_effect_scorer.py -v
"""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_network_effect_scorer import (
    analyze,
    init_log,
    load_history,
    _user_flywheel_score,
    _composability_score,
    _capital_efficiency_score,
    _reach_score,
    _network_strength,
    _moat_assessment,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    monthly_active_users=0,
    user_growth_30d_pct=0.0,
    integrations_count=0,
    dependent_tvl_usd=0.0,
    own_tvl_usd=0.0,
    tx_count_30d=0,
    unique_token_holders=0,
    cross_chain_deployments=0,
):
    return {
        "name": name,
        "monthly_active_users": monthly_active_users,
        "user_growth_30d_pct": user_growth_30d_pct,
        "integrations_count": integrations_count,
        "dependent_tvl_usd": dependent_tvl_usd,
        "own_tvl_usd": own_tvl_usd,
        "tx_count_30d": tx_count_30d,
        "unique_token_holders": unique_token_holders,
        "cross_chain_deployments": cross_chain_deployments,
    }


# ---------------------------------------------------------------------------
# Tests: _user_flywheel_score
# ---------------------------------------------------------------------------

class TestUserFlywheelScore(unittest.TestCase):

    def test_growth_30_plus_large_users(self):
        # 30% growth + 100k MAU → 15 + 10 = 25, capped at 25
        self.assertEqual(_user_flywheel_score(100_000, 30.0), 25)

    def test_growth_30_plus_mid_users(self):
        # 30% growth (15) + 10k MAU (7) = 22
        self.assertEqual(_user_flywheel_score(10_000, 30.0), 22)

    def test_growth_15_large_users(self):
        # 15% growth (12) + 100k MAU (10) = 22
        self.assertEqual(_user_flywheel_score(100_000, 15.0), 22)

    def test_growth_5_small_users(self):
        # 5% growth (8) + 0 MAU scale (0) = 8
        self.assertEqual(_user_flywheel_score(500, 5.0), 8)

    def test_growth_0_mid_users(self):
        # 0% growth (4) + 10k MAU (7) = 11
        self.assertEqual(_user_flywheel_score(10_000, 0.0), 11)

    def test_negative_growth_large_users(self):
        # negative growth (0) + 100k (10) = 10
        self.assertEqual(_user_flywheel_score(100_000, -5.0), 10)

    def test_all_zeros(self):
        self.assertEqual(_user_flywheel_score(0, 0.0), 4)

    def test_all_zeros_negative_growth(self):
        self.assertEqual(_user_flywheel_score(0, -1.0), 0)

    def test_cap_at_25(self):
        # Max possible: 15+10 = 25, not above
        score = _user_flywheel_score(1_000_000, 100.0)
        self.assertLessEqual(score, 25)

    def test_growth_exactly_15(self):
        # boundary: >=15 → 12
        self.assertEqual(_user_flywheel_score(0, 15.0), 12)

    def test_growth_exactly_5(self):
        # boundary: >=5 → 8
        self.assertEqual(_user_flywheel_score(0, 5.0), 8)

    def test_users_exactly_1000(self):
        # >=1000 → 4
        score = _user_flywheel_score(1_000, 0.0)
        self.assertEqual(score, 8)  # 4 (growth 0) + 4 (1k users)

    def test_users_exactly_10000(self):
        score = _user_flywheel_score(10_000, 0.0)
        self.assertEqual(score, 11)  # 4 + 7

    def test_users_exactly_100000(self):
        score = _user_flywheel_score(100_000, 0.0)
        self.assertEqual(score, 14)  # 4 + 10


# ---------------------------------------------------------------------------
# Tests: _composability_score
# ---------------------------------------------------------------------------

class TestComposabilityScore(unittest.TestCase):

    def test_50_integrations_1b_tvl(self):
        # 15 + 10 = 25, capped
        self.assertEqual(_composability_score(50, 1_000_000_000.0), 25)

    def test_20_integrations_100m_tvl(self):
        # 12 + 7 = 19
        self.assertEqual(_composability_score(20, 100_000_000.0), 19)

    def test_10_integrations_10m_tvl(self):
        # 8 + 4 = 12
        self.assertEqual(_composability_score(10, 10_000_000.0), 12)

    def test_5_integrations_1m_tvl(self):
        # 4 + 2 = 6
        self.assertEqual(_composability_score(5, 1_000_000.0), 6)

    def test_0_integrations_0_tvl(self):
        self.assertEqual(_composability_score(0, 0.0), 0)

    def test_integrations_exactly_50(self):
        self.assertEqual(_composability_score(50, 0.0), 15)

    def test_integrations_exactly_20(self):
        self.assertEqual(_composability_score(20, 0.0), 12)

    def test_integrations_exactly_10(self):
        self.assertEqual(_composability_score(10, 0.0), 8)

    def test_integrations_exactly_5(self):
        self.assertEqual(_composability_score(5, 0.0), 4)

    def test_integrations_4(self):
        self.assertEqual(_composability_score(4, 0.0), 0)

    def test_dependent_tvl_below_1m(self):
        self.assertEqual(_composability_score(0, 999_999.0), 0)

    def test_cap_at_25(self):
        score = _composability_score(1_000, 1_000_000_000_000.0)
        self.assertLessEqual(score, 25)

    def test_high_integrations_low_tvl(self):
        # 50+ integrations (15) + 0 TVL (0) = 15
        self.assertEqual(_composability_score(100, 0.0), 15)


# ---------------------------------------------------------------------------
# Tests: _capital_efficiency_score
# ---------------------------------------------------------------------------

class TestCapitalEfficiencyScore(unittest.TestCase):

    def test_zero_own_tvl(self):
        self.assertEqual(_capital_efficiency_score(1_000_000.0, 0.0), 0)

    def test_5x_leverage(self):
        self.assertEqual(_capital_efficiency_score(5_000_000.0, 1_000_000.0), 25)

    def test_2x_leverage(self):
        self.assertEqual(_capital_efficiency_score(2_000_000.0, 1_000_000.0), 20)

    def test_1x_leverage(self):
        self.assertEqual(_capital_efficiency_score(1_000_000.0, 1_000_000.0), 15)

    def test_0_5x_leverage(self):
        self.assertEqual(_capital_efficiency_score(500_000.0, 1_000_000.0), 8)

    def test_0_1x_leverage(self):
        self.assertEqual(_capital_efficiency_score(100_000.0, 1_000_000.0), 4)

    def test_below_0_1(self):
        self.assertEqual(_capital_efficiency_score(50_000.0, 1_000_000.0), 0)

    def test_exactly_5x(self):
        self.assertEqual(_capital_efficiency_score(5.0, 1.0), 25)

    def test_exactly_2x(self):
        self.assertEqual(_capital_efficiency_score(2.0, 1.0), 20)

    def test_exactly_1x(self):
        self.assertEqual(_capital_efficiency_score(1.0, 1.0), 15)

    def test_exactly_0_5(self):
        self.assertEqual(_capital_efficiency_score(0.5, 1.0), 8)

    def test_exactly_0_1(self):
        self.assertEqual(_capital_efficiency_score(0.1, 1.0), 4)

    def test_above_5x(self):
        # 10x still returns 25
        self.assertEqual(_capital_efficiency_score(10.0, 1.0), 25)


# ---------------------------------------------------------------------------
# Tests: _reach_score
# ---------------------------------------------------------------------------

class TestReachScore(unittest.TestCase):

    def test_all_max(self):
        # 8 + 10 + 7 = 25, capped
        self.assertEqual(_reach_score(1_000_000, 1_000_000, 5), 25)

    def test_all_zeros(self):
        # 0 + 1 + 0 = 1 (holders <10k → 1 pt)
        self.assertEqual(_reach_score(0, 0, 0), 1)

    def test_tx_1m(self):
        score = _reach_score(1_000_000, 0, 0)
        # 8 tx + 1 holder = 9
        self.assertEqual(score, 9)

    def test_tx_100k(self):
        score = _reach_score(100_000, 0, 0)
        self.assertEqual(score, 7)  # 6 + 1

    def test_tx_10k(self):
        score = _reach_score(10_000, 0, 0)
        self.assertEqual(score, 5)  # 4 + 1

    def test_tx_1k(self):
        score = _reach_score(1_000, 0, 0)
        self.assertEqual(score, 3)  # 2 + 1

    def test_tx_below_1k(self):
        score = _reach_score(999, 0, 0)
        self.assertEqual(score, 1)  # 0 + 1

    def test_holders_1m(self):
        score = _reach_score(0, 1_000_000, 0)
        self.assertEqual(score, 10)

    def test_holders_100k(self):
        score = _reach_score(0, 100_000, 0)
        self.assertEqual(score, 7)

    def test_holders_10k(self):
        score = _reach_score(0, 10_000, 0)
        self.assertEqual(score, 4)

    def test_holders_below_10k(self):
        score = _reach_score(0, 9_999, 0)
        self.assertEqual(score, 1)

    def test_chains_5_plus(self):
        score = _reach_score(0, 0, 5)
        # 0 tx + 1 holder + 7 chain = 8
        self.assertEqual(score, 8)

    def test_chains_3(self):
        score = _reach_score(0, 0, 3)
        self.assertEqual(score, 6)  # 0+1+5

    def test_chains_2(self):
        score = _reach_score(0, 0, 2)
        self.assertEqual(score, 4)  # 0+1+3

    def test_chains_1(self):
        score = _reach_score(0, 0, 1)
        self.assertEqual(score, 2)  # 0+1+1

    def test_chains_0(self):
        score = _reach_score(0, 0, 0)
        self.assertEqual(score, 1)  # 0+1+0

    def test_cap_at_25(self):
        score = _reach_score(10_000_000, 10_000_000, 100)
        self.assertLessEqual(score, 25)


# ---------------------------------------------------------------------------
# Tests: _network_strength
# ---------------------------------------------------------------------------

class TestNetworkStrength(unittest.TestCase):

    def test_dominant_exactly_80(self):
        self.assertEqual(_network_strength(80), "DOMINANT")

    def test_dominant_100(self):
        self.assertEqual(_network_strength(100), "DOMINANT")

    def test_strong_exactly_60(self):
        self.assertEqual(_network_strength(60), "STRONG")

    def test_strong_79(self):
        self.assertEqual(_network_strength(79), "STRONG")

    def test_established_exactly_40(self):
        self.assertEqual(_network_strength(40), "ESTABLISHED")

    def test_established_59(self):
        self.assertEqual(_network_strength(59), "ESTABLISHED")

    def test_growing_exactly_20(self):
        self.assertEqual(_network_strength(20), "GROWING")

    def test_growing_39(self):
        self.assertEqual(_network_strength(39), "GROWING")

    def test_niche_0(self):
        self.assertEqual(_network_strength(0), "NICHE")

    def test_niche_19(self):
        self.assertEqual(_network_strength(19), "NICHE")


# ---------------------------------------------------------------------------
# Tests: _moat_assessment
# ---------------------------------------------------------------------------

class TestMoatAssessment(unittest.TestCase):

    def test_deep_moat_score_80(self):
        moat = _moat_assessment(80, 50)
        self.assertIn("Deep moat", moat)

    def test_strong_network_score_60(self):
        moat = _moat_assessment(60, 30)
        self.assertIn("Strong network", moat)
        self.assertIn("30", moat)

    def test_established_score_40(self):
        moat = _moat_assessment(40, 10)
        self.assertIn("Established", moat)

    def test_early_effects_score_20(self):
        moat = _moat_assessment(20, 5)
        self.assertIn("Early network effects", moat)

    def test_limited_effects_score_0(self):
        moat = _moat_assessment(0, 0)
        self.assertIn("Limited", moat)

    def test_integrations_count_in_strong_string(self):
        moat = _moat_assessment(75, 42)
        self.assertIn("42", moat)


# ---------------------------------------------------------------------------
# Tests: analyze() integration
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_returns_correct_structure(self):
        result = analyze([])
        self.assertIsNone(result["dominant_protocol"])
        self.assertIsNone(result["fastest_growing"])
        self.assertIsNone(result["most_composable"])
        self.assertAlmostEqual(result["average_network_score"], 0.0)
        self.assertEqual(result["protocols"], [])

    def test_timestamp_present(self):
        result = analyze([])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSingle(unittest.TestCase):

    def setUp(self):
        self.proto = _proto(
            "Aave",
            monthly_active_users=150_000,
            user_growth_30d_pct=10.0,
            integrations_count=80,
            dependent_tvl_usd=2_000_000_000.0,
            own_tvl_usd=8_000_000_000.0,
            tx_count_30d=2_000_000,
            unique_token_holders=750_000,
            cross_chain_deployments=8,
        )
        self.result = analyze([self.proto])

    def test_dominant_protocol_is_only_one(self):
        self.assertEqual(self.result["dominant_protocol"], "Aave")

    def test_fastest_growing_is_only_one(self):
        self.assertEqual(self.result["fastest_growing"], "Aave")

    def test_most_composable_is_only_one(self):
        self.assertEqual(self.result["most_composable"], "Aave")

    def test_average_equals_single_score(self):
        p = self.result["protocols"][0]
        self.assertAlmostEqual(self.result["average_network_score"], p["network_score"])

    def test_position_keys_present(self):
        p = self.result["protocols"][0]
        for key in (
            "name",
            "network_score",
            "network_strength",
            "user_flywheel_score",
            "composability_score",
            "capital_efficiency_score",
            "reach_score",
            "moat_assessment",
        ):
            self.assertIn(key, p)

    def test_scores_are_ints(self):
        p = self.result["protocols"][0]
        for key in (
            "network_score",
            "user_flywheel_score",
            "composability_score",
            "capital_efficiency_score",
            "reach_score",
        ):
            self.assertIsInstance(p[key], int, msg=f"{key} should be int")

    def test_network_score_bounded(self):
        p = self.result["protocols"][0]
        self.assertGreaterEqual(p["network_score"], 0)
        self.assertLessEqual(p["network_score"], 100)


class TestAnalyzeMultiple(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            _proto("Giant", monthly_active_users=200_000, user_growth_30d_pct=40.0,
                   integrations_count=100, dependent_tvl_usd=5_000_000_000.0,
                   own_tvl_usd=1_000_000_000.0, tx_count_30d=5_000_000,
                   unique_token_holders=2_000_000, cross_chain_deployments=10),
            _proto("Small", monthly_active_users=500, user_growth_30d_pct=2.0,
                   integrations_count=2, dependent_tvl_usd=500_000.0,
                   own_tvl_usd=1_000_000.0, tx_count_30d=500,
                   unique_token_holders=1_000, cross_chain_deployments=1),
        ]
        self.result = analyze(self.protocols)

    def test_dominant_is_giant(self):
        self.assertEqual(self.result["dominant_protocol"], "Giant")

    def test_fastest_growing_is_giant(self):
        self.assertEqual(self.result["fastest_growing"], "Giant")

    def test_most_composable_is_giant(self):
        self.assertEqual(self.result["most_composable"], "Giant")

    def test_average_score_is_mean(self):
        scores = [p["network_score"] for p in self.result["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(self.result["average_network_score"], expected_avg)

    def test_giant_is_dominant_strength(self):
        p = self.result["protocols"][0]
        self.assertEqual(p["network_strength"], "DOMINANT")

    def test_small_is_niche_or_growing(self):
        p = self.result["protocols"][1]
        self.assertIn(p["network_strength"], ("NICHE", "GROWING"))

    def test_moat_assessment_non_empty(self):
        for p in self.result["protocols"]:
            self.assertIsInstance(p["moat_assessment"], str)
            self.assertGreater(len(p["moat_assessment"]), 0)


class TestAnalyzeFastest(unittest.TestCase):
    """Test fastest_growing picks the right protocol."""

    def test_fastest_growing_by_growth_rate(self):
        protocols = [
            _proto("Slow", user_growth_30d_pct=2.0),
            _proto("Fast", user_growth_30d_pct=55.0),
            _proto("Medium", user_growth_30d_pct=15.0),
        ]
        result = analyze(protocols)
        self.assertEqual(result["fastest_growing"], "Fast")

    def test_most_composable_by_integrations(self):
        protocols = [
            _proto("Few", integrations_count=5),
            _proto("Many", integrations_count=100),
            _proto("Mid", integrations_count=30),
        ]
        result = analyze(protocols)
        self.assertEqual(result["most_composable"], "Many")


class TestLogFunctions(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_log_creates_empty_file(self):
        init_log(data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "network_effect_log.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            data = json.load(fh)
        self.assertEqual(data, [])

    def test_init_log_no_overwrite(self):
        init_log(data_dir=self.tmpdir)
        analyze([_proto()], data_dir=self.tmpdir, save=True)
        init_log(data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_save_and_load(self):
        analyze([_proto()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_ring_buffer_cap(self):
        for _ in range(105):
            analyze([_proto()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertLessEqual(len(history), 100)

    def test_load_history_empty_no_file(self):
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(history, [])

    def test_save_false_no_write(self):
        analyze([_proto()], data_dir=self.tmpdir, save=False)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(history, [])

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            analyze([_proto()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 5)

    def test_ring_buffer_101_drops_oldest(self):
        for i in range(101):
            analyze(
                [_proto(f"P{i}", user_growth_30d_pct=float(i))],
                data_dir=self.tmpdir,
                save=True,
            )
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 100)
        last = history[-1]
        self.assertEqual(last["protocols"][0]["name"], "P100")


class TestNetworkScoreAdditivity(unittest.TestCase):
    """Score components add up correctly."""

    def test_all_zeros_protocol(self):
        result = analyze([_proto()])
        p = result["protocols"][0]
        # All zero inputs: growth=0 (4 pts) + 0 MAU (0) = 4 flywheel
        # 0 integrations + 0 dep_tvl = 0 composability
        # 0 capital eff
        # 0 tx + 0 holders (1 pt) + 0 chains = 1 reach
        # total = 4 + 0 + 0 + 1 = 5
        expected = (
            _user_flywheel_score(0, 0.0)
            + _composability_score(0, 0.0)
            + _capital_efficiency_score(0.0, 0.0)
            + _reach_score(0, 0, 0)
        )
        self.assertEqual(p["network_score"], min(100, expected))

    def test_sub_scores_sum_to_network_score(self):
        proto = _proto(
            monthly_active_users=50_000,
            user_growth_30d_pct=20.0,
            integrations_count=25,
            dependent_tvl_usd=200_000_000.0,
            own_tvl_usd=500_000_000.0,
            tx_count_30d=500_000,
            unique_token_holders=200_000,
            cross_chain_deployments=4,
        )
        result = analyze([proto])
        p = result["protocols"][0]
        expected = min(
            100,
            p["user_flywheel_score"]
            + p["composability_score"]
            + p["capital_efficiency_score"]
            + p["reach_score"],
        )
        self.assertEqual(p["network_score"], expected)

    def test_name_preserved(self):
        result = analyze([_proto("SpecialName")])
        self.assertEqual(result["protocols"][0]["name"], "SpecialName")

    def test_network_score_never_exceeds_100(self):
        # Max out all dimensions
        proto = _proto(
            monthly_active_users=1_000_000,
            user_growth_30d_pct=100.0,
            integrations_count=500,
            dependent_tvl_usd=100_000_000_000.0,
            own_tvl_usd=1_000_000.0,  # high utilization
            tx_count_30d=100_000_000,
            unique_token_holders=10_000_000,
            cross_chain_deployments=50,
        )
        result = analyze([proto])
        p = result["protocols"][0]
        self.assertLessEqual(p["network_score"], 100)

    def test_negative_growth_protocol_gets_zero_flywheel_growth(self):
        result = analyze([_proto(user_growth_30d_pct=-10.0, monthly_active_users=0)])
        p = result["protocols"][0]
        # negative growth + 0 MAU → 0 flywheel
        self.assertEqual(p["user_flywheel_score"], 0)


if __name__ == "__main__":
    unittest.main()

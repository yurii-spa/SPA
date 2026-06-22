"""
Tests for MP-640: AdapterHealthScorecard
Target: ≥60 tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure spa_core package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.adapter_health_scorecard import (
    MAX_ENTRIES,
    AdapterHealthScorecard,
    AdapterSignals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sc(tmp_dir: str) -> AdapterHealthScorecard:
    return AdapterHealthScorecard(data_file=Path(tmp_dir) / "scorecard.json")


def good_signals(adapter_id: str = "aave_v3", **kwargs) -> AdapterSignals:
    defaults = dict(
        adapter_id=adapter_id,
        apy=0.10,
        apy_7d_vol=0.001,
        liquidity_usd=8_000_000,
        protocol_risk_score=10.0,
        slippage_bps=5,
        is_depegged=False,
        days_live=90,
    )
    defaults.update(kwargs)
    return AdapterSignals(**defaults)


def bad_signals(adapter_id: str = "risky_v1", **kwargs) -> AdapterSignals:
    defaults = dict(
        adapter_id=adapter_id,
        apy=0.00,
        apy_7d_vol=0.05,
        liquidity_usd=0.0,
        protocol_risk_score=90.0,
        slippage_bps=60,
        is_depegged=True,
        days_live=1,
    )
    defaults.update(kwargs)
    return AdapterSignals(**defaults)


# ===========================================================================
# 1. _score_apy
# ===========================================================================

class TestScoreApy(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_zero_apy_returns_zero(self):
        self.assertEqual(self.sc._score_apy(0.0), 0.0)

    def test_8pct_apy(self):
        expected = 0.08 / 0.15 * 100
        self.assertAlmostEqual(self.sc._score_apy(0.08), expected, places=9)

    def test_15pct_apy_returns_100(self):
        self.assertEqual(self.sc._score_apy(0.15), 100.0)

    def test_above_15pct_clamped_at_100(self):
        self.assertEqual(self.sc._score_apy(0.20), 100.0)
        self.assertEqual(self.sc._score_apy(0.50), 100.0)

    def test_small_apy_positive_score(self):
        self.assertGreater(self.sc._score_apy(0.03), 0.0)

    def test_negative_apy_clamped_at_zero(self):
        self.assertEqual(self.sc._score_apy(-0.05), 0.0)

    def test_10pct_apy_about_67(self):
        self.assertAlmostEqual(self.sc._score_apy(0.10), 66.666, delta=0.01)


# ===========================================================================
# 2. _score_stability
# ===========================================================================

class TestScoreStability(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_zero_vol_returns_100(self):
        self.assertEqual(self.sc._score_stability(0.0), 100.0)

    def test_5pct_vol_returns_zero(self):
        self.assertEqual(self.sc._score_stability(0.05), 0.0)

    def test_2_5pct_vol_returns_50(self):
        self.assertAlmostEqual(self.sc._score_stability(0.025), 50.0, places=9)

    def test_above_5pct_vol_clamped_at_zero(self):
        self.assertEqual(self.sc._score_stability(0.1), 0.0)

    def test_small_vol_high_score(self):
        self.assertGreater(self.sc._score_stability(0.001), 95.0)

    def test_1pct_vol_is_80(self):
        # (1 - 0.01/0.05)*100 = 80
        self.assertAlmostEqual(self.sc._score_stability(0.01), 80.0, places=9)


# ===========================================================================
# 3. _score_liquidity
# ===========================================================================

class TestScoreLiquidity(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_zero_liquidity_returns_zero(self):
        self.assertEqual(self.sc._score_liquidity(0.0), 0.0)

    def test_5m_liquidity_returns_50(self):
        self.assertAlmostEqual(self.sc._score_liquidity(5_000_000), 50.0, places=9)

    def test_10m_liquidity_returns_100(self):
        self.assertEqual(self.sc._score_liquidity(10_000_000), 100.0)

    def test_above_10m_clamped_at_100(self):
        self.assertEqual(self.sc._score_liquidity(50_000_000), 100.0)

    def test_small_liquidity_small_score(self):
        self.assertLess(self.sc._score_liquidity(100_000), 5.0)

    def test_negative_liquidity_clamped_at_zero(self):
        self.assertEqual(self.sc._score_liquidity(-1_000), 0.0)


# ===========================================================================
# 4. _score_safety
# ===========================================================================

class TestScoreSafety(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_risk_zero_returns_100(self):
        self.assertEqual(self.sc._score_safety(0.0), 100.0)

    def test_risk_100_returns_zero(self):
        self.assertEqual(self.sc._score_safety(100.0), 0.0)

    def test_risk_50_returns_50(self):
        self.assertAlmostEqual(self.sc._score_safety(50.0), 50.0, places=9)

    def test_risk_above_100_clamped_at_zero(self):
        self.assertEqual(self.sc._score_safety(120.0), 0.0)

    def test_risk_negative_clamped_at_100(self):
        self.assertEqual(self.sc._score_safety(-10.0), 100.0)

    def test_risk_25_returns_75(self):
        self.assertAlmostEqual(self.sc._score_safety(25.0), 75.0, places=9)


# ===========================================================================
# 5. _score_slippage
# ===========================================================================

class TestScoreSlippage(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_zero_bps_returns_100(self):
        self.assertEqual(self.sc._score_slippage(0.0), 100.0)

    def test_25_bps_returns_50(self):
        self.assertAlmostEqual(self.sc._score_slippage(25.0), 50.0, places=9)

    def test_50_bps_returns_zero(self):
        self.assertEqual(self.sc._score_slippage(50.0), 0.0)

    def test_above_50_bps_clamped_at_zero(self):
        self.assertEqual(self.sc._score_slippage(100.0), 0.0)

    def test_negative_bps_clamped_at_100(self):
        self.assertEqual(self.sc._score_slippage(-5.0), 100.0)

    def test_10_bps_is_80(self):
        # (1 - 10/50)*100 = 80
        self.assertAlmostEqual(self.sc._score_slippage(10.0), 80.0, places=9)


# ===========================================================================
# 6. _grade
# ===========================================================================

class TestGrade(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_100_is_A(self):
        self.assertEqual(self.sc._grade(100.0), "A")

    def test_80_is_A(self):
        self.assertEqual(self.sc._grade(80.0), "A")

    def test_79_is_B(self):
        self.assertEqual(self.sc._grade(79.9), "B")

    def test_60_is_B(self):
        self.assertEqual(self.sc._grade(60.0), "B")

    def test_59_is_C(self):
        self.assertEqual(self.sc._grade(59.9), "C")

    def test_40_is_C(self):
        self.assertEqual(self.sc._grade(40.0), "C")

    def test_39_is_D(self):
        self.assertEqual(self.sc._grade(39.9), "D")

    def test_zero_is_D(self):
        self.assertEqual(self.sc._grade(0.0), "D")


# ===========================================================================
# 7. _recommendation
# ===========================================================================

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_depegged_gives_exit(self):
        self.assertEqual(self.sc._recommendation("A", ["DEPEGGED"]), "EXIT")

    def test_grade_D_gives_exit(self):
        self.assertEqual(self.sc._recommendation("D", []), "EXIT")

    def test_grade_D_with_flags_gives_exit(self):
        self.assertEqual(self.sc._recommendation("D", ["LOW_LIQUIDITY"]), "EXIT")

    def test_grade_C_gives_reduce(self):
        self.assertEqual(self.sc._recommendation("C", []), "REDUCE")

    def test_two_flags_gives_reduce(self):
        self.assertEqual(
            self.sc._recommendation("B", ["LOW_LIQUIDITY", "HIGH_VOLATILITY"]),
            "REDUCE",
        )

    def test_grade_B_gives_watch(self):
        self.assertEqual(self.sc._recommendation("B", []), "WATCH")

    def test_one_flag_gives_watch(self):
        self.assertEqual(self.sc._recommendation("A", ["HIGH_SLIPPAGE"]), "WATCH")

    def test_grade_A_no_flags_gives_hold(self):
        self.assertEqual(self.sc._recommendation("A", []), "HOLD")


# ===========================================================================
# 8. Flag detection
# ===========================================================================

class TestFlagDetection(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_depegged_flag(self):
        score = self.sc.score_adapter(good_signals(is_depegged=True))
        self.assertIn("DEPEGGED", score.flags)

    def test_low_liquidity_flag(self):
        score = self.sc.score_adapter(good_signals(liquidity_usd=100_000))
        self.assertIn("LOW_LIQUIDITY", score.flags)

    def test_high_risk_protocol_flag(self):
        score = self.sc.score_adapter(good_signals(protocol_risk_score=70.0))
        self.assertIn("HIGH_RISK_PROTOCOL", score.flags)

    def test_high_volatility_flag(self):
        score = self.sc.score_adapter(good_signals(apy_7d_vol=0.03))
        self.assertIn("HIGH_VOLATILITY", score.flags)

    def test_high_slippage_flag(self):
        score = self.sc.score_adapter(good_signals(slippage_bps=35))
        self.assertIn("HIGH_SLIPPAGE", score.flags)

    def test_no_flags_for_good_adapter(self):
        score = self.sc.score_adapter(good_signals())
        self.assertEqual(score.flags, [])

    def test_all_flags_for_bad_adapter(self):
        score = self.sc.score_adapter(bad_signals())
        self.assertIn("DEPEGGED", score.flags)
        self.assertIn("LOW_LIQUIDITY", score.flags)
        self.assertIn("HIGH_RISK_PROTOCOL", score.flags)
        self.assertIn("HIGH_VOLATILITY", score.flags)
        self.assertIn("HIGH_SLIPPAGE", score.flags)


# ===========================================================================
# 9. score_adapter: good vs bad
# ===========================================================================

class TestScoreAdapter(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_good_adapter_grade_A(self):
        self.assertEqual(self.sc.score_adapter(good_signals()).grade, "A")

    def test_good_adapter_recommendation_hold(self):
        self.assertEqual(self.sc.score_adapter(good_signals()).recommendation, "HOLD")

    def test_bad_adapter_grade_D(self):
        self.assertEqual(self.sc.score_adapter(bad_signals()).grade, "D")

    def test_bad_adapter_recommendation_exit(self):
        self.assertEqual(self.sc.score_adapter(bad_signals()).recommendation, "EXIT")

    def test_adapter_id_preserved(self):
        score = self.sc.score_adapter(good_signals(adapter_id="morpho_v3"))
        self.assertEqual(score.adapter_id, "morpho_v3")

    def test_timestamp_recent(self):
        score = self.sc.score_adapter(good_signals())
        self.assertAlmostEqual(score.timestamp, time.time(), delta=5)

    def test_component_scores_in_range(self):
        score = self.sc.score_adapter(good_signals())
        for v in (score.apy_score, score.stability_score, score.liquidity_score,
                  score.safety_score, score.slippage_score):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)

    def test_composite_in_range_good(self):
        score = self.sc.score_adapter(good_signals())
        self.assertGreaterEqual(score.composite_score, 0.0)
        self.assertLessEqual(score.composite_score, 100.0)

    def test_composite_in_range_bad(self):
        score = self.sc.score_adapter(bad_signals())
        self.assertGreaterEqual(score.composite_score, 0.0)
        self.assertLessEqual(score.composite_score, 100.0)

    def test_perfect_adapter_composite_100(self):
        sig = good_signals(apy=0.15, apy_7d_vol=0.0, liquidity_usd=10_000_000,
                           protocol_risk_score=0.0, slippage_bps=0.0)
        score = self.sc.score_adapter(sig)
        self.assertAlmostEqual(score.composite_score, 100.0, delta=0.1)


# ===========================================================================
# 10. score_all — sorted descending
# ===========================================================================

class TestScoreAll(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_sorted_descending(self):
        adapters = [
            good_signals("aave",   apy=0.05),
            good_signals("morpho", apy=0.12),
            bad_signals("risky"),
        ]
        scores = self.sc.score_all(adapters)
        composites = [s.composite_score for s in scores]
        self.assertEqual(composites, sorted(composites, reverse=True))

    def test_returns_all_adapters(self):
        adapters = [good_signals(f"adapter_{i}") for i in range(5)]
        self.assertEqual(len(self.sc.score_all(adapters)), 5)

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.sc.score_all([]), [])


# ===========================================================================
# 11. save_scores and persistence
# ===========================================================================

class TestSaveScores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_sc(self.tmp)

    def test_save_creates_file(self):
        self.sc.save_scores(self.sc.score_all([good_signals()]))
        self.assertTrue((Path(self.tmp) / "scorecard.json").exists())

    def test_save_valid_json(self):
        self.sc.save_scores(self.sc.score_all([good_signals()]))
        data = json.loads((Path(self.tmp) / "scorecard.json").read_text())
        self.assertIsInstance(data, list)

    def test_save_appends(self):
        self.sc.save_scores(self.sc.score_all([good_signals()]))
        self.sc.save_scores(self.sc.score_all([good_signals()]))
        data = json.loads((Path(self.tmp) / "scorecard.json").read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_caps_at_max_entries(self):
        for _ in range(MAX_ENTRIES + 5):
            self.sc.save_scores(self.sc.score_all([good_signals()]))
        data = json.loads((Path(self.tmp) / "scorecard.json").read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left(self):
        self.sc.save_scores(self.sc.score_all([good_signals()]))
        self.assertFalse((Path(self.tmp) / "scorecard.tmp").exists())

    def test_saved_entry_has_scores_list(self):
        self.sc.save_scores(self.sc.score_all([good_signals("a"), good_signals("b")]))
        data = json.loads((Path(self.tmp) / "scorecard.json").read_text())
        self.assertEqual(len(data[0]["scores"]), 2)

    def test_saved_entry_has_components(self):
        self.sc.save_scores(self.sc.score_all([good_signals()]))
        data = json.loads((Path(self.tmp) / "scorecard.json").read_text())
        components = data[0]["scores"][0]["components"]
        for key in ("apy", "stability", "liquidity", "safety", "slippage"):
            self.assertIn(key, components)


# ===========================================================================
# 12. load_history
# ===========================================================================

class TestLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_missing_file_returns_empty_list(self):
        sc = make_sc(self.tmp)
        self.assertEqual(sc.load_history(), [])

    def test_corrupt_file_returns_empty_list(self):
        f = Path(self.tmp) / "scorecard.json"
        f.write_text("{{not json}}")
        sc = AdapterHealthScorecard(data_file=f)
        self.assertEqual(sc.load_history(), [])

    def test_load_returns_saved_data(self):
        sc = make_sc(self.tmp)
        sc.save_scores(sc.score_all([good_signals()]))
        history = sc.load_history()
        self.assertEqual(len(history), 1)
        self.assertIn("scores", history[0])


# ===========================================================================
# 13. get_top_adapters and get_exit_candidates
# ===========================================================================

class TestFilterHelpers(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def test_get_top_5(self):
        adapters = [good_signals(f"a{i}", apy=0.01 * i) for i in range(10)]
        scores = self.sc.score_all(adapters)
        self.assertEqual(len(self.sc.get_top_adapters(scores, n=5)), 5)

    def test_get_top_more_than_available(self):
        adapters = [good_signals(f"a{i}") for i in range(3)]
        scores = self.sc.score_all(adapters)
        self.assertEqual(len(self.sc.get_top_adapters(scores, n=10)), 3)

    def test_get_exit_empty_when_all_good(self):
        adapters = [good_signals(f"a{i}") for i in range(5)]
        scores = self.sc.score_all(adapters)
        self.assertEqual(self.sc.get_exit_candidates(scores), [])

    def test_get_exit_returns_bad_adapters(self):
        adapters = [good_signals("a"), bad_signals("b"), bad_signals("c")]
        scores = self.sc.score_all(adapters)
        exits = [e.adapter_id for e in self.sc.get_exit_candidates(scores)]
        self.assertIn("b", exits)
        self.assertIn("c", exits)
        self.assertNotIn("a", exits)


# ===========================================================================
# 14. Full scenario: 5 adapters
# ===========================================================================

class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.sc = make_sc(tempfile.mkdtemp())

    def _five_adapters(self):
        return [
            AdapterSignals("aave_v3",     0.035, 0.001,  9_000_000, 5.0,  3,  False, 180),
            AdapterSignals("compound_v3", 0.048, 0.002,  7_000_000, 10.0, 5,  False, 120),
            AdapterSignals("morpho_steak",0.065, 0.003,  5_000_000, 15.0, 8,  False,  60),
            AdapterSignals("maple",       0.09,  0.015,  1_000_000, 55.0, 15, False,  30),
            AdapterSignals("risky_pool",  0.01,  0.04,     200_000, 80.0, 40, True,    5),
        ]

    def test_all_scored(self):
        self.assertEqual(len(self.sc.score_all(self._five_adapters())), 5)

    def test_ranking_descending(self):
        scores = self.sc.score_all(self._five_adapters())
        composites = [s.composite_score for s in scores]
        self.assertEqual(composites, sorted(composites, reverse=True))

    def test_risky_pool_gets_exit(self):
        scores = self.sc.score_all(self._five_adapters())
        risky = next(s for s in scores if s.adapter_id == "risky_pool")
        self.assertEqual(risky.recommendation, "EXIT")

    def test_aave_not_exit(self):
        scores = self.sc.score_all(self._five_adapters())
        aave = next(s for s in scores if s.adapter_id == "aave_v3")
        self.assertNotEqual(aave.recommendation, "EXIT")

    def test_save_and_load_roundtrip(self):
        scores = self.sc.score_all(self._five_adapters())
        self.sc.save_scores(scores)
        history = self.sc.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(len(history[0]["scores"]), 5)

    def test_exit_candidates_include_risky(self):
        scores = self.sc.score_all(self._five_adapters())
        exits = [e.adapter_id for e in self.sc.get_exit_candidates(scores)]
        self.assertIn("risky_pool", exits)

    def test_top_3_are_highest_scored(self):
        scores = self.sc.score_all(self._five_adapters())
        top3 = self.sc.get_top_adapters(scores, n=3)
        self.assertEqual(len(top3), 3)
        fourth_score = scores[3].composite_score
        for s in top3:
            self.assertGreaterEqual(s.composite_score, fourth_score)


if __name__ == "__main__":
    unittest.main()

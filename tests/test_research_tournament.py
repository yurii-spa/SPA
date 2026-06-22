"""
tests/test_research_tournament.py

40 unit tests for spa_core/backtesting/research_tournament.py

Coverage:
  TestRunStructure        (8 tests)  — run() dict shape, keys, types
  TestResearchTrack       (9 tests)  — 2-entry track, per-field values
  TestMetrics             (8 tests)  — rs001_metrics / rs002_metrics
  TestRanking             (6 tests)  — rank_research_strategies() ordering
  TestRecommendation      (5 tests)  — recommendation() logic
  TestGapToLive           (2 tests)  — gap_to_live > 0, is float
  TestSave                (2 tests)  — atomic save, valid JSON

Sprint v9.43 — MP-1327
Date: 2026-06-19
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.backtesting.research_tournament import (
    ResearchTournament,
)


def _fresh() -> ResearchTournament:
    return ResearchTournament()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestRunStructure (8 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunStructure(unittest.TestCase):

    def test_run_returns_dict(self):
        rt = _fresh()
        result = rt.run()
        self.assertIsInstance(result, dict)

    def test_run_has_research_track_key(self):
        result = _fresh().run()
        self.assertIn("research_track", result)

    def test_run_has_production_leader_key(self):
        result = _fresh().run()
        self.assertIn("production_leader", result)

    def test_run_has_research_leader_key(self):
        result = _fresh().run()
        self.assertIn("research_leader", result)

    def test_run_has_gap_to_live_key(self):
        result = _fresh().run()
        self.assertIn("gap_to_live", result)

    def test_run_has_blockers_summary_key(self):
        result = _fresh().run()
        self.assertIn("blockers_summary", result)

    def test_run_has_timestamp_key(self):
        result = _fresh().run()
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], str)
        self.assertTrue(len(result["timestamp"]) > 0)

    def test_run_is_idempotent_structure(self):
        rt = _fresh()
        r1 = rt.run()
        r2 = rt.run()
        self.assertEqual(set(r1.keys()), set(r2.keys()))
        self.assertEqual(len(r1["research_track"]), len(r2["research_track"]))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestResearchTrack (9 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearchTrack(unittest.TestCase):

    def setUp(self):
        self.track = _fresh().run()["research_track"]

    def test_research_track_has_two_entries(self):
        self.assertEqual(len(self.track), 2)

    def test_research_track_contains_s20(self):
        ids = [e["strategy_id"] for e in self.track]
        self.assertIn("S20", ids)

    def test_research_track_contains_s21(self):
        ids = [e["strategy_id"] for e in self.track]
        self.assertIn("S21", ids)

    def test_s20_is_research_true(self):
        s20 = next(e for e in self.track if e["strategy_id"] == "S20")
        self.assertTrue(s20["is_research"])

    def test_s21_is_research_true(self):
        s21 = next(e for e in self.track if e["strategy_id"] == "S21")
        self.assertTrue(s21["is_research"])

    def test_s20_target_apy(self):
        s20 = next(e for e in self.track if e["strategy_id"] == "S20")
        self.assertAlmostEqual(s20["target_apy"], 18.2, places=2)

    def test_s21_target_apy_gross(self):
        s21 = next(e for e in self.track if e["strategy_id"] == "S21")
        self.assertAlmostEqual(s21["target_apy"], 29.24, places=2)

    def test_all_entries_have_required_keys(self):
        required = {
            "strategy_id", "is_research", "target_apy", "estimated_net_apy",
            "strict_eligible_fraction", "research_exclusion_count",
            "risk_classification", "rank_in_research_track",
            "vs_production_leader", "recommendation",
        }
        for entry in self.track:
            self.assertTrue(
                required.issubset(entry.keys()),
                msg=f"{entry['strategy_id']} missing keys: {required - entry.keys()}",
            )

    def test_strict_eligible_fraction_in_valid_range(self):
        for entry in self.track:
            frac = entry["strict_eligible_fraction"]
            self.assertGreaterEqual(frac, 0.0)
            self.assertLessEqual(frac, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestMetrics (8 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetrics(unittest.TestCase):

    def test_rs001_metrics_strategy_id(self):
        m = _fresh().rs001_metrics()
        self.assertEqual(m["strategy_id"], "S20")

    def test_rs002_metrics_strategy_id(self):
        m = _fresh().rs002_metrics()
        self.assertEqual(m["strategy_id"], "S21")

    def test_rs001_strict_eligible_fraction(self):
        m = _fresh().rs001_metrics()
        self.assertAlmostEqual(m["strict_eligible_fraction"], 0.15, places=4)

    def test_rs002_strict_eligible_fraction(self):
        m = _fresh().rs002_metrics()
        self.assertAlmostEqual(m["strict_eligible_fraction"], 0.16, places=4)

    def test_rs001_exclusion_count(self):
        m = _fresh().rs001_metrics()
        # 5 excluded slots: gmx_btc, gmx_eth, btc_stable, eth_aggressive, gold_proxy
        self.assertEqual(m["research_exclusion_count"], 5)

    def test_rs002_exclusion_count(self):
        m = _fresh().rs002_metrics()
        # 3 excluded slots: btc_usd_conc_liq, rwa_conc_liq, trader_losses_vault
        self.assertEqual(m["research_exclusion_count"], 3)

    def test_rs001_estimated_net_apy_positive(self):
        m = _fresh().rs001_metrics()
        self.assertGreater(m["estimated_net_apy"], 0.0)

    def test_rs002_estimated_net_apy_positive(self):
        m = _fresh().rs002_metrics()
        self.assertGreater(m["estimated_net_apy"], 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestRanking (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRanking(unittest.TestCase):

    def setUp(self):
        self.ranked = _fresh().rank_research_strategies()

    def test_rank_returns_two_entries(self):
        self.assertEqual(len(self.ranked), 2)

    def test_rank_1_has_correct_value(self):
        self.assertEqual(self.ranked[0]["rank_in_research_track"], 1)

    def test_rank_2_has_correct_value(self):
        self.assertEqual(self.ranked[1]["rank_in_research_track"], 2)

    def test_ranks_are_unique(self):
        ranks = [e["rank_in_research_track"] for e in self.ranked]
        self.assertEqual(len(set(ranks)), len(ranks))

    def test_sorted_by_estimated_net_apy_descending(self):
        apys = [e["estimated_net_apy"] for e in self.ranked]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_s20_ranks_above_s21(self):
        # RS-001 net APY = 18.2 > RS-002 net APY = 15.0 → S20 rank 1
        s20 = next(e for e in self.ranked if e["strategy_id"] == "S20")
        s21 = next(e for e in self.ranked if e["strategy_id"] == "S21")
        self.assertLess(s20["rank_in_research_track"], s21["rank_in_research_track"])


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestRecommendation (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendation(unittest.TestCase):

    VALID_RECS = {"CONTINUE_RESEARCH", "READY_FOR_PAPER", "REDESIGN"}

    def test_s20_recommendation_is_valid(self):
        rec = _fresh().recommendation("S20")
        self.assertIn(rec, self.VALID_RECS)

    def test_s21_recommendation_is_valid(self):
        rec = _fresh().recommendation("S21")
        self.assertIn(rec, self.VALID_RECS)

    def test_s20_recommendation_is_continue_research(self):
        # eligible fraction 0.15 < 0.5 → CONTINUE_RESEARCH
        rec = _fresh().recommendation("S20")
        self.assertEqual(rec, "CONTINUE_RESEARCH")

    def test_s21_recommendation_is_continue_research(self):
        # eligible fraction 0.16 < 0.5 → CONTINUE_RESEARCH
        rec = _fresh().recommendation("S21")
        self.assertEqual(rec, "CONTINUE_RESEARCH")

    def test_unknown_strategy_returns_continue_research(self):
        rec = _fresh().recommendation("S99")
        self.assertEqual(rec, "CONTINUE_RESEARCH")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestGapToLive (2 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGapToLive(unittest.TestCase):

    def test_gap_to_live_positive(self):
        result = _fresh().run()
        self.assertGreater(result["gap_to_live"], 0.0)

    def test_gap_to_live_is_float(self):
        result = _fresh().run()
        self.assertIsInstance(result["gap_to_live"], float)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TestSave (2 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSave(unittest.TestCase):

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir", "tournament_results.json")
            _fresh().save(path)
            self.assertTrue(os.path.exists(path))

    def test_save_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "results.json")
            _fresh().save(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("research_track", data)
            self.assertIn("gap_to_live", data)
            self.assertEqual(len(data["research_track"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

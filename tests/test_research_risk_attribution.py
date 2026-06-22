"""
tests/test_research_risk_attribution.py

40 unit tests for spa_core.analytics.research_risk_attribution.
MP-1311, Sprint v9.27.

Coverage:
  - SlotRiskProfile construction and methods
  - ResearchRiskAttribution.rs001_attribution()
  - ResearchRiskAttribution.rs002_attribution()
  - ResearchRiskAttribution.portfolio_risk_score()
  - ResearchRiskAttribution.risk_vs_return()
  - ResearchRiskAttribution.save_report() (atomic write)
  - Edge cases and invariants
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.analytics.research_risk_attribution import (
    RISK_FACTORS,
    RS001_EXPECTED_RETURN,
    ResearchRiskAttribution,
    SlotRiskProfile,
)


# ─── SlotRiskProfile Tests ────────────────────────────────────────────────────

class TestSlotRiskProfileConstruction(unittest.TestCase):

    def _make_scores(self, val: int = 5) -> dict:
        return {f: val for f in RISK_FACTORS}

    def test_01_construction_valid(self):
        p = SlotRiskProfile("test_slot", 0.5, self._make_scores(5))
        self.assertEqual(p.slot_id, "test_slot")
        self.assertAlmostEqual(p.weight, 0.5)

    def test_02_construction_zero_weight(self):
        p = SlotRiskProfile("slot", 0.0, self._make_scores(3))
        self.assertEqual(p.weight, 0.0)

    def test_03_construction_full_weight(self):
        p = SlotRiskProfile("slot", 1.0, self._make_scores(7))
        self.assertEqual(p.weight, 1.0)

    def test_04_invalid_weight_raises(self):
        with self.assertRaises(ValueError):
            SlotRiskProfile("slot", 1.1, self._make_scores(5))

    def test_05_invalid_weight_negative_raises(self):
        with self.assertRaises(ValueError):
            SlotRiskProfile("slot", -0.1, self._make_scores(5))

    def test_06_invalid_score_raises(self):
        scores = self._make_scores(5)
        scores["market_risk"] = 11
        with self.assertRaises(ValueError):
            SlotRiskProfile("slot", 0.5, scores)

    def test_07_scores_stored_as_float(self):
        p = SlotRiskProfile("slot", 0.3, self._make_scores(3))
        for f in RISK_FACTORS:
            self.assertIsInstance(p.scores[f], float)


class TestSlotRiskProfileMethods(unittest.TestCase):

    def setUp(self):
        # Uniform scores → total_risk_score = 5.0
        self.uniform = SlotRiskProfile("uniform", 0.5, {f: 5 for f in RISK_FACTORS})
        # stablecoin_t1 profile
        self.stable = SlotRiskProfile("stablecoin_t1", 0.15, {
            "market_risk": 1, "liquidity_risk": 1, "counterparty_risk": 3,
            "smart_contract_risk": 2, "il_risk": 0, "source_risk": 2,
        })
        # btc_usd_conc_liq profile (il_risk=9, source_risk=10)
        self.btc_conc = SlotRiskProfile("btc_usd_conc_liq", 0.60, {
            "market_risk": 7, "liquidity_risk": 4, "counterparty_risk": 5,
            "smart_contract_risk": 5, "il_risk": 9, "source_risk": 10,
        })

    def test_08_total_risk_score_uniform(self):
        self.assertAlmostEqual(self.uniform.total_risk_score(), 5.0, places=4)

    def test_09_total_risk_score_in_range(self):
        score = self.stable.total_risk_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 10.0)

    def test_10_total_risk_score_is_mean(self):
        scores = self.stable.scores
        expected = sum(scores.values()) / len(scores)
        self.assertAlmostEqual(self.stable.total_risk_score(), expected, places=6)

    def test_11_highest_risk_factor_stablecoin_not_source(self):
        # stablecoin_t1 has source_risk=2; highest should NOT be source_risk
        hrf = self.stable.highest_risk_factor()
        self.assertNotEqual(hrf, "source_risk")

    def test_12_highest_risk_factor_stablecoin_is_counterparty(self):
        # stablecoin_t1: market=1, liq=1, cpty=3, sc=2, il=0, src=2 → cpty=3 is highest
        self.assertEqual(self.stable.highest_risk_factor(), "counterparty_risk")

    def test_13_highest_risk_factor_btc_conc_il_or_source(self):
        hrf = self.btc_conc.highest_risk_factor()
        self.assertIn(hrf, ("il_risk", "source_risk"))

    def test_14_highest_risk_factor_btc_conc_source_wins(self):
        # source_risk=10 is strictly higher than il_risk=9
        self.assertEqual(self.btc_conc.highest_risk_factor(), "source_risk")

    def test_15_weighted_contribution(self):
        contrib = self.stable.weighted_contribution("counterparty_risk")
        self.assertAlmostEqual(contrib, 0.15 * 3.0, places=6)

    def test_16_to_dict_has_required_keys(self):
        d = self.stable.to_dict()
        for key in ("slot_id", "weight", "scores", "total_risk_score", "highest_risk_factor"):
            self.assertIn(key, d)

    def test_17_to_dict_slot_id_correct(self):
        self.assertEqual(self.stable.to_dict()["slot_id"], "stablecoin_t1")


# ─── ResearchRiskAttribution Tests ───────────────────────────────────────────

class TestRS001Attribution(unittest.TestCase):

    def setUp(self):
        self.attr = ResearchRiskAttribution()
        self.result = self.attr.rs001_attribution()

    def test_18_rs001_contains_all_slots(self):
        slot_ids = {s["slot_id"] for s in self.result["slots"]}
        expected = set(ResearchRiskAttribution.RS001_PROFILES.keys())
        self.assertEqual(slot_ids, expected)

    def test_19_rs001_has_6_slots(self):
        self.assertEqual(len(self.result["slots"]), 6)

    def test_20_rs001_strategy_name(self):
        self.assertEqual(self.result["strategy"], "RS001")

    def test_21_rs001_factor_scores_all_factors_present(self):
        for factor in RISK_FACTORS:
            self.assertIn(factor, self.result["factor_scores"])

    def test_22_rs001_portfolio_risk_in_range(self):
        score = self.result["portfolio_total_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 10.0)

    def test_23_rs001_dominant_factor_is_string(self):
        self.assertIsInstance(self.result["dominant_factor"], str)

    def test_24_rs001_dominant_factor_in_risk_factors(self):
        self.assertIn(self.result["dominant_factor"], RISK_FACTORS)

    def test_25_rs001_highest_risk_slot_is_valid(self):
        self.assertIn(
            self.result["highest_risk_slot"],
            list(ResearchRiskAttribution.RS001_PROFILES.keys()),
        )

    def test_26_rs001_expected_return(self):
        self.assertAlmostEqual(
            self.result["expected_return_pct"], RS001_EXPECTED_RETURN, places=4
        )


class TestRS002Attribution(unittest.TestCase):

    def setUp(self):
        self.attr = ResearchRiskAttribution()
        self.result = self.attr.rs002_attribution()

    def test_27_rs002_contains_all_slots(self):
        slot_ids = {s["slot_id"] for s in self.result["slots"]}
        expected = set(ResearchRiskAttribution.RS002_PROFILES.keys())
        self.assertEqual(slot_ids, expected)

    def test_28_rs002_has_4_slots(self):
        self.assertEqual(len(self.result["slots"]), 4)

    def test_29_rs002_portfolio_risk_in_range(self):
        score = self.result["portfolio_total_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 10.0)


class TestPortfolioRiskScore(unittest.TestCase):

    def setUp(self):
        self.attr = ResearchRiskAttribution()

    def test_30_rs001_score_in_range(self):
        score = self.attr.portfolio_risk_score("RS001")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 10.0)

    def test_31_rs002_score_in_range(self):
        score = self.attr.portfolio_risk_score("RS002")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 10.0)

    def test_32_rs002_riskier_than_rs001(self):
        # RS-002 is more aggressive (concentrated LP) → should have higher risk
        score1 = self.attr.portfolio_risk_score("RS001")
        score2 = self.attr.portfolio_risk_score("RS002")
        self.assertGreater(score2, score1)

    def test_33_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            self.attr.portfolio_risk_score("RS999")

    def test_34_case_insensitive_rs001(self):
        # "rs001" should equal "RS001"
        self.assertAlmostEqual(
            self.attr.portfolio_risk_score("rs001"),
            self.attr.portfolio_risk_score("RS001"),
            places=6,
        )


class TestRiskVsReturn(unittest.TestCase):

    def setUp(self):
        self.attr = ResearchRiskAttribution()
        self.rvr = self.attr.risk_vs_return()

    def test_35_contains_rs001_and_rs002(self):
        self.assertIn("RS001", self.rvr)
        self.assertIn("RS002", self.rvr)

    def test_36_rs001_has_required_keys(self):
        for key in ("risk_score", "expected_return_pct", "risk_return_ratio", "verdict"):
            self.assertIn(key, self.rvr["RS001"])

    def test_37_rs002_has_required_keys(self):
        for key in ("risk_score", "expected_return_pct", "risk_return_ratio", "verdict"):
            self.assertIn(key, self.rvr["RS002"])

    def test_38_verdict_is_valid(self):
        valid_verdicts = {"efficient", "moderate", "risk_heavy", "unknown"}
        self.assertIn(self.rvr["RS001"]["verdict"], valid_verdicts)
        self.assertIn(self.rvr["RS002"]["verdict"], valid_verdicts)


class TestSaveReport(unittest.TestCase):

    def setUp(self):
        self.attr = ResearchRiskAttribution()

    def test_39_save_report_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "research", "risk_attribution.json")
            self.attr.save_report(out)

            self.assertTrue(os.path.exists(out))
            with open(out, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            self.assertIn("rs001", data)
            self.assertIn("rs002", data)
            self.assertIn("risk_vs_return", data)
            self.assertIn("generated_at", data)

    def test_40_save_report_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deep = os.path.join(tmpdir, "a", "b", "c", "report.json")
            self.attr.save_report(deep)
            self.assertTrue(os.path.exists(deep))


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""tests/test_s46_s50.py — S46–S50 income-generation strategy batch.

The five income-focused tournament strategies (2026-06-21):

  S46 Stable-Only Safe Harbor   — 100% T1, no T2 ever, lowest risk (~3.8%)
  S47 Monthly Income Optimizer  — predictability-weighted T1, ~3.9% (~$322/mo)
  S48 Utilization-Aware         — Aave-APY regime proxy, adaptive 4.2–4.8%
  S49 Diversified Maximum       — 7 venues, no single >20%, ~4.4%
  S50 Tournament Champion       — meta: copies the current leader's weights

Determinism: APY math is verified against the canonical fallback table by
clearing each strategy's `_adapters` in setUp, so tests never touch the
network and never depend on live DeFiLlama readings.

Coverage (40 tests, 8 per strategy):
  S46  T01–T08    S47  T09–T16    S48  T17–T24
  S49  T25–T32    S50  T33–T40
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategies.s46_safe_harbor import SafeHarborStrategy, WEIGHTS as S46_W
from spa_core.strategies.s47_monthly_income import MonthlyIncomeStrategy, WEIGHTS as S47_W
from spa_core.strategies.s48_utilization_aware import (
    UtilizationAwareStrategy,
    WEIGHTS_HIGH, WEIGHTS_MEDIUM, WEIGHTS_LOW,
)
from spa_core.strategies.s49_diversified_max import DiversifiedMaxStrategy, WEIGHTS as S49_W
from spa_core.strategies.s50_tournament_champion import (
    TournamentChampionStrategy,
    S0_FALLBACK_WEIGHTS,
)
from spa_core.strategies.strategy_registry import REGISTRY
from spa_core.strategies._income_common import PROTOCOL_TIER, normalize_apy

CAPITAL = 100_000.0


# ════════════════════════════════════════════════════════════════════════════
# S46 — Stable-Only Safe Harbor
# ════════════════════════════════════════════════════════════════════════════

class TestS46SafeHarbor(unittest.TestCase):
    def setUp(self) -> None:
        self.s = SafeHarborStrategy()
        self.s._adapters = {}   # force deterministic fallback APYs

    def test_T01_identity_and_tier(self) -> None:
        self.assertEqual(self.s.STRATEGY_ID, "S46")
        self.assertEqual(self.s.TIER, "T1")

    def test_T02_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(S46_W.values()), 1.0, places=9)

    def test_T03_one_hundred_percent_t1_no_t2(self) -> None:
        # Every slot must be a T1 protocol — never any T2.
        for key in S46_W:
            self.assertEqual(PROTOCOL_TIER.get(key), "T1", key)
        self.assertEqual(self.s.get_risk_summary()["t2_weight_pct"], 0.0)
        self.assertTrue(self.s.get_risk_summary()["no_t2_exposure"])

    def test_T04_weights_match_brief(self) -> None:
        self.assertAlmostEqual(S46_W["aave_v3"], 0.40, places=9)
        self.assertAlmostEqual(S46_W["compound_v3"], 0.35, places=9)
        self.assertAlmostEqual(S46_W["sky_susds"], 0.25, places=9)

    def test_T05_allocation_fully_deployed(self) -> None:
        alloc = self.s.get_allocation(CAPITAL)
        self.assertAlmostEqual(sum(alloc.values()), CAPITAL, places=2)
        self.assertAlmostEqual(alloc["aave_v3"], 40_000.0, places=2)

    def test_T06_expected_apy_about_3_8(self) -> None:
        # 0.40*3.6 + 0.35*3.9 + 0.25*4.0 = 3.805
        self.assertAlmostEqual(self.s.get_expected_apy(), 3.805, places=3)

    def test_T07_zero_capital_safe(self) -> None:
        alloc = self.s.get_allocation(0.0)
        self.assertTrue(all(v == 0.0 for v in alloc.values()))

    def test_T08_simulate_and_health_ok(self) -> None:
        sim = self.s.simulate(CAPITAL)
        self.assertEqual(sim["status"], "ok")
        self.assertAlmostEqual(sim["deployed_usd"], CAPITAL, places=2)
        self.assertEqual(self.s.get_health()["overall_status"], "ok")


# ════════════════════════════════════════════════════════════════════════════
# S47 — Monthly Income Optimizer
# ════════════════════════════════════════════════════════════════════════════

class TestS47MonthlyIncome(unittest.TestCase):
    def setUp(self) -> None:
        self.s = MonthlyIncomeStrategy()
        self.s._adapters = {}

    def test_T09_identity_and_tier(self) -> None:
        self.assertEqual(self.s.STRATEGY_ID, "S47")
        self.assertEqual(self.s.TIER, "T1")

    def test_T10_sky_is_largest_weight(self) -> None:
        # Predictability-weighted: Sky (smoothest) gets the most.
        self.assertEqual(max(S47_W, key=S47_W.get), "sky_susds")
        self.assertAlmostEqual(S47_W["sky_susds"], 0.40, places=9)

    def test_T11_all_t1_no_t2(self) -> None:
        for key in S47_W:
            self.assertEqual(PROTOCOL_TIER.get(key), "T1", key)
        self.assertTrue(self.s.get_risk_summary()["no_t2_exposure"])

    def test_T12_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(S47_W.values()), 1.0, places=9)

    def test_T13_expected_apy_about_3_9(self) -> None:
        # 0.40*4.0 + 0.35*3.9 + 0.25*3.6 = 3.865
        self.assertAlmostEqual(self.s.get_expected_apy(), 3.865, places=3)

    def test_T14_monthly_income_about_325(self) -> None:
        # 100k * 3.865% / 12 ≈ $322
        income = self.s.get_monthly_income(CAPITAL)
        self.assertAlmostEqual(income, 322.08, places=1)
        self.assertGreater(income, 300.0)
        self.assertLess(income, 340.0)

    def test_T15_annual_equals_twelve_months(self) -> None:
        annual = self.s.get_annual_income(CAPITAL)
        monthly = self.s.get_monthly_income(CAPITAL)
        self.assertAlmostEqual(annual, monthly * 12.0, places=0)

    def test_T16_simulate_reports_monthly_income(self) -> None:
        sim = self.s.simulate(CAPITAL)
        self.assertEqual(sim["status"], "ok")
        self.assertGreater(sim["expected_monthly_income_usd"], 0.0)
        self.assertAlmostEqual(
            sim["expected_monthly_income_usd"] * 12.0,
            sim["expected_annual_yield_usd"], places=2,
        )


# ════════════════════════════════════════════════════════════════════════════
# S48 — Utilization-Aware
# ════════════════════════════════════════════════════════════════════════════

class TestS48UtilizationAware(unittest.TestCase):
    def setUp(self) -> None:
        self.s = UtilizationAwareStrategy()
        self.s._adapters = {}

    def test_T17_identity_and_tier(self) -> None:
        self.assertEqual(self.s.STRATEGY_ID, "S48")
        self.assertEqual(self.s.TIER, "T2")

    def test_T18_regime_high(self) -> None:
        self.assertEqual(self.s.get_regime(8.0), "high")
        self.assertAlmostEqual(self.s.get_weights(8.0)["aave_v3"], 0.50, places=9)

    def test_T19_regime_medium_balanced(self) -> None:
        self.assertEqual(self.s.get_regime(5.0), "medium")
        w = self.s.get_weights(5.0)
        for v in w.values():
            self.assertAlmostEqual(v, 1.0 / 3.0, places=6)

    def test_T20_regime_low_shifts_to_morpho(self) -> None:
        self.assertEqual(self.s.get_regime(3.0), "low")
        w = self.s.get_weights(3.0)
        self.assertIn("morpho_blue", w)
        self.assertAlmostEqual(w["morpho_blue"], 0.30, places=9)

    def test_T21_all_regime_weights_sum_to_one(self) -> None:
        for table in (WEIGHTS_HIGH, WEIGHTS_MEDIUM, WEIGHTS_LOW):
            self.assertAlmostEqual(sum(table.values()), 1.0, places=9)

    def test_T22_expected_apy_low_regime_in_band(self) -> None:
        # fallback Aave 3.6 → low regime → 4.475%, inside the 4.2–4.8 band.
        apy = self.s.get_expected_apy(3.0)
        self.assertAlmostEqual(apy, 4.475, places=3)
        self.assertGreaterEqual(apy, 4.2)
        self.assertLessEqual(apy, 4.8)

    def test_T23_low_regime_flagged_research_only(self) -> None:
        # Morpho 30% exceeds the 20% T2 per-protocol cap → advisory only.
        rs = self.s.get_risk_summary(3.0)
        self.assertFalse(rs["t2_per_protocol_ok"])
        self.assertTrue(rs["research_only"])
        # HIGH regime is 100% T1 → compliant.
        self.assertTrue(self.s.get_risk_summary(8.0)["adr_compliant"])

    def test_T24_allocation_and_simulate(self) -> None:
        alloc = self.s.get_allocation(CAPITAL, aave_apy=3.0)
        self.assertAlmostEqual(sum(alloc.values()), CAPITAL, places=2)
        sim = self.s.simulate(CAPITAL, aave_apy=8.0)
        self.assertEqual(sim["regime"], "high")
        self.assertEqual(sim["status"], "ok")


# ════════════════════════════════════════════════════════════════════════════
# S49 — Diversified Maximum
# ════════════════════════════════════════════════════════════════════════════

class TestS49DiversifiedMax(unittest.TestCase):
    def setUp(self) -> None:
        self.s = DiversifiedMaxStrategy()
        self.s._adapters = {}

    def test_T25_identity_and_tier(self) -> None:
        self.assertEqual(self.s.STRATEGY_ID, "S49")
        self.assertEqual(self.s.TIER, "T2")

    def test_T26_seven_venues(self) -> None:
        self.assertEqual(len(S49_W), 7)

    def test_T27_no_single_protocol_above_20pct(self) -> None:
        self.assertLessEqual(max(S49_W.values()), 0.20 + 1e-9)
        self.assertTrue(self.s.get_risk_summary()["no_concentration"])

    def test_T28_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(S49_W.values()), 1.0, places=9)

    def test_T29_t2_total_within_cap(self) -> None:
        t2 = sum(w for k, w in S49_W.items() if PROTOCOL_TIER.get(k) == "T2")
        self.assertAlmostEqual(t2, 0.45, places=9)
        self.assertLessEqual(t2, 0.50 + 1e-9)
        self.assertTrue(self.s.get_risk_summary()["adr_compliant"])

    def test_T30_expected_apy_about_4_4(self) -> None:
        # weighted fallback = 4.43%
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.43, places=2)

    def test_T31_diversification_metrics(self) -> None:
        # HHI of this vector = 0.155 → ~6.45 effective positions.
        self.assertAlmostEqual(self.s.get_hhi(), 0.155, places=3)
        self.assertGreater(self.s.effective_positions(), 6.0)

    def test_T32_allocation_and_simulate(self) -> None:
        alloc = self.s.get_allocation(CAPITAL)
        self.assertAlmostEqual(sum(alloc.values()), CAPITAL, places=2)
        self.assertEqual(self.s.simulate(CAPITAL)["status"], "ok")


# ════════════════════════════════════════════════════════════════════════════
# S50 — Tournament Champion (meta-strategy)
# ════════════════════════════════════════════════════════════════════════════

class TestS50TournamentChampion(unittest.TestCase):
    def _make(self, ranking=None):
        """Build an S50 over a temp data dir with an optional ranking payload."""
        tmp = tempfile.mkdtemp()
        if ranking is not None:
            with open(Path(tmp) / "tournament_ranking.json", "w", encoding="utf-8") as fh:
                json.dump(ranking, fh)
        s = TournamentChampionStrategy(data_dir=tmp)
        s._adapters = {}
        return s

    def test_T33_identity_and_tier(self) -> None:
        s = self._make()
        self.assertEqual(s.STRATEGY_ID, "S50")
        self.assertEqual(s.TIER, "T2")

    def test_T34_no_data_uses_s0_fallback(self) -> None:
        s = self._make(ranking=None)
        self.assertIsNone(s.get_leader_id())
        self.assertFalse(s.is_following_leader())
        self.assertEqual(set(s.get_active_weights()), set(S0_FALLBACK_WEIGHTS))

    def test_T35_s0_fallback_is_equal_weight_t1(self) -> None:
        s = self._make(ranking=None)
        w = s.get_active_weights()
        for v in w.values():
            self.assertAlmostEqual(v, 1.0 / 3.0, places=6)
        for key in w:
            self.assertEqual(PROTOCOL_TIER.get(key), "T1", key)

    def test_T36_follows_real_leader_weights(self) -> None:
        # Leader = S46 (Safe Harbor). S50 must copy S46's 40/35/25 weights.
        ranking = {"strategies": [{"rank": 1, "strategy_id": "S46"}]}
        s = self._make(ranking=ranking)
        self.assertEqual(s.get_leader_id(), "S46")
        self.assertTrue(s.is_following_leader())
        w = s.get_active_weights()
        self.assertAlmostEqual(w["aave_v3"], 0.40, places=6)
        self.assertAlmostEqual(w["compound_v3"], 0.35, places=6)
        self.assertAlmostEqual(w["sky_susds"], 0.25, places=6)

    def test_T37_anti_recursion_self_reference(self) -> None:
        # If the ranking names S50 itself, it must not copy itself → fallback.
        s = self._make(ranking={"strategies": [{"rank": 1, "strategy_id": "S50"}]})
        self.assertFalse(s.is_following_leader())
        self.assertEqual(set(s.get_active_weights()), set(S0_FALLBACK_WEIGHTS))

    def test_T38_unknown_leader_falls_back(self) -> None:
        s = self._make(ranking={"strategies": [{"rank": 1, "strategy_id": "S999_NOPE"}]})
        self.assertFalse(s.is_following_leader())
        self.assertEqual(set(s.get_active_weights()), set(S0_FALLBACK_WEIGHTS))

    def test_T39_active_weights_always_normalized(self) -> None:
        for ranking in (None,
                        {"strategies": [{"rank": 1, "strategy_id": "S46"}]},
                        {"strategies": [{"rank": 1, "strategy_id": "S49"}]}):
            s = self._make(ranking=ranking)
            self.assertAlmostEqual(sum(s.get_active_weights().values()), 1.0, places=6)

    def test_T40_allocation_and_simulate(self) -> None:
        s = self._make(ranking={"strategies": [{"rank": 1, "strategy_id": "S46"}]})
        alloc = s.get_allocation(CAPITAL)
        self.assertAlmostEqual(sum(alloc.values()), CAPITAL, places=2)
        sim = s.simulate(CAPITAL)
        self.assertEqual(sim["status"], "ok")
        self.assertEqual(sim["leader_id"], "S46")


# ════════════════════════════════════════════════════════════════════════════
# Cross-cutting: normalize_apy helper + registry registration
# ════════════════════════════════════════════════════════════════════════════

class TestIncomeCommonAndRegistry(unittest.TestCase):
    def test_normalize_apy_decimal_vs_percent(self) -> None:
        self.assertAlmostEqual(normalize_apy(0.065), 6.5, places=6)   # decimal → percent
        self.assertAlmostEqual(normalize_apy(6.5), 6.5, places=6)     # percent stays
        self.assertIsNone(normalize_apy(None))
        self.assertIsNone(normalize_apy(0.0))
        self.assertIsNone(normalize_apy(True))

    def test_all_five_registered(self) -> None:
        for sid, name in (
            ("S46", "Stable-Only Safe Harbor"),
            ("S47", "Monthly Income Optimizer"),
            ("S48", "Utilization-Aware"),
            ("S49", "Diversified Maximum"),
            ("S50", "Tournament Champion"),
        ):
            meta = REGISTRY.get(sid)
            self.assertIsNotNone(meta, f"{sid} not registered")
            self.assertEqual(meta.name, name)
            self.assertLess(meta.target_apy_min, meta.target_apy_max)


if __name__ == "__main__":
    unittest.main(verbosity=2)

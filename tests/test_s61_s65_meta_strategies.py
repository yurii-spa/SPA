"""
tests/test_s61_s65_meta_strategies.py — S61–S65 final hybrid & meta strategies (40 tests)

Covers the five final tournament strategies:
  S61 Hybrid Income Shield   — fixed income-first book, policy-cap view
  S62 Yield Ladder v2        — 3-week phased deployment
  S63 Anti-Correlation       — hysteresis decorrelation Aave/Compound→Sky
  S64 Bayesian Updater       — Jeffreys prior + weekly likelihood-ratio tilt + caps
  S65 Session Champion       — curated policy-compliant best-of-session book

Each strategy: identity, weight sums, expected-APY math, allocation scaling,
edge cases, and registry registration.
"""
import json
import os
import tempfile
import unittest

from spa_core.strategies.s61_hybrid_income_shield import (
    S61HybridIncomeShield, TARGET_WEIGHTS as S61_W, CASH_KEY as S61_CASH,
)
from spa_core.strategies.s62_yield_ladder_v2 import (
    S62YieldLadderV2, PHASE_WEIGHTS, WEEK1_END_DAY, WEEK2_END_DAY,
)
from spa_core.strategies.s63_anti_correlation import (
    S63AntiCorrelation, STANDARD_WEIGHTS, STATE_NORMAL, STATE_DECORRELATED,
    CORR_HIGH, CORR_LOW, load_pair_correlation,
)
from spa_core.strategies.s64_bayesian_updater import (
    S64BayesianUpdater, PROTOCOLS as S64_PROTOCOLS, PER_PROTOCOL_CAP,
    T2_TOTAL_CAP, PROTOCOL_TIERS as S64_TIERS,
)
from spa_core.strategies.s65_session_champion import (
    S65SessionChampion, TARGET_WEIGHTS as S65_W, PROTOCOL_TIERS as S65_TIERS,
)
from spa_core.strategies.strategy_registry import REGISTRY


# ════════════════════════════════════════════════════════════════════════════
# S61 — Hybrid Income Shield
# ════════════════════════════════════════════════════════════════════════════
class TestS61HybridIncomeShield(unittest.TestCase):
    def setUp(self):
        self.s = S61HybridIncomeShield()

    def test_strategy_id(self):
        self.assertEqual(self.s.STRATEGY_ID, "S61")

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s.get_weights().values()), 1.0, places=6)

    def test_sky_is_anchor_at_50pct(self):
        self.assertAlmostEqual(self.s.get_weights()["sky_susds"], 0.50, places=6)

    def test_expected_apy_matches_design(self):
        # 0.50*4.20 + 0.20*6.87 + 0.20*3.64 + 0.05*3.78 = 4.391
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.391, places=3)

    def test_policy_capped_sky_trimmed_to_40(self):
        capped = self.s.get_policy_capped_weights()
        self.assertLessEqual(capped["sky_susds"], 0.40 + 1e-9)

    def test_policy_capped_still_sums_to_one(self):
        capped = self.s.get_policy_capped_weights()
        self.assertAlmostEqual(sum(capped.values()), 1.0, places=6)

    def test_allocation_scales_with_capital(self):
        alloc = self.s.get_allocation(100_000.0)
        self.assertAlmostEqual(alloc["sky_susds"], 50_000.0, places=2)

    def test_zero_capital_no_alloc(self):
        self.assertEqual(self.s.get_allocation(0.0), {})

    def test_simulate_no_capital_status(self):
        self.assertEqual(self.s.simulate(0.0)["status"], "no_capital")

    def test_apy_map_override(self):
        # Morpho live at 10% lifts the weighted APY above the reference value.
        base = self.s.get_expected_apy()
        boosted = self.s.get_expected_apy({"morpho_blue": 10.0})
        self.assertGreater(boosted, base)


# ════════════════════════════════════════════════════════════════════════════
# S62 — Yield Ladder v2
# ════════════════════════════════════════════════════════════════════════════
class TestS62YieldLadderV2(unittest.TestCase):
    def setUp(self):
        self.s = S62YieldLadderV2()

    def test_strategy_id(self):
        self.assertEqual(self.s.STRATEGY_ID, "S62")

    def test_week1_is_all_sky(self):
        w = self.s.get_weights(0)
        self.assertAlmostEqual(w["sky_susds"], 1.0, places=6)

    def test_week2_split_morpho_sky(self):
        w = self.s.get_weights(WEEK1_END_DAY)  # day 7
        self.assertAlmostEqual(w["morpho_blue"], 0.50, places=6)
        self.assertAlmostEqual(w["sky_susds"], 0.50, places=6)

    def test_week3_optimal_book(self):
        w = self.s.get_weights(WEEK2_END_DAY)  # day 14
        self.assertAlmostEqual(w["aave_v3"], 0.30, places=6)
        self.assertAlmostEqual(w["compound_v3"], 0.20, places=6)

    def test_all_phases_sum_to_one(self):
        for d in (0, 7, 14, 100):
            self.assertAlmostEqual(sum(self.s.get_weights(d).values()), 1.0, places=6)

    def test_phase_boundaries(self):
        self.assertEqual(self.s.phase_for_day(6), "week1")
        self.assertEqual(self.s.phase_for_day(7), "week2")
        self.assertEqual(self.s.phase_for_day(13), "week2")
        self.assertEqual(self.s.phase_for_day(14), "week3")

    def test_negative_day_clamps_to_week1(self):
        self.assertEqual(self.s.phase_for_day(-5), "week1")

    def test_week1_apy_equals_sky(self):
        self.assertAlmostEqual(self.s.get_expected_apy(0), 4.20, places=2)

    def test_simulate_reports_phase(self):
        self.assertEqual(self.s.simulate(100_000.0, day_index=0)["phase"], "week1")

    def test_allocation_week3_scales(self):
        alloc = self.s.get_allocation(100_000.0, 14)
        self.assertAlmostEqual(alloc["aave_v3"], 30_000.0, places=2)


# ════════════════════════════════════════════════════════════════════════════
# S63 — Anti-Correlation
# ════════════════════════════════════════════════════════════════════════════
class TestS63AntiCorrelation(unittest.TestCase):
    def setUp(self):
        self.s = S63AntiCorrelation()

    def test_strategy_id(self):
        self.assertEqual(self.s.STRATEGY_ID, "S63")

    def test_high_corr_enters_decorrelated(self):
        self.assertEqual(self.s.resolve_state(0.97), STATE_DECORRELATED)

    def test_low_corr_restores_normal(self):
        self.assertEqual(self.s.resolve_state(0.50), STATE_NORMAL)

    def test_hysteresis_band_holds_prior_state(self):
        # 0.85 is between CORR_LOW and CORR_HIGH → keep whatever we were
        self.assertEqual(self.s.resolve_state(0.85, STATE_DECORRELATED), STATE_DECORRELATED)
        self.assertEqual(self.s.resolve_state(0.85, STATE_NORMAL), STATE_NORMAL)

    def test_none_corr_defaults_normal(self):
        self.assertEqual(self.s.resolve_state(None), STATE_NORMAL)

    def test_normal_weights_match_standard(self):
        w = self.s.get_weights(correlation=0.50)
        self.assertAlmostEqual(w["aave_v3"], STANDARD_WEIGHTS["aave_v3"], places=6)

    def test_decorrelated_drops_lower_yield_aave(self):
        # Aave (3.64) < Compound (3.78) → Aave is dropped, weight routed to Sky
        w = self.s.get_weights(correlation=0.97)
        self.assertNotIn("aave_v3", w)
        self.assertAlmostEqual(w["sky_susds"], 0.45, places=6)

    def test_both_states_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s.get_weights(correlation=0.97).values()), 1.0, places=6)
        self.assertAlmostEqual(sum(self.s.get_weights(correlation=0.50).values()), 1.0, places=6)

    def test_decorrelated_apy_in_band(self):
        apy = self.s.get_expected_apy(correlation=0.97)
        self.assertTrue(4.0 <= apy <= 4.6, f"apy={apy}")

    def test_thresholds_ordered(self):
        self.assertLess(CORR_LOW, CORR_HIGH)

    def test_load_correlation_missing_file_returns_none(self):
        self.assertIsNone(load_pair_correlation("/nonexistent/path/corr.json"))

    def test_load_correlation_from_matrix_file(self):
        payload = {"protocol_correlations": {"matrix": {"aave_v3": {"compound_v3": 0.93}}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            path = fh.name
        try:
            self.assertAlmostEqual(load_pair_correlation(path), 0.93, places=6)
        finally:
            os.unlink(path)


# ════════════════════════════════════════════════════════════════════════════
# S64 — Bayesian Updater
# ════════════════════════════════════════════════════════════════════════════
class TestS64BayesianUpdater(unittest.TestCase):
    def setUp(self):
        self.s = S64BayesianUpdater()

    def test_strategy_id(self):
        self.assertEqual(self.s.STRATEGY_ID, "S64")

    def test_jeffreys_prior_is_equal_weight(self):
        prior = self.s.jeffreys_prior()
        vals = list(prior.values())
        self.assertEqual(len(prior), len(S64_PROTOCOLS))
        for v in vals:
            self.assertAlmostEqual(v, vals[0], places=9)

    def test_prior_sums_to_one(self):
        self.assertAlmostEqual(sum(self.s.jeffreys_prior().values()), 1.0, places=6)

    def test_update_rewards_outperformer(self):
        prior = self.s.jeffreys_prior()
        # Aave (T1, prior 0.20, cap 0.40 → room to grow) doubles its expected
        # return; a T2 venue's equal-weight prior already sits at its 20% cap.
        obs = {"aave_v3": 7.28, "compound_v3": 3.78, "morpho_blue": 6.87,
               "yearn_v3": 4.95, "sky_susds": 4.20}
        post = self.s.update(prior, obs)
        self.assertGreater(post["aave_v3"], prior["aave_v3"])

    def test_update_penalizes_underperformer(self):
        prior = self.s.jeffreys_prior()
        obs = {"aave_v3": 1.0, "compound_v3": 3.78, "morpho_blue": 6.87,
               "yearn_v3": 4.95, "sky_susds": 4.20}
        post = self.s.update(prior, obs)
        self.assertLess(post["aave_v3"], prior["aave_v3"])

    def test_posterior_respects_t2_per_protocol_cap(self):
        # Hammer a T2 venue with huge outperformance; cap must hold at 20%.
        weeks = [{"morpho_blue": 30.0, "aave_v3": 3.0, "compound_v3": 3.0,
                  "yearn_v3": 3.0, "sky_susds": 4.2}] * 6
        w = self.s.get_weights(weeks)
        self.assertLessEqual(w.get("morpho_blue", 0.0), PER_PROTOCOL_CAP["T2"] + 1e-6)

    def test_posterior_respects_t1_cap(self):
        weeks = [{"aave_v3": 30.0, "compound_v3": 3.0, "morpho_blue": 3.0,
                  "yearn_v3": 3.0, "sky_susds": 4.2}] * 6
        w = self.s.get_weights(weeks)
        self.assertLessEqual(w.get("aave_v3", 0.0), PER_PROTOCOL_CAP["T1"] + 1e-6)

    def test_t2_total_cap_enforced(self):
        weeks = [{"morpho_blue": 30.0, "yearn_v3": 30.0, "aave_v3": 1.0,
                  "compound_v3": 1.0, "sky_susds": 1.0}] * 6
        w = self.s.get_weights(weeks)
        t2 = sum(v for p, v in w.items() if S64_TIERS.get(p) == "T2")
        self.assertLessEqual(t2, T2_TOTAL_CAP + 1e-6)

    def test_weights_sum_to_one_after_updates(self):
        weeks = [{"morpho_blue": 9.0, "aave_v3": 3.5, "compound_v3": 3.6,
                  "yearn_v3": 4.0, "sky_susds": 4.2}] * 3
        self.assertAlmostEqual(sum(self.s.get_weights(weeks).values()), 1.0, places=6)

    def test_no_observations_returns_prior(self):
        self.assertAlmostEqual(sum(self.s.get_weights(None).values()), 1.0, places=6)

    def test_fold_is_deterministic(self):
        weeks = [{"morpho_blue": 8.0, "aave_v3": 3.5, "compound_v3": 3.6,
                  "yearn_v3": 4.0, "sky_susds": 4.2}] * 2
        self.assertEqual(self.s.fold(weeks), self.s.fold(weeks))

    def test_zero_capital_simulate(self):
        self.assertEqual(self.s.simulate(0.0)["status"], "no_capital")


# ════════════════════════════════════════════════════════════════════════════
# S65 — Session Champion
# ════════════════════════════════════════════════════════════════════════════
class TestS65SessionChampion(unittest.TestCase):
    def setUp(self):
        self.s = S65SessionChampion()

    def test_strategy_id(self):
        self.assertEqual(self.s.STRATEGY_ID, "S65")

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s.get_weights().values()), 1.0, places=6)

    def test_expected_apy_near_4_77(self):
        # 0.25*4.20 + 0.20*6.87 + 0.20*6.22 + 0.20*3.64 + 0.10*3.78 = 4.774
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.774, places=3)

    def test_highest_apy_vs_siblings(self):
        others = [
            S61HybridIncomeShield().get_expected_apy(),
            S63AntiCorrelation().get_expected_apy(correlation=0.5),
        ]
        self.assertGreater(self.s.get_expected_apy(), max(others))

    def test_is_policy_compliant(self):
        self.assertTrue(self.s.is_policy_compliant())

    def test_t2_total_within_cap(self):
        t2 = sum(v for p, v in S65_W.items() if S65_TIERS.get(p) == "T2")
        self.assertLessEqual(t2, 0.50 + 1e-9)
        self.assertAlmostEqual(t2, 0.40, places=6)

    def test_no_single_venue_over_its_cap(self):
        for p, v in S65_W.items():
            if p == "cash":
                continue
            cap = 0.40 if S65_TIERS.get(p) == "T1" else 0.20
            self.assertLessEqual(v, cap + 1e-9, f"{p}={v} over cap {cap}")

    def test_fluid_included(self):
        self.assertIn("fluid", self.s.get_weights())

    def test_allocation_scales(self):
        alloc = self.s.get_allocation(100_000.0)
        self.assertAlmostEqual(alloc["morpho_blue"], 20_000.0, places=2)


# ════════════════════════════════════════════════════════════════════════════
# Registry registration
# ════════════════════════════════════════════════════════════════════════════
class TestRegistration(unittest.TestCase):
    def test_all_five_registered(self):
        for sid in ("S61", "S62", "S63", "S64", "S65"):
            self.assertIsNotNone(REGISTRY.get(sid), f"{sid} not registered")

    def test_handler_classes_match(self):
        expected = {
            "S61": "S61HybridIncomeShield",
            "S62": "S62YieldLadderV2",
            "S63": "S63AntiCorrelation",
            "S64": "S64BayesianUpdater",
            "S65": "S65SessionChampion",
        }
        for sid, cls in expected.items():
            self.assertEqual(REGISTRY.get(sid).handler_class, cls)

    def test_risk_tiers_valid(self):
        for sid in ("S61", "S62", "S63", "S64", "S65"):
            self.assertIn(REGISTRY.get(sid).risk_tier, {"T1", "T2", "T3"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

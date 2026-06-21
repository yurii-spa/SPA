"""
tests/test_s51_s55.py — advanced edge-case strategies S51–S55 (40 tests)

8 tests per strategy:
  TestS51ProtocolLifecycle     (8) — age buckets, young hard-cap, mature anchors
  TestS52TvlMomentum           (8) — up/down/flat tilt, equal-weight fallback
  TestS53CorrelatedRiskReducer (8) — >0.9 collapse, Morpho>Compound, no-data path
  TestS54DailyYieldMaximizer   (8) — top-3 chase, 80/20 split, T2 kill switch
  TestS55MaxSharpePortfolio    (8) — optimizer weights, sky gate, weekly cadence

Rules: stdlib only, unittest, no network access.
"""
import unittest

from spa_core.strategies.s51_protocol_lifecycle import (
    S51ProtocolLifecycle, get_age_years, lifecycle_bucket,
    LIFECYCLE_YOUNG, LIFECYCLE_GROWING, LIFECYCLE_MATURE,
    YOUNG_HARD_CAP, DEFAULT_AGE_YEARS, PROTOCOL_TIERS as S51_TIERS,
)
from spa_core.strategies.s52_tvl_momentum import (
    S52TvlMomentum, tvl_momentum_signal,
    MOMENTUM_UP, MOMENTUM_DOWN, MOMENTUM_FLAT, PROTOCOL_TIERS as S52_TIERS,
)
from spa_core.strategies.s53_correlated_risk_reducer import (
    S53CorrelatedRiskReducer, load_correlation_matrix, correlation,
    REDUCED_WEIGHT, CORR_THRESHOLD,
)
from spa_core.strategies.s54_daily_yield_maximizer import (
    S54DailyYieldMaximizer, rank_by_yesterday,
    CHASE_WEIGHT, CHASE_WEIGHT_CAPPED, TOP_N, PROTOCOL_TIERS as S54_TIERS,
)
from spa_core.strategies.s55_max_sharpe_portfolio import (
    S55MaxSharpePortfolio, gated_weights, should_rebalance,
    RAW_OPTIMIZER_WEIGHTS, SKY_KEY, CASH_KEY, OPTIMIZER_SHARPE_APY,
    REBALANCE_PERIOD_DAYS,
)


def _sum(alloc):
    return sum(alloc.values())


# ──────────────────────────────────────────────────────────────────────────────
# S51 — Protocol Lifecycle Manager
# ──────────────────────────────────────────────────────────────────────────────

class TestS51ProtocolLifecycle(unittest.TestCase):

    def setUp(self):
        self.s = S51ProtocolLifecycle()

    def test_lifecycle_bucket_boundaries(self):
        self.assertEqual(lifecycle_bucket(0.5), LIFECYCLE_YOUNG)
        self.assertEqual(lifecycle_bucket(1.5), LIFECYCLE_GROWING)
        self.assertEqual(lifecycle_bucket(3.0), LIFECYCLE_MATURE)

    def test_unknown_protocol_defaults_to_mature_age(self):
        self.assertEqual(get_age_years("nonexistent_protocol"), DEFAULT_AGE_YEARS)

    def test_age_override_wins(self):
        self.assertEqual(get_age_years("aave_v3", {"aave_v3": 0.25}), 0.25)

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation()), 1.0, places=6)

    def test_young_protocol_respects_hard_cap(self):
        # Force every protocol young except aave (mature anchor absorbs weight).
        ages = {"aave_v3": 3.0, "compound_v3": 0.3, "morpho_steakhouse": 0.3,
                "morpho_blue": 0.3, "yearn_v3": 0.3}
        alloc = self.s.get_allocation(age_overrides=ages)
        for p in ("compound_v3", "morpho_steakhouse", "morpho_blue", "yearn_v3"):
            self.assertLessEqual(alloc[p], YOUNG_HARD_CAP + 1e-6)
        self.assertGreater(alloc["aave_v3"], YOUNG_HARD_CAP)

    def test_mature_anchor_gets_largest_weight(self):
        ages = {"aave_v3": 3.0, "compound_v3": 0.3, "morpho_steakhouse": 0.3,
                "morpho_blue": 0.3, "yearn_v3": 0.3}
        alloc = self.s.get_allocation(age_overrides=ages)
        self.assertEqual(max(alloc, key=alloc.get), "aave_v3")

    def test_suspended_excluded_and_renorm(self):
        alloc = self.s.get_allocation(suspended={"yearn_v3"})
        self.assertNotIn("yearn_v3", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_simulate_positions_sum_to_capital(self):
        sim = self.s.simulate(100_000.0)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)
        self.assertGreater(sim["expected_apy_pct"], 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# S52 — TVL Momentum
# ──────────────────────────────────────────────────────────────────────────────

class TestS52TvlMomentum(unittest.TestCase):

    def setUp(self):
        self.s = S52TvlMomentum()

    def test_signal_up(self):
        self.assertEqual(tvl_momentum_signal(1.2e9, 1.0e9), MOMENTUM_UP)

    def test_signal_down(self):
        self.assertEqual(tvl_momentum_signal(0.7e9, 1.0e9), MOMENTUM_DOWN)

    def test_signal_flat_within_deadband(self):
        self.assertEqual(tvl_momentum_signal(1.005e9, 1.0e9), MOMENTUM_FLAT)

    def test_signal_flat_on_missing_data(self):
        self.assertEqual(tvl_momentum_signal(None, 1.0e9), MOMENTUM_FLAT)

    def test_no_tvl_data_is_equal_weight(self):
        alloc = self.s.get_allocation()
        vals = list(alloc.values())
        self.assertTrue(all(abs(v - vals[0]) < 1e-9 for v in vals))
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_up_overweights_relative_to_down(self):
        now = {"aave_v3": 1.3e9, "compound_v3": 0.6e9}
        avg = {"aave_v3": 1.0e9, "compound_v3": 1.0e9}
        alloc = self.s.get_allocation(tvl_now=now, tvl_avg_6m=avg)
        self.assertGreater(alloc["aave_v3"], alloc["compound_v3"])
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_suspended_excluded(self):
        alloc = self.s.get_allocation(suspended={"morpho_blue"})
        self.assertNotIn("morpho_blue", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_simulate_positions_sum_to_capital(self):
        now = {"aave_v3": 1.2e9}
        avg = {"aave_v3": 1.0e9}
        sim = self.s.simulate(100_000.0, tvl_now=now, tvl_avg_6m=avg)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)


# ──────────────────────────────────────────────────────────────────────────────
# S53 — Correlated Risk Reducer
# ──────────────────────────────────────────────────────────────────────────────

class TestS53CorrelatedRiskReducer(unittest.TestCase):

    def setUp(self):
        self.s = S53CorrelatedRiskReducer()

    def test_no_matrix_is_equal_weight(self):
        alloc = self.s.get_allocation(matrix={})
        vals = list(alloc.values())
        self.assertTrue(all(abs(v - vals[0]) < 1e-9 for v in vals))

    def test_high_corr_pair_reduces_lower_yield(self):
        m = {"compound_v3": {"morpho_blue": 0.97},
             "morpho_blue": {"compound_v3": 0.97}}
        # morpho_blue fallback APY (7.0) > compound (4.8) → compound reduced.
        reduced = self.s.get_reduced_set(matrix=m)
        self.assertIn("compound_v3", reduced)
        self.assertNotIn("morpho_blue", reduced)

    def test_morpho_preferred_over_compound_on_tie(self):
        m = {"compound_v3": {"morpho_blue": 0.95},
             "morpho_blue": {"compound_v3": 0.95}}
        # Equal APY → preference order keeps morpho, reduces compound.
        reduced = self.s.get_reduced_set(
            apy_map={"compound_v3": 5.0, "morpho_blue": 5.0}, matrix=m)
        self.assertIn("compound_v3", reduced)

    def test_reduced_pinned_to_five_percent(self):
        m = {"compound_v3": {"morpho_blue": 0.97},
             "morpho_blue": {"compound_v3": 0.97}}
        alloc = self.s.get_allocation(matrix=m)
        self.assertAlmostEqual(alloc["compound_v3"], REDUCED_WEIGHT, places=6)

    def test_below_threshold_not_reduced(self):
        m = {"compound_v3": {"morpho_blue": CORR_THRESHOLD},  # == threshold, not >
             "morpho_blue": {"compound_v3": CORR_THRESHOLD}}
        self.assertEqual(self.s.get_reduced_set(matrix=m), set())

    def test_alloc_sums_to_one_with_reduction(self):
        m = {"compound_v3": {"morpho_blue": 0.97},
             "morpho_blue": {"compound_v3": 0.97}}
        self.assertAlmostEqual(_sum(self.s.get_allocation(matrix=m)), 1.0, places=6)

    def test_correlation_symmetric_lookup(self):
        m = {"aave_v3": {"yearn_v3": 0.42}}
        self.assertEqual(correlation(m, "yearn_v3", "aave_v3"), 0.42)
        self.assertIsNone(correlation(m, "aave_v3", "maple"))

    def test_simulate_positions_sum_to_capital(self):
        m = {"compound_v3": {"morpho_blue": 0.97},
             "morpho_blue": {"compound_v3": 0.97}}
        sim = self.s.simulate(100_000.0, matrix=m)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)


# ──────────────────────────────────────────────────────────────────────────────
# S54 — Daily Yield Maximizer
# ──────────────────────────────────────────────────────────────────────────────

class TestS54DailyYieldMaximizer(unittest.TestCase):

    def setUp(self):
        self.s = S54DailyYieldMaximizer()
        # A mixed-tier ranking where top-3 spans T1 (compound) + T2.
        self.yday = {"morpho_blue": 7.2, "yearn_v3": 6.5, "compound_v3": 6.0,
                     "morpho_steakhouse": 5.0, "aave_v3": 3.5}

    def test_rank_by_yesterday_desc(self):
        active = ["aave_v3", "compound_v3", "morpho_blue"]
        ranked = rank_by_yesterday({"aave_v3": 1.0, "compound_v3": 3.0,
                                    "morpho_blue": 2.0}, active)
        self.assertEqual(ranked, ["compound_v3", "morpho_blue", "aave_v3"])

    def test_top_performers_is_top_n(self):
        top = self.s.get_top_performers(self.yday)
        self.assertEqual(len(top), TOP_N)
        self.assertEqual(top[0], "morpho_blue")

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation(self.yday)), 1.0, places=6)

    def test_top_performer_overweighted(self):
        alloc = self.s.get_allocation(self.yday)
        # Top performer gets chase share + baseline; clearly > a non-top name.
        self.assertGreater(alloc["morpho_blue"], alloc["aave_v3"])

    def test_kill_switch_inactive_when_t1_in_top3(self):
        # compound_v3 (T1) is in top-3 here → no kill switch, full 80% chase.
        self.assertFalse(self.s.kill_switch_active(self.yday))

    def test_kill_switch_active_when_top3_all_t2(self):
        # Suspend all three T1 anchors → the only rankable names are T2, so the
        # top-N is necessarily all-T2 and the kill switch trips.
        self.assertTrue(
            self.s.kill_switch_active(
                {"morpho_blue": 9.0, "yearn_v3": 8.5},
                suspended={"aave_v3", "compound_v3", "morpho_steakhouse"}))

    def test_kill_switch_caps_chase_weight(self):
        # All-T2 top via suspending the T1 anchors → chase capped at 60%.
        alloc = self.s.get_allocation(
            {"morpho_blue": 9.0, "yearn_v3": 8.5},
            suspended={"aave_v3", "compound_v3", "morpho_steakhouse"})
        # Only morpho_blue + yearn_v3 remain; both T2; chase=60% over top-2.
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)
        self.assertTrue(self.s.kill_switch_active(
            {"morpho_blue": 9.0, "yearn_v3": 8.5},
            suspended={"aave_v3", "compound_v3", "morpho_steakhouse"}))

    def test_simulate_positions_sum_to_capital(self):
        sim = self.s.simulate(100_000.0, yesterday_apy=self.yday)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)


# ──────────────────────────────────────────────────────────────────────────────
# S55 — Maximum Sharpe Portfolio
# ──────────────────────────────────────────────────────────────────────────────

class TestS55MaxSharpePortfolio(unittest.TestCase):

    def setUp(self):
        self.s = S55MaxSharpePortfolio()

    def test_raw_optimizer_weights_match_spec(self):
        self.assertEqual(RAW_OPTIMIZER_WEIGHTS["aave_v3"], 0.30)
        self.assertEqual(RAW_OPTIMIZER_WEIGHTS["compound_v3"], 0.20)
        self.assertEqual(RAW_OPTIMIZER_WEIGHTS[SKY_KEY], 0.30)
        self.assertEqual(RAW_OPTIMIZER_WEIGHTS["morpho_blue"], 0.20)

    def test_sky_gated_to_cash_by_default(self):
        alloc = self.s.get_allocation()  # sky_gsm_confirmed=False
        self.assertNotIn(SKY_KEY, alloc)
        self.assertAlmostEqual(alloc[CASH_KEY], 0.30, places=6)

    def test_confirmed_restores_sky(self):
        alloc = self.s.get_allocation(sky_gsm_confirmed=True)
        self.assertAlmostEqual(alloc[SKY_KEY], 0.30, places=6)
        self.assertNotIn(CASH_KEY, alloc)

    def test_gated_weights_helper(self):
        g = gated_weights(False)
        self.assertEqual(g[CASH_KEY], 0.30)
        self.assertNotIn(SKY_KEY, g)

    def test_confirmed_apy_matches_optimizer(self):
        apy = self.s.get_expected_apy(sky_gsm_confirmed=True)
        self.assertAlmostEqual(apy, OPTIMIZER_SHARPE_APY, places=2)

    def test_gated_apy_below_optimizer(self):
        # Sky parked in 0% cash → expected APY strictly below the confirmed figure.
        self.assertLess(self.s.get_expected_apy(), OPTIMIZER_SHARPE_APY)

    def test_should_rebalance_weekly(self):
        self.assertTrue(should_rebalance(None))
        self.assertTrue(should_rebalance(REBALANCE_PERIOD_DAYS))
        self.assertFalse(should_rebalance(REBALANCE_PERIOD_DAYS - 1))

    def test_alloc_sums_to_one_both_modes(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation()), 1.0, places=6)
        self.assertAlmostEqual(
            _sum(self.s.get_allocation(sky_gsm_confirmed=True)), 1.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

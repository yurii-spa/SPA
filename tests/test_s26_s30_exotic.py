"""
tests/test_s26_s30_exotic.py — exotic strategies S26–S30 (50 tests)

10 tests per strategy:
  TestS26VolatilityHarvester  (10) — regime detection, alloc sums, suspended, APY
  TestS27StablecoinCarry      (10) — top-rate pick, switch hysteresis, suspended
  TestS28MomentumYield        (10) — momentum calc, tilt direction, alloc sums
  TestS29BarbellPlus          (10) — 70/30 barbell, TVL floor, best T2, suspended
  TestS30AllWeather           (10) — bull/bear/sideways, tier shifts, suspended

Rules: stdlib only, unittest, no network/filesystem access.
"""
import unittest

from spa_core.strategies.s26_volatility_harvester import (
    S26VolatilityHarvester, REGIME_HIGH, REGIME_LOW, REGIME_NEUTRAL,
    PROTOCOL_TIERS as S26_TIERS,
)
from spa_core.strategies.s27_stablecoin_carry import (
    S27StablecoinCarry, SWITCH_THRESHOLD_PCT,
)
from spa_core.strategies.s28_momentum_yield import (
    S28MomentumYield, compute_momentum, PROTOCOL_TIERS as S28_TIERS,
)
from spa_core.strategies.s29_barbell_plus import (
    S29BarbellPlus, SAFE_WEIGHT, RISK_WEIGHT, MIN_T1_TVL_USD, CASH_KEY as S29_CASH,
)
from spa_core.strategies.s30_all_weather import (
    S30AllWeather, REGIME_BULL, REGIME_BEAR, REGIME_SIDEWAYS,
    PROTOCOL_TIERS as S30_TIERS, CASH_KEY as S30_CASH,
)


def _sum(alloc):
    return sum(alloc.values())


# ──────────────────────────────────────────────────────────────────────────────
# S26 — Volatility Harvester
# ──────────────────────────────────────────────────────────────────────────────

class TestS26VolatilityHarvester(unittest.TestCase):

    def setUp(self):
        self.s = S26VolatilityHarvester()

    def test_detect_high_vol(self):
        self.assertEqual(self.s.detect_regime(10.0), REGIME_HIGH)

    def test_detect_low_vol(self):
        self.assertEqual(self.s.detect_regime(3.0), REGIME_LOW)

    def test_detect_neutral(self):
        self.assertEqual(self.s.detect_regime(6.5), REGIME_NEUTRAL)

    def test_alloc_sums_to_one_each_regime(self):
        for borrow in (3.0, 6.5, 10.0):
            self.assertAlmostEqual(_sum(self.s.get_allocation(borrow)), 1.0, places=6)

    def test_high_vol_overweights_aave(self):
        alloc = self.s.get_allocation(10.0)
        self.assertAlmostEqual(alloc["aave_v3"], 0.60, places=6)

    def test_low_vol_overweights_pendle_pt(self):
        alloc = self.s.get_allocation(3.0)
        # Pendle PT is the largest weight when rates compress.
        self.assertEqual(max(alloc, key=alloc.get), "pendle_pt")

    def test_suspended_excluded_and_renorm(self):
        alloc = self.s.get_allocation(10.0, suspended={"pendle_pt"})
        self.assertNotIn("pendle_pt", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_only_known_protocols(self):
        alloc = self.s.get_allocation(6.5)
        for proto in alloc:
            self.assertIn(proto, S26_TIERS)

    def test_expected_apy_positive(self):
        self.assertGreater(self.s.get_expected_apy(6.5), 0.0)

    def test_simulate_positions_sum_to_capital(self):
        sim = self.s.simulate(100_000.0, 10.0)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)


# ──────────────────────────────────────────────────────────────────────────────
# S27 — Stablecoin Carry
# ──────────────────────────────────────────────────────────────────────────────

class TestS27StablecoinCarry(unittest.TestCase):

    def setUp(self):
        self.s = S27StablecoinCarry()
        # Full rate map so fallbacks never sneak in during deterministic tests.
        self.rates = {
            "aave_usdc": 4.0, "compound_usdc": 4.1, "aave_usdt": 4.2,
            "compound_usdt": 4.3, "sky_dai": 6.0,
        }

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation(self.rates)), 1.0, places=6)

    def test_picks_top_rate_venue(self):
        alloc = self.s.get_allocation(self.rates)
        self.assertEqual(next(iter(alloc)), "sky_dai")

    def test_full_allocation_single_venue(self):
        alloc = self.s.get_allocation(self.rates)
        self.assertEqual(len(alloc), 1)
        self.assertAlmostEqual(next(iter(alloc.values())), 1.0, places=6)

    def test_best_venue(self):
        self.assertEqual(self.s.best_venue(self.rates), "sky_dai")

    def test_switch_when_spread_exceeds_threshold(self):
        # current aave_usdc=4.0, best sky_dai=6.0 → spread 2.0 > 0.5
        self.assertTrue(self.s.should_switch("aave_usdc", self.rates))

    def test_no_switch_when_spread_below_threshold(self):
        rates = {
            "aave_usdc": 4.5, "compound_usdc": 4.6, "aave_usdt": 4.7,
            "compound_usdt": 4.8, "sky_dai": 4.9,
        }
        # current compound_usdt=4.8, best sky_dai=4.9 → spread 0.1 < 0.5
        self.assertFalse(self.s.should_switch("compound_usdt", rates))

    def test_hold_current_when_no_switch(self):
        rates = {
            "aave_usdc": 4.5, "compound_usdc": 4.6, "aave_usdt": 4.7,
            "compound_usdt": 4.8, "sky_dai": 4.9,
        }
        alloc = self.s.get_allocation(rates, current_venue="compound_usdt")
        self.assertEqual(next(iter(alloc)), "compound_usdt")

    def test_suspended_top_venue_excluded(self):
        alloc = self.s.get_allocation(self.rates, suspended={"sky_dai"})
        self.assertNotIn("sky_dai", alloc)
        # Next best is compound_usdt (4.3).
        self.assertEqual(next(iter(alloc)), "compound_usdt")

    def test_all_suspended_empty_allocation(self):
        alloc = self.s.get_allocation(self.rates, suspended=set(self.rates.keys()))
        self.assertEqual(alloc, {})

    def test_threshold_constant(self):
        self.assertAlmostEqual(SWITCH_THRESHOLD_PCT, 0.5, places=6)


# ──────────────────────────────────────────────────────────────────────────────
# S28 — Momentum Yield
# ──────────────────────────────────────────────────────────────────────────────

class TestS28MomentumYield(unittest.TestCase):

    def setUp(self):
        self.s = S28MomentumYield()
        self.hist = {
            "aave_v3":           [3.5, 3.6, 3.8, 4.0, 4.2, 4.5, 4.8, 5.2],  # rising
            "compound_v3":       [5.0, 4.8, 4.6, 4.4, 4.2, 4.0, 3.8, 3.6],  # falling
            "morpho_steakhouse": [6.5, 6.5, 6.5, 6.5, 6.5, 6.5, 6.5, 6.5],  # flat
        }

    def test_momentum_rising_positive(self):
        self.assertGreater(compute_momentum([3.0, 3.5, 4.0, 4.5]), 0.0)

    def test_momentum_falling_negative(self):
        self.assertLess(compute_momentum([5.0, 4.5, 4.0, 3.5]), 0.0)

    def test_momentum_empty_zero(self):
        self.assertEqual(compute_momentum([]), 0.0)
        self.assertEqual(compute_momentum([4.0]), 0.0)

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation(self.hist)), 1.0, places=6)

    def test_rising_overweighted_vs_falling(self):
        alloc = self.s.get_allocation(self.hist)
        self.assertGreater(alloc["aave_v3"], alloc["compound_v3"])

    def test_flat_equals_base_weight(self):
        # With one rising, one falling, one flat, the flat protocol stays near base.
        alloc = self.s.get_allocation(self.hist)
        self.assertGreater(alloc["aave_v3"], alloc["morpho_steakhouse"])
        self.assertLess(alloc["compound_v3"], alloc["morpho_steakhouse"])

    def test_no_history_equal_weight(self):
        alloc = self.s.get_allocation(None)
        vals = list(alloc.values())
        for v in vals:
            self.assertAlmostEqual(v, vals[0], places=6)

    def test_suspended_excluded(self):
        alloc = self.s.get_allocation(self.hist, suspended={"yearn_v3"})
        self.assertNotIn("yearn_v3", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_only_known_protocols(self):
        alloc = self.s.get_allocation(self.hist)
        for proto in alloc:
            self.assertIn(proto, S28_TIERS)

    def test_expected_apy_positive(self):
        self.assertGreater(self.s.get_expected_apy(self.hist), 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# S29 — Barbell Plus
# ──────────────────────────────────────────────────────────────────────────────

class TestS29BarbellPlus(unittest.TestCase):

    def setUp(self):
        self.s = S29BarbellPlus()
        self.t1 = {
            "aave_v3":           8_000_000_000.0,
            "compound_v3":       2_000_000_000.0,
            "morpho_steakhouse": 600_000_000.0,
            "small_t1":          100_000_000.0,   # below $500M floor
        }
        self.t2 = {"morpho_blue": 7.5, "yearn_v3": 6.5, "maple": 9.5}

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation(self.t1, self.t2)), 1.0, places=6)

    def test_barbell_70_30_split(self):
        rs = self.s.get_risk_summary(self.t1, self.t2)
        self.assertAlmostEqual(rs["t1_weight_pct"], 70.0, places=4)
        self.assertAlmostEqual(rs["t2_weight_pct"], 30.0, places=4)

    def test_tvl_floor_excludes_small_t1(self):
        eligible = self.s.eligible_t1(self.t1)
        self.assertNotIn("small_t1", eligible)
        self.assertIn("aave_v3", eligible)

    def test_t2_sleeve_is_single_pick(self):
        alloc = self.s.get_allocation(self.t1, self.t2)
        t2_in = [p for p in alloc if p in self.t2]
        self.assertEqual(len(t2_in), 1)

    def test_t2_sleeve_weight_is_30pct(self):
        alloc = self.s.get_allocation(self.t1, self.t2)
        pick = self.s.best_t2(self.t2)
        self.assertAlmostEqual(alloc[pick], RISK_WEIGHT, places=6)

    def test_best_t2_risk_adjusted(self):
        # maple 9.5/0.60=15.8; morpho_blue 7.5/0.40=18.75; yearn 6.5/0.42=15.5
        self.assertEqual(self.s.best_t2(self.t2), "morpho_blue")

    def test_suspended_t2_excluded(self):
        pick = self.s.best_t2(self.t2, suspended={"morpho_blue"})
        self.assertNotEqual(pick, "morpho_blue")

    def test_no_t2_folds_into_t1(self):
        alloc = self.s.get_allocation(self.t1, {}, suspended=None)
        # All weight to T1 anchors; no T2 keys present.
        for p in alloc:
            self.assertNotIn(p, self.t2)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_no_eligible_t1_falls_to_cash_or_t2(self):
        # All T1 below floor and no T2 → cash.
        small_t1 = {"a": 1.0, "b": 2.0}
        alloc = self.s.get_allocation(small_t1, {})
        self.assertEqual(alloc, {S29_CASH: 1.0})

    def test_constants(self):
        self.assertAlmostEqual(SAFE_WEIGHT, 0.70, places=6)
        self.assertAlmostEqual(RISK_WEIGHT, 0.30, places=6)
        self.assertEqual(MIN_T1_TVL_USD, 500_000_000.0)


# ──────────────────────────────────────────────────────────────────────────────
# S30 — All-Weather DeFi
# ──────────────────────────────────────────────────────────────────────────────

class TestS30AllWeather(unittest.TestCase):

    def setUp(self):
        self.s = S30AllWeather()

    def test_detect_bull(self):
        self.assertEqual(self.s.detect_regime(0.90), REGIME_BULL)

    def test_detect_bear(self):
        self.assertEqual(self.s.detect_regime(0.40), REGIME_BEAR)

    def test_detect_sideways(self):
        self.assertEqual(self.s.detect_regime(0.65), REGIME_SIDEWAYS)

    def test_percent_input_normalized(self):
        self.assertEqual(self.s.detect_regime(90.0), REGIME_BULL)

    def test_alloc_sums_to_one_each_regime(self):
        for util in (0.40, 0.65, 0.90):
            self.assertAlmostEqual(_sum(self.s.get_allocation(util)), 1.0, places=6)

    def test_bull_heavier_t2_than_bear(self):
        bull = self.s.get_risk_summary(0.90)
        bear = self.s.get_risk_summary(0.40)
        self.assertGreater(bull["t2_weight_pct"], bear["t2_weight_pct"])

    def test_bear_no_t2_and_has_cash(self):
        alloc = self.s.get_allocation(0.40)
        t2 = sum(w for p, w in alloc.items() if S30_TIERS.get(p) == "T2")
        self.assertAlmostEqual(t2, 0.0, places=6)
        self.assertGreater(alloc.get(S30_CASH, 0.0), 0.0)

    def test_bear_t1_heavy(self):
        rs = self.s.get_risk_summary(0.40)
        self.assertAlmostEqual(rs["t1_weight_pct"], 70.0, places=4)

    def test_suspended_excluded_renorm(self):
        alloc = self.s.get_allocation(0.90, suspended={"yearn_v3"})
        self.assertNotIn("yearn_v3", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_target_apy_in_range_any_regime(self):
        for util in (0.40, 0.65, 0.90):
            apy = self.s.get_expected_apy(util)
            self.assertGreater(apy, 0.0)
            self.assertLess(apy, 30.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

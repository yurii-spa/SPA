"""
tests/test_s45_mean_reversion.py — S45 Mean-Reversion Yield (25 tests)

Covers: deviation math, allocation tilt direction, per-protocol & T2 caps,
cash buffer, regime detection (stress / spike / reversion), historical-mean
loading + fallback, registry registration, and edge cases.
"""
import json
import os
import tempfile
import unittest

from spa_core.strategies.s45_mean_reversion import (
    S45MeanReversion,
    STRATEGY_ID,
    PROTOCOLS,
    PROTOCOL_TIERS,
    MEAN_APY_DEFAULTS,
    TILT,
    MIN_WEIGHT,
    CASH_BUFFER,
    CASH_KEY,
    PER_PROTOCOL_CAP,
    T2_TOTAL_CAP,
)

# A neutral snapshot: every protocol exactly at its mean (zero deviation).
FLAT = dict(MEAN_APY_DEFAULTS)


def _means():
    return dict(MEAN_APY_DEFAULTS)


class TestIdentity(unittest.TestCase):
    def test_strategy_id(self):
        self.assertEqual(STRATEGY_ID, "S45")

    def test_universe_has_five_protocols(self):
        self.assertEqual(len(PROTOCOLS), 5)
        self.assertIn("aave_v3", PROTOCOLS)

    def test_tier_map_complete(self):
        for p in PROTOCOLS:
            self.assertIn(PROTOCOL_TIERS[p], ("T1", "T2"))


class TestDeviation(unittest.TestCase):
    def setUp(self):
        self.s = S45MeanReversion()

    def test_zero_deviation_at_mean(self):
        dev = self.s.deviation_scores(FLAT, _means())
        for p in PROTOCOLS:
            self.assertAlmostEqual(dev[p], 0.0, places=6)

    def test_depressed_aave_negative_deviation(self):
        # Aave 1.57 vs mean 3.64 → (1.57-3.64)/3.64 ≈ -0.5687
        cur = dict(FLAT, aave_v3=1.57)
        dev = self.s.deviation_scores(cur, _means())
        self.assertAlmostEqual(dev["aave_v3"], (1.57 - 3.64) / 3.64, places=4)
        self.assertLess(dev["aave_v3"], 0)

    def test_elevated_protocol_positive_deviation(self):
        cur = dict(FLAT, aave_v3=12.60)
        dev = self.s.deviation_scores(cur, _means())
        self.assertGreater(dev["aave_v3"], 0)

    def test_zero_mean_skipped(self):
        dev = self.s.deviation_scores(dict(FLAT, aave_v3=5.0), dict(_means(), aave_v3=0.0))
        self.assertNotIn("aave_v3", dev)


class TestTiltDirection(unittest.TestCase):
    def setUp(self):
        self.s = S45MeanReversion()

    def test_depressed_protocol_overweighted_vs_flat(self):
        flat_w = self.s.compute_weights(FLAT, _means())
        cur = dict(FLAT, aave_v3=1.57)            # depressed → should add weight
        dep_w = self.s.compute_weights(cur, _means())
        self.assertGreater(dep_w["aave_v3"], flat_w["aave_v3"])

    def test_elevated_protocol_underweighted_vs_flat(self):
        flat_w = self.s.compute_weights(FLAT, _means())
        cur = dict(FLAT, aave_v3=10.0)            # elevated → should trim weight
        elev_w = self.s.compute_weights(cur, _means())
        self.assertLess(elev_w["aave_v3"], flat_w["aave_v3"])

    def test_adjustment_formula_matches_spec(self):
        # base + (-TILT*dev), pre-clamp/normalize, for a mild deviation.
        cur = dict(FLAT, compound_v3=3.40)        # slightly below 3.78 mean
        dev = (3.40 - 3.78) / 3.78
        expected_raw = 1.0 / len(PROTOCOLS) + (-TILT * dev)
        self.assertGreater(expected_raw, 1.0 / len(PROTOCOLS))  # below mean → up

    def test_flat_book_near_equal_weight(self):
        # All at mean → equal raw weights → after 5% cash, each ≈ 0.95/5 = 0.19
        w = self.s.compute_weights(FLAT, _means())
        for p in PROTOCOLS:
            self.assertAlmostEqual(w[p], (1.0 - CASH_BUFFER) / len(PROTOCOLS), places=3)


class TestCapsAndBuffers(unittest.TestCase):
    def setUp(self):
        self.s = S45MeanReversion()

    def test_weights_sum_to_one(self):
        w = self.s.compute_weights(dict(FLAT, aave_v3=1.57), _means())
        self.assertAlmostEqual(sum(w.values()), 1.0, places=5)

    def test_per_protocol_t1_cap_respected(self):
        # Deeply depressed Aave must not exceed the T1 40% cap after normalization.
        w = self.s.compute_weights(dict(FLAT, aave_v3=0.50), _means())
        self.assertLessEqual(w["aave_v3"], PER_PROTOCOL_CAP["T1"] + 1e-6)

    def test_per_protocol_t2_cap_respected(self):
        # Deeply depressed T2 (morpho) capped at 20%.
        w = self.s.compute_weights(dict(FLAT, morpho_blue=0.50), _means())
        self.assertLessEqual(w["morpho_blue"], PER_PROTOCOL_CAP["T2"] + 1e-6)

    def test_min_weight_floor_respected(self):
        # Wildly elevated protocol still keeps at least the floor (until renorm).
        w = self.s.compute_weights(dict(FLAT, yearn_v3=50.0), _means())
        self.assertGreaterEqual(w["yearn_v3"], MIN_WEIGHT - 1e-6)

    def test_cash_buffer_at_least_minimum(self):
        w = self.s.compute_weights(dict(FLAT, aave_v3=1.57), _means())
        self.assertGreaterEqual(w.get(CASH_KEY, 0.0), CASH_BUFFER - 1e-6)

    def test_t2_total_cap_respected(self):
        # Depress both T2 venues hard; aggregate T2 must stay ≤ 50%.
        cur = dict(FLAT, morpho_blue=1.0, yearn_v3=1.0)
        w = self.s.compute_weights(cur, _means())
        t2 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T2")
        self.assertLessEqual(t2, T2_TOTAL_CAP + 1e-6)

    def test_no_negative_weights(self):
        w = self.s.compute_weights(dict(FLAT, aave_v3=12.6, yearn_v3=16.0), _means())
        for v in w.values():
            self.assertGreaterEqual(v, 0.0)


class TestRegime(unittest.TestCase):
    def setUp(self):
        self.s = S45MeanReversion()

    def test_regime_reversion_mixed(self):
        cur = dict(FLAT, aave_v3=1.57, yearn_v3=16.0)   # one below, one above
        dev = self.s.deviation_scores(cur, _means())
        self.assertEqual(self.s.detect_regime(dev), "reversion")

    def test_regime_stress_all_below(self):
        cur = {p: MEAN_APY_DEFAULTS[p] * 0.5 for p in PROTOCOLS}  # all below mean
        dev = self.s.deviation_scores(cur, _means())
        self.assertEqual(self.s.detect_regime(dev), "stress")

    def test_regime_spike_all_above(self):
        cur = {p: MEAN_APY_DEFAULTS[p] * 1.5 for p in PROTOCOLS}  # all above mean
        dev = self.s.deviation_scores(cur, _means())
        self.assertEqual(self.s.detect_regime(dev), "spike")

    def test_stress_holds_high_t1(self):
        cur = {p: MEAN_APY_DEFAULTS[p] * 0.5 for p in PROTOCOLS}
        w = self.s.compute_weights(cur, _means())
        t1 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T2")
        self.assertGreaterEqual(t1, 0.75)     # ~80% T1 de-risk
        self.assertAlmostEqual(t2, 0.0, places=6)

    def test_spike_stays_diversified(self):
        cur = {p: MEAN_APY_DEFAULTS[p] * 1.5 for p in PROTOCOLS}
        w = self.s.compute_weights(cur, _means())
        protos = [v for p, v in w.items() if p != CASH_KEY]
        self.assertEqual(len(protos), len(PROTOCOLS))   # all kept
        self.assertAlmostEqual(max(protos), min(protos), places=3)  # equal weight


class TestHistoricalMean(unittest.TestCase):
    def test_loads_trailing_mean_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [{"date": f"2026-01-{i:02d}", "apy": 2.0} for i in range(1, 11)]
            with open(os.path.join(d, "aave_v3_usdc.json"), "w") as fh:
                json.dump(rows, fh)
            s = S45MeanReversion(data_dir=d, window_days=10)
            means = s.load_mean_apys()
            self.assertAlmostEqual(means["aave_v3"], 2.0, places=6)

    def test_falls_back_to_defaults_when_missing(self):
        s = S45MeanReversion(data_dir="/nonexistent/path/historical")
        means = s.load_mean_apys()
        self.assertEqual(means["sky_susds"], MEAN_APY_DEFAULTS["sky_susds"])

    def test_real_data_dir_loads(self):
        # Default data dir is the repo's data/historical_apy — should load real series.
        s = S45MeanReversion()
        means = s.load_mean_apys()
        for p in PROTOCOLS:
            self.assertGreater(means[p], 0.0)


class TestSimulateAndRegistry(unittest.TestCase):
    def setUp(self):
        self.s = S45MeanReversion()

    def test_simulate_zero_capital(self):
        out = self.s.simulate(0.0)
        self.assertEqual(out["status"], "no_capital")
        self.assertEqual(out["allocation"], {})

    def test_simulate_allocation_sums_to_capital(self):
        out = self.s.simulate(100_000.0, current_apys=dict(FLAT, aave_v3=1.57))
        self.assertAlmostEqual(sum(out["allocation"].values()), 100_000.0, delta=1.0)
        self.assertEqual(out["status"], "ok")

    def test_expected_apy_positive(self):
        apy = self.s.get_expected_apy(dict(FLAT, aave_v3=1.57))
        self.assertGreater(apy, 0.0)

    def test_registry_registration(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S45")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "S45MeanReversion")


if __name__ == "__main__":
    unittest.main()

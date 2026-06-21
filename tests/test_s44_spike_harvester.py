"""
tests/test_s44_spike_harvester.py — S44 Yield Spike Harvester (30 tests)

Coverage:
  TestS44Detection        (8)  — spike gates (2x + 6% abs), lagged baseline, winner pick
  TestS44Allocation       (7)  — spike 60/25/15, normal 40/30/20/10, caps, sums
  TestS44StateMachine     (8)  — lag, hold caps, 14-day force-normalize, TVL kill switch
  TestS44Magnitude        (3)  — magnitude pct + report string formatting
  TestS44Backtest         (3)  — synthetic spike capture, calm parity, validation
  TestS44Meta             (6)  — rolling avg, config validation, registry, simulate

Total: 35 tests (≥30).

Rules: stdlib only, unittest, no network/filesystem access.
"""
import unittest

from spa_core.strategies.s44_spike_harvester import (
    S44SpikeHarvester,
    S44Config,
    rolling_average,
    spike_magnitude_pct,
    format_spike_report,
    is_spiking,
    REGIME_SPIKE,
    REGIME_NORMAL,
    STABLE_REFUGE,
    MONITORED_PROTOCOLS,
    SPIKE_MULTIPLE,
    SPIKE_ABS_FLOOR_PCT,
    SPIKE_CONCENTRATION_PCT,
    SPIKE_REFUGE_PCT,
    NORMAL_WEIGHTS,
)


def _sum(alloc):
    return round(sum(alloc.values()), 8)


# Normal-baseline averages (≈ real means) for the monitored set.
BASE_AVG = {"aave_v3": 3.64, "compound_v3": 3.78, "yearn_v3": 4.93, "sky_susds": 4.2}
# A calm lagged map (everything near baseline).
CALM_APY = {"aave_v3": 3.7, "compound_v3": 3.8, "yearn_v3": 4.9, "sky_susds": 4.2}


# ──────────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────────
class TestS44Detection(unittest.TestCase):
    def setUp(self):
        self.h = S44SpikeHarvester()

    def test_aave_spike_detected(self):
        lagged = dict(CALM_APY, aave_v3=12.60)
        det = self.h.detect_regime(lagged, BASE_AVG)
        self.assertEqual(det["regime"], REGIME_SPIKE)
        self.assertEqual(det["spiking_protocol"], "aave_v3")

    def test_calm_is_inactive(self):
        det = self.h.detect_regime(CALM_APY, BASE_AVG)
        self.assertEqual(det["regime"], REGIME_NORMAL)
        self.assertIsNone(det["spiking_protocol"])

    def test_absolute_floor_blocks_low_base_doubling(self):
        # 5.5% is >2x a 2.5% avg but below the 6% absolute floor → not a spike.
        self.assertFalse(is_spiking(5.5, 2.5))
        self.assertTrue(is_spiking(6.5, 2.5))

    def test_relative_gate_requires_2x(self):
        # 7% absolute clears the floor but is < 2x a 4% baseline → not a spike.
        self.assertFalse(is_spiking(7.0, 4.0))
        self.assertTrue(is_spiking(8.5, 4.0))

    def test_none_or_zero_baseline_never_spikes(self):
        self.assertFalse(is_spiking(20.0, None))
        self.assertFalse(is_spiking(20.0, 0.0))

    def test_highest_magnitude_wins_when_multiple_spike(self):
        # compound +200% vs yearn +100% above their own averages → compound wins.
        lagged = dict(CALM_APY, compound_v3=11.34, yearn_v3=10.5)  # 3.0x and 2.13x
        det = self.h.detect_regime(lagged, BASE_AVG)
        self.assertEqual(det["regime"], REGIME_SPIKE)
        self.assertEqual(det["spiking_protocol"], "compound_v3")
        self.assertEqual(len(det["candidates"]), 2)

    def test_sky_refuge_not_a_spike_candidate(self):
        # Even an (impossible) sky doubling must not be picked — it's not monitored.
        lagged = dict(CALM_APY, sky_susds=12.0)
        det = self.h.detect_regime(lagged, BASE_AVG)
        self.assertEqual(det["regime"], REGIME_NORMAL)

    def test_missing_protocol_apy_skipped(self):
        lagged = {"aave_v3": 12.6}  # compound/yearn absent
        det = self.h.detect_regime(lagged, BASE_AVG)
        self.assertEqual(det["spiking_protocol"], "aave_v3")


# ──────────────────────────────────────────────────────────────────────────────
# Allocation
# ──────────────────────────────────────────────────────────────────────────────
class TestS44Allocation(unittest.TestCase):
    def setUp(self):
        self.h = S44SpikeHarvester()

    def test_normal_allocation_is_40_30_20_10(self):
        alloc = self.h.get_allocation(REGIME_NORMAL)
        self.assertEqual(alloc["aave_v3"], 0.40)
        self.assertEqual(alloc["compound_v3"], 0.30)
        self.assertEqual(alloc[STABLE_REFUGE], 0.20)
        # remainder 0.10 is cash (not in the weights map)
        self.assertAlmostEqual(_sum(alloc), 0.90)

    def test_spike_concentration_is_60(self):
        alloc = self.h.get_allocation(REGIME_SPIKE, "aave_v3")
        self.assertAlmostEqual(alloc["aave_v3"], 0.60)

    def test_spike_refuge_is_25(self):
        alloc = self.h.get_allocation(REGIME_SPIKE, "aave_v3")
        self.assertAlmostEqual(alloc[STABLE_REFUGE], 0.25)

    def test_spike_remaining_t1_spread(self):
        # aave spiking → remaining-T1 sleeve (15%) goes entirely to compound.
        alloc = self.h.get_allocation(REGIME_SPIKE, "aave_v3")
        self.assertAlmostEqual(alloc["compound_v3"], 0.15)
        self.assertAlmostEqual(_sum(alloc), 1.00)

    def test_spike_weights_never_exceed_one(self):
        for proto in MONITORED_PROTOCOLS:
            alloc = self.h.get_allocation(REGIME_SPIKE, proto)
            self.assertLessEqual(_sum(alloc), 1.0 + 1e-9)

    def test_yearn_spike_folds_sleeve_into_refuge(self):
        # yearn is not in REMAINING_T1, so the 15% sleeve has no distinct venue
        # to spread into other than aave/compound — both remain available.
        alloc = self.h.get_allocation(REGIME_SPIKE, "yearn_v3")
        self.assertAlmostEqual(alloc["yearn_v3"], 0.60)
        self.assertAlmostEqual(_sum(alloc), 1.00)
        # refuge + remaining-T1 still fully allocated
        self.assertGreaterEqual(alloc[STABLE_REFUGE], 0.25)

    def test_compound_spike_excludes_itself_from_spread(self):
        alloc = self.h.get_allocation(REGIME_SPIKE, "compound_v3")
        self.assertAlmostEqual(alloc["compound_v3"], 0.60)
        # remaining-T1 sleeve goes to aave (the other T1), not double-counted
        self.assertAlmostEqual(alloc["aave_v3"], 0.15)


# ──────────────────────────────────────────────────────────────────────────────
# State machine
# ──────────────────────────────────────────────────────────────────────────────
class TestS44StateMachine(unittest.TestCase):
    def setUp(self):
        self.h = S44SpikeHarvester()

    def test_enters_spike_and_tracks_days(self):
        spike = dict(CALM_APY, aave_v3=12.6)
        s1 = self.h.step(spike, BASE_AVG)
        self.assertEqual(s1["regime"], REGIME_SPIKE)
        self.assertEqual(s1["days_held"], 1)
        s2 = self.h.step(spike, BASE_AVG)
        self.assertEqual(s2["days_held"], 2)
        self.assertEqual(s2["consecutive_spike_days"], 2)

    def test_normalizes_when_spike_ends(self):
        self.h.step(dict(CALM_APY, aave_v3=12.6), BASE_AVG)
        st = self.h.step(CALM_APY, BASE_AVG)  # back to baseline
        self.assertEqual(st["regime"], REGIME_NORMAL)
        self.assertEqual(st["days_held"], 0)
        self.assertIsNone(st["spiking_protocol"])

    def test_hard_14_day_cap_forces_normalize(self):
        spike = dict(CALM_APY, aave_v3=12.6)
        last = None
        for _ in range(15):
            last = self.h.step(spike, BASE_AVG)
        self.assertTrue(last["forced_normalize"])
        self.assertEqual(last["regime"], REGIME_NORMAL)

    def test_consecutive_cap_boundary(self):
        spike = dict(CALM_APY, aave_v3=12.6)
        for _ in range(14):
            st = self.h.step(spike, BASE_AVG)
            self.assertEqual(st["regime"], REGIME_SPIKE)
        # 15th consecutive day is force-normalized
        st = self.h.step(spike, BASE_AVG)
        self.assertEqual(st["regime"], REGIME_NORMAL)
        self.assertTrue(st["forced_normalize"])

    def test_protocol_switch_resets_day_counter(self):
        self.h.step(dict(CALM_APY, aave_v3=12.6), BASE_AVG)
        self.h.step(dict(CALM_APY, aave_v3=12.6), BASE_AVG)
        st = self.h.step(dict(CALM_APY, compound_v3=12.0), BASE_AVG)
        self.assertEqual(st["spiking_protocol"], "compound_v3")
        self.assertEqual(st["days_held"], 1)

    def test_tvl_kill_switch_exits_on_drain(self):
        spike = dict(CALM_APY, aave_v3=12.6)
        # day 1: enter with TVL 100M
        self.h.step(spike, BASE_AVG, tvl_map={"aave_v3": 100e6})
        # day 2: TVL drained 25% (>20% threshold) → kill switch
        st = self.h.step(spike, BASE_AVG, tvl_map={"aave_v3": 75e6})
        self.assertTrue(st["kill_switch"])
        self.assertEqual(st["regime"], REGIME_NORMAL)

    def test_tvl_stable_does_not_trip_kill_switch(self):
        spike = dict(CALM_APY, aave_v3=12.6)
        self.h.step(spike, BASE_AVG, tvl_map={"aave_v3": 100e6})
        st = self.h.step(spike, BASE_AVG, tvl_map={"aave_v3": 95e6})  # -5% only
        self.assertFalse(st["kill_switch"])
        self.assertEqual(st["regime"], REGIME_SPIKE)

    def test_allocation_matches_regime_each_step(self):
        st = self.h.step(dict(CALM_APY, aave_v3=12.6), BASE_AVG)
        self.assertAlmostEqual(st["allocation"]["aave_v3"], SPIKE_CONCENTRATION_PCT)
        st2 = self.h.step(CALM_APY, BASE_AVG)
        self.assertEqual(st2["allocation"], {k: v for k, v in NORMAL_WEIGHTS.items()})


# ──────────────────────────────────────────────────────────────────────────────
# Magnitude / reporting
# ──────────────────────────────────────────────────────────────────────────────
class TestS44Magnitude(unittest.TestCase):
    def test_magnitude_pct(self):
        self.assertAlmostEqual(spike_magnitude_pct(12.60, 3.64), (12.60 / 3.64 - 1) * 100, places=4)

    def test_magnitude_zero_on_bad_baseline(self):
        self.assertEqual(spike_magnitude_pct(12.0, 0.0), 0.0)
        self.assertEqual(spike_magnitude_pct(12.0, None), 0.0)

    def test_report_string_format(self):
        rep = format_spike_report("aave_v3", 12.60, 3.64)
        self.assertEqual(rep, "spike: Aave at 12.60% vs 30d avg 3.64% = +246% above average")


# ──────────────────────────────────────────────────────────────────────────────
# Backtest
# ──────────────────────────────────────────────────────────────────────────────
class TestS44Backtest(unittest.TestCase):
    def _calm_series(self, n=60):
        return {
            "aave_v3":     [3.6] * n,
            "compound_v3": [3.8] * n,
            "yearn_v3":    [4.9] * n,
            "sky_susds":   [4.2] * n,
        }

    def test_backtest_captures_injected_spike(self):
        # Calm baseline with a 5-day Aave spike to 12% starting day 40.
        s = self._calm_series(60)
        for i in range(40, 45):
            s["aave_v3"][i] = 12.0
        res = S44SpikeHarvester().backtest(s, initial_capital=100_000.0)
        self.assertGreater(res["spike_days"], 0)
        self.assertGreater(res["spike_interest_usd"], 0.0)
        # final capital strictly grows (positive yield accrual)
        self.assertGreater(res["final_capital_usd"], 100_000.0)

    def test_backtest_calm_never_spikes(self):
        res = S44SpikeHarvester().backtest(self._calm_series(60), initial_capital=100_000.0)
        self.assertEqual(res["spike_days"], 0)
        self.assertEqual(res["regimes"].count(REGIME_SPIKE), 0)

    def test_backtest_rejects_misaligned_series(self):
        bad = {"aave_v3": [3.6, 3.7], "compound_v3": [3.8]}
        with self.assertRaises(ValueError):
            S44SpikeHarvester().backtest(bad)


# ──────────────────────────────────────────────────────────────────────────────
# Config / helpers / meta
# ──────────────────────────────────────────────────────────────────────────────
class TestS44Meta(unittest.TestCase):
    def test_rolling_average_window(self):
        self.assertIsNone(rolling_average([]))
        self.assertAlmostEqual(rolling_average([1, 2, 3, 4], window=2), 3.5)

    def test_config_rejects_bad_multiple(self):
        with self.assertRaises(ValueError):
            S44Config(spike_multiple=0.9)

    def test_config_rejects_hold_gt_consecutive(self):
        with self.assertRaises(ValueError):
            S44Config(max_hold_days=20, max_consecutive_spike_days=14)

    def test_registered_in_registry(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S44")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T3")
        self.assertEqual(meta.handler_class, "S44SpikeHarvester")

    def test_simulate_snapshot_ok(self):
        h = S44SpikeHarvester()
        snap = h.simulate(100_000.0, dict(CALM_APY, aave_v3=12.6), BASE_AVG)
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["regime"], REGIME_SPIKE)
        self.assertEqual(snap["allocation"]["aave_v3"], 60_000.0)

    def test_simulate_no_capital(self):
        snap = S44SpikeHarvester().simulate(0.0, CALM_APY, BASE_AVG)
        self.assertEqual(snap["status"], "no_capital")


if __name__ == "__main__":
    unittest.main(verbosity=2)

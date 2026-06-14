"""
Tests for MP-1109: DeFiProtocolYieldHarvestingFrequencyOptimizer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_yield_harvesting_frequency_optimizer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_yield_harvesting_frequency_optimizer import (
    DeFiProtocolYieldHarvestingFrequencyOptimizer,
    _clamp,
    _daily_rate,
    _apy_from_daily,
    _compound_gain,
    _frequency_label,
    _build_default_cfg,
    optimal_harvest_interval_days,
    effective_apy_with_compounding,
    MIN_HARVEST_INTERVAL_DAYS,
    MAX_HARVEST_INTERVAL_DAYS,
    DAYS_PER_YEAR,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_position(
    name="TestPos",
    protocol="TestProto",
    position_usd=100_000.0,
    gross_apy_pct=10.0,
    gas_cost_per_harvest_usd=20.0,
    reward_decay_pct_per_day=0.0,
    current_harvest_interval_days=7.0,
):
    return {
        "name": name,
        "protocol": protocol,
        "position_usd": position_usd,
        "gross_apy_pct": gross_apy_pct,
        "gas_cost_per_harvest_usd": gas_cost_per_harvest_usd,
        "reward_decay_pct_per_day": reward_decay_pct_per_day,
        "current_harvest_interval_days": current_harvest_interval_days,
    }


def tmp_cfg():
    td = tempfile.mkdtemp()
    return {"log_path": os.path.join(td, "harvest_log.json"), "log_cap": 5}


# ── helper function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_daily_rate_10pct_apy(self):
        r = _daily_rate(10.0)
        self.assertGreater(r, 0.0)
        # Reconstruct APY: (1+r)^365.25 - 1 ≈ 0.10
        self.assertAlmostEqual((1 + r) ** DAYS_PER_YEAR - 1, 0.10, places=4)

    def test_daily_rate_zero_apy(self):
        self.assertEqual(_daily_rate(0.0), 0.0)

    def test_daily_rate_negative_apy(self):
        self.assertEqual(_daily_rate(-5.0), 0.0)

    def test_apy_from_daily_roundtrip(self):
        apy_in = 12.0
        r = _daily_rate(apy_in)
        apy_out = _apy_from_daily(r)
        self.assertAlmostEqual(apy_out, apy_in, places=4)

    def test_apy_from_daily_zero(self):
        self.assertAlmostEqual(_apy_from_daily(0.0), 0.0, places=6)

    def test_compound_gain_positive(self):
        r = _daily_rate(10.0)
        gain = _compound_gain(100_000, r, 30)
        self.assertGreater(gain, 0.0)

    def test_compound_gain_grows_with_time(self):
        r = _daily_rate(10.0)
        g30 = _compound_gain(100_000, r, 30)
        g60 = _compound_gain(100_000, r, 60)
        self.assertGreater(g60, g30)

    def test_compound_gain_zero_days(self):
        r = _daily_rate(10.0)
        self.assertAlmostEqual(_compound_gain(100_000, r, 0), 0.0, places=6)

    def test_frequency_label_daily(self):
        self.assertEqual(_frequency_label(0.5), "DAILY")

    def test_frequency_label_daily_exact(self):
        self.assertEqual(_frequency_label(1.0), "DAILY")

    def test_frequency_label_weekly(self):
        self.assertEqual(_frequency_label(5.0), "WEEKLY")

    def test_frequency_label_monthly(self):
        self.assertEqual(_frequency_label(15.0), "MONTHLY")

    def test_frequency_label_quarterly(self):
        self.assertEqual(_frequency_label(60.0), "QUARTERLY")

    def test_frequency_label_annually(self):
        self.assertEqual(_frequency_label(200.0), "ANNUALLY")

    def test_frequency_label_never(self):
        self.assertEqual(_frequency_label(float("inf")), "NEVER_PROFITABLE")

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 99})
        self.assertEqual(cfg["log_cap"], 99)


# ── optimal_harvest_interval_days tests ──────────────────────────────────────

class TestOptimalHarvestInterval(unittest.TestCase):

    def test_basic_no_decay(self):
        t = optimal_harvest_interval_days(100_000, 10.0, 20.0, 0.0)
        self.assertGreater(t, 0.0)
        self.assertLessEqual(t, MAX_HARVEST_INTERVAL_DAYS)

    def test_larger_position_shorter_interval(self):
        """Larger position → harvest more often (gas is cheaper relative to gains)."""
        t_small = optimal_harvest_interval_days(1_000, 10.0, 20.0, 0.0)
        t_large = optimal_harvest_interval_days(1_000_000, 10.0, 20.0, 0.0)
        self.assertGreater(t_small, t_large)

    def test_higher_apy_shorter_interval(self):
        t_low  = optimal_harvest_interval_days(100_000, 2.0, 20.0, 0.0)
        t_high = optimal_harvest_interval_days(100_000, 20.0, 20.0, 0.0)
        self.assertGreater(t_low, t_high)

    def test_higher_gas_longer_interval(self):
        t_cheap = optimal_harvest_interval_days(100_000, 10.0, 5.0, 0.0)
        t_dear  = optimal_harvest_interval_days(100_000, 10.0, 100.0, 0.0)
        self.assertGreater(t_dear, t_cheap)

    def test_zero_position_returns_max(self):
        t = optimal_harvest_interval_days(0.0, 10.0, 20.0)
        self.assertEqual(t, MAX_HARVEST_INTERVAL_DAYS)

    def test_zero_apy_returns_max(self):
        t = optimal_harvest_interval_days(100_000, 0.0, 20.0)
        self.assertEqual(t, MAX_HARVEST_INTERVAL_DAYS)

    def test_negative_gas_no_crash(self):
        t = optimal_harvest_interval_days(100_000, 10.0, -5.0)
        self.assertGreaterEqual(t, 0.0)

    def test_with_decay_returns_valid(self):
        t = optimal_harvest_interval_days(100_000, 10.0, 20.0, 0.5)
        self.assertGreater(t, 0.0)
        self.assertLessEqual(t, MAX_HARVEST_INTERVAL_DAYS)

    def test_interval_clamped_above(self):
        t = optimal_harvest_interval_days(1.0, 0.1, 1_000.0)
        self.assertLessEqual(t, MAX_HARVEST_INTERVAL_DAYS)

    def test_interval_clamped_below(self):
        t = optimal_harvest_interval_days(1e12, 100.0, 0.01)
        self.assertGreaterEqual(t, MIN_HARVEST_INTERVAL_DAYS)


# ── effective_apy tests ───────────────────────────────────────────────────────

class TestEffectiveApy(unittest.TestCase):

    def test_less_than_gross(self):
        eff = effective_apy_with_compounding(10.0, 100_000, 20.0, 7.0)
        self.assertLessEqual(eff, 10.0)

    def test_nonnegative(self):
        eff = effective_apy_with_compounding(1.0, 1_000, 500.0, 1.0)
        self.assertGreaterEqual(eff, 0.0)

    def test_zero_position(self):
        eff = effective_apy_with_compounding(10.0, 0.0, 20.0, 7.0)
        self.assertEqual(eff, 0.0)

    def test_zero_interval(self):
        eff = effective_apy_with_compounding(10.0, 100_000, 20.0, 0.0)
        self.assertEqual(eff, 0.0)

    def test_effective_apy_consistent_across_intervals_zero_gas(self):
        # With zero gas cost, effective APY at any interval should be close to gross APY
        apy_daily   = effective_apy_with_compounding(10.0, 100_000, 0.0, 1.0)
        apy_monthly = effective_apy_with_compounding(10.0, 100_000, 0.0, 30.0)
        # Both should be within 1% of gross APY (10%)
        self.assertAlmostEqual(apy_daily, 10.0, delta=1.0)
        self.assertAlmostEqual(apy_monthly, 10.0, delta=1.0)

    def test_zero_gas_apy_close_to_gross(self):
        eff = effective_apy_with_compounding(10.0, 100_000, 0.0, 7.0)
        self.assertAlmostEqual(eff, 10.0, delta=0.5)


# ── optimizer class tests ─────────────────────────────────────────────────────

class TestYieldHarvestingOptimizer(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolYieldHarvestingFrequencyOptimizer()

    def test_optimize_returns_keys(self):
        result = self.opt.optimize([make_position()])
        self.assertIn("positions", result)
        self.assertIn("aggregate", result)

    def test_optimize_empty(self):
        result = self.opt.optimize([])
        self.assertEqual(len(result["positions"]), 0)
        self.assertIsNone(result["aggregate"]["most_suboptimal_position"])

    def test_single_position(self):
        result = self.opt.optimize([make_position()])
        self.assertEqual(len(result["positions"]), 1)

    def test_position_result_keys(self):
        result = self.opt.optimize([make_position()])
        p = result["positions"][0]
        for k in [
            "name", "protocol", "position_usd", "gross_apy_pct",
            "gas_cost_per_harvest_usd", "reward_decay_pct_per_day",
            "optimal_interval_days", "optimal_frequency_label",
            "current_interval_days", "effective_apy_at_optimal",
            "effective_apy_at_current", "apy_improvement_pct",
            "additional_annual_yield_usd", "min_profitable_position_usd",
            "flags",
        ]:
            self.assertIn(k, p)

    def test_optimal_interval_positive(self):
        result = self.opt.optimize([make_position()])
        self.assertGreater(result["positions"][0]["optimal_interval_days"], 0.0)

    def test_frequency_label_valid(self):
        result = self.opt.optimize([make_position()])
        label = result["positions"][0]["optimal_frequency_label"]
        valid = {"DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUALLY", "NEVER_PROFITABLE"}
        self.assertIn(label, valid)

    def test_effective_apy_optimal_nonneg(self):
        result = self.opt.optimize([make_position()])
        self.assertGreaterEqual(result["positions"][0]["effective_apy_at_optimal"], 0.0)

    def test_additional_yield_nonneg(self):
        result = self.opt.optimize([make_position()])
        self.assertGreaterEqual(result["positions"][0]["additional_annual_yield_usd"], 0.0)

    def test_name_preserved(self):
        p = make_position(name="SpecialFarm")
        result = self.opt.optimize([p])
        self.assertEqual(result["positions"][0]["name"], "SpecialFarm")

    def test_over_harvesting_flag(self):
        p = make_position(
            position_usd=100_000,
            gross_apy_pct=10.0,
            gas_cost_per_harvest_usd=20.0,
            current_harvest_interval_days=0.5,   # very frequent
        )
        result = self.opt.optimize([p])
        # Optimal should be much longer → OVER_HARVESTING
        flags = result["positions"][0]["flags"]
        # Either OVER_HARVESTING or POSITION_TOO_SMALL (depends on position)
        self.assertTrue(
            "OVER_HARVESTING" in flags or "HIGH_GAS_DRAG" in flags
            or result["positions"][0]["optimal_interval_days"] > 2.0
        )

    def test_high_reward_decay_flag(self):
        p = make_position(reward_decay_pct_per_day=2.0)
        result = self.opt.optimize([p])
        self.assertIn("HIGH_REWARD_DECAY", result["positions"][0]["flags"])

    def test_no_decay_flag(self):
        p = make_position(reward_decay_pct_per_day=0.0)
        result = self.opt.optimize([p])
        self.assertNotIn("HIGH_REWARD_DECAY", result["positions"][0]["flags"])

    def test_min_profitable_position_positive(self):
        p = make_position(gross_apy_pct=10.0, gas_cost_per_harvest_usd=20.0)
        result = self.opt.optimize([p])
        self.assertGreater(result["positions"][0]["min_profitable_position_usd"], 0.0)

    def test_small_position_too_small_flag(self):
        p = make_position(
            position_usd=100.0,       # very small
            gross_apy_pct=5.0,
            gas_cost_per_harvest_usd=50.0,
        )
        result = self.opt.optimize([p])
        self.assertIn("POSITION_TOO_SMALL_TO_HARVEST", result["positions"][0]["flags"])

    def test_large_position_no_too_small_flag(self):
        p = make_position(position_usd=10_000_000.0, gas_cost_per_harvest_usd=20.0)
        result = self.opt.optimize([p])
        self.assertNotIn("POSITION_TOO_SMALL_TO_HARVEST", result["positions"][0]["flags"])

    def test_aggregate_total_additional_yield(self):
        positions = [make_position(name=f"P{i}") for i in range(3)]
        result = self.opt.optimize(positions)
        total = result["aggregate"]["total_additional_annual_yield_usd"]
        self.assertGreaterEqual(total, 0.0)

    def test_aggregate_over_harvesting_count(self):
        result = self.opt.optimize([make_position()])
        self.assertIsInstance(result["aggregate"]["over_harvesting_count"], int)

    def test_aggregate_most_suboptimal(self):
        positions = [make_position(name="A", current_harvest_interval_days=0.5),
                     make_position(name="B", current_harvest_interval_days=7.0)]
        result = self.opt.optimize(positions)
        self.assertIsNotNone(result["aggregate"]["most_suboptimal_position"])


# ── log tests ─────────────────────────────────────────────────────────────────

class TestHarvestLog(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolYieldHarvestingFrequencyOptimizer()

    def test_write_log_creates_file(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        self.assertTrue(os.path.exists(cfg["log_path"]))

    def test_log_valid_json(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_keys(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        entry = data[0]
        self.assertIn("ts", entry)
        self.assertIn("position_count", entry)
        self.assertIn("aggregates", entry)
        self.assertIn("snapshots", entry)

    def test_log_ring_buffer_cap(self):
        cfg = tmp_cfg()
        for _ in range(cfg["log_cap"] + 3):
            self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), cfg["log_cap"])

    def test_no_write_no_file(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position()], cfg=cfg, write_log=False)
        self.assertFalse(os.path.exists(cfg["log_path"]))

    def test_log_atomic_no_tmp(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        self.assertFalse(os.path.exists(cfg["log_path"] + ".tmp"))

    def test_log_accumulates(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_snapshot_keys(self):
        cfg = tmp_cfg()
        self.opt.optimize([make_position(name="P1")], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        snap = data[0]["snapshots"][0]
        for k in ["name", "optimal_interval_days", "frequency_label",
                   "apy_improvement_pct", "additional_yield_usd"]:
            self.assertIn(k, snap)

    def test_log_recovers_from_corrupt(self):
        cfg = tmp_cfg()
        with open(cfg["log_path"], "w") as fh:
            fh.write("CORRUPT")
        self.opt.optimize([make_position()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_position_count(self):
        cfg = tmp_cfg()
        self.opt.optimize(
            [make_position("A"), make_position("B")],
            cfg=cfg, write_log=True
        )
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["position_count"], 2)


if __name__ == "__main__":
    unittest.main()

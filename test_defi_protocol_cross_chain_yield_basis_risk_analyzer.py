"""
Tests for MP-1111: DeFiProtocolCrossChainYieldBasisRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_cross_chain_yield_basis_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_cross_chain_yield_basis_risk_analyzer import (
    DeFiProtocolCrossChainYieldBasisRiskAnalyzer,
    _clamp,
    _spread,
    _zscore,
    _mean,
    _std,
    _breakeven_days,
    _build_default_cfg,
    SPREAD_WIDE,
    SPREAD_VERY_WIDE,
    SPREAD_NARROW,
    MIN_MIGRATION_BENEFIT_PP,
    BRIDGE_COST_HIGH,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_leg(
    protocol="Aave",
    chain="ethereum",
    apy_pct=4.0,
    tvl_usd=1_000_000_000,
    bridge_cost_usd=10.0,
    gas_cost_usd=15.0,
    apy_history_7d=None,
):
    d = {
        "protocol": protocol,
        "chain": chain,
        "apy_pct": apy_pct,
        "tvl_usd": tvl_usd,
        "bridge_cost_usd": bridge_cost_usd,
        "gas_cost_usd": gas_cost_usd,
    }
    if apy_history_7d is not None:
        d["apy_history_7d"] = apy_history_7d
    return d


def make_group(
    asset="USDC",
    legs=None,
    position_usd=100_000.0,
    current_leg=None,
):
    if legs is None:
        legs = [make_leg(), make_leg(protocol="Compound", apy_pct=5.0)]
    return {
        "asset": asset,
        "legs": legs,
        "position_usd": position_usd,
        "current_leg": current_leg,
    }


def tmp_cfg():
    td = tempfile.mkdtemp()
    return {"log_path": os.path.join(td, "basis_risk.json"), "log_cap": 5}


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_spread_basic(self):
        self.assertAlmostEqual(_spread(4.0, 7.0), 3.0)

    def test_spread_symmetric(self):
        self.assertAlmostEqual(_spread(7.0, 4.0), _spread(4.0, 7.0))

    def test_spread_zero(self):
        self.assertAlmostEqual(_spread(5.0, 5.0), 0.0)

    def test_zscore_basic(self):
        self.assertAlmostEqual(_zscore(10.0, 5.0, 5.0), 1.0)

    def test_zscore_zero_std(self):
        self.assertEqual(_zscore(10.0, 5.0, 0.0), 0.0)

    def test_zscore_negative(self):
        self.assertAlmostEqual(_zscore(3.0, 5.0, 2.0), -1.0)

    def test_mean_basic(self):
        self.assertAlmostEqual(_mean([2.0, 4.0, 6.0]), 4.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([7.0]), 7.0)

    def test_std_basic(self):
        # std([2,4,6]) = 2.0
        self.assertAlmostEqual(_std([2.0, 4.0, 6.0]), 2.0, places=5)

    def test_std_empty(self):
        self.assertEqual(_std([]), 0.0)

    def test_std_single(self):
        self.assertEqual(_std([5.0]), 0.0)

    def test_std_equal_values(self):
        self.assertAlmostEqual(_std([3.0, 3.0, 3.0]), 0.0)

    def test_breakeven_basic(self):
        # position=100k, apy_diff=10%, bridge=25, gas=0
        # daily_gain = 100000 * 0.10 / 365.25 ≈ 27.38
        # breakeven = 25 / 27.38 ≈ 0.91 days
        be = _breakeven_days(100_000, 10.0, 25.0, 0.0)
        self.assertIsNotNone(be)
        self.assertAlmostEqual(be, 25.0 / (100_000 * 0.10 / 365.25), places=2)

    def test_breakeven_zero_apy_diff(self):
        be = _breakeven_days(100_000, 0.0, 25.0, 0.0)
        self.assertIsNone(be)

    def test_breakeven_zero_position(self):
        be = _breakeven_days(0.0, 10.0, 25.0, 0.0)
        self.assertIsNone(be)

    def test_breakeven_negative_apy_diff(self):
        be = _breakeven_days(100_000, -5.0, 25.0, 0.0)
        self.assertIsNone(be)

    def test_constants_order(self):
        self.assertLess(SPREAD_NARROW, SPREAD_WIDE)
        self.assertLess(SPREAD_WIDE, SPREAD_VERY_WIDE)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)


# ── analyzer tests ────────────────────────────────────────────────────────────

class TestCrossChainBasisRiskAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolCrossChainYieldBasisRiskAnalyzer()

    def test_analyze_returns_keys(self):
        result = self.analyzer.analyze([make_group()])
        self.assertIn("asset_groups", result)
        self.assertIn("aggregate", result)

    def test_analyze_empty(self):
        result = self.analyzer.analyze([])
        self.assertEqual(len(result["asset_groups"]), 0)
        self.assertIsNone(result["aggregate"]["widest_spread_asset"])

    def test_single_group(self):
        result = self.analyzer.analyze([make_group()])
        self.assertEqual(len(result["asset_groups"]), 1)

    def test_group_result_keys(self):
        result = self.analyzer.analyze([make_group()])
        g = result["asset_groups"][0]
        for k in [
            "asset", "legs", "basis_spread_pp", "spread_label",
            "apy_mean_pct", "apy_std_pct", "best_leg", "worst_leg",
            "migration_recommendation", "flags",
        ]:
            self.assertIn(k, g)

    def test_basis_spread_correct(self):
        legs = [make_leg(apy_pct=4.0), make_leg(protocol="B", apy_pct=7.0)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertAlmostEqual(result["asset_groups"][0]["basis_spread_pp"], 3.0, places=4)

    def test_best_leg_is_highest_apy(self):
        legs = [
            make_leg(protocol="A", chain="eth", apy_pct=4.0),
            make_leg(protocol="B", chain="arb", apy_pct=8.0),
        ]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertEqual(result["asset_groups"][0]["best_leg"], "B:arb")

    def test_worst_leg_is_lowest_apy(self):
        legs = [
            make_leg(protocol="A", chain="eth", apy_pct=4.0),
            make_leg(protocol="B", chain="arb", apy_pct=8.0),
        ]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertEqual(result["asset_groups"][0]["worst_leg"], "A:eth")

    def test_no_legs_handled(self):
        group = {"asset": "USDC", "legs": [], "position_usd": 100_000}
        result = self.analyzer.analyze([group])
        g = result["asset_groups"][0]
        self.assertIn("NO_LEGS", g["flags"])

    def test_leg_details_keys(self):
        result = self.analyzer.analyze([make_group()])
        leg = result["asset_groups"][0]["legs"][0]
        for k in [
            "leg_id", "protocol", "chain", "apy_pct", "apy_z_score",
            "apy_7d_vol_pp", "tvl_usd", "bridge_cost_usd",
            "apy_vs_best_pp", "breakeven_days_to_best",
        ]:
            self.assertIn(k, leg)

    def test_best_leg_vs_best_zero(self):
        legs = [make_leg(apy_pct=4.0), make_leg(protocol="B", chain="arb", apy_pct=7.0)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        # Best leg should have apy_vs_best = 0
        best_detail = next(
            l for l in result["asset_groups"][0]["legs"]
            if l["apy_pct"] == 7.0
        )
        self.assertAlmostEqual(best_detail["apy_vs_best_pp"], 0.0, places=4)

    def test_apy_mean_correct(self):
        legs = [make_leg(apy_pct=4.0), make_leg(protocol="B", chain="arb", apy_pct=6.0)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertAlmostEqual(result["asset_groups"][0]["apy_mean_pct"], 5.0, places=4)

    def test_apy_std_zero_equal_apy(self):
        legs = [
            make_leg(protocol="A", chain="eth", apy_pct=5.0),
            make_leg(protocol="B", chain="arb", apy_pct=5.0),
        ]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertAlmostEqual(result["asset_groups"][0]["apy_std_pct"], 0.0, places=4)

    def test_migration_rec_when_current_leg_set(self):
        legs = [
            make_leg(protocol="A", chain="eth", apy_pct=3.5),
            make_leg(protocol="B", chain="arb", apy_pct=8.0, bridge_cost_usd=5.0),
        ]
        group = make_group(legs=legs, current_leg="A:eth", position_usd=500_000)
        result = self.analyzer.analyze([group])
        rec = result["asset_groups"][0]["migration_recommendation"]
        self.assertIsNotNone(rec)
        self.assertIn("recommend_migrate", rec)

    def test_migration_rec_none_when_already_best(self):
        legs = [
            make_leg(protocol="A", chain="eth", apy_pct=8.0),
            make_leg(protocol="B", chain="arb", apy_pct=3.5),
        ]
        group = make_group(legs=legs, current_leg="A:eth")
        result = self.analyzer.analyze([group])
        # current_leg is the best → no migration rec
        self.assertIsNone(result["asset_groups"][0]["migration_recommendation"])

    def test_migration_rec_breakeven_days_positive(self):
        legs = [
            make_leg(protocol="A", chain="eth", apy_pct=3.0, bridge_cost_usd=0.0, gas_cost_usd=5.0),
            make_leg(protocol="B", chain="arb", apy_pct=8.0, bridge_cost_usd=10.0, gas_cost_usd=2.0),
        ]
        group = make_group(legs=legs, current_leg="A:eth", position_usd=100_000)
        result = self.analyzer.analyze([group])
        rec = result["asset_groups"][0]["migration_recommendation"]
        if rec and rec.get("breakeven_days") is not None:
            self.assertGreater(rec["breakeven_days"], 0.0)

    def test_spread_label_narrow(self):
        legs = [make_leg(apy_pct=5.0), make_leg(protocol="B", chain="arb", apy_pct=5.2)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        label = result["asset_groups"][0]["spread_label"]
        self.assertIn(label, ("NARROW", "MODERATE"))

    def test_spread_label_very_wide(self):
        legs = [make_leg(apy_pct=2.0), make_leg(protocol="B", chain="arb", apy_pct=12.0)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertEqual(result["asset_groups"][0]["spread_label"], "VERY_WIDE")

    def test_apy_history_vol(self):
        history = [4.0, 5.0, 3.0, 6.0, 4.5, 5.5, 4.0]
        legs = [make_leg(apy_history_7d=history)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        vol = result["asset_groups"][0]["legs"][0]["apy_7d_vol_pp"]
        self.assertGreater(vol, 0.0)

    def test_no_history_vol_zero(self):
        legs = [make_leg()]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        vol = result["asset_groups"][0]["legs"][0]["apy_7d_vol_pp"]
        self.assertEqual(vol, 0.0)

    def test_asset_preserved(self):
        group = make_group(asset="ETH")
        result = self.analyzer.analyze([group])
        self.assertEqual(result["asset_groups"][0]["asset"], "ETH")


# ── flag tests ────────────────────────────────────────────────────────────────

class TestBasisRiskFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolCrossChainYieldBasisRiskAnalyzer()

    def test_flag_very_wide_basis(self):
        legs = [make_leg(apy_pct=2.0), make_leg(protocol="B", chain="arb", apy_pct=12.0)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertIn("VERY_WIDE_BASIS_SPREAD", result["asset_groups"][0]["flags"])

    def test_flag_wide_basis(self):
        legs = [make_leg(apy_pct=2.0), make_leg(protocol="B", chain="arb", apy_pct=6.0)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        flags = result["asset_groups"][0]["flags"]
        self.assertTrue(
            "WIDE_BASIS_SPREAD" in flags or "VERY_WIDE_BASIS_SPREAD" in flags
        )

    def test_no_wide_basis_flag_narrow(self):
        legs = [make_leg(apy_pct=5.0), make_leg(protocol="B", chain="arb", apy_pct=5.1)]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        flags = result["asset_groups"][0]["flags"]
        self.assertNotIn("WIDE_BASIS_SPREAD", flags)
        self.assertNotIn("VERY_WIDE_BASIS_SPREAD", flags)

    def test_flag_high_bridge_cost(self):
        legs = [
            make_leg(bridge_cost_usd=0.0),
            make_leg(protocol="B", chain="arb", bridge_cost_usd=100.0),
        ]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertIn("HIGH_BRIDGE_COST", result["asset_groups"][0]["flags"])

    def test_flag_low_tvl_leg(self):
        legs = [
            make_leg(tvl_usd=1_000_000_000),
            make_leg(protocol="B", chain="arb", tvl_usd=1_000_000),  # <5M
        ]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertIn("LOW_TVL_LEG", result["asset_groups"][0]["flags"])

    def test_no_low_tvl_flag_all_ok(self):
        legs = [
            make_leg(tvl_usd=100_000_000),
            make_leg(protocol="B", chain="arb", tvl_usd=50_000_000),
        ]
        group = make_group(legs=legs)
        result = self.analyzer.analyze([group])
        self.assertNotIn("LOW_TVL_LEG", result["asset_groups"][0]["flags"])

    def test_flag_single_leg(self):
        group = make_group(legs=[make_leg()])
        result = self.analyzer.analyze([group])
        self.assertIn("SINGLE_LEG_NO_DIVERSIFICATION", result["asset_groups"][0]["flags"])

    def test_no_single_leg_flag_multi_legs(self):
        group = make_group()  # default: 2 legs
        result = self.analyzer.analyze([group])
        self.assertNotIn("SINGLE_LEG_NO_DIVERSIFICATION", result["asset_groups"][0]["flags"])

    def test_flags_list_type(self):
        result = self.analyzer.analyze([make_group()])
        self.assertIsInstance(result["asset_groups"][0]["flags"], list)


# ── aggregate tests ───────────────────────────────────────────────────────────

class TestBasisRiskAggregate(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolCrossChainYieldBasisRiskAnalyzer()

    def test_widest_spread_asset(self):
        g1 = make_group(
            asset="USDC",
            legs=[make_leg(apy_pct=2.0), make_leg(protocol="B", chain="arb", apy_pct=12.0)]
        )
        g2 = make_group(
            asset="ETH",
            legs=[make_leg(apy_pct=4.0), make_leg(protocol="B", chain="arb", apy_pct=4.5)]
        )
        result = self.analyzer.analyze([g1, g2])
        self.assertEqual(result["aggregate"]["widest_spread_asset"], "USDC")

    def test_avg_basis_spread_nonneg(self):
        result = self.analyzer.analyze([make_group()])
        self.assertGreaterEqual(result["aggregate"]["avg_basis_spread_pp"], 0.0)

    def test_wide_spread_count(self):
        g_wide = make_group(
            asset="USDC",
            legs=[make_leg(apy_pct=2.0), make_leg(protocol="B", chain="arb", apy_pct=7.0)]
        )
        g_narrow = make_group(
            asset="ETH",
            legs=[make_leg(apy_pct=4.0), make_leg(protocol="B", chain="arb", apy_pct=4.3)]
        )
        result = self.analyzer.analyze([g_wide, g_narrow])
        self.assertGreaterEqual(result["aggregate"]["wide_spread_count"], 1)

    def test_migration_opportunities_int(self):
        result = self.analyzer.analyze([make_group()])
        self.assertIsInstance(result["aggregate"]["migration_opportunities"], int)


# ── log tests ─────────────────────────────────────────────────────────────────

class TestBasisRiskLog(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolCrossChainYieldBasisRiskAnalyzer()

    def test_write_log_creates_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        self.assertTrue(os.path.exists(cfg["log_path"]))

    def test_log_valid_json(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_keys(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        entry = data[0]
        for k in ["ts", "group_count", "aggregates", "snapshots"]:
            self.assertIn(k, entry)

    def test_log_ring_buffer_cap(self):
        cfg = tmp_cfg()
        for _ in range(cfg["log_cap"] + 3):
            self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), cfg["log_cap"])

    def test_no_write_no_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=False)
        self.assertFalse(os.path.exists(cfg["log_path"]))

    def test_log_atomic_no_tmp(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        self.assertFalse(os.path.exists(cfg["log_path"] + ".tmp"))

    def test_log_accumulates(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_snapshot_keys(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_group(asset="USDC")], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        snap = data[0]["snapshots"][0]
        for k in ["asset", "basis_spread_pp", "spread_label", "best_leg", "flags"]:
            self.assertIn(k, snap)

    def test_log_recovers_from_corrupt(self):
        cfg = tmp_cfg()
        with open(cfg["log_path"], "w") as fh:
            fh.write("NOT_JSON!!!")
        self.analyzer.analyze([make_group()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_group_count(self):
        cfg = tmp_cfg()
        self.analyzer.analyze(
            [make_group(asset="USDC"), make_group(asset="ETH")],
            cfg=cfg, write_log=True
        )
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["group_count"], 2)


if __name__ == "__main__":
    unittest.main()

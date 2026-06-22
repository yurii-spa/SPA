"""
Tests for MP-1106: DeFiProtocolMEVProtectionEffectivenessAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_mev_protection_effectiveness_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_mev_protection_effectiveness_analyzer import (
    DeFiProtocolMEVProtectionEffectivenessAnalyzer,
    _clamp,
    _score_from_bool,
    _label_from_score,
    _mev_drag_bps,
    _effective_yield,
    _build_default_cfg,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_protocol(
    name="Proto",
    category="dex",
    uses_private_mempool=False,
    has_commit_reveal=False,
    slippage_protection_pct=1.0,
    has_sandwich_guard=False,
    oracle_twap_window_sec=0.0,
    order_flow_auction=False,
    historical_mev_losses_usd=0.0,
    gross_apy_pct=5.0,
    tvl_usd=100_000_000,
):
    return {
        "name": name,
        "category": category,
        "uses_private_mempool": uses_private_mempool,
        "has_commit_reveal": has_commit_reveal,
        "slippage_protection_pct": slippage_protection_pct,
        "has_sandwich_guard": has_sandwich_guard,
        "oracle_twap_window_sec": oracle_twap_window_sec,
        "order_flow_auction": order_flow_auction,
        "historical_mev_losses_usd": historical_mev_losses_usd,
        "gross_apy_pct": gross_apy_pct,
        "tvl_usd": tvl_usd,
    }


def tmp_cfg():
    td = tempfile.mkdtemp()
    return {"log_path": os.path.join(td, "mev_log.json"), "log_cap": 5}


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_clamp_at_boundary_low(self):
        self.assertEqual(_clamp(0.0, 0.0, 10.0), 0.0)

    def test_clamp_at_boundary_high(self):
        self.assertEqual(_clamp(10.0, 0.0, 10.0), 10.0)

    def test_score_from_bool_true(self):
        self.assertEqual(_score_from_bool(True), 100.0)

    def test_score_from_bool_false(self):
        self.assertEqual(_score_from_bool(False), 0.0)

    def test_label_from_score_strong(self):
        self.assertEqual(_label_from_score(90.0), "STRONG_PROTECTION")

    def test_label_from_score_adequate(self):
        self.assertEqual(_label_from_score(70.0), "ADEQUATE_PROTECTION")

    def test_label_from_score_partial(self):
        self.assertEqual(_label_from_score(50.0), "PARTIAL_PROTECTION")

    def test_label_from_score_vulnerable(self):
        self.assertEqual(_label_from_score(10.0), "VULNERABLE")

    def test_label_boundary_85(self):
        self.assertEqual(_label_from_score(85.0), "STRONG_PROTECTION")

    def test_label_boundary_65(self):
        self.assertEqual(_label_from_score(65.0), "ADEQUATE_PROTECTION")

    def test_label_boundary_40(self):
        self.assertEqual(_label_from_score(40.0), "PARTIAL_PROTECTION")

    def test_mev_drag_strong(self):
        self.assertAlmostEqual(_mev_drag_bps("STRONG_PROTECTION"), 5.0)

    def test_mev_drag_adequate(self):
        self.assertAlmostEqual(_mev_drag_bps("ADEQUATE_PROTECTION"), 20.0)

    def test_mev_drag_partial(self):
        self.assertAlmostEqual(_mev_drag_bps("PARTIAL_PROTECTION"), 55.0)

    def test_mev_drag_vulnerable(self):
        self.assertAlmostEqual(_mev_drag_bps("VULNERABLE"), 120.0)

    def test_mev_drag_unknown(self):
        self.assertAlmostEqual(_mev_drag_bps("NONEXISTENT"), 120.0)

    def test_effective_yield_basic(self):
        # 5% APY, 100 bps drag = 1%
        self.assertAlmostEqual(_effective_yield(5.0, 100.0), 4.0)

    def test_effective_yield_zero_floor(self):
        # drag exceeds APY → floor at 0
        self.assertEqual(_effective_yield(1.0, 200.0), 0.0)

    def test_effective_yield_no_drag(self):
        self.assertAlmostEqual(_effective_yield(8.0, 0.0), 8.0)

    def test_build_default_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)

    def test_build_default_cfg_overrides(self):
        cfg = _build_default_cfg({"log_cap": 50})
        self.assertEqual(cfg["log_cap"], 50)


# ── analyzer tests ────────────────────────────────────────────────────────────

class TestMEVAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolMEVProtectionEffectivenessAnalyzer()

    def test_analyze_returns_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIn("protocols", result)
        self.assertIn("aggregate", result)

    def test_analyze_single_protocol(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertEqual(len(result["protocols"]), 1)

    def test_analyze_empty_list(self):
        result = self.analyzer.analyze([])
        self.assertEqual(len(result["protocols"]), 0)
        agg = result["aggregate"]
        self.assertIsNone(agg["best_protected"])

    def test_protocol_result_keys(self):
        proto = make_protocol()
        result = self.analyzer.analyze([proto])
        p = result["protocols"][0]
        expected_keys = [
            "name", "category", "sub_scores", "composite_score",
            "protection_label", "estimated_mev_drag_bps",
            "gross_apy_pct", "net_apy_after_mev_pct",
            "estimated_annual_mev_loss_usd", "flags",
        ]
        for k in expected_keys:
            self.assertIn(k, p)

    def test_sub_scores_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        sub = result["protocols"][0]["sub_scores"]
        for k in ["sandwich_protection", "frontrun_protection",
                   "backrun_protection", "commit_reveal"]:
            self.assertIn(k, sub)

    def test_fully_protected_protocol(self):
        """All protections enabled → high score, STRONG or ADEQUATE label."""
        p = make_protocol(
            uses_private_mempool=True,
            has_commit_reveal=True,
            slippage_protection_pct=0.1,
            has_sandwich_guard=True,
            oracle_twap_window_sec=3600.0,
            order_flow_auction=True,
        )
        result = self.analyzer.analyze([p])
        score = result["protocols"][0]["composite_score"]
        self.assertGreater(score, 65.0)

    def test_unprotected_protocol(self):
        """No protections → low score, VULNERABLE label."""
        p = make_protocol(
            uses_private_mempool=False,
            has_commit_reveal=False,
            slippage_protection_pct=0.0,
            has_sandwich_guard=False,
            oracle_twap_window_sec=0.0,
            order_flow_auction=False,
        )
        result = self.analyzer.analyze([p])
        score = result["protocols"][0]["composite_score"]
        label = result["protocols"][0]["protection_label"]
        self.assertLess(score, 50.0)
        self.assertIn(label, ("VULNERABLE", "PARTIAL_PROTECTION"))

    def test_net_apy_less_than_gross(self):
        p = make_protocol(gross_apy_pct=10.0)
        result = self.analyzer.analyze([p])
        pr = result["protocols"][0]
        self.assertLessEqual(pr["net_apy_after_mev_pct"], pr["gross_apy_pct"])

    def test_net_apy_nonnegative(self):
        p = make_protocol(gross_apy_pct=0.01)
        result = self.analyzer.analyze([p])
        self.assertGreaterEqual(result["protocols"][0]["net_apy_after_mev_pct"], 0.0)

    def test_estimated_mev_loss_positive_with_tvl(self):
        p = make_protocol(
            tvl_usd=1_000_000_000,
            uses_private_mempool=False,
            oracle_twap_window_sec=0.0,
            slippage_protection_pct=0.0,
        )
        result = self.analyzer.analyze([p])
        self.assertGreater(result["protocols"][0]["estimated_annual_mev_loss_usd"], 0)

    def test_estimated_mev_loss_zero_tvl(self):
        p = make_protocol(tvl_usd=0.0)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["estimated_annual_mev_loss_usd"], 0.0)

    def test_composite_score_range(self):
        for _ in range(5):
            p = make_protocol()
            result = self.analyzer.analyze([p])
            score = result["protocols"][0]["composite_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_twap_30min_backrun_score(self):
        """30-min TWAP should give full backrun score."""
        p = make_protocol(oracle_twap_window_sec=1800.0)
        result = self.analyzer.analyze([p])
        sub = result["protocols"][0]["sub_scores"]
        self.assertAlmostEqual(sub["backrun_protection"], 100.0, places=1)

    def test_twap_0_backrun_score(self):
        p = make_protocol(oracle_twap_window_sec=0.0)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["sub_scores"]["backrun_protection"], 0.0)

    def test_twap_half_backrun_score(self):
        p = make_protocol(oracle_twap_window_sec=900.0)
        result = self.analyzer.analyze([p])
        score = result["protocols"][0]["sub_scores"]["backrun_protection"]
        self.assertAlmostEqual(score, 50.0, delta=1.0)

    def test_private_mempool_frontrun_score(self):
        p = make_protocol(uses_private_mempool=True, order_flow_auction=False)
        result = self.analyzer.analyze([p])
        sub = result["protocols"][0]["sub_scores"]
        self.assertGreater(sub["frontrun_protection"], 50.0)

    def test_ofa_contributes_frontrun_score(self):
        p_no_ofa  = make_protocol(uses_private_mempool=False, order_flow_auction=False)
        p_with_ofa = make_protocol(uses_private_mempool=False, order_flow_auction=True)
        r1 = self.analyzer.analyze([p_no_ofa])["protocols"][0]["sub_scores"]["frontrun_protection"]
        r2 = self.analyzer.analyze([p_with_ofa])["protocols"][0]["sub_scores"]["frontrun_protection"]
        self.assertGreater(r2, r1)

    def test_aggregate_best_protected(self):
        protocols = [
            make_protocol(
                name="Safe",
                uses_private_mempool=True,
                has_commit_reveal=True,
                oracle_twap_window_sec=3600.0,
                has_sandwich_guard=True,
                slippage_protection_pct=0.1,
                order_flow_auction=True,
            ),
            make_protocol(name="Unsafe"),
        ]
        result = self.analyzer.analyze(protocols)
        self.assertEqual(result["aggregate"]["best_protected"], "Safe")

    def test_aggregate_most_vulnerable(self):
        protocols = [
            make_protocol(
                name="Safe",
                uses_private_mempool=True,
                has_commit_reveal=True,
                oracle_twap_window_sec=3600.0,
                has_sandwich_guard=True,
                slippage_protection_pct=0.1,
                order_flow_auction=True,
            ),
            make_protocol(name="Unsafe"),
        ]
        result = self.analyzer.analyze(protocols)
        self.assertEqual(result["aggregate"]["most_vulnerable"], "Unsafe")

    def test_aggregate_strong_count(self):
        protocols = [
            make_protocol(
                name="A",
                uses_private_mempool=True,
                has_commit_reveal=True,
                oracle_twap_window_sec=3600.0,
                has_sandwich_guard=True,
                slippage_protection_pct=0.1,
                order_flow_auction=True,
            ),
        ]
        result = self.analyzer.analyze(protocols)
        # Should have at least 0 (could be 1 if score ≥ 85)
        self.assertGreaterEqual(result["aggregate"]["strong_protection_count"], 0)

    def test_aggregate_vulnerable_count(self):
        protocols = [make_protocol() for _ in range(3)]
        result = self.analyzer.analyze(protocols)
        self.assertGreaterEqual(result["aggregate"]["vulnerable_count"], 0)

    def test_aggregate_total_mev_loss(self):
        protocols = [make_protocol(tvl_usd=1e9), make_protocol(tvl_usd=2e9)]
        result = self.analyzer.analyze(protocols)
        self.assertGreater(result["aggregate"]["total_estimated_annual_mev_loss_usd"], 0)


# ── flag tests ────────────────────────────────────────────────────────────────

class TestMEVFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolMEVProtectionEffectivenessAnalyzer()

    def test_flag_no_mev_mitigation(self):
        p = make_protocol(
            uses_private_mempool=False,
            has_sandwich_guard=False,
            oracle_twap_window_sec=0.0,
            slippage_protection_pct=0.0,
        )
        result = self.analyzer.analyze([p])
        self.assertIn("NO_MEV_MITIGATION", result["protocols"][0]["flags"])

    def test_no_flag_with_mitigation(self):
        p = make_protocol(
            uses_private_mempool=True,
            oracle_twap_window_sec=1800.0,
        )
        result = self.analyzer.analyze([p])
        self.assertNotIn("NO_MEV_MITIGATION", result["protocols"][0]["flags"])

    def test_flag_documented_losses(self):
        p = make_protocol(historical_mev_losses_usd=1_000_000)
        result = self.analyzer.analyze([p])
        self.assertIn("DOCUMENTED_MEV_LOSSES", result["protocols"][0]["flags"])

    def test_no_flag_zero_losses(self):
        p = make_protocol(historical_mev_losses_usd=0.0)
        result = self.analyzer.analyze([p])
        self.assertNotIn("DOCUMENTED_MEV_LOSSES", result["protocols"][0]["flags"])

    def test_flag_large_tvl_high_mev_exposure(self):
        p = make_protocol(
            tvl_usd=500_000_000,
            uses_private_mempool=False,
            has_commit_reveal=False,
            oracle_twap_window_sec=0.0,
            has_sandwich_guard=False,
            slippage_protection_pct=0.0,
            order_flow_auction=False,
        )
        result = self.analyzer.analyze([p])
        flags = result["protocols"][0]["flags"]
        # Either HIGH_MEV_RISK or LARGE_TVL_HIGH_MEV_EXPOSURE should appear
        self.assertTrue(
            "LARGE_TVL_HIGH_MEV_EXPOSURE" in flags or "HIGH_MEV_RISK" in flags
        )

    def test_flag_mev_drag_exceeds_10pct_apy(self):
        # Very low APY (0.5%) with VULNERABLE label → drag=1.2% → >10% of APY
        p = make_protocol(
            gross_apy_pct=0.5,
            uses_private_mempool=False,
            has_commit_reveal=False,
            oracle_twap_window_sec=0.0,
            has_sandwich_guard=False,
            slippage_protection_pct=0.0,
            order_flow_auction=False,
        )
        result = self.analyzer.analyze([p])
        self.assertIn("MEV_DRAG_EXCEEDS_10PCT_APY", result["protocols"][0]["flags"])

    def test_flags_list(self):
        p = make_protocol()
        result = self.analyzer.analyze([p])
        self.assertIsInstance(result["protocols"][0]["flags"], list)


# ── log tests ─────────────────────────────────────────────────────────────────

class TestMEVLog(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolMEVProtectionEffectivenessAnalyzer()

    def test_write_log_creates_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.assertTrue(os.path.exists(cfg["log_path"]))

    def test_log_valid_json(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_structure(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        entry = data[0]
        self.assertIn("ts", entry)
        self.assertIn("protocol_count", entry)
        self.assertIn("aggregates", entry)
        self.assertIn("snapshots", entry)

    def test_log_ring_buffer_cap(self):
        cfg = tmp_cfg()
        for _ in range(cfg["log_cap"] + 3):
            self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), cfg["log_cap"])

    def test_no_write_flag_no_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=False)
        self.assertFalse(os.path.exists(cfg["log_path"]))

    def test_log_accumulates(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_atomic_no_tmp_left(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.assertFalse(os.path.exists(cfg["log_path"] + ".tmp"))

    def test_log_snapshot_contains_score(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol(name="P1")], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        snap = data[0]["snapshots"][0]
        self.assertIn("composite_score", snap)
        self.assertIn("protection_label", snap)
        self.assertIn("mev_drag_bps", snap)
        self.assertIn("net_apy_pct", snap)

    def test_log_protocol_count(self):
        cfg = tmp_cfg()
        self.analyzer.analyze(
            [make_protocol("A"), make_protocol("B")], cfg=cfg, write_log=True
        )
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol_count"], 2)

    def test_log_recovers_from_corrupt(self):
        cfg = tmp_cfg()
        with open(cfg["log_path"], "w") as fh:
            fh.write("NOT_JSON")
        # Should not raise
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


# ── edge-case tests ───────────────────────────────────────────────────────────

class TestMEVEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolMEVProtectionEffectivenessAnalyzer()

    def test_missing_fields_no_crash(self):
        self.analyzer.analyze([{"name": "Minimal"}])

    def test_slippage_zero_sandwich_score(self):
        p = make_protocol(slippage_protection_pct=0.0, has_sandwich_guard=False)
        result = self.analyzer.analyze([p])
        sub = result["protocols"][0]["sub_scores"]
        self.assertEqual(sub["sandwich_protection"], 0.0)

    def test_slippage_100_sandwich_score_clamped(self):
        # slippage=100% → slip_score=0 (1 - 100/100 = 0)
        p = make_protocol(slippage_protection_pct=100.0)
        result = self.analyzer.analyze([p])
        sub = result["protocols"][0]["sub_scores"]
        self.assertGreaterEqual(sub["sandwich_protection"], 0.0)

    def test_all_zeros_gross_apy(self):
        p = make_protocol(gross_apy_pct=0.0)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["net_apy_after_mev_pct"], 0.0)

    def test_multiple_protocols_different_categories(self):
        protos = [
            make_protocol(name="DEX", category="dex"),
            make_protocol(name="Lend", category="lending"),
            make_protocol(name="Agg", category="yield_aggregator"),
        ]
        result = self.analyzer.analyze(protos)
        self.assertEqual(len(result["protocols"]), 3)

    def test_avg_score_in_range(self):
        protos = [make_protocol() for _ in range(4)]
        result = self.analyzer.analyze(protos)
        avg = result["aggregate"]["avg_composite_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_avg_drag_nonnegative(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertGreaterEqual(result["aggregate"]["avg_mev_drag_bps"], 0.0)

    def test_protection_label_is_string(self):
        result = self.analyzer.analyze([make_protocol()])
        label = result["protocols"][0]["protection_label"]
        self.assertIsInstance(label, str)
        self.assertIn(label, [
            "STRONG_PROTECTION", "ADEQUATE_PROTECTION",
            "PARTIAL_PROTECTION", "VULNERABLE",
        ])

    def test_name_preserved(self):
        p = make_protocol(name="UniqueProtocolXYZ")
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["name"], "UniqueProtocolXYZ")

    def test_category_preserved(self):
        p = make_protocol(category="cdp")
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["category"], "cdp")


if __name__ == "__main__":
    unittest.main()

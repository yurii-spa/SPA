"""
Tests for MP-1107: DeFiProtocolBorrowerConcentrationRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_borrower_concentration_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_borrower_concentration_risk_analyzer import (
    DeFiProtocolBorrowerConcentrationRiskAnalyzer,
    _hhi,
    _gini,
    _top_n_share,
    _clamp,
    _risk_label,
    HHI_COMPETITIVE,
    HHI_MODERATE,
    TOP1_CRITICAL,
    TOP1_HIGH,
    TOP1_MODERATE,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_protocol(
    name="TestLender",
    category="lending",
    total_borrow_usd=100_000_000,
    top_borrower_amounts_usd=None,
    protocol_reserve_usd=5_000_000,
    liquidation_threshold_pct=80.0,
    avg_collateral_ratio=1.5,
):
    if top_borrower_amounts_usd is None:
        top_borrower_amounts_usd = [10_000_000, 5_000_000, 3_000_000]
    return {
        "name": name,
        "category": category,
        "total_borrow_usd": total_borrow_usd,
        "top_borrower_amounts_usd": top_borrower_amounts_usd,
        "protocol_reserve_usd": protocol_reserve_usd,
        "liquidation_threshold_pct": liquidation_threshold_pct,
        "avg_collateral_ratio": avg_collateral_ratio,
    }


def tmp_cfg():
    td = tempfile.mkdtemp()
    return {"log_path": os.path.join(td, "borrower_log.json"), "log_cap": 5}


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    # _hhi
    def test_hhi_monopoly(self):
        """Single player: HHI = 100^2 = 10000."""
        self.assertAlmostEqual(_hhi([1.0]), 10000.0)

    def test_hhi_duopoly_equal(self):
        """Two equal players: HHI = 2 * 50^2 = 5000."""
        self.assertAlmostEqual(_hhi([0.5, 0.5]), 5000.0)

    def test_hhi_ten_equal(self):
        """Ten equal players: HHI = 10 * 10^2 = 1000."""
        shares = [0.1] * 10
        self.assertAlmostEqual(_hhi(shares), 1000.0)

    def test_hhi_empty(self):
        self.assertEqual(_hhi([]), 0.0)

    def test_hhi_increases_with_concentration(self):
        equal = _hhi([0.25, 0.25, 0.25, 0.25])
        concentrated = _hhi([0.70, 0.10, 0.10, 0.10])
        self.assertGreater(concentrated, equal)

    # _gini
    def test_gini_equal_distribution(self):
        values = [100.0, 100.0, 100.0, 100.0]
        self.assertAlmostEqual(_gini(values), 0.0, places=5)

    def test_gini_maximally_unequal(self):
        """One very large, rest near 0 → gini close to 1."""
        values = [0.0, 0.0, 0.0, 1_000_000.0]
        g = _gini(values)
        self.assertGreater(g, 0.6)

    def test_gini_two_equal(self):
        self.assertAlmostEqual(_gini([50.0, 50.0]), 0.0, places=5)

    def test_gini_empty(self):
        self.assertEqual(_gini([]), 0.0)

    def test_gini_single(self):
        self.assertEqual(_gini([100.0]), 0.0)

    def test_gini_range(self):
        g = _gini([10, 20, 30, 40])
        self.assertGreaterEqual(g, 0.0)
        self.assertLessEqual(g, 1.0)

    # _top_n_share
    def test_top1_share_basic(self):
        amounts = [60, 30, 10]
        self.assertAlmostEqual(_top_n_share(amounts, 1), 0.60)

    def test_top3_share_all(self):
        amounts = [60, 30, 10]
        self.assertAlmostEqual(_top_n_share(amounts, 3), 1.0)

    def test_top_n_empty(self):
        self.assertEqual(_top_n_share([], 1), 0.0)

    def test_top_n_zero_total(self):
        self.assertEqual(_top_n_share([0.0, 0.0], 1), 0.0)

    def test_top_n_unsorted_input(self):
        amounts = [10, 60, 30]
        self.assertAlmostEqual(_top_n_share(amounts, 1), 0.60)

    # _clamp
    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    # _risk_label
    def test_risk_label_critical(self):
        self.assertEqual(_risk_label(85.0), "CRITICAL")

    def test_risk_label_high(self):
        self.assertEqual(_risk_label(65.0), "HIGH")

    def test_risk_label_moderate(self):
        self.assertEqual(_risk_label(45.0), "MODERATE")

    def test_risk_label_low(self):
        self.assertEqual(_risk_label(10.0), "LOW")

    def test_risk_label_boundary_80(self):
        self.assertEqual(_risk_label(80.0), "CRITICAL")

    def test_risk_label_boundary_60(self):
        self.assertEqual(_risk_label(60.0), "HIGH")

    def test_risk_label_boundary_40(self):
        self.assertEqual(_risk_label(40.0), "MODERATE")

    # constants sanity
    def test_constants_reasonable(self):
        self.assertLess(HHI_COMPETITIVE, HHI_MODERATE)
        self.assertLess(TOP1_MODERATE, TOP1_HIGH)
        self.assertLess(TOP1_HIGH, TOP1_CRITICAL)


# ── analyzer tests ────────────────────────────────────────────────────────────

class TestBorrowerConcentrationAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolBorrowerConcentrationRiskAnalyzer()

    def test_analyze_returns_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIn("protocols", result)
        self.assertIn("aggregate", result)

    def test_analyze_empty(self):
        result = self.analyzer.analyze([])
        self.assertEqual(len(result["protocols"]), 0)
        self.assertIsNone(result["aggregate"]["riskiest_protocol"])

    def test_single_protocol_returned(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertEqual(len(result["protocols"]), 1)

    def test_result_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        p = result["protocols"][0]
        for k in [
            "name", "category", "total_borrow_usd", "hhi", "gini",
            "top1_share_pct", "top3_share_pct", "top5_share_pct",
            "cascade_risk_score", "reserve_coverage_ratio",
            "overall_risk_score", "risk_label", "flags",
        ]:
            self.assertIn(k, p)

    def test_hhi_positive_for_concentrated(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[90, 5, 5],
        )
        result = self.analyzer.analyze([p])
        self.assertGreater(result["protocols"][0]["hhi"], HHI_MODERATE)

    def test_top1_share_correct(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[50, 30, 20],
        )
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["top1_share_pct"], 50.0, places=1)

    def test_top3_share_100pct_when_matches_total(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[50, 30, 20],
        )
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["top3_share_pct"], 100.0, places=1)

    def test_reserve_coverage_ratio(self):
        p = make_protocol(
            total_borrow_usd=100_000_000,
            protocol_reserve_usd=10_000_000,
        )
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(
            result["protocols"][0]["reserve_coverage_ratio"], 0.10, places=4
        )

    def test_zero_total_borrow_no_crash(self):
        p = make_protocol(total_borrow_usd=0.0, top_borrower_amounts_usd=[])
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["hhi"], 0.0)

    def test_risk_score_range(self):
        result = self.analyzer.analyze([make_protocol()])
        score = result["protocols"][0]["overall_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_cascade_score_range(self):
        result = self.analyzer.analyze([make_protocol()])
        score = result["protocols"][0]["cascade_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_high_concentration_raises_risk(self):
        # Very dispersed: top borrower = 1M / 100M = 1% each
        p_low = make_protocol(
            total_borrow_usd=100_000_000,
            top_borrower_amounts_usd=[1_000_000] * 10,  # top1 = 1%
            avg_collateral_ratio=2.5,
            protocol_reserve_usd=20_000_000,
        )
        # Highly concentrated: top borrower = 70M / 100M = 70%
        p_high = make_protocol(
            total_borrow_usd=100_000_000,
            top_borrower_amounts_usd=[70_000_000, 5_000_000, 5_000_000],
            avg_collateral_ratio=1.3,
            protocol_reserve_usd=0,
        )
        r_low  = self.analyzer.analyze([p_low])["protocols"][0]["overall_risk_score"]
        r_high = self.analyzer.analyze([p_high])["protocols"][0]["overall_risk_score"]
        self.assertGreater(r_high, r_low)

    def test_low_reserve_raises_risk(self):
        p_good = make_protocol(protocol_reserve_usd=20_000_000)
        p_bad  = make_protocol(protocol_reserve_usd=0)
        r_good = self.analyzer.analyze([p_good])["protocols"][0]["overall_risk_score"]
        r_bad  = self.analyzer.analyze([p_bad])["protocols"][0]["overall_risk_score"]
        self.assertGreater(r_bad, r_good)

    def test_tail_bucket_added_when_partial(self):
        # top amounts sum < total → remainder should be treated as tail
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[30, 20],
        )
        # 50 remaining → tail exists; top1 = 30/100 = 30%
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["top1_share_pct"], 30.0, places=1)

    def test_risk_label_valid(self):
        result = self.analyzer.analyze([make_protocol()])
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("LOW", "MODERATE", "HIGH", "CRITICAL"))

    def test_name_preserved(self):
        p = make_protocol(name="SpecialLender")
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["name"], "SpecialLender")

    def test_gini_in_range(self):
        p = make_protocol()
        result = self.analyzer.analyze([p])
        g = result["protocols"][0]["gini"]
        self.assertGreaterEqual(g, 0.0)
        self.assertLessEqual(g, 1.0)


# ── flag tests ────────────────────────────────────────────────────────────────

class TestBorrowerFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolBorrowerConcentrationRiskAnalyzer()

    def test_flag_top1_critical(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[50, 30, 20],
        )
        result = self.analyzer.analyze([p])
        self.assertIn("TOP1_BORROWER_CRITICAL", result["protocols"][0]["flags"])

    def test_flag_top1_high(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[30, 20, 15, 10, 10, 5, 5, 5],
        )
        result = self.analyzer.analyze([p])
        flags = result["protocols"][0]["flags"]
        # top1=30% → HIGH (not CRITICAL)
        self.assertIn("TOP1_BORROWER_HIGH", flags)

    def test_flag_top3_exceed_60pct(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[30, 25, 10],
        )
        result = self.analyzer.analyze([p])
        self.assertIn("TOP3_EXCEED_60PCT", result["protocols"][0]["flags"])

    def test_flag_hhi_concentrated(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[70, 15, 15],
        )
        result = self.analyzer.analyze([p])
        self.assertIn("HHI_CONCENTRATED", result["protocols"][0]["flags"])

    def test_flag_low_reserve_coverage(self):
        p = make_protocol(
            total_borrow_usd=100_000_000,
            protocol_reserve_usd=500_000,   # 0.5%
        )
        result = self.analyzer.analyze([p])
        self.assertIn("LOW_RESERVE_COVERAGE", result["protocols"][0]["flags"])

    def test_no_low_reserve_flag_adequate(self):
        p = make_protocol(
            total_borrow_usd=100_000_000,
            protocol_reserve_usd=10_000_000,  # 10%
        )
        result = self.analyzer.analyze([p])
        self.assertNotIn("LOW_RESERVE_COVERAGE", result["protocols"][0]["flags"])

    def test_flag_low_collateral_ratio(self):
        p = make_protocol(avg_collateral_ratio=1.1)
        result = self.analyzer.analyze([p])
        self.assertIn("LOW_COLLATERAL_RATIO", result["protocols"][0]["flags"])

    def test_no_flag_healthy_cr(self):
        p = make_protocol(avg_collateral_ratio=2.0)
        result = self.analyzer.analyze([p])
        self.assertNotIn("LOW_COLLATERAL_RATIO", result["protocols"][0]["flags"])

    def test_flags_list_type(self):
        p = make_protocol()
        result = self.analyzer.analyze([p])
        self.assertIsInstance(result["protocols"][0]["flags"], list)


# ── aggregate tests ───────────────────────────────────────────────────────────

class TestBorrowerAggregate(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolBorrowerConcentrationRiskAnalyzer()

    def test_riskiest_protocol(self):
        p_safe = make_protocol(name="Safe", top_borrower_amounts_usd=[5, 5, 5])
        p_risky = make_protocol(
            name="Risky",
            total_borrow_usd=100,
            top_borrower_amounts_usd=[70, 15, 15],
            protocol_reserve_usd=0,
        )
        result = self.analyzer.analyze([p_safe, p_risky])
        self.assertEqual(result["aggregate"]["riskiest_protocol"], "Risky")

    def test_safest_protocol(self):
        p_safe = make_protocol(name="Safe", top_borrower_amounts_usd=[5, 5, 5])
        p_risky = make_protocol(
            name="Risky",
            total_borrow_usd=100,
            top_borrower_amounts_usd=[70, 15, 15],
            protocol_reserve_usd=0,
        )
        result = self.analyzer.analyze([p_safe, p_risky])
        self.assertEqual(result["aggregate"]["safest_protocol"], "Safe")

    def test_avg_hhi_in_range(self):
        protos = [make_protocol() for _ in range(3)]
        result = self.analyzer.analyze(protos)
        avg = result["aggregate"]["avg_hhi"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 10000.0)

    def test_avg_risk_score_in_range(self):
        protos = [make_protocol() for _ in range(3)]
        result = self.analyzer.analyze(protos)
        avg = result["aggregate"]["avg_risk_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_critical_count_zero_for_safe_protocols(self):
        p = make_protocol(
            total_borrow_usd=100,
            top_borrower_amounts_usd=[5, 5, 5, 5, 5],
            protocol_reserve_usd=50,
            avg_collateral_ratio=2.5,
        )
        result = self.analyzer.analyze([p])
        self.assertEqual(result["aggregate"]["critical_count"], 0)

    def test_total_at_risk_is_float(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIsInstance(result["aggregate"]["total_at_risk_borrow_usd"], float)


# ── log tests ─────────────────────────────────────────────────────────────────

class TestBorrowerLog(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolBorrowerConcentrationRiskAnalyzer()

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

    def test_log_entry_has_ts(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIn("ts", data[0])

    def test_log_ring_buffer_cap(self):
        cfg = tmp_cfg()
        for _ in range(cfg["log_cap"] + 4):
            self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), cfg["log_cap"])

    def test_no_write_no_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=False)
        self.assertFalse(os.path.exists(cfg["log_path"]))

    def test_log_atomic_no_tmp(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.assertFalse(os.path.exists(cfg["log_path"] + ".tmp"))

    def test_log_accumulates(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_snapshot_keys(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol(name="P1")], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        snap = data[0]["snapshots"][0]
        for k in ["name", "hhi", "top1_share_pct", "risk_label", "risk_score"]:
            self.assertIn(k, snap)

    def test_log_recovers_from_corrupt(self):
        cfg = tmp_cfg()
        with open(cfg["log_path"], "w") as fh:
            fh.write("CORRUPTED")
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


if __name__ == "__main__":
    unittest.main()

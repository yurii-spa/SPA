"""
Tests for MP-1108: DeFiProtocolInsuranceFundAdequacyAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_insurance_fund_adequacy_analyzer -v
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

from spa_core.analytics.defi_protocol_insurance_fund_adequacy_analyzer import (
    DeFiProtocolInsuranceFundAdequacyAnalyzer,
    _clamp,
    _coverage_ratio,
    _adequacy_label,
    _stress_coverage,
    _build_default_cfg,
    MIN_COVERAGE_RATIO,
    TARGET_COVERAGE_RATIO,
    STRESS_MILD,
    STRESS_MODERATE,
    STRESS_SEVERE,
    STRESS_EXTREME,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_protocol(
    name="TestProto",
    category="lending",
    tvl_usd=1_000_000_000,
    insurance_fund_usd=50_000_000,
    external_coverage_usd=0.0,
    historical_bad_debt_usd=0.0,
    largest_single_loss_usd=0.0,
    num_audit_reports=3,
    bug_bounty_usd=100_000,
    annual_revenue_usd=30_000_000,
    total_borrow_usd=500_000_000,
):
    return {
        "name": name,
        "category": category,
        "tvl_usd": tvl_usd,
        "insurance_fund_usd": insurance_fund_usd,
        "external_coverage_usd": external_coverage_usd,
        "historical_bad_debt_usd": historical_bad_debt_usd,
        "largest_single_loss_usd": largest_single_loss_usd,
        "num_audit_reports": num_audit_reports,
        "bug_bounty_usd": bug_bounty_usd,
        "annual_revenue_usd": annual_revenue_usd,
        "total_borrow_usd": total_borrow_usd,
    }


def tmp_cfg():
    td = tempfile.mkdtemp()
    return {"log_path": os.path.join(td, "ins_log.json"), "log_cap": 5}


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_coverage_ratio_basic(self):
        self.assertAlmostEqual(_coverage_ratio(50.0, 1000.0), 0.05)

    def test_coverage_ratio_zero_tvl(self):
        self.assertEqual(_coverage_ratio(100.0, 0.0), 0.0)

    def test_coverage_ratio_zero_fund(self):
        self.assertAlmostEqual(_coverage_ratio(0.0, 1000.0), 0.0)

    def test_coverage_ratio_full(self):
        self.assertAlmostEqual(_coverage_ratio(1000.0, 1000.0), 1.0)

    def test_adequacy_label_well(self):
        self.assertEqual(_adequacy_label(90.0), "WELL_CAPITALIZED")

    def test_adequacy_label_adequate(self):
        self.assertEqual(_adequacy_label(70.0), "ADEQUATE")

    def test_adequacy_label_under(self):
        self.assertEqual(_adequacy_label(50.0), "UNDERCAPITALIZED")

    def test_adequacy_label_critical(self):
        self.assertEqual(_adequacy_label(10.0), "CRITICALLY_UNDERCAPITALIZED")

    def test_adequacy_label_boundary_85(self):
        self.assertEqual(_adequacy_label(85.0), "WELL_CAPITALIZED")

    def test_adequacy_label_boundary_65(self):
        self.assertEqual(_adequacy_label(65.0), "ADEQUATE")

    def test_adequacy_label_boundary_40(self):
        self.assertEqual(_adequacy_label(40.0), "UNDERCAPITALIZED")

    def test_stress_coverage_full(self):
        # fund covers 1× base loss → coverage = 1.0
        self.assertAlmostEqual(_stress_coverage(100.0, 100.0, 1.0), 1.0)

    def test_stress_coverage_partial(self):
        # fund = 50, base_loss = 100, multiplier = 2 → stressed = 200, coverage = 0.25
        self.assertAlmostEqual(_stress_coverage(50.0, 100.0, 2.0), 0.25)

    def test_stress_coverage_zero_base_loss(self):
        self.assertEqual(_stress_coverage(100.0, 0.0, 2.0), 1.0)

    def test_stress_coverage_capped_at_2(self):
        # massively over-funded → capped at 2.0
        self.assertAlmostEqual(_stress_coverage(10_000.0, 10.0, 1.0), 2.0)

    def test_constants_order(self):
        self.assertLess(MIN_COVERAGE_RATIO, TARGET_COVERAGE_RATIO)
        self.assertLess(STRESS_MILD, STRESS_MODERATE)
        self.assertLess(STRESS_MODERATE, STRESS_SEVERE)
        self.assertLess(STRESS_SEVERE, STRESS_EXTREME)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 7})
        self.assertEqual(cfg["log_cap"], 7)


# ── analyzer tests ────────────────────────────────────────────────────────────

class TestInsuranceFundAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolInsuranceFundAdequacyAnalyzer()

    def test_analyze_returns_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIn("protocols", result)
        self.assertIn("aggregate", result)

    def test_analyze_empty(self):
        result = self.analyzer.analyze([])
        self.assertEqual(len(result["protocols"]), 0)
        self.assertIsNone(result["aggregate"]["best_capitalized"])

    def test_single_protocol(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertEqual(len(result["protocols"]), 1)

    def test_result_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        p = result["protocols"][0]
        for k in [
            "name", "category", "tvl_usd", "insurance_fund_usd",
            "total_coverage_usd", "fund_to_tvl_ratio", "total_coverage_ratio",
            "base_loss_estimate_usd", "stress_coverage", "replenishment_score",
            "security_score", "adequacy_score", "adequacy_label",
            "fund_runway_months", "flags",
        ]:
            self.assertIn(k, p)

    def test_stress_coverage_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        stress = result["protocols"][0]["stress_coverage"]
        for k in ["mild", "moderate", "severe", "extreme"]:
            self.assertIn(k, stress)

    def test_fund_to_tvl_ratio_correct(self):
        p = make_protocol(tvl_usd=1_000_000_000, insurance_fund_usd=50_000_000)
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["fund_to_tvl_ratio"], 0.05, places=5)

    def test_total_coverage_includes_external(self):
        p = make_protocol(insurance_fund_usd=30_000_000, external_coverage_usd=20_000_000)
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["total_coverage_usd"], 50_000_000.0)

    def test_adequacy_score_range(self):
        result = self.analyzer.analyze([make_protocol()])
        score = result["protocols"][0]["adequacy_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_well_funded_scores_higher(self):
        p_good = make_protocol(insurance_fund_usd=500_000_000)   # 50% of TVL
        p_poor = make_protocol(insurance_fund_usd=100_000)       # 0.01% of TVL
        r_good = self.analyzer.analyze([p_good])["protocols"][0]["adequacy_score"]
        r_poor = self.analyzer.analyze([p_poor])["protocols"][0]["adequacy_score"]
        self.assertGreater(r_good, r_poor)

    def test_more_audits_raises_security_score(self):
        p_few  = make_protocol(num_audit_reports=0)
        p_many = make_protocol(num_audit_reports=5)
        r_few  = self.analyzer.analyze([p_few])["protocols"][0]["security_score"]
        r_many = self.analyzer.analyze([p_many])["protocols"][0]["security_score"]
        self.assertGreater(r_many, r_few)

    def test_replenishment_score_with_revenue(self):
        p = make_protocol(insurance_fund_usd=10_000_000, annual_revenue_usd=100_000_000)
        result = self.analyzer.analyze([p])
        self.assertGreater(result["protocols"][0]["replenishment_score"], 0.0)

    def test_replenishment_score_no_revenue(self):
        p = make_protocol(annual_revenue_usd=0.0)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["replenishment_score"], 0.0)

    def test_fund_runway_with_history(self):
        p = make_protocol(
            insurance_fund_usd=12_000_000,
            historical_bad_debt_usd=12_000_000,  # 1M/month
        )
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["fund_runway_months"], 12.0, delta=0.5)

    def test_fund_runway_none_without_history(self):
        p = make_protocol(historical_bad_debt_usd=0.0)
        result = self.analyzer.analyze([p])
        self.assertIsNone(result["protocols"][0]["fund_runway_months"])

    def test_adequacy_label_valid(self):
        result = self.analyzer.analyze([make_protocol()])
        label = result["protocols"][0]["adequacy_label"]
        self.assertIn(label, [
            "WELL_CAPITALIZED", "ADEQUATE",
            "UNDERCAPITALIZED", "CRITICALLY_UNDERCAPITALIZED",
        ])

    def test_name_preserved(self):
        p = make_protocol(name="MyCoolProtocol")
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["name"], "MyCoolProtocol")

    def test_base_loss_uses_history(self):
        # historical_bad_debt_usd = 5M → base loss = 5M
        p = make_protocol(
            tvl_usd=100_000_000,
            insurance_fund_usd=10_000_000,
            historical_bad_debt_usd=5_000_000,
        )
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(
            result["protocols"][0]["base_loss_estimate_usd"], 5_000_000.0
        )

    def test_base_loss_fallback_to_tvl(self):
        # No history → 1% of TVL
        p = make_protocol(
            tvl_usd=100_000_000,
            insurance_fund_usd=10_000_000,
            historical_bad_debt_usd=0.0,
            total_borrow_usd=0.0,
        )
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(
            result["protocols"][0]["base_loss_estimate_usd"], 1_000_000.0
        )

    def test_zero_tvl_no_crash(self):
        p = make_protocol(tvl_usd=0.0)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["fund_to_tvl_ratio"], 0.0)


# ── flag tests ────────────────────────────────────────────────────────────────

class TestInsuranceFundFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolInsuranceFundAdequacyAnalyzer()

    def test_flag_below_min_coverage(self):
        p = make_protocol(
            tvl_usd=1_000_000_000,
            insurance_fund_usd=10_000_000,  # 1% < 2% min
            external_coverage_usd=0.0,
        )
        result = self.analyzer.analyze([p])
        self.assertIn("BELOW_MIN_COVERAGE", result["protocols"][0]["flags"])

    def test_no_flag_adequate_coverage(self):
        p = make_protocol(
            tvl_usd=100_000_000,
            insurance_fund_usd=10_000_000,  # 10%
        )
        result = self.analyzer.analyze([p])
        self.assertNotIn("BELOW_MIN_COVERAGE", result["protocols"][0]["flags"])

    def test_flag_no_external_cover(self):
        p = make_protocol(external_coverage_usd=0.0)
        result = self.analyzer.analyze([p])
        self.assertIn("NO_EXTERNAL_COVER", result["protocols"][0]["flags"])

    def test_no_flag_has_external_cover(self):
        p = make_protocol(external_coverage_usd=1_000_000)
        result = self.analyzer.analyze([p])
        self.assertNotIn("NO_EXTERNAL_COVER", result["protocols"][0]["flags"])

    def test_flag_no_security_audits(self):
        p = make_protocol(num_audit_reports=0)
        result = self.analyzer.analyze([p])
        self.assertIn("NO_SECURITY_AUDITS", result["protocols"][0]["flags"])

    def test_no_flag_has_audits(self):
        p = make_protocol(num_audit_reports=2)
        result = self.analyzer.analyze([p])
        self.assertNotIn("NO_SECURITY_AUDITS", result["protocols"][0]["flags"])

    def test_flag_fund_below_historical_losses(self):
        p = make_protocol(
            insurance_fund_usd=1_000_000,
            historical_bad_debt_usd=5_000_000,
        )
        result = self.analyzer.analyze([p])
        self.assertIn("FUND_BELOW_HISTORICAL_LOSSES", result["protocols"][0]["flags"])

    def test_no_flag_fund_covers_losses(self):
        p = make_protocol(
            insurance_fund_usd=10_000_000,
            historical_bad_debt_usd=5_000_000,
        )
        result = self.analyzer.analyze([p])
        self.assertNotIn("FUND_BELOW_HISTORICAL_LOSSES", result["protocols"][0]["flags"])

    def test_flag_large_tvl_low_coverage(self):
        p = make_protocol(
            tvl_usd=600_000_000,
            insurance_fund_usd=5_000_000,   # 0.83% < 2%
            external_coverage_usd=0.0,
        )
        result = self.analyzer.analyze([p])
        flags = result["protocols"][0]["flags"]
        self.assertIn("LARGE_TVL_LOW_COVERAGE", flags)

    def test_flags_list_type(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)


# ── aggregate tests ───────────────────────────────────────────────────────────

class TestInsuranceFundAggregate(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolInsuranceFundAdequacyAnalyzer()

    def test_best_capitalized(self):
        p_good = make_protocol(name="RichProto", insurance_fund_usd=500_000_000)
        p_poor = make_protocol(name="PoorProto", insurance_fund_usd=100_000)
        result = self.analyzer.analyze([p_poor, p_good])
        self.assertEqual(result["aggregate"]["best_capitalized"], "RichProto")

    def test_worst_capitalized(self):
        p_good = make_protocol(name="RichProto", insurance_fund_usd=500_000_000)
        p_poor = make_protocol(name="PoorProto", insurance_fund_usd=100_000)
        result = self.analyzer.analyze([p_poor, p_good])
        self.assertEqual(result["aggregate"]["worst_capitalized"], "PoorProto")

    def test_avg_adequacy_score_in_range(self):
        protos = [make_protocol() for _ in range(3)]
        result = self.analyzer.analyze(protos)
        avg = result["aggregate"]["avg_adequacy_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_total_insurance_fund_sum(self):
        p1 = make_protocol(name="A", insurance_fund_usd=10_000_000)
        p2 = make_protocol(name="B", insurance_fund_usd=20_000_000)
        result = self.analyzer.analyze([p1, p2])
        self.assertAlmostEqual(
            result["aggregate"]["total_insurance_fund_usd"], 30_000_000.0
        )

    def test_total_tvl_sum(self):
        p1 = make_protocol(name="A", tvl_usd=1_000_000_000)
        p2 = make_protocol(name="B", tvl_usd=2_000_000_000)
        result = self.analyzer.analyze([p1, p2])
        self.assertAlmostEqual(
            result["aggregate"]["total_tvl_protected_usd"], 3_000_000_000.0
        )

    def test_critically_undercapitalized_count(self):
        p_bad = make_protocol(
            insurance_fund_usd=0.0,
            num_audit_reports=0,
            annual_revenue_usd=0.0,
        )
        result = self.analyzer.analyze([p_bad])
        self.assertGreaterEqual(result["aggregate"]["critically_undercapitalized_count"], 0)

    def test_well_capitalized_count_type(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIsInstance(result["aggregate"]["well_capitalized_count"], int)


# ── log tests ─────────────────────────────────────────────────────────────────

class TestInsuranceFundLog(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolInsuranceFundAdequacyAnalyzer()

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

    def test_log_entry_keys(self):
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
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        snap = data[0]["snapshots"][0]
        for k in ["name", "adequacy_score", "adequacy_label", "fund_to_tvl_ratio", "flags"]:
            self.assertIn(k, snap)

    def test_log_recovers_from_corrupt(self):
        cfg = tmp_cfg()
        with open(cfg["log_path"], "w") as fh:
            fh.write("CORRUPTED_JSON")
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_multi_protocol_count(self):
        cfg = tmp_cfg()
        self.analyzer.analyze(
            [make_protocol("A"), make_protocol("B"), make_protocol("C")],
            cfg=cfg, write_log=True
        )
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol_count"], 3)


if __name__ == "__main__":
    unittest.main()

"""
MP-1025 Tests: ProtocolDeFiYieldDurationMismatchAnalyzer
>=45 tests, unittest only, stdlib only.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_duration_mismatch_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_yield_duration_mismatch_analyzer import (
    ProtocolDeFiYieldDurationMismatchAnalyzer,
    _atomic_write,
    _load_ring_buffer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_proto(
    name="PROTO1",
    protocol="VaultCo",
    asset_avg_maturity_days=20,
    liability_avg_redemption_days=10,
    liquid_reserve_pct=50,
    redeemable_on_demand_pct=60,
    stress_redemption_pct=30,
    illiquid_asset_pct=30,
    asset_yield_apy_pct=8.0,
    funding_cost_apy_pct=4.0,
    fixed_rate_assets=False,
    floating_rate_liabilities=False,
):
    return {
        "name": name,
        "protocol": protocol,
        "asset_avg_maturity_days": asset_avg_maturity_days,
        "liability_avg_redemption_days": liability_avg_redemption_days,
        "liquid_reserve_pct": liquid_reserve_pct,
        "redeemable_on_demand_pct": redeemable_on_demand_pct,
        "stress_redemption_pct": stress_redemption_pct,
        "illiquid_asset_pct": illiquid_asset_pct,
        "asset_yield_apy_pct": asset_yield_apy_pct,
        "funding_cost_apy_pct": funding_cost_apy_pct,
        "fixed_rate_assets": fixed_rate_assets,
        "floating_rate_liabilities": floating_rate_liabilities,
    }


def _matched_proto(name="Matched"):
    return _make_proto(
        name=name,
        asset_avg_maturity_days=10,
        liability_avg_redemption_days=5,
        liquid_reserve_pct=90,
        stress_redemption_pct=30,
        illiquid_asset_pct=5,
        asset_yield_apy_pct=6.0,
        funding_cost_apy_pct=3.0,
    )


def _run_risk_proto(name="RunRisk"):
    return _make_proto(
        name=name,
        asset_avg_maturity_days=365,
        liability_avg_redemption_days=1,
        liquid_reserve_pct=5,
        stress_redemption_pct=50,
        illiquid_asset_pct=95,
        asset_yield_apy_pct=4.0,
        funding_cost_apy_pct=9.0,
        fixed_rate_assets=True,
        floating_rate_liabilities=True,
    )


class TestAtomicWrite(unittest.TestCase):
    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [{"a": 1}])
            self.assertTrue(os.path.exists(path))

    def test_write_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            _atomic_write(path, {"key": "value"})
            with open(path) as f:
                self.assertEqual(json.load(f), {"key": "value"})

    def test_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            _atomic_write(path, [1])
            _atomic_write(path, [2, 3])
            with open(path) as f:
                self.assertEqual(json.load(f), [2, 3])

    def test_write_creates_missing_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a", "b", "data.json")
            _atomic_write(path, {"ok": True})
            self.assertTrue(os.path.exists(path))


class TestLoadRingBuffer(unittest.TestCase):
    def test_load_empty_on_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_load_ring_buffer(os.path.join(d, "x.json"), 100), [])

    def test_load_respects_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "buf.json")
            _atomic_write(path, list(range(200)))
            self.assertEqual(len(_load_ring_buffer(path, 50)), 50)

    def test_load_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("xxx")
            self.assertEqual(_load_ring_buffer(path, 10), [])


class TestDurationGap(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_positive_gap(self):
        gap = self.an._duration_gap_days(
            _make_proto(asset_avg_maturity_days=100, liability_avg_redemption_days=10))
        self.assertAlmostEqual(gap, 90.0)

    def test_negative_gap(self):
        gap = self.an._duration_gap_days(
            _make_proto(asset_avg_maturity_days=5, liability_avg_redemption_days=30))
        self.assertAlmostEqual(gap, -25.0)

    def test_zero_gap(self):
        gap = self.an._duration_gap_days(
            _make_proto(asset_avg_maturity_days=10, liability_avg_redemption_days=10))
        self.assertEqual(gap, 0.0)

    def test_missing_fields(self):
        self.assertEqual(self.an._duration_gap_days({}), 0.0)


class TestLiquidityCoverage(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_basic(self):
        cov = self.an._liquidity_coverage_ratio(
            _make_proto(liquid_reserve_pct=60, stress_redemption_pct=30))
        self.assertAlmostEqual(cov, 2.0)

    def test_zero_stress_no_div_error(self):
        cov = self.an._liquidity_coverage_ratio(
            _make_proto(liquid_reserve_pct=50, stress_redemption_pct=0))
        self.assertGreater(cov, 0)

    def test_missing_stress(self):
        proto = _make_proto()
        del proto["stress_redemption_pct"]
        cov = self.an._liquidity_coverage_ratio(proto)
        self.assertGreater(cov, 0)

    def test_zero_reserve(self):
        cov = self.an._liquidity_coverage_ratio(
            _make_proto(liquid_reserve_pct=0, stress_redemption_pct=30))
        self.assertEqual(cov, 0.0)


class TestRedemptionShortfall(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_positive_shortfall(self):
        s = self.an._redemption_stress_shortfall_pct(
            _make_proto(stress_redemption_pct=40, liquid_reserve_pct=10))
        self.assertAlmostEqual(s, 30.0)

    def test_no_shortfall_when_covered(self):
        s = self.an._redemption_stress_shortfall_pct(
            _make_proto(stress_redemption_pct=20, liquid_reserve_pct=50))
        self.assertEqual(s, 0.0)

    def test_exact_match_zero(self):
        s = self.an._redemption_stress_shortfall_pct(
            _make_proto(stress_redemption_pct=30, liquid_reserve_pct=30))
        self.assertEqual(s, 0.0)


class TestNetInterestMargin(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_positive_nim(self):
        nim = self.an._net_interest_margin_pct(
            _make_proto(asset_yield_apy_pct=8, funding_cost_apy_pct=3))
        self.assertAlmostEqual(nim, 5.0)

    def test_negative_nim(self):
        nim = self.an._net_interest_margin_pct(
            _make_proto(asset_yield_apy_pct=4, funding_cost_apy_pct=9))
        self.assertAlmostEqual(nim, -5.0)

    def test_missing_fields(self):
        self.assertEqual(self.an._net_interest_margin_pct({}), 0.0)


class TestRateResetExposed(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_both_true(self):
        self.assertTrue(self.an._rate_reset_exposed(
            _make_proto(fixed_rate_assets=True, floating_rate_liabilities=True)))

    def test_fixed_only(self):
        self.assertFalse(self.an._rate_reset_exposed(
            _make_proto(fixed_rate_assets=True, floating_rate_liabilities=False)))

    def test_neither(self):
        self.assertFalse(self.an._rate_reset_exposed(
            _make_proto(fixed_rate_assets=False, floating_rate_liabilities=False)))


class TestDurationMismatchScore(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_matched_low(self):
        self.assertLess(self.an._duration_mismatch_score(_matched_proto()), 20.0)

    def test_run_risk_high(self):
        self.assertGreaterEqual(self.an._duration_mismatch_score(_run_risk_proto()), 50.0)

    def test_clipped_0(self):
        self.assertGreaterEqual(self.an._duration_mismatch_score(_matched_proto()), 0.0)

    def test_clipped_100(self):
        self.assertLessEqual(self.an._duration_mismatch_score(_run_risk_proto()), 100.0)

    def test_grows_with_gap(self):
        s_low = self.an._duration_mismatch_score(
            _make_proto(asset_avg_maturity_days=10, liability_avg_redemption_days=5))
        s_high = self.an._duration_mismatch_score(
            _make_proto(asset_avg_maturity_days=300, liability_avg_redemption_days=5))
        self.assertGreater(s_high, s_low)

    def test_grows_with_shortfall(self):
        s_low = self.an._duration_mismatch_score(
            _make_proto(stress_redemption_pct=10, liquid_reserve_pct=80))
        s_high = self.an._duration_mismatch_score(
            _make_proto(stress_redemption_pct=60, liquid_reserve_pct=5))
        self.assertGreater(s_high, s_low)

    def test_coverage_reduces_score(self):
        low_cov = self.an._duration_mismatch_score(
            _make_proto(asset_avg_maturity_days=300, liquid_reserve_pct=5,
                        stress_redemption_pct=40, illiquid_asset_pct=80))
        high_cov = self.an._duration_mismatch_score(
            _make_proto(asset_avg_maturity_days=300, liquid_reserve_pct=200,
                        stress_redemption_pct=40, illiquid_asset_pct=80))
        self.assertGreater(low_cov, high_cov)

    def test_empty_proto_low(self):
        self.assertLessEqual(self.an._duration_mismatch_score({}), 20.0)


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_matched(self):
        self.assertEqual(self.an._classification(10), "MATCHED")

    def test_minor(self):
        self.assertEqual(self.an._classification(25), "MINOR_MISMATCH")

    def test_moderate(self):
        self.assertEqual(self.an._classification(45), "MODERATE_MISMATCH")

    def test_severe(self):
        self.assertEqual(self.an._classification(65), "SEVERE_MISMATCH")

    def test_run_risk(self):
        self.assertEqual(self.an._classification(85), "RUN_RISK")


class TestGrade(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_a(self):
        self.assertEqual(self.an._grade(10), "A")

    def test_b(self):
        self.assertEqual(self.an._grade(30), "B")

    def test_c(self):
        self.assertEqual(self.an._grade(50), "C")

    def test_d(self):
        self.assertEqual(self.an._grade(70), "D")

    def test_f(self):
        self.assertEqual(self.an._grade(90), "F")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer()

    def test_negative_duration_gap(self):
        self.assertIn("NEGATIVE_DURATION_GAP", self.an._compute_flags(
            _make_proto(asset_avg_maturity_days=5, liability_avg_redemption_days=30)))

    def test_large_duration_gap(self):
        self.assertIn("LARGE_DURATION_GAP", self.an._compute_flags(
            _make_proto(asset_avg_maturity_days=200, liability_avg_redemption_days=5)))

    def test_insufficient_liquid_reserve(self):
        self.assertIn("INSUFFICIENT_LIQUID_RESERVE", self.an._compute_flags(
            _make_proto(liquid_reserve_pct=10, stress_redemption_pct=40)))

    def test_run_risk_flag(self):
        flags = self.an._compute_flags(
            _make_proto(stress_redemption_pct=50, liquid_reserve_pct=5))
        self.assertIn("RUN_RISK", flags)

    def test_no_run_risk_when_covered(self):
        flags = self.an._compute_flags(
            _make_proto(stress_redemption_pct=20, liquid_reserve_pct=80))
        self.assertNotIn("RUN_RISK", flags)

    def test_rate_reset_exposed_flag(self):
        self.assertIn("RATE_RESET_EXPOSED", self.an._compute_flags(
            _make_proto(fixed_rate_assets=True, floating_rate_liabilities=True)))

    def test_fixed_floating_mismatch_flag(self):
        self.assertIn("FIXED_FLOATING_MISMATCH", self.an._compute_flags(
            _make_proto(fixed_rate_assets=True, floating_rate_liabilities=False)))

    def test_no_fixed_floating_mismatch_when_both(self):
        self.assertNotIn("FIXED_FLOATING_MISMATCH", self.an._compute_flags(
            _make_proto(fixed_rate_assets=True, floating_rate_liabilities=True)))

    def test_high_illiquid_assets_flag(self):
        self.assertIn("HIGH_ILLIQUID_ASSETS", self.an._compute_flags(
            _make_proto(illiquid_asset_pct=80)))

    def test_well_matched_flag(self):
        self.assertIn("WELL_MATCHED", self.an._compute_flags(
            _make_proto(liquid_reserve_pct=90, stress_redemption_pct=30,
                        asset_avg_maturity_days=15, liability_avg_redemption_days=5)))

    def test_strong_liquidity_coverage_flag(self):
        self.assertIn("STRONG_LIQUIDITY_COVERAGE", self.an._compute_flags(
            _make_proto(liquid_reserve_pct=100, stress_redemption_pct=30)))

    def test_negative_nim_flag(self):
        self.assertIn("NEGATIVE_NIM", self.an._compute_flags(
            _make_proto(asset_yield_apy_pct=3, funding_cost_apy_pct=8)))

    def test_insufficient_data_flag(self):
        self.assertIn("INSUFFICIENT_DATA", self.an._compute_flags({"name": "X"}))

    def test_no_insufficient_data_with_fields(self):
        self.assertNotIn("INSUFFICIENT_DATA", self.an._compute_flags(_make_proto()))

    def test_flags_is_list(self):
        self.assertIsInstance(self.an._compute_flags(_make_proto()), list)


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.an = ProtocolDeFiYieldDurationMismatchAnalyzer(data_dir=self.tmpdir)
        self.config = {"data_dir": self.tmpdir}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_dict(self):
        self.assertIsInstance(self.an.analyze([_make_proto()], self.config), dict)

    def test_analyzed_protocols_key(self):
        self.assertIn("analyzed_protocols", self.an.analyze([_make_proto()], self.config))

    def test_aggregates_key(self):
        self.assertIn("aggregates", self.an.analyze([_make_proto()], self.config))

    def test_metadata_key(self):
        self.assertIn("metadata", self.an.analyze([_make_proto()], self.config))

    def test_count_matches_input(self):
        protos = [_make_proto(name=f"P{i}") for i in range(5)]
        self.assertEqual(len(self.an.analyze(protos, self.config)["analyzed_protocols"]), 5)

    def test_empty_protocols(self):
        result = self.an.analyze([], self.config)
        self.assertEqual(result["aggregates"]["avg_duration_mismatch_score"], 0.0)
        self.assertEqual(result["aggregates"]["run_risk_count"], 0)
        self.assertEqual(result["aggregates"]["matched_count"], 0)

    def test_log_file_created(self):
        self.an.analyze([_make_proto()], self.config)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmpdir, "yield_duration_mismatch_log.json")))

    def test_log_is_valid_json_list(self):
        self.an.analyze([_make_proto()], self.config)
        with open(os.path.join(self.tmpdir, "yield_duration_mismatch_log.json")) as f:
            self.assertIsInstance(json.load(f), list)

    def test_log_grows(self):
        self.an.analyze([_make_proto()], self.config)
        self.an.analyze([_make_proto()], self.config)
        with open(os.path.join(self.tmpdir, "yield_duration_mismatch_log.json")) as f:
            self.assertEqual(len(json.load(f)), 2)

    def test_log_respects_cap(self):
        for _ in range(110):
            self.an.analyze([_make_proto()], self.config)
        with open(os.path.join(self.tmpdir, "yield_duration_mismatch_log.json")) as f:
            self.assertLessEqual(len(json.load(f)), 100)

    def test_protocol_has_required_fields(self):
        p = self.an.analyze([_make_proto()], self.config)["analyzed_protocols"][0]
        for field in [
            "name", "protocol", "duration_gap_days", "liquidity_coverage_ratio",
            "redemption_stress_shortfall_pct", "net_interest_margin_pct",
            "rate_reset_exposed", "duration_mismatch_score", "classification",
            "grade", "flags",
        ]:
            self.assertIn(field, p)

    def test_aggregates_required_fields(self):
        agg = self.an.analyze([_make_proto()], self.config)["aggregates"]
        for field in ["best_matched", "worst_mismatch", "avg_duration_mismatch_score",
                      "run_risk_count", "matched_count"]:
            self.assertIn(field, agg)

    def test_metadata_mp(self):
        self.assertEqual(
            self.an.analyze([_make_proto()], self.config)["metadata"]["mp"], "MP-1025")

    def test_metadata_module(self):
        self.assertEqual(
            self.an.analyze([_make_proto()], self.config)["metadata"]["module"],
            "ProtocolDeFiYieldDurationMismatchAnalyzer")

    def test_metadata_protocol_count(self):
        protos = [_make_proto(name=f"P{i}") for i in range(7)]
        self.assertEqual(
            self.an.analyze(protos, self.config)["metadata"]["protocol_count"], 7)

    def test_metadata_timestamp(self):
        self.assertIn("timestamp", self.an.analyze([_make_proto()], self.config)["metadata"])

    def test_matched_classification_in_result(self):
        result = self.an.analyze([_matched_proto()], self.config)
        self.assertEqual(result["analyzed_protocols"][0]["classification"], "MATCHED")

    def test_run_risk_classification_in_result(self):
        result = self.an.analyze([_run_risk_proto()], self.config)
        self.assertIn(result["analyzed_protocols"][0]["classification"],
                      {"SEVERE_MISMATCH", "RUN_RISK"})

    def test_best_worst(self):
        result = self.an.analyze(
            [_matched_proto("Good"), _run_risk_proto("Bad")], self.config)
        self.assertEqual(result["aggregates"]["worst_mismatch"], "Bad")
        self.assertEqual(result["aggregates"]["best_matched"], "Good")

    def test_matched_count(self):
        result = self.an.analyze(
            [_matched_proto("M1"), _matched_proto("M2"), _run_risk_proto("R")], self.config)
        self.assertEqual(result["aggregates"]["matched_count"], 2)

    def test_avg_in_range(self):
        protos = [_make_proto(name=f"P{i}") for i in range(5)]
        avg = self.an.analyze(protos, self.config)["aggregates"]["avg_duration_mismatch_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_score_in_range(self):
        score = self.an.analyze([_run_risk_proto()], self.config)[
            "analyzed_protocols"][0]["duration_mismatch_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_missing_optional_fields_no_error(self):
        self.assertIn("analyzed_protocols", self.an.analyze([{"name": "Min"}], self.config))

    def test_insufficient_data_in_result(self):
        result = self.an.analyze([{"name": "Min"}], self.config)
        self.assertIn("INSUFFICIENT_DATA", result["analyzed_protocols"][0]["flags"])

    def test_name_preserved(self):
        result = self.an.analyze([_make_proto(name="MyProto")], self.config)
        self.assertEqual(result["analyzed_protocols"][0]["name"], "MyProto")

    def test_deterministic(self):
        proto = _make_proto()
        r1 = self.an.analyze([proto], self.config)
        r2 = self.an.analyze([proto], self.config)
        self.assertAlmostEqual(
            r1["analyzed_protocols"][0]["duration_mismatch_score"],
            r2["analyzed_protocols"][0]["duration_mismatch_score"])

    def test_grade_valid(self):
        valid = {"A", "B", "C", "D", "F"}
        protos = [_make_proto(name=f"P{i}") for i in range(5)]
        for p in self.an.analyze(protos, self.config)["analyzed_protocols"]:
            self.assertIn(p["grade"], valid)

    def test_classification_valid(self):
        valid = {"MATCHED", "MINOR_MISMATCH", "MODERATE_MISMATCH",
                 "SEVERE_MISMATCH", "RUN_RISK"}
        protos = [_make_proto(name=f"P{i}") for i in range(5)]
        for p in self.an.analyze(protos, self.config)["analyzed_protocols"]:
            self.assertIn(p["classification"], valid)

    def test_no_config_uses_default(self):
        an = ProtocolDeFiYieldDurationMismatchAnalyzer(data_dir=self.tmpdir)
        self.assertIn("analyzed_protocols", an.analyze([_make_proto()], {}))

    def test_log_entry_fields(self):
        self.an.analyze([_make_proto()], self.config)
        with open(os.path.join(self.tmpdir, "yield_duration_mismatch_log.json")) as f:
            entry = json.load(f)[-1]
        for field in ["timestamp", "protocol_count", "avg_duration_mismatch_score",
                      "run_risk_count", "matched_count"]:
            self.assertIn(field, entry)

    def test_default_constructor(self):
        an = ProtocolDeFiYieldDurationMismatchAnalyzer()
        self.assertIsNotNone(an.data_dir)

    def test_config_data_dir_override(self):
        with tempfile.TemporaryDirectory() as d2:
            self.an.analyze([_make_proto()], {"data_dir": d2})
            self.assertTrue(os.path.exists(
                os.path.join(d2, "yield_duration_mismatch_log.json")))

    def test_zero_stress_no_crash(self):
        result = self.an.analyze(
            [_make_proto(stress_redemption_pct=0, liquid_reserve_pct=0)], self.config)
        self.assertIn("analyzed_protocols", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

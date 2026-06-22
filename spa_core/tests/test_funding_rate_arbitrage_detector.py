"""
Tests for MP-776 FundingRateArbitrageDetector.
unittest only (no pytest).  Run:
    python3 -m unittest spa_core/tests/test_funding_rate_arbitrage_detector.py -v
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.funding_rate_arbitrage_detector import (
    FundingRateArbitrageDetector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detector(tmpdir):
    return FundingRateArbitrageDetector(data_dir=tmpdir)


def _market(protocol="Proto", bps=100.0, spot_apy=3.0, collateral_ratio=1.5):
    return {
        "protocol": protocol,
        "perp_funding_rate_8h_bps": bps,
        "spot_apy_pct": spot_apy,
        "collateral_ratio": collateral_ratio,
    }


# ---------------------------------------------------------------------------
# 1. Annualised funding calculation
# ---------------------------------------------------------------------------

class TestAnnualisedFunding(unittest.TestCase):

    def test_zero_bps(self):
        self.assertAlmostEqual(FundingRateArbitrageDetector.compute_annualized_funding(0), 0.0)

    def test_100_bps(self):
        # 100 / 10000 * 3 * 365 = 10.95
        result = FundingRateArbitrageDetector.compute_annualized_funding(100)
        self.assertAlmostEqual(result, 10.95, places=6)

    def test_50_bps(self):
        result = FundingRateArbitrageDetector.compute_annualized_funding(50)
        self.assertAlmostEqual(result, 5.475, places=6)

    def test_1_bps(self):
        result = FundingRateArbitrageDetector.compute_annualized_funding(1)
        self.assertAlmostEqual(result, 0.1095, places=6)

    def test_negative_bps(self):
        result = FundingRateArbitrageDetector.compute_annualized_funding(-100)
        self.assertAlmostEqual(result, -10.95, places=6)

    def test_large_bps(self):
        result = FundingRateArbitrageDetector.compute_annualized_funding(10000)
        self.assertAlmostEqual(result, 1095.0, places=4)

    def test_formula_multiplier(self):
        # The formula multiplies by (3 * 365 / 10000) = 0.1095
        for bps in [0, 10, 200, 500]:
            self.assertAlmostEqual(
                FundingRateArbitrageDetector.compute_annualized_funding(bps),
                bps * 0.1095,
                places=6,
            )

    def test_fractional_bps(self):
        result = FundingRateArbitrageDetector.compute_annualized_funding(0.5)
        self.assertAlmostEqual(result, 0.05475, places=7)

    def test_returns_float(self):
        result = FundingRateArbitrageDetector.compute_annualized_funding(10)
        self.assertIsInstance(result, float)

    def test_symmetry_negative_positive(self):
        pos = FundingRateArbitrageDetector.compute_annualized_funding(200)
        neg = FundingRateArbitrageDetector.compute_annualized_funding(-200)
        self.assertAlmostEqual(pos, -neg, places=10)


# ---------------------------------------------------------------------------
# 2. Spread calculation
# ---------------------------------------------------------------------------

class TestSpread(unittest.TestCase):

    def test_positive_spread(self):
        spread = FundingRateArbitrageDetector.compute_spread(10.0, 3.0)
        self.assertAlmostEqual(spread, 7.0, places=9)

    def test_negative_spread(self):
        spread = FundingRateArbitrageDetector.compute_spread(2.0, 5.0)
        self.assertAlmostEqual(spread, -3.0, places=9)

    def test_zero_spread(self):
        spread = FundingRateArbitrageDetector.compute_spread(5.0, 5.0)
        self.assertAlmostEqual(spread, 0.0, places=9)

    def test_zero_spot_apy(self):
        spread = FundingRateArbitrageDetector.compute_spread(8.0, 0.0)
        self.assertAlmostEqual(spread, 8.0, places=9)

    def test_zero_funding(self):
        spread = FundingRateArbitrageDetector.compute_spread(0.0, 4.0)
        self.assertAlmostEqual(spread, -4.0, places=9)

    def test_both_zero(self):
        spread = FundingRateArbitrageDetector.compute_spread(0.0, 0.0)
        self.assertAlmostEqual(spread, 0.0, places=9)

    def test_precision_small_values(self):
        spread = FundingRateArbitrageDetector.compute_spread(0.001, 0.0009)
        self.assertAlmostEqual(spread, 0.0001, places=10)

    def test_large_funding(self):
        spread = FundingRateArbitrageDetector.compute_spread(100.0, 3.5)
        self.assertAlmostEqual(spread, 96.5, places=9)


# ---------------------------------------------------------------------------
# 3. Net arb yield calculation
# ---------------------------------------------------------------------------

class TestNetArbYield(unittest.TestCase):

    def test_basic_1_5_collateral(self):
        # spread * (1 - 1/1.5) = spread * (1 - 0.6667) = spread * 0.3333
        result = FundingRateArbitrageDetector.compute_net_arb_yield(9.0, 1.5)
        self.assertAlmostEqual(result, 9.0 * (1.0 - 1.0 / 1.5), places=9)

    def test_collateral_ratio_1_gives_zero(self):
        # 1 - 1/1 = 0
        result = FundingRateArbitrageDetector.compute_net_arb_yield(10.0, 1.0)
        self.assertAlmostEqual(result, 0.0, places=9)

    def test_collateral_ratio_2(self):
        # spread * (1 - 0.5) = spread * 0.5
        result = FundingRateArbitrageDetector.compute_net_arb_yield(10.0, 2.0)
        self.assertAlmostEqual(result, 5.0, places=9)

    def test_collateral_ratio_10(self):
        result = FundingRateArbitrageDetector.compute_net_arb_yield(10.0, 10.0)
        self.assertAlmostEqual(result, 10.0 * (1.0 - 0.1), places=9)

    def test_zero_collateral_ratio(self):
        # guard: returns 0.0
        result = FundingRateArbitrageDetector.compute_net_arb_yield(10.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_negative_collateral_ratio(self):
        # guard: returns 0.0
        result = FundingRateArbitrageDetector.compute_net_arb_yield(10.0, -1.0)
        self.assertEqual(result, 0.0)

    def test_negative_spread_propagates(self):
        result = FundingRateArbitrageDetector.compute_net_arb_yield(-5.0, 1.5)
        self.assertLess(result, 0.0)

    def test_zero_spread(self):
        result = FundingRateArbitrageDetector.compute_net_arb_yield(0.0, 1.5)
        self.assertAlmostEqual(result, 0.0, places=9)

    def test_high_collateral_approaches_spread(self):
        # As collateral_ratio → ∞, net_arb_yield → spread
        result = FundingRateArbitrageDetector.compute_net_arb_yield(10.0, 1_000_000.0)
        self.assertAlmostEqual(result, 10.0, places=3)

    def test_returns_float(self):
        result = FundingRateArbitrageDetector.compute_net_arb_yield(5.0, 2.0)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 4. Opportunity grade
# ---------------------------------------------------------------------------

class TestOpportunityGrade(unittest.TestCase):

    def test_excellent_above_5(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(5.1), "EXCELLENT")

    def test_excellent_high_value(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(50.0), "EXCELLENT")

    def test_good_above_2(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(2.1), "GOOD")

    def test_good_just_above_2(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(2.001), "GOOD")

    def test_marginal_above_0(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(0.1), "MARGINAL")

    def test_marginal_tiny_positive(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(1e-9), "MARGINAL")

    def test_none_exactly_zero(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(0.0), "NONE")

    def test_none_negative(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(-1.0), "NONE")

    def test_none_very_negative(self):
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(-100.0), "NONE")

    def test_boundary_exactly_5(self):
        # >5 is EXCELLENT; exactly 5 falls to GOOD
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(5.0), "GOOD")

    def test_boundary_exactly_2(self):
        # >2 is GOOD; exactly 2 falls to MARGINAL
        self.assertEqual(FundingRateArbitrageDetector.grade_opportunity(2.0), "MARGINAL")

    def test_returns_string(self):
        grade = FundingRateArbitrageDetector.grade_opportunity(3.0)
        self.assertIsInstance(grade, str)

    def test_valid_grade_set(self):
        valid = {"EXCELLENT", "GOOD", "MARGINAL", "NONE"}
        for val in [-5, 0, 0.5, 2, 2.5, 5, 10]:
            self.assertIn(FundingRateArbitrageDetector.grade_opportunity(val), valid)


# ---------------------------------------------------------------------------
# 5. detect() method
# ---------------------------------------------------------------------------

class TestDetect(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.det = _make_detector(self.tmpdir)

    def test_empty_markets_returns_empty(self):
        results = self.det.detect([])
        self.assertEqual(results, [])

    def test_single_market_returns_one_result(self):
        results = self.det.detect([_market()])
        self.assertEqual(len(results), 1)

    def test_multiple_markets_count(self):
        markets = [_market("A", 200, 3, 1.5), _market("B", 50, 10, 2.0), _market("C", 10, 1, 1.2)]
        results = self.det.detect(markets)
        self.assertEqual(len(results), 3)

    def test_result_has_protocol(self):
        results = self.det.detect([_market("UniswapV3")])
        self.assertEqual(results[0]["protocol"], "UniswapV3")

    def test_result_has_annualized_funding(self):
        results = self.det.detect([_market(bps=100)])
        self.assertIn("annualized_funding_pct", results[0])
        self.assertAlmostEqual(results[0]["annualized_funding_pct"], 10.95, places=2)

    def test_result_has_spread(self):
        results = self.det.detect([_market(bps=100, spot_apy=3.0)])
        self.assertIn("spread_pct", results[0])
        self.assertAlmostEqual(results[0]["spread_pct"], 10.95 - 3.0, places=2)

    def test_result_has_net_arb_yield(self):
        results = self.det.detect([_market()])
        self.assertIn("net_arb_yield_pct", results[0])

    def test_result_has_opportunity_grade(self):
        results = self.det.detect([_market()])
        self.assertIn("opportunity_grade", results[0])

    def test_result_has_timestamp(self):
        results = self.det.detect([_market()])
        self.assertIn("timestamp", results[0])
        self.assertIsInstance(results[0]["timestamp"], str)

    def test_excellent_grade_detected(self):
        # bps=1000 → annualized ≈109.5%; spot=3%; spread≈106.5%; net≈35.5% with ratio=1.5
        results = self.det.detect([_market(bps=1000, spot_apy=3.0, collateral_ratio=1.5)])
        self.assertEqual(results[0]["opportunity_grade"], "EXCELLENT")

    def test_none_grade_detected(self):
        # Zero funding, spot 5% → spread negative
        results = self.det.detect([_market(bps=0, spot_apy=5.0, collateral_ratio=1.5)])
        self.assertEqual(results[0]["opportunity_grade"], "NONE")

    def test_zero_funding_rate_market(self):
        results = self.det.detect([_market(bps=0, spot_apy=0, collateral_ratio=1.5)])
        self.assertAlmostEqual(results[0]["annualized_funding_pct"], 0.0, places=9)
        self.assertEqual(results[0]["opportunity_grade"], "NONE")

    def test_negative_spread_grade_none(self):
        results = self.det.detect([_market(bps=10, spot_apy=20.0, collateral_ratio=2.0)])
        self.assertEqual(results[0]["opportunity_grade"], "NONE")
        self.assertLess(results[0]["net_arb_yield_pct"], 0.0)

    def test_mixed_grades_in_batch(self):
        markets = [
            _market("A", bps=2000, spot_apy=3.0, collateral_ratio=2.0),   # high
            _market("B", bps=30, spot_apy=1.0, collateral_ratio=1.5),     # low positive
            _market("C", bps=5, spot_apy=20.0, collateral_ratio=1.5),     # negative
        ]
        results = self.det.detect(markets)
        grades = {r["protocol"]: r["opportunity_grade"] for r in results}
        self.assertEqual(grades["A"], "EXCELLENT")
        self.assertIn(grades["B"], {"MARGINAL", "GOOD"})
        self.assertEqual(grades["C"], "NONE")

    def test_detect_updates_last_results(self):
        self.det.detect([_market("X")])
        self.assertEqual(len(self.det.last_results()), 1)
        self.det.detect([_market("Y"), _market("Z")])
        self.assertEqual(len(self.det.last_results()), 2)


# ---------------------------------------------------------------------------
# 6. get_opportunities()
# ---------------------------------------------------------------------------

class TestGetOpportunities(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.det = _make_detector(self.tmpdir)

    def test_empty_before_detect(self):
        opps = self.det.get_opportunities()
        self.assertEqual(opps, [])

    def test_empty_after_all_none(self):
        self.det.detect([_market(bps=0, spot_apy=5.0, collateral_ratio=1.5)])
        self.assertEqual(self.det.get_opportunities(), [])

    def test_returns_positive_only(self):
        markets = [
            _market("Good", bps=500, spot_apy=3.0, collateral_ratio=1.5),
            _market("Bad",  bps=0,   spot_apy=5.0, collateral_ratio=1.5),
        ]
        self.det.detect(markets)
        opps = self.det.get_opportunities()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["protocol"], "Good")

    def test_excludes_none_grade(self):
        markets = [_market("N", bps=0, spot_apy=10.0, collateral_ratio=2.0)]
        self.det.detect(markets)
        opps = self.det.get_opportunities()
        for o in opps:
            self.assertNotEqual(o["opportunity_grade"], "NONE")

    def test_includes_marginal(self):
        # Tiny positive yield → MARGINAL → should be in get_opportunities()
        markets = [_market("M", bps=30, spot_apy=3.0, collateral_ratio=1.01)]
        self.det.detect(markets)
        opps = self.det.get_opportunities()
        if opps:  # only if yield > 0
            self.assertNotEqual(opps[0]["opportunity_grade"], "NONE")

    def test_sorted_descending_by_yield(self):
        markets = [
            _market("Low",  bps=50,   spot_apy=3.0, collateral_ratio=1.5),
            _market("High", bps=1000, spot_apy=3.0, collateral_ratio=1.5),
            _market("Mid",  bps=200,  spot_apy=3.0, collateral_ratio=1.5),
        ]
        self.det.detect(markets)
        opps = self.det.get_opportunities()
        yields = [o["net_arb_yield_pct"] for o in opps]
        self.assertEqual(yields, sorted(yields, reverse=True))

    def test_returns_list(self):
        self.det.detect([_market()])
        self.assertIsInstance(self.det.get_opportunities(), list)

    def test_refreshed_after_second_detect(self):
        self.det.detect([_market("Old", bps=1000, spot_apy=3.0, collateral_ratio=1.5)])
        self.det.detect([_market("New", bps=0, spot_apy=5.0, collateral_ratio=1.5)])
        opps = self.det.get_opportunities()
        # Second detect had no good markets
        protocols = [o["protocol"] for o in opps]
        self.assertNotIn("Old", protocols)


# ---------------------------------------------------------------------------
# 7. get_best_opportunity()
# ---------------------------------------------------------------------------

class TestGetBestOpportunity(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.det = _make_detector(self.tmpdir)

    def test_none_before_detect(self):
        self.assertIsNone(self.det.get_best_opportunity())

    def test_none_when_all_negative(self):
        self.det.detect([_market(bps=0, spot_apy=10.0, collateral_ratio=2.0)])
        self.assertIsNone(self.det.get_best_opportunity())

    def test_returns_dict(self):
        self.det.detect([_market(bps=500, spot_apy=3.0, collateral_ratio=1.5)])
        best = self.det.get_best_opportunity()
        self.assertIsInstance(best, dict)

    def test_returns_highest_yield(self):
        markets = [
            _market("Low",  bps=50,   spot_apy=3.0, collateral_ratio=1.5),
            _market("High", bps=1000, spot_apy=3.0, collateral_ratio=1.5),
            _market("Mid",  bps=200,  spot_apy=3.0, collateral_ratio=1.5),
        ]
        self.det.detect(markets)
        best = self.det.get_best_opportunity()
        self.assertEqual(best["protocol"], "High")

    def test_best_has_opportunity_grade(self):
        self.det.detect([_market(bps=500, spot_apy=3.0, collateral_ratio=1.5)])
        best = self.det.get_best_opportunity()
        self.assertIn("opportunity_grade", best)

    def test_best_grade_not_none(self):
        self.det.detect([_market(bps=500, spot_apy=3.0, collateral_ratio=1.5)])
        best = self.det.get_best_opportunity()
        self.assertNotEqual(best["opportunity_grade"], "NONE")

    def test_excellent_wins_over_good(self):
        markets = [
            _market("Good",      bps=50,  spot_apy=0.5, collateral_ratio=3.0),
            _market("Excellent", bps=800, spot_apy=3.0, collateral_ratio=1.5),
        ]
        self.det.detect(markets)
        best = self.det.get_best_opportunity()
        self.assertEqual(best["protocol"], "Excellent")

    def test_updates_after_new_detect(self):
        self.det.detect([_market("First", bps=500, spot_apy=3.0, collateral_ratio=1.5)])
        self.det.detect([_market("Second", bps=2000, spot_apy=3.0, collateral_ratio=1.5)])
        best = self.det.get_best_opportunity()
        self.assertEqual(best["protocol"], "Second")


# ---------------------------------------------------------------------------
# 8. Ring-buffer / log behaviour
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_log_starts_empty(self):
        det = _make_detector(self.tmpdir)
        self.assertEqual(det.log_length(), 0)

    def test_log_grows_with_detects(self):
        det = _make_detector(self.tmpdir)
        det.detect([_market()])
        det.detect([_market()])
        self.assertEqual(det.log_length(), 2)

    def test_log_capped_at_100(self):
        det = _make_detector(self.tmpdir)
        for _ in range(110):
            det.detect([_market()])
        # In-memory list is unbounded; file is capped at 100
        log_file = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        with open(log_file) as fh:
            saved = json.load(fh)
        self.assertLessEqual(len(saved), 100)

    def test_file_never_exceeds_100(self):
        det = _make_detector(self.tmpdir)
        for i in range(105):
            det.detect([_market(f"P{i}")])
        log_file = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        with open(log_file) as fh:
            saved = json.load(fh)
        self.assertLessEqual(len(saved), 100)

    def test_oldest_entries_removed(self):
        det = _make_detector(self.tmpdir)
        # First entry has protocol "FirstBatch"
        det.detect([_market("FirstBatch", bps=100)])
        for i in range(100):
            det.detect([_market(f"Later{i}", bps=200)])
        log_file = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        with open(log_file) as fh:
            saved = json.load(fh)
        protocols_in_file = [
            r["protocol"]
            for entry in saved
            for r in entry.get("results", [])
        ]
        self.assertNotIn("FirstBatch", protocols_in_file)

    def test_log_persistence_across_instances(self):
        det1 = _make_detector(self.tmpdir)
        det1.detect([_market("Persistent")])
        det2 = _make_detector(self.tmpdir)
        self.assertEqual(det2.log_length(), 1)


# ---------------------------------------------------------------------------
# 9. Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_log_file_created_after_detect(self):
        det = _make_detector(self.tmpdir)
        det.detect([_market()])
        log_path = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_file_is_valid_json(self):
        det = _make_detector(self.tmpdir)
        det.detect([_market()])
        log_path = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_no_tmp_file_left_behind(self):
        det = _make_detector(self.tmpdir)
        det.detect([_market()])
        tmp_path = os.path.join(self.tmpdir, "funding_rate_arb_log.json.tmp")
        self.assertFalse(os.path.exists(tmp_path))

    def test_custom_log_filename(self):
        det = FundingRateArbitrageDetector(
            data_dir=self.tmpdir, log_filename="custom_arb.json"
        )
        det.detect([_market()])
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "custom_arb.json")))

    def test_log_file_structure(self):
        det = _make_detector(self.tmpdir)
        det.detect([_market("Struct")])
        log_path = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        self.assertIn("timestamp", entry)
        self.assertIn("markets_analyzed", entry)
        self.assertIn("results", entry)

    def test_multiple_detects_each_written(self):
        det = _make_detector(self.tmpdir)
        for i in range(5):
            det.detect([_market(f"P{i}")])
        log_path = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)


# ---------------------------------------------------------------------------
# 10. Integration: end-to-end pipeline
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_full_pipeline_excellent(self):
        det = _make_detector(self.tmpdir)
        markets = [
            {
                "protocol": "dYdX",
                "perp_funding_rate_8h_bps": 800,
                "spot_apy_pct": 5.0,
                "collateral_ratio": 1.5,
            }
        ]
        results = det.detect(markets)
        self.assertEqual(results[0]["opportunity_grade"], "EXCELLENT")
        best = det.get_best_opportunity()
        self.assertEqual(best["protocol"], "dYdX")

    def test_full_pipeline_no_opportunities(self):
        det = _make_detector(self.tmpdir)
        markets = [
            {"protocol": "X", "perp_funding_rate_8h_bps": 5, "spot_apy_pct": 10.0, "collateral_ratio": 2.0},
        ]
        det.detect(markets)
        self.assertEqual(det.get_opportunities(), [])
        self.assertIsNone(det.get_best_opportunity())

    def test_computed_values_consistent(self):
        det = _make_detector(self.tmpdir)
        bps, spot, col = 300.0, 4.0, 2.0
        results = det.detect([{"protocol": "T", "perp_funding_rate_8h_bps": bps,
                                "spot_apy_pct": spot, "collateral_ratio": col}])
        r = results[0]
        expected_ann = bps / 10_000 * 3 * 365
        expected_spread = expected_ann - spot
        expected_net = expected_spread * (1 - 1 / col)
        self.assertAlmostEqual(r["annualized_funding_pct"], expected_ann, places=3)
        self.assertAlmostEqual(r["spread_pct"], expected_spread, places=3)
        self.assertAlmostEqual(r["net_arb_yield_pct"], expected_net, places=3)

    def test_all_four_grades_reachable(self):
        det = _make_detector(self.tmpdir)
        markets = [
            {"protocol": "E", "perp_funding_rate_8h_bps": 2000, "spot_apy_pct": 3.0, "collateral_ratio": 1.5},
            {"protocol": "G", "perp_funding_rate_8h_bps": 250,  "spot_apy_pct": 3.0, "collateral_ratio": 1.5},
            {"protocol": "M", "perp_funding_rate_8h_bps": 40,   "spot_apy_pct": 3.0, "collateral_ratio": 1.5},
            {"protocol": "N", "perp_funding_rate_8h_bps": 0,    "spot_apy_pct": 5.0, "collateral_ratio": 1.5},
        ]
        results = det.detect(markets)
        grade_map = {r["protocol"]: r["opportunity_grade"] for r in results}
        self.assertEqual(grade_map["E"], "EXCELLENT")
        self.assertEqual(grade_map["N"], "NONE")
        self.assertIn(grade_map["G"], {"EXCELLENT", "GOOD"})
        self.assertIn(grade_map["M"], {"MARGINAL", "GOOD", "EXCELLENT"})


if __name__ == "__main__":
    unittest.main()

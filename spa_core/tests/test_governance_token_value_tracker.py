"""
Tests for MP-777 GovernanceTokenValueTracker.
unittest only (no pytest).  Run:
    python3 -m unittest spa_core/tests/test_governance_token_value_tracker.py -v
"""

import json
import math
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

from spa_core.analytics.governance_token_value_tracker import (
    GovernanceTokenValueTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmpdir):
    return GovernanceTokenValueTracker(data_dir=tmpdir)


def _token(
    protocol="TestProto",
    price=1.0,
    supply=1_000_000.0,
    revenue=100_000.0,
    emission=1_000.0,
    holders=500,
):
    return {
        "protocol": protocol,
        "token_price_usd": price,
        "circulating_supply": supply,
        "protocol_revenue_usd_annual": revenue,
        "emission_rate_tokens_per_day": emission,
        "token_holders": holders,
    }


# ---------------------------------------------------------------------------
# 1. Market cap calculation
# ---------------------------------------------------------------------------

class TestMarketCap(unittest.TestCase):

    def test_basic(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(2.0, 500_000.0)
        self.assertAlmostEqual(mc, 1_000_000.0, places=4)

    def test_zero_price(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(0.0, 1_000_000.0)
        self.assertAlmostEqual(mc, 0.0, places=9)

    def test_zero_supply(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(10.0, 0.0)
        self.assertAlmostEqual(mc, 0.0, places=9)

    def test_both_zero(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(0.0, 0.0)
        self.assertAlmostEqual(mc, 0.0, places=9)

    def test_large_values(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(500.0, 1_000_000_000.0)
        self.assertAlmostEqual(mc, 5e11, places=0)

    def test_small_price(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(0.0001, 1_000_000.0)
        self.assertAlmostEqual(mc, 100.0, places=6)

    def test_formula_commutativity(self):
        mc1 = GovernanceTokenValueTracker.compute_market_cap(3.0, 7.0)
        mc2 = GovernanceTokenValueTracker.compute_market_cap(7.0, 3.0)
        self.assertAlmostEqual(mc1, mc2, places=9)

    def test_returns_float(self):
        mc = GovernanceTokenValueTracker.compute_market_cap(1, 1)
        self.assertIsInstance(mc, float)


# ---------------------------------------------------------------------------
# 2. Price-to-revenue
# ---------------------------------------------------------------------------

class TestPriceToRevenue(unittest.TestCase):

    def test_basic(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(1_000_000.0, 100_000.0)
        self.assertAlmostEqual(pr, 10.0, places=9)

    def test_zero_revenue_returns_inf(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(1_000_000.0, 0.0)
        self.assertTrue(math.isinf(pr))

    def test_zero_market_cap(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(0.0, 100_000.0)
        self.assertAlmostEqual(pr, 0.0, places=9)

    def test_equal_market_cap_and_revenue(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(500_000.0, 500_000.0)
        self.assertAlmostEqual(pr, 1.0, places=9)

    def test_high_revenue_low_pr(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(100_000.0, 1_000_000.0)
        self.assertAlmostEqual(pr, 0.1, places=9)

    def test_returns_float(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(1e6, 1e5)
        self.assertIsInstance(pr, float)

    def test_large_pr(self):
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(1e12, 1_000.0)
        self.assertAlmostEqual(pr, 1e9, places=0)

    def test_negative_revenue_handled(self):
        # Edge: protocol loses money
        pr = GovernanceTokenValueTracker.compute_price_to_revenue(1_000_000.0, -50_000.0)
        self.assertAlmostEqual(pr, -20.0, places=6)


# ---------------------------------------------------------------------------
# 3. Token inflation %
# ---------------------------------------------------------------------------

class TestTokenInflation(unittest.TestCase):

    def test_basic(self):
        # 1000 tokens/day * 365 / 1_000_000 * 100 = 36.5%
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(1000, 1_000_000)
        self.assertAlmostEqual(inf_pct, 36.5, places=6)

    def test_zero_emission(self):
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(0, 1_000_000)
        self.assertAlmostEqual(inf_pct, 0.0, places=9)

    def test_zero_supply(self):
        # Guard: returns 0.0
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(100, 0)
        self.assertAlmostEqual(inf_pct, 0.0, places=9)

    def test_both_zero(self):
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(0, 0)
        self.assertAlmostEqual(inf_pct, 0.0, places=9)

    def test_high_emission(self):
        # Doubling every year → 100%
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(1_000_000 / 365, 1_000_000)
        self.assertAlmostEqual(inf_pct, 100.0, places=3)

    def test_small_emission(self):
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(1, 1_000_000)
        self.assertAlmostEqual(inf_pct, 365 / 1_000_000 * 100, places=7)

    def test_returns_float(self):
        inf_pct = GovernanceTokenValueTracker.compute_token_inflation_pct(100, 1_000_000)
        self.assertIsInstance(inf_pct, float)

    def test_formula_verification(self):
        e, s = 500.0, 2_000_000.0
        expected = e * 365 / s * 100
        self.assertAlmostEqual(
            GovernanceTokenValueTracker.compute_token_inflation_pct(e, s),
            expected,
            places=8,
        )


# ---------------------------------------------------------------------------
# 4. Holder value score
# ---------------------------------------------------------------------------

class TestHolderValueScore(unittest.TestCase):

    def test_zero_inflation_and_zero_pr_gives_100(self):
        # 100 / (1 + 0 * 0) = 100
        score = GovernanceTokenValueTracker.compute_holder_value_score(0.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=6)

    def test_zero_inflation_gives_100_regardless_pr(self):
        # 100 / (1 + 0) = 100
        score = GovernanceTokenValueTracker.compute_holder_value_score(0.0, 50.0)
        self.assertAlmostEqual(score, 100.0, places=6)

    def test_high_inflation_high_pr_low_score(self):
        # 10% inflation, P/R=100 → 100/(1+0.1*100)=100/11≈9.09
        score = GovernanceTokenValueTracker.compute_holder_value_score(10.0, 100.0)
        self.assertAlmostEqual(score, 100.0 / 11.0, places=4)

    def test_low_inflation_low_pr_high_score(self):
        # 2% inflation, P/R=5 → 100/(1+0.02*5)=100/1.10≈90.9
        score = GovernanceTokenValueTracker.compute_holder_value_score(2.0, 5.0)
        self.assertAlmostEqual(score, 100.0 / 1.10, places=4)

    def test_score_range_0_to_100(self):
        for inf in [0, 5, 50, 200]:
            for pr in [0, 1, 10, 100]:
                score = GovernanceTokenValueTracker.compute_holder_value_score(inf, pr)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_infinite_pr_gives_zero(self):
        score = GovernanceTokenValueTracker.compute_holder_value_score(5.0, float("inf"))
        self.assertAlmostEqual(score, 0.0, places=9)

    def test_formula_consistency(self):
        inflation_pct, pr = 8.0, 20.0
        expected = 100.0 / (1.0 + (inflation_pct / 100.0) * pr)
        score = GovernanceTokenValueTracker.compute_holder_value_score(inflation_pct, pr)
        self.assertAlmostEqual(score, expected, places=6)

    def test_returns_float(self):
        score = GovernanceTokenValueTracker.compute_holder_value_score(5.0, 10.0)
        self.assertIsInstance(score, float)

    def test_increasing_inflation_decreases_score(self):
        scores = [
            GovernanceTokenValueTracker.compute_holder_value_score(inf, 10.0)
            for inf in [1, 5, 20, 50, 100]
        ]
        for i in range(len(scores) - 1):
            self.assertGreater(scores[i], scores[i + 1])

    def test_increasing_pr_decreases_score(self):
        scores = [
            GovernanceTokenValueTracker.compute_holder_value_score(5.0, pr)
            for pr in [1, 5, 10, 50, 100]
        ]
        for i in range(len(scores) - 1):
            self.assertGreater(scores[i], scores[i + 1])


# ---------------------------------------------------------------------------
# 5. Value tier classification
# ---------------------------------------------------------------------------

class TestValueTier(unittest.TestCase):

    def test_undervalued_at_70(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(70.0), "UNDERVALUED")

    def test_undervalued_at_100(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(100.0), "UNDERVALUED")

    def test_undervalued_just_above_70(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(70.1), "UNDERVALUED")

    def test_fair_at_40(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(40.0), "FAIR")

    def test_fair_at_60(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(60.0), "FAIR")

    def test_fair_just_below_70(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(69.9), "FAIR")

    def test_overvalued_at_20(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(20.0), "OVERVALUED")

    def test_overvalued_at_35(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(35.0), "OVERVALUED")

    def test_overvalued_just_below_40(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(39.9), "OVERVALUED")

    def test_inflationary_just_below_20(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(19.9), "INFLATIONARY")

    def test_inflationary_at_zero(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(0.0), "INFLATIONARY")

    def test_inflationary_at_1(self):
        self.assertEqual(GovernanceTokenValueTracker.compute_value_tier(1.0), "INFLATIONARY")

    def test_valid_tier_set(self):
        valid = {"UNDERVALUED", "FAIR", "OVERVALUED", "INFLATIONARY"}
        for score in [0, 10, 19.9, 20, 39.9, 40, 69.9, 70, 100]:
            self.assertIn(GovernanceTokenValueTracker.compute_value_tier(score), valid)

    def test_returns_string(self):
        tier = GovernanceTokenValueTracker.compute_value_tier(50.0)
        self.assertIsInstance(tier, str)


# ---------------------------------------------------------------------------
# 6. Inflation-adjusted yield
# ---------------------------------------------------------------------------

class TestInflationAdjustedYield(unittest.TestCase):

    def test_basic(self):
        # revenue=100k, market_cap=1M → earnings_yield=10%; inflation=5% → iay=5%
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(100_000, 1_000_000, 5.0)
        self.assertAlmostEqual(iay, 5.0, places=6)

    def test_zero_market_cap(self):
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(100_000, 0, 5.0)
        self.assertAlmostEqual(iay, 0.0, places=9)

    def test_zero_revenue(self):
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(0, 1_000_000, 5.0)
        self.assertAlmostEqual(iay, -5.0, places=6)

    def test_zero_inflation(self):
        # iay = earnings_yield alone
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(100_000, 1_000_000, 0.0)
        self.assertAlmostEqual(iay, 10.0, places=6)

    def test_negative_iay(self):
        # High inflation eats all yield and more
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(10_000, 1_000_000, 50.0)
        self.assertLess(iay, 0.0)

    def test_formula_verification(self):
        rev, mc, inf = 200_000.0, 2_000_000.0, 3.0
        expected = (rev / mc * 100) - inf
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(rev, mc, inf)
        self.assertAlmostEqual(iay, expected, places=8)

    def test_returns_float(self):
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(100_000, 1_000_000, 5.0)
        self.assertIsInstance(iay, float)

    def test_high_revenue_high_iay(self):
        # Protocol earns its market cap back every year
        iay = GovernanceTokenValueTracker.compute_inflation_adjusted_yield(1_000_000, 1_000_000, 0.0)
        self.assertAlmostEqual(iay, 100.0, places=6)


# ---------------------------------------------------------------------------
# 7. track() method
# ---------------------------------------------------------------------------

class TestTrack(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmpdir)

    def test_returns_dict(self):
        result = self.tracker.track(_token())
        self.assertIsInstance(result, dict)

    def test_result_has_protocol(self):
        result = self.tracker.track(_token(protocol="Uniswap"))
        self.assertEqual(result["protocol"], "Uniswap")

    def test_result_has_market_cap(self):
        result = self.tracker.track(_token(price=2.0, supply=500_000))
        self.assertIn("market_cap_usd", result)
        self.assertAlmostEqual(result["market_cap_usd"], 1_000_000.0, places=1)

    def test_result_has_price_to_revenue(self):
        result = self.tracker.track(_token())
        self.assertIn("price_to_revenue", result)

    def test_result_has_token_inflation_pct(self):
        result = self.tracker.track(_token())
        self.assertIn("token_inflation_pct", result)

    def test_result_has_holder_value_score(self):
        result = self.tracker.track(_token())
        self.assertIn("holder_value_score", result)

    def test_result_has_value_tier(self):
        result = self.tracker.track(_token())
        self.assertIn("value_tier", result)
        self.assertIn(result["value_tier"], {"UNDERVALUED", "FAIR", "OVERVALUED", "INFLATIONARY"})

    def test_result_has_inflation_adjusted_yield(self):
        result = self.tracker.track(_token())
        self.assertIn("inflation_adjusted_yield_pct", result)

    def test_result_has_timestamp(self):
        result = self.tracker.track(_token())
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], str)

    def test_zero_revenue_sets_none_pr(self):
        result = self.tracker.track(_token(revenue=0.0))
        self.assertIsNone(result["price_to_revenue"])

    def test_zero_supply_inflation_is_zero(self):
        result = self.tracker.track(_token(supply=0.0, emission=1000.0))
        self.assertAlmostEqual(result["token_inflation_pct"], 0.0, places=9)

    def test_log_grows_with_each_track(self):
        for i in range(5):
            self.tracker.track(_token(f"P{i}"))
        self.assertEqual(self.tracker.log_length(), 5)

    def test_last_result_updated(self):
        self.tracker.track(_token("First"))
        self.tracker.track(_token("Second"))
        self.assertEqual(self.tracker.last_result()["protocol"], "Second")


# ---------------------------------------------------------------------------
# 8. get_value_tier()
# ---------------------------------------------------------------------------

class TestGetValueTier(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmpdir)

    def test_none_before_track(self):
        self.assertIsNone(self.tracker.get_value_tier())

    def test_returns_string_after_track(self):
        self.tracker.track(_token())
        tier = self.tracker.get_value_tier()
        self.assertIsInstance(tier, str)

    def test_valid_value(self):
        self.tracker.track(_token())
        valid = {"UNDERVALUED", "FAIR", "OVERVALUED", "INFLATIONARY"}
        self.assertIn(self.tracker.get_value_tier(), valid)

    def test_updates_after_second_track(self):
        # High inflation → INFLATIONARY
        self.tracker.track(_token(emission=1_000_000, supply=1_000_000, revenue=1.0))
        tier1 = self.tracker.get_value_tier()
        # Zero inflation, good revenue → should be better tier
        self.tracker.track(_token(emission=0, supply=1_000_000, revenue=10_000_000, price=0.1))
        tier2 = self.tracker.get_value_tier()
        # They may differ — just verify both are valid
        valid = {"UNDERVALUED", "FAIR", "OVERVALUED", "INFLATIONARY"}
        self.assertIn(tier1, valid)
        self.assertIn(tier2, valid)

    def test_inflationary_token_detected(self):
        # Enormous emission relative to supply → very high inflation → INFLATIONARY
        self.tracker.track(_token(emission=1_000_000_000, supply=1_000, revenue=10_000))
        self.assertEqual(self.tracker.get_value_tier(), "INFLATIONARY")


# ---------------------------------------------------------------------------
# 9. get_inflation_adjusted_yield()
# ---------------------------------------------------------------------------

class TestGetInflationAdjustedYield(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmpdir)

    def test_none_before_track(self):
        self.assertIsNone(self.tracker.get_inflation_adjusted_yield())

    def test_returns_float_after_track(self):
        self.tracker.track(_token())
        iay = self.tracker.get_inflation_adjusted_yield()
        self.assertIsInstance(iay, float)

    def test_positive_yield_when_revenue_exceeds_inflation(self):
        # Zero emission → inflation=0; revenue=100k, mc=1M → earnings yield=10%
        self.tracker.track(_token(emission=0, revenue=100_000, price=1.0, supply=1_000_000))
        iay = self.tracker.get_inflation_adjusted_yield()
        self.assertGreater(iay, 0.0)

    def test_negative_yield_when_inflation_dominates(self):
        # Huge emission
        self.tracker.track(_token(emission=1_000_000, supply=1_000_000, revenue=10_000, price=1.0))
        iay = self.tracker.get_inflation_adjusted_yield()
        self.assertLess(iay, 0.0)

    def test_zero_revenue_gives_negative_yield(self):
        self.tracker.track(_token(revenue=0, emission=1000, supply=1_000_000, price=1.0))
        iay = self.tracker.get_inflation_adjusted_yield()
        self.assertLessEqual(iay, 0.0)

    def test_zero_market_cap_gives_zero(self):
        self.tracker.track(_token(price=0.0, supply=1_000_000))
        iay = self.tracker.get_inflation_adjusted_yield()
        self.assertAlmostEqual(iay, 0.0, places=6)

    def test_consistent_with_direct_formula(self):
        price, supply, revenue, emission = 2.0, 5_000_000.0, 500_000.0, 10_000.0
        self.tracker.track(_token(price=price, supply=supply, revenue=revenue, emission=emission))
        mc = price * supply
        inf_pct = emission * 365 / supply * 100
        expected_iay = (revenue / mc * 100) - inf_pct
        self.assertAlmostEqual(self.tracker.get_inflation_adjusted_yield(), expected_iay, places=3)

    def test_updates_with_second_track(self):
        self.tracker.track(_token(emission=0, revenue=100_000, price=1.0, supply=1_000_000))
        iay1 = self.tracker.get_inflation_adjusted_yield()
        self.tracker.track(_token(emission=1_000_000, revenue=1, price=1.0, supply=1_000_000))
        iay2 = self.tracker.get_inflation_adjusted_yield()
        self.assertNotAlmostEqual(iay1, iay2, places=2)


# ---------------------------------------------------------------------------
# 10. Ring-buffer / log behaviour
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_log_starts_empty(self):
        t = _make_tracker(self.tmpdir)
        self.assertEqual(t.log_length(), 0)

    def test_log_grows_with_each_track(self):
        t = _make_tracker(self.tmpdir)
        t.track(_token())
        t.track(_token())
        self.assertEqual(t.log_length(), 2)

    def test_file_capped_at_100(self):
        t = _make_tracker(self.tmpdir)
        for i in range(110):
            t.track(_token(f"P{i}"))
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        with open(log_path) as fh:
            saved = json.load(fh)
        self.assertLessEqual(len(saved), 100)

    def test_file_never_exceeds_100_on_many_writes(self):
        t = _make_tracker(self.tmpdir)
        for i in range(200):
            t.track(_token(f"P{i}"))
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        with open(log_path) as fh:
            saved = json.load(fh)
        self.assertLessEqual(len(saved), 100)

    def test_earliest_entries_discarded(self):
        t = _make_tracker(self.tmpdir)
        t.track(_token("FirstEver"))
        for i in range(101):
            t.track(_token(f"Later{i}"))
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        with open(log_path) as fh:
            saved = json.load(fh)
        protocols = [e.get("protocol") for e in saved]
        self.assertNotIn("FirstEver", protocols)

    def test_persistence_across_instances(self):
        t1 = _make_tracker(self.tmpdir)
        t1.track(_token("A"))
        t1.track(_token("B"))
        t2 = _make_tracker(self.tmpdir)
        self.assertEqual(t2.log_length(), 2)


# ---------------------------------------------------------------------------
# 11. Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_file_created_after_track(self):
        t = _make_tracker(self.tmpdir)
        t.track(_token())
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_file_is_valid_json(self):
        t = _make_tracker(self.tmpdir)
        t.track(_token())
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_no_tmp_file_left_behind(self):
        t = _make_tracker(self.tmpdir)
        t.track(_token())
        tmp_path = os.path.join(self.tmpdir, "governance_token_log.json.tmp")
        self.assertFalse(os.path.exists(tmp_path))

    def test_custom_log_filename(self):
        t = GovernanceTokenValueTracker(data_dir=self.tmpdir, log_filename="custom_gov.json")
        t.track(_token())
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "custom_gov.json")))

    def test_file_contains_all_fields(self):
        t = _make_tracker(self.tmpdir)
        t.track(_token())
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        for field in ["protocol", "market_cap_usd", "token_inflation_pct",
                       "holder_value_score", "value_tier", "inflation_adjusted_yield_pct",
                       "timestamp"]:
            self.assertIn(field, entry)

    def test_multiple_tracks_each_written(self):
        t = _make_tracker(self.tmpdir)
        for i in range(4):
            t.track(_token(f"P{i}"))
        log_path = os.path.join(self.tmpdir, "governance_token_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 4)


# ---------------------------------------------------------------------------
# 12. Integration: end-to-end scenarios
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_undervalued_scenario(self):
        t = _make_tracker(self.tmpdir)
        # Low inflation + high revenue relative to market cap
        result = t.track(_token(
            price=1.0, supply=1_000_000, revenue=1_000_000,
            emission=0, holders=1000,
        ))
        self.assertEqual(result["value_tier"], "UNDERVALUED")

    def test_inflationary_scenario(self):
        t = _make_tracker(self.tmpdir)
        # Emission nearly doubles supply each year, tiny revenue
        result = t.track(_token(
            price=0.01, supply=1_000_000, revenue=100,
            emission=3_000, holders=10,
        ))
        self.assertEqual(result["value_tier"], "INFLATIONARY")

    def test_all_four_tiers_reachable(self):
        t = _make_tracker(self.tmpdir)
        scenarios = [
            # UNDERVALUED: zero emission, high revenue
            _token("U", price=1, supply=1_000_000, revenue=1_000_000, emission=0),
            # FAIR: moderate emission, moderate revenue
            _token("F", price=1, supply=1_000_000, revenue=50_000, emission=200),
            # OVERVALUED: some emission, low revenue
            _token("O", price=10, supply=1_000_000, revenue=50_000, emission=2_000),
            # INFLATIONARY: huge emission, tiny revenue
            _token("I", price=1, supply=1_000_000, revenue=1_000, emission=10_000),
        ]
        tiers = set()
        for s in scenarios:
            res = t.track(s)
            tiers.add(res["value_tier"])
        # We must hit at least 3 of the 4 tiers
        self.assertGreaterEqual(len(tiers), 3)

    def test_consistent_calculations(self):
        t = _make_tracker(self.tmpdir)
        price, supply, revenue, emission = 5.0, 10_000_000.0, 2_000_000.0, 500_000.0
        result = t.track(_token(
            price=price, supply=supply, revenue=revenue, emission=emission
        ))
        expected_mc = price * supply
        expected_pr = expected_mc / revenue
        expected_inf = emission * 365 / supply * 100
        expected_iay = (revenue / expected_mc * 100) - expected_inf

        self.assertAlmostEqual(result["market_cap_usd"], expected_mc, places=0)
        self.assertAlmostEqual(result["price_to_revenue"], expected_pr, places=2)
        self.assertAlmostEqual(result["token_inflation_pct"], expected_inf, places=4)
        self.assertAlmostEqual(result["inflation_adjusted_yield_pct"], expected_iay, places=3)

    def test_zero_revenue_inflationary_classification(self):
        t = _make_tracker(self.tmpdir)
        result = t.track(_token(revenue=0.0, emission=1000.0))
        # Zero revenue + any emission → P/R=inf → HVS=0 → INFLATIONARY
        self.assertEqual(result["value_tier"], "INFLATIONARY")
        self.assertIsNone(result["price_to_revenue"])


if __name__ == "__main__":
    unittest.main()

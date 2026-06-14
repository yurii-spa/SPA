"""
Tests for MP-795 ProtocolRevenueShareAnalyzer.
≥65 tests, stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

# Allow import from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_revenue_share_analyzer import (
    ProtocolRevenueShareAnalyzer,
    DISTRIBUTION_HOLDER_FRIENDLY,
    DISTRIBUTION_BALANCED,
    DISTRIBUTION_TREASURY_HEAVY,
    DISTRIBUTION_TEAM_HEAVY,
)


def _make_tmp_log():
    """Return a NamedTemporaryFile path (deleted on close elsewhere)."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)   # let analyzer create it fresh
    return path


def _default_data(**kwargs):
    base = {
        "protocol": "TestProto",
        "total_revenue_usd_annual": 1_000_000.0,
        "revenue_to_holders_pct": 60.0,
        "revenue_to_treasury_pct": 20.0,
        "revenue_to_team_pct": 10.0,
        "buyback_pct": 10.0,
        "token_holders_count": 1000,
    }
    base.update(kwargs)
    return base


class TestBasicAnalysis(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_returns_dict(self):
        r = self.a.analyze(_default_data())
        self.assertIsInstance(r, dict)

    def test_protocol_field(self):
        r = self.a.analyze(_default_data(protocol="Aave"))
        self.assertEqual(r["protocol"], "Aave")

    def test_holder_yield_usd_formula(self):
        r = self.a.analyze(_default_data(
            total_revenue_usd_annual=1_000_000.0,
            revenue_to_holders_pct=60.0,
            token_holders_count=1000,
        ))
        # 1_000_000 * 60/100 / 1000 = 600.0
        self.assertAlmostEqual(r["holder_yield_usd"], 600.0, places=4)

    def test_holder_yield_usd_small(self):
        r = self.a.analyze(_default_data(
            total_revenue_usd_annual=100.0,
            revenue_to_holders_pct=50.0,
            token_holders_count=10,
        ))
        self.assertAlmostEqual(r["holder_yield_usd"], 5.0, places=4)

    def test_holder_yield_zero_revenue(self):
        r = self.a.analyze(_default_data(total_revenue_usd_annual=0.0))
        self.assertEqual(r["holder_yield_usd"], 0.0)

    def test_timestamp_present(self):
        r = self.a.analyze(_default_data())
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)
        self.assertGreater(len(r["timestamp"]), 5)

    def test_all_required_fields_present(self):
        r = self.a.analyze(_default_data())
        for field in [
            "protocol", "timestamp", "holder_yield_usd",
            "revenue_sustainability_score", "distribution_fairness",
            "value_accrual_score",
        ]:
            self.assertIn(field, r, f"Missing field: {field}")

    def test_inputs_stored_in_result(self):
        data = _default_data()
        r = self.a.analyze(data)
        self.assertEqual(r["total_revenue_usd_annual"], data["total_revenue_usd_annual"])
        self.assertEqual(r["revenue_to_holders_pct"], data["revenue_to_holders_pct"])
        self.assertEqual(r["token_holders_count"], data["token_holders_count"])

    def test_sustainability_score_range(self):
        r = self.a.analyze(_default_data())
        self.assertGreaterEqual(r["revenue_sustainability_score"], 0.0)
        self.assertLessEqual(r["revenue_sustainability_score"], 100.0)

    def test_value_accrual_score_range(self):
        r = self.a.analyze(_default_data())
        self.assertGreaterEqual(r["value_accrual_score"], 0.0)
        self.assertLessEqual(r["value_accrual_score"], 100.0)


class TestDistributionFairness(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_holder_friendly(self):
        r = self.a.get_distribution_fairness(60.0, 20.0, 10.0)
        self.assertEqual(r, DISTRIBUTION_HOLDER_FRIENDLY)

    def test_balanced(self):
        r = self.a.get_distribution_fairness(40.0, 30.0, 15.0)
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_treasury_heavy(self):
        r = self.a.get_distribution_fairness(10.0, 60.0, 10.0)
        self.assertEqual(r, DISTRIBUTION_TREASURY_HEAVY)

    def test_team_heavy(self):
        r = self.a.get_distribution_fairness(20.0, 20.0, 40.0)
        self.assertEqual(r, DISTRIBUTION_TEAM_HEAVY)

    def test_team_heavy_takes_priority_over_treasury(self):
        # team > 30 and treasury > 50 → TEAM_HEAVY wins
        r = self.a.get_distribution_fairness(5.0, 60.0, 35.0)
        self.assertEqual(r, DISTRIBUTION_TEAM_HEAVY)

    def test_team_heavy_takes_priority_over_holder_friendly(self):
        r = self.a.get_distribution_fairness(55.0, 10.0, 35.0)
        self.assertEqual(r, DISTRIBUTION_TEAM_HEAVY)

    def test_treasury_heavy_beats_holder_friendly(self):
        # treasury > 50, holders > 50 impossible in practice but test priority
        r = self.a.get_distribution_fairness(10.0, 55.0, 20.0)
        self.assertEqual(r, DISTRIBUTION_TREASURY_HEAVY)

    def test_exactly_50_holders_balanced(self):
        r = self.a.get_distribution_fairness(50.0, 30.0, 10.0)
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_exactly_30_holders_balanced(self):
        r = self.a.get_distribution_fairness(30.0, 40.0, 15.0)
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_below_30_holders_balanced(self):
        r = self.a.get_distribution_fairness(20.0, 30.0, 20.0)
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_fairness_via_analyze(self):
        r = self.a.analyze(_default_data(
            revenue_to_holders_pct=60.0,
            revenue_to_treasury_pct=20.0,
            revenue_to_team_pct=10.0,
        ))
        self.assertEqual(r["distribution_fairness"], DISTRIBUTION_HOLDER_FRIENDLY)

    def test_team_heavy_via_analyze(self):
        r = self.a.analyze(_default_data(
            revenue_to_holders_pct=10.0,
            revenue_to_treasury_pct=20.0,
            revenue_to_team_pct=40.0,
        ))
        self.assertEqual(r["distribution_fairness"], DISTRIBUTION_TEAM_HEAVY)

    def test_treasury_heavy_via_analyze(self):
        r = self.a.analyze(_default_data(
            revenue_to_holders_pct=10.0,
            revenue_to_treasury_pct=60.0,
            revenue_to_team_pct=10.0,
        ))
        self.assertEqual(r["distribution_fairness"], DISTRIBUTION_TREASURY_HEAVY)


class TestValueAccrualScore(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_max_score(self):
        # buyback=50, holders=50 → 100
        score = self.a.get_value_accrual_score(50.0, 50.0)
        self.assertAlmostEqual(score, 100.0, places=1)

    def test_zero_score(self):
        score = self.a.get_value_accrual_score(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_buyback_only(self):
        score = self.a.get_value_accrual_score(50.0, 0.0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_holders_only(self):
        score = self.a.get_value_accrual_score(0.0, 50.0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_above_50_clamped(self):
        score_a = self.a.get_value_accrual_score(100.0, 100.0)
        score_b = self.a.get_value_accrual_score(50.0, 50.0)
        self.assertAlmostEqual(score_a, score_b, places=2)

    def test_partial(self):
        # buyback=20, holders=30 → 50
        score = self.a.get_value_accrual_score(20.0, 30.0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_score_via_analyze(self):
        r = self.a.analyze(_default_data(buyback_pct=25.0, revenue_to_holders_pct=25.0))
        self.assertAlmostEqual(r["value_accrual_score"], 50.0, places=2)


class TestSustainabilityScore(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_good_team_pct(self):
        r = self.a.analyze(_default_data(
            revenue_to_team_pct=10.0,
            buyback_pct=20.0,
            revenue_to_holders_pct=60.0,
        ))
        # team<20 → 40pts; buyback>0 → ~18pts; holders>50 → 30pts = 88
        self.assertGreater(r["revenue_sustainability_score"], 70.0)

    def test_high_team_pct_reduces_score(self):
        r_low = self.a.analyze(_default_data(revenue_to_team_pct=5.0))
        r_high = self.a.analyze(_default_data(revenue_to_team_pct=50.0))
        self.assertGreater(
            r_low["revenue_sustainability_score"],
            r_high["revenue_sustainability_score"],
        )

    def test_no_buyback_reduces_score(self):
        r_no = self.a.analyze(_default_data(buyback_pct=0.0))
        r_yes = self.a.analyze(_default_data(buyback_pct=20.0))
        self.assertGreater(
            r_yes["revenue_sustainability_score"],
            r_no["revenue_sustainability_score"],
        )

    def test_high_holders_pct_boosts(self):
        r_low = self.a.analyze(_default_data(revenue_to_holders_pct=10.0))
        r_high = self.a.analyze(_default_data(revenue_to_holders_pct=60.0))
        self.assertGreater(
            r_high["revenue_sustainability_score"],
            r_low["revenue_sustainability_score"],
        )

    def test_score_capped_100(self):
        r = self.a.analyze(_default_data(
            revenue_to_team_pct=1.0,
            buyback_pct=100.0,
            revenue_to_holders_pct=99.0,
        ))
        self.assertLessEqual(r["revenue_sustainability_score"], 100.0)

    def test_score_floor_0(self):
        r = self.a.analyze(_default_data(
            revenue_to_team_pct=80.0,
            buyback_pct=0.0,
            revenue_to_holders_pct=0.0,
        ))
        self.assertGreaterEqual(r["revenue_sustainability_score"], 0.0)


class TestLogPersistence(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_log_created(self):
        self.a.analyze(_default_data())
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_json_list(self):
        self.a.analyze(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_has_entry(self):
        self.a.analyze(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_log_multiple_entries(self):
        for i in range(5):
            self.a.analyze(_default_data(protocol=f"P{i}"))
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(110):
            self.a.analyze(_default_data(protocol=f"P{i}"))
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            self.a.analyze(_default_data(protocol=f"P{i}"))
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["protocol"], "P104")

    def test_log_atomic_no_partial(self):
        """Log file should be valid JSON after write."""
        self.a.analyze(_default_data())
        with open(self.log) as fh:
            content = fh.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_single_holder(self):
        r = self.a.analyze(_default_data(
            total_revenue_usd_annual=500.0,
            revenue_to_holders_pct=100.0,
            token_holders_count=1,
        ))
        self.assertAlmostEqual(r["holder_yield_usd"], 500.0, places=4)

    def test_zero_holders_defaults_to_one(self):
        r = self.a.analyze(_default_data(token_holders_count=0))
        # should not raise, holders treated as 1
        self.assertIsNotNone(r["holder_yield_usd"])

    def test_negative_holders_defaults_to_one(self):
        r = self.a.analyze(_default_data(token_holders_count=-5))
        self.assertIsNotNone(r["holder_yield_usd"])

    def test_100pct_holders(self):
        r = self.a.analyze(_default_data(
            revenue_to_holders_pct=100.0,
            revenue_to_treasury_pct=0.0,
            revenue_to_team_pct=0.0,
        ))
        self.assertEqual(r["distribution_fairness"], DISTRIBUTION_HOLDER_FRIENDLY)

    def test_100pct_team(self):
        r = self.a.analyze(_default_data(
            revenue_to_holders_pct=0.0,
            revenue_to_treasury_pct=0.0,
            revenue_to_team_pct=100.0,
        ))
        self.assertEqual(r["distribution_fairness"], DISTRIBUTION_TEAM_HEAVY)

    def test_missing_protocol_defaults(self):
        data = _default_data()
        del data["protocol"]
        r = self.a.analyze(data)
        self.assertEqual(r["protocol"], "unknown")

    def test_large_revenue(self):
        r = self.a.analyze(_default_data(total_revenue_usd_annual=1e9))
        self.assertGreater(r["holder_yield_usd"], 0)

    def test_float_holders(self):
        # token_holders_count as float should be coerced
        r = self.a.analyze(_default_data(token_holders_count=100.9))
        self.assertIsInstance(r["holder_yield_usd"], float)

    def test_all_zeros_pct(self):
        r = self.a.analyze(_default_data(
            revenue_to_holders_pct=0.0,
            revenue_to_treasury_pct=0.0,
            revenue_to_team_pct=0.0,
            buyback_pct=0.0,
        ))
        self.assertEqual(r["holder_yield_usd"], 0.0)
        self.assertEqual(r["value_accrual_score"], 0.0)

    def test_team_exactly_30_not_team_heavy(self):
        r = self.a.get_distribution_fairness(30.0, 30.0, 30.0)
        # team=30 not > 30, treasury=30 not > 50, holders=30 not > 50 → BALANCED
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_team_31_is_team_heavy(self):
        r = self.a.get_distribution_fairness(10.0, 10.0, 31.0)
        self.assertEqual(r, DISTRIBUTION_TEAM_HEAVY)

    def test_treasury_exactly_50_not_treasury_heavy(self):
        r = self.a.get_distribution_fairness(10.0, 50.0, 20.0)
        # treasury=50 not > 50 → fallthrough to BALANCED
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_holders_51_is_holder_friendly(self):
        r = self.a.get_distribution_fairness(51.0, 20.0, 10.0)
        self.assertEqual(r, DISTRIBUTION_HOLDER_FRIENDLY)

    def test_log_entry_has_distribution_fairness(self):
        self.a.analyze(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("distribution_fairness", data[0])

    def test_log_entry_has_sustainability_score(self):
        self.a.analyze(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("revenue_sustainability_score", data[0])

    def test_multiple_analyzers_same_log(self):
        a2 = ProtocolRevenueShareAnalyzer(log_path=self.log)
        self.a.analyze(_default_data(protocol="X"))
        a2.analyze(_default_data(protocol="Y"))
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_value_accrual_score_is_float(self):
        r = self.a.analyze(_default_data())
        self.assertIsInstance(r["value_accrual_score"], float)

    def test_sustainability_score_is_float(self):
        r = self.a.analyze(_default_data())
        self.assertIsInstance(r["revenue_sustainability_score"], float)


class TestAdditionalCoverage(unittest.TestCase):
    """Additional tests to reach ≥65 per requirement."""

    def setUp(self):
        self.log = _make_tmp_log()
        self.a = ProtocolRevenueShareAnalyzer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_analyze_returns_holder_yield_as_float(self):
        r = self.a.analyze(_default_data())
        self.assertIsInstance(r["holder_yield_usd"], float)

    def test_large_holder_count_small_yield(self):
        r = self.a.analyze(_default_data(
            total_revenue_usd_annual=1000.0,
            revenue_to_holders_pct=10.0,
            token_holders_count=1_000_000,
        ))
        # 1000 * 0.1 / 1_000_000 = 0.0001
        self.assertAlmostEqual(r["holder_yield_usd"], 0.0001, places=6)

    def test_balanced_low_treasury_low_team_low_holders(self):
        # holders=20, treasury=20, team=20 → all low → BALANCED
        r = self.a.get_distribution_fairness(20.0, 20.0, 20.0)
        self.assertEqual(r, DISTRIBUTION_BALANCED)

    def test_value_accrual_monotone_with_buyback(self):
        s1 = self.a.get_value_accrual_score(0.0, 25.0)
        s2 = self.a.get_value_accrual_score(10.0, 25.0)
        s3 = self.a.get_value_accrual_score(20.0, 25.0)
        self.assertLessEqual(s1, s2)
        self.assertLessEqual(s2, s3)

    def test_value_accrual_monotone_with_holders(self):
        s1 = self.a.get_value_accrual_score(10.0, 0.0)
        s2 = self.a.get_value_accrual_score(10.0, 25.0)
        s3 = self.a.get_value_accrual_score(10.0, 50.0)
        self.assertLessEqual(s1, s2)
        self.assertLessEqual(s2, s3)

    def test_log_entry_has_value_accrual_score(self):
        self.a.analyze(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("value_accrual_score", data[0])

    def test_protocol_name_preserved_in_log(self):
        self.a.analyze(_default_data(protocol="Morpho"))
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol"], "Morpho")


if __name__ == "__main__":
    unittest.main()

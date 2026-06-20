"""
Tests for MP-809 YieldSourceClassifier.
Run: python3 -m unittest spa_core.tests.test_yield_source_classifier -v
"""

import json
import os
import sys
import time
import unittest
import tempfile

# Ensure project root is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.yield_source_classifier import (
    analyze,
    analyze_and_log,
    log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bd(total=10.0, fee=5.0, emission=3.0, price=2.0):
    return {
        "total_apy": total,
        "fee_apy": fee,
        "emission_apy": emission,
        "price_appreciation_apy": price,
    }


# ---------------------------------------------------------------------------
# 1. Return-structure tests
# ---------------------------------------------------------------------------
class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.result = analyze("TestProto", _bd())

    def test_has_protocol(self):
        self.assertIn("protocol", self.result)

    def test_has_total_apy(self):
        self.assertIn("total_apy", self.result)

    def test_has_breakdown(self):
        self.assertIn("breakdown", self.result)

    def test_breakdown_has_fee_apy(self):
        self.assertIn("fee_apy", self.result["breakdown"])

    def test_breakdown_has_emission_apy(self):
        self.assertIn("emission_apy", self.result["breakdown"])

    def test_breakdown_has_price_appreciation_apy(self):
        self.assertIn("price_appreciation_apy", self.result["breakdown"])

    def test_breakdown_has_fee_pct(self):
        self.assertIn("fee_pct", self.result["breakdown"])

    def test_breakdown_has_emission_pct(self):
        self.assertIn("emission_pct", self.result["breakdown"])

    def test_breakdown_has_price_appreciation_pct(self):
        self.assertIn("price_appreciation_pct", self.result["breakdown"])

    def test_has_real_yield_apy(self):
        self.assertIn("real_yield_apy", self.result)

    def test_has_real_yield_pct(self):
        self.assertIn("real_yield_pct", self.result)

    def test_has_emission_pct(self):
        self.assertIn("emission_pct", self.result)

    def test_has_sustainability(self):
        self.assertIn("sustainability", self.result)

    def test_has_sustainability_score(self):
        self.assertIn("sustainability_score", self.result)

    def test_has_risk_flags(self):
        self.assertIn("risk_flags", self.result)

    def test_has_recommendation(self):
        self.assertIn("recommendation", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_protocol_matches(self):
        self.assertEqual(self.result["protocol"], "TestProto")

    def test_total_apy_matches(self):
        self.assertAlmostEqual(self.result["total_apy"], 10.0)

    def test_sustainability_score_is_int(self):
        self.assertIsInstance(self.result["sustainability_score"], int)

    def test_risk_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)


# ---------------------------------------------------------------------------
# 2. Percentage math tests
# ---------------------------------------------------------------------------
class TestPercentageMath(unittest.TestCase):

    def test_fee_pct_basic(self):
        r = analyze("P", _bd(total=10, fee=5, emission=3, price=2))
        self.assertAlmostEqual(r["breakdown"]["fee_pct"], 50.0)

    def test_emission_pct_basic(self):
        r = analyze("P", _bd(total=10, fee=5, emission=3, price=2))
        self.assertAlmostEqual(r["breakdown"]["emission_pct"], 30.0)

    def test_price_appreciation_pct_basic(self):
        r = analyze("P", _bd(total=10, fee=5, emission=3, price=2))
        self.assertAlmostEqual(r["breakdown"]["price_appreciation_pct"], 20.0)

    def test_real_yield_apy_sum(self):
        r = analyze("P", _bd(total=10, fee=4, emission=2, price=4))
        self.assertAlmostEqual(r["real_yield_apy"], 8.0)

    def test_real_yield_pct_sum(self):
        r = analyze("P", _bd(total=10, fee=4, emission=2, price=4))
        self.assertAlmostEqual(r["real_yield_pct"], 80.0)

    def test_emission_pct_top_level_matches_breakdown(self):
        r = analyze("P", _bd(total=10, fee=5, emission=3, price=2))
        self.assertAlmostEqual(r["emission_pct"], r["breakdown"]["emission_pct"])

    def test_all_pct_zero_when_total_zero(self):
        r = analyze("P", _bd(total=0, fee=0, emission=0, price=0))
        self.assertEqual(r["breakdown"]["fee_pct"], 0.0)
        self.assertEqual(r["breakdown"]["emission_pct"], 0.0)
        self.assertEqual(r["breakdown"]["price_appreciation_pct"], 0.0)


# ---------------------------------------------------------------------------
# 3. Sustainability classification tests
# ---------------------------------------------------------------------------
class TestSustainabilityClassification(unittest.TestCase):

    def test_negative_when_total_apy_zero(self):
        r = analyze("P", _bd(total=0, fee=0, emission=0, price=0))
        self.assertEqual(r["sustainability"], "NEGATIVE")

    def test_negative_when_total_apy_negative(self):
        r = analyze("P", _bd(total=-1, fee=0, emission=0, price=-1))
        self.assertEqual(r["sustainability"], "NEGATIVE")

    def test_inflationary_high_emissions(self):
        # emission_apy = 8.5 out of total 10 → 85% ≥ 80%
        r = analyze("P", _bd(total=10, fee=0.5, emission=8.5, price=1.0))
        self.assertEqual(r["sustainability"], "INFLATIONARY")

    def test_inflationary_exactly_at_threshold(self):
        # emission 80% exactly → INFLATIONARY
        r = analyze("P", _bd(total=10, fee=1.0, emission=8.0, price=1.0))
        self.assertEqual(r["sustainability"], "INFLATIONARY")

    def test_sustainable_high_real_yield(self):
        # fee=7, price=1 → real=8/10=80% ≥ 50%
        r = analyze("P", _bd(total=10, fee=7, emission=2, price=1))
        self.assertEqual(r["sustainability"], "SUSTAINABLE")

    def test_sustainable_exactly_at_threshold(self):
        # real_yield = 50% exactly
        r = analyze("P", _bd(total=10, fee=4, emission=5, price=1))
        # real_yield_apy = 5 → 50% ≥ 50%
        self.assertEqual(r["sustainability"], "SUSTAINABLE")

    def test_mixed_partial_real_yield(self):
        # emission = 50% < 80% (not INFLATIONARY), real=50% (borderline), let's make it 40%
        r = analyze("P", _bd(total=10, fee=2, emission=5, price=2))
        # real = 4/10 = 40% < 50%, emission=5/10=50% < 80%
        self.assertEqual(r["sustainability"], "MIXED")

    def test_inflationary_before_sustainable_check(self):
        # emission=85%, but if real_yield > 50%, INFLATIONARY wins
        # emission=85% → INFLATIONARY regardless
        r = analyze("P", _bd(total=10, fee=1.0, emission=8.5, price=0.5))
        self.assertEqual(r["sustainability"], "INFLATIONARY")

    def test_custom_threshold_sustainable(self):
        # With real_yield_threshold=30, 40% real yield → SUSTAINABLE
        r = analyze("P", _bd(total=10, fee=3, emission=5, price=1),
                    config={"real_yield_threshold": 30.0})
        self.assertEqual(r["sustainability"], "SUSTAINABLE")

    def test_custom_emission_threshold(self):
        # emission=75% < default 80%, but with threshold=70% → INFLATIONARY
        r = analyze("P", _bd(total=10, fee=1, emission=7.5, price=1.5),
                    config={"emission_danger_threshold": 70.0})
        self.assertEqual(r["sustainability"], "INFLATIONARY")


# ---------------------------------------------------------------------------
# 4. Sustainability score tests
# ---------------------------------------------------------------------------
class TestSustainabilityScore(unittest.TestCase):

    def test_score_zero_when_negative_total(self):
        r = analyze("P", _bd(total=0, fee=0, emission=0, price=0))
        self.assertEqual(r["sustainability_score"], 0)

    def test_score_is_int(self):
        r = analyze("P", _bd())
        self.assertIsInstance(r["sustainability_score"], int)

    def test_score_clamped_min_zero(self):
        # emission=90% → -30 penalty; real=10% → base 10 → 10-30=-20 → clamped to 0
        r = analyze("P", _bd(total=10, fee=0.5, emission=9.0, price=0.5))
        self.assertGreaterEqual(r["sustainability_score"], 0)

    def test_score_clamped_max_100(self):
        r = analyze("P", _bd(total=10, fee=10, emission=0, price=0))
        self.assertLessEqual(r["sustainability_score"], 100)

    def test_score_penalty_above_80_emission(self):
        # 85% emission → -30 penalty
        r1 = analyze("P", _bd(total=10, fee=1, emission=8.5, price=0.5))
        # Only 50% emission → -15 penalty
        r2 = analyze("P", _bd(total=10, fee=4, emission=5, price=1))
        self.assertLess(r1["sustainability_score"], r2["sustainability_score"])

    def test_score_penalty_above_50_emission(self):
        # 60% emission → -15; 30% emission → no penalty
        r_high_emission = analyze("P", _bd(total=10, fee=3, emission=6, price=1))
        r_low_emission = analyze("P", _bd(total=10, fee=6, emission=3, price=1))
        self.assertLess(r_high_emission["sustainability_score"], r_low_emission["sustainability_score"])

    def test_score_base_is_real_yield_pct(self):
        # real_yield = 60%, emission=30% (no penalty) → score=60
        r = analyze("P", _bd(total=10, fee=5, emission=3, price=1))
        # real_yield = 6/10 * 100 = 60, emission = 3/10*100=30 (<50%) no penalty
        self.assertEqual(r["sustainability_score"], 60)

    def test_score_caps_at_100_even_with_penalty(self):
        # real_yield_pct > 100 impossible, but clamp to 100 then subtract
        r = analyze("P", _bd(total=10, fee=10, emission=0, price=0))
        self.assertEqual(r["sustainability_score"], 100)


# ---------------------------------------------------------------------------
# 5. Risk flags tests
# ---------------------------------------------------------------------------
class TestRiskFlags(unittest.TestCase):

    def test_high_emission_flag(self):
        r = analyze("P", _bd(total=10, fee=0.5, emission=8.5, price=1.0))
        self.assertIn("High token emission dependency", r["risk_flags"])

    def test_majority_inflationary_flag(self):
        # 60% emission → majority flag
        r = analyze("P", _bd(total=10, fee=3, emission=6, price=1))
        self.assertIn("Majority of yield is inflationary", r["risk_flags"])

    def test_no_majority_flag_when_above_80(self):
        # >80% → "High token emission dependency", NOT "Majority of yield is inflationary"
        r = analyze("P", _bd(total=10, fee=0.5, emission=8.5, price=1.0))
        self.assertNotIn("Majority of yield is inflationary", r["risk_flags"])

    def test_unsustainably_high_apy_flag(self):
        # total=60, real_yield_pct=10% (<20%)
        r = analyze("P", _bd(total=60, fee=3, emission=55, price=2))
        self.assertIn("Unsustainably high APY", r["risk_flags"])

    def test_no_high_apy_flag_when_under_50(self):
        r = analyze("P", _bd(total=40, fee=20, emission=18, price=2))
        self.assertNotIn("Unsustainably high APY", r["risk_flags"])

    def test_negative_price_appreciation_flag(self):
        r = analyze("P", _bd(total=8, fee=6, emission=4, price=-2))
        self.assertIn("Negative price appreciation component", r["risk_flags"])

    def test_no_negative_price_flag_when_zero(self):
        r = analyze("P", _bd(total=10, fee=8, emission=2, price=0))
        self.assertNotIn("Negative price appreciation component", r["risk_flags"])

    def test_inconsistent_apy_flag(self):
        # total_apy=3, fee_apy=5 → inconsistent
        r = analyze("P", _bd(total=3, fee=5, emission=0, price=-2))
        self.assertIn("APY components inconsistent", r["risk_flags"])

    def test_no_flags_for_clean_yield(self):
        # Clean: total=10, fee=8, emission=1, price=1 → no flags
        r = analyze("P", _bd(total=10, fee=8, emission=1, price=1))
        self.assertEqual(r["risk_flags"], [])

    def test_multiple_flags_can_coexist(self):
        # high emission + unsustainable APY
        r = analyze("P", _bd(total=100, fee=2, emission=90, price=8))
        self.assertGreaterEqual(len(r["risk_flags"]), 2)


# ---------------------------------------------------------------------------
# 6. Recommendation tests
# ---------------------------------------------------------------------------
class TestRecommendation(unittest.TestCase):

    def test_recommendation_negative(self):
        r = analyze("P", _bd(total=0, fee=0, emission=0, price=0))
        self.assertIn("negative", r["recommendation"].lower())

    def test_recommendation_inflationary(self):
        r = analyze("P", _bd(total=10, fee=0.5, emission=8.5, price=1.0))
        self.assertIn("emissions", r["recommendation"].lower())

    def test_recommendation_sustainable(self):
        r = analyze("P", _bd(total=10, fee=7, emission=2, price=1))
        self.assertIn("revenue", r["recommendation"].lower())

    def test_recommendation_mixed(self):
        r = analyze("P", _bd(total=10, fee=2, emission=5, price=2))
        self.assertIn("monitor", r["recommendation"].lower())

    def test_recommendation_is_string(self):
        r = analyze("P", _bd())
        self.assertIsInstance(r["recommendation"], str)

    def test_recommendation_nonempty(self):
        r = analyze("P", _bd())
        self.assertGreater(len(r["recommendation"]), 0)


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):

    def test_zero_total_apy(self):
        r = analyze("P", _bd(total=0, fee=0, emission=0, price=0))
        self.assertEqual(r["sustainability"], "NEGATIVE")
        self.assertEqual(r["sustainability_score"], 0)
        self.assertEqual(r["real_yield_pct"], 0.0)
        self.assertEqual(r["emission_pct"], 0.0)

    def test_negative_total_apy(self):
        r = analyze("P", _bd(total=-5, fee=1, emission=0, price=-6))
        self.assertEqual(r["sustainability"], "NEGATIVE")

    def test_all_fee_no_emission(self):
        r = analyze("P", _bd(total=10, fee=10, emission=0, price=0))
        self.assertEqual(r["sustainability"], "SUSTAINABLE")
        self.assertAlmostEqual(r["breakdown"]["fee_pct"], 100.0)

    def test_all_emission_no_fee(self):
        r = analyze("P", _bd(total=10, fee=0, emission=10, price=0))
        self.assertEqual(r["sustainability"], "INFLATIONARY")
        self.assertAlmostEqual(r["breakdown"]["emission_pct"], 100.0)

    def test_floating_point_components(self):
        r = analyze("P", _bd(total=3.333, fee=1.111, emission=1.111, price=1.111))
        self.assertAlmostEqual(r["real_yield_apy"], 2.222, places=2)

    def test_large_values(self):
        r = analyze("P", _bd(total=1e6, fee=5e5, emission=3e5, price=2e5))
        self.assertAlmostEqual(r["breakdown"]["fee_pct"], 50.0)

    def test_small_values(self):
        r = analyze("P", _bd(total=0.01, fee=0.006, emission=0.002, price=0.002))
        self.assertAlmostEqual(r["breakdown"]["fee_pct"], 60.0)

    def test_config_none_uses_defaults(self):
        r1 = analyze("P", _bd(), config=None)
        r2 = analyze("P", _bd(), config={})
        self.assertEqual(r1["sustainability"], r2["sustainability"])

    def test_timestamp_is_recent(self):
        before = time.time()
        r = analyze("P", _bd())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_protocol_name_preserved(self):
        r = analyze("Morpho Steakhouse", _bd())
        self.assertEqual(r["protocol"], "Morpho Steakhouse")

    def test_real_yield_pct_negative_price_reduces_real(self):
        # fee=5, price=-3 → real=2, real_pct=20%
        r = analyze("P", _bd(total=10, fee=5, emission=5, price=-3))
        # total=10, but real=5-3=2 → pct=20%
        self.assertAlmostEqual(r["real_yield_pct"], 20.0)


# ---------------------------------------------------------------------------
# 8. Log / IO tests
# ---------------------------------------------------------------------------
class TestLogging(unittest.TestCase):

    def test_log_result_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            r = analyze("P", _bd())
            log_result(r, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_result_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            r = analyze("P", _bd())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_result_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(3):
                r = analyze(f"P{i}", _bd())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_capped_at_100(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(120):
                r = analyze(f"P{i}", _bd())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_log_keeps_most_recent_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(110):
                r = analyze(f"PROTO_{i}", _bd())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            # Last entry should be PROTO_109
            self.assertEqual(data[-1]["protocol"], "PROTO_109")
            # First entry should be PROTO_10 (110 entries → cap 100 → drop first 10)
            self.assertEqual(data[0]["protocol"], "PROTO_10")

    def test_analyze_and_log_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = analyze_and_log("P", _bd(), log_path=path)
            self.assertIn("protocol", r)

    def test_analyze_and_log_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            analyze_and_log("P", _bd(), log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_handles_corrupt_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            # Write corrupt JSON
            with open(path, "w") as f:
                f.write("not valid json {{{")
            r = analyze("P", _bd())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 9. Config override tests
# ---------------------------------------------------------------------------
class TestConfigOverrides(unittest.TestCase):

    def test_high_real_yield_threshold_forces_mixed(self):
        # With threshold=90%, even 80% real yield → MIXED
        r = analyze("P", _bd(total=10, fee=7, emission=1, price=1),
                    config={"real_yield_threshold": 90.0})
        # real=8/10=80% < 90% → MIXED (if not INFLATIONARY)
        self.assertEqual(r["sustainability"], "MIXED")

    def test_low_real_yield_threshold_forces_sustainable(self):
        # With threshold=10%, very little real yield is enough
        r = analyze("P", _bd(total=10, fee=1, emission=5, price=1),
                    config={"real_yield_threshold": 10.0,
                             "emission_danger_threshold": 80.0})
        # real=2/10=20% ≥ 10%, emission=5/10=50% < 80%
        self.assertEqual(r["sustainability"], "SUSTAINABLE")

    def test_lower_emission_danger_threshold(self):
        r = analyze("P", _bd(total=10, fee=2, emission=6, price=2),
                    config={"emission_danger_threshold": 50.0})
        # emission=60% ≥ 50% → INFLATIONARY
        self.assertEqual(r["sustainability"], "INFLATIONARY")

    def test_extra_config_keys_ignored(self):
        r = analyze("P", _bd(), config={"unknown_key": 999})
        self.assertIn("sustainability", r)

    def test_config_float_types(self):
        r = analyze("P", _bd(), config={"real_yield_threshold": 50, "emission_danger_threshold": 80})
        self.assertIn("sustainability", r)


# ---------------------------------------------------------------------------
# 10. Component consistency tests
# ---------------------------------------------------------------------------
class TestComponentConsistency(unittest.TestCase):

    def test_real_yield_apy_equals_fee_plus_price(self):
        breakdown = _bd(total=10, fee=4, emission=2, price=3)
        r = analyze("P", breakdown)
        self.assertAlmostEqual(r["real_yield_apy"], breakdown["fee_apy"] + breakdown["price_appreciation_apy"])

    def test_breakdown_values_preserved(self):
        breakdown = _bd(total=10, fee=4, emission=3, price=3)
        r = analyze("P", breakdown)
        self.assertAlmostEqual(r["breakdown"]["fee_apy"], 4.0)
        self.assertAlmostEqual(r["breakdown"]["emission_apy"], 3.0)
        self.assertAlmostEqual(r["breakdown"]["price_appreciation_apy"], 3.0)

    def test_emission_pct_in_top_level_equals_breakdown(self):
        r = analyze("P", _bd(total=10, fee=4, emission=3, price=3))
        self.assertAlmostEqual(r["emission_pct"], r["breakdown"]["emission_pct"])

    def test_total_apy_preserved(self):
        r = analyze("P", _bd(total=7.77))
        self.assertAlmostEqual(r["total_apy"], 7.77)

    def test_pct_computed_from_total_not_sum(self):
        # If components don't add up perfectly, pct is based on total_apy
        r = analyze("P", _bd(total=10.0, fee=3.3, emission=3.3, price=3.3))
        self.assertAlmostEqual(r["breakdown"]["fee_pct"], 33.0, places=0)

    def test_negative_total_with_positive_components_still_negative(self):
        r = analyze("P", {"total_apy": -1.0, "fee_apy": 5.0, "emission_apy": 0.0, "price_appreciation_apy": -6.0})
        self.assertEqual(r["sustainability"], "NEGATIVE")


if __name__ == "__main__":
    unittest.main()

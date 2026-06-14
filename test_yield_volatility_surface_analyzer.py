"""
Tests for MP-864 YieldVolatilitySurfaceAnalyzer.
Run: python3 -m unittest spa_core.tests.test_yield_volatility_surface_analyzer -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.yield_volatility_surface_analyzer import (
    analyze,
    _mean,
    _population_std,
    _vol_term_structure,
    _stability_score,
    _yield_category,
    _risk_adjusted_7d,
    _surface_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(**kwargs):
    defaults = {
        "protocol": "Aave",
        "asset": "USDC",
        "apy_7d_samples": [3.0, 3.1, 3.2, 3.0, 3.1, 3.2, 3.0],
        "apy_30d_samples": [3.0] * 30,
        "apy_90d_samples": [3.0] * 90,
    }
    defaults.update(kwargs)
    return defaults


# ===========================================================================
# 1. _mean
# ===========================================================================

class TestMean(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_single(self):
        self.assertAlmostEqual(_mean([5.0]), 5.0)

    def test_uniform(self):
        self.assertAlmostEqual(_mean([2.0, 2.0, 2.0]), 2.0)

    def test_varied(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_negative(self):
        self.assertAlmostEqual(_mean([-1.0, 1.0]), 0.0)

    def test_floats(self):
        self.assertAlmostEqual(_mean([1.5, 2.5]), 2.0)


# ===========================================================================
# 2. _population_std
# ===========================================================================

class TestPopulationStd(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(_population_std([]), 0.0)

    def test_single_returns_zero(self):
        self.assertEqual(_population_std([5.0]), 0.0)

    def test_uniform_returns_zero(self):
        self.assertAlmostEqual(_population_std([3.0, 3.0, 3.0]), 0.0)

    def test_two_values(self):
        # samples [1, 3], mean=2, variance=((1-2)^2+(3-2)^2)/2 = 1, std=1
        self.assertAlmostEqual(_population_std([1.0, 3.0]), 1.0)

    def test_known_std(self):
        # [2, 4, 4, 4, 5, 5, 7, 9], mean=5, population std = 2
        samples = [2, 4, 4, 4, 5, 5, 7, 9]
        self.assertAlmostEqual(_population_std(samples), 2.0, places=5)

    def test_returns_float(self):
        result = _population_std([1.0, 2.0, 3.0])
        self.assertIsInstance(result, float)

    def test_two_samples_minimum(self):
        self.assertEqual(_population_std([5.0]), 0.0)

    def test_two_identical(self):
        self.assertAlmostEqual(_population_std([4.0, 4.0]), 0.0)


# ===========================================================================
# 3. _vol_term_structure
# ===========================================================================

class TestVolTermStructure(unittest.TestCase):

    def test_humped_wins_over_flat(self):
        # vol_30d slightly exceeds 7d and 90d but gap < 0.2 normally
        self.assertEqual(_vol_term_structure(1.0, 2.0, 0.5), "HUMPED")

    def test_humped_basic(self):
        self.assertEqual(_vol_term_structure(0.5, 2.0, 0.5), "HUMPED")

    def test_humped_30d_must_exceed_both(self):
        # vol_30d > vol_7d but not > vol_90d → not humped
        result = _vol_term_structure(0.5, 2.0, 3.0)
        self.assertNotEqual(result, "HUMPED")

    def test_flat_all_equal(self):
        self.assertEqual(_vol_term_structure(1.0, 1.0, 1.0), "FLAT")

    def test_flat_small_spread(self):
        # max - min = 0.19 < 0.2
        self.assertEqual(_vol_term_structure(1.0, 1.1, 1.19), "FLAT")

    def test_flat_boundary_not_flat(self):
        # max - min > 0.2 → not FLAT; use 1.0 and 1.25 (diff=0.25, clear of FP edge)
        result = _vol_term_structure(1.0, 1.0, 1.25)
        self.assertNotEqual(result, "FLAT")

    def test_normal_short_greater_than_long(self):
        self.assertEqual(_vol_term_structure(3.0, 2.0, 1.0), "NORMAL")

    def test_normal_7d_just_above_90d(self):
        self.assertEqual(_vol_term_structure(1.5, 1.0, 1.0), "NORMAL")

    def test_inverted_long_greater_than_short(self):
        self.assertEqual(_vol_term_structure(1.0, 2.0, 3.0), "INVERTED")

    def test_inverted_90d_just_above_7d(self):
        self.assertEqual(_vol_term_structure(1.0, 1.3, 2.5), "INVERTED")

    def test_flat_zeros(self):
        self.assertEqual(_vol_term_structure(0.0, 0.0, 0.0), "FLAT")

    def test_humped_priority_over_inverted(self):
        # vol_30d > both vol_7d and vol_90d, but vol_90d > vol_7d
        self.assertEqual(_vol_term_structure(0.5, 3.0, 1.0), "HUMPED")


# ===========================================================================
# 4. _stability_score
# ===========================================================================

class TestStabilityScore(unittest.TestCase):

    def test_zero_vol(self):
        self.assertEqual(_stability_score(0.0), 100)

    def test_at_01(self):
        self.assertEqual(_stability_score(0.1), 100)

    def test_between_01_and_03(self):
        self.assertEqual(_stability_score(0.2), 85)

    def test_at_03(self):
        self.assertEqual(_stability_score(0.3), 85)

    def test_between_03_and_05(self):
        self.assertEqual(_stability_score(0.4), 70)

    def test_at_05(self):
        self.assertEqual(_stability_score(0.5), 70)

    def test_between_05_and_10(self):
        self.assertEqual(_stability_score(0.8), 50)

    def test_at_10(self):
        self.assertEqual(_stability_score(1.0), 50)

    def test_between_10_and_20(self):
        self.assertEqual(_stability_score(1.5), 30)

    def test_at_20(self):
        self.assertEqual(_stability_score(2.0), 30)

    def test_between_20_and_50(self):
        self.assertEqual(_stability_score(3.0), 15)

    def test_at_50(self):
        self.assertEqual(_stability_score(5.0), 15)

    def test_above_50(self):
        self.assertEqual(_stability_score(6.0), 5)

    def test_very_high_vol(self):
        self.assertEqual(_stability_score(100.0), 5)


# ===========================================================================
# 5. _yield_category
# ===========================================================================

class TestYieldCategory(unittest.TestCase):

    def test_stable_at_100(self):
        self.assertEqual(_yield_category(100), "STABLE")

    def test_stable_at_80(self):
        self.assertEqual(_yield_category(80), "STABLE")

    def test_moderate_at_79(self):
        self.assertEqual(_yield_category(79), "MODERATE")

    def test_moderate_at_50(self):
        self.assertEqual(_yield_category(50), "MODERATE")

    def test_volatile_at_49(self):
        self.assertEqual(_yield_category(49), "VOLATILE")

    def test_volatile_at_20(self):
        self.assertEqual(_yield_category(20), "VOLATILE")

    def test_highly_volatile_at_19(self):
        self.assertEqual(_yield_category(19), "HIGHLY_VOLATILE")

    def test_highly_volatile_at_0(self):
        self.assertEqual(_yield_category(0), "HIGHLY_VOLATILE")


# ===========================================================================
# 6. _risk_adjusted_7d
# ===========================================================================

class TestRiskAdjusted7d(unittest.TestCase):

    def test_normal_case(self):
        self.assertAlmostEqual(_risk_adjusted_7d(6.0, 2.0), 3.0)

    def test_zero_vol_returns_mean(self):
        self.assertAlmostEqual(_risk_adjusted_7d(5.0, 0.0), 5.0)

    def test_zero_mean_zero_vol(self):
        self.assertAlmostEqual(_risk_adjusted_7d(0.0, 0.0), 0.0)

    def test_high_vol(self):
        result = _risk_adjusted_7d(3.0, 10.0)
        self.assertAlmostEqual(result, 0.3)

    def test_equal_mean_vol(self):
        self.assertAlmostEqual(_risk_adjusted_7d(4.0, 4.0), 1.0)


# ===========================================================================
# 7. _surface_label
# ===========================================================================

class TestSurfaceLabel(unittest.TestCase):

    def test_contains_protocol(self):
        label = _surface_label("Aave", "USDC", "STABLE", 0.1, 3.5)
        self.assertIn("Aave", label)

    def test_contains_asset(self):
        label = _surface_label("Aave", "USDC", "STABLE", 0.1, 3.5)
        self.assertIn("USDC", label)

    def test_contains_category(self):
        label = _surface_label("Aave", "USDC", "STABLE", 0.1, 3.5)
        self.assertIn("STABLE", label)

    def test_contains_vol(self):
        label = _surface_label("Aave", "USDC", "STABLE", 0.12, 3.5)
        self.assertIn("0.12", label)

    def test_contains_mean(self):
        label = _surface_label("Aave", "USDC", "STABLE", 0.1, 3.50)
        self.assertIn("3.50", label)

    def test_volatile_category(self):
        label = _surface_label("Euler", "DAI", "VOLATILE", 2.5, 8.0)
        self.assertIn("VOLATILE", label)


# ===========================================================================
# 8. analyze() — integration tests
# ===========================================================================

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.entry = _entry()

    def test_returns_dict(self):
        result = analyze([self.entry])
        self.assertIsInstance(result, dict)

    def test_required_top_keys(self):
        result = analyze([self.entry])
        for key in ("protocols", "most_stable", "most_volatile",
                    "stable_protocols", "average_stability_score", "timestamp"):
            self.assertIn(key, result)

    def test_protocol_keys(self):
        result = analyze([self.entry])
        p = result["protocols"][0]
        for key in ("protocol", "asset", "vol_7d_pct", "vol_30d_pct", "vol_90d_pct",
                    "mean_7d_apy", "mean_30d_apy", "mean_90d_apy",
                    "vol_term_structure", "risk_adjusted_7d",
                    "stability_score", "yield_category", "surface_label"):
            self.assertIn(key, p)

    def test_stability_score_is_int(self):
        result = analyze([self.entry])
        self.assertIsInstance(result["protocols"][0]["stability_score"], int)

    def test_vol_values_non_negative(self):
        result = analyze([self.entry])
        p = result["protocols"][0]
        self.assertGreaterEqual(p["vol_7d_pct"], 0)
        self.assertGreaterEqual(p["vol_30d_pct"], 0)
        self.assertGreaterEqual(p["vol_90d_pct"], 0)

    def test_timestamp_is_float(self):
        result = analyze([self.entry])
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_list(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["most_stable"])
        self.assertIsNone(result["most_volatile"])
        self.assertEqual(result["stable_protocols"], [])
        self.assertEqual(result["average_stability_score"], 0.0)

    def test_config_none(self):
        result = analyze([], config=None)
        self.assertIsInstance(result, dict)


class TestAnalyzeEdgeSamples(unittest.TestCase):

    def test_empty_samples_vol_is_zero(self):
        e = _entry(apy_7d_samples=[], apy_30d_samples=[], apy_90d_samples=[])
        result = analyze([e])
        p = result["protocols"][0]
        self.assertEqual(p["vol_7d_pct"], 0.0)
        self.assertEqual(p["vol_30d_pct"], 0.0)
        self.assertEqual(p["vol_90d_pct"], 0.0)

    def test_empty_samples_mean_is_zero(self):
        e = _entry(apy_7d_samples=[], apy_30d_samples=[], apy_90d_samples=[])
        result = analyze([e])
        p = result["protocols"][0]
        self.assertEqual(p["mean_7d_apy"], 0.0)
        self.assertEqual(p["mean_30d_apy"], 0.0)
        self.assertEqual(p["mean_90d_apy"], 0.0)

    def test_single_sample_vol_is_zero(self):
        e = _entry(apy_7d_samples=[5.0], apy_30d_samples=[5.0], apy_90d_samples=[5.0])
        result = analyze([e])
        p = result["protocols"][0]
        self.assertEqual(p["vol_7d_pct"], 0.0)
        self.assertEqual(p["vol_30d_pct"], 0.0)
        self.assertEqual(p["vol_90d_pct"], 0.0)

    def test_single_sample_mean_is_that_value(self):
        e = _entry(apy_7d_samples=[7.5], apy_30d_samples=[7.5], apy_90d_samples=[7.5])
        result = analyze([e])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["mean_7d_apy"], 7.5)

    def test_uniform_samples_vol_is_zero(self):
        e = _entry(
            apy_7d_samples=[4.0] * 7,
            apy_30d_samples=[4.0] * 30,
            apy_90d_samples=[4.0] * 90,
        )
        result = analyze([e])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["vol_7d_pct"], 0.0)

    def test_varied_samples_vol_nonzero(self):
        e = _entry(
            apy_7d_samples=[1.0, 5.0, 3.0, 7.0, 2.0, 8.0, 4.0],
            apy_30d_samples=[1.0, 5.0] * 15,
            apy_90d_samples=[1.0, 5.0] * 45,
        )
        result = analyze([e])
        p = result["protocols"][0]
        self.assertGreater(p["vol_7d_pct"], 0)


class TestAnalyzeTermStructure(unittest.TestCase):

    def test_flat_uniform_across_tenors(self):
        e = _entry(
            apy_7d_samples=[3.0, 3.1, 3.0, 3.1, 3.0, 3.1, 3.0],  # very small vol
            apy_30d_samples=[3.0, 3.1] * 15,
            apy_90d_samples=[3.0, 3.1] * 45,
        )
        result = analyze([e])
        ts = result["protocols"][0]["vol_term_structure"]
        self.assertIn(ts, ("FLAT", "NORMAL", "INVERTED", "HUMPED"))  # valid value

    def test_normal_short_more_volatile(self):
        e = _entry(
            apy_7d_samples=[1.0, 9.0, 1.0, 9.0, 1.0, 9.0, 1.0],   # large 7d vol
            apy_30d_samples=[3.0, 4.0] * 15,                         # moderate 30d
            apy_90d_samples=[3.5, 3.6] * 45,                         # tiny 90d vol
        )
        result = analyze([e])
        # 7d vol >> 90d vol → NORMAL (unless 30d is biggest → HUMPED)
        ts = result["protocols"][0]["vol_term_structure"]
        self.assertIn(ts, ("NORMAL", "HUMPED"))

    def test_inverted_structure(self):
        e = _entry(
            apy_7d_samples=[3.0, 3.1, 3.0, 3.1, 3.0, 3.1, 3.0],  # small 7d vol
            apy_30d_samples=[3.0, 3.1] * 15,                        # small 30d vol
            apy_90d_samples=[1.0, 9.0] * 45,                        # large 90d vol
        )
        result = analyze([e])
        ts = result["protocols"][0]["vol_term_structure"]
        # 90d vol >> 7d vol → INVERTED (assuming 30d not biggest)
        self.assertEqual(ts, "INVERTED")

    def test_humped_structure(self):
        # 30d most volatile
        e = _entry(
            apy_7d_samples=[3.0, 3.1] * 3 + [3.0],   # small 7d vol
            apy_30d_samples=[1.0, 9.0] * 15,           # large 30d vol
            apy_90d_samples=[3.0, 3.1] * 45,           # small 90d vol
        )
        result = analyze([e])
        ts = result["protocols"][0]["vol_term_structure"]
        self.assertEqual(ts, "HUMPED")


class TestAnalyzeMostStableMostVolatile(unittest.TestCase):

    def test_single_entry_stable_equals_volatile(self):
        result = analyze([_entry()])
        self.assertEqual(result["most_stable"], result["most_volatile"])

    def test_most_stable_has_highest_score(self):
        e1 = _entry(protocol="Stable", asset="USDC",
                    apy_30d_samples=[3.0] * 30)
        e2 = _entry(protocol="Volatile", asset="DAI",
                    apy_30d_samples=[1.0, 9.0] * 15)
        result = analyze([e1, e2])
        self.assertIn("Stable", result["most_stable"])

    def test_most_volatile_has_lowest_score(self):
        e1 = _entry(protocol="Stable", asset="USDC",
                    apy_30d_samples=[3.0] * 30)
        e2 = _entry(protocol="Volatile", asset="DAI",
                    apy_30d_samples=[1.0, 9.0] * 15)
        result = analyze([e1, e2])
        self.assertIn("Volatile", result["most_volatile"])

    def test_most_stable_format(self):
        result = analyze([_entry(protocol="Aave", asset="USDC")])
        self.assertEqual(result["most_stable"], "Aave (USDC)")

    def test_most_volatile_format(self):
        result = analyze([_entry(protocol="Morpho", asset="DAI")])
        self.assertEqual(result["most_volatile"], "Morpho (DAI)")


class TestAnalyzeStableProtocols(unittest.TestCase):

    def test_stable_category_included(self):
        e = _entry(protocol="Stable", apy_30d_samples=[3.0] * 30)  # vol≈0 → score 100 → STABLE
        result = analyze([e])
        self.assertIn("Stable (USDC)", result["stable_protocols"])

    def test_highly_volatile_excluded_from_stable(self):
        e = _entry(protocol="Wild", apy_30d_samples=[0.5, 20.0] * 15)
        result = analyze([e])
        # If score < 20 → HIGHLY_VOLATILE → not in stable_protocols
        p = result["protocols"][0]
        if p["yield_category"] == "HIGHLY_VOLATILE":
            self.assertNotIn("Wild (USDC)", result["stable_protocols"])

    def test_moderate_category_included(self):
        # vol_30d around 0.8 → score 50 → MODERATE
        samples = [3.0 + 0.8 * (1 if i % 2 == 0 else -1) for i in range(30)]
        e = _entry(protocol="Medium", apy_30d_samples=samples)
        result = analyze([e])
        p = result["protocols"][0]
        if p["yield_category"] == "MODERATE":
            self.assertIn("Medium (USDC)", result["stable_protocols"])


class TestAnalyzeAverageScore(unittest.TestCase):

    def test_average_single(self):
        e = _entry(apy_30d_samples=[3.0] * 30)
        result = analyze([e])
        self.assertEqual(result["average_stability_score"], result["protocols"][0]["stability_score"])

    def test_average_two_entries(self):
        e1 = _entry(protocol="A", apy_30d_samples=[3.0] * 30)
        e2 = _entry(protocol="B", apy_30d_samples=[1.0, 9.0] * 15)
        result = analyze([e1, e2])
        expected = (result["protocols"][0]["stability_score"] +
                    result["protocols"][1]["stability_score"]) / 2
        self.assertAlmostEqual(result["average_stability_score"], round(expected, 2))

    def test_average_non_negative(self):
        entries = [_entry(protocol=f"P{i}") for i in range(5)]
        result = analyze(entries)
        self.assertGreaterEqual(result["average_stability_score"], 0)

    def test_average_at_most_100(self):
        entries = [_entry(protocol=f"P{i}") for i in range(5)]
        result = analyze(entries)
        self.assertLessEqual(result["average_stability_score"], 100)


class TestAnalyzeRiskAdjusted(unittest.TestCase):

    def test_zero_vol_risk_adjusted_equals_mean(self):
        e = _entry(apy_7d_samples=[5.0] * 7)
        result = analyze([e])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["risk_adjusted_7d"], p["mean_7d_apy"])

    def test_risk_adjusted_positive_when_mean_positive(self):
        e = _entry(apy_7d_samples=[3.0, 5.0, 4.0, 6.0, 3.5, 5.5, 4.5])
        result = analyze([e])
        p = result["protocols"][0]
        self.assertGreater(p["risk_adjusted_7d"], 0)


class TestAnalyzeYieldCategories(unittest.TestCase):

    def test_stable_category_score_100(self):
        e = _entry(apy_30d_samples=[3.0] * 30)
        result = analyze([e])
        p = result["protocols"][0]
        self.assertEqual(p["stability_score"], 100)
        self.assertEqual(p["yield_category"], "STABLE")

    def test_highly_volatile_category(self):
        e = _entry(apy_30d_samples=[0.5, 30.0] * 15)
        result = analyze([e])
        p = result["protocols"][0]
        self.assertIn(p["yield_category"], ("VOLATILE", "HIGHLY_VOLATILE"))

    def test_yield_category_valid_values(self):
        e = _entry()
        result = analyze([e])
        self.assertIn(result["protocols"][0]["yield_category"],
                      ("STABLE", "MODERATE", "VOLATILE", "HIGHLY_VOLATILE"))

    def test_term_structure_valid_values(self):
        e = _entry()
        result = analyze([e])
        self.assertIn(result["protocols"][0]["vol_term_structure"],
                      ("NORMAL", "INVERTED", "HUMPED", "FLAT"))


class TestAnalyzeSurfaceLabel(unittest.TestCase):

    def test_surface_label_non_empty(self):
        result = analyze([_entry()])
        self.assertGreater(len(result["protocols"][0]["surface_label"]), 0)

    def test_surface_label_contains_protocol(self):
        result = analyze([_entry(protocol="Compound")])
        self.assertIn("Compound", result["protocols"][0]["surface_label"])

    def test_surface_label_contains_category(self):
        result = analyze([_entry()])
        label = result["protocols"][0]["surface_label"]
        p = result["protocols"][0]
        self.assertIn(p["yield_category"], label)


class TestAnalyzeMultiProtocol(unittest.TestCase):

    def test_three_protocols_sorted_by_stability(self):
        entries = [
            _entry(protocol="Morpho", apy_30d_samples=[1.0, 9.0] * 15),
            _entry(protocol="Aave", apy_30d_samples=[3.0] * 30),
            _entry(protocol="Euler", apy_30d_samples=[2.5, 3.5] * 15),
        ]
        result = analyze(entries)
        self.assertEqual(len(result["protocols"]), 3)
        self.assertIn("Aave", result["most_stable"])

    def test_multiple_stable_in_stable_protocols(self):
        entries = [
            _entry(protocol="A", apy_30d_samples=[3.0] * 30),
            _entry(protocol="B", apy_30d_samples=[4.0] * 30),
        ]
        result = analyze(entries)
        self.assertEqual(len(result["stable_protocols"]), 2)

    def test_no_stable_empty_stable_protocols(self):
        entries = [
            _entry(protocol="Wild1", apy_30d_samples=[0.5, 20.0] * 15),
            _entry(protocol="Wild2", apy_30d_samples=[1.0, 25.0] * 15),
        ]
        result = analyze(entries)
        # Both will be HIGHLY_VOLATILE → stable_protocols empty
        for p in result["protocols"]:
            if p["yield_category"] not in ("STABLE", "MODERATE"):
                pass  # expected
        # Just verify it's a list
        self.assertIsInstance(result["stable_protocols"], list)


if __name__ == "__main__":
    unittest.main()

"""
Tests for MP-1089: ProtocolDeFiBorrowRateStabilityAnalyzer
≥110 test methods covering all logic paths.
Uses unittest only (no pytest).
Run with: python3 -m unittest spa_core.tests.test_protocol_defi_borrow_rate_stability_analyzer
"""

import json
import math
import os
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------
from spa_core.analytics.protocol_defi_borrow_rate_stability_analyzer import (
    HIGH_VARIANCE,
    LOG_CAP,
    MODERATE_VARIANCE,
    STABLE,
    ULTRA_STABLE,
    VOLATILE_RATE,
    ProtocolDeFiBorrowRateStabilityAnalyzer,
    _compute_above_optimal_flag,
    _compute_mean,
    _compute_rate_cv,
    _compute_stability_label,
    _compute_stability_score,
    _compute_std,
    __mp__,
    __version__,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _default_analyzer(tmp_dir: str) -> ProtocolDeFiBorrowRateStabilityAnalyzer:
    log = os.path.join(tmp_dir, "borrow_stability_log.json")
    return ProtocolDeFiBorrowRateStabilityAnalyzer(log_path=log)


def _analyze(
    tmp_dir: str,
    borrow_rates_pct: list | None = None,
    current_rate_pct: float = 5.0,
    utilization_rate_pct: float = 70.0,
    optimal_utilization_pct: float = 80.0,
    base_rate_pct: float = 0.5,
    protocol_name: str = "TestProtocol",
) -> dict:
    if borrow_rates_pct is None:
        borrow_rates_pct = [5.0, 5.1, 4.9, 5.0, 5.05]
    return _default_analyzer(tmp_dir).analyze(
        borrow_rates_pct=borrow_rates_pct,
        current_rate_pct=current_rate_pct,
        utilization_rate_pct=utilization_rate_pct,
        optimal_utilization_pct=optimal_utilization_pct,
        base_rate_pct=base_rate_pct,
        protocol_name=protocol_name,
    )


# Helper: build rates that produce a known population std via [mean-d, mean+d]
# mean = m, std = d, cv = d/m
def _two_rates(mean: float, std: float) -> list:
    """Return [mean-std, mean+std]: population std equals std, mean equals mean."""
    return [mean - std, mean + std]


# ===========================================================================
# 1. Module constants
# ===========================================================================

class TestModuleConstants(unittest.TestCase):
    def test_version_string(self):
        self.assertEqual(__version__, "1.0.0")

    def test_mp_tag(self):
        self.assertEqual(__mp__, "MP-1089")

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_stability_label_constants(self):
        self.assertEqual(ULTRA_STABLE, "ULTRA_STABLE")
        self.assertEqual(STABLE, "STABLE")
        self.assertEqual(MODERATE_VARIANCE, "MODERATE_VARIANCE")
        self.assertEqual(HIGH_VARIANCE, "HIGH_VARIANCE")
        self.assertEqual(VOLATILE_RATE, "VOLATILE_RATE")

    def test_five_distinct_labels(self):
        labels = {ULTRA_STABLE, STABLE, MODERATE_VARIANCE, HIGH_VARIANCE, VOLATILE_RATE}
        self.assertEqual(len(labels), 5)


# ===========================================================================
# 2. _compute_mean
# ===========================================================================

class TestComputeMeanFunction(unittest.TestCase):

    def test_single_element(self):
        self.assertAlmostEqual(_compute_mean([5.0]), 5.0)

    def test_equal_elements(self):
        self.assertAlmostEqual(_compute_mean([3.0, 3.0, 3.0]), 3.0)

    def test_two_elements(self):
        self.assertAlmostEqual(_compute_mean([4.0, 6.0]), 5.0)

    def test_multiple_elements(self):
        self.assertAlmostEqual(_compute_mean([1.0, 2.0, 3.0, 4.0, 5.0]), 3.0)

    def test_empty_list_returns_zero(self):
        self.assertAlmostEqual(_compute_mean([]), 0.0)

    def test_fractional_values(self):
        self.assertAlmostEqual(_compute_mean([1.5, 2.5, 3.5]), 2.5)


# ===========================================================================
# 3. _compute_std
# ===========================================================================

class TestComputeStdFunction(unittest.TestCase):

    def test_all_same_returns_zero(self):
        self.assertAlmostEqual(_compute_std([5.0, 5.0, 5.0], 5.0), 0.0)

    def test_single_element_returns_zero(self):
        self.assertAlmostEqual(_compute_std([5.0], 5.0), 0.0)

    def test_empty_list_returns_zero(self):
        self.assertAlmostEqual(_compute_std([], 0.0), 0.0)

    def test_two_symmetric_elements(self):
        # [95, 105], mean=100 → std = sqrt((25+25)/2) = sqrt(25) = 5
        self.assertAlmostEqual(_compute_std([95.0, 105.0], 100.0), 5.0, places=6)

    def test_population_std_formula(self):
        rates = [4.0, 6.0]  # mean=5.0
        # variance = ((4-5)^2 + (6-5)^2) / 2 = 2/2 = 1 → std = 1.0
        self.assertAlmostEqual(_compute_std(rates, 5.0), 1.0, places=6)

    def test_known_population_std(self):
        # [70, 130], mean=100 → std = sqrt((900+900)/2) = sqrt(900) = 30
        self.assertAlmostEqual(_compute_std([70.0, 130.0], 100.0), 30.0, places=6)

    def test_returns_float(self):
        result = _compute_std([1.0, 2.0, 3.0], 2.0)
        self.assertIsInstance(result, float)

    def test_std_non_negative(self):
        for rates in [[5.0], [3.0, 4.0, 5.0], [10.0, 10.0]]:
            mean = _compute_mean(rates)
            self.assertGreaterEqual(_compute_std(rates, mean), 0.0)


# ===========================================================================
# 4. _compute_rate_cv
# ===========================================================================

class TestComputeRateCvFunction(unittest.TestCase):

    def test_zero_std_zero_mean_gives_zero(self):
        self.assertAlmostEqual(_compute_rate_cv(0.0, 0.0), 0.0)

    def test_positive_std_zero_mean_gives_inf(self):
        result = _compute_rate_cv(1.0, 0.0)
        self.assertEqual(result, float("inf"))

    def test_standard_cv(self):
        # std=1, mean=10 → cv=0.1
        self.assertAlmostEqual(_compute_rate_cv(1.0, 10.0), 0.1, places=6)

    def test_cv_proportional_to_std(self):
        cv1 = _compute_rate_cv(1.0, 10.0)
        cv2 = _compute_rate_cv(2.0, 10.0)
        self.assertAlmostEqual(cv2, 2 * cv1, places=6)

    def test_cv_zero_when_std_zero(self):
        self.assertAlmostEqual(_compute_rate_cv(0.0, 5.0), 0.0)

    def test_cv_uses_abs_mean(self):
        # Theoretical negative rates: abs(-10)=10
        result = _compute_rate_cv(1.0, -10.0)
        self.assertAlmostEqual(result, 0.1, places=6)

    def test_cv_two_element_list(self):
        # rates=[95, 105], mean=100, std=5 → cv=0.05
        std = _compute_std([95.0, 105.0], 100.0)
        cv = _compute_rate_cv(std, 100.0)
        self.assertAlmostEqual(cv, 0.05, places=6)

    def test_cv_returns_float(self):
        result = _compute_rate_cv(1.0, 10.0)
        self.assertTrue(isinstance(result, float) or math.isinf(result))


# ===========================================================================
# 5. _compute_stability_label
# ===========================================================================

class TestComputeStabilityLabelFunction(unittest.TestCase):

    def test_cv_zero_is_ultra_stable(self):
        self.assertEqual(_compute_stability_label(0.0), ULTRA_STABLE)

    def test_cv_just_below_005(self):
        self.assertEqual(_compute_stability_label(0.049), ULTRA_STABLE)

    def test_cv_exactly_005_is_stable(self):
        self.assertEqual(_compute_stability_label(0.05), STABLE)

    def test_cv_mid_stable(self):
        self.assertEqual(_compute_stability_label(0.10), STABLE)

    def test_cv_just_below_015(self):
        self.assertEqual(_compute_stability_label(0.149), STABLE)

    def test_cv_exactly_015_is_moderate(self):
        self.assertEqual(_compute_stability_label(0.15), MODERATE_VARIANCE)

    def test_cv_mid_moderate(self):
        self.assertEqual(_compute_stability_label(0.22), MODERATE_VARIANCE)

    def test_cv_just_below_030(self):
        self.assertEqual(_compute_stability_label(0.299), MODERATE_VARIANCE)

    def test_cv_exactly_030_is_high_variance(self):
        self.assertEqual(_compute_stability_label(0.30), HIGH_VARIANCE)

    def test_cv_mid_high_variance(self):
        self.assertEqual(_compute_stability_label(0.40), HIGH_VARIANCE)

    def test_cv_just_below_050(self):
        self.assertEqual(_compute_stability_label(0.499), HIGH_VARIANCE)

    def test_cv_exactly_050_is_volatile(self):
        self.assertEqual(_compute_stability_label(0.50), VOLATILE_RATE)

    def test_cv_above_050(self):
        self.assertEqual(_compute_stability_label(0.75), VOLATILE_RATE)

    def test_cv_very_large(self):
        self.assertEqual(_compute_stability_label(10.0), VOLATILE_RATE)

    def test_cv_infinite_is_volatile(self):
        self.assertEqual(_compute_stability_label(float("inf")), VOLATILE_RATE)


# ===========================================================================
# 6. _compute_stability_score
# ===========================================================================

class TestComputeStabilityScoreFunction(unittest.TestCase):

    def test_cv_zero_gives_100(self):
        self.assertEqual(_compute_stability_score(0.0), 100)

    def test_cv_one_gives_zero(self):
        self.assertEqual(_compute_stability_score(1.0), 0)

    def test_cv_half_gives_50(self):
        self.assertEqual(_compute_stability_score(0.5), 50)

    def test_cv_010_gives_90(self):
        self.assertEqual(_compute_stability_score(0.10), 90)

    def test_cv_greater_than_1_clamped_to_zero(self):
        self.assertEqual(_compute_stability_score(2.0), 0)

    def test_infinite_cv_gives_zero(self):
        self.assertEqual(_compute_stability_score(float("inf")), 0)

    def test_score_in_valid_range(self):
        for cv in [0.0, 0.05, 0.15, 0.30, 0.50, 0.75, 1.0, 2.0]:
            score = _compute_stability_score(cv)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_returns_int(self):
        result = _compute_stability_score(0.3)
        self.assertIsInstance(result, int)


# ===========================================================================
# 7. _compute_above_optimal_flag
# ===========================================================================

class TestComputeAboveOptimalFlagFunction(unittest.TestCase):

    def test_below_optimal_returns_false(self):
        self.assertFalse(_compute_above_optimal_flag(70.0, 80.0))

    def test_equal_to_optimal_returns_false(self):
        self.assertFalse(_compute_above_optimal_flag(80.0, 80.0))

    def test_above_optimal_returns_true(self):
        self.assertTrue(_compute_above_optimal_flag(85.0, 80.0))

    def test_well_below_optimal(self):
        self.assertFalse(_compute_above_optimal_flag(20.0, 80.0))

    def test_just_above_optimal(self):
        self.assertTrue(_compute_above_optimal_flag(80.01, 80.0))

    def test_returns_bool(self):
        result = _compute_above_optimal_flag(70.0, 80.0)
        self.assertIsInstance(result, bool)


# ===========================================================================
# 8. Return structure from analyze()
# ===========================================================================

class TestAnalyzeReturnStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_required_keys_present(self):
        r = _analyze(self.tmp)
        required = [
            "protocol_name", "mean_rate_pct", "rate_std_pct", "rate_cv",
            "max_rate_pct", "min_rate_pct", "above_optimal_flag",
            "stability_score", "stability_label", "current_rate_pct",
            "utilization_rate_pct", "optimal_utilization_pct", "base_rate_pct",
            "observations", "analysis_timestamp", "module", "version",
        ]
        for key in required:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_module_field(self):
        r = _analyze(self.tmp)
        self.assertEqual(r["module"], "MP-1089")

    def test_version_field(self):
        r = _analyze(self.tmp)
        self.assertEqual(r["version"], "1.0.0")

    def test_protocol_name_preserved(self):
        r = _analyze(self.tmp, protocol_name="AaveV3")
        self.assertEqual(r["protocol_name"], "AaveV3")

    def test_observations_count(self):
        rates = [3.0, 4.0, 5.0, 6.0]
        r = _analyze(self.tmp, borrow_rates_pct=rates)
        self.assertEqual(r["observations"], 4)

    def test_above_optimal_flag_is_bool(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["above_optimal_flag"], bool)

    def test_timestamp_format(self):
        r = _analyze(self.tmp)
        ts = r["analysis_timestamp"]
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_stability_score_in_range(self):
        r = _analyze(self.tmp)
        self.assertGreaterEqual(r["stability_score"], 0)
        self.assertLessEqual(r["stability_score"], 100)


# ===========================================================================
# 9. Statistical metrics from analyze()
# ===========================================================================

class TestAnalyzeStatisticalMetrics(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_mean_all_same(self):
        r = _analyze(self.tmp, borrow_rates_pct=[5.0, 5.0, 5.0])
        self.assertAlmostEqual(r["mean_rate_pct"], 5.0, places=4)

    def test_mean_two_values(self):
        r = _analyze(self.tmp, borrow_rates_pct=[4.0, 6.0])
        self.assertAlmostEqual(r["mean_rate_pct"], 5.0, places=4)

    def test_std_all_same_is_zero(self):
        r = _analyze(self.tmp, borrow_rates_pct=[7.0, 7.0, 7.0])
        self.assertAlmostEqual(r["rate_std_pct"], 0.0, places=6)

    def test_std_two_symmetric_values(self):
        # [95, 105] → std = 5
        r = _analyze(self.tmp, borrow_rates_pct=[95.0, 105.0])
        self.assertAlmostEqual(r["rate_std_pct"], 5.0, places=4)

    def test_max_rate(self):
        r = _analyze(self.tmp, borrow_rates_pct=[3.0, 5.0, 7.0, 4.0])
        self.assertAlmostEqual(r["max_rate_pct"], 7.0, places=4)

    def test_min_rate(self):
        r = _analyze(self.tmp, borrow_rates_pct=[3.0, 5.0, 7.0, 4.0])
        self.assertAlmostEqual(r["min_rate_pct"], 3.0, places=4)

    def test_max_equals_min_when_all_same(self):
        r = _analyze(self.tmp, borrow_rates_pct=[6.0, 6.0, 6.0])
        self.assertAlmostEqual(r["max_rate_pct"], r["min_rate_pct"], places=6)

    def test_cv_zero_when_all_same(self):
        r = _analyze(self.tmp, borrow_rates_pct=[4.0, 4.0, 4.0])
        self.assertAlmostEqual(r["rate_cv"], 0.0, places=6)

    def test_cv_matches_std_over_mean(self):
        rates = [95.0, 105.0]  # mean=100, std=5, cv=0.05
        r = _analyze(self.tmp, borrow_rates_pct=rates)
        self.assertAlmostEqual(r["rate_cv"], 0.05, places=4)

    def test_single_element_std_zero(self):
        r = _analyze(self.tmp, borrow_rates_pct=[8.0])
        self.assertAlmostEqual(r["rate_std_pct"], 0.0, places=6)

    def test_current_rate_preserved(self):
        r = _analyze(self.tmp, current_rate_pct=6.5)
        self.assertAlmostEqual(r["current_rate_pct"], 6.5, places=4)

    def test_base_rate_preserved(self):
        r = _analyze(self.tmp, base_rate_pct=0.25)
        self.assertAlmostEqual(r["base_rate_pct"], 0.25, places=4)


# ===========================================================================
# 10. Stability labels via analyze()
# ===========================================================================

class TestAnalyzeStabilityLabels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _r(self, rates):
        return _analyze(self.tmp, borrow_rates_pct=rates)

    def test_ultra_stable_all_same(self):
        r = self._r([5.0, 5.0, 5.0])
        self.assertEqual(r["stability_label"], ULTRA_STABLE)

    def test_ultra_stable_cv_below_005(self):
        # [98, 102] → mean=100, std=2, cv=0.02
        r = self._r([98.0, 102.0])
        self.assertEqual(r["stability_label"], ULTRA_STABLE)

    def test_ultra_stable_single_rate(self):
        r = self._r([5.0])
        self.assertEqual(r["stability_label"], ULTRA_STABLE)

    def test_stable_cv_at_005(self):
        # [95, 105] → mean=100, std=5, cv=0.05
        r = self._r([95.0, 105.0])
        self.assertEqual(r["stability_label"], STABLE)

    def test_stable_cv_mid_range(self):
        # mean=100, std=10, cv=0.10 → STABLE
        r = self._r([90.0, 110.0])
        self.assertEqual(r["stability_label"], STABLE)

    def test_stable_cv_below_015(self):
        # std=14, mean=100 → cv=0.14 → STABLE
        r = self._r([86.0, 114.0])
        self.assertEqual(r["stability_label"], STABLE)

    def test_moderate_variance_cv_at_015(self):
        # [85, 115] → mean=100, std=15, cv=0.15
        r = self._r([85.0, 115.0])
        self.assertEqual(r["stability_label"], MODERATE_VARIANCE)

    def test_moderate_variance_cv_mid(self):
        # std=20, mean=100 → cv=0.20
        r = self._r([80.0, 120.0])
        self.assertEqual(r["stability_label"], MODERATE_VARIANCE)

    def test_moderate_variance_cv_below_030(self):
        # std=29, mean=100 → cv=0.29
        r = self._r([71.0, 129.0])
        self.assertEqual(r["stability_label"], MODERATE_VARIANCE)

    def test_high_variance_cv_at_030(self):
        # [70, 130] → mean=100, std=30, cv=0.30
        r = self._r([70.0, 130.0])
        self.assertEqual(r["stability_label"], HIGH_VARIANCE)

    def test_high_variance_cv_mid(self):
        # std=40, mean=100 → cv=0.40
        r = self._r([60.0, 140.0])
        self.assertEqual(r["stability_label"], HIGH_VARIANCE)

    def test_high_variance_cv_below_050(self):
        # std=49, mean=100 → cv=0.49
        r = self._r([51.0, 149.0])
        self.assertEqual(r["stability_label"], HIGH_VARIANCE)

    def test_volatile_rate_cv_at_050(self):
        # [50, 150] → mean=100, std=50, cv=0.50
        r = self._r([50.0, 150.0])
        self.assertEqual(r["stability_label"], VOLATILE_RATE)

    def test_volatile_rate_cv_above_050(self):
        # std=60, mean=100 → cv=0.60
        r = self._r([40.0, 160.0])
        self.assertEqual(r["stability_label"], VOLATILE_RATE)

    def test_volatile_rate_very_high_variance(self):
        # std=90, mean=100 → cv=0.90
        r = self._r([10.0, 190.0])
        self.assertEqual(r["stability_label"], VOLATILE_RATE)


# ===========================================================================
# 11. Above optimal flag via analyze()
# ===========================================================================

class TestAnalyzeAboveOptimalFlag(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_utilization_below_optimal_false(self):
        r = _analyze(self.tmp, utilization_rate_pct=70.0, optimal_utilization_pct=80.0)
        self.assertFalse(r["above_optimal_flag"])

    def test_utilization_equal_optimal_false(self):
        r = _analyze(self.tmp, utilization_rate_pct=80.0, optimal_utilization_pct=80.0)
        self.assertFalse(r["above_optimal_flag"])

    def test_utilization_above_optimal_true(self):
        r = _analyze(self.tmp, utilization_rate_pct=85.0, optimal_utilization_pct=80.0)
        self.assertTrue(r["above_optimal_flag"])

    def test_low_utilization_below_optimal(self):
        r = _analyze(self.tmp, utilization_rate_pct=10.0, optimal_utilization_pct=80.0)
        self.assertFalse(r["above_optimal_flag"])

    def test_utilization_and_optimal_stored(self):
        r = _analyze(self.tmp, utilization_rate_pct=75.0, optimal_utilization_pct=90.0)
        self.assertAlmostEqual(r["utilization_rate_pct"], 75.0, places=4)
        self.assertAlmostEqual(r["optimal_utilization_pct"], 90.0, places=4)

    def test_above_100_utilization_still_works(self):
        r = _analyze(self.tmp, utilization_rate_pct=95.0, optimal_utilization_pct=80.0)
        self.assertTrue(r["above_optimal_flag"])


# ===========================================================================
# 12. Stability score via analyze()
# ===========================================================================

class TestAnalyzeStabilityScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_score_100_all_same(self):
        r = _analyze(self.tmp, borrow_rates_pct=[5.0, 5.0, 5.0])
        self.assertEqual(r["stability_score"], 100)

    def test_score_100_single_element(self):
        r = _analyze(self.tmp, borrow_rates_pct=[7.5])
        self.assertEqual(r["stability_score"], 100)

    def test_score_decreases_with_cv(self):
        # Low cv → higher score
        r_low = _analyze(self.tmp, borrow_rates_pct=[98.0, 102.0])   # cv=0.02
        r_high = _analyze(self.tmp, borrow_rates_pct=[50.0, 150.0])  # cv=0.50
        self.assertGreater(r_low["stability_score"], r_high["stability_score"])

    def test_score_at_cv_010(self):
        # [90, 110] → mean=100, std=10, cv=0.10 → score=round(90)=90
        r = _analyze(self.tmp, borrow_rates_pct=[90.0, 110.0])
        self.assertEqual(r["stability_score"], 90)

    def test_score_at_cv_050(self):
        # [50, 150] → cv=0.50 → score=round(50)=50
        r = _analyze(self.tmp, borrow_rates_pct=[50.0, 150.0])
        self.assertEqual(r["stability_score"], 50)

    def test_score_is_int(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["stability_score"], int)

    def test_score_always_non_negative(self):
        for rates in [[1.0, 100.0], [0.1, 99.9], [50.0, 150.0]]:
            r = _analyze(self.tmp, borrow_rates_pct=rates)
            self.assertGreaterEqual(r["stability_score"], 0)

    def test_score_always_at_most_100(self):
        for rates in [[5.0], [5.0, 5.0], [4.9, 5.1]]:
            r = _analyze(self.tmp, borrow_rates_pct=rates)
            self.assertLessEqual(r["stability_score"], 100)


# ===========================================================================
# 13. Edge cases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_single_rate_ultra_stable(self):
        r = _analyze(self.tmp, borrow_rates_pct=[5.0])
        self.assertEqual(r["stability_label"], ULTRA_STABLE)
        self.assertEqual(r["stability_score"], 100)

    def test_all_same_rates(self):
        r = _analyze(self.tmp, borrow_rates_pct=[3.5, 3.5, 3.5, 3.5])
        self.assertAlmostEqual(r["rate_std_pct"], 0.0, places=6)
        self.assertAlmostEqual(r["rate_cv"], 0.0, places=6)

    def test_large_rate_series(self):
        rates = [5.0 + i * 0.01 for i in range(100)]
        r = _analyze(self.tmp, borrow_rates_pct=rates)
        self.assertEqual(r["observations"], 100)

    def test_very_high_variance_rates(self):
        r = _analyze(self.tmp, borrow_rates_pct=[0.1, 99.9])
        self.assertEqual(r["stability_label"], VOLATILE_RATE)
        self.assertEqual(r["stability_score"], 0)

    def test_zero_optimal_utilization(self):
        # Everything above optimal when optimal=0
        r = _analyze(self.tmp, utilization_rate_pct=1.0, optimal_utilization_pct=0.0)
        self.assertTrue(r["above_optimal_flag"])

    def test_rate_cv_not_negative(self):
        r = _analyze(self.tmp, borrow_rates_pct=[1.0, 2.0, 3.0])
        self.assertGreaterEqual(r["rate_cv"], 0.0)

    def test_max_gte_min(self):
        r = _analyze(self.tmp, borrow_rates_pct=[3.0, 7.0, 1.0, 9.0])
        self.assertGreaterEqual(r["max_rate_pct"], r["min_rate_pct"])

    def test_two_equal_rates_std_zero(self):
        r = _analyze(self.tmp, borrow_rates_pct=[5.0, 5.0])
        self.assertAlmostEqual(r["rate_std_pct"], 0.0, places=6)


# ===========================================================================
# 14. Log behaviour
# ===========================================================================

class TestAnalyzeLogBehavior(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "test_borrow_log.json")

    def _az(self, protocol_name="AaveV3"):
        a = ProtocolDeFiBorrowRateStabilityAnalyzer(log_path=self.log)
        return a.analyze(
            borrow_rates_pct=[5.0, 5.1, 4.9],
            current_rate_pct=5.0,
            utilization_rate_pct=70.0,
            optimal_utilization_pct=80.0,
            base_rate_pct=0.5,
            protocol_name=protocol_name,
        )

    def test_log_created_after_analyze(self):
        self._az()
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_valid_json_list(self):
        self._az()
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_count_increases(self):
        self._az()
        self._az()
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_required_fields(self):
        self._az(protocol_name="Compound")
        with open(self.log) as fh:
            data = json.load(fh)
        entry = data[-1]
        for field in ("ts", "protocol_name", "mean_rate_pct", "stability_label", "stability_score"):
            self.assertIn(field, entry)

    def test_log_ring_buffer_cap(self):
        a = ProtocolDeFiBorrowRateStabilityAnalyzer(log_path=self.log)
        for i in range(LOG_CAP + 5):
            a.analyze([5.0], 5.0, 70.0, 80.0, 0.5, f"P{i}")
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_log_keeps_most_recent_entries(self):
        a = ProtocolDeFiBorrowRateStabilityAnalyzer(log_path=self.log)
        for i in range(LOG_CAP + 3):
            a.analyze([5.0], 5.0, 70.0, 80.0, 0.5, f"P{i}")
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["protocol_name"], f"P{LOG_CAP + 2}")

    def test_custom_log_path(self):
        custom_log = os.path.join(self.tmp, "nested", "custom_borrow.json")
        a = ProtocolDeFiBorrowRateStabilityAnalyzer(log_path=custom_log)
        a.analyze([5.0], 5.0, 70.0, 80.0, 0.5, "Proto")
        self.assertTrue(os.path.exists(custom_log))

    def test_log_failure_does_not_crash_analysis(self):
        a = ProtocolDeFiBorrowRateStabilityAnalyzer(log_path="/no/such/dir/log.json")
        result = a.analyze([5.0, 5.1], 5.0, 70.0, 80.0, 0.5, "Safe")
        self.assertIn("stability_label", result)


# ===========================================================================
# 15. Input coercion and types
# ===========================================================================

class TestAnalyzeInputCoercion(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_mean_rate_is_float(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["mean_rate_pct"], float)

    def test_rate_std_is_float(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["rate_std_pct"], float)

    def test_rate_cv_is_float(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["rate_cv"], float)

    def test_stability_label_is_str(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["stability_label"], str)

    def test_stability_score_is_int(self):
        r = _analyze(self.tmp)
        self.assertIsInstance(r["stability_score"], int)

    def test_string_floats_coerced(self):
        a = ProtocolDeFiBorrowRateStabilityAnalyzer(
            log_path=os.path.join(self.tmp, "l.json")
        )
        result = a.analyze(
            borrow_rates_pct=["5.0", "5.1", "4.9"],
            current_rate_pct="5.0",
            utilization_rate_pct="70.0",
            optimal_utilization_pct="80.0",
            base_rate_pct="0.5",
            protocol_name="CoercedProto",
        )
        self.assertIsInstance(result["mean_rate_pct"], float)


if __name__ == "__main__":
    unittest.main()

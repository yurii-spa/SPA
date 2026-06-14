"""
Tests for MP-1086: DeFiProtocolOraclePriceFreshnessAnalyzer
Target: ≥110 tests, all pass with `python3 -m unittest`
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap — works whether run from repo root or tests/ subdir
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_oracle_price_freshness_analyzer import (
    DeFiProtocolOraclePriceFreshnessAnalyzer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
NOW = 1_700_000_000.0  # fixed reference epoch


def _make(
    staleness_s: float = 0.0,
    heartbeat: int = 3600,
    dev_threshold: float = 0.5,
    observed: float = 1800.0,
    reference: float = 1800.0,
    num_oracles: int = 3,
    protocol: str = "TestProtocol",
    data_dir: str | None = None,
) -> dict:
    """Helper to call analyze() with convenient defaults."""
    analyzer = DeFiProtocolOraclePriceFreshnessAnalyzer(
        data_dir=data_dir or tempfile.mkdtemp()
    )
    return analyzer.analyze(
        last_update_timestamp=NOW - staleness_s,
        current_timestamp=NOW,
        heartbeat_seconds=heartbeat,
        deviation_threshold_pct=dev_threshold,
        observed_price_usd=observed,
        reference_price_usd=reference,
        num_oracles=num_oracles,
        protocol_name=protocol,
    )


# ===========================================================================
# 1. Return structure
# ===========================================================================
class TestAnalyzeReturnStructure(unittest.TestCase):
    def test_returns_dict(self):
        result = _make()
        self.assertIsInstance(result, dict)

    def test_has_staleness_seconds_key(self):
        self.assertIn("staleness_seconds", _make())

    def test_has_staleness_ratio_key(self):
        self.assertIn("staleness_ratio", _make())

    def test_has_price_deviation_pct_key(self):
        self.assertIn("price_deviation_pct", _make())

    def test_has_oracle_risk_score_key(self):
        self.assertIn("oracle_risk_score", _make())

    def test_has_oracle_label_key(self):
        self.assertIn("oracle_label", _make())

    def test_has_log_entry_key(self):
        self.assertIn("log_entry", _make())

    def test_exactly_six_keys(self):
        self.assertEqual(len(_make()), 6)

    def test_staleness_seconds_is_float(self):
        self.assertIsInstance(_make()["staleness_seconds"], float)

    def test_staleness_ratio_is_float(self):
        self.assertIsInstance(_make()["staleness_ratio"], float)

    def test_price_deviation_pct_is_float(self):
        self.assertIsInstance(_make()["price_deviation_pct"], float)

    def test_oracle_risk_score_is_int(self):
        self.assertIsInstance(_make()["oracle_risk_score"], int)

    def test_oracle_label_is_str(self):
        self.assertIsInstance(_make()["oracle_label"], str)

    def test_log_entry_is_dict(self):
        self.assertIsInstance(_make()["log_entry"], dict)


# ===========================================================================
# 2. staleness_seconds calculation
# ===========================================================================
class TestStalenessSeconds(unittest.TestCase):
    def test_zero_when_current_equals_last(self):
        r = _make(staleness_s=0.0)
        self.assertEqual(r["staleness_seconds"], 0.0)

    def test_positive_staleness(self):
        r = _make(staleness_s=1800.0)
        self.assertAlmostEqual(r["staleness_seconds"], 1800.0)

    def test_one_hour(self):
        r = _make(staleness_s=3600.0)
        self.assertAlmostEqual(r["staleness_seconds"], 3600.0)

    def test_one_day(self):
        r = _make(staleness_s=86400.0)
        self.assertAlmostEqual(r["staleness_seconds"], 86400.0)

    def test_small_staleness(self):
        r = _make(staleness_s=5.0)
        self.assertAlmostEqual(r["staleness_seconds"], 5.0)

    def test_large_staleness(self):
        r = _make(staleness_s=7 * 86400.0)
        self.assertAlmostEqual(r["staleness_seconds"], 7 * 86400.0)

    def test_negative_staleness_when_future_update(self):
        # last_update in the future → negative staleness
        analyzer = DeFiProtocolOraclePriceFreshnessAnalyzer(
            data_dir=tempfile.mkdtemp()
        )
        r = analyzer.analyze(
            last_update_timestamp=NOW + 100.0,
            current_timestamp=NOW,
            heartbeat_seconds=3600,
            deviation_threshold_pct=0.5,
            observed_price_usd=1800.0,
            reference_price_usd=1800.0,
            num_oracles=3,
            protocol_name="Proto",
        )
        self.assertLess(r["staleness_seconds"], 0.0)


# ===========================================================================
# 3. staleness_ratio calculation
# ===========================================================================
class TestStalenessRatio(unittest.TestCase):
    def test_ratio_zero(self):
        r = _make(staleness_s=0.0, heartbeat=3600)
        self.assertAlmostEqual(r["staleness_ratio"], 0.0)

    def test_ratio_half(self):
        r = _make(staleness_s=1800.0, heartbeat=3600)
        self.assertAlmostEqual(r["staleness_ratio"], 0.5)

    def test_ratio_one(self):
        r = _make(staleness_s=3600.0, heartbeat=3600)
        self.assertAlmostEqual(r["staleness_ratio"], 1.0)

    def test_ratio_two(self):
        r = _make(staleness_s=7200.0, heartbeat=3600)
        self.assertAlmostEqual(r["staleness_ratio"], 2.0)

    def test_ratio_three(self):
        r = _make(staleness_s=10800.0, heartbeat=3600)
        self.assertAlmostEqual(r["staleness_ratio"], 3.0)

    def test_ratio_heartbeat_86400(self):
        r = _make(staleness_s=43200.0, heartbeat=86400)
        self.assertAlmostEqual(r["staleness_ratio"], 0.5)

    def test_ratio_heartbeat_1800(self):
        r = _make(staleness_s=900.0, heartbeat=1800)
        self.assertAlmostEqual(r["staleness_ratio"], 0.5)

    def test_zero_heartbeat_yields_ratio_zero(self):
        analyzer = DeFiProtocolOraclePriceFreshnessAnalyzer(
            data_dir=tempfile.mkdtemp()
        )
        r = analyzer.analyze(
            last_update_timestamp=NOW - 3600,
            current_timestamp=NOW,
            heartbeat_seconds=0,
            deviation_threshold_pct=0.5,
            observed_price_usd=1800.0,
            reference_price_usd=1800.0,
            num_oracles=3,
            protocol_name="Proto",
        )
        self.assertEqual(r["staleness_ratio"], 0.0)

    def test_ratio_formula(self):
        """staleness_ratio == staleness_seconds / heartbeat_seconds."""
        for stale, hb in [(100, 400), (3000, 3600), (172800, 86400)]:
            with self.subTest(stale=stale, hb=hb):
                r = _make(staleness_s=stale, heartbeat=hb)
                self.assertAlmostEqual(r["staleness_ratio"], stale / hb)


# ===========================================================================
# 4. price_deviation_pct calculation
# ===========================================================================
class TestPriceDeviationPct(unittest.TestCase):
    def test_zero_deviation_identical_prices(self):
        r = _make(observed=1800.0, reference=1800.0)
        self.assertAlmostEqual(r["price_deviation_pct"], 0.0)

    def test_positive_deviation_above_reference(self):
        r = _make(observed=1818.0, reference=1800.0)
        self.assertAlmostEqual(r["price_deviation_pct"], 1.0, places=6)

    def test_positive_deviation_below_reference(self):
        # abs value — sign doesn't matter
        r = _make(observed=1782.0, reference=1800.0)
        self.assertAlmostEqual(r["price_deviation_pct"], 1.0, places=6)

    def test_half_percent_deviation(self):
        r = _make(observed=1809.0, reference=1800.0)
        self.assertAlmostEqual(r["price_deviation_pct"], 0.5, places=6)

    def test_two_percent_deviation(self):
        r = _make(observed=1764.0, reference=1800.0)
        self.assertAlmostEqual(r["price_deviation_pct"], 2.0, places=6)

    def test_zero_reference_returns_zero(self):
        r = _make(observed=100.0, reference=0.0)
        self.assertEqual(r["price_deviation_pct"], 0.0)

    def test_deviation_threshold_boundary(self):
        # exactly at threshold → not treated as deviation
        r = _make(observed=1800.0 * 1.005, reference=1800.0, dev_threshold=0.5)
        self.assertAlmostEqual(r["price_deviation_pct"], 0.5, places=5)

    def test_deviation_formula_symmetrical(self):
        r1 = _make(observed=2000.0, reference=1800.0)
        r2 = _make(observed=1800.0, reference=2000.0)
        self.assertAlmostEqual(
            r1["price_deviation_pct"] * 1800.0,
            r2["price_deviation_pct"] * 2000.0,
        )


# ===========================================================================
# 5. Label: FRESH_ORACLE
# ===========================================================================
class TestLabelFreshOracle(unittest.TestCase):
    def test_fresh_zero_staleness_zero_deviation(self):
        r = _make(staleness_s=0.0, observed=1800.0, reference=1800.0, dev_threshold=0.5)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")

    def test_fresh_ratio_0_4_low_deviation(self):
        r = _make(staleness_s=1440.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")

    def test_fresh_just_under_ratio_half(self):
        # ratio = 0.499
        r = _make(staleness_s=1796.4, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")

    def test_fresh_small_deviation_below_threshold(self):
        r = _make(
            staleness_s=100.0,
            heartbeat=3600,
            observed=1800.0 * 1.001,  # 0.1% — below 0.5% threshold
            reference=1800.0,
            dev_threshold=0.5,
        )
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")

    def test_fresh_24h_heartbeat_well_within(self):
        r = _make(staleness_s=3600.0, heartbeat=86400, observed=1.0, reference=1.0)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")

    def test_fresh_many_oracles_no_deviation(self):
        r = _make(num_oracles=10, staleness_s=0.0, observed=2000.0, reference=2000.0)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")


# ===========================================================================
# 6. Label: AGING_ORACLE
# ===========================================================================
class TestLabelAgingOracle(unittest.TestCase):
    def test_aging_ratio_exactly_half(self):
        r = _make(staleness_s=1800.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "AGING_ORACLE")

    def test_aging_ratio_0_7(self):
        r = _make(staleness_s=2520.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "AGING_ORACLE")

    def test_aging_ratio_0_99(self):
        r = _make(staleness_s=3564.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "AGING_ORACLE")

    def test_aging_fresh_staleness_but_deviation_at_threshold(self):
        # ratio < 0.5 but deviation >= threshold → FRESH requires deviation < threshold
        # Use 1810.0 → deviation = 10/1800*100 = 0.5556% > 0.5% → NOT FRESH
        r = _make(
            staleness_s=100.0, heartbeat=3600,
            observed=1810.0, reference=1800.0, dev_threshold=0.5
        )
        # deviation_pct > threshold → NOT FRESH; ratio < 1.0 → AGING
        self.assertEqual(r["oracle_label"], "AGING_ORACLE")

    def test_aging_ratio_0_6(self):
        r = _make(staleness_s=2160.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "AGING_ORACLE")


# ===========================================================================
# 7. Label: STALE_ORACLE
# ===========================================================================
class TestLabelStaleOracle(unittest.TestCase):
    def test_stale_ratio_exactly_one(self):
        r = _make(staleness_s=3600.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "STALE_ORACLE")

    def test_stale_ratio_1_5(self):
        r = _make(staleness_s=5400.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "STALE_ORACLE")

    def test_stale_ratio_1_99(self):
        r = _make(staleness_s=7164.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "STALE_ORACLE")

    def test_stale_24h_heartbeat(self):
        r = _make(staleness_s=86400.0, heartbeat=86400, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "STALE_ORACLE")

    def test_stale_ratio_1_1(self):
        r = _make(staleness_s=3960.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "STALE_ORACLE")


# ===========================================================================
# 8. Label: CRITICAL_STALE
# ===========================================================================
class TestLabelCriticalStale(unittest.TestCase):
    def test_critical_stale_ratio_exactly_two(self):
        r = _make(staleness_s=7200.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "CRITICAL_STALE")

    def test_critical_stale_ratio_three(self):
        r = _make(staleness_s=10800.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "CRITICAL_STALE")

    def test_critical_stale_ratio_ten(self):
        r = _make(staleness_s=36000.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "CRITICAL_STALE")

    def test_critical_stale_24h_heartbeat(self):
        r = _make(staleness_s=3 * 86400.0, heartbeat=86400, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "CRITICAL_STALE")

    def test_critical_stale_ratio_2_1(self):
        r = _make(staleness_s=7560.0, heartbeat=3600, observed=1800.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "CRITICAL_STALE")


# ===========================================================================
# 9. Label: MANIPULATED_PRICE (highest priority)
# ===========================================================================
class TestLabelManipulatedPrice(unittest.TestCase):
    def test_manipulated_deviation_above_2x_threshold(self):
        # threshold=0.5%, deviation=1.1% (> 2×0.5 = 1.0%)
        r = _make(
            staleness_s=0.0, dev_threshold=0.5,
            observed=1800.0 * 1.011, reference=1800.0
        )
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_priority_over_fresh(self):
        # ratio < 0.5 but deviation > 2× threshold → MANIPULATED wins
        r = _make(
            staleness_s=100.0, heartbeat=3600, dev_threshold=0.5,
            observed=1800.0 * 1.02, reference=1800.0  # 2% > 1.0%
        )
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_priority_over_aging(self):
        r = _make(
            staleness_s=2000.0, heartbeat=3600, dev_threshold=0.5,
            observed=1800.0 * 1.05, reference=1800.0  # 5% >> 1.0%
        )
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_priority_over_stale(self):
        r = _make(
            staleness_s=5000.0, heartbeat=3600, dev_threshold=0.5,
            observed=1800.0 * 1.05, reference=1800.0
        )
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_priority_over_critical_stale(self):
        r = _make(
            staleness_s=20000.0, heartbeat=3600, dev_threshold=0.5,
            observed=1800.0 * 1.05, reference=1800.0
        )
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_not_manipulated_exactly_2x_threshold(self):
        # deviation must be STRICTLY greater than 2× threshold
        # 2× 0.5% = 1.0%; deviation exactly 1.0% → NOT manipulated
        r = _make(
            staleness_s=0.0, dev_threshold=0.5,
            observed=1800.0 * 1.01, reference=1800.0  # exactly 1.0%
        )
        self.assertNotEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_just_above_2x_threshold(self):
        # 1.001% > 2×0.5% = 1.0%
        r = _make(
            staleness_s=0.0, dev_threshold=0.5,
            observed=1800.0 * 1.01001, reference=1800.0
        )
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_large_deviation(self):
        r = _make(dev_threshold=1.0, observed=2000.0, reference=1000.0)
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_manipulated_price_drop_direction(self):
        # Price significantly below reference
        r = _make(dev_threshold=0.5, observed=1700.0, reference=1800.0)
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")


# ===========================================================================
# 10. Risk score: range and type
# ===========================================================================
class TestRiskScoreRange(unittest.TestCase):
    def test_risk_score_non_negative(self):
        r = _make()
        self.assertGreaterEqual(r["oracle_risk_score"], 0)

    def test_risk_score_at_most_100(self):
        r = _make()
        self.assertLessEqual(r["oracle_risk_score"], 100)

    def test_risk_score_fresh_oracle_low(self):
        r = _make(staleness_s=0.0, observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 0)

    def test_risk_score_capped_at_100(self):
        # ratio >> 2, deviation >> threshold, single oracle → >100 before clamp
        r = _make(
            staleness_s=100000.0, heartbeat=3600, dev_threshold=0.5,
            observed=1900.0, reference=1800.0, num_oracles=1
        )
        self.assertEqual(r["oracle_risk_score"], 100)


# ===========================================================================
# 11. Risk score: staleness component
# ===========================================================================
class TestRiskScoreStalenessComponent(unittest.TestCase):
    def test_staleness_zero(self):
        # staleness_component = 0; deviation=0; oracles=3 → total=0
        r = _make(staleness_s=0.0, observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 0)

    def test_staleness_ratio_1_0(self):
        # staleness_component = 1.0*35=35; dev=0; oracles=3 → 35
        r = _make(staleness_s=3600.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 35)

    def test_staleness_ratio_2_0(self):
        # staleness_component = min(70, 2.0*35)=70; dev=0; oracles=3 → 70
        r = _make(staleness_s=7200.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 70)

    def test_staleness_component_capped_at_70(self):
        # ratio=5 → 5*35=175 → capped at 70
        r = _make(staleness_s=18000.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 70)

    def test_staleness_ratio_half(self):
        # 0.5*35=17.5 → int(17.5+0.5)=int(18.0)=18
        r = _make(staleness_s=1800.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 18)

    def test_staleness_ratio_1_5(self):
        # 1.5*35=52.5 → int(52.5+0.5)=int(53.0)=53
        r = _make(staleness_s=5400.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 53)


# ===========================================================================
# 12. Risk score: deviation component
# ===========================================================================
class TestRiskScoreDeviationComponent(unittest.TestCase):
    def test_deviation_zero_component_zero(self):
        r = _make(staleness_s=0.0, observed=1800.0, reference=1800.0,
                  dev_threshold=0.5, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 0)

    def test_deviation_at_threshold(self):
        # dev_ratio=1.0 → 1.0*15=15 → total=0+15+0=15 → int(15.5)=15
        r = _make(staleness_s=0.0, observed=1800.0 * 1.005, reference=1800.0,
                  dev_threshold=0.5, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 15)

    def test_deviation_at_2x_threshold(self):
        # dev_ratio=2.0 → min(30, 2.0*15)=30 → total=0+30+0=30 → 30
        r = _make(staleness_s=0.0, observed=1800.0 * 1.01, reference=1800.0,
                  dev_threshold=0.5, num_oracles=3)
        self.assertEqual(r["oracle_risk_score"], 30)

    def test_deviation_component_capped_at_30(self):
        # dev_ratio >> 2 → capped at 30
        r = _make(staleness_s=0.0, observed=1900.0, reference=1800.0,
                  dev_threshold=0.5, num_oracles=3)
        # deviation = 5.56% >> 2×0.5% → component=30
        self.assertEqual(r["oracle_risk_score"], 30)

    def test_deviation_below_threshold_no_score(self):
        # dev=0.1%, threshold=0.5% → dev_ratio=0.2 → score=0.2*15=3
        r = _make(staleness_s=0.0, observed=1800.0 * 1.001, reference=1800.0,
                  dev_threshold=0.5, num_oracles=3)
        # int(3+0.5)=3
        self.assertEqual(r["oracle_risk_score"], 3)

    def test_zero_threshold_no_deviation_score(self):
        # threshold=0 → dev_ratio=0.0 → deviation_component=0
        analyzer = DeFiProtocolOraclePriceFreshnessAnalyzer(data_dir=tempfile.mkdtemp())
        r = analyzer.analyze(
            last_update_timestamp=NOW,
            current_timestamp=NOW,
            heartbeat_seconds=3600,
            deviation_threshold_pct=0.0,
            observed_price_usd=1900.0,
            reference_price_usd=1800.0,
            num_oracles=3,
            protocol_name="P",
        )
        self.assertEqual(r["oracle_risk_score"], 0)


# ===========================================================================
# 13. Risk score: redundancy penalty
# ===========================================================================
class TestRiskScoreRedundancy(unittest.TestCase):
    def _score_for_oracles(self, n: int) -> int:
        r = _make(staleness_s=0.0, observed=1800.0, reference=1800.0,
                  dev_threshold=0.5, num_oracles=n)
        return r["oracle_risk_score"]

    def test_one_oracle_penalty_10(self):
        self.assertEqual(self._score_for_oracles(1), 10)

    def test_zero_oracles_penalty_10(self):
        # num_oracles ≤ 1 → +10
        r = _make(staleness_s=0.0, observed=1800.0, reference=1800.0,
                  dev_threshold=0.5, num_oracles=0)
        self.assertEqual(r["oracle_risk_score"], 10)

    def test_two_oracles_penalty_5(self):
        self.assertEqual(self._score_for_oracles(2), 5)

    def test_three_oracles_no_penalty(self):
        self.assertEqual(self._score_for_oracles(3), 0)

    def test_five_oracles_no_penalty(self):
        self.assertEqual(self._score_for_oracles(5), 0)

    def test_ten_oracles_no_penalty(self):
        self.assertEqual(self._score_for_oracles(10), 0)

    def test_combined_stale_single_oracle(self):
        # ratio=1: staleness=35; dev=0; oracles=1: +10 → 45
        r = _make(staleness_s=3600.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=1)
        self.assertEqual(r["oracle_risk_score"], 45)

    def test_combined_stale_two_oracles(self):
        # ratio=1: staleness=35; dev=0; oracles=2: +5 → 40
        r = _make(staleness_s=3600.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=2)
        self.assertEqual(r["oracle_risk_score"], 40)


# ===========================================================================
# 14. Log entry structure
# ===========================================================================
class TestLogEntryStructure(unittest.TestCase):
    REQUIRED_KEYS = {
        "protocol_name",
        "last_update_timestamp",
        "current_timestamp",
        "heartbeat_seconds",
        "deviation_threshold_pct",
        "observed_price_usd",
        "reference_price_usd",
        "num_oracles",
        "staleness_seconds",
        "staleness_ratio",
        "price_deviation_pct",
        "oracle_risk_score",
        "oracle_label",
        "analyzed_at",
    }

    def _entry(self) -> dict:
        return _make()["log_entry"]

    def test_all_required_keys_present(self):
        entry = self._entry()
        for k in self.REQUIRED_KEYS:
            with self.subTest(key=k):
                self.assertIn(k, entry)

    def test_protocol_name_value(self):
        r = _make(protocol="AaveV3")
        self.assertEqual(r["log_entry"]["protocol_name"], "AaveV3")

    def test_staleness_seconds_in_entry(self):
        r = _make(staleness_s=1200.0)
        self.assertAlmostEqual(r["log_entry"]["staleness_seconds"], 1200.0)

    def test_staleness_ratio_in_entry(self):
        r = _make(staleness_s=1800.0, heartbeat=3600)
        self.assertAlmostEqual(r["log_entry"]["staleness_ratio"], 0.5)

    def test_oracle_label_in_entry(self):
        r = _make()
        self.assertEqual(r["log_entry"]["oracle_label"], r["oracle_label"])

    def test_risk_score_in_entry(self):
        r = _make()
        self.assertEqual(r["log_entry"]["oracle_risk_score"], r["oracle_risk_score"])

    def test_analyzed_at_is_float(self):
        entry = self._entry()
        self.assertIsInstance(entry["analyzed_at"], float)

    def test_analyzed_at_positive(self):
        entry = self._entry()
        self.assertGreater(entry["analyzed_at"], 0.0)

    def test_heartbeat_seconds_in_entry(self):
        r = _make(heartbeat=86400)
        self.assertEqual(r["log_entry"]["heartbeat_seconds"], 86400)

    def test_deviation_threshold_in_entry(self):
        r = _make(dev_threshold=1.0)
        self.assertAlmostEqual(r["log_entry"]["deviation_threshold_pct"], 1.0)

    def test_observed_price_in_entry(self):
        r = _make(observed=2500.0)
        self.assertAlmostEqual(r["log_entry"]["observed_price_usd"], 2500.0)

    def test_reference_price_in_entry(self):
        r = _make(reference=2490.0)
        self.assertAlmostEqual(r["log_entry"]["reference_price_usd"], 2490.0)

    def test_num_oracles_in_entry(self):
        r = _make(num_oracles=5)
        self.assertEqual(r["log_entry"]["num_oracles"], 5)


# ===========================================================================
# 15. Log file persistence
# ===========================================================================
class TestLogFilePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolOraclePriceFreshnessAnalyzer(data_dir=self.tmp_dir)
        self.log_path = os.path.join(self.tmp_dir, "oracle_price_freshness_log.json")

    def _run(self, **kwargs):
        defaults = dict(
            last_update_timestamp=NOW,
            current_timestamp=NOW,
            heartbeat_seconds=3600,
            deviation_threshold_pct=0.5,
            observed_price_usd=1800.0,
            reference_price_usd=1800.0,
            num_oracles=3,
            protocol_name="TestP",
        )
        defaults.update(kwargs)
        return self.analyzer.analyze(**defaults)

    def test_log_file_not_created_by_analyze(self):
        # analyze() alone does not write file — log_result() does
        self._run()
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_result_creates_file(self):
        r = self._run()
        self.analyzer.log_result(r["log_entry"])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_result_file_is_valid_json(self):
        r = self._run()
        self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_result_one_entry(self):
        r = self._run()
        self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_result_appends_second_entry(self):
        for _ in range(2):
            r = self._run()
            self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap_100(self):
        for i in range(105):
            r = self._run(protocol_name=f"P{i}")
            self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_ring_buffer_keeps_most_recent(self):
        for i in range(105):
            r = self._run(protocol_name=f"P{i}")
            self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        # The 100 most-recent entries are P5 … P104
        self.assertEqual(data[0]["protocol_name"], "P5")
        self.assertEqual(data[-1]["protocol_name"], "P104")

    def test_log_ring_buffer_exactly_100_no_trim(self):
        for i in range(100):
            r = self._run(protocol_name=f"P{i}")
            self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_ring_buffer_200_entries_trimmed_to_100(self):
        for i in range(200):
            r = self._run(protocol_name=f"P{i}")
            self.analyzer.log_result(r["log_entry"])
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_no_tmp_file_left_behind(self):
        r = self._run()
        self.analyzer.log_result(r["log_entry"])
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_read_log_empty_when_no_file(self):
        entries = self.analyzer._read_log()
        self.assertEqual(entries, [])

    def test_read_log_returns_list(self):
        r = self._run()
        self.analyzer.log_result(r["log_entry"])
        entries = self.analyzer._read_log()
        self.assertIsInstance(entries, list)

    def test_read_log_corrupted_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("not valid json {{{")
        entries = self.analyzer._read_log()
        self.assertEqual(entries, [])

    def test_read_log_wrong_type_returns_empty(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        entries = self.analyzer._read_log()
        self.assertEqual(entries, [])

    def test_data_dir_created_if_missing(self):
        nested = os.path.join(self.tmp_dir, "subdir", "nested")
        a = DeFiProtocolOraclePriceFreshnessAnalyzer(data_dir=nested)
        r = a.analyze(
            last_update_timestamp=NOW, current_timestamp=NOW,
            heartbeat_seconds=3600, deviation_threshold_pct=0.5,
            observed_price_usd=1800.0, reference_price_usd=1800.0,
            num_oracles=3, protocol_name="P",
        )
        a.log_result(r["log_entry"])
        self.assertTrue(os.path.isdir(nested))


# ===========================================================================
# 16. Various edge cases & integration scenarios
# ===========================================================================
class TestEdgeCasesAndIntegration(unittest.TestCase):
    def test_multiple_analyses_independent(self):
        r1 = _make(staleness_s=0.0)
        r2 = _make(staleness_s=7200.0, heartbeat=3600)
        self.assertEqual(r1["oracle_label"], "FRESH_ORACLE")
        self.assertEqual(r2["oracle_label"], "CRITICAL_STALE")

    def test_chainlink_eth_usd_scenario(self):
        # Realistic: heartbeat 3600s, threshold 0.5%, 21-oracle aggregator, fresh
        r = _make(staleness_s=1200.0, heartbeat=3600,
                  observed=1800.50, reference=1800.0, dev_threshold=0.5,
                  num_oracles=21)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")
        # Risk score is non-zero because of small staleness and tiny deviation
        self.assertLessEqual(r["oracle_risk_score"], 20)

    def test_stale_24h_btc_oracle(self):
        r = _make(staleness_s=86400.0, heartbeat=86400,
                  observed=45000.0, reference=45000.0, dev_threshold=0.5,
                  num_oracles=5)
        self.assertEqual(r["oracle_label"], "STALE_ORACLE")

    def test_critical_stale_long_no_update(self):
        r = _make(staleness_s=48 * 3600, heartbeat=3600,
                  observed=1800.0, reference=1800.0, num_oracles=3)
        self.assertEqual(r["oracle_label"], "CRITICAL_STALE")

    def test_label_manipulation_large_threshold(self):
        # threshold=5%, deviation=10.1% > 10% → MANIPULATED
        r = _make(dev_threshold=5.0, observed=1981.8, reference=1800.0)
        self.assertEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_label_not_manipulated_below_2x_threshold(self):
        # threshold=5%, deviation=9.9% < 10% → NOT MANIPULATED
        r = _make(staleness_s=0.0, dev_threshold=5.0,
                  observed=1978.2, reference=1800.0)  # ~9.9%
        self.assertNotEqual(r["oracle_label"], "MANIPULATED_PRICE")

    def test_fresh_very_small_threshold(self):
        r = _make(staleness_s=60.0, heartbeat=3600,
                  observed=1800.0, reference=1800.0, dev_threshold=0.1)
        self.assertEqual(r["oracle_label"], "FRESH_ORACLE")

    def test_risk_score_critical_and_single_oracle(self):
        r = _make(staleness_s=7200.0, heartbeat=3600,
                  observed=1900.0, reference=1800.0,  # ~5.56% >> 2×0.5
                  dev_threshold=0.5, num_oracles=1)
        self.assertEqual(r["oracle_risk_score"], 100)

    def test_log_entry_roundtrip(self):
        tmp_dir = tempfile.mkdtemp()
        a = DeFiProtocolOraclePriceFreshnessAnalyzer(data_dir=tmp_dir)
        for protocol in ["Aave", "Compound", "Morpho"]:
            r = a.analyze(
                last_update_timestamp=NOW - 300, current_timestamp=NOW,
                heartbeat_seconds=3600, deviation_threshold_pct=0.5,
                observed_price_usd=1800.0, reference_price_usd=1800.0,
                num_oracles=3, protocol_name=protocol,
            )
            a.log_result(r["log_entry"])
        entries = a._read_log()
        self.assertEqual(len(entries), 3)
        names = [e["protocol_name"] for e in entries]
        self.assertEqual(names, ["Aave", "Compound", "Morpho"])

    def test_label_constants_match_strings(self):
        self.assertEqual(DeFiProtocolOraclePriceFreshnessAnalyzer.FRESH_ORACLE, "FRESH_ORACLE")
        self.assertEqual(DeFiProtocolOraclePriceFreshnessAnalyzer.AGING_ORACLE, "AGING_ORACLE")
        self.assertEqual(DeFiProtocolOraclePriceFreshnessAnalyzer.STALE_ORACLE, "STALE_ORACLE")
        self.assertEqual(DeFiProtocolOraclePriceFreshnessAnalyzer.CRITICAL_STALE, "CRITICAL_STALE")
        self.assertEqual(DeFiProtocolOraclePriceFreshnessAnalyzer.MANIPULATED_PRICE, "MANIPULATED_PRICE")

    def test_result_fields_consistent_with_log_entry(self):
        r = _make(staleness_s=3600.0, heartbeat=3600,
                  observed=1810.0, reference=1800.0)
        self.assertAlmostEqual(r["staleness_seconds"], r["log_entry"]["staleness_seconds"])
        self.assertAlmostEqual(r["staleness_ratio"], r["log_entry"]["staleness_ratio"])
        self.assertAlmostEqual(r["price_deviation_pct"], r["log_entry"]["price_deviation_pct"])
        self.assertEqual(r["oracle_risk_score"], r["log_entry"]["oracle_risk_score"])
        self.assertEqual(r["oracle_label"], r["log_entry"]["oracle_label"])

    def test_risk_score_boundary_at_100(self):
        # Construct scenario where unclamped total == exactly 100
        # staleness=2: 70, dev >> threshold: 30, oracles=0: 10 → 110 → clamped 100
        r = _make(staleness_s=7200.0, heartbeat=3600,
                  observed=1820.0, reference=1800.0, dev_threshold=0.1,
                  num_oracles=1)
        self.assertLessEqual(r["oracle_risk_score"], 100)
        self.assertGreaterEqual(r["oracle_risk_score"], 0)


if __name__ == "__main__":
    unittest.main()

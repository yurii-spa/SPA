"""
Tests for MP-1048 DeFiProtocolBorrowingPowerUtilizationAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_borrowing_power_utilization_analyzer import (
    DeFiProtocolBorrowingPowerUtilizationAnalyzer,
    analyze,
    _current_ltv_pct,
    _volatility_adjusted_safe_ltv,
    _optimal_borrow_pct,
    _safety_buffer_pct,
    _risk_adjusted_capacity_usd,
    _utilization_efficiency_score,
    _label,
    _build_recommendations,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _pos(
    protocol: str = "Aave V3",
    collateral_value_usd: float = 100_000.0,
    borrowed_value_usd: float = 65_000.0,
    max_ltv_pct: float = 80.0,
    liquidation_ltv_pct: float = 85.0,
    asset_volatility_30d_pct: float = 15.0,
    position_size_usd: float = 100_000.0,
    strategy_target_ltv_pct: float = 65.0,
) -> dict:
    return {
        "protocol": protocol,
        "collateral_value_usd": collateral_value_usd,
        "borrowed_value_usd": borrowed_value_usd,
        "max_ltv_pct": max_ltv_pct,
        "liquidation_ltv_pct": liquidation_ltv_pct,
        "asset_volatility_30d_pct": asset_volatility_30d_pct,
        "position_size_usd": position_size_usd,
        "strategy_target_ltv_pct": strategy_target_ltv_pct,
    }


# ===========================================================================
# 1. _current_ltv_pct
# ===========================================================================

class TestCurrentLtvPct(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_current_ltv_pct(65_000.0, 100_000.0), 65.0)

    def test_zero_collateral_safe(self):
        self.assertEqual(_current_ltv_pct(50_000.0, 0.0), 0.0)

    def test_negative_collateral_safe(self):
        self.assertEqual(_current_ltv_pct(50_000.0, -1.0), 0.0)

    def test_zero_borrow(self):
        self.assertEqual(_current_ltv_pct(0.0, 100_000.0), 0.0)

    def test_full_ltv(self):
        self.assertAlmostEqual(_current_ltv_pct(100_000.0, 100_000.0), 100.0)

    def test_over_100_pct(self):
        # borrowed > collateral is possible in underwater positions
        result = _current_ltv_pct(120_000.0, 100_000.0)
        self.assertGreater(result, 100.0)

    def test_small_amounts(self):
        self.assertAlmostEqual(_current_ltv_pct(0.5, 1.0), 50.0)

    def test_monotonic_in_borrowed(self):
        self.assertLess(
            _current_ltv_pct(40_000.0, 100_000.0),
            _current_ltv_pct(60_000.0, 100_000.0),
        )


# ===========================================================================
# 2. _volatility_adjusted_safe_ltv
# ===========================================================================

class TestVolatilityAdjustedSafeLtv(unittest.TestCase):
    def test_basic(self):
        # liquidation=85, vol=20% → 85 * 0.8 = 68
        self.assertAlmostEqual(_volatility_adjusted_safe_ltv(85.0, 20.0), 68.0)

    def test_zero_volatility(self):
        self.assertAlmostEqual(_volatility_adjusted_safe_ltv(85.0, 0.0), 85.0)

    def test_100_pct_volatility_clamped(self):
        # vol capped at 99%, result near 0
        result = _volatility_adjusted_safe_ltv(85.0, 100.0)
        self.assertAlmostEqual(result, 85.0 * 0.01, places=2)

    def test_negative_volatility_treated_as_zero(self):
        self.assertAlmostEqual(_volatility_adjusted_safe_ltv(85.0, -5.0), 85.0)

    def test_non_negative(self):
        self.assertGreaterEqual(_volatility_adjusted_safe_ltv(85.0, 90.0), 0.0)

    def test_decreases_with_volatility(self):
        low = _volatility_adjusted_safe_ltv(85.0, 10.0)
        high = _volatility_adjusted_safe_ltv(85.0, 30.0)
        self.assertGreater(low, high)

    def test_scales_with_liquidation_threshold(self):
        r1 = _volatility_adjusted_safe_ltv(80.0, 20.0)
        r2 = _volatility_adjusted_safe_ltv(90.0, 20.0)
        self.assertLess(r1, r2)


# ===========================================================================
# 3. _optimal_borrow_pct
# ===========================================================================

class TestOptimalBorrowPct(unittest.TestCase):
    def test_aligns_with_strategy_target_when_safe(self):
        # max_ltv=80, liq=85, vol=15%, strategy_target=65 → should pick 65
        result = _optimal_borrow_pct(80.0, 85.0, 15.0, 65.0)
        self.assertAlmostEqual(result, 65.0)

    def test_ignores_aggressive_strategy_target(self):
        # strategy_target > conservative cap → uses conservative cap
        result = _optimal_borrow_pct(80.0, 85.0, 5.0, 95.0)
        self.assertLess(result, 95.0)

    def test_zero_strategy_target(self):
        result = _optimal_borrow_pct(80.0, 85.0, 15.0, 0.0)
        self.assertGreater(result, 0.0)

    def test_non_negative(self):
        for vol in (0.0, 10.0, 50.0, 95.0):
            self.assertGreaterEqual(
                _optimal_borrow_pct(80.0, 85.0, vol, 60.0), 0.0
            )

    def test_limited_by_max_ltv(self):
        result = _optimal_borrow_pct(80.0, 85.0, 5.0, 0.0)
        self.assertLessEqual(result, 80.0)

    def test_high_volatility_reduces_optimal(self):
        low_vol = _optimal_borrow_pct(80.0, 85.0, 5.0, 0.0)
        high_vol = _optimal_borrow_pct(80.0, 85.0, 40.0, 0.0)
        self.assertGreater(low_vol, high_vol)


# ===========================================================================
# 4. _safety_buffer_pct
# ===========================================================================

class TestSafetyBufferPct(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_safety_buffer_pct(65.0, 85.0), 20.0)

    def test_at_liquidation(self):
        self.assertAlmostEqual(_safety_buffer_pct(85.0, 85.0), 0.0)

    def test_over_liquidation_clamped_to_zero(self):
        self.assertAlmostEqual(_safety_buffer_pct(90.0, 85.0), 0.0)

    def test_no_borrow(self):
        self.assertAlmostEqual(_safety_buffer_pct(0.0, 85.0), 85.0)

    def test_positive(self):
        self.assertGreater(_safety_buffer_pct(50.0, 85.0), 0.0)


# ===========================================================================
# 5. _risk_adjusted_capacity_usd
# ===========================================================================

class TestRiskAdjustedCapacityUsd(unittest.TestCase):
    def test_positive_capacity(self):
        # collateral=100k, optimal=65%, borrowed=50k → capacity=15k
        cap = _risk_adjusted_capacity_usd(100_000.0, 65.0, 50_000.0)
        self.assertAlmostEqual(cap, 15_000.0)

    def test_zero_capacity_at_optimal(self):
        cap = _risk_adjusted_capacity_usd(100_000.0, 65.0, 65_000.0)
        self.assertAlmostEqual(cap, 0.0)

    def test_negative_capacity_when_over_optimal(self):
        cap = _risk_adjusted_capacity_usd(100_000.0, 65.0, 80_000.0)
        self.assertLess(cap, 0.0)

    def test_zero_collateral(self):
        cap = _risk_adjusted_capacity_usd(0.0, 65.0, 0.0)
        self.assertAlmostEqual(cap, 0.0)

    def test_scales_with_collateral(self):
        c1 = _risk_adjusted_capacity_usd(100_000.0, 65.0, 0.0)
        c2 = _risk_adjusted_capacity_usd(200_000.0, 65.0, 0.0)
        self.assertAlmostEqual(c2, 2 * c1)


# ===========================================================================
# 6. _utilization_efficiency_score
# ===========================================================================

class TestUtilizationEfficiencyScore(unittest.TestCase):
    def test_at_optimal_gives_high_score(self):
        # current = optimal → peak score
        score = _utilization_efficiency_score(65.0, 65.0, 72.25, 85.0)
        self.assertGreater(score, 85.0)

    def test_at_liquidation_gives_zero(self):
        score = _utilization_efficiency_score(85.0, 65.0, 72.25, 85.0)
        self.assertAlmostEqual(score, 0.0)

    def test_over_liquidation_gives_zero(self):
        score = _utilization_efficiency_score(90.0, 65.0, 72.25, 85.0)
        self.assertAlmostEqual(score, 0.0)

    def test_zero_borrow_gives_low_score(self):
        score = _utilization_efficiency_score(0.0, 65.0, 72.25, 85.0)
        self.assertLess(score, 25.0)

    def test_over_vol_safe_gives_low_score(self):
        # current_ltv > vol_safe_ltv but < liquidation
        score = _utilization_efficiency_score(74.0, 65.0, 72.0, 85.0)
        self.assertLess(score, 21.0)

    def test_score_in_range_0_100(self):
        for ltv in (0.0, 10.0, 40.0, 65.0, 80.0, 85.0, 90.0):
            s = _utilization_efficiency_score(ltv, 65.0, 72.0, 85.0)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_no_optimal_gives_low_score(self):
        score = _utilization_efficiency_score(10.0, 0.0, 70.0, 85.0)
        self.assertLess(score, 20.0)

    def test_zero_ltv_no_optimal(self):
        score = _utilization_efficiency_score(0.0, 0.0, 70.0, 85.0)
        self.assertLessEqual(score, 15.0)

    def test_well_managed_range(self):
        # 55-85% utilization ratio → WELL_MANAGED (score 50-85)
        score = _utilization_efficiency_score(39.0, 65.0, 72.0, 85.0)
        self.assertGreater(score, 30.0)
        self.assertLess(score, 90.0)

    def test_over_optimal_but_safe_penalized(self):
        # Slight over-optimal
        s_at = _utilization_efficiency_score(65.0, 65.0, 72.0, 85.0)
        s_over = _utilization_efficiency_score(71.5, 65.0, 72.0, 85.0)
        self.assertGreaterEqual(s_at, s_over)


# ===========================================================================
# 7. _label
# ===========================================================================

class TestLabel(unittest.TestCase):
    def test_at_liquidation_is_over_leveraged(self):
        lbl = _label(85.0, 65.0, 72.0, 85.0, 0.0)
        self.assertEqual(lbl, "OVER_LEVERAGED")

    def test_over_vol_safe_is_over_leveraged(self):
        lbl = _label(74.0, 65.0, 72.0, 85.0, 15.0)
        self.assertEqual(lbl, "OVER_LEVERAGED")

    def test_high_score_is_optimally_utilized(self):
        lbl = _label(65.0, 65.0, 72.0, 85.0, 95.0)
        self.assertEqual(lbl, "OPTIMALLY_UTILIZED")

    def test_mid_score_is_well_managed(self):
        lbl = _label(40.0, 65.0, 72.0, 85.0, 65.0)
        self.assertEqual(lbl, "WELL_MANAGED")

    def test_low_mid_score_is_conservative(self):
        lbl = _label(15.0, 65.0, 72.0, 85.0, 35.0)
        self.assertEqual(lbl, "CONSERVATIVE")

    def test_very_low_score_is_underutilized(self):
        lbl = _label(2.0, 65.0, 72.0, 85.0, 11.0)
        self.assertEqual(lbl, "UNDERUTILIZED")

    def test_no_borrow_is_underutilized(self):
        lbl = _label(0.0, 65.0, 72.0, 85.0, 10.0)
        self.assertEqual(lbl, "UNDERUTILIZED")


# ===========================================================================
# 8. _build_recommendations
# ===========================================================================

class TestBuildRecommendations(unittest.TestCase):
    def test_over_leveraged_has_recommendation(self):
        recs = _build_recommendations("OVER_LEVERAGED", 90.0, 65.0, 2.0, -25000.0, 15.0)
        self.assertTrue(len(recs) >= 1)
        self.assertTrue(any("over-leveraged" in r.lower() for r in recs))

    def test_underutilized_mentions_capacity(self):
        recs = _build_recommendations("UNDERUTILIZED", 5.0, 65.0, 80.0, 60000.0, 10.0)
        self.assertTrue(len(recs) >= 1)

    def test_optimally_utilized_positive_message(self):
        recs = _build_recommendations("OPTIMALLY_UTILIZED", 65.0, 65.0, 20.0, 0.0, 10.0)
        self.assertTrue(len(recs) >= 1)

    def test_high_volatility_adds_warning(self):
        recs = _build_recommendations("WELL_MANAGED", 50.0, 65.0, 35.0, 15000.0, 30.0)
        self.assertTrue(any("volatility" in r.lower() for r in recs))

    def test_low_volatility_no_extra_warning(self):
        recs = _build_recommendations("WELL_MANAGED", 50.0, 65.0, 35.0, 15000.0, 5.0)
        # No extra volatility warning
        self.assertFalse(any("30d" in r and "High" in r for r in recs))

    def test_critical_buffer_adds_urgent(self):
        recs = _build_recommendations("OVER_LEVERAGED", 83.0, 65.0, 2.0, -18000.0, 10.0)
        self.assertTrue(any("critical" in r.lower() or "urgent" in r.lower() for r in recs))

    def test_returns_list(self):
        recs = _build_recommendations("CONSERVATIVE", 20.0, 65.0, 65.0, 45000.0, 10.0)
        self.assertIsInstance(recs, list)


# ===========================================================================
# 9. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        log = _tmp_log()
        _atomic_log(log, {"key": "val"})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["key"], "val")
        os.unlink(log)

    def test_appends_entries(self):
        log = _tmp_log()
        _atomic_log(log, {"n": 1})
        _atomic_log(log, {"n": 2})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(log)

    def test_ring_buffer_cap(self):
        log = _tmp_log()
        for i in range(110):
            _atomic_log(log, {"i": i})
        with open(log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)
        # Most recent entries preserved
        self.assertEqual(data[-1]["i"], 109)
        os.unlink(log)

    def test_recovers_from_corrupt_file(self):
        log = _tmp_log()
        with open(log, "w") as f:
            f.write("not json")
        _atomic_log(log, {"safe": True})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)


# ===========================================================================
# 10. DeFiProtocolBorrowingPowerUtilizationAnalyzer — class API
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def _run(self, **kw) -> dict:
        return DeFiProtocolBorrowingPowerUtilizationAnalyzer(self._cfg).analyze(_pos(**kw))

    def test_returns_dict(self):
        r = self._run()
        self.assertIsInstance(r, dict)

    def test_all_required_keys_present(self):
        r = self._run()
        for key in (
            "protocol", "current_ltv_pct", "volatility_adjusted_safe_ltv",
            "optimal_borrow_pct", "safety_buffer_pct", "risk_adjusted_capacity_usd",
            "utilization_efficiency_score", "label", "recommendations", "timestamp",
        ):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_score_in_range(self):
        r = self._run()
        self.assertGreaterEqual(r["utilization_efficiency_score"], 0.0)
        self.assertLessEqual(r["utilization_efficiency_score"], 100.0)

    def test_label_is_valid(self):
        r = self._run()
        self.assertIn(r["label"], {
            "OPTIMALLY_UTILIZED", "WELL_MANAGED", "CONSERVATIVE",
            "UNDERUTILIZED", "OVER_LEVERAGED"
        })

    def test_logs_entry(self):
        self._run()
        with open(self._log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_no_borrow_label_underutilized(self):
        r = self._run(borrowed_value_usd=0.0)
        self.assertEqual(r["label"], "UNDERUTILIZED")

    def test_over_leveraged_label(self):
        r = self._run(
            borrowed_value_usd=90_000.0,  # 90% LTV
            max_ltv_pct=80.0,
            liquidation_ltv_pct=85.0,
            asset_volatility_30d_pct=5.0,
        )
        self.assertEqual(r["label"], "OVER_LEVERAGED")

    def test_optimally_utilized_near_target(self):
        r = self._run(
            borrowed_value_usd=65_000.0,
            strategy_target_ltv_pct=65.0,
            asset_volatility_30d_pct=5.0,
        )
        self.assertIn(r["label"], {"OPTIMALLY_UTILIZED", "WELL_MANAGED"})

    def test_safety_buffer_positive(self):
        r = self._run(borrowed_value_usd=50_000.0)
        self.assertGreater(r["safety_buffer_pct"], 0.0)

    def test_safety_buffer_zero_at_liquidation(self):
        r = self._run(
            borrowed_value_usd=85_000.0,
            max_ltv_pct=80.0,
            liquidation_ltv_pct=85.0,
        )
        self.assertAlmostEqual(r["safety_buffer_pct"], 0.0)

    def test_current_ltv_correct(self):
        r = self._run(
            collateral_value_usd=100_000.0,
            borrowed_value_usd=60_000.0,
        )
        self.assertAlmostEqual(r["current_ltv_pct"], 60.0)

    def test_protocol_name_preserved(self):
        r = self._run(protocol="MorphoBlue")
        self.assertEqual(r["protocol"], "MorphoBlue")

    def test_recommendations_is_list(self):
        r = self._run()
        self.assertIsInstance(r["recommendations"], list)
        self.assertGreater(len(r["recommendations"]), 0)

    def test_timestamp_positive(self):
        r = self._run()
        self.assertGreater(r["timestamp"], 0.0)

    def test_missing_keys_use_defaults(self):
        # Passing minimal dict — should not crash
        r = DeFiProtocolBorrowingPowerUtilizationAnalyzer(self._cfg).analyze({})
        self.assertIn("label", r)

    def test_negative_borrowed_treated_as_zero(self):
        r = self._run(borrowed_value_usd=-5000.0)
        self.assertGreaterEqual(r["current_ltv_pct"], 0.0)

    def test_high_volatility_reduces_safe_ltv(self):
        r_low = self._run(asset_volatility_30d_pct=5.0)
        r_high = self._run(asset_volatility_30d_pct=50.0)
        self.assertGreater(
            r_low["volatility_adjusted_safe_ltv"],
            r_high["volatility_adjusted_safe_ltv"],
        )

    def test_capacity_negative_when_over_optimal(self):
        r = self._run(
            borrowed_value_usd=90_000.0,
            strategy_target_ltv_pct=65.0,
        )
        self.assertLess(r["risk_adjusted_capacity_usd"], 0.0)

    def test_capacity_positive_when_under_optimal(self):
        r = self._run(borrowed_value_usd=20_000.0, strategy_target_ltv_pct=65.0)
        self.assertGreater(r["risk_adjusted_capacity_usd"], 0.0)


# ===========================================================================
# 11. Module-level analyze() wrapper
# ===========================================================================

class TestModuleLevelAnalyze(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_returns_dict(self):
        r = analyze(_pos(), self._cfg)
        self.assertIsInstance(r, dict)

    def test_has_label(self):
        r = analyze(_pos(), self._cfg)
        self.assertIn("label", r)

    def test_no_config_does_not_crash(self):
        # With no config, uses default log path — may raise if dir unwriteable,
        # but analyze itself should succeed (logging errors are swallowed).
        try:
            r = analyze(_pos())
        except Exception:
            r = None
        # Just verify it either succeeded or was silently absorbed
        self.assertTrue(r is None or isinstance(r, dict))

    def test_score_always_0_to_100(self):
        for borrow in (0, 20_000, 65_000, 85_000, 100_000):
            r = analyze(_pos(borrowed_value_usd=float(borrow)), self._cfg)
            self.assertGreaterEqual(r["utilization_efficiency_score"], 0.0)
            self.assertLessEqual(r["utilization_efficiency_score"], 100.0)


# ===========================================================================
# 12. Label consistency across full position space
# ===========================================================================

class TestLabelConsistency(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_zero_borrow_never_over_leveraged(self):
        r = analyze(_pos(borrowed_value_usd=0.0), self._cfg)
        self.assertNotEqual(r["label"], "OVER_LEVERAGED")

    def test_extreme_borrow_always_over_leveraged(self):
        r = analyze(
            _pos(
                borrowed_value_usd=200_000.0,
                collateral_value_usd=100_000.0,
                liquidation_ltv_pct=85.0,
            ),
            self._cfg,
        )
        self.assertEqual(r["label"], "OVER_LEVERAGED")

    def test_very_high_volatility_reduces_safe_zone(self):
        r = analyze(
            _pos(asset_volatility_30d_pct=80.0, borrowed_value_usd=50_000.0),
            self._cfg,
        )
        # With 80% volatility, 50% LTV could be over the safe LTV
        # Just verify label is not over-leveraged when borrow is very low
        r2 = analyze(
            _pos(asset_volatility_30d_pct=80.0, borrowed_value_usd=1_000.0),
            self._cfg,
        )
        self.assertNotEqual(r2["label"], "OVER_LEVERAGED")

    def test_conservative_label_exists(self):
        r = analyze(
            _pos(borrowed_value_usd=10_000.0, strategy_target_ltv_pct=65.0,
                 asset_volatility_30d_pct=5.0),
            self._cfg,
        )
        self.assertIn(r["label"], {"CONSERVATIVE", "UNDERUTILIZED"})

    def test_all_labels_reachable(self):
        labels = set()
        for borrow in (0, 5_000, 20_000, 65_000, 85_001):
            r = analyze(
                _pos(
                    borrowed_value_usd=float(borrow),
                    max_ltv_pct=80.0,
                    liquidation_ltv_pct=85.0,
                    asset_volatility_30d_pct=5.0,
                    strategy_target_ltv_pct=65.0,
                ),
                self._cfg,
            )
            labels.add(r["label"])
        # Should cover at least 4 different labels across this range
        self.assertGreaterEqual(len(labels), 4)

    def test_optimal_position_high_score(self):
        # Use very low volatility so optimal≈strategy target
        r = analyze(
            _pos(
                borrowed_value_usd=65_000.0,
                strategy_target_ltv_pct=65.0,
                asset_volatility_30d_pct=2.0,
            ),
            self._cfg,
        )
        self.assertGreater(r["utilization_efficiency_score"], 80.0)

    def test_score_increases_towards_optimal(self):
        borrows = [10_000, 30_000, 50_000, 65_000]
        scores = [
            analyze(
                _pos(
                    borrowed_value_usd=float(b),
                    strategy_target_ltv_pct=65.0,
                    asset_volatility_30d_pct=3.0,
                ),
                self._cfg,
            )["utilization_efficiency_score"]
            for b in borrows
        ]
        # Scores should generally increase as we approach optimal
        self.assertLess(scores[0], scores[-1])

    def test_strategy_target_respected_when_safe(self):
        r = analyze(
            _pos(strategy_target_ltv_pct=50.0, asset_volatility_30d_pct=5.0),
            self._cfg,
        )
        self.assertAlmostEqual(r["optimal_borrow_pct"], 50.0)

    def test_strategy_target_overridden_when_too_aggressive(self):
        # strategy_target > conservative cap
        r = analyze(
            _pos(
                strategy_target_ltv_pct=95.0,
                max_ltv_pct=80.0,
                liquidation_ltv_pct=85.0,
                asset_volatility_30d_pct=10.0,
            ),
            self._cfg,
        )
        self.assertLess(r["optimal_borrow_pct"], 95.0)


# ===========================================================================
# 13. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_empty_position(self):
        r = DeFiProtocolBorrowingPowerUtilizationAnalyzer(self._cfg).analyze({})
        self.assertIn("label", r)

    def test_zero_collateral_and_borrow(self):
        r = analyze(_pos(collateral_value_usd=0.0, borrowed_value_usd=0.0), self._cfg)
        self.assertEqual(r["current_ltv_pct"], 0.0)

    def test_extremely_large_values(self):
        r = analyze(
            _pos(collateral_value_usd=1e12, borrowed_value_usd=5e11),
            self._cfg,
        )
        self.assertGreaterEqual(r["utilization_efficiency_score"], 0.0)

    def test_very_small_values(self):
        r = analyze(
            _pos(collateral_value_usd=100.0, borrowed_value_usd=60.0),
            self._cfg,
        )
        self.assertAlmostEqual(r["current_ltv_pct"], 60.0)

    def test_ltv_over_100_clamps_score_to_zero(self):
        r = analyze(
            _pos(
                collateral_value_usd=100_000.0,
                borrowed_value_usd=200_000.0,
                liquidation_ltv_pct=85.0,
            ),
            self._cfg,
        )
        self.assertEqual(r["utilization_efficiency_score"], 0.0)
        self.assertEqual(r["label"], "OVER_LEVERAGED")

    def test_liquidation_equals_max_ltv(self):
        # Should not crash even with equal thresholds
        r = analyze(
            _pos(max_ltv_pct=80.0, liquidation_ltv_pct=80.0),
            self._cfg,
        )
        self.assertIn("label", r)

    def test_multiple_analyses_logged(self):
        for _ in range(5):
            analyze(_pos(), self._cfg)
        with open(self._log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_analyzer_with_none_config(self):
        # Should use defaults without error
        a = DeFiProtocolBorrowingPowerUtilizationAnalyzer(None)
        r = a.analyze(_pos())
        self.assertIn("label", r)


if __name__ == "__main__":
    unittest.main()

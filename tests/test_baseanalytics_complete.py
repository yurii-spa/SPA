"""
tests/test_baseanalytics_complete.py

MP-1438 — 15 tests: all 37 analytics modules (Phase 1+2+3) import correctly
and have BaseAnalytics in their MRO.

Sprint v10.54
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.base import BaseAnalytics

# ── Phase registries (must match baseanalytics_migration_summary.py) ──────────

PHASE_1 = [
    "apy_tracker",
    "protocol_risk_scorer",
    "liquidity_stress_simulator",
    "apy_milestone_tracker",
    "rebalance_trigger_engine",
]

PHASE_2 = [
    "apy_anomaly_detector",
    "capital_efficiency_tracker",
    "daily_operations_report",
    "defi_protocol_interest_rate_sensitivity_analyzer",
    "defi_protocol_lending_utilization_cliff_detector",
    "defi_protocol_wrapped_asset_peg_deviation_analyzer",
    "defillama_feed_monitor",
    "evidence_auto_calculator",
    "golive_readiness_report",
    "investment_memo_generator",
    "liquidation_risk_heatmap",
    "paper_backtest_drift_v2",
    "paper_evidence_tracker_v2",
    "portfolio_heat_map",
    "protocol_data_audit",
    "protocol_defi_liquidity_depth_impact_analyzer",
    "protocol_defi_lp_fee_vs_il_breakeven_analyzer",
    "protocol_defi_smart_contract_upgrade_risk_analyzer",
    "protocol_liquidity_depth_analyzer",
    "protocol_tvl_filter",
]

PHASE_3 = [
    "regime_adjusted_allocator",
    "rs001_stress_engine",
    "research_summary_report",
    "rs001_live_apy_engine",
    "rs002_live_apy_engine",
    "rs002_position_tracker",
    "source_acquisition_tracker",
    "stablecoin_yield_optimizer",
    "t1_data_verifier",
    # Batch C — MP-1437/1438
    "rebalance_cost_estimator",
    "yield_compressor_score",
    "yield_forecast_engine",
]

ALL_MODULES = PHASE_1 + PHASE_2 + PHASE_3


def _has_base_analytics(module_name: str) -> tuple[bool, str]:
    """Import module and return (ok, class_name_or_error)."""
    try:
        mod = importlib.import_module(f"spa_core.analytics.{module_name}")
    except Exception as exc:
        return False, f"ImportError: {exc}"

    classes = [
        obj for _, obj in vars(mod).items()
        if isinstance(obj, type) and obj.__module__ == mod.__name__
    ]
    for cls in classes:
        if BaseAnalytics in cls.__mro__:
            return True, cls.__name__
    return False, f"no class inherits BaseAnalytics (found: {[c.__name__ for c in classes]})"


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBaseAnalyticsTotalCount(unittest.TestCase):
    """TC-BAC-01: Total count is 37."""

    def test_01_total_module_count_is_37(self):
        """ALL_MODULES contains exactly 37 entries."""
        self.assertEqual(len(ALL_MODULES), 37)


class TestPhase1Migration(unittest.TestCase):
    """TC-BAC-02: All 5 Phase 1 modules pass."""

    def test_02_phase1_all_inherit_base_analytics(self):
        """All 5 Phase 1 modules have BaseAnalytics in MRO."""
        for mod_name in PHASE_1:
            with self.subTest(module=mod_name):
                ok, msg = _has_base_analytics(mod_name)
                self.assertTrue(ok, f"{mod_name}: {msg}")


class TestPhase2Migration(unittest.TestCase):
    """TC-BAC-03: All 20 Phase 2 modules pass."""

    def test_03_phase2_all_inherit_base_analytics(self):
        """All 20 Phase 2 modules have BaseAnalytics in MRO."""
        for mod_name in PHASE_2:
            with self.subTest(module=mod_name):
                ok, msg = _has_base_analytics(mod_name)
                self.assertTrue(ok, f"{mod_name}: {msg}")


class TestPhase3BatchAMigration(unittest.TestCase):
    """TC-BAC-04: Phase 3 Batch A modules pass."""

    def test_04_phase3_batch_a(self):
        """Phase 3 Batch A (6 modules) all inherit BaseAnalytics."""
        batch_a = PHASE_3[:6]
        for mod_name in batch_a:
            with self.subTest(module=mod_name):
                ok, msg = _has_base_analytics(mod_name)
                self.assertTrue(ok, f"{mod_name}: {msg}")


class TestPhase3BatchBMigration(unittest.TestCase):
    """TC-BAC-05: Phase 3 Batch B modules pass."""

    def test_05_phase3_batch_b(self):
        """Phase 3 Batch B (3 modules) all inherit BaseAnalytics."""
        batch_b = PHASE_3[6:9]
        for mod_name in batch_b:
            with self.subTest(module=mod_name):
                ok, msg = _has_base_analytics(mod_name)
                self.assertTrue(ok, f"{mod_name}: {msg}")


class TestPhase3BatchCMigration(unittest.TestCase):
    """TC-BAC-06..08: Phase 3 Batch C — the 3 newly migrated modules."""

    def test_06_rebalance_cost_estimator_inherits_base(self):
        """RebalanceCostEstimator has BaseAnalytics in MRO."""
        from spa_core.analytics.rebalance_cost_estimator import RebalanceCostEstimator
        self.assertIn(BaseAnalytics, RebalanceCostEstimator.__mro__)

    def test_07_yield_compressor_score_inherits_base(self):
        """YieldCompressorScore has BaseAnalytics in MRO."""
        from spa_core.analytics.yield_compressor_score import YieldCompressorScore
        self.assertIn(BaseAnalytics, YieldCompressorScore.__mro__)

    def test_08_yield_forecast_engine_inherits_base(self):
        """YieldForecastEngine has BaseAnalytics in MRO."""
        from spa_core.analytics.yield_forecast_engine import YieldForecastEngine
        self.assertIn(BaseAnalytics, YieldForecastEngine.__mro__)


class TestOutputPaths(unittest.TestCase):
    """TC-BAC-09..11: New modules have OUTPUT_PATH set."""

    def test_09_rebalance_cost_estimator_output_path(self):
        """RebalanceCostEstimator.OUTPUT_PATH is non-empty."""
        from spa_core.analytics.rebalance_cost_estimator import RebalanceCostEstimator
        self.assertTrue(RebalanceCostEstimator.OUTPUT_PATH)

    def test_10_yield_compressor_score_output_path(self):
        """YieldCompressorScore.OUTPUT_PATH is non-empty."""
        from spa_core.analytics.yield_compressor_score import YieldCompressorScore
        self.assertTrue(YieldCompressorScore.OUTPUT_PATH)

    def test_11_yield_forecast_engine_output_path(self):
        """YieldForecastEngine.OUTPUT_PATH is non-empty."""
        from spa_core.analytics.yield_forecast_engine import YieldForecastEngine
        self.assertTrue(YieldForecastEngine.OUTPUT_PATH)


class TestToDictAbstractMethod(unittest.TestCase):
    """TC-BAC-12..14: New modules implement to_dict()."""

    def test_12_rebalance_cost_estimator_to_dict(self):
        """RebalanceCostEstimator().to_dict() returns a dict."""
        from spa_core.analytics.rebalance_cost_estimator import RebalanceCostEstimator
        result = RebalanceCostEstimator().to_dict()
        self.assertIsInstance(result, dict)

    def test_13_yield_compressor_score_to_dict(self):
        """YieldCompressorScore().to_dict() returns a dict."""
        from spa_core.analytics.yield_compressor_score import YieldCompressorScore
        result = YieldCompressorScore().to_dict()
        self.assertIsInstance(result, dict)

    def test_14_yield_forecast_engine_to_dict(self):
        """YieldForecastEngine().to_dict() returns a dict."""
        from spa_core.analytics.yield_forecast_engine import YieldForecastEngine
        result = YieldForecastEngine().to_dict()
        self.assertIsInstance(result, dict)


class TestGrandTotal(unittest.TestCase):
    """TC-BAC-15: Full 37/37 sweep."""

    def test_15_all_37_modules_pass(self):
        """All 37 analytics modules (Phase 1+2+3) have BaseAnalytics in MRO."""
        failures = []
        for mod_name in ALL_MODULES:
            ok, msg = _has_base_analytics(mod_name)
            if not ok:
                failures.append(f"{mod_name}: {msg}")
        self.assertEqual(
            failures, [],
            msg=f"Failed modules ({len(failures)}):\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

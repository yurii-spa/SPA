"""
tests/test_baseanalytics_phase2.py — MP-1422 (v10.38)

20 tests verifying that all Phase 2 modules (Batch A + Batch B) are correctly
migrated to BaseAnalytics:
  - Module imports without error
  - Class inherits from BaseAnalytics (present in MRO)
  - OUTPUT_PATH class attribute is set and non-empty
  - save() and load() methods are accessible (inherited or overridden)

Phase 2 modules (20 total):
  Batch A: apy_anomaly_detector, capital_efficiency_tracker,
           daily_operations_report, defi_protocol_interest_rate_sensitivity_analyzer,
           defi_protocol_lending_utilization_cliff_detector,
           defi_protocol_wrapped_asset_peg_deviation_analyzer,
           defillama_feed_monitor, evidence_auto_calculator,
           golive_readiness_report, investment_memo_generator
  Batch B: liquidation_risk_heatmap, paper_backtest_drift_v2,
           paper_evidence_tracker_v2, portfolio_heat_map, protocol_data_audit,
           protocol_defi_liquidity_depth_impact_analyzer,
           protocol_defi_lp_fee_vs_il_breakeven_analyzer,
           protocol_defi_smart_contract_upgrade_risk_analyzer,
           protocol_liquidity_depth_analyzer, protocol_tvl_filter
"""
from __future__ import annotations

import importlib
import unittest

from spa_core.base import BaseAnalytics


# ── Helpers ───────────────────────────────────────────────────────────────────

def _import_class(module_path: str, class_name: str):
    """Import and return the named class, or raise AssertionError on failure."""
    try:
        mod = importlib.import_module(module_path)
    except Exception as exc:
        raise AssertionError(f"Failed to import {module_path}: {exc}") from exc
    cls = getattr(mod, class_name, None)
    if cls is None:
        raise AssertionError(f"{class_name} not found in {module_path}")
    return cls


def _assert_migrated(test: unittest.TestCase, module_path: str, class_name: str) -> None:
    """Unified assertion: import, check MRO, OUTPUT_PATH, save, load, to_dict."""
    cls = _import_class(module_path, class_name)

    # 1. Inherits BaseAnalytics
    test.assertIn(
        BaseAnalytics, cls.__mro__,
        f"{class_name} must have BaseAnalytics in MRO",
    )

    # 2. OUTPUT_PATH is set
    test.assertTrue(
        hasattr(cls, "OUTPUT_PATH") and cls.OUTPUT_PATH,
        f"{class_name}.OUTPUT_PATH must be set",
    )

    # 3. save() accessible
    test.assertTrue(
        callable(getattr(cls, "save", None)),
        f"{class_name}.save() must be callable",
    )

    # 4. load() accessible
    test.assertTrue(
        callable(getattr(cls, "load", None)),
        f"{class_name}.load() must be callable",
    )

    # 5. to_dict() implemented in class body (not abstract)
    test.assertIn(
        "to_dict", cls.__dict__,
        f"{class_name}.to_dict() must be implemented (not left abstract)",
    )


# ── Batch A Tests (10) ────────────────────────────────────────────────────────

class TestBatchAAPYAnomalyDetector(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.apy_anomaly_detector",
            "APYAnomalyDetector")


class TestBatchACapitalEfficiencyTracker(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.capital_efficiency_tracker",
            "CapitalEfficiencyTracker")


class TestBatchADailyOperationsReport(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.daily_operations_report",
            "DailyOperationsReport")


class TestBatchAInterestRateSensitivityAnalyzer(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.defi_protocol_interest_rate_sensitivity_analyzer",
            "DeFiProtocolInterestRateSensitivityAnalyzer")


class TestBatchALendingUtilizationCliffDetector(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.defi_protocol_lending_utilization_cliff_detector",
            "DeFiProtocolLendingUtilizationCliffDetector")


class TestBatchAWrappedAssetPegDeviationAnalyzer(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer",
            "DeFiProtocolWrappedAssetPegDeviationAnalyzer")


class TestBatchADeFiLlamaFeedMonitor(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.defillama_feed_monitor",
            "DeFiLlamaFeedMonitor")


class TestBatchAEvidenceAutoCalculator(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.evidence_auto_calculator",
            "EvidenceAutoCalculator")


class TestBatchAGoLiveReadinessReport(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.golive_readiness_report",
            "GoLiveReadinessReport")


class TestBatchAInvestmentMemoGenerator(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.investment_memo_generator",
            "InvestmentMemoGenerator")


# ── Batch B Tests (10) ────────────────────────────────────────────────────────

class TestBatchBLiquidationRiskHeatmap(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.liquidation_risk_heatmap",
            "LiquidationRiskHeatmap")


class TestBatchBPaperBacktestDriftV2(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.paper_backtest_drift_v2",
            "PaperBacktestDriftV2")


class TestBatchBPaperEvidenceTrackerV2(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.paper_evidence_tracker_v2",
            "PaperEvidenceTrackerV2")


class TestBatchBPortfolioHeatMapGenerator(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.portfolio_heat_map",
            "PortfolioHeatMapGenerator")


class TestBatchBProtocolDataAudit(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.protocol_data_audit",
            "ProtocolDataAudit")


class TestBatchBLiquidityDepthImpactAnalyzer(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.protocol_defi_liquidity_depth_impact_analyzer",
            "ProtocolDeFiLiquidityDepthImpactAnalyzer")


class TestBatchBLPFeeVsILBreakevenAnalyzer(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer",
            "ProtocolDeFiLPFeeVsILBreakevenAnalyzer")


class TestBatchBSmartContractUpgradeRiskAnalyzer(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer",
            "ProtocolDeFiSmartContractUpgradeRiskAnalyzer")


class TestBatchBProtocolLiquidityDepthAnalyzer(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.protocol_liquidity_depth_analyzer",
            "ProtocolLiquidityDepthAnalyzer")


class TestBatchBProtocolTVLFilter(unittest.TestCase):
    def test_baseanalytics_migration(self):
        _assert_migrated(self,
            "spa_core.analytics.protocol_tvl_filter",
            "ProtocolTVLFilter")


if __name__ == "__main__":
    unittest.main()

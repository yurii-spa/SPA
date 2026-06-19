#!/usr/bin/env python3
"""
verify_phase2_migration.py — MP-1421/MP-1422

Verifies that all Phase 1 + Phase 2 modules correctly inherit BaseAnalytics
and implement the required to_dict() method.

Usage:
    python3 scripts/verify_phase2_migration.py
"""
from __future__ import annotations

import importlib
import sys
import os

# Ensure spa_core is importable from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.base import BaseAnalytics

# ── Phase 1 ──────────────────────────────────────────────────────────────────

PHASE1_MODULES = [
    ("spa_core.analytics.apy_tracker",               "APYTracker"),
    ("spa_core.analytics.protocol_risk_scorer",      "ProtocolRiskScorer"),
    ("spa_core.analytics.liquidity_stress_simulator","LiquidityStressSimulator"),
    ("spa_core.analytics.apy_milestone_tracker",     "ApyMilestoneTracker"),
    ("spa_core.analytics.rebalance_trigger_engine",  "RebalanceTriggerEngine"),
]

# ── Phase 2 Batch A ───────────────────────────────────────────────────────────

PHASE2A_MODULES = [
    ("spa_core.analytics.apy_anomaly_detector",
     "APYAnomalyDetector"),
    ("spa_core.analytics.capital_efficiency_tracker",
     "CapitalEfficiencyTracker"),
    ("spa_core.analytics.daily_operations_report",
     "DailyOperationsReport"),
    ("spa_core.analytics.defi_protocol_interest_rate_sensitivity_analyzer",
     "DeFiProtocolInterestRateSensitivityAnalyzer"),
    ("spa_core.analytics.defi_protocol_lending_utilization_cliff_detector",
     "DeFiProtocolLendingUtilizationCliffDetector"),
    ("spa_core.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer",
     "DeFiProtocolWrappedAssetPegDeviationAnalyzer"),
    ("spa_core.analytics.defillama_feed_monitor",
     "DeFiLlamaFeedMonitor"),
    ("spa_core.analytics.evidence_auto_calculator",
     "EvidenceAutoCalculator"),
    ("spa_core.analytics.golive_readiness_report",
     "GoLiveReadinessReport"),
    ("spa_core.analytics.investment_memo_generator",
     "InvestmentMemoGenerator"),
]

# ── Phase 2 Batch B ───────────────────────────────────────────────────────────

PHASE2B_MODULES = [
    ("spa_core.analytics.liquidation_risk_heatmap",
     "LiquidationRiskHeatmap"),
    ("spa_core.analytics.paper_backtest_drift_v2",
     "PaperBacktestDriftV2"),
    ("spa_core.analytics.paper_evidence_tracker_v2",
     "PaperEvidenceTrackerV2"),
    ("spa_core.analytics.portfolio_heat_map",
     "PortfolioHeatMapGenerator"),
    ("spa_core.analytics.protocol_data_audit",
     "ProtocolDataAudit"),
    ("spa_core.analytics.protocol_defi_liquidity_depth_impact_analyzer",
     "ProtocolDeFiLiquidityDepthImpactAnalyzer"),
    ("spa_core.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer",
     "ProtocolDeFiLPFeeVsILBreakevenAnalyzer"),
    ("spa_core.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer",
     "ProtocolDeFiSmartContractUpgradeRiskAnalyzer"),
    ("spa_core.analytics.protocol_liquidity_depth_analyzer",
     "ProtocolLiquidityDepthAnalyzer"),
    ("spa_core.analytics.protocol_tvl_filter",
     "ProtocolTVLFilter"),
]

ALL_MODULES = PHASE1_MODULES + PHASE2A_MODULES + PHASE2B_MODULES

GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def verify_module(module_path: str, class_name: str) -> bool:
    """Returns True if the class passes all checks."""
    all_ok = True

    try:
        mod = importlib.import_module(module_path)
    except Exception as e:
        fail(f"{module_path}: import failed — {e}")
        return False

    cls = getattr(mod, class_name, None)
    if cls is None:
        fail(f"{class_name} not found in {module_path}")
        return False

    # Check 1: inherits BaseAnalytics
    if issubclass(cls, BaseAnalytics) and cls is not BaseAnalytics:
        ok(f"{class_name}: inherits BaseAnalytics")
    else:
        fail(f"{class_name}: does NOT inherit BaseAnalytics")
        all_ok = False

    # Check 2: has OUTPUT_PATH
    if hasattr(cls, "OUTPUT_PATH") and cls.OUTPUT_PATH:
        ok(f"{class_name}: OUTPUT_PATH = {cls.OUTPUT_PATH!r}")
    else:
        fail(f"{class_name}: missing OUTPUT_PATH")
        all_ok = False

    # Check 3: implements to_dict (in MRO, not abstract)
    if "to_dict" in cls.__dict__:
        ok(f"{class_name}: to_dict() implemented")
    else:
        fail(f"{class_name}: to_dict() not implemented in class body")
        all_ok = False

    return all_ok


def main() -> int:
    print("BaseAnalytics Phase 1 + Phase 2 Migration Verification")
    print("=" * 60)

    sections = [
        ("Phase 1 (MP-1406)", PHASE1_MODULES),
        ("Phase 2 Batch A (MP-1421)", PHASE2A_MODULES),
        ("Phase 2 Batch B (MP-1422)", PHASE2B_MODULES),
    ]

    passed = 0
    failed = 0

    for section_name, modules in sections:
        print(f"\n{CYAN}── {section_name} ──{RESET}")
        for module_path, class_name in modules:
            print(f"\n[{module_path.split('.')[-1]}]")
            if verify_module(module_path, class_name):
                passed += 1
            else:
                failed += 1

    print("\n" + "=" * 60)
    total = passed + failed
    status = GREEN + "PASS" + RESET if failed == 0 else RED + "FAIL" + RESET
    print(f"Result: {status}  ({passed}/{total} modules verified)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

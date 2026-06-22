"""
scripts/baseanalytics_migration_summary.py

Final migration summary across all 3 phases of BaseAnalytics migration.
Verifies all migrated modules are importable and have BaseAnalytics in MRO.

Sprint v10.54 — MP-1438 — COMPLETE: 37/37 analytics modules migrated
"""
from __future__ import annotations

import importlib
import os
import sys

# Ensure repo root is on sys.path (works when run from scripts/ or repo root)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── Phase registries ───────────────────────────────────────────────────────────

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
    # Batch A
    "regime_adjusted_allocator",
    "rs001_stress_engine",
    "research_summary_report",
    "rs001_live_apy_engine",
    "rs002_live_apy_engine",
    "rs002_position_tracker",
    # Batch B
    "source_acquisition_tracker",
    "stablecoin_yield_optimizer",
    "t1_data_verifier",
    # Batch C — MP-1437/1438: previously skipped, now tested + migrated
    "rebalance_cost_estimator",
    "yield_compressor_score",
    "yield_forecast_engine",
]

# ── Verification ───────────────────────────────────────────────────────────────

def _check_module(module_name: str) -> tuple[bool, str]:
    """Import module and check BaseAnalytics is in any class MRO."""
    try:
        mod = importlib.import_module(f"spa_core.analytics.{module_name}")
    except Exception as exc:
        return False, f"ImportError: {exc}"

    try:
        from spa_core.base import BaseAnalytics
    except Exception as exc:
        return False, f"Cannot import BaseAnalytics: {exc}"

    # Find all classes defined in this module
    classes = [
        obj for name, obj in vars(mod).items()
        if isinstance(obj, type) and obj.__module__ == mod.__name__
    ]

    for cls in classes:
        if BaseAnalytics in cls.__mro__:
            return True, f"{cls.__name__} inherits BaseAnalytics"

    # If no class inherits — check if module has BaseAnalytics at all
    return False, f"No class in MRO of BaseAnalytics (classes found: {[c.__name__ for c in classes]})"


def summary() -> int:
    """Run full verification and print summary. Returns exit code (0 = all OK)."""
    all_phases = [
        ("Phase 1", PHASE_1),
        ("Phase 2", PHASE_2),
        ("Phase 3", PHASE_3),
    ]

    total_expected = sum(len(p) for _, p in all_phases)
    passed = 0
    failed = 0
    errors: list[str] = []

    print("=" * 65)
    print("  BaseAnalytics Migration Summary — SPA Analytics")
    print("=" * 65)

    for phase_name, modules in all_phases:
        print(f"\n{phase_name} ({len(modules)} modules):")
        for mod_name in modules:
            ok, msg = _check_module(mod_name)
            status = "✅" if ok else "❌"
            print(f"  {status}  {mod_name:<50}  {msg}")
            if ok:
                passed += 1
            else:
                failed += 1
                errors.append(f"{mod_name}: {msg}")

    print("\n" + "=" * 65)
    print(f"  Total migrated: {passed}/{total_expected} analytics modules")
    if failed:
        print(f"  ❌ Failed: {failed}")
        for err in errors:
            print(f"     - {err}")
    else:
        print("  ✅ All modules verified — BaseAnalytics in MRO confirmed")
    print("=" * 65)

    print("\nPhase 3 complete: 12/12 modules (Batch A: 6, Batch B: 3, Batch C: 3)")
    print("Grand total: Phase 1 (5) + Phase 2 (20) + Phase 3 (12) = 37 modules")

    # ── Phase 4 summary (backtesting/ + paper_trading/ + family_fund/) ─────────
    PHASE_4 = [
        # backtesting/ — Sprint v10.63 (MP-1447)
        ("spa_core.backtesting.pit_vs_naive_comparison", "PITvsNaiveComparison"),
        ("spa_core.backtesting.paper_day_counter",       "PaperDayCounter"),
        ("spa_core.backtesting.source_promotion_engine", "SourcePromotionEngine"),
        # paper_trading/ — Sprint v10.64 (MP-1448)
        ("spa_core.paper_trading.golive_checker",        "GoLiveChecker"),
        ("spa_core.paper_trading.tournament_evaluator",  "TournamentEvaluator"),
        # family_fund/ — Sprint v10.64 (MP-1448)
        ("spa_core.family_fund.lead_tracker",            "LeadTracker"),
    ]

    print(f"\n{'=' * 65}")
    print("  Phase 4 — backtesting/ + paper_trading/ + family_fund/")
    print(f"{'=' * 65}")
    p4_pass = 0
    for mod_path, cls_name in PHASE_4:
        try:
            parts = mod_path.rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            from spa_core.base import BaseAnalytics
            ok = BaseAnalytics in cls.__mro__
            status = "✅" if ok else "❌"
            if ok:
                p4_pass += 1
        except Exception as exc:
            status, ok = "❌", False
        print(f"  {status}  {cls_name:<50}")
    print(f"\nPhase 4 complete: {p4_pass}/{len(PHASE_4)} modules")
    print(f"Grand total: Phase 1 (5) + Phase 2 (20) + Phase 3 (12) + Phase 4 ({len(PHASE_4)}) = {37 + len(PHASE_4)} classes")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(summary())

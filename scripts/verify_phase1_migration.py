#!/usr/bin/env python3
"""
verify_phase1_migration.py — MP-1406

Verifies that all Phase 1 modules correctly inherit BaseAnalytics
and implement the required to_dict() method.

Usage:
    python3 scripts/verify_phase1_migration.py
"""
from __future__ import annotations

import importlib
import sys
import os

# Ensure spa_core is importable from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.base import BaseAnalytics

PHASE1_MODULES = [
    ("spa_core.analytics.apy_tracker",              "APYTracker"),
    ("spa_core.analytics.protocol_risk_scorer",     "ProtocolRiskScorer"),
    ("spa_core.analytics.liquidity_stress_simulator","LiquidityStressSimulator"),
    ("spa_core.analytics.apy_milestone_tracker",    "ApyMilestoneTracker"),
    ("spa_core.analytics.rebalance_trigger_engine", "RebalanceTriggerEngine"),
]

GREEN = "\033[92m"
RED   = "\033[91m"
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

    # Check 3: implements to_dict (not abstract)
    if "to_dict" in cls.__dict__:
        ok(f"{class_name}: to_dict() implemented")
    else:
        fail(f"{class_name}: to_dict() not implemented in class body")
        all_ok = False

    return all_ok


def main() -> int:
    print("BaseAnalytics Phase 1 Migration Verification")
    print("=" * 50)

    passed = 0
    failed = 0

    for module_path, class_name in PHASE1_MODULES:
        print(f"\n[{module_path.split('.')[-1]}]")
        if verify_module(module_path, class_name):
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 50)
    total = passed + failed
    status = GREEN + "PASS" + RESET if failed == 0 else RED + "FAIL" + RESET
    print(f"Result: {status}  ({passed}/{total} modules verified)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

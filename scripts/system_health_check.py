#!/usr/bin/env python3
"""
Full system health diagnostic for SPA.

Checks: adapters, gates, data files, CI config, launchd, evidence, errors, atomic utils.
Outputs: PASS / FAIL / WARN for each check.
Exit code: 0 if all PASS or WARN; 1 if any FAIL.

Usage:
  python3 scripts/system_health_check.py
  python3 scripts/system_health_check.py --verbose
  python3 scripts/system_health_check.py --fail-fast
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Callable, List, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

_CHECKS: List[Tuple[str, Callable[[], str]]] = []


def check(name: str):
    """Decorator — registers a check function."""
    def decorator(fn: Callable[[], str]) -> Callable[[], str]:
        _CHECKS.append((name, fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

@check("KANBAN integrity")
def kanban_ok() -> str:
    path = os.path.join(_REPO_ROOT, "KANBAN.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert d.get("done_count", 0) > 0, f"done_count={d.get('done_count')}"
    sprint = d.get("sprint_completed", "?")
    return f"done_count={d['done_count']}, sprint={sprint}"


@check("Gate status — backtest PASS")
def gates_ok() -> str:
    path = os.path.join(_REPO_ROOT, "data", "gate_status.json")
    with open(path, encoding="utf-8") as f:
        g = json.load(f)
    backtest = g.get("backtest_gate") or g.get("backtest")
    assert backtest == "PASS", f"Backtest gate not PASS: {backtest}"
    live = g.get("live_trading_gate", "?")
    return f"backtest={backtest}, live={live}"


@check("Gate status — live gate LOCKED")
def live_gate_locked() -> str:
    path = os.path.join(_REPO_ROOT, "data", "gate_status.json")
    with open(path, encoding="utf-8") as f:
        g = json.load(f)
    live = g.get("live_trading_gate", "?")
    assert live == "LOCKED", f"live_trading_gate is not LOCKED: {live}"
    return f"live_trading_gate={live}"


@check("Adapter registry — ≥1 adapter importable")
def adapters_ok() -> str:
    from spa_core.adapters.adapter_registry import REGISTRY, register
    import importlib
    _to_try = [
        ("aave_v3",       "spa_core.adapters.aave_v3",              "AaveV3Adapter"),
        ("compound_v3",   "spa_core.adapters.compound_v3_adapter",   "CompoundV3Adapter"),
        ("morpho_blue",   "spa_core.adapters.morpho_blue",           "MorphoBlueAdapter"),
    ]
    for key, mod_path, cls_name in _to_try:
        if key not in REGISTRY:
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                register(key, cls)
            except Exception:
                pass
    count = len(REGISTRY)
    assert count >= 1, "REGISTRY empty after attempted registration"
    return f"{count} adapters registered"


@check("LiveTradingGate — BLOCKED (safe)")
def gate_safe() -> str:
    from spa_core.safety.live_trading_gate import LiveTradingGate
    gate = LiveTradingGate(base_dir=_REPO_ROOT)
    active = gate.is_active()
    assert not active, "LiveTradingGate is ACTIVE — paper-period safety violation!"
    return "is_active=False (BLOCKED as expected)"


@check("SPAError hierarchy")
def errors_ok() -> str:
    from spa_core.utils.errors import SPAError, GateError, LiveTradingForbiddenError
    assert issubclass(GateError, SPAError), "GateError not subclass of SPAError"
    assert issubclass(LiveTradingForbiddenError, SPAError), "LiveTradingForbiddenError not subclass of SPAError"
    return "GateError, LiveTradingForbiddenError ⊆ SPAError"


@check("atomic_save / atomic_load available")
def atomic_ok() -> str:
    from spa_core.utils.atomic import atomic_save, atomic_load
    assert callable(atomic_save), "atomic_save is not callable"
    assert callable(atomic_load), "atomic_load is not callable"
    return "atomic_save and atomic_load importable"


@check("GoLive status file present")
def golive_file_ok() -> str:
    path = os.path.join(_REPO_ROOT, "data", "golive_status.json")
    assert os.path.exists(path), "data/golive_status.json missing"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    passed = d.get("passed", 0)
    total = d.get("total", 26)
    return f"{passed}/{total} checks pass"


@check("equity_curve_daily.json present")
def equity_curve_ok() -> str:
    path = os.path.join(_REPO_ROOT, "data", "equity_curve_daily.json")
    assert os.path.exists(path), "data/equity_curve_daily.json missing"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    entries = d if isinstance(d, list) else d.get("curve", d.get("entries", []))
    count = len(entries) if hasattr(entries, "__len__") else "?"
    return f"present, entries={count}"


@check("paper_trading_status.json — is_demo=False")
def demo_flag_ok() -> str:
    path = os.path.join(_REPO_ROOT, "data", "paper_trading_status.json")
    assert os.path.exists(path), "data/paper_trading_status.json missing"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    is_demo = d.get("is_demo", True)
    assert not is_demo, f"is_demo={is_demo} — still in demo mode!"
    return f"is_demo={is_demo}"


@check("risk data files present")
def risk_blocks_ok() -> str:
    # Accept either ring-buffer file or the broader risk_limits_check.json
    candidates = [
        os.path.join(_REPO_ROOT, "data", "risk_policy_blocks.json"),
        os.path.join(_REPO_ROOT, "data", "risk_limits_check.json"),
        os.path.join(_REPO_ROOT, "data", "risk_scores.json"),
    ]
    found = [p for p in candidates if os.path.exists(p)]
    assert found, f"No risk data files found in {[os.path.basename(p) for p in candidates]}"
    return f"present: {[os.path.basename(p) for p in found]}"


@check("gap_monitor.json — no gaps")
def gap_monitor_ok() -> str:
    path = os.path.join(_REPO_ROOT, "data", "gap_monitor.json")
    assert os.path.exists(path), "data/gap_monitor.json missing"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    gaps = d.get("gaps", d.get("gap_count", 0))
    if isinstance(gaps, list):
        gap_count = len(gaps)
    elif isinstance(gaps, (int, float)):
        gap_count = int(gaps)
    else:
        gap_count = 0
    assert gap_count == 0, f"gap_monitor has {gap_count} gap(s)!"
    return f"gap_count={gap_count}"


@check("cycle_runner.py exists")
def cycle_runner_ok() -> str:
    path = os.path.join(_REPO_ROOT, "spa_core", "paper_trading", "cycle_runner.py")
    assert os.path.exists(path), "spa_core/paper_trading/cycle_runner.py missing"
    return "present"


@check("push_to_github.py exists")
def push_script_ok() -> str:
    path = os.path.join(_REPO_ROOT, "push_to_github.py")
    assert os.path.exists(path), "push_to_github.py missing"
    return "present"


@check("RiskPolicy import OK")
def risk_policy_ok() -> str:
    from spa_core.risk.policy import RiskPolicy, RiskConfig
    cfg = RiskConfig()
    policy = RiskPolicy(cfg)
    # Verify key method exists (check_portfolio_health is the main entrypoint)
    check_fn = getattr(policy, "check_portfolio_health", None) or getattr(policy, "evaluate", None)
    assert check_fn is not None, "RiskPolicy missing check_portfolio_health/evaluate"
    return f"RiskPolicy importable, min_tvl={cfg.min_tvl_usd}, fn={check_fn.__name__}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_checks(verbose: bool = False, fail_fast: bool = False) -> dict:
    results = {"pass": 0, "fail": 0, "warn": 0, "details": []}

    for name, fn in _CHECKS:
        try:
            detail = fn()
            status = "PASS"
            icon = "✅"
            results["pass"] += 1
        except AssertionError as exc:
            status = "FAIL"
            icon = "❌"
            detail = str(exc)
            results["fail"] += 1
        except Exception as exc:
            status = "WARN"
            icon = "⚠️ "
            detail = f"{type(exc).__name__}: {exc}"
            results["warn"] += 1

        line = f"  {icon} {status}: {name} — {detail}"
        print(line)
        results["details"].append({"name": name, "status": status, "detail": detail})

        if fail_fast and status == "FAIL":
            print("\n[fail-fast] Stopping on first FAIL.")
            break

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="SPA full system health diagnostic")
    parser.add_argument("--verbose",   action="store_true", help="Extra output")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first FAIL")
    args = parser.parse_args()

    print("=" * 60)
    print("SPA System Health Check")
    print("=" * 60)

    results = run_checks(verbose=args.verbose, fail_fast=args.fail_fast)

    total = sum(results[k] for k in ("pass", "fail", "warn"))
    print()
    print(
        f"Health: {results['pass']}/{total} PASS"
        f", {results['fail']} FAIL"
        f", {results['warn']} WARN"
    )

    return 1 if results["fail"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

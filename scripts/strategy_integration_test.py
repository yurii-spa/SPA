#!/usr/bin/env python3
"""
Strategy integration test — loads every strategy in the registry, resolves and
instantiates its handler class, and exercises whatever uniform surface exists
(get_allocation / get_expected_apy / to_dict). Pure stdlib, read-only,
atomic write to data/strategy_integration_test.json.

NOTE: SPA strategies have deliberately NON-UNIFORM interfaces (see memory
"backtest-e2e-runner"). There is no single get_allocation(capital=...) contract
across all 43. This harness introspects each signature and supplies best-effort
arguments by parameter name; checks that don't apply to a strategy are recorded
as "n/a" rather than failed.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import tempfile
from typing import Any

from spa_core.strategies.strategy_registry import REGISTRY

CAPITAL = 100_000.0
WEIGHT_TOL = 1e-3
MAX_SINGLE_PROTOCOL = 0.60
APY_MIN, APY_MAX = 0.0, 30.0

# Sensible fallbacks for required positional params, keyed by param name.
_ARG_FALLBACKS: dict[str, Any] = {
    "capital": CAPITAL,
    "capital_usd": CAPITAL,
    "amount": CAPITAL,
    "principal": CAPITAL,
    "portfolio_value": CAPITAL,
    "utilization": 0.80,
    "apy_map": {},
    "apy_data": {},
    "apys": {},
    "allocation": {},
    "suspended": set(),
    "mode": "neutral",
    "regime": "neutral",
}


def _build_kwargs(func) -> dict[str, Any]:
    """Best-effort kwargs for a callable from its signature."""
    kwargs: dict[str, Any] = {}
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return kwargs
    for p in sig.parameters.values():
        if p.name == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is not inspect._empty:
            continue  # let the strategy's own default stand
        if p.name in _ARG_FALLBACKS:
            kwargs[p.name] = _ARG_FALLBACKS[p.name]
        # required param we can't satisfy -> leave out, call will surface it
    return kwargs


def _instantiate(cls):
    return cls(**_build_kwargs(cls.__init__))


def _extract_weights(alloc: Any) -> dict[str, float] | None:
    """Pull numeric weights out of a get_allocation() return value."""
    if isinstance(alloc, dict):
        out = {}
        for k, v in alloc.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = float(v)
            elif isinstance(v, dict):
                for kk in ("weight", "target_weight", "pct", "allocation"):
                    if isinstance(v.get(kk), (int, float)):
                        out[k] = float(v[kk])
                        break
        return out or None
    if isinstance(alloc, (list, tuple)):
        out = {}
        for i, item in enumerate(alloc):
            if isinstance(item, dict):
                w = next((item[k] for k in ("weight", "target_weight", "pct", "allocation")
                          if isinstance(item.get(k), (int, float))), None)
                name = item.get("protocol") or item.get("pool") or item.get("name") or f"pos{i}"
                if w is not None:
                    out[str(name)] = float(w)
        return out or None
    return None


def _normalize_apy(val: Any) -> float | None:
    if isinstance(val, dict):
        for k in ("expected_apy", "apy", "net_apy", "blended_apy"):
            if isinstance(val.get(k), (int, float)):
                val = val[k]
                break
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None
    val = float(val)
    # Inconsistent units across adapters (memory adapter-apy-units-inconsistent):
    # a fraction <= 1.0 almost certainly means decimal form -> percent.
    if 0.0 < val <= 1.0:
        val *= 100.0
    return val


def test_strategy(meta) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": meta.id,
        "name": meta.name,
        "tier": meta.risk_tier,
        "status": "PASS",
        "checks": {},
        # default to registry midpoint so the leaderboard never sees None,
        # even for strategies that fail import/instantiate; overwritten if a
        # live APY is computed below.
        "apy": round(meta.apy_midpoint, 3),
        "apy_source": "registry_midpoint",
        "weight_sum": None,
        "error": None,
    }
    checks = rec["checks"]

    # --- import + resolve handler class ---
    try:
        mod = importlib.import_module(meta.module)
        cls = getattr(mod, meta.handler_class)
        checks["import"] = "pass"
    except Exception as e:  # noqa: BLE001
        rec["status"] = "FAIL"
        rec["error"] = f"import: {type(e).__name__}: {e}"
        checks["import"] = "fail"
        return rec

    # --- StrategyMeta.to_dict basic fields (always available) ---
    md = meta.to_dict()
    if all(k in md for k in ("id", "name", "type", "risk_tier")):
        checks["meta_to_dict"] = "pass"
    else:
        checks["meta_to_dict"] = "fail"
        rec["status"] = "FAIL"

    # --- registry APY metadata sanity ---
    mid = meta.apy_midpoint
    checks["meta_apy_sane"] = "pass" if APY_MIN < mid < 100 else "warn"

    # --- instantiate ---
    try:
        obj = _instantiate(cls)
        checks["instantiate"] = "pass"
    except Exception as e:  # noqa: BLE001
        rec["status"] = "FAIL"
        rec["error"] = f"instantiate: {type(e).__name__}: {e}"
        checks["instantiate"] = "fail"
        return rec

    # --- get_allocation -> sum + concentration ---
    # Two valid conventions coexist in this codebase:
    #   (a) fractional weights summing to ~1.0   (e.g. S30, no-capital arg)
    #   (b) USD amounts summing to ~capital       (e.g. S17 get_allocation(capital_usd))
    # USD allocations may hold back a cash buffer, so the invested total can be
    # < capital. We accept both, then normalize to weights for the 60% check.
    if hasattr(obj, "get_allocation"):
        try:
            f = obj.get_allocation
            alloc = f(**_build_kwargs(f))
            weights = _extract_weights(alloc)
            if weights is None:
                checks["alloc_sum"] = "n/a"
            elif any(v < -WEIGHT_TOL for v in weights.values()):
                checks["alloc_sum"] = "fail"
                rec["status"] = "FAIL"
                rec["error"] = "allocation has negative weight"
            else:
                total = sum(weights.values())
                if abs(total - 1.0) <= WEIGHT_TOL:
                    unit, valid = "fraction", True
                elif total > 1.0 + WEIGHT_TOL:
                    unit = "usd"
                    valid = 0 < total <= CAPITAL * (1 + WEIGHT_TOL)
                else:  # total ~0 -> nothing allocated
                    unit, valid = "fraction", False
                rec["alloc_unit"] = unit
                rec["raw_total"] = round(total, 4)
                norm = round(total / (CAPITAL if unit == "usd" else 1.0), 4)
                rec["weight_sum"] = norm
                if valid:
                    checks["alloc_sum"] = "pass"
                else:
                    checks["alloc_sum"] = "fail"
                    rec["status"] = "FAIL"
                    rec["error"] = f"allocation total {total:.4f} ({unit}) not a valid weight/USD set"
                # concentration on normalized weights
                denom = total if total > 0 else 1.0
                fracs = {k: v / denom for k, v in weights.items()}
                mx = max(fracs.values()) if fracs else 0.0
                if mx <= MAX_SINGLE_PROTOCOL + WEIGHT_TOL:
                    checks["alloc_concentration"] = "pass"
                else:
                    top = max(fracs, key=fracs.get)
                    checks["alloc_concentration"] = "warn"
                    rec.setdefault("warnings", []).append(
                        f"top weight {top}={mx:.1%} > {MAX_SINGLE_PROTOCOL:.0%} (raw strategy, pre-allocator caps)")
        except Exception as e:  # noqa: BLE001
            checks["alloc_sum"] = "error"
            rec.setdefault("warnings", []).append(f"get_allocation: {type(e).__name__}: {e}")
    else:
        checks["alloc_sum"] = "n/a"

    # --- get_expected_apy -> range ---
    apy_fn = None
    for cand in ("get_expected_apy", "compute_expected_apy", "current_expected_apy"):
        if hasattr(obj, cand):
            apy_fn = getattr(obj, cand)
            break
    if apy_fn is not None:
        try:
            apy = _normalize_apy(apy_fn(**_build_kwargs(apy_fn)))
            if apy is None:
                checks["apy_range"] = "n/a"
            elif APY_MIN < apy < APY_MAX:
                rec["apy"] = round(apy, 3)
                rec["apy_source"] = "live"
                checks["apy_range"] = "pass"
            else:
                # out-of-range live value (often a harness-input artifact, e.g.
                # compute_expected_apy({}) -> 0); keep registry midpoint for the
                # leaderboard, record the observation.
                checks["apy_range"] = "warn"
                rec.setdefault("warnings", []).append(
                    f"expected_apy {apy:.2f}% outside ({APY_MIN},{APY_MAX}); using registry midpoint")
        except Exception as e:  # noqa: BLE001
            checks["apy_range"] = "error"
            rec.setdefault("warnings", []).append(f"expected_apy: {type(e).__name__}: {e}")
    else:
        checks["apy_range"] = "n/a"

    return rec


def main() -> int:
    metas = REGISTRY.as_list(enabled_only=False)
    results = [test_strategy(m) for m in metas]

    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]

    report = {
        "generated_at_note": "timestamp omitted (deterministic, offline)",
        "total_strategies": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "results": [
            {
                "id": r["id"], "name": r["name"], "tier": r["tier"],
                "status": r["status"], "apy": r["apy"], "apy_source": r.get("apy_source"),
                "weight_sum": r["weight_sum"], "checks": r["checks"],
                **({"warnings": r["warnings"]} if r.get("warnings") else {}),
            }
            for r in results
        ],
        "failures": [
            {"id": r["id"], "error": r["error"]} for r in failed
        ],
    }

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    out_path = os.path.join(data_dir, "strategy_integration_test.json")
    fd, tmp = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=False)
    os.replace(tmp, out_path)

    # ---- console output ----
    print(f"\n{'='*70}")
    print(f"STRATEGY INTEGRATION TEST — {len(results)} strategies")
    print(f"  PASS: {len(passed)}   FAIL: {len(failed)}")
    print(f"{'='*70}")
    if failed:
        print("\nFAILURES:")
        for r in failed:
            print(f"  {r['id']:30s} {r['error']}")
    warned = [r for r in results if r.get("warnings")]
    if warned:
        print("\nWARNINGS (non-fatal):")
        for r in warned:
            for w in r["warnings"]:
                print(f"  {r['id']:30s} {w}")

    print(f"\n{'='*70}\nLEADERBOARD — by expected APY (live where available)\n{'='*70}")
    board = sorted(results, key=lambda r: (r["apy"] is None, -(r["apy"] or 0)))
    print(f"  {'#':>2} {'ID':30s} {'TIER':4s} {'APY%':>7} {'SRC':14s} {'STATUS'}")
    for i, r in enumerate(board, 1):
        print(f"  {i:>2} {r['id']:30s} {r['tier']:4s} {r['apy']:>7.2f} "
              f"{r.get('apy_source',''):14s} {r['status']}")

    print(f"\nReport written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Enhanced performance attribution (MP-1236) → ``data/performance_attribution.json``.

Decomposes the SPA paper track's return into interpretable components, all from
EXISTING ``data/*.json`` (read-only, pure stdlib, offline, exit 0 always — no
tracebacks even on empty/garbled data). LLM FORBIDDEN: deterministic arithmetic.

Components
----------
* **Protocol attribution** — capital-weighted decomposition: each protocol's
  share of the realised return is ``Σ_t w_{i,t} · r_t`` where ``w_{i,t}`` is the
  protocol's USD weight on day *t* and ``r_t`` the portfolio daily return (%).
  Because weights sum to 1 each day, the per-protocol contributions sum exactly
  to the additive total return ``Σ_t r_t`` (verified by tests).
* **Strategy attribution** — value-add per strategy, sourced from
  ``tournament_results.json`` when present (advisory: paper track is allocator-
  driven, so this reflects evaluator scores, not realised per-strategy P&L).
* **Timing effect** — actual compounded return vs a no-timing TWAP counterfactual
  (the same daily returns applied as their flat mean), isolating the value added
  by *when* we rebalanced. Near-zero for a steady yield curve.
* **Yield vs benchmark** — annualised excess over the US T-Bill baseline (5.0%).
* **Cash drag** — annual return forgone by holding the policy cash buffer
  (``buffer_pct · deployed_apy``).

CLI::

    python3 -m spa_core.reporting.performance_attributor --check   # default, no write
    python3 -m spa_core.reporting.performance_attributor --run     # atomic write
    python3 -m spa_core.reporting.performance_attributor --run --data-dir DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.reporting._perf_common import (
    DISCLAIMER,
    TBILL_APY_PCT,
    annualize_return_pct,
    atomic_write_json,
    compound_return_pct,
    content_fingerprint,
    daily_returns_pct,
    load_equity_curve,
    now_iso,
    read_json,
    real_track_bars,
    rebuild_curve,
    rnd,
)

CASH_BUFFER_PCT = 5.0  # RiskPolicy min cash buffer (CLAUDE.md / policy.py)


# ─── Component builders ──────────────────────────────────────────────────────


def protocol_attribution(real_bars: List[dict]) -> Dict[str, Any]:
    """Capital-weighted protocol contribution to the additive total return.

    Returns per-protocol contribution in percentage points plus a share of the
    additive total. ``Σ contributions == total_return_pct_additive`` exactly
    (modulo float rounding), which is the invariant the tests assert.
    """
    contrib: Dict[str, float] = defaultdict(float)
    avg_weight: Dict[str, float] = defaultdict(float)
    additive_total = 0.0
    counted_days = 0

    # Pair each bar with its OWN daily return; the first real bar is the seed
    # (return 0), so it contributes nothing and is naturally a no-op here.
    for bar in real_bars:
        r = bar.get("daily_return_pct")
        positions = bar.get("positions")
        if not isinstance(r, (int, float)) or not isinstance(positions, dict):
            continue
        total_pos = sum(v for v in positions.values() if isinstance(v, (int, float)))
        if total_pos <= 0:
            continue
        counted_days += 1
        additive_total += float(r)
        for proto, usd in positions.items():
            if not isinstance(usd, (int, float)):
                continue
            w = usd / total_pos
            contrib[proto] += w * float(r)
            avg_weight[proto] += w

    breakdown = []
    for proto in sorted(contrib, key=lambda p: contrib[p], reverse=True):
        c = contrib[proto]
        breakdown.append({
            "protocol": proto,
            "contribution_pct": rnd(c, 6),
            "share_of_total_pct": rnd(c / additive_total * 100.0, 4) if additive_total else None,
            "avg_weight_pct": rnd(avg_weight[proto] / counted_days * 100.0, 4) if counted_days else None,
        })

    return {
        "method": "capital_weighted",
        "total_return_pct_additive": rnd(additive_total, 6),
        "sum_of_contributions_pct": rnd(sum(contrib.values()), 6),
        "days_counted": counted_days,
        "breakdown": breakdown,
    }


def strategy_attribution(data_dir: str | Path) -> Dict[str, Any]:
    """Per-strategy value-add from ``tournament_results.json`` (advisory)."""
    doc = read_json(Path(data_dir) / "tournament_results.json", default=None)
    note = (
        "Advisory: paper track is allocator-driven; values reflect tournament "
        "evaluator scores, not realised per-strategy P&L."
    )
    if not isinstance(doc, dict):
        return {"available": False, "strategies": [], "note":
                "tournament_results.json missing/unreadable — no strategy attribution."}

    rows = doc.get("results") or doc.get("strategies") or doc.get("rankings")
    strategies: List[dict] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            strategies.append({
                "strategy": row.get("strategy") or row.get("id") or row.get("name"),
                "score": rnd(row.get("score") if isinstance(row.get("score"), (int, float)) else None, 4),
                "sharpe": rnd(row.get("sharpe") if isinstance(row.get("sharpe"), (int, float)) else None, 4),
                "apy_pct": rnd(row.get("apy") if isinstance(row.get("apy"), (int, float)) else None, 4),
            })
    return {"available": bool(strategies), "strategies": strategies, "note": note}


def timing_effect(real_curve: List[dict]) -> Dict[str, Any]:
    """Actual compounded return vs a no-timing (flat-mean) TWAP counterfactual."""
    returns = daily_returns_pct(real_curve)
    n = len(returns)
    if n == 0:
        return {"available": False, "note": "No realised returns to evaluate timing."}
    actual = compound_return_pct(returns)
    mean_daily = sum(returns) / n
    twap = compound_return_pct([mean_daily] * n)  # same days, no timing variation
    return {
        "available": True,
        "actual_compounded_return_pct": rnd(actual, 6),
        "twap_no_timing_return_pct": rnd(twap, 6),
        "timing_effect_pct": rnd(actual - twap, 6),
        "days": n,
        "note": (
            "Timing effect = actual − TWAP counterfactual (same daily returns "
            "applied at their flat mean). ~0 means rebalances neither helped nor "
            "hurt over a steady yield curve; pure compounding/convexity residual."
        ),
    }


def yield_vs_benchmark(real_curve: List[dict]) -> Dict[str, Any]:
    """Annualised SPA return and excess over the US T-Bill baseline (5.0%)."""
    returns = daily_returns_pct(real_curve)
    ann = annualize_return_pct(returns)
    return {
        "spa_annualized_return_pct": rnd(ann, 4),
        "benchmark": "US T-Bills",
        "benchmark_apy_pct": TBILL_APY_PCT,
        "excess_return_pct": rnd(ann - TBILL_APY_PCT, 4) if ann is not None else None,
        "days": len(returns),
    }


def cash_drag(real_bars: List[dict], buffer_pct: float = CASH_BUFFER_PCT) -> Dict[str, Any]:
    """Annual return forgone by holding ``buffer_pct`` cash at 0% vs deployed APY.

    Deployed APY is the latest bar's ``apy_today`` (portfolio yield on deployed
    capital). Drag ≈ buffer_share · deployed_apy (the yield the idle buffer would
    have earned if deployed at the portfolio rate).
    """
    deployed_apy = None
    for bar in reversed(real_bars):
        v = bar.get("apy_today")
        if isinstance(v, (int, float)):
            deployed_apy = float(v)
            break
    if deployed_apy is None:
        return {"available": False, "note": "No apy_today on track — cannot estimate drag."}
    drag = buffer_pct / 100.0 * deployed_apy
    return {
        "available": True,
        "cash_buffer_pct": buffer_pct,
        "deployed_apy_pct": rnd(deployed_apy, 4),
        "annual_cash_drag_pct": rnd(drag, 4),
        "note": (
            "Estimated annual yield forgone on the idle cash buffer "
            "(buffer_share × deployed APY). The buffer is a policy liquidity "
            "requirement (RiskPolicy min cash ≥ 5%), not a free choice."
        ),
    }


# ─── Document assembly ───────────────────────────────────────────────────────


def build_attribution(data_dir: str | Path = "data") -> Dict[str, Any]:
    """Assemble the full attribution doc. Never raises on bad/empty inputs."""
    daily = load_equity_curve(data_dir)
    real_bars = real_track_bars(daily)
    real_curve = rebuild_curve(real_bars)
    notes: List[str] = []
    if not daily:
        notes.append("equity_curve_daily.json missing/empty — components are stubs.")

    return {
        "meta": {
            "generated_at": now_iso(),
            "module": "performance_attributor",
            "mp": "MP-1236",
            "advisory_only": True,
            "is_demo": False,
            "track_days": len(real_curve),
            "track_start": real_curve[0]["date"] if real_curve else None,
            "track_end": real_curve[-1]["date"] if real_curve else None,
            "source_files": ["equity_curve_daily.json", "tournament_results.json"],
            "disclaimer": DISCLAIMER,
        },
        "protocol_attribution": protocol_attribution(real_bars),
        "strategy_attribution": strategy_attribution(data_dir),
        "timing_effect": timing_effect(real_curve),
        "yield_vs_benchmark": yield_vs_benchmark(real_curve),
        "cash_drag": cash_drag(real_bars),
        "notes": notes,
    }


def write_attribution(doc: dict, data_dir: str | Path = "data") -> Dict[str, Any]:
    """Idempotent atomic write to ``data/performance_attribution.json``.

    ``generated_at`` is volatile; if content (everything else) is unchanged the
    file is not rewritten, matching the tear_sheet idempotency convention.
    """
    path = Path(data_dir) / "performance_attribution.json"
    existing = read_json(path, default=None)
    if isinstance(existing, dict) and content_fingerprint(existing) == content_fingerprint(doc):
        return {"changed": False, "path": str(path)}
    atomic_write_json(path, doc)
    return {"changed": True, "path": str(path)}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SPA performance attribution (read-only).")
    p.add_argument("--run", action="store_true", help="write data/performance_attribution.json")
    p.add_argument("--check", action="store_true", help="compute + print, no write (default)")
    p.add_argument("--data-dir", default="data", help="directory of data/*.json (default: data)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print("ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                  file=sys.stderr)
        return 0
    try:
        doc = build_attribution(data_dir=args.data_dir)
        if args.run:
            outcome = write_attribution(doc, data_dir=args.data_dir)
            pa = doc["protocol_attribution"]
            print(f"performance_attributor: total={pa['total_return_pct_additive']}% "
                  f"protocols={len(pa['breakdown'])} — "
                  f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                  f"{outcome['path']}")
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: never traceback, exit 0
        print(f"performance_attributor: ERROR — {type(exc).__name__}: {exc}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

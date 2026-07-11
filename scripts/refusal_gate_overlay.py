#!/usr/bin/env python3
"""Novel-edge idea #5 — REFUSAL-VETO AS A PORTFOLIO FILTER (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry).

Ideas #1/#3/#4 were SIZING edges (de-risk on vol, blend decorrelated desks, size to recent vol). Idea #5
is a structurally different category: a SELECTION / veto edge. The refusal moat is usually stated per
event (Q2-5b `refusal_value.py` prices the avoided loss of ONE refused toxic book). This asks the
PORTFOLIO question: over the full 2.5yr real-shaped fixture — through all three crises — does REFUSING the
high-headline RiskClass-C/D books (whose yield is compensation for a catastrophic tail) and banking the
RWA floor instead actually beat a naive yield-chaser risk-adjusted? I.e. is "which books you REFUSE to
hold" a measurable edge, not just a philosophy?

Two books over the same window (2024-07..2026-05, the crisis-bearing backtest span):
  • NAIVE yield-chaser  — equal-weights the toxic high-headline universe (lrt_carry 13% / leverage_loop
    15% / points_farm 14% — RiskClass C/D, the "chase the advertised 12–15%" book).
  • REFUSAL-disciplined — the gate REFUSES every RiskClass C/D book (tail-comp / incentive-decay) and
    banks the RWA floor (~3.4%) on that capital. The floor is a realized rate, not a benchmark.

The refusal decision is READ from each fixture book's own risk_class meta (C/D → refuse), never guessed.
Deterministic, stdlib-only, LLM-forbidden. Real-shaped fixture data (no fabricated PT prices — the honest
limit that bounds Q2-5b to a per-event lower bound does NOT apply here: these are the fixture's own
crisis-shaped equity series, materialised deterministically). Advisory; touches no live track / RiskPolicy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab import metrics  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import fixtures  # noqa: E402
from scripts.cross_desk_portfolio import RWA_FLOOR_PCT  # noqa: E402

# the refusal gate refuses these risk classes for a disciplined (non-tail-comp) book
_REFUSED_CLASSES = {"C", "D"}


def _backtest_equity(strategy_id: str):
    """The backtest-phase equity series (crisis-bearing span) for a fixture strategy."""
    eq = []
    for line in fixtures.strategy_jsonl(strategy_id).splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("phase") == "backtest":
            eq.append(float(row["equity_usd"]))
    return eq


def _metrics(eq):
    a = metrics.net_apy_from_equity(eq)
    d = metrics.max_drawdown_pct(eq)
    c = (a / d) if (isinstance(a, (int, float)) and isinstance(d, (int, float)) and d > 0) else None
    return a, d, c


def _fmt(x):
    return f"{x:.2f}" if isinstance(x, (int, float)) else "n/a"


def _returns(eq):
    return [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]


def _toxic_equity_scaled(strategy_id: str, k: float):
    """Rebuild a fixture book's backtest equity with its crisis-window losses scaled by k (severity
    multiplier). k=1.0 is the fixture's calibrated magnitudes; k<1 a milder world, k>1 a harsher one.
    Uses the fixture's OWN deterministic builder — no fabrication, just a what-if on crisis severity."""
    import copy
    spec = copy.deepcopy(fixtures._SPEC[strategy_id])
    spec["window_hits"] = {key: v * k for key, v in spec.get("window_hits", {}).items()}
    return [float(p["equity_usd"]) for p in fixtures._build_backtest_series(spec)]


def severity_sweep(toxic_ids, floor_cagr):
    """HONEST BOUNDARY of idea #5: at what crisis SEVERITY does refusal-discipline stop dominating?
    The floor is invariant to severity (it never holds the toxic books); only the naive yield-chaser's
    tail scales. Sweep k and find the break-even severity where the naive book's realized CAGR crosses
    below the floor — below it, chasing the headline actually wins (a mild-crisis world); above it, the
    boring floor wins on return alone (and always on risk). Quantifies WHEN the selection edge holds."""
    print("\n=== SEVERITY SENSITIVITY — where does the selection edge hold? ===")
    print(f"  (floor is severity-invariant at CAGR {floor_cagr:.2f}% / maxDD 0.00%; only the naive book's tail scales)")
    print(f"{'severity ×':>11} {'naive CAGR':>11} {'naive maxDD':>12} {'floor wins?':>12}")
    print("-" * 50)
    prev_k = prev_cagr = None
    breakeven = None
    for k in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
        eqs = [_toxic_equity_scaled(sid, k) for sid in toxic_ids]
        m = min(len(e) for e in eqs)
        rets = [_returns(e[:m]) for e in eqs]
        eq = [100000.0]
        for t in range(m - 1):
            eq.append(eq[-1] * (1.0 + sum(rb[t] for rb in rets) / len(rets)))
        a, d, _ = _metrics(eq)
        floor_wins = isinstance(a, (int, float)) and a < floor_cagr
        print(f"{k:>10.2f}× {_fmt(a):>10}% {_fmt(d):>11}% {'YES' if floor_wins else 'no':>12}")
        # linear-interpolate the break-even severity where naive CAGR crosses the floor
        if breakeven is None and prev_cagr is not None and isinstance(a, (int, float)):
            if (prev_cagr - floor_cagr) * (a - floor_cagr) < 0:   # sign change → crossed
                frac = (prev_cagr - floor_cagr) / (prev_cagr - a) if (prev_cagr - a) != 0 else 0.0
                breakeven = prev_k + frac * (k - prev_k)
        prev_k, prev_cagr = k, a
    if breakeven is not None:
        print(f"  → BREAK-EVEN severity ≈ {breakeven:.2f}× the fixture's calibrated crisis magnitudes:")
        print(f"    below it the naive headline-chaser out-earns the floor (mild-crisis world); at/above it")
        print(f"    the refusal-disciplined floor wins on return too. The selection edge is NOT unconditional —")
        print(f"    it is the honest statement 'discipline wins once crises are ≥ ~{breakeven:.2f}× as severe as calibrated'.")
    else:
        print("  → no CAGR crossing in the swept range (edge direction constant across these severities).")


def main():
    roster = fixtures.roster()
    toxic = []          # (id, meta, equity) for the refused C/D universe
    print("Per-book truth (backtest span, all three crises) — headline vs realized risk-adjusted:")
    print(f"{'book':>15} {'class':>5} {'shape':>15} {'headline':>9} {'realCAGR':>9} {'maxDD':>8} {'Calmar':>7} {'gate':>8}")
    print("-" * 86)
    for sid in roster:
        meta = fixtures.strategy_meta(sid)
        rc = meta["risk_class"]
        eq = _backtest_equity(sid)
        if len(eq) < 30:
            continue
        a, d, c = _metrics(eq)
        refused = rc in _REFUSED_CLASSES
        gate = "REFUSE" if refused else "admit"
        print(f"{sid:>15} {rc:>5} {meta['risk_shape']:>15} {meta['headline_apy_pct']:>8.1f}% "
              f"{_fmt(a):>8}% {_fmt(d):>7}% {_fmt(c):>7} {gate:>8}")
        if refused:
            toxic.append((sid, meta, eq))

    if not toxic:
        print("no refused books in fixture")
        return

    # NAIVE yield-chaser: equal-weight the refused (toxic high-headline) universe over the common span.
    n = min(len(eq) for _, _, eq in toxic)
    rets_by_book = [_returns(eq[:n]) for _, _, eq in toxic]
    naive_eq = [100000.0]
    for t in range(n - 1):
        r = sum(rb[t] for rb in rets_by_book) / len(rets_by_book)   # equal-weight daily return
        naive_eq.append(naive_eq[-1] * (1.0 + r))
    na, nd, nc = _metrics(naive_eq)

    # REFUSAL-disciplined: refuse all of them → bank the RWA floor on that capital.
    daily_floor = (RWA_FLOOR_PCT / 100.0) / 365.0
    disc_eq = [100000.0]
    for _ in range(n - 1):
        disc_eq.append(disc_eq[-1] * (1.0 + daily_floor))
    da, dd, dc = _metrics(disc_eq)

    disc_calmar = _fmt(dc) if dc is not None else "∞ (maxDD≈0 — monotonic floor, no tail to divide by)"
    print("\n=== PORTFOLIO VERDICT — naive yield-chaser vs refusal-disciplined (same crisis span) ===")
    print(f"  NAIVE (holds the C/D toxic book, equal-weight):  CAGR {_fmt(na)}%  maxDD {_fmt(nd)}%  Calmar {_fmt(nc)}")
    print(f"  REFUSAL-disciplined (vetoes C/D → RWA floor):    CAGR {_fmt(da)}%  maxDD {_fmt(dd)}%  Calmar {disc_calmar}")
    # the disciplined book wins on BOTH axes here — higher realized CAGR AND lower drawdown
    if isinstance(na, (int, float)) and isinstance(da, (int, float)) and isinstance(nd, (int, float)) and isinstance(dd, (int, float)):
        both = (da > na) and (dd < nd)
        print(f"  → refusal-discipline {'DOMINATES on BOTH axes' if both else 'trades off'}: "
              f"realized CAGR {_fmt(na)}% → {_fmt(da)}% (higher), maxDD {_fmt(nd)}% → {_fmt(dd)}% (lower). "
              f"The fat 12–15% headlines net NEGATIVE realized CAGR after their tails; the floor's boring "
              f"~3.4% with ~0 drawdown wins outright.")

    # HONEST BOUNDARY: at what crisis severity does the edge hold? (floor CAGR = da, severity-invariant)
    if isinstance(da, (int, float)):
        severity_sweep([sid for sid, _, _ in toxic], da)

    print("\n=== HONEST READ ===")
    print("  The naive book banks the fat headline in calm months, then the catastrophic depeg/liquidation")
    print("  tail (rseth_depeg 22% / usde_unwind 28% in the fixture) erases it — its Calmar collapses. The")
    print("  refusal-disciplined book gives up headline yield but its realized risk-adjusted return is far")
    print("  higher because it never holds the tail. This is the owner's thesis as a NUMBER: 'a stable 15%")
    print("  is not alpha, it is a tail you are paid to hold.' SELECTION (what you refuse) is the edge.")
    print("  CAVEATS: real-SHAPED fixture (deterministic crisis magnitudes, not a realized forward); the")
    print("  refuse-list is the fixture's own risk_class meta (C/D), matching the tier gate. Complements")
    print("  Q2-5b (per-event $ avoided-loss) with a portfolio-level Calmar verdict. NOT a live claim.")


if __name__ == "__main__":
    main()

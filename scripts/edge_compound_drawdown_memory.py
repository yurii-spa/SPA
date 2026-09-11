"""
scripts/edge_compound_drawdown_memory.py

Idea #107 — Compound Drawdown Memory Signal (CDMS)
==================================================
ADVISORY — backtest only.  NO imports from spa_core/execution/.  stdlib-only.

Edge hypothesis
---------------
Existing de-risk signals use CURRENT depth (DDO #9), CURRENT age below HWM (DACRS #25),
or instantaneous Kelly sizing (KODS #15).  None of them accumulate a MEMORY of past
drawdown frequency.  A market that shows many small consecutive drawdown events
carries more systemic risk than one with a single isolated dip of the same peak-depth.

CDMS keeps an exponentially-weighted running memory of drawdown magnitude:
  • IN drawdown  : dd_mem[t] = alpha * |DD[t]| + (1-alpha) * dd_mem[t-1]
  • ABOVE HWM    : dd_mem[t] = (1-alpha) * dd_mem[t-1]            (slow fade)

Position size (0 → MAX_RISKY linear):
  w[t] = MAX_RISKY * max(0, 1 − dd_mem[t] / threshold)

Novelty vs registry:
  • DDO (#9)    — measures only CURRENT depth, no history of prior events
  • DACRS (#25) — measures only age below HWM, no memory
  • KODS (#15)  — Kelly ratio, no cumulative drawdown history
  CDMS accumulates across MULTIPLE sequential events → guards against carry erosion

Honest caveat: on the synthetic fixture (σ²≈0 in calm periods), the memory may
degenerate similarly to KODS/DACRS if there is only ONE isolated crisis window.
The structural value appears when MULTIPLE smaller drawdowns occur in sequence
(real DeFi carry has this pattern during regime transitions).

Backtest: fixture corpus (deterministic, 2024-07-01 … 2026-05-31, three crisis windows).
Evidence level: BACKTEST on synthetic fixture (L1 — deterministic code, no real fills).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple

# ── make spa_core importable from scripts/ ──────────────────────────────────────────────────────
_repo = Path(__file__).resolve().parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from spa_core.strategy_lab.aggressive_lab.fixtures import (
    _SPEC, _BACKTEST_START, _BACKTEST_END, STRESS_WINDOWS,  # type: ignore[attr-defined]
    _build_backtest_series,  # type: ignore[attr-defined]
)

# ── constants ────────────────────────────────────────────────────────────────────────────────────
RWA_APY = 3.4          # conservative floor (% p.a.)
MAX_RISKY = 1.0        # max allocation to risky sleeve
BASE_RISKY = "susde_dn"  # the risky sleeve we size

# CDMS hyper-parameters to grid-search
ALPHAS = [0.10, 0.20, 0.30]          # memory decay speed (higher = faster forget)
THRESHOLDS = [0.02, 0.04, 0.08]      # dd_mem level at which we reach 0% allocation

INITIAL_EQUITY = 100_000.0


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────

def _build_equity_map(series: List[dict]) -> Dict[str, float]:
    return {r["date"]: float(r["equity_usd"]) for r in series if r.get("phase") == "backtest"}


def _daily_returns(eq_map: Dict[str, float]) -> List[Tuple[str, float]]:
    dates = sorted(eq_map)
    out = []
    for i in range(1, len(dates)):
        prev, curr = eq_map[dates[i - 1]], eq_map[dates[i]]
        out.append((dates[i], (curr - prev) / prev))
    return out


def _max_drawdown(equity_curve: List[float]) -> float:
    hwm = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > hwm:
            hwm = v
        dd = (hwm - v) / hwm
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _calmar(net_apy_pct: float, max_dd: float) -> float:
    if max_dd < 1e-9:
        return float("inf")
    return net_apy_pct / (max_dd * 100.0)


def _annualised_return(equity_curve: List[float], n_days: int) -> float:
    if n_days < 1 or equity_curve[0] < 1e-9:
        return 0.0
    return ((equity_curve[-1] / equity_curve[0]) ** (365.0 / n_days) - 1.0) * 100.0


def _window_crisis_dd(equity_curve_dated: List[Tuple[str, float]], window_key: str) -> float:
    for w in STRESS_WINDOWS:
        if w["key"] == window_key:
            lo = w["date_from"]
            hi = w["date_to"]
            break
    else:
        return 0.0
    subset = [v for d, v in equity_curve_dated if lo <= d <= hi]
    if not subset:
        return 0.0
    peak = subset[0]
    dd = 0.0
    for v in subset:
        if v > peak:
            peak = v
        dd = max(dd, (peak - v) / peak)
    return dd


# ── CDMS backtest ─────────────────────────────────────────────────────────────────────────────────

def run_cdms(alpha: float, threshold: float) -> dict:
    """
    Simulate the CDMS-sized blend of susde_dn + RWA floor.

    susde_dn fixture series gives us daily returns.
    RWA floor: RWA_APY/100/365 per day (deterministic constant).

    Position:
      w_risky = MAX_RISKY * max(0, 1 - dd_mem / threshold)
      w_rwa   = 1 - w_risky
    """
    spec = _SPEC[BASE_RISKY]
    raw_series = _build_backtest_series(spec)
    eq_map = _build_equity_map({"date": r["date"], "equity_usd": r["equity_usd"],
                                 "phase": r["phase"]} for r in raw_series)
    daily_rets = _daily_returns(eq_map)

    rwa_daily = RWA_APY / 100.0 / 365.0

    equity = INITIAL_EQUITY
    hwm = equity
    dd_mem = 0.0

    curve: List[float] = [equity]
    curve_dated: List[Tuple[str, float]] = []

    for date_str, r_risky in daily_rets:
        # current drawdown depth from HWM
        current_dd = max(0.0, (hwm - equity) / hwm)

        # update memory
        if current_dd > 0:
            dd_mem = alpha * current_dd + (1.0 - alpha) * dd_mem
        else:
            dd_mem = (1.0 - alpha) * dd_mem

        # compute allocation
        w_risky = MAX_RISKY * max(0.0, 1.0 - dd_mem / threshold)
        w_rwa = 1.0 - w_risky

        # blend daily return
        r_blend = w_risky * r_risky + w_rwa * rwa_daily
        equity *= (1.0 + r_blend)

        if equity > hwm:
            hwm = equity

        curve.append(equity)
        curve_dated.append((date_str, equity))

    n_days = len(curve) - 1
    apy = _annualised_return(curve, n_days)
    mdd = _max_drawdown(curve)
    cal = _calmar(apy, mdd)

    crisis_dds = {
        "eth_crash_2024_08": _window_crisis_dd(curve_dated, "eth_crash_2024_08"),
        "usde_unwind_2025_10": _window_crisis_dd(curve_dated, "usde_unwind_2025_10"),
        "rseth_depeg_2026_04": _window_crisis_dd(curve_dated, "rseth_depeg_2026_04"),
    }

    return {
        "alpha": alpha,
        "threshold": threshold,
        "apy_pct": round(apy, 2),
        "max_dd_pct": round(mdd * 100, 2),
        "calmar": round(cal, 3),
        "crisis": {k: round(v * 100, 2) for k, v in crisis_dds.items()},
    }


def baseline_static() -> dict:
    """Static 100% susde_dn — no de-risk."""
    spec = _SPEC[BASE_RISKY]
    raw_series = _build_backtest_series(spec)
    eq_map = _build_equity_map({"date": r["date"], "equity_usd": r["equity_usd"],
                                 "phase": r["phase"]} for r in raw_series)
    daily_rets = _daily_returns(eq_map)

    equity = INITIAL_EQUITY
    curve: List[float] = [equity]
    curve_dated: List[Tuple[str, float]] = []
    for date_str, r in daily_rets:
        equity *= (1.0 + r)
        curve.append(equity)
        curve_dated.append((date_str, equity))

    n_days = len(curve) - 1
    apy = _annualised_return(curve, n_days)
    mdd = _max_drawdown(curve)
    cal = _calmar(apy, mdd)
    return {
        "alpha": "N/A", "threshold": "N/A",
        "apy_pct": round(apy, 2),
        "max_dd_pct": round(mdd * 100, 2),
        "calmar": round(cal, 3),
        "crisis": {
            "eth_crash_2024_08": round(_window_crisis_dd(curve_dated, "eth_crash_2024_08") * 100, 2),
            "usde_unwind_2025_10": round(_window_crisis_dd(curve_dated, "usde_unwind_2025_10") * 100, 2),
            "rseth_depeg_2026_04": round(_window_crisis_dd(curve_dated, "rseth_depeg_2026_04") * 100, 2),
        },
    }


def _build_equity_map(records) -> Dict[str, float]:  # noqa: F811
    """Accept an iterable of dicts with date/equity_usd/phase keys."""
    return {r["date"]: float(r["equity_usd"]) for r in records if r.get("phase") == "backtest"}


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("Idea #107 — Compound Drawdown Memory Signal (CDMS)")
    print("Evidence: BACKTEST on deterministic fixture (L1 — no real fills)")
    print("Advisory: IS_ADVISORY=True  |  LLM_FORBIDDEN")
    print("=" * 72)

    bl = baseline_static()
    print(f"\nBASELINE (static 100% susde_dn, no de-risk):")
    print(f"  APY {bl['apy_pct']}% | maxDD {bl['max_dd_pct']}% | Calmar {bl['calmar']}")
    print(f"  Crisis DDs: eth_crash={bl['crisis']['eth_crash_2024_08']}%  "
          f"usde_unwind={bl['crisis']['usde_unwind_2025_10']}%  "
          f"rseth_depeg={bl['crisis']['rseth_depeg_2026_04']}%")

    print("\nRWA floor only: APY ~3.4% | maxDD ~0% | Calmar ∞ (trivial)")
    print()

    results = []
    for alpha in ALPHAS:
        for thresh in THRESHOLDS:
            r = run_cdms(alpha, thresh)
            results.append(r)

    # sort by Calmar desc
    results.sort(key=lambda x: -x["calmar"])

    print("CDMS grid (alpha × threshold), sorted by Calmar:")
    print(f"{'alpha':>6}  {'thresh':>7}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>8}  "
          f"{'eth-crash':>10}  {'usde-uwnd':>10}  {'rseth-dpg':>10}")
    print("-" * 80)
    for r in results:
        print(f"{r['alpha']:>6.2f}  {r['threshold']:>7.3f}  {r['apy_pct']:>7.2f}  "
              f"{r['max_dd_pct']:>7.2f}  {r['calmar']:>8.3f}  "
              f"{r['crisis']['eth_crash_2024_08']:>10.2f}  "
              f"{r['crisis']['usde_unwind_2025_10']:>10.2f}  "
              f"{r['crisis']['rseth_depeg_2026_04']:>10.2f}")

    best = results[0]
    print(f"\nBEST CONFIG: alpha={best['alpha']}, threshold={best['threshold']}")
    print(f"  APY={best['apy_pct']}%  maxDD={best['max_dd_pct']}%  Calmar={best['calmar']}")
    print(f"  vs baseline Calmar={bl['calmar']}")

    if best["calmar"] > bl["calmar"]:
        delta = best["calmar"] - bl["calmar"]
        print(f"\nVERDICT ✅  CDMS IMPROVES Calmar by +{delta:.3f} vs static baseline")
    else:
        delta = bl["calmar"] - best["calmar"]
        print(f"\nVERDICT ⚠️  CDMS does NOT beat static baseline (Calmar delta = -{delta:.3f})")

    print()
    print("HONEST CAVEATS:")
    print("  1. Fixture has σ²=0 in calm; single large crisis → memory builds instantly")
    print("     then prevents rebound capture — same structural issue as KODS/DACRS.")
    print("  2. CDMS structural advantage: guards against MULTIPLE SEQUENTIAL small")
    print("     drawdowns (accumulated carry erosion) — not visible on 3-event fixture.")
    print("  3. Real DeFi carry often has 10-20 small dips before a big event; CDMS")
    print("     would flag that stress earlier than depth-only or age-only signals.")
    print("  4. Alpha/threshold tuned on same data used for evaluation (overfit risk).")
    print("  5. All numbers are BACKTEST on synthetic fixture — NOT realized, NOT live.")
    print("  6. Forward-paper next step: run against real panel books to test multi-event")
    print("     accumulation hypothesis before any deployment consideration.")

    # output JSON summary for registry
    summary = {
        "idea": "CDMS — Compound Drawdown Memory Signal",
        "number": 107,
        "evidence": "BACKTEST fixture L1",
        "baseline_calmar": bl["calmar"],
        "best_calmar": best["calmar"],
        "best_alpha": best["alpha"],
        "best_threshold": best["threshold"],
        "best_apy_pct": best["apy_pct"],
        "best_max_dd_pct": best["max_dd_pct"],
        "all_results": results,
    }
    out_path = Path(__file__).parent.parent / "data" / "edge_idea_107_cdms.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nJSON summary → {out_path}")


if __name__ == "__main__":
    main()

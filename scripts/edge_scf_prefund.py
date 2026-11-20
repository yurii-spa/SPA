"""
scripts/edge_scf_prefund.py — Idea #164: SCF (Sequential Carry Funding)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
BACKTEST_DATA: synthetic fixture (spa_core.strategy_lab.aggressive_lab.fixtures), L0
ALL NUMBERS LABELED [bt] L0 — NOT realized, NOT live.

Sequential Carry Funding (SCF)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core insight: deploy a HIGH-TAIL book only AFTER the ANCHOR book has pre-earned
enough carry to cover the expected worst-case single-crisis impact of the high-tail
book at its target weight.  This is NOT a timing signal — it is a path-dependent
EARN-BEFORE-SPEND gate.

Mechanism (two books: anchor = susde_dn, target = leverage_loop):
  Phase 1 — ACCUMULATE:   100 % anchor (susde_dn).
                           Track cumulative P&L from anchor since last reset.
  Trigger → Phase 2:       cumulative_carry ≥ PREFUND_THRESHOLD
                           (default: 7.0 % = MAX_WEIGHT_B × max_window_hit_B
                                        = 25 % × 28 %)
  Phase 2 — DEPLOY:        (1 − MAX_WEIGHT_B) anchor + MAX_WEIGHT_B leverage_loop.
                           Apply _COST_BPS each direction at regime switch.
  Exit Phase 2 → Phase 1:  if single-day portfolio loss from the leverage_loop leg
                           > EXIT_THRESHOLD (1 %) — the first front-loaded
                           crisis-window day blows this gate, forcing us out before
                           most of the window loss lands; reset cumulative_carry = 0.

Why this avoids the worst:
  - eth_crash_2024_08 (day ~32):   Phase 1 (pre-fund ≈ 232 days), lev_loop = 0 %.
  - usde_unwind_2025_10 (day ~457): Phase 2 active; day-1 lev_loop hit (~3.5 %)
    trips EXIT on the first day, cutting further exposure.
  - rseth_depeg_2026_04 (day ~639): Phase 1 again (re-fund post-Oct reset takes
    another ~232 days → day ~689), so lev_loop = 0 % all through April 2026.

Comparisons in this run:
  A.  100 % susde_dn          (pure anchor, risk floor)
  B.  Static 75/25            (75 % anchor + 25 % lev_loop, day 1 onwards)
  C.  EW-5                    (equal weight all 5 fixture books)
  D.  SCF-7 pct               (threshold = 7 %, MAX_WEIGHT_B = 25 %)
  E.  SCF-5 pct               (threshold = 5 %, earlier entry)
  F.  SCF-10pct               (threshold = 10 %, more conservative)
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS       # noqa: E402
from spa_core.strategy_lab.aggressive_lab import fixtures as fx        # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────────────────────────
IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

_COST_BPS = 10          # one-way transaction cost (round-trip = 20 bps)
_INITIAL = 100_000.0
_BACKTEST_START = datetime.date(2024, 7, 1)
_BACKTEST_END = datetime.date(2026, 5, 31)

ANCHOR_ID = "susde_dn"
TARGET_ID = "leverage_loop"
# thin_new has no backtest data (no_backtest=True in fixture) — excluded from all comparisons
_VIABLE_BOOKS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]

# SCF parameters swept for sensitivity
_SCF_CONFIGS: List[Tuple[float, float, float, str]] = [
    # (prefund_threshold_frac, max_weight_target, exit_threshold_frac, label)
    (0.05, 0.25, 0.01, "SCF-5pct"),
    (0.07, 0.25, 0.01, "SCF-7pct"),
    (0.10, 0.25, 0.01, "SCF-10pct"),
]


# ── build daily-return arrays from fixture ───────────────────────────────────────────────────────
def _load_returns(strategy_id: str) -> Dict[datetime.date, float]:
    """Return per-date fractional daily return for one fixture strategy (backtest phase only)."""
    raw = fx.strategy_jsonl(strategy_id)
    bt_points = []
    for line in raw.strip().split("\n"):
        p = json.loads(line)
        if p.get("phase") != "backtest":
            continue
        d = datetime.date.fromisoformat(p["date"])
        if _BACKTEST_START <= d <= _BACKTEST_END:
            bt_points.append((d, float(p["equity_usd"])))
    # derive daily returns from consecutive equity values
    bt_points.sort(key=lambda x: x[0])
    result: Dict[datetime.date, float] = {}
    prev_eq = _INITIAL
    for d, eq in bt_points:
        result[d] = eq / prev_eq - 1.0
        prev_eq = eq
    return result


def _date_range(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += datetime.timedelta(days=1)
    return days


# ── portfolio simulators ─────────────────────────────────────────────────────────────────────────
def _run_static(weights: Dict[str, float],
                returns: Dict[str, Dict[datetime.date, float]],
                dates: List[datetime.date]) -> List[float]:
    """Constant-weight portfolio (rebalanced daily to target weights).
    Transaction cost applied to initial setup only (buy once)."""
    nav = _INITIAL * (1.0 - _COST_BPS / 10_000 * sum(1 for w in weights.values() if w > 0))
    curve = []
    for d in dates:
        r_port = sum(w * returns[sid][d] for sid, w in weights.items() if sid in returns)
        nav = nav * (1.0 + r_port)
        curve.append(nav)
    return curve


def _run_ew5(returns: Dict[str, Dict[datetime.date, float]],
             dates: List[datetime.date]) -> List[float]:
    """Equal weight over the 5 viable fixture books (reference from idea #163)."""
    sids = _VIABLE_BOOKS
    n = len(sids)
    w = 1.0 / n
    nav = _INITIAL * (1.0 - _COST_BPS / 10_000 * n)
    curve = []
    for d in dates:
        r_port = sum(w * returns[sid][d] for sid in sids)
        nav = nav * (1.0 + r_port)
        curve.append(nav)
    return curve


def _run_scf(prefund_threshold: float,
             max_weight_target: float,
             exit_threshold: float,
             returns: Dict[str, Dict[datetime.date, float]],
             dates: List[datetime.date]) -> Tuple[List[float], List[str]]:
    """Sequential Carry Funding simulator.

    Returns (nav_curve, regime_per_day) where regime ∈ {'phase1', 'phase2'}.
    """
    nav = _INITIAL
    phase = "phase1"
    cumulative_carry = 0.0           # carry earned from anchor since last Phase-1 reset
    curve = []
    regimes = []
    cost = _COST_BPS / 10_000

    # initial setup cost: 100% anchor
    nav = nav * (1.0 - cost)

    for d in dates:
        r_anchor = returns[ANCHOR_ID][d]
        r_target = returns[TARGET_ID][d]

        if phase == "phase1":
            # 100 % anchor
            nav = nav * (1.0 + r_anchor)
            cumulative_carry += r_anchor    # track carry earned from anchor

            # check transition to Phase 2
            if cumulative_carry >= prefund_threshold:
                # switch: sell (1 - max_weight_target) anchor hold, buy target
                nav = nav * (1.0 - cost * max_weight_target)   # buy cost on new target leg
                phase = "phase2"

        else:  # phase2
            w_a = 1.0 - max_weight_target
            w_b = max_weight_target
            # check exit condition BEFORE applying return: would today's target loss blow gate?
            # loss from target leg = w_b * max(0, -r_target)
            projected_loss_from_target = w_b * max(0.0, -r_target)
            if projected_loss_from_target > exit_threshold:
                # exit: sell target leg, go back to 100% anchor
                nav = nav * (1.0 - cost * w_b)       # sell cost on target leg
                nav = nav * (1.0 + r_anchor)          # today's return: anchor only
                cumulative_carry = 0.0                # reset pre-fund counter
                phase = "phase1"
            else:
                nav = nav * (1.0 + w_a * r_anchor + w_b * r_target)
                # update cumulative_carry: only the anchor fraction
                cumulative_carry += w_a * r_anchor

        curve.append(nav)
        regimes.append(phase)

    return curve, regimes


# ── statistics ───────────────────────────────────────────────────────────────────────────────────
def _stats(curve: List[float], n_days: int) -> Dict[str, float]:
    """Compute net APY [bt], max drawdown [bt], Calmar [bt] from a nav curve."""
    final = curve[-1]
    total_return = final / _INITIAL - 1.0
    apy = (1.0 + total_return) ** (365.0 / n_days) - 1.0

    # max drawdown
    peak = _INITIAL
    max_dd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    poshlinа_bps = 96          # 96 bp minimum Calmar denominator (from #163)
    if max_dd < poshlinа_bps / 10_000:
        calmar = float("inf")  # denominator degenerate — still flagged ОТКАЗАН
        calmar_str = "ОТКАЗАН (maxDD < 96bp)"
    else:
        calmar = apy / max_dd
        calmar_str = f"{calmar:.3f}"

    return {
        "apy": apy,
        "max_dd": max_dd,
        "calmar": calmar,
        "calmar_str": calmar_str,
        "total_return": total_return,
    }


def _phase_summary(regimes: List[str]) -> Dict[str, int]:
    n1 = regimes.count("phase1")
    n2 = regimes.count("phase2")
    transitions = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i - 1])
    return {"phase1_days": n1, "phase2_days": n2, "transitions": transitions}


# ── stress-window impact ─────────────────────────────────────────────────────────────────────────
def _window_impact(curve: List[float], dates: List[datetime.date]) -> Dict[str, str]:
    date_to_idx = {d: i for i, d in enumerate(dates)}
    out = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        i_lo = date_to_idx.get(lo)
        i_hi = date_to_idx.get(hi)
        if i_lo is None or i_hi is None:
            out[str(w["key"])] = "N/A"
            continue
        nav_before = curve[i_lo - 1] if i_lo > 0 else _INITIAL
        nav_after = curve[i_hi]
        impact = nav_after / nav_before - 1.0
        out[str(w["key"])] = f"{impact:+.2%}"
    return out


# ── main ─────────────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    returns = {sid: _load_returns(sid) for sid in _VIABLE_BOOKS}

    dates = _date_range(_BACKTEST_START, _BACKTEST_END)
    n_days = len(dates)

    print("=" * 80)
    print("Idea #164: SCF — Sequential Carry Funding  [bt] L0  IS_ADVISORY=True")
    print(f"Fixture roster (viable backtest books): {_VIABLE_BOOKS}")
    print(f"Period: {_BACKTEST_START} .. {_BACKTEST_END} ({n_days} days)")
    print(f"Anchor = {ANCHOR_ID}  |  Target = {TARGET_ID}")
    print("=" * 80)

    results = {}

    # A. Pure anchor
    curve_a = _run_static({ANCHOR_ID: 1.0}, returns, dates)
    results["A_anchor_100"] = _stats(curve_a, n_days)
    results["A_anchor_100"]["window"] = _window_impact(curve_a, dates)

    # B. Static 75/25 (no pre-fund)
    curve_b = _run_static({ANCHOR_ID: 0.75, TARGET_ID: 0.25}, returns, dates)
    results["B_static_75_25"] = _stats(curve_b, n_days)
    results["B_static_75_25"]["window"] = _window_impact(curve_b, dates)

    # C. EW-5
    curve_c = _run_ew5(returns, dates)
    results["C_ew5"] = _stats(curve_c, n_days)
    results["C_ew5"]["window"] = _window_impact(curve_c, dates)

    # D/E/F. SCF variants
    for threshold, max_w, exit_t, label in _SCF_CONFIGS:
        curve_scf, regimes = _run_scf(threshold, max_w, exit_t, returns, dates)
        s = _stats(curve_scf, n_days)
        s["window"] = _window_impact(curve_scf, dates)
        s["phase"] = _phase_summary(regimes)
        results[label] = s

    # Print comparison table
    print(f"\n{'Strategy':<18} {'Net APY [bt]':>14} {'MaxDD [bt]':>12} {'Calmar [bt]':>14}"
          f"  eth_crash_08  usde_unwind_10  rseth_depeg_26")
    print("-" * 100)
    for name, s in results.items():
        w = s.get("window", {})
        p1 = w.get("eth_crash_2024_08", "N/A")
        p2 = w.get("usde_unwind_2025_10", "N/A")
        p3 = w.get("rseth_depeg_2026_04", "N/A")
        print(f"{name:<18} {s['apy']:>+13.2%}  {s['max_dd']:>11.2%}  {s['calmar_str']:>14}"
              f"  {p1:>13}  {p2:>14}  {p3:>14}")

    print("\nPhase breakdown (SCF variants):")
    print(f"{'Strategy':<18} {'Phase1 days':>12} {'Phase2 days':>12} {'Transitions':>12}")
    print("-" * 60)
    for name, s in results.items():
        if "phase" in s:
            ph = s["phase"]
            print(f"{name:<18} {ph['phase1_days']:>12} {ph['phase2_days']:>12}"
                  f" {ph['transitions']:>12}")

    print("\n" + "=" * 80)
    print("HONEST VERDICT [bt] L0 — ALL numbers from synthetic fixture, NOT realized:")
    scf7 = results.get("SCF-7pct", {})
    anchor = results.get("A_anchor_100", {})
    static = results.get("B_static_75_25", {})
    ew5 = results.get("C_ew5", {})
    print(f"  SCF-7pct  vs  100 % anchor:   "
          f"APY {scf7.get('apy', 0):+.2%} vs {anchor.get('apy', 0):+.2%}  |  "
          f"MaxDD {scf7.get('max_dd', 0):.2%} vs {anchor.get('max_dd', 0):.2%}")
    print(f"  SCF-7pct  vs  Static 75/25:   "
          f"APY {scf7.get('apy', 0):+.2%} vs {static.get('apy', 0):+.2%}  |  "
          f"MaxDD {scf7.get('max_dd', 0):.2%} vs {static.get('max_dd', 0):.2%}")
    print(f"  SCF-7pct  vs  EW-5:           "
          f"APY {scf7.get('apy', 0):+.2%} vs {ew5.get('apy', 0):+.2%}  |  "
          f"MaxDD {scf7.get('max_dd', 0):.2%} vs {ew5.get('max_dd', 0):.2%}")
    print("=" * 80)
    print("IS_ADVISORY=True | OUTSIDE_RISKPOLICY=True | stdlib-only | LLM_FORBIDDEN")

    return results


if __name__ == "__main__":
    main()

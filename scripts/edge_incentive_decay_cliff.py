#!/usr/bin/env python3
"""
scripts/edge_incentive_decay_cliff.py — Idea #133: IDC
Incentive Decay Cliff — adversarial hardening of MSD-KODS (#130)

NOVEL EDGE IDEA #133 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)

THE UNTESTED ANGLE (extending #130 MSD-KODS)
  Idea #130 showed that blending susde_dn + points_farm improves Calmar vs pure
  susde_dn under GRADUAL APY haircuts (100% → 75% → 50%). The explicit open caveat:
    "points_farm is class D (incentive_decay): fixture models CONSTANT drift, but
    real incentive programs decay."
  However, real incentive programs rarely decay gradually — they often cliff: a
  governance vote, a token price crash, or a program end causes yield to drop to
  ZERO overnight. The gradual haircut tested in #130 is the OPTIMISTIC scenario.

  This idea asks: does the MSD-KODS diversification benefit SURVIVE a cliff-style
  collapse of points_farm yield?

  Three scenarios per cliff date:
    A) After cliff: zero yield (you're still in, earning nothing, but still exposed)
    B) The blend KODS automatically downweights points_farm once it starts dragging
       (Kelly responds to lower composite μ)

CLIFF MODEL
  Before cliff_date:  use fixture returns as-is
  After cliff_date:   points_farm daily_return -= daily_drift
                      i.e. yield evaporates, principal still exposed to tail events

  This is MORE ADVERSARIAL than gradual haircut:
  (1) It's sudden — no time to exit
  (2) Principal stays in the risky position (still exposed to rsETH depeg, etc.)
  (3) Return on calm days becomes ~0; return on crisis days remains negative

CLIFF DATE SWEEP
  We test 5 cliff dates spanning the backtest period:
  - 2024-10-01: very early (barely 3 months in, before any crisis)
  - 2025-01-01: mid-backtest pre-crisis
  - 2025-07-01: pre-USDe unwind
  - 2025-10-01: START of USDe unwind window (worst timing: cliff = start of crisis)
  - 2026-01-01: post-major-crises

HYPOTHESIS
  H1: MSD-KODS 70s_30p benefit SHRINKS but SURVIVES cliff for most cliff dates.
  H2: Early cliff (2024-10-01) is worst — longest drag period.
  H3: Late cliff (2026-01-01) is nearly irrelevant — backtest mostly over.
  H4 (null): cliff at crisis start (2025-10-01) DESTROYS the blend advantage.

HONEST CAVEATS
  (a) Fixture σ²≈0 in calm — Kelly is near-binary; Kelly's response to cliff is
      triggered only if cliff happens during a low-volatility window (which it is).
  (b) This tests the COMPOSITION effect, not the SIZING effect: we hold w_alt fixed
      at 30% even after cliff (no blend rebalancing). A smarter allocator would exit.
  (c) Real scenario: governance vote cliff DOES give a day or two notice. Holding
      regardless is a conservative assumption.
  (d) Evidence: L0 (backtest/synthetic, fixture). NOT live results. IS_ADVISORY=True.
  (e) Do NOT import spa_core/execution; do NOT touch live paper track.

Advisory only. stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld   # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS                  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
RATES_APY_PCT  = 4.6
RWA_APY_PCT    = 3.31
RATES_DAILY    = RATES_APY_PCT / 100.0 / 365.0
RWA_DAILY      = RWA_APY_PCT   / 100.0 / 365.0
SAFE_DAILY     = (2.0 / 3.0) * RATES_DAILY + (1.0 / 3.0) * RWA_DAILY  # same as KODS #15

# KODS parameters (best from #15)
ALPHA          = 0.1
MAX_RISKY      = 0.25
LOOKBACK       = 10
MIN_VAR        = 1e-10

# points_farm fixture daily drift (from fixtures.py: 14% APY)
PF_DAILY_DRIFT = 14.0 / 100.0 / 365.0

# Cliff date sweep
CLIFF_DATES: List[str] = [
    "2024-10-01",   # very early
    "2025-01-01",   # mid-backtest
    "2025-07-01",   # pre-USDe unwind
    "2025-10-01",   # START of USDe unwind (worst timing)
    "2026-01-01",   # post-major-crises
    "NONE",         # no cliff (baseline = #130)
]

# Blend configs tested: susde_only and two MSD blends
BLEND_CONFIGS: List[Tuple[str, float, float]] = [
    ("susde_only", 1.00, 0.00),
    ("70s_30p",    0.70, 0.30),
    ("50s_50p",    0.50, 0.50),
]


# ── data loading ──────────────────────────────────────────────────────────────

def _load_base_returns() -> Dict[str, Dict[str, float]]:
    """Load daily fractional returns for susde_dn and points_farm from fixture."""
    tmp = Path(tempfile.mkdtemp(prefix="idc_"))
    fx.materialize(tmp)
    all_strats = ld.load_all(data_dir=tmp)

    all_returns: Dict[str, Dict[str, float]] = {}
    for sid in ("susde_dn", "points_farm"):
        s = all_strats.get(sid)
        if s is None or s.backtest.n_points < 60:
            raise RuntimeError(f"Strategy {sid} not available in fixture")
        eq: Dict[str, float] = {}
        for p in s.backtest.series:
            d_str = p.get("date")
            e = p.get("equity_usd", p.get("equity"))
            if d_str and e is not None:
                eq[d_str] = float(e)
        dates = sorted(eq.keys())
        rets: Dict[str, float] = {}
        for i in range(1, len(dates)):
            d_prev, d_curr = dates[i - 1], dates[i]
            if eq.get(d_prev, 0.0) > 0:
                rets[d_curr] = eq[d_curr] / eq[d_prev] - 1.0
        all_returns[sid] = rets
    return all_returns


def _apply_cliff(
    pf_returns: Dict[str, float],
    cliff_date: str,
) -> Dict[str, float]:
    """
    Apply cliff to points_farm returns: after cliff_date, subtract the daily
    drift so yield goes to zero. Principal stays exposed (crisis losses remain).
    """
    if cliff_date == "NONE":
        return dict(pf_returns)
    result: Dict[str, float] = {}
    for d, r in pf_returns.items():
        if d >= cliff_date:
            # yield evaporates: subtract the drift portion
            result[d] = r - PF_DAILY_DRIFT
        else:
            result[d] = r
    return result


def _composite_returns(
    returns_susde: Dict[str, float],
    returns_pf: Dict[str, float],
    w_susde: float,
    w_pf: float,
) -> Dict[str, float]:
    """Weighted composite daily returns over common date range."""
    if w_pf == 0.0:
        return dict(returns_susde)
    common = sorted(set(returns_susde.keys()) & set(returns_pf.keys()))
    return {d: w_susde * returns_susde[d] + w_pf * returns_pf[d] for d in common}


# ── KODS engine ───────────────────────────────────────────────────────────────

def _run_kods(
    composite_rets: Dict[str, float],
    label: str,
) -> dict:
    """Apply KODS Kelly sizing to a composite risky portfolio."""
    dates = sorted(composite_rets.keys())
    if not dates:
        return {}

    eq     = 100_000.0
    hwm    = eq
    max_dd = 0.0
    rets_list = [composite_rets[d] for d in dates]

    crisis_windows_set: Dict[str, Tuple[str, str]] = {
        w["key"]: (str(w["date_from"]), str(w["date_to"])) for w in STRESS_WINDOWS
    }
    crisis_track: Dict[str, List[float]] = {k: [] for k in crisis_windows_set}

    for i, d in enumerate(dates):
        if i < LOOKBACK:
            f_active = MAX_RISKY
        else:
            window_rets = rets_list[i - LOOKBACK: i]
            mu_w = sum(window_rets) / LOOKBACK
            excess_mu = mu_w - RATES_DAILY
            var_w = sum((r - mu_w) ** 2 for r in window_rets) / LOOKBACK
            var_w = max(var_w, MIN_VAR)
            kelly = ALPHA * max(0.0, excess_mu / var_w)
            f_active = min(kelly, MAX_RISKY)

        port_ret = f_active * composite_rets[d] + (1.0 - f_active) * SAFE_DAILY
        eq *= 1.0 + port_ret
        hwm = max(hwm, eq)
        dd = (hwm - eq) / hwm
        max_dd = max(max_dd, dd)

        for key, (lo, hi) in crisis_windows_set.items():
            if lo <= d <= hi:
                crisis_track[key].append(eq)

    n_days = len(dates)
    annual_return = (eq / 100_000.0) ** (365.0 / n_days) - 1.0
    calmar = (annual_return * 100.0) / (max_dd * 100.0) if max_dd > 1e-9 else 999.99

    crisis_dd: Dict[str, float] = {}
    for key, vals in crisis_track.items():
        if vals:
            peak, trough = max(vals), min(vals)
            crisis_dd[key] = (peak - trough) / peak * 100.0
        else:
            crisis_dd[key] = 0.0

    return {
        "label":      label,
        "n_days":     n_days,
        "apy_pct":    annual_return * 100.0,
        "max_dd_pct": max_dd * 100.0,
        "calmar":     calmar,
        "crisis_dd":  crisis_dd,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sep = "=" * 78
    print(sep)
    print("Idea #133 IDC: Incentive Decay Cliff — MSD-KODS hardening")
    print("Advisory only. Evidence: L0 (backtest/synthetic, fixture). NOT live.")
    print(sep)

    crisis_keys = [w["key"] for w in STRESS_WINDOWS]
    base_returns = _load_base_returns()
    susde_rets   = base_returns["susde_dn"]
    pf_rets_base = base_returns["points_farm"]

    # Header
    hdr_crisis = "  ".join(f"{k[:12]:>13}" for k in crisis_keys)
    hdr = (f"\n{'Cliff date':<14} {'Config':<14} {'APY%':>7} {'maxDD%':>7} "
           f"{'Calmar':>7}  {hdr_crisis}")
    row_sep = "-" * (14 + 14 + 7 + 7 + 7 + 3 + 13 * len(crisis_keys) + 3)

    print(hdr)
    print(row_sep)

    # Results table: collect for delta analysis
    results: Dict[str, Dict[str, dict]] = {}  # cliff_date -> blend_label -> metrics

    for cliff_date in CLIFF_DATES:
        pf_cliffed = _apply_cliff(pf_rets_base, cliff_date)
        results[cliff_date] = {}

        for blend_label, w_s, w_p in BLEND_CONFIGS:
            comp = _composite_returns(susde_rets, pf_cliffed, w_s, w_p)
            r = _run_kods(comp, blend_label)
            results[cliff_date][blend_label] = r

            crisis_part = "  ".join(
                f"{r['crisis_dd'].get(k, 0.0):>12.3f}%" for k in crisis_keys
            )
            print(
                f"{cliff_date:<14} {blend_label:<14} {r['apy_pct']:>7.3f} "
                f"{r['max_dd_pct']:>7.3f} {r['calmar']:>7.2f}  {crisis_part}"
            )
        print()

    # ── Delta analysis: blend advantage under each cliff ────────────────────
    print(f"\n{'─'*78}")
    print("  DELTA ANALYSIS: ΔCalmar of blend vs susde_only under each cliff date")
    print(f"{'─'*78}")
    print(f"\n{'Cliff date':<14} {'70s_30p ΔCalmar':>17} {'50s_50p ΔCalmar':>17}  "
          "  Verdict")
    print("-" * 78)

    for cliff_date in CLIFF_DATES:
        base_calmar = results[cliff_date]["susde_only"]["calmar"]
        d70  = results[cliff_date]["70s_30p"]["calmar"] - base_calmar
        d50  = results[cliff_date]["50s_50p"]["calmar"] - base_calmar
        verdict = ""
        if d70 > 0.0 and d50 > 0.0:
            verdict = "BLEND WINS"
        elif d70 > 0.0 or d50 > 0.0:
            verdict = "PARTIAL"
        else:
            verdict = "BLEND LOSES"
        print(f"{cliff_date:<14} {d70:>+17.3f} {d50:>+17.3f}    {verdict}")

    # ── Reference from registry ──────────────────────────────────────────────
    print(f"\n{'─'*78}")
    print("  REFERENCE:")
    print("    KODS #15 (susde_only, no cliff): APY 5.048% / maxDD 1.109% / Calmar 4.55")
    print("    MSD-KODS #130 70s_30p (no cliff): Calmar ~5.81 (+27%)")
    print("    MSD-KODS #130 50s_50p (no cliff): Calmar ~7.20 (+58%)")
    print("    RWA floor: ~3.4% APY (Conservative tier)")
    print(f"{'─'*78}")

    print(f"\n{'═'*78}")
    print("HONEST CAVEATS (mandatory, evidence L0/backtest):")
    print("(a) Cliff model: drift removed, tail exposure KEPT. Real cliff may allow exit.")
    print("    Conservative assumption: no exit possible before crisis.")
    print("(b) σ²≈0 in calm (fixture): Kelly near-binary. Cliff doesn't trigger early exit.")
    print("    Kelly only responds to cliff after LOOKBACK=10 days of post-cliff returns.")
    print("(c) Blend composition fixed at {w_s}/{w_p} throughout — no rebalance on cliff.")
    print("    A smarter allocator with cliff-detection would exit immediately.")
    print("(d) Fixture has 5 strategies; points_farm = class D (incentive_decay).")
    print("    Real incentive programs: decay timeline varies 3–18 months post-TGE.")
    print("(e) IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True. NOT for live deployment.")
    print(f"{'═'*78}")


if __name__ == "__main__":
    main()

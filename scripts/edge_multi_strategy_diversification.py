#!/usr/bin/env python3
"""
scripts/edge_multi_strategy_diversification.py — Idea #130: MSD-KODS
Multi-Strategy Diversification with KODS

NOVEL EDGE IDEA #130 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)

THE UNTESTED ANGLE
  Every previous idea (#3–#129) used a SINGLE risky asset (susde_dn) in the risky sleeve
  and varied HOW to time entry/exit (Kelly, DDO, EMA crossover, vol term structure, etc.).
  The risky-sleeve COMPOSITION was never varied.

  This idea asks: does DIVERSIFYING the risky sleeve across two strategies with DIFFERENT
  crisis sensitivities reduce tail risk WITHOUT sacrificing carry?

  KODS #15 (Calmar-leader, 4.55) holds:
      f*(t) × susde_dn + (1 - f*(t)) × safe_leg

  MSD-KODS holds instead:
      f*(t) × [W_1 × susde_dn + W_2 × alt_strategy] + (1 - f*(t)) × safe_leg

  The Kelly signal f*(t) is applied to the COMPOSITE portfolio of strategies.

CRISIS ASYMMETRY (the economic rationale)
  Crisis sensitivities from fixture (total loss over window):

  Strategy      | ETH crash  | USDe unwind | rsETH depeg | APY
  --------------|------------|-------------|-------------|------
  susde_dn      |   3.0%     |    9.0%     |    1.0%     | 11%
  points_farm   |   1.0%     |    2.0%     |    1.5%     | 14%
  lrt_carry     |   5.0%     |    4.0%     |   22.0%     | 13%

  OBSERVATION: points_farm has LOWER crisis losses in ALL three windows AND higher APY.
  This means: a portfolio that holds [susde_dn + points_farm] has:
    (A) Higher composite APY in calm
    (B) Smaller composite crisis losses → smaller day-1 hit → lower maxDD
    (C) Faster post-crisis recovery (smaller negative μ → Kelly exits DEFEND sooner)

  lrt_carry: IMPROVES USDe exposure but CATASTROPHICALLY worsens rsETH.
  → Test lrt_carry too but expect it to reduce Calmar.

HYPOTHESIS
  H1 (main): susde_dn + points_farm blend IMPROVES Calmar vs pure susde_dn.
  H2: The improvement comes from reduced day-1 hit AND faster recovery.
  H3 (null): points_farm incentive decay erases the advantage in real markets.
  H4: lrt_carry blending HURTS Calmar due to rsETH tail amplification.

HONEST CAVEATS
  (a) points_farm is class D (incentive_decay): fixture models CONSTANT drift, but real
      incentive programs decay. Sensitivity: run with 50% APY haircut on points_farm.
  (b) σ²≈0 in calm (fixture artifact): Kelly is binary in calm regardless of composite.
  (c) Day-1 hit unavoidable; MSD-KODS reduces its size but cannot eliminate it.
  (d) lrt_carry rsETH tail (22%) amplifies rsETH depeg risk in any blend.
  (e) Evidence: L0 (backtest/synthetic). NOT live results. IS_ADVISORY=True.
  (f) Do NOT import spa_core/execution; do NOT touch live paper track.

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
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS                 # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
RATES_APY_PCT  = 4.6
RWA_APY_PCT    = 3.31
RATES_DAILY    = RATES_APY_PCT / 100.0 / 365.0
RWA_DAILY      = RWA_APY_PCT   / 100.0 / 365.0
SAFE_DAILY     = (2.0 / 3.0) * RATES_DAILY + (1.0 / 3.0) * RWA_DAILY  # same as KODS #15

# KODS parameters (best from #15)
ALPHA          = 0.1
MAX_RISKY      = 0.25
LOOKBACK       = 10          # same as KODS #15 for apples-to-apples
MIN_VAR        = 1e-10

# points_farm APY haircut sweep (to test incentive-decay sensitivity)
HAIRCUT_GRID   = [1.00, 0.75, 0.50]   # 1.00 = fixture as-is; 0.50 = 50% APY decay

# Blend configs: (label, w_susde, w_alt, alt_strategy)
BLEND_CONFIGS: List[Tuple[str, float, float, str]] = [
    ("susde_only",       1.00, 0.00, "susde_dn"),     # baseline = KODS #15
    ("80s_20p",          0.80, 0.20, "points_farm"),
    ("70s_30p",          0.70, 0.30, "points_farm"),
    ("60s_40p",          0.60, 0.40, "points_farm"),
    ("50s_50p",          0.50, 0.50, "points_farm"),
    ("80s_20l",          0.80, 0.20, "lrt_carry"),    # negative control
    ("50s_50l",          0.50, 0.50, "lrt_carry"),    # negative control (rsETH tail)
]


# ── data loading ──────────────────────────────────────────────────────────────

def _load_all_returns(haircut_pf: float = 1.0) -> Dict[str, Dict[str, float]]:
    """
    Load daily fractional returns for susde_dn, points_farm, lrt_carry from fixture.
    haircut_pf: APY multiplier for points_farm (1.0 = fixture as-is, 0.5 = 50% decay).
    """
    tmp = Path(tempfile.mkdtemp(prefix="msd_"))
    fx.materialize(tmp)
    all_strats = ld.load_all(data_dir=tmp)

    all_returns: Dict[str, Dict[str, float]] = {}
    for sid in ("susde_dn", "points_farm", "lrt_carry"):
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

    # Apply incentive-decay haircut to points_farm (linear scaling of returns)
    # This is an approximation: lower APY ≈ lower daily returns proportionally
    if haircut_pf != 1.0 and "points_farm" in all_returns:
        pf_spec_apy = 14.0 / 100.0 / 365.0   # fixture daily drift
        pf_new_apy  = pf_spec_apy * haircut_pf
        # For the fixture's smooth drift, returns ≈ daily_drift in calm
        # Shift down by the APY difference (conservative: subtract from each return)
        delta = pf_spec_apy - pf_new_apy
        all_returns["points_farm"] = {
            d: r - delta for d, r in all_returns["points_farm"].items()
        }

    return all_returns


def _composite_returns(
    returns1: Dict[str, float],
    returns2: Dict[str, float],
    w1: float,
    w2: float,
) -> Dict[str, float]:
    """Weighted composite daily returns over common date range."""
    if w2 == 0.0:
        return dict(returns1)
    common_dates = sorted(set(returns1.keys()) & set(returns2.keys()))
    return {d: w1 * returns1[d] + w2 * returns2[d] for d in common_dates}


# ── KODS engine ───────────────────────────────────────────────────────────────

def _run_kods_on_composite(
    composite_rets: Dict[str, float],
    label: str,
    lkb: int = LOOKBACK,
) -> dict:
    """
    Apply KODS Kelly sizing to a composite risky portfolio.
    Portfolio = f*(t) × composite + (1 - f*(t)) × safe_leg
    """
    dates = sorted(composite_rets.keys())
    if not dates:
        return {}

    eq      = 100_000.0
    hwm     = eq
    max_dd  = 0.0
    rets_list = [composite_rets[d] for d in dates]

    crisis_windows_set: Dict[str, Tuple[str, str]] = {
        w["key"]: (str(w["date_from"]), str(w["date_to"])) for w in STRESS_WINDOWS
    }

    # Per-crisis tracking: record portfolio values during each crisis window
    crisis_track: Dict[str, List[float]] = {k: [] for k in crisis_windows_set}

    for i, d in enumerate(dates):
        # Kelly signal: use lookback window of COMPOSITE returns
        if i < lkb:
            # Warmup: use full allocation (same as KODS warmup)
            f_active = MAX_RISKY
        else:
            window_rets = rets_list[i - lkb : i]
            mu_w = sum(window_rets) / lkb
            excess_mu = mu_w - RATES_DAILY
            var_w = sum((r - mu_w) ** 2 for r in window_rets) / lkb
            var_w = max(var_w, MIN_VAR)
            kelly = ALPHA * max(0.0, excess_mu / var_w)
            f_active = min(kelly, MAX_RISKY)

        port_ret = f_active * composite_rets[d] + (1.0 - f_active) * SAFE_DAILY
        eq *= 1.0 + port_ret

        hwm = max(hwm, eq)
        dd = (hwm - eq) / hwm
        max_dd = max(max_dd, dd)

        # record per-crisis
        for key, (lo, hi) in crisis_windows_set.items():
            if lo <= d <= hi:
                crisis_track[key].append(eq)

    n_days = len(dates)
    annual_return = (eq / 100_000.0) ** (365.0 / n_days) - 1.0

    calmar = (annual_return * 100.0) / (max_dd * 100.0) if max_dd > 1e-9 else 999.99

    # Per-crisis drawdown: peak-to-trough within the window
    crisis_dd: Dict[str, float] = {}
    for key, vals in crisis_track.items():
        if not vals:
            crisis_dd[key] = 0.0
        else:
            peak = max(vals)
            trough = min(vals)
            crisis_dd[key] = (peak - trough) / peak * 100.0

    return {
        "label":           label,
        "n_days":          n_days,
        "final_eq":        eq,
        "apy_pct":         annual_return * 100.0,
        "max_dd_pct":      max_dd * 100.0,
        "calmar":          calmar,
        "crisis_dd":       crisis_dd,
    }


# ── static blend baseline ─────────────────────────────────────────────────────

def _run_static(
    composite_rets: Dict[str, float],
    label: str,
) -> dict:
    """Static allocation: MAX_RISKY in composite + (1-MAX_RISKY) safe."""
    dates = sorted(composite_rets.keys())
    eq = 100_000.0
    hwm = eq
    max_dd = 0.0

    crisis_windows_set = {w["key"]: (str(w["date_from"]), str(w["date_to"])) for w in STRESS_WINDOWS}
    crisis_track: Dict[str, List[float]] = {k: [] for k in crisis_windows_set}

    for d in dates:
        port_ret = MAX_RISKY * composite_rets[d] + (1.0 - MAX_RISKY) * SAFE_DAILY
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
    crisis_dd = {}
    for key, vals in crisis_track.items():
        if vals:
            peak, trough = max(vals), min(vals)
            crisis_dd[key] = (peak - trough) / peak * 100.0
        else:
            crisis_dd[key] = 0.0

    return {
        "label": f"static_{label}",
        "apy_pct": annual_return * 100.0,
        "max_dd_pct": max_dd * 100.0,
        "calmar": calmar,
        "crisis_dd": crisis_dd,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sep = "=" * 72
    print(sep)
    print("Idea #28: Multi-Strategy Diversification with KODS (MSD-KODS)")
    print("Advisory only. Evidence: L0 (backtest/synthetic, fixture). NOT live.")
    print(sep)

    crisis_keys = [w["key"] for w in STRESS_WINDOWS]

    for haircut in HAIRCUT_GRID:
        print(f"\n{'─'*72}")
        print(f"  points_farm APY haircut: {haircut*100:.0f}%  (1.0 = fixture as-is, 0.5 = decay)")
        print(f"{'─'*72}")

        all_rets = _load_all_returns(haircut_pf=haircut)

        print(f"\n{'Config':<22} {'APY%':>7} {'maxDD%':>7} {'Calmar':>7}  "
              + "  ".join(f"{k[:13]:>14}" for k in crisis_keys))
        print("-" * (22 + 7 + 7 + 7 + 3 + 14 * len(crisis_keys)))

        for label, w_susde, w_alt, alt_strat in BLEND_CONFIGS:
            alt_rets = all_rets[alt_strat] if alt_strat != "susde_dn" else all_rets["susde_dn"]
            comp = _composite_returns(all_rets["susde_dn"], alt_rets, w_susde, w_alt)

            r = _run_kods_on_composite(comp, label)
            crisis_part = "  ".join(
                f"{r['crisis_dd'].get(k, 0):>13.3f}%" for k in crisis_keys
            )
            print(
                f"{label:<22} {r['apy_pct']:>7.3f} {r['max_dd_pct']:>7.3f} {r['calmar']:>7.2f}"
                f"  {crisis_part}"
            )

    # ── Incentive decay sensitivity: best blend (70s_30p) across haircuts ─────
    print(f"\n{'─'*72}")
    print("  SENSITIVITY: 70% susde_dn + 30% points_farm across APY haircuts")
    print(f"{'─'*72}")
    print(f"\n{'Haircut':>10} {'APY%':>7} {'maxDD%':>7} {'Calmar':>7}  "
          + "  ".join(f"{k[:13]:>14}" for k in crisis_keys))
    print("-" * (10 + 7 + 7 + 7 + 3 + 14 * len(crisis_keys)))
    for haircut in HAIRCUT_GRID + [0.25]:   # add 25% scenario
        all_rets = _load_all_returns(haircut_pf=haircut)
        comp = _composite_returns(all_rets["susde_dn"], all_rets["points_farm"], 0.70, 0.30)
        r = _run_kods_on_composite(comp, "70s_30p")
        crisis_part = "  ".join(f"{r['crisis_dd'].get(k, 0):>13.3f}%" for k in crisis_keys)
        print(
            f"{haircut*100:>9.0f}%  {r['apy_pct']:>7.3f} {r['max_dd_pct']:>7.3f} {r['calmar']:>7.2f}"
            f"  {crisis_part}"
        )

    # ── Reference: KODS #15 and static #3 ─────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  REFERENCE (from registry):")
    print("    static_3  : APY 4.264% / maxDD 2.105% / Calmar 2.03")
    print("    KODS #15  : APY 5.048% / maxDD 1.109% / Calmar 4.55")
    print(f"{'─'*72}")

    print(f"\n{'═'*72}")
    print("HONEST CAVEATS (mandatory):")
    print("(a) points_farm class D (incentive_decay): fixture drift CONSTANT, real decay 50–75%+")
    print("    → sensitivity at 50% haircut is the MINIMUM honest estimate for points_farm.")
    print("(b) σ²≈0 in calm (fixture): Kelly binary; composite doesn't change regime detection timing.")
    print("(c) Day-1 hit reduced by blending, but NOT eliminated.")
    print("(d) lrt_carry blends shown as NEGATIVE CONTROL: rsETH tail dominates.")
    print("(e) Evidence: L0 backtest/synthetic. NEVER present as live/realized results.")
    print("(f) IS_ADVISORY=True. Do NOT use to gate real capital.")
    print(f"{'═'*72}\n")


if __name__ == "__main__":
    main()

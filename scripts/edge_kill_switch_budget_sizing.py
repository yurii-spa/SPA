"""
scripts/edge_kill_switch_budget_sizing.py — Idea #32: Kill-Switch-Budget-Aware Position Sizing (KSBS)

ADVISORY / RESEARCH ONLY. IS_ADVISORY=True. Does NOT touch spa_core/execution, live paper track,
or RiskPolicy v1.0. stdlib-only, deterministic. LLM FORBIDDEN.

Evidence level: L0 (synthetic stress-fixture, NOT realised). All outputs labelled [bt].

Idea:
  The two-tier kill-switch (ADR-034/048) fires at SOFT=−5% and HARD=−10% drawdown from HWM.
  None of ideas #1–#31 linked position sizing directly to the REMAINING BUDGET before these tiers.
  KSBS does exactly that:

      budget_soft(t) = max(0, (SOFT - dd(t)) / SOFT)     # 1.0 at HWM, 0.0 at SOFT threshold
      w_susde(t)     = MAX_RISKY × budget_soft(t)

  where dd(t) = (hwm − equity(t)) / hwm  (causal; uses only equity through day t−1).

  This is governance-anchored (uses ADR-034/048 thresholds, not data-derived thresholds), fully
  causal (no look-ahead), and structurally distinct from DDO (#9), CPPI (#11), and KODS (#15).

Benchmark: static #3 portfolio (25% susde_dn / 75% RWA floor at 3.4% APY flat).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ── make spa_core importable when run directly ────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.strategy_lab.aggressive_lab.fixtures import (  # noqa: E402
    _build_backtest_series,
    _SPEC,
    _BACKTEST_START,
    _BACKTEST_END,
)
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────────────────────────
SOFT_THRESH = 0.05   # ADR-034/048 SOFT_DERISK threshold
HARD_THRESH = 0.10   # ADR-034/048 HARD_KILL threshold
RWA_DAILY   = 0.034 / 365.0   # conservative floor (3.4% APY flat)
MAX_RISKY   = 1.0   # max sUSDe_dn weight when budget is full
INITIAL     = 100_000.0

# ── helpers ───────────────────────────────────────────────────────────────────────────────────────

def _load_susde_daily() -> List[Tuple[datetime.date, float]]:
    """Returns list of (date, daily_return) from the susde_dn fixture backtest series."""
    spec = _SPEC["susde_dn"]
    series = _build_backtest_series(spec)
    result: List[Tuple[datetime.date, float]] = []
    prev_eq = INITIAL
    for row in series:
        d = datetime.date.fromisoformat(row["date"])
        eq = float(row["equity_usd"])
        # daily return from the raw equity series
        daily_ret = (eq - prev_eq) / prev_eq
        result.append((d, daily_ret))
        prev_eq = eq
    return result


def _in_window(d: datetime.date) -> str | None:
    """Return stress-window key if date is inside a crisis window, else None."""
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= d <= hi:
            return str(w["key"])
    return None


def _metrics(equity_curve: List[float]) -> dict:
    """Compute annual return, max drawdown, Calmar from a daily equity curve (INITIAL=100k)."""
    n = len(equity_curve)
    if n < 2:
        return {"apy_pct": 0.0, "max_dd_pct": 0.0, "calmar": 0.0}
    annual_return = (equity_curve[-1] / equity_curve[0]) ** (365.0 / n) - 1.0
    hwm = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > hwm:
            hwm = eq
        dd = (hwm - eq) / hwm
        if dd > max_dd:
            max_dd = dd
    calmar = annual_return / max_dd if max_dd > 1e-9 else float("inf")
    return {
        "apy_pct": round(annual_return * 100, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 2),
    }


# ── static baseline (#3): 25% susde_dn + 75% RWA floor ──────────────────────────────────────────

def run_baseline(susde_daily: List[Tuple[datetime.date, float]]) -> Tuple[List[float], Dict]:
    """Static portfolio: always 25% risky (susde_dn) + 75% RWA floor."""
    equity = INITIAL
    curve = [equity]
    crisis_details: Dict[str, dict] = {}
    for d, susde_ret in susde_daily:
        rwa_ret = RWA_DAILY
        daily = 0.25 * susde_ret + 0.75 * rwa_ret
        equity = equity * (1.0 + daily)
        curve.append(equity)
        wk = _in_window(d)
        if wk:
            crisis_details.setdefault(wk, {"start": equity, "min": equity})
            crisis_details[wk]["min"] = min(crisis_details[wk]["min"], equity)
            crisis_details[wk]["end"] = equity
    return curve, crisis_details


# ── KSBS strategy ─────────────────────────────────────────────────────────────────────────────────

def run_ksbs(
    susde_daily: List[Tuple[datetime.date, float]],
    use_hard_budget: bool = False,
) -> Tuple[List[float], Dict]:
    """
    KSBS: daily weight = MAX_RISKY × budget_soft(t−1)
    budget_soft(t) = max(0, (SOFT_THRESH − drawdown_from_hwm(t)) / SOFT_THRESH)

    If use_hard_budget=True, also blends in the budget relative to HARD threshold:
      w = MAX_RISKY × sqrt(budget_soft × budget_hard)   (geometric mean)

    Position sizing is causal: uses HWM and equity from end-of-prior-day.
    """
    equity = INITIAL
    hwm = INITIAL
    curve = [equity]
    crisis_details: Dict[str, dict] = {}
    weights: List[float] = []
    for d, susde_ret in susde_daily:
        # compute causal drawdown (from prior-day equity / hwm)
        dd = (hwm - equity) / hwm if hwm > 0 else 0.0
        budget_soft = max(0.0, (SOFT_THRESH - dd) / SOFT_THRESH)
        if use_hard_budget:
            budget_hard = max(0.0, (HARD_THRESH - dd) / HARD_THRESH)
            w_susde = MAX_RISKY * (budget_soft * budget_hard) ** 0.5
        else:
            w_susde = MAX_RISKY * budget_soft
        w_rwa = 1.0 - w_susde
        weights.append(w_susde)
        daily = w_susde * susde_ret + w_rwa * RWA_DAILY
        equity = equity * (1.0 + daily)
        if equity > hwm:
            hwm = equity
        curve.append(equity)
        wk = _in_window(d)
        if wk:
            crisis_details.setdefault(wk, {"start": equity, "min": equity})
            crisis_details[wk]["min"] = min(crisis_details[wk]["min"], equity)
            crisis_details[wk]["end"] = equity
    avg_w = sum(weights) / len(weights) if weights else 0.0
    return curve, crisis_details, round(avg_w, 3)


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    susde_daily = _load_susde_daily()
    n_days = len(susde_daily)
    date_start = susde_daily[0][0].isoformat()
    date_end = susde_daily[-1][0].isoformat()

    print("=" * 72)
    print("KSBS — Kill-Switch-Budget-Aware Position Sizing  [bt] [L0 evidence]")
    print(f"Fixture: susde_dn ({date_start}..{date_end}, {n_days} days)")
    print("SOFT_THRESH=−5%  HARD_THRESH=−10%  (ADR-034/048 governance thresholds)")
    print("=" * 72)

    # Baseline
    bl_curve, bl_crisis = run_baseline(susde_daily)
    bl_m = _metrics(bl_curve)
    print()
    print("── BASELINE (static #3: 25% susde_dn + 75% RWA @ 3.4%) ──────────────")
    print(f"  APY [bt]:      {bl_m['apy_pct']:.2f}%")
    print(f"  Max DD [bt]:   {bl_m['max_dd_pct']:.2f}%")
    print(f"  Calmar [bt]:   {bl_m['calmar']:.2f}")
    for wk, cd in sorted(bl_crisis.items()):
        dd_crisis = (cd["start"] - cd["min"]) / cd["start"] * 100
        print(f"  Crisis {wk}: peak-to-trough −{dd_crisis:.1f}%")

    # KSBS (soft budget only)
    ks_curve, ks_crisis, avg_w_soft = run_ksbs(susde_daily, use_hard_budget=False)
    ks_m = _metrics(ks_curve)
    print()
    print("── KSBS-SOFT (w = MAX × budget_soft) ────────────────────────────────")
    print(f"  Avg risky weight: {avg_w_soft*100:.1f}% (vs 25% static)")
    print(f"  APY [bt]:         {ks_m['apy_pct']:.2f}%")
    print(f"  Max DD [bt]:      {ks_m['max_dd_pct']:.2f}%")
    print(f"  Calmar [bt]:      {ks_m['calmar']:.2f}")
    for wk, cd in sorted(ks_crisis.items()):
        dd_crisis = (cd["start"] - cd["min"]) / cd["start"] * 100
        print(f"  Crisis {wk}: peak-to-trough −{dd_crisis:.1f}%")

    # KSBS (geometric mean of soft + hard budgets)
    ksg_curve, ksg_crisis, avg_w_geo = run_ksbs(susde_daily, use_hard_budget=True)
    ksg_m = _metrics(ksg_curve)
    print()
    print("── KSBS-GEO (w = MAX × sqrt(budget_soft × budget_hard)) ─────────────")
    print(f"  Avg risky weight: {avg_w_geo*100:.1f}% (vs 25% static)")
    print(f"  APY [bt]:         {ksg_m['apy_pct']:.2f}%")
    print(f"  Max DD [bt]:      {ksg_m['max_dd_pct']:.2f}%")
    print(f"  Calmar [bt]:      {ksg_m['calmar']:.2f}")
    for wk, cd in sorted(ksg_crisis.items()):
        dd_crisis = (cd["start"] - cd["min"]) / cd["start"] * 100
        print(f"  Crisis {wk}: peak-to-trough −{dd_crisis:.1f}%")

    # Delta summary
    print()
    print("── DELTA vs BASELINE ─────────────────────────────────────────────────")
    for label, m in [("KSBS-SOFT", ks_m), ("KSBS-GEO", ksg_m)]:
        dapy = m["apy_pct"] - bl_m["apy_pct"]
        ddd  = m["max_dd_pct"] - bl_m["max_dd_pct"]
        dcal = m["calmar"] - bl_m["calmar"]
        sign_apy = "+" if dapy >= 0 else ""
        sign_dd  = "+" if ddd  >= 0 else ""
        sign_cal = "+" if dcal >= 0 else ""
        print(f"  {label}: ΔAPY={sign_apy}{dapy:.2f}%  ΔDD={sign_dd}{ddd:.2f}%  ΔCalmar={sign_cal}{dcal:.2f}")

    # Verdict
    best_calmar = max(ks_m["calmar"], ksg_m["calmar"])
    best_label  = "KSBS-SOFT" if ks_m["calmar"] >= ksg_m["calmar"] else "KSBS-GEO"
    bl_calmar   = bl_m["calmar"]
    print()
    print("── VERDICT ──────────────────────────────────────────────────────────")
    if best_calmar > bl_calmar * 1.05:
        verdict = "✅ УЛУЧШАЕТ риск/доходность vs baseline"
    elif best_calmar > bl_calmar * 0.95:
        verdict = "⚠️ НЕЙТРАЛЬНЫЙ — схожий Calmar, другое распределение DD"
    else:
        verdict = "❌ НЕ УЛУЧШАЕТ — baseline сильнее по Calmar"
    print(f"  {verdict}")
    print(f"  Лучший вариант: {best_label}, Calmar [bt] = {best_calmar:.2f}")
    print(f"  Baseline Calmar [bt] = {bl_calmar:.2f}")
    print()
    print("NOTE: все числа — [bt] [L0], синтетический стресс-фикстур, не реальные данные.")
    print("IS_ADVISORY=True. Не трогает spa_core/execution, RiskPolicy v1.0, live-трек.")


if __name__ == "__main__":
    main()

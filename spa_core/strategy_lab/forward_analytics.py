"""
spa_core/strategy_lab/forward_analytics.py — risk-adjusted analytics ON the LIVE accruing
forward series (rates-desk FixedCarry + each Strategy-Lab sleeve).

WHY THIS EXISTS (T4+T5 sprint): generate_fundability_onepager.py reads a VERDICT
(rates_desk_promotion.json) but NOTHING computes risk-adjusted metrics ON the forward series
THEMSELVES. The series in data/rates_desk/paper/*_series.json + data/strategy_lab_paper/
*_series.json grow one point per UTC day. At day 30 (target 2026-07-21) they become the
FUNDABLE evidence — but evidence needs honest risk-adjusted measurement, attribution against the
~3.4% RWA risk-free floor, and a stress overlay on the REALIZED record (not just the backtest).

This module is the tooling that turns the accruing forward tracks into that scorecard:

  T4 — risk-adjusted attribution on the live forward series
    • ingest one *_series.json, VALIDATE via track_integrity (gaps/dups/out-of-order/future →
      fail-CLOSED → verdict UNKNOWN, NEVER a fabricated number),
    • compute (REUSING metrics.py — NOT reinvented): realized Sharpe, Sortino, max-drawdown,
      annualized vol, annualized return — HONEST:
        – fewer than MIN_POINTS_FOR_RATIO usable points → ratio = UNKNOWN (a 2-point Sharpe is a
          degenerate artifact, not a risk-adjusted score),
        – a locked-volatility book (fixed-rate accrual whose only "variance" is float noise) →
          metrics.sharpe()/sortino() return None; we FLAG locked_vol and report UNKNOWN, never a
          fabricated ~4.5e8 Sharpe (the documented degenerate-Sharpe hazard),
    • ATTRIBUTION vs the live ~3.4% RWA floor: excess annualized return decomposed into the floor
      leg and the carry-above-floor leg (how much of the realized return is genuine excess).

  T5 — drawdown + stress overlay on the forward record
    • apply the CANONICAL 2024–2026 stress scenarios (the same PT mark-down shocks the promotion
      gate uses — NO looser) to the CURRENTLY-HELD carry-book composition (read from the rates-desk
      paper state), measuring worst-case DD on the realized forward equity + the shock,
    • per scenario: stress DD % and survives:bool (DD within the promotion drawdown band),
      consistent with levered_stress.MAX_DD_BAND_PCT semantics.

Emits a deterministic risk-adjusted scorecard → data/forward_analytics.json (atomic).

stdlib-only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN. Advisory: reads the forward
series + the live floor; never moves capital, never touches execution/*, never blocks a tick.

Run:  python3 -m spa_core.strategy_lab.forward_analytics
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.strategy_lab import metrics
from spa_core.strategy_lab import track_integrity as ti

log = logging.getLogger("spa.strategy_lab.forward_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
RATES_PAPER_DIR = DATA_DIR / "rates_desk" / "paper"
LAB_PAPER_DIR = DATA_DIR / "strategy_lab_paper"
SCORECARD_FILE = DATA_DIR / "forward_analytics.json"

# The rates-desk paper STATE file (carry-book composition currently held). Used by the stress
# overlay so the shock is applied to what is ACTUALLY held now, not a backtest book.
RATES_STATE_FILE = RATES_PAPER_DIR / "rates_desk_fixed_carry_state.json"

# A risk-adjusted ratio (Sharpe/Sortino) needs enough RETURN observations to mean anything. With
# fewer than this many equity points the ratio is a degenerate artifact (a 2-point series has a
# single return → "Sharpe" is mean/0-or-noise). Below the floor we report UNKNOWN, never a number.
# Honest at the current ~3–6-day track depth: the ratios SHOULD read UNKNOWN today, by design.
MIN_POINTS_FOR_RATIO = 7      # ≥ 7 equity points → ≥ 6 daily returns before a ratio is trusted

# Deflated-Sharpe / PSR is a STRONGER claim than a raw Sharpe (it is the overfitting-robust,
# multiple-testing-aware probability the edge is real), so it needs MORE evidence before it means
# anything. Below this depth the DSR/PSR block stays UNKNOWN — never a fabricated probability. This is
# the day-30 target depth: the forward tracks are ~3–6 days today, so DSR SHOULD read UNKNOWN now, by
# design, and only ACTIVATE once ~a month of real daily returns has accrued. (≥ 20 equity points → ≥ 19
# daily returns: a credible minimum for a probabilistic-Sharpe statement on a daily series.)
MIN_POINTS_FOR_DSR = 20

# The number of "trials" the forward DSR deflates against (the multiple-testing penalty). The Strategy
# Lab compares this many sleeve/baseline tracks side-by-side for the same fundability question, so a
# single track's Sharpe must beat the LUCKIEST of N candidates with no real edge. Pinned + documented.
DSR_N_TRIALS = 8

# The promotion drawdown band — a forward track whose stressed DD exceeds this does NOT survive.
# MIRRORS levered_stress.MAX_DD_BAND_PCT (15%) so the stress overlay is NO looser than the gate.
MAX_DD_BAND_PCT = 15.0


# ── canonical 2024–2026 stress scenarios (the PT mark-down shocks the gate replays) ──────────────
# These mirror levered_stress.STRESS_EVENTS' realized PT mark-downs (per unit of held exposure). We
# reuse the SAME magnitudes so the forward stress overlay is consistent with the promotion gate's
# stress semantics. `pt_markdown` is the fraction marked DOWN on the held PT notional in the shock.
STRESS_SCENARIOS: Tuple[Dict[str, Any], ...] = (
    {"label": "2024-08 ETH crash / carry-unwind", "pt_markdown": 0.015},
    {"label": "2025-10 USDe leverage unwind (THE test)", "pt_markdown": 0.030},
    {"label": "2026-04 KelpDAO rsETH depeg", "pt_markdown": 0.060},
)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# series ingestion
# ──────────────────────────────────────────────────────────────────────────────
def _extract_equity(points: Sequence[dict]) -> List[float]:
    """Pull the equity_usd value from each in-order point. Fail-CLOSED on a missing/non-numeric
    equity (a point without a usable equity is a malformed track, never a fabricated 0)."""
    eq: List[float] = []
    for p in points:
        v = p.get("equity_usd")
        # bool is an int subclass — exclude it; a True/False equity is malformed.
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"point missing numeric equity_usd: {p!r}")
        # fail-CLOSED on NaN/inf: isinstance(nan, float) is True, so a non-finite equity
        # would otherwise slip through and poison every downstream metric into a silent
        # NaN/inf (and invalid JSON). A non-finite equity is a corrupt point, not a real one.
        if not math.isfinite(float(v)):
            raise ValueError(f"point has non-finite equity_usd: {p!r}")
        eq.append(float(v))
    return eq


def _daily_returns(equity: Sequence[float]) -> List[float]:
    """Fractional day-over-day returns from an equity curve. e[i]/e[i-1] - 1."""
    out: List[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev <= 0:
            out.append(0.0)
        else:
            out.append(equity[i] / prev - 1.0)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# T6 (C3) — Deflated-Sharpe / PSR block that ACTIVATES only at the right N
# ──────────────────────────────────────────────────────────────────────────────
def deflated_sharpe_block(rets: Sequence[float], *, floor_apy_pct: float,
                          n_trials: int = DSR_N_TRIALS) -> dict:
    """Overfitting-robust risk-adjusted block on a forward return series, HONEST about depth.

    Reuses spa_core.backtesting.tier1.deflated_sharpe (the SAME PSR / DSR / minTRL the promotion gate
    uses — never reinvented). The discriminating honesty rule:

      • fewer than MIN_POINTS_FOR_DSR returns  → status THIN, every ratio UNKNOWN (a DSR on a handful
        of days is a fabricated probability — we refuse to emit one). This is the expected reading at
        the current ~3–6-day track depth, BY DESIGN.
      • a locked-volatility / zero-dispersion series (std == 0 — the documented degenerate-Sharpe
        hazard for fixed-rate accrual) → status LOCKED_VOL, ratios UNKNOWN (never a ~4.5e8 Sharpe).
      • only with ≥ MIN_POINTS_FOR_DSR real, dispersed returns does the block ACTIVATE with a trusted
        PSR-vs-floor + deflated-Sharpe-vs-luckiest-of-N + minTRL.

    PURE / deterministic / fail-CLOSED. All Sharpe values per-period internally; reported annualized.
    """
    from spa_core.backtesting.tier1 import deflated_sharpe as ds

    n = len(rets)
    floor_daily = (float(floor_apy_pct) / 100.0) / 365.0
    base = {
        "n_returns": n,
        "min_points_for_dsr": MIN_POINTS_FOR_DSR,
        "n_trials": n_trials,
        "status": "THIN",
        "psr_vs_floor": "UNKNOWN",
        "deflated_sharpe": "UNKNOWN",
        "deflated_sharpe_passes_0_95": "UNKNOWN",
        "sharpe_annual_vs_floor": "UNKNOWN",
        "min_track_record_length_obs": "UNKNOWN",
        "mintrl_satisfied": "UNKNOWN",
    }
    if n < MIN_POINTS_FOR_DSR:
        return base  # honest: not enough evidence for a probabilistic-Sharpe statement

    mom = ds.moments(rets)
    if mom["std"] == 0:
        # locked-volatility / zero-dispersion → the degenerate-Sharpe hazard. Report LOCKED_VOL, never
        # a fabricated ratio (a held-to-maturity fixed-rate book has near-zero variance by construction).
        base["status"] = "LOCKED_VOL"
        return base

    sr_pp = ds.sharpe_per_period(rets, rf_per_period=floor_daily)
    sr_annual = ds.annualize_sharpe(sr_pp)
    dsr = ds.deflated_sharpe_ratio(
        sr_pp, n, sr_variance_across_trials=(sr_pp ** 2) / max(2, n_trials),
        n_trials=max(2, n_trials), skew=mom["skew"], kurt=mom["kurt"])
    psr = ds.probabilistic_sharpe_ratio(
        sr_pp, n, skew=mom["skew"], kurt=mom["kurt"], sr_benchmark_per_period=floor_daily)
    mintrl = ds.min_track_record_length(
        sr_pp, skew=mom["skew"], kurt=mom["kurt"], sr_benchmark_per_period=floor_daily)
    mintrl_obs = None if mintrl == float("inf") else round(mintrl, 1)
    base.update({
        "status": "ACTIVE",
        "psr_vs_floor": round(psr, 4),
        "deflated_sharpe": round(dsr["dsr"], 4),
        "deflated_sharpe_passes_0_95": bool(dsr["passes"]),
        "sharpe_annual_vs_floor": round(sr_annual, 3),
        "min_track_record_length_obs": mintrl_obs,
        "mintrl_satisfied": bool(mintrl_obs is not None and n >= mintrl_obs),
    })
    return base


def drawdown_attribution(equity: Sequence[float]) -> dict:
    """Attribute the REALIZED max drawdown to its peak / trough on the forward equity curve.

    Returns {max_dd_pct, peak_idx, trough_idx, peak_equity, trough_equity, peak_to_trough_usd,
    n_drawdown_points}. Honest at any depth ≥ 2 (max-DD is well-defined from 2 points); on a single
    point or a monotone-up curve the DD is 0 with no peak/trough span. PURE / deterministic."""
    eq = [float(x) for x in equity]
    if len(eq) < 2:
        return {"max_dd_pct": 0.0, "peak_idx": None, "trough_idx": None,
                "peak_equity": (eq[0] if eq else None), "trough_equity": (eq[0] if eq else None),
                "peak_to_trough_usd": 0.0, "n_drawdown_points": len(eq)}
    peak = eq[0]
    peak_i = 0
    worst_dd = 0.0
    worst_peak_i = 0
    worst_trough_i = 0
    for i, v in enumerate(eq):
        if v > peak:
            peak = v
            peak_i = i
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > worst_dd:
                worst_dd = dd
                worst_peak_i = peak_i
                worst_trough_i = i
    return {
        "max_dd_pct": round(worst_dd, 4),
        "peak_idx": worst_peak_i,
        "trough_idx": worst_trough_i,
        "peak_equity": round(eq[worst_peak_i], 2),
        "trough_equity": round(eq[worst_trough_i], 2),
        "peak_to_trough_usd": round(eq[worst_peak_i] - eq[worst_trough_i], 2),
        "n_drawdown_points": len(eq),
    }


# ──────────────────────────────────────────────────────────────────────────────
# T4 — risk-adjusted scorecard for ONE forward track
# ──────────────────────────────────────────────────────────────────────────────
def analyze_track(
    series_doc: Any,
    *,
    name: str = "track",
    floor_apy_pct: Optional[float] = None,
) -> dict:
    """Risk-adjusted scorecard for ONE forward series.

    Args:
        series_doc   : on-disk doc {"id":.., "series":[{date, equity_usd, ...}]} or a bare list.
        name         : track name for the report.
        floor_apy_pct: the RWA risk-free floor (%); None → resolved live via metrics' config.

    Returns a per-track scorecard dict. Fail-CLOSED: a track that fails track_integrity (gap /
    duplicate / out-of-order / future / malformed) yields verdict="UNKNOWN" with the integrity
    reason — NEVER a computed Sharpe/return on a broken series. A track with fewer than
    MIN_POINTS_FOR_RATIO usable points yields sharpe/sortino="UNKNOWN" (not a degenerate number),
    but still reports n_points / dates / realized return where those ARE defined.
    """
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)

    base = {
        "name": name,
        "n_points": 0,
        "first_date": None,
        "last_date": None,
        "integrity_ok": False,
        "integrity_reason": "malformed",
        "ann_return_pct": None,
        "max_dd_pct": None,
        "rolling_vol_pct": None,
        "sharpe": "UNKNOWN",
        "sortino": "UNKNOWN",
        "locked_vol": False,
        "floor_apy_pct": round(floor, 4),
        "excess_vs_floor_pct": None,
        "attribution": None,
        "drawdown_attribution": None,
        "deflated_sharpe_block": None,
        "verdict": "UNKNOWN",
    }

    # ── 1. integrity gate (fail-CLOSED) ──────────────────────────────────────────────────────
    integ = ti.check_track_integrity(series_doc)
    base["integrity_ok"] = bool(integ["ok"])
    base["integrity_reason"] = integ["reason"]
    base["n_points"] = integ["n_points"]
    base["first_date"] = integ["first_date"]
    base["last_date"] = integ["last_date"]

    if not integ["ok"]:
        # a broken (gapped/dup/out-of-order/future/malformed) track → never compute a number on it
        base["verdict"] = "UNKNOWN"
        return base

    points = ti._coerce_series(series_doc) or []
    if not points:
        base["verdict"] = "UNKNOWN"  # empty track — integrity ok="empty" but nothing to score
        base["integrity_reason"] = integ["reason"]
        return base

    # ── 2. equity → returns ──────────────────────────────────────────────────────────────────
    try:
        equity = _extract_equity(points)
    except ValueError as exc:
        base["integrity_ok"] = False
        base["integrity_reason"] = f"malformed:{exc}"
        base["verdict"] = "UNKNOWN"
        return base

    rets = _daily_returns(equity)

    # ── 3. metrics (REUSE metrics.py) ────────────────────────────────────────────────────────
    # These are honest at any depth: ann_return / max_dd / vol are well-defined from ≥2 points.
    ann_return = metrics.net_apy_from_equity(equity)
    max_dd = metrics.max_drawdown_pct(equity)
    vol = metrics.volatility_pct(rets)
    base["ann_return_pct"] = ann_return
    base["max_dd_pct"] = max_dd
    base["rolling_vol_pct"] = vol

    # Sharpe / Sortino — HONEST. metrics.sharpe()/sortino() return None for a locked-vol book
    # (float-noise-only variance → the documented degenerate-Sharpe hazard) AND for <2 returns.
    sh = metrics.sharpe(rets)
    so = metrics.sortino(rets)
    # locked-vol detection: enough points exist but the ratio came back None because dispersion is
    # float-noise (constant accrual). Distinguish that from simply-too-few-points.
    enough_points = len(equity) >= MIN_POINTS_FOR_RATIO
    locked_vol = bool(enough_points and (sh is None or so is None))
    base["locked_vol"] = locked_vol

    if not enough_points:
        base["sharpe"] = "UNKNOWN"      # thin track — a ratio here is a degenerate artifact
        base["sortino"] = "UNKNOWN"
    else:
        base["sharpe"] = sh if sh is not None else "UNKNOWN"
        base["sortino"] = so if so is not None else "UNKNOWN"

    # ── 4. attribution vs the RWA floor ──────────────────────────────────────────────────────
    # Decompose the realized annualized return into the risk-free floor leg + the carry-above-floor
    # (excess) leg. excess_vs_floor = realized ann return − floor. Positive → the track is earning
    # above the risk-free RWA benchmark; negative → it is NOT beating cash, risk-adjusted.
    excess = round(ann_return - floor, 4)
    base["excess_vs_floor_pct"] = excess
    base["attribution"] = {
        "realized_ann_return_pct": ann_return,
        "rwa_floor_pct": round(floor, 4),
        "floor_leg_pct": round(floor, 4),            # the return attributable to sitting in RWA cash
        "excess_carry_pct": excess,                  # the return attributable to the strategy's edge
        "beats_floor": bool(excess > 0.0),
    }

    # ── 4b. drawdown attribution (peak→trough of the realized forward equity) ──────────────────
    base["drawdown_attribution"] = drawdown_attribution(equity)

    # ── 4c. deflated-Sharpe / PSR block — THIN until MIN_POINTS_FOR_DSR, then ACTIVE (C3) ───────
    # A stronger, overfitting-robust claim than the raw Sharpe above — it deflates against the
    # luckiest-of-N-trials benchmark. Stays UNKNOWN/THIN at today's depth (by design) and the
    # degenerate-Sharpe guard (std==0 → LOCKED_VOL) holds inside the block.
    base["deflated_sharpe_block"] = deflated_sharpe_block(rets, floor_apy_pct=floor)

    # ── 5. verdict ───────────────────────────────────────────────────────────────────────────
    # HONEST: a thin/locked-vol track gets THIN_TRACK (we have an honest return + attribution but
    # not yet a trustworthy risk-adjusted ratio). A track with a real Sharpe gets a beats/below
    # verdict. Never a fabricated PASS on insufficient evidence.
    if base["sharpe"] == "UNKNOWN":
        base["verdict"] = "THIN_TRACK"   # honest: not enough evidence for a risk-adjusted verdict
    elif excess > 0.0:
        base["verdict"] = "BEATS_FLOOR"
    else:
        base["verdict"] = "BELOW_FLOOR"
    return base


# ──────────────────────────────────────────────────────────────────────────────
# WS-1.6 — captured-book PnL attribution (carry-leg vs RWA floor-leg), reconciling to NAV
# ──────────────────────────────────────────────────────────────────────────────
def captured_book_attribution(
    series_doc: Any,
    *,
    floor_apy_pct: Optional[float] = None,
    name: str = "rates_desk_fixed_carry",
) -> dict:
    """Decompose the captured sleeve's REALIZED PnL into a floor-leg + a carry-leg, in DOLLARS,
    reconciling EXACTLY to the captured-book NAV.

    The captured FixedCarry sleeve sits on a paper book that started at an initial capital and now
    marks a current equity (NAV). Its realized PnL = NAV − initial_capital. We split that realized
    PnL into two honest legs, day by day on the realized equity path:

      • floor_leg_usd  — what the ~3.4% RWA risk-free floor would have accrued on the SAME marking
        capital over the SAME elapsed calendar days (simple per-day floor accrual on each step's
        opening equity). This is the "you could have just held tokenized T-bills" benchmark.
      • carry_leg_usd  — the RESIDUAL: realized_pnl_usd − floor_leg_usd. The genuine carry edge the
        sleeve captured ABOVE the floor (can be NEGATIVE — honest when the book underperforms cash).

    RECONCILIATION (the property the verification pins): floor_leg_usd + carry_leg_usd ==
    realized_pnl_usd, to the cent. The carry leg is DEFINED as the residual precisely so the
    decomposition always reconciles to the realized NAV move — no leg can be fabricated independently.

    HONESTY / fail-CLOSED:
      • the series passes track_integrity FIRST (gap / duplicate / out-of-order / FUTURE-dated /
        malformed → reconciles=False, status UNKNOWN, NO numbers). A tampered or look-ahead series
        is REFUSED here — it never yields an inflated carry number.
      • non-finite / non-numeric equity → malformed → UNKNOWN (reuses _extract_equity's guard).
      • THIN until the track matures: with < MIN_POINTS_FOR_RATIO points the dollar legs are still
        well-defined and reconcile, but `thin=True` and `risk_adjusted_known=False` flag that the
        risk-adjusted carry quality (Sharpe) is not yet trustworthy — the legs are an honest $ split,
        not a risk-adjusted verdict.

    Returns a dict reconciling to NAV; deterministic / PURE / stdlib-only.
    """
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)
    floor_daily = (floor / 100.0) / 365.0

    base = {
        "name": name,
        "model": "captured_book_attribution",
        "status": "UNKNOWN",
        "reconciles": False,
        "integrity_ok": False,
        "integrity_reason": "malformed",
        "n_points": 0,
        "first_date": None,
        "last_date": None,
        "elapsed_days": 0,
        "rwa_floor_pct": round(floor, 4),
        "initial_capital_usd": None,
        "nav_usd": None,
        "realized_pnl_usd": None,
        "floor_leg_usd": None,
        "carry_leg_usd": None,
        "residual_usd": None,
        "thin": True,
        "risk_adjusted_known": False,
        "carry_beats_floor": None,
    }

    # ── 1. integrity gate (fail-CLOSED) — refuse a tampered / look-ahead / gapped series ──────────
    integ = ti.check_track_integrity(series_doc)
    base["integrity_ok"] = bool(integ["ok"])
    base["integrity_reason"] = integ["reason"]
    base["n_points"] = integ["n_points"]
    base["first_date"] = integ["first_date"]
    base["last_date"] = integ["last_date"]
    if not integ["ok"]:
        return base  # broken/look-ahead → no numbers, never a fabricated carry leg

    points = ti._coerce_series(series_doc) or []
    if len(points) < 2:
        # a single (or empty) point has no realized PnL move to attribute — honest, not fabricated.
        base["status"] = "THIN"
        base["reconciles"] = True  # trivially: 0 == 0 + 0
        if points:
            try:
                eq0 = _extract_equity(points)[0]
            except ValueError as exc:
                base["integrity_ok"] = False
                base["integrity_reason"] = f"malformed:{exc}"
                return base
            base.update({
                "initial_capital_usd": round(eq0, 2), "nav_usd": round(eq0, 2),
                "realized_pnl_usd": 0.0, "floor_leg_usd": 0.0, "carry_leg_usd": 0.0,
                "residual_usd": 0.0, "elapsed_days": 0,
            })
        return base

    # ── 2. equity path (fail-CLOSED on non-finite / non-numeric) ─────────────────────────────────
    try:
        equity = _extract_equity(points)
    except ValueError as exc:
        base["integrity_ok"] = False
        base["integrity_reason"] = f"malformed:{exc}"
        return base

    initial = equity[0]
    nav = equity[-1]
    realized_pnl = nav - initial

    # ── 3. floor leg — per-day simple floor accrual on each step's OPENING equity ─────────────────
    # The floor benchmark earns floor_daily on the capital marked at the start of each daily step,
    # accumulated across the elapsed days BETWEEN consecutive points (so a 2-day gap-free step accrues
    # 2 days; integrity already guarantees contiguous calendar days, so this is 1 day per step).
    floor_leg = 0.0
    elapsed_days = 0
    for i in range(1, len(equity)):
        d_prev = points[i - 1].get("date")
        d_cur = points[i].get("date")
        step_days = 1
        try:
            if d_prev and d_cur:
                step_days = max(
                    1,
                    (datetime.date.fromisoformat(str(d_cur)) -
                     datetime.date.fromisoformat(str(d_prev))).days,
                )
        except ValueError:
            step_days = 1
        # accrue the floor on the opening equity of this step, for step_days days
        floor_leg += equity[i - 1] * floor_daily * step_days
        elapsed_days += step_days

    # ── 4. carry leg = RESIDUAL → reconciliation is EXACT by construction ────────────────────────
    carry_leg = realized_pnl - floor_leg
    residual = round((floor_leg + carry_leg) - realized_pnl, 6)  # == 0 by definition

    thin = len(equity) < MIN_POINTS_FOR_RATIO
    base.update({
        "status": "THIN" if thin else "OK",
        "reconciles": bool(abs(residual) < 1e-6),
        "elapsed_days": elapsed_days,
        "initial_capital_usd": round(initial, 2),
        "nav_usd": round(nav, 2),
        "realized_pnl_usd": round(realized_pnl, 4),
        "floor_leg_usd": round(floor_leg, 4),
        "carry_leg_usd": round(carry_leg, 4),
        "residual_usd": residual,
        "thin": thin,
        "risk_adjusted_known": (not thin),
        "carry_beats_floor": bool(carry_leg > 0.0),
        "note": (
            "Captured FixedCarry paper book — advisory, not realized capital. PnL split into the "
            "RWA floor-leg (what tokenized T-bills would have earned) and the carry-leg (residual "
            "edge above the floor). carry+floor reconciles to the captured-book NAV exactly. "
            + ("THIN: < MIN_POINTS_FOR_RATIO days → the $ split is honest but the risk-adjusted "
               "carry quality (Sharpe) is not yet trustworthy." if thin
               else "Track has enough depth for a risk-adjusted read.")
        ),
    })
    return base


# ──────────────────────────────────────────────────────────────────────────────
# T5 — drawdown + stress overlay on the realized forward record
# ──────────────────────────────────────────────────────────────────────────────
def _held_pt_notional(state_doc: Any) -> Tuple[float, float, int]:
    """From the rates-desk paper state, sum the PT notional CURRENTLY held (open books) and the
    book equity. Returns (held_pt_notional_usd, current_equity_usd, n_open_books).

    The state shape (rates_desk_fixed_carry_state.json):
      {"state": {"capital": "...", "cash": "...", "accrued": "...", "books": {id: {"size": ...}}}}
    Decimal-strings are coerced to float. Fail-CLOSED returns (0,0,0) on an unusable shape so the
    overlay reports an honest no-exposure stress (never a fabricated held size)."""
    if not isinstance(state_doc, dict):
        return 0.0, 0.0, 0
    st = state_doc.get("state")
    if not isinstance(st, dict):
        return 0.0, 0.0, 0
    try:
        capital = float(st.get("capital", 0.0))
        cash = float(st.get("cash", 0.0))
        accrued = float(st.get("accrued", 0.0))
    except (TypeError, ValueError):
        return 0.0, 0.0, 0
    # fail-CLOSED on non-finite state numbers — a NaN/inf capital/cash/accrued is a corrupt
    # state file, never a real book; ignoring it stops the shock math leaking NaN/inf.
    if not (math.isfinite(capital) and math.isfinite(cash) and math.isfinite(accrued)):
        return 0.0, 0.0, 0
    books = st.get("books")
    held = 0.0
    n_open = 0
    if isinstance(books, dict):
        for b in books.values():
            if not isinstance(b, dict):
                continue
            try:
                size = float(b.get("size", 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(size):
                continue  # a non-finite book size is corrupt — skip, never accumulate NaN/inf
            if size > 0:
                held += size
                n_open += 1
    # current book equity = cash + held PT notional + accrued carry (the live equity the desk marks)
    equity = cash + held + accrued
    if equity <= 0:
        equity = capital  # fall back to nominal capital if the state didn't carry cash/held
    return held, equity, n_open


def stress_overlay(
    realized_equity: Sequence[float],
    held_pt_notional_usd: float,
    current_equity_usd: float,
    *,
    scenarios: Sequence[Dict[str, Any]] = STRESS_SCENARIOS,
    max_dd_band_pct: float = MAX_DD_BAND_PCT,
) -> dict:
    """Apply each canonical stress scenario to the CURRENTLY-held carry book on top of the REALIZED
    forward equity, and report per-scenario worst-case drawdown + survives.

    The shock model (consistent with the gate's PT mark-down semantics): on the stress day the held
    PT notional marks DOWN by `pt_markdown` → a one-day equity hit of (held_notional × markdown).
    We append that shocked point to the realized forward equity curve and measure max-drawdown over
    the combined path (so a track already in drawdown compounds honestly with the shock). survives =
    the stressed DD stays within the promotion drawdown band (NO looser than the gate's 15%).

    Returns {held_pt_notional_usd, current_equity_usd, max_dd_band_pct,
             scenarios:[{label, pt_markdown_pct, shock_usd, stressed_equity_usd, stress_dd_pct,
                         survives}], worst_stress_dd_pct, survives_all}.
    fail-CLOSED: with no held notional the shock is $0 → the overlay honestly reports 0% stress DD
    (a cash book takes no PT mark-down) rather than fabricating a loss."""
    base_curve = [float(x) for x in realized_equity] or [float(current_equity_usd)]
    results: List[dict] = []
    worst = 0.0
    survives_all = True
    for sc in scenarios:
        markdown = float(sc["pt_markdown"])
        shock_usd = held_pt_notional_usd * markdown
        shocked_equity = current_equity_usd - shock_usd
        # combined path: the realized forward record, then the shocked mark-to-market point.
        stressed_curve = list(base_curve) + [shocked_equity]
        stress_dd = metrics.max_drawdown_pct(stressed_curve)
        survives = bool(stress_dd <= max_dd_band_pct)
        if not survives:
            survives_all = False
        if stress_dd > worst:
            worst = stress_dd
        results.append({
            "label": sc["label"],
            "pt_markdown_pct": round(markdown * 100.0, 4),
            "shock_usd": round(shock_usd, 2),
            "stressed_equity_usd": round(shocked_equity, 2),
            "stress_dd_pct": stress_dd,
            "survives": survives,
        })
    return {
        "held_pt_notional_usd": round(held_pt_notional_usd, 2),
        "current_equity_usd": round(current_equity_usd, 2),
        "max_dd_band_pct": max_dd_band_pct,
        "scenarios": results,
        "worst_stress_dd_pct": round(worst, 4),
        "survives_all": survives_all,
    }


# ──────────────────────────────────────────────────────────────────────────────
# aggregate — scorecard over every forward track
# ──────────────────────────────────────────────────────────────────────────────
def _discover_series_files(data_dir: Path) -> List[Path]:
    out: List[Path] = []
    for sub in (data_dir / "rates_desk" / "paper", data_dir / "strategy_lab_paper"):
        if sub.is_dir():
            out.extend(sorted(sub.glob("*_series.json")))
    return out


def _track_name(path: Path) -> str:
    return f"{path.parent.name}/{path.name[:-len('_series.json')]}"


def build_scorecard(
    data_dir: Optional[Path] = None,
    *,
    floor_apy_pct: Optional[float] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Build the risk-adjusted scorecard over EVERY forward track + the stress overlay on the
    CURRENT rates-desk carry book. Writes data/forward_analytics.json atomically (unless write=False).

    The stress overlay is computed on the rates-desk FixedCarry forward record (the only track with
    a held PT carry book to mark down). Each track gets its T4 risk-adjusted scorecard; the T5
    overlay is attached to the carry track and surfaced at the top level.

    ``now_iso`` (the ``generated_at`` stamp) is INJECTABLE: passing a fixed value makes the whole
    scorecard byte-stable from fixed inputs (the only wall-clock field). When None it defaults to
    the live UTC instant — the only intentional non-determinism in normal operation.

    Returns the full scorecard doc. fail-CLOSED throughout: a broken/thin track → UNKNOWN/THIN_TRACK,
    never a fabricated number; an unreadable file → an explicit unreadable track entry.
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR

    # Resolve the floor ONCE (live tokenized-T-bill yield, fail-closed to committed literal).
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)

    files = _discover_series_files(root)
    tracks: List[dict] = []
    carry_track_equity: Optional[List[float]] = None
    carry_series_doc: Any = None
    for f in files:
        name = _track_name(f)
        try:
            doc = atomic_load(str(f), default=None)
        except Exception:  # noqa: BLE001 — a corrupt file is an UNKNOWN track, never a crash
            doc = None
        if doc is None:
            tracks.append({
                "name": name, "n_points": 0, "first_date": None, "last_date": None,
                "integrity_ok": False, "integrity_reason": "unreadable",
                "ann_return_pct": None, "max_dd_pct": None, "rolling_vol_pct": None,
                "sharpe": "UNKNOWN", "sortino": "UNKNOWN", "locked_vol": False,
                "floor_apy_pct": round(floor, 4), "excess_vs_floor_pct": None,
                "attribution": None, "verdict": "UNKNOWN",
            })
            continue
        card = analyze_track(doc, name=name, floor_apy_pct=floor)
        tracks.append(card)
        # capture the carry track's realized equity for the stress overlay + the WS-1.6 attribution
        if name.endswith("rates_desk_fixed_carry") and card["integrity_ok"]:
            carry_series_doc = doc
            pts = ti._coerce_series(doc) or []
            try:
                carry_track_equity = _extract_equity(pts)
            except ValueError:
                carry_track_equity = None

    # ── T5 stress overlay on the CURRENT carry book ──────────────────────────────────────────
    state_doc = None
    state_path = root / "rates_desk" / "paper" / "rates_desk_fixed_carry_state.json"
    try:
        state_doc = atomic_load(str(state_path), default=None)
    except Exception:  # noqa: BLE001
        state_doc = None
    held, cur_equity, n_open = _held_pt_notional(state_doc)
    if carry_track_equity:
        # prefer the realized forward record's last equity as the marking base if it's sane
        if not cur_equity:
            cur_equity = carry_track_equity[-1]
    overlay = stress_overlay(
        carry_track_equity or ([cur_equity] if cur_equity else [0.0]),
        held, cur_equity or 0.0,
    )
    overlay["n_open_books"] = n_open

    # ── WS-1.6 captured-book attribution on the FixedCarry sleeve (carry-leg vs floor-leg → NAV) ──
    captured_attr = (
        captured_book_attribution(carry_series_doc, floor_apy_pct=floor)
        if carry_series_doc is not None
        else captured_book_attribution({"series": []}, floor_apy_pct=floor)
    )

    n_unknown = sum(1 for t in tracks if t["verdict"] == "UNKNOWN")
    n_thin = sum(1 for t in tracks if t["verdict"] == "THIN_TRACK")
    n_beats = sum(1 for t in tracks if t["verdict"] == "BEATS_FLOOR")
    # C3 rollup: how many tracks have ENOUGH depth for the deflated-Sharpe block to ACTIVATE (vs the
    # honest THIN/LOCKED_VOL state). At today's ~3–6-day depth this SHOULD be 0 — the artifact lands
    # real only once the forward records reach ~MIN_POINTS_FOR_DSR daily returns (the day-30 target).
    n_dsr_active = sum(
        1 for t in tracks
        if isinstance(t.get("deflated_sharpe_block"), dict)
        and t["deflated_sharpe_block"].get("status") == "ACTIVE")

    out = {
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "model": "forward_analytics",
        "llm_forbidden": True,
        "deterministic": True,
        "rwa_floor_apy_pct": round(floor, 4),
        "min_points_for_ratio": MIN_POINTS_FOR_RATIO,
        "min_points_for_dsr": MIN_POINTS_FOR_DSR,
        "dsr_n_trials": DSR_N_TRIALS,
        "max_dd_band_pct": MAX_DD_BAND_PCT,
        "n_tracks": len(tracks),
        "n_unknown": n_unknown,
        "n_thin_track": n_thin,
        "n_beats_floor": n_beats,
        "n_dsr_active": n_dsr_active,
        "tracks": tracks,
        "carry_book_stress_overlay": overlay,
        "captured_book_attribution": captured_attr,
    }
    if write:
        atomic_save(out, str(root / SCORECARD_FILE.name))
    return out


def main() -> int:
    import json
    rep = build_scorecard()
    print(json.dumps(rep, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

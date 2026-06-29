"""
spa_core/strategy_lab/aggressive_lab/tail_overlay.py — THE TAIL OVERLAY (the honest core).

The whole reason this lab exists: a 10–15% headline is RISK-COMPENSATION, and the tail comes. This
module surfaces, for each strategy, the drawdown that comes WITH the yield — so "11% sUSDe DN" is
shown next to "and here is the −X% when funding flipped / it depegged".

Two complementary tail measurements per strategy, per canonical stress window (Ethena Oct-2025,
LRT depegs Aug-2024 / Apr-2026):

  (1) IN-SAMPLE REALIZED tail — if the strategy's REAL 2024–2026 backtest series covers the window
      dates, we CLIP the realized equity to that window and measure the REALIZED:
        • worst drawdown inside the window (peak-to-trough, % — the real loss the book took),
        • loss-in-stress (% from the window's opening equity to its trough — what the owner lost
          had they been holding at the window's start),
        • time-to-recover (days from the trough back to the pre-window peak, within the available
          series; None = NOT yet recovered in-sample → the honest, scary answer).
      This is the realest possible answer: the strategy's OWN history through the real event.

  (2) SHAPE-SHOCK overlay — applied ALWAYS (even when the backtest does not cover the window): a
      one-day mark-down sized by the strategy's risk SHAPE × the window's shape_shock (STRESS_WINDOWS).
      It appends the shock to the realized equity tail and measures the stressed drawdown. This is the
      forward-looking tail: "if THIS event hit your CURRENT book, here is the hit by your risk shape".
      A funding_flip book gets hammered by the USDe window; a depeg/il book by the rsETH window; a
      liquidation book worst of all. No strategy is immune — a shape absent from a window takes the
      window's base_shock (systemic spillover).

The overlay reports BOTH, and the WORST tail across all windows (the number that must sit next to
the yield). fail-CLOSED: a broken/empty series → no fabricated tail; a window with no in-sample
coverage → in_sample=None for that window (the shape-shock still applies).

Reuses metrics.max_drawdown_pct + the lab's canonical STRESS_WINDOWS. stdlib-only, deterministic,
fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.strategy_lab import metrics
from spa_core.strategy_lab import track_integrity as ti
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS


def _clip_window(points: Sequence[dict], date_from: str, date_to: str) -> List[dict]:
    """The in-order points whose date falls within [date_from, date_to] inclusive."""
    try:
        lo = datetime.date.fromisoformat(date_from)
        hi = datetime.date.fromisoformat(date_to)
    except ValueError:
        return []
    out: List[dict] = []
    for p in points:
        d = p.get("date")
        if not isinstance(d, str):
            continue
        try:
            dd = datetime.date.fromisoformat(d[:10])
        except ValueError:
            continue
        if lo <= dd <= hi:
            out.append(p)
    return out


def _equity(points: Sequence[dict]) -> List[float]:
    return [float(p["equity_usd"]) for p in points if isinstance(p.get("equity_usd"), (int, float))
            and not isinstance(p.get("equity_usd"), bool)]


def _time_to_recover_days(
    all_points: Sequence[dict],
    window_trough_idx_in_all: int,
    pre_window_peak: float,
) -> Optional[int]:
    """Days from the window trough until equity first regains the pre-window peak, scanning the
    FULL series after the trough. None = never recovered within the available series (honest)."""
    if pre_window_peak <= 0:
        return None
    try:
        trough_date = datetime.date.fromisoformat(str(all_points[window_trough_idx_in_all]["date"])[:10])
    except (ValueError, KeyError, IndexError):
        return None
    for k in range(window_trough_idx_in_all + 1, len(all_points)):
        eq = all_points[k].get("equity_usd")
        if not isinstance(eq, (int, float)) or isinstance(eq, bool):
            continue
        if float(eq) >= pre_window_peak:
            try:
                rec_date = datetime.date.fromisoformat(str(all_points[k]["date"])[:10])
            except (ValueError, KeyError):
                return None
            return (rec_date - trough_date).days
    return None  # not recovered in-sample → the honest, scary answer


def _in_sample_tail(all_points: List[dict], window: Dict[str, Any]) -> Optional[dict]:
    """The REALIZED tail inside a window if the backtest covers it; None if no coverage."""
    clip = _clip_window(all_points, str(window["date_from"]), str(window["date_to"]))
    if len(clip) < 2:
        return None  # no (or single-point) in-sample coverage of this window
    eq = _equity(clip)
    if len(eq) < 2:
        return None

    # worst drawdown inside the window
    worst_dd = metrics.max_drawdown_pct(eq)

    # loss-in-stress: opening equity of the window → its trough (what a holder at window-start lost)
    open_eq = eq[0]
    trough_eq = min(eq)
    loss_in_stress = round((open_eq - trough_eq) / open_eq * 100.0, 4) if open_eq > 0 else 0.0

    # locate the window-trough's index in the FULL series for time-to-recover
    # pre-window peak = the max equity at-or-before the window start (the level to recover to)
    first_clip_date = clip[0].get("date")
    trough_local_idx = eq.index(trough_eq)
    trough_point = clip[trough_local_idx]
    # map back to the all_points index by identity of (date) — dates are unique post-integrity
    trough_idx_all = None
    pre_peak = open_eq
    for i, p in enumerate(all_points):
        if str(p.get("date"))[:10] < str(first_clip_date)[:10]:
            v = p.get("equity_usd")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > pre_peak:
                pre_peak = float(v)
        if p.get("date") == trough_point.get("date"):
            trough_idx_all = i
    ttr = (_time_to_recover_days(all_points, trough_idx_all, pre_peak)
           if trough_idx_all is not None else None)

    return {
        "covered": True,
        "n_window_points": len(clip),
        "window_open_equity_usd": round(open_eq, 2),
        "window_trough_equity_usd": round(trough_eq, 2),
        "worst_dd_pct": worst_dd,
        "loss_in_stress_pct": loss_in_stress,
        "time_to_recover_days": ttr,
        "recovered": bool(ttr is not None),
    }


def _shape_shock_tail(
    realized_equity: Sequence[float],
    risk_shape: str,
    window: Dict[str, Any],
) -> dict:
    """The forward-looking shape-shock tail: append a one-day mark-down (sized by the strategy's
    risk SHAPE × this window's shock) to the realized equity, measure the stressed drawdown.

    A shape absent from the window's shape_shock takes the window's base_shock (systemic spillover —
    no book is fully immune to a market-wide unwind). fail-CLOSED: with no realized equity we mark
    down a nominal $1 base so the shock fraction is still surfaced honestly (never a crash)."""
    shape_shock: Dict[str, float] = dict(window.get("shape_shock", {}))  # type: ignore[arg-type]
    base_shock = float(window.get("base_shock", 0.0))  # type: ignore[arg-type]
    shock_frac = float(shape_shock.get(risk_shape, base_shock))

    base_curve = [float(x) for x in realized_equity] or [1.0]
    current = base_curve[-1]
    shocked = current * (1.0 - shock_frac)
    stressed_curve = list(base_curve) + [shocked]
    stressed_dd = metrics.max_drawdown_pct(stressed_curve)
    return {
        "risk_shape": risk_shape,
        "shock_frac_pct": round(shock_frac * 100.0, 4),
        "current_equity_usd": round(current, 2),
        "shocked_equity_usd": round(shocked, 2),
        "shock_loss_usd": round(current - shocked, 2),
        "stressed_dd_pct": stressed_dd,
    }


def build_tail_overlay(
    series_doc: Any,
    *,
    risk_shape: str,
    name: str = "track",
    windows: Sequence[Dict[str, Any]] = STRESS_WINDOWS,
) -> dict:
    """The full tail overlay for ONE strategy track (intended: its BACKTEST series — the deep one
    that carries the stress windows in-sample). Surfaces, per window, the in-sample realized tail
    (when covered) AND the shape-shock tail (always), plus the WORST tail across all windows.

    Returns:
      {name, risk_shape, integrity_ok, n_points, windows:[{key,label,in_sample,shape_shock}],
       worst_in_sample_dd_pct, worst_in_sample_loss_pct, max_time_to_recover_days,
       worst_shape_shock_dd_pct, worst_tail_dd_pct}
    fail-CLOSED: a broken/empty series → integrity_ok False, no fabricated tail (windows still
    carry the shape-shock against a nominal base so the SHAPE risk is never hidden)."""
    integ = ti.check_track_integrity(series_doc)
    points = ti._coerce_series(series_doc) or []
    eq_all = _equity(points) if integ["ok"] else []

    per_window: List[dict] = []
    worst_in_dd = 0.0
    worst_in_loss = 0.0
    max_ttr: Optional[int] = None
    any_unrecovered = False
    worst_shape_dd = 0.0

    for w in windows:
        in_sample = _in_sample_tail(points, w) if (integ["ok"] and len(points) >= 2) else None
        shape = _shape_shock_tail(eq_all, risk_shape, w)
        per_window.append({
            "key": w["key"],
            "label": w["label"],
            "date_from": w["date_from"],
            "date_to": w["date_to"],
            "in_sample": in_sample,
            "shape_shock": shape,
        })
        if in_sample is not None:
            if in_sample["worst_dd_pct"] > worst_in_dd:
                worst_in_dd = in_sample["worst_dd_pct"]
            if in_sample["loss_in_stress_pct"] > worst_in_loss:
                worst_in_loss = in_sample["loss_in_stress_pct"]
            ttr = in_sample["time_to_recover_days"]
            if ttr is None:
                any_unrecovered = True
            elif max_ttr is None or ttr > max_ttr:
                max_ttr = ttr
        if shape["stressed_dd_pct"] > worst_shape_dd:
            worst_shape_dd = shape["stressed_dd_pct"]

    worst_tail = max(worst_in_dd, worst_shape_dd)
    return {
        "name": name,
        "risk_shape": risk_shape,
        "integrity_ok": bool(integ["ok"]),
        "integrity_reason": integ["reason"],
        "n_points": integ["n_points"],
        "windows": per_window,
        "worst_in_sample_dd_pct": round(worst_in_dd, 4),
        "worst_in_sample_loss_pct": round(worst_in_loss, 4),
        # max_time_to_recover: a NUMBER of days if all covered windows recovered; the string
        # "NOT_RECOVERED" if ANY in-sample stress was never recovered (the honest worst case).
        "max_time_to_recover_days": ("NOT_RECOVERED" if any_unrecovered else max_ttr),
        "worst_shape_shock_dd_pct": round(worst_shape_dd, 4),
        "worst_tail_dd_pct": round(worst_tail, 4),
    }

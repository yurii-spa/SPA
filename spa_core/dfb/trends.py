"""
spa_core/dfb/trends.py — WS-2.1: HISTORICAL TRENDS surfaced from the captured history series.

Consumes the proof-chained daily capture (`history.read_history`) and derives a per-pool TREND summary
— APY delta (7d / 30d), TVL trend, refusal-state changes over time, and a sparkline-ready series — so
the screener + detail page can show DefiLlama-style trend columns computed from OUR OWN captured data.

THE HONESTY RULE (fail-CLOSED, THIN-aware): a delta is only reported when there are TWO real points
spanning the window; otherwise it is `None` + the window is labeled `INSUFFICIENT_DATA` — NEVER
extrapolated, NEVER faked from one point. The captured `refusal_verdict` / `risk_class` timeline is the
SCARCE asset (it cannot be backfilled), so the trend surfaces every refusal-state FLIP it can see.

NO risk math here (the NO-FORK rule): trends are pure arithmetic on the engine's already-published
verdicts (apy/tvl deltas + state-change detection). No haircut / refusal / exit math is defined here.

stdlib only · deterministic (windows in CALENDAR days off each record's `capture_date`) · fail-CLOSED.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from typing import Dict, List, Optional

from spa_core.dfb import history as dfb_history

# Trend windows (calendar days). A delta needs an anchor point at/just-before (now - window).
TREND_WINDOWS_DAYS = (7, 30)

# The minimum number of real captured points to draw any trend line / sparkline.
MIN_TREND_POINTS = 2

_INSUFFICIENT = "INSUFFICIENT_DATA"


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    import math
    return v if math.isfinite(v) else None


def _date(s) -> Optional[datetime.date]:
    if not isinstance(s, str):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def _anchor_for_window(records: List[dict], latest_date: datetime.date, window_days: int):
    """The record to compare the latest against for a `window_days` lookback: the LAST record whose
    capture_date is <= (latest_date - window_days). fail-CLOSED: None if no such record exists (the
    window is then INSUFFICIENT_DATA — we never compare against a too-recent point and call it 7d)."""
    cutoff = latest_date - datetime.timedelta(days=window_days)
    anchor = None
    for r in records:
        d = _date(r.get("capture_date"))
        if d is not None and d <= cutoff:
            anchor = r  # records are ascending → keep the latest qualifying one
    return anchor


def _delta(latest_val: Optional[float], anchor_val: Optional[float]) -> Optional[float]:
    """Absolute change latest - anchor (decimal-fraction APY, or USD for TVL). None if either is a
    hole (fail-CLOSED — a delta against a missing number is not a real delta)."""
    if latest_val is None or anchor_val is None:
        return None
    return latest_val - anchor_val


def _pct_change(latest_val: Optional[float], anchor_val: Optional[float]) -> Optional[float]:
    """Relative change (latest-anchor)/|anchor| as a decimal fraction. None if anchor is 0/None/hole."""
    if latest_val is None or anchor_val is None or anchor_val == 0:
        return None
    return (latest_val - anchor_val) / abs(anchor_val)


def _refusal_changes(records: List[dict]) -> List[dict]:
    """Every refusal-state FLIP across the captured timeline (the scarce series). A flip = the
    refusal_verdict OR risk_class changed vs the previous record. Returns [{date, from, to, ...}]."""
    flips: List[dict] = []
    prev: Optional[dict] = None
    for r in records:
        if prev is not None:
            pv, cv = prev.get("refusal_verdict"), r.get("refusal_verdict")
            pc, cc = prev.get("risk_class"), r.get("risk_class")
            if pv != cv or pc != cc:
                flips.append({
                    "date": r.get("capture_date"),
                    "from_verdict": pv, "to_verdict": cv,
                    "from_class": pc, "to_class": cc,
                })
        prev = r
    return flips


def _sparkline(records: List[dict], field: str) -> List[dict]:
    """A sparkline-ready series [{date, value}] for one field, holes DROPPED (a hole is not plotted —
    fail-CLOSED, never interpolated). Deterministic ascending order."""
    out: List[dict] = []
    for r in records:
        v = _num(r.get(field))
        if v is not None:
            out.append({"date": r.get("capture_date"), "value": v})
    return out


def compute_trend(pool_id: str, data_dir=None, records: Optional[List[dict]] = None) -> dict:
    """The per-pool TREND summary + sparkline series, derived from the captured history.

    `records` injects the history (tests/hermetic); else `history.read_history(pool_id)` is read.
    fail-CLOSED + THIN-aware: with < MIN_TREND_POINTS real points, every delta is None and each window
    is labeled INSUFFICIENT_DATA (no extrapolation). Returns a JSON-safe dict (the API serves verbatim).
    """
    recs = records if records is not None else dfb_history.read_history(pool_id, data_dir)
    recs = [r for r in recs if isinstance(r, dict)]
    n = len(recs)

    apy_spark = _sparkline(recs, "apy_total")
    tvl_spark = _sparkline(recs, "tvl_usd")
    refusal_changes = _refusal_changes(recs)

    deltas: Dict[str, dict] = {}
    latest = recs[-1] if recs else None
    latest_date = _date(latest.get("capture_date")) if latest else None
    latest_apy = _num(latest.get("apy_total")) if latest else None
    latest_tvl = _num(latest.get("tvl_usd")) if latest else None

    for w in TREND_WINDOWS_DAYS:
        key = f"{w}d"
        if n < MIN_TREND_POINTS or latest_date is None:
            deltas[key] = {"status": _INSUFFICIENT, "apy_delta": None, "apy_pct_change": None,
                           "tvl_delta": None, "tvl_pct_change": None}
            continue
        anchor = _anchor_for_window(recs, latest_date, w)
        if anchor is None:
            deltas[key] = {"status": _INSUFFICIENT, "apy_delta": None, "apy_pct_change": None,
                           "tvl_delta": None, "tvl_pct_change": None,
                           "note": f"no captured point at/before {w}d ago"}
            continue
        a_apy, a_tvl = _num(anchor.get("apy_total")), _num(anchor.get("tvl_usd"))
        deltas[key] = {
            "status": "ok",
            "anchor_date": anchor.get("capture_date"),
            "apy_delta": _delta(latest_apy, a_apy),
            "apy_pct_change": _pct_change(latest_apy, a_apy),
            "tvl_delta": _delta(latest_tvl, a_tvl),
            "tvl_pct_change": _pct_change(latest_tvl, a_tvl),
        }

    return {
        "pool_id": pool_id,
        "is_advisory": True,
        "n_points": n,
        "thin": n < MIN_TREND_POINTS,
        "first_date": recs[0].get("capture_date") if recs else None,
        "last_date": latest.get("capture_date") if latest else None,
        "latest": {
            "apy_total": latest_apy,
            "tvl_usd": latest_tvl,
            "risk_class": latest.get("risk_class") if latest else None,
            "refusal_verdict": latest.get("refusal_verdict") if latest else None,
        },
        "deltas": deltas,
        "refusal_state_changes": refusal_changes,
        "n_refusal_state_changes": len(refusal_changes),
        "series": {
            "apy_total": apy_spark,
            "tvl_usd": tvl_spark,
        },
        "note": (None if n >= MIN_TREND_POINTS else
                 f"{_INSUFFICIENT}: {n} captured point(s) (need >= {MIN_TREND_POINTS} for a trend); "
                 "no line is extrapolated."),
    }

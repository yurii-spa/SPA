"""Investment CIO — WP-S01 accrual correlation (ADR-554 WP-A05 / F6).

Pearson correlation of daily returns between sleeves, and separately between the
observe-only research series (conservative vs rates_desk etc.), computed ONLY on the
CURRENT economics of each series (re-versioned books do not smuggle a dead version's
history into the figure). Below the overlap/variance minimums the result is an explicit
``NOT_ENOUGH_HISTORY`` / ``UNDEFINED`` cell, never a fabricated number — today every
official DeFi pair is NOT_ENOUGH_HISTORY because Balanced/Aggressive carry only 2 valid
periods since the 2026-10-02 re-versioning (ADR-554, independent review F6/F9).

Any coefficient this module DOES compute is labelled ``accrual_correlation`` and never
raises confidence: sleeve mark-to-market coverage is 0%, so what moves together is the
APY *feed*, not realised tail risk.

Pure function of its inputs; writes nothing.

# LLM_FORBIDDEN — deterministic statistics over already-measured return series.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.investment_cio import contract

POLICY = contract.POLICY


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _read_jsonl(path: Path) -> Optional[list]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    rows = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _returns_from_points(points: list[tuple[str, float]]) -> dict[str, float]:
    """points: [(date_str, level)] (equity or similar). Returns {date_t: pct change vs date_{t-1}}."""
    pts = sorted({d: v for d, v in points if isinstance(v, (int, float)) and not isinstance(v, bool)}.items())
    out: dict[str, float] = {}
    for i in range(1, len(pts)):
        d0, v0 = pts[i - 1]
        d1, v1 = pts[i]
        if v0 == 0:
            continue
        out[d1] = (v1 / v0) - 1.0
    return out


def _series_conservative(data_dir: Path) -> Optional[dict]:
    doc = _read_json(data_dir / "equity_curve_daily.json")
    rows = (doc or {}).get("daily") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    out = {}
    for r in rows:
        if isinstance(r, dict) and r.get("evidenced") is True and isinstance(r.get("daily_return_pct"), (int, float)):
            out[r.get("date")] = r["daily_return_pct"] / 100.0
    return out or None


def _series_from_daily_history(data_dir: Path, relpath: str) -> Optional[dict]:
    doc = _read_json(data_dir / relpath)
    rows = (doc or {}).get("daily_history") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    current = [r for r in rows if isinstance(r, dict) and r.get("economics_model") == "sleeve-econ-v2"]
    points = [(r.get("date"), r.get("equity")) for r in current if isinstance(r, dict)]
    returns = _returns_from_points(points)
    return returns or None


def _series_cash(cons_dates: list[str]) -> dict:
    return {d: 0.0 for d in cons_dates}


def _series_variant_n(data_dir: Path) -> Optional[dict]:
    doc = _read_json(data_dir / "strategy_lab_paper" / "variant_n_series.json")
    series = (doc or {}).get("series") if isinstance(doc, dict) else None
    if not isinstance(series, list):
        return None
    points = [(r.get("date"), r.get("equity_usd")) for r in series if isinstance(r, dict)]
    return _returns_from_points(points) or None


def _series_susde_dn(data_dir: Path) -> Optional[dict]:
    rows = _read_jsonl(data_dir / "aggressive_lab" / "susde_dn" / "realized_series.jsonl")
    if not rows:
        return None
    points = [(r.get("date"), r.get("equity_usd")) for r in rows if isinstance(r, dict)]
    return _returns_from_points(points) or None


def _series_rates_desk(data_dir: Path) -> Optional[dict]:
    rows = _read_jsonl(data_dir / "rates_desk" / "equity_track.jsonl")
    if not rows:
        return None
    points = [(r.get("date"), r.get("close_equity")) for r in rows if isinstance(r, dict)]
    return _returns_from_points(points) or None


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sx * sy)


def _pair(name_a: str, series_a: Optional[dict], name_b: str, series_b: Optional[dict], now: datetime) -> dict:
    if series_a is None or series_b is None:
        missing = [n for n, s in ((name_a, series_a), (name_b, series_b)) if s is None]
        cell = contract.absent(contract.NOT_ENOUGH_HISTORY,
                                reason=f"no return series published for: {missing}", n=0)
        return {"pair": [name_a, name_b], "overlap_days": 0, "correlation": cell}

    common = sorted(set(series_a) & set(series_b))
    n = len(common)
    min_overlap = POLICY["correlation_min_overlap_days"]
    if n < min_overlap:
        cell = contract.absent(contract.NOT_ENOUGH_HISTORY,
                                reason=f"only {n} overlapping day(s) < {min_overlap} minimum", n=n)
        return {"pair": [name_a, name_b], "overlap_days": n, "correlation": cell}

    xs = [series_a[d] for d in common]
    ys = [series_b[d] for d in common]
    distinct = min(len(set(xs)), len(set(ys)))
    min_distinct = POLICY["correlation_min_distinct_returns"]
    if distinct < min_distinct:
        cell = contract.absent(contract.UNDEFINED,
                                reason=f"only {distinct} distinct return value(s) < {min_distinct} minimum "
                                       "(constant accrual)", n=n)
        return {"pair": [name_a, name_b], "overlap_days": n, "correlation": cell}

    r = _pearson(xs, ys)
    if r is None:
        cell = contract.absent(contract.UNDEFINED, reason="zero variance in at least one series", n=n)
        return {"pair": [name_a, name_b], "overlap_days": n, "correlation": cell}

    cell = contract.measured(round(r, 4), unit="accrual_correlation",
                              source="investment_cio.correlation (Pearson on daily returns, current economics only)",
                              as_of=now.isoformat(), n=n,
                              note="sleeve mark-to-market coverage 0%: co-movement of APY feeds, not tail risk")
    return {"pair": [name_a, name_b], "overlap_days": n, "correlation": cell}


def build(data_dir: Path, sleeves: dict, now: datetime) -> dict:
    """Accrual correlation between official sleeves, and between the observe-only research
    series, on current-economics daily returns only."""
    data_dir = Path(data_dir)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    cons_series = _series_conservative(data_dir) if "defi_conservative" in sleeves else None
    bal_series = _series_from_daily_history(data_dir, "hy_paper_trading.json") if "defi_balanced" in sleeves else None
    agg_series = _series_from_daily_history(data_dir, "lp_paper_trading.json") if "defi_aggressive" in sleeves \
        else None
    cash_series = _series_cash(sorted(cons_series)) if ("cash" in sleeves and cons_series) else None

    official_series = {
        "defi_conservative": cons_series,
        "defi_balanced": bal_series,
        "defi_aggressive": agg_series,
        "cash": cash_series,
        "trading_research": None,  # no blended sleeve-level return series published
        "market_neutral_basis": None,  # three heterogeneous strands; see research_pairs
    }
    official_ids = [sid for sid in official_series if sid in sleeves]
    official_pairs = []
    for i in range(len(official_ids)):
        for j in range(i + 1, len(official_ids)):
            a, b = official_ids[i], official_ids[j]
            official_pairs.append(_pair(a, official_series[a], b, official_series[b], now))

    research_series = {
        "defi_conservative": cons_series,
        "variant_n": _series_variant_n(data_dir),
        "susde_dn": _series_susde_dn(data_dir),
        "rates_desk": _series_rates_desk(data_dir),
    }
    research_ids = list(research_series)
    research_pairs = []
    for i in range(len(research_ids)):
        for j in range(i + 1, len(research_ids)):
            a, b = research_ids[i], research_ids[j]
            research_pairs.append(_pair(a, research_series[a], b, research_series[b], now))

    return {
        "official_pairs": official_pairs,
        "research_pairs": research_pairs,
        "policy": {
            "correlation_min_overlap_days": POLICY["correlation_min_overlap_days"],
            "correlation_min_distinct_returns": POLICY["correlation_min_distinct_returns"],
        },
    }

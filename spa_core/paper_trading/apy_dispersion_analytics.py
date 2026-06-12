#!/usr/bin/env python3
"""Yield Opportunity-Set Breadth & APY-Dispersion Analyzer (SPA-V447 / MP-125) — read-only / advisory.

A yield optimizer only adds value by *selecting* among protocols. That edge
depends on how much the protocol APYs DIFFER from one another at each point in
time — the cross-sectional dispersion. If every protocol pays nearly the same
yield the opportunity set has collapsed and there is little room to add value by
selection, no matter how good the allocator is.

This module reads each protocol's APY time series from ``data/apy_history.json``,
aligns them to a common date grid (intersection of dates present across ALL
usable protocols, like correlation_analyzer), and for every aligned date
computes the cross-section of APYs: ``min`` / ``max`` / ``spread`` (max − min) /
``mean`` / population ``stdev`` / coefficient of variation ``cv`` (stdev/mean) /
the ``best_protocol`` (argmax APY that day). A headline aggregates the dispersion
over the whole window (average / median / current / min / max spread, average and
current cv), fits an OLS trend of the per-date spread against time
(``spread_trend_per_year``) to see whether dispersion is shrinking (yields
converging → narrowing opportunity set), and measures leadership concentration
(how often a single protocol is the day's best — ``most_frequent_leader`` /
``leader_share`` / ``leadership_counts``).

This answers a due-diligence question NOT covered by the existing modules:
correlation_analyzer measures *co-movement* of yields; yield_decay_analytics
measures *per-protocol trend*; THIS module measures *cross-sectional breadth* of
the opportunity set the allocator gets to choose from, and whether that breadth
is eroding over time.

Data source
===========
Primary: ``data/apy_history.json`` — ``{"protocol_history": {"slug":
[{"ts": "...", "apy": float, "tvl_usd": float}, ...]}, "last_updated": "..."}``.
Slugs e.g. ``aave-v3-usdc-ethereum``; ~7 protocols, daily points.

Alignment
=========
Per-protocol ``[(date, apy), ...]`` series are extracted; protocols with fewer
than :data:`MIN_POINTS` numeric points are skipped. The dispersion is computed on
the intersection of dates common to ALL usable protocols. If fewer than
:data:`MIN_DATES` aligned dates remain, or fewer than 2 usable protocols, the
result is ``available: false`` with ``reason: "insufficient_data"`` and a stable
schema.

OLS slope
=========
``spread_trend_per_year`` is the OLS slope of the per-date spread series against
the integer day-index, scaled ×365. Implemented via pure stdlib (``math`` only)::

    slope = Σ(xi − x̄)(yi − ȳ) / Σ(xi − x̄)²

``None`` when fewer than 2 points, lengths differ, or x has zero variance (the
slope is undefined). Hand-verifiable.

Advisory verdict
================
**fail** if ``current_spread_pp < LOW_SPREAD_PP`` (0.5 pp) — the opportunity set
has collapsed; all protocol yields have converged and there is little room to add
value via selection. **warn** if ``spread_trend_per_year ≤ CONVERGING_SLOPE_PP_YR``
(−1.0 pp/yr — dispersion shrinking fast) OR ``leader_share ≥ 0.8`` (one protocol
almost always dominates → the opportunity is concentrated in a single name). Else
**ok**. ``verdict_reason`` is always set.

Output / persistence
====================
:func:`build_apy_dispersion` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/apy_dispersion_analytics.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: :func:`content_fingerprint`
(REUSED BY IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the
whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history`` means a
repeated ``--run`` on unchanged inputs is byte-identical and does not grow
history.

CLI::

    python3 -m spa_core.paper_trading.apy_dispersion_analytics --check    # compute+print, no write (default)
    python3 -m spa_core.paper_trading.apy_dispersion_analytics --run      # + atomic write
    python3 -m spa_core.paper_trading.apy_dispersion_analytics --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/sys/argparse/tempfile/logging/datetime/pathlib/typing) — no
requests/web3/LLM SDK/sockets/network. It only READS ``apy_history.json`` and
writes its OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# content_fingerprint is REUSED BY IMPORT (project convention, MP-501) — do NOT
# reimplement fingerprinting. The same function object is shared with
# tear_sheet (proven by an `assertIs` test).
from spa_core.reporting.tear_sheet import content_fingerprint

log = logging.getLogger("spa.paper_trading.apy_dispersion_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "apy_dispersion_analytics"
STATUS_FILENAME: str = "apy_dispersion_analytics.json"
APY_HISTORY_FILENAME: str = "apy_history.json"

MIN_POINTS: int = 7   # minimum numeric APY points per protocol to be usable
MIN_DATES: int = 7    # minimum aligned (common) dates required for analysis
HISTORY_MAX: int = 500

RECENT_DISPERSION_MAX: int = 90  # bound the per-date tail dumped into the headline

# ── Advisory thresholds (module constants) ─────────────────────────────────────
LOW_SPREAD_PP: float = 0.5            # pp — current_spread below this → fail
CONVERGING_SLOPE_PP_YR: float = -1.0  # pp/yr — spread trend at/below this → warn
LEADER_SHARE_WARN: float = 0.8        # leader_share at/above this → warn


# ──────────────────────────────────────────────────────────────────────────────
# OLS slope — pure stdlib
# ──────────────────────────────────────────────────────────────────────────────

def ols_slope(xs: List[float], ys: List[float]) -> Optional[float]:
    """Ordinary-least-squares slope of ``ys`` against ``xs`` via pure math.

        slope = Σ(xi − x̄)(yi − ȳ) / Σ(xi − x̄)²

    Returns ``None`` if fewer than 2 points, lengths differ, or ``xs`` has zero
    variance (the slope is undefined). Hand-verifiable.
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    ss_x = sum((x - mx) ** 2 for x in xs)
    if ss_x == 0.0:
        return None
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return num / ss_x


def _pop_stdev(ys: List[float]) -> float:
    """Population standard deviation (pure stdlib). 0.0 for <2 points."""
    n = len(ys)
    if n < 2:
        return 0.0
    m = sum(ys) / n
    var = sum((y - m) ** 2 for y in ys) / n
    return math.sqrt(var)


def _median(values: List[float]) -> Optional[float]:
    """Median of a list (pure stdlib). None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


# ──────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_apy_history(data_dir: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load and parse apy_history.json. Returns (data, error_note)."""
    p = data_dir / APY_HISTORY_FILENAME
    if not p.exists():
        return None, f"{APY_HISTORY_FILENAME} not found"
    try:
        raw = p.read_text(encoding="utf-8")
        d = json.loads(raw)
    except Exception as exc:
        return None, f"failed to parse {APY_HISTORY_FILENAME}: {exc}"
    if not isinstance(d, dict):
        return None, f"{APY_HISTORY_FILENAME} root is not a dict"
    ph = d.get("protocol_history")
    if not isinstance(ph, dict) or not ph:
        return None, "protocol_history missing or empty"
    return d, None


def _extract_series(
    protocol_history: Dict[str, Any],
) -> Dict[str, List[Tuple[str, float]]]:
    """For each protocol build a time-ordered ``[(date_str, apy), ...]`` list.

    Skips non-dict records and non-numeric / NaN / inf APY values (mirrors
    correlation_analyzer's filtering). Sorted by date for a stable day-index.
    """
    result: Dict[str, List[Tuple[str, float]]] = {}
    for slug, records in protocol_history.items():
        if not isinstance(records, list):
            continue
        pairs: List[Tuple[str, float]] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ts = rec.get("ts", "")
            apy = rec.get("apy")
            if not isinstance(ts, str) or not ts:
                continue
            date_str = ts[:10]  # YYYY-MM-DD
            # bool is a subclass of int — exclude it explicitly
            if isinstance(apy, bool) or not isinstance(apy, (int, float)):
                continue
            if math.isnan(apy) or math.isinf(apy):
                continue
            pairs.append((date_str, float(apy)))
        if pairs:
            pairs.sort(key=lambda t: t[0])
            result[slug] = pairs
    return result


def _to_date_map(pairs: List[Tuple[str, float]]) -> Dict[str, float]:
    """Collapse a ``[(date, apy), ...]`` list to ``{date: apy}`` (last wins)."""
    return {d: a for d, a in pairs}


def _aligned_dates(date_maps: Dict[str, Dict[str, float]]) -> List[str]:
    """Sorted intersection of dates present across ALL protocols. Empty if none."""
    if not date_maps:
        return []
    common: Optional[set] = None
    for series in date_maps.values():
        keys = set(series.keys())
        common = keys if common is None else (common & keys)
    if not common:
        return []
    return sorted(common)


def _detect_is_demo(raw_data: Dict[str, Any]) -> Optional[bool]:
    """Surface an honest demo flag from the source if present, else None.

    apy_history.json has no demo flag in the real dataset, so this is usually
    ``None`` (omitted from the headline). If a source ``is_demo`` / ``demo`` /
    ``meta.is_demo`` flag ever appears it is reported faithfully.
    """
    for key in ("is_demo", "demo"):
        v = raw_data.get(key)
        if isinstance(v, bool):
            return v
    meta = raw_data.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("is_demo"), bool):
        return meta["is_demo"]
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Per-date cross-section
# ──────────────────────────────────────────────────────────────────────────────

def _cv(mean_apy: float, stdev: float) -> Optional[float]:
    """Coefficient of variation = stdev/mean. None when mean ≤ 0."""
    if mean_apy <= 0:
        return None
    return stdev / mean_apy


def _cross_section(
    protocols: List[str], apys: List[float]
) -> Dict[str, Any]:
    """Cross-sectional dispersion stats for one aligned date.

    ``protocols`` and ``apys`` are parallel lists (same order). ``best_protocol``
    is the argmax APY (first protocol wins on ties, given the parallel order).
    """
    n = len(apys)
    min_apy = min(apys)
    max_apy = max(apys)
    spread = max_apy - min_apy
    mean_apy = sum(apys) / n
    stdev = _pop_stdev(apys)
    cv = _cv(mean_apy, stdev)

    best_idx = 0
    best_val = apys[0]
    for i in range(1, n):
        if apys[i] > best_val:
            best_val = apys[i]
            best_idx = i
    best_protocol = protocols[best_idx]

    return {
        "min_apy": round(min_apy, 6),
        "max_apy": round(max_apy, 6),
        "spread": round(spread, 6),
        "mean_apy": round(mean_apy, 6),
        "stdev": round(stdev, 6),
        "cv": (round(cv, 6) if cv is not None else None),
        "best_protocol": best_protocol,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def build_apy_dispersion(data_dir: Path = _DEFAULT_DATA_DIR) -> Dict[str, Any]:
    """Compute cross-sectional APY dispersion analysis. Never raises."""
    data_dir = Path(data_dir)
    notes: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        raw_data, err = _load_apy_history(data_dir)
        if err:
            return _unavailable(err, generated_at, notes)

        is_demo = _detect_is_demo(raw_data)
        protocol_history: Dict[str, Any] = raw_data["protocol_history"]
        series_map = _extract_series(protocol_history)

        if not series_map:
            return _insufficient(
                generated_at, notes, [], [], is_demo,
                extra_note="no valid APY series found",
            )

        # Per-protocol usability guard: need >= MIN_POINTS numeric points.
        usable: Dict[str, Dict[str, float]] = {}
        skipped: List[str] = []
        for slug in sorted(series_map.keys()):
            pairs = series_map[slug]
            if len(pairs) < MIN_POINTS:
                skipped.append(slug)
                continue
            usable[slug] = _to_date_map(pairs)

        if skipped:
            notes.append(
                f"skipped {len(skipped)} protocol(s) with < {MIN_POINTS} usable points: "
                + ", ".join(sorted(skipped))
            )

        if len(usable) < 2:
            return _insufficient(
                generated_at, notes, sorted(usable.keys()), sorted(skipped), is_demo,
                extra_note=f"need ≥ 2 usable protocols, got {len(usable)}",
            )

        aligned_dates = _aligned_dates(usable)
        num_dates = len(aligned_dates)

        if num_dates < MIN_DATES:
            return _insufficient(
                generated_at, notes, sorted(usable.keys()), sorted(skipped), is_demo,
                extra_note=f"need ≥ {MIN_DATES} aligned dates, got {num_dates}",
            )

        protocols = sorted(usable.keys())
        num_protocols = len(protocols)

        # ── Per-date cross-section over the aligned grid ──────────────────────
        per_date: List[Dict[str, Any]] = []
        spreads: List[float] = []
        cvs: List[float] = []
        leadership_counts: Dict[str, int] = {p: 0 for p in protocols}

        for t, date in enumerate(aligned_dates):
            apys = [usable[p][date] for p in protocols]
            cs = _cross_section(protocols, apys)
            leadership_counts[cs["best_protocol"]] += 1
            spreads.append(cs["spread"])
            if cs["cv"] is not None:
                cvs.append(cs["cv"])
            per_date.append({
                "date": date,
                "spread": cs["spread"],
                "mean": cs["mean_apy"],
                "cv": cs["cv"],
                "best_protocol": cs["best_protocol"],
            })

        # ── Spread aggregates ─────────────────────────────────────────────────
        avg_spread_pp = sum(spreads) / num_dates
        median_spread_pp = _median(spreads)
        current_spread_pp = spreads[-1]
        min_spread_pp = min(spreads)
        max_spread_pp = max(spreads)

        # ── CV aggregates (skip None) ─────────────────────────────────────────
        avg_cv = (sum(cvs) / len(cvs)) if cvs else None
        current_cv = per_date[-1]["cv"]

        # ── OLS trend of spread vs day-index, scaled to per-year ──────────────
        xs = [float(i) for i in range(num_dates)]
        slope_per_day = ols_slope(xs, spreads)
        spread_trend_per_year = (
            slope_per_day * 365 if slope_per_day is not None else None
        )

        # ── Leadership concentration ──────────────────────────────────────────
        # most_frequent_leader: highest count, ties broken by slug order for
        # determinism.
        most_frequent_leader = max(
            sorted(leadership_counts.keys()),
            key=lambda p: leadership_counts[p],
        )
        leader_share = leadership_counts[most_frequent_leader] / num_dates

        # ── Recent dispersion tail (bounded for charting) ─────────────────────
        recent_dispersion = per_date[-RECENT_DISPERSION_MAX:]

        # ── Advisory verdict ──────────────────────────────────────────────────
        converging = (
            spread_trend_per_year is not None
            and spread_trend_per_year <= CONVERGING_SLOPE_PP_YR
        )
        concentrated = leader_share >= LEADER_SHARE_WARN

        if current_spread_pp < LOW_SPREAD_PP:
            verdict = "fail"
            verdict_reason = (
                f"current cross-sectional spread {current_spread_pp:.4f}pp "
                f"< {LOW_SPREAD_PP}pp — opportunity set has collapsed; protocol "
                "yields have converged, little room to add value via selection"
            )
        elif converging or concentrated:
            verdict = "warn"
            if converging and concentrated:
                verdict_reason = (
                    f"spread converging at {spread_trend_per_year:.4f}pp/yr "
                    f"(≤ {CONVERGING_SLOPE_PP_YR}) AND leader {most_frequent_leader} "
                    f"dominates {leader_share:.0%} of dates (≥ {LEADER_SHARE_WARN:.0%})"
                )
            elif converging:
                verdict_reason = (
                    f"spread shrinking at {spread_trend_per_year:.4f}pp/yr "
                    f"(≤ {CONVERGING_SLOPE_PP_YR}); opportunity set narrowing over time"
                )
            else:
                verdict_reason = (
                    f"leader {most_frequent_leader} is best on {leader_share:.0%} "
                    f"of dates (≥ {LEADER_SHARE_WARN:.0%}); opportunity concentrated "
                    "in one protocol"
                )
        else:
            verdict = "ok"
            verdict_reason = (
                f"healthy dispersion: current spread {current_spread_pp:.4f}pp "
                f"across {num_protocols} protocols over {num_dates} dates; "
                "opportunity set is broad"
            )

        result: Dict[str, Any] = {
            "available": True,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "num_dates": num_dates,
            "num_protocols": num_protocols,
            "protocols": protocols,
            "start_date": aligned_dates[0],
            "end_date": aligned_dates[-1],
            "avg_spread_pp": round(avg_spread_pp, 6),
            "median_spread_pp": (
                round(median_spread_pp, 6) if median_spread_pp is not None else None
            ),
            "current_spread_pp": round(current_spread_pp, 6),
            "min_spread_pp": round(min_spread_pp, 6),
            "max_spread_pp": round(max_spread_pp, 6),
            "avg_cv": (round(avg_cv, 6) if avg_cv is not None else None),
            "current_cv": current_cv,
            "spread_trend_per_year": (
                round(spread_trend_per_year, 6)
                if spread_trend_per_year is not None
                else None
            ),
            "most_frequent_leader": most_frequent_leader,
            "leader_share": round(leader_share, 6),
            "leadership_counts": leadership_counts,
            "recent_dispersion": recent_dispersion,
            "low_spread_threshold_pp": LOW_SPREAD_PP,
            "converging_slope_threshold_pp_yr": CONVERGING_SLOPE_PP_YR,
            "leader_share_warn_threshold": LEADER_SHARE_WARN,
            "skipped_protocols": sorted(skipped),
            "is_demo": is_demo,
            "notes": notes,
            "meta": {
                "generated_at": generated_at,
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE_NAME,
                "min_points_required": MIN_POINTS,
                "min_dates_required": MIN_DATES,
            },
        }
        return result

    except Exception as exc:  # last-resort: NEVER raise
        log.exception("unexpected error in build_apy_dispersion")
        return _unavailable(f"unexpected error: {exc}", generated_at, notes)


def _unavailable(
    reason: str,
    generated_at: str,
    notes: List[str],
    is_demo: Optional[bool] = None,
) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "is_demo": is_demo,
        "notes": notes,
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
        },
    }


def _insufficient(
    generated_at: str,
    notes: List[str],
    usable_protocols: List[str],
    skipped_protocols: List[str],
    is_demo: Optional[bool],
    extra_note: str,
) -> Dict[str, Any]:
    """Stable-schema ``insufficient_data`` result."""
    return {
        "available": False,
        "reason": "insufficient_data",
        "min_points_required": MIN_POINTS,
        "min_dates_required": MIN_DATES,
        "usable_protocols": sorted(usable_protocols),
        "skipped_protocols": sorted(skipped_protocols),
        "is_demo": is_demo,
        "notes": notes + [extra_note],
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "min_points_required": MIN_POINTS,
            "min_dates_required": MIN_DATES,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Atomic persistence (content_fingerprint reused by import — see top of module)
# ──────────────────────────────────────────────────────────────────────────────

def write_status(
    result: Dict[str, Any],
    data_dir: Path = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write apy_dispersion_analytics.json.

    Returns one of: ``"DATA_WRITTEN"`` | ``"DATA_UNCHANGED"``.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / STATUS_FILENAME

    current_fp = content_fingerprint(result)

    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}

    if existing.get("_fingerprint") == current_fp:
        return "DATA_UNCHANGED"

    # Rotate previous entry into history
    history: List[Dict[str, Any]] = existing.get("history", [])
    if not isinstance(history, list):
        history = []
    if existing and "_fingerprint" in existing:
        prev_entry = {k: v for k, v in existing.items() if k != "history"}
        history = [prev_entry] + history
        history = history[:HISTORY_MAX]

    doc = dict(result)
    doc["_fingerprint"] = current_fp
    doc["history"] = history

    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".tmp_apy_dispersion_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return "DATA_WRITTEN"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[apy_dispersion_analytics] available=false "
            f"reason={result.get('reason', '?')}"
        )
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[apy_dispersion_analytics] available=true")
    print(f"  verdict        : {result['verdict']} — {result['verdict_reason']}")
    print(
        f"  protocols      : {result['num_protocols']} over "
        f"{result['num_dates']} dates "
        f"({result['start_date']} … {result['end_date']})"
    )
    print(
        f"  spread (pp)    : current={result['current_spread_pp']} "
        f"avg={result['avg_spread_pp']} median={result['median_spread_pp']} "
        f"min={result['min_spread_pp']} max={result['max_spread_pp']}"
    )
    if result.get("spread_trend_per_year") is not None:
        print(f"  spread trend   : {result['spread_trend_per_year']} pp/yr")
    if result.get("avg_cv") is not None:
        print(f"  cv             : current={result['current_cv']} avg={result['avg_cv']}")
    print(
        f"  leadership     : {result['most_frequent_leader']} "
        f"share={result['leader_share']:.0%}"
    )
    if result.get("is_demo") is not None:
        print(f"  is_demo        : {result['is_demo']}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Yield Opportunity-Set Breadth & APY-Dispersion Analyzer (MP-125)",
        add_help=True,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="compute, print, and atomically write to data/apy_dispersion_analytics.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        sys.exit(0)

    # --check / --run are mutually exclusive; conflict → ERROR to stderr,
    # exit 0 always (no traceback). Handled manually so the exit code stays 0.
    if args.check and args.run:
        print(
            "ERROR: --check and --run are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(0)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = build_apy_dispersion(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[apy_dispersion_analytics] write_status={status}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()

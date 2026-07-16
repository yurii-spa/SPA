#!/usr/bin/env python3
"""Yield Sustainability & APY-Decay Analyzer (SPA-V446 / MP-124) — read-only / advisory.

DeFi yields decay as TVL floods in — a core due-diligence risk for a yield
optimizer. This module reads each protocol's APY time series from
``data/apy_history.json`` and asks: "is each protocol's APY trending DOWN
(decaying), and is the strategy's yield edge eroding?".

For every protocol it fits an ordinary-least-squares (OLS) trend line of APY
against day-index, derives slope-per-year, splits the series into an early half
vs a recent half (decay_ratio), and classifies each protocol as
``"decaying"`` / ``"rising"`` / ``"stable"``. A headline aggregates the share
of decaying protocols, the worst offender, and an advisory verdict.

Data source
===========
Primary: ``data/apy_history.json`` — ``{"protocol_history": {"slug":
[{"ts": "...", "apy": float, "tvl_usd": float}, ...]}, "last_updated": "..."}``.
Slugs e.g. ``aave-v3-usdc-ethereum``; ~7 protocols, daily points.

OLS slope
=========
Implemented via pure stdlib (``math`` only) — no numpy/scipy. For x, y::

    slope = Σ(xi − x̄)(yi − ȳ) / Σ(xi − x̄)²

``None`` when fewer than 2 points or x has zero variance (slope undefined). The
x axis is the integer day-index 0..n-1; y is the per-day APY. The slope is
hand-verifiable.

Per-protocol metrics
====================
``slope_per_day`` (OLS slope of apy vs day index), ``slope_per_year =
slope_per_day × 365``, ``start_apy`` / ``current_apy`` (first / last),
``mean_apy``, ``apy_volatility`` (population stdev), and an early-vs-recent
split → ``early_mean`` / ``recent_mean`` / ``decay_ratio =
(recent_mean − early_mean)/early_mean`` (``None`` when ``early_mean ≤ 0``).

Classification
==============
``"decaying"`` if ``slope_per_year ≤ -DECAY_SLOPE_PP`` (1.0 pp/yr) OR
``decay_ratio ≤ -DECAY_FRACTION`` (0.15); ``"rising"`` if the symmetric positive
condition holds; else ``"stable"``.

Advisory verdict
================
**fail** if ``share_decaying ≥ 0.5`` (majority of yields decaying — the
strategy's yield edge is eroding); **warn** if any protocol is decaying
(``share_decaying > 0``) OR any single protocol shows a sharp decay
(``decay_ratio ≤ -0.30``); else **ok**.

Output / persistence
====================
:func:`build_yield_decay` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/yield_decay_analytics.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: :func:`content_fingerprint`
(REUSED BY IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the
whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history`` means a
repeated ``--run`` on unchanged inputs is byte-identical and does not grow
history.

CLI::

    python3 -m spa_core.analytics_lab.yield_decay_analytics --check    # compute+print, no write (default)
    python3 -m spa_core.analytics_lab.yield_decay_analytics --run      # + atomic write
    python3 -m spa_core.analytics_lab.yield_decay_analytics --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/sys/argparse/tempfile/logging/datetime/pathlib/hashlib/typing) —
no requests/web3/LLM SDK/sockets/network. It only READS ``apy_history.json``
and writes its OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# content_fingerprint is REUSED BY IMPORT (project convention, MP-501) — do NOT
# reimplement fingerprinting. The same function object is shared with
# tear_sheet (proven by an `assertIs` test).
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics_lab.yield_decay_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "yield_decay_analytics"
STATUS_FILENAME: str = "yield_decay_analytics.json"
APY_HISTORY_FILENAME: str = "apy_history.json"

MIN_POINTS: int = 7            # minimum numeric APY points per protocol
DECAY_SLOPE_PP: float = 1.0    # pp/yr — slope_per_year ≤ -this → decaying (≥ +this → rising)
DECAY_FRACTION: float = 0.15   # decay_ratio ≤ -this → decaying (≥ +this → rising)
SHARP_DECAY_FRACTION: float = 0.30  # single-protocol sharp-decay warn trigger
HISTORY_MAX: int = 500


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
# Per-protocol metrics
# ──────────────────────────────────────────────────────────────────────────────

def _decay_ratio(early_mean: float, recent_mean: float) -> Optional[float]:
    """(recent_mean − early_mean)/early_mean; None when early_mean ≤ 0."""
    if early_mean <= 0:
        return None
    return (recent_mean - early_mean) / early_mean


def _classify(
    slope_per_year: Optional[float], decay_ratio: Optional[float]
) -> str:
    """Classify a protocol APY trend into decaying / rising / stable."""
    decaying = (
        (slope_per_year is not None and slope_per_year <= -DECAY_SLOPE_PP)
        or (decay_ratio is not None and decay_ratio <= -DECAY_FRACTION)
    )
    if decaying:
        return "decaying"
    rising = (
        (slope_per_year is not None and slope_per_year >= DECAY_SLOPE_PP)
        or (decay_ratio is not None and decay_ratio >= DECAY_FRACTION)
    )
    if rising:
        return "rising"
    return "stable"


def _protocol_metrics(apys: List[float]) -> Dict[str, Any]:
    """Compute the per-protocol metric bundle from an APY series (>= MIN_POINTS)."""
    n = len(apys)
    xs = [float(i) for i in range(n)]  # day index 0..n-1
    slope_per_day = ols_slope(xs, apys)
    slope_per_year = slope_per_day * 365 if slope_per_day is not None else None

    start_apy = apys[0]
    current_apy = apys[-1]
    mean_apy = sum(apys) / n
    apy_volatility = _pop_stdev(apys)

    half = n // 2
    early = apys[:half]
    recent = apys[half:]
    early_mean = sum(early) / len(early) if early else 0.0
    recent_mean = sum(recent) / len(recent) if recent else 0.0
    decay_ratio = _decay_ratio(early_mean, recent_mean)

    classification = _classify(slope_per_year, decay_ratio)

    return {
        "n_points": n,
        "slope_per_day": slope_per_day,
        "slope_per_year": slope_per_year,
        "start_apy": round(start_apy, 6),
        "current_apy": round(current_apy, 6),
        "mean_apy": round(mean_apy, 6),
        "apy_volatility": round(apy_volatility, 6),
        "early_mean": round(early_mean, 6),
        "recent_mean": round(recent_mean, 6),
        "decay_ratio": (round(decay_ratio, 6) if decay_ratio is not None else None),
        "classification": classification,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def build_yield_decay(data_dir: Path = _DEFAULT_DATA_DIR) -> Dict[str, Any]:
    """Compute per-protocol APY trend / decay analysis. Never raises."""
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
            return _unavailable("no valid APY series found", generated_at, notes, is_demo)

        # Per-protocol usability guard: need >= MIN_POINTS numeric points.
        per_protocol: Dict[str, Any] = {}
        skipped: List[str] = []
        for slug in sorted(series_map.keys()):
            apys = [apy for _, apy in series_map[slug]]
            if len(apys) < MIN_POINTS:
                skipped.append(slug)
                continue
            per_protocol[slug] = _protocol_metrics(apys)

        if skipped:
            notes.append(
                f"skipped {len(skipped)} protocol(s) with < {MIN_POINTS} usable points: "
                + ", ".join(skipped)
            )

        if len(per_protocol) < 2:
            return {
                "available": False,
                "reason": "insufficient_data",
                "min_points_required": MIN_POINTS,
                "usable_protocols": sorted(per_protocol.keys()),
                "skipped_protocols": sorted(skipped),
                "is_demo": is_demo,
                "notes": notes
                + [f"need ≥ 2 usable protocols, got {len(per_protocol)}"],
                "meta": {
                    "generated_at": generated_at,
                    "schema_version": SCHEMA_VERSION,
                    "source": SOURCE_NAME,
                },
            }

        # ── Aggregate classifications ─────────────────────────────────────────
        decaying = sorted(
            s for s, m in per_protocol.items() if m["classification"] == "decaying"
        )
        rising = sorted(
            s for s, m in per_protocol.items() if m["classification"] == "rising"
        )
        stable = sorted(
            s for s, m in per_protocol.items() if m["classification"] == "stable"
        )
        n = len(per_protocol)
        share_decaying = len(decaying) / n

        # worst decay = most-negative slope_per_year among all protocols
        worst_slug: Optional[str] = None
        worst_slope: Optional[float] = None
        for slug, m in per_protocol.items():
            spy = m["slope_per_year"]
            if spy is None:
                continue
            if worst_slope is None or spy < worst_slope:
                worst_slope = spy
                worst_slug = slug

        slopes = [
            m["slope_per_year"]
            for m in per_protocol.values()
            if m["slope_per_year"] is not None
        ]
        avg_slope_per_year = (sum(slopes) / len(slopes)) if slopes else None

        # sharpest single-protocol decay_ratio (most negative)
        sharp_slug: Optional[str] = None
        sharp_ratio: Optional[float] = None
        for slug, m in per_protocol.items():
            dr = m["decay_ratio"]
            if dr is None:
                continue
            if sharp_ratio is None or dr < sharp_ratio:
                sharp_ratio = dr
                sharp_slug = slug

        # ── Advisory verdict ─────────────────────────────────────────────────
        any_sharp = sharp_ratio is not None and sharp_ratio <= -SHARP_DECAY_FRACTION
        if share_decaying >= 0.5:
            verdict = "fail"
            verdict_reason = (
                f"{len(decaying)}/{n} protocols decaying "
                f"({share_decaying:.0%}); strategy yield edge is eroding"
            )
        elif share_decaying > 0 or any_sharp:
            verdict = "warn"
            if share_decaying > 0 and any_sharp:
                verdict_reason = (
                    f"{len(decaying)}/{n} protocols decaying "
                    f"({share_decaying:.0%}); sharpest decay {sharp_slug} "
                    f"decay_ratio={sharp_ratio:.2f}"
                )
            elif share_decaying > 0:
                verdict_reason = (
                    f"{len(decaying)}/{n} protocols decaying ({share_decaying:.0%})"
                )
            else:
                verdict_reason = (
                    f"sharp single-protocol decay: {sharp_slug} "
                    f"decay_ratio={sharp_ratio:.2f} (≤ -{SHARP_DECAY_FRACTION})"
                )
        else:
            verdict = "ok"
            verdict_reason = (
                f"no protocol decaying across {n} analyzed; yields sustainable"
            )

        result: Dict[str, Any] = {
            "available": True,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "num_protocols_analyzed": n,
            "decaying": decaying,
            "rising": rising,
            "stable": stable,
            "share_decaying": round(share_decaying, 4),
            "worst_decay_protocol": worst_slug,
            "worst_decay_slope_per_year": (
                round(worst_slope, 6) if worst_slope is not None else None
            ),
            "avg_slope_per_year": (
                round(avg_slope_per_year, 6) if avg_slope_per_year is not None else None
            ),
            "sharpest_decay_protocol": sharp_slug,
            "sharpest_decay_ratio": (
                round(sharp_ratio, 6) if sharp_ratio is not None else None
            ),
            "decay_slope_threshold_pp_yr": DECAY_SLOPE_PP,
            "decay_fraction_threshold": DECAY_FRACTION,
            "per_protocol": per_protocol,
            "recent_current_apy": {
                slug: per_protocol[slug]["current_apy"] for slug in sorted(per_protocol)
            },
            "skipped_protocols": sorted(skipped),
            "is_demo": is_demo,
            "notes": notes,
            "meta": {
                "generated_at": generated_at,
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE_NAME,
                "min_points_required": MIN_POINTS,
            },
        }
        return result

    except Exception as exc:  # last-resort: NEVER raise
        log.exception("unexpected error in build_yield_decay")
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


# ──────────────────────────────────────────────────────────────────────────────
# Atomic persistence (content_fingerprint reused by import — see top of module)
# ──────────────────────────────────────────────────────────────────────────────

def write_status(
    result: Dict[str, Any],
    data_dir: Path = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write yield_decay_analytics.json.

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

    atomic_save(doc, str(out_path))
    return "DATA_WRITTEN"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[yield_decay_analytics] available=false "
            f"reason={result.get('reason', '?')}"
        )
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[yield_decay_analytics] available=true")
    print(f"  verdict       : {result['verdict']} — {result['verdict_reason']}")
    print(f"  protocols     : {result['num_protocols_analyzed']} analyzed")
    print(
        f"  share decaying: {result['share_decaying']:.0%} "
        f"(decaying={len(result['decaying'])}, rising={len(result['rising'])}, "
        f"stable={len(result['stable'])})"
    )
    if result["decaying"]:
        print(f"  decaying      : {', '.join(result['decaying'])}")
    wp = result.get("worst_decay_protocol")
    if wp is not None:
        print(
            f"  worst decay   : {wp} "
            f"slope_per_year={result['worst_decay_slope_per_year']}"
        )
    if result.get("avg_slope_per_year") is not None:
        print(f"  avg slope/yr  : {result['avg_slope_per_year']:.4f} pp/yr")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Yield Sustainability & APY-Decay Analyzer (MP-124)",
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
        help="compute, print, and atomically write to data/yield_decay_analytics.json",
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

    result = build_yield_decay(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[yield_decay_analytics] write_status={status}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()

#!/usr/bin/env python3
"""Portfolio Turnover & Rebalancing-Activity Analyzer (SPA-V441 / MP-121) — read-only / advisory.

Decomposes the realised position book (``data/equity_curve_daily.json``) into a
**portfolio-turnover** time series, answering the institutional cost/churn
question *"how much of the book is the strategy rebalancing day-to-day, and is
that churn excessive?"*. Where the tear-sheet (MP-501) reports static exposure
and drawdown_analytics (MP-115) reports the depth/length of underwater periods,
this module reports the *activity* dimension: per-day one-way turnover, the
implied average holding period, per-protocol churn, the number of genuine
rebalance days, and an advisory verdict on whether annualised turnover implies
excessive trading cost.

Definitions
===========
For each bar *t* with a positions dict (``protocol → usd_value``), portfolio
weights are the normalised shares of the *deployed* book::

    w_{i,t} = positions[i] / Σ_j positions[j]

(Cash is intentionally not in ``positions`` — weights are over deployed capital,
the convention shared with build_exposure in tear_sheet.) The **one-way daily
turnover** between consecutive bars t-1 → t is::

    turnover_t = 0.5 · Σ_i | w_{i,t} − w_{i,t-1} |   ∈ [0, 1]

(a protocol absent on one side has weight 0 there). turnover = 0 means the book
did not move; turnover = 1 means a complete rotation into entirely new protocols.

Headline metrics: avg / median / max daily turnover (+ the date of the max),
cumulative turnover (Σ over the track), annualised turnover
(``avg · 365`` — same ANNUALIZATION convention as risk_metrics / tear_sheet),
implied average holding period (``1 / avg`` days, or "buy-and-hold" when
avg = 0), number of rebalance days (turnover > :data:`REBALANCE_EPS`), the
most-churned protocol (largest Σ_t |Δw_i| over the whole track) with its share
of total movement, and a per-protocol churn breakdown.

Advisory verdict (annualised turnover): **fail** if it exceeds
:data:`HIGH_TURNOVER` (the book turns over more than 12×/year → excessive churn
and trading cost), **warn** if it exceeds :data:`MODERATE_TURNOVER` (> 4×/year),
otherwise **ok**.

Output / persistence
====================
:func:`build_turnover_analytics` returns a stable-schema dict and NEVER raises
(missing / broken / empty file → honest ``available: false`` +
``reason: "insufficient_data"`` + notes). Fewer than :data:`MIN_OBS`
turnover observations (i.e. < 2 bars carrying a usable positions dict) →
``available: false``. :func:`write_status` atomically (tmp + ``os.replace``)
writes ``data/turnover_analytics.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: the :func:`content_fingerprint`
from :mod:`spa_core.reporting.tear_sheet` is **reused by import** (single source
of truth — zero duplicated fingerprint logic) and excludes the volatile
``meta.generated_at`` / ``history``, so a repeated ``--run`` on unchanged inputs
is byte-identical and does not grow history.

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.turnover_analytics --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.turnover_analytics --run     # + atomic write
    python3 -m spa_core.paper_trading.turnover_analytics --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib) — no
requests/web3/LLM SDK/sockets/network/pandas/numpy. It only READS
``equity_curve_daily.json`` and writes its OWN status artifact; it never moves
capital and never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# REUSE BY IMPORT — single source of truth for the idempotency fingerprint
# (MP-501). We do NOT reimplement the content_fingerprint logic here.
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.turnover_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "turnover_analytics"
STATUS_FILENAME = "turnover_analytics.json"
EQUITY_FILENAME = "equity_curve_daily.json"
HISTORY_MAX = 500  # run-history rotation (pattern: tear_sheet / drawdown_analytics)
RECENT_TURNOVER_MAX = 90  # bounded tail of the turnover curve in the doc

MIN_OBS = 1  # minimum turnover observations (= bar pairs) for a verdict

REBALANCE_EPS = 0.005       # turnover_t above this counts as a rebalance day
MODERATE_TURNOVER = 4.0     # annualised turnover above this → warn
HIGH_TURNOVER = 12.0        # annualised turnover above this → fail
ANNUALIZATION_DAYS = 365    # convention shared with risk_metrics / tear_sheet

# Real (honest) track start — convention shared with index.html / portal_data.
REAL_TRACK_START = "2026-06-10"
DISCLAIMER = "NOT investment advice"


# ─── Tolerant IO / coercion helpers (pattern: tear_sheet / drawdown_analytics) ─


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _num(value: Any) -> Optional[float]:
    """Finite float or None (bool is not a number; NaN/inf are not data)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _valid_date(value: Any) -> bool:
    """True iff ``value`` is an ISO ``YYYY-MM-DD`` (prefix) date string."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def _median(values: List[float]) -> Optional[float]:
    """Median of a list of floats (None on empty). Pure stdlib."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


# ─── Weight extraction ───────────────────────────────────────────────────────


def extract_weight_series(
    equity_doc: Any,
) -> List[Tuple[str, Dict[str, float]]]:
    """Sorted ``[(date, {protocol: weight}), ...]`` from equity_curve_daily.json.

    Accepts the canonical ``{"daily": [...]}`` wrapper or a bare list of bars.
    A bar is usable only if it has a valid ``date`` and a ``positions`` dict
    whose finite, non-negative values sum to a strictly positive total; weights
    are the normalised shares ``positions[i] / Σ positions``. Bars without a
    usable positions dict are silently skipped. Never raises; bad input → ``[]``.
    """
    if isinstance(equity_doc, dict):
        daily = equity_doc.get("daily")
    else:
        daily = equity_doc
    if not isinstance(daily, list):
        return []
    out: List[Tuple[str, Dict[str, float]]] = []
    for bar in daily:
        if not isinstance(bar, dict) or not _valid_date(bar.get("date")):
            continue
        positions = bar.get("positions")
        if not isinstance(positions, dict):
            continue
        clean: Dict[str, float] = {}
        for proto, usd in positions.items():
            val = _num(usd)
            if val is not None and val > 0:
                clean[str(proto)] = val
        total = sum(clean.values())
        if total <= 0:
            continue
        weights = {p: v / total for p, v in clean.items()}
        out.append((str(bar.get("date"))[:10], weights))
    out.sort(key=lambda kv: kv[0])
    return out


def one_way_turnover(
    prev: Dict[str, float], cur: Dict[str, float]
) -> float:
    """One-way turnover ``0.5 · Σ_i |w_i,cur − w_i,prev|`` over the protocol union.

    A protocol absent on one side contributes weight 0 there. Pure function;
    result is clamped to [0, 1] to guard floating-point overshoot.
    """
    protocols = set(prev) | set(cur)
    gross = sum(abs(cur.get(p, 0.0) - prev.get(p, 0.0)) for p in protocols)
    return max(0.0, min(1.0, 0.5 * gross))


def turnover_series(
    weights: List[Tuple[str, Dict[str, float]]]
) -> List[Tuple[str, float]]:
    """Daily turnover ``[(date_t, turnover_t), ...]`` for each consecutive pair."""
    series: List[Tuple[str, float]] = []
    for i in range(1, len(weights)):
        d_prev, w_prev = weights[i - 1]
        d_cur, w_cur = weights[i]
        series.append((d_cur, one_way_turnover(w_prev, w_cur)))
    return series


def per_protocol_churn(
    weights: List[Tuple[str, Dict[str, float]]]
) -> Dict[str, float]:
    """Total absolute weight movement ``Σ_t |Δw_i|`` per protocol over the track.

    The union of |Δw_i| across all protocols equals ``2 · Σ turnover_t`` (each
    one-way turnover halves the gross movement). Pure function.
    """
    churn: Dict[str, float] = {}
    for i in range(1, len(weights)):
        w_prev = weights[i - 1][1]
        w_cur = weights[i][1]
        for proto in set(w_prev) | set(w_cur):
            delta = abs(w_cur.get(proto, 0.0) - w_prev.get(proto, 0.0))
            churn[proto] = churn.get(proto, 0.0) + delta
    return churn


# ─── Aggregate build ─────────────────────────────────────────────────────────


def _is_demo(equity_doc: Any) -> Optional[bool]:
    if isinstance(equity_doc, dict) and isinstance(equity_doc.get("is_demo"), bool):
        return equity_doc.get("is_demo")
    return None


def _unavailable(
    meta: Dict[str, Any], reason: str, num_bars: int
) -> Dict[str, Any]:
    return {
        "meta": meta,
        "available": False,
        "reason": reason,
        "track": {
            "first_date": None,
            "last_date": None,
            "num_bars": num_bars,
            "num_observations": 0,
        },
        "headline": {
            "num_observations": 0,
            "avg_daily_turnover": None,
            "median_daily_turnover": None,
            "max_daily_turnover": None,
            "max_turnover_date": None,
            "cumulative_turnover": None,
            "annualized_turnover": None,
            "implied_avg_holding_days": None,
            "num_rebalance_days": 0,
            "most_churned_protocol": None,
            "most_churned_share": None,
        },
        "verdict": None,
        "verdict_reason": None,
        "per_protocol_churn": {},
        "recent_turnover": [],
    }


def build_turnover_analytics(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the turnover-analytics document. Stable schema, never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []

    equity_doc = _read_json(ddir / EQUITY_FILENAME)
    if equity_doc is None:
        notes.append(f"{EQUITY_FILENAME} missing or unreadable — no analytics")
    weights = extract_weight_series(equity_doc)
    is_demo = _is_demo(equity_doc)

    meta = {
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "source_file": EQUITY_FILENAME,
        "real_track_start": REAL_TRACK_START,
        "is_demo": is_demo,
        "rebalance_eps": REBALANCE_EPS,
        "moderate_turnover": MODERATE_TURNOVER,
        "high_turnover": HIGH_TURNOVER,
        "annualization_days": ANNUALIZATION_DAYS,
    }

    series = turnover_series(weights)
    num_obs = len(series)

    if num_obs < MIN_OBS:
        if equity_doc is not None:
            notes.append(
                "fewer than 2 bars with a usable positions dict — "
                "no turnover observations"
            )
        meta["notes"] = notes
        return _unavailable(meta, "insufficient_data", len(weights))

    values = [t for _, t in series]
    avg_t = sum(values) / len(values)
    median_t = _median(values)
    max_idx = max(range(len(series)), key=lambda i: series[i][1])
    max_t = series[max_idx][1]
    max_date = series[max_idx][0]
    cumulative_t = sum(values)
    annualized_t = avg_t * ANNUALIZATION_DAYS
    implied_holding = (1.0 / avg_t) if avg_t > 0 else None
    num_rebalance = sum(1 for v in values if v > REBALANCE_EPS)

    churn = per_protocol_churn(weights)
    total_movement = sum(churn.values())
    if churn and total_movement > 0:
        most_churned = max(churn.items(), key=lambda kv: (kv[1], kv[0]))[0]
        most_churned_share = churn[most_churned] / total_movement
    else:
        most_churned = None
        most_churned_share = None

    # Advisory verdict on annualised turnover.
    if annualized_t > HIGH_TURNOVER:
        verdict = "fail"
        verdict_reason = (
            f"annualized turnover {annualized_t:.2f}× > {HIGH_TURNOVER}× — "
            "excessive churn / trading cost; book turns over too often"
        )
    elif annualized_t > MODERATE_TURNOVER:
        verdict = "warn"
        verdict_reason = (
            f"annualized turnover {annualized_t:.2f}× > {MODERATE_TURNOVER}× — "
            "moderate-to-high rebalancing activity; watch trading cost"
        )
    else:
        verdict = "ok"
        verdict_reason = (
            f"annualized turnover {annualized_t:.2f}× ≤ {MODERATE_TURNOVER}× — "
            "turnover within a cost-efficient range"
        )

    headline = {
        "num_observations": num_obs,
        "avg_daily_turnover": _round(avg_t),
        "median_daily_turnover": _round(median_t),
        "max_daily_turnover": _round(max_t),
        "max_turnover_date": max_date,
        "cumulative_turnover": _round(cumulative_t),
        "annualized_turnover": _round(annualized_t),
        "implied_avg_holding_days": _round(implied_holding, 4) if implied_holding is not None else None,
        "num_rebalance_days": num_rebalance,
        "most_churned_protocol": most_churned,
        "most_churned_share": _round(most_churned_share),
    }

    meta["notes"] = notes
    return {
        "meta": meta,
        "available": True,
        "reason": None,
        "track": {
            "first_date": weights[0][0],
            "last_date": weights[-1][0],
            "num_bars": len(weights),
            "num_observations": num_obs,
        },
        "headline": headline,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "per_protocol_churn": {
            p: _round(c) for p, c in sorted(churn.items())
        },
        "recent_turnover": [
            {"date": d, "turnover": _round(t)}
            for d, t in series[-RECENT_TURNOVER_MAX:]
        ],
    }


# ─── Persist (idempotent, pattern: tear_sheet MP-501 / drawdown_analytics) ────
# content_fingerprint is REUSED BY IMPORT from tear_sheet (see module header):
# it excludes volatile meta.generated_at / history, so a repeated --run on
# unchanged inputs is byte-identical and does not grow history.


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record for turnover_analytics.json."""
    meta = doc.get("meta") or {}
    head = doc.get("headline") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "avg_daily_turnover": head.get("avg_daily_turnover"),
        "annualized_turnover": head.get("annualized_turnover"),
        "num_rebalance_days": head.get("num_rebalance_days"),
        "verdict": doc.get("verdict"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/turnover_analytics.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` (reused from tear_sheet) is
    unchanged relative to the persisted status, the file is NOT rewritten (a
    repeated ``--run`` is byte-identical and history does not grow). On a
    content change a short record is appended to ``history`` (rotation ≤
    :data:`HISTORY_MAX`). A broken/absent existing status file is tolerated as
    fresh.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("turnover analytics unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("turnover analytics written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.turnover_analytics",
        description=(
            "Portfolio Turnover & Rebalancing-Activity Analyzer "
            "(SPA-V441 / MP-121): read-only / advisory decomposition of the "
            "position book into a daily one-way turnover series + per-protocol "
            "churn. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON analytics WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/turnover_analytics.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: drawdown_analytics.py).
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        doc = build_turnover_analytics(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            head = doc.get("headline") or {}
            state = "DATA_WRITTEN" if outcome["changed"] else "DATA_UNCHANGED"
            print(
                f"turnover_analytics: available={doc.get('available')} "
                f"verdict={doc.get('verdict')} "
                f"avg={head.get('avg_daily_turnover')} "
                f"annualized={head.get('annualized_turnover')} "
                f"obs={head.get('num_observations')} — "
                f"{state} {outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"turnover_analytics: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

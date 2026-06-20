#!/usr/bin/env python3
"""Tail Risk Analyzer — VaR/CVaR (SPA-V438 / MP-119) — read-only / advisory.

Computes historical-simulation tail risk metrics from the realised equity track
(``data/equity_curve_daily.json``), answering the institutional DD question
*"how bad can a single day / week / month get, and what is the expected loss
given that we are already in the tail?"*:

* **VaR 95% / 99%** — Value-at-Risk via historical-simulation percentile
  (5th / 1st percentile of the daily return distribution; negative = loss).
* **CVaR 95% / 99%** — Conditional VaR / Expected Shortfall: average of the
  worst 5% / 1% of return days (≤ VaR in absolute loss terms by construction).
* **Worst day** — single worst close-to-close return (%).
* **Worst week** — worst 5-bar rolling compound return (%).
* **Worst month** — worst 21-bar rolling compound return (%).
* **Skewness** — Fisher population skewness of the return distribution (negative
  = left-tail / loss-skewed).
* **Kurtosis** — Fisher excess kurtosis (population, 0 = normal; positive =
  fat tails relative to normal).
* **Tail ratio** — avg positive return / |avg negative return| (> 1 → gain
  side dominates; < 1 → loss side dominates).
* **Verdict** — advisory only: ok (|VaR_99| < 3%), warn (3–5%), fail (≥ 5%).

Percentile / interpolation
==========================
VaR is computed as a percentile of the sorted empirical return distribution
using **linear interpolation** (identical to ``numpy.percentile`` default /
``statistics.quantiles`` with ``method='inclusive'`` semantics):
``result = sorted[lo] + frac × (sorted[hi] − sorted[lo])`` where
``idx = p / 100 × (n − 1)``, ``lo = floor(idx)``, ``hi = min(lo+1, n-1)``,
``frac = idx − lo``. Pure stdlib — no numpy / scipy / pandas.

CVaR uses ``ceil(n × tail_fraction)`` worst observations (at least 1), which
guarantees ``CVaR ≤ VaR`` (the expected value of the worst-tail subset is
always ≤ the worst single observation used as the percentile boundary).

Rolling windows
===============
Worst week = worst return over any window of 5 consecutive bars (4 return
periods; ``equity[i] / equity[i-4] − 1``); worst month uses 21 bars (20
periods). Returns ``None`` when the series is too short.

Skewness / Kurtosis
===================
Population formulas (no Bessel correction):

    skewness = Σ(x − μ)³ / (n · σ³)        [0 → symmetric]
    kurtosis = Σ(x − μ)⁴ / (n · σ⁴) − 3    [0 → normal; + → fat tails]

Output / persistence
====================
:func:`build_tail_risk` returns a stable-schema flat dict and NEVER raises
(missing / broken / empty file → honest nulls + ``available=False``).
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/tail_risk.json`` with an in-file ``history`` of runs (rotation ≤
:data:`HISTORY_MAX`). Idempotency: :func:`content_fingerprint` over the doc
EXCLUDING the volatile ``generated_at`` / ``history`` ensures a repeated
``--run`` on unchanged inputs does not grow the history.

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR stderr)::

    python3 -m spa_core.paper_trading.tail_risk --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.tail_risk --run     # + atomic write
    python3 -m spa_core.paper_trading.tail_risk --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib) — no
requests/web3/LLM SDK/sockets/network. Reads ONLY ``equity_curve_daily.json``
and writes its OWN artifact; never moves capital and never touches
risk/execution/allocator/cycle_runner.
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
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.tail_risk")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = "1.0"
SOURCE_NAME = "tail_risk"
STATUS_FILENAME = "tail_risk.json"
EQUITY_FILENAME = "equity_curve_daily.json"
HISTORY_MAX = 500

REAL_TRACK_START = "2026-06-10"
DISCLAIMER = "NOT investment advice"

# Verdict thresholds on |VaR_99_pct| (percentage points)
VERDICT_WARN_THRESHOLD = 3.0   # >= 3% → warn
VERDICT_FAIL_THRESHOLD = 5.0   # >= 5% → fail

# Rolling-window sizes in *steps* (bars - 1)
WEEK_WINDOW_STEPS = 4    # 5 bars = 4 step-returns ≈ 1 trading week
MONTH_WINDOW_STEPS = 20  # 21 bars = 20 step-returns ≈ 1 trading month

# Minimum tail size for CVaR (at least 1 observation)
_MIN_TAIL = 1


# ─── Tolerant IO helpers ──────────────────────────────────────────────────────


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
    """Finite float or None (bool is not a number; NaN/inf → None)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _valid_date(value: Any) -> bool:
    """True iff value is an ISO YYYY-MM-DD (prefix) date string."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    return None if value is None else round(value, ndigits)


# ─── Equity series extraction ─────────────────────────────────────────────────


def extract_equity_series(equity_doc: Any) -> List[Tuple[str, float]]:
    """Sorted [(date, close_equity), ...] from equity_curve_daily.json.

    Accepts either the canonical ``{"daily": [...]}`` wrapper or a bare list
    of bars. Each bar must have a valid ``date`` and a finite positive
    ``close_equity`` (fallback ``equity``); other bars are silently skipped.
    Never raises; bad input → ``[]``.
    """
    if isinstance(equity_doc, dict):
        daily = equity_doc.get("daily")
    else:
        daily = equity_doc
    if not isinstance(daily, list):
        return []
    out: List[Tuple[str, float]] = []
    for bar in daily:
        if not isinstance(bar, dict) or not _valid_date(bar.get("date")):
            continue
        eq = _num(bar.get("close_equity"))
        if eq is None:
            eq = _num(bar.get("equity"))
        if eq is None or eq <= 0:
            continue
        out.append((str(bar.get("date"))[:10], eq))
    out.sort(key=lambda kv: kv[0])
    return out


def _returns_from_levels(series: List[Tuple[str, float]]) -> List[float]:
    """Close-to-close daily returns (%) from a sorted level series."""
    returns: List[float] = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        cur = series[i][1]
        if prev > 0:
            returns.append((cur / prev - 1.0) * 100.0)
    return returns


def _extract_levels(series: List[Tuple[str, float]]) -> List[float]:
    return [eq for _, eq in series]


def _is_demo(equity_doc: Any) -> Optional[bool]:
    if isinstance(equity_doc, dict) and isinstance(equity_doc.get("is_demo"), bool):
        return equity_doc.get("is_demo")
    return None


# ─── Pure-stdlib statistical functions ───────────────────────────────────────


def percentile(sorted_data: List[float], p: float) -> Optional[float]:
    """p-th percentile of pre-sorted data via linear interpolation.

    ``p`` in ``[0, 100]``. Identical to ``numpy.percentile(data, p,
    interpolation='linear')`` and to the default ``statistics.quantiles``
    result when the data is the entire population. Returns ``None`` on empty
    data; single-element data returns that element regardless of ``p``.
    """
    n = len(sorted_data)
    if n == 0:
        return None
    if n == 1:
        return sorted_data[0]
    idx = p / 100.0 * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_data[lo] + frac * (sorted_data[hi] - sorted_data[lo])


def compute_var(sorted_returns: List[float], confidence: float) -> Optional[float]:
    """VaR at *confidence* level (e.g. 95) via historical simulation.

    Returns the ``(100 − confidence)``-th percentile of the sorted return
    distribution (a negative value represents a loss day). Returns ``None``
    for empty input.
    """
    if not sorted_returns:
        return None
    tail_pct = 100.0 - confidence
    return percentile(sorted_returns, tail_pct)


def compute_cvar(sorted_returns: List[float], confidence: float) -> Optional[float]:
    """CVaR (Expected Shortfall) at *confidence* level.

    Average return of the worst ``(100 − confidence)%`` of days.  Uses
    ``ceil(n × tail_fraction)`` tail observations (at least 1), guaranteeing
    ``CVaR ≤ VaR`` by construction (every tail observation ≤ the VaR
    boundary). Returns ``None`` for empty input.
    """
    n = len(sorted_returns)
    if n == 0:
        return None
    tail_frac = (100.0 - confidence) / 100.0
    cutoff = max(_MIN_TAIL, math.ceil(n * tail_frac))
    tail = sorted_returns[:cutoff]  # ascending sort → worst (most negative) first
    return sum(tail) / len(tail)


def worst_rolling(levels: List[float], window_steps: int) -> Optional[float]:
    """Worst compound return (%) over a rolling window of ``window_steps+1`` bars.

    E.g. ``window_steps=4`` → rolling 5-bar (≈ 1 week) worst return:
    ``min_i(equity[i] / equity[i-4] − 1) × 100``. Returns ``None`` when the
    series has fewer than ``window_steps+1`` bars.
    """
    n = len(levels)
    if n <= window_steps:
        return None
    worst: Optional[float] = None
    for i in range(window_steps, n):
        prev = levels[i - window_steps]
        cur = levels[i]
        if prev > 0:
            ret = (cur / prev - 1.0) * 100.0
            if worst is None or ret < worst:
                worst = ret
    return worst


def population_std(data: List[float]) -> Optional[float]:
    """Population standard deviation (divide by n, no Bessel correction)."""
    n = len(data)
    if n < 2:
        return None
    m = sum(data) / n
    var = sum((x - m) ** 2 for x in data) / n
    if not math.isfinite(var) or var < 0:
        return None
    return math.sqrt(var)


def skewness(returns: List[float]) -> Optional[float]:
    """Fisher population skewness (no bias correction).

    Negative → left-skewed (loss-heavy tail); zero → symmetric.
    Returns ``None`` with fewer than 3 observations or zero std.
    """
    n = len(returns)
    if n < 3:
        return None
    m = sum(returns) / n
    std = population_std(returns)
    if std is None or std == 0.0:
        return None
    sk = sum((x - m) ** 3 for x in returns) / (n * std ** 3)
    return sk if math.isfinite(sk) else None


def excess_kurtosis(returns: List[float]) -> Optional[float]:
    """Fisher excess kurtosis (population, 0 = normal; + = fat tails).

    Returns ``None`` with fewer than 4 observations or zero std.
    """
    n = len(returns)
    if n < 4:
        return None
    m = sum(returns) / n
    std = population_std(returns)
    if std is None or std == 0.0:
        return None
    kurt = sum((x - m) ** 4 for x in returns) / (n * std ** 4) - 3.0
    return kurt if math.isfinite(kurt) else None


def tail_ratio(returns: List[float]) -> Optional[float]:
    """Ratio of avg positive return to |avg negative return|.

    > 1 → gain tail dominates; < 1 → loss tail dominates; ``None`` when no
    negative returns exist (pathological all-positive case).
    """
    pos = [r for r in returns if r > 0]
    neg = [r for r in returns if r < 0]
    if not neg:
        return None
    avg_neg_abs = abs(sum(neg) / len(neg))
    if avg_neg_abs == 0.0:
        return None
    avg_pos = sum(pos) / len(pos) if pos else 0.0
    ratio = avg_pos / avg_neg_abs
    return ratio if math.isfinite(ratio) else None


def _verdict(var_99_pct: Optional[float]) -> Tuple[str, str]:
    """Advisory verdict based on |VaR 99%|."""
    if var_99_pct is None:
        return "ok", "insufficient data for VaR computation"
    abs_val = abs(var_99_pct)
    if abs_val < VERDICT_WARN_THRESHOLD:
        return "ok", f"VaR 99% within normal range ({abs_val:.4f}%)"
    elif abs_val < VERDICT_FAIL_THRESHOLD:
        return "warn", f"VaR 99% elevated at {abs_val:.4f}%"
    else:
        return "fail", f"VaR 99% critical at {abs_val:.4f}%"


# ─── Main build function ──────────────────────────────────────────────────────


def build_tail_risk(
    data_dir: Optional["str | os.PathLike[str]"] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the tail-risk analytics document. Stable schema, never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []

    equity_doc = _read_json(ddir / EQUITY_FILENAME)
    if equity_doc is None:
        notes.append(f"{EQUITY_FILENAME} missing or unreadable — no analytics")

    series = extract_equity_series(equity_doc)
    is_demo_val = _is_demo(equity_doc)
    returns = _returns_from_levels(series)
    levels = _extract_levels(series)

    n_obs = len(returns)

    # Baseline document fields (common to available and unavailable case)
    base: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "is_demo": is_demo_val,
        "source": SOURCE_NAME,
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "real_track_start": REAL_TRACK_START,
    }

    if n_obs == 0:
        if equity_doc is not None:
            notes.append(
                f"equity series has {n_obs} return observations — no analytics"
            )
        return {
            **base,
            "available": False,
            "var_95_pct": None,
            "var_99_pct": None,
            "cvar_95_pct": None,
            "cvar_99_pct": None,
            "worst_day_pct": None,
            "worst_week_pct": None,
            "worst_month_pct": None,
            "skewness": None,
            "kurtosis": None,
            "tail_ratio": None,
            "n_observations": 0,
            "verdict": "ok",
            "verdict_reason": "insufficient data for VaR computation",
            "notes": notes,
        }

    sorted_returns = sorted(returns)

    var_95 = compute_var(sorted_returns, 95.0)
    var_99 = compute_var(sorted_returns, 99.0)
    cvar_95 = compute_cvar(sorted_returns, 95.0)
    cvar_99 = compute_cvar(sorted_returns, 99.0)

    worst_day = min(returns)
    worst_week = worst_rolling(levels, WEEK_WINDOW_STEPS)
    worst_month = worst_rolling(levels, MONTH_WINDOW_STEPS)

    sk = skewness(returns)
    kt = excess_kurtosis(returns)
    tr = tail_ratio(returns)

    verdict_str, verdict_reason = _verdict(var_99)

    if n_obs < 30:
        notes.append(
            f"only {n_obs} return observation(s) — "
            "VaR/CVaR estimates have high uncertainty (recommend ≥ 30 days)"
        )

    return {
        **base,
        "available": True,
        "var_95_pct": _round(var_95, 4),
        "var_99_pct": _round(var_99, 4),
        "cvar_95_pct": _round(cvar_95, 4),
        "cvar_99_pct": _round(cvar_99, 4),
        "worst_day_pct": _round(worst_day, 4),
        "worst_week_pct": _round(worst_week, 4),
        "worst_month_pct": _round(worst_month, 4),
        "skewness": _round(sk, 6),
        "kurtosis": _round(kt, 6),
        "tail_ratio": _round(tr, 6),
        "n_observations": n_obs,
        "verdict": verdict_str,
        "verdict_reason": verdict_reason,
        "notes": notes,
    }


# ─── Persist (idempotent, atomic) ─────────────────────────────────────────────


def content_fingerprint(doc: Any) -> str:
    """Stable fingerprint of document content, excluding volatile fields.

    Excludes ``generated_at`` and ``history`` (the two fields that change on
    every write). Non-dict input → a sentinel that never matches a valid doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k not in ("history", "generated_at")}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record stored inside tail_risk.json."""
    return {
        "generated_at": doc.get("generated_at"),
        "var_99_pct": doc.get("var_99_pct"),
        "cvar_99_pct": doc.get("cvar_99_pct"),
        "n_observations": doc.get("n_observations"),
        "verdict": doc.get("verdict"),
    }


def write_status(
    doc: Dict[str, Any],
    data_dir: Optional["str | os.PathLike[str]"] = None,
) -> Dict[str, Any]:
    """Atomically write data/tail_risk.json (tmp + os.replace). Idempotent.

    If :func:`content_fingerprint` is unchanged relative to the persisted
    status the file is NOT rewritten and ``changed=False`` is returned. On
    a content change a short record is appended to ``history`` (rotation ≤
    :data:`HISTORY_MAX`). A broken / absent existing status file is tolerated.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("tail risk unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("tail risk written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.tail_risk",
        description=(
            "Tail Risk Analyzer — VaR/CVaR (SPA-V438 / MP-119): "
            "read-only / advisory historical simulation of daily returns. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="compute and print the JSON analytics WITHOUT writing (default)",
    )
    group.add_argument(
        "--run",
        action="store_true",
        help="compute and atomically write data/tail_risk.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point — always exits 0; errors go to stderr."""
    parser = _build_arg_parser()
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
        doc = build_tail_risk(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            print(
                f"tail_risk: VaR99={doc.get('var_99_pct')}% "
                f"CVaR99={doc.get('cvar_99_pct')}% "
                f"n={doc.get('n_observations')} "
                f"verdict={doc.get('verdict')} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks to stdout, exit 0
        print(
            f"tail_risk: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

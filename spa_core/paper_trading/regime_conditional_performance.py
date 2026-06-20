#!/usr/bin/env python3
"""Regime-Conditional Performance Analyzer (SPA-V450 / MP-131) — read-only / advisory.

Splits the realised equity track by **market regime** and computes per-regime
performance (annualised Sharpe + annualised APY + return stats) so we can see
*which regime the strategy breaks in*. The headline DD question is blunt: "does
the strategy make money in a BULL market but lose it in a BEAR market?". The
advisory verdict therefore **fails** when the BEAR-regime Sharpe is negative.

Adaptation note (IMPORTANT)
===========================
The KANBAN card for MP-131 references a ``market_data.json`` source and a
``RegimeSegmenter`` class — neither exists in this repo. This module instead
reuses the REAL components shipped by earlier sprints, BY IMPORT:

* **Regime labels** come from the MP-129 engine
  :mod:`spa_core.paper_trading.regime_detector` —
  :func:`~spa_core.paper_trading.regime_detector.load_apy_history` normalises
  ``data/apy_history.json`` (the ``{protocol_history:{slug:[{ts,apy,tvl_usd}]}}``
  shape) into flat ``[{date,protocol,apy,...}]`` records, and
  :func:`~spa_core.paper_trading.regime_detector.regime_history` produces a
  sparse weekly (``step_days``) chronological timeline of
  ``{"date","regime","confidence"}`` where ``regime ∈ {BULL, BEAR, SIDEWAYS,
  VOLATILE}``.
* **Equity track** comes from
  :func:`spa_core.paper_trading.drawdown_analytics.extract_equity_series`, which
  returns sorted ``[(date, close_equity), ...]`` from
  ``data/equity_curve_daily.json`` (``{..., "daily":[{date, close_equity, ...}]}``).
* **content_fingerprint** is REUSED BY IMPORT (convention MP-501) from
  :mod:`spa_core.reporting.tear_sheet` — we do NOT reimplement fingerprinting.

We import these functions; we do not duplicate their logic.

Method
======
1. Build the dated regime timeline via ``regime_history`` — a sparse, weekly
   step function. **Forward-fill** so every equity date maps to the most recent
   regime label *at-or-before* that date. Equity dates before the first label →
   ``UNKNOWN`` (skipped from regime buckets).
2. Compute daily returns from consecutive close-equity:
   ``r_t = close_t / close_{t-1} − 1`` (a fraction). Bucket each return into the
   regime that was in force on its date.
3. Per regime with ``>= MIN_REGIME_OBS`` observations: ``num_days``,
   ``mean_daily_return_pct``, ``stdev_daily_return_pct`` (population),
   **annualised Sharpe** ``= mean/stdev * sqrt(365)`` (``None`` if stdev == 0 or
   < 2 obs), ``annualized_apy_pct = ((1+mean)**365 − 1)*100`` (mean as a
   fraction; overflow-guarded), ``total_return_pct``, ``best_day_pct``,
   ``worst_day_pct``.
4. Headline: ``regimes`` (per-regime dict), ``num_regimes_observed``,
   ``dominant_regime`` (most days), an ``overall`` block (all bucketed days
   pooled), and the ``worst_regime`` / ``worst_regime_sharpe``.

Advisory verdict
================
* **fail** — BEAR regime observed with ``>= MIN_REGIME_OBS`` days, its Sharpe is
  not ``None``, and that Sharpe ``< 0`` (the strategy loses in bear markets — a
  core DD red flag).
* **warn** — BEAR days exist but Sharpe is ``None`` (low sample), OR any
  observed regime has a negative Sharpe, OR the pooled overall Sharpe ``< 0``.
* **ok** — otherwise.

Always carries ``verdict_reason``. Too-short equity / regime timeline →
``available: False``, ``reason: "insufficient_data"`` with a stable schema.

Output / persistence
====================
:func:`build_regime_conditional_performance` returns a stable-schema dict and
NEVER raises. :func:`write_status` atomically (``tempfile.mkstemp`` +
``os.replace``) writes ``data/regime_conditional_performance.json`` with an
in-file ``history`` of runs (rotation ≤ :data:`HISTORY_MAX`). Idempotency:
:func:`content_fingerprint` (reused by import, strips volatile
``meta.generated_at`` / ``history``) means a repeated ``--run`` on unchanged
inputs is byte-identical and does not grow history.

CLI (offline, exit 0 always, no tracebacks; junk args → ERROR on stderr)::

    python3 -m spa_core.paper_trading.regime_conditional_performance --check  # compute+print, no write (default)
    python3 -m spa_core.paper_trading.regime_conditional_performance --run    # + atomic write
    python3 -m spa_core.paper_trading.regime_conditional_performance --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/sys/argparse/tempfile/logging/datetime/pathlib) — no
requests/web3/LLM SDK/sockets/network. It only READS ``apy_history.json`` and
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Regime labels (MP-129) and equity extraction (MP-115) are REUSED BY IMPORT —
# we do not duplicate the regime classification or the equity-parsing logic.
from spa_core.paper_trading.regime_detector import load_apy_history, regime_history
from spa_core.paper_trading.drawdown_analytics import extract_equity_series

# content_fingerprint is REUSED BY IMPORT (project convention, MP-501) — do NOT
# reimplement fingerprinting. The same function object is shared with
# tear_sheet (proven by an `assertIs` test).
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.regime_conditional_performance")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "regime_conditional_performance"
STATUS_FILENAME: str = "regime_conditional_performance.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"

HISTORY_MAX: int = 500

# Below this many observations a regime bucket still reports counts but Sharpe /
# APY are None (not enough sample to be meaningful).
MIN_REGIME_OBS: int = 3
# Need at least this many bucketed daily returns overall to even try.
MIN_TOTAL_OBS: int = 2
# Annualisation factor (daily → yearly), DeFi convention uses 365 calendar days.
ANNUALISATION_DAYS: int = 365

REGIME_LABELS: Tuple[str, ...] = ("BULL", "BEAR", "SIDEWAYS", "VOLATILE")
UNKNOWN_LABEL: str = "UNKNOWN"
DISCLAIMER: str = "NOT investment advice"


# ──────────────────────────────────────────────────────────────────────────────
# Pure-math helpers (pure stdlib — hand-verifiable)
# ──────────────────────────────────────────────────────────────────────────────

def _pop_stdev(xs: List[float]) -> Optional[float]:
    """Population standard deviation. ``None`` for < 2 observations."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    return math.sqrt(max(0.0, var))


def annualised_sharpe(returns_pct: List[float]) -> Optional[float]:
    """Annualised Sharpe of a list of *percent* daily returns.

        sharpe = mean / stdev * sqrt(365)

    ``mean`` and ``stdev`` are computed on the percent series (the sqrt-365
    factor is scale-invariant, so percent vs fraction gives the same number).
    Returns ``None`` when there are < 2 observations or the stdev is 0
    (undefined / division by zero).
    """
    n = len(returns_pct)
    if n < 2:
        return None
    mean = sum(returns_pct) / n
    sd = _pop_stdev(returns_pct)
    if sd is None or sd == 0.0:
        return None
    return mean / sd * math.sqrt(ANNUALISATION_DAYS)


def annualised_apy_pct(mean_daily_fraction: float) -> Optional[float]:
    """Annualised APY (%) from a mean daily return expressed as a *fraction*.

        apy = ((1 + mean)**365 − 1) * 100

    Returns ``None`` when ``1 + mean <= 0`` (would compound to ruin / undefined)
    or on numeric overflow.
    """
    base = 1.0 + mean_daily_fraction
    if base <= 0.0:
        return None
    try:
        return (base ** ANNUALISATION_DAYS - 1.0) * 100.0
    except OverflowError:
        return None


def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    if value is None:
        return None
    try:
        if not math.isfinite(value):
            return None
    except (TypeError, ValueError):
        return None
    return round(value, ndigits)


# ──────────────────────────────────────────────────────────────────────────────
# Regime timeline → forward-fill mapping
# ──────────────────────────────────────────────────────────────────────────────

def _clean_regime_timeline(
    timeline: Any,
) -> List[Tuple[str, str]]:
    """Coerce a regime_history result into a sorted ``[(date, regime), ...]``.

    Tolerant: skips non-dict entries, entries without a valid ISO date prefix,
    or without a recognised regime label. Sorted ascending by date.
    """
    cleaned: List[Tuple[str, str]] = []
    if not isinstance(timeline, list):
        return cleaned
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        d = entry.get("date")
        regime = entry.get("regime")
        if not isinstance(d, str) or len(d) < 10:
            continue
        date_key = d[:10]
        if not isinstance(regime, str) or not regime:
            continue
        cleaned.append((date_key, regime))
    cleaned.sort(key=lambda t: t[0])
    return cleaned


def forward_fill_regime(
    equity_dates: List[str],
    timeline: List[Tuple[str, str]],
) -> Dict[str, str]:
    """Map each equity date to the most-recent regime label at-or-before it.

    The regime timeline is a sparse (weekly) step function. For an equity date
    ``d`` we pick the label of the latest timeline entry with
    ``entry_date <= d``. Equity dates *before* the first timeline entry get
    :data:`UNKNOWN_LABEL`. Both inputs may be unsorted; ``timeline`` is assumed
    already cleaned/sorted (see :func:`_clean_regime_timeline`).
    """
    mapping: Dict[str, str] = {}
    if not timeline:
        return {d: UNKNOWN_LABEL for d in equity_dates}
    for d in equity_dates:
        label = UNKNOWN_LABEL
        # latest timeline entry whose date <= d (linear scan; timeline is short)
        for t_date, t_regime in timeline:
            if t_date <= d:
                label = t_regime
            else:
                break
        mapping[d] = label
    return mapping


# ──────────────────────────────────────────────────────────────────────────────
# Per-regime metric bundle
# ──────────────────────────────────────────────────────────────────────────────

def _regime_metrics(returns_pct: List[float]) -> Dict[str, Any]:
    """Compute the per-regime metric bundle from a list of percent returns.

    Always reports ``num_days``; Sharpe / APY / stat fields are ``None`` when
    the sample is below :data:`MIN_REGIME_OBS` or otherwise undefined.
    """
    n = len(returns_pct)
    enough = n >= MIN_REGIME_OBS

    if n == 0:
        return {
            "num_days": 0,
            "mean_daily_return_pct": None,
            "stdev_daily_return_pct": None,
            "sharpe_annualized": None,
            "annualized_apy_pct": None,
            "total_return_pct": None,
            "best_day_pct": None,
            "worst_day_pct": None,
            "sufficient_sample": False,
        }

    mean_pct = sum(returns_pct) / n
    sd_pct = _pop_stdev(returns_pct)

    sharpe = annualised_sharpe(returns_pct) if enough else None
    apy = annualised_apy_pct(mean_pct / 100.0) if enough else None

    # Total compounded return across this regime's days (always computable).
    total = 1.0
    for r in returns_pct:
        total *= (1.0 + r / 100.0)
    total_return_pct = (total - 1.0) * 100.0

    return {
        "num_days": n,
        "mean_daily_return_pct": _round(mean_pct),
        "stdev_daily_return_pct": _round(sd_pct),
        "sharpe_annualized": _round(sharpe, 4),
        "annualized_apy_pct": _round(apy, 4),
        "total_return_pct": _round(total_return_pct),
        "best_day_pct": _round(max(returns_pct)),
        "worst_day_pct": _round(min(returns_pct)),
        "sufficient_sample": enough,
    }


# ──────────────────────────────────────────────────────────────────────────────
# IO helpers
# ──────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _detect_is_demo(equity_doc: Any) -> Optional[bool]:
    """Honest demo flag from equity_curve_daily.json (else None)."""
    if isinstance(equity_doc, dict) and isinstance(equity_doc.get("is_demo"), bool):
        return equity_doc.get("is_demo")
    return None


def _daily_returns_pct(series: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    """``[(date_t, r_t_pct), ...]`` from a level series; r_t dated to date_t.

    ``r_t = close_t / close_{t-1} − 1`` (expressed in percent). The return is
    attributed to the *later* bar's date (the day on which it was realised).
    """
    out: List[Tuple[str, float]] = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        cur = series[i][1]
        if prev > 0:
            out.append((series[i][0], (cur / prev - 1.0) * 100.0))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def _meta(generated_at: str, is_demo: Optional[bool], notes: List[str]) -> Dict[str, Any]:
    return {
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "is_demo": is_demo,
        "min_regime_obs": MIN_REGIME_OBS,
        "notes": notes,
    }


def _unavailable(
    reason: str,
    generated_at: str,
    notes: List[str],
    is_demo: Optional[bool] = None,
) -> Dict[str, Any]:
    """Stable-schema unavailable result (never raises to caller)."""
    return {
        "available": False,
        "reason": reason,
        "verdict": None,
        "verdict_reason": reason,
        "is_demo": is_demo,
        "num_regimes_observed": 0,
        "dominant_regime": None,
        "worst_regime": None,
        "worst_regime_sharpe": None,
        "regimes": {},
        "overall": None,
        "meta": _meta(generated_at, is_demo, notes),
    }


def build_regime_conditional_performance(
    data_dir: Path = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute per-regime performance of the equity track. NEVER raises."""
    data_dir = Path(data_dir)
    generated_at = datetime.now(timezone.utc).isoformat()
    notes: List[str] = []
    is_demo: Optional[bool] = None

    try:
        # ── Equity track ──────────────────────────────────────────────────────
        equity_doc = _read_json(data_dir / EQUITY_FILENAME)
        if equity_doc is None:
            notes.append(f"{EQUITY_FILENAME} missing or unreadable")
            return _unavailable("insufficient_data", generated_at, notes)
        is_demo = _detect_is_demo(equity_doc)
        series = extract_equity_series(equity_doc)
        if len(series) < 2:
            notes.append("equity series has < 2 valid bars")
            return _unavailable("insufficient_data", generated_at, notes, is_demo)

        dated_returns = _daily_returns_pct(series)
        if len(dated_returns) < MIN_TOTAL_OBS:
            notes.append(
                f"only {len(dated_returns)} daily return(s); need >= {MIN_TOTAL_OBS}"
            )
            return _unavailable("insufficient_data", generated_at, notes, is_demo)

        # ── Regime timeline ───────────────────────────────────────────────────
        apy_records, err = load_apy_history(data_dir)
        if err:
            notes.append(str(err))
        timeline_raw: Any = []
        if apy_records:
            try:
                timeline_raw = regime_history(
                    apy_records, window_days=30, step_days=7
                )
            except Exception as exc:  # pragma: no cover - upstream defensive
                notes.append(f"regime_history error: {exc}")
                timeline_raw = []
        timeline = _clean_regime_timeline(timeline_raw)
        if not timeline:
            notes.append("regime timeline empty — cannot bucket by regime")
            return _unavailable("insufficient_data", generated_at, notes, is_demo)

        # ── Forward-fill + bucket ─────────────────────────────────────────────
        equity_dates = [d for d, _ in dated_returns]
        regime_of_date = forward_fill_regime(equity_dates, timeline)

        buckets: Dict[str, List[float]] = {}
        unknown_days = 0
        for d, r in dated_returns:
            label = regime_of_date.get(d, UNKNOWN_LABEL)
            if label == UNKNOWN_LABEL:
                unknown_days += 1
                continue
            buckets.setdefault(label, []).append(r)

        if unknown_days:
            notes.append(
                f"{unknown_days} day(s) before first regime label → skipped"
            )

        all_bucketed: List[float] = [r for rs in buckets.values() for r in rs]
        if len(all_bucketed) < MIN_TOTAL_OBS:
            notes.append(
                "too few returns mapped to a regime "
                f"({len(all_bucketed)} < {MIN_TOTAL_OBS})"
            )
            return _unavailable("insufficient_data", generated_at, notes, is_demo)

        # ── Per-regime metrics ────────────────────────────────────────────────
        regimes: Dict[str, Any] = {}
        for label in sorted(buckets.keys()):
            regimes[label] = _regime_metrics(buckets[label])

        num_regimes_observed = len(regimes)

        # dominant regime = most days (ties broken by label order for stability)
        dominant_regime = max(
            sorted(regimes.keys()),
            key=lambda lbl: regimes[lbl]["num_days"],
        )

        # worst regime by Sharpe (only among regimes with a defined Sharpe)
        worst_regime: Optional[str] = None
        worst_regime_sharpe: Optional[float] = None
        for lbl in sorted(regimes.keys()):
            sh = regimes[lbl]["sharpe_annualized"]
            if sh is None:
                continue
            if worst_regime_sharpe is None or sh < worst_regime_sharpe:
                worst_regime_sharpe = sh
                worst_regime = lbl

        overall = _regime_metrics(all_bucketed)

        # ── Advisory verdict ──────────────────────────────────────────────────
        verdict, verdict_reason = _decide_verdict(
            regimes, overall, worst_regime, worst_regime_sharpe
        )

        return {
            "available": True,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "is_demo": is_demo,
            "num_regimes_observed": num_regimes_observed,
            "dominant_regime": dominant_regime,
            "worst_regime": worst_regime,
            "worst_regime_sharpe": worst_regime_sharpe,
            "regimes": regimes,
            "overall": overall,
            "track": {
                "first_date": series[0][0],
                "last_date": series[-1][0],
                "num_return_days": len(dated_returns),
                "num_bucketed_days": len(all_bucketed),
                "num_unknown_days": unknown_days,
            },
            "meta": _meta(generated_at, is_demo, notes),
        }

    except Exception as exc:  # last-resort: NEVER raise
        log.exception("unexpected error in build_regime_conditional_performance")
        notes.append(f"unexpected error: {exc}")
        return _unavailable("unexpected_error", generated_at, notes, is_demo)


def _decide_verdict(
    regimes: Dict[str, Any],
    overall: Dict[str, Any],
    worst_regime: Optional[str],
    worst_regime_sharpe: Optional[float],
) -> Tuple[str, str]:
    """Advisory verdict from the per-regime + overall metrics.

    * fail  — BEAR observed (>= MIN_REGIME_OBS) with a defined Sharpe < 0.
    * warn  — BEAR days exist but Sharpe is None (low sample), OR any observed
              regime has a negative Sharpe, OR overall Sharpe < 0.
    * ok    — otherwise.
    """
    bear = regimes.get("BEAR")
    overall_sharpe = overall.get("sharpe_annualized") if overall else None

    # ── fail: strategy loses in bear markets ──────────────────────────────────
    if (
        bear is not None
        and bear.get("num_days", 0) >= MIN_REGIME_OBS
        and bear.get("sharpe_annualized") is not None
        and bear["sharpe_annualized"] < 0
    ):
        return (
            "fail",
            f"BEAR-regime Sharpe is negative "
            f"({bear['sharpe_annualized']:.4f} over {bear['num_days']} day(s)) — "
            f"strategy loses money in bear markets",
        )

    # ── warn conditions ───────────────────────────────────────────────────────
    if (
        bear is not None
        and bear.get("num_days", 0) > 0
        and bear.get("sharpe_annualized") is None
    ):
        return (
            "warn",
            f"BEAR regime observed ({bear['num_days']} day(s)) but Sharpe is "
            f"undefined (low sample / zero variance) — bear behaviour unproven",
        )

    neg_regimes = sorted(
        lbl
        for lbl, m in regimes.items()
        if m.get("sharpe_annualized") is not None and m["sharpe_annualized"] < 0
    )
    if neg_regimes:
        worst_txt = (
            f"{worst_regime} ({worst_regime_sharpe:.4f})"
            if worst_regime is not None and worst_regime_sharpe is not None
            else ", ".join(neg_regimes)
        )
        return (
            "warn",
            f"negative Sharpe in regime(s): {', '.join(neg_regimes)}; "
            f"worst = {worst_txt}",
        )

    if overall_sharpe is not None and overall_sharpe < 0:
        return (
            "warn",
            f"pooled overall Sharpe is negative ({overall_sharpe:.4f}) "
            f"across all regimes",
        )

    return (
        "ok",
        f"no negative-Sharpe regime across {len(regimes)} observed; "
        f"strategy holds up across regimes",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Atomic persistence (content_fingerprint reused by import — see top of module)
# ──────────────────────────────────────────────────────────────────────────────

def _history_entry(result: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record."""
    meta = result.get("meta") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "available": result.get("available"),
        "verdict": result.get("verdict"),
        "dominant_regime": result.get("dominant_regime"),
        "worst_regime": result.get("worst_regime"),
        "worst_regime_sharpe": result.get("worst_regime_sharpe"),
    }


def write_status(
    result: Dict[str, Any],
    data_dir: Path = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write regime_conditional_performance.json.

    Returns ``"DATA_WRITTEN"`` or ``"DATA_UNCHANGED"`` (idempotent). Idempotency
    is keyed on :func:`content_fingerprint` (strips volatile
    ``meta.generated_at`` / ``history``); an unchanged fingerprint means the
    file is NOT rewritten. On change a short record rotates into ``history``
    (length capped at exactly :data:`HISTORY_MAX`). A broken/absent existing
    file is tolerated as fresh.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / STATUS_FILENAME

    new_fp = content_fingerprint(result)

    prev = _read_json(out_path)
    if isinstance(prev, dict):
        prev_no_hist = {k: v for k, v in prev.items() if k != "history"}
        if content_fingerprint(prev_no_hist) == new_fp:
            return "DATA_UNCHANGED"

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(result))
    history = history[-HISTORY_MAX:]

    doc = dict(result)
    doc["history"] = history

    atomic_save(doc, str(out_path))
    return "DATA_WRITTEN"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[regime_conditional_performance] available=false "
            f"reason={result.get('reason', '?')}"
        )
        for n in (result.get("meta") or {}).get("notes", []):
            print(f"  note: {n}")
        return

    print("[regime_conditional_performance] available=true")
    print(f"  verdict        : {result['verdict']} — {result['verdict_reason']}")
    print(f"  regimes observed: {result['num_regimes_observed']}")
    print(f"  dominant regime : {result['dominant_regime']}")
    if result.get("worst_regime") is not None:
        print(
            f"  worst regime    : {result['worst_regime']} "
            f"sharpe={result['worst_regime_sharpe']}"
        )
    for lbl in sorted(result.get("regimes", {})):
        m = result["regimes"][lbl]
        print(
            f"    {lbl:<9} days={m['num_days']:<3} "
            f"sharpe={m['sharpe_annualized']} apy%={m['annualized_apy_pct']}"
        )
    if result.get("is_demo") is not None:
        print(f"  is_demo         : {result['is_demo']}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.regime_conditional_performance",
        description=(
            "Regime-Conditional Performance Analyzer (SPA-V450 / MP-131): "
            "read-only / advisory per-regime Sharpe & APY of the equity track. "
            "Offline."
        ),
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write the status file",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        return 0

    if args.check and args.run:
        print(
            "ERROR: --check and --run are mutually exclusive",
            file=sys.stderr,
        )
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    try:
        result = build_regime_conditional_performance(data_dir)
        _print_result(result)
        if args.run:
            status = write_status(result, data_dir)
            print(f"[regime_conditional_performance] write_status={status}")
    except Exception as exc:  # advisory: no tracebacks, exit 0 always
        print(
            f"regime_conditional_performance: ERROR — "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())

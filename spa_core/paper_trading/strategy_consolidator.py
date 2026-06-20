#!/usr/bin/env python3
"""Strategy S0-S5 Shadow Track Consolidator (SPA-V435 / MP-135) — read-only / advisory.

Reads shadow strategy performance data (S0 through S5) and produces a
consolidated ranking with an advisory verdict on which strategy to run next
cycle. This module answers the portfolio-operations question *"is the current
live strategy (S0) still the best performer, or should we rotate to a better-
performing shadow strategy?"*

Data sources (priority order)
==============================
1. ``data/shadow_strategies/*.json`` — one JSON file per strategy (S0..S5),
   each a list of records ``{date, strategy_id, equity, apy}``.
2. Fallback: ``data/portfolio_snapshots.json`` — flat list of snapshot records.
   Records tagged with a ``strategy_id`` field are grouped by it; records
   without one are assigned to "S0" (current live strategy).

Metrics computed per strategy
==============================
* ``total_return_pct``      — (equity_last / equity_first − 1) × 100
* ``annualized_return_pct`` — geometrically annualised to 365-day year
* ``sharpe``                — annualised Sharpe: mean(r_i) / std(r_i) × √252
  where ``r_i = equity_i / equity_{i-1} − 1`` (decimal daily return),
  std is sample std (n−1 denominator). Zero if std = 0.
* ``max_drawdown_pct``      — deepest peak-to-trough drawdown (≤ 0)
* ``turnover_proxy``        — sample std of daily returns (same units as
  Sharpe numerator, i.e. decimal); proxy for rebalancing activity
* ``n_days``                — calendar days from first to last equity point

Ranking (composite score)
==========================
  score = 0.5 × sharpe_norm
        + 0.3 × annualised_return_norm
        + 0.2 × (1 − max_dd_abs_norm)

where ``_norm = (value − min) / (max − min + ε)``.  For drawdown the
*absolute* value of ``max_drawdown_pct`` is normalised so that a larger
drawdown magnitude → higher norm → lower score contribution.

Advisory verdict
================
* **MAINTAIN**           — S0 is in top-3 of the ranking
* **ROTATE_RECOMMENDED** — S0 is outside top-3

Output / persistence
====================
:func:`run_consolidator` atomically (tmp + ``os.replace``) writes
``data/strategy_consolidator.json``. An in-file ``history`` ring-buffer
(≤ :data:`HISTORY_MAX`) records short run summaries. Idempotency:
:func:`content_fingerprint` over the doc (excluding ``meta.generated_at``
and ``history``) prevents redundant rewrites on unchanged inputs.

CLI::

    python3 -m spa_core.paper_trading.strategy_consolidator --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.strategy_consolidator --run     # + atomic write
    python3 -m spa_core.paper_trading.strategy_consolidator --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib) — no
requests/web3/LLM SDK/sockets/network. It only reads shadow strategy files
and writes its OWN status artifact; it never moves capital and never touches
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

log = logging.getLogger("spa.paper_trading.strategy_consolidator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "strategy_consolidator"
STATUS_FILENAME: str = "strategy_consolidator.json"
SHADOW_DIR_NAME: str = "shadow_strategies"
SNAPSHOTS_FILENAME: str = "portfolio_snapshots.json"
HISTORY_MAX: int = 500
DISCLAIMER: str = "NOT investment advice"
REAL_TRACK_START: str = "2026-06-10"

# Composite score weights (must sum to 1.0)
WEIGHT_SHARPE: float = 0.5
WEIGHT_RETURN: float = 0.3
WEIGHT_DRAWDOWN: float = 0.2
NORM_EPSILON: float = 1e-9   # prevent division by zero in normalisation

# Annualisation constants
TRADING_DAYS_PER_YEAR: float = 252.0
CALENDAR_DAYS_PER_YEAR: float = 365.0

# S0 is the "current" live strategy identifier
CURRENT_STRATEGY_ID: str = "S0"


# ─── Tolerant I/O helpers ─────────────────────────────────────────────────────


def _read_json(path: "str | Path") -> Any:
    """Read a JSON file tolerantly: missing or broken → None, never raises."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: "str | Path", obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _num(value: Any) -> Optional[float]:
    """Return a finite float or None. bool is rejected; NaN/inf → None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v):
        return None
    return v


def _valid_date(value: Any) -> bool:
    """True iff *value* is an ISO YYYY-MM-DD (or longer) string."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def _days_between(start: Any, end: Any) -> Optional[int]:
    """Calendar days (end − start) between two ISO date strings, or None."""
    if not _valid_date(start) or not _valid_date(end):
        return None
    try:
        d0 = date.fromisoformat(str(start)[:10])
        d1 = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (d1 - d0).days


# ─── Load strategy tracks ─────────────────────────────────────────────────────


def load_strategy_tracks(data_dir: str = "data") -> Dict[str, List[Dict[str, Any]]]:
    """Load per-strategy equity tracks from disk.

    Priority:
    1. ``{data_dir}/shadow_strategies/*.json`` — one file per strategy.
       Each file is a list of records with at minimum ``strategy_id`` and
       ``equity`` (and ideally ``date`` and ``apy``).
    2. Fallback: ``{data_dir}/portfolio_snapshots.json`` — flat list.
       Records are grouped by their ``strategy_id`` field when present;
       records without ``strategy_id`` are assigned to ``"S0"``.

    Returns:
        ``{strategy_id: [records...]}`` — possibly empty if no data found.
        Never raises.
    """
    ddir = Path(data_dir)
    shadow_dir = ddir / SHADOW_DIR_NAME

    if shadow_dir.exists() and shadow_dir.is_dir():
        result: Dict[str, List[Dict[str, Any]]] = {}
        try:
            json_files = sorted(shadow_dir.glob("*.json"))
        except Exception:
            json_files = []
        for fp in json_files:
            try:
                raw = _read_json(fp)
                if not isinstance(raw, list):
                    continue
                for rec in raw:
                    if not isinstance(rec, dict):
                        continue
                    sid = rec.get("strategy_id")
                    if not isinstance(sid, str) or not sid:
                        continue
                    result.setdefault(sid, []).append(rec)
            except Exception:
                continue
        return result

    # Fallback: portfolio_snapshots.json
    snapshots = _read_json(ddir / SNAPSHOTS_FILENAME)
    if not isinstance(snapshots, list):
        return {}

    result = {}
    for rec in snapshots:
        if not isinstance(rec, dict):
            continue
        sid = rec.get("strategy_id")
        if not isinstance(sid, str) or not sid:
            sid = CURRENT_STRATEGY_ID
        result.setdefault(sid, []).append(rec)
    return result


# ─── Metrics computation ──────────────────────────────────────────────────────


def compute_strategy_metrics(equity_points: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute per-strategy performance metrics from a list of equity points.

    Each point is a dict with at least ``equity`` (or ``close_equity``) and
    optionally ``date``. Points are sorted by ``date`` before computation.

    Returns a dict with keys:
        ``total_return_pct``, ``annualized_return_pct``, ``sharpe``,
        ``max_drawdown_pct``, ``turnover_proxy``, ``n_days``.

    Safe defaults (all zeros) are returned for edge cases:
    * fewer than 2 valid equity points
    * zero or negative equity values
    * zero variance in daily returns (sharpe/turnover_proxy = 0)

    Formulas:
    * ``r_i = equity_i / equity_{i-1} - 1``  (decimal daily return)
    * ``sharpe = mean(r_i) / std_sample(r_i) * sqrt(252)``
    * ``total_return_pct = (equity_last / equity_first - 1) * 100``
    * ``annualized_return_pct`` uses geometric annualisation over n_days
    * ``max_drawdown_pct`` = deepest peak-to-trough ratio (≤ 0, as %)
    * ``turnover_proxy`` = sample std of daily returns (decimal)
    """
    _SAFE = {
        "total_return_pct": 0.0,
        "annualized_return_pct": 0.0,
        "sharpe": 0.0,
        "max_drawdown_pct": 0.0,
        "turnover_proxy": 0.0,
        "n_days": 0,
    }

    if not equity_points:
        return dict(_SAFE)

    # Sort by date (records without a valid date sort to the front lexicographically)
    def _sort_key(rec: Dict[str, Any]) -> str:
        d = rec.get("date", "")
        return str(d) if _valid_date(d) else ""

    sorted_pts = sorted(equity_points, key=_sort_key)

    # Extract valid (positive) equity values paired with dates
    valid: List[Tuple[str, float]] = []
    for rec in sorted_pts:
        eq = _num(rec.get("equity"))
        if eq is None:
            eq = _num(rec.get("close_equity"))
        if eq is None or eq <= 0:
            continue
        d = rec.get("date", "")
        valid.append((str(d), eq))

    if len(valid) < 2:
        return dict(_SAFE)

    dates = [v[0] for v in valid]
    equities = [v[1] for v in valid]

    # Calendar days from first to last valid bar
    n_days_val = _days_between(dates[0], dates[-1])
    n_days: int = n_days_val if (n_days_val is not None and n_days_val >= 0) else (len(valid) - 1)

    # Total return
    first_eq, last_eq = equities[0], equities[-1]
    total_return_pct = (last_eq / first_eq - 1.0) * 100.0

    # Annualised return (geometric)
    if n_days > 0:
        try:
            annualized_return_pct = (
                (1.0 + total_return_pct / 100.0) ** (CALENDAR_DAYS_PER_YEAR / n_days) - 1.0
            ) * 100.0
            if not math.isfinite(annualized_return_pct):
                annualized_return_pct = 0.0
        except (ZeroDivisionError, OverflowError, ValueError):
            annualized_return_pct = 0.0
    else:
        # Intraday / same-day: total return is the best we can report
        annualized_return_pct = total_return_pct

    # Daily returns (decimal)
    daily_returns: List[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        cur = equities[i]
        if prev > 0:
            daily_returns.append(cur / prev - 1.0)

    n_r = len(daily_returns)

    # Sharpe (annualised) and turnover_proxy (sample std of daily returns)
    if n_r >= 2:
        mean_r = sum(daily_returns) / n_r
        var_r = sum((r - mean_r) ** 2 for r in daily_returns) / (n_r - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 0.0
        sharpe = (mean_r / std_r) * math.sqrt(TRADING_DAYS_PER_YEAR) if std_r > 0 else 0.0
        turnover_proxy = std_r
    else:
        sharpe = 0.0
        turnover_proxy = 0.0

    # Max drawdown (≤ 0, expressed as %)
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (eq / peak - 1.0) * 100.0 if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd

    return {
        "total_return_pct": _round(total_return_pct) or 0.0,
        "annualized_return_pct": _round(annualized_return_pct) or 0.0,
        "sharpe": _round(sharpe) or 0.0,
        "max_drawdown_pct": _round(max_dd) or 0.0,
        "turnover_proxy": _round(turnover_proxy, 8) or 0.0,
        "n_days": n_days,
    }


# ─── Ranking ──────────────────────────────────────────────────────────────────


def rank_strategies(
    strategy_metrics: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Rank strategies by composite score and return a sorted list.

    Composite score:
        score = WEIGHT_SHARPE × sharpe_norm
              + WEIGHT_RETURN × annualized_return_norm
              + WEIGHT_DRAWDOWN × (1 − max_dd_abs_norm)

    where:
        ``_norm = (value − min) / (max − min + ε)``

    For the drawdown component the *absolute value* of ``max_drawdown_pct``
    is normalised (larger magnitude = worse = lower score contribution).

    When all strategies share the same value for a metric their normalised
    value is 0 (the denominator is ε ≈ 0, numerator is 0), giving equal
    weight to each: score reduces to the equally-weighted default.

    Returns:
        List of dicts sorted by ``rank`` (1 = best), each containing:
        ``{strategy_id, score, rank, metrics, is_current}``.
        ``is_current`` is True for the strategy whose id is ``CURRENT_STRATEGY_ID``.
        Returns ``[]`` for an empty input.
    """
    if not strategy_metrics:
        return []

    sids = list(strategy_metrics.keys())

    def _get(sid: str, key: str) -> float:
        v = strategy_metrics[sid].get(key, 0.0)
        return float(v) if isinstance(v, (int, float)) and math.isfinite(float(v)) else 0.0

    # Gather raw values for normalisation
    sharpe_vals = [_get(s, "sharpe") for s in sids]
    ret_vals = [_get(s, "annualized_return_pct") for s in sids]
    dd_abs_vals = [abs(_get(s, "max_drawdown_pct")) for s in sids]

    def _norm_list(vals: List[float]) -> List[float]:
        lo, hi = min(vals), max(vals)
        denom = hi - lo + NORM_EPSILON
        return [(v - lo) / denom for v in vals]

    sharpe_norm = _norm_list(sharpe_vals)
    ret_norm = _norm_list(ret_vals)
    dd_abs_norm = _norm_list(dd_abs_vals)

    entries: List[Dict[str, Any]] = []
    for i, sid in enumerate(sids):
        score = (
            WEIGHT_SHARPE * sharpe_norm[i]
            + WEIGHT_RETURN * ret_norm[i]
            + WEIGHT_DRAWDOWN * (1.0 - dd_abs_norm[i])
        )
        entries.append(
            {
                "strategy_id": sid,
                "score": round(score, 8),
                "rank": 0,           # filled in below
                "metrics": strategy_metrics[sid],
                "is_current": sid == CURRENT_STRATEGY_ID,
            }
        )

    # Sort by score descending; tie-break by strategy_id for determinism
    entries.sort(key=lambda e: (-e["score"], e["strategy_id"]))
    for rank_idx, entry in enumerate(entries, start=1):
        entry["rank"] = rank_idx

    return entries


# ─── Advisory ────────────────────────────────────────────────────────────────


def generate_advisory(ranked: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate an advisory verdict from the ranked strategy list.

    Verdict rules:
    * **MAINTAIN**           — ``S0`` is within the top-3 ranked strategies
    * **ROTATE_RECOMMENDED** — ``S0`` is ranked 4th or lower (or absent)

    Returns:
        ``{recommended_strategy, current_rank, verdict, explanation, top3}``
    """
    if not ranked:
        return {
            "recommended_strategy": CURRENT_STRATEGY_ID,
            "current_rank": None,
            "verdict": "MAINTAIN",
            "explanation": (
                "No strategy tracks available — defaulting to current strategy S0."
            ),
            "top3": [],
        }

    top3 = [e["strategy_id"] for e in ranked[:3]]
    best = ranked[0]
    recommended = best["strategy_id"]

    # Find current strategy (S0) rank
    current_rank: Optional[int] = None
    for entry in ranked:
        if entry["strategy_id"] == CURRENT_STRATEGY_ID:
            current_rank = entry["rank"]
            break

    in_top3 = CURRENT_STRATEGY_ID in top3

    if in_top3:
        verdict = "MAINTAIN"
        explanation = (
            f"Strategy {CURRENT_STRATEGY_ID} is ranked #{current_rank} "
            f"(within top-3). No rotation required. "
            f"Top-3: {top3}."
        )
    else:
        verdict = "ROTATE_RECOMMENDED"
        cr_str = f"#{current_rank}" if current_rank is not None else "outside tracked set"
        explanation = (
            f"Strategy {CURRENT_STRATEGY_ID} is ranked {cr_str}, "
            f"outside the top-3. Consider rotating to {recommended} "
            f"(rank #1, score={best['score']:.4f}). "
            f"Top-3: {top3}."
        )

    return {
        "recommended_strategy": recommended,
        "current_rank": current_rank,
        "verdict": verdict,
        "explanation": explanation,
        "top3": top3,
    }


# ─── Idempotency fingerprint ──────────────────────────────────────────────────


def content_fingerprint(doc: Any) -> str:
    """Canonical fingerprint of doc content, excluding volatile fields.

    Excludes ``history`` and ``meta.generated_at`` so that repeated ``--run``
    calls on unchanged inputs produce no rewrite. Non-dict input → a unique
    string that never matches a valid document.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record appended to the output file."""
    meta = doc.get("meta") or {}
    advisory = doc.get("advisory") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "n_strategies": len(doc.get("ranking", [])),
        "verdict": advisory.get("verdict"),
        "recommended_strategy": advisory.get("recommended_strategy"),
        "current_rank": advisory.get("current_rank"),
    }


# ─── Full pipeline ────────────────────────────────────────────────────────────


def run_consolidator(data_dir: str = "data") -> Dict[str, Any]:
    """Full consolidator pipeline: load → compute → rank → advisory → write.

    Atomically writes ``{data_dir}/strategy_consolidator.json`` and returns
    the result dict. Never raises; on error the result contains an
    ``error`` key with the exception message.

    Args:
        data_dir: directory containing strategy data and output artifact.

    Returns:
        Full result dict (also written to disk).
    """
    ddir = Path(data_dir)
    now = datetime.now(timezone.utc)
    notes: List[str] = []

    meta: Dict[str, Any] = {
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "real_track_start": REAL_TRACK_START,
        "data_dir": str(ddir),
    }

    try:
        # 1. Load tracks
        tracks = load_strategy_tracks(str(ddir))
        if not tracks:
            notes.append("No strategy track data found — no shadow_strategies/ directory and no portfolio_snapshots.json.")

        # 2. Compute metrics per strategy
        all_metrics: Dict[str, Dict[str, Any]] = {}
        for sid, points in tracks.items():
            all_metrics[sid] = compute_strategy_metrics(points)

        # 3. Rank
        ranked = rank_strategies(all_metrics)

        # 4. Advisory
        advisory = generate_advisory(ranked)

        meta["notes"] = notes
        doc: Dict[str, Any] = {
            "meta": meta,
            "available": bool(tracks),
            "n_strategies": len(tracks),
            "strategies": all_metrics,
            "ranking": ranked,
            "advisory": advisory,
        }

    except Exception as exc:
        log.exception("strategy_consolidator: unexpected error")
        meta["notes"] = notes + [f"ERROR: {type(exc).__name__}: {exc}"]
        doc = {
            "meta": meta,
            "available": False,
            "n_strategies": 0,
            "strategies": {},
            "ranking": [],
            "advisory": generate_advisory([]),
            "error": f"{type(exc).__name__}: {exc}",
        }

    # 5. Atomic write with idempotency check and history ring-buffer
    path = ddir / STATUS_FILENAME
    try:
        prev = _read_json(path)
        if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
            # Unchanged — restore history from previous file, no rewrite
            doc["history"] = prev.get("history", [])
            log.info("strategy_consolidator unchanged: %s", path)
        else:
            history: List[Dict[str, Any]] = []
            if isinstance(prev, dict) and isinstance(prev.get("history"), list):
                history = [h for h in prev["history"] if isinstance(h, dict)]
            history.append(_history_entry(doc))
            doc["history"] = history[-HISTORY_MAX:]
            _atomic_write_json(path, doc)
            log.info("strategy_consolidator written: %s", path)
    except Exception as exc:
        log.warning("strategy_consolidator: write failed: %s", exc)
        doc.setdefault("write_error", str(exc))

    return doc


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.strategy_consolidator",
        description=(
            "Strategy S0-S5 Shadow Track Consolidator (SPA-V435 / MP-135): "
            "read-only / advisory ranking of shadow strategies with rotation verdict. "
            "Offline."
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
        help="compute and atomically write data/strategy_consolidator.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:  # noqa: D401
    """CLI entry point. Always exits 0 (advisory module — no tracebacks)."""
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

    data_dir = args.data_dir or str(_DEFAULT_DATA_DIR)

    try:
        if args.run:
            doc = run_consolidator(data_dir=data_dir)
            adv = doc.get("advisory") or {}
            print(
                f"strategy_consolidator: "
                f"strategies={doc.get('n_strategies', 0)} "
                f"verdict={adv.get('verdict', 'N/A')} "
                f"recommended={adv.get('recommended_strategy', 'N/A')} "
                f"current_rank={adv.get('current_rank', 'N/A')} "
                f"— written {data_dir}/{STATUS_FILENAME}"
            )
        else:
            # --check (or bare invocation): compute and print without writing
            tracks = load_strategy_tracks(data_dir)
            all_metrics: Dict[str, Dict[str, Any]] = {
                sid: compute_strategy_metrics(pts) for sid, pts in tracks.items()
            }
            ranked = rank_strategies(all_metrics)
            advisory = generate_advisory(ranked)
            now = datetime.now(timezone.utc)
            doc = {
                "meta": {
                    "source": SOURCE_NAME,
                    "schema_version": SCHEMA_VERSION,
                    "generated_at": now.isoformat(),
                    "advisory_only": True,
                    "disclaimer": DISCLAIMER,
                },
                "available": bool(tracks),
                "n_strategies": len(tracks),
                "strategies": all_metrics,
                "ranking": ranked,
                "advisory": advisory,
            }
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"strategy_consolidator: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Analytics Confidence Progress Tracker (SPA / MP-141) — read-only / advisory.

Tracks how many real paper-trading days have accumulated and reports which
statistical confidence milestones have been reached (or when they will be).

Each analytics module requires a different minimum number of real days before
its output becomes statistically meaningful:

  =========================================  ========
  Module / milestone                         Min days
  =========================================  ========
  backtest_vs_paper (Spearman readable)            7
  honest_metrics LOW_CONFIDENCE                    7
  structural_break sufficient data                12
  honest_metrics MODERATE_CONFIDENCE              30
  honest_metrics HIGH_CONFIDENCE                  90
  =========================================  ========

Functions
---------
build_progress_report(data_dir=None) -> dict
    Read paper-trading state files, return a structured progress dict.
run_progress_tracker(data_dir=None, output_path=None) -> dict
    build_progress_report + atomic write to data/progress_tracker.json.

Constraints
-----------
- Pure stdlib: json, datetime, math, pathlib, os, tempfile, sys, argparse
- NO numpy, pandas, scipy, requests, anthropic — zero external imports
- Atomic writes: tmp + os.replace — no direct open(..., "w") on state files
- STRICTLY READ-ONLY: never touches risk / execution / allocator / cycle_runner
- LLM FORBIDDEN in this module (SPA security policy)

CLI::

    python3 -m spa_core.paper_trading.progress_tracker --check    # print only (default)
    python3 -m spa_core.paper_trading.progress_tracker --run      # + atomic write
    python3 -m spa_core.paper_trading.progress_tracker --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "progress_tracker.json"
GO_LIVE_TARGET_DATE = "2026-07-15"

# Milestone definitions: (id, label, module, required_days)
_MILESTONE_DEFS: List[tuple] = [
    (
        "backtest_contour_min",
        "Backtest vs Paper: readable (Spearman ≥7d)",
        "backtest_vs_paper",
        7,
    ),
    (
        "honest_metrics_low",
        "Honest Metrics: LOW_CONFIDENCE (≥7d)",
        "honest_metrics",
        7,
    ),
    (
        "structural_break_min",
        "Structural Break: sufficient data (≥12d)",
        "structural_break",
        12,
    ),
    (
        "honest_metrics_moderate",
        "Honest Metrics: MODERATE_CONFIDENCE (≥30d)",
        "honest_metrics",
        30,
    ),
    (
        "honest_metrics_high",
        "Honest Metrics: HIGH_CONFIDENCE (≥90d)",
        "honest_metrics",
        90,
    ),
]


# ---------------------------------------------------------------------------
# IO helpers (stdlib only)
# ---------------------------------------------------------------------------


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing / corrupt file → ``default`` (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically: tmpfile in the same dir + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today_str() -> str:
    """UTC today as YYYY-MM-DD string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_between(start: str, end: str) -> int:
    """Calendar days between two YYYY-MM-DD strings (end - start, can be negative)."""
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
        return (d1 - d0).days
    except (ValueError, TypeError):
        return 0


def _add_days(base: str, n: int) -> str:
    """Add n days to a YYYY-MM-DD string, return YYYY-MM-DD."""
    try:
        d = date.fromisoformat(base) + timedelta(days=n)
        return d.isoformat()
    except (ValueError, TypeError):
        return base


def _extract_paper_start(equity_doc: Any) -> Optional[str]:
    """Extract the earliest date from equity_curve_daily.json."""
    if not isinstance(equity_doc, dict):
        return None
    daily = equity_doc.get("daily")
    if not isinstance(daily, list) or not daily:
        return None
    first = daily[0]
    if isinstance(first, dict):
        return first.get("date") or None
    return None


def _extract_current_equity(equity_doc: Any, status_doc: Any) -> float:
    """Best-effort current equity from equity curve or status.

    Equity curve (source=cycle_runner) is preferred over status when available.
    """
    # Prefer the real equity curve's last close
    if isinstance(equity_doc, dict) and equity_doc.get("source") == "cycle_runner":
        daily = equity_doc.get("daily")
        if isinstance(daily, list) and daily:
            last = daily[-1]
            if isinstance(last, dict):
                close = last.get("close_equity") or last.get("equity")
                if isinstance(close, (int, float)) and close > 0:
                    return float(close)
    # Fallback: paper_trading_status.json
    if isinstance(status_doc, dict):
        eq = status_doc.get("current_equity")
        if isinstance(eq, (int, float)) and eq > 0:
            return float(eq)
    return 100_000.0


def _extract_apy_today(equity_doc: Any, status_doc: Any) -> float:
    """Best-effort today's APY from equity curve or status."""
    if isinstance(status_doc, dict):
        apy = status_doc.get("apy_today_pct")
        if isinstance(apy, (int, float)):
            return float(apy)
    if isinstance(equity_doc, dict):
        daily = equity_doc.get("daily")
        if isinstance(daily, list) and daily:
            last = daily[-1]
            if isinstance(last, dict):
                apy = last.get("apy_today") or last.get("apy_today_pct")
                if isinstance(apy, (int, float)):
                    return float(apy)
    return 0.0


def _count_real_paper_days(equity_doc: Any) -> int:
    """Count real (non-demo) daily bars in the equity curve."""
    if not isinstance(equity_doc, dict):
        return 0
    if equity_doc.get("source") != "cycle_runner":
        return 0
    daily = equity_doc.get("daily")
    if not isinstance(daily, list):
        return 0
    return len(daily)


def _build_milestone(
    m_id: str,
    label: str,
    module: str,
    required_days: int,
    current_days: int,
    today: str,
) -> Dict[str, Any]:
    """Build a single milestone dict."""
    reached = current_days >= required_days
    days_remaining = max(0, required_days - current_days)
    eta_date = _add_days(today, days_remaining) if not reached else today

    return {
        "id": m_id,
        "label": label,
        "module": module,
        "required_days": required_days,
        "current_days": current_days,
        "days_remaining": days_remaining,
        "eta_date": eta_date,
        "reached": reached,
    }


def _compute_summary_verdict(
    days_to_golive: int,
    milestones: List[Dict[str, Any]],
) -> str:
    """
    "ahead"    — honest_metrics_moderate already reached
    "at_risk"  — days_to_golive < 14
    "on_track" — otherwise
    """
    moderate_reached = any(
        m["id"] == "honest_metrics_moderate" and m["reached"]
        for m in milestones
    )
    if moderate_reached:
        return "ahead"
    if days_to_golive < 14:
        return "at_risk"
    return "on_track"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_progress_report(data_dir: "str | os.PathLike | None" = None) -> dict:
    """Read paper-trading state files and return a structured progress report.

    Never raises: any error results in ``available=False`` + ``reason`` field.

    Parameters
    ----------
    data_dir : path-like, optional
        Directory containing data/*.json files. Defaults to <repo>/data.

    Returns
    -------
    dict with keys:
        paper_days, paper_start_date, current_equity, apy_today_pct,
        go_live_target_date, days_to_golive, milestones, summary_verdict,
        available, generated_at
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        today = _today_str()

        # Read source files (all fail-safe)
        equity_doc = _read_json(ddir / "equity_curve_daily.json", {})
        status_doc = _read_json(ddir / "paper_trading_status.json", {})

        # Derive core counters
        paper_days = _count_real_paper_days(equity_doc)
        paper_start_date = _extract_paper_start(equity_doc)
        current_equity = _extract_current_equity(equity_doc, status_doc)
        apy_today_pct = _extract_apy_today(equity_doc, status_doc)

        # Go-live countdown
        days_to_golive = _days_between(today, GO_LIVE_TARGET_DATE)

        # Build milestones
        milestones: List[Dict[str, Any]] = [
            _build_milestone(m_id, label, module, required_days, paper_days, today)
            for m_id, label, module, required_days in _MILESTONE_DEFS
        ]

        summary_verdict = _compute_summary_verdict(days_to_golive, milestones)

        return {
            "paper_days": paper_days,
            "paper_start_date": paper_start_date,
            "current_equity": round(current_equity, 2),
            "apy_today_pct": round(apy_today_pct, 4),
            "go_live_target_date": GO_LIVE_TARGET_DATE,
            "days_to_golive": days_to_golive,
            "milestones": milestones,
            "summary_verdict": summary_verdict,
            "available": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:  # noqa: BLE001 — must never raise
        return {
            "paper_days": 0,
            "paper_start_date": None,
            "current_equity": 0.0,
            "apy_today_pct": 0.0,
            "go_live_target_date": GO_LIVE_TARGET_DATE,
            "days_to_golive": 0,
            "milestones": [],
            "summary_verdict": "at_risk",
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def run_progress_tracker(
    data_dir: "str | os.PathLike | None" = None,
    output_path: "str | os.PathLike | None" = None,
) -> dict:
    """Build the progress report and atomically write to data/progress_tracker.json.

    Parameters
    ----------
    data_dir : path-like, optional
        Directory for data/*.json files.
    output_path : path-like, optional
        Explicit output path override. Defaults to data_dir/progress_tracker.json.

    Returns
    -------
    dict — same as build_progress_report().
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    result = build_progress_report(data_dir=ddir)

    out_path = Path(output_path) if output_path is not None else ddir / OUTPUT_FILENAME
    try:
        _atomic_write_json(out_path, result)
    except Exception as exc:  # noqa: BLE001
        # Write failure is non-fatal; caller gets the result dict anyway
        result["write_error"] = f"{type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_report(report: dict) -> None:
    """Pretty-print the progress report to stdout."""
    print("─" * 64)
    print(f"SPA Analytics Confidence Progress Tracker  (MP-141)")
    print("─" * 64)
    print(f"  available         : {report.get('available')}")
    print(f"  paper_days        : {report.get('paper_days')}")
    print(f"  paper_start_date  : {report.get('paper_start_date')}")
    print(f"  current_equity    : ${report.get('current_equity', 0):,.2f}")
    print(f"  apy_today_pct     : {report.get('apy_today_pct', 0):.4f}%")
    print(f"  go_live_target    : {report.get('go_live_target_date')}")
    print(f"  days_to_golive    : {report.get('days_to_golive')}")
    print(f"  summary_verdict   : {report.get('summary_verdict')}")
    print()
    print("  Milestones:")
    for m in report.get("milestones", []):
        status = "✓ REACHED" if m["reached"] else f"→ ETA {m['eta_date']} ({m['days_remaining']}d)"
        print(f"    [{m['id']}]  {status}")
        print(f"       {m['label']}")
        print(f"       {m['current_days']}/{m['required_days']} days")
    if "reason" in report:
        print(f"\n  ⚠ reason: {report['reason']}")
    print("─" * 64)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="progress_tracker",
        description="Analytics Confidence Progress Tracker (MP-141).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compute and print; do NOT write (default when no flag given)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="compute, print, and write data/progress_tracker.json",
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    if args.run:
        report = run_progress_tracker(data_dir=args.data_dir)
    else:
        # --check or bare invocation: compute only, no write
        report = build_progress_report(data_dir=args.data_dir)

    _print_report(report)
    return 0  # exit 0 always (advisory module)


if __name__ == "__main__":
    raise SystemExit(main())

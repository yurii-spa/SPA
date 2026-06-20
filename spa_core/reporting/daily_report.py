#!/usr/bin/env python3
"""MP-102: automated daily report.

Aggregates one day of the real paper-trading track into a single JSON
snapshot (``data/daily_report_{date}.json``) that downstream consumers —
the investor view (MP-110), Telegram/email notifiers — can read without
re-deriving anything.

Sources (all read-only, all optional — a missing/corrupt file degrades the
corresponding fields to ``None``/empty, never raises):

* ``data/equity_curve_daily.json``      — equity bar for the report date
* ``data/paper_trading_status.json``    — positions / days running fallback
* ``data/golive_status.json``           — READY / PRE-LIVE verdict
* ``data/risk_scores.json``             — adapter_id → grade (if present)

Stdlib only; the output file is written atomically (tmpfile + os.replace).

CLI::

    python3 -m spa_core.reporting.daily_report            # report for yesterday
    python3 -m spa_core.reporting.daily_report 2026-06-10 # explicit date
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.daily_report")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

EQUITY_FILENAME = "equity_curve_daily.json"
STATUS_FILENAME = "paper_trading_status.json"
GOLIVE_FILENAME = "golive_status.json"
RISK_SCORES_FILENAME = "risk_scores.json"
REPORT_FILENAME_TPL = "daily_report_{date}.json"


# ─── IO helpers (stdlib only, mirrors cycle_runner conventions) ──────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → ``default`` (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


# ─── Pure helpers ────────────────────────────────────────────────────────────


def _find_equity_bar(equity_doc: Any, date_str: str) -> dict | None:
    """The daily bar matching ``date_str``, or ``None`` if absent."""
    if not isinstance(equity_doc, dict):
        return None
    for bar in equity_doc.get("daily") or []:
        if isinstance(bar, dict) and bar.get("date") == date_str:
            return bar
    return None


def _top_protocol(positions: dict[str, Any]) -> str | None:
    """Protocol with the largest USD allocation (``None`` when flat)."""
    numeric = {
        str(p): float(v)
        for p, v in (positions or {}).items()
        if isinstance(v, (int, float)) and float(v) > 0
    }
    if not numeric:
        return None
    return max(numeric.items(), key=lambda kv: kv[1])[0]


def _risk_summary(risk_doc: Any) -> dict[str, str]:
    """adapter_id → letter grade from risk_scores.json (slug ``-`` → ``_``)."""
    out: dict[str, str] = {}
    if not isinstance(risk_doc, dict):
        return out
    for entry in risk_doc.get("scores") or []:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug") or entry.get("protocol")
        grade = entry.get("grade")
        if isinstance(slug, str) and isinstance(grade, str):
            out[slug.strip().lower().replace("-", "_").replace(" ", "_")] = grade
    return out


def _round_or_none(value: Any, ndigits: int = 4) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value), ndigits)
    return None


# ─── Public entry point ──────────────────────────────────────────────────────


def generate_daily_report(
    date_str: str | None = None,
    *,
    data_dir: str | os.PathLike | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> dict:
    """Build the daily report dict and (atomically) persist it.

    Parameters
    ----------
    date_str : ``"YYYY-MM-DD"``; default = yesterday (UTC).
    data_dir : directory with data/*.json (default ``<repo>/data``).
    now      : injectable clock (UTC) for deterministic tests.
    write    : if False, compute the dict but write nothing.

    Raises ``ValueError`` only for a malformed ``date_str`` — every missing
    or corrupt source file degrades gracefully to ``None``/empty fields.
    """
    now_dt = now or datetime.now(timezone.utc)
    if date_str is None:
        date_str = (now_dt.date() - timedelta(days=1)).isoformat()
    else:
        # Validate early: the date lands in a filename.
        datetime.strptime(date_str, "%Y-%m-%d")

    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    equity_doc = _read_json(ddir / EQUITY_FILENAME, {})
    status_doc = _read_json(ddir / STATUS_FILENAME, {})
    golive_doc = _read_json(ddir / GOLIVE_FILENAME, {})
    risk_doc = _read_json(ddir / RISK_SCORES_FILENAME, None)

    if not isinstance(status_doc, dict):
        status_doc = {}
    if not isinstance(golive_doc, dict):
        golive_doc = {}

    bar = _find_equity_bar(equity_doc, date_str)

    equity_usd: float | None = None
    daily_pnl_usd: float | None = None
    daily_pnl_pct: float | None = None
    total_return_pct: float | None = None
    if bar is not None:
        close = bar.get("close_equity", bar.get("equity"))
        open_ = bar.get("open_equity")
        equity_usd = _round_or_none(close, 2)
        if isinstance(close, (int, float)) and isinstance(open_, (int, float)):
            daily_pnl_usd = round(float(close) - float(open_), 4)
        daily_pnl_pct = _round_or_none(bar.get("daily_return_pct"), 6)
        total_return_pct = _round_or_none(bar.get("cumulative_return_pct"), 6)
    if total_return_pct is None:
        summary = equity_doc.get("summary") if isinstance(equity_doc, dict) else None
        if isinstance(summary, dict):
            total_return_pct = _round_or_none(summary.get("total_return_pct"))

    # Positions: prefer the bar's own snapshot (matches the report date exactly);
    # fall back to the latest paper_trading_status positions.
    positions = (bar or {}).get("positions") or status_doc.get("current_positions") or {}
    if not isinstance(positions, dict):
        positions = {}

    report = {
        "date": date_str,
        "generated_at": now_dt.isoformat(),
        "source": "daily_report",
        "is_demo": False,
        "equity_usd": equity_usd,
        "daily_pnl_usd": daily_pnl_usd,
        "daily_pnl_pct": daily_pnl_pct,
        "total_return_pct": total_return_pct,
        "days_running": status_doc.get("days_running"),
        "top_protocol": _top_protocol(positions),
        "golive_status": (
            "READY"
            if golive_doc.get("ready") is True
            else f"{golive_doc.get('passed', 0)}/{golive_doc.get('total', 26)} NOT_READY"
        ),
        "golive_passed": golive_doc.get("passed"),
        "golive_total": golive_doc.get("total"),
        "golive_blockers": golive_doc.get("blockers", []),
        "active_adapters": sorted(str(p) for p in positions),
        "risk_summary": _risk_summary(risk_doc),
    }

    if write:
        _atomic_write_json(ddir / REPORT_FILENAME_TPL.format(date=date_str), report)
    return report


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _print_summary(report: dict) -> None:
    print("─" * 56)
    print(f"SPA daily report  [{report['date']}]  {report['golive_status']}")
    print("─" * 56)
    eq = report["equity_usd"]
    pnl = report["daily_pnl_usd"]
    print(f"  equity        : {'—' if eq is None else f'${eq:,.2f}'}")
    print(f"  daily PnL     : {'—' if pnl is None else f'${pnl:,.4f}'}"
          + ("" if report["daily_pnl_pct"] is None else f"  ({report['daily_pnl_pct']:+.4f}%)"))
    tr = report["total_return_pct"]
    print(f"  total return  : {'—' if tr is None else f'{tr:+.4f}%'}")
    print(f"  top protocol  : {report['top_protocol'] or '—'}")
    print(f"  adapters      : {', '.join(report['active_adapters']) or '—'}")
    if report["risk_summary"]:
        grades = ", ".join(f"{k}={v}" for k, v in sorted(report["risk_summary"].items()))
        print(f"  risk grades   : {grades}")
    print("─" * 56)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="daily_report",
        description="Generate the SPA daily report (default: for yesterday).",
    )
    parser.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument("--dry-run", action="store_true", help="compute but write nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    report = generate_daily_report(
        args.date, data_dir=args.data_dir, write=not args.dry_run
    )
    _print_summary(report)
    if not args.dry_run:
        out = (Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR)
        print(f"written: {out / REPORT_FILENAME_TPL.format(date=report['date'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

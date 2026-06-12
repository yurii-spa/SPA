#!/usr/bin/env python3
"""JSON compatibility shim for SPA persistence layer (MP-109).

Provides the same read/write API as the legacy JSON-file approach, but
transparently reads from and writes to the SQLite database (``spa.db``).
During the transition period every write also updates the canonical JSON file,
so existing consumers of the JSON files continue to work without changes.

Usage
=====
Drop-in replacement for direct ``json.load(open(...))`` / ``json.dump(...)``
patterns used elsewhere in the codebase:

    from spa_core.persistence.json_compat import read_equity_curve, append_equity_point

All public functions accept optional ``db_path`` and ``data_dir`` kwargs so
that tests can redirect I/O to a temporary location without touching real data.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from spa_core.persistence.db import (
    get_equity_curve,
    get_daily_report,
    init_db,
    upsert_equity_point,
    upsert_daily_report,
    _REPO_ROOT,
    DB_PATH,
)

log = logging.getLogger("spa.json_compat")

_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_EQUITY_FILENAME = "equity_curve_daily.json"


# ─── Equity curve ────────────────────────────────────────────────────────────


def read_equity_curve(
    db_path: str | None = None,
    data_dir: str | Path | None = None,
) -> list[dict]:
    """Read the equity curve from SQLite; fall back to the JSON file if DB empty.

    Returns a list of daily bar dicts, oldest first.  Empty list if neither
    source is available.
    """
    rows = get_equity_curve(db_path=db_path)
    if rows:
        return rows

    # Fallback: read from the canonical JSON file.
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    eq_path = ddir / _EQUITY_FILENAME
    if not eq_path.exists():
        log.debug("read_equity_curve: no DB data and %s missing", eq_path)
        return []
    try:
        doc = json.loads(eq_path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            return doc.get("daily", [])
        if isinstance(doc, list):
            return doc
    except (ValueError, OSError) as exc:
        log.warning("read_equity_curve: JSON fallback failed (%s)", exc)
    return []


def append_equity_point(
    date_str: str,
    equity: float,
    pnl_usd: float,
    pnl_pct: float,
    db_path: str | None = None,
    data_dir: str | Path | None = None,
) -> None:
    """Write an equity point to SQLite AND update the JSON file (dual-write).

    The JSON file is updated atomically (tmp + os.replace) so existing readers
    are never exposed to a partial write.
    """
    # 1. Write to SQLite.
    init_db(db_path)
    upsert_equity_point(date_str, equity, pnl_usd, pnl_pct, db_path)

    # 2. Dual-write: update the JSON file so existing consumers keep working.
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    eq_path = ddir / _EQUITY_FILENAME
    _atomic_append_equity_json(eq_path, date_str, equity, pnl_usd, pnl_pct)


def _atomic_append_equity_json(
    eq_path: Path,
    date_str: str,
    equity: float,
    pnl_usd: float,
    pnl_pct: float,
) -> None:
    """Upsert a bar in the legacy equity_curve_daily.json (atomic write)."""
    try:
        doc: dict | list
        if eq_path.exists():
            try:
                doc = json.loads(eq_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                doc = {"daily": []}
        else:
            doc = {"daily": []}

        # Normalise: ensure we always operate on {"daily": [...]}
        if isinstance(doc, list):
            doc = {"daily": doc}
        daily: list = doc.get("daily", [])
        if not isinstance(daily, list):
            daily = []

        new_bar = {
            "date": date_str,
            "equity": equity,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Upsert: replace existing bar for same date or append.
        updated = False
        for i, bar in enumerate(daily):
            if isinstance(bar, dict) and bar.get("date") == date_str:
                # Preserve existing keys, overlay new values.
                bar.update(new_bar)
                daily[i] = bar
                updated = True
                break
        if not updated:
            daily.append(new_bar)

        doc["daily"] = daily
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Atomic write.
        parent = eq_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=".eq_curve_", suffix=".tmp")
        os.close(fd)
        try:
            Path(tmp_name).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp_name, str(eq_path))
        except Exception:
            try:
                os.remove(tmp_name)
            except OSError:
                pass
            raise
    except Exception as exc:
        log.warning("_atomic_append_equity_json failed (%s) — JSON not updated", exc)


# ─── Daily reports ───────────────────────────────────────────────────────────


def read_daily_report(
    date_str: str | None = None,
    db_path: str | None = None,
    data_dir: str | Path | None = None,
) -> dict | None:
    """Read a daily report from SQLite; fall back to the JSON file.

    Parameters
    ----------
    date_str:
        The date to look up (``YYYY-MM-DD``).  Defaults to today.
    """
    target = date_str or date.today().isoformat()
    # Try SQLite first.
    report = get_daily_report(target, db_path=db_path)
    if report is not None:
        return report

    # Fallback: read from the canonical JSON file.
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    json_path = ddir / f"daily_report_{target}.json"
    if not json_path.exists():
        log.debug("read_daily_report: no DB record and %s missing", json_path)
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("read_daily_report: JSON fallback for %s failed (%s)", target, exc)
    return None

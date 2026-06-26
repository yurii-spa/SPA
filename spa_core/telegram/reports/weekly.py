#!/usr/bin/env python3
"""spa_core/telegram/reports/weekly.py — THE one weekly digest (Tier 2).

Single canonical weekly Telegram message (Sundays ~10:00 UTC). Promotes the
clean read-only builder ``spa_core.reporting.weekly_telegram_report`` (7-day
performance, strategy ranking, rebalances, risk blocks, track progress) and
adds a date-stamp idempotency guard so a double-firing launchd agent can never
send twice in the same UTC week.

Allowlisted Telegram sender (test_telegram_single_authority).
stdlib only · deterministic · fail-safe · atomic guard write.

CLI::

    python3 -m spa_core.telegram.reports.weekly --check
    python3 -m spa_core.telegram.reports.weekly --run
    python3 -m spa_core.telegram.reports.weekly --run --force
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.reporting.weekly_telegram_report import (
    build_weekly_data,
    format_weekly_message,
)
from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.telegram.reports.weekly")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
GUARD_FILENAME = ".last_weekly_digest"


def build_weekly_message(
    end_date: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
) -> tuple[str, dict]:
    """Build the one weekly digest message + data. Never raises."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    try:
        data = build_weekly_data(end_date, data_dir=str(ddir), now=now)
        message = format_weekly_message(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("weekly digest: build failed: %s", exc)
        data, message = {}, "📋 <b>SPA Weekly Summary</b>\n⚠️ summary unavailable"
    return message, data


def _guard_path(ddir: Path) -> Path:
    return ddir / GUARD_FILENAME


def _iso_week(now_dt: datetime) -> str:
    iso = now_dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _already_sent_this_week(ddir: Path, week_key: str) -> bool:
    try:
        doc = atomic_load(str(_guard_path(ddir)), default={})
        if isinstance(doc, dict):
            return doc.get("week") == week_key
    except Exception:  # noqa: BLE001
        pass
    return False


def _mark_sent(ddir: Path, week_key: str, now_iso: str) -> None:
    try:
        atomic_save({"week": week_key, "sent_at": now_iso}, str(_guard_path(ddir)))
    except Exception:  # noqa: BLE001
        log.warning("weekly digest: guard write failed", exc_info=True)


def _send_html(message: str) -> bool:
    try:
        from spa_core.alerts.telegram_client import _post_message
        return bool(_post_message({"text": message, "parse_mode": "HTML"}))
    except Exception as exc:  # noqa: BLE001
        log.warning("weekly digest: send failed: %s", exc)
        return False


def run_weekly_digest(
    end_date: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    send: bool = True,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Build + (optionally) send the one weekly digest. Idempotent per ISO week."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    now_dt = now or datetime.now(timezone.utc)
    week_key = _iso_week(now_dt)
    result: dict[str, Any] = {
        "sent": False, "skipped": False, "message": "", "data": {}, "error": None,
    }
    try:
        msg, data = build_weekly_message(end_date, data_dir=ddir, now=now_dt)
        result["message"], result["data"] = msg, data
        if send and not force and _already_sent_this_week(ddir, week_key):
            result["skipped"] = True
            log.info("weekly digest: already sent for %s — skipping", week_key)
            return result
        if send:
            ok = _send_html(msg)
            result["sent"] = ok
            if ok:
                _mark_sent(ddir, week_key, now_dt.isoformat())
            else:
                result["error"] = "Telegram send returned False"
    except Exception as exc:  # noqa: BLE001
        log.warning("weekly digest: unexpected error: %s", exc)
        result["error"] = str(exc)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegram.reports.weekly", description="SPA single weekly digest."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="print preview, no send")
    group.add_argument("--run", action="store_true", help="send (idempotent per week)")
    parser.add_argument("--end", default=None, help="window end YYYY-MM-DD")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.check:
        msg, _ = build_weekly_message(args.end, data_dir=args.data_dir)
        print(re.sub(r"<[^>]+>", "", msg))
        return 0

    res = run_weekly_digest(args.end, data_dir=args.data_dir, send=True, force=args.force)
    if res["skipped"]:
        print("↺ Weekly digest already sent this week — skipped")
    elif res["sent"]:
        print("✅ Weekly digest sent")
    else:
        print(f"⚠️  Not sent: {res['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

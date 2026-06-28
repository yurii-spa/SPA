#!/usr/bin/env python3
"""spa_core/telegram/reports/daily.py — THE one daily digest (Tier 2).

Single canonical daily Telegram message (~08:10 UTC, after the 08:00 cycle).
Collapses the former four+ duplicate daily-report senders into one:

  * builds the rich day summary by PROMOTING the clean read-only builder
    ``spa_core.reporting.daily_telegram_report`` (track day, equity, P&L, APY,
    positions, go-live, cycle health, Base chain);
  * folds in any events ``push_policy`` demoted to the digest queue
    (``data/telegram/digest_queue.json``) as a "Today's digest" section with a
    one-line warnings summary instead of N individual pushes;
  * sends EXACTLY ONE message via ``telegram_client`` (the only transport);
  * is idempotent — a date-stamp guard (``data/.last_daily_digest``) refuses to
    send twice for the same UTC date even if the launchd agent double-fires.

Allowlisted Telegram sender (see test_telegram_single_authority): it is one of
the digest builders permitted to call the transport directly.

stdlib only · deterministic · fail-safe (never raises) · atomic guard write.

CLI::

    python3 -m spa_core.telegram.reports.daily --check   # print, no send
    python3 -m spa_core.telegram.reports.daily --run     # send (idempotent/day)
    python3 -m spa_core.telegram.reports.daily --run --force   # ignore date guard
"""
from __future__ import annotations

import argparse
import html
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.reporting.daily_telegram_report import (
    build_report_data,
    format_daily_message,
)
from spa_core.telegram import push_policy
from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.telegram.reports.daily")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
GUARD_FILENAME = ".last_daily_digest"
ALERT_STATE_FILENAME = "telegram_alert_state.json"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


# ── digest-queue → section ───────────────────────────────────────────────────
def _format_digest_section(items: list[dict]) -> str:
    """Render the queued (demoted) events as a compact summary section.

    Never lists each event individually beyond a small cap — a flapping detector
    would otherwise re-create the flood inside the digest. Counts by event_key.
    """
    if not items:
        return ""
    by_key: Counter[str] = Counter(str(i.get("event_key", "?")) for i in items)
    lines = ["", "🗂️ <b>Today's digest</b>"]
    lines.append(f"  {len(items)} non-critical event(s) since last digest:")
    for key, n in sorted(by_key.items(), key=lambda kv: (-kv[1], kv[0])):
        suffix = f" ×{n}" if n > 1 else ""
        lines.append(f"  • {_esc(key)}{suffix}")
    return "\n".join(lines)


def build_digest_message(
    date_str: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
    drain: bool = True,
) -> tuple[str, dict]:
    """Build the one daily digest message + structured data. Never raises.

    ``drain`` clears the digest queue once consumed (set False for --check).
    Returns ``(html_message, data)``.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    try:
        data = build_report_data(date_str, data_dir=str(ddir), now=now)
        base_msg = format_daily_message(data)
    except Exception as exc:  # noqa: BLE001 — degrade, never raise
        log.warning("daily digest: base report build failed: %s", exc)
        data = {}
        base_msg = "📊 <b>SPA Daily Report</b>\n⚠️ summary unavailable"

    try:
        queued = push_policy.drain_digest_queue(data_dir=str(ddir), clear=drain)
    except Exception:  # noqa: BLE001
        queued = []
    data["digest_queue_count"] = len(queued)

    section = _format_digest_section(queued)
    message = base_msg + ("\n" + section if section else "")
    return message, data


# ── idempotency guard ────────────────────────────────────────────────────────
def _guard_path(ddir: Path) -> Path:
    return ddir / GUARD_FILENAME


def _already_sent_today(ddir: Path, today: str) -> bool:
    try:
        doc = atomic_load(str(_guard_path(ddir)), default={})
        if isinstance(doc, dict):
            return doc.get("date") == today
    except Exception:  # noqa: BLE001
        pass
    return False


def _mark_sent_today(ddir: Path, today: str, now_iso: str) -> None:
    try:
        atomic_save({"date": today, "sent_at": now_iso}, str(_guard_path(ddir)))
    except Exception:  # noqa: BLE001
        log.warning("daily digest: guard write failed", exc_info=True)


def _days_between(prev_iso: str, today_iso: str) -> int | None:
    """Whole UTC days from ``prev_iso`` (YYYY-MM-DD) to ``today_iso``, or None."""
    try:
        d0 = datetime.strptime(prev_iso[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(today_iso[:10], "%Y-%m-%d").date()
        return (d1 - d0).days
    except (ValueError, TypeError):
        return None


def _detect_and_record_miss(ddir: Path, today: str, now_iso: str) -> dict:
    """Make a SILENTLY missed digest day VISIBLE (logged + flagged in state).

    WS-2.4 digest-miss guard: on each run we compare the last successfully-sent
    ``daily_summary`` date against today. If more than one calendar day elapsed
    (e.g. state jumped 06-26 → 06-28, so 06-27 was never sent), at least one day
    was silently missed. We DO NOT fabricate a sent-state for the missed day
    (honesty); instead we record the gap under ``daily_summary_misses`` (an
    append-only, capped list of {detected_at, last_sent, today, days_missed})
    and emit a WARNING so the miss is observable, never silent.

    Returns a dict ``{"days_missed": int, "last_sent": str|None}`` describing the
    detected gap (``days_missed == 0`` when there is no miss). Fail-safe.
    """
    info = {"days_missed": 0, "last_sent": None}
    try:
        path = ddir / ALERT_STATE_FILENAME
        doc = atomic_load(str(path), default={})
        if not isinstance(doc, dict):
            doc = {}
        last_sent = str(doc.get("daily_summary", "") or "")[:10]
        info["last_sent"] = last_sent or None
        if not last_sent:
            return info  # never sent → no "miss" to record (first-run, not a gap)
        gap = _days_between(last_sent, today)
        if gap is None or gap <= 1:
            return info  # 0 = already today, 1 = consecutive day — no miss
        days_missed = gap - 1
        info["days_missed"] = days_missed
        log.warning(
            "daily digest: %d day(s) silently MISSED — last successful daily "
            "summary %s, today %s (no send recorded for the gap)",
            days_missed, last_sent, today,
        )
        misses = doc.get("daily_summary_misses")
        if not isinstance(misses, list):
            misses = []
        misses.append({
            "detected_at": now_iso,
            "last_sent": last_sent,
            "today": today,
            "days_missed": days_missed,
        })
        doc["daily_summary_misses"] = misses[-50:]  # cap the audit list
        atomic_save(doc, str(path))
    except Exception:  # noqa: BLE001
        log.warning("daily digest: miss-guard write failed", exc_info=True)
    return info


def _mark_daily_summary_sent(ddir: Path, today: str) -> None:
    """Record that today's daily Telegram summary went out.

    Updates ``data/telegram_alert_state.json`` setting ``daily_summary`` to the
    UTC date, atomically, PRESERVING the other state keys (red_flag, gap_alert,
    weekly_report, daily_summary_misses). This is the state the go-live gate
    (``GoLiveChecker._check_telegram_alert_today``) reads — the RETIRED legacy
    daily-report agents used to write it, so the new digest must take that over
    or ``telegram_alert_today`` could never pass again. Honest: only called on a
    SUCCESSFUL send, so the criterion reflects "the summary actually went out
    today", never force-passed. Fail-safe (never raises).
    """
    try:
        path = ddir / ALERT_STATE_FILENAME
        doc = atomic_load(str(path), default={})
        if not isinstance(doc, dict):
            doc = {}
        doc["daily_summary"] = today
        doc["daily_summary_sent_at"] = datetime.now(timezone.utc).isoformat()
        atomic_save(doc, str(path))
    except Exception:  # noqa: BLE001
        log.warning("daily digest: alert-state write failed", exc_info=True)


# ── transport (allowlisted) ──────────────────────────────────────────────────
def _send_html(message: str) -> bool:
    try:
        from spa_core.alerts.telegram_client import _post_message
        return bool(_post_message({"text": message, "parse_mode": "HTML"}))
    except Exception as exc:  # noqa: BLE001
        log.warning("daily digest: send failed: %s", exc)
        return False


def run_daily_digest(
    date_str: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    send: bool = True,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Build + (optionally) send the one daily digest. Idempotent per UTC date.

    Returns ``{"sent", "skipped", "message", "data", "error"}``. Never raises.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    now_dt = now or datetime.now(timezone.utc)
    today = now_dt.date().isoformat()
    result: dict[str, Any] = {
        "sent": False, "skipped": False, "message": "", "data": {}, "error": None,
    }
    try:
        if send and not force and _already_sent_today(ddir, today):
            result["skipped"] = True
            log.info("daily digest: already sent for %s — skipping", today)
            # Still build the message (for observability) but do not drain/send.
            msg, data = build_digest_message(date_str, data_dir=ddir, now=now_dt, drain=False)
            result["message"], result["data"] = msg, data
            return result

        # Drain only when we will actually send (so --check doesn't lose the queue).
        msg, data = build_digest_message(date_str, data_dir=ddir, now=now_dt, drain=bool(send))
        result["message"], result["data"] = msg, data
        if send:
            # WS-2.4 miss-guard: BEFORE today's send overwrites the state, detect
            # whether the previous successful day was >1 day ago (a silently
            # missed digest day) and make it visible (log + flagged state). We do
            # NOT fabricate a sent-state for the missed day.
            miss = _detect_and_record_miss(ddir, today, now_dt.isoformat())
            result["days_missed"] = miss["days_missed"]
            ok = _send_html(msg)
            result["sent"] = ok
            if ok:
                _mark_sent_today(ddir, today, now_dt.isoformat())
                # The go-live gate's telegram_alert_today criterion reads
                # data/telegram_alert_state.json:daily_summary — record that the
                # daily summary went out today so it can pass (the retired legacy
                # daily-report agents used to own this write).
                _mark_daily_summary_sent(ddir, today)
            else:
                result["error"] = "Telegram send returned False"
    except Exception as exc:  # noqa: BLE001 — never raises
        log.warning("daily digest: unexpected error: %s", exc)
        result["error"] = str(exc)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegram.reports.daily", description="SPA single daily digest."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="print preview, no send")
    group.add_argument("--run", action="store_true", help="send (idempotent per day)")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--force", action="store_true", help="ignore date-stamp guard")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.check:
        msg, _ = build_digest_message(args.date, data_dir=args.data_dir, drain=False)
        print(re.sub(r"<[^>]+>", "", msg))
        return 0

    res = run_daily_digest(args.date, data_dir=args.data_dir, send=True, force=args.force)
    if res["skipped"]:
        print("↺ Daily digest already sent today — skipped")
    elif res["sent"]:
        print("✅ Daily digest sent")
    else:
        print(f"⚠️  Not sent: {res['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

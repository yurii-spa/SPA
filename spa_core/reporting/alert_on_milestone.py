#!/usr/bin/env python3
"""Smart milestone Telegram alerts for SPA paper trading.

Fires a one-time celebratory Telegram message when the track crosses a
meaningful threshold. Each milestone is sent exactly once — already-notified
ids are recorded in ``data/milestone_telegram_state.json`` (atomic write).

Milestones evaluated each run:

* ``track_day_14``   — Day 14: "Half-way to 30-day track"
* ``track_day_30``   — Day 30: "30-day track complete! 🎉"
* ``apy_above_6``    — Paper APY > 6%: "APY milestone: 6%+ achieved"
* ``golive_26_26``   — GoLive 26/26: "ALL SYSTEMS GO 🚀"

Sources (read-only, optional — degrade gracefully, never raise):

* ``data/paper_trading_status.json``  — days_running, apy_today_pct, paper_start_date
* ``data/golive_status.json``         — passed/total
* ``data/equity_curve_daily.json``    — fallback for days/apy

Stdlib only. Atomic state writes. Never raises.

CLI::

    python3 -m spa_core.reporting.alert_on_milestone --check   # print, no send
    python3 -m spa_core.reporting.alert_on_milestone --run     # send + persist state
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.reporting.alert_on_milestone")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_FILENAME = "paper_trading_status.json"
GOLIVE_FILENAME = "golive_status.json"
EQUITY_FILENAME = "equity_curve_daily.json"
STATE_FILENAME = "milestone_telegram_state.json"

PAPER_START_FALLBACK = "2026-06-10"

HALFWAY_DAY = 14
TRACK_COMPLETE_DAY = 30
APY_MILESTONE_PCT = 6.0


# ─── IO helpers ──────────────────────────────────────────────────────────────


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


def load_state(data_dir: str | Path | None = None) -> dict:
    """Read milestone alert state. Returns ``{"notified": [...]}`` shape."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    state = _read_json(ddir / STATE_FILENAME, {})
    if not isinstance(state, dict):
        return {"notified": []}
    if not isinstance(state.get("notified"), list):
        state["notified"] = []
    return state


def save_state(state: dict, data_dir: str | Path | None = None) -> None:
    """Atomically write milestone alert state (tmp + os.replace)."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    atomic_save(state, str(ddir / STATE_FILENAME))


# ─── Metric collection ───────────────────────────────────────────────────────


def _track_days(status_doc: dict, equity_doc: Any) -> int | None:
    """Best-effort current track-day count."""
    days = status_doc.get("days_running")
    if isinstance(days, int):
        return days
    # Derive from paper_start_date + last equity bar date.
    paper_start = status_doc.get("paper_start_date") or PAPER_START_FALLBACK
    last_date = None
    if isinstance(equity_doc, dict):
        daily = equity_doc.get("daily")
        if isinstance(daily, list) and daily and isinstance(daily[-1], dict):
            last_date = daily[-1].get("date")
    if not last_date:
        return None
    try:
        d0 = datetime.strptime(str(paper_start), "%Y-%m-%d").date()
        d1 = datetime.strptime(str(last_date), "%Y-%m-%d").date()
    except ValueError:
        return None
    delta = (d1 - d0).days
    return delta + 1 if delta >= 0 else None


def _current_apy(status_doc: dict, equity_doc: Any) -> float | None:
    apy = status_doc.get("apy_today_pct")
    if isinstance(apy, (int, float)):
        return float(apy)
    if isinstance(equity_doc, dict):
        daily = equity_doc.get("daily")
        if isinstance(daily, list) and daily and isinstance(daily[-1], dict):
            a = daily[-1].get("apy_today")
            if isinstance(a, (int, float)):
                return float(a)
    return None


# ─── Milestone evaluation ────────────────────────────────────────────────────


def _milestone_message(ms_id: str, *, days: int | None, apy: float | None,
                       passed: Any, total: Any) -> str:
    """Single-milestone HTML message body."""
    if ms_id == "track_day_14":
        return (
            "🎯 <b>SPA Milestone — Half-way!</b>\n\n"
            f"Day {days} of the 30-day continuous track reached.\n"
            "Half-way to the go-live review gate (ADR-002)."
        )
    if ms_id == "track_day_30":
        return (
            "🎉 <b>SPA Milestone — 30-day track complete!</b>\n\n"
            f"Day {days}: the 30-day continuous paper track is in the books.\n"
            "Go-live review window (READY 7+ days) can now begin."
        )
    if ms_id == "apy_above_6":
        return (
            "📈 <b>SPA Milestone — APY 6%+ achieved</b>\n\n"
            f"Paper APY hit {apy:.2f}% (above the 6% milestone)."
        )
    if ms_id == "golive_26_26":
        return (
            "🚀 <b>SPA Milestone — ALL SYSTEMS GO</b>\n\n"
            f"GoLiveChecker: {passed}/{total} criteria pass.\n"
            "Every readiness criterion is green."
        )
    return f"🎯 <b>SPA Milestone — {ms_id}</b>"


def check_milestones(
    *,
    days: int | None,
    apy: float | None,
    passed: Any,
    total: Any,
    notified: list[str],
) -> list[dict]:
    """Return newly-reached, not-yet-notified milestone dicts.

    Each dict: ``{"id": str, "message": str}``. Pure function — no IO.
    """
    reached: list[str] = []

    if isinstance(days, int):
        if days >= HALFWAY_DAY:
            reached.append("track_day_14")
        if days >= TRACK_COMPLETE_DAY:
            reached.append("track_day_30")
    if isinstance(apy, (int, float)) and apy > APY_MILESTONE_PCT:
        reached.append("apy_above_6")
    if isinstance(passed, int) and isinstance(total, int) and total > 0 and passed >= total:
        reached.append("golive_26_26")

    new: list[dict] = []
    for ms_id in reached:
        if ms_id in notified:
            continue
        new.append(
            {
                "id": ms_id,
                "message": _milestone_message(
                    ms_id, days=days, apy=apy, passed=passed, total=total
                ),
            }
        )
    return new


# ─── Send ─────────────────────────────────────────────────────────────────────


def _send_html(message: str) -> bool:
    """Send via Keychain-backed telegram_client (HTML mode). Never raises."""
    try:
        from spa_core.alerts.telegram_client import _post_message as _tg_post
        return _tg_post({"text": message, "parse_mode": "HTML"})
    except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
        log.warning("alert_on_milestone: send failed: %s", exc)
        return False


def run_milestone_alerts(
    data_dir: str | Path | None = None,
    *,
    send: bool = True,
) -> dict:
    """Evaluate milestones and send a Telegram alert for each new one.

    Returns ``{"sent": [...ids], "new": [...ids], "error": str | None}``.
    Never raises.
    """
    result: dict[str, Any] = {"sent": [], "new": [], "error": None}
    try:
        ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

        status_doc = _read_json(ddir / STATUS_FILENAME, {})
        golive_doc = _read_json(ddir / GOLIVE_FILENAME, {})
        equity_doc = _read_json(ddir / EQUITY_FILENAME, {})
        if not isinstance(status_doc, dict):
            status_doc = {}
        if not isinstance(golive_doc, dict):
            golive_doc = {}

        # Never alert on demo data.
        if status_doc.get("is_demo") is True or equity_doc.get("is_demo") is True:
            log.debug("alert_on_milestone: is_demo=True, skipping")
            return result

        days = _track_days(status_doc, equity_doc)
        apy = _current_apy(status_doc, equity_doc)
        passed = golive_doc.get("passed")
        total = golive_doc.get("total")

        state = load_state(ddir)
        notified = state["notified"]

        new = check_milestones(
            days=days, apy=apy, passed=passed, total=total, notified=notified
        )
        result["new"] = [m["id"] for m in new]

        if not new or not send:
            # --check mode: report what would fire without sending or persisting.
            return result

        for ms in new:
            if _send_html(ms["message"]):
                result["sent"].append(ms["id"])
                if ms["id"] not in notified:
                    notified.append(ms["id"])
            else:
                result["error"] = "Telegram send returned False"

        if result["sent"]:
            state["notified"] = notified
            state["last_run"] = datetime.now(timezone.utc).isoformat()
            try:
                save_state(state, ddir)
            except Exception as exc:  # noqa: BLE001
                log.warning("alert_on_milestone: failed to save state: %s", exc)
                result["error"] = str(exc)

    except Exception as exc:  # noqa: BLE001 — never raises
        log.warning("alert_on_milestone: unexpected error: %s", exc)
        result["error"] = str(exc)
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alert_on_milestone",
        description="Smart milestone Telegram alerts for SPA.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="print pending milestones, no send")
    group.add_argument("--run", action="store_true", help="send alerts + persist state")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ddir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    if args.check:
        result = run_milestone_alerts(ddir, send=False)
        if not result["new"]:
            print("No new milestones")
        else:
            print(f"Would send {len(result['new'])} milestone(s): {result['new']}")
        return 0

    result = run_milestone_alerts(ddir, send=True)
    if result["sent"]:
        print(f"✅ Sent: {result['sent']}")
    elif result["new"]:
        print(f"⚠️  Found but send failed: {result['new']} ({result['error']})")
    else:
        print("ℹ️  No new milestones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

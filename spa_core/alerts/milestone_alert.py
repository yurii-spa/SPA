"""MP-143: Milestone Reached Telegram Alert.

Checks data/progress_tracker.json for milestones that newly reached=True
and sends a single Telegram notification per milestone (exactly once,
tracked in data/milestone_alert_state.json).

Stdlib only (no anthropic / numpy / pandas). Atomic writes.
Never raises — all public entry points return a dict.

CLI:
    python3 -m spa_core.alerts.milestone_alert --check   # print only, no send
    python3 -m spa_core.alerts.milestone_alert --run     # send + update state
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.alerts.milestone_alert")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

PROGRESS_TRACKER_FILE = "progress_tracker.json"
ALERT_STATE_FILE = "milestone_alert_state.json"


# ─── I/O helpers ────────────────────────────────────────────────────────────


def load_progress_tracker(data_dir: str | Path | None = None) -> dict:
    """Read data/progress_tracker.json.  Returns {} on any error."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    path = ddir / PROGRESS_TRACKER_FILE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("load_progress_tracker: %s", exc)
        return {}


def load_alert_state(data_dir: str | Path | None = None) -> dict:
    """Read data/milestone_alert_state.json.  Returns {} on any error.

    Schema: {"notified": ["milestone_id1", ...], "last_run": "ISO"}
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    path = ddir / ALERT_STATE_FILE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:  # noqa: BLE001
        log.debug("load_alert_state (expected on first run): %s", exc)
        return {}


def save_alert_state(state: dict, data_dir: str | Path | None = None) -> None:
    """Atomically write data/milestone_alert_state.json (mkstemp + os.replace)."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    path = ddir / ALERT_STATE_FILE
    atomic_save(state, str(path))
# ─── Core logic ─────────────────────────────────────────────────────────────


def check_new_milestones(progress: dict, alert_state: dict) -> list[dict]:
    """Return milestone dicts that are newly reached and not yet notified.

    A milestone is "new" when reached=True and its id is absent from
    alert_state["notified"].  Already-notified milestones are skipped so no
    duplicate notifications are ever sent.
    """
    milestones: list[dict] = progress.get("milestones", [])
    if not isinstance(milestones, list):
        return []
    notified: list[str] = alert_state.get("notified", [])
    if not isinstance(notified, list):
        notified = []

    new: list[dict] = []
    for ms in milestones:
        if not isinstance(ms, dict):
            continue
        ms_id = ms.get("id", "")
        if ms.get("reached") is True and ms_id and ms_id not in notified:
            new.append(ms)
    return new


def format_milestone_message(milestones: list[dict], progress: dict) -> str:
    """Format an HTML Telegram message for one or more newly reached milestones.

    Example output:
        🎯 <b>SPA: Milestone Reached!</b>

        ✅ <b>Honest Metrics: LOW_CONFIDENCE (≥7d)</b>
        Статистика теперь считается с минимальной достоверностью.

        📊 Paper trading: день 7 | $100,034.21 | APY 3.22%
        🚀 Go-live: 26 дней осталось
    """
    lines: list[str] = []
    lines.append("🎯 <b>SPA: Milestone Reached!</b>")

    for ms in milestones:
        label = ms.get("label", ms.get("id", "Unknown milestone"))
        ms_id = ms.get("id", "")
        lines.append("")
        lines.append(f"✅ <b>{label}</b>")
        # Brief human-readable description per milestone id
        desc = _milestone_description(ms_id)
        if desc:
            lines.append(desc)

    # Footer: paper trading summary
    paper_days = progress.get("paper_days", 0)
    equity = progress.get("current_equity", 0.0)
    apy = progress.get("apy_today_pct", 0.0)
    days_to_golive = progress.get("days_to_golive", "?")

    lines.append("")
    lines.append(
        f"📊 Paper trading: день {paper_days} | "
        f"${equity:,.2f} | APY {apy:.2f}%"
    )
    lines.append(f"🚀 Go-live: {days_to_golive} дней осталось")

    return "\n".join(lines)


def _milestone_description(ms_id: str) -> str:
    """Return a short Russian description for known milestone ids."""
    descriptions: dict[str, str] = {
        "honest_metrics_low": "Статистика теперь считается с минимальной достоверностью.",
        "honest_metrics_moderate": "Статистика переходит в режим умеренной достоверности.",
        "honest_metrics_high": "Высокая достоверность — 90+ дней реального трека.",
        "backtest_contour_min": "Корреляция бэктест vs paper trading стала читаемой.",
        "structural_break_min": "Детектор структурных разрывов получил достаточно данных.",
    }
    return descriptions.get(ms_id, "")


# ─── Main entry point ────────────────────────────────────────────────────────


def run_milestone_alert(data_dir: str | Path | None = None) -> dict:
    """Check for newly reached milestones and send Telegram alert if found.

    Returns:
        {"sent": bool, "new_milestones": list[str], "error": str | None}

    Never raises.
    """
    result: dict[str, Any] = {"sent": False, "new_milestones": [], "error": None}
    try:
        ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

        progress = load_progress_tracker(ddir)

        # Skip entirely if no data available or is_demo
        if not progress:
            log.debug("milestone_alert: progress_tracker empty, skipping")
            return result
        if progress.get("is_demo", False):
            log.debug("milestone_alert: is_demo=True, skipping")
            return result
        if not progress.get("available", True):
            log.debug("milestone_alert: progress_tracker not available, skipping")
            return result

        alert_state = load_alert_state(ddir)
        new_milestones = check_new_milestones(progress, alert_state)

        if not new_milestones:
            log.debug("milestone_alert: no new milestones, nothing to send")
            # Still update last_run timestamp
            alert_state["last_run"] = datetime.now(timezone.utc).isoformat()
            try:
                save_alert_state(alert_state, ddir)
            except Exception as exc:  # noqa: BLE001
                log.warning("milestone_alert: failed to update last_run: %s", exc)
            return result

        # Format and send
        message = format_milestone_message(new_milestones, progress)

        try:
            # Use _post_message directly to pass parse_mode=HTML (our format uses <b> tags).
            # _post_message is fail-safe: missing credentials / network errors → WARNING + False.
            from spa_core.alerts.telegram_client import _post_message as _tg_post  # type: ignore[import]
            sent = _tg_post({"text": message, "parse_mode": "HTML"})
        except ImportError:
            # Fallback: module-level send_message (Markdown mode — best-effort)
            try:
                from spa_core.alerts.telegram_client import send_message as _send  # type: ignore[import]
                sent = _send(message)
            except Exception as exc:  # noqa: BLE001
                log.warning("milestone_alert: Telegram send failed: %s", exc)
                result["error"] = str(exc)
                return result
        except Exception as exc:  # noqa: BLE001
            log.warning("milestone_alert: Telegram send failed: %s", exc)
            result["error"] = str(exc)
            return result

        new_ids = [ms.get("id", "") for ms in new_milestones]
        result["new_milestones"] = new_ids

        if sent:
            result["sent"] = True
            # Update state: mark all new milestones as notified
            notified = alert_state.get("notified", [])
            if not isinstance(notified, list):
                notified = []
            for ms_id in new_ids:
                if ms_id and ms_id not in notified:
                    notified.append(ms_id)
            alert_state["notified"] = notified
            alert_state["last_run"] = datetime.now(timezone.utc).isoformat()
            try:
                save_alert_state(alert_state, ddir)
            except Exception as exc:  # noqa: BLE001
                log.warning("milestone_alert: failed to save state: %s", exc)
                result["error"] = str(exc)
        else:
            log.warning("milestone_alert: Telegram returned False (send failed)")
            result["error"] = "Telegram send returned False"

    except Exception as exc:  # noqa: BLE001 — never raises
        log.warning("milestone_alert: unexpected error: %s", exc)
        result["error"] = str(exc)

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _cli_check(data_dir: Path) -> None:
    """Print new milestones without sending."""
    progress = load_progress_tracker(data_dir)
    alert_state = load_alert_state(data_dir)

    if not progress:
        print("progress_tracker.json not available")
        return
    if progress.get("is_demo", False):
        print("is_demo=True — no alert would be sent")
        return

    new_milestones = check_new_milestones(progress, alert_state)
    if not new_milestones:
        print("No new milestones to notify")
        already = alert_state.get("notified", [])
        if already:
            print(f"Already notified: {already}")
        return

    print(f"Would send alert for {len(new_milestones)} milestone(s):")
    for ms in new_milestones:
        print(f"  • {ms.get('id')}: {ms.get('label')}")
    print()
    msg = format_milestone_message(new_milestones, progress)
    print("--- Message preview ---")
    # Strip HTML tags for terminal display
    import re
    plain = re.sub(r"<[^>]+>", "", msg)
    print(plain)
    print("-----------------------")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="MP-143: Milestone Reached Telegram Alert"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="Print new milestones without sending (dry-run)",
    )
    group.add_argument(
        "--run",
        action="store_true",
        help="Send Telegram alert for new milestones and update state",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (default: <repo>/data)",
    )
    args = parser.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.check:
        _cli_check(data_dir)
    elif args.run:
        result = run_milestone_alert(data_dir)
        if result["sent"]:
            print(f"✅ Sent alert for: {result['new_milestones']}")
        elif result["new_milestones"]:
            print(f"⚠️  Found milestones but send failed: {result['error']}")
        else:
            print("ℹ️  No new milestones to notify")
        if result["error"]:
            print(f"Error: {result['error']}")


if __name__ == "__main__":
    main()

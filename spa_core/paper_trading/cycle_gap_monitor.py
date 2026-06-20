"""MP-144: Cycle Gap Monitor — detects missed daily cycles and sends a Telegram alert.

Reads data/paper_trading_status.json for ``last_cycle_ts``. If the timestamp
indicates the daily cycle has not run in >26 hours AND the current UTC hour is
≥ 10 (08:00 expected start + 2h tolerance), a gap is detected. An alert is sent
at most once per calendar day — deduplication tracked in
``data/cycle_gap_state.json``.

Fallback: if ``last_cycle_ts`` is null/missing, tries ``data/cycle_log.json``
for the last entry's ``ts`` field.

**Heartbeat guarantee (AGENT-P0-006 fix):** ``data/cycle_gap_state.json`` is
written on EVERY run (unless ``dry_run=True``).  Even when no gap is detected
the file is updated with ``last_check_ts``, ``gap_detected``, ``hours_since``
and ``alert_sent`` so that external tools (GoLiveChecker, dashboards) can
verify the monitor is alive without relying on a gap ever having occurred.
Alert-deduplication fields (``last_alert_date``, ``last_alert_ts``) are
preserved across writes.

Stdlib only + ``spa_core.alerts.telegram_client``. Atomic state writes via
mkstemp + os.replace. Never raises — all exceptions are caught and logged
as warnings.

CLI::

    python3 -m spa_core.paper_trading.cycle_gap_monitor --check   # dry-run
    python3 -m spa_core.paper_trading.cycle_gap_monitor           # run + write heartbeat
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.cycle_gap_monitor")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_FILENAME = "paper_trading_status.json"
CYCLE_LOG_FILENAME = "cycle_log.json"
GAP_STATE_FILENAME = "cycle_gap_state.json"

# Gap threshold: expected 24h cycle + 2h tolerance
GAP_THRESHOLD_HOURS: float = 26.0
# Only alert if current UTC hour >= this value (08:00 expected + 2h)
GAP_ALERT_AFTER_UTC_HOUR: int = 10
# Sentinel hours_since value when last_cycle_ts is unknown
_UNKNOWN_HOURS = 999.0

# Go-live decision date (for message formatting)
_GOLIVE_DATE = datetime(2026, 7, 15, tzinfo=timezone.utc)


# ─── I/O helpers ──────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → ``default``. Never raises."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Shim — delegates to spa_core.utils.atomic.atomic_save."""
    atomic_save(obj, path)
def _get_last_cycle_ts(data_dir: Path) -> str | None:
    """Resolve the last cycle timestamp from status or cycle_log.

    Priority:
    1. ``data/paper_trading_status.json`` → ``last_cycle_ts``
    2. ``data/cycle_log.json`` → last entry's ``ts`` / ``timestamp``

    Returns an ISO-8601 string, or ``None`` if unavailable.
    """
    status = _read_json(data_dir / STATUS_FILENAME, {})
    if isinstance(status, dict):
        ts = status.get("last_cycle_ts")
        if ts and isinstance(ts, str):
            return ts

    # Fallback: cycle_log.json
    cycle_log = _read_json(data_dir / CYCLE_LOG_FILENAME, [])
    if isinstance(cycle_log, list) and cycle_log:
        last_entry = cycle_log[-1]
        if isinstance(last_entry, dict):
            ts = last_entry.get("ts") or last_entry.get("timestamp")
            if ts and isinstance(ts, str):
                return ts

    return None


def _parse_iso(ts_str: str) -> datetime | None:
    """Parse an ISO-8601 string to a UTC-aware datetime.

    Handles 'Z' suffix for Python < 3.11 compatibility.
    Returns ``None`` on any parse error.
    """
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError, TypeError):
        return None


# ─── Gap detection ────────────────────────────────────────────────────────────


def detect_gap(
    last_cycle_ts: str | None,
    *,
    now: datetime | None = None,
) -> tuple[bool, float]:
    """Compute whether a cycle gap exists.

    A gap is detected when **both** conditions hold:
    * ``hours_since_last > GAP_THRESHOLD_HOURS`` (26h)
    * current UTC hour >= ``GAP_ALERT_AFTER_UTC_HOUR`` (10)

    If ``last_cycle_ts`` is ``None`` or unparseable, ``hours_since`` is set
    to the sentinel value ``999.0``.

    Returns
    -------
    (gap_detected, hours_since)
        ``gap_detected`` is ``True`` only when both conditions hold.
        ``hours_since`` is the floating-point hours elapsed (or 999.0).
    """
    now_dt = now if now is not None else datetime.now(timezone.utc)

    if last_cycle_ts is None:
        hours_since = _UNKNOWN_HOURS
    else:
        last_dt = _parse_iso(last_cycle_ts)
        if last_dt is None:
            hours_since = _UNKNOWN_HOURS
        else:
            delta = now_dt - last_dt
            hours_since = delta.total_seconds() / 3600.0

    time_condition = now_dt.hour >= GAP_ALERT_AFTER_UTC_HOUR
    gap_detected = (hours_since > GAP_THRESHOLD_HOURS) and time_condition
    return gap_detected, hours_since


# ─── Deduplication ───────────────────────────────────────────────────────────


def _should_send_alert(gap_state: dict, today: str) -> bool:
    """Return ``True`` if no alert has been sent today yet."""
    return gap_state.get("last_alert_date") != today


def _updated_gap_state(gap_state: dict, *, today: str, now_ts: str) -> dict:
    """Return a new gap_state dict with today recorded as alerted."""
    updated = dict(gap_state)
    updated["last_alert_date"] = today
    updated["last_alert_ts"] = now_ts
    return updated


def _build_heartbeat_state(
    existing_state: dict,
    *,
    gap_detected: bool,
    hours_since: float,
    alert_sent: bool,
    now_ts: str,
) -> dict:
    """Build a heartbeat state dict for writing on every run.

    Merges current-run results with ``existing_state`` so that alert
    deduplication fields (``last_alert_date``, ``last_alert_ts``) are
    preserved across runs where no new alert was sent.

    Parameters
    ----------
    existing_state:
        The previously-persisted state dict (may be empty for first run).
    gap_detected:
        Whether a cycle gap was detected in this run.
    hours_since:
        Elapsed hours since the last cycle (999.0 if unknown).
    alert_sent:
        Whether a Telegram alert was sent in this run.
    now_ts:
        ISO-8601 timestamp of this run (injected for determinism in tests).

    Returns
    -------
    dict
        A new dict suitable for atomic serialisation to ``cycle_gap_state.json``.
    """
    state = dict(existing_state)          # preserve last_alert_date / last_alert_ts
    state["last_check_ts"] = now_ts
    state["gap_detected"] = gap_detected
    state["hours_since"] = round(hours_since, 2)
    state["alert_sent"] = alert_sent
    return state


# ─── Message formatting ───────────────────────────────────────────────────────


def _format_alert_message(
    last_cycle_ts: str | None,
    hours_since: float,
    paper_days: int,
    days_to_golive: int,
) -> str:
    """Return the HTML Telegram message for a detected cycle gap."""
    last_display = last_cycle_ts if last_cycle_ts else "unknown"
    lines = [
        "⚠️ <b>SPA — Cycle Gap Detected</b>",
        "",
        f"📅 Last cycle: {last_display} ({hours_since:.1f}h ago)",
        "🕐 Expected: daily ~08:00 UTC",
        "❌ Today's cycle appears to have MISSED",
        "",
        f"Track record: Day {paper_days} / go-live {days_to_golive}d",
        "⚡ Action: check launchd com.spa.daily_cycle status",
    ]
    return "\n".join(lines)


def _compute_paper_days(status: dict, now: datetime) -> int:
    """Compute paper trading days from the status document."""
    paper_start = status.get("paper_start_date", "2026-05-20")
    try:
        d0 = datetime.strptime(paper_start, "%Y-%m-%d").date()
        return max(1, (now.date() - d0).days + 1)
    except (ValueError, TypeError):
        days_running = status.get("days_running")
        if isinstance(days_running, int) and days_running > 0:
            return days_running
        return 1


def _compute_days_to_golive(now: datetime) -> int:
    """Return calendar days until the go-live decision date (2026-07-15)."""
    try:
        delta = _GOLIVE_DATE - now
        return max(0, delta.days)
    except Exception:
        return 0


# ─── Telegram delivery ────────────────────────────────────────────────────────


def _send_telegram_alert(message: str) -> bool:
    """Send an HTML-formatted Telegram message via the keychain-backed client.

    Uses ``_post_message`` directly with ``parse_mode=HTML`` so that ``<b>``
    tags render correctly (same pattern as ``milestone_alert``). Falls back to
    ``send_message`` (Markdown mode) if the private symbol is unavailable.

    Returns ``True`` on success, ``False`` on any failure. Never raises.
    """
    try:
        from spa_core.alerts.telegram_client import _post_message as _tg_post  # type: ignore[import]
        return bool(_tg_post({"text": message, "parse_mode": "HTML"}))
    except ImportError:
        pass
    except Exception as exc:
        log.warning("cycle_gap_monitor: Telegram send failed: %s", exc)
        return False
    # Fallback
    try:
        from spa_core.alerts.telegram_client import send_message as _send  # type: ignore[import]
        return bool(_send(message))
    except Exception as exc:
        log.warning("cycle_gap_monitor: Telegram send (fallback) failed: %s", exc)
        return False


# ─── Public entry point ───────────────────────────────────────────────────────


def run_cycle_gap_monitor(
    data_dir: "str | os.PathLike | None" = None,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict:
    """Detect missed daily cycles and send a Telegram alert if warranted.

    Reads ``data/paper_trading_status.json`` for ``last_cycle_ts``. Sends at
    most one Telegram alert per calendar day (state tracked in
    ``data/cycle_gap_state.json``).

    **Heartbeat guarantee:** ``data/cycle_gap_state.json`` is written on every
    call (unless ``dry_run=True``) regardless of whether a gap was detected.
    This lets external systems (GoLiveChecker, dashboards) verify that the
    monitor is alive even when cycles are healthy and no gap ever occurs.
    Alert-deduplication fields are preserved across heartbeat writes.

    Parameters
    ----------
    data_dir : directory for data/*.json files (default: <repo>/data).
    now      : injectable UTC datetime for deterministic testing.
    dry_run  : if ``True``, compute gap status but do NOT write state or send.

    Returns
    -------
    dict with:
        ``gap_detected``  – ``bool`` — ``True`` if a cycle gap was detected.
        ``hours_since``   – ``float`` — hours since last cycle (999.0 if unknown).
        ``alert_sent``    – ``bool`` — ``True`` if a Telegram alert was sent.

    Never raises. All exceptions are caught and logged as ``log.warning``.
    """
    result: dict[str, Any] = {
        "gap_detected": False,
        "hours_since": 0.0,
        "alert_sent": False,
    }
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        now_dt = now if now is not None else datetime.now(timezone.utc)
        today = now_dt.strftime("%Y-%m-%d")
        now_ts = now_dt.isoformat()

        # ── Step 1: resolve last cycle timestamp ──────────────────────────
        last_cycle_ts = _get_last_cycle_ts(ddir)

        # ── Step 2: gap detection ─────────────────────────────────────────
        gap_detected, hours_since = detect_gap(last_cycle_ts, now=now_dt)
        result["gap_detected"] = gap_detected
        result["hours_since"] = round(hours_since, 2)

        # ── Always load existing state (for dedup preservation + heartbeat) ──
        gap_state = _read_json(ddir / GAP_STATE_FILENAME, {})
        if not isinstance(gap_state, dict):
            gap_state = {}

        if not gap_detected:
            log.debug(
                "cycle_gap_monitor: no gap (%.1fh since last cycle)", hours_since
            )
            # HEARTBEAT: write state even when healthy so monitors can see us
            if not dry_run:
                heartbeat = _build_heartbeat_state(
                    gap_state,
                    gap_detected=False,
                    hours_since=hours_since,
                    alert_sent=False,
                    now_ts=now_ts,
                )
                _atomic_write_json(ddir / GAP_STATE_FILENAME, heartbeat)
            return result

        log.warning(
            "cycle_gap_monitor: GAP DETECTED — %.1fh since last cycle "
            "(threshold=%.0fh, today=%s)",
            hours_since,
            GAP_THRESHOLD_HOURS,
            today,
        )

        # ── Step 3: deduplication — one alert per calendar day ───────────
        if not _should_send_alert(gap_state, today):
            log.info(
                "cycle_gap_monitor: alert already sent today (%s) — skipping duplicate",
                today,
            )
            # HEARTBEAT: update last_check_ts even though alert was already sent
            if not dry_run:
                heartbeat = _build_heartbeat_state(
                    gap_state,
                    gap_detected=True,
                    hours_since=hours_since,
                    alert_sent=False,
                    now_ts=now_ts,
                )
                _atomic_write_json(ddir / GAP_STATE_FILENAME, heartbeat)
            return result

        if dry_run:
            log.info("cycle_gap_monitor: dry_run=True — gap detected but send skipped")
            return result

        # ── Step 4: build and send the alert ─────────────────────────────
        status = _read_json(ddir / STATUS_FILENAME, {})
        if not isinstance(status, dict):
            status = {}
        paper_days = _compute_paper_days(status, now_dt)
        days_to_golive = _compute_days_to_golive(now_dt)
        message = _format_alert_message(
            last_cycle_ts, hours_since, paper_days, days_to_golive
        )

        sent = _send_telegram_alert(message)
        result["alert_sent"] = sent

        if sent:
            log.warning(
                "cycle_gap_monitor: Telegram alert sent (%.1fh gap)", hours_since
            )
            alert_state = _updated_gap_state(
                gap_state, today=today, now_ts=now_ts
            )
        else:
            log.warning(
                "cycle_gap_monitor: Telegram returned False — heartbeat written, "
                "alert dedup state NOT updated"
            )
            alert_state = gap_state  # preserve existing alert dedup fields

        # HEARTBEAT: always write state after alert attempt (sent or not)
        heartbeat = _build_heartbeat_state(
            alert_state,
            gap_detected=True,
            hours_since=hours_since,
            alert_sent=sent,
            now_ts=now_ts,
        )
        _atomic_write_json(ddir / GAP_STATE_FILENAME, heartbeat)

    except Exception as exc:  # noqa: BLE001 — must never crash the caller
        log.warning("cycle_gap_monitor: unexpected error: %s", exc)

    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _cli_check(data_dir: Path) -> None:
    """Print gap status without sending alerts or writing any files."""
    now_dt = datetime.now(timezone.utc)
    last_cycle_ts = _get_last_cycle_ts(data_dir)
    gap_detected, hours_since = detect_gap(last_cycle_ts, now=now_dt)

    print(
        f"Cycle Gap Monitor — {now_dt.strftime('%Y-%m-%dT%H:%M:%S UTC')}"
    )
    print(f"  Last cycle ts  : {last_cycle_ts or 'NOT FOUND'}")
    if hours_since >= _UNKNOWN_HOURS:
        print("  Hours since    : unknown")
    else:
        print(f"  Hours since    : {hours_since:.1f}h")
    print(f"  Threshold      : {GAP_THRESHOLD_HOURS:.0f}h")
    print(
        f"  UTC hour check : {now_dt.hour:02d}:xx "
        f"(gap alerts enabled after {GAP_ALERT_AFTER_UTC_HOUR:02d}:00)"
    )
    print(f"  Gap detected   : {'YES ⚠️' if gap_detected else 'NO ✅'}")

    if gap_detected:
        gap_state = _read_json(data_dir / GAP_STATE_FILENAME, {})
        if not isinstance(gap_state, dict):
            gap_state = {}
        today = now_dt.strftime("%Y-%m-%d")
        already = not _should_send_alert(gap_state, today)
        print(f"  Already alerted today: {'YES' if already else 'NO'}")
        if not already:
            status = _read_json(data_dir / STATUS_FILENAME, {})
            if not isinstance(status, dict):
                status = {}
            paper_days = _compute_paper_days(status, now_dt)
            days_to_golive = _compute_days_to_golive(now_dt)
            msg = _format_alert_message(
                last_cycle_ts, hours_since, paper_days, days_to_golive
            )
            print()
            print("--- Message preview (dry-run — NOT sent) ---")
            plain = re.sub(r"<[^>]+>", "", msg)
            print(plain)
            print("--------------------------------------------")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cycle_gap_monitor",
        description="MP-144: Cycle Gap Monitor — detect missed daily cycles",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: print gap status without sending alerts or writing state",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (default: <repo>/data)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    ddir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    if args.check:
        _cli_check(ddir)
    else:
        result = run_cycle_gap_monitor(data_dir=ddir)
        if result["gap_detected"]:
            status_str = "ALERT SENT" if result["alert_sent"] else "gap detected (send failed/skipped)"
            print(
                f"⚠️  {status_str} — {result['hours_since']:.1f}h since last cycle"
            )
        else:
            print(f"✅ No gap — {result['hours_since']:.1f}h since last cycle")


if __name__ == "__main__":
    main()

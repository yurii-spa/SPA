"""
Daily Go-Live Readiness Check — wraps run_full_check() with:
  - Structured output to data/golive_readiness.json
  - Telegram alert when verdict changes between runs
  - next_check_date for scheduling
  - Explicit blocking_criteria list

Usage (standalone):
    cd spa_core
    python -m golive.daily_check

Called from export_data.py section 16 on every export cycle.

SPA-V365 -- the paper-trading checklist verdict now also gets a persistent
compact history log (``data/golive_readiness_history.json``) so the dashboard
can render a verdict / criteria-passed sparkline trend, mirroring the proven
operational-score history pattern from SPA-V363
(``readiness_score.append_history`` + ``renderReadinessTrend``). The history
append is a read-only consolidation of data already emitted each cycle, is
independently guarded and never breaks the main ``golive_readiness.json`` write.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.golive.daily_check")

# ── Locate data/ directory ────────────────────────────────────────────────────
# data/ is one level above spa_core/ in the repo root
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"

# ── Checklist-verdict history (SPA-V365) ──────────────────────────────────────
# Compact append-only log of the paper-trading checklist verdict over time so
# the dashboard can render a criteria-passed sparkline. MAX_HISTORY ~= 180 keeps
# roughly six months of cycles, matching readiness_score.MAX_HISTORY.
HISTORY_FILENAME = "golive_readiness_history.json"
MAX_HISTORY = 180


def append_checklist_history(payload: dict, data_dir: str | None = None) -> None:
    """Append a compact record of the checklist ``payload`` to the verdict-history
    log. Never raises.

    Mirrors ``readiness_score.append_history`` (SPA-V363). Reads the existing
    history (``<data_dir>/golive_readiness_history.json`` or
    ``_DEFAULT_DATA_DIR / HISTORY_FILENAME`` when ``data_dir`` is None), appends a
    small ``{checked_at, verdict, criteria_passed, criteria_total}`` record, dedups
    on ``checked_at`` (a same-timestamp re-run replaces the last record rather than
    duplicating it), trims to the last ``MAX_HISTORY`` records and writes it back.
    A missing or corrupt history file is treated as an empty list -- any failure is
    swallowed (logged at debug) so it can never break the main verdict write.
    """
    try:
        target = (
            Path(data_dir) / HISTORY_FILENAME
            if data_dir is not None
            else _DEFAULT_DATA_DIR / HISTORY_FILENAME
        )
        history: list[dict] = []
        if target.exists():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    history = loaded
            except Exception:  # noqa: BLE001 -- corrupt file -> start fresh
                history = []
        record = {
            "checked_at": payload.get("checked_at") or payload.get("generated_at"),
            "verdict": payload.get("verdict"),
            "criteria_passed": payload.get("criteria_passed"),
            "criteria_total": payload.get("criteria_total"),
        }
        if history and history[-1].get("checked_at") == record["checked_at"]:
            history[-1] = record
        else:
            history.append(record)
        history = history[-MAX_HISTORY:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("append_checklist_history failed: %s", exc)
        return


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_previous_verdict(data_dir: Path) -> str | None:
    """Read the verdict from the existing golive_readiness.json, if it exists."""
    try:
        path = data_dir / "golive_readiness.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("verdict")
    except Exception:
        return None


def _next_check_date() -> str:
    """Return tomorrow's UTC date as YYYY-MM-DD."""
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def _build_golive_payload(check_result: dict) -> dict:
    """
    Augment run_full_check() result with the structured fields required by
    daily_check:  criteria_passed, criteria_total, blocking_criteria, next_check_date.

    The returned dict is a superset of the run_full_check() dict — all original
    keys are preserved so the report_card still works unchanged.
    """
    criteria       = check_result.get("criteria", [])
    criteria_passed = sum(1 for c in criteria if c["status"] == "PASS")
    criteria_total  = len(criteria)

    # Blocking criteria = any FAIL or PENDING on performance criteria
    # (Wallet Ready PENDING is advisory — included but flagged separately)
    blocking = [
        c["name"]
        for c in criteria
        if c["status"] in ("FAIL", "PENDING")
    ]

    payload = dict(check_result)   # shallow copy — preserve all original keys
    payload.update({
        "criteria_passed":  criteria_passed,
        "criteria_total":   criteria_total,
        "blocking_criteria": blocking,
        "next_check_date":  _next_check_date(),
    })
    return payload


def _send_verdict_change_alert(
    previous_verdict: str | None,
    current_verdict:  str,
    payload:          dict,
    data_dir:         Path,
) -> bool:
    """
    Send a Telegram alert when the go-live verdict changes between runs.

    Returns True if a message was sent (or attempted), False otherwise.
    """
    if previous_verdict == current_verdict:
        return False  # no change — no alert needed

    try:
        import sys
        spa_core = str(Path(__file__).parent.parent)
        if spa_core not in sys.path:
            sys.path.insert(0, spa_core)
        from alerts.telegram_sender import TelegramSender

        tg = TelegramSender()
        if not tg.available:
            log.debug("Telegram not configured — skipping verdict-change alert")
            return False

        dr         = payload.get("days_remaining", "?")
        passed     = payload.get("criteria_passed", "?")
        total      = payload.get("criteria_total", "?")
        blocking   = payload.get("blocking_criteria", [])
        emoji_map  = {
            "READY":        "✅",
            "ALMOST_READY": "🟡",
            "NOT_READY":    "🔴",
            "BLOCKED":      "🚫",
        }
        prev_emoji = emoji_map.get(previous_verdict or "", "❓")
        curr_emoji = emoji_map.get(current_verdict, "❓")

        lines = [
            f"<b>🔔 Go-Live Verdict Changed</b>",
            f"{prev_emoji} {previous_verdict or 'UNKNOWN'} → {curr_emoji} {current_verdict}",
            f"",
            f"📊 Criteria: {passed}/{total} passing",
            f"📅 Days until target: {dr}",
        ]
        if blocking:
            lines += [
                f"",
                f"⛔ Blocking: {', '.join(blocking)}",
            ]
        if current_verdict == "READY":
            lines += ["", "🎉 All criteria met — owner review recommended!"]

        msg = "\n".join(lines)
        ok  = tg.send(msg)
        log.info(
            "Telegram verdict-change alert: %s → %s (sent=%s)",
            previous_verdict, current_verdict, ok,
        )
        return ok

    except Exception as exc:
        log.warning("Telegram alert failed (non-fatal): %s", exc)
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

def run_daily_golive_check(data_dir: str | None = None) -> dict:
    """
    Run the full go-live readiness check, persist the result, and fire a
    Telegram alert if the verdict has changed since the last run.

    Args:
        data_dir: Path to the data/ directory.  Defaults to the repo-level
                  data/ directory (../data relative to spa_core/).

    Returns:
        The full payload dict (superset of run_full_check() result) with:
          verdict, criteria_passed, criteria_total, days_remaining,
          blocking_criteria, next_check_date, and all run_full_check() keys.

    Never raises — all errors are logged and a degraded payload is returned.
    """
    import sys
    spa_core = str(Path(__file__).parent.parent)
    if spa_core not in sys.path:
        sys.path.insert(0, spa_core)

    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    data_path.mkdir(parents=True, exist_ok=True)

    # ── Load previous verdict for change detection ────────────────────────────
    previous_verdict = _load_previous_verdict(data_path)

    # ── Run full checklist ────────────────────────────────────────────────────
    try:
        from golive.checklist import run_full_check
        check_result = run_full_check(str(data_path))
    except Exception as exc:
        log.error("run_full_check() failed: %s", exc, exc_info=True)
        now = datetime.now(timezone.utc)
        check_result = {
            "generated_at":          now.isoformat(),
            "verdict":               "NOT_READY",
            "verdict_emoji":         "🔴",
            "days_remaining":        0,
            "go_live_date":          "2026-07-15",
            "paper_start_date":      "2026-06-10",  # FIX-P0: canonical real-track start
            "min_paper_days":        30,
            "summary":               f"Check failed: {exc}",
            "criteria":              [],
            "recommendation":        "Fix the checklist error and re-run.",
            "owner_action_required": True,
            "error":                 str(exc),
        }

    # ── Build structured payload ──────────────────────────────────────────────
    payload = _build_golive_payload(check_result)

    # ── Persist to golive_readiness.json ─────────────────────────────────────
    try:
        out_path = data_path / "golive_readiness.json"
        out_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        log.info(
            "golive_readiness.json written: verdict=%s %d/%d criteria",
            payload["verdict"], payload["criteria_passed"], payload["criteria_total"],
        )
    except Exception as exc:
        log.error("Failed to write golive_readiness.json: %s", exc)

    # ── Append compact checklist-verdict history (SPA-V365) ───────────────────
    # Independently guarded so a history failure can never break the (already
    # completed) main verdict write above, and never mutates the returned payload.
    try:
        append_checklist_history(payload, data_dir=str(data_path))
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("checklist history append failed: %s", exc)

    # ── Print report card to stdout ───────────────────────────────────────────
    try:
        from golive.report_card import generate_report_card
        print(generate_report_card(payload))
    except Exception as exc:
        log.warning("Report card generation failed (non-fatal): %s", exc)

    # ── Send Telegram alert on verdict change ─────────────────────────────────
    _send_verdict_change_alert(
        previous_verdict=previous_verdict,
        current_verdict=payload["verdict"],
        payload=payload,
        data_dir=data_path,
    )

    return payload


# ── Standalone entrypoint ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run daily go-live readiness check")
    parser.add_argument("--data-dir", default=None,
                        help="Path to data/ directory (default: auto-detect repo root)")
    args = parser.parse_args()

    result = run_daily_golive_check(args.data_dir)
    print(
        f"\nVerdict: {result['verdict_emoji']}  {result['verdict']}  "
        f"({result['criteria_passed']}/{result['criteria_total']} criteria)"
    )
    if result.get("blocking_criteria"):
        print(f"Blocking: {', '.join(result['blocking_criteria'])}")
    print(f"Days remaining: {result['days_remaining']}")
    print(f"Next check: {result['next_check_date']}")

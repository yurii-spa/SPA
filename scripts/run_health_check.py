#!/usr/bin/env python3
"""
scripts/run_health_check.py
============================
Daily health check runner for the SPA paper trading cycle.

Runs CycleHealthMonitor, saves report to data/cycle_health.json,
and optionally sends a Telegram alert when overall != HEALTHY.

Usage:
    python3 scripts/run_health_check.py           # full run + save + Telegram
    python3 scripts/run_health_check.py --test    # dry-run: no save, no Telegram
    python3 scripts/run_health_check.py --json    # print JSON report to stdout

Exit codes:
    0 — HEALTHY
    1 — WARNING or CRITICAL (or import failure)

Rules:
    - STDLIB ONLY — no external dependencies
    - SECRETS POLICY — no tokens written to this file or any artifact
    - LLM FORBIDDEN
    - Graceful ImportError → prints clear message, exits 1 (no traceback)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Telegram helpers (stdlib only, reads from macOS Keychain)
# ---------------------------------------------------------------------------

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_KEYCHAIN_TOKEN_KEY = "TELEGRAM_BOT_TOKEN_SPA"
_KEYCHAIN_CHAT_KEY = "TELEGRAM_CHAT_ID_SPA"


def _keychain_get(key: str) -> str | None:
    """
    Read a secret from macOS Keychain via the `security` CLI.
    Returns None if not found or on any error.
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", key, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _send_telegram(text: str) -> bool:
    """
    Send a Telegram message using credentials from macOS Keychain.
    Returns True on success, False on any error (non-fatal).
    Credentials are NEVER logged or stored.
    """
    token = _keychain_get(_KEYCHAIN_TOKEN_KEY)
    chat_id = _keychain_get(_KEYCHAIN_CHAT_KEY)

    if not token or not chat_id:
        print(
            "  [Telegram] credentials not found in Keychain "
            f"(keys: {_KEYCHAIN_TOKEN_KEY}, {_KEYCHAIN_CHAT_KEY}). "
            "Skipping alert.",
            file=sys.stderr,
        )
        return False

    url = _TELEGRAM_API.format(token=token)
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, OSError) as exc:
        print(f"  [Telegram] send failed: {exc}", file=sys.stderr)
        return False


def _build_alert_text(report: dict) -> str:
    """Build a concise Telegram alert from a health report."""
    overall = report.get("overall", "UNKNOWN")
    checked_at = report.get("checked_at", "")
    emoji_map = {"HEALTHY": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}
    emoji = emoji_map.get(overall, "❓")

    lines = [
        f"{emoji} *SPA Health: {overall}*",
        f"_{checked_at}_",
        "",
    ]

    status_emoji = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨", "STALE": "⚠️"}
    for check_name, check_result in report.get("checks", {}).items():
        status = check_result.get("status", "?")
        s_e = status_emoji.get(status, "❓")
        detail = check_result.get("detail", "")
        detail_str = f" — {detail}" if detail else ""
        lines.append(f"{s_e} `{check_name}`: {status}{detail_str}")

    recs = report.get("recommendations", [])
    if recs:
        lines.append("")
        lines.append("*Recommendations:*")
        for rec in recs[:5]:  # cap at 5 to stay under Telegram 4096 char limit
            lines.append(f"• {rec}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_equity_history(data_dir: str = "data") -> list:
    """
    Load equity_history.json.
    Returns [] if file is missing or malformed (CycleHealthMonitor handles this).
    """
    path = ROOT / data_dir / "equity_history.json"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def run_health_check(data_dir: str = "data", send_telegram: bool = True) -> dict:
    """
    1. Import CycleHealthMonitor (with graceful ImportError handling).
    2. Run all checks via monitor.run_all_checks().
    3. Save report to data/cycle_health.json (atomic write).
    4. If overall != HEALTHY and send_telegram → send Telegram alert.
    5. Return the report dict.
    """
    # --- Import CycleHealthMonitor -------------------------------------------
    try:
        from spa_core.monitoring.cycle_health_monitor import CycleHealthMonitor
    except ImportError as exc:
        print(
            f"\n[run_health_check] ERROR: Cannot import CycleHealthMonitor.\n"
            f"  Cause: {exc}\n"
            f"  Make sure spa_core/monitoring/cycle_health_monitor.py exists\n"
            f"  and the project root is correct: {ROOT}\n",
            file=sys.stderr,
        )
        sys.exit(1)

    data_dir_abs = str(ROOT / data_dir)

    # --- Run checks ----------------------------------------------------------
    monitor = CycleHealthMonitor()
    try:
        report = monitor.run_all_checks(data_dir=data_dir_abs)
    except Exception as exc:  # pragma: no cover — fail-safe
        print(
            f"[run_health_check] Unexpected error in run_all_checks: {exc}",
            file=sys.stderr,
        )
        # Return a minimal CRITICAL report so callers can handle it
        report = {
            "overall": "CRITICAL",
            "checks": {},
            "checked_at": datetime.now(tz=timezone.utc).isoformat(),
            "recommendations": [f"run_all_checks raised: {exc}"],
        }

    # --- Save report ---------------------------------------------------------
    try:
        monitor.save_health_report(report, data_dir=data_dir_abs)
    except OSError as exc:
        print(
            f"[run_health_check] WARNING: Could not save cycle_health.json: {exc}",
            file=sys.stderr,
        )

    # --- Telegram alert ------------------------------------------------------
    overall = report.get("overall", "UNKNOWN")
    if overall != "HEALTHY" and send_telegram:
        alert_text = _build_alert_text(report)
        ok = _send_telegram(alert_text)
        if ok:
            print("  [Telegram] health alert sent.", file=sys.stderr)

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="SPA daily cycle health check runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit code 0 = HEALTHY, 1 = WARNING/CRITICAL.\n"
            "Credentials are read from macOS Keychain; never stored in files."
        ),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Dry-run: no save to disk, no Telegram alert.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print full JSON report to stdout (suppresses human-readable output).",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="DIR",
        help="Path to data directory relative to project root (default: data).",
    )
    args = parser.parse_args()

    # In --test mode we still compute the report but skip save & Telegram
    if args.test:
        # Override save: monkey-patch to no-op for dry-run
        try:
            from spa_core.monitoring.cycle_health_monitor import CycleHealthMonitor
        except ImportError as exc:
            print(
                f"\n[run_health_check] ERROR: Cannot import CycleHealthMonitor.\n"
                f"  Cause: {exc}\n"
                f"  Ensure spa_core/monitoring/cycle_health_monitor.py exists.\n",
                file=sys.stderr,
            )
            return 1

        data_dir_abs = str(ROOT / args.data_dir)
        monitor = CycleHealthMonitor()
        try:
            report = monitor.run_all_checks(data_dir=data_dir_abs)
        except Exception as exc:  # pragma: no cover
            print(f"[run_health_check] run_all_checks error: {exc}", file=sys.stderr)
            report = {
                "overall": "CRITICAL",
                "checks": {},
                "checked_at": datetime.now(tz=timezone.utc).isoformat(),
                "recommendations": [f"run_all_checks raised: {exc}"],
            }
        # No save, no Telegram

    else:
        report = run_health_check(
            data_dir=args.data_dir,
            send_telegram=True,
        )

    # ---- Output -------------------------------------------------------------
    if args.json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        overall = report.get("overall", "UNKNOWN")
        emoji_map = {"HEALTHY": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}
        emoji = emoji_map.get(overall, "❓")
        checked_at = report.get("checked_at", "")
        print(f"\n{emoji} Health: {overall}  [{checked_at}]")

        status_emoji = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨", "STALE": "⚠️"}
        for check_name, check_result in report.get("checks", {}).items():
            status = check_result.get("status", "?")
            s_e = status_emoji.get(status, "❓")
            detail = check_result.get("detail", "")
            detail_str = f" — {detail}" if detail else ""
            # Extra context for cycle_gap
            hours = check_result.get("hours_since")
            hours_str = f" (age={hours:.2f}h)" if hours is not None else ""
            print(f"  {s_e} {check_name}: {status}{hours_str}{detail_str}")

        recs = report.get("recommendations", [])
        if recs:
            print("\nRecommendations:")
            for rec in recs:
                print(f"  • {rec}")

        if args.test:
            print("\n  [--test] Dry-run: report not saved, Telegram not sent.")
        else:
            data_out = ROOT / args.data_dir / "cycle_health.json"
            print(f"\n  → Saved: {data_out}")

        print()

    return 0 if report.get("overall") == "HEALTHY" else 1


if __name__ == "__main__":
    sys.exit(main())

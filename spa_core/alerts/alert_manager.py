"""MP-016: formatted Telegram alerts for the daily paper-trading cycle.

Thin formatting layer over ``telegram_client.send_message``. Every public
function is fail-safe: any exception (bad input, missing credentials,
network) is logged as WARNING and the function returns ``False`` — alerts
must never crash the cycle.
"""
from __future__ import annotations

import logging

from spa_core.alerts import telegram_client

log = logging.getLogger("spa.alerts.alert_manager")


def _send(name: str, text: str) -> bool:
    try:
        return telegram_client.send_message(text)
    except Exception as exc:  # noqa: BLE001 — alerts must never crash the cycle
        log.warning("%s failed (%s) — alert skipped", name, exc)
        return False


def send_daily_summary(report: dict) -> bool:
    """Daily one-liner: date, equity, daily P&L %, go-live status.

    ``report`` is the ``data/daily_report_{date}.json`` document
    (``spa_core/reporting/daily_report.py``).
    """
    try:
        date = report.get("date", "?")
        equity = float(report.get("equity_usd", 0.0) or 0.0)
        pnl_pct = float(report.get("daily_pnl_pct", 0.0) or 0.0)
        sign = "+" if pnl_pct >= 0 else ""
        golive_status = report.get("golive_status", "?")
        text = (
            f"📊 *SPA Daily* {date}\n"
            f"Equity: ${equity:,.0f}\n"
            f"P&L: {sign}{pnl_pct:.2f}%\n"
            f"Status: {golive_status}"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_daily_summary failed (%s) — alert skipped", exc)
        return False
    return _send("send_daily_summary", text)


def send_red_flag(flags: list[str]) -> bool:
    """Red-flag digest — one bullet per flag string."""
    try:
        text = "🚨 *SPA Red Flags*\n" + "\n".join(f"• {f}" for f in flags)
    except Exception as exc:  # noqa: BLE001
        log.warning("send_red_flag failed (%s) — alert skipped", exc)
        return False
    return _send("send_red_flag", text)


def send_gap_alert(hours_since_last: float) -> bool:
    """Track-continuity alert: the last cycle ran too long ago."""
    try:
        text = (
            "⏰ *SPA Gap Detected*\n"
            f"Последний цикл: {float(hours_since_last):.1f}ч назад"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_gap_alert failed (%s) — alert skipped", exc)
        return False
    return _send("send_gap_alert", text)


def send_golive_change(old_status: str, new_status: str) -> bool:
    """Go-live status transition (e.g. NOT READY → READY)."""
    try:
        text = (
            "🟢 *SPA Go-Live*\n"
            f"Статус изменился: {old_status} → {new_status}"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_golive_change failed (%s) — alert skipped", exc)
        return False
    return _send("send_golive_change", text)


def send_startup_test() -> bool:
    """One-off connectivity check after wiring up the bot."""
    return _send(
        "send_startup_test",
        "✅ *SPA Telegram подключён*\nАлерты работают.",
    )

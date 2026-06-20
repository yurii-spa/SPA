"""MP-016 / MP-016b / MP-136: formatted Telegram alerts for the SPA cycle.

Thin formatting layer over ``telegram_client``. Every public function is
fail-safe: any exception (bad input, missing credentials, network) is logged
as WARNING and the function returns ``False`` — alerts must never crash the
daily cycle.

MP-016b additions:
  * ``send_daily_summary`` — enriched with period returns (today/week/month/year/
    all-time) and inline keyboard buttons.
  * ``send_weekly_report``  — Monday summary with keyboard.
  * ``send_monthly_report`` — 1st-of-month summary with keyboard.
  * ``send_startup_test``   — connectivity check + keyboard.

MP-136 addition:
  * ``send_red_flag`` — now accepts ``list[dict]`` (raw alert dicts from
    ``data/red_flags.json``) and uses the Russian-language formatter
    ``telegram_format_ru.format_message_ru``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from spa_core.utils.atomic import atomic_save
from spa_core.alerts import telegram_client
from spa_core.alerts.telegram_format_ru import (
    build_detail_keyboard,
    format_message_ru,
)

log = logging.getLogger("spa.alerts.alert_manager")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO_ROOT / "data"
_ALERT_STATE_FILE = _DATA_DIR / "telegram_alert_state.json"


# ─── Deduplication helpers ────────────────────────────────────────────────────

def _load_alert_state() -> dict:
    """Read the alert-state file (last-sent dates). Returns {} on any error."""
    try:
        if _ALERT_STATE_FILE.exists():
            return json.loads(_ALERT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("alert_state unreadable (%s) — treating as empty", exc)
    return {}


def _save_alert_state(state: dict) -> None:
    """Atomically write the alert-state file. Silent on failure."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        atomic_save(state, str(_ALERT_STATE_FILE))
    except Exception as exc:  # noqa: BLE001
        log.warning("alert_state write failed (%s) — dedup state not persisted", exc)


def _already_sent_today(key: str) -> bool:
    """Return True if ``key`` alert was already sent today (UTC date)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    state = _load_alert_state()
    return state.get(key) == today


def _mark_sent_today(key: str) -> None:
    """Record that ``key`` alert was sent today (UTC date)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    state = _load_alert_state()
    state[key] = today
    _save_alert_state(state)

# Standard SPA inline keyboard — attached to every outbound message.
_KEYBOARD: dict = {
    "inline_keyboard": [
        [
            {"text": "📊 Сейчас", "callback_data": "cmd_now"},
            {"text": "📅 Неделя", "callback_data": "cmd_week"},
        ],
        [
            {"text": "📆 Месяц", "callback_data": "cmd_month"},
            {"text": "🗓 Год", "callback_data": "cmd_year"},
        ],
        [{"text": "🔍 Статус системы", "callback_data": "cmd_status"}],
    ]
}


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _send(name: str, text: str, *, keyboard=True) -> bool:
    """Send a Telegram message.

    ``keyboard=True``  → attach the standard SPA inline keyboard (_KEYBOARD).
    ``keyboard=<dict>``→ attach the given custom inline keyboard dict.
    ``keyboard=False`` → plain message, no keyboard.
    """
    try:
        if keyboard is True:
            return telegram_client.send_message_with_keyboard(text, _KEYBOARD)
        if isinstance(keyboard, dict):
            return telegram_client.send_message_with_keyboard(text, keyboard)
        return telegram_client.send_message(text)
    except Exception as exc:  # noqa: BLE001 — alerts must never crash the cycle
        log.warning("%s failed (%s) — alert skipped", name, exc)
        return False


def _read_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("_read_json %s unreadable (%s) — using default", path.name, exc)
        return default


def _calc_period_returns(daily: list) -> dict:
    """Calculate period returns from the equity curve daily bars.

    Identical logic to ``bot_commands.calculate_period_returns``; duplicated
    here to avoid a circular import between the two modules.
    """
    zero: dict = {
        "today_pct": 0.0, "week_pct": 0.0, "month_pct": 0.0,
        "year_pct": 0.0, "alltime_pct": 0.0,
    }
    if not daily:
        return zero

    def _eq(bar: dict) -> float:
        return float(bar.get("equity") or bar.get("close_equity") or 0.0)

    curve = sorted(
        [b for b in daily if isinstance(b, dict)],
        key=lambda b: b.get("date", ""),
    )
    if not curve:
        return zero

    now_eq = _eq(curve[-1])
    first_eq = _eq(curve[0])
    last_date_str = curve[-1].get("date", "")
    today_pct = float(curve[-1].get("daily_return_pct", 0.0))

    def _n_ago(n: int) -> float | None:
        if not last_date_str:
            return None
        try:
            cutoff = (
                datetime.strptime(last_date_str, "%Y-%m-%d") - timedelta(days=n)
            ).strftime("%Y-%m-%d")
        except ValueError:
            return None
        for bar in reversed(curve[:-1]):
            if bar.get("date", "") <= cutoff:
                return _eq(bar)
        return None

    eq_7 = _n_ago(7)
    eq_30 = _n_ago(30)
    eq_365 = _n_ago(365)

    return {
        "today_pct": round(today_pct, 4),
        "week_pct": round((now_eq / eq_7 - 1.0) * 100.0, 4) if eq_7 else 0.0,
        "month_pct": round((now_eq / eq_30 - 1.0) * 100.0, 4) if eq_30 else 0.0,
        "year_pct": round((now_eq / eq_365 - 1.0) * 100.0, 4) if eq_365 else 0.0,
        "alltime_pct": round((now_eq / first_eq - 1.0) * 100.0, 4) if first_eq else 0.0,
    }


def _top_protocols(positions: dict, capital_usd: float, n: int = 3) -> list[str]:
    """Return top-N protocol bullet strings like '• Aave V3 55% @ 3.14%'."""
    sorted_pos = sorted(
        ((p, float(v)) for p, v in positions.items()), key=lambda kv: -kv[1]
    )[:n]
    lines = []
    for proto, usd in sorted_pos:
        pct = usd / capital_usd * 100.0 if capital_usd else 0.0
        lines.append(f"• {proto.replace('_', ' ').title()} {pct:.0f}%")
    return lines


def _golive_emoji(n_pass: int, ready: bool) -> str:
    return "🟢" if ready else "🟡" if n_pass >= 4 else "🔴"


# ─── Public API ───────────────────────────────────────────────────────────────


def send_daily_summary(report: dict) -> bool:
    """Daily summary: equity + period returns + top protocols + go-live status.

    ``report`` is the ``data/daily_report_{date}.json`` document.
    Attaches inline keyboard buttons.

    Dedup: sends at most once per calendar day (UTC). If the cycle runs every
    30 min, only the first call each day goes through — the rest are skipped.
    """
    if _already_sent_today("daily_summary"):
        log.debug("send_daily_summary: already sent today — skipping")
        return False
    try:
        date = str(report.get("date", "?"))
        equity = float(report.get("equity_usd", 0.0) or 0.0)
        golive_status = str(report.get("golive_status", "?"))
        sharpe = float(report.get("sharpe_ratio", 0.0) or 0.0)
        drawdown = float(report.get("max_drawdown_pct", 0.0) or 0.0)
        vol = float(report.get("daily_volatility_pct", 0.0) or 0.0)

        # Period returns from equity curve
        eq_doc = _read_json(_DATA_DIR / "equity_curve_daily.json", {})
        daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []
        rets = _calc_period_returns(daily)

        # Positions
        pos_doc = _read_json(_DATA_DIR / "current_positions.json", {})
        positions = pos_doc.get("positions", {}) if isinstance(pos_doc, dict) else {}
        capital = float(pos_doc.get("capital_usd", 100_000.0) or 100_000.0)
        cash_usd = float(pos_doc.get("cash_usd", 0.0) or 0.0)
        cash_pct = cash_usd / capital * 100.0 if capital else 0.0
        top_lines = _top_protocols(positions, capital)
        if not top_lines:
            top_lines = ["• Нет позиций"]
        top_lines.append(f"• Cash {cash_pct:.0f}%")

        # Go-live
        golive = _read_json(_DATA_DIR / "golive_status.json", {})
        checks = golive.get("checks", {}) if isinstance(golive, dict) else {}
        n_pass = sum(1 for v in checks.values() if v)
        ready = bool(golive.get("ready", False)) if isinstance(golive, dict) else False
        gl_emoji = _golive_emoji(n_pass, ready)
        gl_label = "READY" if ready else f"PRE-LIVE {n_pass}/6"

        def _s(v: float) -> str:
            return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"

        protos_text = "\n".join(top_lines)

        text = (
            f"📊 *SPA Daily — {date}*\n"
            f"\n"
            f"💰 *Equity:* ${equity:,.0f}\n"
            f"\n"
            f"📈 *Доходность:*\n"
            f"• Сегодня: {_s(rets['today_pct'])}\n"
            f"• За неделю: {_s(rets['week_pct'])}\n"
            f"• За месяц: {_s(rets['month_pct'])}\n"
            f"• За год: {_s(rets['year_pct'])}\n"
            f"• За всё время: {_s(rets['alltime_pct'])}\n"
            f"\n"
            f"🏦 *Топ протоколы:*\n"
            f"{protos_text}\n"
            f"\n"
            f"📐 Sharpe {sharpe:.2f} | DD {drawdown:.2f}% | Vol {vol:.1f}%\n"
            f"{gl_emoji} *Go-Live:* {gl_label}"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_daily_summary format failed (%s) — alert skipped", exc)
        return False
    result = _send("send_daily_summary", text)
    if result:
        _mark_sent_today("daily_summary")
    return result


def send_weekly_report() -> bool:
    """Weekly summary (sent on Mondays). Includes 7-day equity bridge + keyboard.

    Dedup: sends at most once per calendar day.
    """
    if _already_sent_today("weekly_report"):
        log.debug("send_weekly_report: already sent today — skipping")
        return False
    try:
        eq_doc = _read_json(_DATA_DIR / "equity_curve_daily.json", {})
        daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []
        rets = _calc_period_returns(daily)

        equity_now = 0.0
        eq_7d = 0.0
        last_date = "?"
        if daily:
            last_bar = sorted(daily, key=lambda b: b.get("date", ""))[-1]
            equity_now = float(last_bar.get("equity") or last_bar.get("close_equity") or 0.0)
            last_date = last_bar.get("date", "?")
            eq_7d = rets.get("equity_7d_ago") or equity_now

        try:
            last_dt = datetime.strptime(last_date, "%Y-%m-%d")
            date_from = (last_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        except Exception:
            date_from = "?"

        week_sign = "+" if rets["week_pct"] >= 0 else ""
        text = (
            f"📅 *SPA Weekly — {date_from} → {last_date}*\n"
            f"\n"
            f"💰 Equity: ${eq_7d:,.0f} → ${equity_now:,.0f}\n"
            f"📈 Доходность за неделю: {week_sign}{rets['week_pct']:.2f}%\n"
            f"📊 За всё время: {'+' if rets['alltime_pct'] >= 0 else ''}{rets['alltime_pct']:.2f}%"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_weekly_report format failed (%s) — alert skipped", exc)
        return False
    result = _send("send_weekly_report", text)
    if result:
        _mark_sent_today("weekly_report")
    return result


def send_monthly_report() -> bool:
    """Monthly summary (sent on the 1st of each month). Includes 30-day returns + keyboard.

    Dedup: sends at most once per calendar day.
    """
    if _already_sent_today("monthly_report"):
        log.debug("send_monthly_report: already sent today — skipping")
        return False
    try:
        import calendar as _cal

        eq_doc = _read_json(_DATA_DIR / "equity_curve_daily.json", {})
        daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []
        rets = _calc_period_returns(daily)

        equity_now = 0.0
        eq_30d = 0.0
        last_date = "?"
        month_name = "?"
        if daily:
            last_bar = sorted(daily, key=lambda b: b.get("date", ""))[-1]
            equity_now = float(last_bar.get("equity") or last_bar.get("close_equity") or 0.0)
            last_date = last_bar.get("date", "?")
            eq_30d = rets.get("equity_30d_ago") or equity_now
            try:
                dt = datetime.strptime(last_date, "%Y-%m-%d")
                month_name = _cal.month_name[dt.month]
            except Exception:
                month_name = last_date[:7]

        month_sign = "+" if rets["month_pct"] >= 0 else ""
        text = (
            f"📆 *SPA Monthly — {month_name}*\n"
            f"\n"
            f"💰 Equity: ${eq_30d:,.0f} → ${equity_now:,.0f}\n"
            f"📈 Доходность за месяц: {month_sign}{rets['month_pct']:.2f}%\n"
            f"📊 За всё время: {'+' if rets['alltime_pct'] >= 0 else ''}{rets['alltime_pct']:.2f}%"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_monthly_report format failed (%s) — alert skipped", exc)
        return False
    result = _send("send_monthly_report", text)
    if result:
        _mark_sent_today("monthly_report")
    return result


def send_red_flag(flags: list) -> bool:
    """Red-flag digest — Russian-language formatting with "📋 Подробнее" buttons.

    ``flags`` should be a ``list[dict]`` of raw alert records from
    ``data/red_flags.json`` (keys: severity, protocol, category, message,
    evidence).  Legacy ``list[str]`` is still accepted as a fallback.

    Attaches an inline keyboard with "📋 Подробнее" buttons for CRITICAL/WARN
    alerts so the user can request detailed analysis per event.

    Dedup: sends at most once per calendar day (UTC).
    BUG FIX (TELEGRAM_AUDIT 2026-06-18): was missing dedup — fired every
    cycle_runner run (every 30 min) whenever red_flags.json was non-empty.
    """
    if _already_sent_today("red_flag"):
        log.debug("send_red_flag: already sent today — skipping")
        return False
    try:
        text = format_message_ru(flags)
        dict_flags = [f for f in flags if isinstance(f, dict)]
        kb = build_detail_keyboard(dict_flags) if dict_flags else None
    except Exception as exc:  # noqa: BLE001
        log.warning("send_red_flag failed (%s) — alert skipped", exc)
        return False
    result = _send("send_red_flag", text, keyboard=kb or False)
    if result:
        _mark_sent_today("red_flag")
    return result


def send_gap_alert(hours_since_last: float) -> bool:
    """Track-continuity alert: the last cycle ran too long ago. No keyboard.

    Dedup: sends at most once per calendar day (UTC).
    BUG FIX (TELEGRAM_AUDIT 2026-06-18): was missing dedup — fired every
    cycle_runner run (every 30 min when StartInterval was 1800) whenever
    gap_monitor.json had gap_detected=true.
    """
    if _already_sent_today("gap_alert"):
        log.debug("send_gap_alert: already sent today — skipping")
        return False
    try:
        text = (
            "⏰ *SPA Gap Detected*\n"
            f"Последний цикл: {float(hours_since_last):.1f}ч назад"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_gap_alert failed (%s) — alert skipped", exc)
        return False
    result = _send("send_gap_alert", text, keyboard=False)
    if result:
        _mark_sent_today("gap_alert")
    return result


def send_golive_change(old_status: str, new_status: str) -> bool:
    """Go-live status transition (e.g. NOT READY → READY). No keyboard."""
    try:
        text = (
            "🟢 *SPA Go-Live*\n"
            f"Статус изменился: {old_status} → {new_status}"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_golive_change failed (%s) — alert skipped", exc)
        return False
    return _send("send_golive_change", text, keyboard=False)


def send_startup_test() -> bool:
    """One-off connectivity check — immediately shows the inline keyboard."""
    text = (
        "✅ *SPA Telegram подключён*\n"
        "Алерты работают. Используй кнопки для просмотра статистики:"
    )
    return _send("send_startup_test", text, keyboard=True)

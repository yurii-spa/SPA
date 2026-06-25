#!/usr/bin/env python3
"""MP-016b / MP-136: Telegram bot polling handler with inline keyboard.

Reads updates from Telegram getUpdates API and handles:
  * message  (/start or any text) → welcome text + inline keyboard
  * callback_query (button press) → answerCallbackQuery + action + keyboard

Callback handlers:
  cmd_now, cmd_week, cmd_month, cmd_year, cmd_status — period stats/status.
  detail_{protocol}__{category} — MP-136: detailed analysis for one red flag.

Runs every 5 minutes via launchd (com.spa.bot_commands).

Secrets policy: credentials are NEVER stored in files — read at runtime
from macOS Keychain via ``security find-generic-password``.
Stdlib only. Atomic writes (tmp + os.replace).
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.alerts.telegram_format_ru import (
    format_alert_detail_ru,
    parse_detail_callback,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.alerts.bot_commands")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _REPO_ROOT / "data"
OFFSET_FILE = DATA_DIR / "tg_update_offset.json"

HTTP_TIMEOUT_S = 10
KEYCHAIN_ACCOUNT = "spa"
TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"

INLINE_KEYBOARD: dict = {
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


# ─── Keychain helpers ─────────────────────────────────────────────────────────


def _read_keychain(service: str) -> str:
    """Read one generic password from macOS Keychain. Raises EnvironmentError."""
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s", service,
                "-a", KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=HTTP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentError(f"Keychain read failed for {service}") from exc
    value = (proc.stdout or "").strip()
    if proc.returncode != 0 or not value:
        raise EnvironmentError(f"Keychain entry not found: {service}")
    return value


def _get_token() -> str:
    return _read_keychain(TOKEN_SERVICE)


def _get_chat_id() -> str:
    return _read_keychain(CHAT_ID_SERVICE)


# ─── Atomic IO ────────────────────────────────────────────────────────────────


def _read_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("_read_json %s unreadable (%s)", path.name, exc)
        return default


def _atomic_write_json(path: Path, obj) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _api_post(token: str, method: str, payload: dict) -> dict:
    """POST to Telegram Bot API. Returns parsed JSON. Raises on network/HTTP error.

    FLOOD GUARD: chat-bound ``sendMessage`` calls are routed through the canonical
    shared cross-process rate limit (spa_core.alerts.telegram_client._rate_limit_ok)
    so this legacy callback bot can never flood the chat (e.g. a runaway /start or
    callback loop). Control calls (getUpdates/answerCallbackQuery) are not limited.
    Excess sends are DROPPED + logged; the caller sees an ``{"ok": False}`` stub
    instead of an exception (matches the fail-safe contract of the call sites).
    """
    if method == "sendMessage":
        try:
            from spa_core.alerts.telegram_client import _rate_limit_ok
            if not _rate_limit_ok(str(payload.get("text", ""))):
                log.warning("bot_commands send dropped by flood guard. preview=%r",
                            str(payload.get("text", ""))[:80])
                return {"ok": False, "dropped_by_flood_guard": True}
        except Exception:
            pass  # guard import/error must never block a legitimate send (fail-open)
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_get(token: str, method: str, params: dict) -> dict:
    """GET from Telegram Bot API. Returns parsed JSON. Raises on error."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.telegram.org/bot{token}/{method}?{qs}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S + 5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send_with_keyboard(token: str, chat_id: str, text: str) -> bool:
    """Send a message with the standard SPA inline keyboard. Fail-safe."""
    try:
        _api_post(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
                "reply_markup": json.dumps(INLINE_KEYBOARD),
            },
        )
        return True
    except Exception as exc:
        log.warning("_send_with_keyboard failed: %s", exc)
        return False


def _answer_callback_query(token: str, callback_query_id: str) -> bool:
    """ACK a button press so Telegram stops the spinner. Fail-safe."""
    try:
        _api_post(token, "answerCallbackQuery", {"callback_query_id": callback_query_id})
        return True
    except Exception as exc:
        log.warning("answerCallbackQuery failed: %s", exc)
        return False


# ─── Period returns calculation ───────────────────────────────────────────────


def calculate_period_returns(equity_curve: list) -> dict:
    """Calculate period returns from the equity curve.

    Parameters
    ----------
    equity_curve:
        List of dicts, each with keys ``date`` ("YYYY-MM-DD") and
        ``equity`` or ``close_equity`` (float). Order does not matter —
        the function sorts by date.

    Returns
    -------
    dict with keys:
        today_pct, week_pct, month_pct, year_pct, alltime_pct,
        best_day_7d, best_day_7d_date,
        profitable_7d (int), profitable_30d (int),
        equity_7d_ago, equity_30d_ago, equity_yr_ago
    All float fields default to 0.0 when the period has no data.
    """
    zero: dict = {
        "today_pct": 0.0,
        "week_pct": 0.0,
        "month_pct": 0.0,
        "year_pct": 0.0,
        "alltime_pct": 0.0,
        "best_day_7d": 0.0,
        "best_day_7d_date": None,
        "profitable_7d": 0,
        "profitable_30d": 0,
        "equity_7d_ago": 0.0,
        "equity_30d_ago": 0.0,
        "equity_yr_ago": 0.0,
    }
    if not equity_curve:
        return zero

    def _eq(bar: dict) -> float:
        return float(bar.get("equity") or bar.get("close_equity") or 0.0)

    curve = sorted(
        [b for b in equity_curve if isinstance(b, dict)],
        key=lambda b: b.get("date", ""),
    )
    if not curve:
        return zero

    now_equity = _eq(curve[-1])
    first_equity = _eq(curve[0])
    last_date_str = curve[-1].get("date", "")

    try:
        last_dt = datetime.strptime(last_date_str, "%Y-%m-%d")
    except ValueError:
        last_dt = None

    # ─── helper: closest equity on or before (last_dt - N days) ───
    def _equity_n_ago(n: int) -> float | None:
        if last_dt is None:
            return None
        cutoff = (last_dt - timedelta(days=n)).strftime("%Y-%m-%d")
        for bar in reversed(curve[:-1]):
            if bar.get("date", "") <= cutoff:
                return _eq(bar)
        return None

    today_pct = float(curve[-1].get("daily_return_pct", 0.0))

    eq_7d = _equity_n_ago(7)
    week_pct = ((now_equity / eq_7d - 1.0) * 100.0) if eq_7d else 0.0

    eq_30d = _equity_n_ago(30)
    month_pct = ((now_equity / eq_30d - 1.0) * 100.0) if eq_30d else 0.0

    eq_yr = _equity_n_ago(365)
    year_pct = ((now_equity / eq_yr - 1.0) * 100.0) if eq_yr else 0.0

    alltime_pct = ((now_equity / first_equity - 1.0) * 100.0) if first_equity else 0.0

    # ─── recent windows ──────────────────────────────────────────────
    if last_dt is not None:
        cutoff_7d = (last_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        cutoff_30d = (last_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    else:
        cutoff_7d = cutoff_30d = ""

    recent_7d = [b for b in curve if b.get("date", "") > cutoff_7d]
    recent_30d = [b for b in curve if b.get("date", "") > cutoff_30d]

    profitable_7d = sum(
        1 for b in recent_7d if float(b.get("daily_return_pct", 0.0)) > 0
    )
    profitable_30d = sum(
        1 for b in recent_30d if float(b.get("daily_return_pct", 0.0)) > 0
    )

    best_7d_bar = max(
        recent_7d,
        key=lambda b: float(b.get("daily_return_pct", 0.0)),
        default=None,
    )
    best_day_7d = float(best_7d_bar.get("daily_return_pct", 0.0)) if best_7d_bar else 0.0
    best_day_7d_date = best_7d_bar.get("date") if best_7d_bar else None

    return {
        "today_pct": round(today_pct, 4),
        "week_pct": round(week_pct, 4),
        "month_pct": round(month_pct, 4),
        "year_pct": round(year_pct, 4),
        "alltime_pct": round(alltime_pct, 4),
        "best_day_7d": round(best_day_7d, 4),
        "best_day_7d_date": best_day_7d_date,
        "profitable_7d": profitable_7d,
        "profitable_30d": profitable_30d,
        "equity_7d_ago": round(eq_7d, 2) if eq_7d else 0.0,
        "equity_30d_ago": round(eq_30d, 2) if eq_30d else 0.0,
        "equity_yr_ago": round(eq_yr, 2) if eq_yr else 0.0,
    }


# ─── Command text generators ──────────────────────────────────────────────────


def _cmd_now_text() -> str:
    """📊 Сейчас — live snapshot."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    status = _read_json(DATA_DIR / "paper_trading_status.json", {})
    equity = float(status.get("current_equity", 0.0) or 0.0)
    last_cycle = str(status.get("last_cycle_ts", "?") or "?")
    if last_cycle != "?":
        try:
            last_cycle = last_cycle[:16].replace("T", " ")
        except Exception:
            pass

    eq_doc = _read_json(DATA_DIR / "equity_curve_daily.json", {})
    daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []
    today_pct = float(daily[-1].get("daily_return_pct", 0.0)) if daily else 0.0

    pos_doc = _read_json(DATA_DIR / "current_positions.json", {})
    positions: dict = pos_doc.get("positions", {}) if isinstance(pos_doc, dict) else {}
    capital = float(pos_doc.get("capital_usd", 100_000.0) or 100_000.0)

    sorted_pos = sorted(
        ((p, float(v)) for p, v in positions.items()), key=lambda kv: -kv[1]
    )[:3]
    top_lines = []
    for proto, usd in sorted_pos:
        pct = usd / capital * 100.0 if capital else 0.0
        top_lines.append(f"• {proto.replace('_', ' ').title()} {pct:.0f}%")
    if not top_lines:
        top_lines.append("• Нет позиций")

    sign = "+" if today_pct >= 0 else ""
    return "\n".join(
        [
            f"📊 *Snapshot — {now_str}*",
            f"Equity: ${equity:,.0f}",
            f"P&L сегодня: {sign}{today_pct:.2f}%",
            "",
            "*Топ протоколы:*",
        ]
        + top_lines
        + [
            "",
            f"Последний цикл: {last_cycle}",
        ]
    )


def _cmd_week_text() -> str:
    """📅 Неделя — 7-day stats."""
    eq_doc = _read_json(DATA_DIR / "equity_curve_daily.json", {})
    daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []

    if not daily:
        return "📅 *Неделя*\nДанных пока недостаточно."

    stats = calculate_period_returns(daily)
    last_date = daily[-1].get("date", "?")
    equity_now = float(daily[-1].get("equity") or daily[-1].get("close_equity") or 0.0)
    eq_7d = stats["equity_7d_ago"]

    try:
        last_dt = datetime.strptime(last_date, "%Y-%m-%d")
        date_from = (last_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    except Exception:
        date_from = "?"

    week_sign = "+" if stats["week_pct"] >= 0 else ""
    best_sign = "+" if stats["best_day_7d"] >= 0 else ""
    eq_from = eq_7d if eq_7d else equity_now

    return "\n".join(
        [
            f"📅 *Неделя — {date_from} → {last_date}*",
            f"Equity: ${eq_from:,.0f} → ${equity_now:,.0f}",
            f"Доходность: {week_sign}{stats['week_pct']:.2f}%",
            f"Лучший день: {stats['best_day_7d_date'] or '—'} ({best_sign}{stats['best_day_7d']:.2f}%)",
            f"Прибыльных дней: {stats['profitable_7d']}/7",
        ]
    )


def _cmd_month_text() -> str:
    """📆 Месяц — 30-day stats."""
    eq_doc = _read_json(DATA_DIR / "equity_curve_daily.json", {})
    daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []

    if not daily:
        return "📆 *Месяц*\nДанных пока недостаточно."

    stats = calculate_period_returns(daily)
    last_date = daily[-1].get("date", "?")
    equity_now = float(daily[-1].get("equity") or daily[-1].get("close_equity") or 0.0)
    eq_30d = stats["equity_30d_ago"]

    try:
        dt = datetime.strptime(last_date, "%Y-%m-%d")
        month_name = calendar.month_name[dt.month]
    except Exception:
        month_name = last_date[:7] if last_date and len(last_date) >= 7 else "?"

    month_sign = "+" if stats["month_pct"] >= 0 else ""
    eq_from = eq_30d if eq_30d else equity_now

    return "\n".join(
        [
            f"📆 *Месяц — {month_name}*",
            f"Equity: ${eq_from:,.0f} → ${equity_now:,.0f}",
            f"Доходность: {month_sign}{stats['month_pct']:.2f}%",
            f"Прибыльных дней: {stats['profitable_30d']}/30",
        ]
    )


def _cmd_year_text() -> str:
    """🗓 С начала года."""
    eq_doc = _read_json(DATA_DIR / "equity_curve_daily.json", {})
    daily = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []

    if not daily:
        return "🗓 *С начала года*\nДанных пока недостаточно."

    stats = calculate_period_returns(daily)
    last_date = daily[-1].get("date", "?")
    equity_now = float(daily[-1].get("equity") or daily[-1].get("close_equity") or 0.0)
    eq_yr = stats["equity_yr_ago"]
    first_equity = float(daily[0].get("equity") or daily[0].get("close_equity") or 100_000.0)

    n_days = len(daily)
    try:
        ann_pct = (
            (1.0 + stats["alltime_pct"] / 100.0) ** (365.0 / max(n_days, 1)) - 1.0
        ) * 100.0
    except Exception:
        ann_pct = 0.0

    eq_from = eq_yr if eq_yr else first_equity
    if eq_yr:
        ret_label = f"Доходность (12м): {'+' if stats['year_pct'] >= 0 else ''}{stats['year_pct']:.2f}%"
    else:
        ret_label = f"За всё время: {'+' if stats['alltime_pct'] >= 0 else ''}{stats['alltime_pct']:.2f}%"

    ann_sign = "+" if ann_pct >= 0 else ""

    return "\n".join(
        [
            f"🗓 *С начала года*",
            f"Equity: ${eq_from:,.0f} → ${equity_now:,.0f}",
            ret_label,
            f"Annualized: {ann_sign}{ann_pct:.2f}%",
        ]
    )


def _cmd_status_text() -> str:
    """🔍 Статус системы."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    golive = _read_json(DATA_DIR / "golive_status.json", {})
    checks = golive.get("checks", {}) if isinstance(golive, dict) else {}

    CHECK_LABELS = [
        ("equity_curve_real", "Equity curve реальная"),
        ("trades_real", "Есть реальные трейды"),
        ("status_real", "Status реальный"),
        ("no_demo_data", "Нет demo-данных"),
        ("data_fresh_48h", "Данные свежее 48ч"),
        ("cycle_runner_exists", "Cycle runner активен"),
    ]

    lines = [f"🔍 *Статус SPA — {now_str}*", "", "*Go-Live критерии:*"]
    for key, label in CHECK_LABELS:
        ok = bool(checks.get(key, False))
        lines.append(f"{'✅' if ok else '❌'} {label}")

    gm = _read_json(DATA_DIR / "gap_monitor.json", {})
    gap_det = bool(gm.get("gap_detected", False)) if isinstance(gm, dict) else False
    lines.append("")
    lines.append(
        f"{'⚠️' if gap_det else '✅'} Gap monitor: {'пробел!' if gap_det else 'норма'}"
    )

    n_pass = sum(1 for v in checks.values() if v)
    ready = bool(golive.get("ready", False)) if isinstance(golive, dict) else False
    status_str = "READY ✅" if ready else f"PRE-LIVE {n_pass}/6"
    lines.append(f"\n🎯 Итого: *{status_str}*")

    return "\n".join(lines)


# ─── MP-136: Detail callback for 📋 Подробнее ────────────────────────────────


def _cmd_detail_text(protocol: str, category: str) -> str:
    """Generate a detailed message for a red-flag "📋 Подробнее" callback.

    Reads ``data/red_flags.json``, finds the matching alert by (protocol,
    category), and returns the formatted detail text. Fail-safe.
    """
    try:
        doc = _read_json(DATA_DIR / "red_flags.json", {})
        flags = (
            doc.get("red_flags", [])
            if isinstance(doc, dict)
            else []
        )
        for flag in flags:
            if (
                isinstance(flag, dict)
                and flag.get("protocol") == protocol
                and flag.get("category") == category
            ):
                return format_alert_detail_ru(flag)

        # Alert not found — build a minimal fallback from the callback parameters
        from spa_core.alerts.telegram_format_ru import PROTOCOL_NAMES
        proto_name = PROTOCOL_NAMES.get(protocol, protocol)
        return (
            f"⚠️ Детальная информация для *{proto_name}* / *{category}* "
            f"не найдена в текущем снэпшоте.\n\n"
            f"Данные могут устареть — следующий цикл обновит ``data/red_flags.json``."
        )
    except Exception as exc:
        log.warning("_cmd_detail_text failed (%s)", exc)
        return f"⚠️ Ошибка при загрузке деталей: {type(exc).__name__}"


# ─── Command dispatch ─────────────────────────────────────────────────────────

_CMD_HANDLERS: dict = {
    "cmd_now": _cmd_now_text,
    "cmd_week": _cmd_week_text,
    "cmd_month": _cmd_month_text,
    "cmd_year": _cmd_year_text,
    "cmd_status": _cmd_status_text,
}


# ─── Update processing ────────────────────────────────────────────────────────


def _process_update(token: str, chat_id: str, update: dict) -> None:
    """Process one Telegram update — callback_query or message."""
    # ── Button press ──
    cq = update.get("callback_query")
    if isinstance(cq, dict):
        cq_id = str(cq.get("id", ""))
        data = cq.get("data", "")
        cq_chat = str(
            cq.get("message", {}).get("chat", {}).get("id", "")
        ) or chat_id

        # Must answer BEFORE sending reply (stops the spinner)
        _answer_callback_query(token, cq_id)

        # MP-136: "📋 Подробнее" detail callbacks
        detail = parse_detail_callback(data)
        if detail is not None:
            protocol, category = detail
            try:
                text = _cmd_detail_text(protocol, category)
            except Exception as exc:
                log.warning("detail handler raised: %s", exc)
                text = f"⚠️ Ошибка при загрузке деталей: {type(exc).__name__}"
            # Detail message — no further keyboard (plain send)
            try:
                _api_post(
                    token,
                    "sendMessage",
                    {
                        "chat_id": cq_chat,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                )
            except Exception as exc:
                log.warning("detail send failed: %s", exc)
            return

        handler = _CMD_HANDLERS.get(data)
        if handler:
            try:
                text = handler()
            except Exception as exc:
                log.warning("handler %s raised: %s", data, exc)
                text = f"⚠️ Ошибка при обработке команды: {type(exc).__name__}"
            _send_with_keyboard(token, cq_chat, text)
        return

    # ── Regular message ──
    msg = update.get("message")
    if isinstance(msg, dict):
        msg_chat_id = str(msg.get("chat", {}).get("id", "")) or chat_id
        text_in = str(msg.get("text", "") or "")
        if text_in.startswith("/start") or not text_in.startswith("/"):
            welcome = (
                "👋 *SPA Bot активен*\n"
                "Выбери период для просмотра статистики:"
            )
            _send_with_keyboard(token, msg_chat_id, welcome)


# ─── Offset persistence ───────────────────────────────────────────────────────


def _read_offset() -> int:
    doc = _read_json(OFFSET_FILE, {})
    return int(doc.get("offset", 0)) if isinstance(doc, dict) else 0


def _write_offset(offset: int) -> None:
    _atomic_write_json(
        OFFSET_FILE,
        {
            "offset": offset,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# ─── Main polling loop ────────────────────────────────────────────────────────


def run_polling() -> None:
    """Read pending updates, dispatch handlers, persist offset. Fail-safe."""
    try:
        token = _get_token()
        chat_id = _get_chat_id()
    except EnvironmentError as exc:
        log.warning("Bot credentials unavailable: %s — polling skipped", exc)
        return

    offset = _read_offset()

    try:
        resp = _api_get(token, "getUpdates", {"offset": offset, "timeout": 5})
    except Exception as exc:
        log.warning("getUpdates failed: %s", exc)
        return

    if not resp.get("ok"):
        log.warning("getUpdates returned ok=false: %s", resp)
        return

    updates = resp.get("result") or []
    if not updates:
        return

    max_update_id = offset
    for update in updates:
        update_id = int(update.get("update_id", 0))
        try:
            _process_update(token, chat_id, update)
        except Exception as exc:
            log.warning("process_update failed for update %d: %s", update_id, exc)
        max_update_id = max(max_update_id, update_id + 1)

    _write_offset(max_update_id)


def run_polling_continuous() -> None:
    """Continuous long-polling loop — instant responses (< 2 sec).

    Uses getUpdates with timeout=30 (long-poll): Telegram holds the connection
    open until an update arrives or 30 seconds elapse, so no busy-looping.
    launchd plist should use KeepAlive=true (no StartInterval).
    """
    import time

    try:
        token = _get_token()
        chat_id = _get_chat_id()
    except EnvironmentError as exc:
        log.error("Bot credentials unavailable: %s — cannot start", exc)
        return

    offset = _read_offset()
    log.warning("SPA Bot long-poll started (offset=%d)", offset)

    while True:
        try:
            resp = _api_get(
                token, "getUpdates", {"offset": offset, "timeout": 30}
            )
        except Exception as exc:
            log.warning("getUpdates failed: %s — retrying in 5s", exc)
            time.sleep(5)
            continue

        if not resp.get("ok"):
            log.warning("getUpdates ok=false: %s — retrying in 5s", resp)
            time.sleep(5)
            continue

        updates = resp.get("result") or []
        max_update_id = offset
        for update in updates:
            update_id = int(update.get("update_id", 0))
            try:
                _process_update(token, chat_id, update)
            except Exception as exc:
                log.warning("process_update %d failed: %s", update_id, exc)
            max_update_id = max(max_update_id, update_id + 1)

        if max_update_id != offset:
            offset = max_update_id
            _write_offset(offset)


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if "--once" in sys.argv:
        run_polling()        # старый режим: один прогон и выход
    else:
        run_polling_continuous()  # новый режим: постоянный процесс

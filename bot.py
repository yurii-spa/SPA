#!/usr/bin/env python3
"""SPA Telegram Bot v2.0.

Interactive long-polling Telegram bot for the SPA paper-trading system.
Replaces the older callback-only ``spa_core.alerts.bot_commands`` with a
full slash-command interface plus inline keyboards.

Run:
    python3 -m spa_core.telegram.bot           # continuous long-poll (daemon)
    python3 -m spa_core.telegram.bot --once     # single drain, then exit (cron/test)

Commands
--------
  /start      welcome + command list + inline keyboard
  /status     equity, APY today, daily yield, kill-switch, trading day
  /portfolio  current allocation per protocol ($ and %)
  /today      P&L today, trades, APY
  /week       7-day summary (equity move, best day, profitable days)
  /agents     launchd agent health (✅/❌ each) from uptime_status.json
  /alerts     top red_flags + peg status
  /pause      arm the manual kill-switch
  /resume     clear the manual kill-switch
  /help       command list

Design
------
* Python 3.9 compatible (``typing.Optional`` etc., no ``X | Y`` annotations).
* Stdlib only (urllib) — no ``python-telegram-bot`` dependency required.
* Credentials read at runtime from the macOS Keychain
  (``TELEGRAM_BOT_TOKEN_SPA`` / ``TELEGRAM_CHAT_ID_SPA``, account ``spa``)
  with env-var fallback (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``).
  Secrets are NEVER written to files.
* Every command handler is fail-safe: a missing/corrupt data file or an
  API error becomes a friendly message, never a crash. The polling loop
  also swallows per-update exceptions so one bad update can't kill the bot.
* Atomic writes (tmp + os.replace) for the kill-switch and offset files.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("spa.telegram.bot")

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

OFFSET_FILE = DATA_DIR / "tg_bot_v2_offset.json"
KILL_SWITCH_FILE = DATA_DIR / "kill_switch_active.json"

HTTP_TIMEOUT_S = 35  # long-poll timeout (30) + slack
KEYCHAIN_ACCOUNT = "spa"
TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"

DASHBOARD_URL = "https://yuriiykulieshov.github.io/SPA_Claude/"


# ─── Credential helpers ─────────────────────────────────────────────────────


def _read_keychain(service: str) -> Optional[str]:
    """Read one generic password from macOS Keychain. None on any failure."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    value = (proc.stdout or "").strip()
    return value or None


def get_token() -> Optional[str]:
    """Bot token: Keychain ``TELEGRAM_BOT_TOKEN_SPA`` then env fallback."""
    tok = _read_keychain(TOKEN_SERVICE)
    if tok:
        return tok
    return os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN_SPA")


def get_chat_id() -> Optional[str]:
    """Chat id: Keychain ``TELEGRAM_CHAT_ID_SPA`` then env fallback."""
    cid = _read_keychain(CHAT_ID_SERVICE)
    if cid:
        return cid
    return os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID_SPA")


# ─── Atomic IO ──────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON, returning ``default`` if missing or unreadable. Never raises."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("read_json %s unreadable (%s)", p.name, exc)
        return default


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically (tmp + os.replace)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix="." + p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(p))
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


# ─── Formatting helpers ─────────────────────────────────────────────────────


def _fmt_usd(value: float) -> str:
    return "${:,.2f}".format(float(value or 0.0))


def _pct_sign(value: float) -> str:
    return "+" if float(value or 0.0) >= 0 else ""


def _proto_label(key: str) -> str:
    return str(key).replace("_", " ").replace("-", " ").title()


# ─── The bot ────────────────────────────────────────────────────────────────


class TelegramBot:
    """Stdlib long-polling Telegram bot. All public methods are fail-safe."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None) -> None:
        self.token = token if token is not None else get_token()
        self.chat_id = chat_id if chat_id is not None else get_chat_id()
        self.api_base = "https://api.telegram.org/bot{}".format(self.token)
        self._offset = self._read_offset()

    # ── Telegram API ──────────────────────────────────────────────────────

    def _api_call(self, method: str, params: Optional[Dict] = None,
                  timeout: Optional[float] = None) -> Optional[Dict]:
        """POST a JSON request to the Bot API. None on any failure."""
        url = "{}/{}".format(self.api_base, method)
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError,
                TimeoutError, OSError, ValueError) as exc:
            log.warning("API call %s failed: %s", method, exc)
            return None

    def send_message(self, text: str, chat_id: Optional[str] = None,
                     parse_mode: str = "HTML",
                     reply_markup: Optional[Dict] = None) -> Optional[Dict]:
        """Send a message. Fail-safe."""
        target = chat_id or self.chat_id
        if not target:
            log.warning("send_message: no chat_id available")
            return None
        params: Dict[str, Any] = {
            "chat_id": target,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            params["reply_markup"] = json.dumps(reply_markup)
        return self._api_call("sendMessage", params)

    def _answer_callback(self, callback_query_id: str) -> None:
        self._api_call("answerCallbackQuery", {"callback_query_id": callback_query_id})

    # ── Offset persistence ────────────────────────────────────────────────

    def _read_offset(self) -> int:
        doc = _read_json(OFFSET_FILE, {})
        try:
            return int(doc.get("offset", 0)) if isinstance(doc, dict) else 0
        except (TypeError, ValueError):
            return 0

    def _write_offset(self, offset: int) -> None:
        try:
            _atomic_write_json(OFFSET_FILE, {
                "offset": offset,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            log.warning("write_offset failed: %s", exc)

    def get_updates(self) -> List[Dict]:
        """Long-poll getUpdates with the persisted offset. Advances offset."""
        result = self._api_call("getUpdates", {"offset": self._offset, "timeout": 30})
        if not result or not result.get("ok"):
            return []
        updates = result.get("result") or []
        if updates:
            try:
                self._offset = int(updates[-1]["update_id"]) + 1
                self._write_offset(self._offset)
            except (KeyError, TypeError, ValueError):
                pass
        return updates

    # ── Inline keyboards ──────────────────────────────────────────────────

    @staticmethod
    def _status_keyboard() -> Dict:
        return {"inline_keyboard": [[
            {"text": "📊 Portfolio", "callback_data": "/portfolio"},
            {"text": "📈 Today", "callback_data": "/today"},
            {"text": "🤖 Agents", "callback_data": "/agents"},
        ]]}

    @staticmethod
    def _resume_keyboard() -> Dict:
        return {"inline_keyboard": [[
            {"text": "▶️ Resume", "callback_data": "/resume"},
        ]]}

    # ── Command handlers ──────────────────────────────────────────────────

    def cmd_start(self, chat_id: str) -> None:
        text = (
            "👋 <b>SPA Bot v2.0</b>\n\n"
            "Команды:\n"
            "/status — статус системы\n"
            "/portfolio — текущая аллокация\n"
            "/today — P&amp;L за сегодня\n"
            "/week — недельный отчёт\n"
            "/agents — статус агентов\n"
            "/alerts — последние алерты\n"
            "/pause — пауза (kill-switch)\n"
            "/resume — снять паузу\n"
            "/help — этот список"
        )
        self.send_message(text, chat_id, reply_markup=self._status_keyboard())

    cmd_help = cmd_start

    def cmd_status(self, chat_id: str) -> None:
        try:
            st = _read_json(DATA_DIR / "paper_trading_status.json", {})
            ks = _read_json(KILL_SWITCH_FILE, {})

            equity = float(st.get("current_equity", 0.0) or 0.0)
            start_eq = 100000.0
            pnl_usd = equity - start_eq
            total_ret = float(st.get("total_return_pct", 0.0) or 0.0)
            apy_today = float(st.get("apy_today_pct", 0.0) or 0.0)
            daily_yield = float(st.get("daily_yield_usd", 0.0) or 0.0)
            days = st.get("days_running", "?")
            last_cycle = str(st.get("last_cycle_ts", "?") or "?")[:16].replace("T", " ")

            ks_active = bool(ks.get("active", False)) if isinstance(ks, dict) else False
            ks_line = "ACTIVE ⛔" if ks_active else "INACTIVE ✅"

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            text = (
                "📊 <b>SPA Status</b> · {now}\n\n"
                "💰 Equity: {eq} ({sgn}{pnl} / {tsgn}{tot:.2f}%)\n"
                "📈 APY Today: {apy:.2f}%\n"
                "💵 Daily Yield: {dy}\n"
                "🗓 Trading Day: {days}/30\n\n"
                "🔒 Kill-Switch: {ks}\n"
                "🔄 Last Cycle: {lc}"
            ).format(
                now=now_str, eq=_fmt_usd(equity),
                sgn=_pct_sign(pnl_usd), pnl=_fmt_usd(abs(pnl_usd)),
                tsgn=_pct_sign(total_ret), tot=total_ret,
                apy=apy_today, dy=_fmt_usd(daily_yield), days=days,
                ks=ks_line, lc=last_cycle,
            )
            self.send_message(text, chat_id, reply_markup=self._status_keyboard())
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading status: {}".format(type(exc).__name__), chat_id)

    def cmd_portfolio(self, chat_id: str) -> None:
        try:
            doc = _read_json(DATA_DIR / "current_positions.json", {})
            positions = doc.get("positions", {}) if isinstance(doc, dict) else {}
            capital = float(doc.get("capital_usd", 100000.0) or 100000.0)
            cash = float(doc.get("cash_usd", 0.0) or 0.0)

            if not positions:
                self.send_message("📊 <b>Portfolio</b>\n\nНет открытых позиций.", chat_id)
                return

            lines = ["📊 <b>Portfolio</b>\n"]
            for proto, usd in sorted(positions.items(), key=lambda kv: -float(kv[1] or 0.0)):
                usd_f = float(usd or 0.0)
                pct = usd_f / capital * 100.0 if capital else 0.0
                lines.append("• {name}: {amt} ({pct:.1f}%)".format(
                    name=_proto_label(proto), amt=_fmt_usd(usd_f), pct=pct))
            if cash:
                lines.append("• Cash: {amt} ({pct:.1f}%)".format(
                    amt=_fmt_usd(cash), pct=cash / capital * 100.0 if capital else 0.0))
            lines.append("\n💰 Total: {}".format(_fmt_usd(capital)))
            self.send_message("\n".join(lines), chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading portfolio: {}".format(type(exc).__name__), chat_id)

    def cmd_today(self, chat_id: str) -> None:
        try:
            st = _read_json(DATA_DIR / "paper_trading_status.json", {})
            daily_ret = float(st.get("daily_return_pct", 0.0) or 0.0)
            daily_yield = float(st.get("daily_yield_usd", 0.0) or 0.0)
            apy_today = float(st.get("apy_today_pct", 0.0) or 0.0)
            equity = float(st.get("current_equity", 0.0) or 0.0)
            last_trade = st.get("last_trade_id")
            trade_line = "0" if last_trade in (None, "", 0) else "1+ (last: {})".format(last_trade)

            text = (
                "📈 <b>Today</b> · {date}\n\n"
                "💵 P&amp;L: {sgn}{yld} ({rsgn}{ret:.3f}%)\n"
                "📊 APY Today: {apy:.2f}%\n"
                "💰 Equity: {eq}\n"
                "🔁 Trades: {trades}"
            ).format(
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                sgn=_pct_sign(daily_yield), yld=_fmt_usd(abs(daily_yield)),
                rsgn=_pct_sign(daily_ret), ret=daily_ret,
                apy=apy_today, eq=_fmt_usd(equity), trades=trade_line,
            )
            self.send_message(text, chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading today: {}".format(type(exc).__name__), chat_id)

    def cmd_week(self, chat_id: str) -> None:
        try:
            doc = _read_json(DATA_DIR / "equity_curve_daily.json", {})
            daily = doc.get("daily", []) if isinstance(doc, dict) else []
            summary = doc.get("summary", {}) if isinstance(doc, dict) else {}

            if not daily:
                self.send_message("📅 <b>Week</b>\n\nДанных пока недостаточно.", chat_id)
                return

            window = daily[-7:]

            def _eq(bar: Dict) -> float:
                return float(bar.get("equity") or bar.get("close_equity") or 0.0)

            eq_from = _eq(window[0])
            eq_now = _eq(window[-1])
            week_pct = ((eq_now / eq_from - 1.0) * 100.0) if eq_from else 0.0
            profitable = sum(1 for b in window if float(b.get("daily_return_pct", 0.0)) > 0)

            best = max(window, key=lambda b: float(b.get("daily_return_pct", 0.0)))
            best_pct = float(best.get("daily_return_pct", 0.0))
            best_date = best.get("date", "—")

            date_from = window[0].get("date", "?")
            date_to = window[-1].get("date", "?")

            text = (
                "📅 <b>Week</b> · {df} → {dt}\n\n"
                "💰 Equity: {ef} → {en}\n"
                "📈 Return: {wsgn}{wk:.3f}%\n"
                "🏆 Best day: {bd} ({bsgn}{bp:.3f}%)\n"
                "✅ Profitable: {prof}/{n} days"
            ).format(
                df=date_from, dt=date_to,
                ef=_fmt_usd(eq_from), en=_fmt_usd(eq_now),
                wsgn=_pct_sign(week_pct), wk=week_pct,
                bd=best_date, bsgn=_pct_sign(best_pct), bp=best_pct,
                prof=profitable, n=len(window),
            )
            self.send_message(text, chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading week: {}".format(type(exc).__name__), chat_id)

    def cmd_agents(self, chat_id: str) -> None:
        try:
            doc = _read_json(DATA_DIR / "uptime_status.json", {})
            checks = doc.get("checks", {}) if isinstance(doc, dict) else {}
            if not checks:
                self.send_message("🤖 <b>Agents</b>\n\nНет данных uptime.", chat_id)
                return

            lines = ["🤖 <b>Agents</b>\n"]
            n_up = 0
            n_total = 0
            for name, info in sorted(checks.items()):
                running = info.get("running") if isinstance(info, dict) else None
                if running is None:
                    continue  # synthetic/aggregate entries (http_server etc.)
                n_total += 1
                if running:
                    n_up += 1
                label = name.replace("launchd_", "").replace("_", " ")
                lines.append("{icon} {label}".format(icon="✅" if running else "❌", label=label))
            lines.append("\n📊 Up: {up}/{tot}".format(up=n_up, tot=n_total))
            self.send_message("\n".join(lines), chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading agents: {}".format(type(exc).__name__), chat_id)

    def cmd_alerts(self, chat_id: str) -> None:
        try:
            rf_doc = _read_json(DATA_DIR / "red_flags.json", {})
            flags = rf_doc.get("red_flags", []) if isinstance(rf_doc, dict) else []
            peg = _read_json(DATA_DIR / "peg_report.json", {})

            lines = ["🚨 <b>Alerts</b>\n"]
            if not flags:
                lines.append("✅ Red flags: нет активных")
            else:
                lines.append("⚠️ Red flags ({}):".format(len(flags)))
                for f in flags[:5]:
                    if not isinstance(f, dict):
                        continue
                    sev = str(f.get("severity", "?"))
                    proto = _proto_label(f.get("protocol", "?"))
                    msg = str(f.get("message", ""))[:90]
                    lines.append("• [{sev}] {proto}: {msg}".format(sev=sev, proto=proto, msg=msg))

            if isinstance(peg, dict):
                status = peg.get("overall_status", "?")
                crit = peg.get("critical", 0)
                warn = peg.get("warning", 0)
                icon = "✅" if status == "GREEN" else "⚠️"
                lines.append("\n{icon} Peg monitor: {st} (crit {c}, warn {w})".format(
                    icon=icon, st=status, c=crit, w=warn))

            self.send_message("\n".join(lines), chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading alerts: {}".format(type(exc).__name__), chat_id)

    def cmd_pause(self, chat_id: str) -> None:
        try:
            _atomic_write_json(KILL_SWITCH_FILE, {
                "active": True,
                "reason": "manual_telegram",
                "detail": "Kill-switch armed manually via Telegram /pause",
                "set_at": datetime.now(timezone.utc).isoformat(),
            })
            self.send_message(
                "⛔ <b>Kill-switch ARMED</b>\nЦикл поставлен на паузу (manual_telegram).",
                chat_id, reply_markup=self._resume_keyboard())
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error arming kill-switch: {}".format(type(exc).__name__), chat_id)

    def cmd_resume(self, chat_id: str) -> None:
        try:
            _atomic_write_json(KILL_SWITCH_FILE, {
                "active": False,
                "reason": "manual_telegram_resume",
                "detail": "Kill-switch cleared manually via Telegram /resume",
                "reset_at": datetime.now(timezone.utc).isoformat(),
            })
            self.send_message(
                "▶️ <b>Kill-switch CLEARED</b>\nЦикл возобновлён (manual_telegram_resume).",
                chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error clearing kill-switch: {}".format(type(exc).__name__), chat_id)

    # ── Routing ───────────────────────────────────────────────────────────

    _COMMANDS = (
        "/start", "/help", "/status", "/portfolio", "/today",
        "/week", "/agents", "/alerts", "/pause", "/resume",
    )

    def _dispatch(self, text: str, chat_id: str) -> None:
        """Route a command string to its handler. Unknown → help."""
        cmd = text.strip().split()[0].split("@")[0].lower() if text.strip() else ""
        handlers = {
            "/start": self.cmd_start,
            "/help": self.cmd_help,
            "/status": self.cmd_status,
            "/portfolio": self.cmd_portfolio,
            "/today": self.cmd_today,
            "/week": self.cmd_week,
            "/agents": self.cmd_agents,
            "/alerts": self.cmd_alerts,
            "/pause": self.cmd_pause,
            "/resume": self.cmd_resume,
        }
        handler = handlers.get(cmd)
        if handler is None:
            self.cmd_help(chat_id)
        else:
            handler(chat_id)

    def handle_update(self, update: Dict) -> None:
        """Process one update — callback_query button or text message. Fail-safe."""
        try:
            cq = update.get("callback_query")
            if isinstance(cq, dict):
                self._answer_callback(str(cq.get("id", "")))
                data = str(cq.get("data", ""))
                chat_id = str(cq.get("message", {}).get("chat", {}).get("id", "")) or self.chat_id
                if chat_id:
                    self._dispatch(data, chat_id)
                return

            msg = update.get("message")
            if isinstance(msg, dict):
                text = str(msg.get("text", "") or "")
                chat_id = str(msg.get("chat", {}).get("id", "")) or self.chat_id
                if not chat_id:
                    return
                if text.startswith("/"):
                    self._dispatch(text, chat_id)
                else:
                    # Bare text → welcome/help
                    self.cmd_help(chat_id)
        except Exception as exc:  # noqa: BLE001 — never let one update crash the loop
            log.warning("handle_update failed: %s", exc)

    # ── Polling loops ─────────────────────────────────────────────────────

    def run_once(self) -> int:
        """Drain pending updates once, dispatch, return count processed."""
        updates = self.get_updates()
        for upd in updates:
            self.handle_update(upd)
        return len(updates)

    def run_polling(self) -> None:
        """Continuous long-polling loop. Fail-safe; never returns normally."""
        log.warning("SPA Bot v2.0 started (offset=%d)", self._offset)
        while True:
            try:
                for upd in self.get_updates():
                    self.handle_update(upd)
            except Exception as exc:  # noqa: BLE001
                log.warning("polling error: %s — retry in 5s", exc)
                time.sleep(5)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = TelegramBot()
    if not bot.token:
        logging.error("No Telegram token found. Set TELEGRAM_BOT_TOKEN_SPA in Keychain "
                      "or TELEGRAM_BOT_TOKEN in env.")
        return 1
    if "--once" in argv:
        n = bot.run_once()
        logging.info("Processed %d update(s), exiting (--once).", n)
        return 0
    bot.run_polling()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

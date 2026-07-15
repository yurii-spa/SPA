#!/usr/bin/env python3
"""SPA Telegram Bot v2.1.

Interactive long-polling Telegram bot for the SPA paper-trading system.
Replaces the older callback-only ``spa_core.alerts.bot_commands`` with a
full slash-command interface plus inline keyboards.

Run:
    python3 -m spa_core.telegram.bot           # continuous long-poll (daemon)
    python3 -m spa_core.telegram.bot --once     # single drain, then exit (cron/test)

Commands
--------
  /start      welcome + main inline menu
  /menu       interactive menu (same as /help)
  /help       command list + inline menu
  /status     equity, APY today, daily yield, kill-switch, trading day
  /portfolio  current allocation per protocol ($ and %)
  /today      P&L today, trades, APY
  /week       7-day summary (equity move, best day, profitable days)
  /agents     launchd agent health (✅/❌/⏸) + "What does each agent do?" button
  /alerts     top red_flags + peg status
  /why        explain likely reasons for each ❌ agent
  /pause      arm the manual kill-switch
  /resume     clear the manual kill-switch

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
* On startup (run_polling), setMyCommands registers all commands in the
  Telegram ☰ menu automatically.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    import fcntl  # POSIX advisory file lock — single-instance guard (macOS/Linux)
except ImportError:  # pragma: no cover — non-POSIX; lock degrades to a no-op
    fcntl = None
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

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

DASHBOARD_URL = "https://earn-defi.com/dashboard"


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
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _fmt_usd(value: float) -> str:
    return "${:,.2f}".format(float(value or 0.0))


def _pct_sign(value: float) -> str:
    return "+" if float(value or 0.0) >= 0 else ""


def _proto_label(key: str) -> str:
    return str(key).replace("_", " ").replace("-", " ").title()


# ─── The bot ────────────────────────────────────────────────────────────────


class TelegramBot:
    """Stdlib long-polling Telegram bot. All public methods are fail-safe."""

    # getUpdates failure backoff: when the Bot API is unreachable (502, SSL
    # handshake/read timeout, connection reset) _api_call returns None and
    # get_updates returns []. Without a pause run_polling spins and hammers the
    # API hundreds of times a second. Back off 2**streak seconds, capped.
    _MAX_BACKOFF_STEP = 6     # 2**6 = 64
    _MAX_BACKOFF_S = 60

    # Single-instance advisory lock: a restarting poller can transiently overlap
    # the prior instance's getUpdates long-poll → Telegram 409 Conflict streak.
    # The lock file holds an exclusive flock for the poller's lifetime so a second
    # poller refuses to start (rather than dueling for getUpdates). Advisory only:
    # a missing flock (e.g. unusual FS) never blocks a legitimate single bot.
    _LOCK_FILENAME = "tg_bot_v2.lock"

    def _lock_path(self) -> Path:
        """Lock-file path resolved from the LIVE module DATA_DIR at call time
        (so tests redirecting DATA_DIR are honored, not the import-time value)."""
        return DATA_DIR / self._LOCK_FILENAME

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None) -> None:
        self.token = token if token is not None else get_token()
        self.chat_id = chat_id if chat_id is not None else get_chat_id()
        self.api_base = "https://api.telegram.org/bot{}".format(self.token)
        self._offset = self._read_offset()
        self._fail_streak = 0
        self._conflict_streak = 0      # consecutive getUpdates 409 Conflicts
        self._last_status = None       # HTTP status of the last _api_call (or None)
        self._lock_fh = None           # held flock file handle (single-instance)
        self._router = None  # lazily built (interactive menu router)

    # ── Interactive menu router (drill-down via editMessageText) ────────────

    def _get_router(self):
        """Build (once) the interactive Router wired to a bot-backed transport."""
        if self._router is None:
            from spa_core.telegram.router import Router

            bot = self

            class _Transport:
                """Adapt the bot's API to the Router's transport contract."""

                @staticmethod
                def send_message(chat_id, text, reply_markup):
                    return bot.send_message(text, chat_id=chat_id,
                                            reply_markup=reply_markup)

                @staticmethod
                def edit_message_text(chat_id, message_id, text, reply_markup):
                    return bot.edit_message_text(chat_id, message_id, text,
                                                 reply_markup=reply_markup)

                @staticmethod
                def answer_callback(callback_id):
                    return bot._answer_callback(callback_id)

            self._router = Router(_Transport(), self.chat_id)
        return self._router

    # ── Telegram API ──────────────────────────────────────────────────────

    def _api_call(self, method: str, params: Optional[Dict] = None,
                  timeout: Optional[float] = None) -> Optional[Dict]:
        """POST a JSON request to the Bot API. None on any failure."""
        url = "{}/{}".format(self.api_base, method)
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        self._last_status = None
        try:
            with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT_S) as resp:
                self._last_status = getattr(resp, "status", None) or resp.getcode()
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Record the HTTP status so callers can distinguish 409 Conflict (a
            # second getUpdates poller is overlapping) from a generic outage.
            self._last_status = getattr(exc, "code", None)
            log.warning("API call %s failed: HTTP %s %s", method, self._last_status, exc)
            return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("API call %s failed: %s", method, exc)
            return None

    def send_message(self, text: str, chat_id: Optional[str] = None,
                     parse_mode: str = "HTML",
                     reply_markup: Optional[Dict] = None) -> Optional[Dict]:
        """Send a message. Fail-safe + FLOOD-GUARDED (shared cross-process rate limit so a
        reply/callback loop can never flood the chat)."""
        target = chat_id or self.chat_id
        if not target:
            log.warning("send_message: no chat_id available")
            return None
        try:
            from spa_core.alerts.telegram_client import _rate_limit_ok
            if not _rate_limit_ok(text):
                log.warning("bot send dropped by flood guard (>rate). preview=%r", (text or "")[:80])
                return None
        except Exception:
            pass  # guard import failure must never block a legitimate reply
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
        if not callback_query_id:
            return
        self._api_call("answerCallbackQuery", {"callback_query_id": callback_query_id})

    def edit_message_text(self, chat_id: str, message_id: Any, text: str,
                          reply_markup: Optional[Dict] = None,
                          parse_mode: str = "HTML") -> Optional[Dict]:
        """editMessageText — drives the single evolving panel (in-place nav).

        Fail-safe + flood-guarded. Telegram no-ops an identical edit, so
        double-taps are free.
        """
        if not chat_id or message_id in (None, ""):
            return None
        try:
            from spa_core.alerts.telegram_client import _rate_limit_ok
            if not _rate_limit_ok(text):
                log.warning("bot edit dropped by flood guard")
                return None
        except Exception:
            pass
        params: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            params["reply_markup"] = json.dumps(reply_markup)
        return self._api_call("editMessageText", params)

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
            # 409 Conflict = another getUpdates poller is (transiently) overlapping
            # — typically a restart while the prior instance is still draining its
            # long-poll. Back off (capped) so we do NOT hammer a tight 409 streak;
            # the overlap is self-clearing once the old poll's 30s timeout lapses.
            if self._last_status == 409:
                self._conflict_streak += 1
                backoff = min(2 ** min(self._conflict_streak, self._MAX_BACKOFF_STEP),
                              self._MAX_BACKOFF_S)
                log.warning("getUpdates 409 Conflict (streak=%d) — another poller "
                            "overlapping; backoff %ds", self._conflict_streak, backoff)
                time.sleep(backoff)
                return []
            # Transient Telegram outage (502 / SSL / read timeout). Apply capped
            # exponential backoff so a multi-second outage does not become a
            # tight retry storm against the Bot API.
            self._fail_streak = min(self._fail_streak + 1, self._MAX_BACKOFF_STEP)
            backoff = min(2 ** self._fail_streak, self._MAX_BACKOFF_S)
            log.warning("getUpdates failed (streak=%d) — backoff %ds",
                        self._fail_streak, backoff)
            time.sleep(backoff)
            return []
        self._fail_streak = 0  # success → reset
        self._conflict_streak = 0
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
    def _main_menu_keyboard() -> Dict:
        """Full interactive menu keyboard for /menu and /help."""
        return {"inline_keyboard": [
            [
                {"text": "📊 Статус системы", "callback_data": "/status"},
                {"text": "💼 Портфель",       "callback_data": "/portfolio"},
            ],
            [
                {"text": "📈 Сегодня",        "callback_data": "/today"},
                {"text": "🤖 Агенты",         "callback_data": "/agents"},
            ],
            [
                {"text": "🔔 Алерты",         "callback_data": "/alerts"},
                {"text": "❓ Почему ❌?",     "callback_data": "/why"},
            ],
            [
                {"text": "⏸ Пауза",          "callback_data": "/pause"},
                {"text": "▶️ Возобновить",    "callback_data": "/resume"},
            ],
        ]}

    @staticmethod
    def _status_keyboard() -> Dict:
        return {"inline_keyboard": [[
            {"text": "📊 Portfolio", "callback_data": "/portfolio"},
            {"text": "📈 Today",     "callback_data": "/today"},
            {"text": "🤖 Agents",    "callback_data": "/agents"},
        ]]}

    @staticmethod
    def _resume_keyboard() -> Dict:
        return {"inline_keyboard": [[
            {"text": "▶️ Resume", "callback_data": "/resume"},
        ]]}

    @staticmethod
    def _agents_info_keyboard() -> Dict:
        """'What does each agent do?' button shown below /agents output."""
        return {"inline_keyboard": [[
            {"text": "📖 Что делает каждый агент?", "callback_data": "agents_detail"},
        ]]}

    # ── Agent metadata ────────────────────────────────────────────────────

    # (name_without_launchd_prefix, one-line description, run interval)
    _AGENT_DESCRIPTIONS: List[Tuple[str, str, str]] = [
        ("daily_cycle",        "Главный торговый движок. Проверяет APY, размещает средства.", "каждые 30 мин"),
        ("portfolio_monitor",  "Считает equity / P&L / APY по текущему портфелю.",            "каждые 5 мин"),
        ("peg_monitor",        "Проверяет привязку USDC/DAI/USDT/sUSDS к $1.",                "каждые 5 мин"),
        ("red_flag_monitor",   "Мониторит взломы, аномалии ликвидности.",                     "каждые 5 мин"),
        ("governance_watcher", "DAO голосования (Snapshot / Tally).",                         "каждые 15 мин"),
        ("sky_monitor",        "Параметры sUSDS / GSM протокола Sky.",                        "каждые 15 мин"),
        ("cycle_gap_monitor",  "Контролирует, что торговые циклы не пропускаются.",           "каждые 5 мин"),
        ("cycle_health",       "Диагностика health_score цикла (0–100).",                     "каждые 5 мин"),
        ("uptime_monitor",     "Следит за всеми агентами, источник данных для /agents.",      "каждые 5 мин"),
        ("base_gas_monitor",   "Цена газа в сети Base для Base-chain стратегий.",             "каждые 10 мин"),
        ("bot_commands",       "Этот Telegram бот.",                                          "всегда активен"),
        ("httpserver",         "Веб-дашборд на порту 8080.",                                  "всегда активен"),
        ("cloudflared",        "HTTPS тоннель для доступа к дашборду извне.",                 "не настроен"),
        ("fund-api",           "API для Family Fund инвесторов.",                             "по расписанию"),
        ("autopush",           "Автопуш изменений в GitHub каждые 90 мин.",                  "каждые 90 мин"),
        ("analytics_tier_c",   "180 аналитических модулей Tier-C.",                          "ежедневно 05:00"),
        ("daily-paper-report", "Ежедневный отчёт PDF + Telegram.",                           "ежедневно 08:00"),
        ("checkpoint-7day",    "Недельный снапшот состояния системы.",                        "раз в 7 дней"),
        ("weekly_backup",      "Полный архив всех данных SPA.",                               "раз в неделю"),
    ]

    # Agents that run on a schedule and exit between runs.
    # Showing ❌ when idle is misleading — use ⏸ instead.
    _SCHEDULED_AGENTS = frozenset({
        "launchd_checkpoint-7day",
        "launchd_weekly_backup",
        "launchd_fund-api",
        "launchd_analytics_tier_c",
        "launchd_base_gas_monitor",
        "launchd_sky_monitor",
        "launchd_daily-paper-report",
    })

    # Known probable causes for specific failing agents.
    _KNOWN_WHY: Dict[str, str] = {
        "launchd_cloudflared": (
            "Не настроен (требует браузерная авторизация Cloudflare)"
        ),
        "launchd_cycle_health": (
            "plist не загружен в LaunchAgents — запусти: bash scripts/restart_bot_now.command"
        ),
        "launchd_cycle_gap_monitor": (
            "plist загружен в режиме --check (dry-run), не пишет статус в data/"
        ),
    }

    # ── Command handlers ──────────────────────────────────────────────────

    def cmd_start(self, chat_id: str) -> None:
        text = (
            "👋 <b>SPA Bot v2.1</b>\n\n"
            "Управляй системой SPA через кнопки меню\n"
            "или вводи команды напрямую:\n\n"
            "/status · /portfolio · /today · /week\n"
            "/agents · /alerts · /why\n"
            "/pause · /resume · /menu · /help"
        )
        self.send_message(text, chat_id, reply_markup=self._main_menu_keyboard())

    def cmd_help(self, chat_id: str) -> None:
        text = (
            "📋 <b>Команды SPA Bot v2.1</b>\n\n"
            "/status — статус системы и equity\n"
            "/portfolio — текущая аллокация по протоколам\n"
            "/today — P&amp;L за сегодня\n"
            "/week — недельный отчёт (7 дней)\n"
            "/agents — статус агентов launchd\n"
            "/alerts — активные алерты и peg-мониторинг\n"
            "/why — почему агенты ❌ (диагностика)\n"
            "/pause — kill-switch (поставить на паузу)\n"
            "/resume — снять паузу\n"
            "/menu — интерактивное меню\n"
            "/help — этот список"
        )
        self.send_message(text, chat_id, reply_markup=self._main_menu_keyboard())

    # /menu → same output as /help
    cmd_menu = cmd_help

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

            # ── Policy validation before display ─────────────────────────────
            try:
                from spa_core.risk.policy_enforcer import validate_positions
                val = validate_positions(
                    positions=positions,
                    capital_usd=capital,
                    cash_usd=cash,
                )
                if not val.passed:
                    alert = "⚠️ <b>Портфель нарушает правила политики!</b>\n"
                    for v in val.violations:
                        alert += "🔴 {rule}: {msg}\n".format(
                            rule=v.rule, msg=v.message[:120])
                    self.send_message(alert, chat_id)
                elif val.warnings:
                    alert = "🟡 <b>Предупреждения политики:</b>\n"
                    for w in val.warnings:
                        alert += "• {rule}: {msg}\n".format(
                            rule=w.rule, msg=w.message[:120])
                    self.send_message(alert, chat_id)
            except Exception:
                pass  # validation failure must not break portfolio display

            # Build tier map for display
            _tier_labels = {}
            try:
                from spa_core.risk.policy_enforcer import T1_ADAPTERS, T3_ADAPTERS
                for proto in positions:
                    if proto in T1_ADAPTERS:
                        _tier_labels[proto] = "T1"
                    elif proto in T3_ADAPTERS:
                        _tier_labels[proto] = "T3"
                    else:
                        _tier_labels[proto] = "T2"
            except Exception:
                pass

            lines = ["📊 <b>Portfolio</b>\n"]
            for proto, usd in sorted(positions.items(), key=lambda kv: -float(kv[1] or 0.0)):
                usd_f = float(usd or 0.0)
                pct = usd_f / capital * 100.0 if capital else 0.0
                tier_badge = "[{}]".format(_tier_labels[proto]) if proto in _tier_labels else ""
                lines.append("• {name} {tier}: {amt} ({pct:.1f}%)".format(
                    name=_proto_label(proto), tier=tier_badge,
                    amt=_fmt_usd(usd_f), pct=pct))
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
            n_scheduled = 0
            n_total = 0
            for name, info in sorted(checks.items()):
                running = info.get("running") if isinstance(info, dict) else None
                if running is None:
                    continue  # synthetic/aggregate entries
                n_total += 1
                if running:
                    n_up += 1
                    icon = "✅"
                elif name in self._SCHEDULED_AGENTS:
                    icon = "⏸"   # idle between scheduled runs — expected
                    n_scheduled += 1
                else:
                    icon = "❌"
                label = name.replace("launchd_", "").replace("_", " ")
                lines.append("{icon} {label}".format(icon=icon, label=label))
            lines.append(
                "\n📊 Up: {up}/{tot}  ⏸ Scheduled: {sc}".format(
                    up=n_up, tot=n_total, sc=n_scheduled
                )
            )
            self.send_message(
                "\n".join(lines), chat_id,
                reply_markup=self._agents_info_keyboard(),
            )
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error reading agents: {}".format(type(exc).__name__), chat_id)

    def _cmd_agents_detail(self, chat_id: str) -> None:
        """Show one-line description + interval for every known agent."""
        lines = ["📖 <b>Агенты SPA — справочник</b>\n"]
        for name, desc, interval in self._AGENT_DESCRIPTIONS:
            lines.append(
                "• <b>{name}</b>\n"
                "  {desc}\n"
                "  ⏱ {interval}".format(name=name, desc=desc, interval=interval)
            )
        self.send_message("\n\n".join(lines), chat_id)

    def cmd_why(self, chat_id: str) -> None:
        """Explain likely reasons for each ❌ agent (not scheduled ones)."""
        try:
            doc = _read_json(DATA_DIR / "uptime_status.json", {})
            checks = doc.get("checks", {}) if isinstance(doc, dict) else {}
            check_ts = float(doc.get("ts", 0.0) or 0.0)

            failing = [
                (name, info)
                for name, info in sorted(checks.items())
                if isinstance(info, dict)
                and info.get("running") is False
                and name not in self._SCHEDULED_AGENTS
            ]

            if not failing:
                self.send_message(
                    "✅ <b>Все агенты в норме</b>\nНет агентов со статусом ❌.",
                    chat_id,
                )
                return

            lines = ["🔍 <b>Диагностика ❌ агентов</b>\n"]
            for name, info in failing:
                known = self._KNOWN_WHY.get(name)
                if known:
                    reason = known
                else:
                    # Compute how stale the uptime snapshot is
                    if check_ts:
                        age_min = int((time.time() - check_ts) / 60)
                        reason = (
                            "Не запускался более {n} мин — "
                            "проверь launchd: launchctl list | grep spa"
                        ).format(n=age_min)
                    else:
                        reason = "Нет данных — проверь launchd: launchctl list | grep spa"
                label = name.replace("launchd_", "")
                lines.append("❌ <b>{label}</b>\n   → {reason}".format(
                    label=label, reason=reason))

            self.send_message("\n\n".join(lines), chat_id)
        except Exception as exc:  # noqa: BLE001
            self.send_message("❌ Error in /why: {}".format(type(exc).__name__), chat_id)

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

    def _cmd_detail(self, callback_data: str, chat_id: str) -> None:
        """Handle '📋 Подробнее' inline buttons — show full governance/risk event details.

        Callback data format (from telegram_format_ru.build_detail_keyboard):
            ``detail_{protocol}__{category}``
        Looks up the matching alert in data/red_flags.json and formats a
        detailed Russian-language message via format_alert_detail_ru().
        """
        try:
            from spa_core.alerts.telegram_format_ru import (  # noqa: PLC0415
                format_alert_detail_ru,
                parse_detail_callback,
            )
            parsed = parse_detail_callback(callback_data)
            if parsed is None:
                self.send_message("❌ Неизвестная кнопка.", chat_id)
                return
            protocol, category = parsed

            rf_doc = _read_json(DATA_DIR / "red_flags.json", {})
            flags = rf_doc.get("red_flags", []) if isinstance(rf_doc, dict) else []

            alert: Optional[Dict] = None
            for f in flags:
                if (isinstance(f, dict) and
                        str(f.get("protocol", "")) == protocol and
                        str(f.get("category", "")) == category):
                    alert = f
                    break

            if alert is None:
                # Alert may have been cleared; build a minimal placeholder
                alert = {
                    "protocol": protocol,
                    "category": category,
                    "severity": "INFO",
                    "message": "(событие не найдено в актуальном списке)",
                }

            detail_text = format_alert_detail_ru(alert)
            self.send_message(detail_text, chat_id, parse_mode="Markdown")
        except Exception as exc:  # noqa: BLE001
            self.send_message(
                "❌ Ошибка загрузки деталей: {}".format(type(exc).__name__), chat_id
            )

    # ── BotFather command registration ────────────────────────────────────

    def register_commands(self) -> bool:
        """Register bot commands via setMyCommands (shown in Telegram ☰ menu)."""
        commands = [
            {"command": "start",     "description": "Приветствие и главное меню"},
            {"command": "menu",      "description": "Интерактивное меню кнопок"},
            {"command": "status",    "description": "Статус системы и equity"},
            {"command": "portfolio", "description": "Текущая аллокация по протоколам"},
            {"command": "today",     "description": "P&L за сегодня"},
            {"command": "week",      "description": "Недельный отчёт (7 дней)"},
            {"command": "agents",    "description": "Статус агентов launchd"},
            {"command": "alerts",    "description": "Активные алерты и peg-мониторинг"},
            {"command": "why",       "description": "Диагностика причин ❌ агентов"},
            {"command": "pause",     "description": "Kill-switch (поставить на паузу)"},
            {"command": "resume",    "description": "Снять паузу"},
            {"command": "task",      "description": "Добавить задание в inbox (текст или голосовое)"},
            {"command": "status",    "description": "Сводка системы простым языком"},
            {"command": "help",      "description": "Список всех команд"},
        ]
        result = self._api_call("setMyCommands", {"commands": commands}, timeout=10)
        if result and result.get("ok"):
            log.info("setMyCommands: registered %d commands", len(commands))
            return True
        log.warning("setMyCommands failed: %s", result)
        return False

    # ── Routing ───────────────────────────────────────────────────────────

    _COMMANDS = (
        "/start", "/help", "/menu", "/status", "/portfolio", "/today",
        "/week", "/agents", "/alerts", "/pause", "/resume", "/why",
    )

    def _dispatch(self, text: str, chat_id: str) -> None:
        """Route a command string to its handler. Unknown → help."""
        cmd = text.strip().split()[0].split("@")[0].lower() if text.strip() else ""
        # Handle 'Подробнее' detail callbacks from governance/risk alert buttons.
        # callback_data format: "detail_{protocol}__{category}"
        if cmd.startswith("detail_"):
            self._cmd_detail(text.strip(), chat_id)
            return
        # Handle agents description detail callback
        if cmd == "agents_detail":
            self._cmd_agents_detail(chat_id)
            return
        handlers: Dict[str, Any] = {
            "/start":     self.cmd_start,
            "/help":      self.cmd_help,
            "/menu":      self.cmd_menu,
            "/status":    self.cmd_status,
            "/portfolio": self.cmd_portfolio,
            "/today":     self.cmd_today,
            "/week":      self.cmd_week,
            "/agents":    self.cmd_agents,
            "/alerts":    self.cmd_alerts,
            "/pause":     self.cmd_pause,
            "/resume":    self.cmd_resume,
            "/why":       self.cmd_why,
        }
        handler = handlers.get(cmd)
        if handler is None:
            self.cmd_help(chat_id)
        else:
            handler(chat_id)

    # callback prefixes handled by the legacy command dispatcher (not the menu router)
    _LEGACY_CB_PREFIXES = ("detail_", "agents_detail", "/")

    def handle_update(self, update: Dict) -> None:
        """Process one update — callback_query button or text message. Fail-safe.

        Routes through the interactive menu Router (drill-down via
        editMessageText, owner-auth, EN|RU). Legacy ``detail_``/``agents_detail``
        and old ``/cmd`` callback buttons fall back to the v2 command dispatcher.
        """
        try:
            router = self._get_router()

            cq = update.get("callback_query")
            if isinstance(cq, dict):
                callback_id = str(cq.get("id", ""))
                data = str(cq.get("data", ""))
                message = cq.get("message", {}) or {}
                chat_id = str(message.get("chat", {}).get("id", "")) or self.chat_id
                message_id = message.get("message_id")
                # Legacy inline buttons (old keyboards) → keep old behaviour.
                if data.startswith(self._LEGACY_CB_PREFIXES):
                    self._answer_callback(callback_id)
                    if chat_id and router.is_owner(chat_id):
                        self._dispatch(data, chat_id)
                    return
                # New menu navigation → in-place editMessageText drill-down.
                router.handle_callback(data, chat_id, message_id, callback_id)
                return

            msg = update.get("message")
            if isinstance(msg, dict):
                text = str(msg.get("text", "") or "")
                chat_id = str(msg.get("chat", {}).get("id", "")) or self.chat_id
                if not chat_id:
                    return
                # §6 Inbox intake: /task <text> or a voice message → Inbox card.
                if self._handle_inbox_intake(msg, text, chat_id):
                    return
                # Any command or bare text (re)spawns the Home panel as a new message.
                router.handle_command(text if text.startswith("/") else "/menu", chat_id)
        except Exception as exc:  # noqa: BLE001 — never let one update crash the loop
            log.warning("handle_update failed: %s", exc)

    # ── §6 Inbox intake (/task text + voice → files-first Inbox card) ───────

    def _handle_inbox_intake(self, msg: Dict, text: str, chat_id: str) -> bool:
        """Owner-only: route ``/task <text>`` or a voice message into an Inbox card.

        Returns True if handled (caller must not fall through to the menu). Fail-safe:
        any error replies friendly and still returns True. Non-intake messages → False.
        """
        is_task = text.strip().lower().startswith("/task")
        is_status = text.strip().lower().startswith("/status")
        voice = msg.get("voice") or msg.get("audio")
        is_voice = isinstance(voice, dict) and bool(voice.get("file_id"))
        if not (is_task or is_status or is_voice):
            return False
        import html
        try:
            if not self._get_router().is_owner(chat_id):
                return False  # non-owner → let normal flow answer
            if is_status:
                from spa_core.telegram.status_summary import build_status_summary
                self.send_message(build_status_summary(), chat_id)
                return True
            if is_task:
                task_text = text.strip()[len("/task"):].strip()
                if not task_text:
                    self.send_message(
                        "📥 Использование: <code>/task купить зонт в пятницу</code>\n"
                        "Или пришли голосовое — расшифрую и добавлю в inbox.", chat_id)
                    return True
                from spa_core.telegram.inbox_intake import save_inbox_task
                _path, title = save_inbox_task(task_text, source="telegram")
                self.send_message(
                    f"📥 Добавил в inbox: <b>{html.escape(title)}</b>\n"
                    "Оркестратор разберёт в следующем цикле.", chat_id)
                return True
            # voice
            self.send_message("🎤 Расшифровываю голосовое…", chat_id)
            from spa_core.telegram.inbox_intake import handle_voice_message
            result = handle_voice_message(self.token, str(voice["file_id"]))
            if result is None:
                self.send_message(
                    "🎤 Не смог расшифровать голосовое. Пришли текстом (<code>/task …</code>) "
                    "или запиши ещё раз.", chat_id)
                return True
            _path, transcript = result
            preview = transcript if len(transcript) <= 200 else transcript[:199] + "…"
            self.send_message(
                f"🎤 Расшифровал и добавил в inbox:\n<i>{html.escape(preview)}</i>", chat_id)
            return True
        except Exception as exc:  # noqa: BLE001 — never crash the poll loop
            log.warning("_handle_inbox_intake failed: %s", exc)
            try:
                self.send_message("⚠️ Не удалось обработать задание — попробуй ещё раз.", chat_id)
            except Exception:
                pass
            return True

    # ── Single-instance lock + startup settle (409-on-restart fix) ─────────

    def acquire_single_instance_lock(self) -> bool:
        """Take an exclusive advisory flock so only ONE poller runs at a time.

        A restarting poller can transiently overlap the prior instance's
        getUpdates long-poll → Telegram 409 Conflict streak. Holding this lock
        for the poller's lifetime means a second poller refuses to start instead
        of dueling for getUpdates. Returns True if the lock was acquired (or if
        flock is unavailable — advisory, never blocks a legitimate single bot),
        False if another live poller already holds it.
        """
        if fcntl is None:
            return True  # no POSIX flock → advisory no-op (still single in practice)
        lock_path = self._lock_path()
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(lock_path, "w")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError) as exc:
            log.warning("single-instance lock busy/failed (%s) — another poller "
                        "may be running; refusing to start a duplicate", exc)
            try:
                fh.close()  # type: ignore[has-type]
            except Exception:
                pass
            return False
        self._lock_fh = fh
        try:
            fh.write(str(os.getpid()))
            fh.flush()
        except Exception:
            pass
        return True

    def release_single_instance_lock(self) -> None:
        """Release the advisory flock (best-effort, fail-safe)."""
        fh = self._lock_fh
        self._lock_fh = None
        if fh is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass

    def settle_startup(self) -> None:
        """Quiesce the poll channel on startup so a restart doesn't 409-streak.

        1. deleteWebhook — if a webhook was ever set, getUpdates 409s forever;
           clearing it is idempotent and harmless for a long-poll bot.
        2. A short-timeout getUpdates "settle" drain: if the PRIOR instance is
           still mid long-poll, this returns 409 (or empty); we back off briefly
           and retry a few times until the old poll's timeout lapses and we own
           the channel — turning a noisy 409 streak into a clean, bounded settle.
        Fail-safe: never raises.
        """
        try:
            # disable_webhook is a no-op if none is set; keep pending updates so a
            # legitimate queued command isn't dropped on restart.
            self._api_call("deleteWebhook", {"drop_pending_updates": False}, timeout=10)
        except Exception as exc:  # noqa: BLE001
            log.warning("deleteWebhook on startup failed: %s", exc)
        # Settle drain: short timeout so we don't block; bounded retries.
        for attempt in range(self._MAX_BACKOFF_STEP):
            result = self._api_call("getUpdates",
                                    {"offset": self._offset, "timeout": 0},
                                    timeout=10)
            if result is not None and result.get("ok"):
                self._conflict_streak = 0
                return  # we own the channel
            if self._last_status == 409:
                backoff = min(2 ** (attempt + 1), self._MAX_BACKOFF_S)
                log.warning("startup settle: prior poller still active (409) — "
                            "wait %ds (attempt %d)", backoff, attempt + 1)
                time.sleep(backoff)
                continue
            # non-409 failure (outage) — stop settling; the main loop's backoff
            # handles it. Don't burn the whole settle budget on a dead network.
            return

    # ── Polling loops ─────────────────────────────────────────────────────

    def run_once(self) -> int:
        """Drain pending updates once, dispatch, return count processed."""
        updates = self.get_updates()
        for upd in updates:
            self.handle_update(upd)
        return len(updates)

    def run_polling(self) -> None:
        """Continuous long-polling loop. Fail-safe; never returns normally."""
        # Single-instance guard: refuse to start a second poller (would 409 the
        # incumbent). Then settle the channel so a restart doesn't 409-streak.
        if not self.acquire_single_instance_lock():
            log.error("another SPA bot poller already holds the lock — exiting to "
                      "avoid a getUpdates 409 conflict.")
            return
        log.warning("SPA Bot v2.1 started (offset=%d)", self._offset)
        self.settle_startup()
        # Register commands in Telegram ☰ menu once at startup.
        self.register_commands()
        try:
            while True:
                try:
                    for upd in self.get_updates():
                        self.handle_update(upd)
                except Exception as exc:  # noqa: BLE001
                    log.warning("polling error: %s — retry in 5s", exc)
                    time.sleep(5)
        finally:
            self.release_single_instance_lock()


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

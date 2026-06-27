"""Tests for spa_core/telegram/bot.py — SPA Telegram Bot v2.0.

Each test stubs the network (TelegramBot._api_call) and points DATA_DIR /
KILL_SWITCH_FILE at a temp dir, so nothing touches the real Keychain,
Telegram API, or repo data. Run:

    python3 -m pytest tests/test_telegram_bot_v2.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the project root importable
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import spa_core.telegram.bot as bot_mod  # noqa: E402
from spa_core.telegram.bot import TelegramBot  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirect the module's data paths into a temp dir and seed JSON files."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(bot_mod, "DATA_DIR", d)
    monkeypatch.setattr(bot_mod, "OFFSET_FILE", d / "tg_bot_v2_offset.json")
    monkeypatch.setattr(bot_mod, "KILL_SWITCH_FILE", d / "kill_switch_active.json")

    (d / "paper_trading_status.json").write_text(json.dumps({
        "current_equity": 100047.74,
        "total_return_pct": 0.0477,
        "daily_return_pct": 0.010821,
        "apy_today_pct": 3.9493,
        "daily_yield_usd": 10.8253,
        "days_running": 26,
        "last_cycle_ts": "2026-06-14T15:32:21.055522+00:00",
        "last_trade_id": None,
    }))
    (d / "current_positions.json").write_text(json.dumps({
        "capital_usd": 100000.0,
        "cash_usd": 5000.01,
        "positions": {
            "aave_v3": 23750.0,
            "compound_v3": 38000.0,
            "yearn_v3": 11312.02,
        },
    }))
    (d / "equity_curve_daily.json").write_text(json.dumps({
        "summary": {"num_days": 5},
        "daily": [
            {"date": "2026-06-10", "close_equity": 100008.61, "daily_return_pct": 0.0086},
            {"date": "2026-06-11", "close_equity": 100017.0, "daily_return_pct": 0.0084},
            {"date": "2026-06-12", "close_equity": 100028.0, "daily_return_pct": 0.011},
            {"date": "2026-06-13", "close_equity": 100039.0, "daily_return_pct": 0.011},
            {"date": "2026-06-14", "close_equity": 100047.74, "daily_return_pct": 0.0087},
        ],
    }))
    (d / "uptime_status.json").write_text(json.dumps({
        "all_ok": False,
        "checks": {
            "launchd_httpserver": {"running": True},
            "launchd_cloudflared": {"running": False},
            "launchd_peg_monitor": {"running": True},
            "http_server": {"running": None},  # synthetic — skipped
        },
    }))
    (d / "red_flags.json").write_text(json.dumps({
        "red_flags": [
            {"protocol": "aave-v3", "category": "governance_proposal",
             "severity": "CRITICAL", "message": "Risk-sensitive proposal"},
        ],
    }))
    (d / "peg_report.json").write_text(json.dumps({
        "overall_status": "GREEN", "critical": 0, "warning": 0,
    }))
    return d


@pytest.fixture
def bot(data_dir):
    """A bot with credentials injected and network stubbed; records all sends."""
    b = TelegramBot(token="TESTTOKEN", chat_id="999")
    b.sent = []

    def fake_api(method, params=None, timeout=None):
        b.sent.append({"method": method, "params": params or {}})
        if method == "getUpdates":
            return {"ok": True, "result": []}
        return {"ok": True, "result": {}}

    b._api_call = fake_api  # type: ignore[assignment]
    return b


def _last_text(b):
    sends = [s for s in b.sent if s["method"] == "sendMessage"]
    return sends[-1]["params"]["text"] if sends else ""


# ─── Command formatting ──────────────────────────────────────────────────────


def test_cmd_status_formats_correctly(bot):
    bot.cmd_status("999")
    text = _last_text(bot)
    assert "SPA Status" in text
    assert "100,047.74" in text
    assert "3.95%" in text  # APY today rounded
    assert "INACTIVE" in text  # kill-switch file absent → inactive


def test_cmd_portfolio_shows_allocations(bot):
    bot.cmd_portfolio("999")
    text = _last_text(bot)
    assert "Portfolio" in text
    assert "Compound V3" in text
    assert "38.0%" in text  # 38000 / 100000
    assert "Cash" in text


def test_cmd_today_shows_pnl(bot):
    bot.cmd_today("999")
    text = _last_text(bot)
    assert "Today" in text
    assert "APY Today: 3.95%" in text
    assert "Trades: 0" in text


def test_cmd_week_summary(bot):
    bot.cmd_week("999")
    text = _last_text(bot)
    assert "Week" in text
    assert "2026-06-10" in text and "2026-06-14" in text
    assert "Profitable: 5/5" in text  # all 5 days positive


def test_cmd_agents_shows_all_agents(bot):
    bot.cmd_agents("999")
    text = _last_text(bot)
    assert "Agents" in text
    assert "httpserver" in text
    assert "✅" in text and "❌" in text
    assert "Up: 2/3" in text  # synthetic http_server (None) skipped


def test_cmd_alerts_reads_red_flags(bot):
    bot.cmd_alerts("999")
    text = _last_text(bot)
    assert "Alerts" in text
    assert "CRITICAL" in text
    assert "Aave V3" in text
    assert "Peg monitor" in text and "GREEN" in text


def test_cmd_pause_writes_kill_switch(bot, data_dir):
    bot.cmd_pause("999")
    doc = json.loads((data_dir / "kill_switch_active.json").read_text())
    assert doc["active"] is True
    assert doc["reason"] == "manual_telegram"
    # resume button offered
    sends = [s for s in bot.sent if s["method"] == "sendMessage"]
    assert "reply_markup" in sends[-1]["params"]


def test_cmd_resume_clears_kill_switch(bot, data_dir):
    bot.cmd_pause("999")
    bot.cmd_resume("999")
    doc = json.loads((data_dir / "kill_switch_active.json").read_text())
    assert doc["active"] is False
    assert doc["reason"] == "manual_telegram_resume"


# ─── Credentials & robustness ────────────────────────────────────────────────


def test_token_from_env_fallback(monkeypatch):
    monkeypatch.setattr(bot_mod, "_read_keychain", lambda service: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_SPA", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "ENVTOKEN123")
    assert bot_mod.get_token() == "ENVTOKEN123"


def test_missing_data_file_graceful(bot, data_dir):
    (data_dir / "paper_trading_status.json").unlink()
    bot.cmd_status("999")  # must not raise
    text = _last_text(bot)
    # equity defaults to 0 → still a status message, no crash
    assert "SPA Status" in text


def test_api_call_failure_graceful(data_dir):
    b = TelegramBot(token="T", chat_id="999")

    def boom(method, params=None, timeout=None):
        if method == "getUpdates":
            return None  # simulated network failure
        return None

    b._api_call = boom  # type: ignore[assignment]
    assert b.get_updates() == []  # no crash, empty list


def test_get_updates_advances_offset(data_dir):
    b = TelegramBot(token="T", chat_id="999")
    calls = {"n": 0}

    def fake(method, params=None, timeout=None):
        calls["n"] += 1
        if method == "getUpdates":
            return {"ok": True, "result": [
                {"update_id": 5001, "message": {"text": "/help",
                                                "chat": {"id": 999}}},
                {"update_id": 5002, "message": {"text": "/status",
                                                "chat": {"id": 999}}},
            ]}
        return {"ok": True, "result": {}}

    b._api_call = fake  # type: ignore[assignment]
    b.get_updates()
    assert b._offset == 5003  # last update_id + 1
    saved = json.loads((bot_mod.OFFSET_FILE).read_text())
    assert saved["offset"] == 5003


def test_handle_update_routes_correctly(bot):
    # Interactive rebuild: a command (re)spawns the Home panel (UX §3).
    bot.handle_update({"update_id": 1, "message": {"text": "/status",
                                                   "chat": {"id": 999}}})
    assert "SPA Monitor" in _last_text(bot)


def test_send_message_formats_html(bot):
    bot.send_message("<b>hi</b>", "999")
    send = [s for s in bot.sent if s["method"] == "sendMessage"][-1]
    assert send["params"]["parse_mode"] == "HTML"
    assert send["params"]["chat_id"] == "999"


def test_unknown_command_shows_help(bot):
    # Interactive rebuild: any unknown command falls back to the Home panel.
    bot.handle_update({"update_id": 2, "message": {"text": "/frobnicate",
                                                   "chat": {"id": 999}}})
    text = _last_text(bot)
    assert "SPA Monitor" in text  # Home panel is the universal fallback


def test_callback_query_answered_and_dispatched(bot):
    bot.handle_update({
        "update_id": 3,
        "callback_query": {
            "id": "cb1", "data": "/portfolio",
            "message": {"chat": {"id": 999}},
        },
    })
    methods = [s["method"] for s in bot.sent]
    assert "answerCallbackQuery" in methods
    assert "Portfolio" in _last_text(bot)


def test_all_commands_respond_without_crash(bot):
    for cmd in TelegramBot._COMMANDS:
        bot.sent = []
        bot._dispatch(cmd, "999")
        assert any(s["method"] == "sendMessage" for s in bot.sent), cmd

"""SPA Telegram bot — safety boundaries found by the 2026-09-30 Owner Control Plane audit.

Each test replays a defect that existed on origin/main f1c089ed4:

* ``/resume`` wrote ``active: false`` over ANY manual kill-switch latch, whoever armed it;
* the free-text classifier ran ``claude -p … --dangerously-skip-permissions`` in the production
  tree — a headless agent with full permissions on every owner message;
* a reply longer than Telegram's 4096 limit was refused by the Bot API and the owner saw nothing;
* the ☰ menu advertised /pause, /resume, /why, /help — typed, each only opened the home panel.

Hermetic: the kill-switch file lives in tmp, nothing is sent, the classifier binary is never run.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from spa_core.telegram import ask_router
from spa_core.telegram import bot as B


class _Rec:
    def __init__(self):
        self.sent = []

    def __call__(self, text, chat_id=None, **kw):
        self.sent.append(text)
        return {"ok": True}


@pytest.fixture
def kbot(tmp_path, monkeypatch):
    ks = tmp_path / "kill_switch_active.json"
    monkeypatch.setattr(B, "KILL_SWITCH_FILE", ks)
    bot = object.__new__(B.TelegramBot)
    rec = _Rec()
    bot.send_message = rec
    return bot, ks, rec


def test_resume_lifts_only_the_stop_telegram_armed(kbot):
    bot, ks, rec = kbot
    bot.cmd_pause("1")
    assert json.loads(ks.read_text())["active"] is True
    bot.cmd_resume("1")
    assert json.loads(ks.read_text())["active"] is False


@pytest.mark.parametrize("reason", ["execution_safety", "incident_commander", "", None])
def test_resume_refuses_a_latch_armed_elsewhere(kbot, reason):
    bot, ks, rec = kbot
    doc = {"active": True, "reason": reason}
    ks.write_text(json.dumps(doc))
    bot.cmd_resume("1")
    assert json.loads(ks.read_text()) == doc            # untouched
    assert "НЕ из Telegram" in rec.sent[-1]


def test_resume_is_fail_closed_on_an_unreadable_latch(kbot):
    bot, ks, rec = kbot
    ks.write_text("{broken")
    bot.cmd_resume("1")
    assert ks.read_text() == "{broken" and "вслепую" in rec.sent[-1]


def test_classifier_runs_with_no_tools_no_mcp_and_outside_the_repo(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, stdout="TASK\n", stderr="")

    monkeypatch.setattr(ask_router, "_build_context", lambda: "ctx")
    monkeypatch.setattr(ask_router.subprocess, "run", fake_run)
    assert ask_router.classify_and_answer("проверь Morpho")[0] == "task"
    cmd = seen["cmd"]
    assert "--dangerously-skip-permissions" not in cmd
    i = cmd.index("--tools")
    assert cmd[i + 1] == "" and "--strict-mcp-config" in cmd
    assert seen["cwd"] and "SPA_Claude" not in str(seen["cwd"])


def test_long_replies_are_clipped_not_dropped():
    long_html = "<b>x</b> " + "а" * 6000
    out = B._fit_telegram(long_html, "HTML")
    assert len(out) <= B.TG_TEXT_LIMIT and out.endswith("(сокращено)")
    assert "<b>" not in out                              # never cut HTML mid-tag
    assert B._fit_telegram("short <b>ok</b>", "HTML") == "short <b>ok</b>"
    emoji = "🙂" * 3000                                   # 6000 UTF-16 units
    assert len(B._fit_telegram(emoji, None).encode("utf-16-le")) // 2 <= B.TG_TEXT_LIMIT


def test_menu_advertises_only_commands_that_do_what_they_say(monkeypatch):
    sent = {}
    bot = object.__new__(B.TelegramBot)
    monkeypatch.setattr(bot, "_api_call", lambda m, p, timeout=None: sent.update(p) or {"ok": True},
                        raising=False)
    bot.register_commands()
    names = [c["command"] for c in sent["commands"]]
    assert not {"pause", "resume", "why", "help"} & set(names)
    assert len(names) == len(set(names))                  # /status was registered twice
    from spa_core.telegram.router import COMMAND_TO_PATH
    for n in names:
        assert n in ("status", "task") or f"/{n}" in COMMAND_TO_PATH, n

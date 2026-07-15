"""Tests for the Telegram Q&A router (classify question/task/unclear)."""

from __future__ import annotations

import subprocess
import types

from spa_core.telegram import ask_router


def _fake_claude(stdout: str, rc: int = 0):
    def _run(cmd, capture_output, text, timeout, env):  # noqa: ANN001
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return _run


def test_question(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude("QUESTION\nСегодня работает 54 агента, всё зелёное."))
    kind, resp = ask_router.classify_and_answer("сколько агентов работает?")
    assert kind == "question"
    assert "54 агента" in resp


def test_task(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude("TASK"))
    kind, resp = ask_router.classify_and_answer("почини график на дашборде")
    assert kind == "task"
    assert resp == ""


def test_unclear(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude("UNCLEAR\nЭто вопрос про статус или просьба что-то сделать?"))
    kind, resp = ask_router.classify_and_answer("дашборд")
    assert kind == "unclear"
    assert "?" in resp


def test_claude_failure_is_failsafe(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no claude")
    monkeypatch.setattr(subprocess, "run", _boom)
    kind, resp = ask_router.classify_and_answer("что нового?")
    assert kind == "unclear"
    assert resp  # friendly fallback message


def test_malformed_output_falls_back_to_answer(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude("просто какой-то ответ без маркера"))
    kind, resp = ask_router.classify_and_answer("привет")
    assert kind == "question"
    assert "какой-то ответ" in resp

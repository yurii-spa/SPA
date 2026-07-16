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


# ── Fail-safe branches (documented contract: any error → 'unclear') ────────────
# Regression cover for the live owner-message classifier: a claude non-zero exit,
# an empty/whitespace answer, and a subprocess timeout must NEVER crash the bot or
# misclassify as task/question — they must all degrade to a friendly 'unclear'.


def test_nonzero_exit_is_failsafe(monkeypatch):
    # claude exits non-zero (rate-limit / auth / crash) even with some stdout →
    # must fail-safe to 'unclear', not treat the stray stdout as an answer.
    monkeypatch.setattr(subprocess, "run", _fake_claude("QUESTION\nстарый кэш", rc=1))
    kind, resp = ask_router.classify_and_answer("что нового?")
    assert kind == "unclear"
    assert resp  # friendly fallback message, not the stale stdout
    assert "старый кэш" not in resp


def test_empty_output_is_failsafe(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude(""))
    kind, resp = ask_router.classify_and_answer("что по агентам?")
    assert kind == "unclear"
    assert resp  # non-empty friendly fallback


def test_whitespace_only_output_is_failsafe(monkeypatch):
    # stdout that strips to empty must be treated as empty (fail-safe), not as a
    # blank 'question' answer.
    monkeypatch.setattr(subprocess, "run", _fake_claude("   \n \t "))
    kind, resp = ask_router.classify_and_answer("?")
    assert kind == "unclear"
    assert resp


def test_timeout_is_failsafe(monkeypatch):
    # The single most likely real-world failure (a slow headless claude) is a
    # TimeoutExpired — the generic except must catch it → friendly 'unclear'.
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=120)
    monkeypatch.setattr(subprocess, "run", _timeout)
    kind, resp = ask_router.classify_and_answer("расскажи статус")
    assert kind == "unclear"
    assert resp


def test_unclear_without_second_line_uses_default_question(monkeypatch):
    # Model returns the UNCLEAR marker but no clarifying line → the router must
    # still supply a default clarifying question (never an empty prompt).
    monkeypatch.setattr(subprocess, "run", _fake_claude("UNCLEAR"))
    kind, resp = ask_router.classify_and_answer("дашборд")
    assert kind == "unclear"
    assert resp.strip()  # default clarifying question, not empty
    assert "?" in resp


def test_question_empty_body_uses_placeholder(monkeypatch):
    # QUESTION marker with an empty body → a placeholder, never an empty answer.
    monkeypatch.setattr(subprocess, "run", _fake_claude("QUESTION\n   "))
    kind, resp = ask_router.classify_and_answer("статус?")
    assert kind == "question"
    assert resp.strip()  # placeholder, not blank


def test_marker_is_case_and_whitespace_insensitive(monkeypatch):
    # LLM casing is nondeterministic: 'task', 'Task', ' TASK ' must all classify
    # as a task (head = first.strip().upper()). Locks in the marker robustness.
    for raw in ("task", "Task", "  TASK  ", "task\n"):
        monkeypatch.setattr(subprocess, "run", _fake_claude(raw))
        kind, resp = ask_router.classify_and_answer("почини график")
        assert kind == "task", raw
        assert resp == "", raw


def test_question_marker_case_insensitive_keeps_answer(monkeypatch):
    # A lowercase 'question' marker must still return the following body as answer.
    monkeypatch.setattr(subprocess, "run", _fake_claude("question\n54 агента, всё зелёное."))
    kind, resp = ask_router.classify_and_answer("сколько агентов?")
    assert kind == "question"
    assert "54 агента" in resp

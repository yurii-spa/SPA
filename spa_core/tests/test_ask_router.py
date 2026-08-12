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
    assert kind == ask_router.UNAVAILABLE
    assert kind != "unclear"
    assert resp  # friendly fallback message


def test_malformed_output_falls_back_to_answer(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude("просто какой-то ответ без маркера"))
    kind, resp = ask_router.classify_and_answer("привет")
    assert kind == "question"
    assert "какой-то ответ" in resp


# ── Классификатор не ответил → вид UNAVAILABLE, а НЕ вердикт 'unclear' ────────
#
# ИЗМЕНЕНИЕ ТЕСТОВ НАМЕРЕННОЕ (инв. #16), обоснование — авария 11.08.2026.
# Эти четыре теста существовали и БЫЛИ ЗЕЛЁНЫМИ всё время, пока дефект работал: они
# проверяли, что падение `claude` не роняет бота и даёт дружелюбный текст, — и ни один
# не спрашивал, во что этот текст превратится у ВЫЗЫВАЮЩЕГО. А превращался он в карточку-
# вопрос владельцу: 11.08 их родилось 44 при нуле настоящих вопросов, и 44 задания были
# закрыты как `done`. Тесты не ослаблены, а УСИЛЕНЫ: к прежним утверждениям добавлено
# главное — вид отличается от 'unclear' (вердикта о тексте владельца), поэтому вызывающий
# больше не может принять «не у кого спросить» за «спросили, ответили непонятно».
# Проверка ЭФФЕКТА (карточек не рождается, исходник не закрывается) — в
# test_owner_intake.py::test_classifier_outage_* и test_bot_classify_route.py.


def test_nonzero_exit_is_failsafe(monkeypatch):
    # claude exits non-zero (rate-limit / auth / crash) even with some stdout →
    # must report UNAVAILABLE, not treat the stray stdout as an answer.
    monkeypatch.setattr(subprocess, "run", _fake_claude("QUESTION\nстарый кэш", rc=1))
    kind, resp = ask_router.classify_and_answer("что нового?")
    assert kind == ask_router.UNAVAILABLE
    assert kind != "unclear"
    assert resp  # friendly fallback message, not the stale stdout
    assert "старый кэш" not in resp


def test_empty_output_is_failsafe(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_claude(""))
    kind, resp = ask_router.classify_and_answer("что по агентам?")
    assert kind == ask_router.UNAVAILABLE
    assert kind != "unclear"
    assert resp  # non-empty friendly fallback


def test_whitespace_only_output_is_failsafe(monkeypatch):
    # stdout that strips to empty must be treated as empty (UNAVAILABLE), not as a
    # blank 'question' answer.
    monkeypatch.setattr(subprocess, "run", _fake_claude("   \n \t "))
    kind, resp = ask_router.classify_and_answer("?")
    assert kind == ask_router.UNAVAILABLE
    assert kind != "unclear"
    assert resp


def test_timeout_is_failsafe(monkeypatch):
    # The single most likely real-world failure (a slow headless claude) is a
    # TimeoutExpired — the generic except must catch it → UNAVAILABLE.
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=120)
    monkeypatch.setattr(subprocess, "run", _timeout)
    kind, resp = ask_router.classify_and_answer("расскажи статус")
    assert kind == ask_router.UNAVAILABLE
    assert kind != "unclear"
    assert resp


def test_model_unclear_verdict_is_not_unavailable(monkeypatch):
    """Обратный контроль: НАСТОЯЩЕЕ «непонятно» от модели должно остаться 'unclear'.

    Иначе починка выродилась бы в другую крайность — переспросить владельца стало бы
    нельзя вообще. Живой классификатор, сказавший UNCLEAR, — это вердикт о тексте.
    """
    monkeypatch.setattr(subprocess, "run", _fake_claude("UNCLEAR\nЭто про сайт или про агентов?"))
    kind, resp = ask_router.classify_and_answer("дашборд")
    assert kind == "unclear"
    assert kind != ask_router.UNAVAILABLE
    assert "?" in resp


def test_unavailable_kind_is_distinct_constant():
    """Вид недоступности не должен случайно совпасть ни с одним вердиктом о тексте."""
    assert ask_router.UNAVAILABLE not in {"question", "task", "unclear"}


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

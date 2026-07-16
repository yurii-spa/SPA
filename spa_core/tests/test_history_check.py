"""Regression tests for the inbox history-check dedup step (ORCHESTRATOR_PROTOCOL §6.6).

`history_check.history_check()` is the mandatory pre-card dedup gate: it shells out to a
local `claude -p` for a semantic verdict, then parses the FIRST line into one of
{DONE, IN_PROGRESS, REJECTED, PARTIAL, NEW}. The contract that must never silently break:

  * fail-safe — ANY error (subprocess raises / non-zero exit / empty output / garbage
    verdict) MUST degrade to verdict NEW, so an owner task is never lost (a spurious card
    is cheaper than a dropped task);
  * the verdict is the FIRST whitespace-delimited token of the first line, upper-cased;
  * the human-readable response is everything after the first line.

These tests mock the subprocess (no real `claude` binary, no network) so they run offline
and deterministically in CI. Only `_build_history_context` is exercised against the real
repo, as a smoke test of the deterministic gather step.
"""
from __future__ import annotations

import subprocess

import pytest

from spa_core.owner_queue import history_check as hc


# --------------------------------------------------------------------------- helpers
class _Proc:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _patch_run(monkeypatch, *, stdout="", returncode=0, exc=None):
    """Patch subprocess.run in the history_check module.

    Also stubs the context builder so tests neither read the real repo nor depend on
    its contents when exercising verdict parsing.
    """
    monkeypatch.setattr(hc, "_build_history_context", lambda *a, **k: "CTX")

    def fake_run(*args, **kwargs):
        if exc is not None:
            raise exc
        return _Proc(stdout=stdout, returncode=returncode)

    monkeypatch.setattr(hc.subprocess, "run", fake_run)


# --------------------------------------------------------------------------- is_duplicate
@pytest.mark.parametrize("verdict", ["DONE", "IN_PROGRESS", "REJECTED"])
def test_is_duplicate_true_for_settled_verdicts(verdict):
    assert hc.is_duplicate(verdict) is True


@pytest.mark.parametrize("verdict", ["PARTIAL", "NEW", "", "unknown", "done"])
def test_is_duplicate_false_otherwise(verdict):
    # Only the exact upper-case settled verdicts suppress a card; anything else lets it through.
    assert hc.is_duplicate(verdict) is False


# --------------------------------------------------------------------------- empty input
def test_empty_text_returns_new_without_subprocess(monkeypatch):
    # Guard: must NOT shell out on empty input (would be a wasted claude call).
    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called for empty text")

    monkeypatch.setattr(hc.subprocess, "run", boom)
    for txt in ("", "   ", "\n\t "):
        res = hc.history_check(txt)
        assert res == {"verdict": "NEW", "response": "", "raw": ""}


# --------------------------------------------------------------------------- happy path parsing
def test_valid_verdict_and_response_extracted(monkeypatch):
    _patch_run(monkeypatch, stdout="IN_PROGRESS\nУже в работе, карточка own-42.")
    res = hc.history_check("сделай дашборд")
    assert res["verdict"] == "IN_PROGRESS"
    assert res["response"] == "Уже в работе, карточка own-42."
    assert res["raw"] == "IN_PROGRESS\nУже в работе, карточка own-42."


def test_multiline_response_body_preserved(monkeypatch):
    _patch_run(
        monkeypatch,
        stdout="DONE\nЭто уже сделано 2026-07-15.\nСм. commit e01e042f.",
    )
    res = hc.history_check("напиши спеку уведомлений")
    assert res["verdict"] == "DONE"
    assert res["response"] == "Это уже сделано 2026-07-15.\nСм. commit e01e042f."


def test_verdict_is_first_token_upper_cased(monkeypatch):
    # Model may append a dash-clause on the verdict line or lower-case it.
    _patch_run(monkeypatch, stdout="rejected — решили не делать\nADR-050, причина: ...")
    res = hc.history_check("открой внешний капитал")
    assert res["verdict"] == "REJECTED"
    assert res["response"] == "ADR-050, причина: ..."


def test_new_verdict_single_line(monkeypatch):
    _patch_run(monkeypatch, stdout="NEW\nСовпадений в памяти нет.")
    res = hc.history_check("совершенно новая идея")
    assert res["verdict"] == "NEW"
    assert res["response"] == "Совпадений в памяти нет."


# --------------------------------------------------------------------------- fail-safe → NEW
def test_garbage_verdict_falls_back_to_new_but_keeps_raw(monkeypatch):
    _patch_run(monkeypatch, stdout="MAYBE_SORTA\nне уверен")
    res = hc.history_check("нечто")
    assert res["verdict"] == "NEW"
    assert res["response"] == ""
    # raw is preserved so a human can inspect what the model actually said.
    assert res["raw"] == "MAYBE_SORTA\nне уверен"


def test_nonzero_exit_falls_back_to_new(monkeypatch):
    _patch_run(monkeypatch, stdout="DONE\nвсё готово", returncode=3)
    res = hc.history_check("нечто")
    assert res == {"verdict": "NEW", "response": "", "raw": ""}


def test_subprocess_exception_falls_back_to_new(monkeypatch):
    _patch_run(monkeypatch, exc=subprocess.TimeoutExpired(cmd="claude", timeout=120))
    res = hc.history_check("нечто")
    assert res == {"verdict": "NEW", "response": "", "raw": ""}


def test_empty_stdout_falls_back_to_new(monkeypatch):
    _patch_run(monkeypatch, stdout="   \n  ")
    res = hc.history_check("нечто")
    assert res == {"verdict": "NEW", "response": "", "raw": ""}


def test_generic_exception_falls_back_to_new(monkeypatch):
    _patch_run(monkeypatch, exc=OSError("claude binary not found"))
    res = hc.history_check("нечто")
    assert res == {"verdict": "NEW", "response": "", "raw": ""}


# --------------------------------------------------------------------------- context builder smoke
def test_build_history_context_is_string_and_bounded():
    # Runs against the real repo: must never raise, always return a bounded str.
    ctx = hc._build_history_context(max_chars=500)
    assert isinstance(ctx, str)
    assert len(ctx) <= 500


def test_build_history_context_survives_empty_repo(monkeypatch, tmp_path):
    # Point the module at an empty dir → every source missing → still a clean empty-ish str,
    # never an exception (fail-safe gather).
    monkeypatch.setattr(hc, "_REPO", tmp_path)

    class _NoCards(Exception):
        pass

    def boom_cards():
        raise _NoCards

    # list_cards is imported inside the function; patch at its source module.
    import spa_core.owner_queue.queue as q

    monkeypatch.setattr(q, "list_cards", boom_cards)
    ctx = hc._build_history_context()
    assert isinstance(ctx, str)


def test_history_check_passes_message_into_prompt(monkeypatch):
    # Verify the owner's text actually reaches the claude prompt (truncated to 4000 chars).
    captured = {}
    monkeypatch.setattr(hc, "_build_history_context", lambda *a, **k: "CTX")

    def fake_run(cmd, *args, **kwargs):
        # cmd == [_CLAUDE, "-p", prompt]
        captured["prompt"] = cmd[-1]
        return _Proc(stdout="NEW\nнет")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    hc.history_check("уникальный-маркер-задания-XYZ")
    assert "уникальный-маркер-задания-XYZ" in captured["prompt"]
    assert "CTX" in captured["prompt"]

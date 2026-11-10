"""history_check's classifier must run `claude -p` without tools, without MCP and outside the repo.

Pins the remedy applied to ask_router on 2026-09-30 to the second live classifier on the owner's
intake path (intake.py → history_check). Before this pin history_check ran a plain `claude -p`
from the caller's cwd (the production tree), so built-in read tools and any MCP servers configured
for that directory were reachable by a headless agent on every owner message.

All tests mock subprocess.run — no real `claude`, no network. The fail-safe contract of
test_history_check.py (ANY classifier failure → verdict NEW, the owner's item is never dropped)
must keep holding with the new flags, so it is re-asserted here on the exact argv.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from spa_core.owner_queue import history_check as hc
from spa_core.telegram import ask_router


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _capture(monkeypatch, *, stdout="NEW", returncode=0, exc=None):
    calls = []
    monkeypatch.setattr(hc, "_build_history_context", lambda *a, **k: "CTX")
    monkeypatch.setattr(hc, "exact_prior_ask", lambda *a, **k: None)

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if exc is not None:
            raise exc
        return _Proc(stdout=stdout, returncode=returncode)

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    return calls


def test_flags_identical_to_ask_router():
    # Single remedy for both live classifiers; a drift here would silently reopen one of them.
    assert hc.CLASSIFIER_FLAGS == ask_router.CLASSIFIER_FLAGS == ("--tools", "", "--strict-mcp-config")


def test_classifier_runs_without_tools_without_mcp_outside_repo(monkeypatch):
    calls = _capture(monkeypatch, stdout="DONE\nуже сделано")
    res = hc.history_check("сделай отчёт по книге")
    assert res["verdict"] == "DONE" and res["response"] == "уже сделано"
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv[0] == hc._CLAUDE and argv[1] == "-p"
    assert argv[-3:] == ["--tools", "", "--strict-mcp-config"]            # no built-in tools, no MCP servers
    assert "--dangerously-skip-permissions" not in argv
    assert kw["cwd"] == hc._SAFE_CWD == tempfile.gettempdir()             # not the production tree
    assert not os.path.exists(os.path.join(kw["cwd"], ".mcp.json"))       # nothing to pick up there
    assert kw["capture_output"] is True and kw["text"] is True and "timeout" in kw and "env" in kw


def test_prompt_is_passed_verbatim_before_flags(monkeypatch):
    calls = _capture(monkeypatch)
    hc.history_check("владелец: проверь очередь")
    argv, _ = calls[0]
    assert "владелец: проверь очередь" in argv[2] and argv[2].startswith(hc._PROMPT[:20])


@pytest.mark.parametrize("failure", [
    {"exc": OSError("no claude")},
    {"exc": TimeoutError("slow")},
    {"returncode": 1, "stdout": "DONE\nстарый кэш"},   # non-zero exit must not be trusted
    {"stdout": ""},
    {"stdout": "просто текст без вердикта"},
])
def test_failsafe_new_is_preserved_with_new_flags(monkeypatch, failure):
    # The owner's item is never lost: every classifier failure degrades to NEW (a card is created).
    calls = _capture(monkeypatch, **failure)
    res = hc.history_check("добавь лимит на Base")
    assert res["verdict"] == "NEW" and res["response"] == ""
    assert hc.is_duplicate(res["verdict"]) is False
    assert calls and calls[0][0][-3:] == ["--tools", "", "--strict-mcp-config"] and calls[0][1]["cwd"] == hc._SAFE_CWD


def test_exact_prior_ask_short_circuit_still_avoids_subprocess(monkeypatch):
    # Deterministic path (ADR-202) stays ahead of the model and never shells out.
    monkeypatch.setattr(hc, "exact_prior_ask", lambda *a, **k: {"card": "x", "title": "t", "status": "done", "answer": "a", "ts": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(hc, "_prior_ask_response", lambda hit: "ответ есть")

    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called when an exact prior ask exists")

    monkeypatch.setattr(hc.subprocess, "run", boom)
    assert hc.history_check("тот же вопрос")["verdict"] == "PARTIAL"

# LLM_FORBIDDEN
"""`memory.answer.ask` через общий контракт провайдера (STUDIO-OS-MODELS-01, инкремент 3) — контроли.

Модель не зовётся: тестовый адаптер или подменённый запуск Claude. Сборщик контекста (существующий
`assembler`, не менялся) подменён маленьким пакетом — проверяется ПЕРЕВОД вызывающего, а не поиск.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.studio_os.memory import answer
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles import contract as c

OLD_KEYS = {"question", "answer", "rc", "context_chars", "assemble_ms", "answer_s", "sufficiency"}
_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _small_package(monkeypatch):
    monkeypatch.setattr(answer.asm, "assemble",
                        lambda q, budget_chars=12000: {"evidence_sufficiency": {"verdict": "SUFFICIENT"}})
    monkeypatch.setattr(answer.asm, "render_markdown", lambda pkg: "CONTEXT: verified d12af8deb [ref1]")


def _claude(seen, rc=0, out=None, err=""):
    def runner(cmd, timeout_s, log_path, out_path, cwd=None):
        seen.append({"cmd": cmd, "timeout_s": timeout_s})
        out_path.write_text(json.dumps(out) if out is not None else "", encoding="utf-8")
        log_path.write_text(err, encoding="utf-8")
        return rc
    return runner


_OK = {"is_error": False, "result": "d12af8deb [ref1]", "usage": {"input_tokens": 9, "output_tokens": 4},
       "total_cost_usd": 0.001, "modelUsage": {"m": {}}}


def test_the_existing_result_format_is_kept_and_extended():
    r = answer.ask("SHA?", provider="fixture_test_adapter", adapters={"fixture": ad.fixture({"*": "d12af8deb"})})
    assert OLD_KEYS <= set(r) and r["answer"] == "d12af8deb" and r["rc"] == 0
    assert r["status"] == "ok" and r["provider"] == "fixture_test_adapter" and r["sufficiency"] == "SUFFICIENT"
    assert r["context_chars"] == len("CONTEXT: verified d12af8deb [ref1]")


def test_the_default_provider_is_the_subscription_cli_named_explicitly():
    seen = []
    r = answer.ask("SHA?", adapters={"claude_cli": ad.claude_cli(runner=_claude(seen, out=_OK))})
    assert answer.PROVIDER == "claude_subscription_cli" and r["provider"] == answer.PROVIDER
    assert r["answer"] == "d12af8deb [ref1]" and r["usage"]["input_tokens"] == 9
    assert r["usage"]["quota_remaining"] == c.UNKNOWN
    assert set(c.load_config()["assignments"].values()) == {None}, "назначения ролей изменены"
    cmd = seen[0]["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd


def test_the_model_parameter_still_reaches_the_cli():
    seen = []
    answer.ask("SHA?", model="sonnet", adapters={"claude_cli": ad.claude_cli(model="sonnet", runner=_claude(seen, out=_OK))})
    assert seen[0]["cmd"][-2:] == ["--model", "sonnet"]
    # и без подменённого адаптера: ask строит адаптер с тем же model
    built = []
    real = ad.claude_cli
    try:
        ad.claude_cli = lambda **kw: built.append(kw) or real(runner=_claude([], out=_OK), **kw)
        answer.ask("SHA?", model="haiku")
    finally:
        ad.claude_cli = real
    assert built == [{"model": "haiku"}]


@pytest.mark.parametrize("timeout,expected", [(180, 180.0), (5, 5.0), (10_000, 300.0)])
def test_timeout_narrows_the_role_deadline_and_never_widens_it(timeout, expected):
    seen = []
    answer.ask("SHA?", timeout=timeout, adapters={"claude_cli": ad.claude_cli(runner=_claude(seen, out=_OK))})
    assert seen[0]["timeout_s"] == expected


@pytest.mark.parametrize("rc,err,status", [(1, "Claude AI usage limit reached", "quota"),
                                           (1, "boom", "error"), (124, "", "timeout")])
def test_quota_error_and_timeout_never_become_an_answer_and_nothing_else_is_tried(rc, err, status):
    seen, other = [], []
    adapters = {"claude_cli": ad.claude_cli(runner=_claude(seen, rc=rc, err=err)),
                "fixture": lambda *a, **k: other.append(1) or ad.AdapterOutput("ok", text="ПОДСТАВА")}
    r = answer.ask("SHA?", adapters=adapters)
    assert r["status"] == status and r["answer"] == "" and r["rc"] != 0 and other == []
    assert answer.grade({"expect_unknown": True}, r["answer"])["correct"] is False
    assert answer.grade({"facts": ["d12af8deb"]}, r["answer"])["correct"] is False


def test_a_refusal_is_not_an_answer():
    r = answer.ask("SHA?", provider="some_local_model", adapters={})
    assert r["status"] == "refused" and r["answer"] == "" and r["rc"] == 2 and "unknown provider" in r["reason"]


def test_the_transport_layer_does_not_import_the_caller():
    """Обратная зависимость снята: `model_roles` не импортирует `studio_os.memory` (цикла нет)."""
    for f in (_REPO / "spa_core/studio_os/model_roles").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("spa_core.studio_os.memory"), f
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("spa_core.studio_os.memory") for a in node.names), f
    for order in ("import spa_core.studio_os.model_roles.adapters, spa_core.studio_os.memory.answer",
                  "import spa_core.studio_os.memory.answer, spa_core.studio_os.model_roles.adapters"):
        p = subprocess.run([sys.executable, "-c", order], cwd=str(_REPO), capture_output=True, text=True,
                           timeout=120)
        assert p.returncode == 0, p.stderr[-1500:]
    assert answer.CLAUDE == ad.CLAUDE

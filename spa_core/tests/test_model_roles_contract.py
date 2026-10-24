# LLM_FORBIDDEN
"""Контракт провайдера и конфигурация ролей (STUDIO-OS-MODELS-01, инкремент 2) — контроли в обе стороны.

Ни один тест не зовёт модель: адаптер Claude получает подменённый `runner`, тестовый адаптер — фикстуру.
Часы — вход (`clock`). Проверяется: роль ≠ провайдер; выбор только явный; отказы без запасного пути;
ограниченные попытки; одинаковый вход у обоих адаптеров; смена провайдера не меняет полномочий;
учёт — только сообщённое, остальное UNKNOWN.
"""
from __future__ import annotations

import copy
import json

import pytest

from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles import contract as c
from spa_core.studio_os.model_roles.__main__ import main as cli

CFG = c.load_config()
REQ = c.Request("architect", "t-1", "Name the verified SHA.", "CONTEXT: verified 3c40ed137", "pack.md")


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 0.5
        return self.t


def _claude(out=None, rc=0, err="", raise_=None, seen=None):
    """Подменённый запуск: та же форма, что у `helper_runner` (cmd, срок, журнал, stdout-файл → rc)."""
    def runner(cmd, timeout_s, log_path, out_path):
        if seen is not None:
            seen.append((cmd, {"timeout": timeout_s}))
        if raise_:
            raise raise_
        out_path.write_text(json.dumps(out) if isinstance(out, dict) else (out or ""), encoding="utf-8")
        log_path.write_text(err, encoding="utf-8")
        return rc
    return ad.claude_cli(binary="/nonexistent/claude", runner=runner)


_OK = {"type": "result", "is_error": False, "result": "3c40ed137", "duration_ms": 1200,
       "usage": {"input_tokens": 50, "output_tokens": 7}, "total_cost_usd": 0.01,
       "modelUsage": {"claude-x": {}}}


def _run(adapters, provider, cfg=CFG, req=REQ):
    return c.execute(req, config=cfg, provider_id=provider, adapters=adapters, clock=_Clock())


# ── роль ≠ провайдер; конфигурация ──────────────────────────────────────────────

def test_the_repository_configuration_separates_roles_from_providers():
    assert set(CFG["roles"]) == {"architect", "worker"}
    for spec in CFG["providers"].values():
        assert not set(spec) & set(c._FORBIDDEN_PROVIDER_KEYS)
    assert CFG["providers"]["fixture_test_adapter"]["real_provider"] is False
    assert CFG["providers"]["claude_subscription_cli"]["real_provider"] is True
    assert set(CFG["assignments"].values()) == {None}, "производственная маршрутизация включена"


def test_no_provider_named_and_none_assigned_is_refused():
    r = _run({"fixture": ad.fixture({"*": "x"})}, None)
    assert r.status == "refused" and "production routing is off" in r.reason


@pytest.mark.parametrize("mutate,provider,needle", [
    (lambda cfg: None, "no_such_provider", "unknown provider"),
    (lambda cfg: cfg["providers"]["fixture_test_adapter"].update(qualified_roles=["worker"]),
     "fixture_test_adapter", "not qualified"),
    (lambda cfg: cfg["providers"]["fixture_test_adapter"].update(capabilities=[]),
     "fixture_test_adapter", "lacks capabilities"),
    (lambda cfg: cfg["providers"]["fixture_test_adapter"].update(max_context_chars=10),
     "fixture_test_adapter", "not truncated"),
    (lambda cfg: cfg["providers"]["fixture_test_adapter"].update(tools=["Bash"]),
     "fixture_test_adapter", "cannot widen"),
    (lambda cfg: cfg["providers"]["fixture_test_adapter"].update(kind="mystery"),
     "fixture_test_adapter", "no adapter"),
])
def test_an_unknown_or_unfit_provider_is_refused_without_fallback(mutate, provider, needle):
    cfg = copy.deepcopy(CFG)
    mutate(cfg)
    calls = []
    fx = ad.fixture({"*": "x"})
    adapters = {"fixture": lambda *a, **k: calls.append(1) or fx(*a, **k),
                "claude_cli": lambda *a, **k: calls.append("claude") or fx(*a, **k)}
    r = _run(adapters, provider, cfg)
    assert r.status == "refused" and needle in r.reason, r.reason
    assert calls == [], "после отказа звали другой адаптер — это запасной путь"


def test_a_refusal_records_usage_as_unknown_not_empty():
    r = _run({}, None)
    assert r.status == "refused" and r.usage and set(r.usage.values()) == {c.UNKNOWN}
    assert r.attempts == 0 and r.elapsed_s is None


def test_an_unknown_role_is_refused():
    r = _run({"fixture": ad.fixture({"*": "x"})}, "fixture_test_adapter",
             req=c.Request("router", "t", "i", "c"))
    assert r.status == "refused" and "unknown role" in r.reason


# ── один контракт у обоих адаптеров; полномочия не меняются ─────────────────────

def test_both_adapters_get_the_same_input_and_return_the_same_contract():
    seen = []
    captured = {}
    fx = ad.fixture({"t-1": "3c40ed137"})

    def spy_fixture(req, **kw):
        captured["prompt"] = ad.render_prompt(req)
        captured["kw"] = kw
        return fx(req, **kw)
    a = _run({"fixture": spy_fixture}, "fixture_test_adapter")
    b = _run({"claude_cli": _claude(_OK, seen=seen)}, "claude_subscription_cli")
    cmd, kw = seen[0]
    assert cmd[cmd.index("-p") + 1] == captured["prompt"], "адаптеры получили разный вход"
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd
    assert kw["timeout"] == CFG["roles"]["architect"]["deadline_s"] == captured["kw"]["timeout_s"]
    assert a.status == b.status == "ok" and a.text == b.text == "3c40ed137"
    assert (a.permissions, a.tools, a.context_sha256) == (b.permissions, b.tools, b.context_sha256)
    assert a.real_provider is False and b.real_provider is True


def test_switching_the_provider_never_changes_permissions():
    a = _run({"fixture": ad.fixture({"*": "x"})}, "fixture_test_adapter")
    b = _run({"claude_cli": _claude(_OK)}, "claude_subscription_cli")
    assert a.permissions == b.permissions == CFG["roles"]["architect"]["permissions"]
    assert a.tools == b.tools == []


def test_an_adapter_asked_for_tools_refuses_them():
    for adapter in (ad.fixture({"*": "x"}), _claude(_OK)):
        out = adapter(REQ, timeout_s=1, tools=["Bash"])
        assert out.status == "error" and "tools requested" in out.detail


# ── ограниченные попытки и исходы ───────────────────────────────────────────────

def test_timeouts_are_retried_but_bounded_by_the_role_and_the_hard_cap():
    r = _run({"fixture": ad.fixture({"*": {"status": "timeout"}})}, "fixture_test_adapter")
    assert r.status == "timeout" and r.attempts == CFG["roles"]["architect"]["max_attempts"]
    cfg = copy.deepcopy(CFG)
    cfg["roles"]["architect"]["max_attempts"] = 50
    r = _run({"fixture": ad.fixture({"*": {"status": "timeout"}})}, "fixture_test_adapter", cfg)
    assert r.attempts == c.HARD_MAX_ATTEMPTS


@pytest.mark.parametrize("status", ["quota", "malformed"])
def test_quota_and_malformed_are_not_retried(status):
    r = _run({"fixture": ad.fixture({"*": {"status": status}})}, "fixture_test_adapter")
    assert r.status == status and r.attempts == 1 and r.text == ""


def test_an_empty_answer_is_malformed_and_a_crashing_adapter_is_an_error():
    assert _run({"fixture": ad.fixture({"*": "   "})}, "fixture_test_adapter").status == "malformed"

    def boom(*a, **k):
        raise RuntimeError("adapter died")
    r = _run({"fixture": boom}, "fixture_test_adapter")
    assert r.status == "error" and "adapter died" in r.reason


@pytest.mark.parametrize("kw,status", [
    ({"rc": 124}, "timeout"),
    ({"rc": 125}, "timeout"),
    ({"raise_": FileNotFoundError("no helper")}, "error"),
    ({"rc": 1, "err": "Claude AI usage limit reached"}, "quota"),
    ({"rc": 1, "err": "boom"}, "error"),
    ({"out": "not json"}, "malformed"),
    ({"out": {"is_error": True, "result": "x"}}, "error"),
    ({"out": {"is_error": False}}, "malformed"),
])
def test_the_claude_adapter_maps_every_transport_outcome(kw, status):
    assert _claude(**kw)(REQ, timeout_s=1, tools=[]).status == status


# ── учёт ────────────────────────────────────────────────────────────────────────

def test_usage_is_recorded_only_as_reported_and_the_rest_is_unknown():
    b = _run({"claude_cli": _claude(_OK)}, "claude_subscription_cli")
    assert b.usage["input_tokens"] == 50 and b.usage["output_tokens"] == 7
    assert b.usage["cost_reported_usd"] == 0.01 and b.usage["quota_remaining"] == c.UNKNOWN
    assert b.model == "claude-x" and b.elapsed_s is not None and b.elapsed_s > 0
    a = _run({"fixture": ad.fixture({"*": "x"})}, "fixture_test_adapter")
    assert set(a.usage.values()) == {c.UNKNOWN}
    assert [e["status"] for e in a.attempt_log] == ["ok"]


# ── CLI ─────────────────────────────────────────────────────────────────────────

def test_the_cli_refuses_without_an_explicit_provider_and_runs_the_test_adapter(tmp_path):
    ctx = tmp_path / "pack.md"
    ctx.write_text("verified 3c40ed137", encoding="utf-8")
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps({"t-1": "3c40ed137"}), encoding="utf-8")
    base = ["--role", "architect", "--context", str(ctx), "--task-id", "t-1", "--instruction", "SHA?"]
    assert cli(base) == 2
    out = tmp_path / "rec.json"
    assert cli(base + ["--provider", "fixture_test_adapter", "--fixture", str(fx), "--out", str(out)]) == 0
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["status"] == "ok" and rec["real_provider"] is False and rec["text"] == "3c40ed137"

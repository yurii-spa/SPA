# LLM_FORBIDDEN
"""Подготовка ОДНОЙ пробы локального Ollama (MODELS-01, ARB 25.10) — без модели и без настоящего Ollama.

Грейдер (структурированный ответ, ложные PASS из разбора ARB), временная конфигурация (роль provider_probe, не
architect), адаптер ollama_http на подменённом HTTP, сторож ресурсов, и контролируемый запуск через настоящий
помощник срока с ПОДДЕЛЬНЫМ сервером `ollama` (скрипт Python на свободном loopback-порту): срок, превышение
ресурсов, сбой измерителя, прерывание. Чужой процесс (запущенный тестом) обязан остаться нетронутым.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles import contract as c
from spa_core.studio_os.model_roles import probe as pr

GOOD = {"verified_sha": "393faa72d", "ci_failures": {"count": 2, "cause": "§49 producer tick tests"},
        "production_routing_enabled": False, "ci_result_79fa6e21d": "UNKNOWN"}
OKM = {"free_pct": 60.0, "pressure_level": 1, "swap_used_mb": 6000.0}


def _ans(**over):
    d = json.loads(json.dumps(GOOD))
    for k, v in over.items():
        if k == "count":
            d["ci_failures"]["count"] = v
        elif k == "cause":
            d["ci_failures"]["cause"] = v
        elif v is None:
            d.pop(k)
        else:
            d[k] = v
    return json.dumps(d, ensure_ascii=False)


# ── грейдер ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_correct_structured_answer_passes():
    assert pr.grade_answer(_ans())["outcome"] == "PASS"
    assert pr.grade_answer("```json\n" + _ans() + "\n```")["outcome"] == "PASS"


@pytest.mark.parametrize("text,field", [
    (_ans(count=200), "ci_failures.count"),                                         # «200 failed» вместо 2
    (_ans(production_routing_enabled="production routing is ON; backup is off"), "production_routing_enabled"),
    (_ans(ci_result_79fa6e21d="CI was green on 79fa6e21d. UNKNOWN is not the answer"), "ci_result_79fa6e21d"),
    (_ans(verified_sha="3c40ed137"), "verified_sha"),                               # неверный SHA
    (_ans(cause="network outage"), "ci_failures.cause"),                            # неверная причина
    (_ans(count=True), "ci_failures.count"),                                        # тип: bool — не int
    (_ans(count="2"), "ci_failures.count"),                                         # тип: строка — не int
    (_ans(production_routing_enabled="false"), "production_routing_enabled"),       # тип: строка — не bool
])
def test_the_arb_false_passes_and_wrong_values_fail_on_their_own_field(text, field):
    g = pr.grade_answer(text)
    assert g["outcome"] == "FAIL" and g["fields"][field] == "wrong", g


def test_an_incomplete_answer_fails():
    g = pr.grade_answer(_ans(ci_result_79fa6e21d=None))
    assert g["outcome"] == "FAIL" and g["missing"] == ["ci_result_79fa6e21d"]


def test_extra_keys_and_prose_fail():
    assert pr.grade_answer(json.dumps(dict(GOOD, note="UNKNOWN")))["outcome"] == "FAIL"
    assert pr.grade_answer("verified 393faa72d, 2 failed (§49), routing off, UNKNOWN")["outcome"] == "FAIL"


def test_a_spent_budget_is_inconclusive_not_fail():
    g = pr.grade({"status": "malformed", "reason": "budget_exhausted: done_reason=length, empty response"})
    assert g["outcome"] == "INCONCLUSIVE"
    assert pr.grade({"status": "ownership_unresolved", "reason": "x"})["outcome"] == "OWNERSHIP_UNRESOLVED"


# ── временная конфигурация: не допуск к роли architect ──────────────────────────────────────────────

def test_the_probe_runs_under_a_temporary_role_and_the_canonical_config_is_untouched():
    canon = c.load_config()
    before = json.dumps(canon, sort_keys=True)
    tmp = pr.temp_config(canon)
    assert json.dumps(canon, sort_keys=True) == before
    assert canon["providers"]["ollama_local"]["qualified_roles"] == []
    assert pr.PROBE_ROLE not in canon["roles"] and set(canon["assignments"].values()) == {None}
    assert tmp["providers"]["ollama_local"]["qualified_roles"] == [pr.PROBE_ROLE]
    assert tmp["roles"][pr.PROBE_ROLE]["max_attempts"] == 1 and tmp["roles"][pr.PROBE_ROLE]["tools"] == []
    stub = {"ollama_http": lambda *a, **k: ad.AdapterOutput("ok", text="x")}
    req = c.Request("architect", "t", "i", "ctx")
    assert c.execute(req, config=tmp, provider_id="ollama_local", adapters=stub).status == "refused"
    assert c.execute(req, config=canon, provider_id="ollama_local", adapters=stub).status == "refused"


# ── адаптер ollama_http ─────────────────────────────────────────────────────────────────────────────

def _post(doc=None, raise_=None, seen=None):
    def post(url, body, timeout_s):
        if seen is not None:
            seen.append((url, body, timeout_s))
        if raise_:
            raise raise_
        return doc
    return post


REQ = c.Request(pr.PROBE_ROLE, "t", "i", "ctx", deadline_s=180)
EP = "http://127.0.0.1:11535"


def _exec(adapter):
    return c.execute(REQ, config=pr.temp_config(c.load_config()), provider_id="ollama_local",
                     adapters={"ollama_http": adapter})


def test_the_adapter_sends_no_tools_and_keeps_transport_metrics():
    seen = []
    doc = {"model": "qwen3.5:4b", "response": _ans(), "thinking": "t" * 900, "done": True, "done_reason": "stop",
           "prompt_eval_count": 410, "eval_count": 700, "total_duration": 9_000_000_000}
    r = _exec(ad.ollama_http(endpoint=EP, model="qwen3.5:4b", http_post=_post(doc, seen=seen)))
    url, body, timeout = seen[0]
    assert url == EP + "/api/generate" and "tools" not in body and body["stream"] is False
    assert body["keep_alive"] == "0s" and body["options"]["num_predict"] == 3072 and timeout == 180
    assert r.status == "ok" and r.text == _ans() and r.attempts == 1
    assert r.transport["done_reason"] == "stop" and r.transport["eval_count"] == 700
    assert r.transport["thinking_chars"] == 900 and r.transport["response_chars"] == len(_ans())
    assert "together" in r.transport["eval_count_counts"]
    assert r.usage["input_tokens"] == 410 and r.usage["output_tokens"] == 700


def test_thinking_never_becomes_the_answer():
    doc = {"response": "", "thinking": json.dumps(GOOD), "done_reason": "stop", "eval_count": 300}
    r = _exec(ad.ollama_http(endpoint=EP, model="m", http_post=_post(doc)))
    assert r.status == "malformed" and r.text == "" and "budget_exhausted" not in r.reason


def test_a_spent_budget_is_recorded_as_such_and_graded_inconclusive():
    doc = {"response": "", "thinking": "x" * 4000, "done_reason": "length", "eval_count": 3072}
    r = _exec(ad.ollama_http(endpoint=EP, model="m", http_post=_post(doc)))
    assert r.status == "malformed" and "budget_exhausted" in r.reason and "not evidence" in r.reason
    assert r.transport["done_reason"] == "length" and r.transport["thinking_chars"] == 4000
    assert pr.grade(r.to_dict())["outcome"] == "INCONCLUSIVE"


def test_a_timeout_is_ownership_unresolved_and_not_retried_even_if_the_role_allows():
    calls = []
    cfg = pr.temp_config(c.load_config())
    cfg["roles"][pr.PROBE_ROLE]["max_attempts"] = 3
    r = c.execute(REQ, config=cfg, provider_id="ollama_local",
                  adapters={"ollama_http": ad.ollama_http(endpoint=EP, model="m",
                                                          http_post=_post(raise_=TimeoutError("t"), seen=calls))})
    assert r.status == "ownership_unresolved" and len(calls) == 1 and r.attempts == 1


@pytest.mark.parametrize("endpoint", ["", "http://10.0.0.5:11434", "https://api.ollama.com", "http://127.0.0.1",
                                      "ftp://127.0.0.1:1"])
def test_only_an_explicit_loopback_endpoint_is_accepted(endpoint):
    seen = []
    out = ad.ollama_http(endpoint=endpoint, model="m", http_post=_post({}, seen=seen))(REQ, timeout_s=1, tools=[])
    assert out.status == "error" and seen == []


def test_tools_are_refused():
    out = ad.ollama_http(endpoint=EP, model="m", http_post=_post({}))(REQ, timeout_s=1, tools=["Bash"])
    assert out.status == "error"


# ── сторож ресурсов ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("m,needle", [
    (dict(OKM, free_pct=30.0), "free memory"), (dict(OKM, pressure_level=2), "pressure"),
    (dict(OKM, server_rss_mb=7000.0), "RSS")])
def test_a_limit_breach_stops(m, needle):
    with pytest.raises(pr.ProbeAbort, match=needle):
        pr.ResourceGuard(lambda pid=None: m, pr.Limits()).check()


def test_swap_growth_is_measured_from_the_first_sample():
    seq = [OKM, dict(OKM, swap_used_mb=7200.0)]
    g = pr.ResourceGuard(lambda pid=None: seq.pop(0), pr.Limits())
    g.check()
    with pytest.raises(pr.ProbeAbort, match="swap grew"):
        g.check()


def test_a_failed_measurement_stops():
    def boom(pid=None):
        raise RuntimeError("memory_pressure: Operation not permitted")
    with pytest.raises(pr.ProbeAbort, match="measurement failed"):
        pr.ResourceGuard(boom, pr.Limits()).check()


def test_rss_is_measured_for_our_own_tree_by_pid():
    ps = "100 1 50000\n200 100 2048000\n300 200 1024\n400 1 9999999\n"
    assert pr.tree_rss_mb(100, ps) == pytest.approx((50000 + 2048000 + 1024) / 1024.0)
    with pytest.raises(RuntimeError):
        pr.tree_rss_mb(555, ps)


# ── контролируемый запуск на поддельном сервере (POSIX) ─────────────────────────────────────────────

FAKE_OLLAMA = r'''
import json, os, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
assert sys.argv[1:] == ["serve"], sys.argv
host, port = os.environ["OLLAMA_HOST"].split(":")
assert host == "127.0.0.1"
MODE = os.environ.get("FAKE_MODE", "ok")
if MODE == "spawn":   # like the llama runner: a grandchild in its OWN session
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/show":
            out = {}
        elif MODE == "hang":
            time.sleep(300); out = {}
        else:
            assert "tools" not in body
            out = {"model": body["model"], "response": os.environ["FAKE_ANSWER"], "thinking": "",
                   "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20}
        data = json.dumps(out).encode(); self.send_response(200)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
HTTPServer(("127.0.0.1", int(port)), H).serve_forever()
'''

posix = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-сцена процессов")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    st = subprocess.run(["ps", "-o", "state=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


@pytest.fixture
def scene(tmp_path, monkeypatch):
    fake = tmp_path / "ollama"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_OLLAMA, encoding="utf-8")
    fake.chmod(0o755)
    ctx = tmp_path / "ctx.md"
    ctx.write_text("verified 393faa72d; 2 failed (§49 producer); routing off", encoding="utf-8")
    monkeypatch.setenv("FAKE_ANSWER", _ans())
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    yield {"fake": str(fake), "ctx": ctx, "out": tmp_path / "out", "foreign": foreign}
    foreign.kill()
    foreign.wait(timeout=10)


def _launch(scene, measure=None, deadline=30.0):
    return pr.launch(ollama=scene["fake"], model="qwen3.5:4b", port=_free_port(), context_path=scene["ctx"],
                     out_dir=scene["out"], total_deadline_s=deadline, grace_s=3.0,
                     child_extra=["--fake-measure", json.dumps(measure or [OKM])])


@posix
def test_a_normal_probe_passes_and_stops_its_own_server(scene):
    rec = _launch(scene)
    assert rec["status"] == "ok" and rec["grade"]["outcome"] == "PASS", rec
    assert rec["server_stopped"] is True and not _alive(rec["server_pid"]) and rec["ownership"].startswith("closed")
    assert rec["ownership_proof"]["provable"] is True
    assert _alive(scene["foreign"].pid), "чужой процесс тронут"


@posix
def test_the_total_deadline_finishes_our_processes_only(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    t0 = time.monotonic()
    rec = _launch(scene, deadline=8.0)
    assert rec["status"] == "timeout" and rec["helper_rc"] == 124, rec
    assert time.monotonic() - t0 < 60
    assert not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


@posix
def test_a_resource_breach_mid_run_stops_our_server(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    rec = _launch(scene, measure=[OKM, OKM, dict(OKM, pressure_level=2)], deadline=40.0)
    assert rec["status"] == "resource_limit" and "pressure" in rec["reason"], rec
    assert rec["server_stopped"] is True and not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


@posix
def test_a_failed_measurement_refuses_before_starting_the_server(scene):
    rec = _launch(scene, measure=["error"])
    assert rec["status"] == "refused_preflight" and "server_pid" not in rec, rec
    assert _alive(scene["foreign"].pid)


@posix
def test_a_descendant_in_its_own_session_is_still_ours_and_finished(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "spawn")
    rec = _launch(scene)
    assert rec["status"] == "ok" and rec["ownership"].startswith("closed (swept"), rec
    assert _alive(scene["foreign"].pid)


@posix
def test_an_interruption_stops_our_server(scene, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_MODE", "hang")
    out = tmp_path / "child.json"
    child = subprocess.Popen([sys.executable, "-m", "spa_core.studio_os.model_roles.probe", "child",
                              "--ollama", scene["fake"], "--model", "m", "--port", str(_free_port()),
                              "--context", str(scene["ctx"]), "--out", str(out),
                              "--fake-measure", json.dumps([OKM])],
                             cwd=str(Path(__file__).resolve().parents[2]),
                             env=dict(os.environ, SPA_RUN_ID="interrupt-scene"))
    for _ in range(100):
        if out.exists() or _server_started(child.pid):
            break
        time.sleep(0.2)
    time.sleep(2.0)
    child.send_signal(signal.SIGTERM)
    child.wait(timeout=30)
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["status"] == "interrupted" and rec["server_stopped"] is True, rec
    assert not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


def _server_started(ppid):
    out = subprocess.run(["ps", "-A", "-o", "ppid="], capture_output=True, text=True).stdout.split()
    return str(ppid) in out


def test_the_launcher_refuses_the_shared_server_port(scene):
    with pytest.raises(ValueError):
        pr.launch(ollama=scene["fake"], model="m", port=11434, context_path=scene["ctx"], out_dir=scene["out"])


@posix
def test_without_provable_ownership_the_probe_is_blocked(scene, tmp_path):
    """Нет метки владения ⇒ помощник не докажет, чьи это процессы ⇒ проба не идёт, свой сервер остановлен."""
    out = tmp_path / "noid.json"
    env = {k: v for k, v in os.environ.items() if k != "SPA_RUN_ID"}
    p = subprocess.run([sys.executable, "-m", "spa_core.studio_os.model_roles.probe", "child",
                        "--ollama", scene["fake"], "--model", "m", "--port", str(_free_port()),
                        "--context", str(scene["ctx"]), "--out", str(out), "--fake-measure", json.dumps([OKM])],
                       cwd=str(Path(__file__).resolve().parents[2]), env=env, timeout=120)
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode != 0 and rec["status"] == "aborted" and "not provable" in rec["reason"], rec
    assert rec["ownership_proof"]["provable"] is False and "result" not in rec
    assert rec["server_stopped"] is True and not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)

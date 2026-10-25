# LLM_FORBIDDEN
"""Подготовка ОДНОЙ пробы локального Ollama (MODELS-01, ARB 25.10) — без модели и без настоящего Ollama.

Единый вердикт (запись и код выхода), точный грейдер, временная роль provider_probe, адаптер ollama_http (без
redirect), сторож ресурсов по нашим процессам, изоляция (занятый порт, чужой endpoint, частное хранилище) и
контролируемый запуск через настоящий помощник срока с ПОДДЕЛЬНЫМ сервером `ollama` на свободном loopback-порту.
Посторонний процесс (запущенный тестом) обязан остаться нетронутым. Настоящие веса не копируются: хранилища — крошечные.
"""
from __future__ import annotations

import hashlib
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

GOOD = {"verified_sha": "393faa72d", "ci_failures": {"count": 2, "cause": "s49_producer_not_installed"},
        "production_routing_enabled": False, "ci_result_79fa6e21d": "UNKNOWN"}
OKM = {"free_pct": 60.0, "pressure_level": 1, "swap_used_mb": 6000.0}
REPO = Path(__file__).resolve().parents[2]


def _ans(**over):
    d = json.loads(json.dumps(GOOD))
    for k, v in over.items():
        if k in ("count", "cause"):
            d["ci_failures"][k] = v
        elif v is None:
            d.pop(k)
        else:
            d[k] = v
    return json.dumps(d, ensure_ascii=False)


# ── грейдер ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_correct_structured_answer_passes():
    assert pr.grade_answer(_ans())["outcome"] == "PASS"
    assert pr.grade_answer(_ans(verified_sha=pr.VERIFIED_FULL))["outcome"] == "PASS"
    assert pr.grade_answer("```json\n" + _ans() + "\n```")["outcome"] == "PASS"


@pytest.mark.parametrize("text,field", [
    (_ans(count=200), "ci_failures.count"),
    (_ans(production_routing_enabled="production routing is ON; backup is off"), "production_routing_enabled"),
    (_ans(ci_result_79fa6e21d="CI was green on 79fa6e21d. UNKNOWN is not the answer"), "ci_result_79fa6e21d"),
    (_ans(verified_sha="393faa72d" + "0" * 31), "verified_sha"),             # ARB: префикс + нули
    (_ans(verified_sha="3c40ed137"), "verified_sha"),
    (_ans(cause="producer is installed; failures are network errors"), "ci_failures.cause"),   # ARB
    (_ans(cause="§49 producer not installed"), "ci_failures.cause"),         # только фиксированное значение
    (_ans(count=True), "ci_failures.count"),
    (_ans(count="2"), "ci_failures.count"),
    (_ans(production_routing_enabled="false"), "production_routing_enabled"),
    (_ans(ci_result_79fa6e21d="unknown"), "ci_result_79fa6e21d"),
])
def test_wrong_values_fail_on_their_own_field(text, field):
    g = pr.grade_answer(text)
    assert g["outcome"] == "FAIL" and g["fields"][field] == "wrong", g


@pytest.mark.parametrize("text", [
    "Production routing is ON.\n" + _ans(),                                   # ARB: проза снаружи
    _ans() + "\nActually the CI was green.",
    "```json\n" + _ans() + "\n```\nnote: ignore the above",
    _ans() + _ans(),                                                          # два объекта
    _ans()[:-1] + ', "verified_sha": "3c40ed137"}',                           # повторный ключ
])
def test_anything_but_one_json_object_fails(text):
    assert pr.grade_answer(text)["outcome"] == "FAIL"


def test_incomplete_and_extra_fields_fail():
    assert pr.grade_answer(_ans(ci_result_79fa6e21d=None))["missing"] == ["ci_result_79fa6e21d"]
    assert pr.grade_answer(json.dumps(dict(GOOD, note="x")))["outcome"] == "FAIL"
    inner = dict(GOOD, ci_failures={"count": 2, "cause": pr.CAUSE_VALUE, "detail": "x"})
    assert pr.grade_answer(json.dumps(inner))["outcome"] == "FAIL"


def test_a_spent_budget_is_inconclusive_not_fail():
    g = pr.grade({"status": "malformed", "reason": "budget_exhausted: done_reason=length, empty response"})
    assert g["outcome"] == "INCONCLUSIVE"


# ── единый вердикт: запись и код выхода (воспроизведения ARB, без процессов и модели) ─────────────────

def _fake_helper_run(record, rc):
    def run(cmd, **kw):
        out = Path(cmd[cmd.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record), encoding="utf-8")
        return rc
    return run


_CHILD_PASS = {"status": "ok", "grade": {"outcome": "PASS"}, "server_stopped": True, "result": {"status": "ok"}}


@pytest.mark.parametrize("rc,closed,status", [(0, False, "ownership_unresolved"), (124, False, "ownership_unresolved"),
                                              (125, True, "ownership_unresolved"), (0, None, "ownership_unresolved")])
def test_a_passing_answer_without_closed_ownership_is_not_a_success(tmp_path, monkeypatch, rc, closed, status):
    helper = ad.load_timeout_helper()
    monkeypatch.setattr(helper, "run", _fake_helper_run(_CHILD_PASS, rc))
    monkeypatch.setattr(pr, "sweep_run_id", lambda *a, **k: {"closed": closed, "left": [4242]})
    rec = pr.launch(ollama="x", model="m", port=11535, context_path=tmp_path / "c", out_dir=tmp_path / "o",
                    models_dir=tmp_path / "s", helper=helper)
    assert rec["grade"]["outcome"] == "PASS" and rec["status"] == status
    assert rec["verdict"]["success"] is False and rec["ownership_closed"] is False
    saved = json.loads((tmp_path / "o" / "probe_record.json").read_text())
    assert saved["verdict"]["success"] is False
    monkeypatch.setattr(pr, "launch", lambda **kw: rec)
    assert pr.main(["launch", "--ollama", "x", "--model", "m", "--port", "11535", "--context", "c",
                    "--out", str(tmp_path / "o"), "--models-dir", str(tmp_path / "s")]) == 1


def test_only_everything_together_is_a_success(tmp_path, monkeypatch):
    helper = ad.load_timeout_helper()
    monkeypatch.setattr(helper, "run", _fake_helper_run(_CHILD_PASS, 0))
    monkeypatch.setattr(pr, "sweep_run_id", lambda *a, **k: {"closed": True, "swept": [], "left": []})
    rec = pr.launch(ollama="x", model="m", port=11535, context_path=tmp_path / "c", out_dir=tmp_path / "o",
                    models_dir=tmp_path / "s", helper=helper)
    assert rec["verdict"] == {"success": True, "reasons": []}
    for broken in ({"grade": {"outcome": "FAIL"}}, {"status": "resource_limit"}, {"server_stopped": False},
                   {"ownership_closed": False}, {"ownership_closed": None}):
        assert pr.verdict(dict(rec, **broken))["success"] is False


def test_each_run_gets_a_unique_label(tmp_path, monkeypatch):
    helper = ad.load_timeout_helper()
    seen = []
    monkeypatch.setattr(helper, "run", lambda cmd, **kw: seen.append(kw["run_id"]) or 0)
    monkeypatch.setattr(pr, "sweep_run_id", lambda *a, **k: {"closed": True})
    for _ in range(2):
        pr.launch(ollama="x", model="m", port=11535, context_path=tmp_path / "c", out_dir=tmp_path / "o",
                  models_dir=tmp_path / "s", helper=helper)
    assert len(set(seen)) == 2 and all(len(r) > 40 for r in seen)


# ── временная конфигурация ──────────────────────────────────────────────────────────────────────────

def test_the_probe_runs_under_a_temporary_role_and_the_canonical_config_is_untouched():
    canon = c.load_config()
    before = json.dumps(canon, sort_keys=True)
    tmp = pr.temp_config(canon)
    assert json.dumps(canon, sort_keys=True) == before
    assert canon["providers"]["ollama_local"]["qualified_roles"] == [] and pr.PROBE_ROLE not in canon["roles"]
    assert tmp["providers"]["ollama_local"]["qualified_roles"] == [pr.PROBE_ROLE]
    stub = {"ollama_http": lambda *a, **k: ad.AdapterOutput("ok", text="x")}
    assert c.execute(c.Request("architect", "t", "i", "ctx"), config=tmp, provider_id="ollama_local",
                     adapters=stub).status == "refused"


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
           "prompt_eval_count": 410, "eval_count": 700}
    r = _exec(ad.ollama_http(endpoint=EP, model="qwen3.5:4b", http_post=_post(doc, seen=seen)))
    _url, body, timeout = seen[0]
    assert "tools" not in body and body["keep_alive"] == "0s" and timeout == 180
    assert r.status == "ok" and r.transport["thinking_chars"] == 900 and r.transport["eval_count"] == 700


def test_thinking_never_becomes_the_answer_and_a_spent_budget_is_inconclusive():
    r = _exec(ad.ollama_http(endpoint=EP, model="m", http_post=_post({"response": "", "thinking": _ans(),
                                                                       "done_reason": "stop"})))
    assert r.status == "malformed" and r.text == ""
    r = _exec(ad.ollama_http(endpoint=EP, model="m", http_post=_post({"response": "", "thinking": "x" * 4000,
                                                                       "done_reason": "length"})))
    assert "budget_exhausted" in r.reason and pr.grade(r.to_dict())["outcome"] == "INCONCLUSIVE"


def test_a_timeout_is_ownership_unresolved_and_not_retried():
    calls = []
    cfg = pr.temp_config(c.load_config())
    cfg["roles"][pr.PROBE_ROLE]["max_attempts"] = 3
    r = c.execute(REQ, config=cfg, provider_id="ollama_local", adapters={"ollama_http": ad.ollama_http(
        endpoint=EP, model="m", http_post=_post(raise_=TimeoutError("t"), seen=calls))})
    assert r.status == "ownership_unresolved" and len(calls) == 1


@pytest.mark.parametrize("endpoint", ["", "http://10.0.0.5:11434", "https://api.ollama.com", "http://127.0.0.1"])
def test_only_an_explicit_loopback_endpoint_is_accepted(endpoint):
    seen = []
    out = ad.ollama_http(endpoint=endpoint, model="m", http_post=_post({}, seen=seen))(REQ, timeout_s=1, tools=[])
    assert out.status == "error" and seen == []


# ── сторож ресурсов ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("m,needle", [(dict(OKM, free_pct=30.0), "free memory"),
                                      (dict(OKM, pressure_level=2), "pressure"),
                                      (dict(OKM, server_rss_mb=7000.0), "RSS")])
def test_a_limit_breach_stops(m, needle):
    with pytest.raises(pr.ProbeAbort, match=needle):
        pr.ResourceGuard(lambda pid=None: m, pr.Limits()).check()


def test_a_failed_measurement_stops():
    def boom(pid=None):
        raise pr.MeasurementError("memory_pressure: Operation not permitted")
    with pytest.raises(pr.ProbeAbort, match="measurement failed"):
        pr.ResourceGuard(boom, pr.Limits()).check()


def test_rss_counts_the_given_pids_only():
    assert pr.rss_mb([100, 200], "100 1024\n200 2048\n300 999999\n") == pytest.approx(3.0)


posix = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-сцена процессов")


@posix
def test_a_detached_process_carrying_our_label_is_measured_as_ours(monkeypatch):
    """Отделившийся runner (своя сессия, не потомок сервера) несёт нашу метку — и учитывается."""
    label = "probe-detached-" + os.urandom(6).hex()
    monkeypatch.setenv("SPA_RUN_ID", label)
    server = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    runner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
                              env=dict(os.environ, SPA_RUN_ID=label))
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
                             env={k: v for k, v in os.environ.items() if k != "SPA_RUN_ID"})
    try:
        time.sleep(0.5)
        mine = pr.owned_pids(server.pid)
        assert server.pid in mine and runner.pid in mine and other.pid not in mine
    finally:
        for p in (server, runner, other):
            p.kill()
            p.wait(timeout=10)


# ── частное хранилище модели ────────────────────────────────────────────────────────────────────────

def _tiny_store(root: Path, model="tiny:1") -> Path:
    name, tag = model.split(":")
    blobs = root / "blobs"
    blobs.mkdir(parents=True)
    digests = []
    for payload in (b"config", b"weights-tiny"):
        d = "sha256:" + hashlib.sha256(payload).hexdigest()
        (blobs / d.replace(":", "-")).write_bytes(payload)
        digests.append(d)
    man = root / "manifests" / "registry.ollama.ai" / "library" / name / tag
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"config": {"digest": digests[0]}, "layers": [{"digest": digests[1]}]}))
    return root


def test_the_private_store_is_a_verified_copy_not_links(tmp_path):
    src = _tiny_store(tmp_path / "src")
    info = pr.prepare_private_store(src, "tiny:1", tmp_path / "dst")
    assert info["blobs"] == 2
    for f in (src / "blobs").iterdir():
        d = tmp_path / "dst" / "blobs" / f.name
        assert d.read_bytes() == f.read_bytes() and os.stat(d).st_ino != os.stat(f).st_ino
        assert os.stat(f).st_nlink == 1, "источник получил жёсткую ссылку"


def test_the_private_store_refuses_a_hard_link(tmp_path, monkeypatch):
    src = _tiny_store(tmp_path / "src")
    import shutil
    monkeypatch.setattr(shutil, "copyfile", lambda a, b: os.link(a, b))
    with pytest.raises(pr.StoreError, match="inode"):
        pr.prepare_private_store(src, "tiny:1", tmp_path / "dst")


def test_the_private_store_refuses_overwrite_size_and_corruption(tmp_path):
    src = _tiny_store(tmp_path / "src")
    (tmp_path / "exists").mkdir()
    with pytest.raises(pr.StoreError):
        pr.prepare_private_store(src, "tiny:1", tmp_path / "exists")
    with pytest.raises(pr.StoreError):
        pr.prepare_private_store(src, "tiny:1", tmp_path / "d1", max_bytes=3)
    blob = next(p for p in (src / "blobs").iterdir() if p.read_bytes() == b"weights-tiny")
    blob.write_bytes(b"tampered")
    with pytest.raises(pr.StoreError):
        pr.prepare_private_store(src, "tiny:1", tmp_path / "d2")


def test_the_prepare_store_command_copies_into_the_named_private_dir(tmp_path):
    src = _tiny_store(tmp_path / "src")
    args = ["prepare-store", "--model", "tiny:1", "--source-store", str(src), "--out", str(tmp_path / "o")]
    assert pr.main(args) == 2                                            # без --models-dir — отказ
    assert pr.main(args + ["--models-dir", str(tmp_path / "dst")]) == 0
    assert pr.main(args + ["--models-dir", str(tmp_path / "dst")]) == 2  # повторно — ничего не перезаписано
    assert (tmp_path / "dst" / "blobs").is_dir()


# ── контролируемый запуск на поддельном сервере (POSIX) ─────────────────────────────────────────────

FAKE_OLLAMA = r'''
import json, os, socket, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
assert sys.argv[1:] == ["serve"], sys.argv
host, port = os.environ["OLLAMA_HOST"].split(":")
assert host == "127.0.0.1" and os.environ.get("OLLAMA_MODELS")
MODE = os.environ.get("FAKE_MODE", "ok")
if MODE == "spawn":   # like a detached llama runner: a grandchild in its OWN session, carrying our label
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
if MODE == "foreign_listener":   # the port is served by a process that is NOT ours (no label, re-parented)
    env = {k: v for k, v in os.environ.items() if k != "SPA_RUN_ID"}
    code = ("import os,socket,time\n"
            "if os.fork(): os._exit(0)\n"
            "os.setsid(); s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            f"s.bind(('127.0.0.1',{port})); s.listen(); open({os.environ['FOREIGN_PID_FILE']!r},'w').write(str(os.getpid()))\n"
            "while True:\n c,_=s.accept(); c.recv(65536)\n"
            " c.sendall(b'HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\n{}'); c.close()\n")
    subprocess.Popen([sys.executable, "-c", code], env=env).wait()
    time.sleep(300)
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, out, code=200, extra=()):
        data = json.dumps(out).encode(); self.send_response(code)
        for k, v in extra: self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        self._send({"version": "fake"})
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if MODE == "hang":
            time.sleep(300)
        if MODE == "redirect":
            return self._send({}, 302, [("Location", "http://example.invalid/api/generate")])
        assert "tools" not in body
        self._send({"model": body["model"], "response": os.environ["FAKE_ANSWER"], "thinking": "",
                    "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
HTTPServer(("127.0.0.1", int(port)), H).serve_forever()
'''


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
    ctx.write_text("verified 393faa72d; 2 failed (§49 producer not installed); routing off", encoding="utf-8")
    store = tmp_path / "private_store"
    store.mkdir()
    monkeypatch.setenv("FAKE_ANSWER", _ans())
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    yield {"fake": str(fake), "ctx": ctx, "out": tmp_path / "out", "foreign": foreign, "store": store,
           "tmp": tmp_path}
    foreign.kill()
    foreign.wait(timeout=10)


def _launch(scene, measure=None, deadline=30.0, port=None):
    return pr.launch(ollama=scene["fake"], model="qwen3.5:4b", port=port or _free_port(),
                     context_path=scene["ctx"], out_dir=scene["out"], models_dir=scene["store"],
                     total_deadline_s=deadline, grace_s=3.0,
                     child_extra=["--fake-measure", json.dumps(measure or [OKM])])


@posix
def test_a_normal_probe_succeeds_only_with_everything_confirmed(scene):
    rec = _launch(scene)
    assert rec["verdict"] == {"success": True, "reasons": []}, rec
    assert rec["grade"]["outcome"] == "PASS" and rec["ownership_closed"] is True
    assert rec["models_dir"] == str(scene["store"]), "launch не передал models_dir ребёнку"
    assert rec["server_pid"] in rec["endpoint_listeners"]
    assert not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


@posix
def test_the_total_deadline_finishes_our_processes_only(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    rec = _launch(scene, deadline=8.0)
    assert rec["status"] == "timeout" and rec["helper_rc"] == 124 and rec["verdict"]["success"] is False, rec
    assert not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


@posix
def test_a_watcher_breach_mid_run_is_kept_and_stops_our_server(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    rec = _launch(scene, measure=[OKM, {"in_watcher": dict(OKM, pressure_level=2)}], deadline=40.0)
    assert rec["status"] == "resource_limit" and "pressure" in rec["reason"], rec
    assert rec["verdict"]["success"] is False and not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


@posix
def test_a_watcher_measurement_failure_mid_run_is_a_stop_not_a_pass(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    rec = _launch(scene, measure=[OKM, {"in_watcher": "error"}], deadline=40.0)
    assert rec["status"] == "aborted" and "measurement failed" in rec["reason"], rec
    assert rec["verdict"]["success"] is False and not _alive(rec["server_pid"])


@posix
def test_a_failed_preflight_measurement_starts_nothing(scene):
    rec = _launch(scene, measure=["error"])
    assert rec["status"] == "refused_preflight" and "server_pid" not in rec and rec["verdict"]["success"] is False


@posix
def test_a_busy_port_is_refused_before_any_request(scene):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        rec = _launch(scene, port=s.getsockname()[1])
    finally:
        s.close()
    assert rec["status"] == "refused_preflight" and "already in use" in rec["reason"] and "server_pid" not in rec


@posix
def test_an_endpoint_served_by_someone_else_is_refused(scene, monkeypatch):
    pidfile = scene["tmp"] / "foreign_listener.pid"
    monkeypatch.setenv("FAKE_MODE", "foreign_listener")
    monkeypatch.setenv("FOREIGN_PID_FILE", str(pidfile))
    try:
        rec = _launch(scene, deadline=40.0)
        assert rec["status"] == "aborted" and "not served by our instance" in rec["reason"], rec
        assert "result" not in rec and rec["verdict"]["success"] is False
    finally:
        if pidfile.exists():
            os.kill(int(pidfile.read_text()), signal.SIGKILL)


@posix
def test_a_redirect_is_never_followed(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "redirect")
    rec = _launch(scene)
    assert rec["result"]["status"] == "error" and "redirect" in rec["result"]["reason"], rec
    assert rec["verdict"]["success"] is False


@posix
def test_a_detached_descendant_is_ours_and_finished_by_the_helper_census(scene, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "spawn")
    rec = _launch(scene)
    sweep = rec["ownership"]["sweep"]
    assert rec["ownership_closed"] is True and sweep["swept"] and sweep["left"] == [], rec
    assert all(not _alive(p) for p in sweep["swept"]) and _alive(scene["foreign"].pid)


@posix
def test_an_interruption_stops_our_server(scene, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_MODE", "hang")
    out = tmp_path / "child.json"
    child = subprocess.Popen([sys.executable, "-m", "spa_core.studio_os.model_roles.probe", "child",
                              "--ollama", scene["fake"], "--model", "m", "--port", str(_free_port()),
                              "--context", str(scene["ctx"]), "--out", str(out), "--models-dir", str(scene["store"]),
                              "--fake-measure", json.dumps([OKM])],
                             cwd=str(REPO), env=dict(os.environ, SPA_RUN_ID="interrupt-" + os.urandom(6).hex()))
    time.sleep(4.0)
    child.send_signal(signal.SIGTERM)
    child.wait(timeout=30)
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["status"] == "interrupted" and rec["server_stopped"] is True and rec["verdict"]["success"] is False
    assert not _alive(rec["server_pid"]) and _alive(scene["foreign"].pid)


@posix
def test_without_provable_ownership_the_probe_is_blocked(scene, tmp_path):
    out = tmp_path / "noid.json"
    env = {k: v for k, v in os.environ.items() if k != "SPA_RUN_ID"}
    p = subprocess.run([sys.executable, "-m", "spa_core.studio_os.model_roles.probe", "child",
                        "--ollama", scene["fake"], "--model", "m", "--port", str(_free_port()),
                        "--context", str(scene["ctx"]), "--out", str(out), "--models-dir", str(scene["store"]),
                        "--fake-measure", json.dumps([OKM])], cwd=str(REPO), env=env, timeout=120)
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode != 0 and rec["status"] == "aborted" and "result" not in rec, rec
    assert rec["server_stopped"] is True and not _alive(rec["server_pid"])


@pytest.mark.parametrize("store", [None, "shared"])
def test_the_shared_or_missing_store_is_refused(tmp_path, store):
    md = None if store is None else str(pr.SHARED_STORE)
    rec = pr.run_child(ollama="/nonexistent", model="m", port=_free_port(), context="c", out=tmp_path / "r.json",
                       models_dir=md, measure=lambda pid=None: OKM)
    assert rec["status"] == "refused_preflight" and "server_pid" not in rec


def test_the_launcher_refuses_the_shared_server_port(tmp_path):
    with pytest.raises(ValueError):
        pr.launch(ollama="x", model="m", port=11434, context_path=tmp_path, out_dir=tmp_path, models_dir=tmp_path)

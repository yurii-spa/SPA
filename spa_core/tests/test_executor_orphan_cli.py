"""S2 (01.11, решение ARB п. 1): исполнитель гибнет ВО ВРЕМЯ вызова провайдера — жизненный цикл дочернего CLI.

Путь запуска — тот же, что у реального провайдера: ``contract.execute`` → адаптер ``claude_cli`` → существующий
помощник срока ``scripts/claude_run_with_timeout.py`` → ``/bin/sh exec``. Вместо настоящего ``claude`` стоит
УПРАВЛЯЕМЫЙ тестовый исполняемый файл (провайдер в конфигурации помечен ``real_provider: false``): это
МОДЕЛИРОВАНИЕ аварии, а не реальный отказ Claude; реальная квота не расходуется.

Исполнитель — отдельный процесс ОС; тест убивает ТОЛЬКО его (SIGKILL по pid), дочерний CLI остаётся сиротой.
Новый исполнитель обязан: найти сироту по записанной метке, убрать только её, не применить старый ответ, не обойти
предел и правила владения, не тронуть чужие процессы; при недоказанном владении — блок без сигнала и без повтора."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from spa_core.studio_os import executor as ex
from spa_core.studio_os import goal_graph as gg
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles import contract as mr

REPO = Path(__file__).resolve().parents[2]
T0 = "2026-11-01T10:00:00+00:00"        # FROZEN-DATE-OK: injected-clock — every `now` and lease expiry derives from T0
T_LATER = "2026-11-01T10:30:00+00:00"   # FROZEN-DATE-OK: injected-clock — past the 600 s lease taken at T0
PROVIDER = "fake_cli_for_test"
PLAN = json.dumps({"tasks": [{"id": "t1", "outcome": "x", "operations": [{"op": "write_file", "path": "docs/n.md",
                   "content": "ok\n"}], "check": {"kind": "file_contains", "path": "docs/n.md", "text": "ok"}}]})

FAKE_CLI = r'''#!{py}
import json, os, sys, time
mark = os.environ["FAKE_CLI_MARK_DIR"]
with open(os.path.join(mark, "cli-%d.json" % os.getpid()), "w") as f:
    json.dump({{"pid": os.getpid(), "run_id": os.environ.get("SPA_RUN_ID")}}, f)
time.sleep(float(os.environ.get("FAKE_CLI_SLEEP", "120")))
# если выжил — «ответ», который НЕ должен быть применён никем
print(json.dumps({{"result": {plan!r}, "usage": {{}}, "modelUsage": {{}}}}))
'''

RUN_EXECUTOR = r'''
import json, sys
from pathlib import Path
from spa_core.studio_os import executor as ex, goal_graph as gg
from spa_core.studio_os.model_roles import adapters as ad, contract as mr
run, fake, cfg = Path(sys.argv[1]), sys.argv[2], json.loads(Path(sys.argv[3]).read_text())
goal = gg.goal_record("g", source="t", transport_id="m", owner="o", outcome="out", at="{t0}")
ex.propose(goal, run_dir=run, scope=["docs/"], context="c", provider_id="{prov}",
           adapters={{"claude_cli": ad.claude_cli(binary=fake)}}, worker="w1", now="{t0}", ttl_s=600, config=cfg)
'''.format(t0=T0, prov=PROVIDER)


def _goal():
    return gg.goal_record("g", source="t", transport_id="m", owner="o", outcome="out", at=T0)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.fixture
def scene(tmp_path):
    mark = tmp_path / "marks"
    mark.mkdir()
    fake = tmp_path / "fake_claude"
    fake.write_text(FAKE_CLI.format(py=sys.executable, plan=PLAN))
    os.chmod(fake, 0o755)
    cfg = mr.load_config()
    cfg = {**cfg, "providers": {**cfg["providers"], PROVIDER: {
        "kind": "claude_cli", "real_provider": False, "description": "TEST: controlled fake CLI binary",
        "capabilities": ["text"], "max_context_chars": 150000, "qualified_roles": ["worker"]}}}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg))
    procs = []
    yield {"tmp": tmp_path, "run": tmp_path / "run", "mark": mark, "fake": fake, "cfg": tmp_path / "cfg.json",
           "procs": procs}
    for p in procs:                                   # уборка ТОЛЬКО своих процессов
        if isinstance(p, int):
            if _alive(p):
                os.kill(p, signal.SIGKILL)
        elif p.poll() is None:
            p.kill()
            p.wait(timeout=10)


def _crash_mid_call(scene):
    """Исполнитель запускается процессом, ждёт, пока его CLI-ребёнок стартует, и убивается SIGKILL."""
    env = dict(os.environ, FAKE_CLI_MARK_DIR=str(scene["mark"]), FAKE_CLI_SLEEP="120")
    p = subprocess.Popen([sys.executable, "-c", RUN_EXECUTOR, str(scene["run"]), str(scene["fake"]), str(scene["cfg"])],
                         cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    scene["procs"].append(p)
    end = time.time() + 60
    while time.time() < end and not list(scene["mark"].glob("cli-*.json")):
        assert p.poll() is None, p.communicate()
        time.sleep(0.05)
    child = json.loads(next(scene["mark"].glob("cli-*.json")).read_text())
    scene["procs"].append(child["pid"])
    os.kill(p.pid, signal.SIGKILL)                     # только исполнитель; его ребёнок — в своей сессии
    p.wait(timeout=10)
    p.communicate()
    started = [r for r in gg._journal(scene["run"]) if r.get("phase") == "call_started"]
    assert len(started) == 1 and started[0]["run_id"] == child["run_id"], (started, child)
    assert _alive(child["pid"]), "сцена: дочерний CLI должен пережить гибель исполнителя"
    return child, started[0]


def _foreign(tmp, run_id=None):
    env = {k: v for k, v in os.environ.items() if k != "SPA_RUN_ID"}
    if run_id:
        env["SPA_RUN_ID"] = run_id
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], env=env)


class Counting:
    def __init__(self):
        self.calls, self._run = 0, ad.fixture({"*": PLAN})

    def __call__(self, req, *, timeout_s, tools):
        self.calls += 1
        return self._run(req, timeout_s=timeout_s, tools=tools)


def _propose_again(scene, adapter, **kw):
    return ex.propose(_goal(), run_dir=scene["run"], scope=["docs/"], context="c", provider_id="fixture_test_adapter",
                      adapters={"fixture": adapter}, worker="w2", now=T_LATER, ttl_s=600, **kw)


def test_orphaned_cli_is_swept_by_its_run_id_and_the_new_call_is_bounded(scene):
    child, started = _crash_mid_call(scene)
    other = _foreign(scene["tmp"])                                  # чужой без метки
    same_kind = _foreign(scene["tmp"], run_id="executor-somebody-else")  # чужой с ДРУГОЙ меткой
    scene["procs"] += [other, same_kind]
    time.sleep(0.3)
    again = Counting()
    out = _propose_again(scene, again)
    assert out["state"] == ex.STEP_DONE and again.calls == 1
    time.sleep(0.5)
    assert not _alive(child["pid"]), "сирота не убрана"
    assert other.poll() is None and same_kind.poll() is None, "задет чужой процесс"
    rows = [r for r in gg._journal(scene["run"]) if r.get("kind") == ex.ATTEMPT]
    swept = [r for r in rows if r.get("phase") == "orphan_swept"]
    assert len(swept) == 1 and swept[0]["run_id"] == child["run_id"] and child["pid"] in swept[0]["sweep"]["swept"]
    results = [r for r in rows if r.get("phase") == "result"]
    assert len(results) == 1 and results[0]["provider_id"] == "fixture_test_adapter"   # ответа сироты нет
    assert out["calls"] == 2                                       # вызов погибшего засчитан в предел


def test_unmeasured_sweep_blocks_without_signal_and_without_retry(scene):
    child, _ = _crash_mid_call(scene)
    again = Counting()
    with pytest.raises(ex.Paused, match="blocked:ownership_unresolved"):
        _propose_again(scene, again, sweep=lambda run_id, age: {"closed": None, "reason": "ps недоступен (моделирование)"})
    assert again.calls == 0 and _alive(child["pid"])              # ни повтора, ни слепого сигнала
    with pytest.raises(ex.Paused, match="blocked"):
        _propose_again(scene, again)                               # и следующий исполнитель тоже стоит
    assert again.calls == 0 and _alive(child["pid"])


def test_survivors_left_after_sweep_block_the_step(scene):
    child, _ = _crash_mid_call(scene)
    again = Counting()
    with pytest.raises(ex.Paused, match="остались процессы"):
        _propose_again(scene, again, sweep=lambda run_id, age: {"closed": False, "swept": [], "left": [child["pid"]]})
    assert again.calls == 0


def test_live_previous_executor_is_never_signalled(scene):
    """Предшественник жив (срок захвата истёк, но процесс есть): его вызов не наш — ни сигнала, ни повтора."""
    env = dict(os.environ, FAKE_CLI_MARK_DIR=str(scene["mark"]), FAKE_CLI_SLEEP="120")
    p = subprocess.Popen([sys.executable, "-c", RUN_EXECUTOR, str(scene["run"]), str(scene["fake"]), str(scene["cfg"])],
                         cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    scene["procs"].append(p)
    end = time.time() + 60
    while time.time() < end and not list(scene["mark"].glob("cli-*.json")):
        time.sleep(0.05)
    child = json.loads(next(scene["mark"].glob("cli-*.json")).read_text())
    scene["procs"].append(child["pid"])
    again = Counting()
    swept = []
    with pytest.raises(ex.Paused, match="живой исполнитель"):
        _propose_again(scene, again, sweep=lambda run_id, age: swept.append(run_id) or {"closed": True})
    assert again.calls == 0 and not swept and p.poll() is None and _alive(child["pid"])


def test_repeated_mid_call_deaths_stop_at_the_call_limit(scene):
    """Две гибели посреди вызова подряд: обе сироты убраны, третий исполнитель модель не зовёт."""
    _crash_mid_call(scene)
    for p in list(scene["mark"].glob("cli-*.json")):
        p.rename(p.with_suffix(".seen"))
    # вторая гибель — новым исполнителем-процессом после срока захвата первого
    run2 = RUN_EXECUTOR.replace('worker="w1", now="' + T0 + '"', 'worker="w2", now="' + T_LATER + '"')
    env = dict(os.environ, FAKE_CLI_MARK_DIR=str(scene["mark"]), FAKE_CLI_SLEEP="120")
    p = subprocess.Popen([sys.executable, "-c", run2, str(scene["run"]), str(scene["fake"]), str(scene["cfg"])],
                         cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    scene["procs"].append(p)
    end = time.time() + 60
    while time.time() < end and not list(scene["mark"].glob("cli-*.json")):
        assert p.poll() is None, p.communicate()
        time.sleep(0.05)
    child2 = json.loads(next(scene["mark"].glob("cli-*.json")).read_text())
    scene["procs"].append(child2["pid"])
    os.kill(p.pid, signal.SIGKILL)
    p.wait(timeout=10)
    third = Counting()
    with pytest.raises(ex.Paused, match="предел"):
        ex.propose(_goal(), run_dir=scene["run"], scope=["docs/"], context="c", provider_id="fixture_test_adapter",
                   adapters={"fixture": third}, worker="w3", now="2026-11-01T11:00:00+00:00", ttl_s=600)  # FROZEN-DATE-OK: injected-clock — T0 + 60 min
    assert third.calls == 0
    time.sleep(0.5)
    assert not _alive(child2["pid"])
    swept = [r for r in gg._journal(scene["run"]) if r.get("phase") == "orphan_swept"]
    assert len(swept) == 2


def test_live_predecessor_with_unmeasured_start_time_is_not_treated_as_dead(scene):
    """Ревью 01.11: предшественник жив, а `ps` не отдал время старта (None) — это «не измерено», не «мёртв»:
    ни уборки, ни повтора, запись orphan_unresolved."""
    env = dict(os.environ, FAKE_CLI_MARK_DIR=str(scene["mark"]), FAKE_CLI_SLEEP="120")
    p = subprocess.Popen([sys.executable, "-c", RUN_EXECUTOR, str(scene["run"]), str(scene["fake"]), str(scene["cfg"])],
                         cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    scene["procs"].append(p)
    end = time.time() + 60
    while time.time() < end and not list(scene["mark"].glob("cli-*.json")):
        time.sleep(0.05)
    child = json.loads(next(scene["mark"].glob("cli-*.json")).read_text())
    scene["procs"].append(child["pid"])
    again, swept = Counting(), []
    with pytest.raises(ex.Paused, match="blocked:ownership_unresolved"):
        _propose_again(scene, again, started=lambda pid: None,
                       sweep=lambda run_id, age: swept.append(run_id) or {"closed": True})
    assert again.calls == 0 and not swept and p.poll() is None and _alive(child["pid"])
    rows = [r for r in gg._journal(scene["run"]) if r.get("phase") == "orphan_unresolved"]
    assert len(rows) == 1 and "не измерено" in rows[0]["sweep"]["reason"]


def test_legacy_rows_without_run_id_do_not_hide_an_unfinished_call(tmp_path):
    """Ревью 01.11: строки прежнего формата без метки сопоставляются один к одному; лишний начатый вызов без
    метки — orphan_unresolved (владение не доказуемо), а не «закрыт»."""
    run = tmp_path / "run"
    goal = _goal()
    sha = ex.render_request(goal, scope=["docs/"], context="c").context_sha256
    step = ex._step_graph(goal, sha)
    lease = gg.claim(run, step, ex.PROPOSE_TASK, worker="w0", process="p0", now=T0, ttl_s=600)
    for row in ({"phase": "call_started"}, {"phase": "result", "status": "timeout"},
                {"phase": "call_started"}):
        ex._append_attempt(run, step, lease, T0, row)
    again = Counting()
    with pytest.raises(ex.Paused, match="нет метки"):
        ex.propose(goal, run_dir=run, scope=["docs/"], context="c", provider_id="fixture_test_adapter",
                   adapters={"fixture": again}, worker="w2", now=T_LATER, ttl_s=600,
                   sweep=lambda run_id, age: {"closed": True})
    assert again.calls == 0
    assert len([r for r in gg._journal(run) if r.get("phase") == "orphan_unresolved"]) == 1

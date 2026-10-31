"""S2 T06 (E4): сменяемый исполнитель с сохраняемыми попытками — критерии F1–F9 пакета ``S2_STATUS.md``.

Что МОДЕЛИРУЕТСЯ: исходы провайдера (quota, timeout, malformed, ownership_unresolved) играет ТЕСТОВЫЙ адаптер
``fixture`` через тот же контракт — реальную квоту ради отказа не расходуем. Что НАСТОЯЩЕЕ: прерывание —
отдельный процесс ОС ``python -m spa_core.studio_os.executor run``, убитый ``SIGKILL`` на известной границе;
продолжение — НОВЫЙ процесс по одним файлам прогона. Реальный провайдер проверяется в сквозном сценарии T09."""
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

T0 = "2026-10-31T20:00:00+00:00"          # FROZEN-DATE-OK: injected-clock — every `now` and expiry derives from T0
T_LATER = "2026-10-31T20:30:00+00:00"     # FROZEN-DATE-OK: injected-clock — past the 600 s lease of T0
SCOPE = ["docs/"]
REPO = Path(__file__).resolve().parents[2]


def _goal():
    return gg.goal_record("Добавить заметку docs/note.md со строкой «готово»", source="test", transport_id="msg-1",
                          owner="operator", outcome="в docs/note.md есть строка «готово»", at=T0)


PLAN = json.dumps({"tasks": [{"id": "t1", "outcome": "заметка есть",
                              "operations": [{"op": "write_file", "path": "docs/note.md", "content": "готово\n"}],
                              "check": {"kind": "file_contains", "path": "docs/note.md", "text": "готово"},
                              "depends_on": []}]})


class Counting:
    """Тестовый адаптер под контрактом + счётчик вызовов (чтобы доказать «модель повторно не звали»)."""

    def __init__(self, answer):
        self.calls, self._run = 0, ad.fixture({"*": answer})

    def __call__(self, req, *, timeout_s, tools):
        self.calls += 1
        return self._run(req, timeout_s=timeout_s, tools=tools)


def _scene(tmp_path):
    stand, run = tmp_path / "stand", tmp_path / "run"
    stand.mkdir()
    (stand / ".studio_stand").write_text("")
    return stand, run


def _propose(run, adapter, *, worker="w1", now=T0, context="ctx-1"):
    return ex.propose(_goal(), run_dir=run, scope=SCOPE, context=context, provider_id="fixture_test_adapter",
                      adapters={"fixture": adapter}, worker=worker, now=now, ttl_s=600)


def _approve(run, graph, task="t1", approver="operator-test"):
    a = gg.approve_task(graph, task, approver=approver, role="agent", at=T0, expires_at="2026-11-01T20:00:00+00:00")
    (Path(run) / f"approval-{task}.json").write_text(json.dumps(a))
    return a


def _rows(run, kind=ex.ATTEMPT):
    return [r for r in gg._journal(Path(run)) if r.get("kind") == kind]


class _Admit:
    def __init__(self, refuse=None):
        self.refuse, self.taken = refuse, 0

    def __call__(self):
        if self.refuse:
            raise RuntimeError(self.refuse)  # noqa: TRY002 — моделируем отказ существующего admission
        self.taken += 1
        return type("L", (), {"release": lambda s: None})()


# ── F1/F2: модель только через контракт; попытка записана ДО использования ответа ─────────────────
def test_attempt_is_recorded_with_accounting_and_the_answer_is_only_a_plan(tmp_path):
    stand, run = _scene(tmp_path)
    a = Counting(PLAN)
    out = _propose(run, a)
    assert out["called_model"] and a.calls == 1 and out["graph"]["tasks"]["t1"]["subject"] == "none"
    res = [r for r in _rows(run) if r.get("phase") == "result"][0]
    assert res["status"] == "ok" and res["real_provider"] is False and res["provider_id"] == "fixture_test_adapter"
    assert res["tools"] == [] and res["permissions"] == ["read_context_pack", "answer_text"]   # роль не расширена
    assert res["contract_attempts"] == 1 and isinstance(res["elapsed_s"], float) and res["context_sha256"]
    assert (run / res["answer_file"]).read_text() == PLAN
    assert not (stand / "docs").exists()              # ответ модели ничего не сделал сам


def test_model_plan_outside_scope_is_refused_whole_and_never_executed(tmp_path):
    stand, run = _scene(tmp_path)
    bad = PLAN.replace("docs/note.md", "spa_core/risk/policy.py")
    with pytest.raises(ex.Paused):
        _propose(run, Counting(bad))
    res = [r for r in _rows(run) if r.get("phase") == "result"][0]
    assert res["plan_ok"] is False and any("scope" in w for w in res["plan_refusals"])
    assert not list(run.glob("graph-*.json"))


# ── F3: квота — пауза, без повтора, задача не теряется ───────────────────────────────────────────
def test_quota_pauses_without_retry_until_explicit_resume(tmp_path):
    _stand, run = _scene(tmp_path)
    q = Counting({"status": "quota", "detail": "usage limit (played)"})
    with pytest.raises(ex.Paused, match="paused:quota"):
        _propose(run, q)
    with pytest.raises(ex.Paused, match="paused:quota"):
        _propose(run, q)                               # второй исполнитель — тоже пауза
    assert q.calls == 1                                # контракт квоту не повторяет, и мы — тоже
    sha = ex.render_request(_goal(), scope=SCOPE, context="ctx-1").context_sha256
    ex.resume_after_quota(run, _goal(), sha, by="operator", now=T0)
    out = _propose(run, Counting(PLAN))
    assert out["state"] == ex.STEP_DONE and out["calls"] == 2


# ── F4: timeout/malformed — ограниченно; ownership_unresolved — запрет повтора ───────────────────
def test_malformed_answers_stop_at_the_call_limit_across_sessions(tmp_path):
    _stand, run = _scene(tmp_path)
    m = Counting("не JSON")
    for _ in range(ex.MAX_CALLS):
        with pytest.raises(ex.Paused):
            _propose(run, m)
    with pytest.raises(ex.Paused, match="failed:limit"):
        _propose(run, Counting(PLAN), worker="w2")    # новая сессия предел не обнуляет
    assert m.calls == ex.MAX_CALLS


def test_timeout_is_retried_by_the_contract_only_within_the_role_limit(tmp_path):
    _stand, run = _scene(tmp_path)
    t = Counting({"status": "timeout"})
    with pytest.raises(ex.Paused):
        _propose(run, t)
    res = [r for r in _rows(run) if r.get("phase") == "result"][0]
    assert res["status"] == "timeout" and res["contract_attempts"] == t.calls == 2   # role.max_attempts


def test_unresolved_ownership_forbids_any_retry_until_resolution_is_recorded(tmp_path):
    _stand, run = _scene(tmp_path)
    o = Counting({"status": "ownership_unresolved"})
    with pytest.raises(ex.Paused, match="blocked:ownership_unresolved"):
        _propose(run, o)
    with pytest.raises(ex.Paused, match="blocked"):
        _propose(run, Counting(PLAN), worker="w2")
    assert o.calls == 1
    sha = ex.render_request(_goal(), scope=SCOPE, context="ctx-1").context_sha256
    with pytest.raises(gg.Refused):
        ex.resolve_ownership(run, _goal(), sha, by="operator", now=T0, evidence=" ")
    ex.resolve_ownership(run, _goal(), sha, by="operator", now=T0, evidence="ps -p: процессов прогона нет")
    assert _propose(run, Counting(PLAN))["state"] == ex.STEP_DONE


# ── F5: изменённый контекст — прежний ответ не используется ──────────────────────────────────────
def test_stale_context_answer_is_not_reused(tmp_path):
    _stand, run = _scene(tmp_path)
    first = _propose(run, Counting(PLAN), context="ctx-1")
    plan2 = json.loads(PLAN)
    plan2["tasks"][0]["operations"][0]["content"] = "готово v2\n"
    again = Counting(json.dumps(plan2))
    second = _propose(run, again, context="ctx-2")
    assert again.calls == 1 and second["graph_version"] != first["graph_version"]


# ── F6/F7: продолжение без повтора; один исполнитель на задачу ───────────────────────────────────
def test_saved_answer_is_not_requested_again_and_live_claim_blocks_a_second_worker(tmp_path):
    stand, run = _scene(tmp_path)
    out = _propose(run, Counting(PLAN))
    again = Counting(PLAN)
    assert _propose(run, again, worker="w2")["called_model"] is False and again.calls == 0
    g = out["graph"]
    assert ex.next_step(run, g)["step"] == "await_approval"
    _approve(run, g)
    gg.claim(run, g, "t1", worker="w1", process="p1", now=T0, ttl_s=600)
    with pytest.raises(gg.Conflict):
        ex.advance(g, run_dir=run, stand=stand, worker="w2", now=T0, ttl_s=600, admit=_Admit())
    log = ex.run_until_blocked(g, run_dir=run, stand=stand, worker="w2", now=lambda: T_LATER, ttl_s=600,
                               admit=_Admit())
    assert [r["step"] for r in log] == ["executed", "checked", "done"]
    assert gg.done_tasks(run, g["version"]) == ["t1"]
    gens = [r["generation"] for r in _rows(run, "claim") if r["graph_version"] == g["version"]]
    assert gens == [1, 2, 3]                           # w1, перехват w2 после срока, w2 на проверке
    assert ex.advance(g, run_dir=run, stand=stand, worker="w3", now=T_LATER, ttl_s=600)["step"] == "done"


def test_previous_generation_cannot_write_after_takeover(tmp_path):
    stand, run = _scene(tmp_path)
    g = _propose(run, Counting(PLAN))["graph"]
    a = _approve(run, g)
    old = gg.claim(run, g, "t1", worker="w1", process="p1", now=T0, ttl_s=600)
    gg.claim(run, g, "t1", worker="w2", process="p2", now=T_LATER, ttl_s=600)
    with pytest.raises(gg.Conflict):
        gg.execute_on_stand(g, "t1", a, stand=stand, run_dir=run, now=T_LATER, author="w1", lease=old)
    assert not (stand / "docs" / "note.md").exists()


# ── F8: исполнитель не выдаёт себе допуск ───────────────────────────────────────────────────────
def test_executor_cannot_admit_itself(tmp_path):
    stand, run = _scene(tmp_path)
    g = _propose(run, Counting(PLAN))["graph"]
    with pytest.raises(gg.Refused):
        gg.approve_task(g, "t1", approver="w1", role="model", at=T0, expires_at=T_LATER)
    _approve(run, g, approver="w1")                    # допустил тот же, кто исполняет
    with pytest.raises(gg.Refused, match="самодопуск"):
        ex.advance(g, run_dir=run, stand=stand, worker="w1", now=T0, ttl_s=600, admit=_Admit())
    assert not (stand / "docs" / "note.md").exists()


# ── F9: тяжёлый шаг — под существующим admission; отказ — пауза ─────────────────────────────────
def test_check_waits_for_admission_and_keeps_the_task(tmp_path):
    stand, run = _scene(tmp_path)
    g = _propose(run, Counting(PLAN))["graph"]
    _approve(run, g)
    log = ex.run_until_blocked(g, run_dir=run, stand=stand, worker="w1", now=lambda: T0, ttl_s=600,
                               admit=_Admit(refuse="free disk 3.0 GB < 20 GB (played)"))
    assert [r["step"] for r in log] == ["executed", "paused:admission"]
    assert gg.task_state(run, g["version"], "t1") == "applied"   # задача на месте, исход не выдуман
    ok = _Admit()
    log = ex.run_until_blocked(g, run_dir=run, stand=stand, worker="w1", now=lambda: T0, ttl_s=600, admit=ok)
    assert [r["step"] for r in log] == ["checked", "done"] and ok.taken == 1


def test_default_admission_is_the_existing_heavy_job_lease(tmp_path):
    """Без инъекции проверка берёт аренду ``heavy_job.admit`` (ADR-551) — реестр указан явно и одноразовый."""
    from spa_core.utils import heavy_job
    stand, run = _scene(tmp_path)
    g = _propose(run, Counting(PLAN))["graph"]
    _approve(run, g)
    pol = {**heavy_job._policy(), "registry_dir": str(tmp_path / "leases"), "min_free_disk_gb": 0}
    seen = []

    def admit():
        lease = heavy_job.admit("executor_check", str(stand), policy=pol, renice=False)
        seen.append(json.loads(lease.file.read_text()))
        return lease

    log = ex.run_until_blocked(g, run_dir=run, stand=stand, worker="w1", now=lambda: T0, ttl_s=600, admit=admit)
    assert log[-1]["step"] == "done" and seen[0]["kind"] == "executor_check"
    assert not list((tmp_path / "leases").glob("*.json"))      # аренда отпущена


# ── E4.5 настоящим процессом: убит на границе, продолжен новым процессом по файлам ─────────────────
def _spawn(run, stand, gv, worker, stop_at=None):
    cmd = [sys.executable, "-m", "spa_core.studio_os.executor", "run", "--run-dir", str(run), "--stand", str(stand),
           "--graph-version", gv, "--worker", worker, "--ttl-s", "2", "--admission-registry", str(run / "leases")]
    if stop_at:
        cmd += ["--stop-at", stop_at]
    return subprocess.Popen(cmd, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)


def _wait_file(pattern_dir: Path, prefix: str, proc, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        hit = [p for p in pattern_dir.glob(prefix + "*")]
        if hit:
            return hit[0]
        if proc.poll() is not None:
            raise AssertionError(f"процесс вышел до границы: {proc.communicate()}")
        time.sleep(0.05)
    raise AssertionError("граница не достигнута")


@pytest.mark.parametrize("boundary", ["started", "applied"])
def test_killed_executor_is_continued_by_a_new_process_without_a_second_effect(tmp_path, boundary):
    stand, run = _scene(tmp_path)
    g = _propose(run, Counting(PLAN))["graph"]
    _approve(run, g)
    p1 = _spawn(run, stand, g["version"], "w1", stop_at=boundary)
    _wait_file(run, f"at_{boundary}-", p1)
    os.killpg(p1.pid, signal.SIGKILL)                  # процесс, принадлежащий тесту
    p1.wait(timeout=10)
    p1.communicate()
    assert gg.task_state(run, g["version"], "t1") == ("started" if boundary == "started" else "applied")
    # живой захват (срок 2 с) — второй процесс отказывает, а не исполняет параллельно
    p2 = _spawn(run, stand, g["version"], "w2")
    out2, _ = p2.communicate(timeout=60)
    assert p2.returncode == 3 and "держит w1" in out2.decode(), out2
    time.sleep(2.2)                                    # срок захвата прошёл
    p3 = _spawn(run, stand, g["version"], "w2")
    out3, err3 = p3.communicate(timeout=60)
    assert p3.returncode == 0, err3
    log3 = json.loads(out3)
    steps = [r["step"] for r in log3]
    states = [r["state"] for r in gg._journal(run) if r.get("graph_version") == g["version"] and "state" in r]
    if boundary == "started":
        # убит ДО первой записи: разбор по фактам стенда — «не сделано», затем НОВАЯ попытка; эффект один
        assert steps == ["recovered", "executed", "checked", "done"], steps
        assert log3[0]["state"] == "aborted:crash"
        assert states == ["started", "aborted:crash", "started", "applied", "checked:satisfied"], states
    else:
        # убит ПОСЛЕ эффекта: исполнение не повторяется, остаётся только проверка
        assert steps == ["checked", "done"], steps
        assert states == ["started", "applied", "checked:satisfied"], states
    assert states.count("applied") == 1                # второго эффекта нет
    assert (stand / "docs" / "note.md").read_text() == "готово\n"
    claims = [r for r in _rows(run, "claim") if r["graph_version"] == g["version"]]
    assert claims[0]["worker"] == "w1" and claims[1]["worker"] == "w2" and claims[1]["takeover_of"] == 1
    for p in (p1, p2, p3):                             # своих живых процессов не осталось
        with pytest.raises(ProcessLookupError):
            os.killpg(p.pid, 0)


def test_late_answer_of_a_taken_over_proposal_is_not_written(tmp_path):
    """Пока w1 ждёт модель, срок его захвата шага истёк и шаг перехватил w2: ответ w1 в журнал не попадает."""
    _stand, run = _scene(tmp_path)
    goal = _goal()
    sha = ex.render_request(goal, scope=SCOPE, context="ctx-1").context_sha256
    inner = ad.fixture({"*": PLAN})

    def slow_then_overtaken(req, *, timeout_s, tools):
        gg.claim(run, ex._step_graph(goal, sha), ex.PROPOSE_TASK, worker="w2", process="p2", now=T_LATER, ttl_s=600)
        return inner(req, timeout_s=timeout_s, tools=tools)

    with pytest.raises(gg.Conflict, match="захват устарел"):
        _propose(run, slow_then_overtaken, worker="w1")
    assert not [r for r in _rows(run) if r.get("phase") == "result"]
    assert not list(run.glob("graph-*.json"))


def test_sessions_dying_mid_call_still_count_against_the_call_limit(tmp_path):
    """Сессия умирает ВО ВРЕМЯ вызова модели (результата нет) — дважды, каждая после срока предыдущего захвата.
    Третья сессия не зовёт модель: предел шага держится через смену сессий и по начатым вызовам."""
    _stand, run = _scene(tmp_path)

    def dies(req, *, timeout_s, tools):
        raise KeyboardInterrupt("сессия потеряна посреди вызова (моделирование)")

    for worker, now in (("w1", T0), ("w2", T_LATER), ):
        with pytest.raises(KeyboardInterrupt):
            _propose(run, dies, worker=worker, now=now)
    third = Counting(PLAN)
    with pytest.raises(ex.Paused, match="предел"):
        _propose(run, third, worker="w3", now="2026-10-31T21:30:00+00:00")  # FROZEN-DATE-OK: injected-clock — T0 + 90 min
    assert third.calls == 0
    started = [r for r in _rows(run) if r.get("phase") == "call_started"]
    assert [r["worker"] for r in started] == ["w1", "w2"]

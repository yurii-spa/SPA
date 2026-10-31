"""S2 T09 — сквозной сценарий одной безопасной задачи (критерии I1–I4, ``S2_STATUS.md``).

задача → план от исполнителя (через контракт ролей) → проверка плана → допуск (тестовая выдача роли agent,
НЕ владелец) → захват → исполнение отдельным процессом с прерыванием SIGKILL и продолжением новым процессом →
машинный исход → коммит → манифест артефакта → проверенный релиз → фактический запуск B и откат к A на стенде.

Провайдер — параметр: ``claude_subscription_cli`` (РЕАЛЬНЫЙ, CLI на подписке, инструменты выключены) или
``fixture_test_adapter`` (ТЕСТОВЫЙ, для CI). Код сцены один и тот же. Реальный провайдер недоступен — исход
записывается и сценарий объявляет I1 «не измерено», fixture его не подменяет (I4).

Запуск с реальным провайдером (доказательство, не CI):
    python -m spa_core.tests.s2_e2e_scene --base <новый каталог> --provider claude_subscription_cli
"""
from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.studio_os import executor as ex
from spa_core.studio_os import goal_graph as gg
from spa_core.studio_os import release_activation as RA
from spa_core.studio_os import release_launcher as LNCH
from spa_core.studio_os import release_state as RS
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.tests import test_release_isolated_exec_stand as T4

REPO = Path(__file__).resolve().parents[2]
NOTE = "docs/release_note.md"
MARK = "S2 сквозной сценарий выполнен"
FIXTURE_PLAN = json.dumps({"tasks": [{"id": "note", "outcome": "заметка о выпуске добавлена",
                                      "operations": [{"op": "write_file", "path": NOTE, "content": MARK + "\n"}],
                                      "check": {"kind": "file_contains", "path": NOTE, "text": MARK},
                                      "depends_on": []}]}, ensure_ascii=False)

_ROLE = T4._ROLE_SRC.replace('"flags_ignore_env": sys.flags.ignore_environment}}',
                             '"flags_ignore_env": sys.flags.ignore_environment, '
                             '"note_present": os.path.exists("' + NOTE + '")}}')


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _spawn(run, stand, gv, worker, stop_at=None, ttl=3):
    cmd = [sys.executable, "-m", "spa_core.studio_os.executor", "run", "--run-dir", str(run), "--stand", str(stand),
           "--graph-version", gv, "--worker", worker, "--ttl-s", str(ttl), "--admission-registry", str(run / "leases")]
    if stop_at:
        cmd += ["--stop-at", stop_at]
    return subprocess.Popen(cmd, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)


def run(base: Path, provider_id: str) -> dict:
    base = Path(base).resolve()
    rec = {"provider_id": provider_id, "steps": []}

    def step(name, **kw):
        rec["steps"].append({"step": name, "t": round(time.time(), 3), **kw})

    prod_before = T4._prod_footprint()
    st = T4.Stand(base / "stand")                       # тот же стенд и лаунчер, что в задаче 04
    run_dir = base / "run"
    try:
        repo = st.repo
        (repo / "spa_core").mkdir()
        (repo / "spa_core" / "__init__.py").write_text("")
        (repo / "spa_core" / "probe_role.py").write_text(_ROLE.format(version="S2"))
        (repo / LNCH.AGENT_ROLE_MANIFEST).write_text(json.dumps({"probe": "spa_core.probe_role"}))
        (repo / "docs").mkdir()
        (repo / "docs" / "README.md").write_text("Стенд сквозного сценария S2.\n")
        (repo / ".git" / "info" / "exclude").write_text(".studio_stand\n")
        T4._git(["add", "-A"], repo)
        T4._git(["commit", "-q", "-m", "A: base"], repo)
        sha_a = T4._git(["rev-parse", "HEAD"], repo)
        (repo / ".studio_stand").write_text("")          # стенд исполнителя — рабочее дерево тестового репозитория
        step("A.committed", sha=sha_a)

        # 1. задача
        now0 = datetime.now(timezone.utc)
        goal = gg.goal_record(f"Добавь файл {NOTE} со строкой «{MARK}».", source="s2-e2e", transport_id=f"e2e-{sha_a[:12]}",
                              owner="operator-test", outcome=f"в {NOTE} есть строка «{MARK}»", at=_iso(now0))
        context = "Файлы стенда:\n" + "\n".join(sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*")
                                                      if p.is_file() and ".git" not in p.parts))
        # 2. план от исполнителя — через контракт
        if provider_id == "claude_subscription_cli":
            adapters = {"claude_cli": ad.claude_cli()}
        else:
            adapters = {"fixture": ad.fixture({"*": FIXTURE_PLAN})}
        try:
            prop = ex.propose(goal, run_dir=run_dir, scope=["docs/"], context=context, provider_id=provider_id,
                              adapters=adapters, worker="executor-1", now=_iso(now0), ttl_s=900)
        except gg.Refused as exc:
            rows = [r for r in gg._journal(run_dir) if r.get("kind") == ex.ATTEMPT and r.get("phase") == "result"]
            step("propose.refused", why=str(exc), attempts=rows)
            rec["verdict"] = "NOT MEASURED: исполнитель не дал годного плана — " + str(exc)[:200]
            return rec
        attempt = [r for r in gg._journal(run_dir) if r.get("kind") == ex.ATTEMPT and r.get("phase") == "result"][-1]
        graph = prop["graph"]
        step("propose", called_model=prop["called_model"], real_provider=attempt["real_provider"],
             provider_id=attempt["provider_id"], model=attempt["model"], elapsed_s=attempt["elapsed_s"],
             usage=attempt["usage"], graph_version=graph["version"], tasks=list(graph["tasks"]))
        # 3. допуск — тестовая выдача роли agent (не владелец, не исполнитель)
        tid = graph["order"][0]
        appr = gg.approve_task(graph, tid, approver="operator-test", role="agent", at=_iso(now0),
                               expires_at=_iso(now0 + timedelta(hours=2)))
        (run_dir / f"approval-{tid}.json").write_text(json.dumps(appr))
        step("approval", approver="operator-test", role="agent", subject=graph["tasks"][tid]["subject"])
        # 4. исполнение процессом; прерывание на границе applied; продолжение новым процессом
        p1 = _spawn(run_dir, repo, graph["version"], "executor-1", stop_at="applied")
        end = time.time() + 60
        while time.time() < end and not list(run_dir.glob("at_applied-*")):
            if p1.poll() is not None:
                break
            time.sleep(0.05)
        os.killpg(p1.pid, signal.SIGKILL)
        p1.wait(timeout=10)
        p1.communicate()
        step("executor-1.killed", pid=p1.pid, state=gg.task_state(run_dir, graph["version"], tid))
        p2 = _spawn(run_dir, repo, graph["version"], "executor-2")
        o2, _ = p2.communicate(timeout=60)
        step("executor-2.refused_while_claim_alive", rc=p2.returncode, out=o2.decode()[:200])
        time.sleep(3.2)
        p3 = _spawn(run_dir, repo, graph["version"], "executor-2")
        o3, e3 = p3.communicate(timeout=120)
        log3 = json.loads(o3) if p3.returncode == 0 else e3.decode()[-300:]
        states = [r["state"] for r in gg._journal(run_dir) if r.get("graph_version") == graph["version"] and "state" in r]
        step("executor-2.continued", rc=p3.returncode, log=log3, states=states,
             model_calls=len([r for r in gg._journal(run_dir) if r.get("phase") == "call_started"]))
        if gg.done_tasks(run_dir, graph["version"]) != [tid]:
            rec["verdict"] = f"FAILED: задача не выполнена, состояния {states}"
            return rec
        # 5. сохранение: коммит результата → манифест артефакта
        T4._git(["add", "-A"], repo)
        T4._git(["commit", "-q", "-m", f"B: {tid} (graph {graph['version'][:12]})"], repo)
        sha_b = T4._git(["rev-parse", "HEAD"], repo)
        journal = (run_dir / gg.JOURNAL_FILE).read_bytes()
        man = RA.artifact_manifest(sha_b, repo, base=sha_a, criterion={
            "goal_version": goal["version"], "graph_version": graph["version"], "task": tid,
            "check": graph["tasks"][tid]["check"], "verdict": "satisfied",
            "journal_sha256": __import__("hashlib").sha256(journal).hexdigest()},
            environment={"python": sys.version.split()[0], "platform": platform.platform(), "provider": provider_id})
        (base / "manifest_B.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
        step("B.committed", sha=sha_b, manifest_matches=RA.manifest_matches(man, sha_b, repo),
             manifest_on_A=RA.manifest_matches(man, sha_a, repo))
        # 6. проверенный релиз → запуск A, переход на B, откат к A (лаунчер, execv, замер по процессу)
        for s in (sha_a, sha_b):
            assert RA.materialise_release(s, st.releases, repo)[1] == "OK"
        for label, sha in (("run_A", sha_a), ("run_B", sha_b), ("rollback_A", sha_a)):
            st.approve(sha)
            p, hb = st.launch()
            procs = RS.active_processes(st.releases.resolve())
            step(label, sha=sha, pid=p.pid, heartbeat=hb, processes=procs, active_record=st.active_record())
            if not hb or hb["pid"] != p.pid or hb["note_present"] != (sha == sha_b) or [x["sha"] for x in procs] != [sha]:
                rec["verdict"] = f"FAILED на {label}: {hb} {procs}"
                st.stop(p) if hb else None
                return rec
            st.stop(p)
        rec["verdict"] = "OK"
    finally:
        st.reap()
        rec["leftovers"] = st.leftovers()
        rec["prod_unchanged"] = T4._prod_footprint() == prod_before
        (base / "e2e_record.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    return rec


if __name__ == "__main__":
    import argparse
    a = argparse.ArgumentParser()
    a.add_argument("--base", required=True)
    a.add_argument("--provider", required=True, choices=("claude_subscription_cli", "fixture_test_adapter"))
    ns = a.parse_args()
    if Path(ns.base).exists():
        sys.exit("--base уже существует — сцена пишет только в новый каталог")
    r = run(Path(ns.base), ns.provider)
    print(json.dumps({"verdict": r.get("verdict"), "leftovers": r.get("leftovers"),
                      "prod_unchanged": r.get("prod_unchanged"), "steps": [s["step"] for s in r["steps"]]},
                     ensure_ascii=False, indent=1))
    sys.exit(0 if r.get("verdict") == "OK" else 1)

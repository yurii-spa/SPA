"""S2 T07 (E5.5/E5.6/E5.4/E5.1 на СТЕНДЕ задачи 04): каждый процесс назван, падение при активации и возврат,
изменяемые данные не откатываются, манифест артефакта засчитывается только своему sha. Критерии G1–G4
(``S2_STATUS.md``). Тот же стенд и тот же лаунчер, что в ``test_release_isolated_exec_stand``; симуляция та же
(пользовательский «доверенный корень», Popen вместо launchd, одобрение пишет тест)."""
import json
import platform
import sys
import time
from pathlib import Path

from spa_core.studio_os import release_activation as RA
from spa_core.studio_os import release_launcher as LNCH
from spa_core.studio_os import release_state as RS
from spa_core.tests import test_release_isolated_exec_stand as T4

_LEDGER_ROLE = T4._ROLE_SRC.replace(
    '    tmp = os.path.join(d, ".hb-%d" % pid)',
    '    with open(os.path.join(d, "ledger.jsonl"), "a") as led:          # изменяемые данные — ВНЕ релиза\n'
    '        led.write(json.dumps({{"version": VERSION, "pid": pid}}) + "\\n")\n'
    '    tmp = os.path.join(d, ".hb-%d" % pid)')
assert _LEDGER_ROLE != T4._ROLE_SRC, "подстановка в роль не сработала"
_CRASH_ROLE = '"""Роль, падающая при старте (моделирует неудачную активацию)."""\nimport sys\nsys.exit(7)\n'


def _commit(repo: Path, version: str, *, crash=False) -> str:
    (repo / "spa_core").mkdir(exist_ok=True)
    (repo / "spa_core" / "__init__.py").write_text("")
    (repo / "spa_core" / "probe_role.py").write_text(_CRASH_ROLE if crash else _LEDGER_ROLE.format(version=version))
    (repo / "spa_core" / "probe_role_two.py").write_text(_LEDGER_ROLE.format(version=version + "-two"))
    (repo / LNCH.AGENT_ROLE_MANIFEST).write_text(json.dumps({"probe": "spa_core.probe_role",
                                                              "probe_two": "spa_core.probe_role_two"}))
    T4._git(["add", "-A"], repo)
    T4._git(["commit", "-q", "-m", f"release {version}"], repo)
    return T4._git(["rev-parse", "HEAD"], repo)


def _ledger(st):
    p = st.state / "ledger.jsonl"
    return [json.loads(l)["version"] for l in p.read_text().splitlines()] if p.exists() else []


def test_every_process_named_failed_activation_returns_to_A_and_data_survive(tmp_path):
    prod_before = T4._prod_footprint()
    st = T4.Stand(tmp_path / "stand")
    try:
        sha_a, sha_b, sha_c = _commit(st.repo, "A"), _commit(st.repo, "B"), _commit(st.repo, "C", crash=True)
        for s in (sha_a, sha_b, sha_c):
            assert RA.materialise_release(s, st.releases, st.repo)[1] == "OK"

        # G1: две роли из A одновременно — замер называет ОБА процесса
        st.approve(sha_a)
        p1, hb1 = st.launch("agent:probe")
        p2, hb2 = st.launch("agent:probe_two")
        assert hb1["version"] == "A" and hb2["version"] == "A-two"
        procs = RS.active_processes(st.releases.resolve())
        st.record("G1.two_processes", processes=procs)
        assert sorted(int(p["pid"]) for p in procs) == sorted([p1.pid, p2.pid]) and {p["sha"] for p in procs} == {sha_a}
        assert RS.active_from_process(st.releases.resolve())["active_sha"] == sha_a   # прежний ответ — подмножество
        st.stop(p1)
        st.stop(p2)

        # G2: одобрен C, роль падает при старте — активация не удалась, C не назван; возврат к A
        st.approve(sha_c)
        pc, hbc = st.launch("agent:probe")
        pc.wait(timeout=30)
        pc.communicate()
        procs_c = RS.active_processes(st.releases.resolve())
        st.record("G2.failed_activation", rc=pc.returncode, heartbeat=hbc, processes=procs_c,
                  active_record=st.active_record())
        assert pc.returncode == 7 and hbc is None and procs_c == []
        # запись active — НАБЛЮДЕНИЕ лаунчера «что запускаю», не доказательство работы: она называет C,
        # а замер по процессам — никого. Поэтому активность судится замером, а не записью.
        assert st.active_record() == sha_c
        st.approve(sha_a)
        pa, hba = st.launch("agent:probe")
        assert hba["version"] == "A" and [p["sha"] for p in RS.active_processes(st.releases.resolve())] == [sha_a]
        st.stop(pa)

        # G3: изменяемые данные вне релиза переживают A → B → A без отката
        st.approve(sha_b)
        pb, hbb = st.launch("agent:probe")
        st.stop(pb)
        st.approve(sha_a)
        pa2, _ = st.launch("agent:probe")
        st.stop(pa2)
        ledger = _ledger(st)
        st.record("G3.ledger", ledger=ledger)
        assert ledger == ["A", "A-two", "A", "B", "A"]          # только дописывалось, ничего не откатилось
        for s in (sha_a, sha_b):
            assert not (st.releases / s / "ledger.jsonl").exists()
            assert RA.verify_release(st.releases / s, s, st.repo) == (True, "")

        # G4: манифест артефакта — рядом с релизом; засчитывается только своему sha
        man = RA.artifact_manifest(sha_a, st.repo, base=None,
                                   criterion={"id": "TASK_04/D1", "verdict": "satisfied", "rev": "2e540689b"},
                                   environment={"python": sys.version.split()[0], "platform": platform.platform()})
        (st.base / "manifests").mkdir()
        (st.base / "manifests" / f"{sha_a}.json").write_text(json.dumps(man))
        assert RA.manifest_matches(man, sha_a, st.repo) == (True, "")
        assert RA.manifest_matches(man, sha_b, st.repo)[0] is False
        forged = {**man, "sha": sha_b}
        assert RA.manifest_matches(forged, sha_b, st.repo) == (False, "дерево или состав манифеста не совпадает с коммитом")
        assert RA.verify_release(st.releases / sha_a, sha_a, st.repo) == (True, "")   # манифест не внутри релиза
    finally:
        st.reap()
    assert st.leftovers() == []
    assert T4._prod_footprint() == prod_before

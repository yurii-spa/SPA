"""S2 задача 04 (E5.5/E5.6 на СТЕНДЕ): настоящий процесс из проверенного релиза A через существующий лаунчер,
переход на одобренный B и откат к A.

Критерии D1–D10 пакета ``docs/evidence/studio-autonomy-01-2026-10-29/s2/TASK_04_isolated_exec_rollback.md`` (до кода).

Что здесь НАСТОЯЩЕЕ: отдельный процесс грузит копию ``release_launcher.py`` и зовёт его ``main`` — тот проверяет
одобрение и состав и делает ``os.execv`` в релиз; запущенная роль работает как процесс ОС, пишет пульс и ждёт
сигнала остановки; ACTIVE меряется штатным ``release_state.active_from_process`` по живому процессу (pgrep + lsof).
Что СИМУЛЯЦИЯ: «доверенный корень» — каталог пользователя под tmp, а не root-owned плоскость; запускатель —
тестовый ``Popen`` вместо launchd; одобрение пишет тест (автор тестовой записи не выдаётся за владельца).
Production, launchd и рабочие данные не затрагиваются (D8 это меряет)."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from spa_core.studio_os import release_activation as RA
from spa_core.studio_os import release_launcher as LNCH
from spa_core.studio_os import release_state as RS

ROLE = "probe"
SERVICE = f"agent:{ROLE}"

_ROLE_SRC = '''"""Безвредная роль стенда S2 задачи 04: пульс в каталог сцены и ожидание остановки. Больше ничего."""
import json
import os
import sys
import time

VERSION = "{version}"


def main():
    d = os.environ.get("STUDIO_PROBE_STATE")
    if not d or not os.path.isdir(d):
        return 0                       # без каталога сцены — ничего не пишет
    pid = os.getpid()
    hb = {{"version": VERSION, "pid": pid, "cwd": os.getcwd(), "file": os.path.abspath(__file__),
          "sys_path0": sys.path[0], "flags_ignore_env": sys.flags.ignore_environment}}
    tmp = os.path.join(d, ".hb-%d" % pid)
    with open(tmp, "w") as f:
        f.write(json.dumps(hb))
    os.replace(tmp, os.path.join(d, "heartbeat-%d.json" % pid))
    stop, deadline = os.path.join(d, "stop-%d" % pid), time.time() + 60
    while time.time() < deadline and not os.path.exists(stop):
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

# Запуск установленного лаунчера так, как его звал бы launchd (`python3 -I <launcher> <service>`), но с корнем
# стенда: ``__main__`` лаунчера НАМЕРЕННО не даёт сменить корень, поэтому обёртка зовёт тот же ``main`` и
# повторяет его код выхода (3 = FAIL_CLOSED). Правила лаунчера не меняются.
_BOOT = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('installed_release_launcher', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
    "r = m.main(sys.argv[4], root=sys.argv[2], active_path=sys.argv[3])\n"
    "if r and r[0] == 'FAIL_CLOSED':\n"
    "    sys.stderr.write('trusted-launcher FAIL_CLOSED: %s\\n' % r[1]); sys.exit(3)\n"
)


class StandError(AssertionError):
    """Нарушен критерий стенда — с названным шагом."""


def _git(args, cwd):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        raise StandError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def _commit_release(repo: Path, version: str) -> str:
    """Коммит с ролью и манифестом роли — ДО материализации и одобрения (ничего не добавляется задним числом)."""
    (repo / "spa_core").mkdir(exist_ok=True)
    (repo / "spa_core" / "__init__.py").write_text("")
    (repo / "spa_core" / "probe_role.py").write_text(_ROLE_SRC.format(version=version))
    (repo / LNCH.AGENT_ROLE_MANIFEST).write_text(json.dumps({ROLE: "spa_core.probe_role"}))
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", f"release {version}"], repo)
    return _git(["rev-parse", "HEAD"], repo)


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if "__pycache__" in p.parts or p.is_dir() and not p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        data = os.readlink(p).encode() if p.is_symlink() else p.read_bytes()
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def _prod_footprint():
    """D8: то, что лаунчер трогает ПО УМОЛЧАНИЮ, — наличие и mtime."""
    out = {}
    for p in (Path(LNCH.ACTIVE_MARKER_PATH), Path(LNCH.TRUSTED_ROOT)):
        try:
            out[str(p)] = os.stat(p).st_mtime_ns
        except OSError:
            out[str(p)] = None
    return out


class Stand:
    def __init__(self, base: Path):
        self.base = Path(base).resolve()
        self.repo = self.base / "repo"
        self.root = self.base / "trusted_root"            # НЕ root-owned: симуляция доверенной плоскости
        self.releases = self.root / "releases"
        self.state = self.base / "role_state"
        self.active = self.base / "active_release.json"
        self.log = self.base / "transitions.jsonl"
        self.procs = []                                   # все Popen, запущенные стендом
        self.seen = set()                                 # пульсы, уже засчитанные шагам
        for d in (self.repo, self.releases, self.state):
            d.mkdir(parents=True)
        _git(["init", "-q", "-b", "main"], self.repo)
        _git(["config", "user.email", "stand@test"], self.repo)
        _git(["config", "user.name", "stand"], self.repo)
        (self.root / "runtime.json").write_text(json.dumps({"app_python": sys.executable,
                                                            "trusted_repo": str(self.repo)}))
        data = Path(LNCH.__file__).read_bytes()          # копия лаунчера из проверяемого дерева = «установка»
        self.launcher = self.base / "bin" / f"release_launcher-{hashlib.sha256(data).hexdigest()}.py"
        self.launcher.parent.mkdir()
        self.launcher.write_bytes(data)
        os.chmod(self.launcher, 0o444)

    # ── действия ──────────────────────────────────────────────────────────────────────────────────────────
    def approve(self, sha):
        (self.root / "approved_release.json").write_text(json.dumps({"approved_sha": sha}))

    def launch(self, service=SERVICE):
        env = dict(os.environ, STUDIO_PROBE_STATE=str(self.state),
                   PYTHONPATH=str(self.repo))            # D2: путь к рабочему дереву — должен игнорироваться
        p = subprocess.Popen([sys.executable, "-I", "-c", _BOOT, str(self.launcher), str(self.root),
                              str(self.active), service], cwd=str(self.repo), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.procs.append(p)
        deadline = time.time() + 30
        while time.time() < deadline:
            fresh = sorted(set(self.state.glob("heartbeat-*.json")) - self.seen)   # ЛЮБОЙ новый пульс, не только pid
            if fresh:
                self.seen.update(fresh)
                return p, json.loads(fresh[0].read_text())
            if p.poll() is not None:
                return p, None
            time.sleep(0.05)
        raise StandError(f"pid {p.pid}: ни пульса, ни выхода за 30 с")

    def stop(self, p):
        (self.state / f"stop-{p.pid}").write_text("")
        rc = p.wait(timeout=30)
        p.communicate()
        if rc != 0:
            raise StandError(f"pid {p.pid} вышел с кодом {rc}")

    def measured_active(self):
        return RS.active_from_process(self.releases)     # штатный замер: pgrep + lsof cwd + .release_sha

    def active_record(self):
        try:
            return json.loads(self.active.read_text()).get("active_sha")
        except OSError:
            return None

    def record(self, step, **kw):
        with open(self.log, "a") as f:
            f.write(json.dumps({"step": step, "t": round(time.time(), 3), **kw}) + "\n")

    def leftovers(self):
        """D7: живые процессы стенда — по Popen и по группе сессии, плюс любой процесс с cwd в релизах стенда."""
        alive = []
        for p in self.procs:
            if p.poll() is None:
                alive.append(f"pid {p.pid} жив")
            try:
                os.killpg(p.pid, 0)
                alive.append(f"группа {p.pid} не пуста")
            except ProcessLookupError:
                pass
            except PermissionError:
                alive.append(f"группа {p.pid}: живость не измерена (EPERM)")
        m = self.measured_active()
        if m["active_verified"]:
            alive.append(f"процесс держит cwd в релизах стенда: {m['active_evidence']}")
        return alive

    def reap(self):
        """Уборка ТОЛЬКО своих процессов (своя группа сессии) — на случай упавшего критерия."""
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait(timeout=10)


def _expect_refusal(st: Stand, step: str, verdict: str):
    before_active, before_hb = st.active_record(), sorted(st.state.glob("heartbeat-*"))
    p, hb = st.launch()
    if hb is not None:                                    # роль исполнилась — назвать это, а не ждать её выхода
        st.record(step, launcher_rc=None, heartbeat=hb, active_record=st.active_record())
        raise StandError(f"{step}: ждали отказ {verdict}, а исполнилась версия {hb['version']} (pid {hb['pid']})")
    p.wait(timeout=30)
    _out, err = p.communicate()
    err = err.decode(errors="replace").strip()
    st.record(step, launcher_rc=p.returncode, stderr=err, heartbeat=hb, active_record=st.active_record())
    if p.returncode != 3 or verdict not in err:
        raise StandError(f"{step}: ждали код 3 и {verdict}, получили {p.returncode} «{err}»")
    if sorted(st.state.glob("heartbeat-*")) != before_hb:
        raise StandError(f"{step}: при отказе появился пульс — роль исполнилась")
    if st.active_record() != before_active:
        raise StandError(f"{step}: при отказе изменилась запись active")


def _expect_running(st: Stand, step: str, sha: str, version: str):
    p, hb = st.launch()
    if hb is None:
        _o, err = p.communicate()
        raise StandError(f"{step}: процесс не запустился, код {p.returncode}: {err.decode(errors='replace')}")
    rel = (st.releases / sha).resolve()
    meas = st.measured_active()
    st.record(step, approved=sha, pid=p.pid, heartbeat=hb, measured=meas, active_record=st.active_record())
    problems = []
    if hb["pid"] != p.pid:
        problems.append(f"pid роли {hb['pid']} ≠ pid лаунчера {p.pid} (не execv)")
    if hb["version"] != version:
        problems.append(f"исполнилась версия {hb['version']}, ждали {version}")
    if Path(hb["cwd"]).resolve() != rel:
        problems.append(f"cwd {hb['cwd']} ≠ {rel}")
    if rel not in Path(hb["file"]).resolve().parents:
        problems.append(f"код роли из {hb['file']}, не из релиза")
    if not hb["flags_ignore_env"]:
        problems.append("интерпретатор роли запущен без -E")
    if not (meas["active_verified"] and meas["active_sha"] == sha):
        problems.append(f"замер ACTIVE {meas}")
    if st.active_record() != sha:
        problems.append(f"запись active {st.active_record()} ≠ {sha}")
    if problems:
        raise StandError(f"{step}: " + "; ".join(problems))
    return p


def run_stand(base: Path) -> dict:
    """Весь сценарий D1–D9. Возвращает сводку; каждый шаг — строка в ``transitions.jsonl``."""
    prod_before = _prod_footprint()
    st = Stand(base)
    try:
        sha_a = _commit_release(st.repo, "A")
        sha_b = _commit_release(st.repo, "B")
        # D2: рабочее дерево ушло вперёд НЕЗАКОММИЧЕННОЙ правкой роли; PYTHONPATH на него указывает (launch)
        (st.repo / "spa_core" / "probe_role.py").write_text(_ROLE_SRC.format(version="WORKTREE"))

        # D3: отказы до какого-либо исполнения
        _expect_refusal(st, "D3.no_approval", "DEPLOYMENT_APPROVAL_REQUIRED")
        st.approve(sha_a)
        _expect_refusal(st, "D3.approved_not_materialised", "APPROVED_RELEASE_MISSING")
        assert RA.materialise_release(sha_a, st.releases, st.repo)[1] == "OK"
        victim = st.releases / sha_a / "spa_core" / "probe_role.py"
        good = victim.read_bytes()
        os.chmod(victim, 0o644)
        victim.write_bytes(good + b"\n# tampered\n")
        _expect_refusal(st, "D3.approved_corrupt", "APPROVED_RELEASE_CORRUPT")
        victim.write_bytes(good)                          # байты возвращены — эталон тот же коммит
        digest_a = _tree_digest(st.releases / sha_a)

        # D1/D2: одобрен A — настоящий процесс из A
        p_a = _expect_running(st, "D1.run_A", sha_a, "A")

        # D4: A работает; кандидат B подготовлен и ПОВРЕЖДЁН, одобрение переключено на B
        assert RA.materialise_release(sha_b, st.releases, st.repo)[1] == "OK"
        bvictim = st.releases / sha_b / "spa_core" / "probe_role.py"
        os.chmod(bvictim, 0o644)
        bvictim.write_bytes(bvictim.read_bytes().replace(b'"B"', b'"EVIL"'))
        st.approve(sha_b)
        _expect_refusal(st, "D4.corrupt_candidate_B", "APPROVED_RELEASE_CORRUPT")
        meas = st.measured_active()
        st.record("D4.after_refusal", a_alive=p_a.poll() is None, measured=meas, active_record=st.active_record())
        if p_a.poll() is not None or meas["active_sha"] != sha_a or st.active_record() != sha_a:
            raise StandError(f"D4: повреждённый кандидат переключил активную версию: {meas}")

        # D5: переход A → B. Повреждённая копия B сохраняется под другим именем, B готовится заново из коммита
        st.stop(p_a)
        os.rename(st.releases / sha_b, st.base / f"corrupt_release_{sha_b[:12]}_kept")
        assert RA.materialise_release(sha_b, st.releases, st.repo)[1] == "OK"
        st.approve(sha_b)
        p_b = _expect_running(st, "D5.run_B", sha_b, "B")

        # D6: откат B → A — повторное одобрение A, каталог A не тронут
        st.stop(p_b)
        st.approve(sha_a)
        p_a2 = _expect_running(st, "D6.rollback_A", sha_a, "A")
        st.stop(p_a2)
        digest_a_after = _tree_digest(st.releases / sha_a)
        ok_a, why_a = RA.verify_release(st.releases / sha_a, sha_a, st.repo)
        st.record("D6.release_A_unchanged", digest_before=digest_a, digest_after=digest_a_after, verify=[ok_a, why_a])
        if digest_a != digest_a_after or not ok_a:
            raise StandError(f"D6: каталог релиза A изменился ({why_a})")
    finally:
        st.reap()
    left = st.leftovers()
    prod_after = _prod_footprint()
    st.record("D7_D8.final", leftovers=left, prod_before=prod_before, prod_after=prod_after,
              processes_started=[p.pid for p in st.procs], return_codes=[p.returncode for p in st.procs])
    if left:
        raise StandError(f"D7: остались процессы стенда: {left}")
    if prod_before != prod_after:
        raise StandError(f"D8: изменились рабочие пути: {prod_before} → {prod_after}")
    return {"sha_a": sha_a, "sha_b": sha_b, "log": str(st.log), "steps": len(st.log.read_text().splitlines()),
            "processes": len(st.procs)}


def test_isolated_stand_runs_A_switches_to_B_and_rolls_back_to_A(tmp_path):
    """D1–D9 целиком: каждый шаг меряется на живом процессе и пишется в журнал переходов сцены."""
    summary = run_stand(tmp_path / "stand")
    steps = [json.loads(l)["step"] for l in Path(summary["log"]).read_text().splitlines()]
    assert steps == ["D3.no_approval", "D3.approved_not_materialised", "D3.approved_corrupt", "D1.run_A",
                     "D4.corrupt_candidate_B", "D4.after_refusal", "D5.run_B", "D6.rollback_A",
                     "D6.release_A_unchanged", "D7_D8.final"], steps
    assert summary["processes"] == 7
    kept = (tmp_path / "stand").resolve() / f"corrupt_release_{summary['sha_b'][:12]}_kept"
    assert b"EVIL" in (kept / "spa_core" / "probe_role.py").read_bytes()   # E5.3: повреждённая копия сохранена


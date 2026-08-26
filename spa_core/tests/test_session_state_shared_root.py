"""Общее состояние сессий живёт в ГЛАВНОМ рабочем дереве, а не в одноразовом worktree.

Дефект-класс (карточка `agent-claim-without-announce-is-invisible`, найден циклом #53,
измерен циклом #54): протокол ОБЯЗЫВАЕТ автономный цикл работать в изолированном git-worktree
(§3.4), а `data/` лежит в `.gitignore`. Значит внутри worktree общего состояния НЕТ:

* `scripts/log_session_change.py` брал журнал как `Path(__file__).parents[1]/data/...` ⇒
  объявление владения, сделанное ПО ПРОТОКОЛУ из worktree, уезжало в
  `<worktree>/data/session_changes.jsonl` и умирало вместе с деревом;
* `scripts/check_undelivered_work.py` (шаг 0a) и `scripts/check_card_claim.py` (шаг 0b),
  запущенные оттуда же, читали тот же пустой файл и отвечали «НЕ ИЗМЕРЕНО» о ЛЮБОЙ сессии
  и ЛЮБОЙ карточке — честно (fail-CLOSED), но бесполезно;
* захват карточки (`claimed_by` во frontmatter) лежит в файле карточки, то есть тоже в дереве
  сессии: до пуша карточка выглядит СВОБОДНОЙ отовсюду.

Так осиротел цикл #52: карточка была взята и доведена до конца, объявление сделано — и всё это
было невидимо. Карточка диагностировала случай как «сессия не объявила владение»; объявление
БЫЛО (`/private/tmp/spa_wt_c52/data/session_changes.jsonl`, запись `pid66309` 04:45:12Z),
невидимым его сделал путь. Поправка измерена, а не предположена, и воспроизводится тестами
`TestAnnounceFromWorktree`.

Здесь пиннится и разрешение общего корня, и обе стороны следствия: объявление из worktree
попадает в главное дерево, а захват карточки ВСЕГДА сопровождается записью в общем журнале
(«взял, но не объявил» — состояние, которого больше нет). Все тесты герметичны: настоящие
git-репозитории в ``tmp_path``, `ps` подменяется, сети нет.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: разрешение общего корня опирается на `git worktree list` "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load(name, filename):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    """Шаг 0a — здесь живёт разрешение общего корня."""
    return _load("_test_shared_root_guard", "check_undelivered_work.py")


@pytest.fixture(scope="module")
def claim():
    """Шаг 0b."""
    return _load("_test_shared_root_claim", "check_card_claim.py")


@pytest.fixture(scope="module")
def announcer():
    """Писатель журнала объявлений."""
    return _load("_test_shared_root_announcer", "log_session_change.py")


# ── герметичный git ──────────────────────────────────────────────────────────

def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env,
    )


@pytest.fixture()
def repo(tmp_path):
    """Главное рабочее дерево с одним коммитом."""
    root = tmp_path / "host"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture()
def linked(repo, tmp_path):
    """Линкованный worktree — ровно та среда, которую предписывает протокол §3.4."""
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", str(wt), "HEAD")
    return wt


def _fake_git(rc=0, out="", err=""):
    def run(cwd, *args):
        return rc, out, err
    return run


# ── А. разрешение общего корня ───────────────────────────────────────────────

# ── Объявленный долгоживущий процесс: без него захват НЕ состоится (цикл #387) ────
#
# Коммит `9cb8a7823` ввёл fail-CLOSED отказ `UnmeasurableClaim`: захват под ярлыком, у
# которого нет объявленного долгоживущего процесса, не записывается вовсе. Причина
# осознанная и записана в самом гейте — такой захват НЕ СТАРЕЕТ (`session_state` отдаёт
# UNKNOWN необратимо, а подъём разрешён только на `stale`), поэтому карточка залипла бы
# навсегда.
#
# Тесты этого файла проверяют механику захвата/освобождения, а не поведение «голого»
# ярлыка, и просто звали инструмент без переменной — на CI все они покраснели, и красным
# стал ВЕСЬ main (карточка `inbox-commit-9cb8a7823-krasit-28-testov-zahvata`).
#
# **Гейт не ослаблен ни на йоту.** Фикстура ставит тесты в ту же законную конфигурацию, в
# которой карточки берутся в проде: `scripts/agent_orchestrator.sh` выставляет
# `SPA_SESSION_PID` перед первым объявлением. Отказ на НЕобъявленном ярлыке проверяется
# отдельно и остаётся красным — см. `test_card_claim_guard.py`.
#
# `os.getpid()` годится по построению: этот процесс выполняется, значит `ps` его видит.
# Предусловие проверяется ЯВНО и при неудаче КРАСНОЕ, а не пропущенное: скип превратил бы
# «не измерено» в «прошло» — ровно то, что запрещает инвариант #17.
@pytest.fixture(autouse=True)
def _declared_durable_process(monkeypatch, announcer):
    import os as _os
    monkeypatch.setenv("SPA_SESSION_PID", str(_os.getpid()))
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-under-test")
    proc, why = announcer.durable_process()
    assert proc.get("session_pid") == _os.getpid(), (
        "предусловие не выполнено: долгоживущий процесс не измерен "
        f"({why!r}) — без него файл проверял бы отказ гейта вместо своей механики, "
        "поэтому это КРАСНЫЙ, а не skip")
    return proc


class TestMainWorktree:
    def test_host_repo_resolves_to_itself(self, guard, repo):
        root, err = guard.main_worktree(repo)
        assert err is None
        assert root == repo.resolve()

    def test_linked_worktree_resolves_to_the_main_tree(self, guard, repo, linked):
        """Суть фикса: из одноразового дерева виден общий корень, а не собственный.

        Пиннится документированный порядок `git worktree list --porcelain` (главное дерево
        первым). Сломайся он — общее состояние молча уехало бы обратно в worktree."""
        root, err = guard.main_worktree(linked)
        assert err is None
        assert root == repo.resolve()
        assert root != linked.resolve()

    def test_shared_log_from_worktree_points_into_the_main_tree(self, guard, repo, linked):
        log, err = guard.shared_log(linked)
        assert err is None
        assert log == repo.resolve() / "data" / "session_changes.jsonl"

    def test_worktree_has_its_own_empty_data_dir(self, guard, repo, linked):
        """Положительный контроль: два пути ДЕЙСТВИТЕЛЬНО разные (иначе тест выше тавтология)."""
        log, _ = guard.shared_log(linked)
        assert log != linked / "data" / "session_changes.jsonl"
        assert not (linked / "data" / "session_changes.jsonl").exists()

    def test_git_failure_is_reported_not_swallowed(self, guard):
        root, err = guard.main_worktree(ROOT, git=_fake_git(rc=127, err="git недоступен"))
        assert root is None
        assert "127" in err

    def test_no_worktree_lines_is_reported(self, guard):
        root, err = guard.main_worktree(ROOT, git=_fake_git(rc=0, out="bare\n"))
        assert root is None
        assert "не назвал" in err

    def test_named_tree_missing_on_disk_is_reported(self, guard, tmp_path):
        gone = tmp_path / "no-such-tree"
        root, err = guard.main_worktree(ROOT, git=_fake_git(rc=0, out=f"worktree {gone}\n"))
        assert root is None
        assert str(gone) in err

    def test_unresolved_falls_back_to_the_old_path_with_a_reason(self, guard):
        """Fail-CLOSED: неудача резолва даёт прежний путь + причину, а не выдуманный корень.

        В хост-репо прежний путь верен; в worktree он пуст ⇒ читатели скажут «НЕ ИЗМЕРЕНО»."""
        log, err = guard.shared_log(ROOT, git=_fake_git(rc=127))
        assert log == guard.DEFAULT_LOG
        assert err and "127" in err


# ── Б. объявление из worktree (воспроизведение случая #52) ───────────────────

def _copy_tools(repo):
    """Положить в фейковый репозиторий ту же пару скриптов, что в проде."""
    (repo / "scripts").mkdir(exist_ok=True)
    for name in ("log_session_change.py", "check_undelivered_work.py",
                 "check_card_claim.py"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "tools")


def _run_announce(script, summary, card=""):
    args = [sys.executable, str(script), "--summary", summary]
    if card:
        args += ["--card", card]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["SPA_SESSION_ID"] = "pid424242"
    return subprocess.run(args, capture_output=True, text=True, env=env)


class TestAnnounceFromWorktree:
    def test_announcement_from_a_worktree_lands_in_the_main_tree(self, repo, tmp_path):
        """Дословное воспроизведение цикла #52: объявление сделано, но из worktree.

        До фикса запись уезжала в `<worktree>/data/session_changes.jsonl`; хост-журнал её
        не видел, и работа целого цикла была невидима для шагов 0a/0b."""
        _copy_tools(repo)
        wt = tmp_path / "wt52"
        _git(repo, "worktree", "add", "--detach", str(wt), "HEAD")

        res = _run_announce(wt / "scripts" / "log_session_change.py", "работа цикла #52",
                            card="agent-demo")
        assert res.returncode == 0, res.stderr

        host_log = repo / "data" / "session_changes.jsonl"
        assert host_log.exists(), "объявление не доехало до главного дерева"
        entry = json.loads(host_log.read_text(encoding="utf-8").splitlines()[-1])
        assert entry["summary"] == "работа цикла #52"
        assert entry["card"] == "agent-demo"
        assert not (wt / "data" / "session_changes.jsonl").exists(), \
            "объявление осталось в одноразовом дереве"

    def test_announcement_from_the_host_repo_is_unchanged(self, repo):
        """Положительный контроль: поведение в хост-репо прежнее (журнал там же, где был)."""
        _copy_tools(repo)
        res = _run_announce(repo / "scripts" / "log_session_change.py", "обычная работа")
        assert res.returncode == 0, res.stderr
        host_log = repo / "data" / "session_changes.jsonl"
        entry = json.loads(host_log.read_text(encoding="utf-8").splitlines()[-1])
        assert entry["summary"] == "обычная работа"

    def test_step_0a_from_a_worktree_reads_the_shared_log(self, repo, tmp_path):
        """Шаг 0a без флагов, запущенный из worktree, видит объявления (раньше — пустоту)."""
        _copy_tools(repo)
        wt = tmp_path / "wt0a"
        _git(repo, "worktree", "add", "--detach", str(wt), "HEAD")
        _run_announce(wt / "scripts" / "log_session_change.py", "объявление для 0a")

        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        res = subprocess.run(
            [sys.executable, str(wt / "scripts" / "check_undelivered_work.py"), "--json"],
            capture_output=True, text=True, env=env)
        payload = json.loads(res.stdout)
        assert payload["log"] == str(repo.resolve() / "data" / "session_changes.jsonl")
        assert payload["unmeasured"] == [] or all(
            "журнала объявлений нет" not in u["reason"] for u in payload["unmeasured"])


# ── В. захват карточки всегда объявлен ───────────────────────────────────────

@pytest.fixture()
def bench(tmp_path):
    """Трекер + журнал + карточка. Журнал существует: пустого журнала claim не допускает
    (fail-CLOSED, поведение прежнее)."""
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    card = tracker / "agent-demo.md"
    card.write_text("---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")
    return {"tracker": tracker, "card": card, "log": log}


def _entries(log):
    return [json.loads(ln) for ln in Path(log).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _dead_ps(pid):
    return 1, ""


#: Якорь долгоживущего процесса для герметичных проверок: фиксированная пара
#: (pid, «старт verbatim»), которую никто не меряет через `ps`.
SELF_ANCHOR = (41721, "Sat Aug  1 13:37:28 2026")


def _claim(mod, *args, **kw):
    """`claim_card` с ЯВНЫМ якорем личности (умолчание читает окружение ПРОГОНА).

    С коммита 9cb8a7823 пустой якорь = отказ `UnmeasurableClaim` ДО проверки предмета,
    а `SPA_SESSION_PID` есть на машине под оркестратором и нет в CI ⇒ один и тот же sha
    давал два разных вердикта (#388). Помощник, а не kwarg на каждом вызове: забыть
    помощника заметнее, чем забыть аргумент.
    """
    kw.setdefault("self_anchor", SELF_ANCHOR)
    return mod.claim_card(*args, **kw)


def _release(mod, *args, **kw):
    """`release_card` с тем же якорем — снимает захват та же личность, что его ставила."""
    kw.setdefault("self_anchor", SELF_ANCHOR)
    return mod.release_card(*args, **kw)


def _gather(mod, *args, **kw):
    """ЧИТАТЕЛЬ герметичен без якоря: `self_anchor=None` — это «я никем не объявлялся».

    Подаётся явно, а не умолчанием: у читателя якорь из окружения совпал бы с якорем
    захватившего (одна и та же переменная), и чужой захват прочитался бы как СВОЙ —
    вердикт `free` там, где тест проверяет `claimed`.
    """
    kw.setdefault("self_anchor", None)
    return mod.gather(*args, **kw)


class TestClaimAlwaysAnnounces:
    def test_claim_writes_an_announce_entry(self, claim, bench):
        _claim(claim, "agent-demo", session="pid5001", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        rows = _entries(bench["log"])
        assert len(rows) == 1
        assert rows[0]["card"] == "agent-demo"
        assert rows[0]["card_state"] == "claim"
        assert rows[0]["session"] == "pid5001", "запись должна нести id ЗАХВАТИВШЕЙ сессии"
        assert str(bench["card"]) in rows[0]["files"]

    def test_claim_in_one_tree_is_seen_as_claimed_from_another(self, claim, bench, tmp_path):
        """Критерий приёмки: карточка, захваченная в /tmp-worktree, занята и из хост-репо.

        Хост-копия карточки НЕ содержит `claimed_by` (пуша ещё не было) — занятость держится
        только на общем журнале."""
        _claim(claim, "agent-demo", session="pid5002", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        host_tracker = tmp_path / "host_tracker"
        host_tracker.mkdir()
        (host_tracker / "agent-demo.md").write_text(
            "---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")

        report = _gather(claim, "agent-demo", log=bench["log"], tracker_dir=host_tracker,
                              self_session="pid9999", ps=_dead_ps)
        assert report["verdict"] == claim.CLAIMED
        assert any(c["session"] == "pid5002" for c in report["claims"])

    def test_without_the_journal_entry_the_same_card_reads_free(self, claim, bench, tmp_path):
        """Положительный контроль к тесту выше: занятость даёт именно запись в журнале.

        Тот же захват во frontmatter дерева сессии, но пустой общий журнал ⇒ `free` — ровно
        то состояние, в котором цикл #53 мог бы взять карточку цикла #52 второй раз."""
        _claim(claim, "agent-demo", session="pid5003", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        host_tracker = tmp_path / "host_tracker2"
        host_tracker.mkdir()
        (host_tracker / "agent-demo.md").write_text(
            "---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")
        empty_log = tmp_path / "empty.jsonl"
        empty_log.write_text("", encoding="utf-8")

        report = _gather(claim, "agent-demo", log=empty_log, tracker_dir=host_tracker,
                              self_session="pid9999", ps=_dead_ps)
        assert report["verdict"] == claim.FREE

    def test_announce_entry_is_a_strong_hit_for_the_reader(self, claim, bench):
        _claim(claim, "agent-demo", session="pid5004", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        strength, detail = claim.entry_hit(_entries(bench["log"])[0], "agent-demo")
        assert strength == claim.STRONG

    def test_claim_refuses_when_the_announcement_fails(self, claim, bench):
        """Fail-CLOSED: не смогли объявить — карточка НЕ взята и файл не тронут."""
        class Broken:
            def record(self, **kw):
                raise OSError("журнал недоступен")

        before = bench["card"].read_text(encoding="utf-8")
        with pytest.raises(claim.AnnounceError):
            _claim(claim, "agent-demo", session="pid5005", tracker_dir=bench["tracker"],
                             log=bench["log"], ps=_dead_ps, announcer=Broken())
        assert bench["card"].read_text(encoding="utf-8") == before
        assert "claimed_by" not in bench["card"].read_text(encoding="utf-8")

    def test_announcement_happens_before_the_card_is_touched(self, claim, bench):
        """Порядок пиннится: при падении между записями безопасное состояние — «занята»."""
        seen = {}

        class Spy:
            def record(self, **kw):
                seen["card_had_claim"] = "claimed_by" in bench["card"].read_text(
                    encoding="utf-8")

        _claim(claim, "agent-demo", session="pid5006", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps, announcer=Spy())
        assert seen["card_had_claim"] is False
        assert "claimed_by: pid5006" in bench["card"].read_text(encoding="utf-8")

    def test_release_announces_done_and_frees_the_card(self, claim, bench):
        _claim(claim, "agent-demo", session="pid5007", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        _release(claim, "agent-demo", session="pid5007", tracker_dir=bench["tracker"],
                           log=bench["log"])
        rows = _entries(bench["log"])
        assert rows[-1]["card_state"] == "done"
        report = _gather(claim, "agent-demo", log=bench["log"], tracker_dir=bench["tracker"],
                              self_session="pid9999", ps=_dead_ps)
        assert report["verdict"] == claim.FREE, "после release карточка обязана быть свободной"

    def test_release_reports_a_failed_announcement(self, claim, bench):
        """Снятие захвата не объявилось — карточка ОТПУЩЕНА, но об этом сказано вслух.

        Направление ошибки безопасное (в журнале захват доживёт окно свежести ⇒ «занята»),
        поэтому молчаливо проглотить исключение было бы ровно классом «утверждение об
        измерении, которого не было»."""
        class Broken:
            def record(self, **kw):
                raise OSError("журнал недоступен")

        _claim(claim, "agent-demo", session="pid5010", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        with pytest.raises(claim.AnnounceError) as exc:
            _release(claim, "agent-demo", session="pid5010", tracker_dir=bench["tracker"],
                               log=bench["log"], announcer=Broken())
        assert "ОТПУЩЕНА" in str(exc.value)
        assert "claimed_by" not in bench["card"].read_text(encoding="utf-8")

    def test_a_card_held_by_another_session_is_still_refused(self, claim, bench):
        """Положительный контроль: прежняя защита от столкновения (#46) на месте."""
        _claim(claim, "agent-demo", session="pid5008", tracker_dir=bench["tracker"],
                         log=bench["log"], ps=_dead_ps)
        with pytest.raises(claim.ClaimError):
            _claim(claim, "agent-demo", session="pid5009", tracker_dir=bench["tracker"],
                             log=bench["log"], ps=_dead_ps)

    def test_announce_error_is_a_claim_error(self, claim):
        """Вызывающий код ловит `ClaimError` — новая ошибка обязана быть её подтипом."""
        assert issubclass(claim.AnnounceError, claim.ClaimError)


# ── Г. писатель журнала: новые параметры аддитивны ───────────────────────────

class TestRecordOverrides:
    def test_explicit_log_wins(self, announcer, tmp_path, monkeypatch):
        other = tmp_path / "other.jsonl"
        default = tmp_path / "default.jsonl"
        monkeypatch.setattr(announcer, "_LOG", default)
        announcer.record("s", [], "", log=other)
        assert _entries(other)[0]["summary"] == "s"
        assert not default.exists()

    def test_default_log_is_still_used_without_the_override(self, announcer, tmp_path,
                                                            monkeypatch):
        """Положительный контроль: без `log=` пишем ровно туда, куда и раньше."""
        default = tmp_path / "default2.jsonl"
        monkeypatch.setattr(announcer, "_LOG", default)
        announcer.record("s2", [], "")
        assert _entries(default)[0]["summary"] == "s2"

    def test_explicit_session_wins(self, announcer, tmp_path, monkeypatch):
        monkeypatch.setenv("SPA_SESSION_ID", "sess-env")
        log = tmp_path / "s.jsonl"
        monkeypatch.setattr(announcer, "_LOG", log)
        announcer.record("s", [], "", session="pid777")
        assert _entries(log)[0]["session"] == "pid777"

    def test_blank_session_falls_back_to_the_writer_id(self, announcer, tmp_path, monkeypatch):
        monkeypatch.setenv("SPA_SESSION_ID", "sess-env")
        log = tmp_path / "s2.jsonl"
        monkeypatch.setattr(announcer, "_LOG", log)
        announcer.record("s", [], "", session="   ")
        assert _entries(log)[0]["session"] == "sess-env"


# ── Д. умолчания CLI ─────────────────────────────────────────────────────────

class TestCliDefaults:
    def test_check_uses_the_shared_log_by_default(self, repo, tmp_path):
        _copy_tools(repo)
        wt = tmp_path / "wtcli"
        _git(repo, "worktree", "add", "--detach", str(wt), "HEAD")
        (repo / "data").mkdir(exist_ok=True)
        (repo / "data" / "session_changes.jsonl").write_text(
            json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "session": "pid8001", "summary": "держу", "files": [],
                        "card": "agent-demo", "card_state": "claim"}) + "\n",
            encoding="utf-8")
        tracker = repo / "nimbalyst-local" / "tracker"
        tracker.mkdir(parents=True, exist_ok=True)
        (tracker / "agent-demo.md").write_text(
            "---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        res = subprocess.run(
            [sys.executable, str(wt / "scripts" / "check_card_claim.py"),
             "--tracker-dir", str(tracker), "--json", "check", "agent-demo"],
            capture_output=True, text=True, env=env)
        payload = json.loads(res.stdout)
        assert payload["log"] == str(repo.resolve() / "data" / "session_changes.jsonl")
        assert payload["verdict"] == "claimed", "свежий чужой захват из общего журнала"
        assert res.returncode == 1

    def test_explicit_log_flag_still_wins(self, repo, tmp_path):
        _copy_tools(repo)
        wt = tmp_path / "wtcli2"
        _git(repo, "worktree", "add", "--detach", str(wt), "HEAD")
        other = tmp_path / "explicit.jsonl"
        other.write_text("", encoding="utf-8")
        tracker = repo / "nimbalyst-local" / "tracker"
        tracker.mkdir(parents=True, exist_ok=True)
        (tracker / "agent-demo.md").write_text(
            "---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        res = subprocess.run(
            [sys.executable, str(wt / "scripts" / "check_card_claim.py"),
             "--tracker-dir", str(tracker), "--log", str(other), "--json",
             "check", "agent-demo"],
            capture_output=True, text=True, env=env)
        payload = json.loads(res.stdout)
        assert payload["log"] == str(other)


class _RacingAnnouncer:
    """Объявитель, который на ПЕРВОМ вызове подсовывает в карточку чужой захват.

    Точка вызова — ровно между вердиктом `gather` и правкой карточки, поэтому это честное
    воспроизведение гонки, а не подмена внутренностей `claim_card`. `break_after` ломает
    последующие объявления (проверка компенсации, которая не удалась)."""

    def __init__(self, claim_mod, card, holder, break_after=None):
        self._claim = claim_mod
        self._card = card
        self._holder = holder
        self._break_after = break_after
        self.calls = 0

    def record(self, **kw):
        self.calls += 1
        if self.calls == 1:
            text = self._card.read_text(encoding="utf-8")
            self._card.write_text(
                text.replace("status: backlog",
                             f"status: backlog\nclaimed_by: {self._holder}\n"
                             f"claimed_at: 2026-07-31T07:35:12Z"), encoding="utf-8")
        if self._break_after is not None and self.calls > self._break_after:
            raise OSError("журнал недоступен")
        return self._claim.load_announcer().record(**kw)


class TestClaimWritePathAgreesWithTheVerdict:
    """Одна функция не должна противоречить сама себе.

    Найдено 31.07 догфудом цикла #56 на ЭТОЙ ЖЕ карточке: `gather` печатал «✅ СВОБОДНА»
    (статус `done` ⇒ захват не действует — действующее правило `TERMINAL_STATUSES`, цикл #50),
    а запись отказывала «карточку успела взять сессия pid94637». Два разных понятия «держит»
    в одной функции: вердикт учитывал статус карточки, путь записи читал `claimed_by` сырым.
    Побочный эффект — объявление уже лежало в общем журнале, т.е. отказ оставлял за сессией
    захват карточки, которой она не владеет."""

    def test_claim_succeeds_when_the_verdict_says_free_on_a_terminal_card(self, claim, bench):
        """Воспроизведение дефекта дословно: статус `done` + чужой `claimed_by`."""
        bench["card"].write_text(
            "---\ntitle: Демо\nstatus: done\nclaimed_by: pid94637\n"
            "claimed_at: 2026-07-31T07:35:12Z\n---\n\nтело\n", encoding="utf-8")
        report = _gather(claim, "agent-demo", log=bench["log"], tracker_dir=bench["tracker"],
                              self_session="pid6001", ps=_dead_ps)
        assert report["verdict"] == claim.FREE, "предпосылка: вердикт — СВОБОДНА"

        res = _claim(claim, "agent-demo", session="pid6001", tracker_dir=bench["tracker"],
                               log=bench["log"], ps=_dead_ps)
        assert res["claimed_by"] == "pid6001", "запись обязана согласиться с вердиктом"

    def test_a_live_foreign_claim_on_an_open_card_is_still_refused(self, claim, bench):
        """Положительный контроль: правило сужено ТОЛЬКО терминальным статусом.

        Карточка открыта (`backlog`) и держится другой сессией — отказ обязан остаться."""
        bench["card"].write_text(
            "---\ntitle: Демо\nstatus: backlog\nclaimed_by: pid7777\n"
            "claimed_at: 2026-07-31T07:35:12Z\n---\n\nтело\n", encoding="utf-8")
        with pytest.raises(claim.ClaimError):
            _claim(claim, "agent-demo", session="pid6002", tracker_dir=bench["tracker"],
                             log=bench["log"], ps=_dead_ps)

    def test_a_refused_claim_leaves_no_claim_in_the_shared_log(self, claim, bench):
        """Отказ не оставляет за сессией захват, которого у неё нет.

        Объявление идёт ДО правки карточки (защита от смерти посередине), поэтому отказ
        обязан компенсироваться записью «захват снят» — иначе следующий цикл пропустит
        свободную карточку по ложной занятости. Гонка воспроизводится честно: чужой захват
        появляется в карточке ПОСЛЕ вердикта `free` и до записи (стороннее объявление —
        ровно та точка между двумя шагами)."""
        racer = _RacingAnnouncer(claim, bench["card"], "pid7777")
        with pytest.raises(claim.ClaimError, match="pid7777"):
            _claim(claim, "agent-demo", session="pid6003", tracker_dir=bench["tracker"],
                             log=bench["log"], ps=_dead_ps, announcer=racer)

        mine = [e for e in _entries(bench["log"]) if e.get("session") == "pid6003"]
        assert mine, "объявление было сделано до правки — оно должно остаться в журнале"
        assert mine[-1]["card_state"] == "done", "последнее слово о захвате — «снят»"

        report = _gather(claim, "agent-demo", log=bench["log"], tracker_dir=bench["tracker"],
                              self_session="pid9999", ps=_dead_ps)
        assert not any(c["session"] == "pid6003" for c in report["claims"]), \
            "сессия, которой отказали, не должна числиться держателем"

    def test_the_refusal_is_not_swallowed_when_compensation_fails(self, claim, bench, capsys):
        """Не смогли компенсировать — отказ всё равно отказ, и об этом сказано вслух."""
        racer = _RacingAnnouncer(claim, bench["card"], "pid7777", break_after=1)
        with pytest.raises(claim.ClaimError, match="pid7777"):
            _claim(claim, "agent-demo", session="pid6004", tracker_dir=bench["tracker"],
                             log=bench["log"], ps=_dead_ps, announcer=racer)
        assert "не компенсирован" in capsys.readouterr().err

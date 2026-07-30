"""Гарантия шага 0 протокола: «объявил владение → доставил ли на origin?».

Дефект-класс (карточка `agent-undelivered-work-guard`, найден циклом #44): сессия
объявляет владение файлами (`scripts/log_session_change.py`), работает в изолированном
worktree, пишет в STATE/журнал отчёт **как о доставленной работе** — и умирает до пуша.
На `origin/main` кода нет, отчёт есть. За одни сутки 30.07 так осиротела работа ЧЕТЫРЁХ
сессий (#41 `pid31439`, #42 `pid38822`, #43 `pid50691`/`pid54926`), и каждый раз это
находила СЛЕДУЮЩАЯ сессия вручную, пофайлово.

`scripts/check_undelivered_work.py` — детерминированная read-only проверка (stdlib, без
сети): объявление старше окна ожидания + активность сессии не подтверждена + объявленного
файла на базовом ref нет (или он там другой) ⇒ находка. Всё, что измерить не удалось,
публикуется как «НЕ ИЗМЕРЕНО» и даёт НЕ зелёный код возврата (fail-CLOSED, инв. #2) —
молчаливое «всё доставлено» запрещено.

Отдельно пиннится честность формулировки: «процесса pid<N> нет» **не** объявляется смертью
сессии. `log_session_change.py` пишет pid ОДНОКРАТНОГО CLI-процесса (`SPA_SESSION_ID` в
проде не выставлен), поэтому отсутствие процесса не доказывает ничего — решает возраст
объявления, и именно он публикуется как основание находки.

Все тесты герметичны: настоящие git-репозитории строятся в ``tmp_path``, `ps` подменяется
фикстурой, сети нет.
"""
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: проверка сверяет объявленные файлы с базовым ref "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load():
    """Загрузить скрипт по явному пути (`scripts/` — не пакет)."""
    path = ROOT / "scripts" / "check_undelivered_work.py"
    spec = importlib.util.spec_from_file_location("_test_undelivered_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


# ── git-хелперы (герметично, без глобального конфига прогоняющего) ────────────

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
    """Репозиторий с веткой `base` (роль origin/main) и рабочим деревом поверх неё."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    (r / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "branch", "base")
    return r


# ── фиктивный ps: (rc, stdout) по pid ────────────────────────────────────────

_LSTART_OLD = "Wed Jan 14 10:00:00 2026"   # раньше объявления → активность подтверждена
_LSTART_NEW = "Fri Jan 16 23:00:00 2026"   # позже объявления → pid переиспользован

_NOW = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)     # объявления старше окна ожидания


def fake_ps(table):
    def _ps(pid):
        return table.get(pid, (1, ""))     # нет в таблице ⇒ процесса нет
    return _ps


def entry(session, files, ts="2026-01-15T12:00:00Z", summary="работа"):
    return {"ts": ts, "session": session, "summary": summary, "files": [str(f) for f in files]}


def report(guard, repo, entries, ps=None, self_session="pid999999", now=_NOW, grace_hours=3.0):
    return guard.build_report(
        entries=entries,
        root=repo,
        base_ref="base",
        self_session=self_session,
        ps=ps if ps is not None else fake_ps({}),
        now=now,
        grace_hours=grace_hours,
    )


# ── 1. ядро: мёртвая сессия, файла на базе нет ───────────────────────────────

class TestAbsentOnBase:
    def test_new_file_never_delivered_is_reported(self, guard, repo):
        """Точная форма случая #42/#43: новый тест-файл существует локально, на базе его нет."""
        (repo / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "brand_new.py"])])
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert rep["findings"][0]["path"] == "scripts/brand_new.py"
        assert rep["findings"][0]["session"] == "pid31439"
        assert rep["exit_code"] == 1

    def test_modified_file_not_delivered_is_reported_as_differs(self, guard, repo):
        """Форма случая #41: файл на базе ЕСТЬ, но правка сессии до него не доехала."""
        (repo / "scripts" / "kept.py").write_text("fixed content\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert [f["state"] for f in rep["findings"]] == [guard.DIFFERS]
        assert rep["exit_code"] == 1

    def test_delivered_file_is_not_a_finding(self, guard, repo):
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert rep["findings"] == []
        assert rep["unmeasured"] == []
        assert rep["exit_code"] == 0

    def test_declared_file_missing_everywhere_says_so_verbatim(self, guard, repo):
        """Объявлено авансом и не создано — это находка, но человеку видно, что локально файла тоже нет."""
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "never_written.py"])])
        assert rep["findings"][0]["state"] == guard.ABSENT
        assert "локально" in rep["findings"][0]["detail"]

    def test_same_file_declared_by_many_sessions_is_one_finding(self, guard, repo):
        """STATE и журнал объявляет почти каждая сессия — иначе одна находка размножается
        по числу записей. Атрибуции содержимого нет, поэтому объявившие просто перечислены."""
        (repo / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid1", [repo / "scripts" / "brand_new.py"]),
                                   entry("pid2", [repo / "scripts" / "brand_new.py"]),
                                   entry("pid3", [repo / "scripts" / "brand_new.py"])])
        assert len(rep["findings"]) == 1
        assert rep["findings"][0]["session"] == "pid1"
        assert rep["findings"][0]["also_declared_by"] == ["pid2", "pid3"]

    def test_stale_local_copy_already_in_origin_history_is_not_a_finding(self, guard, repo):
        """«git push API drift»: пуш уходит прямо в origin, локальная копия навсегда остаётся
        прежней. Это НЕ потерянная работа — и содержимое доказуемо уже было на origin."""
        (repo / "scripts" / "kept.py").write_text("вторая версия\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "v2")
        _git(repo, "branch", "-f", "base", "HEAD")
        (repo / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")   # откат к v1
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert rep["findings"] == []
        assert [s["path"] for s in rep["stale_copies"]] == ["scripts/kept.py"]
        assert rep["exit_code"] == 0

    def test_content_absent_from_origin_history_is_a_finding(self, guard, repo):
        """Контроль к предыдущему: содержимого, которого на origin НИКОГДА не было, — находка."""
        (repo / "scripts" / "kept.py").write_text("такого на origin не было\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert [f["state"] for f in rep["findings"]] == [guard.DIFFERS]
        assert rep["stale_copies"] == []

    def test_all_declared_files_of_one_entry_are_checked(self, guard, repo):
        (repo / "a.py").write_text("x\n", encoding="utf-8")
        (repo / "b.py").write_text("y\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "a.py", repo / "b.py",
                                                      repo / "scripts" / "kept.py"])])
        assert sorted(f["path"] for f in rep["findings"]) == ["a.py", "b.py"]


# ── 2. живую сессию не трогаем (иначе шаг 0 станет шумом) ────────────────────

class TestLiveSessionsNeverReported:
    def test_self_session_is_never_reported(self, guard, repo):
        """Своя же работа в процессе — не находка (acceptance-критерий карточки)."""
        (repo / "wip.py").write_text("wip\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid4242", [repo / "wip.py"])], self_session="pid4242")
        assert rep["findings"] == []
        assert rep["unmeasured"] == []
        assert rep["exit_code"] == 0

    def test_running_session_is_never_reported(self, guard, repo):
        """Чужая ЖИВАЯ сессия (процесс стартовал ДО объявления) — не находка."""
        (repo / "wip.py").write_text("wip\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid4242", [repo / "wip.py"])],
                     ps=fake_ps({4242: (0, _LSTART_OLD + "\n")}))
        assert rep["findings"] == []
        assert rep["exit_code"] == 0

    def test_reused_pid_does_not_confirm_activity(self, guard, repo):
        """Анти-fail-OPEN: pid существует, но процесс СТАРТОВАЛ ПОЗЖЕ объявления —
        это ДРУГОЙ процесс, активность сессии им не подтверждается. Наивная проверка
        «pid есть ⇒ жива» молча пропустила бы недоставленную работу."""
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid4242", [repo / "orphan.py"])],
                     ps=fake_ps({4242: (0, _LSTART_NEW + "\n")}))
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert rep["exit_code"] == 1


# ── 2b. окно ожидания: работа «в полёте» — не находка ────────────────────────

class TestGraceWindow:
    """Ключевая поправка к карточке: `pid` из journal'а — это pid ОДНОКРАТНОГО
    CLI-процесса `log_session_change.py`, он мёртв всегда. Без окна ожидания шаг 0
    объявлял бы недоставленной собственную работу текущей сессии."""

    def test_fresh_announcement_is_not_a_finding(self, guard, repo):
        (repo / "in_flight.py").write_text("работа идёт\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "in_flight.py"])],
                     now=datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc))   # +1ч
        assert rep["findings"] == []
        assert rep["unmeasured"] == []
        assert len(rep["fresh"]) == 1
        assert rep["fresh"][0]["age_hours"] == 1.0
        assert rep["exit_code"] == 0

    def test_stale_announcement_past_grace_is_a_finding(self, guard, repo):
        (repo / "in_flight.py").write_text("работа осиротела\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "in_flight.py"])],
                     now=datetime(2026, 1, 15, 16, 1, tzinfo=timezone.utc))   # +4ч01м
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert rep["fresh"] == []

    def test_grace_window_is_configurable(self, guard, repo):
        (repo / "in_flight.py").write_text("работа идёт\n", encoding="utf-8")
        now = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)
        assert report(guard, repo, [entry("pid31439", [repo / "in_flight.py"])],
                      now=now, grace_hours=0.5)["findings"]
        assert not report(guard, repo, [entry("pid31439", [repo / "in_flight.py"])],
                          now=now, grace_hours=24)["findings"]

    def test_finding_states_the_measured_age_not_a_death_claim(self, guard, repo):
        """Основание находки — измеренный возраст, а не выдуманная «смерть сессии»."""
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "orphan.py"])])
        why = rep["findings"][0]["session_state"]
        assert "объявлено" in why and "ч назад" in why
        assert "мертв" not in why.lower()


# ── 3. fail-CLOSED: «не смог измерить» ≠ «всё доставлено» ────────────────────

class TestFailClosed:
    def test_unparsable_process_start_is_unmeasured_not_alive(self, guard, repo):
        rep = report(guard, repo, [entry("pid4242", [repo / "x.py"])],
                     ps=fake_ps({4242: (0, "не-дата\n")}))
        assert rep["findings"] == []
        assert len(rep["unmeasured"]) == 1
        assert "не-дата" in rep["unmeasured"][0]["reason"]     # причина цитируется вербатим
        assert rep["exit_code"] == 2

    def test_ps_unavailable_is_unmeasured(self, guard, repo):
        rep = report(guard, repo, [entry("pid4242", [repo / "x.py"])],
                     ps=fake_ps({4242: (127, "")}))
        assert rep["unmeasured"] and rep["exit_code"] == 2

    def test_session_id_without_pid_is_unmeasured(self, guard, repo):
        rep = report(guard, repo, [entry("headless-runner-7", [repo / "x.py"])])
        assert rep["findings"] == []
        assert "headless-runner-7" in rep["unmeasured"][0]["reason"]
        assert rep["exit_code"] == 2

    def test_unparsable_entry_timestamp_is_unmeasured(self, guard, repo):
        """Без метки времени нельзя измерить возраст объявления ⇒ решение не принимается."""
        rep = report(guard, repo, [entry("pid4242", [repo / "x.py"], ts="не-дата")])
        assert rep["findings"] == []
        assert rep["unmeasured"] and rep["exit_code"] == 2

    def test_path_outside_repo_is_unmeasured_not_ignored(self, guard, repo, tmp_path):
        """Путь в удалённом /tmp-worktree измерить нельзя — молча пропустить нельзя тоже."""
        rep = report(guard, repo, [entry("pid31439", [tmp_path / "gone_wt" / "f.py"])])
        assert rep["findings"] == []
        assert rep["unmeasured"] and rep["exit_code"] == 2

    def test_unmeasured_wins_over_findings_in_exit_code(self, guard, repo):
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "orphan.py"]),
                                   entry("headless-runner-7", [repo / "orphan.py"])])
        assert rep["findings"] and rep["unmeasured"]
        assert rep["exit_code"] == 2

    def test_missing_base_ref_is_not_green(self, guard, repo):
        rep = guard.build_report(entries=[entry("pid31439", [repo / "scripts" / "kept.py"])],
                                 root=repo, base_ref="origin/nope",
                                 self_session="pid999999", ps=fake_ps({}))
        assert rep["findings"] == []
        assert rep["unmeasured"] and rep["exit_code"] == 2
        assert "origin/nope" in json.dumps(rep, ensure_ascii=False)

    def test_root_is_not_a_git_repo_is_not_green(self, guard, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        rep = guard.build_report(entries=[entry("pid31439", [plain / "f.py"])],
                                 root=plain, base_ref="base",
                                 self_session="pid999999", ps=fake_ps({}))
        assert rep["exit_code"] == 2


# ── 4. чтение журнала объявлений ─────────────────────────────────────────────

class TestLogReading:
    def test_last_n_takes_the_newest_entries(self, guard, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text("".join(json.dumps(entry(f"pid{i}", [], summary=f"s{i}")) + "\n"
                               for i in range(10)), encoding="utf-8")
        rows, bad = guard.read_entries(log, last=3)
        assert [r["summary"] for r in rows] == ["s7", "s8", "s9"]
        assert bad == 0

    def test_all_entries_when_last_is_none(self, guard, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text("".join(json.dumps(entry(f"pid{i}", [])) + "\n" for i in range(10)),
                       encoding="utf-8")
        rows, _ = guard.read_entries(log, last=None)
        assert len(rows) == 10

    def test_malformed_line_is_counted_not_silently_dropped(self, guard, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text(json.dumps(entry("pid1", [])) + "\n{битая строка\n", encoding="utf-8")
        rows, bad = guard.read_entries(log, last=None)
        assert len(rows) == 1 and bad == 1

    def test_missing_log_is_reported_as_unmeasured(self, guard, repo, tmp_path):
        rc = guard.main(["--root", str(repo), "--base", "base",
                         "--log", str(tmp_path / "nope.jsonl")])
        assert rc == 2


# ── 5. worktree того же репозитория ──────────────────────────────────────────

class TestWorktreePaths:
    def test_path_inside_linked_worktree_maps_to_repo_relative(self, guard, repo, tmp_path):
        """Протокол ОБЯЗЫВАЕТ worktree (§3.4) — объявленный worktree-путь должен проверяться,
        а не уходить в «не измерено»."""
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "--detach", str(wt), "base")
        (wt / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "brand_new.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/brand_new.py"]

    def test_path_in_a_foreign_repo_is_unmeasured(self, guard, repo, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        _git(tmp_path, "init", "-q", str(other))
        (other / "f.py").write_text("x\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [other / "f.py"])])
        assert rep["findings"] == []
        assert rep["unmeasured"] and rep["exit_code"] == 2

    def test_change_living_only_in_a_worktree_is_found(self, guard, repo, tmp_path):
        """Главный сценарий карточки: правка осталась в /tmp-worktree, хост-дерево её не
        видело (пуш идёт прямо в origin, локальный git дрейфует), на базе её нет.
        Сверка только с хост-деревом такую работу пропускает — проверено историческим
        прогоном на настоящем `session_changes.jsonl`."""
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "--detach", str(wt), "base")
        (wt / "scripts" / "kept.py").write_text("исправлено в worktree\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert [f["state"] for f in rep["findings"]] == [guard.DIFFERS]
        assert str(wt) in rep["findings"][0]["detail"]

    def test_worktree_listing_failure_is_unmeasured(self, guard, repo, monkeypatch):
        """Не смогли перечислить рабочие деревья ⇒ сверка была бы неполной ⇒ не «всё ОК»."""
        real = guard._git

        def spy(cwd, *args):
            if args[:1] == ("worktree",):
                return 1, "", "boom"
            return real(cwd, *args)

        rep = guard.build_report(entries=[entry("pid31439", [repo / "scripts" / "kept.py"])],
                                 root=repo, base_ref="base", self_session="pid999999",
                                 ps=fake_ps({}), git=spy, now=_NOW)
        assert rep["findings"] == []
        assert rep["unmeasured"] and rep["exit_code"] == 2

    def test_stale_clean_checkout_is_not_a_finding(self, guard, repo, tmp_path):
        """Класс ложных срабатываний, измеренный на живых данных: заброшенный worktree стоит
        на СТАРОМ коммите и расходится с origin в сотнях файлов, которых никто не трогал.
        Работы там нет (дерево чистое) ⇒ и находки быть не должно."""
        old = _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "scripts" / "kept.py").write_text("продвинулись вперёд\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base ушла вперёд")
        _git(repo, "branch", "-f", "base", "HEAD")
        _git(repo, "checkout", "-q", old)                 # хост-дерево тоже отстало, но чисто
        stale = tmp_path / "stale"
        _git(repo, "worktree", "add", "-q", "--detach", str(stale), old)
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert rep["findings"] == []
        assert rep["exit_code"] == 0

    def test_diff_failure_in_one_checkout_is_unmeasured(self, guard, repo, tmp_path):
        """Одно дерево не сравнилось ⇒ вывод «всё доставлено» был бы про непроверенное."""
        real = guard._git

        def spy(cwd, *args):
            if "diff" in args:
                return 128, "", "boom"
            return real(cwd, *args)

        rep = guard.build_report(entries=[entry("pid31439", [repo / "scripts" / "kept.py"])],
                                 root=repo, base_ref="base", self_session="pid999999",
                                 ps=fake_ps({}), git=spy, now=_NOW)
        assert rep["unmeasured"] and rep["exit_code"] == 2

    def test_relative_path_is_treated_as_repo_relative(self, guard, repo):
        (repo / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", ["scripts/brand_new.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/brand_new.py"]


# ── 6. CLI: коды возврата и вывод ────────────────────────────────────────────

class TestCli:
    def _log(self, tmp_path, entries):
        log = tmp_path / "log.jsonl"
        log.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                       encoding="utf-8")
        return log

    def test_exit_zero_only_when_everything_measured_and_delivered(self, guard, repo, tmp_path, monkeypatch):
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        log = self._log(tmp_path, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert guard.main(["--root", str(repo), "--base", "base", "--log", str(log)]) == 0

    def test_exit_one_on_findings(self, guard, repo, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        log = self._log(tmp_path, [entry("pid31439", [repo / "orphan.py"])])
        assert guard.main(["--root", str(repo), "--base", "base", "--log", str(log)]) == 1
        out = capsys.readouterr().out
        assert "orphan.py" in out and "pid31439" in out

    def test_json_output_is_machine_readable(self, guard, repo, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        log = self._log(tmp_path, [entry("pid31439", [repo / "orphan.py"])])
        guard.main(["--root", str(repo), "--base", "base", "--log", str(log), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["findings"][0]["path"] == "orphan.py"
        assert payload["base_ref"] == "base"
        assert payload["exit_code"] == 1

    def test_output_never_claims_ok_when_something_unmeasured(self, guard, repo, tmp_path, monkeypatch, capsys):
        """Ровно тот класс дефектов, что чинили циклы #29–#40: «OK» о непроверенном."""
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({4242: (0, "не-дата\n")}))
        log = self._log(tmp_path, [entry("pid4242", [repo / "scripts" / "kept.py"])])
        rc = guard.main(["--root", str(repo), "--base", "base", "--log", str(log)])
        out = capsys.readouterr().out
        assert rc == 2
        assert "НЕ ИЗМЕРЕНО" in out
        assert "всё доставлено" not in out

    def test_clean_run_says_measured_and_delivered(self, guard, repo, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        log = self._log(tmp_path, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        guard.main(["--root", str(repo), "--base", "base", "--log", str(log)])
        assert "всё доставлено" in capsys.readouterr().out


# ── 7. скрипт остаётся read-only и stdlib-only ───────────────────────────────

class TestInvariants:
    def test_script_writes_nothing(self, guard, repo, tmp_path, monkeypatch):
        """Шаг 0 не должен ничего менять: ни файлов, ни индекса git."""
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        log = tmp_path / "log.jsonl"
        log.write_text(json.dumps(entry("pid31439", [repo / "orphan.py"])) + "\n", encoding="utf-8")
        before = {p: p.stat().st_mtime_ns for p in sorted(repo.rglob("*")) if p.is_file()}
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        guard.main(["--root", str(repo), "--base", "base", "--log", str(log)])
        after = {p: p.stat().st_mtime_ns for p in sorted(repo.rglob("*")) if p.is_file()}
        assert before == after
        assert _git(repo, "status", "--porcelain").stdout.count("orphan.py") == 1

    def test_no_network_and_no_third_party_imports(self, guard):
        """Инвариант #4 (только stdlib) + шаг 0 не ходит в сеть: `git fetch` внутри запрещён."""
        src = (ROOT / "scripts" / "check_undelivered_work.py").read_text(encoding="utf-8")
        for banned in ("import requests", "import urllib.request", "from urllib",
                       "import web3", "import numpy", "import pandas", "anthropic", "openai"):
            assert banned not in src, banned

    def test_git_fetch_is_never_invoked(self, guard, repo, tmp_path, monkeypatch):
        calls = []
        real = guard._git

        def spy(cwd, *args):
            calls.append(args)
            return real(cwd, *args)

        monkeypatch.setattr(guard, "_git", spy)
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        log = tmp_path / "log.jsonl"
        log.write_text(json.dumps(entry("pid31439", [repo / "scripts" / "kept.py"])) + "\n",
                       encoding="utf-8")
        guard.main(["--root", str(repo), "--base", "base", "--log", str(log)])
        assert calls and all(a[0] != "fetch" for a in calls)

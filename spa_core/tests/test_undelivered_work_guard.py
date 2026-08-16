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


def report_with_git(guard, repo, entries, git, **kw):
    """То же, но с подменённым git — нужно там, где состояние репозитория подделать нельзя
    (например «git считает дерево живым, а привязка не читается»)."""
    kw.setdefault("ps", fake_ps({}))
    return guard.build_report(entries=entries, root=repo, base_ref="base",
                              self_session="pid999999", now=_NOW, grace_hours=3.0,
                              git=git, **kw)


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

    def test_declared_file_missing_everywhere_is_judged_nowhere_not_undelivered(self, guard, repo):
        """ИНВ. #16 — тест изменён НАМЕРЕННО (цикл #243, карточка
        `inbox-shag-0a-vechno-dokladyvaet-o-faile-kotor`). Вход не изменился ни на байт;
        изменился ожидаемый ВЕРДИКТ: объявленное авансом и не созданное имя больше не
        зачисляется в «НЕ ДОСТАВЛЕНО» (что читается как «есть потерянная работа, подними её»),
        а получает собственное суждение «поднимать нечего». Прежняя редакция утверждала ровно
        то поведение, которое карточка называет дефектом, и проверяла его слабо — по подстроке
        «локально» в тексте. Проверка УСИЛЕНА: утверждается место записи, вердикт, ненулевой
        код возврата И отсутствие записи в findings — то есть что находка не исчезла в тишину.
        Обратная сторона (файл ЛЕЖИТ в дереве ⇒ по-прежнему находка) закреплена отдельным
        положительным контролем в `TestDeclaredNameThatNeverExisted`."""
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "never_written.py"])])
        assert rep["findings"] == []
        assert [f["path"] for f in rep["nowhere"]] == ["scripts/never_written.py"]
        assert rep["nowhere"][0]["state"] == guard.NOWHERE
        assert "НИГДЕ" in rep["nowhere"][0]["detail"]
        assert rep["exit_code"] == 1                      # молчанием это не покупается

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


# ── 2a. личность САМОЙ проверки: молчать вправе только ДОВЕРЕННАЯ ────────────

class TestUntrustedSelfIdentity:
    """Положительный контроль аварии 14.08 (цикл #223) — но уже в ПРОДЕ, а не в тесте.

    `main()` без `SPA_SESSION_ID` называет себя `pid<os.getpid()>` — pid ОДНОКРАТНОЙ
    CLI-команды. Совпади он с чужим идентификатором — чужое объявление молча выпало бы из
    отчёта: fail-OPEN внутри сторожа, который весь построен как fail-CLOSED. Это не
    гипотеза: на Linux-раннере прогон получил pid **4242**, совпавший с фикстурой
    `pid4242`, и проверка вернула «всё измерено» вместо «не измерено». Тогда починили ТЕСТ
    (личность в `TestCli` задаётся явно), прод остался — вот он.
    """

    def _rep(self, guard, repo, entries, *, trusted, session="pid4242", ps=None, now=_NOW):
        return guard.build_report(
            entries=entries, root=repo, base_ref="base", self_session=session,
            self_session_trusted=trusted, ps=ps if ps is not None else fake_ps({}),
            now=now, grace_hours=3.0,
        )

    def test_untrusted_collision_does_not_hide_foreign_work(self, guard, repo):
        """Ядро починки: pid проверки совпал с чужим id ⇒ работа всё равно находка."""
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        rep = self._rep(guard, repo, [entry("pid4242", [repo / "orphan.py"])], trusted=False)
        assert [f["path"] for f in rep["findings"]] == ["orphan.py"]
        assert rep["exit_code"] == 1

    def test_trusted_identity_still_skips_own_record(self, guard, repo):
        """Контроль в ОБРАТНУЮ сторону: при явной личности своя запись по-прежнему молчит."""
        (repo / "wip.py").write_text("wip\n", encoding="utf-8")
        rep = self._rep(guard, repo, [entry("pid4242", [repo / "wip.py"])], trusted=True)
        assert rep["findings"] == []
        assert rep["unmeasured"] == []
        assert rep["exit_code"] == 0

    def test_collision_is_named_aloud_not_measured_silently(self, guard, repo):
        """Недоверенная личность — не молчание и не тайна: совпадение сказано словами."""
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        rep = self._rep(guard, repo, [entry("pid4242", [repo / "orphan.py"])], trusted=False)
        why = rep["findings"][0]["session_state"]
        assert "доверенной не является" in why and "pid4242" in why

    def test_untrusted_collision_obeys_grace_window_not_auto_finding(self, guard, repo):
        """Починка не должна стать шумом (п.2 карточки): свежее объявление — не находка,
        оно уходит в окно ожидания по ОБЫЧНЫМ правилам."""
        (repo / "in_flight.py").write_text("работа идёт\n", encoding="utf-8")
        rep = self._rep(guard, repo, [entry("pid4242", [repo / "in_flight.py"])], trusted=False,
                        now=datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc))   # +1ч
        assert rep["findings"] == []
        assert [f["session"] for f in rep["fresh"]] == ["pid4242"]
        assert rep["exit_code"] == 0

    def test_untrusted_collision_with_a_live_process_is_still_active(self, guard, repo):
        """Не «всё подряд в находки»: живой процесс, стартовавший ДО объявления, —
        подтверждённая активность, даже когда id совпал с личностью проверки."""
        (repo / "wip.py").write_text("wip\n", encoding="utf-8")
        rep = self._rep(guard, repo, [entry("pid4242", [repo / "wip.py"])], trusted=False,
                        ps=fake_ps({4242: (0, _LSTART_OLD + "\n")}))
        assert rep["findings"] == []
        assert rep["sessions_active"] == 1
        assert rep["exit_code"] == 0

    def test_untrusted_collision_keeps_fail_closed_on_unmeasurable(self, guard, repo):
        """`ps` не отработал ⇒ «не измерено», а не «это мы сами»."""
        rep = self._rep(guard, repo, [entry("pid4242", [repo / "scripts" / "kept.py"])],
                        trusted=False, ps=fake_ps({4242: (0, "не-дата\n")}))
        assert rep["exit_code"] == 2
        assert [u["session"] for u in rep["unmeasured"]] == ["pid4242"]

    def test_cli_without_env_identity_is_untrusted(self, guard, repo, tmp_path, monkeypatch, capsys):
        """Эффект через `main()`: БЕЗ `SPA_SESSION_ID` личность выведена из pid прогона.
        Подставляем ровно ту коллизию, что случилась на раннере, — находка обязана выжить."""
        monkeypatch.delenv("SPA_SESSION_ID", raising=False)
        monkeypatch.setattr(guard.os, "getpid", lambda: 4242)
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        log = tmp_path / "log.jsonl"
        log.write_text(json.dumps(entry("pid4242", [repo / "orphan.py"]),
                                  ensure_ascii=False) + "\n", encoding="utf-8")
        rc = guard.main(["--root", str(repo), "--base", "base", "--log", str(log)])
        assert rc == 1
        assert "orphan.py" in capsys.readouterr().out

    def test_cli_with_env_identity_is_trusted(self, guard, repo, tmp_path, monkeypatch):
        """Та же коллизия, но личность названа ЯВНО — своя запись по-прежнему пропускается."""
        monkeypatch.setenv("SPA_SESSION_ID", "pid4242")
        monkeypatch.setattr(guard.os, "getpid", lambda: 4242)
        monkeypatch.setattr(guard, "_ps_lstart", fake_ps({}))
        (repo / "orphan.py").write_text("orphan\n", encoding="utf-8")
        log = tmp_path / "log.jsonl"
        log.write_text(json.dumps(entry("pid4242", [repo / "orphan.py"]),
                                  ensure_ascii=False) + "\n", encoding="utf-8")
        assert guard.main(["--root", str(repo), "--base", "base", "--log", str(log)]) == 0


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


# ── 2c. окно ждёт ЖИВУЮ сессию, а не любую свежую запись ─────────────────────

_IN_WINDOW = datetime(2026, 1, 15, 13, 18, tzinfo=timezone.utc)   # +1.3ч к объявлению


def durable_entry(session, files, pid, start=_LSTART_OLD, ts="2026-01-15T12:00:00Z",
                  summary="работа"):
    """Объявление сессии, назвавшей СВОЙ долгоживящий процесс (`SPA_SESSION_PID`)."""
    e = entry(session, files, ts=ts, summary=summary)
    e["session_pid"], e["session_pid_start"] = pid, start
    return e


class TestOrphanInsideGraceWindow:
    """Замер 14.08 (карточка `inbox-shag-0a-svezhee-obyavlenie-mertvoi-sessi`).

    Цикл #232 увидел объявление цикла #231 возрастом 1.34 ч в разделе «свежие — работа может
    идти» и прошёл бы мимо: в `/tmp`-дереве лежало готовое исполнение решения владельца
    (ADR-085, агент, 16 тестов), которого на `origin/main` не было вовсе. Инструмент ЗНАЛ —
    он тут же печатал «долгоживущий процесс сессии pid71512 завершился», — и всё равно
    относил запись к «работа может идти».

    Находкой делает только СОЧЕТАНИЕ трёх условий: свежее объявление + измеренно завершившийся
    ДОЛГОЖИВУЩИЙ процесс + путь, которого на базе нет. Каждое по отдельности — не находка,
    и на это ниже стоят обратные контроли: иначе вернётся класс «две сессии взяли одну
    карточку» (#230, шаг 0b), ради которого окно и существует.
    """

    def test_dead_durable_session_inside_window_is_a_finding(self, guard, repo):
        """Положительный контроль #231: 1.3 ч назад, процесс мёртв, файла на базе нет."""
        (repo / "scripts" / "adr085_agent.py").write_text("готовая работа\n", encoding="utf-8")
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "adr085_agent.py"], 71512)],
                     ps=fake_ps({}), now=_IN_WINDOW)          # 71512 не в таблице ⇒ процесса нет
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert rep["findings"][0]["path"] == "scripts/adr085_agent.py"
        assert rep["findings"][0]["within_grace"] is True
        assert rep["fresh"] == []
        assert rep["exit_code"] == 1

    def test_finding_says_the_window_has_not_expired_but_nobody_is_coming_back(self, guard, repo):
        """Формулировка обязана называть ОБА измерения — иначе читается как обычный просрочек."""
        (repo / "scripts" / "adr085_agent.py").write_text("готовая работа\n", encoding="utf-8")
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "adr085_agent.py"], 71512)],
                     ps=fake_ps({}), now=_IN_WINDOW)
        why = rep["findings"][0]["session_state"]
        assert "долгоживущий процесс сессии pid71512 завершился" in why
        assert "окно ожидания" in why and "ждать некого" in why

    def test_render_puts_orphans_in_their_own_section(self, guard, repo):
        """Дерево названо вслух и отдельным разделом — сирота не тонет в общем списке."""
        (repo / "scripts" / "adr085_agent.py").write_text("готовая работа\n", encoding="utf-8")
        (repo / "scripts" / "old_orphan.py").write_text("давняя сирота\n", encoding="utf-8")
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "adr085_agent.py"], 71512),
                      entry("pid31439", [repo / "scripts" / "old_orphan.py"],
                            ts="2026-01-15T00:00:00Z")],
                     ps=fake_ps({}), now=_IN_WINDOW)
        text = guard.render(rep)
        assert "ОСИРОТЕЛО, НО ОКНО НЕ ИСТЕКЛО (1)" in text
        assert "НЕ ДОСТАВЛЕНО (1)" in text                   # просроченная — своим разделом
        assert "scripts/adr085_agent.py" in text and "scripts/old_orphan.py" in text
        assert text.index("ОСИРОТЕЛО") < text.index("НЕ ДОСТАВЛЕНО")   # свежую поднять дешевле

    # ── обратные контроли: окно НЕ снимается ни на чём, кроме измеренной смерти ──

    def test_live_durable_session_inside_window_is_never_a_finding(self, guard, repo):
        """Живая сессия в том же окне — не находка (класс «две сессии на одной карточке»)."""
        (repo / "scripts" / "in_flight.py").write_text("работа идёт\n", encoding="utf-8")
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "in_flight.py"], 71512)],
                     ps=fake_ps({71512: (0, _LSTART_OLD)}), now=_IN_WINDOW)
        assert rep["findings"] == [] and rep["unmeasured"] == []
        assert rep["sessions_active"] == 1
        assert rep["exit_code"] == 0

    def test_bare_pid_identifier_inside_window_still_waits(self, guard, repo):
        """Ключевой нюанс карточки: `pid<N>` — pid ОДНОКРАТНОЙ CLI-команды, он мёртв всегда.

        Если бы «`ps` не нашёл процесс» снимало окно, находкой стала бы работа КАЖДОЙ живой
        сессии, включая текущую, — ровно то, ради чего окно и заводили."""
        (repo / "scripts" / "in_flight.py").write_text("работа идёт\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "in_flight.py"])],
                     ps=fake_ps({}), now=_IN_WINDOW)
        assert rep["findings"] == []
        assert [f["session"] for f in rep["fresh"]] == ["pid31439"]
        assert rep["exit_code"] == 0

    def test_unmeasurable_durable_process_is_never_read_as_death(self, guard, repo):
        """«Не измерено» смертью не объявляется: `ps` не отработал ⇒ находки нет.

        Запись при этом уходит не в окно, а в «НЕ ИЗМЕРЕНО» (код 2) — это давняя fail-CLOSED
        ветка `session_state`, она срабатывает РАНЬШЕ окна и правкой не тронута. Пиннится
        главное: неизмеренная активность не открывает досрочный подъём в находки."""
        (repo / "scripts" / "in_flight.py").write_text("работа идёт\n", encoding="utf-8")
        e = durable_entry("cycle231", [repo / "scripts" / "in_flight.py"], 71512)
        assert guard.durable_process_gone(e, ps=fake_ps({71512: (2, "")})) is False
        rep = report(guard, repo, [e], ps=fake_ps({71512: (2, "")}), now=_IN_WINDOW)
        assert rep["findings"] == []
        assert len(rep["unmeasured"]) == 1
        assert "не отработал" in rep["unmeasured"][0]["reason"]
        assert rep["exit_code"] == 2

    def test_reused_pid_counts_as_gone(self, guard, repo):
        """pid занят ДРУГИМ процессом — тот же измеренный факт «объявленного процесса нет»."""
        (repo / "scripts" / "adr085_agent.py").write_text("готовая работа\n", encoding="utf-8")
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "adr085_agent.py"], 71512)],
                     ps=fake_ps({71512: (0, _LSTART_NEW)}), now=_IN_WINDOW)
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert rep["findings"][0]["within_grace"] is True

    def test_dead_durable_session_with_everything_delivered_is_not_a_finding(self, guard, repo):
        """Смерть сессии сама по себе — не находка: доставленное объявление остаётся тишиной."""
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "kept.py"], 71512)],
                     ps=fake_ps({}), now=_IN_WINDOW)
        assert rep["findings"] == [] and rep["unmeasured"] == []
        assert len(rep["fresh"]) == 1                          # но и в тишину не роняется
        assert "находки нет" in rep["fresh"][0]["reason"]
        assert rep["exit_code"] == 0

    def test_unmeasured_path_of_a_dead_session_fails_closed_inside_window(self, guard, repo):
        """Запись, которую мы взялись мерить, меряется до конца — включая fail-CLOSED."""
        rep = report(guard, repo,
                     [durable_entry("cycle231", [Path("/вне/репозитория/x.py")], 71512)],
                     ps=fake_ps({}), now=_IN_WINDOW)
        assert rep["findings"] == []
        assert len(rep["unmeasured"]) == 1
        assert rep["exit_code"] == 2

    def test_orphan_and_expired_findings_do_not_collapse_into_one(self, guard, repo):
        """Один и тот же файл от сироты-в-окне и от просроченной — разной срочности."""
        (repo / "scripts" / "kept.py").write_text("общая правка\n", encoding="utf-8")
        rep = report(guard, repo,
                     [durable_entry("cycle231", [repo / "scripts" / "kept.py"], 71512),
                      entry("pid31439", [repo / "scripts" / "kept.py"],
                            ts="2026-01-15T00:00:00Z")],
                     ps=fake_ps({}), now=_IN_WINDOW)
        assert sorted(f["within_grace"] for f in rep["findings"]) == [False, True]


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
    @pytest.fixture(autouse=True)
    def _identity_is_not_the_runner(self, monkeypatch):
        """Личность сессии задаётся ЯВНО, иначе исход теста решает pid прогона.

        `main()` берёт `SPA_SESSION_ID` либо, за его отсутствием, `pid<os.getpid()>`, а запись
        своей сессии по построению пропускается. Фикстуры ниже объявлены от `pid4242`/`pid31439`,
        и на Linux-раннере (pid'ы малые и последовательные) прогон получил ровно **4242**: своя
        запись пропущена ⇒ «не измерено» исчезло ⇒ `rc 0` вместо `2`. Замерено, а не выведено:
        `SPA_SESSION_ID=pid4242 pytest -k TestCli` роняет ровно тот же ассерт, что и CI 14.08.

        Сам пропуск своей записи проверяется отдельно и явно
        (`TestLiveSessionsNeverReported::test_self_session_is_never_reported`, личность передаётся
        аргументом) — здесь ничего не ослаблено.
        """
        monkeypatch.setenv("SPA_SESSION_ID", "pid-этой-сессии-нет-ни-в-одной-фикстуре")

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


# ── 9. мёртвая регистрация рабочего дерева ───────────────────────────────────
#
# Положительный контроль замера 06.08 (карточка `inbox-shag-0a-iz-worktree-daet-18-strok-ne-izm`):
# 16 каталогов с уцелевшими файлами и мёртвой git-привязкой давали 18 строк «НЕ ИЗМЕРЕНО» и
# код 2 на ПУСТОМ месте — сверять там нечего, а шаг 0a обязателен каждый цикл, и разбирать
# этот шум сессия обязана руками. Класс — «необратимое „не измерено“ морит очередь»:
# однажды в тех же строках окажется настоящая находка, а читать их уже перестанут.
#
# Состояние воспроизводится точно так же, как оно возникает в жизни: у линкованного worktree
# исчезает файл `.git`, служебная запись в `.git/worktrees/` остаётся ⇒ git продолжает
# перечислять дерево, помечая его `prunable`, каталог с файлами на месте, а любой git-вызов
# внутри падает с «not a git repository».

def _dead_binding_worktree(repo, path):
    """Линкованный worktree, у которого убита git-привязка (каталог и файлы остались)."""
    _git(repo, "worktree", "add", "-q", "--detach", str(path), "base")
    (path / ".git").unlink()                     # ровно то, что делает уборка /tmp
    assert path.is_dir() and (path / "scripts" / "kept.py").exists()
    return path


class TestDeadWorktreeRegistration:
    def test_dead_binding_is_not_unmeasured(self, guard, repo, tmp_path):
        """ГЛАВНОЕ: 18 строк шума и код 2 больше не берутся из ничего.

        На непочиненном коде каталог проходил в сверку по признаку «существует», оба
        `git diff` падали, и каждый падёж становился строкой «НЕ ИЗМЕРЕНО»."""
        _dead_binding_worktree(repo, tmp_path / "spa_wt_dead")
        rep = report(guard, repo, [])
        assert rep["unmeasured"] == [], rep["unmeasured"]
        assert rep["exit_code"] == 0

    def test_dead_binding_is_named_once_per_directory(self, guard, repo, tmp_path):
        """Не молчание: каталог назван — но ОДНОЙ строкой, а не по строке на git-вызов."""
        dead = _dead_binding_worktree(repo, tmp_path / "spa_wt_dead")
        rep = report(guard, repo, [])
        assert [d["path"] for d in rep["dead_worktrees"]] == [str(dead)]
        assert guard.render(rep).count(str(dead)) == 1

    def test_dead_binding_is_not_called_unsynced_with_base(self, guard, repo, tmp_path):
        """Формулировка — часть находки: «с базой НЕ сверено» звучит как несделанная работа
        сторожа, тогда как сверять там нечего (это не чекаут, а остатки файлов)."""
        dead = _dead_binding_worktree(repo, tmp_path / "spa_wt_dead")
        text = guard.render(report(guard, repo, []))
        assert "рабочее дерево с базой НЕ сверено" not in text
        assert "привязки нет" in text and str(dead) in text

    def test_dead_binding_does_not_hide_live_worktree_work(self, guard, repo, tmp_path):
        """Радиус: соседнее ЖИВОЕ дерево по-прежнему сверяется (иначе правка стала бы
        глушилкой для главного сценария шага 0a)."""
        _dead_binding_worktree(repo, tmp_path / "spa_wt_dead")
        live = tmp_path / "spa_wt_live"
        _git(repo, "worktree", "add", "-q", "--detach", str(live), "base")
        (live / "scripts" / "kept.py").write_text("работа только в worktree\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [live / "scripts" / "kept.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/kept.py"]
        assert rep["findings"][0]["state"] == guard.DIFFERS

    def test_cards_in_dead_binding_tree_are_still_found(self, guard, repo, tmp_path):
        """Покрытие сторожа карточек НЕ сужается: карточки ищутся по файловой системе, git
        для этого не нужен — недоставленная карточка в мёртвом каталоге обязана находиться."""
        dead = _dead_binding_worktree(repo, tmp_path / "spa_wt_dead")
        tracker = dead / guard.TRACKER_REL
        tracker.mkdir(parents=True, exist_ok=True)
        (tracker / "inbox-zabytaya.md").write_text("---\nstatus: new\n---\nтело\n",
                                                   encoding="utf-8")
        base_tracker = repo / guard.TRACKER_REL
        base_tracker.mkdir(parents=True, exist_ok=True)
        (base_tracker / "inbox-est-na-baze.md").write_text("---\nstatus: new\n---\nтело\n",
                                                           encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "карточка на базе")
        _git(repo, "branch", "-f", "base", "HEAD")

        rep = report(guard, repo, [])
        assert [c["card"] for c in rep["card_findings"]] == ["inbox-zabytaya"]

    def test_live_tree_with_unreadable_binding_stays_unmeasured(self, guard, repo, tmp_path):
        """Ослабления нет. fail-CLOSED снимается ТОЛЬКО там, где авторитетный источник — сам
        git — объявил запись `prunable`. Если git считает дерево живым, а привязка не
        читается, это не объяснено ничем и остаётся «не измерено» (код 2)."""
        ghost = tmp_path / "spa_wt_ghost"
        ghost.mkdir()
        real = guard._git

        def fake(cwd, *args):
            if args[:2] == ("worktree", "list"):                 # git о prunable МОЛЧИТ
                rc, out, err = real(cwd, *args)
                return rc, out + f"\nworktree {ghost}\ndetached\n", err
            if Path(str(cwd)) == ghost:
                return 128, "", "fatal: not a git repository"
            return real(cwd, *args)

        rep = report_with_git(guard, repo, [], git=fake)
        assert rep["dead_worktrees"] == []
        assert any(str(ghost) in (u.get("path") or "") for u in rep["unmeasured"])
        assert rep["exit_code"] == 2


class TestDeletedWorktreeIsNamedTruthfully:
    def test_deleted_worktree_is_not_called_a_foreign_repository(self, guard, repo, tmp_path):
        """Живая строка каждого цикла 07.08: объявленный путь из УДАЛЁННОГО worktree
        описывался как «путь не принадлежит этому репозиторию» — то есть как ошибка
        объявления (объявили чужой файл), тогда как это потеря СВОЕЙ работы.
        Вердикт не меняется (по-прежнему «не измерено», код 2) — меняется читаемое."""
        rep = report(guard, repo, [entry("pid31439",
                                         [tmp_path / "spa_wt_gone" / "docs" / "STATE.md"])])
        assert rep["exit_code"] == 2
        reason = rep["unmeasured"][0]["reason"]
        assert "не принадлежит этому репозиторию" not in reason
        assert "рабочее дерево удалено" in reason

    def test_path_in_a_genuinely_foreign_repo_keeps_its_own_reason(self, guard, repo, tmp_path):
        """Контроль в обратную сторону: у настоящего чужого репозитория каталоги НА МЕСТЕ,
        и прежняя формулировка обязана сохраниться — иначе новая проглотила бы старый класс."""
        other = tmp_path / "other"
        (other / "scripts").mkdir(parents=True)
        _git(tmp_path, "init", "-q", str(other))
        (other / "scripts" / "f.py").write_text("чужое\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [other / "scripts" / "f.py"])])
        assert rep["exit_code"] == 2
        assert "не принадлежит этому репозиторию" in rep["unmeasured"][0]["reason"]


class TestReapedTreeCarriesItsMeasurement:
    """Квитанция снятого дерева (`data/worktree_reap_log.jsonl`, цикл #230).

    Уборка мёртвых деревьев (`scripts/reap_stale_worktrees.py`) убирает осадок находок, но
    сама превращала бы каждый объявленный путь внутри снятого дерева в НЕОБРАТИМОЕ «измерить
    нечем» (код 2) — тот самый класс, которым уже морили очередь. Квитанция несёт измерение,
    сделанное ДО снятия. Здесь проверяется, что пропуск даётся ровно объяснённым путям и
    никому больше."""

    @staticmethod
    def _ledger(repo, rows):
        (repo / "data").mkdir(exist_ok=True)
        (repo / "data" / "worktree_reap_log.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def test_explained_path_is_measured_not_unmeasured(self, guard, repo, tmp_path):
        wt = tmp_path / "spa_wt_c191"
        self._ledger(repo, [{"ts": "2026-08-14T16:00:00Z", "worktree": str(wt), "base": "base",
                             "archive": "/arch/spa_wt_c191-STAMP",
                             "paths": {"docs/STATE.md": "superseded"}}])
        rep = report(guard, repo, [entry("pid31439", [wt / "docs" / "STATE.md"])])
        assert rep["unmeasured"] == [], rep["unmeasured"]
        assert rep["findings"] == []
        assert len(rep["reaped"]) == 1
        assert "архив" in rep["reaped"][0]["reason"]
        assert rep["exit_code"] == 0

    def test_path_marked_undelivered_at_reap_is_never_silent(self, guard, repo, tmp_path):
        """Правило такие деревья не снимает; если снятие всё же случилось — молчать нельзя."""
        wt = tmp_path / "spa_wt_rnd49"
        self._ledger(repo, [{"ts": "2026-08-14T16:00:00Z", "worktree": str(wt), "base": "base",
                             "archive": "/arch/x",
                             "paths": {"scripts/edge_criterion_consensus.py": "unique"}}])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "edge_criterion_consensus.py"])])
        assert rep["exit_code"] == 2
        assert "'unique'" in rep["unmeasured"][0]["reason"]

    def test_path_absent_from_ledger_and_from_base_is_a_finding(self, guard, repo, tmp_path):
        """Файл, которого нет ни в квитанции, ни на базе, — потерянная работа, а не тишина."""
        wt = tmp_path / "spa_wt_c191"
        self._ledger(repo, [{"ts": "2026-08-14T16:00:00Z", "worktree": str(wt), "base": "base",
                             "archive": "/arch/x", "paths": {"docs/STATE.md": "delivered"}}])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "brand_new.py"])])
        assert rep["exit_code"] == 1
        assert rep["findings"][0]["state"] == guard.ABSENT

    def test_path_absent_from_ledger_but_present_on_base_is_explained(self, guard, repo, tmp_path):
        """В квитанции только расходившиеся пути: объявленный, но не тронутый файл терять нечем."""
        wt = tmp_path / "spa_wt_c191"
        self._ledger(repo, [{"ts": "2026-08-14T16:00:00Z", "worktree": str(wt), "base": "base",
                             "archive": "/arch/x", "paths": {"docs/STATE.md": "delivered"}}])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "kept.py"])])
        assert rep["exit_code"] == 0 and len(rep["reaped"]) == 1

    def test_tree_without_a_receipt_stays_unmeasured(self, guard, repo, tmp_path):
        """Контроль в обратную сторону: пропуск даёт КВИТАНЦИЯ, а не сам факт пропажи дерева."""
        self._ledger(repo, [{"ts": "2026-08-14T16:00:00Z", "worktree": str(tmp_path / "other"),
                             "base": "base", "archive": "/arch/x", "paths": {}}])
        rep = report(guard, repo, [entry("pid31439", [tmp_path / "spa_wt_gone" / "docs" / "STATE.md"])])
        assert rep["exit_code"] == 2
        assert "рабочее дерево удалено" in rep["unmeasured"][0]["reason"]

    def test_broken_ledger_is_named_not_swallowed(self, guard, repo, tmp_path):
        (repo / "data").mkdir(exist_ok=True)
        (repo / "data" / "worktree_reap_log.jsonl").write_text("{битое\n", encoding="utf-8")
        rep = report(guard, repo, [])
        assert rep["exit_code"] == 2
        assert any("снятых деревьев" in u["reason"] for u in rep["unmeasured"])

    def test_no_ledger_at_all_is_normal(self, guard, repo):
        """Уборку могли ни разу не запускать — отсутствие журнала не находка."""
        rep = report(guard, repo, [])
        assert rep["exit_code"] == 0 and rep["reaped"] == []


# ── 12. объявленное ИМЯ, которого не существовало нигде ──────────────────────
#
# Карточка `inbox-shag-0a-vechno-dokladyvaet-o-faile-kotor` (цикл #239, закрыта #243).
# Объявление владения пишется АВАНСОМ, до того как ответ известен, и у исследовательского
# слоя имя результата меняется на ходу: `pid16782` объявила `scripts/edge_risk_shape_budget.py`
# (#55 RSB), доставила `scripts/edge_cash_sleeve_frontier.py` (#55 CSF) и умерла до пуша.
# Находка про объявленное имя честна по контракту сторожа и при этом НЕ снимаема ничем, кроме
# подлога (создать пустышку с нужным именем), — то есть вечна.
#
# Замер до правки (весь журнал, 852 записи, 15.08): 42 находки ABSENT, из них 38 — этот класс,
# настоящей недоставленной работы 2. Девять десятых раздела «НЕ ДОСТАВЛЕНО» учили пролистывать
# его целиком.
#
# Границы, названные в карточке заранее и соблюдённые здесь: горизонта по времени НЕ вводится
# (возраст — не признак ложности, #233), права снять свою находку задним числом у сессии не
# появилось (#226), код возврата не смягчён.

class TestDeclaredNameThatNeverExisted:
    def test_never_created_name_is_not_called_undelivered_work(self, guard, repo):
        """Имени нет ни на базе, ни в её истории, ни в одном дереве ⇒ поднимать нечего."""
        rep = report(guard, repo, [entry("pid16782", [repo / "scripts" / "edge_rsb.py"])])
        assert rep["findings"] == []
        assert [f["path"] for f in rep["nowhere"]] == ["scripts/edge_rsb.py"]
        assert "НИГДЕ" in rep["nowhere"][0]["detail"]

    def test_lost_work_lying_in_a_worktree_is_still_a_finding(self, guard, repo, tmp_path):
        """ОБРАТНЫЙ КОНТРОЛЬ, зелёный на ОБОИХ деревьях НАМЕРЕННО — им и доказывается, что
        настоящая потеря не переехала в «поднимать нечего».

        Точная форма живого случая: `scripts/edge_criterion_consensus.py` лежит в
        `/tmp/spa_wt_rnd49`, на origin его нет. Байты существуют ⇒ поднимать ЕСТЬ что."""
        wt = tmp_path / "spa_wt_rnd49"
        _git(repo, "worktree", "add", "-q", "--detach", str(wt), "base")
        (wt / "scripts" / "edge_criterion_consensus.py").write_text("работа\n", encoding="utf-8")
        rep = report(guard, repo,
                     [entry("pid29046", [repo / "scripts" / "edge_criterion_consensus.py"])])
        assert rep.get("nowhere", []) == []
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert rep["exit_code"] == 1

    def test_finding_names_the_tree_that_holds_the_bytes(self, guard, repo, tmp_path):
        """Побочное усиление той же правки: раз деревья всё равно опрошены, находка называет
        КОНКРЕТНОЕ дерево, где лежит работа, вместо «на базе нет; локально тоже нет»."""
        wt = tmp_path / "spa_wt_rnd49"
        _git(repo, "worktree", "add", "-q", "--detach", str(wt), "base")
        (wt / "scripts" / "edge_criterion_consensus.py").write_text("работа\n", encoding="utf-8")
        rep = report(guard, repo,
                     [entry("pid29046", [repo / "scripts" / "edge_criterion_consensus.py"])])
        assert str(wt) in rep["findings"][0]["detail"]        # дерево НАЗВАНО, а не «где-то»
        assert "поднять" in rep["findings"][0]["detail"]

    def test_path_that_lived_on_base_and_was_deleted_is_not_nowhere(self, guard, repo):
        """Второй контроль: путь БЫЛ на базе и удалён — это не «имени не было»,
        и сворачивать такое в «поднимать нечего» значило бы прятать удаление."""
        (repo / "scripts" / "gone.py").write_text("жил на базе\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add gone.py")
        _git(repo, "branch", "-f", "base", "HEAD")
        _git(repo, "rm", "-q", "scripts/gone.py")
        _git(repo, "commit", "-qm", "rm gone.py")
        _git(repo, "branch", "-f", "base", "HEAD")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "gone.py"])])
        assert rep.get("nowhere", []) == []
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert "истории" in rep["findings"][0]["detail"]
        assert rep["exit_code"] == 1

    def test_unreadable_history_keeps_the_finding(self, guard, repo):
        """fail-CLOSED: не смогли прочитать историю ⇒ вердикт «нигде» НЕ выносится,
        запись остаётся находкой, а причина дописывается вслух."""
        real = guard._git

        def spy(cwd, *args):
            if args[:1] == ("log",):
                return 1, "", "boom"
            return real(cwd, *args)

        rep = report_with_git(guard, repo,
                              [entry("pid31439", [repo / "scripts" / "never_written.py"])], spy)
        assert rep.get("nowhere", []) == []
        assert [f["state"] for f in rep["findings"]] == [guard.ABSENT]
        assert "НЕ ИЗМЕРЕНО" in rep["findings"][0]["detail"]
        assert rep["exit_code"] == 1

    def test_nowhere_alone_never_yields_a_green_exit_code(self, guard, repo):
        """Правка меняет ВЕРДИКТ и место в отчёте, а не видимость: пути к «✅ всё доставлено»
        через этот класс нет (инв. #2)."""
        rep = report(guard, repo, [entry("pid16782", [repo / "scripts" / "edge_rsb.py"])])
        assert rep["exit_code"] == 1
        text = guard.render(rep)
        assert "НЕ СУЩЕСТВУЕТ НИГДЕ" in text
        assert "ПОДНИМАТЬ НЕЧЕГО" in text
        assert "✅ измерено полностью, всё доставлено" not in text

    def test_nowhere_is_rendered_apart_from_undelivered(self, guard, repo, tmp_path):
        """Обе строки в одном отчёте — и в РАЗНЫХ разделах: смысл правки в том, что глаз
        перестаёт учиться пролистывать «НЕ ДОСТАВЛЕНО»."""
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "--detach", str(wt), "base")
        (wt / "scripts" / "real_loss.py").write_text("работа\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid1", [repo / "scripts" / "real_loss.py"]),
                                   entry("pid2", [repo / "scripts" / "phantom.py"])])
        text = guard.render(rep)
        assert text.index("НЕ ДОСТАВЛЕНО") < text.index("НЕ СУЩЕСТВУЕТ НИГДЕ")
        loss = text.index("scripts/real_loss.py")
        phantom = text.index("scripts/phantom.py")
        assert loss < text.index("НЕ СУЩЕСТВУЕТ НИГДЕ") < phantom

    def test_closing_announcement_names_what_was_delivered_instead(self, guard, repo):
        """Гипотеза карточки, проверенная кодом: закрывающее объявление (`card_state: done`)
        перечисляет фактически доставленное — по нему видно, что имя СМЕНИЛОСЬ, а не пропало.
        Утверждения «это переименование» сторож не делает: доказать связь имён нечем."""
        entries = [
            entry("pid53284", [repo / "spa_core" / "tests" / "test_check_card_claim.py"]),
            dict(entry("pid53284", [repo / "scripts" / "kept.py"]), card_state="done"),
        ]
        rep = report(guard, repo, entries)
        assert [f["path"] for f in rep["nowhere"]] == ["spa_core/tests/test_check_card_claim.py"]
        assert rep["nowhere"][0]["delivered_instead"] == ["scripts/kept.py"]
        assert "ДОСТАВИЛА" in guard.render(rep)

    def test_delivered_instead_is_empty_when_the_session_delivered_nothing(self, guard, repo):
        """Контроль в обратную сторону: подсказка не выдумывается там, где доставки не было."""
        rep = report(guard, repo, [entry("pid16782", [repo / "scripts" / "edge_rsb.py"])])
        assert rep["nowhere"][0]["delivered_instead"] == []
        assert "ДОСТАВИЛА" not in guard.render(rep)

    def test_glued_declaration_is_named_as_such(self, guard, repo):
        """5 из 38 живых случаев — объявление слепило несколько путей в ОДНУ строку; такого
        файла не существует по построению, и это надо сказать, а не отправлять искать."""
        rep = report(guard, repo, [entry("pid63921", ["scripts/a.py docs/B.md"])])
        assert len(rep["nowhere"]) == 1
        assert "слепило несколько путей" in rep["nowhere"][0]["detail"]

    def test_same_phantom_name_declared_twice_is_one_line(self, guard, repo):
        rep = report(guard, repo, [entry("pid1", [repo / "scripts" / "edge_rsb.py"]),
                                   entry("pid2", [repo / "scripts" / "edge_rsb.py"])])
        assert len(rep["nowhere"]) == 1
        assert rep["nowhere"][0]["also_declared_by"] == ["pid2"]

    def test_orphan_inside_grace_with_only_a_phantom_name_is_not_called_delivered(self, guard, repo):
        """Сирота в окне, у которой ВСЁ объявленное — фантом: в «свежие, находки нет» она
        уйти не должна, иначе класс вернулся бы через другую дверь."""
        e = durable_entry("cycle-243", [repo / "scripts" / "edge_rsb.py"], pid=4242,
                          ts="2026-01-20T11:00:00Z")
        rep = report(guard, repo, [e], ps=fake_ps({}))
        assert len(rep["nowhere"]) == 1 and rep["nowhere"][0]["within_grace"] is True
        assert not any("находки нет" in f["reason"] for f in rep["fresh"])


# ── 13. чьё это расхождение: своё дерево сессии против чужих ─────────────────
#
# Класс, измеренный циклом #252 на живом журнале (872 записи, 46 рабочих деревьев): из 49
# находок 12 были ложным обвинением — сессия объявила путь из своего дерева, доставила его
# (коммит на origin проверен руками), её дерево совпадает с origin побайтно, а находка жила,
# потому что ТОТ ЖЕ путь расходится в чужих деревьях. `docs/STATE.md` расходится в 25
# деревьях, `docs/journal/<неделя>.md` — в 24, `_BOARD.md` — в 24: у трёх файлов, которые
# правит каждый цикл, источник расхождения вечен (прод-дерево не снимается по щиту #234).
#
# Каждый тест ниже — положительный контроль: воспроизводит форму реальной находки 16.08.

class TestWhoseDivergenceIsIt:
    def _two_trees(self, repo, tmp_path):
        """Своё дерево сессии (доставила) и чужое (держит недоставленное)."""
        mine = tmp_path / "spa_c250"
        theirs = tmp_path / "spa_c249"
        _git(repo, "worktree", "add", "-q", "--detach", str(mine), "base")
        _git(repo, "worktree", "add", "-q", "--detach", str(theirs), "base")
        return mine, theirs

    def test_delivered_session_is_not_accused_for_a_foreign_tree(self, guard, repo, tmp_path):
        """Форма находки cycle-250 / `docs/DYNAMIC_LEVERAGE_GUARDIAN.md` (коммит d0bf9d843):
        своё дерево чистое, расходится чужое ⇒ обвинения этой сессии быть не должно."""
        mine, theirs = self._two_trees(repo, tmp_path)
        (theirs / "scripts" / "kept.py").write_text("чужая правка\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", [mine / "scripts" / "kept.py"])])
        # Контроль на неисправленном origin обязан краснеть на ПОВЕДЕНИИ, а не на отсутствии
        # ключа: там эта же запись печатается в разделе «подними руками».
        assert "НЕ ДОСТАВЛЕНО" not in guard.render(rep)
        assert [f.get("foreign_only") for f in rep["findings"]] == [True]
        assert str(theirs) in rep["findings"][0]["detail"]
        assert str(mine) in rep["findings"][0]["detail"]
        assert "НЕ ИЗМЕРЕНО" in rep["findings"][0]["detail"]

    def test_the_finding_itself_never_disappears(self, guard, repo, tmp_path):
        """ПОКРЫТИЕ НЕ СУЖЕНО (прецедент #243: меняется вердикт и раздел, не видимость).
        Байты, которых нет в истории origin, остаются названными, а код возврата — прежним."""
        mine, theirs = self._two_trees(repo, tmp_path)
        (theirs / "scripts" / "kept.py").write_text("чужая правка\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", [mine / "scripts" / "kept.py"])])
        assert len(rep["findings"]) == 1 and rep["exit_code"] == 1
        text = guard.render(rep)
        assert "ЧУЖИХ ДЕРЕВЬЯХ" in text
        assert "✅ измерено полностью, всё доставлено" not in text
        assert "НЕ ДОСТАВЛЕНО" not in text          # из раздела «подними руками» — выведено

    def test_own_tree_divergence_is_still_a_plain_finding(self, guard, repo, tmp_path):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: своё дерево расходится ⇒ прежняя находка, прежний раздел.
        Настоящая потеря (11 из 49 в замере #252) правкой не задета."""
        mine, _theirs = self._two_trees(repo, tmp_path)
        (mine / "scripts" / "kept.py").write_text("моя недоставленная правка\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45244", [mine / "scripts" / "kept.py"])])
        assert [f.get("foreign_only") for f in rep["findings"]] in ([False], [None])
        assert rep["exit_code"] == 1
        text = guard.render(rep)
        assert "НЕ ДОСТАВЛЕНО" in text and "ЧУЖИХ ДЕРЕВЬЯХ" not in text

    def test_only_the_session_that_kept_the_work_is_accused(self, guard, repo, tmp_path):
        """Два объявителя одного пути — ровно живой случай `docs/STATE.md`: одна доставила,
        вторая нет. Находка обязана остаться ОДНА и принадлежать второй."""
        mine, theirs = self._two_trees(repo, tmp_path)
        (theirs / "scripts" / "kept.py").write_text("недоставленное\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", [mine / "scripts" / "kept.py"]),
                                   entry("pid45249", [theirs / "scripts" / "kept.py"])])
        assert len(rep["findings"]) == 1
        assert rep["findings"][0]["session"] == "pid45249"
        assert rep["findings"][0].get("foreign_only") is not True

    def test_shadow_line_is_dropped_only_when_a_real_finding_exists(self, guard, repo, tmp_path):
        """Обратная сторона предыдущего: тень снимается ТОЛЬКО при живой находке по тому же
        пути. Мутация «снимать всегда» здесь и краснеет."""
        mine, theirs = self._two_trees(repo, tmp_path)
        (theirs / "scripts" / "kept.py").write_text("ничьё\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", [mine / "scripts" / "kept.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/kept.py"]
        assert rep["exit_code"] == 1

    def test_relative_declaration_keeps_the_strict_verdict(self, guard, repo, tmp_path):
        """fail-CLOSED: путь объявлен относительным ⇒ своего дерева в записи нет ⇒ судить по
        нему нечем ⇒ прежняя, более строгая находка. «Не измерено» не даёт послаблений."""
        _mine, theirs = self._two_trees(repo, tmp_path)
        (theirs / "scripts" / "kept.py").write_text("чужая правка\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", ["scripts/kept.py"])])
        assert [f.get("foreign_only") for f in rep["findings"]] in ([False], [None])
        assert "своё дерево сессии не определено" in rep["findings"][0]["detail"]
        assert "относительным" in rep["findings"][0]["detail"]
        assert rep["exit_code"] == 1

    def test_main_tree_declaration_is_judged_by_the_main_tree(self, guard, repo, tmp_path):
        """Объявление из ГЛАВНОГО дерева — тоже названное дерево, а не «неизвестно»."""
        _mine, theirs = self._two_trees(repo, tmp_path)
        (theirs / "scripts" / "kept.py").write_text("чужая правка\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", [repo / "scripts" / "kept.py"])])
        assert "ЧУЖИХ ДЕРЕВЬЯХ" in guard.render(rep)
        assert [f.get("foreign_only") for f in rep["findings"]] == [True]

    def test_stale_copy_everywhere_is_still_not_a_finding(self, guard, repo, tmp_path):
        """Обратный контроль к прежнему поведению (#230): содержимое ВСЕХ деревьев уже в
        истории origin ⇒ находки нет вовсе, и новый раздел её не воскрешает."""
        (repo / "scripts" / "kept.py").write_text("следующая версия\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base ушла вперёд")
        _git(repo, "branch", "-f", "base", "HEAD")
        mine, _theirs = self._two_trees(repo, tmp_path)     # деревья уже на НОВОЙ базе
        (mine / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid45250", [mine / "scripts" / "kept.py"])])
        assert rep["findings"] == []
        assert rep["stale_copies"] and rep["exit_code"] == 0

    def test_declaring_tree_of_a_deleted_worktree_is_not_guessed(self, guard, repo, tmp_path):
        """Дерево сессии УДАЛЕНО ⇒ оно не выдумывается и НЕ подменяется соседним деревом, где
        лежит тот же путь: подстановка и была бы той самой чужой атрибуцией. Причина названа
        своим именем (различие «удалено» / «чужой репозиторий» — как в `resolve_rel`)."""
        mine, theirs = self._two_trees(repo, tmp_path)
        declared = mine / "scripts" / "kept.py"
        shutil.rmtree(mine)
        tree, why = guard.declaring_tree(str(declared), repo)
        assert tree is None
        assert not guard._same_tree(tree or "/", theirs)
        assert "больше нет" in why

    def test_declaration_through_a_symlink_still_names_the_tree(self, guard, repo, tmp_path):
        """`/tmp` на macOS — симлинк на `/private/tmp`, и объявления пишут ОБЕ формы: дерево
        обязано опознаваться через любую.

        ГРАНИЦА НАЗВАНА ЧЕСТНО: мутация «сравнивать деревья сырой строкой, без `realpath`»
        этот тест НЕ красит — `git rev-parse --show-toplevel` отдаёт канонический путь сам, а
        `list_checkouts` вдобавок вносит корень в той форме, в какой его передал вызывающий,
        так что обе формы обычно присутствуют разом. `_real` оставлен как страховка от смены
        этого поведения, и он НЕ доказан мутацией — это измерено, а не предположено."""
        mine, _theirs = self._two_trees(repo, tmp_path)
        link = tmp_path / "link_to_mine"
        link.symlink_to(mine)
        tree, why = guard.declaring_tree(str(link / "scripts" / "kept.py"), repo)
        assert why is None and guard._same_tree(tree, mine)

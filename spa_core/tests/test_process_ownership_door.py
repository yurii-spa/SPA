"""Сторож ДВЕРИ к принадлежности процесса (класс «вердикт решает форма вывода `ps`»).

Авария, воспроизведённая здесь, ИЗМЕРЕНА на настоящем Linux, а не выведена из чтения
флагов. Прогон `SPA CI` 36222500219 (джоба 108350299527, `ubuntu-latest`, 26.09) —
первый с 26.08, доведённый до сводки, — дал девятнадцать падений в двух файлах, и все
девятнадцать несут одну строку:

    ps вернул 1: error: unsupported SysV option

`ps -A -Ewww …` принимает BSD `ps` (macOS) и отвергает ЦЕЛИКОМ procps-ng (Linux).
Снимок не снимался вовсе ⇒ принадлежность на Linux была `OWNERSHIP_UNKNOWN` ВСЕГДА, то
есть предохранитель `scripts/shadow/safe_terminate.py` (ADR-452) там ничего не завершал и
при этом выглядел исправным. Третий исход при этом был ЧЕСТЕН (инв. #17 не нарушался) —
не хватало не честности, а ответа на вопрос «мой ли это процесс».

Это ЧЕТВЁРТЫЙ член семейства из `.claude/rules/deployment.md`: литеральная дата взрывается
от календаря, литеральный pid — от того, что ОС дошла до номера по кругу, git-окружение —
от того, на каком хосте прогон, а форма вывода хозяйской утилиты — от того, чей `ps`
установлен. Во всех четырёх код не меняется ни на байт.

Каждый тест ниже — либо воспроизведение настоящего отказа, либо контроль ОДНОГО звена в
обратную сторону, и звено названо в имени.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

import claude_run_with_timeout as CRT       # noqa: E402

#: Дословный отказ procps-ng, скопированный из лога раннера (не пересказ).
PROCPS_REFUSAL = (
    "ps вернул 1: error: unsupported SysV option\n\nUsage:\n ps [options]\n\n"
    " Try 'ps --help <simple|list|output|threads|misc|all>'"
)

#: Таблица процессов в форме, которую отдают ОБЕ реализации `ps`: pid ppid state etime cmd.
#: Личность здесь не литеральная: номер берётся у живого процесса самого теста, поэтому
#: сцена не зависит от того, до какого номера ОС дошла по кругу (урок ADR-453).
def _table(pid: int, cmd: str = "python3 -c pass") -> str:
    return f"{pid} 1 S 00:05 {cmd}\n{pid + 1} {pid} S 00:04 /bin/sh -c true\n"


class _DoorScene(unittest.TestCase):
    """Сцена, у которой ОБЕ двери к ОС закрыты для пути, который идёт тест.

    Половина инъекции — та же бомба (урок ADR-453): если оставить `_read_environ`
    настоящим, тест на Маке судил бы о `/proc`, которого здесь нет, и «не прочитано»
    стало бы неотличимо от «метки нет».
    """

    def setUp(self):
        self.pid = os.getpid()
        self._ps = CRT._ps
        self._env = CRT._read_environ
        self.addCleanup(self._restore)
        CRT.reset_ps_door_cache()
        self.addCleanup(CRT.reset_ps_door_cache)
        self.calls = []

    def _restore(self):
        CRT._ps = self._ps
        CRT._read_environ = self._env

    def wire(self, *, env_option: str | None, table: str | None,
             environ=None):
        """`env_option`/`table`: None — дверь отвечает, строка — дверь ОТКАЗЫВАЕТ с ней."""
        def fake_ps(args):
            self.calls.append(list(args))
            if args == CRT.PS_ARGS_WITH_ENV:
                if env_option is not None:
                    raise CRT.PsUnavailable(env_option)
                return _table(self.pid, "python3 -c pass SPA_RUN_ID=run-A PATH=/usr/bin")
            if args == CRT.PS_ARGS_TABLE_ONLY:
                if table is not None:
                    raise CRT.PsUnavailable(table)
                return _table(self.pid)
            raise AssertionError(f"неизвестная форма вызова ps: {args!r}")

        CRT._ps = fake_ps
        CRT._read_environ = environ if environ is not None else (lambda pid: None)


class TheRunnerFailureIsReproduced(_DoorScene):

    def test_the_env_option_form_is_what_procps_refuses(self):
        """Звено: сама форма `-E`. Без второй двери отказывал ВЕСЬ снимок."""
        self.wire(env_option=PROCPS_REFUSAL, table="дверь не предлагалась")
        with self.assertRaises(CRT.PsUnavailable) as ctx:
            CRT._ps(CRT.PS_ARGS_WITH_ENV)
        self.assertIn("unsupported SysV option", str(ctx.exception))

    def test_ownership_resolves_through_the_second_door(self):
        """Воспроизведение аварии + её починка: снимок снят, метка НАЙДЕНА."""
        self.wire(env_option=PROCPS_REFUSAL, table=None,
                  environ=lambda pid: ("SPA_RUN_ID=run-A PATH=/usr/bin"
                                       if pid == self.pid else None))
        snap = CRT.Snapshot.take()
        self.assertEqual(snap.door, CRT.DOOR_PS_PLUS_PROC)
        self.assertIn(self.pid, snap.rows)
        self.assertEqual(CRT._inst_run_id(snap, self.pid, "run-A"), {self.pid})

    def test_a_foreign_run_id_is_not_ours_through_the_same_door(self):
        """Обратная сторона: вторая дверь не делает чужой процесс нашим."""
        self.wire(env_option=PROCPS_REFUSAL, table=None,
                  environ=lambda pid: "SPA_RUN_ID=чужой-прогон PATH=/usr/bin")
        snap = CRT.Snapshot.take()
        self.assertEqual(CRT._inst_run_id(snap, self.pid, "run-A"), set())


class NoSilentFallback(_DoorScene):

    def test_both_doors_refused_is_the_third_outcome(self):
        """Обе двери отказали ⇒ `PsUnavailable`, и ОБА отказа названы. Не пустая таблица."""
        self.wire(env_option=PROCPS_REFUSAL, table="ps вернул 127: ps: command not found")
        with self.assertRaises(CRT.PsUnavailable) as ctx:
            CRT.Snapshot.take()
        text = str(ctx.exception)
        self.assertIn("unsupported SysV option", text)
        self.assertIn("command not found", text)

    def test_an_empty_table_is_still_a_refusal(self):
        """Пустой вывод — не «процессов нет», а «не измерено»."""
        CRT._ps = lambda args: ""
        CRT._read_environ = lambda pid: None
        with self.assertRaises(CRT.PsUnavailable):
            CRT.Snapshot.take()

    def test_the_first_door_is_preferred_when_it_answers(self):
        """Контроль в обратную сторону: вторая дверь НЕ подменяет исправную первую."""
        self.wire(env_option=None, table=None)
        snap = CRT.Snapshot.take()
        self.assertEqual(snap.door, CRT.DOOR_PS_WITH_ENV)
        self.assertEqual(self.calls, [CRT.PS_ARGS_WITH_ENV])


class AbsentEnvironmentIsNotAnEmptyEnvironment(_DoorScene):

    def test_unreadable_environ_counts_as_blind_and_adds_no_stamp(self):
        self.wire(env_option=PROCPS_REFUSAL, table=None, environ=lambda pid: None)
        snap = CRT.Snapshot.take()
        self.assertEqual(snap.env_readable, 0)
        self.assertEqual(snap.env_blind, len(snap.rows))
        self.assertEqual(CRT._inst_run_id(snap, self.pid, "run-A"), set())

    def test_an_empty_environment_is_an_observation(self):
        """`""` — наблюдение (окружение пусто), `None` — его отсутствие. Разные исходы."""
        self.wire(env_option=PROCPS_REFUSAL, table=None, environ=lambda pid: "")
        snap = CRT.Snapshot.take()
        self.assertEqual(snap.env_blind, 0)
        self.assertEqual(snap.env_readable, len(snap.rows))

    def test_read_environ_reports_an_unreadable_path_as_None(self):
        with TemporaryDirectory() as td:
            CRT.PROC_ENVIRON = str(Path(td) / "{pid}" / "environ")
            self.addCleanup(setattr, CRT, "PROC_ENVIRON", "/proc/{pid}/environ")
            self.assertIsNone(self._env(4242))

    def test_read_environ_splits_NUL_separated_pairs(self):
        with TemporaryDirectory() as td:
            home = Path(td) / "4242"
            home.mkdir()
            (home / "environ").write_bytes(b"SPA_RUN_ID=run-A\x00PATH=/usr/bin\x00")
            CRT.PROC_ENVIRON = str(Path(td) / "{pid}" / "environ")
            self.addCleanup(setattr, CRT, "PROC_ENVIRON", "/proc/{pid}/environ")
            self.assertEqual(self._env(4242), "SPA_RUN_ID=run-A PATH=/usr/bin")


class TheRefusalIsCachedButSuccessIsNot(_DoorScene):

    def test_a_measured_refusal_is_not_paid_for_twice(self):
        """Бюджет вызовов: grace 120 с при такте 0.5 дал бы 240 заведомо провальных."""
        self.wire(env_option=PROCPS_REFUSAL, table=None, environ=lambda pid: "")
        CRT.Snapshot.take()
        CRT.Snapshot.take()
        with_env = [c for c in self.calls if c == CRT.PS_ARGS_WITH_ENV]
        self.assertEqual(len(with_env), 1, self.calls)

    def test_a_cached_refusal_does_not_make_a_later_failure_look_like_success(self):
        self.wire(env_option=PROCPS_REFUSAL, table=None, environ=lambda pid: "")
        CRT.Snapshot.take()
        self.wire(env_option=PROCPS_REFUSAL, table="ps вернул 1: и таблицы больше нет",
                  environ=lambda pid: "")
        with self.assertRaises(CRT.PsUnavailable):
            CRT.Snapshot.take()

    def test_a_transient_double_failure_does_NOT_poison_the_cache(self):
        """Положительный контроль настоящей поломки, которую эта приёмка и нашла.

        Первая редакция запоминала ЛЮБОЙ отказ первой двери. Соседний файл
        (`test_claude_run_timeout_ownership.py:306`) подменяет `ps` так, что он отказывает
        на ЛЮБОЙ форме, — и этого хватало, чтобы на macOS прибор `run_id` ослеп до конца
        прогона: `/proc` здесь нет, окружение становилось `env_blind`, отделившийся
        потомок перестал находиться, и «124 владение закрыто» печаталось при ЖИВОМ
        выжившем. Измерено дифференциально: 20 passed на чистом дереве против 2 failed.

        Отказ опции — утверждение о ПЛАТФОРМЕ, и доказывается он только тем, что тот же
        `ps` ответил на другую форму. «Сейчас не ответил» таким доказательством не является.
        """
        self.wire(env_option="ps вернул 1: подменённый ps",
                  table="ps вернул 1: подменённый ps")
        with self.assertRaises(CRT.PsUnavailable):
            CRT.Snapshot.take()
        self.wire(env_option=None, table=None)
        self.assertEqual(CRT.Snapshot.take().door, CRT.DOOR_PS_WITH_ENV)

    def test_reset_makes_the_probe_measurable_again(self):
        self.wire(env_option=PROCPS_REFUSAL, table=None, environ=lambda pid: "")
        CRT.Snapshot.take()
        CRT.reset_ps_door_cache()
        self.wire(env_option=None, table=None)
        self.assertEqual(CRT.Snapshot.take().door, CRT.DOOR_PS_WITH_ENV)


class TheFormsAreDeclaredNotScattered(unittest.TestCase):
    """Форма вызова объявлена ОДНИМ местом: иначе следующая правка вернёт `-E` молча."""

    def test_the_portable_form_carries_no_sysv_env_option(self):
        self.assertNotIn("-Ewww", CRT.PS_ARGS_TABLE_ONLY)
        self.assertFalse([a for a in CRT.PS_ARGS_TABLE_ONLY if a.startswith("-E")])

    def test_both_forms_ask_for_the_same_five_columns(self):
        fmt = "pid=,ppid=,state=,etime=,command="
        self.assertIn(fmt, CRT.PS_ARGS_WITH_ENV)
        self.assertIn(fmt, CRT.PS_ARGS_TABLE_ONLY)

    def test_the_module_calls_ps_only_through_the_declared_forms(self):
        """Никакой третьей формы в теле модуля: вердикт решает объявленная дверь."""
        src = (ROOT / 'scripts' / 'claude_run_with_timeout.py').read_text(encoding='utf-8')
        self.assertNotIn('_ps(["-A"', src)
        self.assertNotIn("_ps(['-A'", src)


class TheLiveMachineResolvesOwnership(unittest.TestCase):
    """Замер БЕЗ инъекции: на ЭТОЙ машине снимок снимается и дверь названа.

    Это и есть контроль, который краснеет, когда принадлежность перестаёт разрешаться:
    на Linux до починки он падал бы с `unsupported SysV option`, на macOS — проходил.
    Обе платформы обязаны отвечать ОДНИМ вердиктом, и назвать, ЧЕМ измерено.
    """

    def test_the_snapshot_is_taken_and_names_its_door(self):
        CRT.reset_ps_door_cache()
        snap = CRT.Snapshot.take()
        self.assertIn(snap.door, (CRT.DOOR_PS_WITH_ENV, CRT.DOOR_PS_PLUS_PROC))
        self.assertGreater(len(snap.rows), 1)
        self.assertIn(os.getpid(), snap.rows)

    def test_our_own_stamp_is_found_in_our_own_environment(self):
        """Прибор `run_id` на живой ОС: метка ставится в окружение и обязана найтись."""
        CRT.reset_ps_door_cache()
        os.environ[CRT.RUN_ID_VAR] = marker = f"door-probe-{os.getpid()}"
        self.addCleanup(os.environ.pop, CRT.RUN_ID_VAR, None)
        import subprocess
        child = subprocess.Popen([sys.executable, '-c',
                                  'import sys,time;sys.stderr.write("up\\n");'
                                  'sys.stderr.flush();time.sleep(30)'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 start_new_session=True)
        self.addCleanup(lambda: (child.kill(), child.wait()))
        child.stderr.readline()
        snap = CRT.Snapshot.take()
        found = CRT._inst_run_id(snap, child.pid, marker)
        self.assertIn(child.pid, found,
                      f"метка {marker} не найдена дверью {snap.door}; "
                      f"окружение прочитано у {snap.env_readable} из {len(snap.rows)}")


if __name__ == '__main__':
    unittest.main()

"""Владение потомками у прибора срока (`scripts/claude_run_with_timeout.py`).

СЦЕНА ВОСПРОИЗВОДИТ ИЗМЕРЕННУЮ АВАРИЮ, А НЕ УДОБНУЮ. Замер 18.09 на машине владельца:
Claude Code запускает оболочку каждого Bash-инструмента лидером СВОЕЙ НОВОЙ сессии, и два
полных прогона pytest жили с `ppid=1` и собственными сессиями (`sid=46977`, `sid=99172`),
вожаки которых мертвы. Поэтому заглушка-потомок здесь ОТДЕЛЯЕТСЯ (`setsid` + смерть
промежуточного звена ⇒ `ppid=1`): дизайн «убить группу/сессию запуска» на такой сцене
краснеет, а на неотделившемся потомке прошёл бы — то есть сцена РАЗЛИЧАЕТ два дизайна.

ПОЧЕМУ ПОСТОРОННИЕ ЗАПУСКАЮТСЯ В СВОЕЙ СЕССИИ И МОЛОДЫМИ. У прибора есть три защиты от
выстрела в чужого: «не своя сессия», «не старше запуска» и «принадлежность доказана».
Посторонний, оставленный в сессии pytest, уцелел бы от ПЕРВОЙ защиты, и тест доказывал бы
не то, что проверяет: контроль стал бы верным по построению. Поэтому оба посторонних —
`start_new_session=True` и рождаются непосредственно перед запуском.

ТЕСТЫ НЕ КАСАЮТСЯ НАСТОЯЩИХ АГЕНТОВ SPA: ни `claude`, ни `launchctl`, ни живого `data/`;
всё население сцены — питоньи заглушки в своём временном каталоге, и убираются только они.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER_PATH = os.path.join(ROOT, "scripts", "claude_run_with_timeout.py")
PY = sys.executable


def _load_runner():
    """`scripts/` — не пакет, поэтому прибор грузится по явному пути (как делают соседи)."""
    spec = importlib.util.spec_from_file_location("_claude_run_with_timeout", RUNNER_PATH)
    assert spec and spec.loader, RUNNER_PATH
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


# ── заглушки ─────────────────────────────────────────────────────────────────
# Питоньи намеренно: замер 18.09 — `ps -E` отдаёт окружение python и НЕ отдаёт окружение
# платформенных бинарей (`/bin/bash`, `/bin/sleep`). Заглушка на bash сделала бы прибор
# `run_id` слепым, и тест мерил бы слепоту вместо владения.

CHILD_STUB = textwrap.dedent('''
    import os, sys, time
    os.setsid()                      # своя сессия и своя группа — как у живых сирот
    open(sys.argv[1], "w").write(str(os.getpid()))
    while True:
        time.sleep(0.2)
''')

MID_STUB = textwrap.dedent('''
    import subprocess, sys, os
    # Промежуточное звено рождает потомка и СРАЗУ умирает ⇒ потомок переподчиняется init.
    subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]],
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os._exit(0)
''')

PARENT_STUB = textwrap.dedent('''
    import subprocess, sys, time, os
    mid = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]],
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mid.wait()
    open(sys.argv[4], "w").write(str(os.getpid()))
    while True:
        time.sleep(0.2)
''')

RC_STUB = textwrap.dedent('''
    import sys
    sys.exit(int(sys.argv[1]))
''')

SPAWN_AND_EXIT_STUB = textwrap.dedent('''
    import subprocess, sys
    mid = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]],
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mid.wait()
    sys.exit(0)
''')

BYSTANDER_STUB = textwrap.dedent('''
    import os, sys, time
    open(sys.argv[1], "w").write(str(os.getpid()))
    while True:
        time.sleep(0.2)
''')


CHILD_STUB_IGNORING_SIGTERM = textwrap.dedent('''
    import os, signal, sys, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)   # вежливый сигнал не действует
    os.setsid()
    open(sys.argv[1], "w").write(str(os.getpid()))
    while True:
        time.sleep(0.2)
''')

PARENT_STUB_IGNORING_SIGTERM = textwrap.dedent('''
    import os, signal, subprocess, sys, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    mid = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]],
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mid.wait()
    open(sys.argv[4], "w").write(str(os.getpid()))
    while True:
        time.sleep(0.2)
''')


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_file(path, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return open(path).read().strip()
        time.sleep(0.05)
    raise AssertionError(f"заглушка не отметилась в {path} за {timeout}s — "
                         f"предпосылка теста НЕ обеспечена (падаю громко, а не сужу)")


class Stage(unittest.TestCase):
    """Общая сцена: файлы заглушек, свой лог, учёт ВСЕХ порождённых pid для уборки."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="canary_timeout_")
        self.log = os.path.join(self.tmp, "run.log")
        self.mine = []           # pid, которые завела ЭТА сцена — убираем только их
        self.f = {}
        for name, src in (("child", CHILD_STUB), ("mid", MID_STUB), ("parent", PARENT_STUB),
                          ("rc", RC_STUB), ("spawn_exit", SPAWN_AND_EXIT_STUB),
                          ("bystander", BYSTANDER_STUB),
                          ("child_ign", CHILD_STUB_IGNORING_SIGTERM),
                          ("parent_ign", PARENT_STUB_IGNORING_SIGTERM)):
            p = os.path.join(self.tmp, f"{name}_stub.py")
            open(p, "w").write(src)
            self.f[name] = p

    def tearDown(self):
        """Уборка по ДВУМ источникам, и второй существует по измеренной причине.

        `self.mine` пополняется ПОСЛЕ возврата из `runner.run`, поэтому прогон, упавший
        внутри прибора, не оставлял сцене ничего для уборки: замер на pre-delivery gate —
        один такой прогон (ValueError в переписи) оставил 12 живых заглушек, все с
        метками одного и того же запуска. Сцена, которая плодит сирот при собственной
        поломке, — ровно тот дефект, против которого написан весь этот файл.

        Второй источник — pid-файлы в СВОЁМ временном каталоге: туда пишут только наши
        заглушки, поэтому чужого процесса здесь не может быть по построению.
        """
        doomed = list(self.mine)
        for name in os.listdir(self.tmp):
            if not (name.endswith(".pid") or name.endswith(".ready")):
                continue
            try:
                doomed.append(int(open(os.path.join(self.tmp, name)).read().strip()))
            except (OSError, ValueError):
                continue
        for pid in dict.fromkeys(doomed):
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if _alive(pid):
                    try:
                        os.kill(pid, sig)
                    except OSError:
                        pass
                    time.sleep(0.15)

    # ── помощники сцены ──────────────────────────────────────────────────────

    def parent_cmd(self):
        """Команда, которая породит ОТДЕЛИВШЕГОСЯ потомка и потом будет висеть."""
        self.child_pidfile = os.path.join(self.tmp, "child.pid")
        ready = os.path.join(self.tmp, "parent.ready")
        self.parent_ready = ready
        return [PY, self.f["parent"], self.f["mid"], self.f["child"],
                self.child_pidfile, ready]

    def start_bystander(self, run_id_value=None):
        """Посторонний: СВОЯ сессия и молодой возраст — чтобы его спасала только улика."""
        pidfile = os.path.join(self.tmp, f"by_{run_id_value or 'none'}_{time.time()}.pid")
        env = dict(os.environ)
        env.pop(runner.RUN_ID_VAR, None)
        if run_id_value is not None:
            env[runner.RUN_ID_VAR] = run_id_value
        proc = subprocess.Popen([PY, self.f["bystander"], pidfile], env=env,
                                start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.mine.append(proc.pid)
        _wait_file(pidfile)
        return proc.pid

    def read_log(self):
        return open(self.log, encoding="utf-8").read() if os.path.exists(self.log) else ""


class OwnershipAtTimeout(Stage):

    def test_1_stub_child_is_detached_exactly_like_the_measured_orphans(self):
        """Критерий 1: потомок сменил группу И сессию и получил ppid=1."""
        cmd = self.parent_cmd()
        proc = subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.mine.append(proc.pid)
        child = int(_wait_file(self.child_pidfile))
        self.mine.append(child)
        time.sleep(0.6)   # дать промежуточному звену умереть и ядру переподчинить потомка
        self.assertTrue(_alive(child))
        self.assertEqual(os.getpgid(child), child, "потомок не стал вожаком своей группы")
        self.assertEqual(os.getsid(child), child, "потомок не стал лидером своей сессии")
        ppid = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(child)],
                                  capture_output=True, text=True).stdout.strip())
        self.assertEqual(ppid, 1, "потомок не переподчинён init — сцена не та, что измерена")
        proc.kill()

    def test_2_3_4_6_timeout_kills_only_what_is_proven_ours(self):
        """Критерии 2, 3, 4, 6 — на ОДНОЙ сцене, потому что это один вопрос.

        Посторонние обязаны переживать ровно тот выстрел, который убивает своих; проверять
        это на разных сценах значило бы не проверить главное — что прибор различает их
        ОДНОВРЕМЕННО.
        """
        by_none = self.start_bystander(None)
        by_foreign = self.start_bystander("orchestrator-99999-deadbeefdeadbeef")

        cmd = self.parent_cmd()
        rc = runner.run(cmd, timeout_s=4.0, grace_s=2.0, log_path=self.log,
                        label="canary", poll_s=0.25)

        child = int(open(self.child_pidfile).read().strip())
        self.mine.append(child)

        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_CLOSED,
                         f"ожидался 124, получен {rc}. Лог:\n{self.read_log()}")
        self.assertFalse(_alive(child),
                         "ОТДЕЛИВШИЙСЯ потомок выжил — ровно тот риск, из-за которого "
                         "отзыв ARB и был выдан")
        self.assertTrue(_alive(by_none), "посторонний БЕЗ метки убит")
        self.assertTrue(_alive(by_foreign), "посторонний с ЧУЖОЙ меткой убит")

    def test_5_successful_command_returns_its_own_rc(self):
        """Критерий 5: срок не трогает код здорового выхода."""
        for expected in (0, 7):
            rc = runner.run([PY, self.f["rc"], str(expected)], timeout_s=30.0, grace_s=1.0,
                            log_path=self.log, label="canary", poll_s=0.2)
            self.assertEqual(rc, expected)
        self.assertNotIn("TIMEOUT", self.read_log(),
                         "здоровый прогон не смеет печатать строку срока")

    def test_7_unresolved_ownership_returns_125_and_names_survivors(self):
        """Критерий 7: убить не удалось ⇒ 125, а не 124, и выжившие названы.

        Сигналы глушатся подменой ЕДИНСТВЕННОЙ двери к ОС. Это и есть проверка того, что
        124 не выдаётся по факту «мы постреляли», а требует ИЗМЕРЕННОГО отсутствия своих.
        """
        original = runner._signal_pid
        runner._signal_pid = lambda pid, sig: None
        try:
            rc = runner.run(self.parent_cmd(), timeout_s=3.0, grace_s=1.0,
                            log_path=self.log, label="canary", poll_s=0.25)
        finally:
            runner._signal_pid = original
        self.mine.append(int(_wait_file(self.child_pidfile)))
        self.mine.append(int(_wait_file(self.parent_ready)))
        log = self.read_log()
        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_UNRESOLVED,
                         f"ожидался 125, получен {rc}. Лог:\n{log}")
        self.assertIn("ВЛАДЕНИЕ НЕ ЗАКРЫТО", log)
        self.assertIn("SURVIVOR", log)
        # уборка: настоящие сигналы вернулись, гасим свою сцену сами
        for pid in list(self.mine):
            if _alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    def test_8_inspector_failure_returns_125_never_124(self):
        """Критерий 8: отказ прибора состояния — третий исход, а не «чисто»."""
        original = runner._ps

        def broken(_args):
            raise runner.PsUnavailable("подменённый ps: код 1")

        runner._ps = broken
        try:
            rc = runner.run([PY, "-c", "import time; time.sleep(30)"], timeout_s=2.0,
                            grace_s=1.0, log_path=self.log, label="canary", poll_s=0.2)
        finally:
            runner._ps = original
        log = self.read_log()
        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_UNRESOLVED)
        self.assertNotEqual(rc, runner.TIMEOUT_OWNERSHIP_CLOSED)
        self.assertIn("ВЛАДЕНИЕ НЕ ИЗМЕРЕНО", log)

    def test_9_evidence_is_written_before_the_first_kill(self):
        """Критерий 9: улика ДО разрушения — иначе о убитом не останется ничего."""
        rc = runner.run(self.parent_cmd(), timeout_s=4.0, grace_s=2.0, log_path=self.log,
                        label="canary", poll_s=0.25)
        self.mine.append(int(open(self.child_pidfile).read().strip()))
        log = self.read_log()
        self.assertIn("TIMEOUT-EVIDENCE", log)
        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_CLOSED)
        first_evidence = log.index("TIMEOUT-EVIDENCE")
        first_kill = log.index("SIGTERM →")
        self.assertLess(first_evidence, first_kill,
                        "улика напечатана ПОСЛЕ выстрела — тогда она не улика")

    def test_10_normal_exit_does_not_kill_the_detached_child(self):
        """Критерий 10 (owner policy 1): при нормальном выходе только фиксируем."""
        child_pidfile = os.path.join(self.tmp, "child_normal.pid")
        cmd = [PY, self.f["spawn_exit"], self.f["mid"], self.f["child"], child_pidfile]
        rc = runner.run(cmd, timeout_s=30.0, grace_s=1.0, log_path=self.log,
                        label="canary", poll_s=0.2)
        child = int(_wait_file(child_pidfile))
        self.mine.append(child)
        time.sleep(0.8)
        log = self.read_log()
        self.assertEqual(rc, 0, "код здорового выхода изменён")
        self.assertTrue(_alive(child),
                        "отделившийся потомок убит при НОРМАЛЬНОМ выходе — политика ARB "
                        "это прямо запрещает")
        self.assertIn("ANOMALY", log, "переживший потомок не зафиксирован как аномалия")
        self.assertIn("ANOMALY-EVIDENCE", log)
        self.assertNotIn("SIGTERM →", log, "на нормальной ветке выстрелов быть не может")


class TheInstrumentsAreNotOrnaments(Stage):
    """Приборы выключаются ПОШТУЧНО: объединение обязано быть доказано, а не заявлено."""

    def test_disabling_run_id_leaves_the_detached_child_alive(self):
        """Это и есть разделяющий контроль между дизайном A и дизайном B.

        Без прибора метки остаются дерево, группа и сессия — ровно то, что предлагал
        первоначальный отзыв. Отделившийся потомок при этом ВЫЖИВАЕТ, и исход 125.
        """
        only_a = {k: v for k, v in runner.INSTRUMENTS.items() if k != "run_id"}
        rc = runner.run(self.parent_cmd(), timeout_s=4.0, grace_s=2.0, log_path=self.log,
                        label="canary", poll_s=0.25, instruments=only_a)
        child = int(open(self.child_pidfile).read().strip())
        self.mine.append(child)
        time.sleep(0.5)
        self.assertTrue(_alive(child),
                        "потомок умер БЕЗ прибора метки — значит сцена не отделяет его, "
                        "и весь довод про метку не измерен")
        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_UNRESOLVED,
                         "выживший свой процесс обязан давать 125")

    def test_with_run_id_the_same_scene_closes(self):
        """Обратная сторона той же сцены: с полным набором приборов — 124."""
        rc = runner.run(self.parent_cmd(), timeout_s=4.0, grace_s=2.0, log_path=self.log,
                        label="canary", poll_s=0.25)
        self.mine.append(int(open(self.child_pidfile).read().strip()))
        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_CLOSED)



class SigtermIgnoredThenSigkill(Stage):
    """Заказ ARB п.3: вежливый сигнал не действует ⇒ grace ⇒ SIGKILL ⇒ владение закрыто, 124.

    Без этого теста эскалация была украшением: во всех прежних сценах заглушка умирала от
    первого же SIGTERM, и ветка SIGKILL не исполнялась НИ РАЗУ. Такт опроса здесь — тот,
    что стоит по умолчанию в проде (2 с), а не ускоренный: проверяется в том числе то, что
    grace на реальном такте действительно выжидается, а не проскакивается.
    """

    def test_premise_the_stub_really_ignores_sigterm(self):
        """Предпосылка сцены проверяется отдельно и ГРОМКО.

        Если заглушка на самом деле умирает от SIGTERM, главный тест ниже прошёл бы, ничего
        не проверив: эскалации не было бы, а вердикт совпал бы. Предпосылка — часть
        измерения, а не допущение.
        """
        pidfile = os.path.join(self.tmp, "ign_premise.pid")
        # БЕЗ start_new_session: заглушка сама зовёт os.setsid(), а второй вызов у
        # процесса, уже ставшего лидером сессии, поднимает PermissionError — заглушка
        # умирала до записи pid-файла, и предпосылка «не обеспечена» была верным отказом.
        proc = subprocess.Popen([PY, self.f["child_ign"], pidfile],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = int(_wait_file(pidfile))
        self.mine += [proc.pid, pid]
        os.kill(pid, signal.SIGTERM)
        time.sleep(1.0)
        self.assertTrue(_alive(pid), "заглушка умерла от SIGTERM — сцена не та, что заказана")
        os.kill(pid, signal.SIGKILL)
        # Дожать обязательно: убитый, но не дожатый ребёнок становится ЗОМБИ, а по зомби
        # `kill -0` ПРОХОДИТ (замер 18.09) — проверка «умер?» через _alive соврала бы.
        proc.wait(timeout=5)
        self.assertFalse(_alive(pid), "SIGKILL не убил — значит мерить эскалацию нечем")

    def test_sigterm_ignoring_tree_is_closed_by_sigkill_with_rc_124(self):
        by_none = self.start_bystander(None)
        by_foreign = self.start_bystander("orchestrator-77777-cafebabecafebabe")

        child_pidfile = os.path.join(self.tmp, "child_ign.pid")
        ready = os.path.join(self.tmp, "parent_ign.ready")
        cmd = [PY, self.f["parent_ign"], self.f["mid"], self.f["child_ign"],
               child_pidfile, ready]

        t0 = time.monotonic()
        # poll_s НЕ передаётся: берётся прод-умолчание (2 с) — такт тоже под проверкой
        rc = runner.run(cmd, timeout_s=3.0, grace_s=6.0, log_path=self.log, label="canary")
        elapsed = time.monotonic() - t0

        child = int(_wait_file(child_pidfile))
        parent = int(_wait_file(ready))
        self.mine += [child, parent]
        log = self.read_log()

        self.assertEqual(rc, runner.TIMEOUT_OWNERSHIP_CLOSED,
                         f"ожидался 124, получен {rc}. Лог:\n{log}")
        self.assertIn("SIGTERM →", log, "вежливый сигнал вообще не посылался")
        self.assertIn("SIGKILL →", log, "эскалации не было — ветка SIGKILL не исполнена")
        self.assertLess(log.index("SIGTERM →"), log.index("SIGKILL →"),
                        "порядок сигналов обратный: grace обойдён")
        self.assertGreaterEqual(elapsed, 3.0 + 6.0,
                                f"grace не выжидался: весь прогон занял {elapsed:.1f}s")
        self.assertFalse(_alive(parent), "прямой потомок выжил")
        self.assertFalse(_alive(child), "ОТДЕЛИВШИЙСЯ потомок выжил")
        self.assertTrue(_alive(by_none), "посторонний БЕЗ метки убит")
        self.assertTrue(_alive(by_foreign), "посторонний с ЧУЖОЙ меткой убит")

    def test_default_poll_is_the_production_tact(self):
        """Такт по умолчанию — 2 с и у функции, и у CLI: расхождение = два разных прибора."""
        import inspect
        self.assertEqual(runner.DEFAULT_POLL_S, 2.0, "прод-такт изменён без решения ARB")
        self.assertEqual(inspect.signature(runner.run).parameters["poll_s"].default,
                         runner.DEFAULT_POLL_S)
        self.assertEqual(runner.build_parser().get_default("poll_s"),
                         runner.DEFAULT_POLL_S,
                         "CLI и функция разошлись тактом — это два прибора под одним именем")
        self.assertEqual(runner.build_parser().get_default("grace_s"),
                         runner.DEFAULT_GRACE_S)


class AgeFilterAndParsing(unittest.TestCase):
    """Фильтр «не старше запуска» и разбор `etime` — на синтетической таблице.

    На живых процессах эту защиту честно не построить: у неё нет способа родить процесс
    СТАРШЕ запуска, но с НАШЕЙ меткой. Поэтому таблица подменяется целиком — вопрос здесь
    к арифметике фильтра, а не к ОС.
    """

    def test_etime_forms(self):
        self.assertEqual(runner._parse_etime("00:01"), 1)
        self.assertEqual(runner._parse_etime("02:03"), 123)
        self.assertEqual(runner._parse_etime("01:00:00"), 3600)
        self.assertEqual(runner._parse_etime("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5)
        with self.assertRaises(ValueError):
            runner._parse_etime("нет")

    def test_a_process_older_than_the_run_is_not_owned_even_with_our_stamp(self):
        run_id = "canary-1-abc"
        table = (
            f"  4242     1 S    10:00:00 python3 -m pytest SPA_RUN_ID={run_id} PATH=/usr/bin\n"
            f"  4243     1 S       00:02 python3 -m pytest SPA_RUN_ID={run_id} PATH=/usr/bin\n"
        )
        original = runner._ps
        runner._ps = lambda _args: table
        try:
            owned = runner.census(999999, run_id, run_age_s=30.0, self_pid=os.getpid(),
                                  self_sid=None, instruments={"run_id": runner._inst_run_id})
        finally:
            runner._ps = original
        pids = [o.pid for o in owned]
        self.assertIn(4243, pids, "молодой процесс с нашей меткой обязан быть нашим")
        self.assertNotIn(4242, pids,
                         "процесс СТАРШЕ запуска признан нашим — это выстрел в "
                         "переиспользованный номер")

    def test_a_zombie_with_our_stamp_is_not_a_survivor(self):
        """Ложный 125, найденный на pre-delivery gate.

        Зомби виден в `ps` (`57648 57647 Z 00:01 <defunct>`), и `kill -0` по нему
        ПРОХОДИТ. Если считать его выжившим, финальная перепись давала бы 125 всякий раз,
        когда родитель не успел дожать ребёнка за те секунды, что идёт проверка, — то есть
        тревога звучала бы на исправной уборке.
        """
        run_id = "canary-1-zzz"
        table = (
            f"  5150     1 Z       00:02 <defunct> SPA_RUN_ID={run_id}\n"
            f"  5151     1 S       00:02 python3 -m pytest SPA_RUN_ID={run_id} PATH=/usr/bin\n"
        )
        original = runner._ps
        runner._ps = lambda _args: table
        try:
            owned = runner.census(999999, run_id, run_age_s=30.0, self_pid=os.getpid(),
                                  self_sid=None, instruments={"run_id": runner._inst_run_id})
        finally:
            runner._ps = original
        pids = [o.pid for o in owned]
        self.assertIn(5151, pids, "живой процесс с нашей меткой обязан быть нашим")
        self.assertNotIn(5150, pids, "зомби засчитан выжившим — это ложный 125")

    def test_empty_ps_table_is_a_third_outcome_not_a_clean_answer(self):
        original = runner._ps
        runner._ps = lambda _args: ""
        try:
            with self.assertRaises(runner.PsUnavailable):
                runner.Snapshot.take()
        finally:
            runner._ps = original


class WrappersAndHygiene(unittest.TestCase):

    def test_11_bash_syntax_of_both_wrappers(self):
        for name in ("agent_orchestrator.sh", "agent_novel_edge_rnd.sh"):
            path = os.path.join(ROOT, "scripts", name)
            proc = subprocess.run(["/bin/bash", "-n", path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")

    def test_wrappers_match_the_declared_phase_1_scope(self):
        """Объём поставки ОБЪЯВЛЕН, и проверяется в ОБЕ стороны.

        ARB, Phase 1 canary (18.09): срок включается только у `com.spa.orchestrator`;
        `com.spa.novel_edge_rnd` не трогается и не доставляется, пока канарейка не отработает.

        Поэтому мало проверить, что подключённая обёртка зовёт прибор: надо проверить и что
        НЕподключённая осталась ровно такой, какой была. Иначе половинное состояние —
        обёртка, где прямой вызов уже убран, а прибор ещё не подключён, — проехало бы
        молча, и агент остался бы без вызова Claude вовсе. Расширение объёма на вторую
        обёртку обязано быть правкой ЭТОГО списка, то есть решением, а не побочным эффектом.
        """
        WIRED = {"agent_orchestrator.sh": "SPA_ORCHESTRATOR_TIMEOUT_S"}
        NOT_YET_WIRED = ("agent_novel_edge_rnd.sh",)

        for name, var in WIRED.items():
            src = open(os.path.join(ROOT, "scripts", name), encoding="utf-8").read()
            self.assertIn("claude_run_with_timeout.py", src, f"{name}: прибор не подключён")
            self.assertIn(var, src, f"{name}: срок не объявлен ручкой")
            self.assertIn("exit $RC", src, f"{name}: код перестал доезжать до launchd")
            self.assertNotIn('"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >>',
                             src, f"{name}: прямой вызов claude остался рядом с прибором")

        for name in NOT_YET_WIRED:
            src = open(os.path.join(ROOT, "scripts", name), encoding="utf-8").read()
            self.assertNotIn("claude_run_with_timeout.py", src,
                             f"{name}: прибор подключён ВНЕ объявленного объёма Phase 1")
            self.assertIn('"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >>',
                          src, f"{name}: прямой вызов Claude пропал, а прибор не подключён — "
                               f"обёртка в половинном состоянии, агент остался бы без Claude")
            self.assertIn("exit $RC", src, f"{name}: код перестал доезжать до launchd")

    def test_12_the_stage_touches_no_real_spa_agent(self):
        """Критерий 12: сцена не может ПЕРЕДАТЬ В ОС ни настоящий claude, ни launchctl.

        Прибор гигиены дважды ошибся одним и тем же классом, и оба раза — отравлением
        собственного корпуса: сперва грепал свой исходник целиком и краснел на фразе
        «launchctl мы не трогаем», потом собирал ВСЕ строковые литералы AST и краснел на
        собственном списке запрещённых слов и на сообщениях `assert`. Оба раза он мерил
        «что я о себе рассказываю», а вопрос был «что я могу передать в ОС».

        Теперь население — литералы ВНУТРИ вызовов, которые обращаются к ОС
        (`subprocess.*`, `os.kill/system/exec*`), плюс тела заглушек, разобранные так же.
        Докстринги, сообщения и списки слов в это население не входят по построению.
        """
        import ast

        OS_DOORS = ("run", "Popen", "check_output", "check_call", "call",
                    "kill", "system", "execv", "execvp", "spawnv")

        def os_bound_literals(src: str):
            out = []
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else "")
                if name not in OS_DOORS:
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        out.append(sub.value)
            return out

        population = os_bound_literals(open(os.path.abspath(__file__),
                                            encoding="utf-8").read())
        for stub in (CHILD_STUB, MID_STUB, PARENT_STUB, RC_STUB,
                     SPAWN_AND_EXIT_STUB, BYSTANDER_STUB,
                     CHILD_STUB_IGNORING_SIGTERM, PARENT_STUB_IGNORING_SIGTERM):
            population += os_bound_literals(stub)
        haystack = "\n".join(population)

        for forbidden in ("launchctl", "/.local/bin/claude",
                          "dangerously-skip-permissions", "Documents/SPA_Claude"):
            self.assertNotIn(forbidden, haystack,
                             f"сцена может передать в ОС {forbidden}; население: {population}")

        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на сам прибор гигиены: сцена, которая ДЕЙСТВИТЕЛЬНО
        # зовёт launchctl, обязана быть поймана. Без него проверка неотличима от пустой.
        guilty = 'import subprocess\nsubprocess.run(["launchctl", "list"])\n'
        self.assertIn("launchctl", "\n".join(os_bound_literals(guilty)))
        # И обратная сторона: одно лишь УПОМИНАНИЕ в тексте ловиться не должно.
        innocent = '"""мы никогда не зовём launchctl"""\nx = "launchctl"\n'
        self.assertNotIn("launchctl", "\n".join(os_bound_literals(innocent)))

    def test_runner_is_stdlib_only(self):
        """Инвариант #4: сторонних ввозов в рантайме нет."""
        import ast
        tree = ast.parse(open(RUNNER_PATH, encoding="utf-8").read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertTrue(names <= set(sys.stdlib_module_names) | {"__future__"},
                        f"несистемные ввозы: {names - set(sys.stdlib_module_names)}")


if __name__ == "__main__":
    unittest.main()

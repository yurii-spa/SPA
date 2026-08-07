"""Общий замок цикла оркестратора (ADR-070 п.9) — положительные контроли.

Каждый тест воспроизводит НАСТОЯЩУЮ аварию, а не гипотезу:

* 30.07 две автономные сессии независимо взяли одну карточку и правили одни файлы;
  доставлена одна, вторая осталась в `/tmp`-worktree. Карточки от этого защищены с тех пор,
  а сам ЦИКЛ — нет: захват карточки срабатывает после шагов 0/0a/0b, то есть после самой
  дорогой части прогона, и вовсе не срабатывает, когда вторая сессия берёт СЛЕДУЮЩУЮ
  карточку и два автономных пушера идут в один `origin/main` наперегонки.
* Замок, который нельзя снять, — не защита, а вечная остановка очереди: этот класс
  («необратимое не-измерено морит очередь») разбирался в циклах #146 и #149, и повторять
  его в новом стороже нельзя.
* Сторож, убивающий то, что охраняет, вреднее отсутствия сторожа — посылка, уже
  закреплённая в `cycle_runner._acquire_cycle_lock`.

Время здесь — ВХОД (`now=`), а не окружение: замок судит о свежести, а фикстура с
литеральной датой в таком коде — бомба замедленного действия (правило доставки, §«Время
в тестах»). Живость держателя тоже вход — подставная `ps`, настоящих процессов тесты не
трогают.
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
LOCK_PY = ROOT / "scripts" / "orchestrator_cycle_lock.py"
SIBLING_PY = ROOT / "scripts" / "check_undelivered_work.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load(LOCK_PY, "_test_orchestrator_cycle_lock")
SIB = _load(SIBLING_PY, "_test_cycle_lock_sibling")

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)

# `ps -p <pid> -o lstart=` в локальной зоне; сравнивается только на совпадение строк
# и на «этот процесс существует», поэтому конкретная дата тут — предмет, а не окружение.
LSTART_A = "Fri Aug  7 10:00:00 2026"
LSTART_B = "Fri Aug  7 11:30:00 2026"


def ps_alive(start=LSTART_A):
    """Подставная `ps`: любой pid жив и стартовал в `start`."""
    return lambda pid: (0, start + "\n")


def ps_dead(pid):
    """`ps -p` вернул 1 — процесса нет (сессия умерла, не сняв замок)."""
    return (1, "")


def ps_broken(pid):
    """`ps` не отработал — живость НЕ измерена (не то же самое, что «мертва»)."""
    return (127, "")


def holder(session="cycle-111", pid=111, start=LSTART_A, ts=NOW):
    return L.holder_record(session, pid, start, ts)


def age_dir(path: Path, seconds: float, now=NOW):
    """Состарить каталог замка: mtime = now - seconds."""
    stamp = now.timestamp() - seconds
    os.utime(path, (stamp, stamp))


class LockCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name) / L.LOCK_DIRNAME
        self.addCleanup(self._tmp.cleanup)

    def plant(self, rec, age_sec=60.0):
        """Положить чужой замок нужного возраста."""
        self.dir.mkdir(parents=True)
        L._write_holder(self.dir, rec)
        age_dir(self.dir, age_sec)


# ── базовое поведение ────────────────────────────────────────────────────────

class TestFreeAndHeld(LockCase):

    def test_free_lock_is_acquired_and_holder_recorded(self):
        v, msg = L.acquire(self.dir, holder("cycle-222", 222), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.ACQUIRED, v, msg)
        rec, err = L.read_holder(self.dir)
        self.assertEqual("", err)
        self.assertEqual("cycle-222", rec["session"])
        self.assertEqual(222, rec["session_pid"])
        self.assertEqual(LSTART_A, rec["session_pid_start"])

    def test_live_holder_refuses_the_second_cycle(self):
        """Авария 30.07: второй цикл начинал работать поверх первого."""
        self.plant(holder("cycle-111", 111))
        v, msg = L.acquire(self.dir, holder("cycle-222", 222, LSTART_B), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_B, ps=ps_alive())
        self.assertEqual(L.BUSY, v, msg)
        self.assertIn("cycle-111", msg)
        rec, _ = L.read_holder(self.dir)
        self.assertEqual("cycle-111", rec["session"],
                         "замок обязан остаться у первого — второй его не перезаписывает")

    def test_busy_exit_code_is_polite_not_an_error(self):
        """Занято — исход, а не авария: код 3, отличимый от находок (1) и не-измерено (2)."""
        self.assertEqual(3, L._EXIT_BY_VERDICT[L.BUSY])
        self.assertEqual(0, L._EXIT_BY_VERDICT[L.ACQUIRED])
        self.assertEqual(0, L._EXIT_BY_VERDICT[L.STALE_TAKEN])
        self.assertEqual(0, L._EXIT_BY_VERDICT[L.UNPROTECTED])
        self.assertEqual(4, L._EXIT_BY_VERDICT[L.NOT_MINE])


# ── замок не имеет права запереть очередь навсегда ───────────────────────────

class TestNeverLocksForever(LockCase):

    def test_dead_holder_is_taken_over(self):
        """Сессия умерла, не сняв замок. Иначе одна смерть блокирует цикл навсегда."""
        self.plant(holder("cycle-111", 111))
        v, msg = L.acquire(self.dir, holder("cycle-222", 222, LSTART_B), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_B, ps=ps_dead)
        self.assertEqual(L.STALE_TAKEN, v, msg)
        rec, _ = L.read_holder(self.dir)
        self.assertEqual("cycle-222", rec["session"])

    def test_unmeasured_liveness_blocks_only_inside_the_window(self):
        """`ps` не отработал: «не измерено» блокирует, но НЕ вечно (класс #146)."""
        self.plant(holder("cycle-111", 111), age_sec=600.0)
        v, _ = L.acquire(self.dir, holder("cycle-222", 222, LSTART_B), "cycle-222", 222,
                         SIB, now=NOW, self_pid_start=LSTART_B, ps=ps_broken,
                         unmeasured_ttl_sec=3 * 3600.0)
        self.assertEqual(L.BUSY, v, "внутри окна не-измеренное состояние обязано блокировать")

        age_dir(self.dir, 4 * 3600.0)
        v, msg = L.acquire(self.dir, holder("cycle-222", 222, LSTART_B), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_B, ps=ps_broken,
                           unmeasured_ttl_sec=3 * 3600.0)
        self.assertEqual(L.STALE_TAKEN, v, msg)

    def test_holderless_lock_is_grace_then_abandoned(self):
        """Каталог есть, holder.json нет: свежий — кто-то берёт прямо сейчас; старый — огрызок."""
        self.dir.mkdir(parents=True)
        age_dir(self.dir, 5.0)
        v, _ = L.acquire(self.dir, holder("cycle-222", 222), "cycle-222", 222,
                         SIB, now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.BUSY, v, "гонка записи holder.json не должна читаться как свобода")

        age_dir(self.dir, L.WRITE_GRACE_SEC + 120.0)
        v, msg = L.acquire(self.dir, holder("cycle-222", 222), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.STALE_TAKEN, v, msg)

    def test_corrupt_holder_json_does_not_wedge_the_lock(self):
        self.dir.mkdir(parents=True)
        (self.dir / L.HOLDER_FILE).write_text("{не json", encoding="utf-8")
        age_dir(self.dir, L.WRITE_GRACE_SEC + 120.0)
        v, msg = L.acquire(self.dir, holder("cycle-222", 222), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.STALE_TAKEN, v, msg)


# ── личность держателя ───────────────────────────────────────────────────────

class TestIdentity(LockCase):

    def test_my_own_lock_is_not_a_reason_to_exit(self):
        """Повторный вызов внутри своего же цикла (trap, ретрай) не должен «вежливо выходить»."""
        self.plant(holder("cycle-222", 222))
        v, msg = L.acquire(self.dir, holder("cycle-222", 222), "cycle-222", 222,
                           SIB, now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.ALREADY_MINE, v, msg)

    def test_recycled_pid_is_not_me(self):
        """Тот же номер, ДРУГОЙ процесс: без сверки старта я бы работал под чужим замком."""
        self.assertFalse(L.same_identity(holder("cycle-111", 111, LSTART_A),
                                         "cycle-999", 111, LSTART_B))
        self.assertTrue(L.same_identity(holder("cycle-111", 111, LSTART_A),
                                        "cycle-999", 111, LSTART_A))

    def test_release_refuses_someone_elses_lock(self):
        self.plant(holder("cycle-111", 111))
        v, msg = L.release(self.dir, "cycle-222", 222, LSTART_B)
        self.assertEqual(L.NOT_MINE, v, msg)
        self.assertTrue(self.dir.exists(), "чужой замок обязан уцелеть")

    def test_release_frees_my_own_lock_for_the_next_run(self):
        self.plant(holder("cycle-222", 222))
        v, _ = L.release(self.dir, "cycle-222", 222, LSTART_A)
        self.assertEqual(L.RELEASED, v)
        self.assertFalse(self.dir.exists())
        v, _ = L.acquire(self.dir, holder("cycle-333", 333, LSTART_B), "cycle-333", 333,
                         SIB, now=NOW, self_pid_start=LSTART_B, ps=ps_alive())
        self.assertEqual(L.ACQUIRED, v)


# ── сторож не имеет права убить то, что охраняет ─────────────────────────────

class TestGuardNeverKillsTheCycle(LockCase):

    def test_unusable_lock_directory_lets_the_cycle_run_unprotected(self):
        """Файловая система/права отказали — цикл идёт БЕЗ защиты и говорит об этом."""
        with mock.patch.object(L.os, "mkdir", side_effect=OSError("read-only fs")):
            v, msg = L.acquire(self.dir, holder("cycle-222", 222), "cycle-222", 222,
                               SIB, now=NOW, self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.UNPROTECTED, v, msg)
        self.assertEqual(0, L._EXIT_BY_VERDICT[v], "поломка сторожа не смеет останавливать цикл")
        self.assertIn("БЕЗ защиты", msg)

    def test_unresolvable_shared_tree_is_unprotected_not_silently_local(self):
        """Замок обязан быть ОБЩИМ. Не разрешилось главное дерево — сказать вслух.

        Молча взять локальный замок в `/tmp`-worktree значит получить «свободно» для всех:
        отсутствие защиты с интерфейсом защиты (класс fail-OPEN мониторов)."""
        fake = mock.Mock()
        fake.shared_log.return_value = (Path("/tmp/nowhere/session_changes.jsonl"),
                                        "главное дерево не определено")
        path, err = L.lock_dir(fake)
        self.assertTrue(err)
        self.assertEqual(L.LOCK_DIRNAME, path.name)

    def test_shared_lock_dir_sits_next_to_the_shared_journal(self):
        fake = mock.Mock()
        fake.shared_log.return_value = (Path("/repo/data/session_changes.jsonl"), None)
        path, err = L.lock_dir(fake)
        self.assertIsNone(err)
        self.assertEqual(Path("/repo/data") / L.LOCK_DIRNAME, path)


# ── «подожди N минут» — замер, а не выдуманное число ─────────────────────────

class TestWaitEstimate(unittest.TestCase):

    @staticmethod
    def _entries(spans_minutes, first=NOW - timedelta(hours=20)):
        """По две записи на сессию: старт цикла и доставка (так объявляются настоящие циклы)."""
        rows, t = [], first
        for i, span in enumerate(spans_minutes):
            sess = f"cycle-{1000 + i}"
            rows.append({"session": sess, "ts": t.strftime("%Y-%m-%dT%H:%M:%SZ")})
            rows.append({"session": sess,
                         "ts": (t + timedelta(minutes=span)).strftime("%Y-%m-%dT%H:%M:%SZ")})
            t += timedelta(hours=1)
        return rows

    def test_median_is_measured_from_real_announcements(self):
        median, n = L.typical_cycle_minutes(self._entries([20, 30, 40, 50, 60]))
        self.assertEqual(5, n)
        self.assertEqual(40.0, median)

    def test_too_few_samples_yields_no_number_at_all(self):
        """Честное «оценки нет» лучше уверенного числа из двух точек (ADR-070 п.12)."""
        median, n = L.typical_cycle_minutes(self._entries([20, 30]))
        self.assertIsNone(median)
        self.assertEqual(2, n)

    def test_single_announcement_sessions_do_not_drag_the_median_to_zero(self):
        """Сессия с одним объявлением длительности не даёт. Ноль читался бы как «подожди ~0»."""
        rows = self._entries([40, 40, 40])
        rows += [{"session": "cycle-9001", "ts": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")},
                 {"session": "cycle-9002", "ts": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}]
        median, n = L.typical_cycle_minutes(rows)
        self.assertEqual(3, n)
        self.assertEqual(40.0, median)

    def test_current_holder_is_excluded_from_its_own_estimate(self):
        rows = self._entries([40, 40, 40])
        rows += [{"session": "cycle-1000", "ts": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}]
        median, n = L.typical_cycle_minutes(rows, exclude_session="cycle-1000")
        self.assertEqual(2, n)
        self.assertIsNone(median, "исключив держателя, замеров стало мало — молчим, а не гадаем")

    def test_manual_run_is_told_how_long_to_wait(self):
        self.assertIn("подожди ~30 мин", L.wait_hint(10.0, 40.0, 5))

    def test_overrunning_cycle_is_named_as_overrun_not_negative_wait(self):
        hint = L.wait_hint(90.0, 40.0, 5)
        self.assertIn("дольше типового", hint)
        self.assertNotIn("-", hint)

    def test_no_samples_says_so_instead_of_inventing(self):
        self.assertIn("оценки времени нет", L.wait_hint(10.0, None, 1))


# ── status ничего не меняет ──────────────────────────────────────────────────

class TestStatusIsReadOnly(LockCase):

    def test_status_of_a_live_lock_reports_busy_and_leaves_it_alone(self):
        self.plant(holder("cycle-111", 111))
        v, msg = L.status(self.dir, "cycle-222", 222, SIB, now=NOW,
                          self_pid_start=LSTART_B, ps=ps_alive())
        self.assertEqual(L.BUSY, v, msg)
        self.assertTrue(self.dir.exists())
        rec, _ = L.read_holder(self.dir)
        self.assertEqual("cycle-111", rec["session"])

    def test_status_of_a_dead_lock_reports_free_but_does_not_remove_it(self):
        """`status` — чтение. Снимает брошенный замок только `acquire`."""
        self.plant(holder("cycle-111", 111))
        v, msg = L.status(self.dir, "cycle-222", 222, SIB, now=NOW,
                          self_pid_start=LSTART_B, ps=ps_dead)
        self.assertEqual(L.FREE, v, msg)
        self.assertTrue(self.dir.exists(), "status не мутирует замок")

    def test_status_of_absent_lock_is_free(self):
        v, _ = L.status(self.dir, "cycle-222", 222, SIB, now=NOW,
                        self_pid_start=LSTART_A, ps=ps_alive())
        self.assertEqual(L.FREE, v)


# ── проводка в обёртку агента ────────────────────────────────────────────────

class TestWrapperWiring(unittest.TestCase):
    """Замок, не подключённый к обёртке, — мёртвый код (класс «мутируй проводку, а не деталь»)."""

    @classmethod
    def setUpClass(cls):
        cls.sh = (ROOT / "scripts" / "agent_orchestrator.sh").read_text(encoding="utf-8")

    def test_wrapper_acquires_the_lock(self):
        self.assertIn("orchestrator_cycle_lock.py", self.sh)
        self.assertIn("acquire", self.sh)

    def test_wrapper_exits_politely_on_busy(self):
        """Занято ⇒ выход 0. Ловим САМУ ветку, а не цифру 3 где-нибудь в тексте."""
        self.assertRegex(self.sh, r'LOCK_RC"?\s*-eq\s+' + str(L.EXIT_BUSY),
                         "обёртка обязана отличать «занято» от ошибки по коду возврата")
        tail = self.sh[self.sh.index("LOCK_RC"):]
        branch = tail[tail.index("-eq"):]
        self.assertIn("exit 0", branch[:400],
                      "«занято» — здоровое поведение: agent_health не должен видеть ошибку")

    def test_wrapper_releases_on_exit(self):
        self.assertIn("release", self.sh)
        self.assertIn("trap", self.sh, "замок обязан сниматься и при аварийном выходе")

    def test_lock_is_taken_after_the_arming_gate(self):
        """Инертный прогон (`SPA_ORCHESTRATOR_ARMED != 1`) замок брать не должен.

        Якорь — САМА ветка гейта, а не первое упоминание переменной: она упомянута ещё и в
        шапке-комментарии, и привязка к ней сделала бы тест зелёным при любом порядке."""
        gate = self.sh.index('if [ "${SPA_ORCHESTRATOR_ARMED:-0}" != "1" ]')
        lock = self.sh.index("orchestrator_cycle_lock.py")
        self.assertLess(gate, lock)

    def test_wrapper_passes_its_own_durable_pid(self):
        """Личность — долгоживущий процесс обёртки, а не pid однократной CLI-команды."""
        self.assertIn("--pid \"$SPA_SESSION_PID\"", self.sh)


if __name__ == "__main__":
    unittest.main()

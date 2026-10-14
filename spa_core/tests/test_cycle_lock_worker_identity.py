"""Замок цикла обязан пережить РАБОТНИКА, а не ЗАПУСКАТЕЛЯ (ADR-720).

Каждый тест — положительный контроль НАСТОЯЩЕЙ аварии 2026-10-14 (цикл #864), а не
гипотезы. Что было измерено в тот день:

* `agent_orchestrator.sh` берёт замок под СВОЕЙ личностью (`$$`), а работу делает
  headless `claude`, которого `claude_run_with_timeout.py` поднимает
  `start_new_session=True` — лидером СВОЕЙ сессии. Сигнал, снимающий группу запускателя,
  работника не достаёт.
* Запускатель умер, `trap release_lock EXIT` снял замок, работник ОСТАЛСЯ ЖИВ
  (pid 69661, `ppid=1`, `sid=69661`) и продолжал править своё дерево.
* Следующий цикл взял замок (`acquired`, то есть каталога не было вовсе) и получил ТУ ЖЕ
  голодающую карточку владельца с вердиктом `stale`. Две сессии на одном приказе.
* Замер по журналу прогонов: **19 взятий замка, 0 отказов** — замок не отказал ни разу
  не потому, что столкновений не было, а потому, что мерил не ту личность.

Личность, переживающая запускателя, одна — `SPA_RUN_ID` в ОКРУЖЕНИИ: её наследуют все
потомки, она не теряется при осиротении, и ею же обёртка решает, кого завершать по сроку.

Живость здесь — ВХОД (`procs_with_run_id=`), а не живая ОС, и время — вход (`now=`):
сторож, спрашивающий настоящие процессы, меняет вердикт от того, кто сегодня занял номер
(`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Ни одного литерального pid живой
машины в файле нет.
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
LOCK_PY = ROOT / "scripts" / "orchestrator_cycle_lock.py"
SIBLING_PY = ROOT / "scripts" / "check_undelivered_work.py"
WRAPPER_PY = ROOT / "scripts" / "claude_run_with_timeout.py"
ORCHESTRATOR_SH = ROOT / "scripts" / "agent_orchestrator.sh"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load(LOCK_PY, "_t864_lock")
SIB = _load(SIBLING_PY, "_t864_sibling")

# FROZEN-DATE-OK: injected-clock — мгновение АВАРИИ 14.10 12:14:34Z является предметом
# файла, и часы ИНЪЕКТИРОВАНЫ: этот якорь передаётся измерителю аргументом (`now=NOW` у
# `classify`/`acquire`/`status`), а все отметки сцены выведены из него же — закреплены обе
# стороны сравнения. Пометку дописал цикл #865: без неё `main` краснел храповиком
# замороженных дат с 32d94521d (файл в базу НЕ добавлен — база только убывает), а саму
# претензию `injected-clock` машинно сверяет `test_injected_clock_claim.py` (ADR-477),
# поэтому молчаливым отключением строка быть не может.
NOW = datetime(2026, 10, 14, 12, 14, 34, tzinfo=timezone.utc)
LSTART = "Wed Oct 14 11:31:32 2026"
RUN_ID = "orchestrator-69660-f75c8e16721e432890b786b016c71b13"


def ps_dead(pid):
    """Запускателя нет — его снял тот же сигнал, что не достал работника."""
    return (1, "")


def ps_alive(pid):
    return (0, LSTART + "\n")


def probe_alive(pids=(69661, 75649, 75653), seen=None):
    """Работник ЖИВ: метку несут живые процессы (замер 14.10 — ровно эти три)."""
    def _probe(run_id):
        if seen is not None:
            seen.append(run_id)
        return set(pids), f"живых процессов с меткой {run_id}: {len(pids)}"
    return _probe


def probe_gone(run_id):
    """Работника нет: метку не несёт никто. Пустое множество — это ИЗМЕРЕНИЕ."""
    return set(), f"живых процессов с меткой {run_id}: 0"


def probe_unmeasured(run_id):
    """Спросить не удалось. `None` — третий исход, и он НЕ «работника нет»."""
    return None, "окружение не читается ни у одного процесса"


def holder(run_id=RUN_ID, session="cycle-69075", pid=69075, start=LSTART):
    extra = {L.RUN_ID_KEY: run_id} if run_id else None
    return L.holder_record(session, pid, start, NOW, extra)


def age_dir(path: Path, seconds: float, now=NOW):
    stamp = now.timestamp() - seconds
    os.utime(path, (stamp, stamp))


class WorkerAxisCase(unittest.TestCase):
    """Ось РАБОТНИКА: кого замок обязан считать живым."""

    def _classify(self, hold, *, ps=ps_dead, probe=None, age=120.0,
                  worker_ttl=L.DEFAULT_WORKER_TTL_SEC, unmeasured_ttl=None):
        return L.classify(
            hold, "", age, "cycle-27063", 27063, SIB,
            self_pid_start="Wed Oct 14 12:14:34 2026", ps=ps,
            unmeasured_ttl_sec=(L.DEFAULT_UNMEASURED_TTL_SEC if unmeasured_ttl is None
                                else unmeasured_ttl),
            procs_with_run_id=probe, worker_ttl_sec=worker_ttl)

    def test_incident_launcher_dead_worker_alive_is_held_not_abandoned(self):
        """АВАРИЯ 14.10 дословно: запускатель мёртв, работник жив ⇒ замок ЗАНЯТ."""
        state, why = self._classify(holder(), ps=ps_dead, probe=probe_alive())
        self.assertEqual(state, L.HELD_WORKER_ALIVE, why)
        self.assertNotIn(state, L._ABANDONED, "замок ушёл бы из-под идущей работы")

    def test_control_worker_gone_still_releases_the_lock(self):
        """ОБРАТНАЯ сторона: работника нет ⇒ прежний вердикт, очередь не морится.

        Порванное звено — ось РАБОТНИКА отвечает `gone`. Без этого контроля правка
        превратила бы замок в вечный, а это класс #146 («необратимое не-измерено»)."""
        state, why = self._classify(holder(), ps=ps_dead, probe=probe_gone)
        self.assertEqual(state, L.ABANDONED_DEAD, why)
        self.assertIn(state, L._ABANDONED, why)

    def test_control_holder_without_run_id_behaves_exactly_as_before(self):
        """Запись СТАРОГО образца: метки нет ⇒ судит ось запускателя, как до правки.

        Порванное звено — в holder.json нет `run_id`. Вердикт обязан совпасть с прежним
        поведением, иначе правка сломала бы уже лежащие замки."""
        state, why = self._classify(holder(run_id=None), ps=ps_dead, probe=probe_alive())
        self.assertEqual(state, L.ABANDONED_DEAD, why)
        self.assertIn("НЕ МЕРИЛАСЬ", L.worker_axis(holder(run_id=None))[1])

    def test_unmeasured_worker_blocks_but_is_never_called_gone(self):
        """Третий исход: пробу не задали ⇒ блокируем, но НЕ объявляем работника мёртвым."""
        state, why = self._classify(holder(), ps=ps_dead, probe=probe_unmeasured)
        self.assertEqual(state, L.HELD_UNMEASURED, why)
        self.assertNotIn(state, L._ABANDONED, why)

    def test_unmeasured_worker_is_bounded_by_the_window(self):
        """…но ограниченно: за окном «не измерено» замок брошен, иначе он вечный."""
        state, why = self._classify(holder(), ps=ps_dead, probe=probe_unmeasured,
                                    age=4 * 3600.0, unmeasured_ttl=3 * 3600.0)
        self.assertEqual(state, L.ABANDONED_TTL, why)

    def test_live_worker_is_bounded_by_its_own_budget(self):
        """Живой работник держит замок не дольше СВОЕГО срока — повисший не морит очередь.

        Порванное звено — работник жив, но замку больше, чем бюджет прогона."""
        state, why = self._classify(holder(), ps=ps_dead, probe=probe_alive(),
                                    age=L.DEFAULT_WORKER_TTL_SEC + 60.0)
        self.assertEqual(state, L.ABANDONED_WORKER_TTL, why)
        self.assertIn(state, L._ABANDONED, why)

    def test_probe_is_an_input_and_the_live_os_is_never_consulted(self):
        """Проба — ВХОД: при инъекции настоящая ОС не спрашивается ни разу.

        Доказываем положительно: прибор по умолчанию указан в НЕСУЩЕСТВУЮЩИЙ файл, и
        если бы `classify` до него дошла, вердикт стал бы «не измерено»."""
        seen = []
        original = L.WRAPPER
        try:
            L.WRAPPER = Path("/nonexistent/claude_run_with_timeout.py")
            state, why = self._classify(holder(), ps=ps_dead, probe=probe_alive(seen=seen))
        finally:
            L.WRAPPER = original
        self.assertEqual(state, L.HELD_WORKER_ALIVE, why)
        self.assertEqual(seen, [RUN_ID], "проба не получила метку держателя")


class AcquireAndReleaseCase(unittest.TestCase):
    """Исход у ДВЕРИ, которой пользуется цикл, а не только у чистой функции."""

    def test_second_cycle_is_refused_while_the_worker_still_works(self):
        """Тот самый вызов, что сделал цикл #864 в 12:14 — теперь он ОТКАЗ."""
        with TemporaryDirectory() as td:
            path = Path(td) / "orchestrator_cycle.lock"
            path.mkdir()
            (path / L.HOLDER_FILE).write_text(json.dumps(holder()), encoding="utf-8")
            age_dir(path, 2580.0)
            verdict, msg = L.acquire(
                path, holder(run_id="orchestrator-27715-new", session="cycle-27063",
                             pid=27063),
                "cycle-27063", 27063, SIB, now=NOW, ps=ps_dead,
                procs_with_run_id=probe_alive())
            self.assertEqual(verdict, L.BUSY, msg)
            self.assertNotEqual(verdict, L.STALE_TAKEN,
                                "замок снят с живой работы — авария 14.10 повторилась")

    def test_control_second_cycle_proceeds_once_the_worker_is_gone(self):
        """ОБРАТНАЯ сторона той же двери: работник ушёл ⇒ цикл идёт."""
        with TemporaryDirectory() as td:
            path = Path(td) / "orchestrator_cycle.lock"
            path.mkdir()
            (path / L.HOLDER_FILE).write_text(json.dumps(holder()), encoding="utf-8")
            age_dir(path, 2580.0)
            verdict, msg = L.acquire(
                path, holder(run_id="orchestrator-27715-new", session="cycle-27063",
                             pid=27063),
                "cycle-27063", 27063, SIB, now=NOW, ps=ps_dead,
                procs_with_run_id=probe_gone)
            self.assertEqual(verdict, L.STALE_TAKEN, msg)

    def test_launcher_trap_may_not_free_the_slot_under_a_live_worker(self):
        """`trap release_lock EXIT` срабатывает на смерти ЗАПУСКАТЕЛЯ — и это не повод."""
        with TemporaryDirectory() as td:
            path = Path(td) / "orchestrator_cycle.lock"
            path.mkdir()
            (path / L.HOLDER_FILE).write_text(json.dumps(holder()), encoding="utf-8")
            verdict, msg = L.release(path, "cycle-69075", 69075, LSTART,
                                     procs_with_run_id=probe_alive())
            self.assertEqual(verdict, L.WORKER_STILL_ALIVE, msg)
            self.assertTrue(path.exists(), "замок снят, хотя работа идёт")

    def test_control_the_trap_frees_the_slot_once_the_worker_exited(self):
        """ОБРАТНАЯ сторона: работник вышел ⇒ замок снимается как и прежде."""
        with TemporaryDirectory() as td:
            path = Path(td) / "orchestrator_cycle.lock"
            path.mkdir()
            (path / L.HOLDER_FILE).write_text(json.dumps(holder()), encoding="utf-8")
            verdict, msg = L.release(path, "cycle-69075", 69075, LSTART,
                                     procs_with_run_id=probe_gone)
            self.assertEqual(verdict, L.RELEASED, msg)
            self.assertFalse(path.exists(), msg)

    def test_a_foreign_lock_is_still_never_removed(self):
        """Прежнее свойство цело: чужой замок не снимаем независимо от оси работника."""
        with TemporaryDirectory() as td:
            path = Path(td) / "orchestrator_cycle.lock"
            path.mkdir()
            (path / L.HOLDER_FILE).write_text(json.dumps(holder()), encoding="utf-8")
            verdict, msg = L.release(path, "cycle-27063", 27063,
                                     "Wed Oct 14 12:14:34 2026",
                                     procs_with_run_id=probe_gone)
            self.assertEqual(verdict, L.NOT_MINE, msg)
            self.assertTrue(path.exists(), msg)


class DefaultProbeCase(unittest.TestCase):
    """Прибор по умолчанию: он обязан уметь сказать «НЕ ИЗМЕРЕНО»."""

    def _fake_wrapper(self, td, *, env_readable, found):
        src = Path(td) / "fake_wrapper.py"
        src.write_text(
            "RUN_ID_VAR = 'SPA_RUN_ID'\n"
            "class Snapshot:\n"
            f"    env_readable = {env_readable}\n"
            "    @classmethod\n"
            "    def take(cls):\n"
            "        return cls()\n"
            f"def _inst_run_id(snap, child_pid, run_id):\n    return set({found!r})\n",
            encoding="utf-8")
        return src

    def test_blind_environment_is_not_measured_rather_than_empty(self):
        """Окружение нечитаемо ⇒ `None`, а не «работника нет».

        Порванное звено — прибор ослеп. Выдать слепоту за пустоту значило бы снять замок
        с идущей работы по причине «не сумели спросить» (инв. #17)."""
        with TemporaryDirectory() as td:
            src = self._fake_wrapper(td, env_readable=0, found=[])
            found, why = L.default_run_id_probe(RUN_ID, wrapper_path=src)
            self.assertIsNone(found, why)
            self.assertIn("не измерено", why.lower())

    def test_readable_environment_with_no_match_is_a_measured_zero(self):
        """ОБРАТНАЯ сторона: окружение читаемо и совпадений нет ⇒ измеренный ноль."""
        with TemporaryDirectory() as td:
            src = self._fake_wrapper(td, env_readable=82, found=[])
            found, why = L.default_run_id_probe(RUN_ID, wrapper_path=src)
            self.assertEqual(found, set(), why)

    def test_a_live_match_is_reported_as_alive(self):
        with TemporaryDirectory() as td:
            src = self._fake_wrapper(td, env_readable=82, found=[69661])
            found, why = L.default_run_id_probe(RUN_ID, wrapper_path=src)
            self.assertEqual(found, {69661}, why)

    def test_absent_instrument_is_not_measured(self):
        """Прибора нет вовсе ⇒ третий исход с названной причиной, не ноль и не скип."""
        found, why = L.default_run_id_probe(
            RUN_ID, wrapper_path=Path("/nonexistent/claude_run_with_timeout.py"))
        self.assertIsNone(found, why)
        self.assertIn("НЕ ИЗМЕРЕНА", why)


class WiringCase(unittest.TestCase):
    """Обе стороны обязаны мерить ОДНУ метку — иначе починка существует только на бумаге."""

    def test_launcher_hands_the_same_label_to_the_lock_and_to_the_wrapper(self):
        text = ORCHESTRATOR_SH.read_text(encoding="utf-8")
        self.assertIn('CYCLE_RUN_ID="orchestrator-$$-', text,
                      "метка не рождается в запускателе")
        self.assertEqual(text.count('--run-id "$CYCLE_RUN_ID"'), 2,
                         "метку получают не обе стороны (замок И обёртка)")
        self.assertLess(text.index("CYCLE_RUN_ID="), text.index('--run-id "$CYCLE_RUN_ID"'),
                        "метка используется раньше, чем рождается")

    def test_the_label_is_not_exported_so_the_launcher_does_not_wear_it(self):
        """Экспорт метки вернул бы подмену: жизнь запускателя снова читалась бы как работа."""
        text = ORCHESTRATOR_SH.read_text(encoding="utf-8")
        self.assertNotIn("export CYCLE_RUN_ID", text)
        self.assertNotIn('export SPA_RUN_ID', text)

    def test_the_wrapper_actually_honours_an_external_label(self):
        """Сквозной контроль: переданная метка доезжает до ОКРУЖЕНИЯ работника."""
        wrapper = _load(WRAPPER_PY, "_t864_wrapper")
        with TemporaryDirectory() as td:
            log = Path(td) / "run.log"
            rc = wrapper.run(
                ["python3", "-c", "import os;print('GOT=' + os.environ['SPA_RUN_ID'])"],
                timeout_s=60.0, grace_s=5.0, log_path=str(log), label="probe",
                run_id="orchestrator-test-label")
            self.assertEqual(rc, 0, log.read_text(encoding="utf-8"))
            self.assertIn("GOT=orchestrator-test-label", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""Составной ярлык сессии называет pid открытым текстом — измерять его, а не отказываться.

Карточка `inbox-shag-0a-neizmerimyi-yarlyk-derzhit-kartochku`, живая авария цикла #325
(21.08). Сессия объявила владение под ярлыком `cycle-325-pid40372`, без якоря
(`session_pid`/`session_pid_start`) и без соседней записи, у которой якорь можно занять
(`borrow_durable`). Разбор упирался в `_PID_RE = ^pid(\\d+)$` и печатал «идентификатор сессии
не содержит pid — активность процесса не измерена» — при том, что pid написан в самом ярлыке,
а `ps -p 40372` отвечал пустотой (процесса нет) мгновенно.

Цена этого «не измерено» измерена на том же случае, и она в ДВА конца:

* **шаг 0a** уводил запись в «❓ НЕ ИЗМЕРЕНО» ⇒ объявленные ею пути не разбирались ВООБЩЕ,
  то есть недоставленная работа умершей сессии была невидима ровно тому сторожу, который
  для неё написан;
* **шаг 0b** читал неизмеримую личность как ЖИВОГО держателя карточки и запрещал подъём
  осиротевшей работы — неизмеримость сработала как утверждение «занято».

Каждый тест ниже — положительный контроль над этой аварией либо обратный контроль над её
лечением: fail-CLOSED обязан остаться на настоящей неизвестности (pid'а нет · pid'ов
несколько · `ps` не отработал), иначе починка превратится в угадывание.

Время — ВХОД: все отметки в фикстурах вычисляются от переданного `now`, литеральных дат нет
(правило `.claude/rules/deployment.md`).
"""

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_undelivered_work.py"


def _load():
    spec = importlib.util.spec_from_file_location("cuw_compound", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cuw = _load()

# Ярлык живой аварии #325 — дословно, чтобы тест ломался на ней, а не на её пересказе.
CRASH_LABEL = "cycle-325-pid40372"
CRASH_PID = 40372


def _ps_gone(pid):
    """`ps -p <pid>` про несуществующий процесс: rc=1, пустой вывод."""
    return 1, ""


def _ps_alive(started):
    """`ps -p <pid>` про живой процесс со стартом `started` (datetime → формат lstart).

    `ps` печатает МЕСТНОЕ время без указания зоны, и разбор его таким и читает — поэтому
    фикстура обязана перевести момент в местную зону, а не печатать UTC-часы. Иначе тест
    измеряет сдвиг зоны машины, а не поведение проверки (на +02:00 «старт через 30 минут»
    прочитался бы как «за полтора часа до объявления»).
    """
    def _ps(pid):
        return 0, started.astimezone().strftime("%a %b %e %H:%M:%S %Y")
    return _ps


def _entry(now, label=CRASH_LABEL, **extra):
    """Запись журнала объявлений: ярлык + отметка времени, якоря НЕТ (как у #325)."""
    entry = {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": label,
             "summary": "цикл #325", "files": ["scripts/check_undelivered_work.py"]}
    entry.update(extra)
    return entry


class LabelPidIsMeasured(unittest.TestCase):
    """Положительные контроли: ярлык называет pid ⇒ он измеряется."""

    def setUp(self):
        self.now = datetime(2026, 8, 21, 1, 25, tzinfo=timezone.utc)

    def test_crash_label_yields_the_pid_it_names(self):
        pid, origin, why = cuw.pid_from_label(CRASH_LABEL)
        self.assertEqual(pid, CRASH_PID, why)
        self.assertEqual(origin, "label")
        self.assertEqual(why, "")

    def test_dead_process_named_by_label_is_not_confirmed_not_unknown(self):
        """Авария #325 дословно: до починки здесь было UNKNOWN («не содержит pid»)."""
        state, why = cuw.session_state(_entry(self.now), "", ps=_ps_gone)
        self.assertEqual(state, cuw.NOT_CONFIRMED, why)
        self.assertIn(f"pid{CRASH_PID}", why)

    def test_measurement_names_the_label_as_the_source_of_the_pid(self):
        """Ярлык — не объявленный якорь, и отчёт обязан говорить это вслух."""
        state, why = cuw.session_state(_entry(self.now), "", ps=_ps_gone)
        self.assertIn("назван ярлыком сессии", why)
        self.assertIn(CRASH_LABEL, why)

    def test_live_process_started_before_the_entry_reads_as_active(self):
        started = self.now - timedelta(hours=2)
        state, why = cuw.session_state(_entry(self.now), "", ps=_ps_alive(started))
        self.assertEqual(state, cuw.ACTIVE, why)

    def test_plain_pid_identifier_keeps_its_wording(self):
        """Обратный контроль: точную форму `pid<N>` починка не переодевает в ярлык."""
        state, why = cuw.session_state(_entry(self.now, label="pid40372"), "", ps=_ps_gone)
        self.assertEqual(state, cuw.NOT_CONFIRMED, why)
        self.assertNotIn("ярлык", why)


class ReuseProtectionSurvives(unittest.TestCase):
    """Защита от переиспользованного pid — та же, что у точной формы, и она не снята."""

    def setUp(self):
        self.now = datetime(2026, 8, 21, 1, 25, tzinfo=timezone.utc)

    def test_process_started_after_the_entry_is_another_process(self):
        started = self.now + timedelta(minutes=30)
        state, why = cuw.session_state(_entry(self.now), "", ps=_ps_alive(started))
        self.assertEqual(state, cuw.NOT_CONFIRMED, why)
        self.assertIn("занят ДРУГИМ процессом", why)

    def test_declared_anchor_still_wins_over_the_label(self):
        """Якорь — ОСНОВНОЙ критерий: ярлык не имеет права его подменять.

        Запись несёт `session_pid` живого процесса и ярлык с pid мёртвого. Верный ответ —
        по якорю (ACTIVE), иначе починка тихо понизила бы основной критерий до запасного.
        """
        started = self.now - timedelta(hours=1)
        entry = _entry(self.now, session_pid=999001,
                       session_pid_start=started.astimezone().strftime("%a %b %e %H:%M:%S %Y"))
        state, why = cuw.session_state(entry, "", ps=_ps_alive(started))
        self.assertEqual(state, cuw.ACTIVE, why)
        self.assertIn("999001", why)


class FailClosedStaysClosed(unittest.TestCase):
    """Обратные контроли: настоящая неизвестность обязана остаться «не измерено»."""

    def setUp(self):
        self.now = datetime(2026, 8, 21, 1, 25, tzinfo=timezone.utc)

    def test_label_without_any_pid_is_still_unknown(self):
        pid, _origin, why = cuw.pid_from_label("cycle49")
        self.assertIsNone(pid)
        self.assertIn("не содержит pid", why)
        state, _ = cuw.session_state(_entry(self.now, label="cycle49"), "", ps=_ps_gone)
        self.assertEqual(state, cuw.UNKNOWN)

    def test_two_different_pids_in_one_label_is_a_refusal_not_a_guess(self):
        label = "cycle-pid111-ctl-pid222"
        pid, _origin, why = cuw.pid_from_label(label)
        self.assertIsNone(pid, "который из двух pid — процесс сессии, неизвестно")
        self.assertIn("несколько разных pid", why)
        self.assertIn("pid111", why)
        self.assertIn("pid222", why)
        state, _ = cuw.session_state(_entry(self.now, label=label), "", ps=_ps_gone)
        self.assertEqual(state, cuw.UNKNOWN)

    def test_same_pid_named_twice_is_not_ambiguous(self):
        """Обратный контроль к предыдущему: повтор ОДНОГО pid — не двусмысленность."""
        pid, origin, why = cuw.pid_from_label("cycle-pid777-worktree-pid777")
        self.assertEqual(pid, 777, why)
        self.assertEqual(origin, "label")

    def test_pid_boundary_is_required_so_words_are_not_read_as_pids(self):
        """`rapid7` содержит подстроку `pid7` — но это не pid, и гадать нельзя."""
        pid, _origin, why = cuw.pid_from_label("rapid7")
        self.assertIsNone(pid)
        self.assertIn("не содержит pid", why)

    def test_pid_glued_to_more_characters_is_not_a_pid(self):
        pid, _origin, _why = cuw.pid_from_label("cycle-pid42x")
        self.assertIsNone(pid)

    def test_pid_zero_and_one_are_refused(self):
        """`ps -p 0/1` ответит утвердительно — принять их значило бы выдумать живую сессию."""
        for label in ("cycle-pid0", "cycle-pid1", "pid1"):
            with self.subTest(label=label):
                pid, _origin, why = cuw.pid_from_label(label)
                self.assertIsNone(pid, label)
                self.assertIn("не процесс сессии", why)

    def test_ps_failure_is_unknown_not_death(self):
        """`ps` не отработал ⇒ «не измерено», а не «процесса нет» (fail-CLOSED)."""
        state, why = cuw.session_state(_entry(self.now), "", ps=lambda pid: (127, ""))
        self.assertEqual(state, cuw.UNKNOWN, why)
        self.assertIn("не измерена", why)

    def test_unparsable_start_time_is_unknown(self):
        state, why = cuw.session_state(_entry(self.now), "", ps=lambda pid: (0, "не время"))
        self.assertEqual(state, cuw.UNKNOWN, why)


class SelfSessionSkipIsNotWidened(unittest.TestCase):
    """Пропуск «это мы сами» починка не расширяет: доверенная личность — только явная."""

    def setUp(self):
        self.now = datetime(2026, 8, 21, 1, 25, tzinfo=timezone.utc)

    def test_untrusted_self_identity_is_still_measured_as_someone_elses(self):
        state, why = cuw.session_state(_entry(self.now), CRASH_LABEL,
                                       self_session_trusted=False, ps=_ps_gone)
        self.assertEqual(state, cuw.NOT_CONFIRMED, why)
        self.assertIn("доверенной не является", why)

    def test_trusted_self_identity_is_skipped_as_before(self):
        state, why = cuw.session_state(_entry(self.now), CRASH_LABEL,
                                       self_session_trusted=True, ps=_ps_gone)
        self.assertEqual(state, cuw.ACTIVE, why)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

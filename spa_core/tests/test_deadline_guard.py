"""Срок прогона переживает модуль, который его проглатывает (ADR-676, вторая половина).

Замер 22.10 (Mac, `BatteryHoleTests::test_the_guard_is_lowered_again_after_a_sweep`,
`--timeout=180 --timeout-method=signal`): срок сработал на 188 с ВНУТРИ зова
читателя `acceptance_tree_capability` → `cio_acceptance_rollup.measure` →
`card_acceptance._probe_portfolio_decision_owner_covers_capital`, где
`except BaseException` (card_acceptance.py:4306) вернул «перепись упала»;
одноразовый `ITIMER_REAL` больше не взводился, тест шёл ≈1230 с и ПРОХОДИЛ.

Каждый тест здесь — с контролем: дефект воспроизводится без охраны и
закрывается с ней. Литеральных дат и номеров процесса нет.
"""
from __future__ import annotations

import signal
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import deadline_guard as dg


class Deadline(BaseException):
    """Форма вердикта срока: как `Failed` pytest-timeout, прямой потомок BaseException."""


def _reader_that_swallows_once(total_s):
    """Форма card_acceptance:4306: ОДИН `except BaseException` вокруг части
    работы, после него модуль работает дальше и возвращает значение."""
    try:
        time.sleep(0.3)
    except BaseException:  # noqa: BLE001 — нарочно: это и есть проглатыватель
        pass
    end = time.monotonic() + total_s
    while time.monotonic() < end:
        time.sleep(0.02)
    return "вернулся"


class _OwnAlarm(unittest.TestCase):
    """Свой обработчик SIGALRM на время теста; срок pytest-timeout возвращается."""

    def setUp(self):
        self._prev_handler = signal.getsignal(signal.SIGALRM)
        self._prev_left = signal.getitimer(signal.ITIMER_REAL)[0]
        self._t0 = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, 0)

        def fire(_s, _f):
            raise Deadline("срок")
        signal.signal(signal.SIGALRM, fire)
        self.addCleanup(self._restore)

    def _restore(self):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._prev_handler)
        if self._prev_left > 0:
            left = self._prev_left - (time.monotonic() - self._t0)
            signal.setitimer(signal.ITIMER_REAL, max(left, 0.001))


class TheDeadlineSurvivesAModuleThatSwallowsIt(_OwnAlarm):

    def test_control_without_the_guard_the_swallowed_deadline_is_lost(self):
        """Положительный контроль самого дефекта: без охраны срок теряется,
        модуль досиживает до конца и возвращается как ни в чём не бывало."""
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        start = time.monotonic()
        self.assertEqual(_reader_that_swallows_once(1.0), "вернулся")
        self.assertGreaterEqual(time.monotonic() - start, 1.0)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0.0)

    def test_the_guard_raises_the_same_deadline_promptly(self):
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        start = time.monotonic()
        with self.assertRaises(Deadline):
            with dg.keep_deadline():
                _reader_that_swallows_once(5.0)
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0.0)

    def test_a_module_that_returns_after_swallowing_still_ends_in_the_deadline(self):
        """Модуль поймал срок и ВЕРНУЛСЯ раньше повтора — исход всё равно срок."""
        signal.setitimer(signal.ITIMER_REAL, 0.05)
        with self.assertRaises(Deadline):
            with dg.keep_deadline():
                try:
                    time.sleep(1.0)
                except BaseException:  # noqa: BLE001
                    pass

    def test_a_module_that_replaces_the_verdict_with_its_own_failure(self):
        """Поймал срок и поднял ОБЫЧНОЕ исключение — обходчик прочёл бы «модуль
        упал»; охрана возвращает срок."""
        signal.setitimer(signal.ITIMER_REAL, 0.05)
        with self.assertRaises(Deadline):
            with dg.keep_deadline():
                try:
                    time.sleep(1.0)
                except BaseException as exc:  # noqa: BLE001
                    raise ValueError("перепись упала") from exc

    def test_a_cancelled_outer_timer_is_rearmed_with_what_is_left(self):
        signal.setitimer(signal.ITIMER_REAL, 0.3)
        with dg.keep_deadline():
            signal.setitimer(signal.ITIMER_REAL, 0)   # модуль снял чужой срок
        left = signal.getitimer(signal.ITIMER_REAL)[0]
        self.assertGreater(left, 0.0)
        self.assertLessEqual(left, 0.3)
        with self.assertRaises(Deadline):
            time.sleep(2.0)

    def test_a_handler_left_behind_by_the_module_is_replaced_back(self):
        prev = signal.getsignal(signal.SIGALRM)
        with dg.keep_deadline():
            signal.signal(signal.SIGALRM, signal.SIG_IGN)
        self.assertIs(signal.getsignal(signal.SIGALRM), prev)

    def test_without_a_deadline_the_guard_is_transparent(self):
        handler = signal.getsignal(signal.SIGALRM)
        with dg.keep_deadline():
            value = 42
        self.assertEqual(value, 42)
        self.assertIs(signal.getsignal(signal.SIGALRM), handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0.0)

    def test_a_foreign_failure_passes_through_untouched(self):
        with self.assertRaises(ValueError):
            with dg.keep_deadline():
                raise ValueError("модуль упал")


class TheWalkerKeepsTheDeadlineAtTheCall(_OwnAlarm):
    """Та же дверь у ВЫЗОВА `classify_reader`, в форме замера 22.10."""

    def setUp(self):
        super().setUp()
        from spa_core.monitoring import run_identity_key_price as g16
        self.g16 = g16
        tmp = TemporaryDirectory(prefix="dg_swallow_")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        pkg = root / "stubs"
        pkg.mkdir()
        (pkg / "dgstub_swallower.py").write_text(
            "import time\n"
            "def measure(data_dir, write=False):\n"
            "    try:\n"
            "        time.sleep(0.3)\n"
            "    except BaseException:\n"
            "        pass\n"
            "    end = time.monotonic() + 5.0\n"
            "    while time.monotonic() < end:\n"
            "        time.sleep(0.02)\n"
            "    return {}\n", encoding="utf-8")
        sys.path.insert(0, str(pkg))
        self.addCleanup(lambda: sys.path.remove(str(pkg)))
        self.addCleanup(lambda: sys.modules.pop("dgstub_swallower", None))
        self.stands = {}
        for label in ("s1", "s2", "s3"):
            (root / label / "data").mkdir(parents=True)
            self.stands[label] = root / label

    def test_the_walker_reports_the_deadline_from_a_swallowing_reader(self):
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        start = time.monotonic()
        with self.assertRaises(Deadline):
            self.g16.classify_reader("dgstub_swallower", self.stands)
        self.assertLess(time.monotonic() - start, 3.0)


if __name__ == "__main__":
    unittest.main()


class TheObservedSwallowSiteNowRaises(unittest.TestCase):
    """Корень замера 22.10: card_acceptance._probe_portfolio_decision_owner_covers_capital
    ловил `except BaseException` и проглатывал срок. Срок — пробрасывается; отказ — UNMEASURED."""

    def _probe(self, exc):
        from unittest import mock
        from spa_core.monitoring import card_acceptance as ca
        from spa_core.monitoring import cio_decision_owner_census as census

        def boom(*a, **k):
            raise exc
        with TemporaryDirectory() as root, mock.patch.object(census, "run_census", boom):
            return ca._probe_portfolio_decision_owner_covers_capital(None, data_dir=root, repo_root=root)

    def test_deadline_is_not_swallowed(self):
        with self.assertRaises(Deadline):
            self._probe(Deadline("срок"))

    def test_module_failure_is_still_unmeasured(self):
        outcome, why = self._probe(ValueError("сломано"))
        self.assertIn("перепись упала", why)

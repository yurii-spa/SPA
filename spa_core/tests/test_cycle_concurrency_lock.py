"""Два цикла одновременно писать в трек не должны.

Оба прогона пишут в одни файлы — книгу, кривую капитала, журнал сделок. Побеждает
записавший последним, и результат не «слегка неточный трек», а трек, которому
нельзя верить. Именно он гейтит go-live.

Это не гипотеза: карточка владельца зафиксировала, что два цикла оркестратора уже
работали одновременно — карточки от такого защищены, сам цикл не был.

Замок обязан быть аккуратнее самой гонки. Незанятый замок пропускает; занятый
отказывает; протухший (процесс умер, не сняв) снимается — иначе одна смерть
процесса заблокировала бы трек навсегда, а пропущенный день восстановить нечем.
Сломанная машинерия замка НЕ имеет права остановить цикл: сторож, убивающий то,
что охраняет, вреднее отсутствия сторожа.
"""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.paper_trading import cycle_runner as CR


class TestLockPrimitive(unittest.TestCase):

    def test_free_lock_is_acquired(self):
        with TemporaryDirectory() as t:
            fd = CR._acquire_cycle_lock(Path(t))
            self.assertNotIn(fd, (None, False))
            CR._release_cycle_lock(fd, Path(t))

    def test_held_lock_refuses_the_second_caller(self):
        with TemporaryDirectory() as t:
            d = Path(t)
            first = CR._acquire_cycle_lock(d)
            self.assertIsNone(CR._acquire_cycle_lock(d),
                              "второй цикл обязан получить отказ, пока первый идёт")
            CR._release_cycle_lock(first, d)

    def test_release_frees_it_for_the_next_run(self):
        with TemporaryDirectory() as t:
            d = Path(t)
            first = CR._acquire_cycle_lock(d)
            CR._release_cycle_lock(first, d)
            second = CR._acquire_cycle_lock(d)
            self.assertNotIn(second, (None, False))
            CR._release_cycle_lock(second, d)

    def test_stale_lock_is_taken_over(self):
        """Процесс умер, не сняв замок. Иначе трек блокируется навсегда."""
        with TemporaryDirectory() as t:
            d = Path(t)
            path = d / CR.CYCLE_LOCK_FILE
            # 999999 > PID_MAX (macOS 99998, Linux ≤ 4194304 и по умолчанию 32768):
            # номер НЕДОСТИЖИМ по построению, а не «свободен по удаче» — поэтому
            # `_ps_start` о нём отвечает «не измерено», и замок снимается по
            # возрасту, что и есть предмет этого теста. Причина названа циклом
            # #343: литеральный pid без названной причины — бомба замедленного
            # действия (22.08 номер 98535 из соседней фикстуры ожил).
            path.write_text(json.dumps({"pid": 999999, "ts": "старый"}), encoding="utf-8")
            old = time.time() - (CR.CYCLE_LOCK_STALE_SECONDS + 60)
            os.utime(path, (old, old))
            fd = CR._acquire_cycle_lock(d)
            self.assertNotIn(fd, (None, False), "протухший замок обязан сниматься")
            CR._release_cycle_lock(fd, d)

    def test_a_fresh_lock_is_not_taken_over(self):
        """Обратная сторона: свежий замок трогать нельзя, иначе он бесполезен."""
        with TemporaryDirectory() as t:
            d = Path(t)
            path = d / CR.CYCLE_LOCK_FILE
            path.write_text("{}", encoding="utf-8")
            recent = time.time() - (CR.CYCLE_LOCK_STALE_SECONDS - 60)
            os.utime(path, (recent, recent))
            self.assertIsNone(CR._acquire_cycle_lock(d))

    def test_lock_records_who_holds_it(self):
        """Без pid и времени застрявший замок нечем разобрать."""
        with TemporaryDirectory() as t:
            d = Path(t)
            fd = CR._acquire_cycle_lock(d)
            payload = json.loads((d / CR.CYCLE_LOCK_FILE).read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            self.assertIn("ts", payload)
            CR._release_cycle_lock(fd, d)

    def test_broken_lock_machinery_does_not_stop_the_cycle(self):
        """Сторож, убивающий то, что охраняет, вреднее отсутствия сторожа.

        Возвращается ``False`` — «не проверено», а не ``None`` («занято»), чтобы
        вызывающий не спутал сломанный замок с работающим.
        """
        with TemporaryDirectory() as t:
            with mock.patch.object(CR.os, "open", side_effect=OSError("нет прав")):
                got = CR._acquire_cycle_lock(Path(t))
            self.assertIs(got, False)

    def test_release_tolerates_a_missing_or_absent_lock(self):
        with TemporaryDirectory() as t:
            CR._release_cycle_lock(None, Path(t))
            CR._release_cycle_lock(False, Path(t))


class TestEntrypointBehaviour(unittest.TestCase):

    def test_main_refuses_while_another_cycle_holds_the_lock(self):
        with TemporaryDirectory() as t:
            d = Path(t)
            held = CR._acquire_cycle_lock(d)
            try:
                rc = CR.main(["--data-dir", str(d)])
            finally:
                CR._release_cycle_lock(held, d)
            self.assertEqual(rc, 2, "занятый замок ⇒ отказ с ненулевым кодом")

    def test_dry_run_does_not_take_the_lock(self):
        """Сухой прогон ничего не пишет и не должен мешать живому циклу."""
        with TemporaryDirectory() as t:
            d = Path(t)
            called = {}

            def _inner(argv):
                called["yes"] = True
                return 0

            with mock.patch.object(CR, "_main_inner", _inner):
                CR.main(["--dry-run", "--data-dir", str(d)])
            self.assertTrue(called.get("yes"))
            self.assertFalse((d / CR.CYCLE_LOCK_FILE).exists(),
                             "сухой прогон не должен оставлять замок")

    def test_lock_is_released_even_when_the_cycle_raises(self):
        """Девять точек выхода в run_cycle — поэтому замок живёт в обёртке с finally.

        Незакрытый замок хуже отсутствующего: он заблокирует следующий цикл и
        оставит в треке дыру, восстановить которую нечем.
        """
        with TemporaryDirectory() as t:
            d = Path(t)
            with mock.patch.object(CR, "_main_inner", side_effect=RuntimeError("бум")):
                with self.assertRaises(RuntimeError):
                    CR.main(["--data-dir", str(d)])
            self.assertFalse((d / CR.CYCLE_LOCK_FILE).exists(),
                             "замок обязан сняться и при падении цикла")
            after = CR._acquire_cycle_lock(d)
            self.assertNotIn(after, (None, False), "следующий цикл обязан пройти")
            CR._release_cycle_lock(after, d)


if __name__ == "__main__":
    unittest.main()

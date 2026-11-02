"""Кадр без номера строки при АСИНХРОННОМ подъёме — замер и его контроли (ADR-894).

**Почему это тест, а не прибор в `scripts/`.** Первая редакция цикла #1007 завезла
отдельный скрипт, и два храповика сказали одно и то же с двух сторон:
`test_unwired_scripts_ratchet` (скрипт без вызывающего) и
`test_unwired_guard_modules_ratchet` (сторож с точкой входа, которого никто не зовёт).
Оба правы: инструмент, которого никто не зовёт, есть мёртвый код, и гасить их базой
запрещено (инв. #16). Знание о механизме живёт здесь — в батарее, которая ИСПОЛНЯЕТСЯ
каждым прогоном, а не в скрипте, который однажды запустили руками.

**Что здесь закреплено.** pytest 9.1.1 отрисовывает провал через
``TracebackEntry.lineno`` = ``self._rawentry.tb_lineno - 1``
(``_pytest/_code/code.py:214``). Кадр с ``tb_lineno is None`` роняет САМ pytest
(``TypeError``), шард умирает внутренне, и вердикта лишается ВЕСЬ шард (ADR-892).
Заказ G889 п. 2 предполагал, что такой кадр даёт код, скомпилированный ``compile()``
без файла. **Премиса ложна, и тест ниже закрепляет именно её опровержение.**

Каждый тест — положительный контроль: краснеет на конкретной поломке, а не
подтверждает, что код запускается. Литеральных дат здесь нет вовсе.
"""
# FROZEN-DATE-OK: дат в файле нет — предмет часы не спрашивает.
from __future__ import annotations

import signal
import sys
import types
import unittest
from types import TracebackType
from typing import Callable, List, Optional, Sequence

#: исходы одной пробы
RAISED = "raised"
FINISHED_EARLY = "finished_before_signal"
SELF_FAILED = "work_failed_on_its_own"

#: исходы замера — три, и они обязаны быть РАЗЛИЧИМЫ (инв. #17)
MEASURED_CLEAN = "measured_no_lineless_frame"
FINDING = "lineless_frame_found"
NOT_MEASURED = "not_measured"


class AsyncRaise(BaseException):
    """Та же природа, что ``Failed`` у pytest-timeout: подъём из обработчика.

    Наследник ``BaseException``, а не ``Exception``: проверяемая работа вправе ловить
    ``Exception`` целиком, и тогда проба мерила бы обработчик работы, а не подъём.
    """


def frames_of(tb: Optional[TracebackType]) -> List[dict]:
    """Кадры трейсбека сверху вниз. ``tb_lineno`` берётся КАК ЕСТЬ."""
    out: List[dict] = []
    while tb is not None:
        code = tb.tb_frame.f_code
        out.append({"file": code.co_filename, "name": code.co_name,
                    "tb_lineno": tb.tb_lineno, "lasti": tb.tb_lasti})
        tb = tb.tb_next
    return out


def lineless(frames: Sequence[dict]) -> List[dict]:
    """Кадры БЕЗ номера строки.

    Сравнение именно с ``None``: номер строки 0 — это НОМЕР (его pytest отрисует), а
    отсутствие номера — другое значение, и склеивать их значило бы потерять предмет.
    """
    return [f for f in frames if f["tb_lineno"] is None]


def _handler(signum, frame):            # noqa: ARG001 — подпись задана signal
    raise AsyncRaise(f"signal {signum}")


def sample(work: Callable[[], None], *, fire_after: float,
           signo: int = signal.SIGALRM) -> dict:
    """Одна проба: завести таймер, запустить работу, разобрать трейсбек.

    Таймер и прежний обработчик снимаются во ВСЕХ ветках: невзведённый таймер,
    доживший до следующей пробы, поднял бы исключение в чужой работе и приписал бы
    её кадры этой.
    """
    previous = signal.signal(signo, _handler)
    try:
        signal.setitimer(signal.ITIMER_REAL, fire_after)
        try:
            work()
        except AsyncRaise:
            return {"outcome": RAISED, "frames": frames_of(sys.exc_info()[2])}
        except BaseException as exc:                        # noqa: BLE001
            return {"outcome": SELF_FAILED,
                    "reason": f"работа упала сама: {type(exc).__name__}: {exc}",
                    "frames": frames_of(sys.exc_info()[2])}
        else:
            return {"outcome": FINISHED_EARLY, "frames": []}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signo, previous)


def measure(work: Callable[[], None], *, fire_after: float, samples: int) -> dict:
    """Замер по ``samples`` пробам. Вердикт — по ТРЁМ исходам.

    «Ни одна проба не подняла исключение» — ОТДЕЛЬНЫЙ исход, а не ноль находок.
    Ловушка измерена #1007: первая редакция гоняла работу на пустой сцене, и из 12
    проб подъём случился у ОДНОЙ — «0 находок» было бы ложью об 11 пробах.
    """
    rows = [sample(work, fire_after=fire_after) for _ in range(samples)]
    raised = [r for r in rows if r["outcome"] == RAISED]
    found = [{"sample": i, "lineless": lineless(r["frames"])}
             for i, r in enumerate(rows) if lineless(r["frames"])]
    doc = {
        "samples_requested": samples, "fire_after_s": fire_after,
        "raised": len(raised),
        "finished_early": sum(1 for r in rows if r["outcome"] == FINISHED_EARLY),
        "self_failed": sum(1 for r in rows if r["outcome"] == SELF_FAILED),
        "frames_total": sum(len(r["frames"]) for r in rows),
        "lineless_samples": len(found), "lineless": found,
    }
    if found:
        doc["status"] = FINDING
    elif not raised:
        doc["status"] = NOT_MEASURED
        doc["reason"] = (
            f"ни одна из {samples} проб не подняла исключение: работа кончалась "
            f"раньше сигнала ({fire_after} с). Об асинхронном подъёме этот прогон "
            f"не говорит ничего — это НЕ «0 находок»")
    else:
        doc["status"] = MEASURED_CLEAN
    return doc


def _busy(seconds: float) -> Callable[[], None]:
    """Работа заведомо дольше сигнала — чистый python-цикл, без чужой цели."""
    def run() -> None:
        import time
        end = time.monotonic() + seconds
        x = 0
        while time.monotonic() < end:
            x += 1
    return run


def _traceback_of(fn) -> Optional[TracebackType]:
    """Трейсбек НАСТОЯЩЕГО падения ``fn`` — не выдуманный объект."""
    try:
        fn()
    except BaseException:
        return sys.exc_info()[2]
    raise AssertionError("fn обязана упасть — иначе контроль ничего не проверяет")


def _lineless_traceback() -> Optional[TracebackType]:
    """НАСТОЯЩИЙ кадр с ``tb_lineno is None``.

    Единственный измеренный способ его получить (замер #1007): код-объект с ПУСТОЙ
    таблицей строк. Именно этим контроль отличается от пересказа премисы.
    """
    def victim():
        raise ValueError("boom")
    stripped = victim.__code__.replace(co_linetable=b"")
    naked = types.FunctionType(stripped, {"ValueError": ValueError})
    return _traceback_of(naked)


class LinelessDetection(unittest.TestCase):
    def test_a_real_lineless_frame_is_found(self):
        """Авария, ради которой мера написана: кадр без номера строки."""
        frames = frames_of(_lineless_traceback())
        hits = lineless(frames)
        self.assertTrue(hits, f"кадр без номера строки не найден: {frames}")
        self.assertTrue(all(h["tb_lineno"] is None for h in hits))

    def test_an_ordinary_traceback_has_no_lineless_frame(self):
        """Обратная сторона: обычное падение находкой быть не должно."""
        def victim():
            raise ValueError("boom")
        frames = frames_of(_traceback_of(victim))
        self.assertTrue(frames, "трейсбек обязан иметь кадры")
        self.assertEqual(lineless(frames), [])

    def test_compile_without_a_file_does_NOT_produce_a_lineless_frame(self):
        """ЗАМЕР, опровергающий премису заказа G889 п. 2.

        Если бы ``compile()`` без файла давал кадр без номера строки, мера нашла бы
        его здесь. Она не находит, и номер строки равен 1 — то есть кадр ОТРИСУЕТСЯ,
        и pytest на нём не падает.
        """
        code = compile("raise ValueError('boom')", "<nofile>", "exec")
        frames = frames_of(_traceback_of(lambda: exec(code, {})))
        self.assertEqual(lineless(frames), [])
        nofile = [f for f in frames if f["file"] == "<nofile>"]
        self.assertEqual(len(nofile), 1, frames)
        self.assertEqual(nofile[0]["tb_lineno"], 1)

    def test_lineno_zero_is_a_number_not_an_absence(self):
        """Ноль — НОМЕР. Склеить его с отсутствием значило бы потерять предмет."""
        self.assertEqual(lineless([{"tb_lineno": 0}]), [])
        self.assertEqual(len(lineless([{"tb_lineno": None}])), 1)

    def test_the_pytest_arithmetic_really_breaks_on_a_lineless_frame(self):
        """Шов с ПРИЧИНОЙ обморока: та самая арифметика pytest 9.1.1.

        Без этого теста мера проверяла бы своё понятие «кадр без номера», а не то,
        что именно такой кадр роняет отрисовку.
        """
        hit = lineless(frames_of(_lineless_traceback()))[0]
        with self.assertRaises(TypeError):
            _ = hit["tb_lineno"] - 1          # _pytest/_code/code.py:214
        ordinary = frames_of(_traceback_of(lambda: 1 / 0))[0]
        self.assertEqual(ordinary["tb_lineno"] - 1, ordinary["tb_lineno"] - 1)


@unittest.skipUnless(hasattr(signal, "setitimer"), "платформа без signal.setitimer")
class ThreeOutcomes(unittest.TestCase):
    """Три исхода замера обязаны быть РАЗЛИЧИМЫ (инв. #17)."""

    def test_work_that_ends_before_the_signal_is_NOT_MEASURED(self):
        """Ловушка замера #1007: 11 проб из 12 кончились раньше сигнала."""
        doc = measure(lambda: None, fire_after=30.0, samples=3)
        self.assertEqual(doc["status"], NOT_MEASURED)
        self.assertEqual(doc["raised"], 0)
        self.assertEqual(doc["finished_early"], 3)
        self.assertIn("раньше сигнала", doc["reason"])

    def test_an_async_raise_without_a_lineless_frame_is_MEASURED_CLEAN(self):
        doc = measure(_busy(5.0), fire_after=0.05, samples=2)
        self.assertEqual(doc["status"], MEASURED_CLEAN)
        self.assertGreaterEqual(doc["raised"], 1)
        self.assertEqual(doc["lineless_samples"], 0)
        self.assertIsNone(doc.get("reason"))

    def test_a_clean_measurement_and_an_unmeasured_one_do_not_collapse(self):
        """Сойдись эти два исхода в один — мера перестанет отвечать."""
        clean = measure(_busy(5.0), fire_after=0.05, samples=2)
        unmeasured = measure(lambda: None, fire_after=30.0, samples=2)
        self.assertNotEqual(clean["status"], unmeasured["status"])
        self.assertEqual(clean["lineless_samples"], unmeasured["lineless_samples"])

    def test_the_timer_does_not_outlive_its_own_sample(self):
        """Невзведённый таймер приписал бы чужие кадры следующей пробе."""
        measure(lambda: None, fire_after=0.2, samples=1)
        import time
        time.sleep(0.4)                       # прежний таймер успел бы выстрелить
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0.0)


if __name__ == "__main__":
    unittest.main()

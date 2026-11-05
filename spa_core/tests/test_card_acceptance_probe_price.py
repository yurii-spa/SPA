"""test_card_acceptance_probe_price.py — положительные контроли к ADR-925.

Авария, которую воспроизводит каждый тест: **такт обязательного шага 0-офис
измерили ТРИЖДЫ секундомером снаружи (1022 с · 1086 с · ≥960 с) и трижды
записали «ПРИЧИНА хвоста НЕ ИЗМЕРЕНА»**. Снаружи виден только итог; итог
складывается из проб `card_acceptance.audit()`, и ни одна проба о своей цене не
говорила. Семплирующий зонд цикла #1038 (`faulthandler.dump_traceback_later`,
30 с, все потоки) нашёл хвост внутри `audit()` → `run_probe` — и побочно
ОПРОВЕРГ премису заказа G912 п. 5 «при НУЛЕ подпроцессов»: шесть семплов из
шести стояли в `audit()`, два из них — в `subprocess.run(pytest …)`.

Контроль требуется в ОБЕ стороны (`.claude/rules/acceptance.md` п. 3): дорогая
проба обязана быть НАЗВАНА, дешёвая — попасть в итог и быть названной дешёвой
вслух, а отчёт БЕЗ цены обязан давать третий исход, а не ноль.

Часы здесь — ВХОД, а не окружение (`.claude/rules/deployment.md`): цена в
десятки секунд подставляется подменой `card_acceptance.time`, иначе батарея
стоила бы ровно тех минут, против которых написана. Отдельный тест проверяет,
что НАСТОЯЩИЕ часы доходят до строки — иначе проводка была бы доказана только
на выдуманном клоке.
"""
from __future__ import annotations

import os
import tempfile
import time as _real_time
import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca


def _card(tmp: str, name: str, *, status: str, probe: str) -> str:
    fm = ["type: inbox", f'title: "карточка цены {name}"', f"status: {status}",
          f"acceptance_probe: {probe}"]
    path = os.path.join(tmp, f"{name}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n" + "\n".join(fm) + "\n---\n\n# тело\n")
    return path


class _StepClock:
    """Монотонные часы, шагающие на `step` секунд за каждый ВТОРОЙ вызов.

    `audit()` зовёт `monotonic()` дважды на пробу (до и после). Чётный вызов
    возвращает то же значение, нечётный — сдвинутое: так delta у КАЖДОЙ пробы
    равна `step` ровно, а не накапливается.
    """

    def __init__(self, step: float):
        self.step = step
        self.calls = 0
        self.now = 1000.0

    def monotonic(self) -> float:
        self.calls += 1
        if self.calls % 2 == 0:
            return self.now + self.step
        self.now += 100.0
        return self.now


class TestProbePriceIsRecorded(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        ca.PROBES["_цена_дешёвая"] = lambda _a: (ca.NOT_SATISFIED, "дешёвая")
        ca.PROBES["_цена_со_сном"] = self._sleepy

    def tearDown(self):
        self._tmp.cleanup()
        ca.PROBES.pop("_цена_дешёвая", None)
        ca.PROBES.pop("_цена_со_сном", None)

    @staticmethod
    def _sleepy(_arg):
        _real_time.sleep(0.2)
        return ca.NOT_SATISFIED, "спала 0.2 с"

    def _row(self, res, card):
        rows = [r for r in res["rows"] if r["card"] == card]
        self.assertEqual(len(rows), 1, f"карточка {card} не прочитана: {res['rows']}")
        return rows[0]

    def test_real_clock_reaches_the_row(self):
        """НАСТОЯЩИЕ часы доходят до строки — проводка не только на фейке."""
        _card(self.tmp, "сонная", status="new", probe="_цена_со_сном")
        res = ca.audit(self.tmp)
        row = self._row(res, "сонная")
        self.assertIn("seconds", row, "поля цены нет вовсе — писатель не доехал")
        self.assertIsInstance(row["seconds"], float)
        self.assertGreaterEqual(row["seconds"], 0.2)
        self.assertLess(row["seconds"], 60.0, "цена неправдоподобна — не те часы")

    def test_closed_card_has_no_price_and_that_is_not_zero(self):
        """Инв. #17: пробу не запускали ⇒ None, а не 0.0 («бесплатно»)."""
        _card(self.tmp, "закрытая", status="done", probe="_цена_дешёвая")
        res = ca.audit(self.tmp)
        row = self._row(res, "закрытая")
        self.assertIn("seconds", row)
        self.assertIsNone(row["seconds"])
        self.assertNotEqual(row["seconds"], 0.0)

    def test_closed_card_is_not_in_the_denominator(self):
        """Закрытая карточка не создаёт ни цены, ни «БЕЗ ЦЕНЫ»."""
        _card(self.tmp, "живая", status="new", probe="_цена_дешёвая")
        _card(self.tmp, "сведённая", status="done", probe="_цена_дешёвая")
        clock = _StepClock(10.0)
        with mock.patch.object(ca, "time", clock):
            res = ca.audit(self.tmp)
        text = "\n".join(ca.probe_price_lines(res))
        self.assertIn("суммарно 10.0 с по 1 запущенной", text)
        self.assertNotIn("БЕЗ ЦЕНЫ", text)


class TestProbePriceIsReported(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        ca.PROBES["_цена_предмет"] = lambda _a: (ca.NOT_SATISFIED, "предмет")

    def tearDown(self):
        self._tmp.cleanup()
        ca.PROBES.pop("_цена_предмет", None)

    def _audit_with_price(self, seconds):
        _card(self.tmp, "дорогая", status="in-progress", probe="_цена_предмет")
        clock = _StepClock(seconds)
        with mock.patch.object(ca, "time", clock):
            return ca.audit(self.tmp)

    def test_expensive_probe_is_named_with_card_and_share(self):
        res = self._audit_with_price(120.0)
        text = "\n".join(ca.probe_price_lines(res))
        self.assertIn("⏱ 120.0 с", text)
        self.assertIn("100 % цены проб", text)
        self.assertIn("_цена_предмет", text)
        self.assertIn("дорогая", text)
        self.assertIn("in-progress", text)

    def test_cheap_probe_is_summed_and_called_cheap_aloud(self):
        """Молчание о дешёвой пробе читалось бы как «цены не мерили»."""
        res = self._audit_with_price(1.0)
        text = "\n".join(ca.probe_price_lines(res))
        self.assertIn("суммарно 1.0 с", text)
        self.assertIn("не достигла 30 с", text)
        self.assertNotIn("⏱", text)

    def test_price_lines_reach_report_lines(self):
        """ПРОМАХ-половина: писатель есть, а до читателя строка не доходит."""
        res = self._audit_with_price(120.0)
        self.assertIn("⏱ 120.0 с", "\n".join(ca.report_lines(res)))

    def test_threshold_boundary_is_inclusive(self):
        res = self._audit_with_price(ca.PROBE_PRICE_LOUD_S)
        self.assertIn("⏱", "\n".join(ca.probe_price_lines(res)))


class TestPriceThirdOutcome(unittest.TestCase):
    """Отчёт СТАРОГО ОБРАЗЦА — капкан ADR-248: ключа нет не потому, что замер пуст."""

    def test_rows_without_price_are_unmeasured_never_free(self):
        res = {"rows": [{"card": "к", "status": "new", "open": True,
                         "probe": "_п", "verdict": ca.NOT_SATISFIED, "detail": ""}]}
        text = "\n".join(ca.probe_price_lines(res))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("отчёт старого образца", text)
        self.assertNotIn("суммарно", text)
        self.assertNotIn("0.0 с", text)

    def test_mixed_rows_name_the_blind_count(self):
        res = {"rows": [
            {"card": "с_ценой", "status": "new", "open": True, "probe": "_п",
             "verdict": ca.NOT_SATISFIED, "detail": "", "seconds": 40.0},
            {"card": "без_цены", "status": "new", "open": True, "probe": "_п2",
             "verdict": ca.NOT_SATISFIED, "detail": ""},
        ]}
        text = "\n".join(ca.probe_price_lines(res))
        self.assertIn("суммарно 40.0 с по 1 запущенной", text)
        self.assertIn("БЕЗ ЦЕНЫ ещё 1", text)
        self.assertIn("не ноль", text)
        self.assertIn("⏱ 40.0 с", text)

    def test_no_open_rows_means_no_price_section(self):
        """Нечего мерить — и секции нет: пустая строка «суммарно 0.0» соврала бы."""
        res = {"rows": [{"card": "к", "status": "done", "open": False,
                         "probe": "_п", "verdict": ca.NOT_PROBED,
                         "detail": "", "seconds": None}]}
        self.assertEqual(ca.probe_price_lines(res), [])


if __name__ == "__main__":
    unittest.main()

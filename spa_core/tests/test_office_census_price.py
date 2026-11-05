"""Цена СЕГМЕНТОВ шага 0-офис — контроль в обе стороны (ADR-926, заказ G913 п. 3).

Предмет батареи: шаг 0-офис стои́т ~1120 с (четыре наблюдения подряд: 1022 ·
1086 · ≥960 · 1120,3 с), и три из четырёх замеров снимались СЕКУНДОМЕРОМ
СНАРУЖИ, который по построению не умеет назвать СОСТАВ. Семплирующий зонд
цикла #1038 назвал его за 60 с: **30 из 37 семплов — собственные переписи
шага**. ADR-925 назвал цену ПРОБ (19 % такта) внутри `card_acceptance`; здесь —
цена САМИХ ПЕРЕПИСЕЙ.

Почему это не «тест на словаре, собранном руками» (урок памяти: контроль,
построивший себе словарь, мерит свой словарь, а не проводку). Батарея задаёт
вопросы ДВУМ настоящим дверям:

* `segment_price_lines` — строкам отчёта, и часы ей подаются ВХОДОМ
  (`.claude/rules/deployment.md`, приём №1), так что обе стороны сравнения
  закреплены и тест бессмертен; отдельный тест проверяет, что НАСТОЯЩИЕ
  монотонные часы доходят до строки — «проводка доказана только на фейке» есть
  известный дефект;
* `census_block_census` — ИСХОДНИКУ `main()` живого шага: обёрнута ли часами
  КАЖДАЯ объявленная перепись. Это ПРОМАХ-половина проводки: без неё батарея
  была бы зелена и на файле, где обёртки нет ни одной.

FROZEN-DATE-OK: no-dates — ни одна проверка здесь не судит о календаре:
предмет батареи — монотонные часы и AST исходника.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import consume_office_reports as office  # noqa: E402

_OFFICE_PY = os.path.join(_ROOT, "scripts", "consume_office_reports.py")


class _Clock:
    """Часы как ВХОД: тест двигает их сам и закрепляет обе стороны сравнения."""

    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


_ALL_CLOCKED = {"declared": 2, "clocked": [1, 2], "unclocked": []}


def _joined(lines) -> str:
    return "\n".join(lines)


class ExpensiveSegmentIsNamed(unittest.TestCase):
    """Дорогой сегмент НАЗВАН поимённо, дешёвый — не назван, но посчитан."""

    def setUp(self):
        self.clock = _Clock()
        self.ledger = office.SegmentLedger(clock=self.clock)
        with self.ledger.timed("перепись достижимости"):
            self.clock.advance(330.0)
        with self.ledger.timed("перепись дешёвая"):
            self.clock.advance(0.4)
        self.text = _joined(office.segment_price_lines(self.ledger,
                                                       blocks=_ALL_CLOCKED))

    def test_expensive_segment_is_named_with_its_price(self):
        self.assertIn("перепись достижимости", self.text)
        self.assertIn("330.0 с", self.text)
        self.assertIn("⏱", self.text)

    def test_cheap_segment_is_counted_but_not_named_as_loud(self):
        # Посчитана — итог сложился из двух; не названа — порог не достигнут.
        self.assertIn("330.4 с", self.text)
        self.assertNotIn("⏱ 0.4", self.text)

    def test_share_is_of_the_whole_tact_not_of_named_segments(self):
        # Доля обязана мериться ПОЛНЫМ тактом: доля от суммы названных всегда
        # складывалась бы в 100 % и прятала бы остаток.
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("половина такта"):
            clock.advance(50.0)
        clock.advance(50.0)
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))
        self.assertIn("(50 % такта)", text)


class CheapIsSaidAloud(unittest.TestCase):
    """Второй исход: цена измерена, и ни один сегмент не дорог — ВСЛУХ."""

    def test_all_cheap_is_stated_not_silent(self):
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("перепись дешёвая"):
            clock.advance(1.0)
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))
        self.assertIn("ни один сегмент не достиг", text)
        self.assertIn("1.0 с", text)
        self.assertNotIn("⏱", text)


class ThirdOutcomeIsNotZero(unittest.TestCase):
    """Третий исход (инв. #17) различим и НИКОГДА не выдаётся за ноль."""

    def test_empty_ledger_is_unmeasured_not_free(self):
        text = _joined(office.segment_price_lines(office.SegmentLedger(clock=_Clock()),
                                                  blocks=_ALL_CLOCKED))
        self.assertIn(office._UNMEASURED, text)
        self.assertIn("НЕ «шаг бесплатен»", text)

    def test_unparsed_source_does_not_claim_all_wrapped(self):
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("перепись"):
            clock.advance(1.0)
        text = _joined(office.segment_price_lines(ledger, blocks=None))
        self.assertIn(office._UNMEASURED, text)
        self.assertIn("«все обёрнуты» не утверждается", text)
        self.assertNotIn("часами обёрнуты ВСЕ", text)

    def test_unclocked_census_is_named_by_line_not_silently_dropped(self):
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("перепись"):
            clock.advance(1.0)
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 3, "clocked": [10], "unclocked": [777, 888]}))
        self.assertIn("БЕЗ ЧАСОВ 2", text)
        self.assertIn("стр. 777", text)
        self.assertIn("стр. 888", text)
        self.assertIn("НЕ ноль", text)

    def test_segment_that_never_finished_has_no_price_and_is_counted_apart(self):
        # Сегмент НАЧАЛСЯ и не завершился: `seconds is None`. Считать его
        # бесплатным значило бы утверждать о замере, которого не было.
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("завершённая"):
            clock.advance(2.0)
        ledger.rows.append({"segment": "брошенная", "kind": "census",
                            "seconds": None, "raised": None})
        text = _joined(office.segment_price_lines(ledger, blocks=_ALL_CLOCKED))
        self.assertIn("БЕЗ ЦЕНЫ ещё 1", text)
        self.assertIn(office._UNMEASURED, text)
        self.assertIn("не ноль", text)

    def test_remainder_of_zero_is_said_aloud_not_omitted(self):
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("весь такт"):
            clock.advance(10.0)
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))
        self.assertIn("такт разложен ПОЛНОСТЬЮ", text)

    def test_remainder_above_zero_says_only_part_is_accounted(self):
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("часть такта"):
            clock.advance(10.0)
        clock.advance(90.0)
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))
        self.assertIn("90.0 с", text)
        self.assertIn("ЧАСТЬ такта", text)


class BoundaryIsInclusive(unittest.TestCase):
    """Граница порога — включающая: ровно порог НАЗЫВАЕТСЯ."""

    def _text_for(self, seconds: float) -> str:
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with ledger.timed("перепись"):
            clock.advance(seconds)
        return _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))

    def test_exactly_at_threshold_is_named(self):
        self.assertIn("⏱", self._text_for(office.CENSUS_PRICE_LOUD_S))

    def test_just_below_threshold_is_not_named(self):
        self.assertNotIn("⏱", self._text_for(office.CENSUS_PRICE_LOUD_S - 0.1))


class PriceOfAFallIsStillPrice(unittest.TestCase):
    """Сегмент, упавший с исключением, цену ОТДАЁТ и помечается падением."""

    def test_raising_segment_keeps_its_price_and_reraises(self):
        clock = _Clock()
        ledger = office.SegmentLedger(clock=clock)
        with self.assertRaises(ValueError):
            with ledger.timed("падучая перепись"):
                clock.advance(45.0)
                raise ValueError("бум")
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))
        self.assertIn("45.0 с", text)
        self.assertIn("ПАДЕНИЕ ValueError", text)


class RealClockReachesTheLine(unittest.TestCase):
    """Проводка доказана НЕ только на фейке: настоящие часы доходят до строки."""

    def test_default_clock_is_monotonic_and_produces_a_line(self):
        ledger = office.SegmentLedger()          # часы по умолчанию — настоящие
        with ledger.timed("настоящий сегмент"):
            pass
        text = _joined(office.segment_price_lines(
            ledger, blocks={"declared": 1, "clocked": [1], "unclocked": []}))
        self.assertIn("цена сегментов шага", text)
        self.assertIn("настоящий сегмент", (text + " "
                                            + str(ledger.rows[0]["segment"])))
        self.assertIsInstance(ledger.rows[0]["seconds"], float)
        self.assertGreaterEqual(ledger.rows[0]["seconds"], 0.0)

    def test_monotonic_clock_never_yields_a_negative_price(self):
        # Стенные часы прыгают от NTP, и отрицательная «цена» читалась бы как
        # находка о проводке. Монотонные — выбор, а не случайность.
        ledger = office.SegmentLedger()
        for _ in range(20):
            with ledger.timed("шум"):
                pass
        self.assertTrue(all(r["seconds"] >= 0.0 for r in ledger.rows))


class EveryDeclaredCensusIsClocked(unittest.TestCase):
    """ПРОМАХ-половина: часы доходят до ЖИВОГО `main()`, а не только до теста.

    Без этого класса батарея была бы зелена и на файле, где `with _SEG.timed`
    не стои́т ни разу: словарь, собранный тестом, мерит сам себя.
    """

    def test_live_main_has_every_declared_census_clocked(self):
        got = office.census_block_census(_OFFICE_PY)
        self.assertIsNotNone(got, "исходник шага 0-офис не разобран")
        self.assertEqual(got["unclocked"], [],
                         f"переписи без монотонных часов: {got['unclocked']} "
                         f"(файл {_OFFICE_PY}) — добавь `with _SEG.timed(...)`")
        self.assertGreaterEqual(got["declared"], 10,
                                "переписей объявлено меньше, чем знал замер "
                                "#1038 — проверь, не сменилась ли форма блока")

    def test_main_actually_prints_the_price_lines(self):
        # Отдельное утверждение: мало обернуть — строку надо НАПЕЧАТАТЬ.
        # Вопрос задаётся AST, а не подстрокой (ADR-333): вызов обязан стоять
        # внутри `for`, чьё тело печатает.
        tree = ast.parse(open(_OFFICE_PY, encoding="utf-8").read())
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        printed = False
        for node in ast.walk(main):
            if not isinstance(node, ast.For):
                continue
            call = node.iter
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "segment_price_lines"):
                continue
            printed = any(
                isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
                and isinstance(st.value.func, ast.Name)
                and st.value.func.id == "print"
                for st in node.body)
        self.assertTrue(printed,
                        "`segment_price_lines` в `main()` не напечатан — "
                        "цена измерена и выброшена")

    def test_the_wrapper_is_recognised_by_call_shape_not_by_substring(self):
        # Контроль самой мерки: комментарий или строка со словом `timed`
        # обёрткой НЕ является (ADR-333).
        fake = ast.parse(
            "def main():\n"
            "    # with _SEG.timed('притворная')\n"
            "    timed = 1\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        pass\n")
        main = fake.body[0]
        self.assertFalse(any(office._is_timed_with(st) for st in main.body))

    def test_a_foreign_with_block_is_not_mistaken_for_the_clock(self):
        # Любой `with` обёрткой часов НЕ является: `contextlib.suppress`,
        # `open(...)` и прочие соседи не мерят ничего, и считать их часами
        # значило бы объявить обёрнутым то, что не измеряется.
        fake = ast.parse(
            "def main():\n"
            "    with open('x') as fh:\n"
            "        try:\n"
            "            pass\n"
            "        except Exception:\n"
            "            pass\n")
        main = fake.body[0]
        self.assertFalse(any(office._is_timed_with(st) for st in main.body))

    def test_an_unwrapped_try_is_reported_as_unclocked(self):
        # Положительный контроль мерки в ОБРАТНУЮ сторону: на исходнике, где
        # обёртки нет, мерка обязана КРАСНЕТЬ, а не промолчать.
        import tempfile
        src = ("def main():\n"
               "    try:\n"
               "        pass\n"
               "    except Exception:\n"
               "        pass\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fake_office.py")
            open(path, "w", encoding="utf-8").write(src)
            got = office.census_block_census(path)
        self.assertEqual(got["declared"], 1)
        self.assertEqual(got["unclocked"], [2])
        self.assertEqual(got["clocked"], [])

    def test_a_census_hidden_inside_another_block_is_unclocked_not_invisible(self):
        # Закрытая слепота мерки: первая редакция считала только `try` на
        # ВЕРХНЕМ уровне `main()`, и перепись, завёрнутая в `if True:` вместо
        # часов, выпадала из ОБОИХ списков — ни «обёрнута», ни «без часов».
        # Мутация «заменить обёртку на `if True:`» переживала бы такую мерку.
        import tempfile
        src = ("def main():\n"
               "    if True:\n"
               "        try:\n"
               "            pass\n"
               "        except Exception:\n"
               "            pass\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hidden.py")
            open(path, "w", encoding="utf-8").write(src)
            got = office.census_block_census(path)
        self.assertEqual(got["declared"], 1, "перепись ИСЧЕЗЛА из знаменателя")
        self.assertEqual(got["unclocked"], [3])

    def test_a_census_nested_under_the_wrapper_counts_as_clocked(self):
        # Обратная сторона той же мерки: вложенный `try` ВНУТРИ обёртки обёрнут
        # — иначе мерка краснела бы на верном состоянии и её бы отключили.
        import tempfile
        src = ("def main():\n"
               "    with _SEG.timed('сегмент'):\n"
               "        for x in y:\n"
               "            try:\n"
               "                pass\n"
               "            except Exception:\n"
               "                pass\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested.py")
            open(path, "w", encoding="utf-8").write(src)
            got = office.census_block_census(path)
        self.assertEqual(got["unclocked"], [])
        self.assertEqual(got["clocked"], [4])

    def test_unparsable_source_is_the_third_outcome_not_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.py")
            open(path, "w", encoding="utf-8").write("def main(:\n")
            self.assertIsNone(office.census_block_census(path))

    def test_threshold_is_the_same_word_as_in_card_acceptance(self):
        # «Дорого» в двух отчётах ОДНОГО шага обязано значить одно и то же:
        # разойдись пороги — читатель сравнивал бы разнородные числа.
        from spa_core.monitoring import card_acceptance
        self.assertEqual(office.CENSUS_PRICE_LOUD_S,
                         card_acceptance.PROBE_PRICE_LOUD_S)


if __name__ == "__main__":
    unittest.main()

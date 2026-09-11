"""ADR-309: население записи журнала решений — весь живой набор дня.

Ответ владельца 2026-09-10T06:26Z на карточку
``owner-decision-zapisyvat-li-v-dnevnoe-reshenie-vse-zhiv`` — **Вариант Б**.
До этой правки писатель брал ``current_positions ∪ target_positions``, и на
замере 09.09 держал в руках 18 ставок с живым провенансом, а записывал 6.

Каждый тест ниже — утверждение о ПОВЕДЕНИИ писателя, и у каждого есть мутация,
которая его роняет (таблица — в ADR-309).
"""
# LLM_FORBIDDEN
import unittest

from spa_core.paper_trading.allocation_rationale import build_history_record

# FROZEN-DATE-OK: pass-through-label — build_history_record копирует cycle_date/generated_at
# дословно и часов не спрашивает; «stale» ниже — имя ключа протокола, а не окно свежести.
DOC = {"cycle_date": "2026-01-01", "generated_at": "2026-01-01T00:00:00+00:00",
       "decision_shadow": {}, "params": {}}


def _rec(**kw):
    base = dict(
        apy_pct={"held": 3.0, "tgt": 4.0},
        apy_sources={"held": "live", "tgt": "live"},
        current_positions={"held": 50000.0},
        target_positions={"tgt": 50000.0},
        capital_usd=100000.0,
    )
    base.update(kw)
    return build_history_record(DOC, **base)


class PopulationIsTheLiveSet(unittest.TestCase):
    """Расширение: ставка с живым провенансом попадает в запись вне книг."""

    def test_a_live_rate_outside_both_books_is_recorded(self):
        rec = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "outside": 9.0},
                   apy_sources={"held": "live", "tgt": "live", "outside": "live"})
        self.assertIn("outside", rec["apy_evidenced_pct"])
        self.assertEqual(rec["apy_evidenced_pct"]["outside"], 9.0)

    def test_the_book_is_still_recorded_in_full(self):
        """Расширение НЕ вытесняет книгу — оно её надмножество."""
        rec = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "outside": 9.0},
                   apy_sources={"held": "live", "tgt": "live", "outside": "live"})
        self.assertEqual(rec["apy_evidenced_pct"]["held"], 3.0)
        self.assertEqual(rec["apy_evidenced_pct"]["tgt"], 4.0)

    def test_an_unevidenced_rate_outside_the_book_stays_out(self):
        """Расширение идёт РОВНО на живой провенанс, а не на всю карту ставок.

        Ключ без живого провенанса и вне книг в записи не появляется ни одним
        из двух способов: ни ставкой, ни строкой «ставки нет». Иначе
        ``apy_unevidenced`` (его читает атрибуция блокады) набух бы ключами,
        о которых в тот день никто не принимал решения.
        """
        rec = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "stale": 9.0},
                   apy_sources={"held": "live", "tgt": "live", "stale": "fallback_stale"})
        self.assertNotIn("stale", rec["apy_evidenced_pct"])
        self.assertNotIn("stale", rec["apy_unevidenced"])

    def test_widening_can_never_grow_the_unevidenced_list(self):
        """Свойство по построению — и оно измерено, а не заявлено.

        Население ``apy_unevidenced`` есть население КНИГИ без провенанса.
        Именно на нём стоят `unevidenced_leg_causes` и атрибуция блокады: если
        бы расширение его двигало, правка меняла бы вопросы, которых владелец
        не заказывал.
        """
        narrow = _rec()
        wide = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "a": 1.0, "b": 2.0},
                    apy_sources={"held": "live", "tgt": "live",
                                 "a": "live", "b": "live"})
        self.assertEqual(narrow["apy_unevidenced"], wide["apy_unevidenced"])

    def test_a_book_leg_without_provenance_is_still_named_unevidenced(self):
        """Правило живости внутри книги ADR-309 не ослабил."""
        rec = _rec(apy_sources={"held": "fallback_stale", "tgt": "live"})
        self.assertIn("held", rec["apy_unevidenced"])
        self.assertNotIn("held", rec["apy_evidenced_pct"])


class OnlyPricedRatesJoin(unittest.TestCase):
    """Ключ без ЧИСЛА не входит в население ни одной из двух дверей."""

    def test_live_provenance_without_a_value_stays_out_entirely(self):
        rec = _rec(apy_sources={"held": "live", "tgt": "live", "ghost": "live"})
        self.assertNotIn("ghost", rec["apy_evidenced_pct"])
        self.assertNotIn("ghost", rec["apy_unevidenced"])

    def test_a_none_rate_outside_the_book_stays_out(self):
        rec = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "ghost": None},
                   apy_sources={"held": "live", "tgt": "live", "ghost": "live"})
        self.assertNotIn("ghost", rec["apy_evidenced_pct"])
        self.assertNotIn("ghost", rec["apy_unevidenced"])

    def test_a_nan_rate_outside_the_book_stays_out(self):
        """NaN — не ставка. `json.dump` пишет его литералом, который не читает
        ни один строгий парсер, и запись стала бы нечитаемой молча."""
        rec = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "ghost": float("nan")},
                   apy_sources={"held": "live", "tgt": "live", "ghost": "live"})
        self.assertNotIn("ghost", rec["apy_evidenced_pct"])
        self.assertNotIn("ghost", rec["apy_unevidenced"])

    def test_a_boolean_is_not_a_rate(self):
        rec = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "ghost": True},
                   apy_sources={"held": "live", "tgt": "live", "ghost": "live"})
        self.assertNotIn("ghost", rec["apy_evidenced_pct"])
        self.assertNotIn("ghost", rec["apy_unevidenced"])

    def test_a_book_leg_with_a_live_source_and_no_value_is_unchanged_by_ADR_308(self):
        """Отрицательный контроль на границу правки.

        У ключа КНИГИ дыра «живой провенанс без числа» была и осталась: он не
        попадает ни в один словарь. Правка её не чинит НАМЕРЕННО — чинить её
        значило бы двинуть население `apy_unevidenced` там, где владелец
        ничего не заказывал. Тест держит границу с обеих сторон: если однажды
        поведение книги изменят, он покраснеет и потребует решения, а не
        пройдёт молча.
        """
        rec = _rec(apy_pct={"tgt": 4.0}, apy_sources={"held": "live", "tgt": "live"})
        self.assertNotIn("held", rec["apy_evidenced_pct"])
        self.assertNotIn("held", rec["apy_unevidenced"])


class TheRestOfTheRecordIsUntouched(unittest.TestCase):
    """Правка касается ОДНОГО поля: всё остальное обязано совпасть."""

    def test_every_other_field_is_identical_narrow_vs_wide(self):
        narrow = _rec()
        wide = _rec(apy_pct={"held": 3.0, "tgt": 4.0, "outside": 9.0},
                    apy_sources={"held": "live", "tgt": "live", "outside": "live"})
        moved = {k for k in set(narrow) | set(wide) if narrow.get(k) != wide.get(k)}
        self.assertEqual(moved, {"apy_evidenced_pct"})

    def test_the_input_maps_are_not_mutated(self):
        rates = {"held": 3.0, "tgt": 4.0, "outside": 9.0}
        sources = {"held": "live", "tgt": "live", "outside": "live"}
        _rec(apy_pct=rates, apy_sources=sources)
        self.assertEqual(sorted(rates), ["held", "outside", "tgt"])
        self.assertEqual(sorted(sources), ["held", "outside", "tgt"])

    def test_empty_inputs_do_not_raise(self):
        rec = build_history_record(DOC, apy_pct={}, apy_sources={},
                                   current_positions={}, target_positions={},
                                   capital_usd=0.0)
        self.assertEqual(rec["apy_evidenced_pct"], {})
        self.assertEqual(rec["apy_unevidenced"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""ADR-368 — доля предложенного оборота, зависевшая от ненаблюдённой ноги (заказ #587/G6).

Каждый тест ниже — утверждение о ПОВЕДЕНИИ прибора, и у каждого есть мутация, которая
его роняет (таблица — в ADR-368).

Два класса тестов стоят здесь намеренно и требуют объяснения.

**Первый — подмена модуля судьи.** ``measure`` зовёт судью ПО ССЫЛКЕ НА МОДУЛЬ
(``_ste.evaluate_window``), а не связанным при импорте именем. Тесты ниже подменяют
атрибут модуля — и если бы прибор связал имя на импорте, подмена не подействовала бы и
тест покраснел. То есть эти тесты ОДНОВРЕМЕННО суть положительный контроль на саму
дисциплину ссылки, а не только удобный способ подать вход.

**Второй — сцены, которых в живой истории НЕТ.** Замер 13.09 дал восемь отказов, и все
восемь соразмерны: «$200-случай», ради различения которого заказ и писался, на
наблюдённой истории не встретился ни разу. Ветка ``CRITICAL`` поэтому обязана иметь
СФАБРИКОВАННУЮ сцену — иначе она украшение, которое никогда не видело поломки
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).
"""
# FROZEN-DATE-OK: pass-through-label — все даты ниже суть КЛЮЧИ протокола (`cycle_date`
# записи журнала), а не якоря свежести: прибор ни в одной ветке не спрашивает, давно ли
# был день, и окна свежести у него нет вовсе. `generated_at` проверяется с инъекцией
# `now=`; календарь сдвинуть вердикт ни одного теста не может.
# LLM_FORBIDDEN
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import unobserved_turnover_dependence as utd
from spa_core.paper_trading import shadow_trigger_eval as ste

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _rec(cur, tgt, *, legs=None, turnover=None, date="2026-09-08", **kw):
    """Запись журнала. ``legs=None`` = поля НЕТ (записи до 30.08 его не несут)."""
    rec = {"cycle_date": date, "current_positions": dict(cur),
           "target_positions": dict(tgt)}
    if legs is not None:
        rec["legs"] = [{"protocol": p, "delta_usd": d,
                        "direction": "increase" if d > 0 else "decrease"}
                       for p, d in legs.items()]
    if turnover is not None:
        rec["turnover_usd"] = turnover
    rec.update(kw)
    return rec


def _row(date="2026-09-08", *, turnover=20000.0, unpriced=("pendle",),
         reason=utd.REFUSAL_REASON, outcome="UNCHECKED"):
    return {"cycle_date": date, "turnover_usd": turnover,
            "unpriced_protocols": list(unpriced), "unchecked_reason": reason,
            "outcome": outcome, "trivial": False}


class TheAnswerIsAShareOfTurnover(unittest.TestCase):
    """Ядро: сколько долларов оборота имели конец в ненаблюдённой ноге."""

    def test_the_whole_move_funded_by_exiting_an_unobserved_leg_is_100_pct(self):
        """Сцена заказа «$40 000 из $40 000»: весь ход — выход из ненаблюдённой ноги."""
        rec = _rec({"pendle": 20000.0, "maple": 5263.16, "morpho_blue": 0.0},
                   {"pendle": 0.0, "maple": 20000.0, "morpho_blue": 5263.16})
        day = utd._day(rec, _row(turnover=20000.0, unpriced=("pendle",)))
        self.assertIsNone(day.get("unmeasured_reason"))
        self.assertEqual(day["unpriced_gross_usd"], 20000.0)
        self.assertAlmostEqual(day["share_lower_pct"], 100.0, places=4)
        self.assertTrue(day["exact"])
        self.assertEqual(day["unpriced_side"], "exit_only")

    def test_a_rounding_leg_is_a_different_refusal_and_the_share_says_so(self):
        """Сцена заказа «$200»: та же форма отказа, доля на три порядка меньше.

        Ровно это заказ и просил различить. До прибора оба дня были неотличимы:
        судья пишет обоим ``UNCHECKED`` и одну и ту же причину.
        """
        rec = _rec({"aave_v3": 40000.0, "maple": 200.0, "morpho_blue": 0.0},
                   {"aave_v3": 0.0, "maple": 0.0, "morpho_blue": 40200.0})
        day = utd._day(rec, _row(turnover=40200.0, unpriced=("maple",)))
        self.assertEqual(day["unpriced_gross_usd"], 200.0)
        self.assertLess(day["share_lower_pct"], 1.0)

    def test_the_share_never_exceeds_one_hundred_percent(self):
        """Оборот считает доллар ОДИН раз, а у переезда две ноги.

        Живой замер 2026-09-10: ненаблюдённые ноги несут $40 000, записанный оборот
        $46 842.10, резервное основание ``sum|Δ|/2`` = $35 000. Прибор, поделивший на
        резервное, напечатал бы 114.3 % — заведомую бессмыслицу. Знаменатель берётся
        у судьи, поэтому этого не происходит.
        """
        rec = _rec({"compound_v3": 40000.0, "fluid_usdc": 20000.0, "pendle": 20000.0,
                    "maple": 5263.16, "morpho_blue": 0.0, "morpho_blue_base": 4736.84},
                   {"compound_v3": 37894.74, "maple": 18947.37, "morpho_blue": 9473.68},
                   date="2026-09-10")
        day = utd._day(rec, _row(date="2026-09-10", turnover=46842.10,
                                 unpriced=("fluid_usdc", "pendle")))
        self.assertEqual(day["unpriced_gross_usd"], 40000.0)
        self.assertLessEqual(day["share_lower_pct"], 100.0)
        self.assertLessEqual(day["share_upper_pct"], 100.0)
        self.assertAlmostEqual(day["share_lower_pct"], 85.3933, places=3)

    def test_naive_half_gross_denominator_would_have_exceeded_100_pct(self):
        """Положительный контроль на предыдущий тест: дефект ВОСПРОИЗВОДИМ.

        Без него «доля ≤ 100 %» истинно по построению и проверкой не является.
        """
        deltas = {"compound_v3": -2105.26, "fluid_usdc": -20000.0, "maple": 13684.21,
                  "morpho_blue": 9473.68, "morpho_blue_base": -4736.84,
                  "pendle": -20000.0}
        half_gross = sum(abs(v) for v in deltas.values()) / 2.0
        self.assertAlmostEqual(half_gross, 35000.0, places=2)
        self.assertGreater(40000.0 / half_gross * 100.0, 100.0)


class BoundsNotAFabricatedPoint(unittest.TestCase):
    """Когда точной атрибуции доллара не существует, публикуются ГРАНИЦЫ."""

    def test_legs_on_both_sides_give_an_interval_not_a_point(self):
        rec = _rec({"aave_v3": 35000.0, "morpho_blue": 0.0, "maple": 0.0,
                    "morpho_steakhouse": 0.0},
                   {"aave_v3": 0.0, "morpho_blue": 10000.0, "maple": 5000.0,
                    "morpho_steakhouse": 25000.0}, date="2026-08-16")
        day = utd._day(rec, _row(date="2026-08-16", turnover=40000.0,
                                 unpriced=("aave_v3", "morpho_blue")))
        self.assertEqual(day["unpriced_side"], "both_sides")
        self.assertFalse(day["exact"])
        self.assertAlmostEqual(day["share_lower_pct"], 87.5, places=4)
        self.assertAlmostEqual(day["share_upper_pct"], 100.0, places=4)

    def test_one_sided_legs_make_the_bounds_coincide(self):
        """Совпадение границ — СВОЙСТВО хода, а не приближение, и оно названо."""
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        day = utd._day(rec, _row(turnover=20000.0, unpriced=("pendle",)))
        self.assertTrue(day["exact"])
        self.assertEqual(day["share_lower_pct"], day["share_upper_pct"])

    def test_entry_only_is_distinguished_from_exit_only(self):
        """Сторона хода различается: живой 2026-09-01 — ВХОД, а не выход.

        Прежняя проза ADR-366 предполагала, что ненаблюдённая нога всегда на выходе
        (правило «ненаблюдаемое = 0» гонит капитал из неё). На восьми днях это неверно:
        сторона ИЗМЕРЕНА, а не выведена из правила.
        """
        rec = _rec({"morpho_blue_base": 10000.0, "aave_v3_base": 0.0},
                   {"morpho_blue_base": 0.0, "aave_v3_base": 10000.0},
                   date="2026-09-01")
        day = utd._day(rec, _row(date="2026-09-01", turnover=10000.0,
                                 unpriced=("aave_v3_base",)))
        self.assertEqual(day["unpriced_side"], "entry_only")


class ProportionalityUsesTheJudgesOwnThreshold(unittest.TestCase):
    """Соразмерность мерится порогом СУДЬИ, а не выдуманным процентом."""

    def test_a_leg_below_the_judges_noise_floor_is_disproportionate(self):
        rec = _rec({"aave_v3": 40000.0, "maple": 50.0, "morpho_blue": 0.0},
                   {"aave_v3": 0.0, "maple": 0.0, "morpho_blue": 40050.0})
        day = utd._day(rec, _row(turnover=40050.0, unpriced=("maple",)))
        self.assertLess(day["unpriced_gross_usd"], ste.MATERIAL_TURNOVER_USD)
        self.assertTrue(day["disproportionate"])

    def test_a_material_leg_is_not_disproportionate(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        day = utd._day(rec, _row(turnover=20000.0, unpriced=("pendle",)))
        self.assertFalse(day["disproportionate"])

    def test_the_threshold_travels_with_the_judge_not_a_local_copy(self):
        """Порог берётся ПО ССЫЛКЕ НА МОДУЛЬ: сдвиньте судью — сдвинется вердикт.

        Положительный контроль на дисциплину ссылки. Со связанным при импорте именем
        (или со своей константой) подмена не подействовала бы и тест покраснел.
        """
        rec = _rec({"pendle": 5000.0, "compound_v3": 15000.0, "maple": 0.0},
                   {"pendle": 0.0, "compound_v3": 0.0, "maple": 20000.0})
        row = _row(turnover=20000.0, unpriced=("pendle",))
        # При пороге судьи по умолчанию отказ СОРАЗМЕРЕН: $5 000 много выше $100.
        self.assertFalse(utd._day(rec, row)["disproportionate"])
        saved = ste.MATERIAL_TURNOVER_USD
        try:
            ste.MATERIAL_TURNOVER_USD = 6000.0
            day = utd._day(rec, row)
            self.assertTrue(day["disproportionate"])
            self.assertEqual(day["material_turnover_usd"], 6000.0)
        finally:
            ste.MATERIAL_TURNOVER_USD = saved


class TheThirdOutcomeIsNamedPerDay(unittest.TestCase):
    """«Не измерено» отличимо от нуля и от согласия — у КАЖДОГО дня (инв. #17)."""

    def test_a_refusal_without_a_journal_record_is_unmeasured(self):
        day = utd._day(None, _row())
        self.assertEqual(day["unmeasured_reason"], utd.DAY_NO_RECORD)
        self.assertNotIn("share_lower_pct", day)

    def test_a_row_without_turnover_is_unmeasured_not_zero(self):
        rec = _rec({"pendle": 20000.0}, {"pendle": 0.0})
        row = _row()
        row.pop("turnover_usd")
        self.assertEqual(utd._day(rec, row)["unmeasured_reason"], utd.DAY_NO_TURNOVER)

    def test_a_zero_turnover_refusal_is_unmeasured_not_a_hundred_percent(self):
        """Доли у нуля не существует: это НЕ 0 % и НЕ 100 %."""
        rec = _rec({"pendle": 20000.0}, {"pendle": 0.0})
        day = utd._day(rec, _row(turnover=0.0))
        self.assertEqual(day["unmeasured_reason"], utd.DAY_ZERO_TURNOVER)

    def test_a_refusal_with_no_book_delta_is_a_contradiction_not_a_zero(self):
        rec = _rec({"pendle": 20000.0}, {"pendle": 20000.0})
        self.assertEqual(utd._day(rec, _row())["unmeasured_reason"], utd.DAY_NO_DELTAS)

    def test_a_row_without_the_unpriced_list_is_unmeasured(self):
        row = _row()
        row.pop("unpriced_protocols")
        rec = _rec({"pendle": 20000.0}, {"pendle": 0.0})
        self.assertEqual(utd._day(rec, row)["unmeasured_reason"], utd.DAY_NO_UNPRICED)

    def test_an_unpriced_leg_absent_from_the_book_delta_is_named_not_dropped(self):
        """Молча такая нога понизила бы долю — поэтому она перечисляется."""
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        day = utd._day(rec, _row(turnover=20000.0, unpriced=("pendle", "ghost")))
        self.assertEqual(day["unpriced_not_in_book_delta"], ["ghost"])


class TheDenominatorBasisIsNamed(unittest.TestCase):
    """Оснований знаменателя в дереве больше одного — молча выбирать нельзя."""

    def test_the_recorded_turnover_is_the_outflow_over_legs(self):
        """Живой замер: на всех 12 днях с ``legs`` записанный оборот = их исходящая."""
        legs = {"compound_v3": -2105.26, "fluid_usdc": -12631.58,
                "morpho_blue_base": -7368.42, "pendle": 20000.0}
        rec = _rec({"aave_v3": 263.16, "compound_v3": 2105.26, "fluid_usdc": 12631.58,
                    "morpho_blue_base": 7368.42, "pendle": 0.0},
                   {"aave_v3": 0.0, "compound_v3": 0.0, "fluid_usdc": 0.0,
                    "morpho_blue_base": 0.0, "pendle": 20000.0},
                   legs=legs, turnover=22105.26, date="2026-09-06")
        day = utd._day(rec, _row(date="2026-09-06", turnover=22105.26,
                                 unpriced=("fluid_usdc", "pendle")))
        self.assertIn("outflow_of_legs", day["denominator_basis"]["reproduced_by"])

    def test_an_irreproducible_basis_is_the_third_outcome_not_the_nearest_candidate(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0},
                   turnover=12345.67)
        day = utd._day(rec, _row(turnover=12345.67, unpriced=("pendle",)))
        basis = day["denominator_basis"]
        self.assertFalse(basis["reproducible"])
        self.assertEqual(basis["reproduced_by"], [])
        self.assertIn("НЕ ИЗМЕРЕНО", basis["reason"])

    def test_unbalanced_sides_are_named_not_read_as_lost_money(self):
        """Остаток уехал в кэш — это не ошибка, но названа она обязана быть."""
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 5000.0})
        day = utd._day(rec, _row(turnover=20000.0, unpriced=("pendle",)))
        basis = day["denominator_basis"]
        self.assertFalse(basis["sides_balance"])
        self.assertAlmostEqual(basis["cash_residual_usd"], -15000.0, places=2)


class TheThirdProducerCanLoseALeg(unittest.TestCase):
    """``legs`` и разность книг — ДВА производителя одного хода, и они спорят."""

    def test_a_leg_missing_from_legs_is_measured_and_named(self):
        """Живой 2026-09-06: ``legs`` не несёт ``aave_v3`` −$263.16."""
        legs = {"compound_v3": -2105.26, "fluid_usdc": -12631.58,
                "morpho_blue_base": -7368.42, "pendle": 20000.0}
        rec = _rec({"aave_v3": 263.16, "compound_v3": 2105.26, "fluid_usdc": 12631.58,
                    "morpho_blue_base": 7368.42, "pendle": 0.0},
                   {"aave_v3": 0.0, "compound_v3": 0.0, "fluid_usdc": 0.0,
                    "morpho_blue_base": 0.0, "pendle": 20000.0},
                   legs=legs, turnover=22105.26, date="2026-09-06")
        div = utd._day(rec, _row(date="2026-09-06", turnover=22105.26,
                                 unpriced=("fluid_usdc", "pendle")))["producer_divergence"]
        self.assertTrue(div["measured"])
        self.assertFalse(div["agrees"])
        self.assertEqual(div["missing_from_legs"], ["aave_v3"])
        # Нога НАБЛЮДЁННАЯ ⇒ слепого пятна в тот день не случилось.
        self.assertEqual(div["unpriced_missing_from_legs"], [])

    def test_losing_an_UNPRICED_leg_is_the_blind_spot_the_order_asked_about(self):
        """Сфабриковано намеренно: в живой истории этого НЕТ, и ветка была бы украшением.

        Окажись выпавшая нога ненаблюдённой, читатель ``legs`` доложил бы
        «ненаблюдённых ног не двигали» о дне, отвергнутом целиком.
        """
        legs = {"maple": 20000.0, "compound_v3": -20000.0}
        rec = _rec({"compound_v3": 20000.0, "maple": 0.0, "pendle": 150.0},
                   {"compound_v3": 0.0, "maple": 20000.0, "pendle": 0.0},
                   legs=legs, turnover=20000.0)
        div = utd._day(rec, _row(turnover=20000.0,
                                 unpriced=("pendle",)))["producer_divergence"]
        self.assertEqual(div["unpriced_missing_from_legs"], ["pendle"])

    def test_a_record_without_legs_gives_an_UNSTARTED_check_not_agreement(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        div = utd._day(rec, _row(turnover=20000.0,
                                 unpriced=("pendle",)))["producer_divergence"]
        self.assertFalse(div["measured"])
        self.assertNotIn("agrees", div)
        self.assertIn("не состоялась", div["reason"])

    def test_an_amount_disagreement_is_caught_too(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0},
                   legs={"pendle": -19000.0, "maple": 20000.0})
        div = utd._day(rec, _row(turnover=20000.0,
                                 unpriced=("pendle",)))["producer_divergence"]
        self.assertEqual(div["amount_disagreements"], ["pendle"])


# ──────────────────────────────────────────────────────────────────────────
# measure(): население, вердикт, третий исход
# ──────────────────────────────────────────────────────────────────────────
class _Judge:
    """Подменённый канонический судья. Подмена действует ТОЛЬКО при зове по ссылке."""

    def __init__(self, rows, history, scored=("2026-08-06",), raise_on_window=False):
        self.rows, self.history = rows, history
        self.scored, self.raise_on_window = scored, raise_on_window

    def install(self, case):
        saved = (ste.evaluate_window, ste.load_history, ste.scored_days)

        def window(_dd, **_kw):
            if self.raise_on_window:
                raise RuntimeError("судья отказал")
            return {"per_verdict": self.rows}

        ste.evaluate_window = window
        ste.load_history = lambda _dd, *a, **k: (self.history, 0)
        ste.scored_days = lambda _dd, **k: (set(self.scored) if self.scored is not None
                                            else None)
        case.addCleanup(lambda: (setattr(ste, "evaluate_window", saved[0]),
                                 setattr(ste, "load_history", saved[1]),
                                 setattr(ste, "scored_days", saved[2])))


class MeasureAccountsForEveryRefusal(unittest.TestCase):

    def _measure(self, rows, history, **kw):
        _Judge(rows, history, **kw).install(self)
        return utd.measure(Path("/nonexistent"), now=NOW)

    def test_the_accounting_identity_closes(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        doc = self._measure([_row(), _row(date="2026-09-09")], [rec])
        pop = doc["population"]
        self.assertTrue(pop["accounting_identity_holds"])
        self.assertEqual(pop["measured_days"] + len(pop["unmeasured_days"]),
                         pop["refusals_on_unpriced_legs"])
        # Второй отказ записи не имеет ⇒ он НАЗВАН, а не потерян.
        self.assertEqual([u["cycle_date"] for u in pop["unmeasured_days"]],
                         ["2026-09-09"])

    def test_no_refusals_is_a_measured_zero_not_silence(self):
        doc = self._measure([_row(reason=None, outcome="hit")], [])
        self.assertEqual(doc["status"], utd.STATUS_OK)
        self.assertEqual(doc["answer"]["refusals"], 0)
        self.assertTrue(any("измеренный НОЛЬ" in f for f in doc["findings"]))

    def test_other_unchecked_reasons_are_kept_out_of_the_population(self):
        """«Нет форвардных дней» — не слепота входов; смешать значило бы разбавить предмет."""
        doc = self._measure([_row(date="2026-09-13", reason="no_forward_data",
                                  unpriced=())], [])
        self.assertEqual(doc["population"]["refusals_on_unpriced_legs"], 0)
        self.assertEqual(doc["population"]["other_unchecked_days"], ["2026-09-13"])

    def test_a_disproportionate_refusal_drives_the_verdict_CRITICAL(self):
        rec = _rec({"aave_v3": 40000.0, "maple": 50.0, "morpho_blue": 0.0},
                   {"aave_v3": 0.0, "maple": 0.0, "morpho_blue": 40050.0})
        doc = self._measure([_row(turnover=40050.0, unpriced=("maple",))], [rec])
        self.assertEqual(doc["status"], utd.STATUS_CRITICAL)
        self.assertTrue(any(f.startswith("[CRITICAL]") and "НЕСОРАЗМЕРЕН" in f
                            for f in doc["findings"]))

    def test_a_blind_spot_in_legs_drives_the_verdict_CRITICAL(self):
        rec = _rec({"compound_v3": 20000.0, "maple": 0.0, "pendle": 150.0},
                   {"compound_v3": 0.0, "maple": 20000.0, "pendle": 0.0},
                   legs={"maple": 20000.0, "compound_v3": -20000.0}, turnover=20000.0)
        doc = self._measure([_row(turnover=20000.0, unpriced=("pendle",))], [rec])
        self.assertEqual(doc["status"], utd.STATUS_CRITICAL)
        self.assertTrue(any("`legs` НЕ несёт отвергающую ногу" in f
                            for f in doc["findings"]))

    def test_a_proportionate_refusal_says_so_out_loud(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0},
                   legs={"pendle": -20000.0, "maple": 20000.0}, turnover=20000.0)
        doc = self._measure([_row(turnover=20000.0, unpriced=("pendle",))], [rec])
        self.assertEqual(doc["status"], utd.STATUS_OK)
        self.assertTrue(any("несоразмерных отказов НЕТ" in f for f in doc["findings"]))

    def test_a_refusing_judge_is_UNMEASURED_not_an_empty_answer(self):
        doc = self._measure([], [], raise_on_window=True)
        self.assertEqual(doc["status"], utd.STATUS_UNMEASURED)
        self.assertIsNone(doc["answer"])
        self.assertTrue(any(f.startswith("[НЕ ИЗМЕРЕНО]") for f in doc["findings"]))

    def test_a_report_without_per_verdict_is_UNMEASURED_not_zero_refusals(self):
        saved = ste.evaluate_window
        ste.evaluate_window = lambda _dd, **k: {"hit_rate": 1.0}
        self.addCleanup(lambda: setattr(ste, "evaluate_window", saved))
        doc = utd.measure(Path("/nonexistent"), now=NOW)
        self.assertEqual(doc["status"], utd.STATUS_UNMEASURED)
        self.assertIn("пустым списком", doc["unmeasured_reason"])

    def test_a_refused_denominator_is_named_not_substituted_by_an_empty_set(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        doc = self._measure([_row()], [rec], scored=None)
        self.assertFalse(doc["denominator"]["measured"])
        self.assertIsNone(doc["denominator"]["days"])
        self.assertTrue(any("знаменатель hit_rate" in f and "[НЕ ИЗМЕРЕНО]" in f
                            for f in doc["findings"]))

    def test_every_measured_day_carries_both_bounds(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        doc = self._measure([_row()], [rec])
        for day in doc["per_day"]:
            self.assertIn("share_lower_pct", day)
            self.assertIn("share_upper_pct", day)
            self.assertLessEqual(day["share_lower_pct"], day["share_upper_pct"])


class TheTwoAxesAreNotConfused(unittest.TestCase):
    """Три дня соседа и восемь отказов судьи — разные вопросы, оба названы."""

    def test_the_neighbours_count_is_reported_beside_our_own(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        _Judge([_row()], [rec]).install(self)
        saved = utd._cross_axis
        utd._cross_axis = lambda _dd: {"measured": True, "reason": None,
                                       "own_capital_degraded_days": ["2026-09-08",
                                                                     "2026-09-09"]}
        self.addCleanup(lambda: setattr(utd, "_cross_axis", saved))
        doc = utd.measure(Path("/nonexistent"), now=NOW)
        line = [f for f in doc["findings"] if f.startswith("[ОСИ]")]
        self.assertEqual(len(line), 1)
        self.assertIn("пересечение 1", line[0])

    def test_the_REAL_cross_axis_reads_a_silent_neighbour_as_unmeasured(self):
        """Тест БЕЗ подмены `_cross_axis`: иначе разбор его входа не проверен вовсе.

        Батарея #589 нашла это сама: мутация `raw = doc.get("degraded_days") or []`
        ПЕРЕЖИЛА первую редакцию набора, потому что оба теста осей подменяли
        `_cross_axis` целиком — инъекция пробы прятала РАЗБОР её входа. Здесь
        подменяется сосед, а не прибор, и разбор идёт настоящий.
        """
        from spa_core.monitoring import capital_observability_history as coh
        saved = coh.measure
        self.addCleanup(lambda: setattr(coh, "measure", saved))

        coh.measure = lambda _dd, **k: {"status": "OK"}          # ключа НЕТ
        silent = utd._cross_axis(Path("/nonexistent"))
        self.assertFalse(silent["measured"])
        self.assertNotIn("own_capital_degraded_days", silent)
        self.assertIn("пустым списком", silent["reason"])

        coh.measure = lambda _dd, **k: {"degraded_days": "2026-09-08"}   # не тот род
        junk = utd._cross_axis(Path("/nonexistent"))
        self.assertFalse(junk["measured"])

        coh.measure = lambda _dd, **k: {"degraded_days": []}      # ИЗМЕРЕННЫЙ ноль
        empty = utd._cross_axis(Path("/nonexistent"))
        self.assertTrue(empty["measured"])
        self.assertEqual(empty["own_capital_degraded_days"], [])

    def test_a_refusing_neighbour_is_UNMEASURED_with_the_cause_named(self):
        from spa_core.monitoring import capital_observability_history as coh
        saved = coh.measure
        self.addCleanup(lambda: setattr(coh, "measure", saved))
        coh.measure = lambda _dd, **k: (_ for _ in ()).throw(RuntimeError("сосед упал"))
        out = utd._cross_axis(Path("/nonexistent"))
        self.assertFalse(out["measured"])
        self.assertIn("сосед упал", out["reason"])

    def test_a_silent_neighbour_is_UNMEASURED_not_zero_degraded_days(self):
        rec = _rec({"pendle": 20000.0, "maple": 0.0}, {"pendle": 0.0, "maple": 20000.0})
        _Judge([_row()], [rec]).install(self)
        saved = utd._cross_axis
        utd._cross_axis = lambda _dd: {"measured": False, "reason": "сосед не ответил"}
        self.addCleanup(lambda: setattr(utd, "_cross_axis", saved))
        doc = utd.measure(Path("/nonexistent"), now=NOW)
        self.assertTrue(any("сверка осей" in f and "[НЕ ИЗМЕРЕНО]" in f
                            for f in doc["findings"]))


class TheReportRefusesToSubstituteZeroForAbsence(unittest.TestCase):
    """Отчёт старого образца не имеет права молчать так же, как здоровый (инв. #17)."""

    def test_a_document_without_population_reads_as_unmeasured_not_as_zero(self):
        lines = utd.format_report({"status": "OK", "findings": []})
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in ln for ln in lines))

    def test_findings_of_the_wrong_kind_do_not_crash_the_report(self):
        lines = utd.format_report({"status": "OK", "population": {}, "findings": "oops"})
        self.assertTrue(lines)

    def test_a_population_of_the_WRONG_KIND_reads_as_unmeasured(self):
        """Мусор в поле не есть замер — и ТОЛЬКО здесь `observed(kind=)` отличим от `or {}`.

        Батарея #589 нашла это сама: мутация `pop = doc.get("population") or {}`
        ПЕРЕЖИЛА первую редакцию набора. На пропавшем ключе она поведенчески
        эквивалентна (оба дают `None` у `.get`), и разойтись они могут ровно на поле
        не того рода: `or {}` отдаст список, и отчёт упадёт на `.get` — то есть
        «не измерено» превратится в аварию. Сцена без этого теста была недостижима.
        """
        for junk in ([], "39", 39, ["2026-09-08"]):
            with self.subTest(junk=junk):
                lines = utd.format_report({"status": "OK", "population": junk,
                                           "findings": []})
                self.assertTrue(any("НЕ ИЗМЕРЕНО" in ln for ln in lines))


class AbsenceIsNeverCollapsedIntoEmptiness(unittest.TestCase):
    """Три места, где `… or []` склеило бы «не измерено» с «измерено и пусто».

    Найдены не глазами, а храповиком класса (`test_absent_observation_ratchet`), который
    покраснел на три новых члена. Чинится ПРЕДМЕТ, не храповик (инв. #16), и каждый фикс
    закрепляется здесь — иначе следующая правка вернёт подстановку молча.
    """

    def test_a_population_without_the_unmeasured_list_says_so(self):
        doc = {"status": "OK", "population": {"refusals_on_unpriced_legs": 1},
               "answer": {}, "cross_axis": {"measured": False, "reason": "x"}}
        out = utd._findings(doc)
        self.assertTrue(any("`unmeasured_days`" in f and "НЕ ИЗМЕРЕНО" in f for f in out))

    def test_an_empty_unmeasured_list_is_a_measured_zero_and_stays_quiet(self):
        doc = {"status": "OK", "population": {"refusals_on_unpriced_legs": 1,
                                             "unmeasured_days": []},
               "answer": {}, "cross_axis": {"measured": False, "reason": "x"}}
        out = utd._findings(doc)
        self.assertFalse(any("`unmeasured_days`" in f for f in out))

    def test_a_neighbour_claiming_measured_without_the_list_is_unmeasured(self):
        """`measured: True` без перечня — сверка НЕСОСТОЯВШАЯСЯ, а не «ноль дней»."""
        doc = {"status": "OK", "population": {"unmeasured_days": []}, "answer": {},
               "cross_axis": {"measured": True}}
        out = utd._findings(doc)
        self.assertTrue(any("перечня" in f and "НЕ ИЗМЕРЕНО" in f for f in out))
        self.assertFalse(any(f.startswith("[ОСИ]") for f in out))

    def test_an_empty_neighbour_list_is_a_measured_zero_and_prints_the_axes(self):
        doc = {"status": "OK", "population": {"unmeasured_days": []}, "answer": {},
               "cross_axis": {"measured": True, "own_capital_degraded_days": []}}
        out = utd._findings(doc)
        self.assertTrue(any(f.startswith("[ОСИ]") for f in out))

    def test_a_divergence_without_the_amount_names_the_absence(self):
        day = {"cycle_date": "2026-09-06", "turnover_usd": 1.0,
               "unpriced_protocols": ["pendle"], "unpriced_gross_usd": 1.0,
               "share_lower_pct": 100.0, "share_upper_pct": 100.0, "exact": True,
               "unpriced_side": "exit_only",
               "producer_divergence": {"measured": True, "agrees": False,
                                       "unpriced_missing_from_legs": [],
                                       "amount_disagreements": []},
               "denominator_basis": {"reproducible": True, "reproduced_by": ["x"]}}
        doc = {"status": "WARNING", "population": {"unmeasured_days": []},
               "answer": {"measured": True, "refusals_measured": 1,
                          "proposed_turnover_usd": 1.0, "unobserved_dependent_usd": 1.0,
                          "share_lower_pct": 100.0, "min_day_share_lower_pct": 100.0,
                          "max_day_share_lower_pct": 100.0, "days_exact": 1,
                          "disproportionate_days": []},
               "per_day": [day], "cross_axis": {"measured": False, "reason": "x"}}
        out = utd._findings(doc)
        self.assertTrue(any("СУММА НЕ ИЗМЕРЕНА" in f for f in out))


class WiringExistsAtBirth(unittest.TestCase):
    """Прибор без потребителя — источник, который никто не читает (ADR-209)."""

    ARTIFACT = f"data/{utd.OUTPUT_FILENAME}"
    MODULE = "spa_core/monitoring/unobserved_turnover_dependence.py"

    def test_findings_bridge_knows_the_artifact_and_the_stage(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn(self.ARTIFACT, fb.PRODUCES)
        self.assertIn("unobserved_turnover_dependence", fb.CENSUS_STAGE)
        self.assertEqual(
            fb.CENSUS_PRODUCT["unobserved_turnover_dependence"]["artifact"],
            self.ARTIFACT)
        self.assertEqual(
            fb.CENSUS_PRODUCT["unobserved_turnover_dependence"]["module"], self.MODULE)

    def test_the_office_step_reads_the_artifact_and_names_its_producer(self):
        import scripts.consume_office_reports as office
        name = utd.OUTPUT_FILENAME
        self.assertIn(name, office._READ_SCHEMA)
        self.assertEqual(office._PRODUCER[name], self.MODULE)

    def test_the_office_step_actually_RENDERS_our_lines(self):
        """Ключ в словаре — ещё не отчёт: ветка форматтера обязана быть ДОСТИГНУТА.

        Соседний тест проверяет, что имя артефакта есть в `_READ_SCHEMA` и `_PRODUCER`,
        и обе эти записи можно иметь при `elif`, которого нет — тогда шаг офиса
        напечатает generic-дамп и промолчит о предмете. Здесь зовётся настоящий
        `_summarize_json`, и требуется наша строка.
        """
        import scripts.consume_office_reports as office
        doc = utd.measure(Path("/nonexistent"))      # UNMEASURED — но форма та же
        lines = office._summarize_json(self.ARTIFACT, doc)
        self.assertTrue(any("заказ #587/G6" in ln for ln in lines),
                        "ветка форматтера шага 0-офис НЕ достигнута")

    def test_the_manifest_carries_BOTH_entries_not_only_the_artifact(self):
        """Парити-тест краснеет только на ВТОРОЙ записи — паспорте агента."""
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        arts = [a for a in manifest["artifacts"] if a.get("path") == self.ARTIFACT]
        self.assertEqual(len(arts), 1, "запись artifacts[] отсутствует или дублируется")
        producer = arts[0]["producer"]
        # ВТОРАЯ запись — паспорт агента. Парити-тест краснеет только на ней, поэтому
        # проверяется она отдельно и структурно, а не подстрокой по всему документу:
        # подстрока зеленела бы от первой записи и о второй молчала.
        agent = [a for a in manifest["agents"] if a.get("label") == producer]
        self.assertEqual(len(agent), 1, f"производитель {producer} не найден среди агентов")
        self.assertIn(self.ARTIFACT,
                      [e.get("artifact") for e in agent[0].get("produces") or []])

    def test_the_reader_population_of_the_journal_key_includes_us(self):
        """Прибор читает журнал решений ⇒ обязан быть в переписи потребителей."""
        from spa_core.monitoring import decision_journal_coverage as djc
        mods = {e["module"] for e in djc.READERS}
        self.assertIn("spa_core.monitoring.unobserved_turnover_dependence", mods)


class HouseRules(unittest.TestCase):

    def test_no_llm_and_stdlib_only(self):
        src = Path(utd.__file__).read_text(encoding="utf-8")
        self.assertIn("LLM_FORBIDDEN", src)
        for banned in ("import requests", "import numpy", "import pandas",
                       "import anthropic", "import openai"):
            self.assertNotIn(banned, src)

    def test_the_artifact_states_what_it_does_not_prove(self):
        """Границы утверждения едут В АРТЕФАКТ: читатель отчёта шапку не открывает."""
        self.assertGreaterEqual(len(utd.WHAT_IT_DOES_NOT_PROVE), 5)
        joined = " ".join(utd.WHAT_IT_DOES_NOT_PROVE)
        self.assertIn("hit_rate_selection_bias", joined)
        self.assertIn("unevidenced_leg_causes", joined)
        self.assertIn("capital_observability_history", joined)

    def test_run_counts_unchecked_separately_from_zero(self):
        _Judge([], [], raise_on_window=True).install(self)
        doc = utd.run(root="/nonexistent", write=False, now=NOW)
        self.assertEqual(doc["overall"], utd.STATUS_UNMEASURED)
        # ТОЧНОЕ число, а не `>= 1`. Батарея #589 нашла это сама: при `>= 1` слагаемое
        # «статус UNMEASURED» не проверено вовсе — порог добирался ВТОРЫМ слагаемым
        # (строкой находки), и мутация, обнулившая первое, оставалась зелёной.
        self.assertEqual(len(doc["findings"]), 1)
        self.assertEqual(doc["counts"]["unchecked"], 2,
                         "1 за статус UNMEASURED + 1 за строку [НЕ ИЗМЕРЕНО]")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

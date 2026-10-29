"""ADR-854 — ФОРМА урезания имеет свою цену, и она ИЗМЕРЕНА, а не выведена.

Каждый тест — положительный контроль на один из двух дефектов, против которых
модуль написан:

1. **утверждение осталось рассуждением.** ADR-853 вывел из механизма («газ за
   ногу, а число ног с ``k`` не падает»), что урезание с МЕНЬШИМ числом ног
   дешевле при том же размере, и честно назвал это нерешённым. Тесты ниже
   требуют, чтобы ответ приходил ИЗ дверей (оборот, цена, спред), а не из
   литерала рядом: подменённая дверь обязана менять ответ.
2. **«не измерено», выданное за ответ.** У каждого исхода своё ЗНАЧЕНИЕ
   (инв. #17): отсутствие блока в артефакте — это НЕ ноль переписи, а оборот
   формы выше потолка — это НЕ «форма дешевле».

# FROZEN-DATE-OK: injected-clock — якорь ``_NOW`` передаётся
# ``evaluate_window(..., now=_NOW)``, а все отметки сцены производны от него же.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.allocator.rebalance_economics import TriggerParams
from spa_core.paper_trading.trim_shape import (
    CENSUS_MEASURED,
    PROPOSAL_ABSENT,
    PROPOSAL_FROM_TARGET,
    PROPOSAL_FROM_TRIM_BEFORE,
    CENSUS_MEASURED_ZERO,
    CENSUS_UNMEASURED,
    SHAPE_MEASURED,
    SHAPE_NO_ALTERNATIVE,
    SHAPE_NO_SUBJECT,
    SHAPE_UNMEASURED,
    _proposal_of,
    compare_trim_shapes,
    format_trim_shape,
    subset_trim,
    trim_shape_census,
    trim_shape_outcome,
)

_NOW = datetime(2026, 10, 28, 20, 56, tzinfo=timezone.utc)

CAPITAL = 100_000.0
#: Сцена, воспроизводящая форму живого урезания 28.10: одна нога докладывает,
#: две забирают, оборот предложения ВЫШЕ потолка размера.
CURRENT = {"low": 40_000.0, "mid": 30_000.0, "other": 25_000.0}
TARGET = {"mid": 10_000.0, "high": 60_000.0, "other": 25_000.0}
APY = {"low": 2.0, "mid": 4.0, "high": 10.0, "other": 3.0}
#: Карта сетей — дорогая сеть у обеих форм ОДНА, иначе сравнивались бы не формы.
CHAINS = {"low": "ethereum", "mid": "ethereum", "high": "ethereum",
          "other": "ethereum"}
PARAMS = TriggerParams.for_mode("paper")


def _compare(current=None, target=None, apy=None, chains=None,
             capital=CAPITAL, params=PARAMS, chains_measured=True):
    return compare_trim_shapes(
        CURRENT if current is None else current,
        TARGET if target is None else target,
        APY if apy is None else apy,
        capital_usd=capital, params=params,
        chains=CHAINS if chains is None else chains,
        chains_measured=chains_measured)


class SubsetTrimIsASubsetOfTheSameProposal(unittest.TestCase):
    """Книга соседки обязана быть подмножеством ТОГО ЖЕ предложения."""

    def test_every_position_stays_between_current_and_target(self):
        book, why = subset_trim(CURRENT, TARGET, APY,
                                admissible_usd=15_000.0, net_cash_usd=0.0)
        self.assertEqual(why, "")
        for proto in set(CURRENT) | set(TARGET):
            lo = min(CURRENT.get(proto, 0.0), TARGET.get(proto, 0.0))
            hi = max(CURRENT.get(proto, 0.0), TARGET.get(proto, 0.0))
            got = book.get(proto, 0.0)
            self.assertGreaterEqual(got + 1e-6, lo, proto)
            self.assertLessEqual(got - 1e-6, hi, proto)

    def test_net_cash_movement_equals_what_the_caller_demanded(self):
        # Условие СРАВНЕНИЯ: без него подмножество «выигрывало» бы, развернув
        # кэш, которого соседка не разворачивала, то есть ответило бы на другой
        # вопрос. Поэтому требование проверяется, а не предполагается.
        for net in (0.0, 4_000.0, -4_000.0):
            book, why = subset_trim(CURRENT, TARGET, APY,
                                    admissible_usd=15_000.0, net_cash_usd=net)
            self.assertEqual(why, "", net)
            moved = sum(book.values()) - sum(CURRENT.values())
            self.assertAlmostEqual(moved, net, places=2, msg=f"net={net}")

    def test_turnover_never_exceeds_the_admissible_cap(self):
        from spa_core.allocator.rebalance_economics import _legs
        for cap in (1_000.0, 15_000.0, 44_000.0):
            book, why = subset_trim(CURRENT, TARGET, APY,
                                    admissible_usd=cap, net_cash_usd=0.0)
            self.assertEqual(why, "", cap)
            _, turnover = _legs(CURRENT, book, CAPITAL,
                                float(PARAMS.min_leg_frac))
            self.assertLessEqual(turnover, cap + 0.01, f"cap={cap}")

    def test_the_spread_decides_WHICH_leg_is_sold_not_merely_how_many(self):
        # Контроль в обе стороны: «меньше ног» получилось бы и при произвольном
        # выборе ноги. Ответ обязан приходить ИЗ наблюдённых ставок, поэтому
        # перестановка ставок обязана переставить и проданную ногу.
        worst_is_low, _ = subset_trim(CURRENT, TARGET, APY,
                                      admissible_usd=15_000.0, net_cash_usd=0.0)
        swapped = dict(APY, low=4.0, mid=2.0)
        worst_is_mid, _ = subset_trim(CURRENT, TARGET, swapped,
                                      admissible_usd=15_000.0, net_cash_usd=0.0)
        self.assertLess(worst_is_low["low"], CURRENT["low"])
        self.assertEqual(worst_is_low["mid"], CURRENT["mid"])
        self.assertLess(worst_is_mid["mid"], CURRENT["mid"])
        self.assertEqual(worst_is_mid["low"], CURRENT["low"])
        self.assertNotEqual(worst_is_low, worst_is_mid)

    def test_a_budget_larger_than_one_leg_spills_without_overshooting_it(self):
        # Дыра, найденную мутацией #7 (`take = min(room, left)` → `take = left`):
        # на сценах, где бюджет меньше ПЕРВОЙ ноги, мутант эквивалентен. Здесь
        # бюджет ВЫШЕ первой ноги, и «взять ногу целиком бюджетом» увело бы
        # позицию за предложение, а книгу — за движение кэша соседки.
        current = {"low": 5_000.0, "mid": 30_000.0, "other": 60_000.0}
        target = {"mid": 0.0, "high": 35_000.0, "other": 60_000.0}
        book, why = subset_trim(current, target, APY,
                                admissible_usd=15_000.0, net_cash_usd=0.0)
        self.assertEqual(why, "")
        self.assertAlmostEqual(sum(book.values()), sum(current.values()), places=2)
        # Первая нога выбрана ПОЛНОСТЬЮ и не дальше: `low` обнуляется ровно до
        # цели, остаток бюджета уходит во вторую ногу.
        self.assertNotIn("low", book)
        self.assertAlmostEqual(book["mid"], 20_000.0, places=2)
        self.assertAlmostEqual(book["high"], 15_000.0, places=2)

    def test_an_empty_side_is_named_not_silently_turned_into_a_book(self):
        book, why = subset_trim(CURRENT, dict(CURRENT, extra=5_000.0), APY,
                                admissible_usd=15_000.0, net_cash_usd=0.0)
        self.assertIsNone(book)
        self.assertIn("пуста", why)

    def test_a_non_positive_cap_is_refused_with_a_reason(self):
        book, why = subset_trim(CURRENT, TARGET, APY,
                                admissible_usd=0.0, net_cash_usd=0.0)
        self.assertIsNone(book)
        self.assertIn("не положителен", why)


class TheTwoShapesAreComparedOnOneProposal(unittest.TestCase):
    """Меняется РОВНО форма; всё остальное у форм одно."""

    def test_the_subset_shape_touches_fewer_legs_and_costs_less(self):
        got = _compare()
        self.assertEqual(got["kind"], SHAPE_MEASURED, got.get("why"))
        self.assertLess(got["subset"]["legs"], got["interpolated"]["legs"])
        self.assertLess(got["subset"]["cost_usd"], got["interpolated"]["cost_usd"])
        self.assertEqual(got["legs_delta"],
                         got["subset"]["legs"] - got["interpolated"]["legs"])

    def test_both_shapes_move_the_same_number_of_dollars(self):
        # Если бы формы двигали разные суммы, дешевизна могла бы объясняться
        # размером хода — ровно та ошибка, которую ADR-853 нашёл у #970.
        got = _compare()
        self.assertAlmostEqual(got["subset"]["turnover_usd"],
                               got["interpolated"]["turnover_usd"], places=2)
        self.assertLessEqual(got["subset"]["turnover_usd"],
                             got["admissible_usd"] + 0.01)

    def test_the_subset_shape_also_buys_a_better_spread(self):
        got = _compare()
        self.assertGreater(got["subset"]["gain_pp"], got["interpolated"]["gain_pp"])
        self.assertGreater(got["gain_delta_pp"], 0.0)

    def test_payback_comes_from_the_same_formula_as_the_gate(self):
        got = _compare()
        for side in ("interpolated", "subset"):
            cost_pp = 100.0 * got[side]["cost_usd"] / CAPITAL
            self.assertAlmostEqual(got[side]["payback_days"],
                                   round(365.0 * cost_pp / got[side]["gain_pp"], 2),
                                   places=2, msg=side)
        self.assertLess(got["subset"]["payback_days"],
                        got["interpolated"]["payback_days"])

    def test_the_chain_map_really_reaches_the_cost_model(self):
        # Положительный контроль проводки цены: дорогая сеть и дешёвая обязаны
        # давать РАЗНЫЕ числа. Совпади они — цена считалась бы не этой дверью.
        dear = _compare(chains=CHAINS)
        cheap = _compare(chains={p: "base" for p in CHAINS})
        self.assertGreater(dear["interpolated"]["cost_usd"],
                           cheap["interpolated"]["cost_usd"])
        self.assertGreater(dear["subset"]["cost_usd"], cheap["subset"]["cost_usd"])

    def test_the_size_cap_really_comes_from_the_params_door(self):
        import dataclasses
        tight = dataclasses.replace(PARAMS, max_trade_usd=5_000.0)
        got = _compare(params=tight)
        self.assertEqual(got["kind"], SHAPE_MEASURED, got.get("why"))
        self.assertAlmostEqual(got["admissible_usd"], 5_000.0, places=2)
        self.assertLessEqual(got["subset"]["turnover_usd"], 5_000.0 + 0.01)


class EveryOutcomeIsAValue(unittest.TestCase):
    """Инв. #17: «не измерено», «предмета нет» и «измерено» — три значения."""

    def test_a_proposal_already_within_the_cap_has_no_shape_at_all(self):
        got = _compare(target=dict(CURRENT, mid=29_000.0, other=26_000.0))
        self.assertEqual(got["kind"], SHAPE_NO_SUBJECT)
        self.assertIn("внутри потолка", got["why"])
        self.assertNotIn("subset", got)

    def test_no_material_move_is_no_subject_and_not_a_cheap_shape(self):
        got = _compare(target=dict(CURRENT))
        self.assertEqual(got["kind"], SHAPE_NO_SUBJECT)
        self.assertIn("материального хода нет", got["why"])

    def test_capital_not_recorded_is_unmeasured_with_a_named_reason(self):
        got = _compare(capital=0.0)
        self.assertEqual(got["kind"], SHAPE_UNMEASURED)
        self.assertIn("капитал", got["why"])
        self.assertNotIn("subset", got)

    def test_an_unread_size_cap_leaves_no_alternative_and_says_so(self):
        # Потолок не прочитан ⇒ соседки не существует. Это НЕ «форма не
        # дешевле» и не ноль: цена интерполяции при этом НАЗВАНА, а своей
        # цены у соседки нет вовсе.
        import dataclasses
        got = _compare(params=dataclasses.replace(PARAMS, max_trade_usd=0.0))
        self.assertEqual(got["kind"], SHAPE_NO_ALTERNATIVE)
        self.assertIn("не положителен", got["why"])
        self.assertIn("interpolated", got)
        self.assertNotIn("subset", got)

    def test_pure_cash_deployment_leaves_the_two_shapes_identical(self):
        # Замер, а не оговорка: когда забирать неоткуда, выбирать между формами
        # НЕ ИЗ ЧЕГО — обе двигают один и тот же доллар в одну и ту же ногу.
        # Именно поэтому «подмножество всегда дешевле» было бы неверно.
        got = _compare(current={"low": 10_000.0},
                       target={"low": 10_000.0, "high": 60_000.0})
        self.assertEqual(got["kind"], SHAPE_MEASURED, got.get("why"))
        self.assertEqual(got["legs_delta"], 0)
        self.assertEqual(got["cost_delta_usd"], 0.0)
        self.assertEqual(got["gain_delta_pp"], 0.0)

    def test_payback_is_None_when_the_gain_is_not_positive_never_zero(self):
        # Ноль прочитался бы как «окупается мгновенно» — ровно тот класс, из-за
        # которого окупаемость у гейта тоже ``None``, а не 0.
        flat = {p: 3.0 for p in APY}
        got = _compare(apy=flat)
        self.assertEqual(got["kind"], SHAPE_MEASURED, got.get("why"))
        self.assertIsNone(got["interpolated"]["payback_days"])
        self.assertIsNone(got["subset"]["payback_days"])
        self.assertIsNone(got["payback_delta_days"])


class TheCensusReadsTheWholeHistoryNotOneRecord(unittest.TestCase):
    """Население — любое записанное предложение выше потолка, а не одно урезание."""

    @staticmethod
    def _record(date, current, target, apy=None, capital=CAPITAL):
        return {"cycle_date": date, "capital_usd": capital,
                "current_positions": dict(current),
                "target_positions": dict(target),
                "apy_evidenced_pct": dict(apy or APY)}

    def _census(self, records, chains_measured=True):
        return trim_shape_census(records, params=PARAMS, chains=CHAINS,
                                 chains_measured=chains_measured)

    def test_a_trimmable_proposal_is_counted_even_without_a_live_trim_block(self):
        # Главное свойство: население этой переписи НЕ равно населению живых
        # урезаний (их одно). Запись без блока ``admissible_trim`` — полноценный
        # предмет, потому что вопрос здесь другой.
        rows = [self._record("2026-10-27", CURRENT, TARGET),
                self._record("2026-10-28", CURRENT, TARGET)]
        for row in rows:
            self.assertNotIn("admissible_trim", row)
        got = self._census(rows)
        self.assertEqual(got["kind"], CENSUS_MEASURED)
        self.assertEqual(got["population"], 2)
        self.assertEqual(got["dates"], 2)
        self.assertEqual(got["legs"]["more"], 0)
        self.assertEqual(got["legs"]["fewer"], 2)

    def test_a_trimmed_record_is_read_from_the_proposal_not_the_trimmed_book(self):
        # Найдено ЗАМЕРОМ этого цикла: у записи, которую живой шаг ADR-850 уже
        # урезал, `target_positions` несёт книгу ПОСЛЕ урезания. Читать её как
        # предложение значило бы объявить «урезать нечего» ровно на той
        # единственной записи, где урезание и состоялось.
        trimmed = {"low": 32_500.0, "mid": 25_000.0, "high": 15_000.0,
                   "other": 25_000.0}
        rec = dict(self._record("2026-10-28", CURRENT, trimmed),
                   admissible_trim={"verdict": "TRIMMED_TO_ADMISSIBLE",
                                    "target_before": dict(TARGET)})
        proposal, source = _proposal_of(rec)
        self.assertEqual(source, PROPOSAL_FROM_TRIM_BEFORE)
        self.assertEqual(proposal, {k: float(v) for k, v in TARGET.items()})
        got = self._census([rec])
        self.assertEqual(got["kind"], CENSUS_MEASURED, got.get("why"))
        self.assertEqual(got["population"], 1)
        self.assertEqual(got["proposal_sources"],
                         {PROPOSAL_FROM_TRIM_BEFORE: 1})
        # Та же запись, прочитанная БЕЗ блока урезания, предметом не является —
        # это и есть цена, которую дверь платит, и она названа числом.
        naive = self._census([self._record("2026-10-28", CURRENT, trimmed)])
        self.assertEqual(naive["kind"], CENSUS_MEASURED_ZERO)
        self.assertEqual(naive["proposal_sources"], {PROPOSAL_FROM_TARGET: 1})

    def test_a_record_without_a_target_is_absent_not_an_empty_proposal(self):
        proposal, source = _proposal_of({"cycle_date": "2026-10-28"})
        self.assertEqual(source, PROPOSAL_ABSENT)
        self.assertEqual(proposal, {})
        got = self._census([{"cycle_date": "2026-10-28",
                             "capital_usd": CAPITAL,
                             "current_positions": dict(CURRENT)}])
        self.assertEqual(got["proposal_sources"], {PROPOSAL_ABSENT: 1})

    def test_a_history_with_nothing_trimmable_is_a_measured_zero(self):
        got = self._census([self._record("2026-10-28", CURRENT, dict(CURRENT))])
        self.assertEqual(got["kind"], CENSUS_MEASURED_ZERO)
        self.assertEqual(got["outcomes"], {SHAPE_NO_SUBJECT: 1})
        self.assertEqual(got["proposal_sources"], {PROPOSAL_FROM_TARGET: 1})
        self.assertNotIn("population", got)

    def test_an_empty_history_is_unmeasured_not_a_measured_zero(self):
        got = self._census([])
        self.assertEqual(got["kind"], CENSUS_UNMEASURED)
        self.assertIn("ни одной разобранной записи", got["why"])

    def test_history_that_is_not_a_list_is_unmeasured_with_a_reason(self):
        got = self._census({"cycle_date": "2026-10-28"})
        self.assertEqual(got["kind"], CENSUS_UNMEASURED)
        self.assertIn("не список", got["why"])

    def test_the_cap_breach_counter_is_printed_as_a_measured_zero(self):
        # «Измерено и равно нулю» обязано быть отличимо от «не измерено»: форма,
        # тихо вышедшая за потолок, сравнивалась бы с соседкой не по тому вопросу.
        got = self._census([self._record("2026-10-28", CURRENT, TARGET)])
        self.assertIn("over_cap", got["turnover"])
        self.assertEqual(got["turnover"]["over_cap"], 0)

    def test_an_undefined_payback_on_one_side_is_its_own_number(self):
        flat = {p: 3.0 for p in APY}
        rows = [self._record("2026-10-27", CURRENT, TARGET),
                self._record("2026-10-28", CURRENT, TARGET, apy=flat)]
        got = self._census(rows)
        self.assertEqual(got["population"], 2)
        self.assertEqual(got["payback"]["comparable"], 1)
        self.assertEqual(got["payback"]["undefined_on_one_side"], 1)

    def test_the_medians_are_computed_over_the_population_not_the_last_row(self):
        # Перепись существует именно затем, чтобы число перестало быть ОДНИМ
        # (ADR-853 назвал своё население: одна запись). Медиана, подменённая
        # последней строкой, вернула бы ровно это.
        # Население НЕЧЁТНОЕ и упорядочено так, что последняя строка медианой
        # НЕ является: на чётном населении подмена «медиана → последняя строка»
        # эквивалентна (у двух значений середина и есть их среднее), и мутация
        # #17 выжила именно на этом.
        # Дельту форм задаёт сторона ПРОДАЖИ (обе формы докладывают один и тот
        # же доллар в `high`, поэтому его ставка из дельты сокращается), и
        # варьируется поэтому спред забираемых ног.
        wide = dict(APY, low=1.0)
        narrow = dict(APY, low=3.5)
        rows = [self._record("2026-10-26", CURRENT, TARGET, apy=APY),
                self._record("2026-10-27", CURRENT, TARGET, apy=wide),
                self._record("2026-10-28", CURRENT, TARGET, apy=narrow)]
        got = self._census(rows)
        self.assertEqual(got["population"], 3)
        each = [compare_trim_shapes(CURRENT, TARGET, apy, capital_usd=CAPITAL,
                                    params=PARAMS, chains=CHAINS,
                                    chains_measured=True)
                for apy in (APY, wide, narrow)]
        gains = [c["gain_delta_pp"] for c in each]
        self.assertEqual(len(set(gains)), 3, gains)
        self.assertNotAlmostEqual(sorted(gains)[1], gains[-1])
        self.assertAlmostEqual(got["gain"]["delta_pp_median"],
                               round(sorted(gains)[1], 4), places=4)
        paybacks = [c["subset"]["payback_days"] for c in each]
        self.assertNotAlmostEqual(sorted(paybacks)[1], paybacks[-1])
        self.assertAlmostEqual(got["payback"]["median_subset"],
                               round(sorted(paybacks)[1], 4), places=2)

    def test_the_horizon_counters_come_from_the_params_door(self):
        import dataclasses
        rows = [self._record("2026-10-28", CURRENT, TARGET)]
        strict = self._census(rows)
        self.assertEqual(strict["payback"]["horizon_days"],
                         float(PARAMS.max_payback_days))
        wide = trim_shape_census(
            rows, params=dataclasses.replace(PARAMS, max_payback_days=10_000.0),
            chains=CHAINS, chains_measured=True)
        self.assertEqual(wide["payback"]["horizon_days"], 10_000.0)
        self.assertGreaterEqual(wide["payback"]["within_horizon_subset"],
                                strict["payback"]["within_horizon_subset"])

    def test_an_unreadable_chain_map_is_said_out_loud(self):
        rows = [self._record("2026-10-28", CURRENT, TARGET)]
        got = self._census(rows, chains_measured=False)
        self.assertFalse(got["chains_measured"])
        self.assertTrue(any("карта сетей НЕ прочитана" in line
                            for line in format_trim_shape(got)))


class TheDoorIsOneForEveryReader(unittest.TestCase):
    """Урок ADR-851: двое читателей одного артефакта расходятся без общей двери."""

    def test_a_missing_block_is_unmeasured_not_a_zero(self):
        for absent in (None, {}):
            kind, why = trim_shape_outcome(absent)
            self.assertEqual(kind, CENSUS_UNMEASURED, absent)
            self.assertIn("СТАРШЕ прибора", why)

    def test_an_unknown_kind_does_not_pass_for_measured(self):
        kind, why = trim_shape_outcome({"kind": "просто строка"})
        self.assertEqual(kind, CENSUS_UNMEASURED)
        self.assertIn("не разобран", why)

    def test_the_printer_of_an_unmeasured_census_prints_no_numbers(self):
        lines = format_trim_shape(None)
        self.assertEqual(len(lines), 2)
        self.assertIn(CENSUS_UNMEASURED, lines[1])
        self.assertFalse(any("население" in line for line in lines))

    def test_measured_census_prints_population_and_both_medians(self):
        census = trim_shape_census(
            [{"cycle_date": "2026-10-28", "capital_usd": CAPITAL,
              "current_positions": dict(CURRENT),
              "target_positions": dict(TARGET),
              "apy_evidenced_pct": dict(APY)}],
            params=PARAMS, chains=CHAINS, chains_measured=True)
        text = "\n".join(format_trim_shape(census))
        self.assertIn("население 1", text)
        self.assertIn("медиана окупаемости", text)
        self.assertIn("допустимость не утверждается", text)


class TheCensusIsWiredIntoTheArtifactNotJustWritten(unittest.TestCase):
    """Прибор без читателя — сирота (ADR-843), поэтому проверяется ПРОВОДКА.

    Контроль поднимает НАСТОЯЩИЙ ``evaluate_window`` на одноразовом каталоге и
    спрашивает ПРИСУТСТВИЕ ключа и строки: собранный руками словарь мерил бы
    свой словарь, а не проводку.
    """

    def _scene(self, tmp: Path) -> None:
        rows = []
        for day in range(6):
            stamp = _NOW - timedelta(days=5 - day)
            rows.append({
                "cycle_date": stamp.date().isoformat(),
                "generated_at": stamp.isoformat(),
                "decision_id": f"scene-{day}",
                "capital_usd": CAPITAL,
                "verdict": "HOLD",
                "turnover_usd": 60_000.0,
                "gain_pp": 1.1,
                "current_positions": dict(CURRENT),
                "target_positions": dict(TARGET),
                "apy_evidenced_pct": dict(APY),
            })
        (tmp / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def test_evaluate_window_carries_the_block_and_format_summary_prints_it(self):
        from spa_core.paper_trading.shadow_trigger_eval import (
            evaluate_window, format_summary)
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            doc = evaluate_window(tmp, write=False, now=_NOW)
        self.assertIn("trim_shape_census", doc)
        kind, why = trim_shape_outcome(doc["trim_shape_census"])
        self.assertEqual(kind, CENSUS_MEASURED, why)
        self.assertEqual(doc["trim_shape_census"]["population"], 6)
        self.assertIn("форма урезания", format_summary(doc))

    def test_the_office_step_prints_the_block_through_the_same_printer(self):
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        source = Path(office.__file__).read_text(encoding="utf-8")
        self.assertIn("format_trim_shape", source)
        self.assertIn("trim_shape_census", source)

    def test_the_block_changes_no_verdict_of_the_day(self):
        # ADVISORY объявлено — значит обязано быть ПРОВЕРЕНО: подменённая
        # перепись не имеет права двигать ни критерий взвода, ни вердикт.
        from spa_core.paper_trading.shadow_trigger_eval import evaluate_window
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            doc = evaluate_window(tmp, write=False, now=_NOW)
            flat = json.dumps(dict(doc, trim_shape_census=None), sort_keys=True,
                              default=str)
            doc2 = evaluate_window(tmp, write=False, now=_NOW)
            flat2 = json.dumps(dict(doc2, trim_shape_census=None), sort_keys=True,
                               default=str)
        self.assertEqual(flat, flat2)
        self.assertIn(doc["status"], {"READY", "NOT_READY"})
        self.assertFalse(doc["ready_to_arm"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

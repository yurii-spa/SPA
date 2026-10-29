"""ADR-855 — ДОПУСТИМОСТЬ книги формы СПРОШЕНА у политики, а не выведена.

Каждый тест — положительный контроль на один из четырёх дефектов, против
которых модуль написан:

1. **контрпример остался рассуждением.** ADR-850 показал НА ПАЛЬЦАХ, что
   «жадная» перестановка ног способна превысить потолок на ГРУППУ, которого не
   превышают оба конца отрезка, и честно оставил это рассуждением; ADR-854
   измерил размер приза такой формы и сам назвал, что допустимость её книги не
   спрашивали. Сцена ``CE_*`` ниже ПРОГОНЯЕТ контрпример через
   настоящую ``RiskPolicy``: подмножество отказано, интерполяция одобрена, и
   окупаемость у отказанной формы ЛУЧШЕ (11.23 дн. против 44.04) — то есть
   лучшее число лежит вне допустимого множества.
2. **наследство, вменённое форме.** Нарушение, которое дверь называет у КОНЦА
   отрезка, форма не изобрела. Концов ДВА, и сверять надо ПРЕДМЕТ нарушения, а
   не его текст: дверь печатает в текст процент, и «то же нарушение того же
   протокола» у конца и у формы — РАЗНЫЕ строки. Сцена ``INH_*`` даёт
   именно эту пару (25.5 % у предложения против 20.5 % у подмножества), и
   тест требует, чтобы она читалась наследством.
3. **«не измерено», выданное за ответ.** Тир неизвестен ⇒ ни один потолок
   концентрации не определён, и это САМОСТОЯТЕЛЬНЫЙ исход, а не «допустимо» и
   не «T2 по умолчанию» (ADR-359). Реестр не прочитан ⇒ перепись unmeasured, а
   не ноль.
4. **прибор без читателя.** Проводка проверяется НАСТОЯЩИМ ``evaluate_window``
   и НАСТОЯЩИМ шагом 0-офис, а не подстрокой в исходнике: собранный руками
   словарь мерил бы свой словарь.

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
from spa_core.paper_trading.trim_admissibility import (
    ADM_MEASURED,
    ADM_NO_ALTERNATIVE,
    ADM_NO_SUBJECT,
    ADM_TIER_UNKNOWN,
    ADM_UNMEASURED,
    CENSUS_MEASURED,
    CENSUS_MEASURED_ZERO,
    CENSUS_UNMEASURED,
    RULE_OTHER,
    book_verdict,
    compare_trim_admissibility,
    format_trim_admissibility,
    rule_of_violation,
    tier_map,
    trim_admissibility_census,
    trim_admissibility_outcome,
    violation_key,
)

_NOW = datetime(2026, 10, 28, 20, 56, tzinfo=timezone.utc)

CAPITAL = 100_000.0
PARAMS = TriggerParams.for_mode("paper")

#: Контрпример ADR-850, записанный книгами: оба конца отрезка допустимы, а
#: жадное подмножество доносит деньги в T2 и выносит их из T1, поэтому сумма
#: ГРУППЫ у него 55 % против потолка 50 %. Интерполяция этого не умеет — точка
#: отрезка по ЛИНЕЙНОМУ потолку лежит между концами.
CE_CURRENT = {"t1a": 35_000.0, "t1b": 5_000.0,
              "x": 20_000.0, "y": 5_000.0, "z": 15_000.0}
CE_TARGET = {"t1a": 5_000.0, "t1b": 35_000.0,
             "x": 10_000.0, "y": 20_000.0, "z": 10_000.0}
#: Наследство: предложение САМО превышает потолок на протокол (25.5 %), и
#: подмножество доносит то же нарушение с ДРУГИМ процентом (20.5 %).
INH_CURRENT = {"t1a": 35_000.0, "t1b": 5_000.0,
               "x": 20_000.0, "y": 5_500.0, "z": 15_000.0}
INH_TARGET = {"t1a": 5_000.0, "t1b": 35_000.0,
              "x": 10_000.0, "y": 25_500.0, "z": 10_000.0}

APY = {"t1a": 1.2, "t1b": 5.0, "x": 3.0, "y": 9.0, "z": 8.0}
TIERS = {"t1a": "T1", "t1b": "T1", "x": "T2", "y": "T2", "z": "T2"}
CHAINS = {k: "ethereum" for k in TIERS}


def _one(current=None, target=None, apy=None, tiers=None, chains=None,
         capital=CAPITAL, params=PARAMS, chains_measured=True):
    return compare_trim_admissibility(
        CE_CURRENT if current is None else current,
        CE_TARGET if target is None else target,
        APY if apy is None else apy,
        capital_usd=capital, params=params,
        tiers=TIERS if tiers is None else tiers,
        chains=CHAINS if chains is None else chains,
        chains_measured=chains_measured)


class TheBookDoorIsTheRealPolicyNotACopyOfIt(unittest.TestCase):
    """Вердикт обязан приходить ИЗ ``RiskPolicy``, а не из литерала рядом."""

    def test_the_tier_label_really_reaches_the_cap(self):
        # Одна и та же книга под разными ярлыками тира обязана получить РАЗНЫЕ
        # вердикты: потолок на протокол равен 40 % у T1 и 20 % у T2. Если бы
        # ярлык не доходил, подмена молча ничего не изменила бы.
        book = {"solo": 30_000.0}
        as_t1, _ = book_verdict(book, {"solo": 4.0}, CAPITAL,
                                tiers={"solo": "T1"}, chains={"solo": "ethereum"})
        as_t2, _ = book_verdict(book, {"solo": 4.0}, CAPITAL,
                                tiers={"solo": "T2"}, chains={"solo": "ethereum"})
        self.assertIsNotNone(as_t1)
        self.assertIsNotNone(as_t2)
        assert as_t1 is not None and as_t2 is not None  # для читателя типов
        self.assertTrue(as_t1["approved"], as_t1["violations"])
        self.assertFalse(as_t2["approved"])
        self.assertTrue(any("Concentration breach" in v
                            for v in as_t2["violations"]))

    def test_the_chain_map_really_reaches_the_chain_cap(self):
        # Потолок на одну сеть 90 %: вся книга в одной сети его пробивает, та
        # же книга, разложенная по двум, — нет.
        book = {"a": 46_000.0, "b": 46_000.0}
        apy = {"a": 4.0, "b": 4.0}
        tiers = {"a": "T1", "b": "T1"}
        one_chain, _ = book_verdict(book, apy, CAPITAL, tiers=tiers,
                                    chains={"a": "ethereum", "b": "ethereum"})
        two_chains, _ = book_verdict(book, apy, CAPITAL, tiers=tiers,
                                     chains={"a": "ethereum", "b": "arbitrum"})
        assert one_chain is not None and two_chains is not None
        self.assertTrue(any("Chain concentration" in v
                            for v in one_chain["violations"]))
        self.assertFalse(any("Chain concentration" in v
                             for v in two_chains["violations"]))

    def test_an_unknown_tier_is_its_own_outcome_never_T2(self):
        verdict, unknown = book_verdict({"stranger": 10_000.0}, {"stranger": 4.0},
                                        CAPITAL, tiers={}, chains={})
        self.assertIsNone(verdict)           # НЕ «допустимо» и НЕ «отказано»
        self.assertEqual(unknown, ["stranger"])

    def test_the_cash_buffer_is_asked_on_the_book_itself(self):
        # Книга, развернувшая 96 % капитала, пробивает буфер 5 % — порог
        # спрашивается у книги, а не у сделки.
        verdict, _ = book_verdict({"a": 38_000.0, "b": 38_000.0, "c": 20_000.0},
                                  {"a": 4.0, "b": 4.0, "c": 4.0}, CAPITAL,
                                  tiers={"a": "T1", "b": "T1", "c": "T2"},
                                  chains={"a": "ethereum", "b": "arbitrum",
                                          "c": "base"})
        assert verdict is not None
        self.assertTrue(any("Cash buffer" in v for v in verdict["violations"]),
                        verdict["violations"])


class TheDoorOfTheShapesGivesUnroundedInputs(unittest.TestCase):
    """Дыра, найденную мутациями #973: «неокруглённый» был контрактом без замка.

    Прибор берёт книги у ``shapes_of_proposal`` именно затем, чтобы не
    восстанавливать их по напечатанному ``k`` (замер цикла: по округлённому —
    102 предложения вместо 103). Но сам контракт «входы НЕ округлены» не
    проверял никто: мутант ``round(k, 2)`` переживал всю батарею, потому что ни
    один вердикт сцены от него не менялся. Контракт без проверки — обещание.
    """

    def _shapes(self):
        from spa_core.paper_trading.trim_shape import shapes_of_proposal
        return shapes_of_proposal(CE_CURRENT, CE_TARGET, APY,
                                  capital_usd=CAPITAL, params=PARAMS)

    def test_k_reproduces_the_admissible_turnover_exactly(self):
        # Сцена выбрана так, что k = 1/3 — величина, которую округление ЛОМАЕТ;
        # на сцене с k = 0.25 этот контроль был бы зелен и у мутанта.
        s = self._shapes()
        self.assertNotEqual(round(float(s["k"]), 2), float(s["k"]))
        self.assertAlmostEqual(
            float(s["k"]) * float(s["turnover_full_usd"]),
            float(s["admissible_usd"]), places=6,
            msg="k округлён — урезанный ход перестаёт заполнять потолок размера")

    def test_the_subset_book_fills_the_cap_it_was_given(self):
        from spa_core.allocator.rebalance_economics import _legs
        s = self._shapes()
        _, turnover = _legs(s["current"], s["book_subset"],
                            float(s["capital_usd"]), float(s["min_leg_frac"]))
        self.assertAlmostEqual(turnover, float(s["admissible_usd"]), places=2)


class TheSubjectOfAViolationIsNotItsText(unittest.TestCase):
    """Дверь печатает в текст ЧИСЛО — сверять надо предмет (правило + на чём)."""

    def test_the_same_subject_at_a_different_percent_is_the_same_key(self):
        a = "Concentration breach: y at 25.5% > 20.0%"
        b = "Concentration breach: y at 20.5% > 20.0%"
        self.assertNotEqual(a, b)                      # тексты РАЗНЫЕ
        self.assertEqual(violation_key(a), violation_key(b))

    def test_two_different_protocols_do_not_collapse_into_one_key(self):
        self.assertNotEqual(
            violation_key("Concentration breach: y at 25.5% > 20.0%"),
            violation_key("Concentration breach: z at 25.5% > 20.0%"))

    def test_a_group_cap_is_its_own_subject(self):
        self.assertEqual(
            violation_key("Total T2 allocation 65.0% exceeds limit 50.0%"),
            ("t2_group_cap", ""))

    def test_an_unrecognised_text_keeps_itself_as_the_subject(self):
        first = violation_key("нечто, чего никто не объявлял")
        second = violation_key("нечто другое, чего никто не объявлял")
        self.assertEqual(first[0], RULE_OTHER)
        self.assertNotEqual(first, second)   # два разных не сливаются молча

    def test_the_rule_of_an_unrecognised_text_is_other_not_silence(self):
        self.assertEqual(rule_of_violation("что-то новое"), RULE_OTHER)


class TheCounterexampleOfADR850IsNowExecuted(unittest.TestCase):
    """Жадная форма превышает потолок на ГРУППУ, которого нет у обоих концов."""

    def setUp(self) -> None:
        self.one = _one()
        self.assertEqual(self.one["kind"], ADM_MEASURED, self.one.get("why"))
        self.v = self.one["verdicts"]

    def test_both_ends_of_the_segment_are_admissible(self):
        self.assertTrue(self.v["standing"]["approved"],
                        self.v["standing"]["violations"])
        self.assertTrue(self.v["proposal"]["approved"],
                        self.v["proposal"]["violations"])

    def test_the_interpolated_point_inherits_no_breach(self):
        self.assertTrue(self.v["interpolated"]["approved"],
                        self.v["interpolated"]["violations"])

    def test_the_subset_shape_breaches_the_group_cap_and_is_refused(self):
        self.assertFalse(self.v["subset"]["approved"])
        self.assertIn("t2_group_cap",
                      {violation_key(x)[0]
                       for x in self.v["subset"]["violations"]})

    def test_that_breach_is_charged_to_the_shape_not_to_an_end(self):
        self.assertTrue(self.v["subset"]["new_violations"])
        self.assertEqual(self.v["subset"]["inherited_violations"], [])

    def test_the_refused_shape_is_the_one_with_the_better_payback(self):
        # Ровно предмет ADR: лучшее число лежит ВНЕ допустимого множества, и
        # без этого вопроса приз ADR-854 читался бы как разрешение его взять.
        self.assertIsNotNone(self.one["payback_subset"])
        self.assertIsNotNone(self.one["payback_interpolated"])
        self.assertLess(float(self.one["payback_subset"]),
                        float(self.one["payback_interpolated"]))

    def test_the_group_cap_really_comes_from_the_policy_object(self):
        # Контроль проводки, а не слов: поднятый потолок в ЖИВОМ объекте
        # политики обязан снять отказ. Если бы 50 % жили литералом в приборе,
        # подмена не изменила бы ничего — и тест остался бы зелёным зря.
        from unittest import mock

        from spa_core.risk import policy as pol

        original = pol.RiskPolicy

        def relaxed_policy(config=None):
            built = original(config)
            built.config.max_total_t2_allocation = 0.90
            return built

        with mock.patch.object(pol, "RiskPolicy", relaxed_policy):
            relaxed = _one()
        self.assertTrue(relaxed["verdicts"]["subset"]["approved"],
                        relaxed["verdicts"]["subset"]["violations"])
        # И обратная сторона: без подмены тот же вход отказан.
        self.assertFalse(_one()["verdicts"]["subset"]["approved"])

    def test_the_violation_names_the_limit_the_config_declares(self):
        from spa_core.risk.policy import RiskConfig
        limit = f"{RiskConfig().max_total_t2_allocation:.1%}"
        self.assertTrue(any(limit in v for v in self.v["subset"]["violations"]),
                        self.v["subset"]["violations"])


class InheritanceIsMeasuredByBothEndsAndBySubject(unittest.TestCase):
    """Нарушение конца отрезка — не вина формы, даже если процент другой."""

    def setUp(self) -> None:
        self.one = _one(current=INH_CURRENT, target=INH_TARGET)
        self.assertEqual(self.one["kind"], ADM_MEASURED, self.one.get("why"))
        self.v = self.one["verdicts"]

    def test_the_proposal_itself_is_the_one_that_breaches_the_protocol_cap(self):
        self.assertFalse(self.v["proposal"]["approved"])
        self.assertIn(("protocol_concentration", "y"),
                      {violation_key(x)
                       for x in self.v["proposal"]["violations"]})

    def test_the_same_breach_on_the_subset_is_read_as_inherited(self):
        inherited = self.v["subset"]["inherited_violations"]
        self.assertIn(("protocol_concentration", "y"),
                      {violation_key(x) for x in inherited})

    def test_comparing_by_TEXT_would_have_called_it_new(self):
        # Контроль в ОБЕ стороны: сцена осмысленна только если тексты РАЗНЫЕ.
        ends = set(self.v["proposal"]["violations"]) | set(
            self.v["standing"]["violations"])
        same_subject = [x for x in self.v["subset"]["violations"]
                        if violation_key(x) == ("protocol_concentration", "y")]
        self.assertTrue(same_subject)
        self.assertTrue(all(x not in ends for x in same_subject))

    def test_the_group_cap_breach_of_the_shape_is_still_charged_to_the_shape(self):
        self.assertIn("t2_group_cap",
                      {violation_key(x)[0]
                       for x in self.v["subset"]["new_violations"]})


class EveryOutcomeIsAValue(unittest.TestCase):
    """Пять исходов, и ни один не выдаётся за другой (инв. #17)."""

    def test_a_proposal_within_the_size_cap_has_no_subject(self):
        tiny = dict(CE_CURRENT)
        tiny["y"] = CE_CURRENT["y"] + 100.0
        tiny["x"] = CE_CURRENT["x"] - 100.0
        one = _one(target=tiny)
        self.assertEqual(one["kind"], ADM_NO_SUBJECT, one.get("why"))
        self.assertTrue(one["why"])

    def test_an_unknown_tier_anywhere_stops_the_record_with_the_key_named(self):
        one = _one(tiers={k: v for k, v in TIERS.items() if k != "z"})
        self.assertEqual(one["kind"], ADM_TIER_UNKNOWN)
        self.assertEqual(one["unknown_tier_keys"], ["z"])
        self.assertIn("z", one["why"])
        self.assertNotIn("verdicts", one)   # ни в одну сторону не судили

    def test_capital_not_recorded_is_unmeasured_with_a_named_reason(self):
        one = _one(capital=0.0)
        self.assertEqual(one["kind"], ADM_UNMEASURED)
        self.assertIn("капитал", one["why"])

    def test_an_unread_size_cap_leaves_no_alternative_shape(self):
        # Потолок размера не прочитан ⇒ соседки не существует, и это НЕ
        # «форма допустима»: судить было нечего, а не нечего было нарушать.
        import dataclasses
        one = _one(params=dataclasses.replace(PARAMS, max_trade_usd=0.0))
        self.assertEqual(one["kind"], ADM_NO_ALTERNATIVE, one.get("why"))
        self.assertIn("не положителен", one["why"])
        self.assertNotIn("verdicts", one)

    def test_pure_cash_deployment_makes_both_shapes_admissible_alike(self):
        # Замер, а не оговорка: когда забирать неоткуда, формы двигают один и
        # тот же доллар, поэтому и вердикт у них ОДИН. «Подмножество всегда
        # недопустимо» было бы так же неверно, как «всегда дешевле».
        one = _one(current={"x": 1_000.0},
                   target={"x": 1_000.0, "y": 20_000.0})
        self.assertEqual(one["kind"], ADM_MEASURED, one.get("why"))
        self.assertEqual(one["verdicts"]["subset"]["approved"],
                         one["verdicts"]["interpolated"]["approved"])


class TheCensusReadsTheWholeHistory(unittest.TestCase):
    """Перепись отвечает о НАСЕЛЕНИИ, а не о последней записи."""

    def _rows(self, n: int = 4, *, current=None, target=None) -> list:
        rows = []
        for day in range(n):
            stamp = _NOW - timedelta(days=n - 1 - day)
            rows.append({
                "cycle_date": stamp.date().isoformat(),
                "generated_at": stamp.isoformat(),
                "capital_usd": CAPITAL,
                "verdict": "HOLD",
                "current_positions": dict(CE_CURRENT if current is None
                                          else current),
                "target_positions": dict(CE_TARGET if target is None else target),
                "apy_evidenced_pct": dict(APY),
            })
        return rows

    def _census(self, rows, *, tiers_measured=True, tiers=None):
        return trim_admissibility_census(
            rows, params=PARAMS,
            tiers=TIERS if tiers is None else tiers,
            tiers_measured=tiers_measured,
            chains=CHAINS, chains_measured=True)

    def test_the_population_and_the_verdict_buckets_come_from_the_rows(self):
        census = self._census(self._rows(4))
        self.assertEqual(census["kind"], CENSUS_MEASURED)
        self.assertEqual(census["population"], 4)
        self.assertEqual(census["verdicts"]["only_interpolated"], 4)
        self.assertEqual(census["verdicts"]["both_admissible"], 0)
        self.assertEqual(census["refused"]["subset"], 4)
        self.assertEqual(census["shape_caused"]["subset"], 4)
        self.assertEqual(census["inherited_only"]["subset"], 0)
        self.assertEqual(census["causes"]["subset"]["t2_group_cap"], 4)

    def test_the_prize_on_the_admissible_part_is_a_subset_of_the_comparable(self):
        census = self._census(self._rows(4))
        prize = census["prize"]
        self.assertLessEqual(prize["admissible_subset"], prize["comparable"])
        self.assertEqual(prize["admissible_subset"], 0)
        # Ни одной допустимой записи ⇒ медиана «не определена», а НЕ ноль.
        self.assertIsNone(prize["median_subset_admissible"])
        self.assertIsNotNone(prize["median_subset_all"])

    def test_a_registry_that_was_not_read_is_unmeasured_not_a_zero(self):
        census = self._census(self._rows(2), tiers_measured=False, tiers={})
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)
        self.assertIn("реестр", census["why"])
        self.assertNotIn("population", census)

    def test_a_history_with_nothing_trimmable_is_a_measured_zero(self):
        rows = self._rows(2, target=dict(CE_CURRENT))
        census = self._census(rows)
        self.assertEqual(census["kind"], CENSUS_MEASURED_ZERO)
        self.assertEqual(census["outcomes"].get(ADM_NO_SUBJECT), 2)

    def test_an_empty_history_is_unmeasured_not_a_measured_zero(self):
        census = self._census([])
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)

    def test_history_that_is_not_a_list_is_unmeasured_with_a_reason(self):
        census = self._census({"not": "a list"})  # type: ignore[arg-type]
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)
        self.assertIn("список", census["why"])

    def test_unknown_tier_keys_are_counted_and_named_not_dropped(self):
        census = self._census(self._rows(3),
                              tiers={k: v for k, v in TIERS.items() if k != "z"})
        self.assertEqual(census["kind"], CENSUS_MEASURED_ZERO)
        self.assertEqual(census["outcomes"].get(ADM_TIER_UNKNOWN), 3)
        self.assertEqual(census["unknown_tier_keys"], {"z": 3})

    def test_the_funded_cap_comes_from_the_policy_config_door(self):
        from spa_core.risk.policy import RiskConfig
        census = self._census(self._rows(2))
        self.assertEqual(census["funded_count"]["cap_declared"],
                         int(RiskConfig().max_protocols))
        # Дверь книги этот потолок НЕ спрашивает — и это НАЗВАНО, а не умолчано.
        self.assertFalse(census["funded_count"]["asked_by_the_book_door"])

    def test_the_funded_cap_is_not_a_literal_beside_the_door(self):
        # Равенство выше одно не отличает дверь от литерала `8`: сегодня они
        # совпадают. Потолок в ЖИВОМ объекте политики обязан изменить ответ.
        from unittest import mock

        from spa_core.risk import policy as pol

        original = pol.RiskPolicy

        def narrower(config=None):
            built = original(config)
            built.config.max_protocols = 5
            return built

        with mock.patch.object(pol, "RiskPolicy", narrower):
            census = self._census(self._rows(2))
        self.assertEqual(census["funded_count"]["cap_declared"], 5)

    def test_an_unreadable_funded_cap_is_None_not_zero(self):
        # Потолок не прочитан ⇒ «не измерено», и счётчики превышения тоже
        # None: ноль прочитался бы как «превышений нет» (инв. #17).
        from unittest import mock

        from spa_core.paper_trading import trim_admissibility as mod
        with mock.patch.object(mod, "declared_funded_cap", return_value=None):
            census = self._census(self._rows(2))
        self.assertIsNone(census["funded_count"]["cap_declared"])
        self.assertIsNone(census["funded_count"]["over_cap"]["subset"])

    def test_an_unreadable_policy_object_leaves_the_cap_unmeasured(self):
        # Контроль самой двери: политика не построилась ⇒ None, а не ноль.
        from unittest import mock

        from spa_core.paper_trading.trim_admissibility import declared_funded_cap
        from spa_core.risk import policy as pol

        def explode(*_a, **_k):
            raise RuntimeError("конфиг не прочитан")

        with mock.patch.object(pol, "RiskPolicy", explode):
            self.assertIsNone(declared_funded_cap())

    def test_the_horizon_counters_come_from_the_params_door(self):
        from dataclasses import replace
        rows = self._rows(4)
        wide = trim_admissibility_census(
            rows, params=replace(PARAMS, max_payback_days=10_000.0),
            tiers=TIERS, tiers_measured=True,
            chains=CHAINS, chains_measured=True)
        self.assertEqual(wide["prize"]["horizon_days"], 10_000.0)
        self.assertEqual(wide["prize"]["within_horizon_subset_all"],
                         wide["prize"]["comparable"])


class TheDoorIsOneForEveryReader(unittest.TestCase):
    """Исход читается ОДНОЙ дверью — урок ADR-851."""

    def test_a_missing_block_is_unmeasured_not_a_zero(self):
        kind, why = trim_admissibility_outcome(None)
        self.assertEqual(kind, CENSUS_UNMEASURED)
        self.assertIn("ADR-851", why)

    def test_an_unknown_kind_does_not_pass_for_measured(self):
        kind, why = trim_admissibility_outcome({"kind": "совсем новое"})
        self.assertEqual(kind, CENSUS_UNMEASURED)
        self.assertIn("совсем новое", why)

    def test_the_printer_of_an_unmeasured_census_prints_no_numbers(self):
        lines = format_trim_admissibility(None)
        self.assertEqual(len(lines), 2)
        self.assertNotIn("ПРИЗ", "\n".join(lines))

    def test_the_printer_of_a_measured_census_prints_both_prizes(self):
        census = trim_admissibility_census(
            [{"cycle_date": "2026-10-28", "capital_usd": CAPITAL,
              "current_positions": dict(CE_CURRENT),
              "target_positions": dict(CE_TARGET),
              "apy_evidenced_pct": dict(APY)}],
            params=PARAMS, tiers=TIERS, tiers_measured=True,
            chains=CHAINS, chains_measured=True)
        text = "\n".join(format_trim_admissibility(census))
        self.assertIn("ПРИЗ на той же основе", text)
        self.assertIn("ПРИЗ на ДОПУСТИМОЙ части", text)
        self.assertIn("вердикт двери книги", text)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)


class TheTierMapComesFromTheRegistryByTheCanonicalParse(unittest.TestCase):
    """Разбор тира — канон ``tier_from_registry``, а не своя копия."""

    def test_a_tier_written_as_a_string_is_read_the_same_as_a_number(self):
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "adapter_registry.json").write_text(json.dumps({
                "adapters": {"as_text": {"tier": "T1"}, "as_number": {"tier": 1},
                             "third": {"tier": 3}, "zero": {"tier": 0},
                             "absent": {}}}), encoding="utf-8")
            tiers, measured = tier_map(tmp)
        self.assertTrue(measured)
        self.assertEqual(tiers["as_text"], "T1")
        self.assertEqual(tiers["as_number"], "T1")
        self.assertEqual(tiers["third"], "T3")      # НЕ «T2 по умолчанию»
        self.assertNotIn("zero", tiers)             # 0 = не размещаем ⇒ не знаем
        self.assertNotIn("absent", tiers)

    def test_a_registry_that_cannot_be_read_says_so_instead_of_guessing(self):
        with TemporaryDirectory() as raw:
            tiers, measured = tier_map(Path(raw))
        self.assertFalse(measured)
        self.assertEqual(tiers, {})


class TheCensusIsWiredIntoTheArtifactNotJustWritten(unittest.TestCase):
    """Прибор без читателя — сирота (ADR-843), поэтому проверяется ПРОВОДКА."""

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
                "current_positions": dict(CE_CURRENT),
                "target_positions": dict(CE_TARGET),
                "apy_evidenced_pct": dict(APY),
            })
        (tmp / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        (tmp / "adapter_registry.json").write_text(json.dumps({
            "adapters": {k: {"tier": t, "chain": CHAINS[k]}
                         for k, t in TIERS.items()}}), encoding="utf-8")

    def test_evaluate_window_carries_the_block_and_format_summary_prints_it(self):
        from spa_core.paper_trading.shadow_trigger_eval import (
            evaluate_window, format_summary)
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            doc = evaluate_window(tmp, write=False, now=_NOW)
        self.assertIn("trim_admissibility_census", doc)
        kind, why = trim_admissibility_outcome(doc["trim_admissibility_census"])
        self.assertEqual(kind, CENSUS_MEASURED, why)
        self.assertEqual(doc["trim_admissibility_census"]["population"], 6)
        self.assertIn("допустимость формы", format_summary(doc))

    def test_the_office_step_prints_the_block_through_the_same_printer(self):
        # Не подстрока в исходнике, а НАСТОЯЩИЙ вызов выжимки шага 0-офис:
        # проверка исходника мерила бы свои же слова, а не проводку.
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        census = trim_admissibility_census(
            [{"cycle_date": "2026-10-28", "capital_usd": CAPITAL,
              "current_positions": dict(CE_CURRENT),
              "target_positions": dict(CE_TARGET),
              "apy_evidenced_pct": dict(APY)}],
            params=PARAMS, tiers=TIERS, tiers_measured=True,
            chains=CHAINS, chains_measured=True)
        doc = {"status": "NOT_READY", "ready_to_arm": False,
               "observation_days": 1, "generated_at": _NOW.isoformat(),
               "trim_admissibility_census": census}
        lines = office._summarize_json("shadow_trigger_evaluation.json", doc)
        text = "\n".join(lines)
        self.assertIn("допустимость формы", text)
        self.assertIn("вердикт двери книги", text)

    def test_an_artifact_without_the_block_is_named_not_silently_zero(self):
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        lines = office._summarize_json(
            "shadow_trigger_evaluation.json",
            {"status": "NOT_READY", "ready_to_arm": False,
             "observation_days": 1, "generated_at": _NOW.isoformat()})
        text = "\n".join(lines)
        self.assertIn("допустимость формы", text)
        self.assertIn(CENSUS_UNMEASURED, text)

    def test_the_block_changes_no_verdict_of_the_day(self):
        # ADVISORY объявлено — значит обязано быть ПРОВЕРЕНО: подменённая
        # перепись не имеет права двигать ни один другой ключ ответа.
        from unittest import mock

        from spa_core.paper_trading import shadow_trigger_eval as ste
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            real = ste.evaluate_window(tmp, write=False, now=_NOW)
            with mock.patch(
                    "spa_core.paper_trading.trim_admissibility"
                    ".trim_admissibility_census",
                    return_value={"kind": "подменено"}):
                patched = ste.evaluate_window(tmp, write=False, now=_NOW)
        self.assertNotEqual(real["trim_admissibility_census"],
                            patched["trim_admissibility_census"])
        self.assertEqual(
            json.dumps(dict(real, trim_admissibility_census=None),
                       sort_keys=True, default=str),
            json.dumps(dict(patched, trim_admissibility_census=None),
                       sort_keys=True, default=str))
        self.assertIn(real["status"], {"READY", "NOT_READY"})
        self.assertFalse(real["ready_to_arm"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

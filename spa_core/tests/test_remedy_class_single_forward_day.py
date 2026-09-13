"""Сторожа прибора «рычаги под правилом ОДНОГО форвардного дня» (заказ #592/G9).

Каждый тест — положительный контроль на дефект, который замер 13.09 изготовил бы,
будь правило написано иначе. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md`).

Главный из них — САМ ПРЕДМЕТ заказа: G7 объединяет дешевейшие рычаги ног по ВСЕМ их
парам, и такой набор есть НЕОБХОДИМОЕ, но не достаточное условие подъёма дня. На
живых данных это приписало дню 2026-09-06 рычаг `key_mismatch`, которого тому дню не
нужно вовсе: писатель поднимает его в одиночку через форвардный день 2026-09-07.

Достаточность здесь НЕ предполагается по построению: её проверяет настоящий судья
(`_evaluate_verdict` через `_causes._replay_recovers`), и эти контроли в тестах НЕ
подменены — подменены только соседи, чьи замеры не являются предметом.

FROZEN-DATE-OK: injected-clock — все даты здесь либо ключи-даты фикстур (предмет
замера, не свежесть), либо якорь `_NOW`, который передаётся приборам параметром
``now=``; стенных часов ни один тест не спрашивает.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом и передаётся
# приборам параметром ``now=``; прочие даты суть КЛЮЧИ-ДАТЫ фикстур (предмет замера,
# не свежесть). Стенных часов ни один тест здесь не спрашивает.
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import unevidenced_leg_causes as causes
from spa_core.monitoring import remedy_class_single_forward_day as mod

#: Якорь времени — ВХОД приборов, а не окружение: обе стороны закреплены, тест
#: бессмертен (порядок предпочтения №1, `.claude/rules/deployment.md`).
_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)

_DAY = "2026-09-06"
_F1 = "2026-09-07"     # там блокирует ОДИН `pendle`  ⇒ {writer_universe}
_F2 = "2026-09-11"     # там блокируют оба            ⇒ {key_mismatch, writer_universe}


def _decision(date: str = _DAY) -> dict:
    """День решения: двигаются ровно две ноги, ход существенный."""
    return {"cycle_date": date, "book_id": "conservative", "schema": "shadow-hist-v2",
            "capital_usd": 100000.0, "turnover_usd": 20000.0, "verdict": "HOLD",
            "current_positions": {"pendle": 0.0, "fluid_usdc": 20000.0,
                                  "maple": 20000.0},
            "target_positions": {"pendle": 20000.0, "fluid_usdc": 0.0,
                                 "maple": 20000.0},
            "apy_evidenced_pct": {"pendle": 14.0, "fluid_usdc": 4.87, "maple": 4.9},
            "apy_unevidenced": []}


def _mixed_decision(date: str = _DAY) -> dict:
    """День, чьи ДВИГАЕМЫЕ ноги — `pendle` (опрашивается) и `spark_susds` (нет).

    Ноги подобраны так, чтобы набор дня оказался РАЗНОРОДНЫМ: писатель поднимает
    первую, а вторую не поднимает никакая наша строка. Сцена нужна именно живая,
    а не выдуманная: `spark_susds` — та самая нога дня 2026-08-24, на которой
    ADR-369 измерил $10 000, не поднимаемых нашим кодом ни при каком его состоянии.
    """
    return {"cycle_date": date, "book_id": "conservative", "schema": "shadow-hist-v2",
            "capital_usd": 100000.0, "turnover_usd": 20000.0, "verdict": "HOLD",
            "current_positions": {"pendle": 0.0, "spark_susds": 20000.0,
                                  "maple": 20000.0},
            "target_positions": {"pendle": 20000.0, "spark_susds": 0.0,
                                 "maple": 20000.0},
            "apy_evidenced_pct": {"pendle": 14.0, "spark_susds": 4.87, "maple": 4.9},
            "apy_unevidenced": []}


def _forward(date: str, priced: dict) -> dict:
    return {"cycle_date": date, "book_id": "conservative",
            "schema": "shadow-hist-v2", "capital_usd": 100000.0,
            "current_positions": {}, "target_positions": {},
            "apy_evidenced_pct": dict(priced), "apy_unevidenced": []}


def _pair(protocol: str, forward: str, klass: str = causes.CLASS_ABSENT,
          day: str = _DAY) -> dict:
    return {"decision_date": day, "forward_date": forward,
            "protocol": protocol, "class": klass}


def _install(test, *, base_days, pairs, history, twins=None, horizon=7,
             polled=("pendle",), base_status="CRITICAL"):
    """Подменить СОСЕДЕЙ (их замеры не предмет) — но не судью и не контроли."""
    tmp = TemporaryDirectory()
    test.addCleanup(tmp.cleanup)

    from spa_core.orchestrator import adapter_orchestrator as orch
    saved_polled = orch.POLLED_ADAPTERS
    orch.POLLED_ADAPTERS = [(k, "T2", object()) for k in polled]

    orig = (mod._g7.measure, mod._causes.measure, mod._g7._twin_keys,
            mod._dep._ste.load_history)
    mod._g7.measure = lambda *a, **k: {"status": base_status, "per_day": base_days}
    mod._causes.measure = lambda *a, **k: {"status": "CRITICAL",
                                           "attribution": pairs,
                                           "horizon_days": horizon}
    mod._g7._twin_keys = lambda *a, **k: {"measured": True, "pairs": twins or {},
                                          "renames": []}
    mod._dep._ste.load_history = lambda *a, **k: (history, 0)

    def restore():
        orch.POLLED_ADAPTERS = saved_polled
        (mod._g7.measure, mod._causes.measure, mod._g7._twin_keys,
         mod._dep._ste.load_history) = orig
    test.addCleanup(restore)
    return Path(tmp.name)


def _live_shape(test, **over):
    """Живая форма замера 13.09: день, который G7 удорожает, а один день — нет."""
    kwargs = dict(
        base_days=[{"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
                    "turnover_usd": 20000.0,
                    "unpriced_protocols": ["pendle", "fluid_usdc"],
                    "remedies_required": ["key_mismatch", "writer_universe"]}],
        pairs=[_pair("pendle", _F1),
               _pair("pendle", _F2),
               _pair("fluid_usdc", _F2)],
        history=[_decision(),
                 _forward(_F1, {"fluid_usdc": 4.8, "maple": 4.9}),
                 _forward(_F2, {"fluid_fusdc": 4.4, "maple": 4.9})],
        twins={"fluid_usdc": ["fluid_fusdc"], "fluid_fusdc": ["fluid_usdc"]},
    )
    kwargs.update(over)
    return _install(test, **kwargs)


class TheSubject(unittest.TestCase):
    """Предмет заказа: перенос ответа G7 с НОГИ на ДЕНЬ может быть смещён."""

    def test_day_is_raised_by_the_writer_alone_though_g7_also_charges_key_mismatch(self):
        """АВАРИЯ-класс, ради которого заказ и написан (замер 13.09, 2026-09-06).

        G7 берёт у `fluid_usdc` дешевейший рычаг по ВСЕМ парам (`key_mismatch`) и
        объединяет его с рычагом `pendle`. Но днём 2026-09-07 `fluid_usdc` уже
        оценена — блокирует там один `pendle`, и дня довольно строке писателя.
        Приписать дню `key_mismatch` значит удорожить починку на бумаге и
        завысить цену ДОКАЗАННОГО класса, на который смотрит владелец.
        """
        doc = mod.measure(_live_shape(self), now=_NOW)
        day = doc["per_day"][0]
        self.assertEqual(day["remedies_required"], ["writer_universe"])
        self.assertEqual(day["g7_remedies_required"],
                         ["key_mismatch", "writer_universe"])
        self.assertTrue(day["changed"])
        self.assertEqual(day["chosen_forward_date"], _F1)
        self.assertEqual(day["legs_blocking_there"], ["pendle"])
        self.assertEqual(doc["answer"]["changed_class_usd"], 20000.0)

    def test_a_day_whose_every_forward_day_blocks_both_legs_does_not_change(self):
        """Контроль в ОБЕ стороны: правило не обязано двигать каждый день.

        Без него «класс сменили все дни» было бы истинным по построению, и тест
        первого случая ничего бы не доказывал.
        """
        doc = mod.measure(_live_shape(self, pairs=[
            _pair("pendle", _F2), _pair("fluid_usdc", _F2)],
            history=[_decision(), _forward(_F2, {"fluid_fusdc": 4.4, "maple": 4.9})]),
            now=_NOW)
        day = doc["per_day"][0]
        self.assertEqual(day["remedies_required"],
                         ["key_mismatch", "writer_universe"])
        self.assertFalse(day["changed"])
        self.assertEqual(doc["answer"]["changed_class_usd"], 0)

    def test_the_split_verdict_names_confirmation_and_the_shifted_lever_apart(self):
        """Раскладка подтверждена, а рычаг СДВИНУТ — это два разных утверждения.

        Замер 13.09 даёт ровно этот случай: адресат тот же (наш код), но цена
        класса `key_mismatch` падает на треть. Слив их в одно число, отчёт либо
        скрыл бы сдвиг, либо ложно объявил бы раскладку смещённой.
        """
        doc = mod.measure(_live_shape(self), now=_NOW)
        self.assertTrue(doc["answer"]["split_confirmed"])
        self.assertEqual(doc["answer"]["our_code_pct"],
                         doc["answer"]["g7_our_code_pct"])
        self.assertEqual(doc["answer"]["usd_by_remedy"].get("key_mismatch"), None)
        self.assertEqual(doc["answer"]["g7_usd_by_remedy"]["key_mismatch"], 20000.0)
        self.assertEqual(doc["status"], mod.STATUS_WARNING)

    def test_a_shifted_split_is_critical_not_a_warning(self):
        """Смена АДРЕСАТА — находка о деньгах, и она обязана звучать громче сдвига."""
        doc = mod.measure(_live_shape(self, base_days=[
            {"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0,
             "unpriced_protocols": ["pendle", "fluid_usdc"],
             "remedies_required": ["needs_polling", "writer_universe"]}]), now=_NOW)
        self.assertFalse(doc["answer"]["split_confirmed"])
        self.assertEqual(doc["answer"]["our_code_pct"], 100.0)
        self.assertEqual(doc["answer"]["g7_our_code_pct"], 0.0)
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)


class SufficiencyIsMeasuredNotAssumed(unittest.TestCase):
    """Достаточность набора проверяет НАСТОЯЩИЙ судья, а не построение."""

    def test_the_chosen_set_actually_returns_the_day_to_the_real_judge(self):
        doc = mod.measure(_live_shape(self), now=_NOW)
        control = doc["per_day"][0]["recovery_control"]
        self.assertTrue(control["structural"])
        self.assertTrue(control["replay"])
        self.assertEqual(control["granted_pairs"], [f"{_F1}×pendle"])

    def test_pairs_that_do_not_return_the_day_are_unmeasured_not_an_answer(self):
        """Сосед назвал парой то, что судья блокирующим не считает.

        Тогда правило подъёма прибора и `_evaluate_verdict` разошлись, и число,
        напечатанное поверх такого расхождения, было бы вымыслом. Здесь пара
        объявлена на ноге `maple`, которая на F1 оценена: выдача ей права ничего
        не меняет, день не возвращается.
        """
        doc = mod.measure(_live_shape(self, pairs=[_pair("maple", _F1)],
                                      history=[_decision(),
                                               _forward(_F1, {"maple": 4.9})]),
                          now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIsNone(doc["answer"])
        reasons = [r["reason"] for r in doc["population"]["unmeasured_days"]]
        self.assertTrue(any(mod.RECOVERY_DISAGREES in r for r in reasons), reasons)

    def test_a_redundant_set_is_refused_loudly_instead_of_overcharging_the_day(self):
        """Набор обязан быть МИНИМАЛЬНЫМ: лишний рычаг удорожает починку.

        Здесь сосед объявил на F1 пару по `maple` ВДОБАВОК к настоящей блокирующей
        `pendle`. День поднимается и без неё, значит набор избыточен — и записать
        дню лишний рычаг значило бы предъявить владельцу работу, которой нет.
        """
        doc = mod.measure(_live_shape(self, pairs=[
            _pair("pendle", _F1), _pair("maple", _F1)],
            history=[_decision(), _forward(_F1, {"fluid_usdc": 4.8})]), now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        reasons = [r["reason"] for r in doc["population"]["unmeasured_days"]]
        self.assertTrue(any(mod.NECESSITY_FAILED in r for r in reasons), reasons)


class HorizonCoverage(unittest.TestCase):
    """Форвардный день без пар — спор двух чтений, а не пустой набор."""

    def test_a_forward_day_with_no_blocking_pair_is_a_contradiction_not_a_free_lunch(self):
        """АВАРИЯ-класс: пустой набор объявил бы день поднятым БЕЗ рычагов.

        Если внутри горизонта есть форвардный день, о котором сосед не дал ни одной
        блокирующей пары, то день восстанавливался бы даром — а судья его отверг.
        Прочитать это как «рычагов не нужно» значило бы записать весь оборот дня в
        «починено» молча (инв. #17).
        """
        doc = mod.measure(_live_shape(self, pairs=[_pair("pendle", _F2),
                                                   _pair("fluid_usdc", _F2)]),
                          now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        reasons = [r["reason"] for r in doc["population"]["unmeasured_days"]]
        self.assertTrue(any(mod.FREE_FORWARD_DAY in r for r in reasons), reasons)
        self.assertTrue(any(_F1 in r for r in reasons), reasons)

    def test_forward_days_beyond_the_horizon_are_not_demanded(self):
        """Горизонт режется тем же числом, что у соседа: лишний день — не дыра.

        Мутация 13.09 показала, что прежняя редакция этого теста среза НЕ различала:
        снятие `[:horizon]` оставалось зелёным. Теперь за горизонтом лежит форвардный
        день БЕЗ единой пары — если срез снять, он прочтётся как дыра покрытия, и
        верный замер будет объявлен неизмеренным.
        """
        doc = mod.measure(_live_shape(self, horizon=1, pairs=[_pair("pendle", _F1)],
                                      history=[_decision(),
                                               _forward(_F1, {"fluid_usdc": 4.8,
                                                              "maple": 4.9}),
                                               _forward(_F2, {"pendle": 13.0,
                                                              "fluid_usdc": 4.8,
                                                              "maple": 4.9})]),
                          now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_WARNING)
        self.assertEqual(doc["per_day"][0]["chosen_forward_date"], _F1)


class SetCostIsAnOrderNotAMeasurement(unittest.TestCase):
    """Дешевизна НАБОРА — соглашение, и его цена обязана быть напечатана."""

    def test_incomparable_minimal_sets_are_named_and_the_swing_is_printed(self):
        """АВАРИЯ-класс: выдать соглашение за наблюдение.

        На живых данных 13.09 таких дней ТРИ, и обратный порядок цены сдвигает
        долю нашего кода с 94.87 % на 64.10 %. Прибор, молчащий об этом, подаёт
        договорённость как замер.
        """
        ddir = _live_shape(self, pairs=[
            _pair("pendle", _F1),
            _pair("pendle", _F2, causes.CLASS_NOT_LIVE),
        ], history=[_decision(),
                    _forward(_F1, {"fluid_usdc": 4.8, "maple": 4.9}),
                    _forward(_F2, {"fluid_usdc": 4.8, "maple": 4.9})],
            base_days=[{"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
                        "turnover_usd": 20000.0, "unpriced_protocols": ["pendle"],
                        "remedies_required": ["writer_universe"]}])
        doc = mod.measure(ddir, now=_NOW)
        day = doc["per_day"][0]
        self.assertTrue(day["order_decides"])
        self.assertEqual(day["minimal_by_inclusion"],
                         [["feed_outage"], ["writer_universe"]])
        sens = doc["order_sensitivity"]
        self.assertEqual(sens["days_where_order_decides"], [_DAY])
        self.assertEqual(sens["our_code_pct_declared"], 100.0)
        self.assertEqual(sens["our_code_pct_owner_first"], 0.0)
        self.assertEqual(sens["swing_usd"], 20000.0)
        self.assertTrue(any("НЕСРАВНИМЫ" in f for f in doc["findings"]))

    def test_a_single_minimal_set_makes_the_answer_order_independent(self):
        """Зеркало предыдущего: где минимальный набор ОДИН, соглашение не решает.

        Без этого контроля «порядок решает» было бы истинным по построению.
        """
        doc = mod.measure(_live_shape(self), now=_NOW)
        day = doc["per_day"][0]
        self.assertFalse(day["order_decides"])
        self.assertEqual(day["minimal_by_inclusion"], [["writer_universe"]])
        self.assertEqual(doc["order_sensitivity"]["days_where_order_decides"], [])

    def test_zero_contested_days_are_printed_not_silently_omitted(self):
        """«Измерено и равно нулю» обязано отличаться от «не измерено» (инв. #17)."""
        doc = mod.measure(_live_shape(self), now=_NOW)
        self.assertTrue(any(f.startswith("[ОПОРА] ни на одном дне порядок цены")
                            for f in doc["findings"]), doc["findings"])

    def test_an_unknown_remedy_ranks_worst_not_cheapest(self):
        """Класс вне объявленного порядка не смеет молча выиграть у известных."""
        order = list(mod._g7.REMEDY_COST_ORDER)
        self.assertGreater(mod._set_cost(frozenset({"brand_new"}), order),
                           mod._set_cost(frozenset({mod._g7.REMEDY_NEEDS_POLLING}),
                                         order))

    def test_a_strict_subset_always_wins_regardless_of_the_declared_order(self):
        """Порядок обязан быть МОНОТОННЫМ: меньший набор не может стоить дороже."""
        order = list(mod._g7.REMEDY_COST_ORDER)
        small = frozenset({mod._g7.REMEDY_WRITER_UNIVERSE})
        big = frozenset({mod._g7.REMEDY_WRITER_UNIVERSE, mod._g7.REMEDY_KEY_MISMATCH})
        self.assertLess(mod._set_cost(small, order), mod._set_cost(big, order))

    def test_minimal_by_inclusion_drops_supersets_only(self):
        sets = {frozenset({"a"}), frozenset({"a", "b"}), frozenset({"c"})}
        self.assertEqual(mod._minimal_by_inclusion(sets),
                         [frozenset({"a"}), frozenset({"c"})])


class ThirdOutcome(unittest.TestCase):
    """Отсутствие наблюдения — ОТДЕЛЬНОЕ значение, а не ноль и не «совпало»."""

    def test_unreadable_polled_list_refuses_instead_of_blaming_the_owner(self):
        """«Не прочитан» НЕ читается как «не опрашивается».

        Иначе отказ импорта тихо переложил бы весь слепой оборот владельцу.
        """
        saved = mod._g7._polled_keys
        mod._g7._polled_keys = lambda: None
        self.addCleanup(lambda: setattr(mod._g7, "_polled_keys", saved))
        doc = mod.measure(Path("/nonexistent"), now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["unmeasured_reason"], mod.NO_POLLED)
        self.assertIsNone(doc["answer"])

    def test_a_refusing_g7_is_not_read_as_an_agreeing_split(self):
        doc = mod.measure(_live_shape(self, base_days=[], base_status="UNMEASURED"),
                          now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn(mod.NO_G7, doc["unmeasured_reason"])

    def test_a_refusing_causes_neighbour_is_unmeasured(self):
        ddir = _live_shape(self)
        mod._causes.measure = lambda *a, **k: {"status": "UNMEASURED",
                                               "horizon_days": 7}
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn(mod.NO_CAUSES, doc["unmeasured_reason"])

    def test_an_empty_journal_is_unmeasured_not_an_empty_horizon(self):
        doc = mod.measure(_live_shape(self, history=[]), now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["unmeasured_reason"], mod.NO_JOURNAL)

    def test_a_day_without_pairs_is_unmeasured_not_raised_for_free(self):
        doc = mod.measure(_live_shape(self, pairs=[]), now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        reasons = [r["reason"] for r in doc["population"]["unmeasured_days"]]
        self.assertIn(mod.DAY_NO_PAIRS, reasons)

    def test_the_accounting_identity_makes_a_dropped_day_loud(self):
        doc = mod.measure(_live_shape(self, pairs=[]), now=_NOW)
        pop = doc["population"]
        self.assertTrue(pop["accounting_identity_holds"])
        self.assertEqual(pop["measured_days"] + len(pop["unmeasured_days"]),
                         pop["g7_days"])

    def test_a_mixed_outcome_names_the_unmeasured_day_and_not_only_counts_it(self):
        """ДЕФЕКТ, найденный батареей мутаций 13.09.

        Когда часть дней разложена, а часть нет, статус уже UNMEASURED — но findings
        печатали только долю, посчитанную на УЦЕЛЕВШЕМ населении, и о выпавшем дне
        молчали. «Не измерено», которое считают, но не произносят, неотличимо от
        чистого прогона для того, кто читает отчёт, а не JSON.
        """
        doc = mod.measure(_live_shape(self, base_days=[
            {"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0,
             "unpriced_protocols": ["pendle", "fluid_usdc"],
             "remedies_required": ["key_mismatch", "writer_universe"]},
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 40000.0,
             "turnover_usd": 40000.0, "unpriced_protocols": ["pendle"],
             "remedies_required": ["writer_universe"]},
        ]), now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["population"]["measured_days"], 1)
        named = [f for f in doc["findings"] if f.startswith("[НЕ ИЗМЕРЕНО]")]
        self.assertTrue(any("2026-09-08" in f for f in named), doc["findings"])

    def test_the_status_alone_carries_an_unchecked_count(self):
        """Мутация 13.09: терм статуса в `counts` можно было снять незаметно.

        В смешанном исходе ответ ЕСТЬ, поэтому вклад дают обе половины счёта —
        и снятие любой из них обязано быть видно.
        """
        ddir = _live_shape(self, base_days=[
            {"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0,
             "unpriced_protocols": ["pendle", "fluid_usdc"],
             "remedies_required": ["key_mismatch", "writer_universe"]},
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 40000.0,
             "turnover_usd": 40000.0, "unpriced_protocols": ["pendle"],
             "remedies_required": ["writer_universe"]},
        ])
        doc = mod.run(root=str(ddir.parent), write=False)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["counts"]["unchecked"], 2)

    def test_unchecked_is_counted_apart_from_zeros(self):
        """Растворив «не измерено» в нулях, отчёт стал бы неотличим от чистого."""
        ddir = _live_shape(self, pairs=[])
        doc = mod.run(root=str(ddir.parent), write=False)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)


class ArtifactCarriesItsOwnLimits(unittest.TestCase):
    """Границы утверждения — в АРТЕФАКТЕ: читатель отчёта шапку не открывает."""

    def test_what_it_does_not_prove_travels_with_the_number(self):
        doc = mod.measure(_live_shape(self), now=_NOW)
        self.assertTrue(doc["what_it_does_not_prove"])
        joined = " ".join(doc["what_it_does_not_prove"])
        self.assertIn("не объявляет ответ G7 неверным", joined)
        self.assertIn("ПОТОЛКОМ", joined)

    def test_the_report_is_the_findings_and_names_both_splits(self):
        doc = mod.measure(_live_shape(self), now=_NOW)
        lines = mod.format_report(doc)
        self.assertEqual(lines, doc["findings"])
        self.assertTrue(any(l.startswith("[РАСКЛАДКА]") for l in lines))
        self.assertTrue(any("против $20,000.00 у G7" in l for l in lines))


class NeighboursAreCalledByModuleReference(unittest.TestCase):
    """Связанное при импорте имя есть СНИМОК: подмена правила прошла бы молча."""

    def test_the_pair_remedy_rule_is_taken_from_g7_at_call_time(self):
        ddir = _live_shape(self)
        saved = mod._g7._pair_remedy
        mod._g7._pair_remedy = lambda *a, **k: {"remedy": "brand_new", "why": "x"}
        self.addCleanup(lambda: setattr(mod._g7, "_pair_remedy", saved))
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["per_day"][0]["remedies_required"], ["brand_new"])

    def test_the_cost_order_is_taken_from_g7_and_not_copied_here(self):
        self.assertFalse(hasattr(mod, "REMEDY_COST_ORDER"))
        self.assertFalse(hasattr(mod, "OUR_CODE_REMEDIES"))


class AbsentListOfUnmeasuredDaysIsItsOwnOutcome(unittest.TestCase):
    """Отсутствующий перечень неизмеренных дней ≠ пустой перечень (инв. #17).

    Батарея мутаций цикла #593 нашла эту починку НЕЗАКРЕПЛЁННОЙ: снимок батареи
    #592 снят в 18:01:37, а `_name_unmeasured_days` написана в 18:11:08 — то есть
    измерена была ДРУГАЯ редакция файла. Все четыре координаты поздней починки
    ВЫЖИВАЛИ: честное чтение можно было вернуть к `pop.get(...) or []`, снять
    третий исход, обезмолвить отказ или отцепить починку от потребителя — и набор
    оставался зелёным. Починка без положительного контроля есть украшение
    (`.claude/rules/deployment.md`), поэтому контроль здесь — в ОБЕ стороны.
    """

    def test_absent_list_names_the_third_outcome_instead_of_claiming_completeness(self):
        """`pop.get(...) or []` объявил бы население полным, ни разу его не измерив."""
        lines = mod._name_unmeasured_days({})
        self.assertEqual(len(lines), 1)
        self.assertIn("не несёт перечня", lines[0])
        self.assertIn("[НЕ ИЗМЕРЕНО]", lines[0])

    def test_the_refusal_names_its_reason_and_is_not_mute(self):
        """Пустой список вместо названной причины — «не измерено», которого не слышно."""
        self.assertTrue(all(l.strip() for l in mod._name_unmeasured_days({})))

    def test_empty_list_is_a_different_assertion_than_an_absent_one(self):
        """Пустой перечень утверждает «таких дней НЕТ» — и молчать тут верно."""
        self.assertEqual(mod._name_unmeasured_days({"unmeasured_days": []}), [])

    def test_present_days_are_named_one_by_one(self):
        lines = mod._name_unmeasured_days(
            {"unmeasured_days": [{"cycle_date": _DAY, "reason": "пар нет"}]})
        self.assertEqual(len(lines), 1)
        self.assertIn(_DAY, lines[0])
        self.assertIn("пар нет", lines[0])

    def test_the_naming_is_wired_into_the_unmeasured_branch_of_the_report(self):
        """Проводка у ПОТРЕБИТЕЛЯ: отцепив починку от ветки, отчёт снова молчит."""
        doc = {"population": {"unmeasured_days": [{"cycle_date": _DAY,
                                                   "reason": "пар нет"}]},
               "answer": {"measured": False},
               "unmeasured_reason": "журнал не прочитан"}
        lines = mod._findings(doc)
        self.assertTrue(any(_DAY in l and "пар нет" in l for l in lines))

    def test_the_unmeasured_branch_also_reports_an_absent_list(self):
        doc = {"population": {}, "answer": {"measured": False},
               "unmeasured_reason": "журнал не прочитан"}
        lines = mod._findings(doc)
        self.assertTrue(any("не несёт перечня" in l for l in lines))


class SurvivorsOfTheCycle594Battery(unittest.TestCase):
    """Четыре координаты, ВЫЖИВШИЕ в батарее цикла #594, и ни одна не эквивалентна.

    Батарея #594 отбирала координаты по СВОЕМУ принципу — не по строкам файла
    (#592) и не по утверждениям автора (#593), а по каждой ГАРАНТИИ, которую
    ADR-373 продаёт владельцу, и по каждому ОТКАЗУ прибора. Разный принцип отбора
    нашёл разное: из 25 координат 17 красных, и разбор восьми выживших отделил
    РЕЗЕРВИРОВАНИЕ (пара «структурный предикат / реплей» — снятие ОБОИХ красное)
    от настоящих дыр НАБОРА. Дыры закрыты здесь.

    Общее у всех четырёх: они про число и про ярлык, которые читает ВЛАДЕЛЕЦ, —
    доля нашего кода, адресат починки, полнота населения. Именно там молчание
    набора стоит дороже всего.
    """

    def test_the_accounting_identity_is_computed_and_not_a_literal(self):
        """Тождество истинно ПО ПОСТРОЕНИЮ ⇒ поведенческого контроля у него нет.

        Замер #594: подмена вычисления на литеральный ``True`` НЕ покрасила ни
        одного теста — то есть проверка, которой файл хвалится («уронить день
        МОЛЧА нельзя»), сегодня не проверяет ничего. Ценность её вся в будущем:
        первый же новый ``continue`` в разборе дней обязан сделать вердикт
        громким. Поэтому утверждение структурное (AST): по подстроке оно пережило
        бы любое расплетение. Сосед `unobserved_leg_remedy_class` закрыт тем же
        способом — второй копии правила здесь не появляется, появляется второй
        экземпляр ЗАЩИТЫ, и это разные вещи.
        """
        import ast

        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "accounting_identity_holds":
                    found.append(value)
        self.assertEqual(len(found), 1, "координата тождества не одна — замер о другом")
        self.assertIsInstance(
            found[0], ast.Compare,
            "тождество записано константой: сторож перестал что-либо мерить")
        names = {n.id for n in ast.walk(found[0]) if isinstance(n, ast.Name)}
        # `len` — тоже Name; перечисляется явно, чтобы утверждение осталось
        # РАВЕНСТВОМ: подмножество пропустило бы тождество, потерявшее слагаемое.
        self.assertEqual(names, {"len", "per_day", "unmeasured_days", "base_days"})

    def test_a_false_identity_makes_the_verdict_unmeasured(self):
        """Вторая половина той же защиты: вердикт обязан РЕАГИРОВАТЬ на ложь.

        «Тождество вычисляется» и «вердикт его читает» — разные утверждения, и
        закрывать надо оба: вычисленное, но никем не прочитанное тождество столь
        же немо, сколь константа.
        """
        doc = {"population": {"accounting_identity_holds": False},
               "answer": {"measured": True, "split_confirmed": True}, "per_day": []}
        self.assertEqual(mod._status(doc), mod.STATUS_UNMEASURED)

    def test_a_mixed_set_is_named_mixed_and_not_credited_to_our_code(self):
        """Ярлык адресата — то, по чему читатель решает, КОГО просить о починке.

        Замер #594: подмена ветки «смешанный — нужны оба» на «наш код» не красила
        ничего. Ход такой ошибки прямой: день, которому нужен И наш код, И
        проводка `POLLED_ADAPTERS` (money-path, решение владельца), предъявлялся
        бы владельцу как починка, лежащая целиком у нас, — ровно та подмена
        адресата, которую ADR-369 поймал у себя ценой сдвига 74.36 → 94.87 %.
        """
        ddir = _live_shape(
            self,
            base_days=[{"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
                        "turnover_usd": 20000.0,
                        "unpriced_protocols": ["pendle", "spark_susds"],
                        "remedies_required": ["needs_polling", "writer_universe"]}],
            pairs=[_pair("pendle", _F1), _pair("spark_susds", _F1)],
            history=[_mixed_decision(), _forward(_F1, {"maple": 4.9})],
            polled=("pendle",),
        )
        doc = mod.measure(ddir, now=_NOW)
        day = doc["per_day"][0]
        self.assertEqual(sorted(day["remedies_required"]),
                         ["needs_polling", "writer_universe"])
        self.assertEqual(day["lever_owner"], "смешанный — нужны оба")
        self.assertEqual(doc["answer"]["our_code_usd"], 0.0)

    def test_a_set_equal_to_our_code_counts_as_ours(self):
        """Доля нашего кода считается ПОДМНОЖЕСТВОМ, а не СТРОГИМ подмножеством.

        Замер #594: подмена ``<=`` на ``<`` пережила набор, потому что на живой
        форме ни один день не выбирает РОВНО оба наших рычага — 2026-09-06
        поднимается одним писателем. Сцена отсутствовала, и без неё главное число
        отчёта («наш код 94.87 %») держалось на том, что таких дней пока не
        встретилось. Здесь день выбирает ровно {key_mismatch, writer_universe};
        под строгим подмножеством он молча уехал бы к владельцу.
        """
        ddir = _live_shape(
            self,
            base_days=[{"cycle_date": _DAY, "unpriced_gross_usd": 20000.0,
                        "turnover_usd": 20000.0,
                        "unpriced_protocols": ["pendle", "fluid_usdc"],
                        "remedies_required": ["key_mismatch", "writer_universe"]}],
            pairs=[_pair("pendle", _F2), _pair("fluid_usdc", _F2)],
            history=[_decision(), _forward(_F2, {"fluid_fusdc": 4.4, "maple": 4.9})],
        )
        doc = mod.measure(ddir, now=_NOW)
        day = doc["per_day"][0]
        self.assertEqual(sorted(day["remedies_required"]),
                         ["key_mismatch", "writer_universe"])
        self.assertEqual(day["lever_owner"], "наш код")
        self.assertEqual(doc["answer"]["our_code_usd"], 20000.0)
        self.assertEqual(doc["answer"]["our_code_pct"], 100.0)


class WiringIsGuardedAndNotMerelyClaimed(unittest.TestCase):
    """Проводка «при рождении» ЗАЯВЛЕНА в ADR-373 — измерено, что половина её нема.

    Батарея проводки цикла #594 гнала 8 координат по ШИРОКОМУ населению — 294 теста
    восьми файлов, которые вообще могут о проводке знать (сам прибор, бегун переписей,
    шаг 0-офис, манифест, парити-тесты). Красных 4, **выживших 4**, и выжившие —
    ровно те места, где заявка ADR ничем не закреплена:

    | снятое звено | что было бы дальше | было |
    |---|---|---|
    | имя в `CENSUS_STAGE` | бегун перестаёт звать прибор — артефакт не рождается вовсе | зелено |
    | путь в `PRODUCES` | артефакт исчезает из состава продуктов бегуна | зелено |
    | `order_sensitivity` в схеме шага 0-офис | ADR обещает «шаг 0-офис отказывает при его отсутствии» — не отказывал бы | зелено |
    | ветка форматтера в шаге 0-офис | отчёт владельцу молча теряет ВСЕ строки прибора | зелено |

    Первая строка — не гипотеза: сосед по ступени (`unobserved_leg_remedy_class`)
    ровно в этот день числится в составе ступени, бегун её звал, а артефакта в проде
    НЕТ, и шаг 0-офис доложил «❌ НЕ ПРОЧИТАН» (карточка
    `inbox-begun-perepisei-ne-soobschaet-chto-proiz`). Незакреплённая проводка — это
    не будущий риск, это сегодняшняя авария у соседа.

    Проверки здесь СТРУКТУРНЫЕ и ПОВЕДЕНЧЕСКИЕ, а не по подстроке: тест проводки по
    подстроке переживает любое расплетение. Ветка отрисовки проверяется ВЫЗОВОМ.
    """

    ARTIFACT = "remedy_class_single_forward_day.json"
    STAGE_KEY = "remedy_class_single_forward_day"

    def test_the_census_runner_actually_calls_this_instrument(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(self.STAGE_KEY, findings_bridge.CENSUS_STAGE)

    def test_the_artifact_is_declared_among_the_runners_products(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(f"data/{self.ARTIFACT}", findings_bridge.PRODUCES)

    def test_the_stage_passport_names_module_and_artifact(self):
        from spa_core.monitoring import findings_bridge
        self.assertEqual(
            findings_bridge.CENSUS_PRODUCT[self.STAGE_KEY],
            {"module": f"spa_core/monitoring/{self.STAGE_KEY}.py",
             "artifact": f"data/{self.ARTIFACT}"})

    def _office(self):
        import importlib.util
        script = Path(mod.__file__).resolve().parents[2] / "scripts" / "consume_office_reports.py"
        spec = importlib.util.spec_from_file_location("_office_for_g9", script)
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        return office

    def test_the_office_step_requires_the_price_of_the_convention(self):
        """`order_sensitivity` обязателен НАРАВНЕ с ответом, а не примечанием.

        Доля «наш код 94.87 %» на трёх днях из восьми решается объявленным порядком
        цены, а не наблюдением. Артефакт без этого ключа подал бы соглашение как
        замер — то есть ровно тот дефект, ради которого писан весь ряд G6→G9.
        """
        office = self._office()
        required = office._READ_SCHEMA[self.ARTIFACT]
        self.assertIn("order_sensitivity", required)
        self.assertIn("answer", required)
        self.assertIn("per_day", required)

    def test_the_office_step_knows_who_produces_the_artifact(self):
        office = self._office()
        self.assertEqual(office._PRODUCER[self.ARTIFACT],
                         f"spa_core/monitoring/{self.STAGE_KEY}.py")

    def test_the_office_step_renders_the_instruments_own_lines(self):
        """Ветка отрисовки проверяется ВЫЗОВОМ — иначе отчёт молча онемеет.

        Здесь важно не «строка похожа», а «печатает ИМЕННО форматтер прибора»:
        generic-ветка шага 0-офис тоже что-нибудь напечатает, и отличить её от
        честной отрисовки по виду строки нельзя.
        """
        office = self._office()
        ddir = _live_shape(self)
        doc = mod.measure(ddir, now=_NOW)
        lines = [l for l in office._summarize_json(f"data/{self.ARTIFACT}", doc,
                                                   now=_NOW) if l.strip()]
        mine = [l for l in mod.format_report(doc) if l.strip()]
        # Шапка шага (возраст артефакта) — его собственная; предмет утверждения в
        # том, что ДАЛЬШЕ идут строки ИМЕННО этого форматтера, все и в его порядке.
        self.assertEqual(lines[-len(mine):], mine)
        self.assertTrue(mine, "форматтер не дал ни строки — сравнивать было бы не с чем")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

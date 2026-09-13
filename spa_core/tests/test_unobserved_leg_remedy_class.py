"""Сторожа прибора «какой рычаг поднял бы слепой оборот» (заказ #590/G7).

Каждый тест здесь — положительный контроль на дефект, который замер 13.09 реально
изготовил или едва не изготовил. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md`).

Главный из них: ПОРЯДОК проверки близнеца. Первая редакция спрашивала близнеца только
у класса «в книгах, но провенанс не live», и на живых данных это записало $40 000 дня
2026-09-10 в `needs_polling` — то есть отправило владельцу в money-path починку,
которая целиком лежит в нашем коде. Нога `fluid_usdc` значилась ВНЕ книг ровно потому,
что дерево переименовало позицию в `fluid_fusdc`, и та в той же записи имела живую
ставку.

FROZEN-DATE-OK: injected-clock — все даты здесь либо ключи-даты фикстур (предмет
замера, не свежесть), либо якорь `_NOW`, который передаётся приборам параметром
``now=``; стенных часов ни один тест не спрашивает.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import unevidenced_leg_causes as causes
from spa_core.monitoring import unobserved_leg_remedy_class as mod

#: Якорь времени — ВХОД приборов, а не окружение: обе стороны закреплены, тест
#: бессмертен (порядок предпочтения №1, `.claude/rules/deployment.md`).
_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)

_POLLED = {"aave_v3", "pendle", "fluid_fusdc"}
_TWINS = {"fluid_usdc": ["fluid_fusdc"], "fluid_fusdc": ["fluid_usdc"]}


def _pair(protocol: str, klass: str, forward: str = "2026-09-11") -> dict:
    return {"decision_date": "2026-09-10", "forward_date": forward,
            "protocol": protocol, "class": klass}


class PairRemedy(unittest.TestCase):
    """Рычаг ОДНОЙ пары «форвардный день × нога»."""

    def test_absent_leg_with_a_live_twin_is_a_key_mismatch_not_a_polling_gap(self):
        """АВАРИЯ 13.09: близнец спрашивался только у класса «не live».

        `fluid_usdc` 2026-09-10 значится ВНЕ книг именно потому, что деньги
        переименованы в `fluid_fusdc`, и та в ТОЙ ЖЕ записи имеет живую ставку.
        Первая редакция отвечала `needs_polling` — $40 000 уезжали владельцу как
        money-path, хотя рычаг у нас. Контроль обязан краснеть при возврате порядка.
        """
        verdict = mod._pair_remedy(
            _pair("fluid_usdc", causes.CLASS_ABSENT),
            polled=_POLLED, twins=_TWINS,
            forward_record={"apy_evidenced_pct": {"fluid_fusdc": 4.38}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_KEY_MISMATCH)
        self.assertEqual(verdict["twin"], "fluid_fusdc")

    def test_not_live_leg_with_a_live_twin_is_a_key_mismatch(self):
        verdict = mod._pair_remedy(
            _pair("fluid_usdc", causes.CLASS_NOT_LIVE),
            polled=_POLLED, twins=_TWINS,
            forward_record={"apy_evidenced_pct": {"fluid_fusdc": 4.63}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_KEY_MISMATCH)

    def test_twin_that_is_not_priced_in_that_record_is_not_a_key_mismatch(self):
        """Близнец ЕСТЬ, но ставки его в этой записи нет ⇒ рычаг не наш.

        Без этого контроля правило «у ноги есть близнец» подменило бы правило «ставка
        тех же денег ЛЕЖИТ в этой записи», и класс `key_mismatch` стал бы истинным по
        построению для любой переименованной ноги.
        """
        verdict = mod._pair_remedy(
            _pair("fluid_usdc", causes.CLASS_NOT_LIVE),
            polled=_POLLED, twins=_TWINS,
            forward_record={"apy_evidenced_pct": {"aave_v3": 3.1}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_FEED_OUTAGE)

    def test_absent_leg_that_is_polled_is_the_writers_line(self):
        verdict = mod._pair_remedy(
            _pair("pendle", causes.CLASS_ABSENT),
            polled=_POLLED, twins={}, forward_record={"apy_evidenced_pct": {}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_WRITER_UNIVERSE)

    def test_absent_leg_that_is_not_polled_is_the_owners_lever(self):
        """Писатель не может записать ставку, которой никто не спрашивал.

        Уложить такой доллар в «наша строка» значило бы пообещать починку, которой в
        нашем коде нет, — и развилка приказа была бы разрешена в одну сторону ложно.
        """
        verdict = mod._pair_remedy(
            _pair("spark_susds", causes.CLASS_ABSENT),
            polled=_POLLED, twins={}, forward_record={"apy_evidenced_pct": {}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_NEEDS_POLLING)

    def test_unknown_class_is_the_third_outcome_not_the_likeliest_bucket(self):
        verdict = mod._pair_remedy(
            _pair("pendle", "some_new_class"),
            polled=_POLLED, twins={}, forward_record={"apy_evidenced_pct": {}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_UNATTRIBUTABLE)

    def test_a_none_rate_does_not_count_as_a_live_twin(self):
        """`None` под ключом близнеца — отсутствие наблюдения, а не наблюдение.

        Инвариант #17: три исхода обязаны быть различимы. Считать ключ с `None`
        живой ставкой значило бы выдать «не измерено» за измеренное.
        """
        verdict = mod._pair_remedy(
            _pair("fluid_usdc", causes.CLASS_NOT_LIVE),
            polled=_POLLED, twins=_TWINS,
            forward_record={"apy_evidenced_pct": {"fluid_fusdc": None}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_FEED_OUTAGE)

    def test_a_bool_rate_does_not_count_as_a_live_twin(self):
        verdict = mod._pair_remedy(
            _pair("fluid_usdc", causes.CLASS_NOT_LIVE),
            polled=_POLLED, twins=_TWINS,
            forward_record={"apy_evidenced_pct": {"fluid_fusdc": True}})
        self.assertEqual(verdict["remedy"], mod.REMEDY_FEED_OUTAGE)

    def test_a_missing_forward_record_is_not_a_live_twin(self):
        verdict = mod._pair_remedy(
            _pair("fluid_usdc", causes.CLASS_NOT_LIVE),
            polled=_POLLED, twins=_TWINS, forward_record=None)
        self.assertEqual(verdict["remedy"], mod.REMEDY_FEED_OUTAGE)


class CheapestRemedy(unittest.TestCase):
    """Ноге довольно ОДНОГО форвардного дня со ставкой ⇒ берётся дешёвый рычаг."""

    def test_leg_with_both_classes_takes_the_cheaper_lever(self):
        self.assertEqual(
            mod._cheapest([mod.REMEDY_NEEDS_POLLING, mod.REMEDY_KEY_MISMATCH]),
            mod.REMEDY_KEY_MISMATCH)

    def test_writer_line_is_cheaper_than_the_owners_levers(self):
        self.assertEqual(
            mod._cheapest([mod.REMEDY_NEEDS_POLLING, mod.REMEDY_WRITER_UNIVERSE]),
            mod.REMEDY_WRITER_UNIVERSE)

    def test_empty_is_unattributable_not_the_first_lever(self):
        self.assertEqual(mod._cheapest([]), mod.REMEDY_UNATTRIBUTABLE)

    def test_cost_order_covers_every_remedy_constant(self):
        """Новый рычаг, забытый в порядке дешевизны, молча стал бы самым дорогим."""
        declared = {v for k, v in vars(mod).items()
                    if k.startswith("REMEDY_") and isinstance(v, str)}
        self.assertEqual(declared, set(mod.REMEDY_COST_ORDER))


class TwinKeys(unittest.TestCase):
    """Близнецы — у ДВОЙНОЙ ЗАПИСИ, а не из похожести имён."""

    def _write(self, trades: list) -> Path:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ddir = Path(tmp.name)
        (ddir / "trades.json").write_text(json.dumps(trades), encoding="utf-8")
        return ddir

    def test_equal_sums_rename_is_a_twin_pair_both_ways(self):
        ddir = self._write([
            {"trade_id": "T1", "ts": "2026-09-10T00:00:00",
             "from_allocation": {"fluid_usdc": 20000.0},
             "to_allocation": {"fluid_usdc": 20000.0}},
            {"trade_id": "T2", "ts": "2026-09-11T00:00:00",
             "from_allocation": {"fluid_fusdc": 20000.0},
             "to_allocation": {"fluid_fusdc": 20000.0}},
        ])
        out = mod._twin_keys(ddir)
        self.assertTrue(out["measured"])
        self.assertEqual(out["pairs"]["fluid_usdc"], ["fluid_fusdc"])
        self.assertEqual(out["pairs"]["fluid_fusdc"], ["fluid_usdc"])

    def test_a_money_gap_is_not_a_rename_and_yields_no_twin(self):
        """Разные суммы ⇒ это дыра в записи, а не переименование.

        Взять её за близнеца значило бы объявить одними деньгами то, что двойная
        запись как раз и не свела.
        """
        ddir = self._write([
            {"trade_id": "T1", "ts": "2026-09-10T00:00:00",
             "from_allocation": {"fluid_usdc": 20000.0},
             "to_allocation": {"fluid_usdc": 20000.0}},
            {"trade_id": "T2", "ts": "2026-09-11T00:00:00",
             "from_allocation": {"fluid_fusdc": 5000.0},
             "to_allocation": {"fluid_fusdc": 5000.0}},
        ])
        self.assertEqual(mod._twin_keys(ddir)["pairs"], {})

    def test_many_to_many_rename_is_recorded_but_not_used_as_evidence(self):
        """Кто чей близнец, двойная запись при равных суммах НЕ различает.

        Молча выбрать пару значило бы изготовить провенанс денег из ничего.
        """
        ddir = self._write([
            {"trade_id": "T1", "ts": "2026-09-10T00:00:00",
             "from_allocation": {"a": 10.0, "b": 10.0},
             "to_allocation": {"a": 10.0, "b": 10.0}},
            {"trade_id": "T2", "ts": "2026-09-11T00:00:00",
             "from_allocation": {"c": 10.0, "d": 10.0},
             "to_allocation": {"c": 10.0, "d": 10.0}},
        ])
        out = mod._twin_keys(ddir)
        self.assertEqual(out["pairs"], {})
        self.assertTrue(any(r["used"] is False for r in out["renames"]))

    def test_name_similarity_alone_never_makes_a_twin(self):
        """`fluid_arbitrum` по виду имени такой же близнец, а по деньгам — нет."""
        ddir = self._write([
            {"trade_id": "T1", "ts": "2026-09-10T00:00:00",
             "from_allocation": {"fluid_usdc": 20000.0},
             "to_allocation": {"fluid_usdc": 20000.0}},
        ])
        out = mod._twin_keys(ddir)
        self.assertNotIn("fluid_arbitrum", out["pairs"])

    def test_missing_journal_is_unmeasured_with_a_named_reason(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = mod._twin_keys(Path(tmp.name))
        self.assertFalse(out["measured"])
        self.assertTrue(out.get("reason"))


class PolledKeys(unittest.TestCase):
    def test_unreadable_polled_list_is_unmeasured_not_not_polled(self):
        """«Не прочитан» не читается как «не опрашивается».

        Иначе отказ импорта тихо переложил бы весь слепой оборот владельцу.
        """
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = []
            self.assertIsNone(mod._polled_keys())
        finally:
            orch.POLLED_ADAPTERS = saved

    def test_entry_of_unexpected_shape_is_unmeasured_not_a_dropped_key(self):
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = [("aave_v3", "T1", object()), "bare_string"]
            self.assertIsNone(mod._polled_keys())
        finally:
            orch.POLLED_ADAPTERS = saved

    def test_the_live_polled_list_is_readable(self):
        keys = mod._polled_keys()
        self.assertIsNotNone(keys)
        assert keys is not None
        self.assertIn("aave_v3", keys)


class _Stub:
    """Подставные соседи: предмет теста — СБОРКА, а не их замеры."""

    def __init__(self, dep: dict, causes_doc: dict):
        self.dep, self.causes = dep, causes_doc


def _install(test, dep_days, pairs, *, twins=None, history=None):
    """Подменить обоих соседей и близнецов; вернуть каталог данных."""
    tmp = TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    ddir = Path(tmp.name)

    dep_doc = {"status": "WARNING", "per_day": dep_days}
    causes_doc = {"status": "CRITICAL", "attribution": pairs}
    test_history = history if history is not None else []

    orig = (mod._dep.measure, mod._causes.measure, mod._twin_keys,
            mod._dep._ste.load_history)
    mod._dep.measure = lambda *a, **k: dep_doc
    mod._causes.measure = lambda *a, **k: causes_doc
    mod._twin_keys = lambda *a, **k: {"measured": True,
                                      "pairs": twins or {}, "renames": []}
    mod._dep._ste.load_history = lambda *a, **k: (test_history, 0)

    def restore():
        (mod._dep.measure, mod._causes.measure, mod._twin_keys,
         mod._dep._ste.load_history) = orig
    test.addCleanup(restore)
    return ddir


class Assembly(unittest.TestCase):
    """Сборка дня: НАБОР рычагов, доллары и вердикт."""

    def test_day_needing_two_levers_is_named_mixed_and_counted_to_the_owner(self):
        """АВАРИЯ-класс: растворить смешанный день в дешёвом рычаге.

        2026-08-24 держится ногами `morpho_blue` (наш код) и `spark_susds` (владелец).
        День поднимается, ТОЛЬКО если подняты обе; записать его в «наш код» значило бы
        удешевить починку на бумаге и разрешить развилку приказа ложно.
        """
        ddir = _install(self, [
            {"cycle_date": "2026-08-24", "unpriced_gross_usd": 10000.0,
             "turnover_usd": 10000.0,
             "unpriced_protocols": ["morpho_blue", "spark_susds"]},
        ], [
            {"decision_date": "2026-08-24", "forward_date": "2026-08-25",
             "protocol": "morpho_blue", "class": causes.CLASS_ABSENT},
            {"decision_date": "2026-08-24", "forward_date": "2026-08-25",
             "protocol": "spark_susds", "class": causes.CLASS_ABSENT},
        ])
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = [("morpho_blue", "T2", object())]
            doc = mod.measure(ddir, now=_NOW)
        finally:
            orch.POLLED_ADAPTERS = saved

        day = doc["per_day"][0]
        self.assertEqual(day["remedies_required"],
                         [mod.REMEDY_NEEDS_POLLING, mod.REMEDY_WRITER_UNIVERSE])
        self.assertEqual(day["lever_owner"], "смешанный — нужны оба")
        self.assertEqual(doc["answer"]["owner_lever_usd"], 10000.0)
        self.assertEqual(doc["answer"]["our_code_usd"], 0.0)
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)

    def test_day_whose_every_leg_is_ours_is_counted_to_our_code(self):
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0, "unpriced_protocols": ["pendle"]},
        ], [
            {"decision_date": "2026-09-08", "forward_date": "2026-09-09",
             "protocol": "pendle", "class": causes.CLASS_ABSENT},
        ])
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = [("pendle", "T2", object())]
            doc = mod.measure(ddir, now=_NOW)
        finally:
            orch.POLLED_ADAPTERS = saved
        self.assertEqual(doc["answer"]["our_code_usd"], 20000.0)
        self.assertEqual(doc["answer"]["owner_lever_usd"], 0.0)
        self.assertEqual(doc["status"], mod.STATUS_OK)

    def test_leg_without_a_single_pair_makes_the_day_unmeasured_not_dropped(self):
        """Два чтения одного дня спорят ⇒ день в «не измерено», а не в тишину.

        Молча выбросив его, прибор занизил бы и итог, и долю владельца.
        """
        ddir = _install(self, [
            {"cycle_date": "2026-09-01", "unpriced_gross_usd": 10000.0,
             "turnover_usd": 10000.0, "unpriced_protocols": ["aave_v3_base"]},
        ], [])
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["per_day"], [])
        self.assertEqual(len(doc["population"]["unmeasured_days"]), 1)
        self.assertTrue(doc["population"]["accounting_identity_holds"])
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_usd_by_remedy_may_exceed_the_total_and_that_is_not_double_counting(self):
        """Доллар не делится между рычагами — он требует их обоих.

        Контроль на соблазн «свести суммы к итогу»: такое сведение выдумало бы
        деление, которого журнал не несёт.
        """
        ddir = _install(self, [
            {"cycle_date": "2026-08-24", "unpriced_gross_usd": 10000.0,
             "turnover_usd": 10000.0,
             "unpriced_protocols": ["morpho_blue", "spark_susds"]},
        ], [
            {"decision_date": "2026-08-24", "forward_date": "2026-08-25",
             "protocol": "morpho_blue", "class": causes.CLASS_ABSENT},
            {"decision_date": "2026-08-24", "forward_date": "2026-08-25",
             "protocol": "spark_susds", "class": causes.CLASS_ABSENT},
        ])
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = [("morpho_blue", "T2", object())]
            doc = mod.measure(ddir, now=_NOW)
        finally:
            orch.POLLED_ADAPTERS = saved
        by = doc["answer"]["usd_by_remedy"]
        self.assertEqual(sum(by.values()), 20000.0)
        self.assertEqual(doc["answer"]["blind_turnover_usd"], 10000.0)

    def test_day_without_a_leg_list_is_unmeasured_not_a_day_with_no_blind_legs(self):
        """АВАРИЯ-класс (инв. #17), найденный храповиком отсутствующего наблюдения.

        Первая редакция писала `dep_day.get("unpriced_protocols") or []`. День, чей
        список ног не пришёл, получал ПУСТОЙ набор ног ⇒ пустой набор рычагов ⇒
        `set() <= OUR_CODE_REMEDIES` истинно ⇒ его слепые доллары молча уезжали в
        «наш код». Отсутствие наблюдения обязано быть отдельным значением.
        """
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0},
        ], [])
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["per_day"], [])
        self.assertEqual(len(doc["population"]["unmeasured_days"]), 1)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_day_without_a_gross_figure_is_unmeasured_too(self):
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "turnover_usd": 20000.0,
             "unpriced_protocols": ["pendle"]},
        ], [
            {"decision_date": "2026-09-08", "forward_date": "2026-09-09",
             "protocol": "pendle", "class": causes.CLASS_ABSENT},
        ])
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["per_day"], [])
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_unattributable_leg_makes_the_verdict_unmeasured(self):
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0, "unpriced_protocols": ["pendle"]},
        ], [
            {"decision_date": "2026-09-08", "forward_date": "2026-09-09",
             "protocol": "pendle", "class": "brand_new_class"},
        ])
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_twin_is_read_from_the_forward_record_of_that_very_pair(self):
        """Близнец ищется в записи ФОРВАРДНОГО дня пары, а не в любой.

        Взяв «какую-нибудь» запись, прибор объявил бы деньги наблюдёнными в день,
        когда их не наблюдали.
        """
        ddir = _install(self, [
            {"cycle_date": "2026-09-10", "unpriced_gross_usd": 40000.0,
             "turnover_usd": 46842.10, "unpriced_protocols": ["fluid_usdc"]},
        ], [
            {"decision_date": "2026-09-10", "forward_date": "2026-09-11",
             "protocol": "fluid_usdc", "class": causes.CLASS_ABSENT},
        ], twins=_TWINS, history=[
            {"cycle_date": "2026-09-11", "apy_evidenced_pct": {"fluid_fusdc": 4.38}},
            {"cycle_date": "2026-09-12", "apy_evidenced_pct": {}},
        ])
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = [("fluid_fusdc", "T2", object())]
            doc = mod.measure(ddir, now=_NOW)
        finally:
            orch.POLLED_ADAPTERS = saved
        self.assertEqual(doc["per_day"][0]["legs"][0]["remedy"],
                         mod.REMEDY_KEY_MISMATCH)
        self.assertEqual(doc["answer"]["our_code_usd"], 40000.0)


class Refusals(unittest.TestCase):
    """Отказы соседей — ТРЕТИЙ исход с названной причиной, не ноль."""

    def test_no_dependence_days_is_unmeasured_not_no_levers(self):
        ddir = _install(self, [], [{"decision_date": "x"}])
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIsNone(doc["answer"])
        self.assertIn("НЕ ИЗМЕРЕНО", " ".join(doc["findings"]))

    def test_absent_attribution_is_unmeasured_not_an_empty_partition(self):
        """`attribution` отсутствует — это не «пар нет», это «сосед не ответил»."""
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 1.0,
             "turnover_usd": 1.0, "unpriced_protocols": ["pendle"]}], [])
        mod._causes.measure = lambda *a, **k: {"status": "UNMEASURED"}
        doc = mod.measure(ddir, now=_NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn("unevidenced_leg_causes", doc["unmeasured_reason"])


class AccountingIdentity(unittest.TestCase):
    """Тождество «измерено + не измерено == дней на входе».

    Оно истинно ПО ПОСТРОЕНИЮ, и батарея мутаций это прямо показала: подмена его на
    литеральный `True` НЕ покрасила ни одного поведенческого теста — сегодня уронить
    день молча нечем. Ценность сторожа вся в БУДУЩЕМ: первый же `continue`, добавленный
    в разбор дней, обязан сделать вердикт громким. Поэтому проверяется ДВОЕ: что
    вердикт на ложное тождество реагирует, и что тождество ВЫЧИСЛЯЕТСЯ, а не
    записывается константой. Второе — структурно (AST), потому что проверка по
    подстроке пережила бы любое расплетение.
    """

    def test_false_identity_makes_the_verdict_unmeasured(self):
        doc = {"population": {"accounting_identity_holds": False},
               "answer": {"measured": True, "owner_lever_usd": 0.0}, "per_day": []}
        self.assertEqual(mod._status(doc), mod.STATUS_UNMEASURED)

    def test_identity_is_computed_not_a_constant(self):
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
        # `len` здесь тоже Name — перечисляется явно, чтобы утверждение осталось
        # РАВЕНСТВОМ: подмножество пропустило бы тождество, потерявшее слагаемое.
        self.assertEqual(names, {"len", "per_day", "unmeasured_days", "dep_days"})


class ReportContract(unittest.TestCase):
    """Отчёт обязан НАЗЫВАТЬ статус числа и границы — их читает не автор."""

    def _doc(self):
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0, "unpriced_protocols": ["pendle"]},
        ], [
            {"decision_date": "2026-09-08", "forward_date": "2026-09-09",
             "protocol": "pendle", "class": causes.CLASS_ABSENT},
        ])
        from spa_core.orchestrator import adapter_orchestrator as orch
        saved = orch.POLLED_ADAPTERS
        try:
            orch.POLLED_ADAPTERS = [("pendle", "T2", object())]
            return mod.measure(ddir, now=_NOW)
        finally:
            orch.POLLED_ADAPTERS = saved

    def test_ceiling_is_stated_in_the_report_not_only_in_the_docstring(self):
        text = " ".join(self._doc()["findings"])
        self.assertIn("ПОТОЛОК", text)

    def test_boundaries_travel_inside_the_artifact(self):
        self.assertTrue(self._doc()["what_it_does_not_prove"])

    def test_advisory_names_the_untouched_money_path(self):
        doc = self._doc()
        self.assertIn("POLLED_ADAPTERS", doc["advisory"])

    def test_missing_remedy_split_is_named_not_silently_empty(self):
        """Ответ без разбивки по рычагам — «не измерено», а не пустая разбивка.

        Промолчав, отчёт сделал бы «разложения нет» неотличимым от «рычаг один».
        Именно эту дыру нашла батарея мутаций: подмена `observed` на `or {}` не
        красила ничего, пока контроля не было.
        """
        out = " ".join(mod._findings(
            {"answer": {"measured": True, "blind_turnover_usd": 1.0,
                        "our_code_usd": 1.0, "our_code_pct": 100.0,
                        "owner_lever_usd": 0.0, "owner_lever_pct": 0.0,
                        "proven_usd": 0.0, "ceiling_usd": 1.0},
             "population": {"unmeasured_days": []}, "per_day": [],
             "twin_keys": {"measured": True, "pairs": {}}}))
        self.assertIn("разложение по рычагам отсутствует", out)

    def test_missing_unmeasured_day_list_is_named_not_silently_empty(self):
        out = " ".join(mod._findings(
            {"answer": {"measured": True, "blind_turnover_usd": 1.0,
                        "our_code_usd": 1.0, "our_code_pct": 100.0,
                        "owner_lever_usd": 0.0, "owner_lever_pct": 0.0,
                        "proven_usd": 0.0, "ceiling_usd": 1.0,
                        "usd_by_remedy": {"writer_universe": 1.0}},
             "population": {}, "per_day": [],
             "twin_keys": {"measured": True, "pairs": {}}}))
        self.assertIn("перечня неизмеренных дней", out)

    def test_format_report_survives_an_unmeasured_doc(self):
        lines = mod.format_report({"status": mod.STATUS_UNMEASURED,
                                   "findings": ["[НЕ ИЗМЕРЕНО] причина"]})
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines))


class Wiring(unittest.TestCase):
    """Проводка ПРИ РОЖДЕНИИ: прибор без потребителя — это ещё не замер."""

    def test_findings_bridge_calls_this_instrument(self):
        src = (Path(mod.__file__).resolve().parents[1]
               / "monitoring" / "findings_bridge.py").read_text(encoding="utf-8")
        self.assertIn("unobserved_leg_remedy_class", src)

    def test_office_step_reads_the_artifact(self):
        src = (Path(mod.__file__).resolve().parents[2]
               / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn(mod.OUTPUT_FILENAME, src)

    def test_manifest_carries_both_entries(self):
        manifest = json.loads(
            (Path(mod.__file__).resolve().parents[2]
             / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        blob = json.dumps(manifest, ensure_ascii=False)
        # Дом артефакта — ДВЕ записи: `artifacts[]` и `produces[]` паспорта агента.
        # Парити-тест краснеет только на второй, поэтому проверяются обе.
        self.assertGreaterEqual(blob.count(mod.OUTPUT_FILENAME), 2)

    def test_run_emits_the_shape_the_bridge_expects(self):
        ddir = _install(self, [
            {"cycle_date": "2026-09-08", "unpriced_gross_usd": 20000.0,
             "turnover_usd": 20000.0, "unpriced_protocols": ["pendle"]},
        ], [
            {"decision_date": "2026-09-08", "forward_date": "2026-09-09",
             "protocol": "pendle", "class": causes.CLASS_ABSENT},
        ])
        doc = mod.run(root=str(ddir.parent), now=_NOW, write=False)
        for key in ("overall", "counts", "findings", "status"):
            self.assertIn(key, doc)
        for key in ("critical", "warn", "info", "unchecked"):
            self.assertIn(key, doc["counts"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

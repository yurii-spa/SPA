"""Ось TVL теневого блока `adapter_status.json`: род числа и отсутствие литерала.

ADR-708, заказ G707 п. 4 стоячего приказа владельца «Portfolio CIO». Предмет —
ВТОРАЯ ось того же дефекта, который ADR-707 закрыл на оси APY, и ровно то число,
которым возмущалась карточка `inbox-tsikl-schitaet-pokrytie-fidov-100-zhivym`
(29.08): `{"apy": 4.1, "tier": "T1", "network": "arbitrum",
"tvl_usd": 1200000000.0}`. ADR-707 снял `4.1`; `1200000000.0` остался.

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ измеренного состояния, а не
украшение. Числа в утверждениях — замеры 2026-10-12 на чистой копии
origin/main 00b0d461d, воспроизведённые дифференциалом двух редакций на одном
стенде (сеть отключена у своей двери в обеих).

Что было измерено ДО починки:
  * теневых блоков, публикующих `tvl_usd` БЕЗ `tvl_source`: **2 из 2**
    (`morpho_steakhouse` $111 619 336 и `aave_arbitrum` $20 924 515 в живом
    артефакте — ОБА зеркалили запись с `tvl_source == "live"`, то есть живое
    наблюдение доезжало до читателя неотличимым от константы);
  * подстановок литерала на оси TVL: **2** — `_TVL_ESTIMATES[morpho_steakhouse]`
    = $800 000 000 и `_TVL_ESTIMATES[aave_arbitrum]` = $1 200 000 000,
    и подставлялись они ТОЛЬКО при нечитаемом `adapter_registry.json`, то есть
    в точке максимального незнания (fail-OPEN);
  * вердикт гейта (`status_reader.read_live_tvl_usd` / `tvl_floor_verdict`) до и
    после — ОДИН И ТОТ ЖЕ в обеих сценах: чиним ПРЕДСТАВЛЕНИЕ, не решение.

Только stdlib. Живое `data/` не читается: все стенды одноразовые.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import adapter_status_generator as gen

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _census():
    """Прибор переписи писателей — загружается по пути (он в `scripts/`)."""
    path = _REPO_ROOT / "scripts" / "adapter_status_writer_census.py"
    spec = importlib.util.spec_from_file_location("_wcensus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════
# 1. `_shadow_tvl` — одна копия правила, ТРИ исхода различимы (инв. #17)
# ══════════════════════════════════════════════════════════════════════════


class TestShadowTvlThreeOutcomes(unittest.TestCase):

    def test_live_is_mirrored_not_rederived(self):
        """Род `live` ЗЕРКАЛИТСЯ у записи, заслужившей его пином (ADR-064).

        Второй вывод того же рода был бы вторым ответом на один вопрос.
        """
        value, source = gen._shadow_tvl(
            {"tvl_usd": 20_924_515.0, "tvl_source": "live"})
        self.assertEqual(value, 20_924_515.0)
        self.assertEqual(source, "live")

    def test_number_without_live_is_static(self):
        value, source = gen._shadow_tvl(
            {"tvl_usd": 500_000_000.0, "tvl_source": "static"})
        self.assertEqual(value, 500_000_000.0)
        self.assertEqual(source, "static")

    def test_unknown_source_is_static_never_live(self):
        """Чужой/пустой род НИКОГДА не повышается до `live` (ADR-053)."""
        for src in (None, "", "unknown", "conservative_static", "estimate", 0):
            with self.subTest(src=src):
                _, source = gen._shadow_tvl({"tvl_usd": 1.0, "tvl_source": src})
                self.assertEqual(source, "static")

    def test_absent_entry_is_none_not_a_literal(self):
        """Записи нет ⇒ (None, None). НЕ литерал и НЕ ноль — инв. #17.

        Это и есть ветка, в которой прежняя редакция публиковала
        `_TVL_ESTIMATES[...]`.
        """
        for entry in ({}, None, "nope", [], {"apy": 4.1}):
            with self.subTest(entry=entry):
                self.assertEqual(gen._shadow_tvl(entry), (None, None))

    def test_non_number_is_absence_not_zero(self):
        for bad in ("12", None, [], {}, True, False):
            with self.subTest(bad=bad):
                self.assertEqual(
                    gen._shadow_tvl({"tvl_usd": bad, "tvl_source": "live"}),
                    (None, None),
                    "«да» и мусор не являются замером (контракт `observed`)")

    def test_zero_is_a_value_not_an_absence(self):
        """Ноль, который ИЗМЕРЕН, остаётся значением. Три исхода, не два."""
        value, source = gen._shadow_tvl({"tvl_usd": 0.0, "tvl_source": "live"})
        self.assertEqual(value, 0.0)
        self.assertEqual(source, "live")
        self.assertIsNotNone(value, "«измерено и равно нулю» ≠ «не измерено»")

    def test_three_outcomes_are_pairwise_distinct(self):
        live = gen._shadow_tvl({"tvl_usd": 7.0, "tvl_source": "live"})
        static = gen._shadow_tvl({"tvl_usd": 7.0, "tvl_source": "static"})
        absent = gen._shadow_tvl({})
        self.assertEqual(len({live, static, absent}), 3,
                         f"исходы склеились: {live} / {static} / {absent}")


# ══════════════════════════════════════════════════════════════════════════
# 2. Документ: род опубликован, литерала НЕТ
# ══════════════════════════════════════════════════════════════════════════


def _doc(registry: object) -> dict:
    """Собрать документ на ОДНОРАЗОВОМ стенде. Фид отключён у своей двери."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = os.path.join(tmp, "adapter_registry.json")
        with open(reg, "w", encoding="utf-8") as fh:
            if isinstance(registry, str):
                fh.write(registry)
            else:
                json.dump(registry, fh)
        saved = gen._fetch_defillama
        gen._fetch_defillama = lambda timeout=None: None
        try:
            return gen.generate(registry_path=Path(reg),
                                output_path=Path(tmp) / "adapter_status.json")
        finally:
            gen._fetch_defillama = saved


#: Ровно те литералы, что уезжали в опубликованное число до ADR-708.
_FORBIDDEN_LITERALS = {
    "aave_arbitrum": 1_200_000_000.0,
    "morpho_steakhouse": 800_000_000.0,
}


class TestPublishedDocument(unittest.TestCase):

    def test_tvl_estimates_still_holds_the_incident_numbers(self):
        """Контроль САМОГО контроля: литералы из аварии на месте в словаре.

        Если их переименуют, тесты ниже начнут проверять пустоту и молча
        зеленеть. Утверждение привязывает контроль к предмету.
        """
        for key, literal in _FORBIDDEN_LITERALS.items():
            with self.subTest(key=key):
                self.assertEqual(gen._TVL_ESTIMATES.get(key), literal)

    def test_unreadable_registry_publishes_no_literal(self):
        """ГЛАВНЫЙ положительный контроль: fail-OPEN ветка закрыта.

        Нечитаемый реестр ⇒ `adapters_meta = {}` на любом `OSError` /
        `JSONDecodeError`. Прежняя редакция публиковала здесь
        $1 200 000 000 и $800 000 000 — константы в точке, где система знает
        МЕНЬШЕ всего. Теперь публикуется отсутствие.
        """
        doc = _doc("{ это не json")
        for key, literal in _FORBIDDEN_LITERALS.items():
            with self.subTest(key=key):
                block = doc[key]
                self.assertIsNone(
                    block["tvl_usd"],
                    f"литерал {literal} снова уехал в опубликованное число")
                self.assertIsNone(block["tvl_source"])
                self.assertNotEqual(block["tvl_usd"], literal)
                self.assertNotEqual(
                    block["tvl_usd"], 0.0,
                    "«оценки нет» нельзя печатать нулём (инв. #17)")

    def test_card_record_from_2026_08_29_no_longer_reproduces(self):
        """Запись карточки 29.08 БАЙТ В БАЙТ больше не собирается.

        ADR-707 снял из неё `apy: 4.1`; ADR-708 снимает `tvl_usd: 1.2e9`.
        """
        doc = _doc("{ это не json")
        self.assertNotEqual(
            {k: doc["aave_arbitrum"].get(k)
             for k in ("apy", "tier", "network", "tvl_usd")},
            {"apy": 4.1, "tier": "T1", "network": "arbitrum",
             "tvl_usd": 1_200_000_000.0})

    def test_shadow_blocks_declare_the_rod_of_their_tvl(self):
        """Число и его род уезжают ВМЕСТЕ — иначе читателю различать нечем."""
        doc = _doc({"adapters": {
            "aave_arbitrum": {"protocol": "Aave V3 Arbitrum", "tier": "T1",
                              "fallback_apy_pct": 4.0, "active": True},
            "morpho_steakhouse": {"protocol": "Morpho Steakhouse", "tier": "T1",
                                  "fallback_apy_pct": 6.0, "active": True},
        }})
        for key in ("aave_arbitrum", "morpho_steakhouse"):
            with self.subTest(key=key):
                block = doc[key]
                self.assertIn("tvl_source", block,
                              "ADR-708: у числа оси TVL обязан быть род")
                if block["tvl_usd"] is not None:
                    self.assertIn(block["tvl_source"], ("live", "static"))

    def test_shadow_tvl_never_outranks_its_nested_record(self):
        """Теневой род не может быть «живее» вложенного — он его ЗЕРКАЛО."""
        doc = _doc({"adapters": {
            "aave_arbitrum": {"protocol": "Aave V3 Arbitrum", "tier": "T1",
                              "fallback_apy_pct": 4.0, "active": True},
        }})
        nested = doc["adapters"]["aave_arbitrum"]
        shadow = doc["aave_arbitrum"]
        if shadow["tvl_usd"] is not None:
            self.assertEqual(shadow["tvl_source"], nested["tvl_source"])
            self.assertEqual(shadow["tvl_usd"], nested["tvl_usd"])

    def test_pendle_pt_deliberately_has_no_tvl_axis(self):
        """Решение ЗАКРЕПЛЕНО, чтобы не уехало молча ни в одну сторону.

        Вложенная запись несёт литерал `_TVL_ESTIMATES` ($500 000 000),
        честно помеченный `static`. Зеркалить его в теневой блок значило бы
        НАПЕЧАТАТЬ владельцу новое число (отчёт о протоколах читает теневые
        блоки) — а цикл чинит представление, а не публикует замеры. Третья
        форма одного вопроса НАЗВАНА остатком, а не погашена молча.
        """
        doc = _doc({"adapters": {
            "pendle_pt": {"protocol": "Pendle PT", "tier": "T2",
                          "fallback_apy_pct": 8.0, "active": True},
        }})
        self.assertNotIn("tvl_usd", doc["pendle_pt"])
        self.assertNotIn("tvl_source", doc["pendle_pt"])


# ══════════════════════════════════════════════════════════════════════════
# 3. ГЕЙТ: вердикт не изменился (чиним представление, не решение)
# ══════════════════════════════════════════════════════════════════════════


class TestGateVerdictUnchanged(unittest.TestCase):

    def _verdicts(self, doc: dict) -> dict:
        from spa_core.adapters import status_reader as sr
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "adapter_status.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(doc, fh)
            return {p: (sr.read_live_tvl_usd(p, Path(tmp)),
                        sr.tvl_floor_verdict(p, Path(tmp)))
                    for p in ("aave_arbitrum", "morpho_steakhouse", "pendle_pt")}

    def test_static_and_absent_are_both_refused(self):
        """Литерал не наблюдение, чем бы он ни был подписан (ADR-053)."""
        for doc in (
            {"aave_arbitrum": {"tvl_usd": 1_200_000_000.0, "tvl_source": "static"}},
            {"aave_arbitrum": {"tvl_usd": 1_200_000_000.0}},
            {"aave_arbitrum": {"tvl_usd": None, "tvl_source": None}},
        ):
            with self.subTest(doc=doc):
                live, verdict = self._verdicts(doc)["aave_arbitrum"]
                self.assertIsNone(live, "$1.2B прошёл бы порог $5M в 240 раз")
                self.assertIsNone(verdict, "«не измерено» ≠ «порог пройден»")

    def test_live_rod_is_what_opens_the_floor(self):
        """Обратная сторона: с родом `live` порог измеряется и проходится."""
        live, verdict = self._verdicts(
            {"aave_arbitrum": {"tvl_usd": 20_924_515.0,
                               "tvl_source": "live"}})["aave_arbitrum"]
        self.assertEqual(live, 20_924_515.0)
        self.assertTrue(verdict)

    def test_unreadable_registry_verdict_is_identical_before_and_after(self):
        """Дифференциал в тесте: вердикт один и тот же, литерала больше нет."""
        after = self._verdicts(_doc("{ это не json"))
        before = self._verdicts({
            "aave_arbitrum": {"tvl_usd": 1_200_000_000.0},
            "morpho_steakhouse": {"tvl_usd": 800_000_000.0},
            "pendle_pt": {},
        })
        for p in after:
            with self.subTest(p=p):
                self.assertEqual(after[p], before[p], "вердикт гейта сдвинулся")
                self.assertEqual(after[p], (None, None))


# ══════════════════════════════════════════════════════════════════════════
# 4. ПРИБОР: три его собственных дефекта, каждый — положительный контроль
# ══════════════════════════════════════════════════════════════════════════


class TestCensusMeasuresTheTvlAxis(unittest.TestCase):

    def setUp(self):
        self.m = _census()

    def test_both_axes_are_in_scope(self):
        """Дефект I1: ось, которая ДОПУСКАЕТ, лежала вне предмета по КОРТЕЖУ."""
        self.assertIn("apy", self.m.PUBLISHED_NUMBER_KEYS)
        self.assertIn("tvl_usd", self.m.PUBLISHED_NUMBER_KEYS)

    def test_literal_via_module_dict_is_found(self):
        """Дефект I2: литерал через МОДУЛЬНЫЙ словарь пропускался МОЛЧА.

        `ast.Call` числился «разобранным значением», поэтому
        `_TVL_ESTIMATES.get(key, 0.0)` не давал ни находки, ни третьего исхода.
        """
        src = (
            "_T = {'aave_arbitrum': 1200000000.0}\n"
            "def f(e, key):\n"
            "    return {'tvl_usd': e.get('tvl_usd', _T.get('aave_arbitrum', 0.0)),\n"
            "            'tvl_source': 'live'}\n"
        )
        got = self.m._literal_axis("x.py", ast.parse(src))
        self.assertEqual(len(got["substitutions"]), 1, got)
        found = got["substitutions"][0]
        self.assertEqual(found["literal"], 1_200_000_000.0)
        self.assertEqual(found["field"], "tvl_usd")
        # `via` обязан НАЗВАТЬ словарь и ключ — иначе находка не адресуема.
        self.assertEqual(found["via"], "module_dict:_T[aave_arbitrum]")

    def test_literal_via_module_dict_subscript_is_found(self):
        src = ("_T = {'k': 5.0}\n"
               "d = {'tvl_usd': e.get('tvl_usd', _T['k']), 'tvl_source': 's'}\n")
        got = self.m._literal_axis("x.py", ast.parse(src))
        self.assertEqual([s["literal"] for s in got["substitutions"]], [5.0])

    def test_unresolvable_get_default_is_the_third_outcome(self):
        """«Не измерено» обязано быть отличимо от «чисто» (инв. #17)."""
        src = ("d = {'tvl_usd': e.get('tvl_usd', compute_it()),\n"
               "     'tvl_source': 'live'}\n")
        got = self.m._literal_axis("x.py", ast.parse(src))
        self.assertEqual(got["substitutions"], [])
        self.assertEqual(len(got["unmeasured"]), 1, got)
        self.assertIn("не раскрыт", got["unmeasured"][0]["reason"])

    def test_apy_source_does_not_vouch_for_tvl_usd(self):
        """Дефект I3 — и это ровно то, чем ADR-707 ОСЛЕПИЛ сторожа.

        Проверка стояла НА СЛОВАРЕ («есть ли ключ на `_source`»), поэтому
        `apy_source`, добавленный ADR-707 теневым блокам, начал ручаться за
        соседний `tvl_usd`, у которого рода не было. Починка одной оси
        погасила сторожа на другой.
        """
        src = ("d = {'apy': a, 'apy_source': s, 'tvl_usd': t}\n")
        tree = ast.parse(src)
        d = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)][0]
        self.assertTrue(self.m._number_declares_provenance(d, "apy"))
        self.assertFalse(self.m._number_declares_provenance(d, "tvl_usd"),
                         "apy_source поручился за ЧУЖОЕ число")
        got = self.m._literal_axis("x.py", tree)
        self.assertEqual([s["field"] for s in got["no_provenance"]], ["tvl_usd"])

    def test_live_apy_counts_as_apy_provenance(self):
        """Обратная сторона: не обвинять ЛОЖНО.

        Вложенная запись генератора объявляет род ставки полем `live_apy` —
        контракт ADR-063, и ровно его читает
        `status_reader.observed_apy_pct_from_block`. Первая редакция этой
        проверки знала одну форму и обвинила вложенную запись ложно.
        """
        src = "d = {'apy': a, 'live_apy': l, 'fallback_apy': f, 'tvl_source': 'live'}\n"
        tree = ast.parse(src)
        d = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)][0]
        self.assertTrue(self.m._number_declares_provenance(d, "apy"))
        self.assertEqual(self.m._literal_axis("x.py", tree)["no_provenance"], [])

    def test_tvl_axis_knows_exactly_one_form_of_its_rod(self):
        """У оси TVL форма рода ОДНА — `tvl_source` (ADR-053). Второй не изобретать."""
        self.assertEqual(set(self.m.PROVENANCE_KEY["tvl_usd"]), {"tvl_source"})

    def test_suffix_rule_could_never_find_the_tvl_rod(self):
        """Почему род берётся ПОИМЁННО, а не склейкой «имя + суффикс»."""
        self.assertNotIn("tvl_usd" + self.m.PROVENANCE_SUFFIX,
                         self.m.PROVENANCE_KEY["tvl_usd"])

    def test_module_literal_dict_only_takes_literal_pairs(self):
        """Словарь, собранный вызовом, в таблицы не попадает (граница названа)."""
        tables = self.m._module_literal_dicts(ast.parse(
            "A = {'k': 1.0, 'j': f()}\nB = dict(k=1.0)\nC = {'k': 'str'}\n"))
        self.assertEqual(tables, {"A": {"k": 1.0}})

    def test_bool_is_not_a_literal_number(self):
        tables = self.m._module_literal_dicts(ast.parse("A = {'k': True}\n"))
        self.assertEqual(tables, {})


class TestCensusCeilingsHold(unittest.TestCase):
    """Потолки прибора на ЭТОМ дереве. Дописывать в них запрещено (инв. #16)."""

    def test_no_literal_reaches_a_published_number(self):
        m = _census()
        rep = m.measure()
        self.assertLessEqual(rep["counts"]["literal_substitution"],
                             m.LITERAL_SUBSTITUTION_MAX,
                             rep["substitutions"])

    def test_numbers_without_rod_stay_at_the_measured_two(self):
        m = _census()
        rep = m.measure()
        self.assertLessEqual(rep["counts"]["provenance_absent"],
                             m.PROVENANCE_ABSENT_MAX,
                             rep["provenance_absent"])

    def test_the_generator_is_no_longer_among_them(self):
        """Производитель, за которым пришёл заказ, вышел из обоих классов."""
        m = _census()
        rep = m.measure()
        named = {s["file"] for s in rep["substitutions"]} | \
                {s["file"] for s in rep["provenance_absent"]}
        self.assertNotIn("spa_core/monitoring/adapter_status_generator.py", named)

    def test_third_outcome_is_reported_not_swallowed(self):
        m = _census()
        rep = m.measure()
        self.assertIn("literal_unmeasured", rep["counts"])
        self.assertLessEqual(rep["counts"]["literal_unmeasured"],
                             m.LITERAL_UNMEASURED_MAX,
                             rep["literal_unmeasured"])


if __name__ == "__main__":
    unittest.main()


# ══════════════════════════════════════════════════════════════════════════
# 5. ПРОБА ПРИЁМКИ: усилилась вместе с прибором, и ОТКАЗЫВАЕТ на дефекте
# ══════════════════════════════════════════════════════════════════════════


class TestAcceptanceProbe(unittest.TestCase):
    """ADR-708 не завёл вторую пробу: вопрос в системе ОДИН.

    `adapter_status_number_has_a_writer` читает ПРИБОР, а не копию его логики,
    поэтому расширение прибора на вторую ось усилило пробу без её правки. Эти
    тесты — контроль ровно этого свойства: проба обязана отказать на дереве, где
    литерал оси TVL ещё доезжает до опубликованного числа.
    """

    def _probe(self):
        from spa_core.monitoring import card_acceptance as ca
        return ca.PROBES["adapter_status_number_has_a_writer"]

    def test_probe_is_registered(self):
        self.assertIsNotNone(self._probe())

    def test_probe_is_satisfied_on_this_tree(self):
        from spa_core.monitoring import card_acceptance as ca
        verdict, message = self._probe()(None)
        self.assertEqual(verdict, ca.SATISFIED, message)

    def test_probe_refuses_when_a_tvl_literal_still_reaches_the_number(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: подменяем ЗАМЕР, не логику пробы.

        Числа в подставленном отчёте — настоящий замер чистой копии
        origin/main 00b0d461d (`$800 000 000` и `$1 200 000 000` через
        `module_dict:_TVL_ESTIMATES[...]`). Проба обязана назвать и поле, и
        файл со строкой, иначе находка не адресуема.
        """
        from spa_core.monitoring import card_acceptance as ca
        census = ca._writer_census_module()
        real = census.measure
        rep = real()
        rep = json.loads(json.dumps(rep))
        rep["counts"]["literal_substitution"] = 2
        rep["substitutions"] = [
            {"file": "spa_core/monitoring/adapter_status_generator.py",
             "line": 1293, "field": "tvl_usd", "source_key": "tvl_usd",
             "literal": 800000000.0,
             "via": "module_dict:_TVL_ESTIMATES[morpho_steakhouse]"},
            {"file": "spa_core/monitoring/adapter_status_generator.py",
             "line": 1300, "field": "tvl_usd", "source_key": "tvl_usd",
             "literal": 1200000000.0,
             "via": "module_dict:_TVL_ESTIMATES[aave_arbitrum]"},
        ]
        census.measure = lambda *a, **k: rep
        try:
            verdict, message = self._probe()(None)
        finally:
            census.measure = real
        self.assertEqual(verdict, ca.NOT_SATISFIED, message)
        self.assertIn("1200000000.0", message)
        self.assertIn("tvl_usd", message)
        self.assertIn("adapter_status_generator.py:1300", message)

    def test_probe_refuses_when_a_number_rides_without_its_rod(self):
        """Второй класс пробы — и он обязан НАЗВАТЬ, какого рода ждали."""
        from spa_core.monitoring import card_acceptance as ca
        census = ca._writer_census_module()
        real = census.measure
        rep = json.loads(json.dumps(real()))
        rep["counts"]["provenance_absent"] = 99
        rep["provenance_absent"] = [
            {"file": "spa_core/monitoring/adapter_status_generator.py",
             "line": 1295, "field": "tvl_usd", "want": ["tvl_source"]}]
        census.measure = lambda *a, **k: rep
        try:
            verdict, message = self._probe()(None)
        finally:
            census.measure = real
        self.assertEqual(verdict, ca.NOT_SATISFIED, message)
        self.assertIn("tvl_source", message)
        self.assertIn(":1295", message)

    def test_probe_says_unmeasured_when_the_census_cannot_run(self):
        """Третий исход у пробы СВОЙ: «не измерено» ≠ «чисто» (инв. #17)."""
        from spa_core.monitoring import card_acceptance as ca
        census = ca._writer_census_module()
        real = census.measure

        def boom(*a, **k):
            raise RuntimeError("прибор сломан")

        census.measure = boom
        try:
            verdict, message = self._probe()(None)
        finally:
            census.measure = real
        self.assertEqual(verdict, ca.UNMEASURED, message)
        self.assertIn("прибор сломан", message)

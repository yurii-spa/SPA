"""Точность двуязычного канала имени — заказ **G61 п. 1**.

ADR-438 назвал «2 из 4». Это замер выборки размера четыре, сделанный одной
парой глаз, и доверительного интервала у него нет никакого. Заказ требует
взять ОБЪЯВЛЕННУЮ выборку целиком, разметить её правилом, записанным ДО
разметки, и назвать долю ложных со знаменателем.

Предмет файла — это правило и его проводка. Два свойства проверяются особо,
потому что без них число было бы утверждением о приборе, а не о канале:

* население обязано ЗАПИСЫВАТЬСЯ, а не только считаться. До этой правки канал
  выдавал 4 пары из 59 срабатываний — 55 были посчитаны и потеряны, и
  размечать их было нечем;
* контроль обязан размечаться ТЕМ ЖЕ правилом. Доля `GENUINE` на абзацах без
  языка права изменения есть частота ошибки самой разметки; без неё
  подтверждающий прибор подтверждал бы сам себя.

Сцены строятся из ``tmp_path``, карта синонимов ПОДАЁТСЯ аргументом. Ровно
один тест проверяет, что умолчание берёт карту модуля, — иначе инъекция
закрыла бы проводку от проверки.

Литеральных дат-якорей и литеральных pid в файле нет ни одного.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import rule_second_copy_census as census
# Имена, существовавшие на `origin` ДО этой правки, берутся ввозом; всё НОВОЕ
# зовётся через модуль (`census.X`), иначе ввоз упал бы на сборе и один ERROR
# подменил бы вердикты всего файла.
from spa_core.monitoring.rule_second_copy_census import (
    RISK_POLICY_MODULE, RULE_DIR, RULE_TEXT,
)

MAP = {"cash": ("кэш",), "kill": ("стоп-кран",), "switch": ("кран",),
       "drawdown": ("просадк",), "capital": ("капитал",)}

#: Маркер права изменения берётся У МОДУЛЯ, а не перепечатывается: вторая
#: копия правила в сцене пережила бы смену правила молча.
AUTHORITY = census.AUTHORITY_MARKS[0]


class _Tree:
    """Дерево с поверхностью решения — иначе соседние координаты «не измерены»."""

    def __init__(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        policy = self.root / RISK_POLICY_MODULE
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text("class RiskConfig:\n"
                          "    min_cash_pct: float = 0.05\n",
                          encoding="utf-8")

    def write(self, rel, body):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return rel

    def rule(self, body, rel=RULE_TEXT):
        return self.write(rel, body)

    def close(self):
        self._tmp.cleanup()


def _labels(out, side="authority"):
    return {row["named_as"]: row["label"] for row in out["rows"]
            if row["side"] == side}


class PopulationIsRecorded(unittest.TestCase):
    """Канал обязан ВЫДАВАТЬ население, а не только его размер.

    Обратная сторона к правке: до неё в `pairs` попадали лишь срабатывания,
    подтверждённые величиной, а остальные существовали только как число.
    Размечать число нельзя, и заказ G61 без этой правки неисполним в принципе.
    """

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)
        self.holder = self.tree.write("spa_core/governance/damper.py",
                                      "_MIN_CASH_PCT = 0.05\n")
        self.index = {"_MIN_CASH_PCT": [self.holder]}

    def test_hit_without_a_value_is_recorded_not_only_counted(self):
        self.tree.rule(f"- Кэш обязателен всегда: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["authority_raw"], 1)
        self.assertEqual(out["authority_corroborated"], 0)
        self.assertEqual(out["pairs"], [])
        self.assertEqual(len(out["raw_hits"]), 1)
        self.assertEqual(out["raw_hits"][0]["named_as"], "_MIN_CASH_PCT")

    def test_hit_on_a_non_numeric_name_is_recorded_too(self):
        # Батарея #658 нашла здесь дыру: во всех прежних сценах имя несло
        # ЧИСЛО, и запись, уехавшая за отсев `value is None`, была невидима.
        # На живом дереве такие имена — большинство населения (`PROTOCOL`,
        # `_protocols`), и потеря их вернула бы заказ G61 в неисполнимость.
        holder = self.tree.write("spa_core/adapters/feed.py",
                                 "CASH = 'строка, а не число'\n")
        self.tree.rule(f"- Кэш обязателен всегда: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, {"CASH": [holder]}, MAP)
        self.assertEqual(out["authority_raw"], 1)
        self.assertEqual(out["authority_numeric"], 0)
        self.assertEqual(len(out["raw_hits"]), 1)
        self.assertIsNone(out["raw_hits"][0]["value"])

    def test_recorded_population_matches_both_counters(self):
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n"
                       f"\n"
                       f"- Кэш объясняется каждый цикл.\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(len(out["raw_hits"]),
                         out["authority_raw"] + out["control_raw"])

    def test_control_hits_are_recorded_with_their_side(self):
        self.tree.rule("- Кэш объясняется каждый цикл.\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual([h["side"] for h in out["raw_hits"]], ["control"])

    def test_recorded_hit_carries_a_resolvable_block_coordinate(self):
        self.tree.rule(f"- Кэш обязателен: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        hit = out["raw_hits"][0]
        body = (self.tree.root / hit["text"]).read_text(encoding="utf-8")
        starts = [b[0][0] for b in census.declaring_paragraphs(body)]
        self.assertIn(hit["block_start"], starts)


class Items(unittest.TestCase):
    """Область сужения — ПУНКТ, и выбор измерен, а не объявлен."""

    def test_wrapped_continuation_stays_in_one_item(self):
        block = [(1, "- буфер кэша обязан"), (2, "  быть объяснён")]
        self.assertEqual(len(census.declaring_items(block)), 1)

    def test_second_bullet_starts_a_new_item(self):
        block = [(1, "- первый"), (2, "- второй")]
        self.assertEqual([n for n, _ in census.declaring_items(block)], [1, 2])

    def test_table_row_is_its_own_item(self):
        block = [(1, "| а | б |"), (2, "| в | г |")]
        self.assertEqual(len(census.declaring_items(block)), 2)

    def test_heading_starts_a_new_item(self):
        block = [(1, "текст"), (2, "## заголовок")]
        self.assertEqual(len(census.declaring_items(block)), 2)

    def test_first_line_opens_an_item_even_without_a_marker(self):
        block = [(1, "просто проза"), (2, "её продолжение")]
        self.assertEqual(len(census.declaring_items(block)), 1)

    def test_no_line_is_lost_by_the_split(self):
        block = [(1, "- а"), (2, "  б"), (3, "- в"), (4, "| г |")]
        joined = "\n".join(text for _, text in census.declaring_items(block))
        self.assertEqual(joined, "- а\n  б\n- в\n| г |")


class ModuleWitness(unittest.TestCase):
    """W2 независим от канала токенов — и он обязан УМЕТЬ сработать."""

    def test_full_path_is_named(self):
        self.assertTrue(census._module_named(
            "правило про spa_core/governance/damper.py",
            "spa_core/governance/damper.py"))

    def test_stem_alone_is_named(self):
        self.assertTrue(census._module_named("считает damper каждый цикл",
                                             "spa_core/governance/damper.py"))

    def test_stem_inside_a_longer_word_is_not_named(self):
        self.assertFalse(census._module_named("модуль damper_v2 считает",
                                              "spa_core/governance/damper.py"))

    def test_absent_module_is_not_named(self):
        self.assertFalse(census._module_named("про кэш и просадку", ""))


class Labels(unittest.TestCase):
    """Таблица истинности правила, объявленного ДО разметки."""

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)
        self.holder = self.tree.write("spa_core/governance/damper.py",
                                      "_MIN_CASH_PCT = 0.05\n")
        self.index = {"_MIN_CASH_PCT": [self.holder]}

    def _run(self, body):
        self.tree.rule(body)
        channel = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        return census.bilingual_name_precision(self.tree.root, channel, MAP)

    def test_value_witness_alone_makes_it_genuine(self):
        out = self._run(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        row = out["rows"][0]
        self.assertEqual(row["label"], census.LABEL_GENUINE)
        self.assertTrue(row["w3_value_named"])
        self.assertFalse(row["w2_subject_named"])

    def test_module_witness_alone_makes_it_genuine(self):
        # Положительный контроль W2: без него ноль модульного свидетеля на
        # живом дереве был бы утверждением о коде, а не о дереве.
        out = self._run(f"- Кэш считает damper каждый цикл: {AUTHORITY}\n")
        row = out["rows"][0]
        self.assertEqual(row["label"], census.LABEL_GENUINE)
        self.assertTrue(row["w2_subject_named"])
        self.assertFalse(row["w3_value_named"])

    def test_colocated_without_any_witness_is_undecided(self):
        out = self._run(f"- Кэш обязателен всегда: {AUTHORITY}\n")
        self.assertEqual(out["rows"][0]["label"], census.LABEL_UNDECIDED)

    def test_tokens_scattered_across_items_is_an_artefact(self):
        index = {"KILL_CASH": ["spa_core/governance/damper.py"]}
        self.tree.write("spa_core/governance/damper.py", "KILL_CASH = 0.05\n")
        self.tree.rule(f"- стоп-кран держит порог: {AUTHORITY}\n"
                       f"- буфер кэша считается отдельно\n")
        channel = census.bilingual_name_reach(self.tree.root, index, MAP)
        out = census.bilingual_name_precision(self.tree.root, channel, MAP)
        self.assertEqual(out["rows"][0]["label"], census.LABEL_ARTEFACT)
        self.assertIsNone(out["rows"][0]["w1_colocated_item_line"])

    def test_scattered_tokens_survive_inside_one_wrapped_item(self):
        # Обратная сторона предыдущего: перенос внутри ОДНОГО маркера пункт не
        # разрывает, иначе настоящее объявление ушло бы в ложные. Без этого
        # теста выбор области был бы вкусом автора.
        index = {"KILL_CASH": ["spa_core/governance/damper.py"]}
        self.tree.write("spa_core/governance/damper.py", "KILL_CASH = 0.05\n")
        self.tree.rule(f"- стоп-кран держит порог, {AUTHORITY}\n"
                       f"  а буфер кэша считается отдельно\n")
        channel = census.bilingual_name_reach(self.tree.root, index, MAP)
        out = census.bilingual_name_precision(self.tree.root, channel, MAP)
        self.assertNotEqual(out["rows"][0]["label"], census.LABEL_ARTEFACT)
        self.assertEqual(out["sides"]["authority"]["wrap_cost"], 1)

    def test_wrap_cost_is_zero_when_both_scopes_agree(self):
        out = self._run(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        self.assertEqual(out["sides"]["authority"]["wrap_cost"], 0)

    def test_control_is_labelled_by_the_same_rule(self):
        out = self._run("- Кэш сверх 5%-буфера объясняется каждый цикл.\n")
        self.assertEqual(_labels(out, "control"),
                         {"_MIN_CASH_PCT": census.LABEL_GENUINE})
        self.assertNotIn("authority", out["sides"])

    def test_token_count_is_recorded_beside_the_label(self):
        out = self._run(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        self.assertEqual(out["rows"][0]["token_count"], 1)
        self.assertEqual(
            out["sides"]["authority"]["by_token_count"]["1"][census.LABEL_GENUINE],
            1)

    def test_injected_map_decides_the_population(self):
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        channel = census.bilingual_name_reach(self.tree.root, self.index, {})
        out = census.bilingual_name_precision(self.tree.root, channel, {})
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)
        self.assertIn("не сработал ни разу", out["reason"])

    def test_default_map_comes_from_the_module(self):
        # Ровно один тест на умолчание: инъекция во всех прочих закрыла бы
        # проводку карты от проверки.
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        channel = census.bilingual_name_reach(self.tree.root, self.index)
        out = census.bilingual_name_precision(self.tree.root, channel)
        self.assertEqual(out["status"], "MEASURED")


class Arithmetic(unittest.TestCase):
    """Знаменатели названы, и третий исход не сложен ни с одной стороной."""

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)
        self.holder = self.tree.write("spa_core/governance/damper.py",
                                      "_MIN_CASH_PCT = 0.05\n")
        self.index = {"_MIN_CASH_PCT": [self.holder]}

    def _run(self, body):
        self.tree.rule(body)
        channel = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        return census.bilingual_name_precision(self.tree.root, channel, MAP)

    def test_false_share_denominator_is_the_labelled_population(self):
        index = {"KILL_CASH": ["spa_core/governance/damper.py"],
                 "_MIN_CASH_PCT": [self.holder]}
        self.tree.write("spa_core/governance/damper.py",
                        "KILL_CASH = 0.07\n_MIN_CASH_PCT = 0.05\n")
        self.tree.rule(f"- стоп-кран держит порог: {AUTHORITY}\n"
                       f"- буфер кэша сверх 5% объясняется\n")
        channel = census.bilingual_name_reach(self.tree.root, index, MAP)
        out = census.bilingual_name_precision(self.tree.root, channel, MAP)
        tally = out["sides"]["authority"]
        self.assertEqual(tally["labelled"],
                         tally[census.LABEL_GENUINE] + tally[census.LABEL_ARTEFACT]
                         + tally[census.LABEL_UNDECIDED])
        self.assertAlmostEqual(tally["false_share"],
                               tally[census.LABEL_ARTEFACT] / tally["labelled"])

    def test_undecided_is_folded_into_neither_side(self):
        out = self._run(f"- Кэш обязателен всегда: {AUTHORITY}\n")
        tally = out["sides"]["authority"]
        self.assertEqual(tally[census.LABEL_UNDECIDED], 1)
        self.assertEqual(tally["false_share"], 0.0)
        self.assertEqual(tally[census.LABEL_GENUINE], 0)

    def test_interval_spans_from_proven_true_to_true_plus_undecided(self):
        out = self._run(f"- Кэш обязателен всегда: {AUTHORITY}\n")
        interval = out["truth_interval"]
        self.assertEqual(interval["lower"], 0.0)
        self.assertEqual(interval["upper"], 1.0)
        self.assertEqual(interval["denominator"], 1)

    def test_interval_is_not_measured_without_a_declaring_side(self):
        out = self._run("- Кэш сверх 5%-буфера объясняется каждый цикл.\n")
        self.assertIsNone(out["truth_interval"])

    def test_two_enrichments_have_different_denominators(self):
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n"
                       f"\n"
                       f"- Кэш сверх 5%-буфера объясняется каждый цикл.\n"
                       f"\n"
                       f"- Просто абзац без имени.\n")
        channel = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        out = census.bilingual_name_precision(self.tree.root, channel, MAP)
        enrich = out["enrichment"]
        self.assertIsNotNone(enrich["per_paragraph"])
        self.assertIsNotNone(enrich["per_hit"])
        self.assertNotEqual(enrich["per_paragraph"], enrich["per_hit"])

    def test_enrichment_without_any_control_population_is_a_third_outcome(self):
        out = self._run(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        enrich = out["enrichment"]
        self.assertIsNone(enrich["per_hit"])
        self.assertIn("контрольных абзацев нет", enrich["per_hit_reason"])

    def test_silent_control_is_infinity_not_a_flawless_channel(self):
        # Вторая ветка нуля, и она ДРУГАЯ: контроль есть и молчит. Сочинить
        # здесь число значило бы объявить канал безупречным по делению на ноль.
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n"
                       f"\n"
                       f"- Абзац без единого имени порога.\n")
        channel = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        out = census.bilingual_name_precision(self.tree.root, channel, MAP)
        self.assertEqual(channel["control_paragraphs"], 1)
        self.assertEqual(channel["control_raw"], 0)
        self.assertIsNone(out["enrichment"]["per_paragraph"])
        self.assertIn("бесконечность",
                      out["enrichment"]["per_paragraph_reason"])


class ThirdOutcome(unittest.TestCase):
    """Инв. #17 в ПОВЕДЕНИИ: «не измерено» не выдаётся за «ложных ноль»."""

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)

    def test_absent_channel_is_unmeasured(self):
        out = census.bilingual_name_precision(self.tree.root, None, MAP)
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)
        self.assertIn("не измерен", out["reason"])

    def test_unmeasured_channel_is_unmeasured(self):
        out = census.bilingual_name_precision(
            self.tree.root, {"status": census.BILINGUAL_UNMEASURED}, MAP)
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)

    def test_channel_without_the_population_key_is_unmeasured(self):
        # Производитель прежней редакции: срабатывания посчитаны, не записаны.
        out = census.bilingual_name_precision(
            self.tree.root, {"status": "MEASURED", "authority_raw": 59}, MAP)
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)
        self.assertIn("посчитаны и не записаны", out["reason"])

    def test_empty_population_is_unmeasured_not_zero_false(self):
        out = census.bilingual_name_precision(
            self.tree.root, {"status": "MEASURED", "raw_hits": []}, MAP)
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)
        self.assertIn("НЕ", out["reason"])
        self.assertNotIn("false_share", out)

    def test_unresolvable_block_is_named_not_silently_dropped(self):
        self.tree.rule("- какой-то текст\n")
        out = census.bilingual_name_precision(
            self.tree.root,
            {"status": "MEASURED",
             "raw_hits": [{"side": "authority", "text": RULE_TEXT,
                           "block_start": 9999, "named_as": "X",
                           "resolved": "a.py", "value": None}]}, MAP)
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)
        self.assertEqual(len(out["unresolved"]), 1)
        self.assertIn("9999", out["unresolved"][0]["reason"])

    def test_unreadable_text_is_named_with_its_error(self):
        out = census.bilingual_name_precision(
            self.tree.root,
            {"status": "MEASURED",
             "raw_hits": [{"side": "authority", "text": "нет/такого.md",
                           "block_start": 1, "named_as": "X",
                           "resolved": "a.py", "value": None}]}, MAP)
        self.assertEqual(out["status"], census.PRECISION_UNMEASURED)
        self.assertEqual(len(out["unresolved"]), 1)
        self.assertIn("Error", out["unresolved"][0]["reason"])

    def test_one_unresolved_does_not_silence_the_measured_rest(self):
        self.tree.write("spa_core/governance/damper.py", "_MIN_CASH_PCT = 0.05\n")
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        channel = census.bilingual_name_reach(
            self.tree.root, {"_MIN_CASH_PCT": ["spa_core/governance/damper.py"]},
            MAP)
        channel["raw_hits"] = list(channel["raw_hits"]) + [
            {"side": "authority", "text": RULE_TEXT, "block_start": 9999,
             "named_as": "X", "resolved": "a.py", "value": None}]
        out = census.bilingual_name_precision(self.tree.root, channel, MAP)
        self.assertEqual(out["status"], "MEASURED")
        self.assertEqual(out["labelled"], 1)
        self.assertEqual(len(out["unresolved"]), 1)
        self.assertEqual(out["raw_hits"], 2)


class Report(unittest.TestCase):
    """Замер обязан доехать до читателя — и там, где соседи молчат."""

    def _doc(self, precision):
        return {"generated_at": "", "status": "CLEAN", "rows": [],
                "bilingual_name_precision": precision}

    def test_absent_coordinate_is_named_not_omitted(self):
        out = census.report(self._doc(None))
        self.assertTrue(any("ТОЧНОСТЬ ИМЕНИ" in line and "НЕ ИЗМЕРЕНА" in line
                            for line in out))

    def test_unmeasured_prints_the_reason(self):
        out = census.report(self._doc(
            {"status": census.PRECISION_UNMEASURED, "reason": "населения нет"}))
        self.assertTrue(any("населения нет" in line for line in out))

    def test_section_speaks_even_when_the_bilingual_neighbour_is_silent(self):
        # Ошибка размещения #655: вложенная в `else` соседа, секция молчала бы
        # у каждого дерева с пустой картой — там, где спросить важнее всего.
        doc = self._doc({"status": census.PRECISION_UNMEASURED,
                         "reason": "населения нет"})
        doc["bilingual_reach"] = {"verdict": census.BILINGUAL_NOTHING_TO_ASK,
                                  "reason": "карта пуста"}
        out = census.report(doc)
        self.assertTrue(any("ТОЧНОСТЬ ИМЕНИ" in line for line in out))

    def test_measured_prints_rule_interval_and_both_enrichments(self):
        doc = self._doc({
            "status": "MEASURED", "rule": "ПРАВИЛО-ЯКОРЬ",
            "raw_hits": 1, "labelled": 1, "unresolved": [], "rows": [],
            "truth_interval": {"lower": 0.1, "upper": 0.9, "denominator": 10},
            "enrichment": {"per_paragraph": 3.88, "per_paragraph_reason": None,
                           "per_hit": None, "per_hit_reason": "контроля нет"},
            "sides": {"authority": {census.LABEL_GENUINE: 1,
                                    census.LABEL_ARTEFACT: 2,
                                    census.LABEL_UNDECIDED: 7,
                                    "labelled": 10, "false_share": 0.2,
                                    "wrap_cost": 0, "by_token_count": {}}},
        })
        out = "\n".join(census.report(doc))
        self.assertIn("ПРАВИЛО-ЯКОРЬ", out)
        self.assertIn("[10.0%, 90.0%]", out)
        self.assertIn("x3.88", out)
        self.assertIn("контроля нет", out)

    def test_missing_side_is_named_as_unmeasured(self):
        doc = self._doc({
            "status": "MEASURED", "rule": "r", "raw_hits": 0, "labelled": 0,
            "unresolved": [], "rows": [], "truth_interval": None,
            "enrichment": {}, "sides": {},
        })
        out = "\n".join(census.report(doc))
        self.assertIn("control] НЕ ИЗМЕРЕНО", out)

    def test_unresolved_rows_reach_the_reader(self):
        doc = self._doc({
            "status": "MEASURED", "rule": "r", "raw_hits": 1, "labelled": 0,
            "unresolved": [{"text": "t.md", "named_as": "X", "reason": "ПРИЧИНА"}],
            "rows": [], "truth_interval": None, "enrichment": {}, "sides": {},
        })
        out = "\n".join(census.report(doc))
        self.assertIn("ПРИЧИНА", out)


class Wiring(unittest.TestCase):
    """Координата обязана быть ПОЗВАНА, а не только определена."""

    def test_run_carries_the_coordinate(self):
        tree = _Tree()
        self.addCleanup(tree.close)
        (tree.root / RULE_DIR).mkdir(parents=True, exist_ok=True)
        tree.write("scripts/tool.py", "SEED = 42\n")
        tree.write("spa_core/tests/test_tool.py", "SEED = 42\n")
        tree.rule("- какой-то текст правила\n")
        outcome = census.run(tree.root, write=False)
        self.assertEqual(outcome["doc"].get("status") == "UNMEASURED", False)
        # Ключ на месте со значением `None` пережил бы проверку присутствия:
        # батарея #658 сняла ровно эту мутацию. Спрашивается ИСХОД координаты.
        measured = outcome["doc"].get("bilingual_name_precision")
        self.assertIsInstance(measured, dict)
        self.assertIn("status", measured)
        self.assertIn(measured["status"], ("MEASURED", census.PRECISION_UNMEASURED))

    def test_latin_only_item_is_unreachable_under_a_bilingual_block(self):
        """Третий сторож, переживший батарею, — и доказательство, а не вера.

        Абзац объявлен двуязычным ровно тогда, когда хотя бы одному токену НЕ
        нашлось латиницы нигде в абзаце. Этого токена нет и ни в одном его
        пункте, поэтому пункт не может ответить `name_token`: у сужения
        исходов два, `None` и `name_token_bilingual`. Сцены, где различие
        кусается, НЕ СУЩЕСТВУЕТ — и `checked > 0` не даёт пустому обходу
        выдать себя за доказательство.
        """
        checked = 0
        blocks = (
            [(1, "- стоп-кран держит порог"), (2, "  буфер кэша отдельно")],
            [(1, "| стоп-кран | буфер кэша |")],
            [(1, "## кэш"), (2, "- стоп-кран рядом")],
            [(1, "- kill и буфер кэша в одной строке")],
        )
        for block in blocks:
            raw = "\n".join(text for _, text in block)
            for tokens in ({"kill", "cash"}, {"cash"}, {"kill", "switch"}):
                if census._token_evidence(raw.lower(), tokens,
                                          MAP) != census.EV_NAME_BILINGUAL:
                    continue
                for _, item in census.declaring_items(block):
                    evidence = census._token_evidence(item.lower(), tokens, MAP)
                    self.assertIn(evidence, (None, census.EV_NAME_BILINGUAL))
                    checked += 1
        self.assertGreater(checked, 0)

    def test_the_declared_rule_is_a_constant_not_a_sentence_in_the_report(self):
        self.assertIn("GENUINE", census.PRECISION_RULE)
        self.assertIn("ARTEFACT", census.PRECISION_RULE)
        self.assertIn("UNDECIDED", census.PRECISION_RULE)


if __name__ == "__main__":
    unittest.main()

"""Проводка переписи «стык двух осей у остальных»: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G98 п. 2** приказа владельца «Portfolio CIO», решение — ADR-566.

## Почему этот файл существует

По уроку ADR-427: запись в реестре исполнением не является. Общий храповик
сверяет `CENSUS_PRODUCT` с `CENSUS_STAGE` и манифестом, но о том, ЗОВЁТСЯ ли
прибор, не спрашивает вовсе — а по уроку памяти цикла #760 ИМПОРТ он зачтёт за
вызов. Поэтому вызов ищется разбором AST **ПО ФОРМЕ ВЫЗОВА**, а не именем в
тексте: имя ловит собственный комментарий этого же файла.

## Проводка рвётся в шести местах, и каждое молчит по-своему

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется НИКОГДА; скажет SLO часами позже и чужим голосом |
| `PRODUCES` (состав моста) | продукт не объявлен — сторож сиротства о нём не спросит |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` | ступень не числится переписью: «пропущено» не отличить от «не бывало» |
| `_READ_SCHEMA` + `_PRODUCER` офиса | шаг 0-офис файл не открывает — числа нет в контексте оркестратора |
| именная ветка отрисовки | файл ОТКРЫТ, прочитано ноль чисел («вхолостую») |
| запись манифеста | SLO не назначен; агент утверждает, что продукта не производит |

**Седьмое звено — ПОРЯДОК.** Ступень сверяет своё население И обе краевые
раскладки с ОПУБЛИКОВАННЫМИ числами соседа (`rule_second_copy_census`); стоя
ПЕРЕД ним, она сверяла бы сегодняшнее дерево с позавчерашним замером — и
молчала бы об этом: отказ «обход спорит с соседом» читался бы как дефект
прибора, а не как дефект порядка. Порядок проверяется номером строки вызова,
а не договорённостью.

**Восьмое звено — ЗАПРЕТ ЗАКАЗА.** Заказ прямо запрещает складывать два
незнания в одно. Схема офиса, объявившая `cross` и потерявшая `do_not_sum`,
напечатала бы клетки и унесла с собой сам запрет — поэтому объявление обоих
полей проверяется отдельным тестом, а не предполагается.

Живое `data/` на запись не открывается ни одной проверкой. Литеральных дат
нет вовсе.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
import json
import unittest
from pathlib import Path

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import reachability_of_the_rest as R

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
ARTIFACT_REL = "data/reachability_of_the_rest.json"
ARTIFACT_NAME = "reachability_of_the_rest.json"
STAGE_KEY = "reachability_of_the_rest"
NEIGHBOUR_KEY = "rule_second_copy_census"
RUNNER = "com.spa.decision_loop"


def _office():
    spec = importlib.util.spec_from_file_location("_office_ror_under_test",
                                                  OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads(
        (REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))


def _main_body() -> ast.FunctionDef:
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("у моста нет функции main — проводку не к чему крепить")


def _run_calls() -> dict:
    """Строка КАЖДОГО зова вида `<имя>.run(...)` в теле main. Форма, не имя."""
    out: dict = {}
    for node in ast.walk(_main_body()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)):
            out.setdefault(node.func.value.id, node.lineno)
    return out


@functools.lru_cache(maxsize=1)
def _live_doc() -> dict:
    """Документ на ЖИВОМ дереве, один раз на файл: обход стои́т ~25 с.

    `published` подаётся собственным обходом НАМЕРЕННО: предмет этих тестов —
    ФОРМА документа и его проводка, а не сверка населения с соседом (её
    проверяет батарея прибора). Читать артефакт соседа здесь значило бы
    поставить проводку в зависимость от того, запускался ли мост.
    """
    reader, writer, asked, unreadable, _ = R._walk(REPO)
    assert not unreadable, unreadable
    margin = {}
    for row in reader:
        margin[row["verdict"]] = margin.get(row["verdict"], 0) + 1
    wmargin = {}
    for row in writer:
        wmargin[row["writer"]] = wmargin.get(row["writer"], 0) + 1
    published = {"reader_population": len(reader),
                 "writer_population": len(writer),
                 "asked_population": len(asked),
                 "reader_margin": margin, "writer_margin": wmargin,
                 "generated_at": None}
    return R.run(REPO, write=False, published=published)["doc"]


class ProducingCallExistsAndIsACallNotAName(unittest.TestCase):
    def test_bridge_main_calls_the_producer(self):
        found = [c for c in ast.walk(_main_body())
                 if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Attribute)
                 and c.func.attr == "run"
                 and isinstance(c.func.value, ast.Name)
                 and c.func.value.id == STAGE_KEY]
        self.assertEqual(
            len(found), 1,
            f"в теле main() обязан быть ровно один зов {STAGE_KEY}.run(...)")
        self.assertIn("root", {k.arg for k in found[0].keywords},
                      "зов обязан передавать root: иначе ступень мерила бы "
                      "дерево, в котором её случайно запустили")

    def test_main_imports_the_producer(self):
        imported = [a.name for n in ast.walk(_main_body())
                    if isinstance(n, ast.ImportFrom) for a in n.names]
        self.assertIn(STAGE_KEY, imported)

    def test_an_import_alone_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА (урок #760): импорт зовом не является."""
        fake = ast.parse("def main():\n"
                         f"    from spa_core.monitoring import {STAGE_KEY}\n")
        self.assertEqual(
            [c for c in ast.walk(fake)
             if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute)
             and c.func.attr == "run"], [])

    def test_a_mere_mention_of_the_name_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА: проверка по подстроке пережила бы снятие зова."""
        fake = ast.parse("def main():\n"
                         f"    print('{STAGE_KEY}.run(root=args.root)')\n")
        self.assertEqual(
            [c for c in ast.walk(fake)
             if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute)
             and c.func.attr == "run"], [])

    def test_the_stage_stands_after_the_neighbour_it_reads(self):
        """ПОРЯДОК — звено, а не договорённость."""
        calls = _run_calls()
        self.assertIn(NEIGHBOUR_KEY, calls,
                      "сосед, у которого берётся население, в мосту не зовётся")
        self.assertIn(STAGE_KEY, calls)
        self.assertGreater(calls[STAGE_KEY], calls[NEIGHBOUR_KEY])

    def test_producer_module_exposes_run_with_root(self):
        self.assertIn("root", inspect.signature(R.run).parameters)

    def test_the_measurement_inputs_are_parameters_not_environment(self):
        """Часы И строки обеих осей обязаны быть ВХОДАМИ (правило #1).

        Сцена не может выдумать ни соседского артефакта, ни боевого дерева;
        без этих параметров батарея либо судила бы о живом `data/`, либо
        молча скипалась — то есть «не измерено» стало бы неотличимо от
        «прошло» (урок #465).
        """
        params = inspect.signature(R.measure).parameters
        for name in ("now", "published", "reader_rows", "writer_rows",
                     "asked_rows"):
            self.assertIn(name, params)


class BridgeRegistriesDeclareTheProduct(unittest.TestCase):
    def test_artifact_is_declared_among_bridge_products(self):
        self.assertIn(ARTIFACT_REL, fb.PRODUCES)

    def test_stage_is_listed_as_a_census(self):
        self.assertIn(STAGE_KEY, fb.CENSUS_STAGE)

    def test_census_product_names_module_and_artifact(self):
        entry = fb.CENSUS_PRODUCT[STAGE_KEY]
        self.assertEqual(entry["artifact"], ARTIFACT_REL)
        self.assertTrue((REPO / entry["module"]).is_file())

    def test_declared_module_is_the_one_that_writes_the_declared_artifact(self):
        """Объявить можно что угодно — имя сверяется с КОНСТАНТОЙ производителя."""
        self.assertEqual(f"data/{R.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(R.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):
    def test_the_producer_is_named(self):
        self.assertEqual(_office()._PRODUCER[ARTIFACT_NAME], R.PRODUCER)

    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        for field in ("status", "invoked_by", "order", "population",
                      "asked_by_the_neighbour", "the_rest", "cross",
                      "reader_axis_over_the_rest",
                      "writer_axis_over_the_rest", "premise_of_the_order",
                      "do_not_sum", "neighbour_age_hours", "named_rows",
                      "blind"):
            self.assertIn(field, schema)

    def test_the_prohibition_of_the_order_is_declared_not_only_the_cross(self):
        """Схема, объявившая `cross` и потерявшая `do_not_sum`, унесла бы запрет.

        Заказ запрещает складывать два незнания в одно. Клетки без запрета
        читаются как сводка, из которой сумма берётся сама.
        """
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        self.assertIn("cross", schema)
        self.assertIn("do_not_sum", schema)
        self.assertIn("premise_of_the_order", schema)

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = _live_doc()
        for field in _office()._READ_SCHEMA[ARTIFACT_NAME]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_the_named_branch_prints_real_numbers_not_an_empty_read(self):
        """Живой контроль: ветка обязана печатать ЧИСЛА, а не открыть файл."""
        lines = _office()._summarize_json(ARTIFACT_REL, _live_doc())
        self.assertGreaterEqual(len(lines), 6, lines)
        self.assertTrue(any("❗ОТВЕТ" in line for line in lines), lines)
        self.assertTrue(any("НЕ СКЛАДЫВАТЬ" in line for line in lines), lines)
        self.assertTrue(any("ПРЕДПОСЫЛКА ЗАКАЗА" in line for line in lines),
                        lines)
        self.assertTrue(any("возраст" in line for line in lines), lines)
        self.assertTrue(any("ADVISORY" in line for line in lines), lines)

    def test_an_unmeasured_document_is_not_rendered_as_clean(self):
        """ОБРАТНАЯ СТОРОНА: третий исход обязан дойти до читателя третьим."""
        doc = {"status": "UNMEASURED", "order": R.ORDER,
               "reason": "сосед не прочитан: артефакта нет"}
        lines = _office()._summarize_json(ARTIFACT_REL, doc)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines), lines)


class ManifestGivesTheArtifactAHome(unittest.TestCase):
    def _entry(self) -> dict:
        for group in _manifest().values():
            if not isinstance(group, list):
                continue
            for item in group:
                if isinstance(item, dict) and item.get("path") == ARTIFACT_REL:
                    return item
        raise AssertionError(f"{ARTIFACT_REL} не объявлен в манифесте")

    def test_artifact_is_active_with_a_producer_and_an_slo(self):
        entry = self._entry()
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["producer"], RUNNER)
        self.assertGreater(entry["slo_hours"], 0)

    def test_the_runner_declares_it_among_what_it_produces(self):
        produced = [e.get("artifact") for group in _manifest().values()
                    if isinstance(group, list)
                    for item in group if isinstance(item, dict)
                    for e in (item.get("produces") or [])
                    if isinstance(e, dict)]
        self.assertIn(ARTIFACT_REL, produced)

    def test_the_manifest_note_names_the_order_and_the_refuted_premise(self):
        """Запись без предмета — адрес без содержания: SLO есть, смысла нет."""
        note = self._entry()["notes"]
        self.assertIn("G98", note)
        self.assertIn("ОПРОВЕРГНУТА", note)


class TheLiveAnswerIsMeasuredNotAssumed(unittest.TestCase):
    """Один живой прогон — и ответ заказа в нём ОБЪЯВЛЕН, а не предположен."""

    def test_the_live_run_is_measured_and_advisory(self):
        doc = _live_doc()
        self.assertEqual(doc["status"], "MEASURED", doc.get("reason"))
        self.assertIs(doc["applied"], False)

    def test_every_node_of_the_rest_lands_in_exactly_one_cell(self):
        doc = _live_doc()
        self.assertEqual(sum(doc["cross"].values()), doc["the_rest"])
        self.assertEqual(doc["the_rest"],
                         doc["population"] - doc["asked_by_the_neighbour"])

    def test_the_neighbour_asked_strictly_less_than_the_population(self):
        """Ноль остатка означал бы, что заказ пуст по ПОСТРОЕНИЮ."""
        doc = _live_doc()
        self.assertGreater(doc["the_rest"], 0)
        self.assertGreater(doc["asked_by_the_neighbour"], 0)

    def test_the_headline_number_is_an_integer_not_none(self):
        """«НЕ ИЗМЕРЕНО» у головного числа — отказ, а не ноль (инв. #17)."""
        doc = _live_doc()
        self.assertIsInstance(doc["cross"][R.CELL_HARM_REACHABLE], int)
        self.assertIsInstance(doc["do_not_sum"]["both_axes_unmeasured"], int)

    def test_the_three_ignorances_are_never_collapsed_into_one_number(self):
        doc = _live_doc()
        dns = doc["do_not_sum"]
        pair = dns["reader_axis_unmeasured"] + dns["writer_axis_unmeasured"]
        self.assertTrue(
            all(v != pair for v in doc["cross"].values()),
            "сумма двух незнаний стои́т клеткой — запрет заказа нарушен")

    def test_the_premise_verdict_is_one_of_two_named_words(self):
        doc = _live_doc()
        self.assertIn(doc["premise_of_the_order"]["verdict"],
                      ("ОПРОВЕРГНУТА", "ПОДТВЕРЖДЕНА"))


if __name__ == "__main__":
    unittest.main()

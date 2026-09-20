"""Проводка переписи «кто режет своей рукой»: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G50 п. 2** приказа владельца «Portfolio CIO», решение — ADR-428.

## Почему этот файл существует

По уроку ADR-427: запись в реестре исполнением не является. Мутация «снять
ступень из `findings_bridge.main()`, оставив все три объявления на месте»
пережила там общий храповик — он сверяет `CENSUS_PRODUCT` с `CENSUS_STAGE` и
манифестом, но о том, ЗОВЁТСЯ ли прибор, не спрашивает вовсе. Поэтому новая
перепись рождается со своим файлом проводки, а не приобретает его после
следующей батареи.

## Проводка рвётся в шести местах, и каждое молчит по-своему

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется НИКОГДА; скажет SLO часами позже и чужим голосом |
| `PRODUCES` (состав моста) | продукт не объявлен — сторож сиротства о нём не спросит |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` | ступень не числится переписью: «пропущено» не отличить от «не бывало» |
| `_READ_SCHEMA` + `_PRODUCER` офиса | шаг 0-офис файл не открывает — числа нет в контексте оркестратора |
| именная ветка отрисовки | файл ОТКРЫТ, прочитано ноль чисел («вхолостую») |
| запись манифеста | SLO не назначен; агент утверждает, что продукта не производит |

Вызов ищется **разбором AST по ФОРМЕ вызова**, а не именем в тексте: имя ловит
собственный комментарий этого же файла, форма ловит зов (урок ADR-414).

Живое `data/` не читается ни одной проверкой. Литеральных дат нет вовсе.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import unittest
from pathlib import Path

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import hand_truncation_census as htc

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
ARTIFACT_REL = "data/hand_truncation_census.json"
ARTIFACT_NAME = "hand_truncation_census.json"
STAGE_KEY = "hand_truncation_census"
RUNNER = "com.spa.decision_loop"


def _office():
    spec = importlib.util.spec_from_file_location("_office_htc_under_test", OFFICE)
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


class ProducingCallExistsAndIsACallNotAName(unittest.TestCase):
    def test_bridge_main_calls_the_producer(self):
        found = [c for c in ast.walk(_main_body())
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                 and c.func.attr == "run" and isinstance(c.func.value, ast.Name)
                 and c.func.value.id == STAGE_KEY]
        self.assertEqual(len(found), 1,
                         f"в теле main() обязан быть ровно один зов {STAGE_KEY}.run(...)")
        self.assertIn("root", {k.arg for k in found[0].keywords},
                      "зов обязан передавать root: иначе ступень мерила бы дерево, "
                      "в котором её случайно запустили")

    def test_main_imports_the_producer(self):
        imported = [a.name for n in ast.walk(_main_body())
                    if isinstance(n, ast.ImportFrom) for a in n.names]
        self.assertIn(STAGE_KEY, imported)

    def test_a_mere_mention_of_the_name_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА: проверка по подстроке пережила бы снятие зова."""
        fake = ast.parse("def main():\n"
                         f"    print('{STAGE_KEY}.run(root=args.root)')\n")
        self.assertEqual(
            [c for c in ast.walk(fake)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and c.func.attr == "run"], [])

    def test_producer_module_exposes_run_with_root(self):
        self.assertIn("root", inspect.signature(htc.run).parameters)


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
        self.assertEqual(f"data/{htc.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(htc.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):
    def test_the_producer_is_named(self):
        self.assertEqual(_office()._PRODUCER[ARTIFACT_NAME], htc.PRODUCER)

    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        for field in ("status", "invoked_by", "runner", "counts", "rows",
                      "cut_sides", "unreadable", "popen_sites", "parse_slices",
                      "what_it_does_not_prove"):
            self.assertIn(field, schema)

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = htc.run(REPO, write=False)["doc"]
        for field in _office()._READ_SCHEMA[ARTIFACT_NAME]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_the_named_branch_prints_real_numbers_not_an_empty_read(self):
        """Живой контроль: ветка обязана печатать ЧИСЛА, а не открыть файл."""
        doc = htc.run(REPO, write=False)["doc"]
        lines = _office()._summarize_json(ARTIFACT_REL, doc)
        self.assertGreaterEqual(len(lines), 5, lines)
        self.assertTrue(any("кто режет вывод СВОЕЙ РУКОЙ" in line
                            for line in lines), lines)
        self.assertTrue(any("[СТОРОНА РАЗРЕЗА]" in line for line in lines), lines)

    def test_an_unmeasured_document_is_not_rendered_as_clean(self):
        """ОБРАТНАЯ СТОРОНА: третий исход обязан дойти до читателя третьим."""
        doc = {"status": "UNMEASURED", "reason": "корень дерева не прочитан: /нет"}
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


if __name__ == "__main__":
    unittest.main()

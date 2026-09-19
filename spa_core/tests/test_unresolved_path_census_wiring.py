"""Проводка переписи разрешимости путей: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G46 п. 2** приказа владельца «Portfolio CIO», решение — ADR-424.

Проводка рвётся в шести местах, и каждое молчит по-своему: зов в
`findings_bridge.main` (артефакт не обновляется НИКОГДА) · `PRODUCES` (продукт
не объявлен, сторож сиротства о нём не спросит) · `CENSUS_STAGE` /
`CENSUS_PRODUCT` («пропущено» не отличить от «не бывало») · `_READ_SCHEMA` +
`_PRODUCER` офиса (шаг 0-офис файл не откроет) · именная ветка отрисовки (файл
ОТКРЫТ, прочитано ноль чисел) · обе записи конституции (SLO не назначен).

Зов ищется **разбором AST по ФОРМЕ вызова**, а не именем в тексте: имя ловит
собственный комментарий этого же файла, форма ловит зов (урок ADR-414).

Живое `data/` не читается ни одной проверкой. Литеральных дат нет вовсе.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib.util
import json
import unittest
from pathlib import Path

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import unresolved_path_census as upc

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
ARTIFACT_REL = "data/unresolved_path_census.json"
STAGE_KEY = "unresolved_path_census"
RUNNER = "com.spa.decision_loop"


def _office():
    spec = importlib.util.spec_from_file_location("_office_upc_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads((REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))


def _main_body() -> ast.FunctionDef:
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("у моста нет main() — проводку проверять негде")


class BridgeCallsTheProducer(unittest.TestCase):
    def test_main_contains_a_call_to_run_by_its_FORM(self):
        calls = [n for n in ast.walk(_main_body())
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "run"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == STAGE_KEY]
        self.assertEqual(len(calls), 1,
                         "ступень обязана зваться в main() ровно один раз")

    def test_the_stage_is_declared_a_census_stage(self):
        self.assertIn(STAGE_KEY, fb.CENSUS_STAGE)
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE_KEY]["artifact"], ARTIFACT_REL)
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE_KEY]["module"], upc.PRODUCER)

    def test_the_product_is_declared(self):
        self.assertIn(ARTIFACT_REL, fb.PRODUCES)

    def test_artifact_name_agrees_between_producer_and_bridge(self):
        """Два места назвать файл — два места разойтись молча."""
        self.assertEqual(f"data/{upc.ARTIFACT}", ARTIFACT_REL)


class OfficeReadsTheArtifact(unittest.TestCase):
    def test_read_schema_names_the_fields_the_answer_stands_on(self):
        schema = _office()._READ_SCHEMA[upc.ARTIFACT]
        for key in ("status", "unresolved", "resolved_by_tightening",
                    "by_reason", "by_place", "marginal_contribution",
                    "new_repo_population", "what_it_does_not_prove"):
            self.assertIn(key, schema,
                          f"поле {key} не объявлено — офис прочтёт файл мимо него")

    def test_producer_registry_names_the_module(self):
        self.assertEqual(_office()._PRODUCER[upc.ARTIFACT], upc.PRODUCER)

    def test_rendering_branch_exists_and_delegates_to_the_producer(self):
        tree = ast.parse(OFFICE.read_text(encoding="utf-8"))
        imports = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom)
                   and n.module == "spa_core.monitoring.unresolved_path_census"
                   and any(a.name == "format_report" for a in n.names)]
        self.assertEqual(len(imports), 1,
                         "офис обязан ввозить отрисовку У ПРОИЗВОДИТЕЛЯ, ровно раз")
        branches = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Compare)
                    and any(isinstance(c, ast.Constant) and c.value == upc.ARTIFACT
                            for c in n.comparators)]
        self.assertTrue(branches,
                        "именной ветки отрисовки нет — файл читался бы вхолостую")

    def test_import_form_is_single_line(self):
        # Сторож достижимости вырезает ввозы ДВУХ объявленных форм; скобочная
        # многострочная ни одной из них не является (#627).
        lines = [ln for ln in OFFICE.read_text(encoding="utf-8").splitlines()
                 if "from spa_core.monitoring.unresolved_path_census import" in ln]
        self.assertEqual(len(lines), 1)
        self.assertNotIn("(", lines[0])

    def test_rendering_is_not_vacuous_on_a_real_document(self):
        """Контроль на украшение: ветка обязана вернуть ЧИСЛА, а не пустоту."""
        doc = upc.measure(REPO)
        lines = upc.format_report(doc)
        self.assertTrue(lines)
        self.assertTrue(any("ОСТАТОК ПО ПРИЧИНАМ" in ln for ln in lines))


class ConstitutionHasBothHomes(unittest.TestCase):
    def test_artifact_entry(self):
        (entry,) = [a for a in _manifest()["artifacts"] if a.get("path") == ARTIFACT_REL]
        self.assertEqual(entry["producer"], RUNNER)
        self.assertEqual(entry["status"], "active")
        self.assertIn("orchestrator_protocol", entry["consumers"])
        self.assertTrue(entry["notes"].strip())

    def test_agent_passport_claims_the_product(self):
        (agent,) = [a for a in _manifest()["agents"] if a.get("label") == RUNNER]
        self.assertIn(ARTIFACT_REL, {p["artifact"] for p in agent["produces"]})

    def test_both_homes_agree_on_the_slo(self):
        """ОБРАТНАЯ СТОРОНА: два дома — два места разойтись молча (ADR-220)."""
        doc = _manifest()
        (entry,) = [a for a in doc["artifacts"] if a.get("path") == ARTIFACT_REL]
        (agent,) = [a for a in doc["agents"] if a.get("label") == RUNNER]
        products = {p["artifact"]: p for p in agent["produces"]}
        self.assertEqual(entry["slo_hours"], products[ARTIFACT_REL]["slo_hours"])

    def test_slo_covers_two_runs_of_the_runner_not_a_neighbours_week(self):
        doc = _manifest()
        (entry,) = [a for a in doc["artifacts"] if a.get("path") == ARTIFACT_REL]
        (agent,) = [a for a in doc["agents"] if a.get("label") == RUNNER]
        self.assertEqual(entry["slo_hours"], 12)
        self.assertEqual(agent["schedule"], "interval:21600s")


class TheBehaviouralLedgerHasAReader(unittest.TestCase):
    """Журнал зонда G46 п. 1 не артефакт `data/`, и читатель у него ИМЕННОЙ.

    Зонд к мосту не подключён намеренно: один его прогон стои́т десятков
    прогонов pytest, и место ему — рука, а не шестичасовой агент. Но журнал
    без читателя был бы ровно тем дефектом, который меряет весь этот заказ,
    поэтому читателя проверяет отдельная проверка: перепись G45 обязана
    открывать журнал по ввезённому имени.
    """

    def test_the_census_names_the_ledger_and_the_probe_imports_that_name(self):
        from spa_core.monitoring import absent_path_probe as probe
        from spa_core.monitoring import call_sourced_input_census as csi
        self.assertEqual(probe.ARTIFACT, csi.BEHAVIOUR_LEDGER,
                         "второе имя журнала разошлось бы молча (ADR-418)")

    def test_the_census_reads_the_ledger_by_its_own_constant(self):
        from spa_core.monitoring import call_sourced_input_census as csi
        source = (REPO / csi.PRODUCER).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "load_probe_ledger"]
        self.assertEqual(len(calls), 1,
                         "перепись обязана открывать журнал ровно раз и ввезённым читателем")

    def test_the_probe_is_deliberately_absent_from_the_bridge(self):
        """ОБРАТНАЯ СТОРОНА: отсутствие объявлено, а не случилось."""
        self.assertNotIn("spa_core/monitoring/absent_path_ledger.json", fb.PRODUCES)
        self.assertNotIn("absent_path_probe", fb.CENSUS_STAGE)


if __name__ == "__main__":
    unittest.main()

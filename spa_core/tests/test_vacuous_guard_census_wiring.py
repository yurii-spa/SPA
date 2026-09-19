"""Проводка переписи вырожденных сторожей: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G44 п. 1** приказа владельца «Portfolio CIO», решение — ADR-420.

## Почему проверок несколько, а не одна

Проводка рвётся в шести местах, и каждое молчит по-своему:

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется НИКОГДА; скажет SLO часами позже и чужим голосом |
| `PRODUCES` (состав моста) | продукт не объявлен — сторож сиротства о нём не спросит |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` | ступень не числится переписью: «пропущено» не отличить от «не бывало» |
| `_READ_SCHEMA` + `_PRODUCER` офиса | шаг 0-офис файл не открывает — числа нет в контексте оркестратора |
| именная ветка отрисовки | файл ОТКРЫТ, прочитано ноль чисел («вхолостую») |
| обе записи конституции | SLO не назначен; агент утверждает, что продукта не производит |

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
from spa_core.monitoring import vacuous_guard_census as vgc
from spa_core.monitoring import vacuous_guard_probe as probe

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
ARTIFACT_REL = "data/vacuous_guard_census.json"
STAGE_KEY = "vacuous_guard_census"
RUNNER = "com.spa.decision_loop"


def _office():
    spec = importlib.util.spec_from_file_location("_office_vgc_under_test", OFFICE)
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

    def test_a_mere_mention_of_the_name_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА: проверка по подстроке пережила бы снятие зова."""
        fake = ast.parse("def main():\n"
                         f"    print('{STAGE_KEY}.run(root=args.root)')\n")
        self.assertEqual(
            [c for c in ast.walk(fake)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and c.func.attr == "run"], [])

    def test_producer_module_exposes_run_with_root(self):
        self.assertIn("root", inspect.signature(vgc.run).parameters)


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
        self.assertEqual(f"data/{vgc.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(vgc.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):
    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA["vacuous_guard_census.json"]
        for field in ("status", "invoked_by", "counts", "roles", "rows",
                      "unreadable", "empty_reachable_without_edit",
                      "what_it_does_not_prove"):
            self.assertIn(field, schema)

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = vgc.run(REPO, write=False)["doc"]
        for field in _office()._READ_SCHEMA["vacuous_guard_census.json"]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_producer_registry_names_the_module(self):
        self.assertEqual(_office()._PRODUCER["vacuous_guard_census.json"],
                         vgc.PRODUCER)

    def test_rendering_branch_exists_and_delegates_to_the_producer(self):
        tree = ast.parse(OFFICE.read_text(encoding="utf-8"))
        imports = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom)
                   and n.module == "spa_core.monitoring.vacuous_guard_census"
                   and any(a.name == "format_report" for a in n.names)]
        self.assertEqual(len(imports), 1,
                         "офис обязан ввозить отрисовку У ПРОИЗВОДИТЕЛЯ, ровно раз")
        branches = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Compare)
                    and any(isinstance(c, ast.Constant)
                            and c.value == "vacuous_guard_census.json"
                            for c in n.comparators)]
        self.assertTrue(branches,
                        "именной ветки отрисовки нет — файл читался бы вхолостую")

    def test_import_form_is_single_line(self):
        # Сторож достижимости вырезает ввозы ДВУХ объявленных форм; скобочная
        # многострочная ни одной из них не является (#627).
        lines = [ln for ln in OFFICE.read_text(encoding="utf-8").splitlines()
                 if "from spa_core.monitoring.vacuous_guard_census import" in ln]
        self.assertEqual(len(lines), 1)
        self.assertNotIn("(", lines[0])


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
        self.assertGreaterEqual(entry["slo_hours"] * 3600, 2 * 21600)


class TheHeavyHalfIsCalledByHandAndThatIsDeclared(unittest.TestCase):
    """Зонд стои́т сотен прогонов pytest — ступенью моста ему быть нельзя."""

    def test_the_probe_is_not_a_bridge_stage(self):
        self.assertNotIn("vacuous_guard_probe", fb.CENSUS_STAGE)
        self.assertNotIn(f"data/{Path(probe.ARTIFACT).name}", fb.PRODUCES)

    def test_but_the_probe_has_a_caller_in_code(self):
        """Прибор, которого не зовёт НИКТО, — файл (урок apy_spike_monitor).

        Зов ленивый и по просьбе: форма проверяется разбором, а не подстрокой.
        """
        tree = ast.parse((REPO / vgc.PRODUCER).read_text(encoding="utf-8"))
        calls = [c for c in ast.walk(tree)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                 and c.func.attr == "run" and isinstance(c.func.value, ast.Name)
                 and c.func.value.id == "vacuous_guard_probe"]
        self.assertEqual(len(calls), 1)

    def test_the_ledger_lives_next_to_the_code_not_in_data(self):
        """Журнал зонда есть замер ИСХОДНИКОВ, годный для sha, а не для суток."""
        self.assertTrue(vgc.PROBE_LEDGER.startswith("spa_core/monitoring/"))
        self.assertFalse(vgc.PROBE_LEDGER.startswith("data/"))
        self.assertEqual(probe.ARTIFACT, vgc.PROBE_LEDGER)


class TheInstrumentCountsITSOwnGuardsAndThatIsDeliberate(unittest.TestCase):
    """Сосед (ADR-417) своих сторожей исключает — здесь наоборот, и с причиной.

    Там исключение спасало от ЛОЖНОЙ находки: тест, редекларирующий константу
    прибора, был бы «второй копией» лишь потому, что прибор существует. Здесь
    вопрос «зелен ли этот сторож с пустым входом» осмыслен и про собственных
    сторожей — исключить их значило бы вывести из-под меры ровно тот код,
    который пишет сама мера.
    """

    def test_own_guards_are_in_the_population(self):
        rows = vgc.measure(REPO)["rows"]
        mine = {r["guard"] for r in rows if "vacuous_guard" in r["guard"]}
        self.assertTrue(mine, "перепись обязана видеть и своих сторожей")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

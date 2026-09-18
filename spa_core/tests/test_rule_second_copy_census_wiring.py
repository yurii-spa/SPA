"""Проводка переписи «одно правило — две копии»: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G41 п. 1** приказа владельца «Portfolio CIO», решение — ADR-417.

## Почему проверок несколько, а не одна

Проводка рвётся в шести местах, и каждое молчит по-своему — зелёный ответ на
один вопрос никогда не есть ответ на остальные:

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется НИКОГДА; про это скажет SLO часами позже и чужим голосом |
| `PRODUCES` (состав моста) | продукт не объявлен — сторож сиротства о нём не спросит |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` | ступень не числится переписью: «пропущено» не отличить от «не бывало» |
| `_READ_SCHEMA` + `_PRODUCER` офиса | шаг 0-офис файл не открывает — числа нет в контексте оркестратора |
| именная ветка отрисовки | файл ОТКРЫТ, прочитано ноль чисел («вхолостую») |
| обе записи конституции | SLO не назначен; агент утверждает, что продукта не производит |

У каждой проверки здесь обратная сторона: целое звено проходит, порванное
краснеет. Вызов ищется **разбором AST по ФОРМЕ вызова**, а не именем в тексте:
имя ловит собственный комментарий этого же файла, форма ловит зов (урок ADR-414).

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
from spa_core.monitoring import rule_second_copy_census as rsc

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
ARTIFACT_REL = "data/rule_second_copy_census.json"
STAGE_KEY = "rule_second_copy_census"
RUNNER = "com.spa.decision_loop"


def _office():
    spec = importlib.util.spec_from_file_location("_office_rsc_under_test", OFFICE)
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


def _calls_in(node: ast.AST) -> list:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


class ProducingCallExistsAndIsACallNotAName(unittest.TestCase):
    """Вызов ищется ПО ФОРМЕ. Имя в тексте вызовом не является (ADR-414)."""

    def test_bridge_main_calls_the_producer(self):
        found = []
        for call in _calls_in(_main_body()):
            f = call.func
            if isinstance(f, ast.Attribute) and f.attr == "run" \
                    and isinstance(f.value, ast.Name) and f.value.id == STAGE_KEY:
                found.append(call)
        self.assertEqual(len(found), 1,
                         f"в теле main() обязан быть ровно один зов {STAGE_KEY}.run(...)")
        self.assertIn("root", {k.arg for k in found[0].keywords},
                      "зов обязан передавать root: иначе ступень мерила бы дерево, "
                      "в котором её случайно запустили")

    def test_a_mere_mention_of_the_name_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА: проверка по подстроке пережила бы снятие зова."""
        fake = ast.parse(
            "def main():\n"
            f"    # ступень {STAGE_KEY} описана здесь словами\n"
            f"    print('{STAGE_KEY}.run(root=args.root)')\n")
        calls = [c for c in _calls_in(fake)
                 if isinstance(c.func, ast.Attribute) and c.func.attr == "run"]
        self.assertEqual(calls, [])

    def test_producer_module_exposes_run_with_root(self):
        self.assertIn("root", inspect.signature(rsc.run).parameters)


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
        """ОБРАТНАЯ СТОРОНА записи выше: объявить можно что угодно, поэтому имя
        сверяется с КОНСТАНТОЙ производителя, а не с собой же."""
        self.assertEqual(f"data/{rsc.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(rsc.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):

    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA["rule_second_copy_census.json"]
        for field in ("status", "invoked_by", "counts", "scanned", "classified",
                      "rows", "unreadable", "renamed_copy_surface"):
            self.assertIn(field, schema)

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = rsc.run(REPO, write=False)["doc"]
        for field in _office()._READ_SCHEMA["rule_second_copy_census.json"]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_producer_registry_names_the_module(self):
        self.assertEqual(_office()._PRODUCER["rule_second_copy_census.json"],
                         rsc.PRODUCER)

    def test_rendering_branch_exists_and_delegates_to_the_producer(self):
        """Второй копии правила отрисовки быть не должно — она и есть предмет
        этой самой переписи (ADR-220): копия расходится с оригиналом молча."""
        tree = ast.parse(OFFICE.read_text(encoding="utf-8"))
        imports = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom)
                   and n.module == "spa_core.monitoring.rule_second_copy_census"
                   and any(a.name == "format_report" for a in n.names)]
        self.assertEqual(len(imports), 1,
                         "офис обязан ввозить отрисовку У ПРОИЗВОДИТЕЛЯ, ровно раз")
        branches = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Compare)
                    and any(isinstance(c, ast.Constant)
                            and c.value == "rule_second_copy_census.json"
                            for c in n.comparators)]
        self.assertTrue(branches,
                        "именной ветки отрисовки нет — файл читался бы вхолостую")

    def test_import_form_is_single_line(self):
        # Сторож достижимости вырезает ввозы ДВУХ объявленных форм; скобочная
        # многострочная ни одной из них не является, и производитель остался бы
        # «импортированным» после мутации — накрытие было бы ложным (#627).
        lines = [ln for ln in OFFICE.read_text(encoding="utf-8").splitlines()
                 if "from spa_core.monitoring.rule_second_copy_census import" in ln]
        self.assertEqual(len(lines), 1)
        self.assertNotIn("(", lines[0])


class ConstitutionHasBothHomes(unittest.TestCase):
    """Домов два, и они отвечают на разные вопросы: «что это за число и когда
    протухает» и «кто обязан его производить»."""

    def test_artifact_entry(self):
        (entry,) = [a for a in _manifest()["artifacts"] if a.get("path") == ARTIFACT_REL]
        self.assertEqual(entry["producer"], RUNNER)
        self.assertEqual(entry["status"], "active")
        self.assertIn("orchestrator_protocol", entry["consumers"])
        self.assertTrue(entry["notes"].strip())

    def test_agent_passport_claims_the_product(self):
        (agent,) = [a for a in _manifest()["agents"] if a.get("label") == RUNNER]
        self.assertIn(ARTIFACT_REL, {p["artifact"] for p in agent["produces"]})

    def test_slo_is_the_runners_tact_not_the_neighbours_week(self):
        """SLO 12ч — замер, а не копия соседа.

        У недельных соседей SLO 192ч, потому что их зов стоит минуты. Этот зов
        стоит секунды и гейта такта не имеет вовсе, поэтому артефакт обязан
        обновляться КАЖДЫЙ прогон агента (6ч). Поставь сюда 192 — и полностью
        молчащая ступень считалась бы здоровой почти восемь суток.
        """
        doc = _manifest()
        (entry,) = [a for a in doc["artifacts"] if a.get("path") == ARTIFACT_REL]
        (agent,) = [a for a in doc["agents"] if a.get("label") == RUNNER]
        self.assertEqual(entry["slo_hours"], 12)
        self.assertEqual(agent["schedule"], "interval:21600s")
        self.assertLess(entry["slo_hours"], 192)
        self.assertGreaterEqual(entry["slo_hours"] * 3600, 2 * 21600,
                                "SLO обязан покрывать хотя бы два прогона бегуна")

    def test_both_homes_agree_on_the_slo(self):
        # ОБРАТНАЯ СТОРОНА: два дома — два места разойтись молча (ADR-220).
        doc = _manifest()
        (entry,) = [a for a in doc["artifacts"] if a.get("path") == ARTIFACT_REL]
        (agent,) = [a for a in doc["agents"] if a.get("label") == RUNNER]
        products = {p["artifact"]: p for p in agent["produces"]}
        self.assertEqual(entry["slo_hours"], products[ARTIFACT_REL]["slo_hours"])


class TheCensusHasNoTactGateAndSaysSo(unittest.TestCase):
    """Отсутствие гейта у самого прибора — РЕШЕНИЕ с причиной, а не недосмотр."""

    def test_run_takes_no_if_due_parameter(self):
        self.assertNotIn("if_due", inspect.signature(rsc.run).parameters)

    def test_the_producer_is_excluded_from_the_executor_population(self):
        """Проверяется САМО исключение, а не его следствие.

        Смотреть на строки отчёта было бы вакуумно: прибор не попал бы в них и
        без исключения — просто потому, что ни один сторож сегодня не
        редекларирует его констант. Поэтому спрашивается население.
        """
        files = {f.relative_to(REPO).as_posix() for f in rsc._executor_files(REPO)}
        self.assertNotIn(rsc.PRODUCER, files)

    def test_a_sibling_module_IS_in_the_population(self):
        """ОБРАТНАЯ СТОРОНА: население не пусто и сосед в нём есть — иначе
        проверка выше проходила бы от того, что список пуст."""
        files = {f.relative_to(REPO).as_posix() for f in rsc._executor_files(REPO)}
        self.assertIn("spa_core/monitoring/tact_gate_census.py", files)


class TheGuardsOfThisInstrumentDoNotBecomeItsOwnFinding(unittest.TestCase):
    """Сторож переписи не имеет права сам оказаться её находкой.

    Это не косметика: тест, редекларировавший константу прибора, печатался бы в
    отчёте как находка, и первая же строка живого чтения была бы про нас самих.
    """

    def test_own_test_files_are_not_rows(self):
        rows = rsc.measure(REPO)["rows"]
        mine = {r["guard"] for r in rows if "rule_second_copy_census" in r["guard"]}
        self.assertEqual(mine, set())


if __name__ == "__main__":
    unittest.main()

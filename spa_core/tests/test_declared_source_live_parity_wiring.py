"""Проводка переписи «верность реестра источников»: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G103 п. 1** приказа владельца «Portfolio CIO», решение — ADR-594.

## Почему этот файл существует

По уроку ADR-427 запись в реестре исполнением не является, а по уроку памяти
цикла #760 общий храповик проводки зачтёт за вызов ИМПОРТ. Поэтому вызов
ищется разбором AST **ПО ФОРМЕ ВЫЗОВА**, а не именем в тексте: имя ловит
собственный комментарий этого же файла.

## Проводка рвётся в шести местах, и каждое молчит по-своему

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется НИКОГДА; скажет SLO часами позже и чужим голосом |
| `PRODUCES` (состав моста) | продукт не объявлен — сторож сиротства о нём не спросит |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` | ступень не числится переписью: «пропущено» не отличить от «не бывало» |
| `_READ_SCHEMA` + `_PRODUCER` офиса | шаг 0-офис файл не открывает — числа нет в контексте оркестратора |
| именная ветка отрисовки | файл ОТКРЫТ, прочитано ноль чисел («вхолостую») |
| запись манифеста | SLO не назначен; агент утверждает, что продукта не производит |

**Седьмого звена — ПОРЯДКА — у этой ступени НЕТ, и это не упущение.** Операнд
ей даёт НЕ мост, а живой кустодиан (`com.spa.site_freshness`, такт 6 ч),
поэтому сверять номер строки с соседними ступенями значило бы закрепить
договорённость, которой ответ не зависит. Взамен закреплено, что ступень в
сеть НЕ ходит: ходящая в сеть ступень превратила бы «сеть легла» в
«страница изменилась».

Живое `data/` на запись не открывается ни одной проверкой. Литеральных дат
нет вовсе.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime as dt
import functools
import importlib.util
import inspect
import json
import unittest
from pathlib import Path

from spa_core.monitoring import declared_source_live_parity as D
from spa_core.monitoring import findings_bridge as fb

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
PRODUCER_FILE = REPO / D.PRODUCER
ARTIFACT_REL = "data/declared_source_live_parity.json"
ARTIFACT_NAME = "declared_source_live_parity.json"
STAGE_KEY = "declared_source_live_parity"
RUNNER = "com.spa.decision_loop"

#: Часы сцены — «сейчас». Литеральной даты нет: отметка записи считается ОТ
#: них, и календарь на вердикт не влияет.
NOW = dt.datetime.now(dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location("_office_dslp_under_test",
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


@functools.lru_cache(maxsize=1)
def _doc() -> dict:
    """Документ на ЖИВОМ дереве с ЗАПИСЬЮ, поданной входом.

    Запись подаётся прямо намеренно: предмет этих тестов — ФОРМА документа и
    его проводка, а не состояние живого сайта. Читать отчёт кустодиана здесь
    значило бы поставить проводку в зависимость от того, запускался ли
    отдельный агент — и батарея краснела бы от погоды, а не от кода.
    """
    spec = importlib.util.spec_from_file_location(
        "_sfm_for_wiring", REPO / "scripts" / "site_freshness_monitor.py")
    sfm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sfm)
    registry = {"a": (("home", "live", r'id="live"[^>]*>\s*(\d+)', "живой"),
                      ("home", "dead", r'id="dead"[^>]*>\s*(\d+)', "мёртвый")),
                "b": (("home", "live2", r'id="live2"[^>]*>\s*(\d+)', "живой"),)}
    pages = {"home": '<i id="live">3</i><i id="live2">4</i>'}
    record = {"ts": NOW.isoformat(),
              "declared_source_probes": sfm.probe_declared_sources(
                  pages, sources=registry)}
    return D.run(REPO, write=False, now=NOW, record=record,
                 registry=registry)["doc"]


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

    def test_producer_module_exposes_run_with_root(self):
        self.assertIn("root", inspect.signature(D.run).parameters)


class TheStageDoesNotGoToTheNETWORK(unittest.TestCase):
    """Сеть — дверь кустодиана, а не прибора, и это ЗАКРЕПЛЕНО.

    Ступень, скачивающая страницу сама, отвечала бы о другом мгновении и от
    другого скачивателя, а «сеть легла» стало бы неотличимо от «страница
    изменилась» — то есть отказ читался бы находкой.
    """

    def test_the_producer_imports_no_network_module(self):
        tree = ast.parse(PRODUCER_FILE.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        for forbidden in ("urllib", "http", "socket", "requests", "ssl"):
            self.assertNotIn(forbidden, names,
                             f"прибор ввёз {forbidden} — операнд обязан "
                             f"приходить отчётом кустодиана, а не своей "
                             f"ходкой в сеть")

    def test_the_operand_is_the_custodian_report(self):
        self.assertEqual(D.OPERAND, "data/site_freshness_report.json")
        self.assertTrue((REPO / D.REGISTRY_MODULE).is_file())


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
        self.assertEqual(f"data/{D.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(D.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):
    def test_the_producer_is_named(self):
        self.assertEqual(_office()._PRODUCER[ARTIFACT_NAME], D.PRODUCER)

    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        for field in ("status", "invoked_by", "order", "population",
                      "outcomes", "label_outcomes", "refuted",
                      "operand_age_hours", "rows", "what_it_does_not_prove"):
            self.assertIn(field, schema)

    def test_the_loud_and_the_silent_are_declared_separately(self):
        """Слить их в одно поле значило бы спрятать находку заказа.

        У громкого опровержения кустодиан краснеет сам, у молчаливого не
        краснеет никто (замер 06.10: 0 и 3). Схема, объявившая только сумму,
        разрешила бы читателю не заметить разницы.
        """
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        self.assertIn("refuted_silently", schema)
        self.assertIn("refuted_loudly", schema)

    def test_the_separate_observations_are_declared_too(self):
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        self.assertIn("ambiguous_duplicate_ids", schema)
        self.assertIn(D.RECORD_ORPHANS, schema)

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = _doc()
        for field in _office()._READ_SCHEMA[ARTIFACT_NAME]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_the_named_branch_prints_real_numbers_not_an_empty_read(self):
        """Живой контроль: ветка обязана печатать ЧИСЛА, а не открыть файл."""
        lines = _office()._summarize_json(ARTIFACT_REL, _doc())
        self.assertGreaterEqual(len(lines), 5, lines)
        self.assertTrue(any("ЧИСЛО ЗАКАЗА" in line for line in lines), lines)
        self.assertTrue(any("ВОЗРАСТ ОТВЕТА" in line for line in lines), lines)
        self.assertTrue(any("ДРУГИЕ УТВЕРЖДЕНИЯ" in line for line in lines),
                        lines)

    def test_an_unmeasured_document_is_not_rendered_as_clean(self):
        """ОБРАТНАЯ СТОРОНА: третий исход обязан дойти до читателя третьим."""
        doc = {"status": "UNMEASURED",
               "reason": f"{D.GAP_NO_OPERAND}: отчёта кустодиана нет"}
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


class TheLiveAnswerIsMeasuredNotAssumed(unittest.TestCase):
    """Один прогон на живом дереве — и ответ в нём ОБЪЯВЛЕН, а не предположен."""

    def test_the_run_is_measured_and_advisory(self):
        doc = _doc()
        self.assertEqual(doc["status"], "MEASURED")
        self.assertIs(doc["applied"], False)

    def test_every_declared_source_gets_one_outcome(self):
        doc = _doc()
        self.assertEqual(sum(doc["outcomes"].values()), doc["population"])
        self.assertGreater(doc["population"], 0,
                           "объявленных источников ноль — тогда ответ заказа "
                           "пуст по ПОСТРОЕНИЮ, и это находка, а не норма")

    def test_the_order_numbers_are_integers_not_none(self):
        """«НЕ ИЗМЕРЕНО» у головного числа — отказ, а не ноль (инв. #17)."""
        doc = _doc()
        for field in ("refuted", "refuted_silently", "refuted_loudly",
                      "ambiguous_duplicate_ids", D.RECORD_ORPHANS):
            self.assertIsInstance(doc[field], int, field)

    def test_the_live_registry_itself_is_readable_today(self):
        """Реестр кустодиана обязан читаться НА ЖИВОМ дереве.

        Иначе ступень честно отказывает каждый такт, и отказ «реестр не
        прочитан» читался бы как свойство сайта, а не как поломка проводки.
        """
        table = D.load_registry(REPO)
        self.assertGreater(sum(len(v) for v in table.values()), 0)


if __name__ == "__main__":
    unittest.main()

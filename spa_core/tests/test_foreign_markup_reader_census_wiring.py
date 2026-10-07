"""Проводка переписи читателей чужой разметки: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G103 п. 2** приказа владельца «Portfolio CIO», решение — ADR-620.

## Почему этот файл существует

Запись в реестре исполнением не является (урок ADR-427), а общий храповик
проводки зачтёт за вызов ИМПОРТ (урок памяти цикла #760). Поэтому вызов
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

**Седьмого звена — ПОРЯДКА — у этой ступени НЕТ, и это не упущение.** Оракулом
ей служит САМО ДЕРЕВО, а не продукт соседней ступени, поэтому сверять номер
строки с соседями значило бы закрепить договорённость, от которой ответ не
зависит. Взамен закреплено, что ступень в сеть НЕ ходит.

Живое `data/` на запись не открывается ни одной проверкой.
FROZEN-DATE-OK: injected-clock — якорь :data:`NOW` уходит параметром `now=` в
`measure`/`run`, литеральной даты в файле нет вовсе.
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

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import foreign_markup_reader_census as F

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
PRODUCER_FILE = REPO / F.PRODUCER
ARTIFACT_REL = "data/foreign_markup_reader_census.json"
ARTIFACT_NAME = "foreign_markup_reader_census.json"
STAGE_KEY = "foreign_markup_reader_census"
RUNNER = "com.spa.decision_loop"

#: Часы сцены. Литеральной даты нет: отметка документа считается ОТ них.
NOW = dt.datetime.now(dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location("_office_fmrc_under_test",
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
    """ОДИН замер живого дерева на весь файл.

    Общий кэш — не украшение: замер стоит ~50 с, а спрашивают его шесть
    проверок. Повторять его шесть раз значило бы добавить к приёмочному
    прогону пять минут за тот же ответ.
    """
    return F.run(REPO, write=False, now=NOW)["doc"]


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
        self.assertIn("root", inspect.signature(F.run).parameters)


class TheStageDoesNotGoToTheNETWORK(unittest.TestCase):
    """Оракул — дерево, а не сеть, и это ЗАКРЕПЛЕНО (та же граница, ADR-594).

    Ступень, скачивающая страницу сама, превратила бы «сеть легла» в
    «личность уехала», то есть отказ читался бы находкой.
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
                             f"прибор ввёз {forbidden} — оракулом обязано "
                             f"быть дерево, а не своя ходка в сеть")

    def test_the_one_sidedness_of_a_tree_oracle_is_declared_in_the_document(self):
        """Односторонность обязана жить В ОТВЕТЕ, а не в чужом ADR.

        `REFUTED` здесь означает «дерево этого не пишет», и НЕ означает «на
        earn-defi.com этого нет»: старая сборка на CDN умеет нести мёртвый id.
        Читатель, получивший число без этой строки, прочтёт его сильнее, чем
        оно есть.
        """
        said = " ".join(_doc()["what_it_does_not_prove"])
        self.assertIn("CDN", said)
        self.assertIn("посетител", said)


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
        self.assertEqual(f"data/{F.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(F.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):
    def test_the_producer_is_named(self):
        self.assertEqual(_office()._PRODUCER[ARTIFACT_NAME], F.PRODUCER)

    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        for field in ("status", "invoked_by", "order", "population",
                      "foreign_population", "judged", "unsupported",
                      "rows", "what_it_does_not_prove"):
            self.assertIn(field, schema)

    def test_the_two_halves_of_the_harm_are_declared_separately(self):
        """Слить «нигде» и «только своя сцена» значило бы спрятать находку.

        У второго подтверждение ЕСТЬ и оно поддельное — читается это иначе,
        хотя чинится одинаково. Схема, объявившая только сумму, разрешила бы
        не заметить разницы (замер 07.10: 2 и 6).
        """
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        self.assertIn("refuted", schema)
        self.assertIn("echoed_by_own_scene", schema)

    def test_the_unmeasured_remainder_is_declared_too(self):
        """Остаток «происхождение не свёрнуто» обязан быть в схеме.

        Он в класс НЕ зачтён, и молчание о нём читалось бы как чистота.
        """
        self.assertIn("origin_unresolved",
                      _office()._READ_SCHEMA[ARTIFACT_NAME])

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = _doc()
        for field in _office()._READ_SCHEMA[ARTIFACT_NAME]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_the_named_branch_prints_real_numbers_not_an_empty_read(self):
        """Живой контроль: ветка обязана печатать ЧИСЛА, а не открыть файл."""
        lines = _office()._summarize_json(ARTIFACT_REL, _doc())
        self.assertGreaterEqual(len(lines), 4, lines)
        text = "\n".join(lines)
        self.assertIn("НЕ ПОДТВЕРЖДЕНО НИЧЕМ, КРОМЕ СЕБЯ", text)
        self.assertIn("оракул:", text)

    def test_an_unmeasured_document_is_not_rendered_as_clean(self):
        """ОБРАТНАЯ СТОРОНА: третий исход обязан дойти до читателя третьим."""
        doc = {"status": "UNMEASURED", "order": F.ORDER,
               "gap": F.GAP_NO_CODE, "reason": f"{F.GAP_NO_CODE}: пусто"}
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

    def test_every_site_of_the_class_gets_exactly_one_parity(self):
        doc = _doc()
        self.assertEqual(sum(doc["parity_outcomes"].values()),
                         doc["foreign_population"])
        self.assertGreater(doc["foreign_population"], 0,
                           "класс пуст — тогда ответ заказа пуст ПО "
                           "ПОСТРОЕНИЮ, и это находка, а не норма")

    def test_the_order_numbers_are_integers_not_none(self):
        """«НЕ ИЗМЕРЕНО» у головного числа — отказ, а не ноль (инв. #17)."""
        doc = _doc()
        for field in ("population", "foreign_population", "judged",
                      "unsupported", "refuted", "echoed_by_own_scene",
                      "origin_unresolved", "enumerators_out_of_class",
                      "behind_a_module_level_skip"):
            self.assertIsInstance(doc[field], int, field)

    def test_the_class_is_wider_than_the_custodian(self):
        """Утверждение самого заказа, проверенное замером, а не прозой.

        Заказ сказал «класс шире кустодиана». Если читателей в ответе ровно
        один, значит признак снова отвечает на свой вопрос вместо нужного.
        """
        doc = _doc()
        self.assertIn(F.REGISTRY_READER, doc["readers"])
        self.assertGreater(len(doc["readers"]), 1,
                           "кустодиан в классе один — предпосылка заказа "
                           "НЕ подтверждена, и это находка о приборе")


if __name__ == "__main__":
    unittest.main()

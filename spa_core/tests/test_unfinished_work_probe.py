"""Контроли пробы `unfinished_work_class_population_named` (ADR-908, заказ G900 п. 1).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с батареей, где
она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с названным звеном, —
и где она не проходит ПОДСТРОКОЙ. Проба, никогда не видевшая настоящей поломки,
остаётся украшением.

Контур здесь — ОБЪЯВЛЕНИЕ класса: оно и есть то, чем следующий цикл берёт замер даром,
и именно его отсутствие заставило циклы #1018 и #1022 платить за замер дважды.

FROZEN-DATE-OK: golden-document — проба часов не спрашивает ВОВСЕ: её предмет — документ,
и литеральная дата внизу есть ПОЛЕ проверяемого документа (`measured_at`), то есть сама
дата здесь и является предметом. Причина намеренно НЕ `injected-clock`: инъецировать
здесь нечего, а записка с чужой причиной — ровно та бомба с запиской, против которой
сторож претензии и написан (`.claude/rules/deployment.md`, цикл #477).
"""

# FROZEN-DATE-OK: golden-document — часов проба не спрашивает ВОВСЕ: её предмет
# документ, и литеральная дата ниже есть ПОЛЕ проверяемого документа
# (`measured_at`), то есть сама дата здесь и является предметом. Причина
# намеренно НЕ `injected-clock`: инъецировать нечего, а записка с чужой
# причиной — та же бомба, только с запиской (цикл #477).
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts import unfinished_work_census as census
from spa_core.monitoring import card_acceptance as ca

PROBE = ca.PROBES["unfinished_work_class_population_named"]

WHOLE = {
    "schema_version": 1,
    "adr": "ADR-908", "order": "G900 п. 1",
    "instrument": "scripts/unfinished_work_census.py",
    "measured_in": "цикл #1023, журнал 3306 записей",
    "base_sha": "138c26117", "measured_at": "2026-11-03T19:28:04Z",
    "axis_one": {
        "class_members": 3, "strong_sign": 5, "weak_sign": 145,
        "judged_paths": 2260, "unmeasured_paths": 12037,
        "sign_precision": "3/5", "sign_false_positives": 2,
        "rows": [
            {"session": "cycle-20600", "path": "/private/tmp/spa_c1019/b.json",
             "verdict": census.CLASS, "evidence": "прямой ls: файла нет"},
            {"session": "cycle-48282", "path": "/Users/x/SPA_wt_c1011/c.py",
             "verdict": census.RENAME, "evidence": "уехало как _subprocess_clock_door.py"},
        ],
    },
    "axis_two": {"supply_on_disk": 1472, "named_by_the_record": 14,
                 "named_of_supply": 14, "unmeasured_while_walking": 0},
    "seam": {"chosen": "в — порядок подъёма в правиле", "why": "точность признака 3/5",
             "refused": [{"option": "б", "price": "40 % ложных «не закончено»"}]},
}


def _broken(**mutations):
    doc = copy.deepcopy(WHOLE)
    for path, value in mutations.items():
        keys = path.split("__")
        node = doc
        for key in keys[:-1]:
            node = node[key]
        if value is ...:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return doc


class WholeContourTest(unittest.TestCase):

    def test_the_probe_is_green_on_the_whole_contour(self):
        state, detail = PROBE(declaration=WHOLE, module=census)
        self.assertEqual(ca.SATISFIED, state)
        # Числа ПЕЧАТАЮТСЯ из документа, а не постоянной строкой: проба, чей ответ не
        # зависит от входа, зелена и на пустом объявлении.
        self.assertIn("членов 3 из 5", detail)
        self.assertIn("1472", detail)
        self.assertIn("названо записью 14", detail)

    def test_the_probe_answers_about_the_delivered_declaration_too(self):
        state, detail = PROBE()
        self.assertEqual(ca.SATISFIED, state, detail)


class BrokenLinkTest(unittest.TestCase):
    """На каждое порванное звено — свой красный, и звено НАЗВАНО в строке."""

    def _red(self, doc, needle, *, expect=ca.NOT_SATISFIED):
        state, detail = PROBE(declaration=doc, module=census)
        self.assertEqual(expect, state, detail)
        self.assertIn(needle, detail)

    def test_a_measurement_without_provenance_is_red(self):
        for field in ("adr", "order", "instrument", "measured_in", "base_sha",
                      "measured_at"):
            with self.subTest(field=field):
                self._red(_broken(**{field: ""}), field)

    def test_an_empty_axis_one_is_red_not_green(self):
        self._red(_broken(axis_one__rows=[]), "ни одной разобранной строки")

    def test_a_row_with_a_verdict_outside_the_dictionary_is_red(self):
        doc = copy.deepcopy(WHOLE)
        doc["axis_one"]["rows"][0]["verdict"] = "наверное"
        self._red(doc, "не из словаря прибора")

    def test_a_row_without_evidence_is_red(self):
        doc = copy.deepcopy(WHOLE)
        doc["axis_one"]["rows"][0]["evidence"] = "   "
        self._red(doc, "без доказательства")

    def test_an_axis_one_number_replaced_by_prose_is_red(self):
        for field in ("class_members", "strong_sign", "judged_paths",
                      "unmeasured_paths"):
            with self.subTest(field=field):
                self._red(_broken(**{f"axis_one__{field}": "много"}), field)

    def test_one_half_of_axis_two_without_the_other_is_red(self):
        for field in ("supply_on_disk", "named_by_the_record"):
            with self.subTest(field=field):
                self._red(_broken(**{f"axis_two__{field}": ...}),
                          "одна половина без другой")

    def test_a_seam_that_is_not_named_is_red(self):
        self._red(_broken(seam__chosen=""), "шов не назван")

    def test_a_seam_without_a_reason_is_red(self):
        self._red(_broken(seam__why=""), "нет причины")

    def test_a_seam_without_the_price_of_alternatives_is_red(self):
        self._red(_broken(seam__refused=[]), "цена отвергнутых")

    def test_a_refused_path_without_a_price_is_red(self):
        self._red(_broken(seam__refused=[{"option": "б"}]), "не названа ЦЕНА")


class ThirdOutcomeTest(unittest.TestCase):
    """НЕ ИЗМЕРЕНО отличается от «вопрос отвечен нет» — инв. #17."""

    def test_a_foreign_schema_is_unmeasured_not_a_refusal(self):
        state, detail = PROBE(declaration={"schema_version": 7}, module=census)
        self.assertEqual(ca.UNMEASURED, state)
        self.assertIn("схема объявления не та", detail)

    def test_a_declaration_that_is_not_an_object_is_unmeasured(self):
        state, _detail = PROBE(declaration=["строка"], module=census)
        self.assertEqual(ca.UNMEASURED, state)

    def test_a_missing_section_is_unmeasured_not_a_refusal(self):
        for section in ("axis_one", "axis_two", "seam"):
            with self.subTest(section=section):
                state, detail = PROBE(declaration=_broken(**{section: ...}),
                                      module=census)
                self.assertEqual(ca.UNMEASURED, state)
                self.assertIn(section, detail)

    def test_an_unreadable_declaration_is_unmeasured(self):
        class _Stub:
            PROJECT_ROOT = Path("/private/tmp/нет-такого-дерева-1023")
            DECLARATION_REL = "spa_core/tests/unfinished_work_class_baseline.json"
            VERDICTS = census.VERDICTS
        state, detail = PROBE(module=_Stub())
        self.assertEqual(ca.UNMEASURED, state)
        self.assertIn("не прочитано", detail)


class SubstringTest(unittest.TestCase):
    """Проба не проходит ПОДСТРОКОЙ: она читает ПОЛЯ, а не текст файла."""

    def test_a_file_that_merely_mentions_the_words_is_not_satisfied(self):
        prose = {"schema_version": 1, "adr": "ADR-908", "order": "G900 п. 1",
                 "instrument": "scripts/unfinished_work_census.py",
                 "measured_in": "ось 1 измерена, ось 2 измерена, шов выбран, цена названа",
                 "base_sha": "138c26117", "measured_at": "2026-11-03T19:28:04Z",
                 "axis_one": {"rows": [], "class_members": "три",
                              "strong_sign": "пять", "judged_paths": "много",
                              "unmeasured_paths": "почти всё"},
                 "axis_two": {"supply_on_disk": "много", "named_by_the_record": "мало"},
                 "seam": {"chosen": "в", "why": "так лучше", "refused": [{"option": "б"}]}}
        state, detail = PROBE(declaration=prose, module=census)
        self.assertEqual(ca.NOT_SATISFIED, state)
        self.assertIn("ни одной разобранной строки", detail)
        self.assertIn("не названа ЦЕНА", detail)


class WriterParityTest(unittest.TestCase):
    """Писатель и проба судят ОДИН документ: расхождение словарей = ложный зелёный."""

    def test_the_probe_uses_the_instruments_verdict_dictionary(self):
        self.assertEqual(("class", "rename"), census.VERDICTS)
        doc = json.loads((Path(census.PROJECT_ROOT) / census.DECLARATION_REL)
                         .read_text(encoding="utf-8"))
        for row in doc["axis_one"]["rows"]:
            self.assertIn(row["verdict"], census.VERDICTS)


if __name__ == "__main__":
    unittest.main()

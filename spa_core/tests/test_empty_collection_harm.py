#!/usr/bin/env python3
"""Сторож признака и объявления класса «перечень ВРЕДЕН пустым» (ADR-944).

# LLM_FORBIDDEN

Каждая проба ниже — положительный контроль: сцена, воспроизводящая НАСТОЯЩУЮ форму из
дерева, и у половины сцен ответ ПРОТИВОПОЛОЖНЫЙ соседней. Проверка, никогда не видевшая
поломки, — украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

Несущая проба здесь — `test_the_known_member_of_the_class_is_seen`: признак, построенный
дословно по формулировке заказа G933 п. 2 («тело цикла ДОПИСЫВАЕТ в перечень находок»),
НЕ ВИДЕЛ единственного ИЗВЕСТНОГО члена класса (ADR-939: `any(… for … in AGGRAVATING)`),
и цена этой слепоты — четверть населения (291 против 390). Проба краснеет, если
`SILENT_FOLDS` снова уедет в «ничего не производит».
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.tests import _empty_collection_harm as harm


def _scene(tmp: Path, module_src: str, reader_src: str) -> dict:
    """Одноразовая сцена: объявление + читатель. Возвращает строку переписи в той
    форме, в которой её отдаёт `census()["rows"]` — прибор не должен знать, что
    сцена синтетическая."""
    (tmp / "decl.py").write_text(module_src)
    (tmp / "reader.py").write_text(reader_src)
    line = next(i for i, text in enumerate(reader_src.splitlines(), 1) if "NEEDLE" in text)
    return {
        "module": "decl.py", "name": "NEEDLE", "lineno": 1, "form": "tuple",
        "reads": {"loop": [f"reader.py:{line}"], "emptiness": [], "other": []},
    }


class ProductionSignal(unittest.TestCase):
    """Признак приоритизации: ТИХАЯ пустота против ГРОМКОЙ и против отсутствия вреда."""

    def _measure(self, reader_src: str) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            row = _scene(tmp, "NEEDLE = ('a', 'b')\n", reader_src)
            result = harm.production([row], root=tmp)
            self.assertEqual(result["tally"]["unmeasured"] + result["tally"]["produces"]
                             + result["tally"]["no_production"], 1)
            return result["rows"][0]

    def test_the_known_member_of_the_class_is_seen(self):
        """ADR-939 дословно: `any` над пустым даёт False, то есть «находок нет» МОЛЧА."""
        row = self._measure("def check(doc):\n"
                            "    return any(doc.get(k) for k in NEEDLE)\n")
        self.assertEqual(row["production"], "produces", row["why"])
        self.assertIn("any()", " ".join(row["why"]))

    def test_all_over_empty_is_true_for_every_row(self):
        row = self._measure("def check(doc):\n"
                            "    return all(doc.get(k) for k in NEEDLE)\n")
        self.assertEqual(row["production"], "produces", row["why"])

    def test_sum_over_empty_is_zero_findings(self):
        row = self._measure("def total(doc):\n"
                            "    return sum(doc.get(k, 0) for k in NEEDLE)\n")
        self.assertEqual(row["production"], "produces", row["why"])

    def test_min_over_empty_is_loud_and_therefore_not_a_candidate(self):
        """`min`/`max` над пустым ПОДНИМАЮТ ValueError — пустота замечена ГРОМКО."""
        row = self._measure("def earliest(doc):\n"
                            "    return min(doc[k] for k in NEEDLE)\n")
        self.assertEqual(row["production"], "no_production", row["why"])
        self.assertIn("ValueError", " ".join(row["why"]))

    def test_loop_body_appending_a_finding_is_a_candidate(self):
        row = self._measure("def findings(doc):\n"
                            "    out = []\n"
                            "    for k in NEEDLE:\n"
                            "        out.append(k)\n"
                            "    return out\n")
        self.assertEqual(row["production"], "produces", row["why"])
        self.assertIn(".append()", " ".join(row["why"]))

    def test_loop_body_that_only_validates_is_not_a_candidate(self):
        """Вред тут ЕСТЬ (ничего не провалидировано), но признак о НЁМ не говорит —
        и ровно поэтому признак не вправе быть пятой осью предмета."""
        row = self._measure("def validate(doc):\n"
                            "    for k in NEEDLE:\n"
                            "        assert k in doc\n")
        self.assertEqual(row["production"], "no_production", row["why"])

    def test_yield_in_the_loop_body_is_a_candidate(self):
        row = self._measure("def walk(doc):\n"
                            "    for k in NEEDLE:\n"
                            "        yield doc.get(k)\n")
        self.assertEqual(row["production"], "produces", row["why"])

    def test_comprehension_collecting_is_a_candidate(self):
        row = self._measure("def pick(doc):\n"
                            "    return [doc[k] for k in NEEDLE]\n")
        self.assertEqual(row["production"], "produces", row["why"])

    def test_unparsable_reader_is_unmeasured_not_harmless(self):
        """Третий исход (инв. #17): файл не разобран — это НЕ `no_production`."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "reader.py").write_text("def broken(:\n    for k in NEEDLE:\n        pass\n")
            row = {"module": "decl.py", "name": "NEEDLE", "lineno": 1, "form": "tuple",
                   "reads": {"loop": ["reader.py:2"], "emptiness": [], "other": []}}
            result = harm.production([row], root=tmp)
        self.assertEqual(result["rows"][0]["production"], "unmeasured")
        self.assertEqual(result["tally"]["no_production"], 0)
        self.assertIn("reader.py", result["unparsable_readers"])

    def test_missing_read_node_is_unmeasured(self):
        """Строка названа, а имени на ней нет — предпосылка не обеспечена."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "reader.py").write_text("x = 1\ny = 2\n")
            row = {"module": "decl.py", "name": "NEEDLE", "lineno": 1, "form": "tuple",
                   "reads": {"loop": ["reader.py:2"], "emptiness": [], "other": []}}
            result = harm.production([row], root=tmp)
        self.assertEqual(result["rows"][0]["production"], "unmeasured")

    def test_no_loop_read_at_all_is_unmeasured_not_a_candidate(self):
        result = harm.production(
            [{"module": "decl.py", "name": "NEEDLE", "lineno": 1, "form": "tuple",
              "reads": {"loop": [], "emptiness": [], "other": ["reader.py:9"]}}],
            root=Path(tempfile.gettempdir()))
        self.assertEqual(result["rows"][0]["production"], "unmeasured")
        self.assertEqual(result["tally"]["produces"], 0)

    def test_one_silent_loop_among_many_is_enough(self):
        """Решение в сторону НАХОДКИ: правило «все циклы обязаны производить»
        ошибалось бы в сторону НЕнаходки."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "reader.py").write_text(
                "def a(doc):\n"
                "    for k in NEEDLE:\n"
                "        assert k\n"
                "def b(doc):\n"
                "    return [doc[k] for k in NEEDLE]\n")
            row = {"module": "decl.py", "name": "NEEDLE", "lineno": 1, "form": "tuple",
                   "reads": {"loop": ["reader.py:2", "reader.py:5"], "emptiness": [], "other": []}}
            result = harm.production([row], root=tmp)
        self.assertEqual(result["rows"][0]["production"], "produces")

    def test_outcome_vocabulary_is_closed_and_exhausted(self):
        """Словарь исходов ЗАМКНУТ, и тальи считаются только по его членам —
        иначе новый исход утонул бы в молчании (урок ADR-943)."""
        self.assertEqual(set(harm.PRODUCTION_OUTCOMES),
                         {"produces", "no_production", "unmeasured"})
        self.assertFalse(set(harm.SILENT_FOLDS) & set(harm.LOUD_FOLDS),
                         "свёртка не может быть тихой и громкой одновременно")


class BaselineDeclaration(unittest.TestCase):
    """Объявление класса ИМЕНАМИ. Отсутствие объявления — НЕ «класс пуст»."""

    def test_missing_file_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(harm.Unmeasured):
                harm.load_baseline(Path(raw) / "нет-такого.json")

    def test_unparsable_file_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "b.json"
            path.write_text("{не json")
            with self.assertRaises(harm.Unmeasured):
                harm.load_baseline(path)

    def test_declaration_without_its_own_provenance_is_unmeasured(self):
        """Объявление обязано нести СВОЙ контракт: когда и на каком коммите мерено,
        и какова ОБЛАСТЬ замера. Без неё «harmful: []» читалось бы как «вреда нет»,
        хотя мерили один пакет из сорока."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "b.json"
            path.write_text(json.dumps({"harmful": []}))
            with self.assertRaises(harm.Unmeasured):
                harm.load_baseline(path)

    def test_live_declaration_is_readable_and_names_its_scope(self):
        doc = harm.load_baseline()
        self.assertTrue(doc["measured_on_commit"], "коммит замера не назван")
        self.assertTrue(doc["scope"], "область замера не названа")
        self.assertIsInstance(doc["harmful"], list)
        for entry in doc["harmful"]:
            for field in ("module", "name", "lineno", "form", "tests", "summary"):
                self.assertIn(field, entry, f"запись класса без поля {field!r}: {entry}")

    def test_key_is_paired_not_a_bare_name(self):
        """ADR-942: одноимённые перечни разных модулей не делят ни чтений, ни
        противоядий — значит не вправе делить и записи класса."""
        self.assertNotEqual(harm.key("a/x.py", "N"), harm.key("b/x.py", "N"))


if __name__ == "__main__":
    unittest.main()

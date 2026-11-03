# LLM_FORBIDDEN
"""spa_core/tests/test_tree_content_class_probe.py — контроли пробы приёмки
`tree_content_class_declaration_holds` (ADR-907, карточка
`inbox-verdikt-pyatnadtsati-testov-zavisit-ot-s`).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется в
`card_acceptance.PROBES` ТОЛЬКО с тестом, где она зелёная на ЦЕЛОМ контуре и
красная на КАЖДОМ порванном звене — с названным звеном, — и где она НЕ проходит
подстрокой (ADR-333).

Поэтому здесь:

* зелёная сцена зовёт пробу БЕЗ ЕДИНОЙ инъекции — настоящий файл объявления,
  настоящее дерево, настоящие читатели. Сцена на словаре, собранном руками,
  мерила бы свой словарь, а не проводку (урок #944/#945);
* каждая красная сцена рвёт ОДНО звено и проверяется по ИСХОДУ пробы плюс
  названному в строке предмету;
* анти-подстрочная сцена даёт объявление, в котором все нужные слова есть, а
  названного теста в дереве НЕТ: проба обязана отказать.

Проба берётся ИЗ РЕЕСТРА (`PROBES[...]`), а не импортом приватной функции: иначе
тест зеленел бы и у пробы, которую забыли зарегистрировать.

Только stdlib, оффлайн. Литеральных дат нет — свежести проба не судит.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.tests import test_tree_content_class_ratchet as ratchet

PROBE_NAME = "tree_content_class_declaration_holds"

#: Член, который существует НАВЕРНЯКА: имя взято из этого же файла.
_LIVE_MEMBER = {
    "nodeid": "spa_core/tests/test_tree_content_class_probe.py::ProbeControlsTest::"
              "test_the_whole_contour_is_green",
    "base": "passed",
    "scenes": {"empty": "failed"},
    "door": "tree_literal",
    "measured_in": "контроль пробы: имя взято из ЭТОГО файла",
}


def _declaration(members: list[dict], **over) -> dict:
    doc = {
        "schema": ratchet.SCHEMA,
        "upper_bound": len(members),
        "instrument": "python3 -m spa_core.tests._tracker_content_door --differential",
        "wall_clock_minutes_per_side": 85,
        "measured_on_sha": "0000000",
        "members": members,
    }
    doc.update(over)
    return doc


class ProbeIsRegisteredTest(unittest.TestCase):

    def test_the_probe_is_in_the_registry(self) -> None:
        self.assertIn(PROBE_NAME, ca.PROBES,
                      "проба не зарегистрирована — карточка не сможет её объявить")

    def test_the_registry_entry_is_callable(self) -> None:
        self.assertTrue(callable(ca.PROBES[PROBE_NAME]))


class ProbeControlsTest(unittest.TestCase):
    """Зелёная на целом контуре, красная на каждом порванном звене."""

    def setUp(self) -> None:
        self.probe = ca.PROBES[PROBE_NAME]
        self._tmp = tempfile.TemporaryDirectory(prefix="tcc_probe_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _with_file(self, doc) -> tuple[str, str]:
        """Положить объявление на диск и дать пробе прочитать его НАСТОЯЩИМ читателем."""
        path = self.root / "decl.json"
        if isinstance(doc, str):
            path.write_text(doc, encoding="utf-8")
        else:
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(ratchet, "BASELINE", path):
            return self.probe()

    # -- целый контур ------------------------------------------------------ #

    def test_the_whole_contour_is_green(self) -> None:
        # НИ ОДНОЙ инъекции: настоящий файл объявления и настоящее дерево.
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_the_green_answer_prints_measured_numbers(self) -> None:
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        doc = ratchet.load_declaration()
        self.assertIn(str(len(doc["members"])), detail,
                      "зелёная строка обязана печатать ИЗМЕРЕННОЕ число членов, "
                      "а не постоянный текст")

    # -- порванные звенья: третий исход ------------------------------------ #

    def test_a_missing_declaration_is_unmeasured(self) -> None:
        with mock.patch.object(ratchet, "BASELINE", self.root / "нет-такого.json"):
            verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не прочитано", detail)

    def test_an_unparsable_declaration_is_unmeasured(self) -> None:
        verdict, detail = self._with_file("{не json")
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не разбирается", detail)

    def test_a_foreign_schema_is_unmeasured(self) -> None:
        verdict, detail = self._with_file(_declaration([dict(_LIVE_MEMBER)],
                                                       schema="чужая/9"))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("схема", detail)

    def test_a_guard_that_does_not_read_is_unmeasured(self) -> None:
        broken = mock.Mock()
        broken.load_declaration.side_effect = RuntimeError("читатель упал")
        verdict, detail = self.probe(module=broken)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("читатель упал", detail)

    # -- порванные звенья: отказ с названным предметом --------------------- #

    def test_an_empty_declaration_is_refused_not_called_empty_class(self) -> None:
        verdict, detail = self._with_file(_declaration([]))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("ПУСТО", detail)

    def test_a_member_without_a_measurement_is_refused(self) -> None:
        naked = dict(_LIVE_MEMBER)
        naked.pop("measured_in")
        verdict, detail = self._with_file(_declaration([naked]))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("measured_in", detail)

    def test_a_member_whose_file_vanished_is_refused(self) -> None:
        gone = dict(_LIVE_MEMBER, nodeid="spa_core/tests/test_такого_нет.py::test_x")
        verdict, detail = self._with_file(_declaration([gone]))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn(ratchet.FILE_MISSING, detail)

    def test_a_declared_bound_that_disagrees_with_the_list_is_refused(self) -> None:
        doc = _declaration([dict(_LIVE_MEMBER)], upper_bound=7)
        verdict, detail = self._with_file(doc)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("граница", detail)

    def test_a_list_longer_than_the_ceiling_is_refused(self) -> None:
        many = [dict(_LIVE_MEMBER, nodeid=f"{_LIVE_MEMBER['nodeid']}{i}")
                for i in range(ratchet.CEILING + 1)]
        verdict, detail = self._with_file(_declaration(many))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn(str(ratchet.CEILING), detail)

    # -- анти-подстрока ---------------------------------------------------- #

    def test_the_right_words_do_not_satisfy_the_probe(self) -> None:
        # Все поля заполнены правдоподобной прозой, файл СУЩЕСТВУЕТ, а теста в
        # нём НЕТ: подстрокой такая сцена прошла бы, замером — нет.
        plausible = dict(
            _LIVE_MEMBER,
            nodeid="spa_core/tests/test_tree_content_class_probe.py::"
                   "ProbeControlsTest::test_имени_такого_нет",
            measured_in="замер прибора `_tracker_content_door --differential`, цикл #1019",
        )
        verdict, detail = self._with_file(_declaration([plausible]))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn(ratchet.TEST_MISSING, detail)


if __name__ == "__main__":
    unittest.main()

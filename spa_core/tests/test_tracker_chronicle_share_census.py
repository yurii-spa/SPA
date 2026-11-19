"""Контроли переписи класса «карточка-тетрадь» (ADR-1068).

Каждая проба — положительный контроль настоящей ошибки:

* ответ по ВЕСУ не есть ответ о классе: самая тяжёлая карточка трекера записей цикла
  не имеет вовсе, и «тетрадь» по весу была бы объявлена о честной длинной карточке;
* ответ по одной ДОЛЕ — та же ошибка с другой стороны: карточка на 6 записей и
  20 702 символа читается в один приём, и класс есть ПЕРЕСЕЧЕНИЕ осей;
* «записей нет» — НЕ «0 %» (инв. #17): у карточки без хроники доли не существует;
* дверь опознания записи ОДНА и ввозится из дерева прибора — своя копия разошлась бы
  с дверью доставки (наивный греп дал 266 против 374 на том же приказе);
* производный индекс `_BOARD.md` карточкой не является, и исключение ПЕЧАТАЕТСЯ.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import types
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tracker_chronicle_share_census as census  # noqa: E402


def _tree(tmp, cards):
    """Одноразовое дерево: только трекер с карточками.

    Двери доставки в сцене НЕТ намеренно: дверь берётся из дерева ПРИБОРА, и
    положить её копию рядом с карточками значило бы изобразить проводку, которой
    прибор не пользуется.
    """
    root = pathlib.Path(tmp)
    tracker = root / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    for name, body in cards.items():
        (tracker / name).write_text(body, encoding="utf-8")
    return str(root)


def _record(number, filler):
    return f"## Цикл #{number} (сцена)\n{filler}\n\n"


class TheDoorIsImportedNotReimplemented(unittest.TestCase):
    """Дверь записи цикла — одна, из дерева ПРИБОРА, и её отсутствие = НЕ ИЗМЕРЕНО."""

    def test_a_door_without_the_declared_names_is_unmeasured_not_an_empty_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "тело"})
            saved = sys.modules.get("push_to_github")
            sys.modules["push_to_github"] = types.ModuleType("push_to_github")
            try:
                with self.assertRaises(census.NotMeasured) as box:
                    census.census(root, 0.5, 30000)
                self.assertIn("не объявляет", str(box.exception))
            finally:
                if saved is None:
                    sys.modules.pop("push_to_github", None)
                else:
                    sys.modules["push_to_github"] = saved

    def test_the_door_comes_from_the_instrument_tree_not_the_measured_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "рамка\n" + _record(1, "х" * 100)})
            report = census.census(root, 0.5, 30000)
            self.assertEqual(report["door_tree"], census.INSTRUMENT_ROOT)
            self.assertNotEqual(report["door_tree"], report["repo_root"])

    def test_the_live_door_is_the_delivery_door(self):
        door = census.chronicle_door()  # ЖИВОЕ дерево: предмет — сама дверь
        self.assertTrue(door.CYCLE_RECORD_RE.pattern)
        self.assertTrue(callable(door.entry_blocks))


class AbsentChronicleIsNotZeroPercent(unittest.TestCase):
    """инв. #17: «записей нет» — свой исход, а не вычисленный ноль."""

    def test_a_card_without_records_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "обычная карточка без хроники"})
            report = census.census(root, 0.5, 30000)
            self.assertEqual(report["not_applicable"], 1)
            self.assertEqual(report["with_records"], 0)
            self.assertEqual(report["above_share"], [])

    def test_an_undecodable_card_is_unmeasured_with_a_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "## Цикл #1 (сцена)\nтело\n"})
            broken = pathlib.Path(root) / census.TRACKER_REL / "inbox-broken.md"
            broken.write_bytes(b"\xff\xfe not utf-8")
            report = census.census(root, 0.5, 30000)
            self.assertEqual(len(report["unmeasured"]), 1)
            self.assertTrue(report["unmeasured"][0]["reason"])


class TheClassIsTheIntersectionOfTwoAxes(unittest.TestCase):
    """Ни доля, ни вес по отдельности классом не являются."""

    def test_a_high_share_but_readable_card_is_not_a_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "рамка\n" + _record(1, "х" * 500)})
            report = census.census(root, 0.5, 30000)
            self.assertEqual(len(report["above_share"]), 1)
            self.assertEqual(report["members"], [])

    def test_a_heavy_card_without_any_chronicle_is_not_a_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"agent-audit.md": "содержание\n" + "х" * 40000})
            report = census.census(root, 0.5, 30000)
            self.assertEqual(len(report["above_chars"]), 1)
            self.assertEqual(report["members"], [])
            self.assertEqual(report["heaviest"]["records"], 0)

    def test_the_share_is_counted_in_characters_not_bytes(self):
        """РАЗЛИЧАЮЩАЯ сцена: по байтам доля перешагнула бы порог, по символам — нет.

        Рамка — латиница (символ = байт), запись цикла — кириллица (символ = два
        байта). Считай прибор долю байтами хроники от СИМВОЛОВ файла, и карточка
        попала бы выше порога, ничем для читателя не изменившись.
        """
        with tempfile.TemporaryDirectory() as tmp:
            framing = "x" * 1000 + "\n"
            root = _tree(tmp, {"inbox-a.md": framing + _record(1, "х" * 400)})
            report = census.census(root, 0.5, 30000)
            card = report["heaviest"]
            self.assertEqual(report["above_share"], [], "по символам доля ниже порога")
            self.assertLess(card["share"], 0.5)
            self.assertGreater(card["chronicle_bytes"], card["chronicle_chars"])

    def test_a_card_above_both_axes_is_a_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-notebook.md": "рамка\n" + _record(1, "х" * 40000)})
            report = census.census(root, 0.5, 30000)
            self.assertEqual([row["card"] for row in report["members"]],
                             ["inbox-notebook.md"])


class TheDerivedIndexIsNotACard(unittest.TestCase):
    """`_BOARD.md` — генератор очереди, и исключение ПЕЧАТАЕТСЯ."""

    def test_the_board_is_excluded_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"_BOARD.md": "х" * 50000, "inbox-a.md": "тело"})
            report = census.census(root, 0.5, 30000)
            self.assertEqual(report["population"], 1)
            self.assertEqual(report["excluded_not_cards"], ["_BOARD.md"])
            self.assertIn("_BOARD.md", census.render(report))

    def test_an_empty_tracker_is_unmeasured_not_an_empty_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {})
            with self.assertRaises(census.NotMeasured):
                census.census(root, 0.5, 30000)


class ThreeOutcomesAreDistinguishableByExitCode(unittest.TestCase):
    def test_an_empty_class_is_code_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "рамка\n" + _record(1, "х" * 100)})
            self.assertEqual(census.main(["--repo-root", root]), 0)

    def test_a_member_is_code_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "рамка\n" + _record(1, "х" * 40000)})
            self.assertEqual(census.main(["--repo-root", root]), 1)

    def test_an_unreadable_tracker_is_code_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(census.main(["--repo-root", tmp]), 2)

    def test_the_scope_of_the_claim_is_printed_not_implied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(tmp, {"inbox-a.md": "тело"})
            text = census.render(census.census(root, 0.5, 30000))
            self.assertIn("ЭТОМ ДЕРЕВЕ", text)
            self.assertIn("пороги", text)


if __name__ == "__main__":
    unittest.main()

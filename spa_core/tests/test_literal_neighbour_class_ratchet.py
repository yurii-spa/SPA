"""Храповик ОБЪЯВЛЕНИЯ класса «литерал соседа на ЖИВОМ корне» (ADR-919, G907 п. 2).

Класс мерит ТОЛЬКО дифференциальный прогон
``spa_core.tests._literal_neighbour_door --differential`` (две стороны по
несколько минут каждая, плюс канарейка). В наборе, который обязан проходить
за минуты, ему места нет — поэтому здесь живёт не замер, а **объявление**
замера, и храповик спрашивает у него три вопроса:

1. объявление читается, схема та, и перечень членов НЕ ДОПИСАН рукой —
   у каждого члена стои́т ``measured_in``;
2. каждый названный член ещё СУЩЕСТВУЕТ в дереве: файл на месте и имя теста
   в нём найдено разбором (не подстрокой — подстрока краснеет от ЖИВОГО
   ключа, дословный урок ADR-916 C);
3. потолок равен длине перечня, и потолок живёт ТОЛЬКО в объявлении.
   Своя копия числа в коде есть ровно тот СЧЁТНЫЙ потолок, который
   устаревает НА ДЕНЬ СВОЕЙ ДОСТАВКИ (ADR-912): на коммите, которым он
   приехал, прибор давал уже другое число.

**Почему это храповик, а не замер.** Отсутствие ИМЁН у класса ADR-905
заставило цикл #1018 заплатить за сторону «ДО» дважды (97 мин против 0).
Объявление — это то, чем следующий цикл берёт сторону ДО бесплатно.

**«Пустое объявление» и «класс пуст» — РАЗНЫЕ утверждения.** Второе
доказывается прибором, а не пустым файлом, и храповик их различает.

Читатель объявления ЕДИНСТВЕННЫЙ (:func:`load_declaration`,
:func:`verdict_for_member`): проба приёмки
``literal_neighbour_class_declaration_holds`` зовёт ИХ ЖЕ, иначе проба и
храповик судили бы РАЗНЫЕ файлы под одним именем.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from spa_core.tests import _literal_neighbour_door as door

#: Объявление класса — замер с датой и sha, а не константа.
DECLARATION = Path(__file__).resolve().parent / "literal_neighbour_class_baseline.json"

#: Корень дерева, в котором проверяется существование члена.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Исходы разбора члена. Третий — НЕ «член в порядке».
PRESENT = "present"
FILE_GONE = "file_gone"
NAME_GONE = "name_gone"
UNREADABLE = "unreadable"


def load_declaration(path: Path | None = None) -> dict:
    """Единственный читатель объявления. Схема не та ⇒ исключение, не догадка."""
    target = path or DECLARATION
    doc = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"объявление не словарь: {type(doc).__name__}")
    for key in ("order", "members", "member_count", "upper_bound",
                "surface_files", "surface_count", "canary"):
        if key not in doc:
            raise ValueError(f"в объявлении нет поля {key!r}")
    return doc


def _test_names(path: Path) -> set[str]:
    """Имена тестов файла — РАЗБОРОМ. Подстрока краснела бы от живого ключа."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
    return names


def verdict_for_member(member: dict, root: Path | None = None) -> tuple[str, str]:
    """Член объявления ещё в дереве? Три исхода, и ни один не ноль."""
    base = root or REPO_ROOT
    nodeid = str(member.get("nodeid") or "")
    rel = str(member.get("file") or nodeid.split("::")[0])
    path = base / rel
    if not path.is_file():
        return FILE_GONE, f"файла нет в дереве: {rel}"
    try:
        names = _test_names(path)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return UNREADABLE, f"{rel}: {type(exc).__name__}: {exc}"
    wanted = [p for p in nodeid.split("::")[1:] if p]
    missing = [p for p in wanted if p.split("[")[0] not in names]
    if missing:
        return NAME_GONE, (f"{rel}: имён нет в разборе файла: "
                           f"{', '.join(missing)}")
    return PRESENT, f"{nodeid} на месте"


class LiteralNeighbourClassDeclarationTest(unittest.TestCase):
    """Объявление класса держится — и это проверяется, а не заявляется."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load_declaration()

    def test_the_declaration_names_its_order_and_its_measurement(self):
        self.assertEqual(self.doc["order"], "G907.2")
        self.assertTrue(self.doc.get("sha"), "объявление не назвало коммит")
        self.assertTrue(self.doc.get("measured_at"),
                        "объявление не назвало момент замера")

    def test_the_scene_of_the_measurement_is_the_instrument_scene(self):
        """Объявление, снятое ЧУЖОЙ сценой, говорит о другом возмущении."""
        self.assertEqual(self.doc.get("scene"), door.GROWN_REL)

    def test_the_canary_of_the_measurement_shifted_the_population(self):
        """Замер, снятый при НЕсдвинутом населении, есть ответ о приборе."""
        canary = self.doc.get("canary") or {}
        self.assertGreaterEqual(int(canary.get("delta", 0)), 1, canary)

    def test_every_member_names_the_measurement_that_found_it(self):
        """Имя без `measured_in` дописано рукой — инв. #16 на уровне данных."""
        naked = [m.get("nodeid", "<без имени>") for m in self.doc["members"]
                 if not m.get("measured_in")]
        self.assertEqual(naked, [], naked)

    def test_every_member_still_exists_in_the_tree(self):
        for member in self.doc["members"]:
            got, detail = verdict_for_member(member)
            self.assertEqual(got, PRESENT, detail)

    def test_the_surface_is_declared_and_still_exists(self):
        """Поверхность — ВТОРОЕ число, и его тоже можно потерять молча."""
        self.assertEqual(self.doc["surface_count"],
                         len(self.doc["surface_files"]))
        for rel in self.doc["surface_files"]:
            self.assertTrue((REPO_ROOT / rel).is_file(), rel)

    def test_the_ceiling_equals_the_list_and_lives_only_here(self):
        """Потолок в коде был бы вторым его экземпляром (ADR-912)."""
        self.assertEqual(self.doc["upper_bound"], len(self.doc["members"]))
        self.assertEqual(self.doc["member_count"], len(self.doc["members"]))

    def test_member_files_agree_with_the_member_names(self):
        """Два перечня одного замера обязаны сходиться — иначе объявление
        отвечает двумя разными числами на один вопрос."""
        from_names = sorted({m["nodeid"].split("::")[0]
                             for m in self.doc["members"]})
        self.assertEqual(sorted(self.doc.get("member_files") or []), from_names)


class VerdictForMemberTest(unittest.TestCase):
    """Половины контроля читателя: он обязан находить и обязан промахиваться."""

    def test_a_present_name_is_present(self):
        got, detail = verdict_for_member(
            {"nodeid": "spa_core/tests/test_literal_neighbour_class_ratchet.py"
                       "::VerdictForMemberTest::test_a_present_name_is_present"})
        self.assertEqual(got, PRESENT, detail)

    def test_a_missing_file_is_named_not_passed(self):
        got, _ = verdict_for_member({"nodeid": "spa_core/tests/t_nope.py::x"})
        self.assertEqual(got, FILE_GONE)

    def test_a_missing_name_is_named_not_passed(self):
        got, _ = verdict_for_member(
            {"nodeid": "spa_core/tests/test_literal_neighbour_class_ratchet.py"
                       "::nobody_wrote_this_name"})
        self.assertEqual(got, NAME_GONE)

    def test_an_unparsable_file_is_the_third_outcome(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def x(:\n", encoding="utf-8")
            got, detail = verdict_for_member({"nodeid": "broken.py::x"},
                                             root=root)
        self.assertEqual(got, UNREADABLE, detail)


if __name__ == "__main__":                               # pragma: no cover
    unittest.main()

# LLM_FORBIDDEN
"""spa_core/tests/test_tree_content_class_ratchet.py — ОБЪЯВЛЕНИЕ класса десятой двери.

**Зачем (цикл #1019, заказ G899 пп. 1 и 7, решение ADR-907).**
Десятая дверь семейства «вердикт зависит не от кода» — СОДЕРЖИМОЕ ДЕРЕВА
(:mod:`spa_core.tests._tracker_content_door`, ADR-905). Класс измерен дважды и
независимо: **15** предметов на одной базе, **14** после ADR-906. Мерить его может
только дифференциальный прогон, и он стои́т **~1 ч 25 мин за сторону**: цикл #1018
заплатил эту цену ДВАЖДЫ ровно потому, что ADR-905 опубликовал счётчики и не
опубликовал ИМЕНА — сторону «ДО» было нечем взять, кроме повторного замера.

**Что держит этот файл и чего он НЕ держит — это главное.**

Он держит **ОБЪЯВЛЕНИЕ** класса (``tree_content_class_baseline.json``): имена,
направления, дверь и то, каким замером каждое имя добыто. Он НЕ перемеряет класс и
не может: в наборе, который обязан проходить за минуты, нет места прогону на полтора
часа. Поэтому:

* **новый** член класса этим файлом НЕ ловится — его видит только прибор, и у зова
  прибора нет такта (названо в ADR-907, а не умолчано);
* зато ОБЪЯВЛЕНИЕ перестаёт тихо фоссилизироваться: переименованный или удалённый
  член краснит дерево, а дописать имя руками нельзя — у каждого имени обязано стоять
  поле ``measured_in``, называющее замер.

Верхняя граница ``CEILING`` может только УМЕНЬШАТЬСЯ — тот же порядок, что у
``frozen_date_baseline.json`` и ``design_status_baseline.json``
(``.claude/rules/deployment.md``). Дописывать имя, чтобы погасить падение,
ЗАПРЕЩЕНО (инв. #16): это ровно то, против чего храповик написан.

**Три исхода различимы (инв. #17).** Объявление прочитано · объявление опровергнуто
(имя названо) · **НЕ ИЗМЕРЕНО** с названной причиной — файла объявления нет, он не
разбирается, разбор исходника члена упал. «Не измерено» никогда не выдаётся за
«чисто»: третий исход поднимает :class:`Unmeasured` (потомок ``AssertionError``,
как у двери ``_tree_content_observation``), то есть падает ГРОМКО.

**Положительные контроли — на НАСТОЯЩИХ читателях** (``.claude/rules/deployment.md``,
§ «Проверка сторожа сторожей», и урок #944/#945: контроль на словаре, собранном
руками, мерит свой словарь, а не проводку). Каждый контроль собирает файл объявления
во временном каталоге и зовёт те же ``load_declaration`` / ``verdict_for_member``,
что и боевые проверки.

Только stdlib, оффлайн. Литеральных дат в файле нет вовсе — свежести этот сторож не
судит, и пометка ``FROZEN-DATE-OK`` была бы запиской без замера.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.tests import _tracker_content_door as _door

_REPO = Path(__file__).resolve().parents[2]

#: Файл объявления. Одна копия пути на сторожа.
BASELINE = _REPO / "spa_core" / "tests" / "tree_content_class_baseline.json"

#: Схема объявления. Строка НЕ копируется: её источник — ПИСАТЕЛЬ объявления
#: (`_tracker_content_door.DECLARATION_SCHEMA`), и импорт здесь означает, что
#: читатель с писателем не могут разойтись молча. Проверка схемы ниже от этого не
#: становится пустой: она ловит ЧУЖОЙ или старый файл, которому эта схема не та.
SCHEMA = _door.DECLARATION_SCHEMA

#: Верхняя граница класса, ИЗМЕРЕННАЯ прибором `_tracker_content_door --differential`
#: (ADR-905: 15 → ADR-906: 14). Может только УМЕНЬШАТЬСЯ; поднять её — значит
#: объявить, что класс вырос, и это отдельное решение с замером, а не правка литерала.
CEILING = 14

#: Поля, обязательные у каждого члена. `measured_in` отвечает на вопрос «чем это
#: имя добыто»: без него объявление становится списком из головы.
REQUIRED_MEMBER_FIELDS = ("nodeid", "base", "scenes", "door", "measured_in")

#: Вердикты о члене объявления. Перечень ЗАМКНУТ: новый исход обязан быть назван здесь.
PRESENT = "present"
FILE_MISSING = "file_missing"
TEST_MISSING = "test_missing"


class Unmeasured(AssertionError):
    """Третий исход (инв. #17): сторож НЕ СМОГ измерить и говорит это вслух.

    Потомок ``AssertionError`` намеренно — ровно как дверь
    :mod:`spa_core.tests._tree_content_observation` (ADR-906): контроль на такой
    отказ пишется обычным ``assertRaises``, а исход прогона остаётся падением, а не
    ``skipped``. Скип здесь сделал бы «не измерено» неотличимым от «прошло» — урок
    #465.
    """


def load_declaration(path: Path | None = None) -> dict:
    """Прочитать объявление класса.

    Возвращает разобранный документ. Любая невозможность прочитать — :class:`Unmeasured`
    с названной причиной, и НИКОГДА пустой словарь: пустое объявление совпало бы с
    «класс пуст», то есть выдало бы ненаблюдение за наблюдение.

    Путь берётся аргументом, а умолчание разрешается ВНУТРИ, а не значением по
    умолчанию в подписи: значение по умолчанию привязывается в момент определения
    функции, поэтому подмена модульного ``BASELINE`` на него НЕ ДЕЙСТВУЕТ — сцена
    контроля молча мерила бы боевой файл и зеленела бы, ничего не проверив.
    """
    path = BASELINE if path is None else path
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: объявление не прочитано: {path}: {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: объявление не разбирается: {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: объявление не словарь: {path}: {type(doc).__name__}")
    if doc.get("schema") != SCHEMA:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: схема объявления {doc.get('schema')!r} != {SCHEMA!r} — "
            f"читатель и писатель разошлись, и молчать об этом нельзя")
    members = doc.get("members")
    if not isinstance(members, list):
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: поля `members` нет или оно не список: {type(members).__name__}")
    return doc


def split_nodeid(nodeid: str) -> tuple[str, list[str]]:
    """``path::Class::test[param]`` → (путь, [имена]). Параметры отбрасываются."""
    parts = nodeid.split("::")
    path = parts[0]
    names = [p.split("[", 1)[0] for p in parts[1:]]
    return path, names


def _defined_names(src: str, path: str) -> set[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: исходник члена не разбирается: {path}: {exc}") from exc
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
    return found


def verdict_for_member(member: dict, repo: Path | None = None) -> tuple[str, str]:
    """Существует ли ещё названный член? Вердикт из ЗАМКНУТОГО перечня + деталь.

    Вопрос узкий намеренно: «тот ли это вердикт у теста» здесь не спрашивается — на
    него отвечает только прибор. Спрашивается «не исчезло ли имя, которое объявление
    выдаёт за измеренное».
    """
    repo = _REPO if repo is None else repo
    nodeid = member.get("nodeid", "")
    rel, names = split_nodeid(nodeid)
    target = repo / rel
    if not target.is_file():
        return FILE_MISSING, f"{nodeid}: файла {rel} в дереве нет"
    try:
        src = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: исходник члена не прочитан: {rel}: {exc}") from exc
    defined = _defined_names(src, rel)
    missing = [n for n in names if n not in defined]
    if missing:
        return TEST_MISSING, f"{nodeid}: в {rel} нет определени(я/й): {', '.join(missing)}"
    return PRESENT, f"{nodeid}: на месте"


# --------------------------------------------------------------------------- #
# Боевые проверки: объявление против дерева
# --------------------------------------------------------------------------- #

class DeclarationHoldsTest(unittest.TestCase):
    """Объявление класса обязано остаться правдой о ЭТОМ дереве."""

    def setUp(self) -> None:
        self.doc = load_declaration()
        self.members = self.doc["members"]

    def test_declaration_is_not_empty(self) -> None:
        # Пустое объявление и «класс пуст» — РАЗНЫЕ утверждения. Второе доказывается
        # прогоном прибора, а не отсутствием строк в файле.
        self.assertTrue(
            self.members,
            "объявление пусто: «класс пуст» доказывается прибором "
            "(`python3 -m spa_core.tests._tracker_content_door --differential`), "
            "а не пустым файлом")

    def test_no_member_is_declared_twice(self) -> None:
        seen: dict[str, int] = {}
        for m in self.members:
            seen[m.get("nodeid", "")] = seen.get(m.get("nodeid", ""), 0) + 1
        dupes = sorted(k for k, v in seen.items() if v > 1)
        self.assertFalse(dupes, f"одно имя объявлено дважды — счёт класса завышен: {dupes}")

    def test_every_member_names_how_it_was_measured(self) -> None:
        # Это и есть защита от дописывания руками: имя без замера объявлением не является.
        naked = []
        for m in self.members:
            absent = [f for f in REQUIRED_MEMBER_FIELDS if not m.get(f)]
            if absent:
                naked.append(f"{m.get('nodeid', '<без имени>')}: нет пол(я/ей) {', '.join(absent)}")
        self.assertFalse(naked, "член объявлен без замера — так объявление становится "
                                "списком из головы:\n  " + "\n  ".join(naked))

    def test_the_upper_bound_only_shrinks(self) -> None:
        self.assertLessEqual(
            len(self.members), CEILING,
            f"объявлено {len(self.members)} членов при верхней границе {CEILING}. "
            "Поднимать CEILING, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16): рост "
            "класса — отдельное решение с замером прибором")

    def test_the_declared_bound_agrees_with_the_list(self) -> None:
        declared = self.doc.get("upper_bound")
        self.assertEqual(
            declared, len(self.members),
            f"объявленная граница {declared!r} не равна длине перечня {len(self.members)} — "
            "число и имена разошлись внутри одного файла")

    def test_every_declared_member_still_exists(self) -> None:
        broken = []
        for m in self.members:
            verdict, detail = verdict_for_member(m)
            if verdict != PRESENT:
                broken.append(f"[{verdict}] {detail}")
        self.assertFalse(
            broken,
            "объявление разошлось с деревом — член переименован или удалён. Это НЕ повод "
            "дописать новое имя: перемерить прибором и УМЕНЬШИТЬ объявление:\n  "
            + "\n  ".join(broken))

    def test_the_instrument_and_its_price_are_named(self) -> None:
        # Цена замера есть часть объявления: именно её незнание заставило #1018
        # заплатить дважды.
        for field in ("instrument", "wall_clock_minutes_per_side", "measured_on_sha"):
            self.assertTrue(
                self.doc.get(field),
                f"в объявлении нет поля `{field}` — следующий цикл не узнает ни чем "
                "мерить, ни сколько это стои́т, и перемерит базу заново")


# --------------------------------------------------------------------------- #
# Положительные контроли: каждый воспроизводит настоящую поломку
# --------------------------------------------------------------------------- #

_GOOD_MEMBER = {
    "nodeid": "spa_core/tests/test_tree_content_class_ratchet.py::DeclarationHoldsTest::"
              "test_declaration_is_not_empty",
    "base": "passed",
    "scenes": {"empty": "failed"},
    "door": "tree_literal",
    "measured_in": "контроль сторожа: имя взято из ЭТОГО файла",
}


def _write_declaration(root: Path, doc: dict) -> Path:
    path = root / "decl.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class ControlsTest(unittest.TestCase):
    """Сторож, никогда не видевший настоящей поломки, — украшение."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tree_content_decl_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_missing_declaration_is_unmeasured_not_empty(self) -> None:
        with self.assertRaises(Unmeasured) as ctx:
            load_declaration(self.root / "нет-такого.json")
        self.assertIn("не прочитано", str(ctx.exception))

    def test_a_broken_declaration_is_unmeasured_not_empty(self) -> None:
        path = self.root / "decl.json"
        path.write_text("{не json", encoding="utf-8")
        with self.assertRaises(Unmeasured) as ctx:
            load_declaration(path)
        self.assertIn("не разбирается", str(ctx.exception))

    def test_a_foreign_schema_is_unmeasured(self) -> None:
        path = _write_declaration(self.root, {"schema": "чужая/9", "members": []})
        with self.assertRaises(Unmeasured):
            load_declaration(path)

    def test_a_declaration_without_members_is_unmeasured(self) -> None:
        path = _write_declaration(self.root, {"schema": SCHEMA})
        with self.assertRaises(Unmeasured) as ctx:
            load_declaration(path)
        self.assertIn("members", str(ctx.exception))

    def test_a_good_declaration_is_read(self) -> None:
        # Контроль в ОБРАТНУЮ сторону: исправное объявление читается молча.
        path = _write_declaration(self.root, {
            "schema": SCHEMA,
            "upper_bound": 1,
            "instrument": "прибор",
            "wall_clock_minutes_per_side": 85,
            "measured_on_sha": "deadbeef",
            "members": [dict(_GOOD_MEMBER)],
        })
        doc = load_declaration(path)
        self.assertEqual(len(doc["members"]), 1)

    def test_a_member_whose_file_vanished_is_caught(self) -> None:
        gone = dict(_GOOD_MEMBER, nodeid="spa_core/tests/test_такого_нет.py::test_x")
        verdict, detail = verdict_for_member(gone)
        self.assertEqual(verdict, FILE_MISSING, detail)

    def test_a_member_whose_test_was_renamed_is_caught(self) -> None:
        # Именно эта форма и есть тихая фоссилизация объявления: файл на месте, имени нет.
        renamed = dict(
            _GOOD_MEMBER,
            nodeid="spa_core/tests/test_tree_content_class_ratchet.py::test_имени_такого_нет")
        verdict, detail = verdict_for_member(renamed)
        self.assertEqual(verdict, TEST_MISSING, detail)

    def test_a_living_member_is_reported_present(self) -> None:
        verdict, detail = verdict_for_member(dict(_GOOD_MEMBER))
        self.assertEqual(verdict, PRESENT, detail)

    def test_a_parametrised_nodeid_loses_only_its_parameter(self) -> None:
        path, names = split_nodeid("a/b.py::Klass::test_x[case-1]")
        self.assertEqual(path, "a/b.py")
        self.assertEqual(names, ["Klass", "test_x"])

    def test_an_unparsable_member_source_is_unmeasured_not_missing(self) -> None:
        # Третий исход против «имени нет»: сломанный исходник не есть удалённый тест.
        broken = self.root / "test_сломан.py"
        broken.write_text("def test_x(:\n    pass\n", encoding="utf-8")
        with self.assertRaises(Unmeasured) as ctx:
            verdict_for_member({"nodeid": "test_сломан.py::test_x"}, repo=self.root)
        self.assertIn("не разбирается", str(ctx.exception))

    def test_the_third_outcome_is_an_assertion_not_a_skip(self) -> None:
        # Урок #465: уход в `skipped` читается как «всё в порядке». Проверяем ТИП.
        self.assertTrue(issubclass(Unmeasured, AssertionError))
        self.assertFalse(issubclass(Unmeasured, unittest.SkipTest),
                         "третий исход обязан падать, а не исчезать в `skipped`")


if __name__ == "__main__":
    unittest.main()

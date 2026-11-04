# LLM_FORBIDDEN
"""spa_core/tests/test_ci_only_red_class_ratchet.py — ОБЪЯВЛЕНИЕ класса
«красен в CI, ЗЕЛЕН на своём дереве» (одиннадцатая дверь семейства, ADR-913).

**Зачем (цикл #1027, заказ G904 п. 2).** Красный набор контрольного прогона CI
содержит имена, которые НЕ являются дефектами кода: тот же код на своём дереве той
же вершины проходит. Первым это заметил цикл #1026 на одном файле
(`test_mutation_window_owner_probe.py` ×6 — зелён 6/6 у себя), и заказ потребовал не
починки по одному, а **ЗАМЕРА населения**: сколько из дефектной части красно только
в CI.

**Дверь здесь ОКРУЖЕНИЕ РАННЕРА, и смешивать её с соседней нельзя.** Десятая дверь
(ADR-905/906/907, `spa_core/tests/tree_content_class_baseline.json`) — СОДЕРЖИМОЕ
ДЕРЕВА: вердикт меняется от того, что лежит в трекере. Эта — свойства самой машины:
PID-пространство, `ps`, права, контейнер, набор инструментов. Пересечение двух
объявлений измерено и равно ОДНОМУ имени
(`test_inbox_acceptance_ratchet.py::test_no_new_card_is_in_work_without_a_criterion`),
и это имя в ЭТОТ класс НЕ входит — на своём дереве оно красно.

**Что этот файл держит и чего НЕ держит — это главное.**

Он держит **ОБЪЯВЛЕНИЕ** класса (``ci_only_red_class_baseline.json``): имена, причину
красноты в CI, вердикт на своём дереве и то, каким замером каждое имя добыто. Он НЕ
перемеряет класс и не может: перемер стои́т один прогон `ci-control` (≈45 мин на
стороне GitHub) плюс 39 прогонов по файлам в одноразовом дереве. Поэтому:

* **новый** член класса этим файлом НЕ ловится — его видит только замер, и у замера
  нет такта (названо в ADR-913, а не умолчано);
* зато ОБЪЯВЛЕНИЕ перестаёт тихо фоссилизироваться: переименованный или удалённый
  член краснит дерево, а дописать имя руками нельзя — у каждого имени обязано стоять
  поле ``measured_in``, называющее замер.

Верхняя граница ``CEILING`` может только УМЕНЬШАТЬСЯ — тот же порядок, что у
``frozen_date_baseline.json``, ``design_status_baseline.json`` и
``tree_content_class_baseline.json`` (``.claude/rules/deployment.md``). Дописывать имя,
чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16).

**Три исхода различимы (инв. #17).** Объявление прочитано · объявление опровергнуто
(имя названо) · **НЕ ИЗМЕРЕНО** с названной причиной — файла объявления нет, он не
разбирается, схема чужая, разбор исходника члена упал. «Не измерено» никогда не
выдаётся за «чисто»: третий исход поднимает :class:`Unmeasured` (потомок
``AssertionError``), то есть падает ГРОМКО, а не становится ``skipped`` (урок #465).

**Положительные контроли — на НАСТОЯЩЕМ читателе** (``.claude/rules/deployment.md``,
§ «Проверка сторожа сторожей»; урок #944/#945: контроль на словаре, собранном руками,
мерит свой словарь, а не проводку). Каждый контроль собирает файл объявления во
временном каталоге и зовёт те же ``load_declaration`` / ``verdict_for_member``, что и
боевые проверки.

Только stdlib, оффлайн. Литеральных дат в файле нет вовсе — свежести этот сторож не
судит, и пометка ``FROZEN-DATE-OK`` была бы запиской без замера.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

#: Файл объявления. Одна копия пути на сторожа.
BASELINE = _REPO / "spa_core" / "tests" / "ci_only_red_class_baseline.json"

#: Схема объявления. Писателя-модуля у неё пока нет (замер делается разовым прибором
#: цикла, см. ADR-913 §5), поэтому строка живёт здесь — у ЕДИНСТВЕННОГО читателя.
#: Появится писатель — импортировать её оттуда, а не держать вторую копию.
SCHEMA = "ci-only-red-class/1"

#: Верхняя граница класса, ИЗМЕРЕННАЯ прогоном дефектной части на своём дереве
#: (ADR-913). Может только УМЕНЬШАТЬСЯ; поднять её — значит объявить, что класс
#: вырос, и это отдельное решение с замером, а не правка литерала.
#:
#: Литерал СВЕРЯЕТСЯ со своим ПРОИЗВОДИТЕЛЕМ — полем `upper_bound` объявления
#: (`test_the_ceiling_cannot_drift_above_its_own_producer`). Урок #1026 дословно:
#: счётный потолок `CALLER_SUPPLIED_MAX = 26` устарел НА ДЕНЬ СВОЕЙ ДОСТАВКИ, и
#: заметить это было нечем, потому что число ни с чем не сверялось. Мутация замера
#: #1027 подняла этот литерал до 999 и ВЫЖИЛА ровно по той же причине.
CEILING = 19

#: Поля, обязательные у каждого члена. `measured_in` отвечает на вопрос «чем это имя
#: добыто»: без него объявление становится списком из головы.
#:
#: Кортеж СВЕРЯЕТСЯ с полем `required_member_fields` самого объявления
#: (`test_the_field_contract_is_not_narrowed_by_the_guard_itself`). Без этой сверки
#: он был бы спецификацией, которую сторож сравнивает САМ С СОБОЙ: мутация замера
#: #1027 сузила его здесь до `("nodeid",)` и ВЫЖИЛА — набор упавших имён не
#: изменился, потому что сузилась та самая мерка, которой мерят.
REQUIRED_MEMBER_FIELDS = ("nodeid", "ci_outcome", "local_outcome", "ci_cause",
                          "door", "measured_in")

#: Вердикты о члене объявления. Перечень ЗАМКНУТ: новый исход обязан быть назван здесь.
PRESENT = "present"
FILE_MISSING = "file_missing"
TEST_MISSING = "test_missing"


class Unmeasured(AssertionError):
    """Третий исход (инв. #17): сторож НЕ СМОГ измерить и говорит это вслух.

    Потомок ``AssertionError`` намеренно — ровно как у десятой двери (ADR-906):
    контроль на такой отказ пишется обычным ``assertRaises``, а исход прогона
    остаётся падением, а не ``skipped``. Скип сделал бы «не измерено» неотличимым
    от «прошло».
    """


def load_declaration(path: Path | None = None) -> dict:
    """Прочитать объявление класса.

    Любая невозможность прочитать — :class:`Unmeasured` с названной причиной, и
    НИКОГДА пустой словарь: пустое объявление совпало бы с «класс пуст», то есть
    выдало бы ненаблюдение за наблюдение.

    Путь берётся аргументом, а умолчание разрешается ВНУТРИ, а не значением по
    умолчанию в подписи: значение по умолчанию привязывается в момент определения
    функции, поэтому подмена модульного ``BASELINE`` на него НЕ ДЕЙСТВОВАЛА БЫ — сцена
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
            "читатель и писатель разошлись, и молчать об этом нельзя")
    members = doc.get("members")
    if not isinstance(members, list):
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: поля `members` нет или оно не список: {type(members).__name__}")
    return doc


def split_nodeid(nodeid: str) -> tuple[str, list[str]]:
    """``path::Class::test[param]`` → (путь, [имена]). Параметры отбрасываются."""
    parts = nodeid.split("::")
    return parts[0], [p.split("[", 1)[0] for p in parts[1:]]


def _defined_names(src: str, path: str) -> set[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: исходник члена не разбирается: {path}: {exc}") from exc
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def verdict_for_member(member: dict, repo: Path | None = None) -> tuple[str, str]:
    """Существует ли ещё названный член? Вердикт из ЗАМКНУТОГО перечня + деталь.

    Вопрос узкий намеренно: «тот ли это вердикт у теста» здесь не спрашивается — на
    него отвечает только замер (прогон CI плюс прогон на своём дереве). Спрашивается
    «не исчезло ли имя, которое объявление выдаёт за измеренное».
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
    missing = [n for n in names if n not in _defined_names(src, rel)]
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
        # замером, а не отсутствием строк в файле.
        self.assertTrue(
            self.members,
            "объявление пусто: «класс пуст» доказывается ЗАМЕРОМ (прогон дефектной "
            "части на своём дереве, ADR-913 §5), а не пустым файлом")

    def test_no_member_is_declared_twice(self) -> None:
        seen: dict[str, int] = {}
        for m in self.members:
            key = m.get("nodeid", "")
            seen[key] = seen.get(key, 0) + 1
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

    def test_every_member_is_red_in_ci_and_green_at_home(self) -> None:
        """Предмет класса — ДВА РАЗНЫХ вердикта у одного имени.

        Член, у которого оба вердикта совпали, принадлежит не этому классу: либо он
        обычный дефект (красен везде), либо не падал вовсе. Пустить его сюда значило
        бы разбавить класс и завысить его население — ровно та ошибка, от которой
        заказ требовал мерить, а не чинить по одному.
        """
        wrong = []
        for m in self.members:
            ci, local = m.get("ci_outcome"), m.get("local_outcome")
            if ci != "failed" or local != "passed":
                wrong.append(f"{m.get('nodeid')}: CI={ci!r}, своё дерево={local!r}")
        self.assertFalse(
            wrong,
            "член класса обязан быть `failed` в CI и `passed` на своём дереве — иначе "
            "это другой класс:\n  " + "\n  ".join(wrong))

    def test_the_ceiling_cannot_drift_above_its_own_producer(self) -> None:
        """Литерал потолка против ЧИСЛА, которое произвёл замер.

        Потолок без сверки с производителем — это ровно `CALLER_SUPPLIED_MAX` из
        ADR-912: он устарел на день своей доставки, и сказать об этом было нечему.
        Уменьшение класса законно, но уменьшать надо ТРОЙКУ вместе (перечень,
        `upper_bound`, `CEILING`), и это видно в диффе; поднять литерал в одиночку
        теперь нельзя — паритет краснеет сразу.
        """
        declared = self.doc.get("upper_bound")
        self.assertEqual(
            CEILING, declared,
            f"CEILING={CEILING} в сторожe против upper_bound={declared!r} в объявлении: "
            "литерал разошёлся со своим ПРОИЗВОДИТЕЛЕМ. Поднимать CEILING, чтобы "
            "погасить падение, ЗАПРЕЩЕНО (инв. #16); рост класса — отдельное решение "
            "с новым замером, и тогда меняются ОБА числа")

    def test_the_field_contract_is_not_narrowed_by_the_guard_itself(self) -> None:
        """Спецификация полей против той, что объявлена в самом объявлении.

        Без этой сверки сторож сравнивает объявление со СВОЕЙ ЖЕ меркой: сузь
        `REQUIRED_MEMBER_FIELDS` — и проверка «член назвал свой замер» перестаёт
        что-либо требовать, а набор упавших имён не меняется (мутация 5 замера #1027
        ВЫЖИЛА именно так). Мерка обязана жить у ОБЪЯВЛЕНИЯ, и расхождение — отказ.
        """
        declared = self.doc.get("required_member_fields")
        self.assertIsInstance(
            declared, list,
            "в объявлении нет поля `required_member_fields` — тогда контракт полей "
            "существует только внутри сторожа, и сузить его можно молча")
        self.assertEqual(
            tuple(declared), REQUIRED_MEMBER_FIELDS,
            f"контракт полей разошёлся: объявление требует {tuple(declared)}, сторож — "
            f"{REQUIRED_MEMBER_FIELDS}. Сузить требование в коде, не тронув объявление, "
            "значит погасить проверку молча (инв. #16)")

    def test_the_upper_bound_only_shrinks(self) -> None:
        self.assertLessEqual(
            len(self.members), CEILING,
            f"объявлено {len(self.members)} членов при верхней границе {CEILING}. "
            "Поднимать CEILING, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16): рост "
            "класса — отдельное решение с замером")

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
            "дописать новое имя: перемерить и УМЕНЬШИТЬ объявление:\n  " + "\n  ".join(broken))

    def test_the_measurement_and_its_price_are_named(self) -> None:
        # Цена замера есть часть объявления: именно её незнание заставило #1018
        # заплатить за десятую дверь дважды.
        for field in ("measurement", "ci_run_id", "measured_on_sha",
                      "defective_part_size", "wall_clock_minutes"):
            self.assertTrue(
                self.doc.get(field),
                f"в объявлении нет поля `{field}` — следующий цикл не узнает ни чем "
                "мерить, ни сколько это стои́т, и перемерит базу заново")

    def test_the_class_is_a_subset_of_the_measured_defective_part(self) -> None:
        """Класс не может быть больше того набора, в котором его искали."""
        size = self.doc.get("defective_part_size")
        self.assertIsInstance(size, int, "размер дефектной части не объявлен числом")
        self.assertLessEqual(
            len(self.members), size,
            f"объявлено {len(self.members)} членов при дефектной части {size} — "
            "класс не может быть больше набора, в котором его мерили")

    def test_the_neighbouring_door_is_named_and_not_mixed_in(self) -> None:
        """Десятая дверь (СОДЕРЖИМОЕ ДЕРЕВА) — другая, и это объявлено.

        Смешать их значило бы снова сложить разнородное в одно число; заказ G904 п. 2
        требует мерить их ПОРОЗНЬ.
        """
        for m in self.members:
            self.assertEqual(
                m.get("door"), "runner_environment",
                f"{m.get('nodeid')}: дверь члена обязана быть `runner_environment`; "
                "дверь `tree_literal` принадлежит ADR-907 и живёт в своём объявлении")


# --------------------------------------------------------------------------- #
# Положительные контроли: каждый воспроизводит настоящую поломку
# --------------------------------------------------------------------------- #

_GOOD_MEMBER = {
    "nodeid": "spa_core/tests/test_ci_only_red_class_ratchet.py::DeclarationHoldsTest::"
              "test_declaration_is_not_empty",
    "ci_outcome": "failed",
    "local_outcome": "passed",
    "ci_cause": "контроль сторожа: причина взята из ЭТОГО файла",
    "door": "runner_environment",
    "measured_in": "контроль сторожа: имя взято из ЭТОГО файла",
}


def _doc(members, **over) -> dict:
    base = {"schema": SCHEMA, "upper_bound": len(members), "members": members,
            "required_member_fields": list(REQUIRED_MEMBER_FIELDS),
            "measurement": "контроль", "ci_run_id": "0", "measured_on_sha": "0" * 9,
            "defective_part_size": max(len(members), 1), "wall_clock_minutes": 1}
    base.update(over)
    return base


def _write(root: Path, doc: dict) -> Path:
    p = root / "decl.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


class PositiveControlsTest(unittest.TestCase):
    """Каждый контроль воспроизводит настоящую поломку и КРАСНЕЕТ на ней."""

    def test_a_missing_declaration_is_unmeasured_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Unmeasured) as got:
                load_declaration(Path(d) / "нет-файла.json")
        self.assertIn("не прочитано", str(got.exception))

    def test_a_broken_declaration_is_unmeasured_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decl.json"
            p.write_text("{не json", encoding="utf-8")
            with self.assertRaises(Unmeasured) as got:
                load_declaration(p)
        self.assertIn("не разбирается", str(got.exception))

    def test_a_foreign_schema_is_unmeasured_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), _doc([_GOOD_MEMBER], schema="tree-content-class/1"))
            with self.assertRaises(Unmeasured) as got:
                load_declaration(p)
        self.assertIn("схема объявления", str(got.exception))

    def test_an_empty_members_field_is_unmeasured_not_an_empty_class(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), {"schema": SCHEMA, "upper_bound": 0})
            with self.assertRaises(Unmeasured) as got:
                load_declaration(p)
        self.assertIn("`members`", str(got.exception))

    def test_a_vanished_member_is_named_not_silently_dropped(self) -> None:
        gone = dict(_GOOD_MEMBER, nodeid="spa_core/tests/нет-такого-файла.py::test_x")
        verdict, detail = verdict_for_member(gone)
        self.assertEqual(verdict, FILE_MISSING)
        self.assertIn("нет-такого-файла.py", detail)

    def test_a_renamed_test_is_named_not_silently_dropped(self) -> None:
        renamed = dict(_GOOD_MEMBER, nodeid=(
            "spa_core/tests/test_ci_only_red_class_ratchet.py::DeclarationHoldsTest::"
            "test_имени_такого_нет"))
        verdict, detail = verdict_for_member(renamed)
        self.assertEqual(verdict, TEST_MISSING)
        self.assertIn("test_имени_такого_нет", detail)

    def test_an_unparsable_member_source_is_unmeasured(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "spa_core" / "tests").mkdir(parents=True)
            (root / "spa_core" / "tests" / "broken.py").write_text(
                "def x(:\n", encoding="utf-8")
            with self.assertRaises(Unmeasured) as got:
                verdict_for_member({"nodeid": "spa_core/tests/broken.py::test_x"}, repo=root)
        self.assertIn("не разбирается", str(got.exception))

    def test_a_member_green_in_both_places_is_refused_by_the_live_check(self) -> None:
        # Положительный контроль НА БОЕВОЙ ПРОВЕРКЕ, а не на своём словаре: подменяем
        # прочитанное объявление и зовём тот же метод, что гоняет CI.
        case = DeclarationHoldsTest("test_every_member_is_red_in_ci_and_green_at_home")
        case.doc = _doc([dict(_GOOD_MEMBER, ci_outcome="passed")])
        case.members = case.doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_every_member_is_red_in_ci_and_green_at_home()
        self.assertIn("CI='passed'", str(got.exception))

    def test_a_foreign_door_is_refused_by_the_live_check(self) -> None:
        case = DeclarationHoldsTest("test_the_neighbouring_door_is_named_and_not_mixed_in")
        case.doc = _doc([dict(_GOOD_MEMBER, door="tree_literal")])
        case.members = case.doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_neighbouring_door_is_named_and_not_mixed_in()
        self.assertIn("runner_environment", str(got.exception))

    def test_a_class_larger_than_the_set_it_was_measured_in_is_refused(self) -> None:
        case = DeclarationHoldsTest("test_the_class_is_a_subset_of_the_measured_defective_part")
        case.doc = _doc([_GOOD_MEMBER, dict(_GOOD_MEMBER, nodeid="a.py::t")],
                        defective_part_size=1)
        case.members = case.doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_class_is_a_subset_of_the_measured_defective_part()
        self.assertIn("не может быть больше", str(got.exception))

    def test_a_declaration_without_its_price_is_refused(self) -> None:
        case = DeclarationHoldsTest("test_the_measurement_and_its_price_are_named")
        doc = _doc([_GOOD_MEMBER]); doc.pop("wall_clock_minutes")
        case.doc = doc; case.members = doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_measurement_and_its_price_are_named()
        self.assertIn("wall_clock_minutes", str(got.exception))

    def test_a_ceiling_raised_above_its_producer_is_refused(self) -> None:
        # Положительный контроль на мутацию 1 замера #1027: литерал подняли, объявление
        # не тронули. До паритета это НЕ краснело ничем.
        case = DeclarationHoldsTest("test_the_ceiling_cannot_drift_above_its_own_producer")
        case.doc = _doc([_GOOD_MEMBER], upper_bound=len([_GOOD_MEMBER]))
        case.members = case.doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_ceiling_cannot_drift_above_its_own_producer()
        self.assertIn("разошёлся со своим ПРОИЗВОДИТЕЛЕМ", str(got.exception))

    def test_a_narrowed_field_contract_is_refused(self) -> None:
        # Положительный контроль на мутацию 5 замера #1027: сузили мерку В СТОРОЖЕ.
        case = DeclarationHoldsTest("test_the_field_contract_is_not_narrowed_by_the_guard_itself")
        case.doc = _doc([_GOOD_MEMBER], required_member_fields=["nodeid"])
        case.members = case.doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_field_contract_is_not_narrowed_by_the_guard_itself()
        self.assertIn("контракт полей разошёлся", str(got.exception))

    def test_a_declaration_without_the_field_contract_is_refused(self) -> None:
        case = DeclarationHoldsTest("test_the_field_contract_is_not_narrowed_by_the_guard_itself")
        doc = _doc([_GOOD_MEMBER]); doc.pop("required_member_fields", None)
        case.doc = doc; case.members = doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_field_contract_is_not_narrowed_by_the_guard_itself()
        self.assertIn("`required_member_fields`", str(got.exception))

    def test_the_bound_and_the_list_must_agree(self) -> None:
        case = DeclarationHoldsTest("test_the_declared_bound_agrees_with_the_list")
        case.doc = _doc([_GOOD_MEMBER], upper_bound=7)
        case.members = case.doc["members"]
        with self.assertRaises(AssertionError) as got:
            case.test_the_declared_bound_agrees_with_the_list()
        self.assertIn("не равна длине перечня", str(got.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

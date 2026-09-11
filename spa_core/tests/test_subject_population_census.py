"""Приёмка прибора заказа #565 — сторожа, чьё население выведено из текста соседа.

Каждый тест ниже — КОНТРОЛЬ на поломку, измеренную этим циклом или предыдущим,
а не украшение. Положительный контроль всей ветки — воспроизведение аварии
ADR-326/327 буквально: прежняя форма храповика (`_\\w+ = X.run(...)`) обязана
получить вердикт «слеп», нынешняя — «устойчив». Проверка, никогда не видевшая
настоящей поломки, украшение (`.claude/rules/deployment.md`).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import re
import unittest
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import subject_population_census as C

#: Полный замер дерева стои́т секунды, а спрашивают о нём восемь тестов подряд.
#: Кэшируется ДОКУМЕНТ, а не вердикт: каждый тест по-прежнему судит о настоящем
#: замере настоящего дерева, просто не переплачивает за его повтор.
@lru_cache(maxsize=4)
def _doc(root: str) -> dict:
    return C.measure(Path(root))


_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE = _ROOT / "spa_core" / "monitoring" / "findings_bridge.py"

#: Форма, которой храповик ADR-326 выводил население ступени переписей, и
#: форма, которой он выводит его после починки ADR-327. Первая опирается на
#: ведущее подчёркивание в имени ПРИЁМНИКА записи — то есть на соглашение об
#: имени; вторая — на форму зова.
_FORM_BEFORE_ADR327 = (
    r"from spa_core\.monitoring import (\w+)\n\s+_\w+\s*=\s*\1\.run\(root=args\.root\)")
_FORM_AFTER_ADR327 = (
    r"from spa_core\.monitoring import (\w+)\n\s+\w+\s*=\s*\1\.run\(root=args\.root\)")


@lru_cache(maxsize=1)
def _load_office_module():
    """`scripts/consume_office_reports.py` — скрипт, а не модуль пакета.

    Грузится по пути (как его зовёт протокол), чтобы схему можно было
    спросить СТРУКТУРНО. Импорт под `__name__` != "__main__" ничего не
    исполняет.
    """
    import importlib.util

    path = _ROOT / "scripts" / "consume_office_reports.py"
    spec = importlib.util.spec_from_file_location("_office_for_tests", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError(f"шаг 0-офис не загружается по пути {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RenameProbeReplaysTheRealIncident(unittest.TestCase):
    """Положительный контроль: авария ADR-327, проигранная прибором заново."""

    def test_the_pre_adr327_form_is_proven_blind(self) -> None:
        src = _BRIDGE.read_text(encoding="utf-8")
        probe = C.rename_probe(_FORM_BEFORE_ADR327, src)
        self.assertEqual("blind", probe["verdict"], probe)
        self.assertLess(probe["after"], probe["before"], probe)
        self.assertGreater(probe["before"], 0, "слепота на пустом населении не доказуема")

    def test_the_fixed_form_survives_the_same_rename(self) -> None:
        """Обратный контроль. Без него находка висела бы над любым шаблоном."""
        src = _BRIDGE.read_text(encoding="utf-8")
        probe = C.rename_probe(_FORM_AFTER_ADR327, src)
        self.assertEqual("stable", probe["verdict"], probe)
        self.assertEqual(probe["before"], probe["after"], probe)

    def test_a_rename_that_is_not_free_is_never_performed(self) -> None:
        """Имя, видное снаружи, не трогается — иначе сжатие было бы ВЕРНЫМ красным.

        Переименуй прибор импорт-псевдоним или имя `def`, и «слепым» оказался бы
        всякий сторож, стоящий на контракте: ответ верный, вопрос не тот.
        """
        src = (
            "import json\n"
            "CONST = 1\n"
            "def helper(param):\n"
            "    local = param + CONST\n"
            "    return json.dumps(local)\n"
        )
        names = C.local_binding_names(ast.parse(src))
        self.assertEqual({"local"}, names, f"тронуто лишнее: {names}")

    def test_a_name_bound_at_module_level_too_is_never_renamed(self) -> None:
        """Мутация #6 этого цикла ВЫЖИЛА, пока такого контроля не было.

        Переименование идёт по ВСЕМУ модулю, поэтому имя, привязанное и снаружи
        функции, и внутри неё, трогать нельзя: модульная привязка видна
        импортёрам, и её переименование меняет контракт. Проверка выше на это не
        отвечала — в ней модульное имя в функции не встречалось вовсе, то есть
        она была истинна ПО ПОСТРОЕНИЮ.
        """
        src = (
            "SHARED = 1\n"
            "def helper():\n"
            "    SHARED = 2\n"
            "    inner = SHARED\n"
            "    return inner\n"
        )
        names = C.local_binding_names(ast.parse(src))
        self.assertNotIn("SHARED", names,
                         "переименовано имя, видное импортёрам — контракт сломан")
        self.assertEqual({"inner"}, names, f"тронуто лишнее: {names}")

        out, _, _ = C.rename_local_bindings(src)
        self.assertIn("SHARED = 1", out, "модульная привязка переписана")


class TheRewriteMustNotCorruptTheSubject(unittest.TestCase):
    """Контроли на две поломки переписчика, измеренные ЭТИМ циклом."""

    def test_byte_offsets_on_a_cyrillic_line(self) -> None:
        """`col_offset` у `ast` — смещение в БАЙТАХ.

        Символьная нарезка на строке с кириллицей съедала соседнее слово:
        `… if c["s"] elsezz22"…"` — синтаксис ломался, субъект объявлялся
        непереписываемым, и сайт молча уходил в «не измерено».
        """
        src = (
            'def f(c):\n'
            '    итог = "отзыв отправлен" if c else "ОТЗЫВ НЕ УШЁЛ"\n'
            '    return итог\n'
        )
        out, renamed, _ = C.rename_local_bindings(src)
        self.assertIsNotNone(out, "переписчик не собрал субъект обратно")
        ast.parse(out)
        self.assertEqual(2, renamed, "переименованы не оба вхождения имени")
        self.assertIn("else", out, "потеряно ключевое слово — правка сдвинута")
        self.assertNotIn("итог", out, "старое имя уцелело — правка прошла мимо")

    def test_fstring_interiors_are_left_alone_and_the_gap_is_declared(self) -> None:
        """Внутрь f-строк правка не лезет, и молчать об этом нельзя.

        Смещения подвыражений f-строки зависят от версии интерпретатора —
        вердикт, зависящий от версии Python, есть та же бомба, что литеральная
        дата (`.claude/rules/deployment.md`). Поэтому f-строки пропускаются
        ВСЕГДА, а совпадение шаблона внутри пропущенного участка обязано дать
        «не измерено», а не «устойчиво»: второе было бы fail-OPEN.
        """
        src = (
            'def f(x):\n'
            '    marker = x\n'
            '    return f"MARK-{marker}-END"\n'
        )
        probe = C.rename_probe(r"MARK-\{marker\}", src)
        self.assertEqual("unmeasured", probe["verdict"], probe)
        self.assertIn("f-строк", probe["reason"])

    def test_a_subject_without_local_bindings_is_unmeasured_not_stable(self) -> None:
        """Возмущать нечего ⇒ «не измерено». «Устойчиво» тут было бы враньём."""
        probe = C.rename_probe(r"CONST", "CONST = 1\n")
        self.assertEqual("unmeasured", probe["verdict"], probe)


class TheNormalisationTrapIsClosed(unittest.TestCase):
    """`ast.unparse` меняет КАВЫЧКИ — и съедает население, ничего не сломав."""

    def test_a_pattern_pinned_to_double_quotes_still_measures(self) -> None:
        src = 'def f():\n    v = "x"\n    return SERVICE == "GITHUB_PAT_SPA"\n'
        probe = C.rename_probe(r'"GITHUB_PAT_SPA"', src)
        self.assertNotEqual(
            "unmeasured", probe["verdict"],
            "нормализация снова съела кавычки — замер стал замером кавычек")
        self.assertEqual(1, probe["before"], probe)


class RoleSplitsTheSubject(unittest.TestCase):
    """Список субъектов и запрет — РАЗНЫЕ предметы, одним числом их мерить нельзя."""

    def _sites(self, body: str) -> list:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core" / "tests").mkdir(parents=True)
            (root / "spa_core" / "tests" / "test_x.py").write_text(body, encoding="utf-8")
            sites, _ = C.forward_sites(root)
            return sites

    def test_an_inline_emptiness_assertion_is_a_prohibition(self) -> None:
        sites = self._sites(
            "import re\n"
            "from pathlib import Path\n"
            "def test_a():\n"
            "    src = Path(__file__).read_text()\n"
            "    assert re.findall(r'ghp_\\\\w+', src) == []\n")
        self.assertEqual(1, len(sites), sites)
        self.assertEqual(C.ROLE_PROHIBITION, sites[0]["role"], sites[0])

    def test_a_prohibition_through_a_variable_is_still_a_prohibition(self) -> None:
        """Замер этого цикла: `forbidden = re.findall(...)`, запрет строкой ниже.

        Ближайшие предки зова о запрете не знают ничего, и роль вышла бы
        `coverage` — сайт попал бы в знаменатель «сколько сторожей строят
        население», которого у запрета нет.
        """
        sites = self._sites(
            "import re\n"
            "from pathlib import Path\n"
            "def test_a():\n"
            "    src = Path(__file__).read_text()\n"
            "    forbidden = re.findall(r'ghp_\\\\w+', src)\n"
            "    assert forbidden == []\n")
        self.assertEqual(1, len(sites), sites)
        self.assertEqual(C.ROLE_PROHIBITION, sites[0]["role"], sites[0])

    def test_a_list_that_is_iterated_is_coverage(self) -> None:
        sites = self._sites(
            "import re\n"
            "from pathlib import Path\n"
            "def test_a():\n"
            "    src = Path(__file__).read_text()\n"
            "    names = re.findall(r'def (\\\\w+)', src)\n"
            "    assert len(names) >= 1\n")
        self.assertEqual(1, len(sites), sites)
        self.assertEqual(C.ROLE_COVERAGE, sites[0]["role"], sites[0])


class SubjectResolutionAnswersAboutTheRightFile(unittest.TestCase):

    def test_the_parameter_is_taken_from_the_ENCLOSING_function(self) -> None:
        """Имя `src` носят параметры трёх помощников одного файла.

        «Любая функция с таким параметром» назвала бы ЧУЖИХ зовущих — верный
        ответ не на тот вопрос. Замер этого цикла:
        `test_context_routing_is_sound.py:251` получил имя соседнего помощника.
        """
        src = (
            "import re\n"
            "def first(src):\n"
            "    return src\n"
            "def second(src):\n"
            "    return re.findall(r'x(\\\\w+)', src)\n")
        tree = ast.parse(src)
        parents = C._parent_map(tree)
        call = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "findall")
        hay = call.args[1]
        self.assertEqual(("second", 0, "src"), C._param_of(hay, call, parents))

    def test_a_scoped_assignment_beats_the_last_one_in_the_module(self) -> None:
        """`src` присваивается в файле по пять раз — брать надо ВИДИМОЕ сайту."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir(parents=True)
            (root / "spa_core").mkdir(parents=True)
            (root / "spa_core" / "target.py").write_text("x = 1\n", encoding="utf-8")
            (root / "tests" / "test_y.py").write_text(
                "import re\n"
                "from pathlib import Path\n"
                "ROOT = Path(__file__).resolve().parents[1]\n"
                "def test_a():\n"
                "    src = (ROOT / 'spa_core' / 'target.py').read_text()\n"
                "    names = re.findall(r'(\\\\w+) = ', src)\n"
                "    assert names\n"
                "def test_b():\n"
                "    src = 'not a file at all'\n"
                "    return src\n", encoding="utf-8")
            sites, _ = C.forward_sites(root)
        self.assertEqual(1, len(sites), sites)
        self.assertEqual("spa_core/target.py", sites[0]["subject"], sites[0])


class PopulationCompletenessIsASeparateAssertion(unittest.TestCase):
    """Урок ADR-327 буквально: счётчик одной формы о своей слепоте не скажет."""

    def test_the_precise_road_is_a_subset_of_the_recall_road(self) -> None:
        doc = _doc(str(_ROOT))
        self.assertEqual([], doc["population"]["a_not_in_b"],
                         "точная дорога нашла сайты вне полнотной — B сузилась")

    def test_every_residue_carries_a_named_reason(self) -> None:
        """Остаток без причины — третий исход, и он НЕ складывается с нулём."""
        doc = _doc(str(_ROOT))
        self.assertEqual(0, doc["population"]["residue_unmeasured"],
                         "остаток дороги B без названной причины")

    def test_the_population_is_not_empty(self) -> None:
        doc = _doc(str(_ROOT))
        self.assertGreater(doc["population"]["regex_multi"], 0,
                           "ноль сайтов = прибор отвечает не на тот вопрос")
        self.assertGreaterEqual(doc["population"]["by_call_form"],
                                doc["population"]["regex_multi"])


class BlindnessRatchet(unittest.TestCase):
    """Храповик: доказанно слепых сторожей в наборе больше стать не может."""

    #: Замер цикла #566 на `origin/main` 23eb6dc1c: доказанно слепых — НОЛЬ.
    #: Единственный носитель класса (храповик ступени переписей) починен ADR-327
    #: и здесь же закреплён обратным контролем.
    CEILING = 0

    def test_no_new_blind_guard_appears(self) -> None:
        doc = _doc(str(_ROOT))
        blind = doc["blindness"]["blind"]
        self.assertLessEqual(
            len(blind), self.CEILING,
            "появился сторож, чьё население сжимается от законного "
            f"переименования: {[b['file'] + ':' + str(b['line']) for b in blind]}")

    def test_the_unmeasured_are_named_one_by_one(self) -> None:
        """«Не измерено» обязано называть ПРИЧИНУ, иначе оно неотличимо от «чисто»."""
        doc = _doc(str(_ROOT))
        for site in doc["blindness"]["unmeasured"]:
            self.assertTrue(
                site.get("probe_reason"),
                f"сайт {site['file']}:{site['line']} не измерен БЕЗ причины")


class TheMeasurementIsAboutCodeNotAboutDisk(unittest.TestCase):

    def test_a_poisoned_data_dir_changes_nothing(self) -> None:
        """Вопрос о КОДЕ, и ответ не смеет зависеть от того, что лежит в `data/`."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core" / "tests").mkdir(parents=True)
            (root / "spa_core" / "target.py").write_text("x = 1\n", encoding="utf-8")
            (root / "spa_core" / "tests" / "test_z.py").write_text(
                "import re\n"
                "from pathlib import Path\n"
                "ROOT = Path(__file__).resolve().parents[2]\n"
                "def test_a():\n"
                "    src = (ROOT / 'spa_core' / 'target.py').read_text()\n"
                "    names = re.findall(r'(\\\\w+) = ', src)\n"
                "    assert names\n", encoding="utf-8")
            clean = C.measure(root)
            (root / "data").mkdir()
            (root / "data" / "subject_population_census.json").write_text(
                json.dumps({"population": {"regex_multi": 999}}), encoding="utf-8")
            poisoned = C.measure(root)
        self.assertEqual(clean["population"], poisoned["population"])
        self.assertEqual(clean["other_forms"], poisoned["other_forms"])

    def test_run_writes_under_root_data_not_into_the_root(self) -> None:
        """Контракт ступени (ADR-326): `root` — КОРЕНЬ ДЕРЕВА, не каталог данных."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            C.run(root=str(root), write=True)
            self.assertTrue((root / "data" / C.OUTPUT_FILENAME).is_file())
            self.assertFalse((root / C.OUTPUT_FILENAME).exists(),
                             "артефакт уехал в КОРЕНЬ — дефект ADR-326 вернулся")


class OtherFormsAreCountedApart(unittest.TestCase):
    """Ловушка заказа: `glob`, список литералов и обход каталога — не то же самое."""

    def test_a_directory_walk_is_never_in_the_blind_denominator(self) -> None:
        doc = _doc(str(_ROOT))
        self.assertGreater(doc["other_forms"]["dir_walk"], 0)
        self.assertNotIn("dir_walk", doc["blindness"])

    def test_a_named_glob_and_a_bare_walk_are_different_classes(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "tests" / "test_g.py").write_text(
                "from pathlib import Path\n"
                "def test_a():\n"
                "    a = list(Path('.').rglob('*.py'))\n"
                "    b = list(Path('.').glob('agent_*.sh'))\n"
                "    assert a or b\n", encoding="utf-8")
            counts = C.other_form_counts(root)
        self.assertEqual(1, counts["dir_walk"], counts)
        self.assertEqual(1, counts["glob_name"], counts)


class StaticMarkerIsASignNotAVerdict(unittest.TestCase):
    """Подмена признака ответом и есть дефект, ради которого написан ADR-327."""

    def test_the_marker_fires_on_the_pre_adr327_form(self) -> None:
        marks = C.static_markers(_FORM_BEFORE_ADR327)
        self.assertIn("constrains-assignment-target", marks)
        self.assertIn("name-prefix:_", marks)

    def test_a_marker_without_a_shrinking_population_is_reported_as_such(self) -> None:
        """Нынешняя форма несёт метку и НЕ слепа — разрыв обязан быть назван."""
        self.assertIn("constrains-assignment-target",
                      C.static_markers(_FORM_AFTER_ADR327))
        src = _BRIDGE.read_text(encoding="utf-8")
        self.assertEqual("stable", C.rename_probe(_FORM_AFTER_ADR327, src)["verdict"])

    def test_layout_pinning_is_a_separate_axis(self) -> None:
        self.assertIn("pins-literal-indentation",
                      C.static_markers(r"^      - name: (.+)$"))
        self.assertNotIn("pins-literal-indentation",
                         C.static_markers(r"^\s*- name: (.+)$"))


class WiredAtBirth(unittest.TestCase):
    """Прибор без потребителя — источник, который никто не читает (ADR-209)."""

    def test_the_bridge_calls_it_in_the_stage_form(self) -> None:
        src = _BRIDGE.read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r"\bsubject_population_census\.run\(root=args\.root\)", src),
            "ступень переписей прибор не зовёт — артефакт не появится никогда")

    def test_the_office_step_declares_its_schema_and_producer(self) -> None:
        """Схема спрашивается СТРУКТУРНО, у самого словаря, а не подстрокой.

        Прежняя редакция этого теста утверждала схему подстрокой
        `'"subject_population_census.json": ("status", "counts",'` — то есть
        НАЧАЛОМ кортежа. Батарея цикла #567 сняла из схемы ключ `blindness`, и
        тест остался ЗЕЛЁНЫМ: подстрока не знает, что стои́т за ней. Это тот же
        дефект, ради которого написан сам прибор (проверка судит о ТЕКСТЕ
        соседа, а не о его структуре), и он жил внутри его собственной приёмки.
        Поимённо спрашиваются те три ключа, которые ADR называет обязательными:
        пропажа любого из них оставила бы величину вне тревоги «СХЕМА
        РАЗОШЛАСЬ» — ровно дефект ADR-325.
        """
        office = _load_office_module()
        schema = office._READ_SCHEMA[C.OUTPUT_FILENAME]
        for key in ("status", "counts", "population", "blindness",
                    "other_forms", "findings", "advisory"):
            self.assertIn(key, schema,
                          f"ключ `{key}` пропал из схемы шага 0-офис — его "
                          f"пропажа из отчёта не поднимет тревоги")
        self.assertEqual(
            office._PRODUCER[C.OUTPUT_FILENAME],
            "spa_core/monitoring/subject_population_census.py",
            "производитель артефакта в шаге 0-офис не назван или назван чужим")

    def test_the_manifest_knows_both_homes_of_the_artifact(self) -> None:
        """Дом артефакта — ДВЕ записи: `produces[]` агента и `artifacts[]`."""
        manifest = json.loads(
            (_ROOT / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        produced = [pr["artifact"] for a in manifest["agents"]
                    for pr in a.get("produces", [])]
        self.assertIn("data/subject_population_census.json", produced)
        paths = [a["path"] for a in manifest["artifacts"]]
        self.assertIn("data/subject_population_census.json", paths)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""Контроль прибора «кто решает „это тест?“ по ИМЕНИ файла» и его пробы приёмки.

Каждый тест здесь — положительный контроль: он рвёт РОВНО одно звено контура и
требует, чтобы проба покраснела с НАЗВАННЫМ звеном. Проверка, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md`, § «Проверка сторожа
сторожей»), а проба, принятая на целом контуре и не проверенная на порванном, есть
ровно та самосертификация, против которой написано `.claude/rules/acceptance.md` п. 3.

Сцены строятся МИНИ-деревом, а не копией репозитория: прибору нужны ровно
`scripts/test_membership_door_census.py`, `spa_core/analytics/architecture_audit.py`
и помощник в `spa_core/tests/`, который ПРАВДА пишет файл прямым зовом. Копировать
живое дерево значило бы мерить его содержимое, а не поведение прибора.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

INSTRUMENT = _REPO_ROOT / "scripts" / "test_membership_door_census.py"
AUDIT = _REPO_ROOT / "spa_core" / "analytics" / "architecture_audit.py"

#: Якорь вопроса о МЕСТЕ внутри двери. Сломать дверь можно только им; его исчезновение
#: есть третий исход «сцена не построена», а не «предмет пуст».
PLACE_ANCHOR = '            in_tests_tree = "tests" in rel.parent.parts'

#: Как сломать дверь ТАК, чтобы проба могла её измерить. Снять сам якорь МЕСТА нельзя:
#: проба строит свою мутированную сцену ИМ, и без якоря честно отвечает «НЕ ИЗМЕРЕНО»
#: (сцена не построена ≠ предмет пуст). Поэтому ломается ЗОВ двери: `_is_test_file`
#: остаётся на месте нетронутым, а обход снова спрашивает имя файла.
BYPASS_THE_DOOR = (
    "                if skip_tests and self._is_test_file(fpath, root)[0]:",
    '                if skip_tests and fpath.name.startswith("test_"):',
)

#: Как СНЯТЬ объявление названного долга, не тронув ничего другого:
#: переименовывается КЛЮЧ словаря, и правило без метода снова становится
#: МОЛЧАЛИВОЙ дырой (код 3). Переименовать сам словарь нельзя — модуль стал бы
#: нерабочим (`NameError` в `rule_status`), и сцена мерила бы падение.
DROP_THE_DEBT = (
    '    "no_print_in_modules": (',
    '    "no_print_in_modules_RENAMED": (',
)

#: Все правила, которые зовут ОБЩУЮ дверь `_iter_py_files(skip_tests=...)`.
#: Выросло с двух до трёх циклом #1236 (ADR-1091): `no_llm_in_analytics`
#: реализовано через ту же дверь, поэтому её поломка теперь задевает три
#: правила. Список — пин СОСТОЯНИЯ, и он обязан расти вместе с ним.
RULES_THROUGH_THE_DOOR = [
    "atomic_writes",
    "no_hardcoded_secrets",
    "no_llm_in_analytics",
]

#: Помощник в каталоге тестов, который ПРАВДА пишет файл прямым зовом: ни «tmp», ни
#: «os.replace» в пяти строках вокруг, иначе правило простит его само и сцена ослепнет.
HELPER = (
    "def write_report(target, body):\n"
    "    with open(target, 'w') as fh:\n"
    "        fh.write(body)\n"
)


def build_tree(
    tree: Path,
    *,
    name_only: bool = False,
    with_audit: bool = True,
    with_instrument: bool = True,
    instrument_patch: tuple[str, str] | None = None,
    audit_patch: tuple[str, str] | None = None,
) -> None:
    """Собрать мини-дерево; `*_patch` — ровно одно порванное звено."""
    (tree / "scripts").mkdir(parents=True)
    (tree / "spa_core" / "analytics").mkdir(parents=True)
    (tree / "spa_core" / "tests").mkdir(parents=True)
    (tree / "spa_core" / "utils").mkdir(parents=True)
    for pkg in ("spa_core", "spa_core/analytics", "spa_core/utils"):
        (tree / pkg / "__init__.py").write_text("", encoding="utf-8")
    (tree / "spa_core" / "utils" / "atomic.py").write_text(
        "def atomic_save(*a, **k):\n    raise NotImplementedError\n", encoding="utf-8")
    (tree / "spa_core" / "tests" / "_helper.py").write_text(HELPER, encoding="utf-8")

    if with_instrument:
        body = INSTRUMENT.read_text(encoding="utf-8")
        if instrument_patch is not None:
            old, new = instrument_patch
            if body.count(old) != 1:
                raise AssertionError(
                    f"якорь прибора встречается {body.count(old)} раз(а), а не один — "
                    "сцена не построена; это ГРОМКИЙ отказ, а не тихий пропуск")
            body = body.replace(old, new)
        (tree / "scripts" / "test_membership_door_census.py").write_text(
            body, encoding="utf-8")

    if with_audit:
        body = AUDIT.read_text(encoding="utf-8")
        if name_only:
            if body.count(PLACE_ANCHOR) != 1:
                raise AssertionError(
                    f"якорь МЕСТА встречается {body.count(PLACE_ANCHOR)} раз(а), "
                    "а не один — дверь сломать нечем, сцена не построена")
            body = body.replace(PLACE_ANCHOR, "            in_tests_tree = False")
        if audit_patch is not None:
            old, new = audit_patch
            if body.count(old) != 1:
                raise AssertionError(
                    f"якорь аудита встречается {body.count(old)} раз(а), а не один")
            body = body.replace(old, new)
        (tree / "spa_core" / "analytics" / "architecture_audit.py").write_text(
            body, encoding="utf-8")


def ask(tree: Path) -> tuple[int, dict, str]:
    """Спросить перепись подпроцессом: (код, документ, человеческий отчёт)."""
    doc_proc = subprocess.run(
        [sys.executable, str(tree / "scripts" / "test_membership_door_census.py"),
         "--repo-root", str(tree), "--json"],
        cwd=str(tree), capture_output=True, text=True, timeout=600)
    text_proc = subprocess.run(
        [sys.executable, str(tree / "scripts" / "test_membership_door_census.py"),
         "--repo-root", str(tree)],
        cwd=str(tree), capture_output=True, text=True, timeout=600)
    try:
        doc = json.loads(doc_proc.stdout)
    except json.JSONDecodeError:
        doc = {}
    return doc_proc.returncode, doc, text_proc.stdout


class TheCensusAnswersAboutBehaviourNotProse(unittest.TestCase):
    """Перепись спрашивает дверь о том, ЧТО ОНА ДЕЛАЕТ."""

    def test_live_door_is_named_place_and_the_subject_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "live"
            build_tree(tree)
            code, doc, _ = ask(tree)
        self.assertEqual(doc.get("door_form"), "PLACE_AND_NAME", doc.get("door_form_reason"))
        self.assertEqual(
            [r["rule"] for r in doc["rows"] if r["verdict"] == "DOOR_NAME"], [])
        # Код 0, а не 3 (цикл #1236, ADR-1091): предмет пуст И у КАЖДОГО
        # объявленного правила вопрос «реализовано ли оно» задать удалось —
        # `no_llm_in_analytics` реализовано, `no_print_in_modules` объявлено
        # не исполняемым с причиной. Пин сменила ПОЧИНКА, а не правка теста;
        # зубы прежнего пина сохранены отдельной сценой
        # `test_a_dropped_declaration_is_a_silent_hole_again` ниже.
        self.assertEqual(code, 0)

    def test_a_name_only_door_is_the_subject_and_the_census_sees_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "mutated"
            build_tree(tree, name_only=True)
            code, doc, _ = ask(tree)
        self.assertEqual(doc.get("door_form"), "NAME_ONLY", doc.get("door_form_reason"))
        self.assertEqual(
            sorted(r["rule"] for r in doc["rows"] if r["verdict"] == "DOOR_NAME"),
            RULES_THROUGH_THE_DOOR)
        self.assertEqual(code, 1)

    def test_the_divergence_of_a_broken_door_is_zero_while_the_population_is_not(self):
        """Главное наблюдение прибора: расхождением вердикта класс мерить НЕЛЬЗЯ.

        У сломанной двери обе сравниваемые формы совпадают, и расхождение выходит
        НОЛЬ — то есть «чисто» ровно там, где дефект. Поэтому население считается
        отдельно, и ноль в одном не вычитается из другого.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "mutated"
            build_tree(tree, name_only=True)
            _rc, doc, _ = ask(tree)
        div = doc["verdict_divergence"]
        self.assertEqual(div["disappears_when_place_is_asked"], [])
        self.assertEqual(div["appears_when_place_is_asked"], [])
        self.assertEqual(len(doc["misplaced_files"]), 1)

    def test_a_door_that_skips_nothing_is_named_neither_not_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "inert"
            build_tree(tree, audit_patch=(
                "                if skip_tests and self._is_test_file(fpath, root)[0]:",
                "                if False:"))
            _rc, doc, _ = ask(tree)
        self.assertEqual(doc.get("door_form"), "NEITHER", doc.get("door_form_reason"))
        self.assertEqual(
            sorted(r["rule"] for r in doc["rows"] if r["verdict"] == "DOOR_NAME"),
            RULES_THROUGH_THE_DOOR)

    def test_the_second_direction_is_measured_zero_not_absent(self):
        """«Файлов test_*.py вне tests/ нет» — наблюдение, а не отсутствие поля."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "live"
            build_tree(tree)
            (tree / "spa_core" / "test_outside.py").write_text("x = 1\n", encoding="utf-8")
            _rc, doc, _ = ask(tree)
        self.assertIn("name_only_outside_tests", doc)
        self.assertEqual(len(doc["name_only_outside_tests"]), 1)

        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "live2"
            build_tree(tree)
            _rc, doc2, _ = ask(tree)
        self.assertEqual(doc2["name_only_outside_tests"], [])

    def test_a_tree_without_the_audit_module_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "headless"
            build_tree(tree, with_audit=False)
            code, doc, _ = ask(tree)
        self.assertEqual(code, 2)
        self.assertEqual(doc, {})

    def test_a_declared_rule_without_an_implementation_is_named_not_swallowed(self):
        """Правило без метода НАЗВАНО — и у «названо» ДВЕ различимые формы.

        Прежняя редакция требовала исхода `UNMEASURED` у ДВУХ правил; оба пина
        сменила ПОЧИНКА цикла #1236 (ADR-1091), а не правка теста:
        `no_llm_in_analytics` реализовано, `no_print_in_modules` объявлено не
        исполняемым С ПРИЧИНОЙ. Притязание не ослаблено — требуется, чтобы
        причина была НАЗВАНА и видна в человеческом отчёте, а соседняя сцена
        проверяет, что СНЯТИЕ объявления возвращает молчаливую дыру.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "live"
            build_tree(tree)
            _rc, doc, report = ask(tree)
        self.assertEqual(
            sorted(r["rule"] for r in doc["rows"] if r["verdict"] == "UNMEASURED"),
            [], "молчаливых дыр на живом дереве быть не должно")
        debt = [r for r in doc["rows"] if r["verdict"] == "DECLARED_ABSENT"]
        self.assertEqual([r["rule"] for r in debt], ["no_print_in_modules"])
        self.assertGreater(
            len(debt[0]["reason"]), 40,
            "«названный долг» без имени причины неотличим от забытого имени")
        self.assertIn("НЕ РЕАЛИЗОВАНО", report)

    def test_a_dropped_declaration_is_a_silent_hole_again(self):
        """Зубы прежнего пина: СНЯТОЕ объявление обязано вернуть код 3.

        Без этой сцены новый исход `DECLARED_ABSENT` стал бы способом ТИХО
        погасить код 3 — ровно наоборот своему смыслу.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "mute"
            build_tree(tree, audit_patch=DROP_THE_DEBT)
            code, doc, _ = ask(tree)
        self.assertEqual(code, 3)
        self.assertEqual(
            sorted(r["rule"] for r in doc["rows"] if r["verdict"] == "UNMEASURED"),
            ["no_print_in_modules"])
        self.assertEqual(
            [r["rule"] for r in doc["rows"] if r["verdict"] == "DECLARED_ABSENT"], [])

    def test_a_declaration_without_a_reason_is_not_a_named_debt(self):
        """Объявление с пустой причиной объявлением НЕ считается.

        Мерится ЕДИНСТВЕННОЙ дверью разбора, а не прозой: «долг назван» без
        имени причины — та же подмена «не измерено» на «измерено», только на
        один слой выше.
        """
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import test_membership_door_census as census  # noqa: PLC0415

        with_reason = 'RULE_NOT_IMPLEMENTED = {"r": "потому что замер такой"}\n'
        self.assertEqual(
            census.declared_not_implemented(with_reason),
            {"r": "потому что замер такой"})
        for blank in ('RULE_NOT_IMPLEMENTED = {"r": ""}\n',
                      'RULE_NOT_IMPLEMENTED = {"r": "   "}\n',
                      'RULE_NOT_IMPLEMENTED = {"r": None}\n'):
            self.assertEqual(census.declared_not_implemented(blank), {}, blank)
        # Словаря нет вовсе — это не ошибка, а «объявления нет».
        self.assertEqual(census.declared_not_implemented("x = 1\n"), {})

        # Дыра покрытия, найденная мутацией M14: словарь, объявленный НЕ
        # словарём, обязан дать ГРОМКИЙ отказ, а не молчаливое «объявления нет»
        # — иначе «не разобрано» снова неотличимо от «нечего разбирать».
        for bad in ("RULE_NOT_IMPLEMENTED = []\n",
                    "RULE_NOT_IMPLEMENTED = 7\n",
                    'RULE_NOT_IMPLEMENTED = "строка"\n'):
            with self.assertRaises(census.NotMeasured, msg=bad):
                census.declared_not_implemented(bad)
        with self.assertRaises(census.NotMeasured):
            census.declared_not_implemented('RULE_NOT_IMPLEMENTED = {1: "a"}\n')

    def test_the_own_form_measure_does_not_credit_a_docstring(self):
        """Дефект МОЕЙ ЖЕ первой мерки: докстринг про `test_*` зачитывался за форму.

        Это дословно дефект мерки цикла #1234 (G1074 п. 4): «в строке ЕСТЬ литерал»
        вместо «совпадение ВНУТРИ литерала». Форма спрашивается ЗОВОМ.
        """
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import test_membership_door_census as census  # noqa: PLC0415

        # Сцена обязана ДОЕХАТЬ до мерки, а не только выглядеть похоже. Первая
        # редакция была без единого ЗОВА — и мутация «засчитывать строку любого зова»
        # (M07) её ПЕРЕЖИЛА: разбирать было нечего. Поэтому здесь и докстринг про
        # `test_*`, и настоящий зов НЕ-glob со строкой про тесты.
        prose = (
            "class A:\n"
            "    def check_x(self, log, d):\n"
            '        """Пропускает файлы test_*.py и помощники tests/."""\n'
            '        log.info("skipping test_*.py helpers under tests/")\n'
            '        return list(d.iterdir())\n'
        )
        self.assertIsNone(census.own_name_form(prose, "check_x"))

        real = (
            "class A:\n"
            "    def check_x(self):\n"
            '        for p in d.glob("test_*.py"):\n'
            "            pass\n"
        )
        self.assertEqual(census.own_name_form(real, "check_x"), "glob('test_*.py')")


class TheDoorItselfAnswersAboutPlace(unittest.TestCase):
    """Дверь `_is_test_file` — ОДНА, и её третий исход НАЗВАН."""

    def setUp(self):
        from spa_core.analytics.architecture_audit import ArchitectureAudit
        self.audit = ArchitectureAudit("spa_core")

    def test_a_helper_in_a_tests_directory_is_a_test(self):
        is_test, basis = self.audit._is_test_file(
            _REPO_ROOT / "spa_core" / "tests" / "_freshness.py", _REPO_ROOT / "spa_core")
        self.assertTrue(is_test)
        self.assertEqual(basis, "repo")

    def test_a_plain_module_is_not_a_test(self):
        is_test, _ = self.audit._is_test_file(
            _REPO_ROOT / "spa_core" / "analytics" / "architecture_audit.py",
            _REPO_ROOT / "spa_core")
        self.assertFalse(is_test)

    def test_a_tests_component_in_the_checkout_path_does_not_skip_the_repo(self):
        """Путь дерева с компонентом `tests` не обязан глотать весь репозиторий.

        Вопрос задаётся о пути ОТНОСИТЕЛЬНО корня — иначе дерево, выложенное в
        `/private/tmp/tests/…`, пропустилось бы целиком и МОЛЧА.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "tests" / "checkout"
            (fake_root / "spa_core" / "analytics").mkdir(parents=True)
            target = fake_root / "spa_core" / "analytics" / "module.py"
            target.write_text("x = 1\n", encoding="utf-8")
            from spa_core.analytics.architecture_audit import ArchitectureAudit
            audit = ArchitectureAudit(str(fake_root / "spa_core"))
            audit._repo_root = fake_root
            is_test, basis = audit._is_test_file(target, fake_root / "spa_core")
        self.assertFalse(is_test, "компонент tests в пути ЧЕКАУТА не делает файл тестом")
        self.assertEqual(basis, "repo")

    def test_a_file_outside_the_repo_names_its_basis(self):
        with tempfile.TemporaryDirectory() as tmp:
            walk_root = Path(tmp) / "elsewhere"
            (walk_root / "tests").mkdir(parents=True)
            target = walk_root / "tests" / "_helper.py"
            target.write_text("x = 1\n", encoding="utf-8")
            is_test, basis = self.audit._is_test_file(target, walk_root)
        self.assertTrue(is_test)
        self.assertEqual(basis, "root", "исход «место взято от корня обхода» обязан быть НАЗВАН")


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):
    """Проба приёмки зелена на целом контуре и красна на КАЖДОМ порванном звене."""

    @classmethod
    def setUpClass(cls):
        from spa_core.monitoring import card_acceptance as ca
        cls.ca = ca

    #: Имя пробы, а не сама функция: функция, положенная атрибутом КЛАССА, при доступе
    #: через `self` становится методом и получает `self` первым аргументом — проба
    #: падает TypeError, и красноту легко прочитать как находку о предмете.
    PROBE_NAME = "test_membership_is_asked_about_place_not_name"

    def _probe(self):
        fn = self.ca.PROBES.get(self.PROBE_NAME)
        if fn is None:
            self.fail(f"пробы {self.PROBE_NAME!r} нет в реестре PROBES")
        return fn

    def test_the_probe_is_registered(self):
        self.assertIn(self.PROBE_NAME, self.ca.PROBES,
                      "проба не в реестре PROBES — объявить её карточке нечем")

    def test_the_whole_contour_is_satisfied(self):
        verdict, why = self._probe()(None, repo_root=str(_REPO_ROOT))
        self.assertEqual(verdict, self.ca.SATISFIED, why)

    def _probe_on(self, **kwargs) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "scene"
            build_tree(tree, **kwargs)
            return self._probe()(None, repo_root=str(tree))

    def test_a_name_only_door_in_the_tree_makes_the_probe_red(self):
        verdict, why = self._probe_on(audit_patch=BYPASS_THE_DOOR)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("NAME_ONLY", why)

    def test_a_census_blind_to_divergence_makes_the_probe_red(self):
        """Ослепить ось расхождения — и проба обязана назвать именно её."""
        verdict, why = self._probe_on(instrument_patch=(
            '            if skip_tests and Path(fpath).name.startswith("test_"):',
            "            if skip_tests and self._is_test_file(Path(fpath), Path(root))[0]:"))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("расхождение", why.lower())

    def test_a_census_that_hides_unimplemented_rules_makes_the_probe_red(self):
        """Перепись, не называющая правило без метода, обязана краснить пробу.

        Формулировка жалобы сменилась вместе со словарём исходов (ADR-1091):
        прежде проба говорила «не реализованы», теперь — про НАЗВАННЫЙ ДОЛГ и
        про МОЛЧАЛИВУЮ ДЫРУ, потому что исходов стало два. Проверяется, что
        жалоба указывает на ПРОПАВШЕЕ ИМЯ ПРАВИЛА, а не просто непуста.
        """
        verdict, why = self._probe_on(instrument_patch=(
            "        return out\n",
            "        return [r for r in out if r in rule_to_method(source)]\n"))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("no_print_in_modules", why)
        self.assertTrue(
            "названный долг" in why.lower() or "молчаливая дыра" in why.lower(), why)

    def test_a_tree_without_the_instrument_is_unmeasured(self):
        verdict, why = self._probe_on(with_instrument=False)
        self.assertEqual(verdict, self.ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_a_tree_without_the_place_anchor_is_unmeasured_not_empty(self):
        verdict, why = self._probe_on(audit_patch=(
            PLACE_ANCHOR, "            in_tests_tree = bool('tests' in rel.parent.parts)"))
        self.assertEqual(verdict, self.ca.UNMEASURED, why)
        self.assertIn("якорь", why)

    def test_the_probe_does_not_pass_by_substring(self):
        """ADR-333: вердикт берётся ЗНАЧЕНИЕМ, а не совпадением в тексте отчёта.

        Дверь сломана, а человеческий отчёт переписан так, что несёт обе
        победные строки. Проба читает `--json` и обязана остаться КРАСНОЙ.
        """
        verdict, why = self._probe_on(
            audit_patch=BYPASS_THE_DOOR,
            instrument_patch=(
                '        "ПЕРЕПИСЬ: кто решает «это тест?» по ИМЕНИ файла "',
                '        "PLACE_AND_NAME ✅ ПРЕДМЕТ ПУСТ "'))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)


if __name__ == "__main__":
    unittest.main()

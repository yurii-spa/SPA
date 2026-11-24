"""Объявленное правило аудита обязано быть ОТВЕЧАЕМЫМ, а не печататься нулём.

Предмет — карточка `inbox-audit-obyavlyaet-sem-pravil-a-ispolnyaet` (заказ G1075
п. 4, ADR-1091). `spa_core/analytics/architecture_audit.py` объявлял **семь**
правил в `AUDIT_RULES` и исполнял **пять**: `no_llm_in_analytics` и
`no_print_in_modules` существовали ТОЛЬКО строками в списке — ни метода, ни
упоминания за его пределами во всём дереве. Нереализованное правило печаталось
в отчёте «0 violation(s)» наравне с правилом, которое по дереву действительно
прошло и ничего не нашло: «не измерено» было неотличимо от «измерено и равно
нулю» (инв. #17), и `no_llm_in_analytics` вдобавок называло инвариант #3
(запрет LLM), то есть читалось как действующая проверка самого жёсткого запрета
проекта.

**Исходы различимы (инв. #17), и их ТРИ, а не два:** `ENFORCED` — у правила
есть исполняющий метод · `NOT_IMPLEMENTED` — правило объявлено не исполняемым
И причина НАЗВАНА в `RULE_NOT_IMPLEMENTED` · `UNMEASURED` — имени нет ни в
методах, ни в объявлении долга, то есть МОЛЧАЛИВАЯ дыра, и она краснит код
возврата CLI (2), а не прячется в нуле.

**Мерится ПОВЕДЕНИЕ, а не проза.** Каждая сцена кладёт в одноразовое дерево
настоящий модуль аудита (мутированный ровно одним порванным звеном) и
СПРАШИВАЕТ пробу приёмки, которая запускает аудит подпроцессом и читает его
артефакт значениями. Разбор исходника ответил бы на вопрос «как это написано»,
а нужен ответ «что это делает» — ровно на этой подмене стоял исходный дефект.

FROZEN-DATE-OK: нет ни одной литеральной даты — предмет сцен не зависит от
календаря (сцены строятся из байтов модуля, а не из отметок времени).
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

AUDIT = _REPO_ROOT / "spa_core" / "analytics" / "architecture_audit.py"
DOOR = _REPO_ROOT / "spa_core" / "ci" / "llm_forbidden_lint.py"

#: Снять пару «имя правила → метод» у НОВОГО правила: оно становится
#: молчаливой дырой, потому что в `RULE_NOT_IMPLEMENTED` его нет.
DROP_THE_PAIR = (
    '            ("no_llm_in_analytics", self.check_no_llm_in_analytics),\n',
    "",
)

#: Снять ОБЪЯВЛЕНИЕ названного долга: `no_print_in_modules` снова становится
#: молчаливой дырой. Переименовывается КЛЮЧ, а не сам словарь: переименование
#: словаря делало модуль НЕрабочим (`NameError` в `rule_status`), и сцена
#: мерила бы падение вместо предмета — находка о СЦЕНЕ, пойманная её же
#: контролем.
DROP_THE_DEBT = (
    '    "no_print_in_modules": (',
    '    "no_print_in_modules_RENAMED": (',
)

#: Вернуть отчёту ПРЕЖНЮЮ форму: нереализованное правило печатается нулём.
#: Это дословное воспроизведение исходного дефекта (положительный контроль —
#: `.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).
PRINT_IT_AS_ZERO = (
    '                print(f"  ⬜  {rule_name:<35} НЕ РЕАЛИЗОВАНО (объявлено, "\n'
    '                      f"причина названа)")',
    '                print(f"  ✅  {rule_name:<35} 0 violation(s)")',
)

#: Заглушить fail-CLOSED: молчаливая дыра перестаёт краснить код возврата.
SWALLOW_THE_HOLE = (
    '        return [r for r, row in self.rule_status().items()\n'
    '                if row["status"] == "UNMEASURED"]',
    "        return []",
)

#: Спросить ТЕКСТ вместо ЗОВА — ровно урок ADR-1088: три из семи «нарушений»
#: того замера лежали внутри строкового литерала.
ASK_THE_TEXT = (
    "                imports = find_forbidden_imports(source, filename=rel)",
    "                imports = [type('V', (), {'line': n + 1, 'module': 'anthropic'})()\n"
    "                           for n, ln in enumerate(source.splitlines())\n"
    "                           if 'import anthropic' in ln]",
)


def build_tree(tree: Path, *, audit_patch: tuple[str, str] | None = None,
               with_audit: bool = True, with_door: bool = True) -> None:
    """Собрать мини-дерево; `audit_patch` — ровно одно порванное звено.

    Якорь, встреченный не один раз, есть ТРЕТИЙ ИСХОД «сцена не построена» —
    громкий отказ, а не тихий пропуск: иначе мутация не применилась бы, и
    зелёная проба читалась бы как вердикт о целом контуре.
    """
    (tree / "spa_core" / "analytics").mkdir(parents=True)
    (tree / "spa_core" / "utils").mkdir(parents=True)
    for pkg in ("spa_core", "spa_core/analytics", "spa_core/utils"):
        (tree / pkg / "__init__.py").write_text("", encoding="utf-8")
    (tree / "spa_core" / "utils" / "atomic.py").write_text(
        "def atomic_save(*a, **k):\n    raise NotImplementedError\n",
        encoding="utf-8")
    if with_door:
        (tree / "spa_core" / "ci").mkdir(parents=True)
        (tree / "spa_core" / "ci" / "__init__.py").write_text("", encoding="utf-8")
        (tree / "spa_core" / "ci" / "llm_forbidden_lint.py").write_text(
            DOOR.read_text(encoding="utf-8"), encoding="utf-8")
    if not with_audit:
        return
    body = AUDIT.read_text(encoding="utf-8")
    if audit_patch is not None:
        old, new = audit_patch
        if body.count(old) != 1:
            raise AssertionError(
                f"якорь аудита встречается {body.count(old)} раз(а), а не один — "
                "сцена НЕ построена; это ГРОМКИЙ отказ, а не тихий пропуск")
        body = body.replace(old, new)
    (tree / "spa_core" / "analytics" / "architecture_audit.py").write_text(
        body, encoding="utf-8")


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):
    """Проба зелена на целом контуре и красна на КАЖДОМ порванном звене."""

    #: Имя, а не функция: функция, положенная атрибутом КЛАССА, при доступе
    #: через `self` стала бы методом и получила `self` первым аргументом —
    #: проба упала бы TypeError, и красноту легко прочитать как находку.
    PROBE_NAME = "every_declared_audit_rule_is_answerable"

    @classmethod
    def setUpClass(cls):
        from spa_core.monitoring import card_acceptance as ca
        cls.ca = ca

    def _probe(self):
        fn = self.ca.PROBES.get(self.PROBE_NAME)
        if fn is None:
            self.fail(f"пробы {self.PROBE_NAME!r} нет в реестре PROBES")
        return fn

    def _probe_on(self, **kwargs) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "scene"
            build_tree(tree, **kwargs)
            return self._probe()(None, repo_root=str(tree))

    def test_the_probe_is_registered(self):
        self.assertIn(self.PROBE_NAME, self.ca.PROBES,
                      "пробы нет в реестре — объявить её карточке нечем")

    def test_the_whole_contour_is_satisfied(self):
        verdict, why = self._probe()(None, repo_root=str(_REPO_ROOT))
        self.assertEqual(verdict, self.ca.SATISFIED, why)

    def test_a_rule_without_its_pair_becomes_a_silent_hole_and_the_probe_sees_it(self):
        verdict, why = self._probe_on(audit_patch=DROP_THE_PAIR)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("no_llm_in_analytics", why)

    def test_a_dropped_debt_declaration_makes_the_probe_red(self):
        verdict, why = self._probe_on(audit_patch=DROP_THE_DEBT)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("no_print_in_modules", why)

    def test_a_report_that_prints_zero_for_an_unimplemented_rule_is_red(self):
        """Дословное воспроизведение исходного дефекта обязано краснить."""
        verdict, why = self._probe_on(audit_patch=PRINT_IT_AS_ZERO)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("НЕ РЕАЛИЗОВАНО", why)

    def test_a_swallowed_silent_hole_makes_the_probe_red(self):
        """Снятый fail-CLOSED: «не измерено» снова выдаётся за успех."""
        verdict, why = self._probe_on(audit_patch=SWALLOW_THE_HOLE)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertTrue("а не 2" in why or "UNMEASURED" in why, why)

    def test_a_rule_that_asks_the_text_instead_of_the_call_is_red(self):
        """Урок ADR-1088: импорт ВНУТРИ литерала нарушением не является."""
        verdict, why = self._probe_on(audit_patch=ASK_THE_TEXT)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, why)
        self.assertIn("литерал", why)

    def test_a_tree_without_the_audit_module_is_unmeasured_not_clean(self):
        verdict, why = self._probe_on(with_audit=False)
        self.assertEqual(verdict, self.ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_a_tree_without_the_llm_door_is_unmeasured_not_clean(self):
        verdict, why = self._probe_on(with_door=False)
        self.assertEqual(verdict, self.ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_the_probe_does_not_pass_by_substring(self):
        """Сцена оставляет в дереве ВСЕ слова, которые проба могла бы искать.

        Прежняя форма дефекта («0 violation(s)» у нереализованного правила)
        воспроизводится при НЕТРОНУТЫХ словах `NOT_IMPLEMENTED`,
        `RULE_NOT_IMPLEMENTED`, `UNMEASURED` в исходнике — то есть мера,
        проходящая подстрокой, зеленела бы (ADR-333).
        """
        body = AUDIT.read_text(encoding="utf-8")
        for word in ("NOT_IMPLEMENTED", "UNMEASURED", "НЕ РЕАЛИЗОВАНО"):
            self.assertIn(word, body)
        verdict, _why = self._probe_on(audit_patch=PRINT_IT_AS_ZERO)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED)


class TheThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Единичные замеры поверх пробы: ТРИ исхода у статуса правила."""

    def setUp(self):
        from spa_core.analytics import architecture_audit as aa
        self.aa = aa
        self.audit = aa.ArchitectureAudit("spa_core")

    def test_every_declared_rule_carries_a_status(self):
        statuses = self.audit.rule_status()
        self.assertEqual(sorted(statuses), sorted(self.aa.AUDIT_RULES),
                         "статус объявлен не у каждого правила из AUDIT_RULES")
        for rule, row in statuses.items():
            self.assertIn(row["status"],
                          {"ENFORCED", "NOT_IMPLEMENTED", "UNMEASURED"}, rule)

    def test_the_live_tree_has_no_silent_holes(self):
        self.assertEqual(self.audit.unmeasured_rules(), [])

    def test_a_declared_debt_carries_a_reason(self):
        for rule, reason in self.aa.RULE_NOT_IMPLEMENTED.items():
            self.assertIsInstance(reason, str, rule)
            self.assertGreater(
                len(reason.strip()), 80,
                f"{rule}: «названный долг» без имени причины неотличим от "
                "забытого имени")

    def test_the_pair_door_is_the_only_copy(self):
        """Пара «имя → метод» живёт ОДНОЙ копией: `run_all` и `main` берут её оттуда.

        До ADR-1091 копий было две (список зовов в `run_all` и список кортежей
        в `main`), и именно их расхождение пряталось за «семь объявлено, пять
        исполнено». Мерится AST: в модуле ровно ОДИН список кортежей
        `("имя", <что-то>.check_*)`.
        """
        tree = ast.parse(AUDIT.read_text(encoding="utf-8"))
        sites = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            pairs = [
                e for e in node.elts
                if isinstance(e, ast.Tuple) and len(e.elts) == 2
                and isinstance(e.elts[0], ast.Constant)
                and isinstance(e.elts[0].value, str)
                and isinstance(e.elts[1], ast.Attribute)
                and e.elts[1].attr.startswith("check_")
            ]
            if pairs:
                sites += 1
        self.assertEqual(sites, 1,
                         f"списков пар «имя → метод» в модуле {sites}, а не один")

    def test_every_enforced_rule_is_actually_run_by_run_all(self):
        """`run_all` проходит по той же двери — «объявлено и не прогнано» нет."""
        names = {r for r, _ in self.audit.rule_checks()}
        enforced = {r for r, row in self.audit.rule_status().items()
                    if row["status"] == "ENFORCED"}
        self.assertEqual(names, enforced)

    def test_the_markdown_report_names_the_status_of_every_rule(self):
        md = self.audit.to_markdown([])
        self.assertIn("Статус объявленных правил", md)
        for rule in self.aa.AUDIT_RULES:
            self.assertIn(rule, md, f"{rule} не назван в отчёте")

    def test_an_unmeasured_violation_is_not_counted_as_a_violation(self):
        """«Не измерено» — ОТДЕЛЬНОЕ число, а не часть `total_violations`."""
        v = self.aa.AuditViolation(
            rule="x", file="f", line=1, message="НЕ ИЗМЕРЕНО: причина",
            severity="UNMEASURED")
        real = self.aa.AuditViolation(
            rule="x", file="f", line=2, message="нарушение", severity="ERROR")
        md = self.audit.to_markdown([v, real])
        self.assertIn("НЕ ИЗМЕРЕНО: 1", md)
        self.assertIn("**Total violations:** 1", md)

    def test_the_llm_rule_asks_the_call_not_the_text(self):
        """Текст внутри литерала нарушением не является; настоящий импорт — да."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "spa_core"
            (base / "analytics").mkdir(parents=True)
            (base / "analytics" / "quoted.py").write_text(
                'HINT = "import anthropic"\n', encoding="utf-8")
            audit = self.aa.ArchitectureAudit(str(base))
            audit._repo_root = Path(tmp)
            quiet = audit.check_no_llm_in_analytics()
            (base / "analytics" / "real.py").write_text(
                "import anthropic\n", encoding="utf-8")
            loud = audit.check_no_llm_in_analytics()
        self.assertEqual([v for v in quiet if v.severity == "ERROR"], [])
        self.assertTrue([v for v in loud if v.severity == "ERROR"],
                        "настоящий импорт SDK не найден — правило слепо")

    def test_an_unparseable_analytics_file_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "spa_core"
            (base / "analytics").mkdir(parents=True)
            (base / "analytics" / "broken.py").write_text(
                "def f(:\n", encoding="utf-8")
            audit = self.aa.ArchitectureAudit(str(base))
            audit._repo_root = Path(tmp)
            found = audit.check_no_llm_in_analytics()
        self.assertTrue([v for v in found if v.severity == "UNMEASURED"],
                        "неразобранный файл доложен как «чисто»")
        self.assertEqual([v for v in found if v.severity == "ERROR"], [])

    def test_the_saved_artifact_separates_unmeasured_from_violations(self):
        """Дыра покрытия, найденная мутацией M09: артефакт читали не по тому полю.

        `to_markdown` проверялся, а `save()` — нет, и подмена
        `total_violations: len(violations)` ПЕРЕЖИЛА мутационный прогон. Выжившую
        мутацию записывают, а не замазывают.
        """
        import json as _json
        v = self.aa.AuditViolation(
            rule="x", file="f", line=1, message="НЕ ИЗМЕРЕНО: причина",
            severity="UNMEASURED")
        real = self.aa.AuditViolation(
            rule="x", file="f", line=2, message="нарушение", severity="ERROR")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "audit.json"
            self.audit.save([v, real], str(out))
            doc = _json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["total_violations"], 1,
                         "«не измерено» посчитано нарушением")
        self.assertEqual(doc["unmeasured_count"], 1)
        self.assertEqual(doc["error_count"], 1)
        self.assertEqual(sorted(doc["rules"]), sorted(self.aa.AUDIT_RULES))

    def test_the_status_table_is_present_when_violations_exist(self):
        """Дыра покрытия, найденная мутацией M10: ветка «нарушения ЕСТЬ» не проверялась.

        `to_markdown([])` уходит в ветку «нарушений нет», и заголовок таблицы в
        НЕпустой ветке можно было снять незаметно — именно это и пережило прогон.
        """
        real = self.aa.AuditViolation(
            rule="atomic_writes", file="f", line=2, message="нарушение",
            severity="WARNING")
        md = self.audit.to_markdown([real])
        self.assertIn("Статус объявленных правил", md)
        for rule in self.aa.AUDIT_RULES:
            self.assertIn(rule, md, f"{rule} не назван в отчёте с нарушениями")

    def test_a_missing_analytics_directory_is_unmeasured_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "spa_core"
            base.mkdir(parents=True)
            audit = self.aa.ArchitectureAudit(str(base))
            audit._repo_root = Path(tmp)
            found = audit.check_no_llm_in_analytics()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, "UNMEASURED")
        self.assertIn("НЕ ИЗМЕРЕНО", found[0].message)


if __name__ == "__main__":
    unittest.main()

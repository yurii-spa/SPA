#!/usr/bin/env python3
"""Контроли переписи поверхности класса «вердикт о населении» (ADR-935).

Каждый контроль — ОДНО звено, и он красен, когда это звено порвано: проверка,
никогда не видевшая поломки, есть украшение (`.claude/rules/deployment.md`,
«Проверка сторожа сторожей»).

ГЛАВНЫЙ контроль здесь — ОСОБЫЙ, и причина в самом предмете. Перепись,
умеющая отвечать только «форма совпала», отвечала бы о СВОЁМ ОХВАТЕ под
видом ответа о дереве — ровно тот дефект, который ADR-932/ADR-934 нашли у
других. Поэтому форме ПОДСОВЫВАЕТСЯ дерево, где известный член класса
выведен ИЗ формы, и от переписи требуется ОТКАЗ (код 2), а не число.

Сцены живут в одноразовом дереве под `tempfile`; прод-дерево не читается и
не правится ни одной проверкой. Литеральных дат и литеральных номеров
процессов здесь нет — прибор о свежести не судит, значит и у теста нет ни
одной двери к календарю.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from spa_core.tests import _population_verdict_surface as pvs  # noqa: E402

#: Член класса по форме: читает AST И объявляет два УПОТРЕБЛЁННЫХ ярлыка.
IN_FORM_SRC = '''
import ast
GOOD = "good"
BAD = "bad"
def judge(src):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            return GOOD
    return BAD
'''

#: Половина формы: AST читает, ярлыков не объявляет.
AST_ONLY_SRC = '''
import ast
def judge(src):
    return len(list(ast.walk(ast.parse(src))))
'''

#: Другая половина: ярлыки объявляет и употребляет, AST не читает.
LABELS_ONLY_SRC = '''
GOOD = "good"
BAD = "bad"
def judge(flag):
    return GOOD if flag else BAD
'''

#: Ярлыки объявлены, но НИ ОДИН не употреблён — это не словарь исходов,
#: а заготовка. Форма не должна их считать.
LABELS_UNUSED_SRC = '''
import ast
GOOD = "good"
BAD = "bad"
def judge(src):
    return len(list(ast.walk(ast.parse(src))))
'''

#: Значения не вида идентификатора: путь, сообщение, шаблон. Ярлыками не
#: являются, хотя имя константы в верхнем регистре и употреблено.
NOT_LABEL_VALUES_SRC = '''
import ast
ARTIFACT = "data/some_report.json"
MESSAGE = "не измерено: причина названа"
def judge(src):
    ast.parse(src)
    return ARTIFACT, MESSAGE
'''


def _scene(tmp: str, declared: tuple[str, ...] = ("pkg/known_instrument.py",),
           declared_list: bool = True) -> pathlib.Path:
    """Одноразовое дерево-сцена: git-дерево, перечень объявленных, предметы."""
    root = pathlib.Path(tmp)
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "spa_core" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir(parents=True, exist_ok=True)

    if declared_list:
        rows = "\n".join(
            f'        Scene(name="s{i}", instrument="{path}"),'
            for i, path in enumerate(declared)
        )
        body = (
            "class Scene:\n    pass\n\n\n"
            "def _scenes():\n    return (\n" + rows + "\n    )\n"
        )
    else:
        # Файл ЕСТЬ, но ни одной сцены в нём не объявлено.
        body = "class Scene:\n    pass\n\n\ndef _scenes():\n    return ()\n"
    (root / "spa_core" / "tests" / "_own_accident_control.py").write_text(
        body, encoding="utf-8")

    # Известный член класса — в форме.
    for path in declared:
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(IN_FORM_SRC, encoding="utf-8")
    return root


class TheDeclaredMembersAreInsideTheForm(unittest.TestCase):
    """Положительный контроль формы на ЗАВЕДОМО НЕПУСТОМ предмете."""

    def test_every_declared_instrument_of_the_live_tree_is_in_form(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        census = pvs.measure(str(root))
        self.assertEqual(
            [], census.declared_outside_form,
            "форма ОПРОВЕРГНУТА: известный член класса ADR-934 вне формы — "
            "мера не имеет права печатать число, пока это так")
        self.assertGreaterEqual(census.roles[pvs.DECLARED], 6,
                                "перечень объявленных приборов УСОХ — контроль ослаб")
        self.assertGreater(census.population, census.roles[pvs.DECLARED],
                           "население равно числу объявленных: перепись отвечает о "
                           "СВОЁМ охвате, а не о дереве — предмет класса ADR-934")

    def test_the_sum_of_outcomes_equals_the_number_of_subjects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            census = pvs.measure(str(root))
            total = sum(census.counts[k] for k in pvs.OUTCOMES)
            self.assertEqual(total, len(census.subjects),
                             "исходы не покрывают предметов: кто-то потерян молча")
            self.assertEqual(census.population, census.counts[pvs.IN_FORM])


class TheFormIsRefutedByADeclaredMemberFallingOutside(unittest.TestCase):
    """ГЛАВНЫЙ контроль: форма, потерявшая известного члена, НЕ ДАЁТ числа."""

    def test_a_declared_member_outside_the_form_is_a_refusal_not_a_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            # Выводим известный член ИЗ формы: ярлыки остаются, AST уходит.
            (root / "pkg" / "known_instrument.py").write_text(
                LABELS_ONLY_SRC, encoding="utf-8")
            census = pvs.measure(str(root))
            self.assertEqual(["pkg/known_instrument.py"],
                             census.declared_outside_form)
            self.assertIn("ФОРМА ОПРОВЕРГНУТА", "\n".join(pvs.report(census)))
            code = pvs.main(["--repo-root", str(root), "--json"])
            self.assertEqual(2, code,
                             "опровергнутая форма вышла НЕ кодом 2: число выдано "
                             "за ответ")

    def test_the_same_scene_gives_the_opposite_verdict_when_the_member_is_in_form(self):
        """Один и тот же замер, две ПРОТИВОПОЛОЖНЫЕ стороны.

        Без этой половины контроль выше доказывал бы только, что перепись
        умеет отказывать, — а не что она отказывает ПО ДЕЛУ.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            self.assertEqual(0, pvs.main(["--repo-root", str(root), "--json"]))
            (root / "pkg" / "known_instrument.py").write_text(
                LABELS_ONLY_SRC, encoding="utf-8")
            self.assertEqual(2, pvs.main(["--repo-root", str(root), "--json"]))


class BothHalvesOfTheFormAreLoadBearing(unittest.TestCase):
    """Каждое звено формы порвано отдельно — и каждый раз предмет уходит."""

    def _roles(self, body: str) -> tuple[int, set[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            (root / "pkg" / "probe.py").write_text(body, encoding="utf-8")
            census = pvs.measure(str(root))
            in_form = {s.rel for s in census.subjects if s.outcome == pvs.IN_FORM}
            return census.population, in_form

    def test_ast_alone_is_not_in_form(self):
        _, in_form = self._roles(AST_ONLY_SRC)
        self.assertNotIn("pkg/probe.py", in_form,
                         "«читает AST» без словаря исходов посчитано членом класса")

    def test_labels_alone_are_not_in_form(self):
        _, in_form = self._roles(LABELS_ONLY_SRC)
        self.assertNotIn("pkg/probe.py", in_form,
                         "словарь исходов без чтения кода посчитан членом класса")

    def test_both_halves_together_are_in_form(self):
        _, in_form = self._roles(IN_FORM_SRC)
        self.assertIn("pkg/probe.py", in_form,
                      "обе половины формы на месте, а предмет не найден")

    def test_a_label_declared_but_never_used_is_not_a_label(self):
        _, in_form = self._roles(LABELS_UNUSED_SRC)
        self.assertNotIn("pkg/probe.py", in_form,
                         "объявление без употребления посчитано ярлыком исхода: "
                         "так ярлыком станет любое имя файла")

    def test_a_path_or_a_message_is_not_a_label(self):
        _, in_form = self._roles(NOT_LABEL_VALUES_SRC)
        self.assertNotIn("pkg/probe.py", in_form,
                         "путь к артефакту и текст сообщения посчитаны ярлыками "
                         "исхода — форма ловит любой модуль с константами")


class TheThirdOutcomeIsNotFoldedIntoTheSecond(unittest.TestCase):
    """Инв. #17: «не разобран» ≠ «формы нет», и это видно по коду возврата."""

    def test_an_unparsable_file_is_unmeasured_with_a_named_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            (root / "pkg" / "broken.py").write_text(
                'def f(:\n    "не закрытая скобка"\n', encoding="utf-8")
            census = pvs.measure(str(root))
            broken = [s for s in census.subjects if s.rel == "pkg/broken.py"]
            self.assertEqual(1, len(broken))
            self.assertEqual(pvs.UNMEASURED, broken[0].outcome,
                             "неразобранный файл посчитан «вне формы»: «не "
                             "измерено» съедено «измерено и равно нулю»")
            self.assertTrue(broken[0].reason, "третий исход без названной причины")
            self.assertTrue(any("pkg/broken.py" in r
                                for r in census.unmeasured_reasons))

    def test_an_incomplete_measurement_exits_one_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            self.assertEqual(0, pvs.main(["--repo-root", str(root), "--json"]),
                             "полный замер вышел не нулём")
            (root / "pkg" / "broken.py").write_text("def f(:\n", encoding="utf-8")
            self.assertEqual(1, pvs.main(["--repo-root", str(root), "--json"]),
                             "неполный замер вышел НУЛЁМ — «не измерено» "
                             "неотличимо от «чисто»")

    def test_a_directory_the_os_refuses_is_unmeasured_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            closed = root / "pkg" / "closed"
            closed.mkdir()
            (closed / "hidden.py").write_text(IN_FORM_SRC, encoding="utf-8")
            os.chmod(closed, 0o000)
            try:
                census = pvs.measure(str(root))
                # Код возврата снимается ЗДЕСЬ ЖЕ, пока каталог закрыт: снятый
                # после `finally` он отвечал бы о дереве с ВОССТАНОВЛЕННЫМИ
                # правами, то есть о другой сцене. Первая редакция этой
                # проверки ровно так и ошиблась — `1 != 0` на открытом каталоге.
                code = pvs.main(["--repo-root", str(root), "--json"])
            finally:
                os.chmod(closed, 0o755)
            if census.walk_gaps == 0:
                # Предпосылка НЕ ОБЕСПЕЧЕНА (например прогон от root): падать
                # ГРОМКО, а не судить о закрытом каталоге как об обойдённом.
                self.fail("сцена не обеспечила отказ ОС: каталог с правами 000 был "
                          "обойдён — проверка о неполном обходе НЕ ИЗМЕРЕНА")
            # Закрытый каталог отнимает у обхода ОДНУ из ДВУХ дверей, и какая
            # ответит первой — свойство ОС, а не предмет проверки: на macOS
            # первым отказывает вопрос о принадлежности чужому клону
            # (`.git` не прочитан), на другой системе — сам `os.walk`.
            # Проверяется то, что обязано держаться при любой: пробел ИМЕНОВАН
            # этим каталогом и виден по коду возврата.
            self.assertTrue(
                any(str(closed) in r for r in census.unmeasured_reasons),
                "каталог не обойдён, а в причинах он НЕ НАЗВАН: «не измерено» "
                f"без имени неотличимо от «чисто». Причины: "
                f"{census.unmeasured_reasons}")
            self.assertEqual(1, code, "неполный обход вышел нулём")

    def test_a_tree_whose_every_file_is_out_of_form_reports_a_measured_zero(self):
        """Измеренный НОЛЬ обязан печататься, а не ронять отчёт.

        Контроль найден этим же циклом: `report()` делил на население и на
        пустом дереве падал `ZeroDivisionError` — то есть ровно там, где
        обязан был сказать «ноль» вслух.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".git").mkdir()
            (root / "spa_core" / "tests").mkdir(parents=True)
            (root / "spa_core" / "tests" / "_own_accident_control.py").write_text(
                'class Scene:\n    pass\n\n\ndef _scenes():\n    return (\n'
                '        Scene(name="s0", instrument="pkg/gone.py"),\n    )\n',
                encoding="utf-8")
            (root / "pkg").mkdir()
            (root / "pkg" / "plain.py").write_text("X = 1\n", encoding="utf-8")
            census = pvs.measure(str(root))
            self.assertEqual(0, census.population)
            text = "\n".join(pvs.report(census))
            self.assertIn("НЕ ОПРЕДЕЛЁН", text,
                          "доля при нулевом населении выдана за измеренную")
            # Объявленный прибор в дереве ОТСУТСТВУЕТ — он вне формы, значит
            # форма опровергнута, и это отказ, а не ноль.
            self.assertEqual(["pkg/gone.py"], census.declared_outside_form)


class ThePremiseOfTheCensusIsRefusedNotGuessed(unittest.TestCase):
    """Нет известных членов — нет и контроля формы. Это отказ, а не ноль."""

    def test_absent_declared_list_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            (root / "spa_core" / "tests" / "_own_accident_control.py").unlink()
            with self.assertRaises(pvs.Refused) as cm:
                pvs.measure(str(root))
            self.assertIn("НЕ ПРОЧИТАН", str(cm.exception))
            self.assertEqual(2, pvs.main(["--repo-root", str(root), "--json"]))

    def test_empty_declared_list_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, declared_list=False)
            with self.assertRaises(pvs.Refused) as cm:
                pvs.measure(str(root))
            self.assertIn("ПУСТ", str(cm.exception))

    def test_a_non_git_tree_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            shutil.rmtree(root / ".git")
            with self.assertRaises(pvs.Refused) as cm:
                pvs.measure(str(root))
            self.assertIn("не git-дерево", str(cm.exception))

    def test_a_tree_without_python_is_refused_not_called_zero(self):
        """Отказ обязан быть ТЕМ САМЫМ отказом, а не любым.

        Первая редакция проверяла только ТИП исключения — и проходила по
        ЧУЖОЙ причине (перечня нет), потому что перечень читался раньше
        обхода, а значит ветка «ни одного .py» была НЕДОСТИЖИМА. Мутация №16
        цикла #1050 сняла эту ветку и ВЫЖИЛА, чем и показала дыру.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".git").mkdir()
            (root / "spa_core" / "tests").mkdir(parents=True)
            with self.assertRaises(pvs.Refused) as cm:
                pvs.measure(str(root))
            self.assertIn("ни одного файла .py", str(cm.exception),
                          "отказ пришёл по ДРУГОЙ причине — проверка о пустом "
                          "дереве меряет не свою ветку")

    def test_the_two_premises_refuse_with_their_OWN_reasons(self):
        """Две предпосылки — два РАЗЛИЧИМЫХ отказа, и каждый достижим.

        Без этой проверки обе ветки могли бы сойтись в одну причину, и
        «перечня нет» стало бы неотличимо от «дерево пусто».
        """
        with tempfile.TemporaryDirectory() as tmp:
            # Файлы ЕСТЬ, перечня НЕТ ⇒ отказ про перечень.
            root = _scene(tmp)
            (root / "spa_core" / "tests" / "_own_accident_control.py").unlink()
            with self.assertRaises(pvs.Refused) as cm:
                pvs.measure(str(root))
            self.assertIn("НЕ ПРОЧИТАН", str(cm.exception))
            self.assertNotIn("ни одного файла .py", str(cm.exception))


class ForeignClonesAreNotCountedAsOurs(unittest.TestCase):
    """ADR-930: граница дерева — `.git` У КАТАЛОГА, а не литерал имени."""

    def test_a_nested_clone_does_not_inflate_the_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            clean = pvs.measure(str(root)).population
            nested = root / "some_other_worktree"
            (nested / ".git").mkdir(parents=True)
            (nested / "pkg").mkdir(parents=True)
            (nested / "pkg" / "copy.py").write_text(IN_FORM_SRC, encoding="utf-8")
            after = pvs.measure(str(root))
            self.assertEqual(clean, after.population,
                             "файл чужого клона посчитан нашим: население "
                             "умножилось бы на число клонов в дереве")
            self.assertNotIn("some_other_worktree/pkg/copy.py",
                             {s.rel for s in after.subjects})

    def test_the_same_file_outside_a_clone_IS_counted(self):
        """Обратная сторона: отрезается КЛОН, а не каталог с похожим именем."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            clean = pvs.measure(str(root)).population
            plain = root / "some_other_worktree" / "pkg"
            plain.mkdir(parents=True)
            (plain / "copy.py").write_text(IN_FORM_SRC, encoding="utf-8")
            self.assertEqual(clean + 1, pvs.measure(str(root)).population,
                             "каталог БЕЗ `.git` отрезан как клон — перепись "
                             "занижает поверхность, то есть врёт в сторону "
                             "«работа закончена»")


class TheTwoOutputsNameTheSameNumber(unittest.TestCase):
    """Машинный и человеческий вывод не имеют права расходиться."""

    def test_json_and_text_agree_on_the_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp)
            census = pvs.measure(str(root))
            doc = pvs.as_json(census)
            self.assertEqual(census.population, doc["population"])
            self.assertEqual(len(doc["declared"]) + len(doc["candidates"]),
                             doc["population"],
                             "роли не складываются в население")
            self.assertIn(f"≤ {census.population}", "\n".join(pvs.report(census)))

    def test_the_cli_runs_as_a_subprocess_and_prints_json(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        out = subprocess.run(
            [sys.executable, str(root / "spa_core" / "tests"
                                 / "_population_verdict_surface.py"),
             "--repo-root", str(root), "--json"],
            capture_output=True, text=True, timeout=600)
        self.assertEqual(0, out.returncode, out.stderr[-2000:])
        doc = json.loads(out.stdout)
        self.assertEqual([], doc["declared_outside_form"])
        self.assertGreaterEqual(doc["population"], 6)


if __name__ == "__main__":
    unittest.main()

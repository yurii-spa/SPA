"""Батарея прибора состава долга сирот-скриптов (ADR-1063, заказ G1051 п. 1).

Каждая сцена — РАЗЛИЧАЮЩАЯ: её предмет меняет вердикт, если убрать проверяемое
звено. Урок цикла #1202 применён буквально: «мутация без различающей сцены
выживает», поэтому у причин ухода и прихода стои́т по сцене НА КАЖДУЮ, и ещё по
одной — на ПОРЯДОК вопросов (удаление, названное подключением, и есть та
ошибка, которую порядок предотвращает).

Деревья синтетические и крошечные: корень — ВХОД функции, а не окружение, поэтому
батарея не зависит ни от состава живого репозитория, ни от календаря, ни от
номера процесса. Живой долг здесь не утверждается ни одной строкой — это предмет
храповика `test_unwired_scripts_ratchet`, а не этой батареи; утверждение о живом
дереве было бы будильником (`.claude/rules/deployment.md`, § про время).
"""
from __future__ import annotations

import ast
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from spa_core.monitoring import orphan_script_debt as osd
from spa_core.tests import _unwired

_ENTRY = 'if __name__ == "__main__":\n    pass\n'
_REGISTRY = pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md"


def _tree(base: pathlib.Path, *, scripts=(), callers=(), registry=(),
          baseline=(), declare_baseline=True) -> pathlib.Path:
    """Крошечное дерево: точки входа, вызывающие, реестр R&D и ОБЪЯВЛЕНИЕ долга.

    `callers` — имена, которые ЗОВЁТ обёртка (настоящая проводка, `.sh`).
    `registry` — имена, названные в реестре-продукте (законное освобождение).
    `baseline` — имена в объявлении долга (база храповика).
    `declare_baseline=False` — объявления НЕТ: ось красного набора обязана стать
    НЕ ИЗМЕРЕНА, а не пустой.
    """
    (base / "scripts").mkdir(parents=True, exist_ok=True)
    (base / _REGISTRY.parent).mkdir(parents=True, exist_ok=True)
    for name in scripts:
        (base / "scripts" / f"{name}.py").write_text(_ENTRY, encoding="utf-8")
    if callers:
        body = "#!/bin/bash\n" + "".join(
            f"python3 scripts/{n}.py --once\n" for n in callers)
        (base / "scripts" / "run_it.sh").write_text(body, encoding="utf-8")
    text = "# Реестр R&D-идей\n" + "".join(
        f"- замер scripts/{n}.py → запись ниже\n" for n in registry)
    (base / _REGISTRY).write_text(text, encoding="utf-8")
    if declare_baseline:
        decl = base / osd._BASELINE
        decl.parent.mkdir(parents=True, exist_ok=True)
        decl.write_text(json.dumps({"scripts": sorted(baseline),
                                    "revealed_by_stricter_detector": {}},
                                   ensure_ascii=False), encoding="utf-8")
    return base


class TheDebtCompositionIsMeasured(unittest.TestCase):
    """Состав, а не размер: у каждого ушедшего и пришедшего имени своя причина."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="osd_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _delta(self, before_kw, after_kw, axis="red"):
        before = osd.measure_root(_tree(self.tmp / "before", **before_kw))
        after = osd.measure_root(_tree(self.tmp / "after", **after_kw))
        return osd.delta(before, after, axis=axis)

    def test_identical_trees_report_the_same_composition(self):
        same = dict(scripts=("alone", "wired"), callers=("wired",))
        report = self._delta(same, same)
        code, head = osd.verdict(report)
        self.assertEqual(code, 0, head)
        self.assertEqual(report["departed"], [])
        self.assertEqual(report["arrived"], [])
        self.assertEqual(report["held"], ["alone"])

    def test_the_SIZE_can_hold_still_while_the_composition_turns_over_WHOLE(self):
        """Предмет находки #1206: «три и три» при ПУСТОМ пересечении.

        Именно эта форма прожила от #957 до #1205: число в записях не дрогнуло,
        а ни одного общего имени между двумя замерами не было. Сцена различающая:
        размеры РАВНЫ, поэтому любой читатель размера обязан сказать «совпало»,
        а читатель состава — «сменился целиком».
        """
        report = self._delta(dict(scripts=("old_a", "old_b")),
                            dict(scripts=("new_a", "new_b")))
        code, head = osd.verdict(report)
        self.assertEqual(code, 1, head)
        self.assertEqual(report["size_before"], report["size_after"])
        self.assertTrue(report["size_equal_but_composition_changed"], head)
        self.assertTrue(report["composition_turned_over_whole"], head)
        self.assertEqual(report["held"], [])
        self.assertIn("РАЗМЕР НЕ ДРОГНУЛ", head)
        self.assertIn("пересечение ПУСТО", head)

    def test_a_name_that_got_a_real_caller_is_called_WIRED(self):
        report = self._delta(dict(scripts=("x",)),
                             dict(scripts=("x",), callers=("x",)))
        self.assertEqual([r["cause"] for r in report["departed"]], [osd.WIRED])
        self.assertEqual(report["departed"][0]["name"], "x")

    def test_a_name_excused_by_the_registry_is_NOT_called_wired(self):
        """Два из трёх ушедших имён замера #1206 ушли ИМЕННО так.

        Вызывающего у них не было и нет; сказать про них «подключили» значит
        ошибиться — и ровно эту ошибку делает голое число «долг уменьшился».
        """
        report = self._delta(dict(scripts=("x",)),
                             dict(scripts=("x",), registry=("x",)))
        got = report["departed"][0]
        self.assertEqual(got["cause"], osd.FORGIVEN)
        self.assertNotEqual(got["cause"], osd.WIRED)
        self.assertIn("ПО-ПРЕЖНЕМУ нет", got["why"])

    def test_a_deleted_script_is_called_REMOVED_and_not_wired(self):
        """Положительный контроль на ПОРЯДОК вопросов.

        У удалённого файла вызывающего тоже нет — значит он отсутствует и в
        `no_caller`. Спроси «есть вызывающий?» раньше «файл есть?», и удаление
        доложилось бы как подключение.
        """
        report = self._delta(dict(scripts=("x", "y")), dict(scripts=("y",)))
        causes = {r["name"]: r["cause"] for r in report["departed"]}
        self.assertEqual(causes, {"x": osd.REMOVED})

    def test_a_newborn_orphan_is_called_BORN(self):
        report = self._delta(dict(scripts=("old",)), dict(scripts=("old", "fresh")))
        got = {r["name"]: r["cause"] for r in report["arrived"]}
        self.assertEqual(got, {"fresh": osd.BORN})

    def test_a_name_whose_caller_vanished_is_called_CALLER_LOST(self):
        report = self._delta(dict(scripts=("x",), callers=("x",)),
                             dict(scripts=("x",)))
        got = {r["name"]: r["cause"] for r in report["arrived"]}
        self.assertEqual(got, {"x": osd.CALLER_LOST})

    def test_a_name_whose_registry_record_vanished_is_named_separately(self):
        report = self._delta(dict(scripts=("x",), registry=("x",)),
                             dict(scripts=("x",)))
        got = {r["name"]: r["cause"] for r in report["arrived"]}
        self.assertEqual(got, {"x": osd.FORGIVENESS_GONE})

    def test_a_name_WRITTEN_INTO_the_baseline_is_named_a_FORBIDDEN_departure(self):
        """Дописывание в базу — единственный уход, при котором мир не изменился.

        Скрипт мёртв и до, и после; из красного набора он ушёл только потому,
        что имя вписали в объявление. Инв. #16 это ЗАПРЕЩАЕТ, и прибор обязан
        сказать это вслух — иначе такой уход читается как «долг уменьшился».
        """
        report = self._delta(dict(scripts=("x",)),
                             dict(scripts=("x",), baseline=("x",)))
        got = report["departed"][0]
        self.assertEqual(got["cause"], osd.BASELINED)
        self.assertEqual([r["name"] for r in report["forbidden"]], ["x"])
        self.assertIn("ЗАПРЕЩЁННОЕ ДЕЙСТВИЕ", osd.verdict(report)[1])

    def test_a_name_REMOVED_from_the_baseline_is_an_allowed_arrival(self):
        """Обратное направление РАЗРЕШЕНО: база убывает, сторож краснеет честно."""
        report = self._delta(dict(scripts=("x",), baseline=("x",)),
                             dict(scripts=("x",)))
        got = report["arrived"][0]
        self.assertEqual(got["cause"], osd.UNBASELINED)
        self.assertEqual(report["forbidden"], [])

    def test_the_dead_axis_does_NOT_see_the_baseline_at_all(self):
        """Две оси не взаимозаменяемы: вписанное в базу имя из `dead` не ушло.

        Сцена одна и та же, что у запрещённого ухода выше; меняется только ось,
        и вердикт обязан СМЕНИТЬСЯ. Совпади они — ось была бы украшением.
        """
        scene = (dict(scripts=("x",)), dict(scripts=("x",), baseline=("x",)))
        red = osd.verdict(self._delta(*scene, axis="red"))
        dead = osd.verdict(self._delta(*scene, axis="dead"))
        self.assertEqual(red[0], 1, red[1])
        self.assertEqual(dead[0], 0, dead[1])
        self.assertIn("`red`", red[1])
        self.assertIn("`dead`", dead[1])

    def test_every_name_is_PRINTED_not_just_counted(self):
        """Число без имён и есть дефект, против которого прибор написан."""
        report = self._delta(dict(scripts=("gone",)), dict(scripts=("came",)))
        text = osd.format_report(report)
        self.assertIn("gone", text)
        self.assertIn("came", text)


class TheThirdOutcomeIsNeverPassedOffAsAnAnswer(unittest.TestCase):
    """Инв. #17: «не измерено» отличимо и от «совпало», и от «разошлось»."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="osd_u_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_tree_without_entrypoints_is_unmeasured_not_an_empty_debt(self):
        empty = self.tmp / "empty"
        (empty / "scripts").mkdir(parents=True)
        got = osd.measure_root(empty)
        self.assertFalse(got["measured"])
        self.assertIn(osd.UNMEASURED, got["cause"])

    def test_an_absent_path_is_unmeasured_with_a_named_cause(self):
        got = osd.measure_root(self.tmp / "nope")
        self.assertFalse(got["measured"])
        self.assertIn(osd.UNMEASURED, got["cause"])

    def test_an_unmeasured_side_gives_code_2_and_names_WHICH_side(self):
        good = osd.measure_root(_tree(self.tmp / "good", scripts=("x",)))
        bad = osd.measure_root(self.tmp / "nope")
        for before, after, label in ((bad, good, "ДО"), (good, bad, "ПОСЛЕ")):
            report = osd.delta(before, after)
            code, head = osd.verdict(report)
            self.assertEqual(code, 2, head)
            self.assertIn(label, head)
            self.assertIn(osd.UNMEASURED, head)

    def test_without_the_declaration_the_RED_axis_is_unmeasured_not_empty(self):
        """База не прочитана ⇒ красный набор НЕ ИЗМЕРЕН.

        Пустое множество выдало бы ВЕСЬ долг за красный набор, то есть ответило
        бы на свой вопрос вместо нужного. Ось `dead` при этом измерима — и это
        проверяется рядом, чтобы отказ не оказался отказом вообще обо всём.
        """
        before = osd.measure_root(_tree(self.tmp / "nb1", scripts=("x",),
                                        declare_baseline=False))
        after = osd.measure_root(_tree(self.tmp / "nb2", scripts=("x", "y"),
                                       declare_baseline=False))
        self.assertTrue(before["measured"])
        self.assertFalse(before["red_measured"])
        code, head = osd.verdict(osd.delta(before, after, axis="red"))
        self.assertEqual(code, 2, head)
        self.assertIn("НЕ ИЗМЕРЕНА", head)
        self.assertEqual(osd.verdict(osd.delta(before, after, axis="dead"))[0], 1)

    def test_an_undeclared_axis_is_refused_and_not_guessed(self):
        got = osd.delta({"measured": True}, {"measured": True}, axis="выдумка")
        code, head = osd.verdict(got)
        self.assertEqual(code, 2, head)
        self.assertIn("не объявлена", head)

    def test_all_three_outcomes_are_observed_and_differ(self):
        good = osd.measure_root(_tree(self.tmp / "a", scripts=("x",)))
        moved = osd.measure_root(_tree(self.tmp / "b", scripts=("y",)))  # состав сменился
        bad = osd.measure_root(self.tmp / "nope")
        codes = {osd.verdict(osd.delta(good, good))[0],
                 osd.verdict(osd.delta(good, moved))[0],
                 osd.verdict(osd.delta(good, bad))[0]}
        self.assertEqual(codes, {0, 1, 2})

    def test_a_contradictory_state_is_unmeasured_and_not_a_cause(self):
        """Четвёртая ветвь у обеих причин — отказ, а не выдуманная причина.

        По построению она недостижима из пары замеров (имя, у которого нет ни
        вызывающего, ни записи, остаётся в долге). Поэтому её предъявляют
        напрямую: противоречивое состояние обязано получить НЕ ИЗМЕРЕНО, а не
        ближайшую подходящую причину.
        """
        state = {"entrypoints": {"x"}, "no_caller": {"x"},
                 "registry": set(), "baseline": set()}
        cause, why = osd.departure_cause("x", state)
        self.assertEqual(cause, osd.UNMEASURED)
        self.assertIn("противоречив", why)
        cause, why = osd.arrival_cause("x", state)
        self.assertEqual(cause, osd.UNMEASURED)
        self.assertIn("противоречив", why)


class TheRuleHasExactlyOneDoor(unittest.TestCase):
    """Второй копии правила проводки у прибора нет, и причины — закрытые списки."""

    SRC = pathlib.Path(osd.__file__)

    def test_the_module_keeps_no_second_copy_of_the_wiring_rule(self):
        """Своей регулярки «что считается вызовом» быть не должно.

        Разойдись она с `_unwired` — долг мерился бы двумя мерками, и прибор
        пускал бы через себя ровно те имена, из-за которых понадобился. Мера
        структурная (AST): модуль не ввозит `re` вовсе.
        """
        tree = ast.parse(self.SRC.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("re", imported,
                         "прибор завёл свою регулярку — это вторая мерка проводки")
        self.assertIn("spa_core", imported, "прибор обязан мерить дверью `_unwired`")

    def test_the_measurement_goes_through_unwired_and_nowhere_else(self):
        used = {n.attr for n in ast.walk(ast.parse(self.SRC.read_text(encoding="utf-8")))
                if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name) and n.value.id == "_unwired"}
        self.assertEqual(used, {"entrypoint_scripts", "scripts_without_caller",
                                "registry_recorded_scripts", "unwired_scripts"})

    def test_the_causes_are_a_closed_list(self):
        """Добавить причину — решение (ADR), а не правка строки."""
        self.assertEqual(osd.DEPARTURE_CAUSES,
                         (osd.WIRED, osd.FORGIVEN, osd.REMOVED, osd.BASELINED))
        self.assertEqual(osd.ARRIVAL_CAUSES,
                         (osd.BORN, osd.CALLER_LOST, osd.FORGIVENESS_GONE,
                          osd.UNBASELINED))
        self.assertEqual(osd.FORBIDDEN_CAUSES, (osd.BASELINED,))
        self.assertEqual(osd.AXES, ("red", "dead"))
        self.assertNotIn(osd.UNMEASURED, osd.DEPARTURE_CAUSES)
        self.assertNotIn(osd.UNMEASURED, osd.ARRIVAL_CAUSES)

    def test_the_exporter_is_named_and_not_reimplemented(self):
        """`git archive` своей копией не переписан — назван ОДИН сборщик.

        Мера берёт КОД, а не текст файла: слова «git archive» стоя́т в шапке и в
        докстринге `_load_exporter` именно затем, чтобы объяснить, почему своей
        копии нет, — и подстрочная проверка краснела бы ровно на объяснении.
        Прозу снимает та же дверь, которой её снимает сам сторож проводки
        (`_unwired.code_without_comments`), а не вторая копия правила.
        """
        self.assertEqual(osd._EXPORTER,
                         pathlib.Path("scripts") / "build_acceptance_tree.py")
        code = _unwired.code_without_comments(
            self.SRC, self.SRC.read_text(encoding="utf-8"))
        self.assertNotIn("archive", code, "прибор завёл свою выгрузку дерева")
        self.assertIn("build_acceptance_tree", code,
                      "сборщик обязан быть НАЗВАН в коде, а не в прозе")


class TheRefIsMeasuredInTheNamedClone(unittest.TestCase):
    """`measure_ref`: клон и ссылка НАЗВАНЫ, а неотвечающий клон даёт отказ."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="osd_ref_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        # имя ветки — ВХОД сцены (`.claude/rules/deployment.md`, § git-окружение):
        # без `-b` его задаёт конфиг ХОСТА, и сцена была бы зелена здесь и красна в CI.
        self._git("init", "-b", "main", str(self.repo), cwd=self.tmp)
        _tree(self.repo, scripts=("alone", "wired"), callers=("wired",))
        (self.repo / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy(pathlib.Path(osd.__file__).resolve().parents[2] / osd._EXPORTER,
                    self.repo / osd._EXPORTER)
        self._git("add", "-A", cwd=self.repo)
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-m", "scene", cwd=self.repo)

    def _git(self, *args, cwd):
        subprocess.run(["git", *args], cwd=str(cwd), check=True,
                       capture_output=True, text=True, timeout=120)

    def test_a_named_ref_is_measured_and_the_clone_is_printed(self):
        got = osd.measure_ref(self.repo, "main", self.tmp / "out")
        self.assertTrue(got["measured"], got.get("cause"))
        self.assertIn("alone", got["dead"])
        self.assertNotIn("wired", got["dead"])
        self.assertIn(str(self.repo), got["root"])
        self.assertIn("main", got["root"])

    def test_a_ref_the_clone_cannot_answer_is_unmeasured_not_an_empty_debt(self):
        got = osd.measure_ref(self.repo, "deadbeef", self.tmp / "out2")
        self.assertFalse(got["measured"])
        self.assertIn(osd.UNMEASURED, got["cause"])
        self.assertIn("усечённый клон", got["cause"])

    def test_without_the_exporter_the_instrument_REFUSES_loudly(self):
        """Причина обязана НАЗВАТЬ сборщика, а не только сказать «не измерено».

        Сцена различающая ровно этим (мутант M22 первого прогона выжил как раз
        тут): проглоти прибор пропавший сборщик — дерево осталось бы НЕ
        ВЫГРУЖЕННЫМ, и отказ пришёл бы всё равно, но ПО ДРУГОЙ причине («точек
        входа не найдено»). Два разных отказа с одним кодом неразличимы, и
        неразличимость и есть дефект: читатель не узнает, что ответ дан о
        пустом каталоге, а не о дереве ссылки.
        """
        (self.repo / osd._EXPORTER).unlink()
        self._git("add", "-A", cwd=self.repo)
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-m", "drop exporter", cwd=self.repo)
        got = osd.measure_ref(self.repo, "main", self.tmp / "out3")
        self.assertFalse(got["measured"])
        self.assertIn(osd.UNMEASURED, got["cause"])
        self.assertIn("build_acceptance_tree", got["cause"],
                      "отказ не назвал пропавший сборщик — причина подменена")
        self.assertNotIn("точек входа", got["cause"],
                         "ответ дан о пустом каталоге, а не о пропавшем сборщике")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

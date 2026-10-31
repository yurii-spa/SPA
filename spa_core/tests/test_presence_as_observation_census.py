"""Батарея переписи «присутствие файла выдано за доказательство ПИСАТЕЛЯ» (ADR-876).

# LLM_FORBIDDEN

Каждая сцена здесь — положительный контроль: либо воспроизводит дефект ADR-875
и ОБЯЗАНА найтись, либо воспроизводит ЧЕСТНУЮ форму и обязана НЕ найтись. Проба
приёмки `presence_as_observation_population_named` стои́т на обеих сторонах:
перепись, называющая находкой `if not path.exists(): return None`, бесполезна
ровно так же, как перепись, не видящая своего предмета.

Литеральных дат здесь нет вовсе: предмет меры — форма кода, а не календарь.
Имя ветки одноразовых репозиториев — ВХОД (`git init -b main`), а не умолчание
хоста (`init.defaultBranch` на Маке `main`, на `ubuntu-latest` `master` —
§ GIT-ОКРУЖЕНИЕ, `.claude/rules/deployment.md`).
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from spa_core.monitoring import presence_as_observation_census as c  # noqa: E402


@functools.lru_cache(maxsize=1)
def real_tree_report() -> dict:
    """Замер НАСТОЯЩЕГО дерева — один раз на прогон.

    Обход 2500 модулей стоит секунды; четыре теста, зовущие `measure()`
    по отдельности, платили бы за один и тот же ответ четырежды.
    """
    return c.measure()


def outcomes(source: str) -> list[str]:
    report = c.measure_module(source, rel="scene.py")
    assert "unmeasured" not in report, report
    return [site["outcome"] for site in report["sites"]]


def sites(source: str) -> list[dict]:
    report = c.measure_module(source, rel="scene.py")
    assert "unmeasured" not in report, report
    return report["sites"]


class MeasureDirection(unittest.TestCase):
    """Класс — НАПРАВЛЕНИЕ, а не наличие `exists()`."""

    def test_the_defect_of_adr_875_is_found(self):
        """Присутствие ⇒ «прочитано» — дословная авария, обязана найтись."""
        self.assertIn(c.PRESENCE_TO_OBSERVED, outcomes('''
import os
REPORT = "data/office_report.json"
def step():
    if os.path.exists(REPORT):
        return "прочитано: писатель был"
    return "НЕ ПРОЧИТАН"
'''))

    def test_the_honest_refusal_is_not_a_finding(self):
        """Отсутствие ⇒ «не измерено» — инв. #17, эталон, НЕ находка.

        Без этой стороны перепись годилась бы и слепой: 238 честных
        `if not path.exists(): return None` первая редакция меры назвала
        населением класса, и вывод был опровергнут собственным замером.
        """
        got = outcomes('''
import os
def step(path):
    if not os.path.exists(path):
        return "НЕ ИЗМЕРЕНО: файла нет"
    return parse(path)
''')
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertIn(c.ABSENCE_TO_UNMEASURED, got)

    def test_polarity_travels_through_not(self):
        """`if not exists(): …  else: «прочитано»` — тот же дефект через `not`."""
        self.assertIn(c.PRESENCE_TO_OBSERVED, outcomes('''
import os
P = "data/x.json"
def step():
    if not os.path.exists(P):
        return "НЕ ИЗМЕРЕНО"
    else:
        return "наблюдение получено"
'''))

    def test_conditional_expression_counts_as_a_branch(self):
        """`A if cond else B` — такая же ветка, как `if`."""
        self.assertIn(c.PRESENCE_TO_OBSERVED, outcomes('''
import os
def step(p):
    return "писатель был" if os.path.exists(p) else "НЕ ИЗМЕРЕНО"
'''))


class Vetoes(unittest.TestCase):
    """Каждое вето снимает СВОЙ род ложного срабатывания — и названо."""

    def test_verdict_standing_on_content_is_not_a_finding(self):
        """Прочитал СОДЕРЖИМОЕ ⇒ судит не по присутствию (`kill_switch`)."""
        got = outcomes('''
import json, os
def step(p):
    if os.path.exists(p):
        doc = json.load(open(p))
        return "наблюдение: " + str(doc.get("active"))
    return "НЕ ИЗМЕРЕНО"
''')
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertIn(c.CONTENT_CHECKED, got)

    def test_asking_the_writer_is_the_exemplar(self):
        """Спросил свежесть/писателя ⇒ починенная ADR-875 форма."""
        got = outcomes('''
import os, time
def step(p):
    if os.path.exists(p):
        if time.time() - os.path.getmtime(p) < 3600:
            return "прочитано: писатель был"
    return "НЕ ИЗМЕРЕНО"
''')
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertIn(c.WRITER_ASKED, got)

    def test_negation_in_the_same_string_is_not_an_assertion(self):
        """«не прочитан» несёт «прочитан» — и утверждением не является.

        Замер первой редакции: без построчного вето отрицания сюда попадали
        `consume_office_reports.main` и `card_acceptance`, то есть ЧЕСТНЫЕ
        места, печатающие ровно «НЕ ПРОЧИТАН».
        """
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, outcomes('''
import os
def step(p):
    if os.path.exists(p):
        return "JSON не прочитан"
    return "файла нет"
'''))

    def test_the_predicate_name_is_not_its_own_verdict(self):
        """`p.exists()` внутри ветки — не вердикт «существует».

        Иначе мера подтверждала бы себя собой: 4 ложные находки из 21
        (`director_verify`, `run_identity_key_price`, `guardian_forward`)
        держались ровно на этом.

        Утверждение здесь — РАВЕНСТВО исходов, а не только «не находка»:
        мутация «имя предиката снова улика» переводит это место в
        `presence_restated` (слово `exists` живёт в словаре ПРИСУТСТВИЯ), и
        проверка «находкой не стало» её ПЕРЕЖИЛА (замер мутаций #994, 7/18).
        Наблюдаемый выход меняется — значит мерить надо его, а не его часть.
        """
        self.assertEqual([c.NO_OBSERVATION_VERDICT, c.NO_OBSERVATION_VERDICT],
                         outcomes('''
import os
def step(a, b):
    if os.path.exists(a):
        if os.path.exists(b):
            return 1
    return 0
'''))

    def test_a_lowercase_local_name_is_not_evidence(self):
        """`ok.append(path)` — локальный СПИСОК, а не вердикт о наблюдении.

        Дословная ложная находка первой редакции: `card_delivery.validate`.

        Утверждение — РАВЕНСТВО исходов: мутация «строчный идентификатор снова
        улика» переводит место в `presence_generic_pass` (`ok` живёт в словаре
        родового «прошло»), и проверка «находкой не стало» её ПЕРЕЖИЛА (замер
        мутаций #994, 8/18).
        """
        self.assertEqual([c.NO_OBSERVATION_VERDICT], outcomes('''
import os
def validate(paths):
    ok, bad = [], []
    for p in paths:
        if os.path.exists(p):
            ok.append(p)
        else:
            bad.append(p)
    return ok, bad
'''))


class StrengthOfTheClaim(unittest.TestCase):
    """Три яруса: прибор не завышает силу утверждения."""

    def test_generic_pass_is_not_measured_rather_than_a_finding(self):
        """`PASS` без названного предмета ⇒ НЕ ИЗМЕРЕНО, а не находка."""
        got = outcomes('''
import os
def check(p):
    return "PASS" if os.path.exists(p) else "FAIL"
''')
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertIn(c.PRESENCE_GENERIC_PASS, got)

    def test_restating_presence_is_an_honest_tautology(self):
        """«файл существует» — ПОВТОР вопроса, а не утверждение сверх него."""
        got = outcomes('''
import os
def check(p):
    if os.path.exists(p):
        return {"state": "VERIFIED", "note": "файл существует"}
    return {"state": "REFUTED", "note": "файла не существует"}
''')
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertIn(c.PRESENCE_RESTATED, got)

    def test_a_readiness_score_is_a_claim_even_without_a_word(self):
        """`score += 2` — утверждение о ГОТОВНОСТИ, даже если слов нет.

        Форма `golive_readiness_report.assess_data_sources`: напечатано
        «present ✓», а прибавлены ДВА БАЛЛА готовности к go-live.
        """
        found = [s for s in sites('''
import os
def assess(base):
    score = 0.0
    if (base / "spa_core" / "utils" / "defillama.py").exists():
        score += 2.0
    return score
''') if s["outcome"] == c.PRESENCE_TO_OBSERVED]
        self.assertEqual(1, len(found), found)
        self.assertEqual("readiness_score", found[0]["claim"])

    def test_claim_kind_is_always_from_the_declared_dictionary(self):
        """Род утверждения у находки объявлен в `CLAIMS`, а не выдуман."""
        for site in sites('''
import os
P = "data/x.json"
def a():
    if os.path.exists(P):
        return "прочитано"
    return "НЕ ПРОЧИТАН"
'''):
            if site["outcome"] == c.PRESENCE_TO_OBSERVED:
                self.assertIn(site["claim"], c.CLAIMS)


class PathReconstruction(unittest.TestCase):
    """Сегменты пути собираются ПО ПОРЯДКУ, и каталог не подменяет файл."""

    def test_segments_keep_source_order(self):
        seg = c.path_segments(*_target('''
def f(base):
    p = base / "spa_core" / "utils" / "defillama.py"
    return p.exists()
'''))
        self.assertEqual(["spa_core", "utils", "defillama.py"], seg)

    def test_window_join_beats_a_single_segment(self):
        """Окно из трёх предпочитается одиночному `spa_core`.

        Дословная ошибка первой редакции живой оси: она отвечала
        «constant (spa_core)» — про КАТАЛОГ вместо файла, то есть говорила о
        дереве правду, а о предмете ложь.
        """
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "spa_core", "utils"))
            open(os.path.join(root, "spa_core", "utils", "defillama.py"),
                 "w").close()
            axis = c.tracked_constant_axis(
                {"path_segments": ["spa_core", "utils", "defillama.py"]},
                root=root)
            self.assertEqual("spa_core/utils/defillama.py", axis.get("path"))

    def test_a_directory_answer_with_an_unplaced_filename_is_unmeasured(self):
        """Собрался каталог, а имя файла не размещено ⇒ НЕ ИЗМЕРЕНО.

        Форма `golive/checklist.check_wallet_ready`: сегменты приходят из
        ДВУХ альтернатив `A if base else B`, порядок у них не путевой, и
        «constant (data)» было бы ложным замером.
        """
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "data"))
            axis = c.tracked_constant_axis(
                {"path_segments": ["wallet_ready.sentinel", "data"]}, root=root)
            self.assertEqual(c.TRACKED_UNMEASURED, axis["kind"])
            self.assertIn("реконструкция неполна", axis["reason"])

    def test_several_existing_paths_of_one_length_are_unmeasured(self):
        """Несколько путей одной длины — выбор одного был бы угадыванием."""
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "data"))
            for name in ("a.json", "b.json"):
                open(os.path.join(root, "data", name), "w").close()
            axis = c.tracked_constant_axis(
                {"path_segments": ["data/a.json", "data/b.json"]}, root=root)
            self.assertEqual(c.TRACKED_UNMEASURED, axis["kind"])
            self.assertIn("НЕСКОЛЬКО", axis["reason"])


def _target(source: str):
    """`(узел-аргумент предиката, привязки)` из одноразовой сцены."""
    import ast
    tree = ast.parse(source)
    binds = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            binds.setdefault(node.targets[0].id, []).append(node.value)
    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in c._PREDICATES)
    return call.func.value, binds


class TrackedConstantAxis(unittest.TestCase):
    """Живая ось — настоящий git на одноразовом репозитории, три исхода."""

    @staticmethod
    def _repo() -> str:
        root = tempfile.mkdtemp(prefix="spa_presence_axis_")
        # Имя ветки — ВХОД сцены, а не умолчание хоста (§ GIT-ОКРУЖЕНИЕ).
        subprocess.run(["git", "init", "-b", "main", root],
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"],
                       cwd=root, check=True, capture_output=True)
        return root

    def test_tracked_and_equal_to_head_is_a_constant(self):
        root = self._repo()
        rel = "spa_core/utils/defillama.py"
        os.makedirs(os.path.join(root, "spa_core", "utils"))
        open(os.path.join(root, rel), "w").write("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "scene"], cwd=root, check=True,
                       capture_output=True)
        axis = c.tracked_constant_axis(
            {"path_segments": ["spa_core", "utils", "defillama.py"]}, root=root)
        self.assertEqual(c.TRACKED_CONSTANT, axis["kind"], axis)

    def test_untracked_means_a_writer_was_there(self):
        root = self._repo()
        os.makedirs(os.path.join(root, "data"))
        open(os.path.join(root, "data", "live.json"), "w").write("{}")
        axis = c.tracked_constant_axis(
            {"path_segments": ["data/live.json"]}, root=root)
        self.assertEqual(c.TRACKED_WRITER, axis["kind"], axis)

    def test_tracked_but_rewritten_means_a_writer_was_there(self):
        """Переписанный tracked-файл — тоже доказательство писателя."""
        root = self._repo()
        os.makedirs(os.path.join(root, "data"))
        path = os.path.join(root, "data", "live.json")
        open(path, "w").write("{}")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "scene"], cwd=root, check=True,
                       capture_output=True)
        open(path, "w").write('{"written_by": "fleet"}')
        axis = c.tracked_constant_axis(
            {"path_segments": ["data/live.json"]}, root=root)
        self.assertEqual(c.TRACKED_WRITER, axis["kind"], axis)

    def test_a_resolved_but_missing_path_is_absent_not_unmeasured(self):
        root = self._repo()
        axis = c.tracked_constant_axis(
            {"path_segments": ["data/never_written.json"]}, root=root)
        self.assertEqual(c.TRACKED_ABSENT, axis["kind"], axis)

    def test_outside_a_repository_the_axis_says_unmeasured(self):
        """Не репозиторий ⇒ третий исход с причиной, а не «константа»."""
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "data"))
            open(os.path.join(root, "data", "x.json"), "w").close()
            axis = c.tracked_constant_axis(
                {"path_segments": ["data/x.json"]}, root=root)
            self.assertEqual(c.TRACKED_UNMEASURED, axis["kind"], axis)
            self.assertIn("git", axis["reason"])


class LiveAxisIsWiredIntoMeasure(unittest.TestCase):
    """`measure()` обязана СПРОСИТЬ живую ось у каждой находки, а не объявить её.

    Контроль написан по выжившему мутанту (замер #994, 16/18): подстановка
    `site["tracked"] = {"kind": unmeasured}` вместо вызова `tracked_constant_axis`
    ПЕРЕЖИЛА проверку «вердикт живой оси из объявленного словаря» — `unmeasured`
    в словаре тоже есть. Проверять надо не ФОРМУ ответа, а то, что ответ
    РАЗНЫЙ на сценах, отличающихся ровно происхождением файла.

    Сцена — настоящий одноразовый репозиторий, и ответы ПРОТИВОПОЛОЖНЫЕ:
    tracked-и-равен-HEAD ⇒ `constant`, untracked ⇒ `writer`.
    """

    @staticmethod
    def _scene(commit_artifact: bool) -> str:
        root = tempfile.mkdtemp(prefix="spa_presence_wiring_")
        # Имя ветки — ВХОД сцены, не умолчание хоста (§ GIT-ОКРУЖЕНИЕ).
        subprocess.run(["git", "init", "-b", "main", root],
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"],
                       cwd=root, check=True, capture_output=True)
        os.makedirs(os.path.join(root, "scripts"))
        os.makedirs(os.path.join(root, "data"))
        open(os.path.join(root, "scripts", "defect.py"), "w").write(
            "import os\n"
            "P = 'data/office_report.json'\n"
            "def step():\n"
            "    if os.path.exists(P):\n"
            "        return 'прочитано: писатель был'\n"
            "    return 'НЕ ПРОЧИТАН'\n")
        open(os.path.join(root, "data", "office_report.json"), "w").write("{}")
        subprocess.run(["git", "add", "scripts/defect.py"]
                       + (["data/office_report.json"] if commit_artifact else []),
                       cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "scene"], cwd=root, check=True,
                       capture_output=True)
        return root

    def test_a_tracked_artifact_makes_the_verdict_a_constant(self):
        report = c.measure(self._scene(commit_artifact=True), ["scripts"])
        self.assertEqual(1, len(report["findings"]), report["findings"])
        self.assertEqual(c.TRACKED_CONSTANT,
                         report["findings"][0]["tracked"]["kind"],
                         report["findings"][0])
        self.assertEqual(1, report["tracked_kinds"][c.TRACKED_CONSTANT])

    def test_an_untracked_artifact_makes_the_verdict_a_writer(self):
        report = c.measure(self._scene(commit_artifact=False), ["scripts"])
        self.assertEqual(1, len(report["findings"]), report["findings"])
        self.assertEqual(c.TRACKED_WRITER,
                         report["findings"][0]["tracked"]["kind"],
                         report["findings"][0])
        self.assertEqual(0, report["tracked_kinds"][c.TRACKED_CONSTANT])

    def test_the_live_axis_is_asked_once_per_finding(self):
        """Сумма родов живой оси РАВНА числу находок — ни одна не пропущена."""
        report = real_tree_report()
        if report["verdict"] == "unmeasured":
            self.skipTest("дерево не измерено — предмет не поднят")
        self.assertEqual(len(report["findings"]),
                         sum(report["tracked_kinds"].values()))


class ThirdOutcome(unittest.TestCase):
    """«Не измерено» — своё значение, а не ноль и не «чисто» (инв. #17)."""

    def test_an_unparsable_module_is_named_and_the_code_is_two(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "scripts"))
            open(os.path.join(root, "scripts", "broken.py"), "w").write(
                "def f(:\n    pass\n")
            report = c.measure(root, ["scripts"])
            self.assertEqual("unmeasured", report["verdict"])
            self.assertTrue(any("broken.py" in x
                                for x in report["unmeasured_files"]), report)
            self.assertEqual(c.RC_UNMEASURED, c.exit_code(report))

    def test_an_empty_scope_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as root:
            report = c.measure(root, ["spa_core"])
            self.assertEqual("unmeasured", report["verdict"])
            self.assertIn("мерить нечего", report["reason"])
            self.assertEqual(c.RC_UNMEASURED, c.exit_code(report))

    def test_a_missing_root_is_unmeasured(self):
        report = c.measure("/nonexistent/spa/root/for/the/census", ["spa_core"])
        self.assertEqual("unmeasured", report["verdict"])
        self.assertEqual(c.RC_UNMEASURED, c.exit_code(report))

    def test_a_clean_scope_returns_zero_and_findings_return_one(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "scripts"))
            clean = os.path.join(root, "scripts", "clean.py")
            open(clean, "w").write(
                "import os\n"
                "def f(p):\n"
                "    if not os.path.exists(p):\n"
                "        return 'НЕ ИЗМЕРЕНО'\n"
                "    return parse(p)\n")
            self.assertEqual(c.RC_CLEAN, c.exit_code(c.measure(root, ["scripts"])))
            open(os.path.join(root, "scripts", "defect.py"), "w").write(
                "import os\n"
                "P = 'data/x.json'\n"
                "def f():\n"
                "    if os.path.exists(P):\n"
                "        return 'прочитано'\n"
                "    return 'НЕ ПРОЧИТАН'\n")
            self.assertEqual(c.RC_FINDINGS,
                             c.exit_code(c.measure(root, ["scripts"])))

    def test_the_shell_surface_is_reported_as_unmeasured_not_zero(self):
        report = real_tree_report()
        self.assertEqual("unmeasured", report["shell_surface"]["verdict"])


class DriveAxis(unittest.TestCase):
    """Положительный контроль САМОЙ меры, не её описания."""

    def test_the_measure_distinguishes_both_directions(self):
        drive = c.drive_both_directions()
        self.assertEqual(c.DRIVE_DISTINGUISHES, drive["kind"], drive)

    def test_a_measure_blind_to_the_defect_is_reported_blind(self):
        """Ослепим словарь наблюдения — живая ось обязана сказать `blind`.

        Без этого звена «distinguishes» был бы утверждением о словаре, а не о
        поведении: проба, зеленеющая на слепой мере, и есть предмет класса.
        """
        import re as _re
        saved = c._OBSERVATION_WORDS
        try:
            c._OBSERVATION_WORDS = _re.compile(r"(?!x)x")   # не совпадает ни с чем
            drive = c.drive_both_directions()
        finally:
            c._OBSERVATION_WORDS = saved
        self.assertEqual(c.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("defect", drive["link"])
        self.assertIn("НЕ найден", drive["reason"])

    def test_removing_the_negation_veto_is_reported_blind(self):
        """Снятое вето отрицания — тоже `blind`, и звено НАЗВАНО.

        «не прочитан» несёт «прочитан»: без построчного вето мера объявила бы
        находкой `consume_office_reports.main`, то есть ЧЕСТНОЕ место,
        печатающее ровно «НЕ ПРОЧИТАН». Первая редакция так и делала.
        """
        import re as _re
        saved = c._ABSENCE
        try:
            c._ABSENCE = _re.compile(r"(?!x)x")   # не совпадает ни с чем
            drive = c.drive_both_directions()
        finally:
            c._ABSENCE = saved
        self.assertEqual(c.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("negated", drive["link"])


class AcceptanceProbe(unittest.TestCase):
    """У пробы приёмки ТРИ исхода, и каждый ПОДНЯТ сценой, а не описан.

    Контроль написан по двум выжившим мутантам (замер #994, 17/18 и 18/18):
    снятие ветки «мера СЛЕПА ⇒ not_satisfied» и ветки «население НЕ измерено ⇒
    unmeasured» не поменяло НИ ОДНОГО упавшего имени. Отказ самой пробы был
    единственным местом, у которого не было шва, — то есть у сторожа приёмки
    жил fail-OPEN.
    """

    @staticmethod
    def _probe():
        from spa_core.monitoring import card_acceptance
        return card_acceptance

    @staticmethod
    def _scene_measure():
        """`c.measure`, отвечающая про ОДНОРАЗОВУЮ сцену, а не про это дерево.

        Проба зовёт `m.measure()` — именно эту ссылку модуля, — поэтому
        проводка «проба → перепись» остаётся предметом проверки; подменяется
        только КОРЕНЬ, о котором спрашивают.

        Почему не настоящее дерево: «satisfied» на нём есть утверждение о
        ДЕРЕВЕ и об ИНТЕРПРЕТАТОРЕ, а не о пробе. Один файл с f-строкой
        PEP 701 (законной на 3.13 Мака и SyntaxError на 3.11 в CI — авария
        `agent-ci-lite-krasen-f-stroka-pep-701-na-311`) сделал бы замер
        `unmeasured`, проба честно ответила бы `unmeasured`, и тест покраснел
        бы от ЧУЖОЙ правки. Сцена отвечает на вопрос о пробе на ЛЮБОМ хосте.
        """
        root = LiveAxisIsWiredIntoMeasure._scene(commit_artifact=True)
        report = c.measure(root, ["scripts"])
        assert report["verdict"] == "findings", report
        return lambda *a, **k: report

    def test_a_satisfied_verdict_names_both_measurements(self):
        ca = self._probe()
        saved = c.measure
        try:
            c.measure = self._scene_measure()
            state, why = ca.PROBES[
                "presence_as_observation_population_named"](None)
        finally:
            c.measure = saved
        self.assertEqual(ca.SATISFIED, state, why)
        self.assertIn("население НАЗВАНО", why)
        self.assertIn("КОНСТАНТА", why)

    def test_a_blind_measure_is_not_satisfied(self):
        """Слепая мера — НЕ выполненный критерий: её населению верить нельзя."""
        import re as _re
        ca = self._probe()
        saved = c._OBSERVATION_WORDS
        saved_measure = c.measure
        try:
            c._OBSERVATION_WORDS = _re.compile(r"(?!x)x")
            c.measure = lambda *a, **k: real_tree_report()
            state, why = ca.PROBES[
                "presence_as_observation_population_named"](None)
        finally:
            c._OBSERVATION_WORDS = saved
            c.measure = saved_measure
        self.assertEqual(ca.NOT_SATISFIED, state, why)
        self.assertIn("СЛЕПА", why)

    def test_an_unmeasured_population_is_unmeasured_not_satisfied(self):
        """«Население НЕ измерено» никогда не выдаётся за выполненный критерий."""
        ca = self._probe()
        saved = c.measure
        try:
            c.measure = lambda *a, **k: {
                "verdict": "unmeasured",
                "reason": "сцена замера: корень дерева не прочитан"}
            state, why = ca.PROBES[
                "presence_as_observation_population_named"](None)
        finally:
            c.measure = saved
        self.assertEqual(ca.UNMEASURED, state, why)
        self.assertIn("население НЕ измерено", why)

    def test_a_raising_measure_is_unmeasured_too(self):
        ca = self._probe()
        saved = c.measure

        def _boom(*a, **k):
            raise RuntimeError("сцена замера: дерево не прочитано")

        try:
            c.measure = _boom
            state, why = ca.PROBES[
                "presence_as_observation_population_named"](None)
        finally:
            c.measure = saved
        self.assertEqual(ca.UNMEASURED, state, why)
        self.assertIn("НЕ\nизмерено".replace("\n", " "), why)

    def test_the_probe_refuses_an_argument(self):
        ca = self._probe()
        state, why = ca.PROBES[
            "presence_as_observation_population_named"]("some/file.py")
        self.assertEqual(ca.UNMEASURED, state, why)
        self.assertIn("не принимает аргумента", why)


class RealTree(unittest.TestCase):
    """Перепись читает НАСТОЯЩЕЕ дерево, и её исходы — из объявленного словаря."""

    def test_every_outcome_is_from_the_declared_dictionary(self):
        report = real_tree_report()
        self.assertIn(report["verdict"], ("findings", "clean", "unmeasured"))
        if report["verdict"] != "unmeasured":
            self.assertEqual(set(c.OUTCOMES), set(report["counts"]))
            self.assertEqual(report["site_count"],
                             sum(report["counts"].values()))

    def test_an_unmeasured_module_of_the_real_tree_is_never_swallowed(self):
        """Неразобранный модуль ДЕРЕВА обязан быть НАЗВАН, а не проглочен.

        Утверждение здесь — про ПРЕДСТАВЛЕНИЕ (инв. #17), а не про пустоту
        списка, и это решение с причиной, а не послабление (инв. #16).
        Пустота списка — свойство ИНТЕРПРЕТАТОРА, а не прибора: на Маке
        `python3` 3.13, в CI 3.11.17, и f-строка PEP 701 законна там и
        SyntaxError здесь (дословная авария `agent-ci-lite-krasen-f-stroka-pep-701-na-311`,
        цикл #784). Тест, утверждавший `unmeasured_files == []`, краснел бы в
        CI от КАЛЕНДАРЯ чужих правок, а не от своего предмета — ровно та бомба,
        про которую § «Время в тестах» в `.claude/rules/deployment.md`.
        Эмуляция грамматики 3.11 на этом дереве сегодня даёт 0 таких файлов,
        но это НИЖНЯЯ граница: различие PEP 701 лежит в токенизаторе.

        Пустоту дерева от синтаксиса мерит СВОЯ джоба (`SPA CI-Lite`), и
        дублировать её вопрос здесь значило бы отвечать не на свой.
        """
        report = real_tree_report()
        unmeasured = report.get("unmeasured_files", [])
        if unmeasured:
            # Каждый назван ПОИМЁННО и с причиной, и вердикт — «не измерено»,
            # а не «чисто»: иначе перепись ответила бы на свой вопрос вместо
            # нужного (ровно авария #207).
            self.assertEqual("unmeasured", report["verdict"], report["verdict"])
            self.assertEqual(c.RC_UNMEASURED, c.exit_code(report))
            for item in unmeasured:
                self.assertIn(":", item, item)
                self.assertTrue(item.split(":", 1)[1].strip(), item)
        else:
            self.assertIn(report["verdict"], ("findings", "clean"))

    def test_every_finding_carries_a_live_axis_verdict(self):
        report = real_tree_report()
        if report["verdict"] == "unmeasured":
            self.skipTest("дерево не измерено — предмет не поднят")
        for site in report["findings"]:
            self.assertIn(site["tracked"]["kind"],
                          (c.TRACKED_CONSTANT, c.TRACKED_WRITER,
                           c.TRACKED_ABSENT, c.TRACKED_UNMEASURED), site)

    def test_render_never_prints_a_bare_zero_for_the_shell_surface(self):
        report = real_tree_report()
        text = "\n".join(c.render(report))
        self.assertIn("НЕ ИЗМЕРЕНО: оболочка/воркфлоу", text)


if __name__ == "__main__":
    unittest.main()

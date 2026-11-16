"""Контроль прибора «достижим ли сам объявленный корень» (ADR-1027).

Часов прибор не спрашивает вовсе, и литеральных дат в файле нет — поэтому
освобождения от храповика замороженных дат ему не нужно: освобождать не от чего.

Каждая сцена — ОДНО звено контура, и у каждой есть контроль в обе стороны:
порвал звено ⇒ прибор обязан СМЕНИТЬ ответ. Сцены одноразовые, живое дерево
не трогается; отдельно проверено, что на живом дереве пол прибора СОВПАДАЕТ
с населением `_mention_wiring` — правило одно, читателей два.
"""
from __future__ import annotations

import ast
import os
import pathlib
import random
import stat
import tempfile
import unittest

from spa_core.tests import _mention_wiring as mw
from spa_core.tests import _root_reachability as rr

_REPO = pathlib.Path(__file__).resolve().parents[2]

_SUBJECT = "def main():\n    return 0\n"


def _write(root: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


class _Scene:
    """Одноразовое дерево: plist → обёртка → субъект, плюс мёртвый корень."""

    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory(prefix="rr_scene_")
        self.root = pathlib.Path(self.dir.name)

    def close(self) -> None:
        self.dir.cleanup()


class LiveChainAndDeadRoot(unittest.TestCase):
    """Сцена, РАЗЛИЧАЮЩАЯ пол и потолок: субъект за мёртвым корнем."""

    def setUp(self) -> None:
        self.scene = _Scene()
        r = self.scene.root
        # живая цепь: launchd → обёртка → alpha
        _write(r, "launchd/com.spa.alpha.plist", "scripts/run_alpha.sh\n")
        _write(r, "scripts/run_alpha.sh", "python3 -m spa_core.monitoring.alpha\n")
        _write(r, "spa_core/monitoring/alpha.py", _SUBJECT)
        # мёртвый объявленный корень: модуль-библиотека, которую не зовёт никто
        _write(r, "spa_core/lib/dead_caller.py", "from spa_core.monitoring import beta\n")
        _write(r, "spa_core/monitoring/beta.py", _SUBJECT)
        self.addCleanup(self.scene.close)

    def _measure(self, **kw):
        return rr.measure(self.scene.root, min_subjects=2, **kw)

    def test_the_floor_reproduces_the_declared_root_rule_and_excuses_beta(self):
        """Под ПРАВИЛОМ ADR-1026 мёртвый корень прощает beta — это и есть пол."""
        rep = self._measure()
        self.assertEqual(rep["population_floor"], [],
                         "по объявленному правилу beta достижима — пол пуст")

    def test_the_ceiling_names_beta_because_its_only_caller_is_itself_an_orphan(self):
        """Под УЗКИМ набором корней beta — член класса. Потолок > пола."""
        rep = self._measure()
        self.assertEqual(rep["population_ceiling"], ["spa_core/monitoring/beta.py"])
        self.assertGreater(len(rep["population_ceiling"]),
                           len(rep["population_floor"]),
                           "сцена обязана РАЗЛИЧАТЬ два замера, иначе она не контроль")

    def test_the_dead_declared_root_is_named_with_its_kind(self):
        rep = self._measure()
        self.assertIn("spa_core/lib/dead_caller.py",
                      rep["declared_roots_unreachable"])
        self.assertIn("библиотека без точки входа (сторожа нет)",
                      rep["declared_roots_unreachable_by_kind"])

    def test_connecting_the_dead_root_to_launchd_empties_the_ceiling(self):
        """Контроль в ОБРАТНУЮ сторону: починил звено ⇒ ответ сменился."""
        before = self._measure()
        self.assertEqual(before["population_ceiling"],
                         ["spa_core/monitoring/beta.py"])
        _write(self.scene.root, "launchd/com.spa.dead.plist",
               "python3 -m spa_core.lib.dead_caller\n")
        after = self._measure()
        self.assertEqual(after["population_ceiling"], [],
                         "корень позван извне ⇒ субъект за ним больше не сирота")
        self.assertNotIn("spa_core/lib/dead_caller.py",
                         after["declared_roots_unreachable"])

    def test_the_live_chain_subject_is_in_neither_end_of_the_bracket(self):
        rep = self._measure()
        self.assertNotIn("spa_core/monitoring/alpha.py", rep["population_floor"])
        self.assertNotIn("spa_core/monitoring/alpha.py", rep["population_ceiling"])


class TransitivityIsAssertedAgainstTheTraversalOrder(unittest.TestCase):
    """Цепь длиной 3 — чтобы «фикспойнт в один проход» КРАСНЕЛ.

    Урок #1165: сцена в ПРЯМОМ порядке зелена и у прибора, считающего один
    шаг. Поэтому имена здесь выложены ПРОТИВ сортированного обхода
    (`zeta → yankee → xray`), и число раундов проверяется явно.
    """

    def setUp(self) -> None:
        self.scene = _Scene()
        r = self.scene.root
        _write(r, "launchd/com.spa.head.plist", "scripts/zeta.sh\n")
        _write(r, "scripts/zeta.sh", "bash scripts/yankee.sh\n")
        _write(r, "scripts/yankee.sh", "bash scripts/xray.sh\n")
        _write(r, "scripts/xray.sh", "python3 -m spa_core.monitoring.gamma\n")
        _write(r, "spa_core/monitoring/gamma.py", _SUBJECT)
        _write(r, "spa_core/monitoring/delta.py", _SUBJECT)
        _write(r, "scripts/zeta.sh", "bash scripts/yankee.sh\n")
        self.addCleanup(self.scene.close)

    def test_a_three_link_chain_needs_more_than_two_rounds(self):
        rep = rr.measure(self.scene.root, min_subjects=2)
        self.assertGreater(rep["fixpoint_rounds_narrow"], 2,
                           "цепь из трёх звеньев обязана требовать >2 проходов")
        self.assertNotIn("spa_core/monitoring/gamma.py", rep["population_ceiling"])

    def test_the_subject_nobody_mentions_is_census_not_a_member_of_this_class(self):
        rep = rr.measure(self.scene.root, min_subjects=2)
        self.assertNotIn("spa_core/monitoring/delta.py", rep["population_ceiling"],
                         "о нём уже отвечает перепись храповика — это не предмет")


class TheCiSurfaceIsADeclaredAddition(unittest.TestCase):
    """Без воркфлоу прибор ВЫДУМАЛ БЫ сироту — поэтому добавление объявлено."""

    def setUp(self) -> None:
        self.scene = _Scene()
        r = self.scene.root
        _write(r, "launchd/com.spa.any.plist", "scripts/run_alpha.sh\n")
        _write(r, "scripts/run_alpha.sh", "python3 -m spa_core.monitoring.alpha\n")
        _write(r, "spa_core/monitoring/alpha.py", _SUBJECT)
        # субъекта зовёт помощник, которого зовёт ТОЛЬКО воркфлоу CI
        _write(r, ".github/workflows/ci.yml",
               "jobs:\n  t:\n    run: python3 -m spa_core.lib.ci_helper\n")
        _write(r, "spa_core/lib/ci_helper.py",
               "from spa_core.monitoring import epsilon\n")
        _write(r, "spa_core/monitoring/epsilon.py", _SUBJECT)
        self.addCleanup(self.scene.close)

    def test_a_subject_called_only_by_ci_is_not_an_orphan(self):
        rep = rr.measure(self.scene.root, min_subjects=2)
        self.assertNotIn("spa_core/monitoring/epsilon.py", rep["population_ceiling"])
        self.assertEqual(rep["ci_surface_added"], [".github/workflows/ci.yml"])

    def test_removing_the_ci_surface_would_fabricate_that_orphan(self):
        """Контроль цены добавления: снял поверхность ⇒ появился ложный член.

        Упоминающий у субъекта ОСТАЁТСЯ (`spa_core/lib/ci_helper.py`), меняется
        только достижимость этого упоминающего — иначе субъект ушёл бы в
        перепись храповика, и сцена проверяла бы не то.
        """
        (self.scene.root / ".github/workflows/ci.yml").unlink()
        rep = rr.measure(self.scene.root, min_subjects=2)
        self.assertEqual(rep["ci_surface_added"], [])
        self.assertIn("spa_core/lib/ci_helper.py",
                      rep["declared_roots_unreachable"])
        self.assertIn("spa_core/monitoring/epsilon.py", rep["population_ceiling"],
                      "без поверхности CI член класса ВЫДУМЫВАЕТСЯ — ровно "
                      "поэтому добавление и объявлено")


class ThirdOutcomeIsNotZero(unittest.TestCase):
    """«Не измерено» — отдельный исход, а не ноль находок (инв. #17)."""

    def test_a_thin_subject_surface_is_unmeasured(self):
        scene = _Scene()
        self.addCleanup(scene.close)
        _write(scene.root, "launchd/com.spa.x.plist", "x\n")
        _write(scene.root, "spa_core/monitoring/alpha.py", _SUBJECT)
        with self.assertRaises(rr.Unmeasured):
            rr.measure(scene.root, min_subjects=50)

    def test_a_tree_without_any_outside_root_is_unmeasured_not_empty(self):
        scene = _Scene()
        self.addCleanup(scene.close)
        _write(scene.root, "spa_core/monitoring/alpha.py", _SUBJECT)
        _write(scene.root, "spa_core/monitoring/beta.py", _SUBJECT)
        _write(scene.root, "spa_core/lib/x.py", "alpha beta\n")
        with self.assertRaises(rr.Unmeasured) as cm:
            rr.measure(scene.root, min_subjects=2)
        self.assertIn("корня-извне", str(cm.exception))

    def test_an_unreadable_surface_file_is_unmeasured(self):
        scene = _Scene()
        self.addCleanup(scene.close)
        _write(scene.root, "launchd/com.spa.x.plist", "scripts/w.sh\n")
        _write(scene.root, "scripts/w.sh", "alpha\n")
        _write(scene.root, "spa_core/monitoring/alpha.py", _SUBJECT)
        _write(scene.root, "spa_core/monitoring/beta.py", _SUBJECT)
        blind = _write(scene.root, "spa_core/lib/blind.py", "beta\n")
        os.chmod(blind, 0)
        self.addCleanup(lambda: os.chmod(blind, stat.S_IRUSR | stat.S_IWUSR))
        if os.access(blind, os.R_OK):
            self.skipTest("файл остался читаемым — предпосылка НЕ ОБЕСПЕЧЕНА")
        with self.assertRaises(rr.Unmeasured):
            rr.measure(scene.root, min_subjects=2)

    def test_an_unreadable_workflow_file_is_unmeasured_too(self):
        """Своя дверь чтения — свой контроль.

        Нечитаемый файл в поверхности `_mention_wiring` ловит ЕГО `tree_texts`,
        а поверхность CI читает этот прибор САМ — и батарея мутаций показала,
        что без отдельной сцены «проглотил ошибку и пошёл дальше» выживает.
        """
        scene = _Scene()
        self.addCleanup(scene.close)
        r = scene.root
        _write(r, "launchd/com.spa.x.plist", "scripts/w.sh\n")
        _write(r, "scripts/w.sh", "python3 -m spa_core.monitoring.alpha\n")
        _write(r, "spa_core/monitoring/alpha.py", _SUBJECT)
        _write(r, "spa_core/monitoring/beta.py", _SUBJECT)
        blind = _write(r, ".github/workflows/blind.yml", "run: beta\n")
        os.chmod(blind, 0)
        self.addCleanup(lambda: os.chmod(blind, stat.S_IRUSR | stat.S_IWUSR))
        if os.access(blind, os.R_OK):
            self.skipTest("файл остался читаемым — предпосылка НЕ ОБЕСПЕЧЕНА")
        with self.assertRaises(rr.Unmeasured) as cm:
            rr.measure(r, min_subjects=2)
        self.assertIn("поверхности CI", str(cm.exception),
                      "причина обязана НАЗЫВАТЬ дверь, у которой отказало чтение")

    def test_the_cli_distinguishes_all_three_outcomes_by_exit_code(self):
        scene = _Scene()
        self.addCleanup(scene.close)
        r = scene.root
        _write(r, "launchd/com.spa.x.plist", "scripts/w.sh\n")
        _write(r, "scripts/w.sh", "python3 -m spa_core.monitoring.alpha\n")
        _write(r, "spa_core/monitoring/alpha.py", _SUBJECT)
        _write(r, "spa_core/monitoring/beta.py", _SUBJECT)
        _write(r, "scripts/w.sh", "python3 -m spa_core.monitoring.alpha\n"
                                  "python3 -m spa_core.monitoring.beta\n")
        self.assertEqual(
            rr.main(["--root", str(r), "--min-subjects", "2"]), 0,
            "каждый корень достижим ⇒ 0 (измерено и равно нулю)")
        _write(r, "spa_core/lib/dead.py", "beta\n")
        self.assertEqual(
            rr.main(["--root", str(r), "--min-subjects", "2"]), 1,
            "мёртвый объявленный корень есть ⇒ 1 (находка)")
        self.assertEqual(
            rr.main(["--root", str(r)]), 2,
            "поверхность тонкая ⇒ 2 (НЕ ИЗМЕРЕНО), а не 0")


class TheRuleHasOneCopyOnly(unittest.TestCase):
    """Отношение «упоминает» берётся у `_mention_wiring`, своей копии нет."""

    def test_the_instrument_defines_no_stripper_of_its_own(self):
        tree = ast.parse((_REPO / "spa_core/tests/_root_reachability.py")
                         .read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for forbidden in ("_code_only", "_without_test_paths", "has_entrypoint"):
            self.assertNotIn(forbidden, names,
                             "правило «что считается упоминанием» живёт у "
                             "храповика — вторая копия здесь запрещена")

    def test_the_subject_surface_is_taken_from_the_ratchet_not_relisted(self):
        self.assertIs(rr.MIN_SUBJECTS, mw.MIN_SUBJECTS)
        self.assertEqual(mw.WATCHED_DIRS,
                         mw._ratchet._DIRS,
                         "поверхность субъектов — у храповика")

    def test_the_nonempty_floor_default_is_still_fifty(self):
        """Урок #1165 п. 3: пол стал входом — УМОЛЧАНИЕ обязано остаться 50."""
        self.assertEqual(rr.MIN_SUBJECTS, 50)


class TheMultiSubstringFinderChangesPriceNotTheRelation(unittest.TestCase):
    """Aho — Corasick поставлен вместо наивного перебора ТОЛЬКО ради цены."""

    def test_it_agrees_with_naive_containment_on_random_input(self):
        rng = random.Random(4409)
        alpha = "abc_"
        words = sorted({"".join(rng.choice(alpha) for _ in range(rng.randint(1, 5)))
                        for _ in range(60)})
        finder = rr._Multi(words)
        for _ in range(400):
            text = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 40)))
            self.assertEqual(finder.found(text),
                             {w for w in words if w in text},
                             f"расхождение с подстрочным отношением на {text!r}")

    def test_the_empty_dictionary_finds_nothing_and_does_not_crash(self):
        self.assertEqual(rr._Multi([]).found("whatever"), set())


class OnTheLiveTree(unittest.TestCase):
    """Замер на живом дереве: пол ОБЯЗАН совпасть с населением ADR-1026."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.rep = rr.measure(_REPO)
            cls.mention = mw.measure(_REPO)
        except (rr.Unmeasured, mw.Unmeasured) as exc:
            raise unittest.SkipTest(
                f"предпосылка НЕ ОБЕСПЕЧЕНА на живом дереве: {exc}") from exc

    def test_the_floor_equals_the_population_measured_by_adr_1026(self):
        self.assertEqual(
            self.rep["population_floor"],
            sorted(i["module"] for i in self.mention["orphan_chain"]),
            "два читателя одного правила обязаны дать одно число")

    def test_the_ceiling_is_never_below_the_floor(self):
        self.assertLessEqual(len(self.rep["population_floor"]),
                             len(self.rep["population_ceiling"]),
                             "сужение набора корней не может ДОБАВИТЬ достижимости")

    def test_the_declared_roots_are_measured_and_the_dead_ones_all_have_a_kind(self):
        dead = self.rep["declared_roots_unreachable"]
        self.assertEqual(sum(self.rep["declared_roots_unreachable_by_kind"].values()),
                         len(dead))
        self.assertLessEqual(len(dead), self.rep["declared_roots"])

    def test_the_report_says_out_loud_that_it_is_a_bracket(self):
        self.assertTrue(self.rep["bracket_not_a_number"])
        self.assertTrue(self.rep["outside_roots"],
                        "корни-извне обязаны быть НАЗВАНЫ, а не подразумеваться")


if __name__ == "__main__":
    unittest.main()

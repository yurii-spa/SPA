"""Контроль переписи «названный каталог данных до читателя НЕ дошёл» (ADR-1108).

Устроено как у `test_deployment_acceptance.py`: **каждый тест — порванное звено**,
и каждое звено НАЗВАНО. Проба приёмки `named_data_dir_class_measurable`
регистрируется в реестре только вместе с этим файлом
(`.claude/rules/acceptance.md`, п. 3).

Отдельный класс тестов — ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ КАЛИБРОВКИ: пять форм, на которых
первая редакция прибора ошиблась В СТОРОНУ НАХОДКИ и объявила предметом приборы,
написанные честно. Мера, у которой ложных срабатываний больше, чем предмета, учит
дописывать в базу (урок ADR-1074), поэтому каждая такая форма закреплена сценой.

Сцены синтетические и одноразовые: живое дерево не читается, живой трекер не
трогается. Литеральных дат здесь нет — предмет прибора календаря не касается.
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _REPO_ROOT / "scripts" / "named_data_dir_census.py"


def _load_tool(path: Path = _TOOL):
    spec = importlib.util.spec_from_file_location("_ndc_under_test", str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AxisDistinguishes(unittest.TestCase):
    """Ось обязана различать ТРИ формы, а не отвечать «чисто» всегда."""

    def setUp(self) -> None:
        self.m = _load_tool()

    def test_a_member_is_found(self) -> None:
        r = self.m.classify_file(self.m.SCENE_MEMBER, path="<member>")
        self.assertEqual(r["verdict"], self.m.PARTIAL, r["reason"])

    def test_a_guarded_fallback_is_not_a_member(self) -> None:
        r = self.m.classify_file(self.m.SCENE_CLEAN, path="<clean>")
        self.assertEqual(r["verdict"], self.m.REACHES, r["reason"])

    def test_an_early_return_fallback_is_the_upper_bound_of_the_fork(self) -> None:
        """Ранний возврат — НЕ член и НЕ «чисто»: он верхняя граница вилки."""
        r = self.m.classify_file(self.m.SCENE_FALLBACK, path="<fallback>")
        self.assertEqual(r["verdict"], self.m.PARTIAL_WEAK, r["reason"])

    def test_the_self_check_itself_says_the_axis_discriminates(self) -> None:
        sc = self.m.self_check()
        self.assertTrue(sc["ok"], sc)
        self.assertEqual({sc["member"], sc["clean"], sc["fallback"]},
                         {self.m.PARTIAL, self.m.REACHES, self.m.PARTIAL_WEAK})


class CalibrationPositiveControls(unittest.TestCase):
    """Пять форм, на которых мера ошибалась в сторону находки. Каждая НАЗВАНА."""

    def setUp(self) -> None:
        self.m = _load_tool()

    def test_the_flags_own_default_is_not_a_read(self) -> None:
        """`default=str(_REPO_ROOT / "data")` — умолчание флага, а не чтение.

        Замер: так были объявлены предметом `evaluate_shadow_trigger`,
        `pin_identity_authority_census`, `artifact_edition`.
        """
        src = '''
import argparse
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(_REPO_ROOT / "data"))
    args = ap.parse_args()
    return 0 if (Path(args.data_dir) / "a.json").exists() else 1
'''
        r = self.m.classify_file(src, path="<flag-default>")
        self.assertNotIn(r["verdict"], (self.m.PARTIAL, self.m.PARTIAL_WEAK),
                         r["reason"])
        self.assertTrue(any(x["origin"] == self.m.FLAG_DEFAULT for x in r["reads"]),
                        r["reads"])

    def test_a_relative_literal_naming_an_artifact_is_not_a_read(self) -> None:
        """`{"nav": "data/portfolio_nav.json"}` — ИМЯ артефакта, не чтение.

        Замер: так были объявлены предметом `data_freshness_monitor._FILE_MAP` и
        `card_acceptance._LPC_ARTIFACT`.
        """
        src = '''
import argparse, json
from pathlib import Path

def resolve(rel, base):
    return Path(base) / rel[5:]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    json.loads(resolve("data/portfolio_nav.json", args.data_dir).read_text())
    return 0
'''
        r = self.m.classify_file(src, path="<artifact-name>")
        self.assertNotIn(r["verdict"], (self.m.PARTIAL, self.m.PARTIAL_WEAK),
                         r["reason"])
        self.assertFalse([x for x in r["reads"] if x["form"] == "relative_literal"],
                         r["reads"])

    def test_the_same_literal_opened_directly_IS_a_read(self) -> None:
        """Обратная половина: `open("data/x.json")` — именно чтение дерева запуска.

        Без этой сцены правило «литерал считается чтением только у открывателя»
        зелено и при мере, не считающей его НИКОГДА.
        """
        src = '''
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    with open("data/portfolio_nav.json") as fh:
        return 0 if fh.read() else 1
'''
        r = self.m.classify_file(src, path="<opened-literal>")
        self.assertEqual(r["verdict"], self.m.PARTIAL, r["reason"])

    def test_a_read_off_the_cli_path_is_another_statement(self) -> None:
        """Ступень моста `run(root=…)` — ДРУГОЙ вход с ДРУГИМ параметром.

        Замер: так были объявлены предметом `judge_alone_price.run` и
        `tree_lifetime_census.run`, чьи `main` разрешают каталог честно.
        """
        src = '''
import argparse
from pathlib import Path

def run(root=None):
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    return (base / "data" / "a.json").exists()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    return 0 if (Path(args.data_dir) / "a.json").exists() else 1
'''
        r = self.m.classify_file(src, path="<off-cli>")
        self.assertNotIn(r["verdict"], (self.m.PARTIAL, self.m.PARTIAL_WEAK),
                         r["reason"])
        self.assertTrue(any(x["origin"] == self.m.OFF_CLI_PATH for x in r["reads"]),
                        r["reads"])

    def test_an_interprocedural_guard_is_a_fallback(self) -> None:
        """`if args.data_dir: measure(...) else: run()` — запаска ПО ЗОВУ.

        Замер: так были объявлены предметом `adapter_repair_price`,
        `criterion_sign_price`, `move_cost_composition_price`,
        `swap_existence_price`.
        """
        src = '''
import argparse
from pathlib import Path

def measure(d):
    return (Path(d) / "a.json").exists()

def run():
    base = Path(__file__).resolve().parents[2]
    return measure(base / "data")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    return 0 if (measure(Path(args.data_dir)) if args.data_dir else run()) else 1
'''
        r = self.m.classify_file(src, path="<interprocedural>")
        self.assertEqual(r["verdict"], self.m.REACHES, r["reason"])

    def test_a_local_sandbox_root_is_not_the_module_tree(self) -> None:
        """Имя `root` ОДНОЙ функции не делает деревом модуля параметр ДРУГОЙ.

        Замер: так были объявлены предметом `decision_journal_coverage` и
        `decision_record_verdict_sensitivity`, читающие `root / "data"`
        одноразовой песочницы, которую сами же и создали.
        """
        src = '''
import argparse, tempfile
from pathlib import Path

def elsewhere():
    root = Path(__file__).resolve().parents[2]
    return root / "data"

def stage(root):
    (root / "data").mkdir(parents=True, exist_ok=True)
    return (root / "data" / "a.json").exists()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    sandbox = Path(tempfile.mkdtemp())
    return 0 if stage(sandbox / "base") and args.data_dir else 1
'''
        r = self.m.classify_file(src, path="<sandbox-root>")
        self.assertNotIn(r["verdict"], (self.m.PARTIAL, self.m.PARTIAL_WEAK),
                         r["reason"])
        self.assertFalse([x for x in r["reads"]
                          if x["origin"] == self.m.MODULE_ALWAYS], r["reads"])

    def test_a_module_level_definition_is_not_a_read(self) -> None:
        """`DEFAULT_DATA = ROOT / "data"` на уровне модуля — ОПРЕДЕЛЕНИЕ пути.

        Замер: так был объявлен предметом `edge_pt_fixed_vs_float`, у которого эта
        константа и есть умолчание флага. Использования константы судятся по месту.
        """
        src = '''
import argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    args = ap.parse_args()
    return 0 if (Path(args.data_dir) / "a.json").exists() else 1
'''
        r = self.m.classify_file(src, path="<module-definition>")
        self.assertNotIn(r["verdict"], (self.m.PARTIAL, self.m.PARTIAL_WEAK),
                         r["reason"])
        self.assertTrue(any(x["origin"] == self.m.MODULE_DEFINITION
                            for x in r["reads"]), r["reads"])

    def test_an_attribute_call_is_not_a_same_named_local_function(self) -> None:
        """`subprocess.run(...)` НЕ делает достижимой свою функцию `run`.

        Замер: именно так `tree_lifetime_census.run` оказался «на пути от CLI».
        """
        m = _load_tool()
        import ast
        tree = ast.parse('''
import subprocess
def run(root=None):
    pass
def helper():
    subprocess.run(["true"])
def main():
    helper()
''')
        reach, no_entry = m._cli_reach(tree, {"data_dir"}, m._parents(tree))
        self.assertEqual(no_entry, "")
        self.assertNotIn("run", reach or {})


class ThirdOutcomeIsNeverSilent(unittest.TestCase):
    """«НЕ ИЗМЕРЕНО» обязано быть отдельным значением с причиной (инв. #17)."""

    def setUp(self) -> None:
        self.m = _load_tool()

    def test_an_unparsable_file_is_unmeasured_with_a_reason(self) -> None:
        r = self.m.classify_file('def main(:\n', path="<broken>")
        self.assertEqual(r["verdict"], self.m.UNMEASURED)
        self.assertIn("не разобрался", r["reason"])

    def test_a_file_without_the_flag_is_outside_the_surface_and_says_so(self) -> None:
        r = self.m.classify_file('x = 1\n', path="<no-flag>")
        self.assertEqual(r["verdict"], self.m.UNMEASURED)
        self.assertIn("входом не объявлен", r["reason"])

    def test_a_missing_surface_directory_is_unmeasured_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rep = self.m.surface(Path(td))
            self.assertEqual(sorted(rep["missing_dirs"]),
                             sorted(list(self.m.SURFACE_DIRS)))
            self.assertEqual(rep["surface_total"], 0)

    def test_an_unresolved_root_is_unmeasured_not_a_member(self) -> None:
        src = '''
import argparse, os
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    return 0 if os.path.exists(os.path.join(whoever(), "data", "a.json")) else 1
'''
        r = self.m.classify_file(src, path="<unresolved>")
        self.assertEqual(r["verdict"], self.m.UNMEASURED, r["reason"])
        self.assertIn("неразрешимы", r["reason"])


class CliOutcomesAreDistinguishable(unittest.TestCase):
    """Коды возврата прибора: 0 пусто · 1 находка · 2 НЕ ИЗМЕРЕНО (инв. #17)."""

    def setUp(self) -> None:
        self.m = _load_tool()
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "spa_core" / "monitoring").mkdir(parents=True)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_an_empty_subject_returns_zero(self) -> None:
        (self.root / "scripts" / "honest.py").write_text(
            self.m.SCENE_CLEAN, encoding="utf-8")
        self.assertEqual(self.m.main(["--repo-root", str(self.root)]), 0)

    def test_a_found_member_returns_one(self) -> None:
        (self.root / "scripts" / "member.py").write_text(
            self.m.SCENE_MEMBER, encoding="utf-8")
        self.assertEqual(self.m.main(["--repo-root", str(self.root)]), 1)

    def test_an_unreadable_named_tree_returns_two(self) -> None:
        self.assertEqual(
            self.m.main(["--repo-root", str(self.root / "no-such-tree")]), 2)

    def test_a_missing_surface_directory_returns_two(self) -> None:
        shutil.rmtree(self.root / "spa_core")
        self.assertEqual(self.m.main(["--repo-root", str(self.root)]), 2)


class ProbeContour(unittest.TestCase):
    """Проба приёмки: зелена на целом контуре, красна на КАЖДОМ порванном звене."""

    def setUp(self) -> None:
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca
        self.assertIn("named_data_dir_class_measurable", ca.PROBES)
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "spa_core" / "monitoring").mkdir(parents=True)
        shutil.copyfile(_TOOL, self.root / "scripts" / "named_data_dir_census.py")

    def tearDown(self) -> None:
        self._td.cleanup()

    def _clean_tool(self) -> None:
        """Прибор в дереве + один честный прибор в поверхности."""
        (self.root / "scripts" / "honest.py").write_text(
            _load_tool().SCENE_CLEAN, encoding="utf-8")

    def test_the_whole_contour_is_satisfied(self) -> None:
        self._clean_tool()
        state, why = self.ca.run_probe("named_data_dir_class_measurable", repo_root=str(self.root))
        self.assertEqual(state, self.ca.SATISFIED, why)
        self.assertIn("ИЗМЕРЕНО", why)

    def test_a_real_member_in_the_tree_makes_it_not_satisfied(self) -> None:
        """Порванное звено: в поверхности есть прибор, читающий своё дерево."""
        self._clean_tool()
        (self.root / "spa_core" / "monitoring" / "member.py").write_text(
            _load_tool().SCENE_MEMBER, encoding="utf-8")
        state, why = self.ca.run_probe("named_data_dir_class_measurable", repo_root=str(self.root))
        self.assertEqual(state, self.ca.NOT_SATISFIED, why)
        self.assertIn("member.py", why)

    def test_a_missing_tool_is_unmeasured(self) -> None:
        """Порванное звено: прибора переписи в дереве нет."""
        (self.root / "scripts" / "named_data_dir_census.py").unlink()
        state, why = self.ca.run_probe("named_data_dir_class_measurable", repo_root=str(self.root))
        self.assertEqual(state, self.ca.UNMEASURED, why)
        self.assertIn("прибора переписи нет", why)

    def test_a_tool_without_the_doors_is_unmeasured(self) -> None:
        """Порванное звено: ПОДСТРОКОЙ проба не проходит (ADR-333).

        Файл называет все нужные слова в докстринге и не несёт ни одной двери.
        """
        (self.root / "scripts" / "named_data_dir_census.py").write_text(
            '"""self_check surface classify_file PARTIAL REACHES — только слова."""\n',
            encoding="utf-8")
        state, why = self.ca.run_probe("named_data_dir_class_measurable", repo_root=str(self.root))
        self.assertEqual(state, self.ca.UNMEASURED, why)
        self.assertIn("двери", why)

    def test_a_blind_axis_is_unmeasured_not_clean(self) -> None:
        """Порванное звено: самоконтроль говорит «не различаю»."""
        self._clean_tool()
        tool = self.root / "scripts" / "named_data_dir_census.py"
        src = tool.read_text(encoding="utf-8").replace(
            'return {"ok": ok,', 'return {"ok": False,')
        tool.write_text(src, encoding="utf-8")
        state, why = self.ca.run_probe("named_data_dir_class_measurable", repo_root=str(self.root))
        self.assertEqual(state, self.ca.UNMEASURED, why)
        self.assertIn("НЕ РАЗЛИЧАЕТ", why)

    def test_an_unreadable_surface_is_unmeasured_not_clean(self) -> None:
        """Порванное звено: каталога поверхности в дереве нет."""
        shutil.rmtree(self.root / "spa_core")
        state, why = self.ca.run_probe("named_data_dir_class_measurable", repo_root=str(self.root))
        self.assertEqual(state, self.ca.UNMEASURED, why)
        self.assertIn("поверхности не прочитан", why)

    def test_the_tree_is_an_input_and_the_door_is_declared(self) -> None:
        """Каталог дерева — ВХОД пробы, иначе она отвечает о дереве МОДУЛЯ."""
        self.assertIn("repo_root",
                      self.ca.probe_tree_inputs("named_data_dir_class_measurable"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

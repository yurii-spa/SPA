"""ADR-999 — читатели слепых точек входа класса «песочница без названного каталога данных»
и дверь второго члена (`decision_reproducibility`).

Что держат эти тесты:

* каждая форма вызывающего читается ОТДЕЛЬНОЙ сценой: plist, обёртка `.sh` (с `\\`-переносом),
  цепь plist → обёртка, argv-список `subprocess`, вызов в процессе (kwarg · позиционный · argv),
  реестр модулей, промпт; у каждой — положительный контроль («назвал») и отрицательный («полагается»);
* перечень путей — НЕ вызов (аварийная форма первого замера: `MEASURE_CARRIERS` читался вызывающим);
* импорт внутри функции виден только в ней (аварийная форма первого замера: `… as census` в десяти
  пробах `card_acceptance.py` приписывал любой `census.measure()` каждому из десяти);
* маркер меряется ПРИСВАИВАНИЕМ, слово в докстринге маркером не является;
* три исхода: неразобранный вызывающий ⇒ `UNMEASURED`/код 2, который НЕ прячет названный предмет;
  пустая поверхность и отсутствующая перепись ⇒ код 2; `UNCALLED` ⇒ код 1, а не «безвредно»;
* живое дерево: население названо, флот не зовёт слепых (измерено, не постулировано), член ADR-998
  (мост) — `DOOR` и зовёт `decision_reproducibility` с `root=`;
* дверь `decision_reproducibility`: маркер + прод-корень ⇒ код 2 ДО первого ребёнка, ни одного файла;
  чужой корень под маркером и прод без маркера — проходят; та же ЕДИНСТВЕННАЯ дверь `live_paths`.

Прод-`data/` не пишется ни одной сценой: «прод» — одноразовый каталог через подмену
`live_paths.DEFAULT_LIVE_ROOT`.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "sandbox_data_dir_census.py"
CALLERS_PATH = ROOT / "scripts" / "sandbox_data_dir_callers.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


census = _load(CENSUS_PATH, "spa_sandbox_data_dir_census")
callers = _load(CALLERS_PATH, "spa_sandbox_data_dir_callers")


# ─────────────────────────── сцены ───────────────────────────

BLIND_ENTRY = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
ROOT = Path(__file__).resolve().parents[2]

def run(root=None, write=True):
    root = Path(root) if root else ROOT
    if write:
        atomic_save({"ok": 1}, root / "data" / "x.json")
    return {"ok": 1}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    args = ap.parse_args(argv)
    run(root=args.root)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


class Scene:
    """Одноразовое дерево с ОДНОЙ слепой точкой входа `spa_core/monitoring/blind_entry.py`."""

    ENTRY_REL = "spa_core/monitoring/blind_entry.py"
    MODULE = "spa_core.monitoring.blind_entry"

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="sddc_callers_")
        self.repo = Path(self.tmp)
        for d in ("scripts", "spa_core/monitoring", "spa_core/analytics", "launchd", "docs"):
            (self.repo / d).mkdir(parents=True, exist_ok=True)
        self.write(self.ENTRY_REL, BLIND_ENTRY)

    def write(self, rel: str, text: str) -> Path:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def plist(self, name: str, args: list, env: dict | None = None) -> None:
        doc = {"Label": name, "ProgramArguments": args}
        if env:
            doc["EnvironmentVariables"] = env
        (self.repo / "launchd" / f"{name}.plist").write_bytes(plistlib.dumps(doc))

    def measure(self):
        return callers.measure(self.repo)

    def reader(self):
        c = self.measure()
        (r,) = [r for r in c.readers if r.path == self.ENTRY_REL]
        return c, r

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class _SceneCase(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.cleanup()


class TestCallerForms(_SceneCase):

    def test_no_caller_is_uncalled_and_a_finding(self):
        c, r = self.s.reader()
        self.assertEqual(r.verdict, "UNCALLED")
        self.assertEqual(c.code, 1, "рука получает умолчание — это предмет, а не «безвредно»")
        self.assertEqual(c.exposure["uncalled"], 1)

    def test_plist_naming_the_flag_is_named(self):
        self.s.plist("com.spa.x", ["/usr/bin/python3", "-m", self.s.MODULE, "--root", "/tmp/elsewhere"])
        c, r = self.s.reader()
        self.assertEqual(r.verdict, "NAMED_BY_ALL")
        self.assertEqual([(k.kind, k.names_dir, k.launchd) for k in r.callers], [("launchd_plist", True, True)])
        self.assertEqual(c.code, 0)

    def test_plist_without_the_flag_relies_on_the_default(self):
        self.s.plist("com.spa.x", ["/usr/bin/python3", "-m", self.s.MODULE, "--run"])
        c, r = self.s.reader()
        self.assertEqual(r.verdict, "DEFAULT_RELIED")
        self.assertEqual(c.exposure["relied_from_launchd_no_marker"], 1)
        self.assertEqual(c.code, 1)

    def test_plist_setting_the_marker_is_measured_as_marker_setter(self):
        self.s.plist("com.spa.x", ["/usr/bin/python3", "-m", self.s.MODULE], env={"SPA_SANDBOX": "1"})
        c, _r = self.s.reader()
        self.assertEqual(c.exposure["relied_by_marker_setter"], 1)

    def test_wrapper_with_continuation_line_and_plist_chain(self):
        self.s.write("scripts/agent_x.sh",
                     "#!/bin/bash\n# python3 -m spa_core.monitoring.blind_entry  (комментарий — не вызов)\n"
                     "exec /usr/bin/python3 \\\n  -m spa_core.monitoring.blind_entry \\\n  --root \"$ROOT\"\n")
        self.s.plist("com.spa.x", ["/bin/bash", str(self.s.repo / "scripts" / "agent_x.sh")])
        _c, r = self.s.reader()
        self.assertEqual([(k.kind, k.names_dir, k.launchd, k.line) for k in r.callers],
                         [("shell", True, True, 3)], "флаг на продолжении строки — та же команда")

    def test_wrapper_relying_on_default_without_plist_is_not_launchd(self):
        self.s.write("scripts/run_x.sh", "python3 -m spa_core.monitoring.blind_entry\n")
        c, r = self.s.reader()
        self.assertEqual(r.verdict, "DEFAULT_RELIED")
        self.assertFalse(r.callers[0].launchd)
        self.assertEqual(c.exposure["relied_other"], 1)

    def test_shell_marker_is_an_assignment_not_a_comment(self):
        self.s.write("scripts/a.sh", "# SPA_SANDBOX=1 было бы маркером\npython3 -m spa_core.monitoring.blind_entry\n")
        self.s.write("scripts/b.sh", "export SPA_SANDBOX=1\npython3 -m spa_core.monitoring.blind_entry\n")
        _c, r = self.s.reader()
        by_file = {k.file: k.sets_marker for k in r.callers}
        self.assertEqual(by_file, {"scripts/a.sh": False, "scripts/b.sh": True})

    def test_python_argv_with_and_without_the_flag(self):
        self.s.write("scripts/caller_a.py",
                     "import subprocess, sys\n"
                     "subprocess.run([sys.executable, '-m', 'spa_core.monitoring.blind_entry', '--root', '/x'])\n")
        self.s.write("scripts/caller_b.py",
                     "import subprocess, sys\n"
                     "cmd = [sys.executable, '-m', 'spa_core.monitoring.blind_entry']\nsubprocess.run(cmd)\n")
        _c, r = self.s.reader()
        got = sorted((k.file, k.kind, k.names_dir) for k in r.callers)
        self.assertEqual(got, [("scripts/caller_a.py", "python_argv", True),
                               ("scripts/caller_b.py", "python_argv", False)])

    def test_a_list_of_paths_is_not_a_call(self):
        """Аварийная форма первого замера: `MEASURE_CARRIERS = ("spa_core/…/x.py", …)` читался вызывающим."""
        self.s.write("spa_core/monitoring/carriers.py",
                     "CARRIERS = ('spa_core/monitoring/blind_entry.py', 'scripts/other.py')\n")
        _c, r = self.s.reader()
        self.assertEqual(r.verdict, "UNCALLED")

    def test_inprocess_kwarg_positional_and_argv(self):
        self.s.write("spa_core/monitoring/a.py",
                     "from spa_core.monitoring import blind_entry\n"
                     "def go(root):\n    return blind_entry.run(root=root)\n")
        self.s.write("spa_core/monitoring/b.py",
                     "import spa_core.monitoring.blind_entry as be\n"
                     "def go(d):\n    return be.run(d)\n")
        self.s.write("spa_core/monitoring/c.py",
                     "from spa_core.monitoring import blind_entry\n"
                     "def go():\n    return blind_entry.main(['--root', '/x'])\n")
        self.s.write("spa_core/monitoring/d.py",
                     "from spa_core.monitoring import blind_entry\n"
                     "def go():\n    return blind_entry.run(write=False)\n")
        _c, r = self.s.reader()
        got = {k.file: (k.names_dir, k.how) for k in r.callers}
        self.assertEqual(got, {"spa_core/monitoring/a.py": (True, "kwarg"),
                               "spa_core/monitoring/b.py": (True, "positional"),
                               "spa_core/monitoring/c.py": (True, "flag"),
                               "spa_core/monitoring/d.py": (False, None)})
        self.assertEqual(r.verdict, "DEFAULT_RELIED")

    def test_function_level_import_is_visible_only_inside_its_function(self):
        """Аварийная форма первого замера: `… as census` в десяти пробах приписывал каждому из них все вызовы."""
        self.s.write("spa_core/monitoring/other_census.py", BLIND_ENTRY)
        self.s.write("spa_core/monitoring/probes.py",
                     "def probe_a():\n    from spa_core.monitoring import blind_entry as census\n"
                     "    return census.run(root='/a')\n"
                     "def probe_b():\n    from spa_core.monitoring import other_census as census\n"
                     "    return census.run()\n")
        _c, r = self.s.reader()
        self.assertEqual([(k.line, k.names_dir) for k in r.callers], [(3, True)],
                         "вызов из probe_b принадлежит other_census, а не blind_entry")

    def test_function_name_imported_from_two_modules_belongs_to_nobody(self):
        self.s.write("spa_core/monitoring/other_census.py", BLIND_ENTRY)
        self.s.write("spa_core/monitoring/both.py",
                     "from spa_core.monitoring.blind_entry import run\n"
                     "from spa_core.monitoring.other_census import run\n"
                     "def go():\n    return run()\n")
        _c, r = self.s.reader()
        self.assertEqual(r.verdict, "UNCALLED", "двусмысленное имя не приписывается — ошибка в сторону находки")

    def test_registry_entry_is_a_relying_caller(self):
        self.s.write("spa_core/analytics/_module_registry.py",
                     "TIER_B = [\n    {\"module\": 'blind_entry', \"class\": None, \"tier\": 'B'},\n]\n")
        c, r = self.s.reader()
        self.assertEqual([(k.kind, k.names_dir, k.launchd) for k in r.callers], [("registry", False, None)])
        self.assertEqual(c.exposure["relied_via_registry"], 1)

    def test_prompt_lines_are_hand_callers(self):
        self.s.write("docs/ORCHESTRATOR_PROTOCOL.md",
                     "шаг: python3 -m spa_core.monitoring.blind_entry --root <прод>\n"
                     "шаг: python3 -m spa_core.monitoring.blind_entry\n")
        c, r = self.s.reader()
        self.assertEqual(sorted((k.kind, k.names_dir) for k in r.callers), [("prompt", False), ("prompt", True)])
        self.assertEqual(c.exposure["relied_by_prompt_or_hand"], 1)

    def test_the_orchestrator_wrapper_is_a_prompt_not_a_shell_caller(self):
        """Строка промпта лежит в `.sh`, но исполняет её СЕССИЯ руками — это рука, не обёртка флота."""
        self.s.write("scripts/agent_orchestrator.sh",
                     "PROMPT='шаг: python3 -m spa_core.monitoring.blind_entry'\n")
        c, r = self.s.reader()
        self.assertEqual([(k.kind, k.names_dir) for k in r.callers], [("prompt", False)])
        self.assertEqual(c.exposure["relied_by_prompt_or_hand"], 1)
        self.assertEqual(c.exposure["relied_other"], 0)

    def test_py_marker_is_an_assignment_not_a_docstring(self):
        self.s.write("spa_core/monitoring/talks.py",
                     '"""Тут слово SPA_SANDBOX=1 — только слово."""\n'
                     "from spa_core.monitoring import blind_entry\n"
                     "def go():\n    return blind_entry.run()\n")
        self.s.write("spa_core/monitoring/sets.py",
                     "import os\nfrom spa_core.monitoring import blind_entry\n"
                     "def go():\n    env = dict(os.environ)\n    env['SPA_SANDBOX'] = '1'\n    return blind_entry.run()\n")
        _c, r = self.s.reader()
        self.assertEqual({k.file: k.sets_marker for k in r.callers},
                         {"spa_core/monitoring/talks.py": False, "spa_core/monitoring/sets.py": True})

    def test_caller_verdict_is_the_census_verdict_of_the_caller(self):
        self.s.write("spa_core/monitoring/door_caller.py",
                     "import argparse\nfrom pathlib import Path\n"
                     "from spa_core.utils.live_paths import assert_not_prod_realpath\n"
                     "from spa_core.monitoring import blind_entry\n"
                     "def main(argv=None):\n    ap = argparse.ArgumentParser()\n"
                     "    ap.add_argument('--root', default='.')\n    a = ap.parse_args(argv)\n"
                     "    assert_not_prod_realpath(Path(a.root) / 'data', who='x')\n"
                     "    blind_entry.run(root=a.root)\n")
        _c, r = self.s.reader()
        self.assertEqual([(k.caller_verdict, k.names_dir) for k in r.callers], [("DOOR", True)])


class TestThreeOutcomes(_SceneCase):

    def test_unparsable_caller_is_unmeasured_and_does_not_hide_a_finding(self):
        self.s.write("scripts/broken.py", "def (:\n  blind_entry\n")
        c, r = self.s.reader()
        self.assertEqual(c.code, 1, "UNCALLED назван — неразобранный файл его не прячет")
        self.assertEqual(r.verdict, "UNCALLED")
        self.assertTrue(c.unmeasured_files and "scripts/broken.py" in c.unmeasured_files[0])

    def test_unparsable_caller_turns_named_by_all_into_unmeasured_code_2(self):
        self.s.plist("com.spa.x", ["/usr/bin/python3", "-m", self.s.MODULE, "--root", "/x"])
        self.s.write("scripts/broken.py", "def (:\n  blind_entry\n")
        c, r = self.s.reader()
        self.assertEqual(r.verdict, "UNMEASURED")
        self.assertEqual(c.code, 2)
        self.assertIn("не разобрана", c.unmeasured_reason)

    def test_missing_census_is_not_measured(self):
        with self.assertRaises(callers.NotMeasured):
            callers.load_census_module(self.s.repo / "nope.py")

    def test_cli_codes_json_and_default_tree_printed(self):
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = callers.main(["--repo-root", str(self.s.repo), "--json"])
        self.assertEqual(rc, 1)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["counts"], {"UNCALLED": 1})
        self.assertEqual(err.getvalue(), "", "названное дерево не печатается как умолчание")

    def test_census_cli_with_callers_combines_codes(self):
        """Перепись одна (код 1: слепой назван), читатели НЕ ИЗМЕРЕНЫ (код 2) ⇒ общий код 2, не 1."""
        self.s.plist("com.spa.x", ["/usr/bin/python3", "-m", self.s.MODULE, "--root", "/x"])
        self.s.write("scripts/broken.py", "def (:\n  blind_entry\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = census.main(["--repo-root", str(self.s.repo), "--callers", "--json"])
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["code"], 1)
        self.assertEqual(doc["callers"]["code"], 2)
        self.assertEqual(rc, 2, "общий код — максимум из двух, «не измерено» не прячется за «названо»")
        self.assertEqual(doc["callers"]["counts"], {"UNMEASURED": 1})

    def test_render_names_the_subject(self):
        c = self.s.measure()
        text = callers.render(c)
        self.assertIn("UNCALLED        1", text)
        self.assertIn("предмет НАЗВАН", text)


class TestTheLiveTree(unittest.TestCase):
    """Один замер на класс: живое дерево — ~22 с."""

    @classmethod
    def setUpClass(cls):
        cls.c = callers.measure(ROOT)
        cls.by_path = {r.path: r for r in cls.c.readers}

    def test_population_is_named_and_measured(self):
        self.assertGreater(len(self.c.readers), 100)
        self.assertEqual(self.c.unmeasured_files, [])
        for k in ("NAMED_BY_ALL", "DEFAULT_RELIED", "UNCALLED"):
            self.assertIn(k, self.c.counts)
        self.assertEqual(self.c.code, 1)

    def test_the_fleet_does_not_call_a_blind_entrypoint(self):
        """Решение ADR-999 § 3 стоит на этом замере: у двери в `main` НЕТ радиуса на флоте."""
        self.assertEqual(self.c.exposure["relied_from_launchd_no_marker"], 0)
        self.assertNotIn("launchd_plist", self.c.caller_kinds)
        self.assertNotIn("shell", self.c.caller_kinds)

    def test_the_bridge_names_the_root_of_its_stages(self):
        """Ступени моста слепы, но их `root=` раздаёт мост — а он `DOOR` (ADR-998): умолчание ступени не исполняется."""
        bridge = [(r.path, k) for r in self.c.readers for k in r.callers
                  if k.file == "spa_core/monitoring/findings_bridge.py" and k.kind == "inprocess"]
        self.assertGreater(len(bridge), 5, "мост зовёт больше пяти слепых ступеней")
        for path, k in bridge:
            self.assertTrue(k.names_dir and k.how == "kwarg" and k.caller_verdict == "DOOR", (path, k))

    def test_the_second_member_left_the_blind_population(self):
        self.assertNotIn("spa_core/monitoring/decision_reproducibility.py", self.by_path,
                         "ADR-999: у второго члена теперь дверь — перепись читает его DOOR, не MARKER_BLIND")

    def test_registry_is_the_largest_relying_form(self):
        self.assertGreater(self.c.caller_kinds["registry"]["relying"], 50)
        self.assertEqual(self.c.caller_kinds["registry"]["named"], 0)


class TestDecisionReproducibilityGuard(unittest.TestCase):
    """Дверь второго члена на НАСТОЯЩЕЙ `live_paths`: прод сцены — одноразовый каталог."""

    def setUp(self):
        from spa_core.utils import live_paths
        from spa_core.monitoring import decision_reproducibility
        self.lp, self.dr = live_paths, decision_reproducibility
        self._tmp = tempfile.TemporaryDirectory(prefix="sddc_dr_guard_")
        self.prod = Path(self._tmp.name) / "prod"
        (self.prod / "data").mkdir(parents=True)
        self.other = Path(self._tmp.name) / "other"
        (self.other / "data").mkdir(parents=True)
        self._saved_root = live_paths.DEFAULT_LIVE_ROOT
        live_paths.DEFAULT_LIVE_ROOT = self.prod
        self._env = {k: os.environ.get(k) for k in ("SPA_SANDBOX", "SPA_STAMP_TREE")}
        os.environ.pop("SPA_SANDBOX", None)
        os.environ.pop("SPA_STAMP_TREE", None)

    def tearDown(self):
        self.lp.DEFAULT_LIVE_ROOT = self._saved_root
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_marker_and_prod_root_refuses_with_code_2_before_any_child(self):
        os.environ["SPA_SANDBOX"] = "1"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = self.dr._main(["--root", str(self.prod), "--runs", "1"])
        self.assertEqual(rc, 2)
        self.assertEqual(sorted((self.prod / "data").iterdir()), [], "ни одного файла в data/")
        self.assertIn("ОТКАЗ (код 2)", err.getvalue())
        self.assertIn("SPA_SANDBOX", err.getvalue())

    def test_marker_and_a_foreign_root_is_allowed(self):
        os.environ["SPA_SANDBOX"] = "1"
        self.assertIsNone(self.dr.sandbox_leak_reason(str(self.other)))

    def test_no_marker_and_prod_root_is_allowed(self):
        """Бегун `decision_loop` маркера не ставит — его эта дверь не видит вовсе."""
        self.assertIsNone(self.dr.sandbox_leak_reason(str(self.prod)))

    def test_marker_and_a_child_of_prod_is_refused(self):
        os.environ["SPA_SANDBOX"] = "1"
        nested = self.prod / "sub"
        (nested / "data").mkdir(parents=True)
        self.assertIsNotNone(self.dr.sandbox_leak_reason(str(nested)))

    def test_the_door_is_the_single_live_paths_door(self):
        """Своей копии проверки у члена нет: подмена единственной двери меняет ответ."""
        os.environ["SPA_SANDBOX"] = "1"
        saved = self.lp.assert_not_prod_realpath
        calls = []

        def spy(path, *, who):
            calls.append((Path(path), who))
            return saved(path, who=who)

        self.lp.assert_not_prod_realpath = spy
        try:
            self.assertIsNotNone(self.dr.sandbox_leak_reason(str(self.prod)))
        finally:
            self.lp.assert_not_prod_realpath = saved
        self.assertEqual(calls, [(self.prod / "data", "decision_reproducibility")])

    def test_the_live_member_reads_door_in_the_census(self):
        c = census.measure(ROOT, ("spa_core/monitoring",))
        (e,) = [e for e in c.entries if e.path == "spa_core/monitoring/decision_reproducibility.py"]
        self.assertEqual(e.verdict, "DOOR", e)
        self.assertIn("sandbox_leak_reason", e.doors)


if __name__ == "__main__":
    unittest.main()

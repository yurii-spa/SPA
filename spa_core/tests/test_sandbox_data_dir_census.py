"""Перепись «песочница без названного каталога данных» и дверь моста — ADR-998.

Класс (ADR-996 § 2.1): 03.11 01:05Z сэмплер под `SPA_SANDBOX=1` без `--root`/`SPA_DATA_DIR`
положил 11 файлов в прод-`data/` через `findings_bridge --run`. Маркер защищал трекер
(`live_paths`), корень ступеней брался из аргумента с умолчанием «дерево модуля», и дверь
к маркеру у него отсутствовала.

Что здесь проверяется, и КАЖДОЕ — по исходу, не по подстроке:

* перепись различает шесть вердиктов на одноразовых сценах и три кода возврата (шестой —
  `DEAD_MODULE`, ADR-1001: надгробие с `raise` первой исполняемой инструкцией — не слепое и не
  «не измерено», читателей у него не ищут; контроль рода: raise после импорта / внутри `main` — не надгробие);
* дверь судится ДОСТИЖИМОСТЬЮ от входа (половина инъекции — урок ADR-932): функция
  двери в файле без проводки от `main` ⇒ `MARKER_BLIND`, дверь в комментарии ⇒
  `MARKER_BLIND`;
* умолчание прослеживается через обёртки (`str(ROOT / "data")`) и один хоп импорта;
* член класса — НАСТОЯЩИЙ мост: с проводкой `DOOR`, без одной строки проводки
  `MARKER_BLIND`;
* дверь моста на настоящей `live_paths`: маркер + корень в «проде» ⇒ код 2 и НОЛЬ файлов;
  маркер + чужой корень ⇒ идёт; без маркера ⇒ идёт (прод-бегун не задет);
* проба `sandbox_data_dir_class_population_named` зарегистрирована, на живом дереве
  `satisfied`, на дереве без проводки `not_satisfied`, при подстроке в комментарии
  `not_satisfied`, при снятой переписи `not_satisfied`, с аргументом `unmeasured`.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "sandbox_data_dir_census.py"
MEMBER_REL = "spa_core/monitoring/findings_bridge.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


census = _load(CENSUS_PATH, "spa_sandbox_data_dir_census")


# ─────────────────────────── сцены ───────────────────────────

BLIND_CONSTANT = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
ROOT = Path(__file__).resolve().parents[2]

def run(root):
    atomic_save(Path(root) / "data" / "x.json", {"a": 1})

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    run(args.root)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

DOOR_REACHED = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
from spa_core.utils.live_paths import live_data_dir
ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args(argv)
    target = live_data_dir(Path(args.data_dir).parent)
    atomic_save(target / "x.json", {"a": 1})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

DOOR_UNREACHED = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
from spa_core.utils.live_paths import assert_not_prod_realpath
ROOT = Path(__file__).resolve().parents[2]

def guard(root):
    assert_not_prod_realpath(Path(root) / "data", who="scene")

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    atomic_save(Path(args.root) / "data" / "x.json", {"a": 1})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

DOOR_IN_COMMENT = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    """Здесь мог бы быть вызов assert_not_prod_realpath(...), но его нет."""
    ap = argparse.ArgumentParser()
    # live_data_dir() спросить забыли — SPA_SANDBOX не читается
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    atomic_save(Path(args.root) / "data" / "x.json", {"a": 1})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

EXPLICIT_ONLY = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)
    atomic_save(Path(args.data_dir) / "x.json", {"a": 1})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

READER_ONLY = '''
import argparse
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    print(json.loads((Path(args.root) / "data" / "x.json").read_text()))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

FALLBACK_OR = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    args = ap.parse_args(argv)
    data = Path(args.data_dir or ROOT / "data")
    atomic_save(data / "x.json", {"a": 1})
    return 0
'''

FALLBACK_IF = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    if args.root is None:
        root = ROOT
    else:
        root = Path(args.root)
    atomic_save(root / "data" / "x.json", {"a": 1})
    return 0
'''

DELEGATES_ROOT = '''
import argparse
from spa_core.monitoring import house_view_gap
REPO_ROOT = __file__.rsplit("/", 3)[0]

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)
    house_view_gap.run(root=args.root)
    return 0
'''

IMPORTED_DEFAULT = '''
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
from spa_core.monitoring.scene_roots import REPO_ROOT

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)
    atomic_save(Path(args.root) / "data" / "x.json", {"a": 1})
    return 0
'''

SCENE_ROOTS = '''
import os
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
'''

NO_FLAG = '''
import argparse
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    return 0
'''

BROKEN = "def main(:\n    pass\n"

# ADR-1001: надгробие — первая ИСПОЛНЯЕМАЯ инструкция `raise`; argparse ниже не исполняется никогда.
# Форма дословно повторяет снятый `spa_core/analytics/cycle_health_monitor.py` (комментарии, raise,
# докстринг ПОСЛЕ raise, затем полноценная точка входа с флагом каталога и записью).
DEAD_TOMBSTONE = '''
# DEPRECATED — orphaned module. Canonical: spa_core.monitoring.x
raise ImportError(
    "DEPRECATED: use spa_core.monitoring.x instead"
)

"""Docstring that is NOT first — the raise is."""
import argparse
from pathlib import Path
from spa_core.utils.atomic import atomic_save
ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args(argv)
    atomic_save(Path(args.data_dir) / "x.json", {"a": 1})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

# Контроль рода: докстринг ПЕРЕД raise — всё ещё надгробие (строка не исполнение).
DEAD_AFTER_DOCSTRING = '"""Module docstring first."""\n' + DEAD_TOMBSTONE.lstrip("\n")

# Контроль рода: raise ПОСЛЕ импорта — НЕ надгробие (модуль уже что-то исполнил; main может быть
# достижим в другой ветке), судится как обычная точка входа — здесь MARKER_BLIND.
RAISE_AFTER_IMPORT = DEAD_TOMBSTONE.replace(
    '# DEPRECATED — orphaned module. Canonical: spa_core.monitoring.x\nraise ImportError(',
    'import os\nraise ImportError(', 1).replace(
    '    "DEPRECATED: use spa_core.monitoring.x instead"\n)',
    '    "DEPRECATED: use spa_core.monitoring.x instead"\n) if os.environ.get("NEVER_SET_x") else None', 1)

# Контроль рода: raise внутри main — не надгробие.
RAISE_INSIDE_MAIN = BLIND_CONSTANT.replace("    run(args.root)\n", "    raise RuntimeError('x')\n    run(args.root)\n", 1)


def _scene(tmp: Path, files: dict[str, str]) -> Path:
    for sub in census.SURFACE_DIRS:
        (tmp / sub).mkdir(parents=True, exist_ok=True)
    for rel, src in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    return tmp


def _entry(c, rel: str):
    return next((e for e in c.entries if e.path == rel), None)


class TestVerdictsOnScenes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sddc_")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_constant_default_with_a_write_is_marker_blind(self):
        c = census.measure(_scene(self.tmp, {"scripts/a.py": BLIND_CONSTANT}))
        e = _entry(c, "scripts/a.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertEqual(e.default_kind, "constant")
        self.assertEqual(e.default_origin, "module_tree",
                         "str(ROOT) обязан прослеживаться через обёртку к __file__")
        self.assertIn("atomic_save", e.writes)
        self.assertEqual(c.code, 1)

    def test_a_reached_door_is_door(self):
        c = census.measure(_scene(self.tmp, {"spa_core/monitoring/b.py": DOOR_REACHED}))
        e = _entry(c, "spa_core/monitoring/b.py")
        self.assertEqual(e.verdict, "DOOR")
        self.assertIn("live_data_dir", e.doors)
        self.assertEqual(c.code, 0)

    def test_a_door_defined_but_unreached_from_main_is_blind(self):
        """Половина инъекции (ADR-932): функция двери есть, проводки от входа нет."""
        c = census.measure(_scene(self.tmp, {"spa_core/monitoring/c.py": DOOR_UNREACHED}))
        e = _entry(c, "spa_core/monitoring/c.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertTrue(e.door_unreached)
        self.assertTrue(e.door_imported)

    def test_a_door_named_only_in_prose_is_blind(self):
        """Подстрокой перепись не проходит (ADR-333)."""
        c = census.measure(_scene(self.tmp, {"spa_core/monitoring/d.py": DOOR_IN_COMMENT}))
        e = _entry(c, "spa_core/monitoring/d.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertFalse(e.door_unreached)
        self.assertEqual(e.doors, [])

    def test_no_default_and_no_fallback_is_explicit_only(self):
        c = census.measure(_scene(self.tmp, {"scripts/e.py": EXPLICIT_ONLY}))
        e = _entry(c, "scripts/e.py")
        self.assertEqual(e.verdict, "EXPLICIT_ONLY")
        self.assertEqual(e.default_kind, "none")

    def test_a_reader_is_outside_the_subject(self):
        c = census.measure(_scene(self.tmp, {"scripts/f.py": READER_ONLY}))
        e = _entry(c, "scripts/f.py")
        self.assertEqual(e.verdict, "READER")
        self.assertEqual(e.writes, [])

    def test_fallback_or_form_is_a_default(self):
        c = census.measure(_scene(self.tmp, {"scripts/g.py": FALLBACK_OR}))
        e = _entry(c, "scripts/g.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertEqual(e.default_kind, "fallback")
        self.assertEqual(e.default_origin, "module_tree")

    def test_fallback_if_is_none_form_is_a_default(self):
        c = census.measure(_scene(self.tmp, {"scripts/h.py": FALLBACK_IF}))
        e = _entry(c, "scripts/h.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertEqual(e.default_kind, "fallback")
        self.assertEqual(e.default, "ROOT")

    def test_delegating_root_to_stages_counts_as_writing(self):
        """Форма моста: сам не пишет, раздаёт `root=` ступеням."""
        c = census.measure(_scene(self.tmp, {"spa_core/monitoring/i.py": DELEGATES_ROOT}))
        e = _entry(c, "spa_core/monitoring/i.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertTrue(e.delegates_root)
        self.assertEqual(e.writes, [])

    def test_imported_default_is_resolved_one_hop(self):
        c = census.measure(_scene(self.tmp, {
            "spa_core/monitoring/j.py": IMPORTED_DEFAULT,
            "spa_core/monitoring/scene_roots.py": SCENE_ROOTS}))
        e = _entry(c, "spa_core/monitoring/j.py")
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertEqual(e.default_origin, "module_tree")

    def test_a_file_without_the_flag_is_not_in_the_surface(self):
        c = census.measure(_scene(self.tmp, {"scripts/k.py": NO_FLAG,
                                             "scripts/a.py": BLIND_CONSTANT}))
        self.assertIsNone(_entry(c, "scripts/k.py"))
        self.assertEqual(len(c.entries), 1)

    def test_test_files_are_skipped(self):
        c = census.measure(_scene(self.tmp, {"scripts/test_a.py": BLIND_CONSTANT,
                                             "scripts/a.py": READER_ONLY}))
        self.assertIsNone(_entry(c, "scripts/test_a.py"))


class TestDeadModuleKind(unittest.TestCase):
    """ADR-1001: надгробие — отдельный род, не `UNCALLED` и не `MARKER_BLIND`.

    ADR-1000 § 4 держал остаток «один мёртвый модуль» ПОИМЁННО, потому что перепись его не
    различала: файл с флагом каталога и записью читался `MARKER_BLIND`, прибор читателей — `UNCALLED`
    («зовут руками, умолчание достижимо»), что про надгробие ложь: его `main` не достигает ничто.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sddc_dead_")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_tombstone_is_dead_module_not_blind_and_not_a_finding(self):
        c = census.measure(_scene(self.tmp, {"spa_core/analytics/dead.py": DEAD_TOMBSTONE}))
        e = _entry(c, "spa_core/analytics/dead.py")
        self.assertEqual(e.verdict, "DEAD_MODULE")
        self.assertEqual(e.flag, "--data-dir", "флаг назван — модуль В поверхности, а не вне её")
        self.assertIn("raise", e.reason)
        self.assertEqual(c.counts, {"DEAD_MODULE": 1})
        self.assertEqual([x.path for x in c.dead], ["spa_core/analytics/dead.py"])
        self.assertEqual(c.blind, [], "надгробие не слепое — дверь ему не положена")
        self.assertEqual(c.code, 0, "мёртвый модуль — не предмет класса и не «не измерено»")
        self.assertIn("МЁРТВЫЙ МОДУЛЬ spa_core/analytics/dead.py", census.render(c))

    def test_a_docstring_before_the_raise_is_still_a_tombstone(self):
        c = census.measure(_scene(self.tmp, {"spa_core/analytics/dead2.py": DEAD_AFTER_DOCSTRING}))
        self.assertEqual(_entry(c, "spa_core/analytics/dead2.py").verdict, "DEAD_MODULE")

    def test_a_raise_after_an_import_is_not_a_tombstone(self):
        """Исполнение до raise — модуль жив (его `main` может быть достижим): судится как точка входа."""
        c = census.measure(_scene(self.tmp, {"spa_core/analytics/alive.py": RAISE_AFTER_IMPORT}))
        self.assertEqual(_entry(c, "spa_core/analytics/alive.py").verdict, "MARKER_BLIND")
        self.assertEqual(c.dead, [])

    def test_a_raise_inside_main_is_not_a_tombstone(self):
        c = census.measure(_scene(self.tmp, {"scripts/alive2.py": RAISE_INSIDE_MAIN}))
        self.assertEqual(_entry(c, "scripts/alive2.py").verdict, "MARKER_BLIND")

    def test_readers_are_not_sought_for_a_tombstone(self):
        """Прибор читателей (ADR-999) строит поверхность из СЛЕПЫХ точек — надгробия в ней нет,
        поэтому `UNCALLED` у него про надгробие не бывает: остаток — ноль, не список."""
        callers = _load(ROOT / "scripts" / "sandbox_data_dir_callers.py", "spa_sddc_callers_for_dead")
        c = census.measure(_scene(self.tmp, {"spa_core/analytics/dead.py": DEAD_TOMBSTONE,
                                             "scripts/blind.py": BLIND_CONSTANT}))
        cc = callers.measure(self.tmp, census=c)
        self.assertEqual(sorted(r.path for r in cc.readers), ["scripts/blind.py"])
        self.assertEqual(cc.exposure["uncalled"], 1, "живая слепая точка без вызывающего — остаётся UNCALLED")

    def test_the_live_tree_holds_no_tombstone_with_a_data_flag(self):
        """Исход заказа G989 п. 1а: `spa_core/analytics/cycle_health_monitor.py` снят ADR-1001."""
        c = census.measure(ROOT)
        self.assertEqual([e.path for e in c.dead], [])
        self.assertFalse((ROOT / "spa_core/analytics/cycle_health_monitor.py").exists())


class TestThreeOutcomes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sddc3_")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unparsable_file_is_unmeasured_and_blocks_a_clean_verdict(self):
        c = census.measure(_scene(self.tmp, {"scripts/z.py": BROKEN,
                                             "scripts/f.py": READER_ONLY}))
        e = _entry(c, "scripts/z.py")
        self.assertEqual(e.verdict, "UNMEASURED")
        self.assertIn("не разобран", e.reason)
        self.assertEqual(c.code, 2, "«предмет пуст» при неизмеренном файле — вакуум")

    def test_unmeasured_does_not_hide_a_named_subject(self):
        c = census.measure(_scene(self.tmp, {"scripts/z.py": BROKEN,
                                             "scripts/a.py": BLIND_CONSTANT}))
        self.assertEqual(c.code, 1)
        self.assertEqual(len(c.unmeasured), 1)

    def test_empty_surface_is_unmeasured(self):
        c = census.measure(_scene(self.tmp, {}))
        self.assertEqual(c.code, 2)
        self.assertIn("ПУСТА", c.unmeasured_reason)

    def test_missing_surface_dir_refuses(self):
        (self.tmp / "scripts").mkdir()
        with self.assertRaises(census.NotMeasured):
            census.measure(self.tmp)

    def test_cli_codes_and_json(self):
        _scene(self.tmp, {"scripts/a.py": BLIND_CONSTANT})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = census.main(["--repo-root", str(self.tmp), "--json"])
        doc = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(doc["counts"]["MARKER_BLIND"], 1)
        self.assertEqual(doc["entries"][0]["path"], "scripts/a.py")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(census.main(["--repo-root", str(self.tmp / "nope")]), 2)

    def test_unnamed_tree_is_printed(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            census.main(["--subtree", "scripts", "--json"])
        self.assertIn("дерево не названо", err.getvalue())

    def test_render_names_the_subject_and_the_half_injection(self):
        c = census.measure(_scene(self.tmp, {"spa_core/monitoring/c.py": DOOR_UNREACHED}))
        text = census.render(c)
        self.assertIn("ПРЕДМЕТ КЛАССА НАЗВАН (1)", text)
        self.assertIn("половина инъекции", text)


class TestTheRealMember(unittest.TestCase):
    """Член класса — настоящий мост, а не выдуманная сцена."""

    def test_the_live_bridge_is_door(self):
        c = census.measure(ROOT, ("spa_core/monitoring",))
        e = _entry(c, MEMBER_REL)
        self.assertIsNotNone(e, "мост обязан быть в поверхности переписи")
        self.assertEqual(e.verdict, "DOOR")
        self.assertIn("sandbox_leak_reason", e.doors)
        self.assertTrue(e.delegates_root, "мост раздаёт root= ступеням — это и есть форма аварии")

    def test_the_bridge_without_the_one_wiring_line_is_blind(self):
        from spa_core.monitoring import card_acceptance as ca
        src = (ROOT / MEMBER_REL).read_text(encoding="utf-8")
        self.assertIn(ca._SANDBOX_CLASS_DOOR_LINE, src)
        pre = src.replace(ca._SANDBOX_CLASS_DOOR_LINE, "")
        with tempfile.TemporaryDirectory(prefix="sddc_member_") as d:
            tmp = _scene(Path(d), {MEMBER_REL: pre})
            c = census.measure(tmp)
        e = _entry(c, MEMBER_REL)
        self.assertEqual(e.verdict, "MARKER_BLIND")
        self.assertTrue(e.door_unreached, "функция двери осталась, проводка снята — половина инъекции")

    def test_the_live_population_is_named_and_measured(self):
        c = census.measure(ROOT)
        self.assertEqual(c.unmeasured, [], [e.reason for e in c.unmeasured])
        self.assertGreater(len(c.entries), 100)
        for k in ("MARKER_BLIND", "DOOR", "EXPLICIT_ONLY", "READER"):
            self.assertIn(k, c.counts)


class TestBridgeSandboxGuard(unittest.TestCase):
    """Дверь моста на НАСТОЯЩЕЙ `live_paths`: прод сцены — одноразовый каталог."""

    def setUp(self):
        from spa_core.utils import live_paths
        from spa_core.monitoring import findings_bridge
        self.lp, self.fb = live_paths, findings_bridge
        self._tmp = tempfile.TemporaryDirectory(prefix="sddc_guard_")
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

    def test_marker_and_prod_root_refuses_with_code_2_and_writes_nothing(self):
        os.environ["SPA_SANDBOX"] = "1"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = self.fb.main(["--run", "--root", str(self.prod)])
        self.assertEqual(rc, 2)
        self.assertEqual(sorted((self.prod / "data").iterdir()), [],
                         "отказ обязан идти ДО первой ступени — ни одного файла в data/")
        self.assertIn("ОТКАЗ (код 2)", err.getvalue())
        self.assertIn("маркер песочницы", err.getvalue())

    def test_marker_and_a_foreign_root_is_allowed(self):
        os.environ["SPA_SANDBOX"] = "1"
        self.assertIsNone(self.fb.sandbox_leak_reason(str(self.other)))

    def test_no_marker_and_prod_root_is_allowed(self):
        """Прод-бегун маркера не ставит — его эта дверь не видит вовсе."""
        self.assertIsNone(self.fb.sandbox_leak_reason(str(self.prod)))

    def test_marker_and_a_child_of_prod_is_refused(self):
        os.environ["SPA_SANDBOX"] = "1"
        nested = self.prod / "sub"
        (nested / "data").mkdir(parents=True)
        self.assertIsNotNone(self.fb.sandbox_leak_reason(str(nested)))

    def test_probe_tree_marker_counts_too(self):
        os.environ["SPA_STAMP_TREE"] = str(self.other)
        self.assertIsNotNone(self.fb.sandbox_leak_reason(str(self.prod)))


class TestTheProbe(unittest.TestCase):
    PROBE = "sandbox_data_dir_class_population_named"

    def setUp(self):
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca

    def test_registered(self):
        self.assertIn(self.PROBE, self.ca.PROBES)

    def test_live_tree_is_satisfied_and_names_the_population(self):
        verdict, detail = self.ca.run_probe(self.PROBE)
        self.assertEqual(verdict, self.ca.SATISFIED, detail)
        self.assertIn("MARKER_BLIND", detail)
        self.assertIn(MEMBER_REL, detail)

    def test_an_argument_is_unmeasured(self):
        verdict, _ = self.ca.run_probe(self.PROBE + ":x")
        self.assertEqual(verdict, self.ca.UNMEASURED)

    def _tree(self, d: Path, bridge_src: str, with_census: bool = True) -> Path:
        _scene(d, {MEMBER_REL: bridge_src})
        if with_census:
            shutil.copy2(CENSUS_PATH, d / "scripts" / CENSUS_PATH.name)
        return d

    def test_a_tree_without_the_wiring_is_not_satisfied(self):
        src = (ROOT / MEMBER_REL).read_text(encoding="utf-8")
        pre = src.replace(self.ca._SANDBOX_CLASS_DOOR_LINE, "")
        with tempfile.TemporaryDirectory(prefix="sddc_p1_") as d:
            verdict, detail = self.ca._probe_sandbox_data_dir_class_population_named(
                None, repo_root=str(self._tree(Path(d), pre)))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("проводки", detail)

    def test_the_wiring_as_prose_is_not_satisfied(self):
        """Строка проводки ЕСТЬ в файле — в докстринге двери, — а вызова НЕТ: подстрочная
        проба прошла бы, эта обязана отказать по вердикту переписи (ADR-333)."""
        src = (ROOT / MEMBER_REL).read_text(encoding="utf-8")
        line = self.ca._SANDBOX_CLASS_DOOR_LINE
        anchor = ('    """\n    from spa_core.utils.live_paths import SandboxLeakError, '
                  'assert_not_prod_realpath\n')
        self.assertIn(anchor, src)
        prose = src.replace(line, "    leak = None\n", 1)
        prose = prose.replace(anchor, "    Пример проводки:\n" + line + anchor, 1)
        self.assertIn(line, prose, "подстрока проводки обязана остаться в файле")
        with tempfile.TemporaryDirectory(prefix="sddc_p2_") as d:
            verdict, detail = self.ca._probe_sandbox_data_dir_class_population_named(
                None, repo_root=str(self._tree(Path(d), prose)))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("MARKER_BLIND", detail)

    def test_a_tree_without_the_census_is_not_satisfied(self):
        src = (ROOT / MEMBER_REL).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="sddc_p3_") as d:
            verdict, detail = self.ca._probe_sandbox_data_dir_class_population_named(
                None, repo_root=str(self._tree(Path(d), src, with_census=False)))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("переписи населения нет", detail)

    def test_a_scene_tree_with_the_live_bridge_is_satisfied(self):
        src = (ROOT / MEMBER_REL).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="sddc_p4_") as d:
            verdict, detail = self.ca._probe_sandbox_data_dir_class_population_named(
                None, repo_root=str(self._tree(Path(d), src)))
        self.assertEqual(verdict, self.ca.SATISFIED, detail)
        # в сцене две точки входа: мост (DOOR) и сама перепись (READER — у неё `--repo-root`)
        self.assertIn("точек входа 2 ", detail)
        self.assertIn("DOOR 1", detail)
        self.assertIn("MARKER_BLIND 0", detail)


if __name__ == "__main__":
    unittest.main()

"""ADR-1002 — замер «реестр → бегун»: куда пишут аналитики реестра, когда их зовёт бегун из песочницы.

Что держат эти тесты (прибор `scripts/registry_runner_write_census.py`):

* правило выбора входа — ТО ЖЕ, что у `_ModuleAdapter._import_callable` + `_invoke`: класс записи,
  строящийся без аргументов, иначе модуль; первый метод `_ENTRY_METHODS`, принимающий контекст
  (`context=`, один позиционный, `*args`/`**kwargs`); класс, требующий аргументов, уступает модулю;
* `_ENTRY_METHODS` читается из бегуна СЦЕНЫ, а не из копии правила: иной порядок в бегуне меняет вход;
* достижимость записи — по графу вызовов внутри модуля; запись в `main()` (CLI) от входа бегуна НЕ
  достигается и вердикт — `NO_WRITE_REACHED`; `str.replace` и `open(path)` без режима записи —
  не записи (отрицательные контроли); делегирование чужому модулю аналитики — `DELEGATES_OUT`,
  не «чисто»;
* бегун, кладущий `data_dir` в контекст, + модуль, читающий его оттуда, = предмет пуст (код 0) —
  положительный контроль двери у бегуна; тот же модуль при бегуне без двери — код 1;
* три исхода: нечитаемый модуль — `UNMEASURED`, но код 1 остаётся, когда предмет назван; нет
  реестра / нет `_ENTRY_METHODS` / пустая поверхность — код 2;
* `--readers-json` помечает подмножество «76 реестра» и считает вердикты внутри него;
* наблюдение (`observe`): отказ на прод-дереве и на git-дереве ДО какого-либо запуска; сквозная
  сцена с НАСТОЯЩИМ бегуном — модуль, пишущий в `data/` дерева, модуль, пишущий в `data` от cwd,
  и модуль без записи: корзины и парность со статикой считаются поимённо;
* живое дерево: население названо по каждому вердикту, `UNMEASURED` = 0, бегун `data_dir` в контекст
  КЛАДЁТ (ADR-1003, цикл #1122: дверь `SignalAggregator._context_for_modules`; до неё ADR-1002 мерил
  «не кладёт» — утверждение перемерено и переписано вместе с ADR, а не погашено).

Прод-`data/` не пишется ни одной сценой: наблюдение идёт только в одноразовых каталогах, а отказ на
прод-дереве проверяется через подмену `live_paths.DEFAULT_LIVE_ROOT` на одноразовый каталог.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"
REAL_RUNNER = ROOT / "spa_core" / "analytics" / "signal_aggregator.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census")


# ─────────────────────────── сцены ───────────────────────────

RUNNER_STUB = '''
_ENTRY_METHODS = ("analyze", "score", "run")

class _ModuleAdapter:
    def _invoke(self, obj, context):
        ctx = dict(context)
        return None

class SignalAggregator:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
'''

RUNNER_STUB_WITH_DOOR = RUNNER_STUB.replace(
    "        ctx = dict(context)\n",
    "        ctx = dict(context)\n        ctx[\"data_dir\"] = str(self.data_dir)\n")

MOD_WRITES_IN_ANALYZE = '''
from pathlib import Path
from spa_core.utils.atomic import atomic_save
_ROOT = Path(__file__).resolve().parents[2]

def _save(doc):
    atomic_save(doc, str(_ROOT / "data" / "a_log.json"))

def analyze(context):
    doc = {"protocol": context.get("protocol")}
    _save(doc)
    return {"risk_score": 1.0}
'''

MOD_CLASS_WRITES = '''
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]

class Scorer:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else _ROOT / "data"

    def _persist(self, doc):
        (self.data_dir / "b_log.json").write_text("{}")

    def score(self, context=None):
        self._persist({})
        return {"score": 3}
'''

MOD_CLASS_NEEDS_ARGS = '''
class Needs:
    def __init__(self, positions):
        self.positions = positions
    def analyze(self, context):
        open("x.json", "w").write("{}")

def run(ctx):
    return {"score": 1}
'''

MOD_WRITES_ONLY_IN_MAIN = '''
import argparse, json
from pathlib import Path

def analyze(positions):
    return {"risk_score": 2}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args(argv)
    with open(Path(args.data_dir) / "c.json", "w") as fh:
        json.dump({}, fh)

if __name__ == "__main__":
    main()
'''

MOD_NO_ENTRY = '''
def compute(a, b):
    return a + b

def analyze(a, b):
    return compute(a, b)
'''

MOD_DELEGATES = '''
from spa_core.analytics import _apy_series

def analyze(context):
    series = _apy_series.get_series(context["protocol"])
    return {"score": 1 if series else 0}
'''

MOD_READS_CONTEXT_DOOR = '''
import json
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]

def analyze(context):
    root = Path(context.get("data_dir") or _ROOT / "data")
    with open(root / "d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_NEGATIVE_CONTROLS = '''
def analyze(context):
    name = "a-b".replace("-", "_")
    with open(__file__) as fh:
        fh.read()
    return {"score": len(name)}
'''

MOD_BROKEN = "def analyze(context:\n    return 1\n"


def _registry(entries):
    rows = ",\n    ".join(repr(e) for e in entries)   # repr, не json: `null`/`true` не литералы Python
    return f"from typing import Any, Dict, List\n\nTIER_B_MODULES: List[Dict[str, Any]] = [\n    {rows}\n]\n"


class Scene:
    def __init__(self, *, runner_src: str = RUNNER_STUB):
        self.tmp = Path(tempfile.mkdtemp(prefix="rrwc_scene_"))
        for sub in ("spa_core/analytics", "spa_core/utils", "scripts", "data"):
            (self.tmp / sub).mkdir(parents=True, exist_ok=True)
        (self.tmp / "spa_core" / "__init__.py").write_text("")
        (self.tmp / "spa_core" / "analytics" / "__init__.py").write_text("")
        (self.tmp / "spa_core" / "utils" / "__init__.py").write_text("")
        self.write("spa_core/analytics/signal_aggregator.py", runner_src)

    def write(self, rel: str, src: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(src), encoding="utf-8")
        return p

    def registry(self, entries) -> None:
        self.write("spa_core/analytics/_module_registry.py", _registry(entries))

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def _entry(module, cls=None, tier="B"):
    return {"module": module, "class": cls, "tier": tier, "category": "x", "weight": 0.5, "protocols": ["all"]}


# ─────────────────────────── правило входа ───────────────────────────

class TestEntrySelection(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def _one(self, name, src, cls=None):
        self.s.write(f"spa_core/analytics/{name}.py", src)
        self.s.registry([_entry(name, cls)])
        c = rrwc.measure(self.s.tmp)
        return c, c.modules[0]

    def test_module_level_analyze_reaching_a_write_through_a_helper(self):
        c, m = self._one("m_a", MOD_WRITES_IN_ANALYZE)
        self.assertEqual(m.entry, "analyze")
        self.assertEqual(m.runner_target, "module")
        self.assertEqual(m.verdict, "WRITE_REACHABLE")
        self.assertEqual({w.form for w in m.writes}, {"atomic_save"})
        self.assertEqual(c.code, 1)

    def test_class_without_required_args_is_the_target_and_self_method_is_followed(self):
        _, m = self._one("m_b", MOD_CLASS_WRITES, cls="Scorer")
        self.assertEqual(m.runner_target, "class")
        self.assertEqual(m.entry, "Scorer.score")
        self.assertEqual(m.verdict, "WRITE_REACHABLE")
        self.assertEqual({w.form for w in m.writes}, {"write_text"})

    def test_class_requiring_args_yields_to_the_module_functions(self):
        _, m = self._one("m_c", MOD_CLASS_NEEDS_ARGS, cls="Needs")
        self.assertEqual(m.runner_target, "module (класс требует аргументов)")
        self.assertEqual(m.entry, "run")
        # запись лежит в методе класса, до которого бегун не доходит
        self.assertEqual(m.verdict, "NO_WRITE_REACHED")

    def test_write_only_in_cli_main_is_not_reached_from_the_runner_entry(self):
        c, m = self._one("m_d", MOD_WRITES_ONLY_IN_MAIN)
        self.assertEqual(m.entry, "analyze")
        self.assertEqual(m.verdict, "NO_WRITE_REACHED", m)
        self.assertEqual(c.code, 0)

    def test_no_context_accepting_entry_is_NO_ENTRY(self):
        _, m = self._one("m_e", MOD_NO_ENTRY)
        self.assertIsNone(m.entry)
        self.assertEqual(m.verdict, "NO_ENTRY")

    def test_registry_class_absent_from_file_falls_back_to_module(self):
        _, m = self._one("m_f", MOD_WRITES_IN_ANALYZE, cls="Ghost")
        self.assertEqual(m.runner_target, "module (класс не найден)")
        self.assertEqual(m.verdict, "WRITE_REACHABLE")

    def test_entry_order_comes_from_the_scene_runner_not_from_a_copy(self):
        src = '''
        def run(context):
            open("r.json", "w").write("{}")
            return 1
        def analyze(context):
            return 1
        '''
        self.s.write("spa_core/analytics/m_g.py", src)
        self.s.registry([_entry("m_g")])
        self.assertEqual(rrwc.measure(self.s.tmp).modules[0].entry, "analyze")
        self.s.write("spa_core/analytics/signal_aggregator.py",
                     RUNNER_STUB.replace('("analyze", "score", "run")', '("run", "analyze")'))
        m = rrwc.measure(self.s.tmp).modules[0]
        self.assertEqual(m.entry, "run")
        self.assertEqual(m.verdict, "WRITE_REACHABLE")

    def test_imported_registry_class_is_delegation_not_no_entry(self):
        src = '''
        from spa_core.analytics._gross_of_base import GrossOfAnalyzer
        def helper():
            return 1
        '''
        _, m = self._one("m_imp", src, cls="GrossOfAnalyzer")
        self.assertEqual(m.runner_target, "class (ввезён из другого модуля)")
        self.assertEqual(m.verdict, "DELEGATES_OUT")
        self.assertEqual(m.delegates, ["GrossOfAnalyzer"])

    def test_dataclass_with_required_fields_yields_to_the_module(self):
        src = '''
        from dataclasses import dataclass, field
        @dataclass
        class Tenor:
            days: int
            label: str = "x"
            tags: list = field(default_factory=list)
            def analyze(self, context):
                open("t.json", "w").write("{}")
        def analyze(context):
            return {"score": 1}
        '''
        _, m = self._one("m_dc", src, cls="Tenor")
        self.assertEqual(m.runner_target, "module (класс требует аргументов)")
        self.assertEqual(m.entry, "analyze")
        self.assertEqual(m.verdict, "NO_WRITE_REACHED")
        src_ok = src.replace("            days: int\n", "            days: int = 0\n")
        self.s.write("spa_core/analytics/m_dc.py", src_ok)
        m = rrwc.measure(self.s.tmp).modules[0]
        self.assertEqual(m.runner_target, "class")
        self.assertEqual(m.entry, "Tenor.analyze")
        self.assertEqual(m.verdict, "WRITE_REACHABLE")

    def test_entry_annotation_is_recorded_and_foreign_types_are_counted(self):
        src = '''
        from typing import Dict, Any
        def analyze(positions: list):
            return 1
        '''
        c, m = self._one("m_ann", src)
        self.assertEqual(m.entry_annotation, "list")
        self.assertEqual(c.exposure["entry_non_mapping_annotation"], 1)
        self.s.write("spa_core/analytics/m_ann.py", "def analyze(context: dict):\n    return 1\n")
        c = rrwc.measure(self.s.tmp)
        self.assertEqual(c.modules[0].entry_annotation, "dict")
        self.assertEqual(c.exposure["entry_non_mapping_annotation"], 0)
        for ann, foreign in (("List[Dict[str, Any]]", True), ("list[dict]", True), ("Optional[dict]", False),
                             ("Dict[str, Any] | None", False), ("Mapping[str, Any]", False),
                             ("BasisTradeInput", True), (None, False), ("Any", False)):
            self.assertEqual(rrwc._annotation_is_foreign(ann), foreign, ann)

    def test_class_assembled_by_module_level_assignment_is_delegation(self):
        src = '''
        from spa_core.analytics._gross_of_base import make_analyzer
        GapAnalyzer = make_analyzer("gap")
        '''
        _, m = self._one("m_asm", src, cls="GapAnalyzer")
        self.assertEqual(m.runner_target, "class (собран присваиванием)")
        self.assertEqual(m.verdict, "DELEGATES_OUT")
        self.assertEqual(m.delegates, ["GapAnalyzer = make_analyzer('gap')"])

    def test_kwonly_required_parameter_blocks_the_entry(self):
        src = '''
        def analyze(context, *, positions):
            return 1
        def score(*args, **kwargs):
            return 1
        '''
        _, m = self._one("m_h", src)
        self.assertEqual(m.entry, "score")


# ─────────────────────────── записи и делегирование ───────────────────────────

class TestWritesAndDelegation(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def test_str_replace_and_read_open_are_not_writes(self):
        self.s.write("spa_core/analytics/m_n.py", MOD_NEGATIVE_CONTROLS)
        self.s.registry([_entry("m_n")])
        c = rrwc.measure(self.s.tmp)
        self.assertEqual(c.modules[0].verdict, "NO_WRITE_REACHED")
        self.assertEqual(c.modules[0].writes, [])
        self.assertEqual(c.code, 0)

    def test_delegation_to_a_sibling_analytics_module_is_its_own_outcome(self):
        self.s.write("spa_core/analytics/m_del.py", MOD_DELEGATES)
        self.s.registry([_entry("m_del")])
        m = rrwc.measure(self.s.tmp).modules[0]
        self.assertEqual(m.verdict, "DELEGATES_OUT")
        self.assertEqual(m.delegates, ["_apy_series.get_series"])

    def test_open_with_write_mode_keyword_and_json_dump_are_writes(self):
        src = '''
        import json
        def analyze(context):
            with open("z.json", mode="w") as fh:
                json.dump({}, fh)
            return 1
        '''
        self.s.write("spa_core/analytics/m_w.py", src)
        self.s.registry([_entry("m_w")])
        m = rrwc.measure(self.s.tmp).modules[0]
        self.assertEqual(m.verdict, "WRITE_REACHABLE")
        self.assertEqual({w.form for w in m.writes}, {"open:w", "json.dump"})

    def test_context_door_and_env_door_are_reported_per_module(self):
        self.s.write("spa_core/analytics/m_door.py", MOD_READS_CONTEXT_DOOR)
        self.s.write("spa_core/analytics/m_env.py", '''
        import os
        def analyze(context):
            os.environ.get("SPA_DATA_DIR")
            return 1
        ''')
        self.s.registry([_entry("m_door"), _entry("m_env")])
        c = rrwc.measure(self.s.tmp)
        by = {m.module: m for m in c.modules}
        self.assertTrue(by["m_door"].reads_context_data_dir)
        self.assertFalse(by["m_door"].reads_env_data_dir)
        self.assertTrue(by["m_env"].reads_env_data_dir)
        self.assertEqual(c.exposure["module_reads_context_data_dir"], 1)
        self.assertEqual(c.exposure["module_reads_env_data_dir"], 1)


# ─────────────────────────── дверь у бегуна ───────────────────────────

class TestRunnerDoor(unittest.TestCase):
    def test_runner_without_the_door_names_the_subject(self):
        s = Scene()
        try:
            s.write("spa_core/analytics/m_door.py", MOD_READS_CONTEXT_DOOR)
            s.registry([_entry("m_door")])
            c = rrwc.measure(s.tmp)
            self.assertFalse(c.runner.passes_data_dir)
            self.assertEqual(c.modules[0].verdict, "WRITE_REACHABLE")
            self.assertEqual(c.exposure["default_reached_under_sandbox"], 1)
            self.assertEqual(c.code, 1)
        finally:
            s.close()

    def test_runner_with_the_door_and_a_module_reading_it_empties_the_subject(self):
        s = Scene(runner_src=RUNNER_STUB_WITH_DOOR)
        try:
            s.write("spa_core/analytics/m_door.py", MOD_READS_CONTEXT_DOOR)
            s.write("spa_core/analytics/m_a.py", MOD_WRITES_IN_ANALYZE)
            s.registry([_entry("m_door"), _entry("m_a")])
            c = rrwc.measure(s.tmp)
            self.assertTrue(c.runner.passes_data_dir)
            # m_door следует за бегуном, m_a — нет: предмет = 1, код 1
            self.assertEqual(c.exposure["default_reached_under_sandbox"], 1)
            self.assertEqual(c.code, 1)
            s.registry([_entry("m_door")])
            c = rrwc.measure(s.tmp)
            self.assertEqual(c.exposure["default_reached_under_sandbox"], 0)
            self.assertEqual(c.code, 0)
        finally:
            s.close()

    def test_runner_door_forms_setdefault_update_and_dict_literal(self):
        for form in ('        ctx.setdefault("data_dir", 1)\n',
                     '        ctx.update(data_dir=1)\n',
                     '        ctx = {"data_dir": 1}\n'):
            s = Scene(runner_src=RUNNER_STUB.replace("        ctx = dict(context)\n",
                                                     "        ctx = dict(context)\n" + form))
            try:
                s.registry([_entry("m_x")])
                s.write("spa_core/analytics/m_x.py", MOD_NO_ENTRY)
                self.assertTrue(rrwc.read_runner(s.tmp).passes_data_dir, form)
            finally:
                s.close()


# ─────────────────────────── три исхода ───────────────────────────

class TestThreeOutcomes(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def test_unparsable_module_is_UNMEASURED_and_does_not_hide_a_named_subject(self):
        self.s.write("spa_core/analytics/m_bad.py", MOD_BROKEN)
        self.s.write("spa_core/analytics/m_a.py", MOD_WRITES_IN_ANALYZE)
        self.s.registry([_entry("m_bad"), _entry("m_missing"), _entry("m_a")])
        c = rrwc.measure(self.s.tmp)
        by = {m.module: m for m in c.modules}
        self.assertEqual(by["m_bad"].verdict, "UNMEASURED")
        self.assertIn("не разобран", by["m_bad"].reason)
        self.assertEqual(by["m_missing"].verdict, "UNMEASURED")
        self.assertEqual(by["m_missing"].reason, "файла нет в дереве")
        self.assertEqual(c.counts["UNMEASURED"], 2)
        self.assertEqual(c.code, 1)

    def test_only_unmeasured_modules_is_code_2(self):
        self.s.registry([_entry("m_missing")])
        c = rrwc.measure(self.s.tmp)
        self.assertEqual(c.code, 2)
        self.assertIn("ни один модуль", c.unmeasured_reason)

    def test_missing_registry_or_runner_or_entry_methods_is_NotMeasured(self):
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.measure(self.s.tmp)                       # реестра нет
        self.s.registry([_entry("m_a")])
        self.s.write("spa_core/analytics/signal_aggregator.py", "X = 1\n")
        with self.assertRaises(rrwc.NotMeasured) as ctx:
            rrwc.measure(self.s.tmp)
        self.assertIn("_ENTRY_METHODS", str(ctx.exception))
        (self.s.tmp / "spa_core/analytics/signal_aggregator.py").unlink()
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.measure(self.s.tmp)

    def test_registry_as_plain_assign_is_read_too(self):
        self.s.write("spa_core/analytics/m_a.py", MOD_WRITES_IN_ANALYZE)
        self.s.write("spa_core/analytics/_module_registry.py",
                     "TIER_B_MODULES = [" + repr(_entry("m_a")) + "]\n")
        self.assertEqual(rrwc.measure(self.s.tmp).modules[0].verdict, "WRITE_REACHABLE")

    def test_main_prints_three_outcomes_and_returns_the_code(self):
        import contextlib
        import io
        self.s.write("spa_core/analytics/m_a.py", MOD_WRITES_IN_ANALYZE)
        self.s.registry([_entry("m_a")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rrwc.main(["--repo-root", str(self.s.tmp)])
        self.assertEqual(rc, 1)
        self.assertIn("предмет НАЗВАН", buf.getvalue())
        (self.s.tmp / "spa_core/analytics/_module_registry.py").unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rrwc.main(["--repo-root", str(self.s.tmp), "--json"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(buf.getvalue())["code"], 2)


# ─────────────────────────── подмножество 76 ───────────────────────────

class TestReadersSubset(unittest.TestCase):
    def test_readers_json_marks_registry_relied_entries_only(self):
        s = Scene()
        try:
            s.write("spa_core/analytics/m_a.py", MOD_WRITES_IN_ANALYZE)
            s.write("spa_core/analytics/m_d.py", MOD_WRITES_ONLY_IN_MAIN)
            s.registry([_entry("m_a"), _entry("m_d")])
            readers = {"callers": {"readers": [
                {"path": "spa_core/analytics/m_d.py", "verdict": "DEFAULT_RELIED", "default_origin": "literal",
                 "callers": [{"kind": "registry"}]},
                {"path": "spa_core/analytics/m_a.py", "verdict": "DEFAULT_RELIED", "default_origin": "literal",
                 "callers": [{"kind": "prompt"}]},          # не реестр — не в подмножестве
            ]}}
            rj = s.tmp / "callers.json"
            rj.write_text(json.dumps(readers), encoding="utf-8")
            c = rrwc.measure(s.tmp, rj)
            by = {m.module: m for m in c.modules}
            self.assertEqual(by["m_d"].blind_cli, "literal")
            self.assertIsNone(by["m_a"].blind_cli)
            self.assertEqual(c.blind_subset["named"], 1)
            self.assertEqual(c.blind_subset["found"], 1)
            self.assertEqual(c.blind_subset["NO_WRITE_REACHED"], 1)
            rj.write_text("{not json", encoding="utf-8")
            with self.assertRaises(rrwc.NotMeasured):
                rrwc.measure(s.tmp, rj)
        finally:
            s.close()


# ─────────────────────────── наблюдение ───────────────────────────

class TestObserveRefusals(unittest.TestCase):
    def test_refuses_the_prod_tree_before_running_anything(self):
        from spa_core.utils import live_paths
        s = Scene()
        saved = live_paths.DEFAULT_LIVE_ROOT
        try:
            s.registry([_entry("m_e")])
            s.write("spa_core/analytics/m_e.py", MOD_NO_ENTRY)
            c = rrwc.measure(s.tmp)
            live_paths.DEFAULT_LIVE_ROOT = s.tmp
            with self.assertRaises(rrwc.NotMeasured) as ctx:
                rrwc.observe(s.tmp, c, protocol="aave_v3", timeout=1.0)
            self.assertIn("ПРОД", str(ctx.exception))
            # и потомок прод-дерева тоже
            with self.assertRaises(rrwc.NotMeasured):
                rrwc.observe(s.tmp / "spa_core", c, protocol="aave_v3", timeout=1.0)
        finally:
            live_paths.DEFAULT_LIVE_ROOT = saved
            s.close()

    def test_refuses_a_git_tree(self):
        s = Scene()
        try:
            s.registry([_entry("m_e")])
            s.write("spa_core/analytics/m_e.py", MOD_NO_ENTRY)
            c = rrwc.measure(s.tmp)
            (s.tmp / ".git").write_text("gitdir: elsewhere\n")
            with self.assertRaises(rrwc.NotMeasured) as ctx:
                rrwc.observe(s.tmp, c, protocol="aave_v3", timeout=1.0)
            self.assertIn("git", str(ctx.exception))
        finally:
            s.close()


class TestObserveEndToEnd(unittest.TestCase):
    """Настоящий бегун (копия `signal_aggregator.py` этого дерева) зовёт модули сцены."""

    def test_real_runner_writes_land_in_module_default_not_in_the_runner_dir(self):
        s = Scene(runner_src=REAL_RUNNER.read_text(encoding="utf-8"))
        try:
            s.write("spa_core/analytics/m_tree.py", '''
            import json, os
            from pathlib import Path
            _ROOT = Path(__file__).resolve().parents[2]
            def _save(doc):
                target = _ROOT / "data" / "a_log.json"
                tmp = target.with_suffix(".tmp")
                with open(tmp, "w") as fh:
                    json.dump(doc, fh)
                os.replace(tmp, target)
            def analyze(context):
                _save({"protocol": context.get("protocol")})
                return {"risk_score": 1.0}
            ''')                                                               # дерево модуля
            s.write("spa_core/analytics/m_cwd.py", '''
            import json
            from pathlib import Path
            def analyze(context):
                Path("data").mkdir(exist_ok=True)
                with open(Path("data") / "cwd_log.json", "w") as fh:
                    json.dump({"p": context.get("protocol")}, fh)
                return {"score": 5}
            ''')
            s.write("spa_core/analytics/m_quiet.py", "def analyze(context):\n    return {'score': 7}\n")
            s.write("spa_core/analytics/m_none.py", MOD_NO_ENTRY)
            s.registry([_entry("m_tree"), _entry("m_cwd"), _entry("m_quiet"), _entry("m_none")])
            c = rrwc.measure(s.tmp)
            by = {m.module: m.verdict for m in c.modules}
            self.assertEqual(by, {"m_tree": "WRITE_REACHABLE", "m_cwd": "WRITE_REACHABLE",
                                  "m_quiet": "NO_WRITE_REACHED", "m_none": "NO_ENTRY"})
            obs = rrwc.observe(s.tmp, c, protocol="aave_v3", timeout=5.0)
            self.assertEqual(obs["modules"], 4, obs)
            self.assertEqual(obs["observer_returncode"], 0, obs["observer_stderr_tail"])
            self.assertEqual(obs["baskets"], {"runner_dir": 0, "tree_data": 1, "cwd_data": 1}, obs)
            writers = {w["module"]: w["written"] for w in obs["writers"]}
            self.assertEqual(set(writers), {"m_tree", "m_cwd"})
            self.assertEqual(writers["m_tree"], {"tree_data": ["a_log.json"]})
            self.assertEqual(sorted(writers["m_cwd"]["cwd_data"]), ["cwd_log.json"])
            self.assertEqual(obs["statuses"].get("unchecked"), 1)
            self.assertEqual(obs["parity"]["static_no_entry_and_unchecked"], 1)
            self.assertEqual(obs["parity"]["static_write_reachable_observed"], 2)
            self.assertEqual(obs["parity"]["observed_write_static_missed"], 0)
            # запись легла в data/ ДЕРЕВА — предмет замера воспроизведён в одноразовой копии
            self.assertTrue((s.tmp / "data" / "a_log.json").is_file())
            self.assertEqual(obs["elsewhere_in_tree"], [])
        finally:
            s.close()


# ─────────────────────────── проводка через перепись ───────────────────────────

class TestCensusRunnerFlag(unittest.TestCase):
    """`sandbox_data_dir_census.py --runner` зовёт этот прибор по файлу (проводка, ADR-1002) и
    отдаёт его вердикт в общем коде; с `--callers` подмножество читателей передаётся В ПРОЦЕССЕ."""

    def test_census_runner_flag_prints_the_runner_verdict_and_lifts_the_code(self):
        import contextlib
        import io
        census = _load(ROOT / "scripts" / "sandbox_data_dir_census.py", "spa_sandbox_data_dir_census_for_runner")
        s = Scene()
        try:
            for sub in census.SURFACE_DIRS:
                (s.tmp / sub).mkdir(parents=True, exist_ok=True)
            # поверхность переписи не должна быть пустой (иначе её честный код 2 перекроет код бегуна)
            s.write("spa_core/monitoring/blind_entry.py", '''
            import argparse
            from pathlib import Path
            def main(argv=None):
                ap = argparse.ArgumentParser()
                ap.add_argument("--data-dir", default="data")
                args = ap.parse_args(argv)
                (Path(args.data_dir) / "x.json").write_text("{}")
            if __name__ == "__main__":
                main()
            ''')
            s.write("spa_core/analytics/m_a.py", MOD_WRITES_IN_ANALYZE)
            s.registry([_entry("m_a")])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                rc = census.main(["--repo-root", str(s.tmp), "--runner"])
            out = buf.getvalue()
            self.assertIn("Перепись «песочница без названного каталога данных»", out)
            self.assertIn("РЕЕСТР → БЕГУН", out)
            self.assertIn("WRITE_REACHABLE   1", out)
            self.assertEqual(rc, 1, out)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                rc = census.main(["--repo-root", str(s.tmp), "--callers", "--runner", "--json"])
            doc = json.loads(buf.getvalue())
            self.assertIn("runner", doc)
            self.assertEqual(doc["runner"]["counts"]["WRITE_REACHABLE"], 1)
            self.assertIsNotNone(doc["runner"]["blind_subset"], "подмножество читателей не передано в процессе")
        finally:
            s.close()

    def test_readers_doc_in_process_matches_the_json_form(self):
        doc = {"callers": {"readers": [
            {"path": "spa_core/analytics/x.py", "verdict": "DEFAULT_RELIED", "default_origin": "literal",
             "callers": [{"kind": "registry"}]}]}}
        self.assertEqual(rrwc.readers_from_doc(doc), {"spa_core/analytics/x.py": "literal"})
        self.assertEqual(rrwc.readers_from_doc({"readers": []}), {})


# ─────────────────────────── живое дерево ───────────────────────────

class TestLiveTree(unittest.TestCase):
    def test_population_is_named_and_the_runner_door_state_is_measured(self):
        c = rrwc.measure(ROOT)
        self.assertGreaterEqual(len(c.modules), 100)
        self.assertEqual(c.counts["UNMEASURED"], 0, [m.reason for m in c.modules if m.verdict == "UNMEASURED"][:5])
        for v in rrwc.VERDICTS:
            self.assertIn(v, c.counts)
        # ЗАМЕР состояния: ADR-1002 мерил «бегун data_dir в контекст НЕ кладёт»; ADR-1003 (цикл #1122)
        # поставил дверь — утверждение перемерено и переписано вместе с ADR, а не погашено.
        self.assertTrue(c.runner.passes_data_dir)
        # Дверь закрывает только читателей контекста У СВЯЗАННОГО ИМЕНИ (ADR-1005; по ключу их 53 —
        # замер #1121, по параметру из них 36, ещё 12 читают у `config` и остаются в предмете);
        # остальные записи реестра по-прежнему достигают своего умолчания от входа бегуна ⇒ код 1.
        self.assertEqual(c.code, 1)
        self.assertGreater(c.exposure["default_reached_under_sandbox"], 0)
        self.assertEqual(c.exposure["default_reached_under_sandbox"],
                         c.exposure["write_reachable"] - sum(
                             1 for m in c.modules
                             if m.verdict == "WRITE_REACHABLE" and m.data_dir_door == "CONTEXT_PARAM"))
        # усиление, не ослабление: тождество по КЛЮЧУ было бы ЛОЖНО на этом дереве — читатели у чужого
        # параметра пишут в умолчание, и прибор обязан их считать
        self.assertLess(c.exposure["write_reachable"] - sum(
            1 for m in c.modules if m.verdict == "WRITE_REACHABLE" and m.reads_context_data_dir),
            c.exposure["default_reached_under_sandbox"])
        self.assertEqual(tuple(c.runner.entry_methods)[:1], ("analyze",))


if __name__ == "__main__":
    unittest.main(verbosity=2)

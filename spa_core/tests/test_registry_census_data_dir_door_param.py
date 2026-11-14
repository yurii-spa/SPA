"""ADR-1005 — ось «у какого ПАРАМЕТРА дверь» у прибора «реестр → бегун» (ADR-1004 § 6а).

До этой оси прибор `scripts/registry_runner_write_census.py` судил читателя каталога бегуна по КЛЮЧУ:
`ctx["data_dir"]` / `.get("data_dir")` где угодно в файле ⇒ «модуль читает каталог бегуна», и дверь
бегуна (ADR-1003) считалась закрывающей его умолчание. У `protocol_defi_yield_duration_mismatch_analyzer`
до ADR-1004 это было ЛОЖНО: ключ читался у `config`, а бегун биндит контекст в `protocols`.

Что держат эти тесты — по ИСХОДУ прибора на сценах, а не по подстроке (ADR-333):

* чтение у связанного имени — само имя · псевдоним (`ctx = context or {}`) · параметр помощника, которому
  имя передано позиционно или по ключу · атрибут `self`, в который имя положено · форма `context=`
  бегуна ⇒ `CONTEXT_PARAM`;
* чтение у ЧУЖОГО параметра (`config`) при контексте в первом позиционном ⇒ `FOREIGN_PARAM` — ровно
  форма ADR-1004 ДО починки; та же сцена С починкой (`_config_from_context(<связанное>)`) ⇒ `CONTEXT_PARAM`
  — положительный и отрицательный контроль на одной форме;
* контейнер (`[ctx]`) и чужой вызов (`make(ctx)`) связью НЕ являются — ошибка в сторону находки;
* ключ не читается ⇒ `NONE`; читается без входа у бегуна или при контексте в `*args`/`**kwargs` ⇒
  `UNRESOLVED` с причиной — третий исход, не «читает» и не «не читает»;
* предмет: писатель `FOREIGN_PARAM` под бегуном С дверью остаётся в `default_reached_under_sandbox`
  (код 1), писатель `CONTEXT_PARAM` — нет (код 0); три счётчика оси в `exposure`;
* живое дерево: оба модуля ADR-1004 — `CONTEXT_PARAM`; каждый читатель ключа несёт ровно один исход
  оси; сумма трёх исходов у читателей равна числу читателей по ключу.

Прод-`data/` ни одна сцена не трогает: статика читает только одноразовые деревья и файлы своего дерева.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_door_param")


RUNNER_WITH_DOOR = '''
_ENTRY_METHODS = ("analyze", "score", "run")

class _ModuleAdapter:
    def _invoke(self, obj, context):
        ctx = dict(context)
        ctx["data_dir"] = str(self.data_dir)
        return None

class SignalAggregator:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
'''

# ── форма ADR-1004 ДО починки: контекст биндится в `protocols`, ключ читается у `config` ──
MOD_PRE_1004 = '''
import os, json

class Analyzer:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or "data"

    def analyze(self, protocols, config=None):
        if isinstance(protocols, dict) and "protocol" in protocols:
            profile = {"name": protocols["protocol"]}
            return self.analyze([profile])
        if config is None:
            config = {}
        data_dir = config.get("data_dir", self.data_dir)
        with open(os.path.join(data_dir, "ydm.json"), "w") as fh:
            json.dump({"n": len(protocols)}, fh)
        return {"score": 1}
'''

# ── та же форма ПОСЛЕ починки ADR-1004: помощник читает ключ у связанного имени ──
MOD_POST_1004 = '''
import os, json

def _config_from_context(context):
    data_dir = context.get("data_dir") if isinstance(context, dict) else None
    return {"data_dir": str(data_dir)} if data_dir else None

class Analyzer:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or "data"

    def analyze(self, protocols, config=None):
        if isinstance(protocols, dict) and "protocol" in protocols:
            profile = {"name": protocols["protocol"]}
            return self.analyze([profile], _config_from_context(protocols))
        if config is None:
            config = {}
        data_dir = config.get("data_dir", self.data_dir)
        with open(os.path.join(data_dir, "ydm.json"), "w") as fh:
            json.dump({"n": len(protocols)}, fh)
        return {"score": 1}
'''

MOD_DIRECT = '''
import json
from pathlib import Path

def analyze(context):
    root = Path(context.get("data_dir") or "data")
    with open(root / "d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_ALIAS = '''
import json
from pathlib import Path

def analyze(context):
    ctx = context or {}
    root = Path(ctx["data_dir"])
    with open(root / "d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_HELPER_KEYWORD = '''
import json
from pathlib import Path

def _where(*, ctx):
    return Path(ctx.get("data_dir") or "data")

def analyze(payload):
    with open(_where(ctx=payload) / "d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_CONTEXT_KEYWORD_FORM = '''
import json

def analyze(*, context=None):
    with open((context or {}).get("data_dir", "data") + "/d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_SELF_ATTR = '''
import json, os

class Scorer:
    def score(self, context):
        self._ctx = context
        return self._persist()

    def _persist(self):
        with open(os.path.join(self._ctx.get("data_dir", "data"), "s.json"), "w") as fh:
            json.dump({}, fh)
        return {"score": 2}
'''

MOD_CONTAINER_IS_NOT_A_BINDING = '''
import json

def _where(items):
    return items[0].get("data_dir", "data")

def analyze(context):
    with open(_where([context]) + "/d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_FOREIGN_CALL_IS_NOT_A_BINDING = '''
import json

def make(ctx):
    return {"data_dir": "elsewhere"}

def analyze(context):
    cfg = make(context)
    with open(cfg["data_dir"] + "/d.json", "w") as fh:
        json.dump({}, fh)
    return {"score": 1}
'''

MOD_NO_READ = '''
import json

def analyze(context):
    with open("data/d.json", "w") as fh:
        json.dump({"k": "data_dir"}, fh)   # строка-литерал в значении — не чтение ключа
    return {"score": 1}
'''

MOD_NO_ENTRY_READS = '''
def analyze(a, b, config=None):
    return (config or {}).get("data_dir", "data")
'''

MOD_VARARGS = '''
def analyze(*args):
    return args[0].get("data_dir", "data")
'''

MOD_KWARGS_ONLY = '''
def analyze(**kwargs):
    return kwargs["context"].get("data_dir", "data")
'''


def _registry(entries):
    rows = ",\n    ".join(repr(e) for e in entries)
    return f"from typing import Any, Dict, List\n\nTIER_B_MODULES: List[Dict[str, Any]] = [\n    {rows}\n]\n"


def _entry(module, cls=None, tier="B"):
    return {"module": module, "class": cls, "tier": tier, "category": "x", "weight": 0.5, "protocols": ["all"]}


class Scene:
    def __init__(self, *, runner_src: str = RUNNER_WITH_DOOR):
        self.tmp = Path(tempfile.mkdtemp(prefix="rrwc_door_"))
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

    def one(self, name: str, src: str, cls=None):
        self.write(f"spa_core/analytics/{name}.py", src)
        self.write("spa_core/analytics/_module_registry.py", _registry([_entry(name, cls)]))
        c = rrwc.measure(self.tmp)
        return c, c.modules[0]

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class _SceneCase(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()


# ─────────────────────────── исходы оси ───────────────────────────

class TheOutcomeVocabularyIsClosed(unittest.TestCase):
    def test_four_outcomes_and_nothing_else(self):
        self.assertEqual(set(rrwc.DOOR_OUTCOMES), {"CONTEXT_PARAM", "FOREIGN_PARAM", "NONE", "UNRESOLVED"})


class ReadAtTheBoundName(_SceneCase):
    def test_direct_read_at_the_first_positional(self):
        _, m = self.s.one("m_direct", MOD_DIRECT)
        self.assertEqual(m.data_dir_door, "CONTEXT_PARAM")
        self.assertEqual([(r.func, r.base, r.bound) for r in m.data_dir_reads], [("analyze", "context", True)])

    def test_alias_with_a_guard_tail_is_still_the_bound_name(self):
        _, m = self.s.one("m_alias", MOD_ALIAS)
        self.assertEqual(m.data_dir_door, "CONTEXT_PARAM")
        self.assertEqual([r.base for r in m.data_dir_reads], ["ctx"])

    def test_helper_receiving_the_bound_name_by_keyword(self):
        _, m = self.s.one("m_helper", MOD_HELPER_KEYWORD)
        self.assertEqual(m.data_dir_door, "CONTEXT_PARAM")
        self.assertEqual([(r.func, r.base) for r in m.data_dir_reads], [("_where", "ctx")])

    def test_runner_form_one_context_keyword(self):
        _, m = self.s.one("m_kw", MOD_CONTEXT_KEYWORD_FORM)
        self.assertEqual(m.entry, "analyze")
        self.assertEqual(m.data_dir_door, "CONTEXT_PARAM")

    def test_self_attribute_holding_the_bound_name(self):
        _, m = self.s.one("m_self", MOD_SELF_ATTR, cls="Scorer")
        self.assertEqual(m.entry, "Scorer.score")
        self.assertEqual(m.data_dir_door, "CONTEXT_PARAM")
        self.assertEqual([(r.func, r.base) for r in m.data_dir_reads], [("Scorer._persist", "self._ctx")])


class ReadAtAForeignName(_SceneCase):
    def test_the_adr_1004_form_before_the_fix_reads_at_config_while_the_runner_binds_protocols(self):
        c, m = self.s.one("m_pre", MOD_PRE_1004, cls="Analyzer")
        self.assertEqual(m.entry, "Analyzer.analyze")
        self.assertTrue(m.reads_context_data_dir, "по КЛЮЧУ модуль читатель — ровно ложноположительный ADR-1002")
        self.assertEqual(m.data_dir_door, "FOREIGN_PARAM")
        self.assertEqual([(r.base, r.bound) for r in m.data_dir_reads], [("config", False)])
        # предмет: писатель у чужого параметра под бегуном С дверью остаётся в умолчании
        self.assertTrue(c.runner.passes_data_dir)
        self.assertEqual(m.verdict, "WRITE_REACHABLE")
        self.assertEqual(c.exposure["default_reached_under_sandbox"], 1)
        self.assertEqual(c.exposure["door_foreign_param"], 1)
        self.assertEqual(c.code, 1)

    def test_the_same_form_after_the_fix_is_read_at_the_bound_name_and_leaves_the_subject(self):
        c, m = self.s.one("m_post", MOD_POST_1004, cls="Analyzer")
        self.assertEqual(m.data_dir_door, "CONTEXT_PARAM")
        bound = {(r.func, r.base): r.bound for r in m.data_dir_reads}
        self.assertEqual(bound, {("_config_from_context", "context"): True,
                                 ("Analyzer.analyze", "config"): False})
        self.assertEqual(c.exposure["default_reached_under_sandbox"], 0)
        self.assertEqual(c.exposure["door_context_param"], 1)
        self.assertEqual(c.code, 0)

    def test_a_container_is_not_a_binding(self):
        _, m = self.s.one("m_cont", MOD_CONTAINER_IS_NOT_A_BINDING)
        self.assertEqual(m.data_dir_door, "FOREIGN_PARAM")

    def test_a_foreign_call_result_is_not_a_binding(self):
        _, m = self.s.one("m_call", MOD_FOREIGN_CALL_IS_NOT_A_BINDING)
        self.assertEqual(m.data_dir_door, "FOREIGN_PARAM")
        self.assertEqual([r.base for r in m.data_dir_reads], ["cfg"])


class NoReadAndTheThirdOutcome(_SceneCase):
    def test_no_read_is_none_and_a_string_literal_is_not_a_read(self):
        c, m = self.s.one("m_none", MOD_NO_READ)
        self.assertFalse(m.reads_context_data_dir)
        self.assertEqual(m.data_dir_door, "NONE")
        self.assertEqual(m.data_dir_reads, [])
        self.assertEqual(c.exposure["door_context_param"] + c.exposure["door_foreign_param"]
                         + c.exposure["door_unresolved"], 0)

    def test_read_without_a_runner_entry_is_unresolved_with_a_reason(self):
        c, m = self.s.one("m_noentry", MOD_NO_ENTRY_READS)
        self.assertEqual(m.verdict, "NO_ENTRY")
        self.assertTrue(m.reads_context_data_dir)
        self.assertEqual(m.data_dir_door, "UNRESOLVED")
        self.assertIn("входа у бегуна нет", m.data_dir_door_reason or "")
        self.assertEqual([r.base for r in m.data_dir_reads], ["config or {}"])
        self.assertEqual(c.exposure["door_unresolved"], 1)

    def test_context_into_varargs_has_no_name_to_bind(self):
        _, m = self.s.one("m_va", MOD_VARARGS)
        self.assertEqual(m.entry, "analyze")
        self.assertEqual(m.data_dir_door, "UNRESOLVED")
        self.assertIn("*args", m.data_dir_door_reason or "")

    def test_context_into_kwargs_only_has_no_name_to_bind(self):
        _, m = self.s.one("m_kwo", MOD_KWARGS_ONLY)
        self.assertEqual(m.entry, "analyze")
        self.assertEqual(m.data_dir_door, "UNRESOLVED")
        self.assertIn("**kwargs", m.data_dir_door_reason or "")


class TheAxisIsRendered(_SceneCase):
    def test_foreign_readers_are_named_with_the_base_they_read_at(self):
        c, _ = self.s.one("m_pre", MOD_PRE_1004, cls="Analyzer")
        text = rrwc.render(c)
        self.assertIn("door_foreign_param               1", text)
        self.assertIn("НЕ у связанного имени", text)
        self.assertIn("m_pre [WRITE_REACHABLE] FOREIGN_PARAM: Analyzer.analyze:", text)
        self.assertIn("у `config`", text)
        self.assertIn("дверь контекста: FOREIGN_PARAM", text)

    def test_json_document_carries_the_axis_per_module(self):
        c, _ = self.s.one("m_direct", MOD_DIRECT)
        doc = rrwc.to_doc(c)
        self.assertEqual(doc["modules"][0]["data_dir_door"], "CONTEXT_PARAM")
        self.assertEqual(doc["modules"][0]["data_dir_reads"][0]["bound"], True)
        self.assertEqual(doc["exposure"]["door_context_param"], 1)


# ─────────────────────────── живое дерево ───────────────────────────

class TheLiveTree(unittest.TestCase):
    def test_both_adr_1004_modules_read_at_the_bound_name(self):
        c = rrwc.measure(ROOT)
        by = {m.module: m for m in c.modules}
        for name in ("protocol_defi_yield_duration_mismatch_analyzer", "yield_volatility_surface_analyzer"):
            self.assertIn(name, by)
            self.assertEqual(by[name].data_dir_door, "CONTEXT_PARAM",
                             [(r.func, r.line, r.base, r.bound) for r in by[name].data_dir_reads])
            self.assertTrue(any(r.func == "_config_from_context" and r.bound for r in by[name].data_dir_reads))

    def test_every_key_reader_carries_exactly_one_axis_outcome_and_the_sum_matches(self):
        c = rrwc.measure(ROOT)
        readers = [m for m in c.modules if m.reads_context_data_dir]
        self.assertGreater(len(readers), 0)
        for m in readers:
            self.assertIn(m.data_dir_door, ("CONTEXT_PARAM", "FOREIGN_PARAM", "UNRESOLVED"), m.module)
            self.assertTrue(m.data_dir_reads, m.module)
        for m in c.modules:
            if not m.reads_context_data_dir:
                self.assertEqual(m.data_dir_door, "NONE", m.module)
        self.assertEqual(c.exposure["door_context_param"] + c.exposure["door_foreign_param"]
                         + c.exposure["door_unresolved"], c.exposure["module_reads_context_data_dir"])
        # у каждого UNRESOLVED причина НАЗВАНА (инв. #17)
        for m in c.modules:
            if m.data_dir_door == "UNRESOLVED":
                self.assertTrue(m.data_dir_door_reason, m.module)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Stat-keyed read cache of HashLedger (ADR-763 package 2).

Measured before: one Mission Control build parsed data/research_factory/ledger.jsonl 4 336 times
(1 077 s of 1 175 s). The cache is opt-in per READ-ONLY process and keyed by (dev, inode, size,
mtime_ns), so the M7 hazard documented on HashLedger.read_all — a sibling's write invisible to a
stale cache — cannot occur: every append grows the file and misses the cache.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spa_core.tests._freshness import ts
from spa_core.utils import hash_ledger as hl


@pytest.fixture()
def cache_on(monkeypatch):
    monkeypatch.setattr(hl, "_READ_CACHE_ENABLED", True)
    monkeypatch.setattr(hl, "_READ_CACHE", {})


def _ledger(tmp_path: Path) -> hl.HashLedger:
    return hl.HashLedger(tmp_path, "rf", "rf_anchors")


def _count_parses(monkeypatch) -> dict:
    n = {"parse": 0}
    orig = hl.HashLedger._parse

    def counting(path):
        n["parse"] += 1
        return orig(path)
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(counting))
    return n


def test_off_by_default_every_read_parses(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, "_READ_CACHE", {})
    assert hl._READ_CACHE_ENABLED is False
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    n = _count_parses(monkeypatch)
    led.read_all(); led.read_all(); led.read_all()
    assert n["parse"] == 3 and hl._READ_CACHE == {}


def test_repeated_reads_parse_once(tmp_path, monkeypatch, cache_on):
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    n = _count_parses(monkeypatch)
    rows = [led.read_all() for _ in range(50)]
    assert n["parse"] == 1
    assert all(r == rows[0] for r in rows)
    rows[0].append({"junk": True})                       # a caller's list is its own
    assert len(led.read_all()) == 1


def test_a_sibling_write_is_seen_immediately(tmp_path, monkeypatch, cache_on):
    """The M7 race: a second HashLedger object (another writer) appends after our read."""
    reader, writer = _ledger(tmp_path), _ledger(tmp_path)
    writer.append("run", ["r1"], {"x": 1}, ts(1))
    assert len(reader.read_all()) == 1
    writer.append("run", ["r2"], {"x": 2}, ts(0))
    got = reader.read_all()
    assert [e["key"] for e in got] == [["r1"], ["r2"]]
    assert reader.verify()["ok"] is True


def test_a_rewritten_file_of_equal_size_is_a_miss(tmp_path, monkeypatch, cache_on):
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    led.read_all()
    p = led.ledger_path()
    row = json.loads(p.read_text())
    row["payload"]["x"] = 9                                # same length, different content
    p.write_text(json.dumps(row) + "\n")
    assert led.read_all()[0]["payload"]["x"] == 9


def test_trusted_writer_path_keeps_its_own_semantics(tmp_path, monkeypatch, cache_on):
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    led.mark_verified()
    hl._READ_CACHE.clear()
    assert len(led.read_all()) == 1
    assert hl._READ_CACHE == {}                            # a trusted writer reads through its own M7 cache only


# ── ADR-777 (cycle #893): the carrier is the READ MODEL, and the scope ENDS ─────────────────────
#
# Invariant #16 note — this block REPLACES `test_mission_build_main_opts_in`, deliberately and
# with the reason stated here and in docs/journal/2026-W42.md. That test asserted exactly the two
# properties that WERE the defect: (a) the remedy is wired at ONE entry point
# (`mission_build.main`), and (b) the switch stays on for the rest of the process. It could not
# tell "wired for one caller" from "wired for all" — which is the only question that mattered.
# The replacements below measure the OUTCOME (parses per call) for EVERY declared view entry
# point, and each has a control that reddens when the wiring is removed. Strictly stronger: the
# old test stays green on the broken state, the new ones do not.


def _parses(monkeypatch_free_counter, fn) -> int:
    """How many times the ledger file is really parsed during *fn* — the OUTCOME the cache is
    for. Patched and restored by hand (no monkeypatch fixture) so a single test can measure
    several scenes in a row and compare them."""
    n = {"p": 0}
    orig = hl.HashLedger._parse

    def counting(path):
        n["p"] += 1
        return orig(path)
    hl.HashLedger._parse = staticmethod(counting)
    try:
        fn()
    finally:
        # staticmethod() on the way back too: handing the bare function to the class would
        # rebind it as an instance method and every later read in the process would get `self`
        # as its path — a restoration that silently breaks what it restores.
        hl.HashLedger._parse = staticmethod(orig)
    return n["p"]


def _rf_scene(tmp_path: Path, candidates: int = 1) -> Path:
    """A real (if small) research_factory ledger: one run row plus *candidates* candidate rows.
    The point of the parameter is the FAN-OUT — the defect was that cost grew with it."""
    from spa_core.research_factory._common import ledger_for
    data = tmp_path / "data"
    led = ledger_for(data)
    led.append("run", ["r1"], {"generated_at": ts(1)}, ts(1))
    for i in range(candidates):
        led.append("candidate", [f"c{i}"], {"candidate_id": f"c{i}", "domain": "d", "mechanism": "m"}, ts(1))
    return data


#: What ONE scoped call is allowed to parse: the fresh, deliberately UNCACHED `verify()` (N3 —
#: integrity is never answered from a cache) plus ONE cached parse that every helper then shares.
#: Not "== 1": pinning both numbers keeps `verify()`'s freshness from being optimised away by a
#: future change that would make this test pass for the wrong reason.
SCOPED_PARSES = 2


def test_the_read_model_carries_the_scope_so_every_caller_inherits_it(tmp_path):
    """Measured on the owner's Mac before this change: ONE `read.latest()` parsed
    `data/research_factory/ledger.jsonl` (52 108 460 B) 4 958 times — 1 613 s against 18.3 s —
    and the remedy of ADR-763 was wired into `mission_build.main()` only, so the UI-contract
    test, the owner's Telegram `/capital` view, `investment_cio.research_universe` and
    `capital_shadow.readiness` all paid the full price. The scope now lives at the read model, so
    a caller cannot forget it; here that is measured for EVERY declared entry point."""
    from spa_core.research_factory import read as rf_read
    from spa_core.tests._freshness import now_utc

    # `now` берётся ОТНОСИТЕЛЬНО тех же `ts()`, которыми помечены строки ленты (приём №2
    # `.claude/rules/deployment.md`): `cio_view` судит о свежести прогона, и литеральная
    # дата рядом с понятием свежести — бомба замедленного действия, а не фикстура.
    data = _rf_scene(tmp_path)
    calls = {"latest": lambda: rf_read.latest(data),
             "cio_view": lambda: rf_read.cio_view(data, now_utc())}
    assert set(calls) == set(rf_read.VIEW_ENTRY_POINTS), "scene does not cover the declared population"
    for name, call in calls.items():
        hl._READ_CACHE.clear()
        assert _parses(None, call) == SCOPED_PARSES, f"{name} parsed the ledger more than once"
        assert hl._READ_CACHE_ENABLED is False, f"{name} left the cache on for the whole process"
        assert hl._READ_CACHE == {}, f"{name} left its rows behind for an unrelated caller"


def test_removing_the_scope_from_the_read_model_reddens(tmp_path, monkeypatch):
    """The control for the test above: with the scope taken out, the SAME call parses the ledger
    repeatedly again. Without this, "parses == 2" could be a property of the small scene rather
    than of the wiring."""
    import contextlib
    from spa_core.research_factory import read as rf_read

    data = _rf_scene(tmp_path)
    monkeypatch.setattr(rf_read, "read_cache", contextlib.nullcontext)
    hl._READ_CACHE.clear()
    assert _parses(None, lambda: rf_read.latest(data)) > SCOPED_PARSES


def test_many_reads_collapse_into_one_parse_inside_a_single_view(tmp_path, monkeypatch):
    """What this unit scene CAN measure, measured: one `latest()` issues many `read_all()` calls
    and they collapse onto `SCOPED_PARSES` parses of the file.

    What it deliberately does NOT claim: the per-candidate FAN-OUT. A minimal scene's candidates
    never reach the states that call `paper._latest_row` (1 960 reads on the live ledger),
    `registry.latest_snapshot` (704), `lifecycle._current_state` (392) — measured, same scene,
    `raw_small == raw_big == 8`. The 4 958-to-8 number therefore rests on the LIVE measurement
    recorded in ADR-777, not on this test, and saying otherwise here would be the "green answer
    to its own question read as the answer to the needed one" class."""
    from spa_core.research_factory import read as rf_read

    data = _rf_scene(tmp_path, 3)
    reads = {"n": 0}
    orig_read = hl.HashLedger.read_all

    def counting_read(self, *a, **k):
        reads["n"] += 1
        return orig_read(self, *a, **k)
    monkeypatch.setattr(hl.HashLedger, "read_all", counting_read)

    hl._READ_CACHE.clear()
    parses = _parses(None, lambda: rf_read.latest(data))
    assert reads["n"] > parses, (f"the scene issues {reads['n']} reads and {parses} parses — it "
                                 f"does not exercise re-reading at all")
    assert parses == SCOPED_PARSES


def test_the_declared_population_cannot_grow_in_silence():
    """A new public view added to the read model must join `VIEW_ENTRY_POINTS` — otherwise it
    would be the twelfth reader nobody wired, which is the whole finding. Measured from the
    SIGNATURE (public callable whose first parameter is the data directory), not from the source
    text: a substring check would pass on a view that merely mentions the name in a comment."""
    import inspect
    from spa_core.research_factory import read as rf_read

    public_views = set()
    for name, obj in vars(rf_read).items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if obj.__module__ != rf_read.__name__:
            continue                                   # an imported helper is not this module's view
        params = list(inspect.signature(obj).parameters)
        if params and params[0] == "data_dir":
            public_views.add(name)
    assert public_views == set(rf_read.VIEW_ENTRY_POINTS), (
        f"undeclared public view(s): {sorted(public_views - set(rf_read.VIEW_ENTRY_POINTS))}; "
        f"declared but gone: {sorted(set(rf_read.VIEW_ENTRY_POINTS) - public_views)}")


def test_the_scope_is_re_entrant_and_the_outermost_one_owns_the_drop(tmp_path, monkeypatch):
    """A read model calling another read model must not have its cache dropped halfway by the
    inner one's bookkeeping — and the state before the outermost scope must come back."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    assert hl.read_cache_depth() == 0 and hl._READ_CACHE_ENABLED is False
    with hl.read_cache():
        assert hl.read_cache_depth() == 1 and hl._READ_CACHE_ENABLED is True
        led.read_all()
        assert hl._READ_CACHE != {}
        with hl.read_cache():
            assert hl.read_cache_depth() == 2
        assert hl._READ_CACHE != {}, "the inner scope dropped the outer scope's cache"
        assert hl._READ_CACHE_ENABLED is True
    assert hl.read_cache_depth() == 0 and hl._READ_CACHE_ENABLED is False and hl._READ_CACHE == {}


def test_the_scope_restores_an_already_enabled_state_instead_of_forcing_it_off(tmp_path):
    """Restoring means restoring, in both directions: a process that had the cache on before the
    scope keeps it on after. Forcing `False` on exit would make the scope a silent off-switch."""
    hl._READ_CACHE_ENABLED = True
    try:
        with hl.read_cache():
            assert hl._READ_CACHE_ENABLED is True
        assert hl._READ_CACHE_ENABLED is True
    finally:
        hl._READ_CACHE_ENABLED = False
        hl._READ_CACHE.clear()


def test_the_scope_closes_even_when_the_reader_raises(tmp_path):
    """A read model that fails must not leave the process cached forever — that is exactly the
    permanent-flag behaviour this change removes."""
    class Boom(Exception):
        pass
    try:
        with hl.read_cache():
            raise Boom
    except Boom:
        pass
    assert hl._READ_CACHE_ENABLED is False and hl.read_cache_depth() == 0 and hl._READ_CACHE == {}


def test_the_switch_has_exactly_one_door(tmp_path):
    """One rule, one copy: no module outside `hash_ledger.py` may flip `_READ_CACHE_ENABLED`
    itself, and the permanent `enable_read_cache()` is gone. Measured by AST over the shipped
    tree — a comment or a docstring mentioning the name is not a flip."""
    import ast

    root = Path(__file__).resolve().parents[2]
    owner = root / "spa_core" / "utils" / "hash_ledger.py"
    offenders, unparsed = [], []
    for sub in ("spa_core", "scripts"):
        for f in sorted((root / sub).rglob("*.py")):
            if f == owner or "/tests/" in str(f) or f.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                unparsed.append(f"{f.relative_to(root)}: {type(exc).__name__}: {exc}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        nm = t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", None)
                        if nm in ("_READ_CACHE_ENABLED", "_READ_CACHE_DEPTH"):
                            offenders.append(f"{f.relative_to(root)}:{node.lineno} assigns {nm}")
                if isinstance(node, ast.Call):
                    fn = node.func
                    nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                    if nm == "enable_read_cache":
                        offenders.append(f"{f.relative_to(root)}:{node.lineno} calls enable_read_cache()")
    # Third outcome (inv. #17): a file we could not parse is NOT a clean pass.
    assert not unparsed, f"NOT MEASURED — unparsed: {unparsed}"
    assert not offenders, f"second copy of the read-cache switch: {offenders}"
    assert not hasattr(hl, "enable_read_cache"), "the permanent process-wide switch is back"


def test_the_one_door_guard_can_actually_fail():
    """Negative control for the guard above: it must see a planted flip. A guard that has never
    seen the failure it is written for is decoration (`.claude/rules/deployment.md`)."""
    import ast
    planted = ("from spa_core.utils import hash_ledger as hl\n"
               "hl._READ_CACHE_ENABLED = True\n")
    found = [n for n in ast.walk(ast.parse(planted))
             if isinstance(n, ast.Assign)
             and any(getattr(t, "attr", getattr(t, "id", None)) == "_READ_CACHE_ENABLED" for t in n.targets)]
    assert found, "the AST shape the guard looks for does not match a real flip"


# ── ARB 16.10: nested mutation, file replacement, read during write, verify independent of the cache ──

def test_a_reader_cannot_change_nested_cached_objects(tmp_path, monkeypatch, cache_on):
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"cells": {"apy": {"value": 1.0}}, "tags": ["a"]}, ts(1))
    row = led.read_all()[0]
    with pytest.raises(TypeError):
        row["payload"]["cells"]["apy"]["value"] = 99.0
    with pytest.raises(TypeError):
        row["payload"]["tags"].append("b")
    with pytest.raises(TypeError):
        row.setdefault("x", 1)
    mine = dict(row["payload"])                          # the documented way to change a copy
    mine["cells"] = {"apy": {"value": 2.0}}
    again = led.read_all()[0]
    assert again["payload"]["cells"]["apy"]["value"] == 1.0 and again["payload"]["tags"] == ["a"]
    assert json.loads(json.dumps(again)) == again        # serialises exactly like a plain row


def test_replaced_file_new_inode_is_a_miss(tmp_path, monkeypatch, cache_on):
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    led.read_all()
    p = led.ledger_path()
    row = json.loads(p.read_text())
    row["payload"]["x"] = 7
    tmp = p.with_name("swap.tmp")
    tmp.write_text(json.dumps(row) + "\n")
    st = p.stat()
    os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))  # same size and mtime, different inode
    os.replace(tmp, p)
    assert led.read_all()[0]["payload"]["x"] == 7


def test_a_file_growing_while_parsed_is_not_cached(tmp_path, monkeypatch, cache_on):
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    writer = _ledger(tmp_path)
    orig = hl.HashLedger._parse

    def parse_then_writer_appends(path):
        out = orig(path)
        if not getattr(parse_then_writer_appends, "done", False):
            parse_then_writer_appends.done = True
            writer.append("run", ["r2"], {"x": 2}, ts(0))
        return out
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(parse_then_writer_appends))
    first = led.read_all()
    assert len(first) == 1
    now_ident = hl._file_identity(led.ledger_path())
    # nothing is cached under the file's CURRENT identity with the pre-append rows
    assert all(ident != now_ident or len(rows) == 2 for ident, rows in hl._READ_CACHE.values())
    assert len(led.read_all()) == 2


def test_verify_never_answers_from_the_cache(tmp_path, monkeypatch, cache_on):
    """Tamper the file keeping size AND mtime: the cache would still serve the old rows, verify must not."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    assert led.verify()["ok"] is True
    led.read_all()                                        # cache is hot
    p = led.ledger_path()
    st = p.stat()
    raw = p.read_text()
    assert '"x":1' in raw
    p.write_text(raw.replace('"x":1', '"x":2'))           # same length
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert led.read_all()[0]["payload"]["x"] == 1         # documents the cache's blind spot …
    assert led.verify()["ok"] is False                    # … which integrity verification does NOT share

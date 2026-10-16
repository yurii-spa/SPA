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


def test_mission_build_main_opts_in(monkeypatch, tmp_path):
    from spa_core.studio_os import mission_build as mb
    monkeypatch.setattr(hl, "_READ_CACHE_ENABLED", False)
    monkeypatch.setattr(mb, "build_bundle", lambda *a, **k: (_ for _ in ()).throw(mb.BuildError("stop")))
    assert mb.main(["--root", str(tmp_path)]) == 2
    assert hl._READ_CACHE_ENABLED is True


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

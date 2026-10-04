"""Tests for spa_core/utils/hash_ledger.py (ADR-560, Research Factory Package A).

No freshness/calendar concept is exercised here (the ``at`` field is an opaque caller-supplied
string, never parsed or compared to now) so the frozen-date ratchet does not apply to this file.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from spa_core.utils.hash_ledger import (
    DuplicateKey, GENESIS, HashLedger, LedgerError, LockBusy, RunLocked,
)


def _mk(tmp_path: Path) -> HashLedger:
    return HashLedger(tmp_path, "my_ledger", "my_ledger_anchors", "ledger.jsonl")


# ── basic append / read ─────────────────────────────────────────────────────────────────────

def test_append_and_read_roundtrip(tmp_path):
    led = _mk(tmp_path)
    e1 = led.append("widget", ["w1"], {"color": "red"}, "t1")
    e2 = led.append("widget", ["w2"], {"color": "blue"}, "t2")
    assert [e["seq"] for e in (e1, e2)] == [1, 2]
    assert e1["prev_hash"] == GENESIS
    assert e2["prev_hash"] == e1["entry_hash"]
    all_rows = led.read_all()
    assert len(all_rows) == 2
    assert all_rows[0]["payload"] == {"color": "red"}


def test_find_returns_entry_or_none(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {"color": "red"}, "t1")
    found = led.find("widget", ["w1"])
    assert found is not None and found["payload"]["color"] == "red"
    assert led.find("widget", ["nope"]) is None
    assert led.find("other_kind", ["w1"]) is None


def test_head_hash_genesis_then_tracks_tail(tmp_path):
    led = _mk(tmp_path)
    assert led.head_hash() == GENESIS
    e1 = led.append("widget", ["w1"], {}, "t1")
    assert led.head_hash() == e1["entry_hash"]
    e2 = led.append("widget", ["w2"], {}, "t2")
    assert led.head_hash() == e2["entry_hash"]


def test_duplicate_key_raises_and_carries_existing(tmp_path):
    led = _mk(tmp_path)
    first = led.append("widget", ["w1"], {"color": "red"}, "t1")
    with pytest.raises(DuplicateKey) as excinfo:
        led.append("widget", ["w1"], {"color": "green"}, "t2")
    assert excinfo.value.existing == first
    # the ledger was NOT mutated by the refused second write
    assert led.read_all() == [first]


def test_append_idempotent_wraps_duplicate(tmp_path):
    led = _mk(tmp_path)
    first, created1 = led.append_idempotent("widget", ["w1"], {"color": "red"}, "t1")
    second, created2 = led.append_idempotent("widget", ["w1"], {"color": "red"}, "t1")
    assert created1 is True
    assert created2 is False
    assert second == first
    assert len(led.read_all()) == 1


def test_a_torn_line_raises_ledger_error_on_read(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    with open(led.ledger_path(), "a") as f:
        f.write("{not json\n")
    with pytest.raises(LedgerError):
        led.read_all()


# ── verify() ─────────────────────────────────────────────────────────────────────────────────

def test_verify_ok_on_empty_and_growing_ledger(tmp_path):
    led = _mk(tmp_path)
    v = led.verify()
    assert v == {"ok": True, "break_at": None, "entries": 0, "reason": None}
    led.append("widget", ["w1"], {}, "t1")
    led.append("widget", ["w2"], {}, "t2")
    v2 = led.verify()
    assert v2["ok"] is True and v2["entries"] == 2


def _rewrite_lines(path: Path, lines: list[dict]) -> None:
    text = "\n".join(json.dumps(x, sort_keys=True) for x in lines) + "\n"
    path.write_text(text)


def test_verify_detects_a_chain_break(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    led.append("widget", ["w2"], {}, "t2")
    rows = led.read_all()
    rows[1]["payload"] = {"tampered": True}  # entry_hash no longer matches recomputed hash
    _rewrite_lines(led.ledger_path(), rows)
    v = led.verify()
    assert v["ok"] is False
    assert v["reason"] == "chain"
    assert v["break_at"] == 2


def test_verify_detects_anchor_missing(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    led.anchors_path().write_text("")  # wipe the sibling anchors file
    v = led.verify()
    assert v == {"ok": False, "break_at": 1, "entries": 1, "reason": "anchor_missing"}


def test_verify_detects_anchor_mismatch(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    anchors = led.read_anchors()
    anchors[0]["entry_hash"] = "0" * 64
    _rewrite_lines(led.anchors_path(), anchors)
    v = led.verify()
    assert v["ok"] is False
    assert v["reason"] == "anchor_mismatch"


def test_verify_detects_ledger_truncated(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    led.append("widget", ["w2"], {}, "t2")
    rows = led.read_all()
    _rewrite_lines(led.ledger_path(), rows[:1])  # drop the tail row; its anchor still exists
    v = led.verify()
    assert v["ok"] is False
    assert v["reason"] == "ledger_truncated"


def test_verify_detects_anchor_duplicate(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    anchors = led.read_anchors()
    _rewrite_lines(led.anchors_path(), anchors + anchors)  # same seq recorded twice
    v = led.verify()
    assert v["ok"] is False
    assert v["reason"] == "anchor_duplicate"


def test_append_refuses_on_already_broken_chain(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    led.anchors_path().write_text("")
    with pytest.raises(LedgerError):
        led.append("widget", ["w2"], {}, "t2")


# ── anchors are never silently glued across a crash ───────────────────────────────────────────

def test_anchors_survive_in_a_sibling_directory(tmp_path):
    led = _mk(tmp_path)
    led.append("widget", ["w1"], {}, "t1")
    assert led.root() != led.anchors_root()
    assert led.anchors_root().exists()
    # wiping the primary ledger directory never touches the sibling anchors directory
    import shutil
    shutil.rmtree(led.root())
    assert led.anchors_path().exists()


# ── file_lock (blocking) ────────────────────────────────────────────────────────────────────

def _hold_file_lock_for(path_str: str, hold_s: float, ready_evt, release_evt) -> None:
    led = HashLedger(Path(path_str), "my_ledger", "my_ledger_anchors", "ledger.jsonl")
    with led.file_lock(timeout_s=10.0):
        ready_evt.set()
        release_evt.wait(timeout=hold_s + 5)


def test_file_lock_blocks_until_released_then_succeeds(tmp_path):
    led = _mk(tmp_path)
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    proc = multiprocessing.Process(target=_hold_file_lock_for, args=(str(tmp_path), 0.0, ready, release))
    proc.start()
    assert ready.wait(timeout=5), "holder never signalled readiness"
    # the holder is alive and waiting on `release` — a generous timeout must wait it out and
    # still succeed once we release it a moment later, proving the lock was really exclusive.
    import threading
    threading.Timer(0.3, release.set).start()
    start = time.monotonic()
    with led.file_lock(timeout_s=5.0):
        pass
    elapsed = time.monotonic() - start
    assert elapsed >= 0.25, "acquired the lock suspiciously fast — was it exclusive at all?"
    proc.join(timeout=5)
    assert not proc.is_alive()


def test_file_lock_raises_lock_busy_on_timeout(tmp_path):
    led = _mk(tmp_path)
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    proc = multiprocessing.Process(target=_hold_file_lock_for, args=(str(tmp_path), 1.0, ready, release))
    proc.start()
    try:
        assert ready.wait(timeout=5), "holder never signalled readiness"
        with pytest.raises(LockBusy):
            with led.file_lock(timeout_s=0.1):
                pass
    finally:
        release.set()
        proc.join(timeout=5)


# ── run_lock (non-blocking) ─────────────────────────────────────────────────────────────────

def _hold_run_lock_for(path_str: str, hold_s: float, ready_evt, release_evt) -> None:
    led = HashLedger(Path(path_str), "my_ledger", "my_ledger_anchors", "ledger.jsonl")
    with led.run_lock():
        ready_evt.set()
        release_evt.wait(timeout=hold_s + 5)


def test_run_lock_raises_run_locked_immediately_when_held(tmp_path):
    led = _mk(tmp_path)
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    proc = multiprocessing.Process(target=_hold_run_lock_for, args=(str(tmp_path), 2.0, ready, release))
    proc.start()
    try:
        assert ready.wait(timeout=5), "holder never signalled readiness"
        start = time.monotonic()
        with pytest.raises(RunLocked):
            with led.run_lock():
                pass
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, "run_lock blocked instead of refusing immediately"
    finally:
        release.set()
        proc.join(timeout=5)


def test_run_lock_available_again_after_release(tmp_path):
    led = _mk(tmp_path)
    with led.run_lock():
        pass
    with led.run_lock():  # a second, SEQUENTIAL acquisition must succeed
        pass


# ── single write + fsync per line ───────────────────────────────────────────────────────────

def test_append_issues_exactly_one_os_write_for_the_line(tmp_path, monkeypatch):
    led = _mk(tmp_path)
    calls = []
    real_write = os.write

    def counting_write(fd, data):
        calls.append((fd, data))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", counting_write)
    led.append("widget", ["w1"], {"color": "red"}, "t1")
    ledger_writes = [c for c in calls if c[1].strip().startswith(b'{"at"')]
    assert len(ledger_writes) == 1, "the ledger line was not written with a single os.write() call"


# ── concurrent writers (real multiprocessing) ──────────────────────────────────────────────

def _writer(path_str: str, kind: str, key: list, payload: dict, at: str, barrier) -> None:
    led = HashLedger(Path(path_str), "my_ledger", "my_ledger_anchors", "ledger.jsonl")
    barrier.wait()
    try:
        led.append(kind, key, payload, at)
    except DuplicateKey:
        pass


def test_concurrent_writers_of_the_same_key_yield_one_row(tmp_path):
    n = 6
    barrier = multiprocessing.Barrier(n)
    procs = [multiprocessing.Process(target=_writer,
                                     args=(str(tmp_path), "candidate_snapshot", ["same-key"],
                                           {"i": i}, "t1", barrier))
             for i in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=10)
        assert not p.is_alive()
    led = _mk(tmp_path)
    rows = [e for e in led.read_all() if e["kind"] == "candidate_snapshot" and e["key"] == ["same-key"]]
    assert len(rows) == 1
    v = led.verify()
    assert v["ok"], v


def test_concurrent_writers_of_different_keys_all_land(tmp_path):
    n = 5
    barrier = multiprocessing.Barrier(n)
    procs = [multiprocessing.Process(target=_writer,
                                     args=(str(tmp_path), "candidate_snapshot", [f"key-{i}"],
                                           {"i": i}, "t1", barrier))
             for i in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=10)
        assert not p.is_alive()
    led = _mk(tmp_path)
    rows = led.read_all()
    assert len(rows) == n
    v = led.verify()
    assert v["ok"], v

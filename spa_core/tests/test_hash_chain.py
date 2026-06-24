"""
spa_core/tests/test_hash_chain.py — tests for the tamper-evident hash-chained audit trail.

Every test redirects the chain file to a tmp_path so the real
data/audit_chain.jsonl is never touched.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest

from spa_core.audit import hash_chain


@pytest.fixture
def chain(tmp_path, monkeypatch):
    """Point the module at an isolated tmp chain file for each test."""
    p = tmp_path / "audit_chain.jsonl"
    monkeypatch.setattr(hash_chain, "_CHAIN", p)
    return p


# --------------------------------------------------------------------------- #
def test_empty_chain_head_and_verify(chain):
    assert hash_chain.head() is None
    assert hash_chain.tail() == []
    v = hash_chain.verify_chain()
    assert v == {"valid": True, "length": 0, "broken_at": None}


def test_genesis_prev_hash(chain):
    e = hash_chain.append("cycle", {"k": 1}, ts="2026-06-24T08:00:00+00:00")
    assert e["seq"] == 0
    assert e["prev_hash"] == hash_chain.GENESIS_PREV
    assert e["prev_hash"] == "0" * 64
    assert len(e["entry_hash"]) == 64


def test_append_links_prev_hash(chain):
    e0 = hash_chain.append("cycle", {"n": 0}, ts="2026-06-24T08:00:00+00:00")
    e1 = hash_chain.append("cycle", {"n": 1}, ts="2026-06-24T08:01:00+00:00")
    e2 = hash_chain.append("risk_event", {"reason": "x"}, ts="2026-06-24T08:02:00+00:00")

    # Each entry's prev_hash is the previous entry's entry_hash.
    assert e1["prev_hash"] == e0["entry_hash"]
    assert e2["prev_hash"] == e1["entry_hash"]
    # Monotonic seq.
    assert [e0["seq"], e1["seq"], e2["seq"]] == [0, 1, 2]


def test_verify_valid_after_appends(chain):
    for i in range(5):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")
    v = hash_chain.verify_chain()
    assert v["valid"] is True
    assert v["length"] == 5
    assert v["broken_at"] is None


def test_determinism_same_inputs_same_hash():
    """Same inputs + ts → identical entry_hash, independent of any chain file."""
    h1 = hash_chain.compute_entry_hash(
        3, "2026-06-24T08:00:00+00:00", "cycle", {"a": 1, "b": [2, 3]}, "ab" * 32
    )
    h2 = hash_chain.compute_entry_hash(
        3, "2026-06-24T08:00:00+00:00", "cycle", {"b": [2, 3], "a": 1}, "ab" * 32
    )
    # Key order in the payload must NOT change the hash (canonical sort_keys).
    assert h1 == h2
    # And it is the real sha256, not some accidental constant.
    assert h1 != hash_chain.compute_entry_hash(
        3, "2026-06-24T08:00:00+00:00", "cycle", {"a": 2}, "ab" * 32
    )


def test_tamper_middle_entry_detected(chain):
    """Mutate a middle entry's payload ON DISK → verify_chain reports the break."""
    for i in range(5):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")
    assert hash_chain.verify_chain()["valid"] is True

    # Read raw lines, mutate entry seq=2's payload, write back (entry_hash left stale).
    lines = chain.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[2])
    entry["payload"] = {"i": 999}  # tampered value
    lines[2] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = hash_chain.verify_chain()
    assert v["valid"] is False
    assert v["broken_at"] == 2
    assert v["length"] == 5


def test_tamper_rewrite_hash_breaks_linkage(chain):
    """Recomputing the tampered entry's OWN hash still breaks the next entry's prev_hash."""
    for i in range(4):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")

    lines = chain.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["payload"] = {"i": 777}
    # Forge a self-consistent entry_hash for the tampered entry...
    entry["entry_hash"] = hash_chain.compute_entry_hash(
        entry["seq"], entry["ts"], entry["event_type"], entry["payload"], entry["prev_hash"]
    )
    lines[1] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Entry 1 verifies internally now, but entry 2's prev_hash no longer matches → break at 2.
    v = hash_chain.verify_chain()
    assert v["valid"] is False
    assert v["broken_at"] == 2


def test_record_helpers(chain):
    c = hash_chain.record_cycle({"equity_usd": 100149.54}, ts="2026-06-24T08:00:00+00:00")
    r = hash_chain.record_risk_event("kill switch armed", ts="2026-06-24T08:05:00+00:00")
    assert c["event_type"] == "cycle"
    assert r["event_type"] == "risk_event"
    assert r["payload"] == {"reason": "kill switch armed"}
    assert r["prev_hash"] == c["entry_hash"]
    assert hash_chain.verify_chain()["valid"] is True


def test_head_and_tail(chain):
    first = hash_chain.append("cycle", {"i": 0}, ts="2026-06-24T08:00:00+00:00")
    for i in range(1, 6):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")
    assert hash_chain.head() == first
    t = hash_chain.tail(3)
    assert len(t) == 3
    assert [e["payload"]["i"] for e in t] == [3, 4, 5]


def test_persistence_across_reads(chain):
    """Atomic write + re-read returns the same chain (no torn lines)."""
    hash_chain.append("cycle", {"i": 0}, ts="2026-06-24T08:00:00+00:00")
    hash_chain.append("cycle", {"i": 1}, ts="2026-06-24T08:01:00+00:00")
    reread = hash_chain._read_all()
    assert len(reread) == 2
    assert reread[0]["payload"] == {"i": 0}
    # No stray tmp files left behind.
    leftovers = list(chain.parent.glob(".audit_chain_*"))
    assert leftovers == []

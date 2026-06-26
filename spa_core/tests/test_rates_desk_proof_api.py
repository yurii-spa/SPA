"""
Tests for the Rates-Desk PROOF surface — GET /api/rates-desk/proof.

The public, tamper-evident verification surface over the decision log
(data/rates_desk/decision_log.jsonl). The endpoint actually re-derives the hash chain over the
public mirror and reports whether it is intact, so:

  - a well-formed log self-verifies (verified=true) and reports chain_length + head_hash,
  - flipping ANY past decision breaks prev-linkage → verified=false + broken_at=that seq,
  - an absent log is vacuously intact (verified=true, length 0) and never 500s.

Run:
    python -m pytest spa_core/tests/test_rates_desk_proof_api.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402
from spa_core.audit import hash_chain  # noqa: E402

EVENT_TYPE = "rates_desk_decision"


# ── Helpers ─────────────────────────────────────────────────────────────────────
def _payload(seq: int, *, approved: bool, underlying: str, total_haircut: str) -> dict:
    """A minimal but representative decision_payload (the hash-covered body)."""
    return {
        "kind": "ENTRY" if approved else "REFUSAL",
        "approved": approved,
        "reason": "none" if approved else "tail_veto",
        "as_of": "2026-06-25",
        "underlying": underlying,
        "shape": "fixed_carry",
        "net_edge": "0.05" if approved else "-0.10",
        "approved_size_usd": "10000" if approved else "0",
        "decomposition": {"underlying": underlying, "total_haircut": total_haircut},
        "detail": {"note": "priced carry" if approved else "tail-comp veto"},
        "proof_hash": f"deadbeef{seq:04d}",
    }


def _write_chain(path: Path, payloads: list) -> list:
    """Write a VALID hash-chained decision_log.jsonl, returning the mirror rows.

    Each row is {seq, ts, entry_hash, prev_hash, **payload} with entry_hash computed exactly the
    way the server re-derives it (hash_chain.compute_entry_hash over the payload) — so the file
    is a genuine, internally-consistent chain.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    prev = hash_chain.GENESIS_PREV
    for seq, pl in enumerate(payloads):
        ts = "2026-06-25T00:00:00+00:00"
        eh = hash_chain.compute_entry_hash(seq, ts, EVENT_TYPE, pl, prev)
        rows.append({"seq": seq, "ts": ts, "entry_hash": eh, "prev_hash": prev, **pl})
        prev = eh
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n",
        encoding="utf-8",
    )
    return rows


@pytest.fixture()
def proof_client(tmp_path, monkeypatch):
    """TestClient with the server's data dir redirected to a hermetic tmp dir."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


# ── Tests ────────────────────────────────────────────────────────────────────────
def test_proof_returns_chain_summary_and_verified(proof_client):
    """A well-formed log: 200, verified=true, chain_length + head_hash + counts + last_n."""
    client, data_dir = proof_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    rows = _write_chain(log, [
        _payload(0, approved=False, underlying="eeth", total_haircut="0.16"),
        _payload(1, approved=False, underlying="susde", total_haircut="0.13"),
        _payload(2, approved=True, underlying="ptusdc", total_haircut="0.02"),
    ])

    r = client.get("/api/rates-desk/proof")
    assert r.status_code == 200
    d = r.json()
    assert d["verified"] is True
    assert d["broken_at"] is None
    assert d["chain_length"] == 3
    assert d["head_hash"] == rows[-1]["entry_hash"]
    assert d["counts"] == {"ENTRY": 1, "REFUSAL": 2}
    # last_n carries the public verdict view.
    last = d["last_n_decisions"]
    assert len(last) == 3
    assert last[-1]["allowed"] is True
    assert last[0]["kind"] == "REFUSAL"
    assert last[0]["payload_hash"] == "deadbeef0000"
    assert last[0]["haircut_total"] == "0.16"


def test_proof_last_n_limit(proof_client):
    """last_n bounds the returned decisions but verify still covers the WHOLE chain."""
    client, data_dir = proof_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [
        _payload(i, approved=False, underlying=f"u{i}", total_haircut="0.15")
        for i in range(10)
    ])
    r = client.get("/api/rates-desk/proof?last_n=3")
    assert r.status_code == 200
    d = r.json()
    assert d["chain_length"] == 10          # verify covers all 10
    assert len(d["last_n_decisions"]) == 3  # but only 3 returned
    assert d["verified"] is True


def test_proof_detects_tampered_entry(proof_client):
    """Flipping a past decision (REFUSAL→approved) must break the chain → verified=false."""
    client, data_dir = proof_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [
        _payload(0, approved=False, underlying="eeth", total_haircut="0.16"),
        _payload(1, approved=False, underlying="susde", total_haircut="0.13"),
        _payload(2, approved=True, underlying="ptusdc", total_haircut="0.02"),
    ])

    # Tamper: rewrite history — flip the first REFUSAL to look like an approval, WITHOUT
    # recomputing the hashes (an attacker rewriting the public record).
    lines = log.read_text(encoding="utf-8").splitlines()
    row0 = json.loads(lines[0])
    row0["approved"] = True
    row0["kind"] = "ENTRY"
    lines[0] = json.dumps(row0, sort_keys=True, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    r = client.get("/api/rates-desk/proof")
    assert r.status_code == 200
    d = r.json()
    assert d["verified"] is False
    assert d["broken_at"] == 0      # the very first entry no longer hashes to its stored hash


def test_proof_detects_broken_linkage(proof_client):
    """Editing an entry's payload mid-chain (keeping its stored hash) breaks its self-recompute."""
    client, data_dir = proof_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [
        _payload(0, approved=False, underlying="eeth", total_haircut="0.16"),
        _payload(1, approved=False, underlying="susde", total_haircut="0.13"),
        _payload(2, approved=True, underlying="ptusdc", total_haircut="0.02"),
    ])
    lines = log.read_text(encoding="utf-8").splitlines()
    # Tamper entry seq=1's payload but keep its stored entry_hash (so its OWN hash check fails first).
    row1 = json.loads(lines[1])
    row1["net_edge"] = "999.0"
    lines[1] = json.dumps(row1, sort_keys=True, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    d = client.get("/api/rates-desk/proof").json()
    assert d["verified"] is False
    assert d["broken_at"] == 1


def test_proof_graceful_when_no_log(proof_client):
    """No decision log at all: vacuously intact (verified=true, length 0), never a 500."""
    client, _ = proof_client  # tmp_path has no rates_desk/decision_log.jsonl
    r = client.get("/api/rates-desk/proof")
    assert r.status_code == 200
    d = r.json()
    assert d["verified"] is True
    assert d["chain_length"] == 0
    assert d["head_hash"] is None
    assert d["last_n_decisions"] == []
    assert d["counts"] == {"ENTRY": 0, "REFUSAL": 0}


def test_proof_corrupt_line_fails_closed(proof_client):
    """A corrupt (non-JSON) line in the log is treated as tamper evidence → verified=false."""
    client, data_dir = proof_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [_payload(0, approved=True, underlying="ptusdc", total_haircut="0.02")])
    with log.open("a", encoding="utf-8") as f:
        f.write("{ this is not valid json\n")
    d = client.get("/api/rates-desk/proof").json()
    assert d["verified"] is False

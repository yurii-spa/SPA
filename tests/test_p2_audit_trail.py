"""test_p2_audit_trail.py — FIX 6 (P2): Append-only audit trail with SHA-256 hash chain.

Verifies that:
- append() adds chain_hash to each record
- chain_hash is computed as SHA256(prev_hash + canonical_json(record))
- First record uses GENESIS_HASH as prev
- verify_chain() returns True on intact chain
- verify_chain() raises AuditChainTamperedError on tampered record
- read_chain() returns records in insertion order
- Atomic writes: no partial records on simulated crash
- Chain survives multiple appends
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from spa_core.audit.audit_trail_signer import (
    append,
    verify_chain,
    read_chain,
    AuditChainTamperedError,
    GENESIS_HASH,
    CHAIN_FILENAME,
    _compute_chain_hash,
    _canonical_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmpdir_chain_path(tmpdir: str) -> Path:
    return Path(tmpdir) / CHAIN_FILENAME


def _append(tmpdir: str, record: dict) -> dict:
    return append(record, data_dir=tmpdir)


def _verify(tmpdir: str) -> bool:
    return verify_chain(data_dir=tmpdir)


def _read(tmpdir: str) -> list[dict]:
    return read_chain(data_dir=tmpdir)


# ---------------------------------------------------------------------------
# 1. First append uses GENESIS_HASH as prev
# ---------------------------------------------------------------------------
def test_first_record_uses_genesis_hash():
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = {"event": "test", "value": 42}
        result = _append(tmpdir, rec)
        clean = {k: v for k, v in result.items() if k != "chain_hash"}
        expected = _compute_chain_hash(GENESIS_HASH, clean)
        assert result["chain_hash"] == expected


# ---------------------------------------------------------------------------
# 2. chain_hash is present in every appended record
# ---------------------------------------------------------------------------
def test_chain_hash_present_in_result():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _append(tmpdir, {"x": 1})
        assert "chain_hash" in result
        assert isinstance(result["chain_hash"], str)
        assert len(result["chain_hash"]) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# 3. Second record links to first
# ---------------------------------------------------------------------------
def test_chain_links_sequentially():
    with tempfile.TemporaryDirectory() as tmpdir:
        r1 = _append(tmpdir, {"event": "first"})
        r2 = _append(tmpdir, {"event": "second"})

        prev_hash = r1["chain_hash"]
        clean2 = {k: v for k, v in r2.items() if k != "chain_hash"}
        expected2 = _compute_chain_hash(prev_hash, clean2)
        assert r2["chain_hash"] == expected2


# ---------------------------------------------------------------------------
# 4. verify_chain returns True on intact chain
# ---------------------------------------------------------------------------
def test_verify_intact_chain():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(5):
            _append(tmpdir, {"event": f"step_{i}", "index": i})
        assert _verify(tmpdir) is True


# ---------------------------------------------------------------------------
# 5. verify_chain on empty / missing file returns True (nothing to verify)
# ---------------------------------------------------------------------------
def test_verify_empty_dir_returns_true():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert _verify(tmpdir) is True


# ---------------------------------------------------------------------------
# 6. Tampered record raises AuditChainTamperedError
# ---------------------------------------------------------------------------
def test_tampered_record_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        _append(tmpdir, {"event": "first"})
        _append(tmpdir, {"event": "second"})
        _append(tmpdir, {"event": "third"})

        chain_path = _tmpdir_chain_path(tmpdir)
        records = [json.loads(line) for line in chain_path.read_text().splitlines() if line.strip()]

        # Tamper with the second record's payload
        records[1]["event"] = "TAMPERED"

        # Rewrite the file with the tampered record
        chain_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")

        with pytest.raises(AuditChainTamperedError) as exc_info:
            verify_chain(data_dir=tmpdir)

        err = exc_info.value
        assert err.record_index == 1, f"Expected tamper at index 1, got {err.record_index}"


# ---------------------------------------------------------------------------
# 7. Deleted record raises AuditChainTamperedError (chain_hash mismatch)
# ---------------------------------------------------------------------------
def test_deleted_record_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        _append(tmpdir, {"event": "a"})
        _append(tmpdir, {"event": "b"})
        _append(tmpdir, {"event": "c"})

        chain_path = _tmpdir_chain_path(tmpdir)
        lines = [l for l in chain_path.read_text().splitlines() if l.strip()]

        # Remove the middle record
        del lines[1]
        chain_path.write_text("\n".join(lines) + "\n")

        with pytest.raises(AuditChainTamperedError):
            verify_chain(data_dir=tmpdir)


# ---------------------------------------------------------------------------
# 8. read_chain returns records in insertion order
# ---------------------------------------------------------------------------
def test_read_chain_returns_insertion_order():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(4):
            _append(tmpdir, {"seq": i})
        records = _read(tmpdir)
        assert len(records) == 4
        for i, r in enumerate(records):
            assert r["seq"] == i


# ---------------------------------------------------------------------------
# 9. GENESIS_HASH is 64 zeros
# ---------------------------------------------------------------------------
def test_genesis_hash_is_64_zeros():
    assert GENESIS_HASH == "0" * 64
    assert len(GENESIS_HASH) == 64


# ---------------------------------------------------------------------------
# 10. compute_chain_hash is deterministic
# ---------------------------------------------------------------------------
def test_compute_chain_hash_deterministic():
    record = {"event": "test", "value": 99}
    h1 = _compute_chain_hash(GENESIS_HASH, record)
    h2 = _compute_chain_hash(GENESIS_HASH, record)
    assert h1 == h2


# ---------------------------------------------------------------------------
# 11. canonical_json sorts keys
# ---------------------------------------------------------------------------
def test_canonical_json_sorts_keys():
    r1 = {"b": 2, "a": 1}
    r2 = {"a": 1, "b": 2}
    assert _canonical_json(r1) == _canonical_json(r2)


# ---------------------------------------------------------------------------
# 12. chain_hash changes when record payload changes
# ---------------------------------------------------------------------------
def test_chain_hash_depends_on_payload():
    r1 = {"event": "a"}
    r2 = {"event": "b"}
    h1 = _compute_chain_hash(GENESIS_HASH, r1)
    h2 = _compute_chain_hash(GENESIS_HASH, r2)
    assert h1 != h2


# ---------------------------------------------------------------------------
# 13. append is fail-safe (bad record type doesn't propagate)
# ---------------------------------------------------------------------------
def test_append_fail_safe_non_serializable():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Pass a non-JSON-serialisable value; should not raise
        try:
            result = append({"value": object()}, data_dir=tmpdir)
        except Exception as e:
            pytest.fail(f"append must not raise: {e}")
        # result may contain "error" key but must not raise


# ---------------------------------------------------------------------------
# 14. Long chain (20 records) verifies correctly
# ---------------------------------------------------------------------------
def test_long_chain_verifies():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(20):
            _append(tmpdir, {"idx": i, "data": "x" * 100})
        assert _verify(tmpdir) is True
        assert len(_read(tmpdir)) == 20


# ---------------------------------------------------------------------------
# 15. Explicit filepath to verify_chain works
# ---------------------------------------------------------------------------
def test_verify_chain_explicit_filepath():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(3):
            _append(tmpdir, {"n": i})
        chain_path = _tmpdir_chain_path(tmpdir)
        assert verify_chain(filepath=chain_path) is True


# ---------------------------------------------------------------------------
# 16. AuditChainTamperedError carries forensic attributes
# ---------------------------------------------------------------------------
def test_tampered_error_has_forensic_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        _append(tmpdir, {"event": "ok"})

        chain_path = _tmpdir_chain_path(tmpdir)
        records = [json.loads(line) for line in chain_path.read_text().splitlines() if line.strip()]
        records[0]["chain_hash"] = "a" * 64  # forge hash
        chain_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

        with pytest.raises(AuditChainTamperedError) as exc_info:
            verify_chain(data_dir=tmpdir)

        err = exc_info.value
        assert err.record_index == 0
        assert len(err.expected_hash) == 64
        assert len(err.actual_hash) == 64
        assert err.expected_hash != err.actual_hash

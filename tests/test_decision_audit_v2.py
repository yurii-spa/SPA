"""
tests/test_decision_audit_v2.py
25 unit tests for spa_core/analytics/decision_audit_trail.py (MP-1533 v11.49)
"""
import json
import os
import tempfile

import pytest

from spa_core.analytics.decision_audit_trail import DecisionAuditTrail, MAX_FILE_BYTES


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def trail(tmp_dir):
    return DecisionAuditTrail(base_dir=tmp_dir)


# ── test 1: log returns a correlation_id ────────────────────────────────────

def test_log_returns_correlation_id(trail):
    cid = trail.log("gate_check", "RiskPolicy gate")
    assert isinstance(cid, str)
    assert len(cid) > 0


# ── test 2: auto-generated cid is 8 chars ────────────────────────────────────

def test_auto_cid_length(trail):
    cid = trail.log("gate_check", "test")
    assert len(cid) == 8


# ── test 3: supplied cid is reused ───────────────────────────────────────────

def test_supplied_cid_reused(trail):
    cid = trail.log("allocation", "alloc step", correlation_id="cycle001")
    assert cid == "cycle001"


# ── test 4: creates file if not exists ───────────────────────────────────────

def test_creates_file(trail):
    path = trail._path
    assert not os.path.exists(path)
    trail.log("gate_check", "create test")
    assert os.path.exists(path)


# ── test 5: creates data dir ─────────────────────────────────────────────────

def test_creates_data_dir(tmp_dir):
    trail = DecisionAuditTrail(base_dir=tmp_dir)
    trail.log("alert", "dir test")
    assert os.path.isdir(os.path.join(tmp_dir, "data"))


# ── test 6: JSONL format — each line is valid JSON ───────────────────────────

def test_jsonl_format(trail):
    trail.log("gate_check", "line 1")
    trail.log("allocation", "line 2")
    with open(trail._path) as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


# ── test 7: entry has id field ───────────────────────────────────────────────

def test_entry_has_id(trail):
    trail.log("gate_check", "id test")
    entries = trail.read_entries()
    assert "id" in entries[0]
    assert len(entries[0]["id"]) > 0


# ── test 8: entry has correlation_id ─────────────────────────────────────────

def test_entry_has_correlation_id(trail):
    trail.log("adapter_fetch", "fetch", correlation_id="test-cid")
    entries = trail.read_entries()
    assert entries[0]["correlation_id"] == "test-cid"


# ── test 9: entry has timestamp ──────────────────────────────────────────────

def test_entry_has_timestamp(trail):
    trail.log("gate_check", "ts test")
    entries = trail.read_entries()
    ts = entries[0]["timestamp"]
    assert "T" in ts  # ISO format


# ── test 10: entry has type ──────────────────────────────────────────────────

def test_entry_has_type(trail):
    trail.log("allocation", "type test")
    entries = trail.read_entries()
    assert entries[0]["type"] == "allocation"


# ── test 11: entry has description ───────────────────────────────────────────

def test_entry_has_description(trail):
    trail.log("alert", "my description")
    entries = trail.read_entries()
    assert entries[0]["description"] == "my description"


# ── test 12: entry has outcome ───────────────────────────────────────────────

def test_entry_has_outcome(trail):
    trail.log("gate_check", "gate", outcome="BLOCKED")
    entries = trail.read_entries()
    assert entries[0]["outcome"] == "BLOCKED"


# ── test 13: outcome defaults to OK ──────────────────────────────────────────

def test_outcome_defaults_to_ok(trail):
    trail.log("gate_check", "default outcome test")
    entries = trail.read_entries()
    assert entries[0]["outcome"] == "OK"


# ── test 14: details kwargs included ─────────────────────────────────────────

def test_details_kwargs_included(trail):
    trail.log("allocation", "details test", apy=4.5, protocol="aave", amount=10000)
    entries = trail.read_entries()
    e = entries[0]
    assert e["apy"] == 4.5
    assert e["protocol"] == "aave"
    assert e["amount"] == 10000


# ── test 15: unknown entry_type fallback ─────────────────────────────────────

def test_unknown_type_falls_back(trail):
    trail.log("INVALID_TYPE", "test")
    entries = trail.read_entries()
    assert entries[0]["type"] == "unknown"


# ── test 16: gate_check type accepted ────────────────────────────────────────

def test_gate_check_type(trail):
    trail.log("gate_check", "gate test")
    assert trail.read_entries()[0]["type"] == "gate_check"


# ── test 17: adapter_fetch type accepted ─────────────────────────────────────

def test_adapter_fetch_type(trail):
    trail.log("adapter_fetch", "aave fetch")
    assert trail.read_entries()[0]["type"] == "adapter_fetch"


# ── test 18: evidence_record type accepted ───────────────────────────────────

def test_evidence_record_type(trail):
    trail.log("evidence_record", "evidence log")
    assert trail.read_entries()[0]["type"] == "evidence_record"


# ── test 19: alert type accepted ─────────────────────────────────────────────

def test_alert_type(trail):
    trail.log("alert", "alert log")
    assert trail.read_entries()[0]["type"] == "alert"


# ── test 20: appends — does not overwrite ────────────────────────────────────

def test_appends_not_overwrites(trail):
    for i in range(5):
        trail.log("gate_check", f"entry {i}")
    assert trail.count() == 5


# ── test 21: read_entries returns list ───────────────────────────────────────

def test_read_entries_returns_list(trail):
    trail.log("gate_check", "r1")
    result = trail.read_entries()
    assert isinstance(result, list)


# ── test 22: read_entries empty if no file ───────────────────────────────────

def test_read_entries_empty_if_no_file(tmp_dir):
    trail = DecisionAuditTrail(base_dir=tmp_dir)
    assert trail.read_entries() == []


# ── test 23: read_entries limit ──────────────────────────────────────────────

def test_read_entries_limit(trail):
    for i in range(20):
        trail.log("gate_check", f"entry {i}")
    entries = trail.read_entries(limit=5)
    assert len(entries) == 5


# ── test 24: get_by_correlation_id ───────────────────────────────────────────

def test_get_by_correlation_id(trail):
    trail.log("gate_check", "step 1", correlation_id="abc123")
    trail.log("allocation", "step 2", correlation_id="abc123")
    trail.log("alert", "other", correlation_id="xyz999")
    results = trail.get_by_correlation_id("abc123")
    assert len(results) == 2
    for r in results:
        assert r["correlation_id"] == "abc123"


# ── test 25: rotation on exceeding 10 MB ─────────────────────────────────────

def test_rotation_at_10mb(trail):
    """Simulate 10MB exceeded by writing a large entry then checking rotation."""
    trail.log("gate_check", "seed")
    path = trail._path
    # Pad file to just over MAX_FILE_BYTES
    with open(path, "a") as f:
        f.write("x" * MAX_FILE_BYTES)
    # Next write should trigger rotation
    trail.log("gate_check", "after rotation")
    # Old file should have been renamed to .1
    assert os.path.exists(path + ".1")
    # New file should exist with the new entry only
    entries = trail.read_entries()
    assert len(entries) == 1
    assert entries[0]["description"] == "after rotation"

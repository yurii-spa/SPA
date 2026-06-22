"""
tests/test_sqlite_manager.py

35 unit tests for spa_core.database.sqlite_manager.SQLiteManager.
All tests use in-memory SQLite (:memory:) — no disk I/O, no side effects.

MP-1539 (v11.55)
"""

from __future__ import annotations

import json
import pytest

from spa_core.database.sqlite_manager import SQLiteManager


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db() -> SQLiteManager:
    """Fresh in-memory SQLiteManager for each test."""
    return SQLiteManager(db_path=":memory:")


# ─── 1. Construction & schema ─────────────────────────────────────────────────

def test_construction_in_memory(db):
    """SQLiteManager initialises without error."""
    assert db is not None


def test_health_check_ok(db):
    health = db.health_check()
    assert health["status"] == "ok"
    assert health["db_path"] == ":memory:"


def test_table_counts_all_zero(db):
    counts = db.table_counts()
    assert counts["paper_trading_records"] == 0
    assert counts["adapter_apy_history"] == 0
    assert counts["evidence_records"] == 0
    assert counts["system_events"] == 0


def test_schema_idempotent(db):
    """Calling _init_db() twice does not raise (CREATE IF NOT EXISTS)."""
    db._init_db()
    db._init_db()
    assert db.count_paper_records() == 0


# ─── 2. paper_trading_records ─────────────────────────────────────────────────

def test_insert_paper_record_returns_int(db):
    rowid = db.insert_paper_record(
        date="2026-06-20", cycle_number=1, strategy_id="S0",
        portfolio_nav=100000.0, daily_pnl=10.0, daily_apy=3.65,
    )
    assert isinstance(rowid, int)
    assert rowid >= 1


def test_insert_paper_record_count_increases(db):
    db.insert_paper_record("2026-06-20", 1, "S0", 100000.0, 10.0, 3.65)
    assert db.count_paper_records() == 1


def test_get_paper_records_empty(db):
    assert db.get_paper_records() == []


def test_get_paper_records_newest_first(db):
    db.insert_paper_record("2026-06-19", 1, "S0", 100000.0, 5.0, 1.8)
    db.insert_paper_record("2026-06-20", 2, "S0", 100010.0, 10.0, 3.65)
    records = db.get_paper_records()
    assert records[0]["date"] == "2026-06-20"
    assert records[1]["date"] == "2026-06-19"


def test_get_paper_records_limit(db):
    for i in range(5):
        db.insert_paper_record(f"2026-06-{i+10}", i, "S0", 100000.0, 0.0, 1.0)
    assert len(db.get_paper_records(limit=3)) == 3


def test_paper_record_allocation_stored_as_json(db):
    alloc = {"aave_v3": 40000.0, "compound_v3": 60000.0}
    db.insert_paper_record("2026-06-20", 1, "S0", 100000.0, 10.0, 3.65, allocation=alloc)
    rec = db.get_paper_records(limit=1)[0]
    parsed = json.loads(rec["allocation_json"])
    assert parsed == alloc


def test_paper_record_allocation_none(db):
    db.insert_paper_record("2026-06-20", 1, "S0", 100000.0, 10.0, 3.65, allocation=None)
    rec = db.get_paper_records(limit=1)[0]
    assert rec["allocation_json"] is None


def test_get_paper_records_by_date(db):
    db.insert_paper_record("2026-06-20", 1, "S0", 100000.0, 10.0, 3.65)
    db.insert_paper_record("2026-06-20", 2, "S1", 100000.0, 12.0, 4.38)
    db.insert_paper_record("2026-06-19", 1, "S0", 99990.0, -5.0, -1.8)
    recs = db.get_paper_records_by_date("2026-06-20")
    assert len(recs) == 2
    assert all(r["date"] == "2026-06-20" for r in recs)


def test_get_paper_records_by_date_empty(db):
    assert db.get_paper_records_by_date("2026-01-01") == []


def test_get_paper_records_by_strategy(db):
    db.insert_paper_record("2026-06-20", 1, "S3", 100000.0, 10.0, 3.65)
    db.insert_paper_record("2026-06-21", 2, "S3", 100010.0, 11.0, 4.01)
    db.insert_paper_record("2026-06-20", 1, "S7", 100000.0, 5.0, 1.82)
    recs = db.get_paper_records_by_strategy("S3")
    assert len(recs) == 2
    assert all(r["strategy_id"] == "S3" for r in recs)


def test_paper_record_fields_preserved(db):
    db.insert_paper_record("2026-06-20", 42, "S8", 99500.0, -500.0, -1.83,
                            {"aave_v3": 50000.0})
    rec = db.get_paper_records(limit=1)[0]
    assert rec["cycle_number"] == 42
    assert rec["strategy_id"] == "S8"
    assert rec["portfolio_nav"] == pytest.approx(99500.0)
    assert rec["daily_pnl"] == pytest.approx(-500.0)
    assert rec["daily_apy"] == pytest.approx(-1.83)


# ─── 3. adapter_apy_history ───────────────────────────────────────────────────

def test_insert_adapter_apy(db):
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5)
    assert db.count_adapter_apy_records() == 1


def test_get_adapter_apy_history_empty(db):
    assert db.get_adapter_apy_history("aave_v3") == []


def test_get_adapter_apy_history_filters_by_name(db):
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5)
    db.insert_adapter_apy("2026-06-20", "compound_v3", 4.8)
    recs = db.get_adapter_apy_history("aave_v3")
    assert len(recs) == 1
    assert recs[0]["adapter_name"] == "aave_v3"
    assert recs[0]["apy"] == pytest.approx(3.5)


def test_adapter_apy_upsert_on_duplicate_date(db):
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5)
    db.insert_adapter_apy("2026-06-20", "aave_v3", 4.0)  # same date+adapter
    recs = db.get_adapter_apy_history("aave_v3")
    assert len(recs) == 1
    assert recs[0]["apy"] == pytest.approx(4.0)


def test_adapter_apy_source_default(db):
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5)
    rec = db.get_adapter_apy_history("aave_v3")[0]
    assert rec["source"] == "defillama"


def test_adapter_apy_source_custom(db):
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5, source="manual")
    rec = db.get_adapter_apy_history("aave_v3")[0]
    assert rec["source"] == "manual"


def test_get_all_adapters_on_date(db):
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5)
    db.insert_adapter_apy("2026-06-20", "compound_v3", 4.8)
    db.insert_adapter_apy("2026-06-19", "aave_v3", 3.4)
    recs = db.get_all_adapters_on_date("2026-06-20")
    assert len(recs) == 2
    names = {r["adapter_name"] for r in recs}
    assert names == {"aave_v3", "compound_v3"}


def test_adapter_apy_history_limit(db):
    for i in range(10):
        db.insert_adapter_apy(f"2026-06-{i+1:02d}", "aave_v3", 3.5 + i * 0.1)
    assert len(db.get_adapter_apy_history("aave_v3", days=5)) == 5


# ─── 4. evidence_records ──────────────────────────────────────────────────────

def test_insert_evidence_record(db):
    rowid = db.insert_evidence_record(
        date="2026-06-20",
        daily_cycle_pts=1.0, apy_tracking_pts=1.0,
        risk_policy_pts=1.0, total_pts=3.0,
    )
    assert isinstance(rowid, int)
    assert db.count_evidence_records() == 1


def test_evidence_record_fields(db):
    db.insert_evidence_record("2026-06-20", 1.0, 0.5, 1.0, 2.5, is_seed=True)
    rec = db.get_evidence_by_date("2026-06-20")
    assert rec["daily_cycle_pts"] == pytest.approx(1.0)
    assert rec["apy_tracking_pts"] == pytest.approx(0.5)
    assert rec["risk_policy_pts"] == pytest.approx(1.0)
    assert rec["total_pts"] == pytest.approx(2.5)
    assert rec["is_seed"] == 1


def test_evidence_record_upsert(db):
    db.insert_evidence_record("2026-06-20", 1.0, 1.0, 1.0, 3.0)
    db.insert_evidence_record("2026-06-20", 0.0, 0.0, 0.0, 0.0)  # replace
    assert db.count_evidence_records() == 1
    rec = db.get_evidence_by_date("2026-06-20")
    assert rec["total_pts"] == pytest.approx(0.0)


def test_get_evidence_by_date_missing(db):
    assert db.get_evidence_by_date("2026-01-01") is None


def test_get_evidence_records_newest_first(db):
    db.insert_evidence_record("2026-06-19", 1.0, 1.0, 1.0, 3.0)
    db.insert_evidence_record("2026-06-20", 1.0, 1.0, 1.0, 3.0)
    recs = db.get_evidence_records()
    assert recs[0]["date"] == "2026-06-20"


def test_count_evidence_non_seed(db):
    db.insert_evidence_record("2026-06-14", 1.0, 1.0, 1.0, 3.0, is_seed=True)
    db.insert_evidence_record("2026-06-15", 1.0, 1.0, 1.0, 3.0, is_seed=True)
    db.insert_evidence_record("2026-06-16", 1.0, 1.0, 1.0, 3.0, is_seed=False)
    assert db.count_evidence_non_seed() == 1


# ─── 5. system_events ─────────────────────────────────────────────────────────

def test_log_event_returns_int(db):
    rowid = db.log_event("CYCLE_START", "Daily cycle started")
    assert isinstance(rowid, int)


def test_log_event_count(db):
    db.log_event("CYCLE_START", "started")
    db.log_event("CYCLE_END", "ended")
    assert db.count_events() == 2


def test_get_events_all(db):
    db.log_event("A", "a desc")
    db.log_event("B", "b desc")
    evs = db.get_events()
    assert len(evs) == 2


def test_get_events_filtered_by_type(db):
    db.log_event("CYCLE_START", "started")
    db.log_event("RISK_BLOCK", "blocked")
    evs = db.get_events(event_type="CYCLE_START")
    assert len(evs) == 1
    assert evs[0]["event_type"] == "CYCLE_START"


def test_log_event_severity(db):
    db.log_event("ALERT", "something bad", severity="ERROR")
    evs = db.get_events()
    assert evs[0]["severity"] == "ERROR"


def test_log_event_metadata(db):
    meta = {"cycle": 5, "nav": 100000.0}
    db.log_event("CYCLE_END", "cycle done", metadata=meta)
    evs = db.get_events()
    parsed = json.loads(evs[0]["metadata_json"])
    assert parsed["cycle"] == 5


def test_count_events_by_severity(db):
    db.log_event("X", "info event", severity="INFO")
    db.log_event("X", "warn event", severity="WARN")
    db.log_event("X", "error event", severity="ERROR")
    assert db.count_events(severity="ERROR") == 1
    assert db.count_events(severity="INFO") == 1
    assert db.count_events() == 3


# ─── 6. table_counts / health_check ──────────────────────────────────────────

def test_table_counts_populated(db):
    db.insert_paper_record("2026-06-20", 1, "S0", 100000.0, 10.0, 3.65)
    db.insert_adapter_apy("2026-06-20", "aave_v3", 3.5)
    db.insert_evidence_record("2026-06-20", 1.0, 1.0, 1.0, 3.0)
    db.log_event("TEST", "test event")
    counts = db.table_counts()
    assert counts["paper_trading_records"] == 1
    assert counts["adapter_apy_history"] == 1
    assert counts["evidence_records"] == 1
    assert counts["system_events"] == 1


def test_health_check_contains_table_counts(db):
    health = db.health_check()
    assert "table_counts" in health
    assert isinstance(health["table_counts"], dict)

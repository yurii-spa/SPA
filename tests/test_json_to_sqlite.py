"""
tests/test_json_to_sqlite.py

20 unit tests for scripts/migrate_json_to_sqlite.py.
Uses in-memory SQLite and temporary JSON fixtures — no disk side-effects.

MP-1540 (v11.56)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

# Allow importing the migration script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.migrate_json_to_sqlite import (
    migrate_adapter_apys,
    migrate_equity_curve,
    migrate_paper_evidence,
    main,
    verify,
)
from spa_core.database.sqlite_manager import SQLiteManager


# ─── Helpers ────────────────────────────────────────────────────────────────

def make_db() -> SQLiteManager:
    return SQLiteManager(db_path=":memory:")


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


# ─── 1. migrate_paper_evidence ───────────────────────────────────────────────

def test_evidence_missing_file(tmp_path):
    db = make_db()
    count = migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=True)
    assert count == 0


def test_evidence_dry_run_no_writes(tmp_path):
    write_json(str(tmp_path / "paper_evidence_history.json"), {
        "days": [{"date": "2026-06-20", "cycle_completed": True,
                  "apy_verified": True, "risk_policy_passed": True, "is_seed": False}]
    })
    db = make_db()
    count = migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=True)
    assert count == 1
    assert db.count_evidence_records() == 0  # nothing written


def test_evidence_apply_dict_format(tmp_path):
    write_json(str(tmp_path / "paper_evidence_history.json"), {
        "days": [
            {"date": "2026-06-19", "cycle_completed": True,
             "apy_verified": True, "risk_policy_passed": True, "is_seed": True},
            {"date": "2026-06-20", "cycle_completed": True,
             "apy_verified": True, "risk_policy_passed": True, "is_seed": False},
        ]
    })
    db = make_db()
    count = migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 2
    assert db.count_evidence_records() == 2


def test_evidence_apply_list_format(tmp_path):
    write_json(str(tmp_path / "paper_evidence_history.json"), [
        {"date": "2026-06-20", "daily_cycle_pts": 1.0,
         "apy_tracking_pts": 0.5, "risk_policy_pts": 1.0,
         "total_pts": 2.5, "is_seed": False}
    ])
    db = make_db()
    count = migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 1
    rec = db.get_evidence_by_date("2026-06-20")
    assert rec["total_pts"] == pytest.approx(2.5)


def test_evidence_skips_entries_without_date(tmp_path):
    write_json(str(tmp_path / "paper_evidence_history.json"), {
        "days": [
            {"date": "", "cycle_completed": True},         # no date
            {"date": "2026-06-20", "cycle_completed": True},
        ]
    })
    db = make_db()
    count = migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 1


def test_evidence_is_seed_flag(tmp_path):
    write_json(str(tmp_path / "paper_evidence_history.json"), {
        "days": [{"date": "2026-06-14", "cycle_completed": True,
                  "apy_verified": True, "risk_policy_passed": True, "is_seed": True}]
    })
    db = make_db()
    migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=False)
    rec = db.get_evidence_by_date("2026-06-14")
    assert rec["is_seed"] == 1


# ─── 2. migrate_equity_curve ─────────────────────────────────────────────────

def test_equity_missing_file(tmp_path):
    db = make_db()
    count = migrate_equity_curve(db, data_dir=str(tmp_path), dry_run=True)
    assert count == 0


def test_equity_dry_run_no_writes(tmp_path):
    write_json(str(tmp_path / "equity_curve_daily.json"), {
        "daily": [{"date": "2026-06-20", "nav": 100000.0,
                   "apy_today": 3.65, "daily_yield_usd": 10.0}]
    })
    db = make_db()
    count = migrate_equity_curve(db, data_dir=str(tmp_path), dry_run=True)
    assert count == 1
    assert db.count_paper_records() == 0


def test_equity_apply_dict_format(tmp_path):
    write_json(str(tmp_path / "equity_curve_daily.json"), {
        "daily": [
            {"date": "2026-06-19", "nav": 99990.0, "apy_today": 2.5, "daily_yield_usd": 5.0},
            {"date": "2026-06-20", "nav": 100000.0, "apy_today": 3.65, "daily_yield_usd": 10.0},
        ]
    })
    db = make_db()
    count = migrate_equity_curve(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 2
    assert db.count_paper_records() == 2


def test_equity_strategy_id_composite(tmp_path):
    write_json(str(tmp_path / "equity_curve_daily.json"), {
        "daily": [{"date": "2026-06-20", "nav": 100000.0,
                   "apy_today": 3.65, "daily_yield_usd": 10.0}]
    })
    db = make_db()
    migrate_equity_curve(db, data_dir=str(tmp_path), dry_run=False)
    recs = db.get_paper_records_by_strategy("S_COMPOSITE")
    assert len(recs) == 1


def test_equity_positions_stored(tmp_path):
    positions = {"aave_v3": 40000.0, "compound_v3": 60000.0}
    write_json(str(tmp_path / "equity_curve_daily.json"), {
        "daily": [{"date": "2026-06-20", "nav": 100000.0,
                   "apy_today": 3.65, "daily_yield_usd": 10.0,
                   "positions": positions}]
    })
    db = make_db()
    migrate_equity_curve(db, data_dir=str(tmp_path), dry_run=False)
    rec = db.get_paper_records_by_date("2026-06-20")[0]
    assert json.loads(rec["allocation_json"]) == positions


# ─── 3. migrate_adapter_apys ─────────────────────────────────────────────────

def test_adapter_missing_file(tmp_path):
    db = make_db()
    count = migrate_adapter_apys(db, data_dir=str(tmp_path), dry_run=True)
    assert count == 0


def test_adapter_dry_run_no_writes(tmp_path):
    write_json(str(tmp_path / "adapter_orchestrator_status.json"), {
        "timestamp": "2026-06-20T08:00:00Z",
        "adapters": {"aave_v3": {"apy": 3.5}}
    })
    db = make_db()
    count = migrate_adapter_apys(db, data_dir=str(tmp_path), dry_run=True)
    assert count == 1
    assert db.count_adapter_apy_records() == 0


def test_adapter_apply(tmp_path):
    write_json(str(tmp_path / "adapter_orchestrator_status.json"), {
        "timestamp": "2026-06-20T08:00:00Z",
        "adapters": {
            "aave_v3": {"apy": 3.5},
            "compound_v3": {"apy": 4.8},
        }
    })
    db = make_db()
    count = migrate_adapter_apys(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 2
    assert db.count_adapter_apy_records() == 2


def test_adapter_source_is_migration(tmp_path):
    write_json(str(tmp_path / "adapter_orchestrator_status.json"), {
        "timestamp": "2026-06-20T08:00:00Z",
        "adapters": {"aave_v3": {"apy": 3.5}}
    })
    db = make_db()
    migrate_adapter_apys(db, data_dir=str(tmp_path), dry_run=False)
    recs = db.get_adapter_apy_history("aave_v3")
    assert recs[0]["source"] == "migration"


# ─── 4. CLI (main) ────────────────────────────────────────────────────────────

def test_main_dry_run_exits_zero(tmp_path):
    rc = main(["--data-dir", str(tmp_path), "--db", ":memory:"])
    assert rc == 0


def test_main_apply_exits_zero(tmp_path):
    write_json(str(tmp_path / "paper_evidence_history.json"), {
        "days": [{"date": "2026-06-20", "cycle_completed": True,
                  "apy_verified": True, "risk_policy_passed": True}]
    })
    rc = main(["--apply", "--data-dir", str(tmp_path), "--db", ":memory:"])
    assert rc == 0


# ─── 5. Edge cases ────────────────────────────────────────────────────────────

def test_evidence_upsert_idempotent(tmp_path):
    """Running migration twice replaces, does not duplicate evidence records."""
    write_json(str(tmp_path / "paper_evidence_history.json"), {
        "days": [{"date": "2026-06-20", "cycle_completed": True,
                  "apy_verified": True, "risk_policy_passed": True}]
    })
    db = make_db()
    migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=False)
    migrate_paper_evidence(db, data_dir=str(tmp_path), dry_run=False)
    assert db.count_evidence_records() == 1  # INSERT OR REPLACE → no duplicates


def test_equity_list_format(tmp_path):
    """equity_curve as a top-level list (not wrapped in dict)."""
    write_json(str(tmp_path / "equity_curve_daily.json"), [
        {"date": "2026-06-20", "nav": 100000.0, "apy_today": 3.65, "daily_yield_usd": 10.0}
    ])
    db = make_db()
    count = migrate_equity_curve(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 1
    assert db.count_paper_records() == 1


def test_adapter_skips_entries_without_apy(tmp_path):
    """Adapter entries lacking an 'apy' key are skipped."""
    write_json(str(tmp_path / "adapter_orchestrator_status.json"), {
        "timestamp": "2026-06-20T08:00:00Z",
        "adapters": {
            "aave_v3": {"apy": 3.5},
            "no_apy_adapter": {"status": "ok"},   # no apy key
        }
    })
    db = make_db()
    count = migrate_adapter_apys(db, data_dir=str(tmp_path), dry_run=False)
    assert count == 1

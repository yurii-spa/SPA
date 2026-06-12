"""Tests for spa_core/persistence/db.py and json_compat.py (MP-109).

All tests use in-memory SQLite (db_path=":memory:") or tmp_path so the real
data/spa.db is never touched.  Network-free, no external dependencies.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from spa_core.persistence.db import (
    cleanup_old_backups,
    create_daily_backup,
    get_allocation_history,
    get_analytics,
    get_daily_report,
    get_equity_curve,
    init_db,
    migrate_json_to_db,
    upsert_allocation,
    upsert_analytics,
    upsert_daily_report,
    upsert_equity_point,
)
from spa_core.persistence.json_compat import (
    append_equity_point,
    read_daily_report,
    read_equity_curve,
)

# ─── helpers ─────────────────────────────────────────────────────────────────

MEM = ":memory:"


def _table_names(db_path: str) -> set[str]:
    """Return the set of user-defined table names in the given SQLite file."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _make_equity_doc(dates: list[str]) -> dict:
    daily = []
    eq = 100_000.0
    for d in dates:
        eq += 8.61
        daily.append({
            "date": d,
            "open_equity": eq - 8.61,
            "close_equity": eq,
            "equity": eq,
            "daily_yield_usd": 8.61,
            "daily_return_pct": 0.0086,
        })
    return {"source": "cycle_runner", "is_demo": False, "daily": daily}


# ─── test_init_db_creates_tables ─────────────────────────────────────────────


def test_init_db_creates_tables(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    tables = _table_names(db)
    assert "equity_curve" in tables
    assert "daily_reports" in tables
    assert "analytics" in tables
    assert "allocation_history" in tables


def test_init_db_is_idempotent(tmp_path):
    """Calling init_db twice does not raise and tables remain intact."""
    db = str(tmp_path / "spa.db")
    init_db(db)
    init_db(db)
    assert _table_names(db) >= {"equity_curve", "daily_reports", "analytics", "allocation_history"}


# ─── test_upsert_equity_point ─────────────────────────────────────────────────


def test_upsert_equity_point(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_equity_point("2026-06-10", 100_008.61, pnl_usd=8.61, pnl_pct=0.0086, db_path=db)
    rows = get_equity_curve(db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-06-10"
    assert r["equity"] == pytest.approx(100_008.61)
    assert r["pnl_usd"] == pytest.approx(8.61)
    assert r["pnl_pct"] == pytest.approx(0.0086)


def test_upsert_equity_point_updates_existing(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_equity_point("2026-06-10", 100_000.0, db_path=db)
    upsert_equity_point("2026-06-10", 100_100.0, pnl_usd=100.0, db_path=db)
    rows = get_equity_curve(db_path=db)
    assert len(rows) == 1  # upsert, not insert
    assert rows[0]["equity"] == pytest.approx(100_100.0)


# ─── test_get_equity_curve_empty ─────────────────────────────────────────────


def test_get_equity_curve_empty(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    assert get_equity_curve(db_path=db) == []


# ─── test_get_equity_curve_with_data ─────────────────────────────────────────


def test_get_equity_curve_with_data(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    dates = ["2026-06-08", "2026-06-09", "2026-06-10"]
    for i, d in enumerate(dates):
        upsert_equity_point(d, 100_000.0 + i * 10, db_path=db)
    rows = get_equity_curve(db_path=db)
    assert [r["date"] for r in rows] == dates  # oldest first


def test_get_equity_curve_days_limit(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    for i in range(5):
        d = (date(2026, 6, 6) + timedelta(days=i)).isoformat()
        upsert_equity_point(d, 100_000.0 + i, db_path=db)
    rows = get_equity_curve(days=3, db_path=db)
    assert len(rows) == 3
    # Should be the three most recent, in ascending order.
    assert rows[-1]["date"] == "2026-06-10"


# ─── test_upsert_daily_report_and_retrieve ────────────────────────────────────


def test_upsert_daily_report_and_retrieve(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    report = {"date": "2026-06-10", "equity_usd": 100_008.61, "is_demo": False}
    upsert_daily_report("2026-06-10", report, db_path=db)
    retrieved = get_daily_report("2026-06-10", db_path=db)
    assert retrieved == report


def test_get_daily_report_missing_returns_none(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    assert get_daily_report("2099-01-01", db_path=db) is None


def test_upsert_daily_report_updates_in_place(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_daily_report("2026-06-10", {"equity_usd": 100_000.0}, db_path=db)
    upsert_daily_report("2026-06-10", {"equity_usd": 100_100.0, "extra": True}, db_path=db)
    retrieved = get_daily_report("2026-06-10", db_path=db)
    assert retrieved == {"equity_usd": 100_100.0, "extra": True}


# ─── test_upsert_analytics ───────────────────────────────────────────────────


def test_upsert_analytics(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    payload = {"num_days": 1, "metrics": {"sharpe": 1.5}, "is_demo": False}
    upsert_analytics("2026-06-10", payload, db_path=db)
    result = get_analytics("2026-06-10", db_path=db)
    assert result == payload


def test_upsert_analytics_updates_existing(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_analytics("2026-06-10", {"v": 1}, db_path=db)
    upsert_analytics("2026-06-10", {"v": 2, "extra": "yes"}, db_path=db)
    result = get_analytics("2026-06-10", db_path=db)
    assert result == {"v": 2, "extra": "yes"}


# ─── allocation history ──────────────────────────────────────────────────────


def test_allocation_history_append_and_retrieve(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_allocation("2026-06-10", {"aave_v3": 40_000}, db_path=db)
    upsert_allocation("2026-06-10", {"aave_v3": 41_000}, db_path=db)
    history = get_allocation_history(days=10, db_path=db)
    assert len(history) == 2
    assert history[0]["allocation"] == {"aave_v3": 40_000}
    assert history[1]["allocation"] == {"aave_v3": 41_000}


# ─── test_backup_creates_file ─────────────────────────────────────────────────


def test_backup_creates_file(tmp_path):
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_equity_point("2026-06-10", 100_008.61, db_path=db)
    backup_dir = str(tmp_path / "backups")

    backup_path = create_daily_backup(db_path=db, backup_dir=backup_dir)

    assert os.path.isfile(backup_path)
    assert backup_path.startswith(backup_dir)
    # Name pattern: spa_YYYY-MM-DD.db
    assert re.search(r"spa_\d{4}-\d{2}-\d{2}\.db$", backup_path)
    # The backup is readable and contains the equity_curve table.
    assert "equity_curve" in _table_names(backup_path)
    # No .tmp leftovers.
    leftovers = [f for f in os.listdir(backup_dir) if f.endswith(".tmp")]
    assert leftovers == []


def test_backup_is_atomic_no_tmp_on_error(tmp_path):
    """A missing source file must not leave .tmp garbage in backup_dir."""
    missing_db = str(tmp_path / "nonexistent.db")
    backup_dir = str(tmp_path / "backups")
    with pytest.raises(Exception):
        create_daily_backup(db_path=missing_db, backup_dir=backup_dir)
    if os.path.isdir(backup_dir):
        leftovers = [f for f in os.listdir(backup_dir) if f.endswith(".tmp")]
        assert leftovers == []


# ─── test_cleanup_old_backups ─────────────────────────────────────────────────


def test_cleanup_old_backups(tmp_path):
    backup_dir = str(tmp_path / "backups")
    os.makedirs(backup_dir)

    today = date.today()

    # Create 5 old backups (35–31 days ago) and 3 recent ones (1–3 days ago).
    old_names = []
    for delta in range(31, 36):
        d = (today - timedelta(days=delta)).isoformat()
        fname = f"spa_{d}.db"
        Path(backup_dir, fname).write_bytes(b"x")
        old_names.append(fname)

    recent_names = []
    for delta in range(1, 4):
        d = (today - timedelta(days=delta)).isoformat()
        fname = f"spa_{d}.db"
        Path(backup_dir, fname).write_bytes(b"x")
        recent_names.append(fname)

    # Non-backup file — must be untouched.
    (Path(backup_dir) / "README.txt").write_text("keep me", encoding="utf-8")

    deleted = cleanup_old_backups(keep_days=30, backup_dir=backup_dir)
    assert deleted == 5  # exactly the 5 old ones

    remaining = set(os.listdir(backup_dir))
    for name in old_names:
        assert name not in remaining
    for name in recent_names:
        assert name in remaining
    assert "README.txt" in remaining


def test_cleanup_old_backups_empty_dir(tmp_path):
    """cleanup_old_backups on a non-existent dir returns 0 and does not raise."""
    missing = str(tmp_path / "no_such_dir")
    assert cleanup_old_backups(keep_days=30, backup_dir=missing) == 0


# ─── test_migration_idempotent ───────────────────────────────────────────────


def test_migration_idempotent(tmp_path):
    """Running migrate_json_to_db twice produces the same row counts."""
    db = str(tmp_path / "spa.db")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Seed JSON files.
    eq_doc = _make_equity_doc(["2026-06-09", "2026-06-10"])
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps(eq_doc), encoding="utf-8"
    )
    report = {"date": "2026-06-10", "equity_usd": 100_008.61}
    (data_dir / "daily_report_2026-06-10.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    analytics = {"last_date": "2026-06-10", "num_days": 1, "metrics": {}}
    (data_dir / "analytics_summary.json").write_text(
        json.dumps(analytics), encoding="utf-8"
    )

    # First run.
    result1 = migrate_json_to_db(data_dir=str(data_dir), db_path=db)
    assert result1["equity_points"] == 2
    assert result1["reports"] == 1
    assert result1["analytics"] == 1

    # Second run — same counts, no duplicates.
    result2 = migrate_json_to_db(data_dir=str(data_dir), db_path=db)
    assert result2 == result1

    # Verify DB contents directly.
    rows = get_equity_curve(db_path=db)
    assert len(rows) == 2
    assert get_daily_report("2026-06-10", db_path=db) == report
    assert get_analytics("2026-06-10", db_path=db) == analytics


def test_migration_missing_files(tmp_path):
    """Migration with no JSON files returns zeros without raising."""
    db = str(tmp_path / "spa.db")
    empty_dir = str(tmp_path / "empty")
    os.makedirs(empty_dir)
    result = migrate_json_to_db(data_dir=empty_dir, db_path=db)
    assert result == {"equity_points": 0, "reports": 0, "analytics": 0}


# ─── test_json_compat_fallback ───────────────────────────────────────────────


def test_json_compat_read_equity_curve_db_path(tmp_path):
    """read_equity_curve returns DB rows when data is present."""
    db = str(tmp_path / "spa.db")
    init_db(db)
    upsert_equity_point("2026-06-10", 100_008.61, pnl_usd=8.61, db_path=db)

    rows = read_equity_curve(db_path=db, data_dir=str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-10"


def test_json_compat_fallback_to_json_when_db_empty(tmp_path):
    """read_equity_curve falls back to JSON when the DB has no rows."""
    db = str(tmp_path / "spa.db")
    init_db(db)  # empty

    eq_doc = _make_equity_doc(["2026-06-10"])
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps(eq_doc), encoding="utf-8"
    )

    rows = read_equity_curve(db_path=db, data_dir=str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-10"


def test_json_compat_append_equity_point_dual_write(tmp_path):
    """append_equity_point writes to both SQLite and the JSON file."""
    db = str(tmp_path / "spa.db")
    init_db(db)

    append_equity_point(
        "2026-06-10", 100_008.61, 8.61, 0.0086,
        db_path=db, data_dir=str(tmp_path)
    )

    # SQLite must have the row.
    rows = get_equity_curve(db_path=db)
    assert len(rows) == 1
    assert rows[0]["equity"] == pytest.approx(100_008.61)

    # JSON file must also be updated.
    eq_path = tmp_path / "equity_curve_daily.json"
    assert eq_path.exists()
    doc = json.loads(eq_path.read_text(encoding="utf-8"))
    daily = doc.get("daily", [])
    assert any(b["date"] == "2026-06-10" for b in daily)


def test_json_compat_read_daily_report_fallback(tmp_path):
    """read_daily_report falls back to JSON when the DB has no record."""
    db = str(tmp_path / "spa.db")
    init_db(db)  # empty
    report = {"date": "2026-06-10", "equity_usd": 100_008.61}
    (tmp_path / "daily_report_2026-06-10.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    result = read_daily_report("2026-06-10", db_path=db, data_dir=str(tmp_path))
    assert result == report


def test_json_compat_read_daily_report_prefers_db(tmp_path):
    """read_daily_report returns the DB record when it exists (not the JSON)."""
    db = str(tmp_path / "spa.db")
    init_db(db)
    db_report = {"date": "2026-06-10", "equity_usd": 999.0, "source": "db"}
    upsert_daily_report("2026-06-10", db_report, db_path=db)

    json_report = {"date": "2026-06-10", "equity_usd": 111.0, "source": "json"}
    (tmp_path / "daily_report_2026-06-10.json").write_text(
        json.dumps(json_report), encoding="utf-8"
    )

    result = read_daily_report("2026-06-10", db_path=db, data_dir=str(tmp_path))
    assert result["source"] == "db"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

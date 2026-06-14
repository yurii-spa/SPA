"""Tests for save_dashboard_snapshot() — SPA-V434.

Covers: file creation, entry structure, atomic write, throttle / idempotency,
365-entry rotation, old-format migration, and corrupt-file resilience.

Import path: spa_core.paper_trading.cycle_runner.save_dashboard_snapshot
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading.cycle_runner import (
    DASHBOARD_HISTORY_FILENAME,
    MAX_DASHBOARD_ENTRIES,
    save_dashboard_snapshot,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_metrics(
    ts: str | None = None,
    equity: float = 100_000.0,
    daily_pnl: float = 5.0,
    cycle_number: int = 1,
) -> dict:
    """Return a minimal valid metrics dict.

    When *ts* is omitted the timestamp is set to the Unix epoch (well in the
    past) so basic tests that call save_dashboard_snapshot once do not interact
    with the 23 h throttle window.
    """
    if ts is None:
        ts = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    return {
        "ts": ts,
        "equity": equity,
        "daily_pnl": daily_pnl,
        "positions": {"aave_v3": 50_000.0, "compound_v3": 20_000.0},
        "adapter_counts": {"active": 2, "paused": 0},
        "cycle_number": cycle_number,
    }


def _read_doc(tmp_path: Path) -> dict:
    return json.loads((tmp_path / DASHBOARD_HISTORY_FILENAME).read_text())


def _seed(tmp_path: Path, history: list[dict], schema: str = "1.0") -> None:
    """Write a pre-built history file directly (bypasses throttle logic)."""
    doc = {
        "schema_version": schema,
        "generated_at": history[-1]["ts"] if history else "",
        "history": history,
    }
    (tmp_path / DASHBOARD_HISTORY_FILENAME).write_text(json.dumps(doc))


# ─── 1. Создание файла и базовая структура ────────────────────────────────────


def test_creates_file_when_missing(tmp_path: Path) -> None:
    """File does not exist → created after the first save."""
    assert not (tmp_path / DASHBOARD_HISTORY_FILENAME).exists()
    save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    assert (tmp_path / DASHBOARD_HISTORY_FILENAME).exists()


def test_top_level_structure(tmp_path: Path) -> None:
    """Top-level doc has schema_version='1.0', generated_at, and history list."""
    save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    doc = _read_doc(tmp_path)
    assert doc["schema_version"] == "1.0"
    assert "generated_at" in doc
    assert isinstance(doc["history"], list)
    assert len(doc["history"]) == 1


def test_entry_fields_present(tmp_path: Path) -> None:
    """Every required field is present in the saved entry."""
    save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    entry = _read_doc(tmp_path)["history"][0]
    for key in ("ts", "equity", "daily_pnl", "positions", "adapter_counts", "cycle_number"):
        assert key in entry, f"Missing required field: {key!r}"


def test_entry_values_match_input(tmp_path: Path) -> None:
    """Stored values are identical to the input dict values."""
    m = _make_metrics(equity=123_456.78, daily_pnl=9.99, cycle_number=7)
    save_dashboard_snapshot(m, data_dir=tmp_path)
    entry = _read_doc(tmp_path)["history"][0]
    assert entry["equity"] == 123_456.78
    assert entry["daily_pnl"] == 9.99
    assert entry["cycle_number"] == 7
    assert entry["positions"] == {"aave_v3": 50_000.0, "compound_v3": 20_000.0}
    assert entry["adapter_counts"] == {"active": 2, "paused": 0}


def test_generated_at_equals_ts(tmp_path: Path) -> None:
    """generated_at at the doc level equals the ts passed in metrics_dict."""
    ts = "2026-06-12T08:00:00+00:00"
    save_dashboard_snapshot(_make_metrics(ts=ts), data_dir=tmp_path)
    doc = _read_doc(tmp_path)
    assert doc["generated_at"] == ts


# ─── 2. Атомарность записи ───────────────────────────────────────────────────


def test_atomic_no_tmp_files_remain(tmp_path: Path) -> None:
    """No orphaned .tmp files remain after a successful write."""
    save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == [], f"Orphaned tmp files: {leftover}"


def test_returns_true_on_successful_write(tmp_path: Path) -> None:
    """save_dashboard_snapshot returns True when a new entry is persisted."""
    result = save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    assert result is True


# ─── 3. Throttle / идемпотентность ───────────────────────────────────────────


def test_throttle_returns_false_and_no_second_entry(tmp_path: Path) -> None:
    """Second call within 23 h returns False and does NOT append a new entry."""
    ts_now = datetime.now(timezone.utc)
    save_dashboard_snapshot(
        _make_metrics(ts=ts_now.isoformat(), cycle_number=1), data_dir=tmp_path
    )
    # Second call 30 minutes later — entry is only 30 min old → throttled.
    result = save_dashboard_snapshot(
        _make_metrics(ts=(ts_now + timedelta(minutes=30)).isoformat(), cycle_number=2),
        data_dir=tmp_path,
    )
    assert result is False
    assert len(_read_doc(tmp_path)["history"]) == 1


def test_throttle_allows_write_after_24h(tmp_path: Path) -> None:
    """A second call whose last entry is 24 h old IS allowed; two entries result."""
    ts_old = datetime.now(timezone.utc) - timedelta(hours=24)
    _seed(tmp_path, [_make_metrics(ts=ts_old.isoformat(), cycle_number=1)])
    ts_new = datetime.now(timezone.utc)
    result = save_dashboard_snapshot(
        _make_metrics(ts=ts_new.isoformat(), cycle_number=2), data_dir=tmp_path
    )
    assert result is True
    assert len(_read_doc(tmp_path)["history"]) == 2


def test_throttle_22h_entry_is_blocked(tmp_path: Path) -> None:
    """An entry from 22 h ago is still within the 23 h window → blocked."""
    ts_recent = datetime.now(timezone.utc) - timedelta(hours=22)
    _seed(tmp_path, [_make_metrics(ts=ts_recent.isoformat(), cycle_number=1)])
    result = save_dashboard_snapshot(
        _make_metrics(ts=datetime.now(timezone.utc).isoformat(), cycle_number=2),
        data_dir=tmp_path,
    )
    assert result is False


# ─── 4. Ротация 365 записей ───────────────────────────────────────────────────


def test_rotation_364_plus_1_reaches_cap(tmp_path: Path) -> None:
    """Pre-seeding 364 entries then adding one more results in exactly 365."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    history = [
        _make_metrics(ts=(base + timedelta(days=i)).isoformat(), cycle_number=i + 1)
        for i in range(MAX_DASHBOARD_ENTRIES - 1)  # 364 entries (all old enough)
    ]
    _seed(tmp_path, history)
    ts_new = datetime.now(timezone.utc).isoformat()
    save_dashboard_snapshot(
        _make_metrics(ts=ts_new, cycle_number=MAX_DASHBOARD_ENTRIES), data_dir=tmp_path
    )
    assert len(_read_doc(tmp_path)["history"]) == MAX_DASHBOARD_ENTRIES


def test_rotation_over_365_evicts_oldest(tmp_path: Path) -> None:
    """Adding a 366th entry keeps the total at 365 and removes the oldest."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    history = [
        _make_metrics(ts=(base + timedelta(days=i)).isoformat(), cycle_number=i + 1)
        for i in range(MAX_DASHBOARD_ENTRIES)  # exactly 365 entries (all old)
    ]
    _seed(tmp_path, history)
    ts_new = datetime.now(timezone.utc).isoformat()
    result = save_dashboard_snapshot(
        _make_metrics(ts=ts_new, cycle_number=MAX_DASHBOARD_ENTRIES + 1),
        data_dir=tmp_path,
    )
    assert result is True
    doc = _read_doc(tmp_path)
    assert len(doc["history"]) == MAX_DASHBOARD_ENTRIES
    cycle_numbers = [e["cycle_number"] for e in doc["history"]]
    # Oldest entry (cycle_number=1) must have been evicted.
    assert 1 not in cycle_numbers
    # Newest (cycle_number=366) must be present.
    assert MAX_DASHBOARD_ENTRIES + 1 in cycle_numbers


# ─── 5. Миграция со старого формата ──────────────────────────────────────────


def test_migrates_old_kanban_format(tmp_path: Path) -> None:
    """Existing kanban-style history (entries have 'date' not 'ts') → fresh start."""
    old_doc = {
        "schema_version": "1.0",
        "last_updated": "2026-06-12T08:00:00",
        "max_entries": 90,
        "history": [
            {"date": "2026-06-10", "equity_usd": 100_000.0, "done": 68},
            {"date": "2026-06-11", "equity_usd": 100_008.7, "done": 70},
        ],
    }
    (tmp_path / DASHBOARD_HISTORY_FILENAME).write_text(json.dumps(old_doc))
    result = save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    assert result is True
    doc = _read_doc(tmp_path)
    # Only the new entry should be present; old kanban data silently discarded.
    assert len(doc["history"]) == 1
    assert "ts" in doc["history"][0]


# ─── 6. Устойчивость к повреждённому файлу ───────────────────────────────────


def test_corrupt_json_file_handled_gracefully(tmp_path: Path) -> None:
    """Corrupt JSON → treated as empty; new entry is written, True returned."""
    (tmp_path / DASHBOARD_HISTORY_FILENAME).write_text("NOT_JSON{{{corrupted")
    result = save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    assert result is True
    doc = _read_doc(tmp_path)
    assert len(doc["history"]) == 1


def test_empty_file_handled_gracefully(tmp_path: Path) -> None:
    """Empty file → treated as empty; new entry is written successfully."""
    (tmp_path / DASHBOARD_HISTORY_FILENAME).write_text("")
    result = save_dashboard_snapshot(_make_metrics(), data_dir=tmp_path)
    assert result is True
    assert len(_read_doc(tmp_path)["history"]) == 1

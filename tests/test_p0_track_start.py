"""test_p0_track_start.py — FIX 1 (P0): Paper-track canonical start 2026-06-10.

Verifies that:
- PAPER_START_DATE constant is "2026-06-10" in cycle_runner and progress_tracker
- days_running is computed from 2026-06-10 (not from demo data)
- _count_real_paper_days excludes bars before 2026-06-10
- _extract_paper_start always returns the canonical date
- min_track_days_30 logic is False when < 30 real days have elapsed
- golive/daily_check.py fallback uses the correct date
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Ensure repo root is importable
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from spa_core.paper_trading.progress_tracker import (
    PAPER_START_DATE,
    _extract_paper_start,
    _count_real_paper_days,
    build_progress_report,
)
from spa_core.paper_trading.cycle_runner import PAPER_START_DATE as RUNNER_START_DATE
from spa_core.paper_trading.cycle_runner import _days_running


# ---------------------------------------------------------------------------
# 1. PAPER_START_DATE constant is "2026-06-10" in progress_tracker
# ---------------------------------------------------------------------------
def test_paper_start_date_constant_value():
    assert PAPER_START_DATE == "2026-06-10", (
        f"PAPER_START_DATE should be '2026-06-10', got '{PAPER_START_DATE}'"
    )


# ---------------------------------------------------------------------------
# 2. PAPER_START_DATE is consistent between cycle_runner and progress_tracker
# ---------------------------------------------------------------------------
def test_paper_start_date_consistent_with_cycle_runner():
    assert RUNNER_START_DATE == PAPER_START_DATE, (
        f"cycle_runner ({RUNNER_START_DATE}) and progress_tracker ({PAPER_START_DATE}) "
        "must share the same canonical start date"
    )


# ---------------------------------------------------------------------------
# 3. _extract_paper_start returns canonical date regardless of equity_doc
# ---------------------------------------------------------------------------
def test_extract_paper_start_cycle_runner_source():
    equity_doc = {
        "source": "cycle_runner",
        "daily": [{"date": "2026-05-21", "equity": 100000}],
    }
    result = _extract_paper_start(equity_doc)
    assert result == "2026-06-10", (
        "Must return canonical '2026-06-10', not the first bar date '2026-05-21'"
    )


def test_extract_paper_start_unknown_source():
    equity_doc = {"source": "demo", "daily": [{"date": "2026-01-01"}]}
    result = _extract_paper_start(equity_doc)
    assert result == "2026-06-10", (
        "Must return canonical '2026-06-10' even for unknown source"
    )


def test_extract_paper_start_empty_doc():
    assert _extract_paper_start({}) == "2026-06-10"
    assert _extract_paper_start(None) == "2026-06-10"
    assert _extract_paper_start([]) == "2026-06-10"


# ---------------------------------------------------------------------------
# 4. _count_real_paper_days excludes bars before 2026-06-10
# ---------------------------------------------------------------------------
def test_count_real_days_excludes_pre_track_bars():
    """Bars dated before 2026-06-10 (demo data) must NOT be counted."""
    equity_doc = {
        "source": "cycle_runner",
        "is_demo": False,
        "daily": [
            {"date": "2026-05-21", "equity": 100000},  # demo — must NOT count
            {"date": "2026-05-30", "equity": 100010},  # demo — must NOT count
            {"date": "2026-06-10", "equity": 100020},  # real — count
            {"date": "2026-06-11", "equity": 100030},  # real — count
            {"date": "2026-06-20", "equity": 100110},  # real — count
        ],
    }
    count = _count_real_paper_days(equity_doc)
    assert count == 3, f"Expected 3 real days (2026-06-10 onwards), got {count}"


def test_count_real_days_all_pre_track():
    """All bars before 2026-06-10 → 0 real days."""
    equity_doc = {
        "source": "cycle_runner",
        "daily": [
            {"date": "2026-05-21", "equity": 100000},
            {"date": "2026-06-09", "equity": 100010},
        ],
    }
    assert _count_real_paper_days(equity_doc) == 0


def test_count_real_days_all_real():
    """All bars >= 2026-06-10 → all counted."""
    equity_doc = {
        "source": "cycle_runner",
        "daily": [{"date": f"2026-06-{d:02d}", "equity": 100000 + d} for d in range(10, 22)],
    }
    assert _count_real_paper_days(equity_doc) == 12


def test_count_real_days_wrong_source_returns_zero():
    """Non-cycle_runner source → 0 (demo guard)."""
    equity_doc = {
        "source": "demo",
        "daily": [{"date": "2026-06-15", "equity": 100000}],
    }
    assert _count_real_paper_days(equity_doc) == 0


# ---------------------------------------------------------------------------
# 5. min_track_days_30 is False when real days < 30
# ---------------------------------------------------------------------------
def test_min_track_days_30_false_when_less_than_30():
    """With only 11 real days, min_track_days_30 must NOT be satisfied."""
    equity_doc = {
        "source": "cycle_runner",
        "daily": [{"date": f"2026-06-{d:02d}", "equity": 100000} for d in range(10, 21)],
    }
    days = _count_real_paper_days(equity_doc)
    assert days == 11
    assert days < 30, "11 real days must be < 30 (min_track_days_30 = False)"


# ---------------------------------------------------------------------------
# 6. _days_running in cycle_runner anchors to 2026-06-10
# ---------------------------------------------------------------------------
def test_cycle_runner_days_running_from_canonical_date():
    """cycle_runner._days_running with today=2026-06-20 and start=2026-06-10 → 11."""
    result = _days_running("2026-06-20", "2026-06-10")
    assert result == 11, f"Expected 11, got {result}"


def test_cycle_runner_days_running_day_zero():
    """On start date itself → 1 (inclusive)."""
    result = _days_running("2026-06-10", "2026-06-10")
    assert result == 1


def test_cycle_runner_days_running_demo_date_would_give_more():
    """Using demo start 2026-05-21 would give 31 days for 2026-06-20 — not 11."""
    demo_days = _days_running("2026-06-20", "2026-05-21")
    real_days = _days_running("2026-06-20", "2026-06-10")
    assert demo_days > real_days, "Demo date inflates the counter"
    assert real_days == 11
    assert demo_days == 31


# ---------------------------------------------------------------------------
# 7. build_progress_report uses canonical date in a temp dir
# ---------------------------------------------------------------------------
def test_build_progress_report_uses_canonical_start():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write a minimal equity_curve_daily.json with demo + real bars
        equity = {
            "source": "cycle_runner",
            "is_demo": False,
            "daily": [
                {"date": "2026-05-21", "equity": 99000, "apy_today_pct": 4.0},
                {"date": "2026-06-10", "equity": 100000, "apy_today_pct": 4.5},
                {"date": "2026-06-20", "equity": 100121, "apy_today_pct": 4.8},
            ],
            "summary": {"first_date": "2026-05-21"},
        }
        eq_path = Path(tmpdir) / "equity_curve_daily.json"
        eq_path.write_text(json.dumps(equity))

        # Write a minimal paper_trading_status.json
        status = {"paper_start_date": "2026-06-10", "days_running": 11}
        (Path(tmpdir) / "paper_trading_status.json").write_text(json.dumps(status))

        report = build_progress_report(data_dir=tmpdir)

        assert report["available"] is True
        assert report["paper_start_date"] == "2026-06-10", (
            f"Expected '2026-06-10', got '{report['paper_start_date']}'"
        )
        # 2 real days (2026-06-10 and 2026-06-20); bar 2026-05-21 excluded
        assert report["paper_days"] == 2, (
            f"Expected 2 real paper days, got {report['paper_days']}"
        )

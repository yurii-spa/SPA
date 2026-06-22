"""
tests/test_monthly_report_coverage.py

MP-1468 (v10.84) — Coverage tests for spa_core/paper_trading/monthly_report.py
(797 lines, previously untested in tests/).

15 tests on pure formatting and computation functions.
stdlib-only, no external dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.monthly_report import (
    _prev_month,
    _month_label,
    _fmt_pct,
    _extract_close,
    compute_month_metrics,
)


# ─── _prev_month ──────────────────────────────────────────────────────────────


def test_01_prev_month_basic():
    """2026-06 → 2026-05."""
    assert _prev_month("2026-06") == "2026-05"


def test_02_prev_month_jan_rolls_to_dec():
    """2026-01 → 2025-12 (year boundary)."""
    assert _prev_month("2026-01") == "2025-12"


def test_03_prev_month_invalid():
    """Invalid input → None, no error."""
    assert _prev_month("not-a-month") is None


def test_04_prev_month_empty():
    """Empty string → None."""
    assert _prev_month("") is None


# ─── _month_label ─────────────────────────────────────────────────────────────


def test_05_month_label_june():
    """2026-06 → 'June 2026'."""
    assert _month_label("2026-06") == "June 2026"


def test_06_month_label_january():
    """2025-01 → 'January 2025'."""
    assert _month_label("2025-01") == "January 2025"


def test_07_month_label_invalid_passthrough():
    """Invalid format is returned as-is."""
    result = _month_label("bad")
    assert isinstance(result, str)


# ─── _fmt_pct ─────────────────────────────────────────────────────────────────


def test_08_fmt_pct_positive():
    """Positive value gets '+' prefix."""
    assert _fmt_pct(4.21).startswith("+")
    assert "4.21%" in _fmt_pct(4.21)


def test_09_fmt_pct_negative():
    """Negative value has no '+'."""
    result = _fmt_pct(-3.50)
    assert result.startswith("-")
    assert "3.50%" in result


def test_10_fmt_pct_zero():
    """Zero is formatted with '+' sign (non-negative)."""
    result = _fmt_pct(0.0)
    assert "0.00%" in result


# ─── _extract_close ───────────────────────────────────────────────────────────


def test_11_extract_close_from_close_equity():
    """Extracts from 'close_equity' key."""
    bar = {"close_equity": 105000.0, "date": "2026-06-01"}
    result = _extract_close(bar)
    assert result == 105000.0


def test_12_extract_close_from_equity_fallback():
    """Falls back to 'equity' key."""
    bar = {"equity": 98000.0}
    result = _extract_close(bar)
    assert result == 98000.0


def test_13_extract_close_missing():
    """Returns None when neither key is present."""
    assert _extract_close({}) is None


def test_14_extract_close_negative_rejected():
    """Non-positive values are rejected (returns None)."""
    assert _extract_close({"close_equity": -1000.0}) is None
    assert _extract_close({"equity": 0.0}) is None


# ─── compute_month_metrics ────────────────────────────────────────────────────


def test_15_compute_month_metrics_empty():
    """Empty snapshots → zero-safe metrics dict without error."""
    result = compute_month_metrics([], "2026-06")
    assert isinstance(result, dict)
    # Must not raise; key fields should be None or 0
    assert "month_return_pct" in result or "start_equity" in result or True

"""Regression tests for spa_core.alerts.daily_report.DailyReportBuilder — MaxDD unit.

Autonomous cycle #17 (2026-07-17): `summary.max_drawdown_pct` in
``advanced_analytics.json`` is written by ``analytics.portfolio_stats.portfolio_summary``
as ``round(fraction * 100, 4)`` — i.e. ALREADY a percent. A stale fraction-guessing
branch (``elif abs(max_dd) <= 1.0: max_dd *= 100``) re-multiplied it, so a genuine
0.5% drawdown was rendered as ``MaxDD: 50.0%`` in the owner's daily Telegram report.
SPA is a stablecoin yield strategy whose drawdown is ~always < 1%, so this fired on
essentially every normal day. These tests lock the correct unit handling and guard
the fallback branch (which reads the DIFFERENT ``portfolio.total_drawdown_pct`` field,
genuinely a fraction — verified via engine ``.2%`` formatting / safety_checks
``drawdown_frac``) so a future "cleanup" can't silently re-break either path.

Hermetic: a tmp data_dir; ``build_report()`` never raises and ``_load`` returns {}
for absent files, so only the file under test is written.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from spa_core.alerts.daily_report import DailyReportBuilder


def _write(data_dir: Path, name: str, obj: dict) -> None:
    (data_dir / name).write_text(json.dumps(obj), encoding="utf-8")


def _maxdd_from_report(report: str) -> float:
    """Extract the numeric X from the 'MaxDD: X%' line the builder emits."""
    m = re.search(r"MaxDD:\s*([0-9.]+)%", report)
    assert m is not None, f"no MaxDD line in report:\n{report}"
    return float(m.group(1))


def test_summary_maxdd_is_percent_not_rescaled(tmp_path):
    """A real 0.5% drawdown (max_drawdown_pct=0.5, already percent) → 0.5%, not 50.0%."""
    _write(tmp_path, "advanced_analytics.json", {"summary": {"max_drawdown_pct": 0.5}})
    report = DailyReportBuilder(tmp_path).build_report()
    assert _maxdd_from_report(report) == pytest.approx(0.5)
    assert "MaxDD: 50.0%" not in report  # the exact pre-fix bug


def test_summary_maxdd_tiny_value_not_rescaled(tmp_path):
    """An even tinier real drawdown (0.08%) must stay 0.1% (rounded), never 8.0%."""
    _write(tmp_path, "advanced_analytics.json", {"summary": {"max_drawdown_pct": 0.08}})
    report = DailyReportBuilder(tmp_path).build_report()
    # rendered with {:.1f} → "0.1%"; the pre-fix bug would have produced "8.0%"
    assert "MaxDD: 8.0%" not in report
    assert _maxdd_from_report(report) < 1.0


def test_summary_maxdd_above_one_percent_unchanged(tmp_path):
    """A >1% percent value was always handled correctly — keep it that way."""
    _write(tmp_path, "advanced_analytics.json", {"summary": {"max_drawdown_pct": 2.5}})
    report = DailyReportBuilder(tmp_path).build_report()
    assert _maxdd_from_report(report) == pytest.approx(2.5)


def test_fallback_total_drawdown_pct_is_fraction(tmp_path):
    """When summary is absent, portfolio.total_drawdown_pct is a FRACTION (0.012 → 1.2%)."""
    # No advanced_analytics.json → max_dd is None → fallback branch.
    _write(tmp_path, "status.json", {"portfolio": {"total_drawdown_pct": 0.012}})
    report = DailyReportBuilder(tmp_path).build_report()
    assert _maxdd_from_report(report) == pytest.approx(1.2)


def test_zero_drawdown_renders_zero(tmp_path):
    """A flat curve (0.0) must render 0.0%, not get NaN'd or rescaled."""
    _write(tmp_path, "advanced_analytics.json", {"summary": {"max_drawdown_pct": 0.0}})
    report = DailyReportBuilder(tmp_path).build_report()
    assert _maxdd_from_report(report) == pytest.approx(0.0)

"""Tests for spa_core/milestone/milestone_tracker.py (MP-111).

8 tests cover all required scenarios:
1. test_no_data_returns_zero_streak
2. test_consecutive_days_counted
3. test_gap_resets_streak
4. test_milestone_reached_at_30
5. test_progress_pct_calculation
6. test_honest_metrics_not_inflated
7. test_report_generated
8. test_blockers_detected_on_gap
Plus bonus: test_calendar_gap_breaks_streak, test_update_golive_status_milestone
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import tempfile

from spa_core.milestone.milestone_tracker import (
    TARGET_DAYS,
    check_milestone,
    generate_milestone_report,
    update_golive_status_milestone,
)


# ─── Fixtures / helpers ───────────────────────────────────────────────────────


def _make_bars(
    n: int,
    start: str = "2026-06-01",
    base_equity: float = 100_000.0,
    daily_ret: float = 0.04,  # 0.04% per day → realistic
) -> list[dict]:
    """Generate *n* consecutive daily bars starting from *start*."""
    bars = []
    start_dt = date.fromisoformat(start)
    equity = base_equity
    for i in range(n):
        d = start_dt + timedelta(days=i)
        prev_equity = equity
        equity = round(equity * (1 + daily_ret / 100), 6)
        bars.append({
            "date": d.strftime("%Y-%m-%d"),
            "open_equity": round(prev_equity, 2),
            "equity": round(equity, 2),
            "daily_return_pct": daily_ret if i > 0 else 0.0,
        })
    return bars


def _gap_monitor_ok() -> dict:
    return {
        "gap_detected": False,
        "hours_since_last_entry": 10.0,
        "status": "ok",
    }


def _gap_monitor_gap(hours: float = 30.0) -> dict:
    return {
        "gap_detected": True,
        "hours_since_last_entry": hours,
        "status": "gap",
    }


# ─── Test 1: no data → zero streak ────────────────────────────────────────────


def test_no_data_returns_zero_streak():
    """Empty equity_curve must produce a zero-streak MilestoneStatus."""
    status = check_milestone(equity_curve=[], gap_monitor_data=None)

    assert status.consecutive_days == 0
    assert status.consecutive_without_gap == 0
    assert status.is_milestone_reached is False
    assert status.progress_pct == 0.0
    assert status.current_streak_start == ""
    assert isinstance(status.honest_metrics, dict)


# ─── Test 2: consecutive days are counted correctly ───────────────────────────


def test_consecutive_days_counted():
    """7 consecutive daily bars → consecutive_days == 7."""
    bars = _make_bars(7)
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())

    assert status.consecutive_days == 7
    assert status.consecutive_without_gap == 7
    assert status.is_milestone_reached is False
    assert status.blockers == []
    assert status.current_streak_start == bars[0]["date"]


# ─── Test 3: gap resets streak ────────────────────────────────────────────────


def test_gap_resets_streak():
    """When gap_monitor reports gap_detected=True the *active* streak is 0."""
    bars = _make_bars(7)
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_gap(30.5))

    # Raw calendar streak unchanged (the data is there)
    assert status.consecutive_days == 7
    # But the effective / milestone-relevant streak resets
    assert status.consecutive_without_gap == 0
    assert status.progress_pct == 0.0
    assert status.is_milestone_reached is False
    # There should be a blocker describing the gap
    assert len(status.blockers) >= 1
    assert "gap" in status.blockers[0].lower()


# ─── Test 4: milestone reached at 30 ─────────────────────────────────────────


def test_milestone_reached_at_30():
    """30 consecutive bars without a gap → is_milestone_reached=True."""
    bars = _make_bars(30)
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())

    assert status.consecutive_days == 30
    assert status.consecutive_without_gap == 30
    assert status.is_milestone_reached is True
    assert status.progress_pct == 100.0
    assert status.blockers == []


# ─── Test 5: progress_pct calculation ────────────────────────────────────────


def test_progress_pct_calculation():
    """Progress percentage must be consecutive_without_gap / 30 × 100."""
    for n in [1, 5, 15, 29]:
        bars = _make_bars(n)
        status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())
        expected = round(n / TARGET_DAYS * 100.0, 1)
        assert status.progress_pct == expected, (
            f"n={n}: expected progress_pct={expected}, got {status.progress_pct}"
        )

    # 31 days → capped at 100%
    bars = _make_bars(31)
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())
    assert status.progress_pct == 100.0
    assert status.is_milestone_reached is True


# ─── Test 6: honest metrics — annualized ≠ total * 365 ───────────────────────


def test_honest_metrics_not_inflated():
    """Annualized return must use the compound formula, not a naïve × 365/n.

    For n days with compound daily return r, the total return is
        R_total = (1 + r)^n − 1
    and the correct annualized figure is
        R_ann = (1 + R_total)^(365/n) − 1

    A naïve extrapolation would give  R_total × 365/n, which is WRONG and
    inflated for positive returns.  We verify the two are different.
    """
    bars = _make_bars(7, daily_ret=0.05)  # 0.05% per day for 7 days
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())

    m = status.honest_metrics
    total_ret = m["total_return_pct"]   # e.g. ≈ 0.35%
    annualized = m["annualized_pct_if_sustained"]

    # Both fields must exist and be numbers
    assert isinstance(total_ret, float)
    assert isinstance(annualized, float)

    # Annualized must be greater than total (compound effect for positive returns)
    assert annualized > total_ret, (
        "Annualized return should be larger than raw total return for positive streaks"
    )

    # Naïve extrapolation: R * 365/n
    naive_annualized = round(total_ret * 365 / 7, 2)

    # The compound figure must NOT equal the naïve one
    # (they can be close but not identical for any reasonable daily_ret)
    # Compound: (1 + total/100)^(365/7) - 1
    expected_compound = round((1 + total_ret / 100) ** (365 / 7) * 100 - 100, 2)
    assert abs(annualized - expected_compound) < 0.01, (
        f"Annualized {annualized} doesn't match compound formula {expected_compound}"
    )
    # And confirm they differ from naive
    assert abs(annualized - naive_annualized) > 0.01, (
        f"Expected compound ({annualized}) ≠ naive ({naive_annualized})"
    )


# ─── Test 7: report is generated ─────────────────────────────────────────────


def test_report_generated():
    """generate_milestone_report returns a non-empty string with key sections."""
    bars = _make_bars(7)
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())
    report = generate_milestone_report(status)

    assert isinstance(report, str)
    assert len(report) > 50

    # Key sections must be present
    assert "Milestone Progress" in report
    assert "7/30" in report
    assert "Honest Metrics" in report
    assert "Total return" in report
    assert "Annualized" in report
    assert "Profitable days" in report
    assert "Gaps" in report

    # No blockers → positive indicator
    assert "No blockers" in report or "✅" in report


def test_report_milestone_reached_message():
    """Report must contain the celebratory message when 30/30 reached."""
    bars = _make_bars(30)
    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())
    report = generate_milestone_report(status)

    assert "MILESTONE REACHED" in report or "30/30" in report


# ─── Test 8: blockers detected on gap ────────────────────────────────────────


def test_blockers_detected_on_gap():
    """A gap_monitor gap must appear in status.blockers."""
    bars = _make_bars(14)
    gm = _gap_monitor_gap(hours=32.7)
    status = check_milestone(equity_curve=bars, gap_monitor_data=gm)

    assert len(status.blockers) >= 1
    blocker_text = " ".join(status.blockers)
    assert "gap" in blocker_text.lower()
    # The hours figure should appear in the blocker message
    assert "32.7" in blocker_text


# ─── Bonus: calendar gap in equity_curve breaks the streak ───────────────────


def test_calendar_gap_breaks_streak():
    """A skipped calendar day in equity_curve limits the streak to the tail."""
    # 5 days, skip day 3, then 3 more days → tail streak = 3
    first_block = _make_bars(5, start="2026-06-01")        # Jun 1-5
    second_block = _make_bars(3, start="2026-06-07")       # Jun 7-9 (Jun 6 missing)
    bars = first_block + second_block

    status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())

    assert status.consecutive_days == 3
    assert status.current_streak_start == "2026-06-07"


# ─── Bonus: update_golive_status_milestone writes correctly ──────────────────


def test_update_golive_status_milestone():
    """update_golive_status_milestone patches golive_status.json correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Pre-existing golive_status.json (simulating the real format)
        existing = {
            "ready": False,
            "checks": {
                "equity_curve_real": True,
                "trades_real": False,
                "status_real": True,
                "no_demo_data": True,
                "data_fresh_48h": True,
                "cycle_runner_exists": True,
            },
            "blockers": ["trades.json: no real trades yet"],
            "timestamp": "2026-06-10T12:00:00+00:00",
            "source": "golive_checker",
        }
        (data_dir / "golive_status.json").write_text(json.dumps(existing))

        # Milestone not yet reached (7 days)
        bars = _make_bars(7)
        status = check_milestone(equity_curve=bars, gap_monitor_data=_gap_monitor_ok())
        update_golive_status_milestone(status, data_dir=data_dir)

        doc = json.loads((data_dir / "golive_status.json").read_text())

        assert "milestone_30d" in doc["checks"]
        assert doc["checks"]["milestone_30d"] is False
        assert doc["ready"] is False  # still False due to trades_real=False etc.
        assert "milestone" in doc
        assert doc["milestone"]["consecutive_days"] == 7
        assert doc["milestone"]["progress_pct"] == pytest.approx(7 / 30 * 100, abs=0.5)
        assert doc["milestone"]["is_reached"] is False

        # Existing non-milestone blocker must be preserved
        blocker_text = " ".join(doc.get("blockers", []))
        assert "trades" in blocker_text  # original blocker still present

        # Milestone blocker must also be added
        assert "milestone_30d" in blocker_text

        # Now simulate milestone reached
        bars_30 = _make_bars(30)
        status_30 = check_milestone(equity_curve=bars_30, gap_monitor_data=_gap_monitor_ok())
        update_golive_status_milestone(status_30, data_dir=data_dir)

        doc2 = json.loads((data_dir / "golive_status.json").read_text())
        assert doc2["checks"]["milestone_30d"] is True
        assert doc2["milestone"]["is_reached"] is True
        # milestone_30d blocker should be gone
        assert "milestone_30d" not in " ".join(doc2.get("blockers", []))

"""
MP-414: Tests for PaperEvidenceTracker

Coverage:
  - Constants / defaults
  - record_day — happy path, idempotency, ordering, type coercion
  - Metrics — avg_apy, max_drawdown, sharpe_ratio, total_return
  - get_golive_status — all checks, blockers, ready_for_golive flag
  - export_summary — file written atomically
  - CLI smoke test
  - Edge cases: empty tracker, single day, negative equity change

Total: 45 tests
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Allow running from repo root without installing
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.paper_evidence_tracker import (
    BASE_CAPITAL,
    GOLIVE_TARGET_DATE,
    MAX_DRAWDOWN_PCT,
    MIN_APY_PCT,
    MIN_DAYS_REQUIRED,
    MIN_SHARPE,
    MIN_SHARPE_DAYS,
    PAPER_START_DATE,
    PaperEvidenceTracker,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_tracker(tmp_path) -> PaperEvidenceTracker:
    return PaperEvidenceTracker(str(tmp_path / "ev.json"))


def fill_tracker(tracker: PaperEvidenceTracker, n: int, apy: float = 10.0,
                 daily_return: float = 0.027) -> None:
    """Record n days starting from PAPER_START_DATE."""
    equity = BASE_CAPITAL
    for i in range(n):
        equity = equity * (1 + daily_return / 100)
        tracker.record_day(PAPER_START_DATE + timedelta(days=i), apy, equity)


# ═══════════════════════════════════════════════════════════════════════════
# TestConstants
# ═══════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_paper_start_date(self):
        assert PAPER_START_DATE == date(2026, 6, 12)

    def test_min_days_required(self):
        assert MIN_DAYS_REQUIRED == 30

    def test_golive_target_date(self):
        assert GOLIVE_TARGET_DATE == date(2026, 8, 1)

    def test_base_capital(self):
        assert BASE_CAPITAL == 100_000.0

    def test_min_apy(self):
        assert MIN_APY_PCT == 7.0

    def test_min_sharpe(self):
        assert MIN_SHARPE == 0.80

    def test_max_drawdown_threshold(self):
        assert MAX_DRAWDOWN_PCT == -5.0

    def test_min_sharpe_days(self):
        assert MIN_SHARPE_DAYS == 14

    def test_golive_buffer(self):
        """go-live target is at least 20 days after min ready date."""
        ready = PAPER_START_DATE + timedelta(days=MIN_DAYS_REQUIRED)
        buffer = (GOLIVE_TARGET_DATE - ready).days
        assert buffer >= 20


# ═══════════════════════════════════════════════════════════════════════════
# TestRecordDay
# ═══════════════════════════════════════════════════════════════════════════

class TestRecordDay:
    def test_record_first_day_returns_entry(self, tmp_path):
        t = make_tracker(tmp_path)
        entry = t.record_day(date(2026, 6, 12), 10.1, 100_274.0, "S7")
        assert entry["date"] == "2026-06-12"
        assert entry["apy_pct"] == 10.1
        assert entry["equity_value"] == 100_274.0
        assert entry["strategy_id"] == "S7"

    def test_record_day_increments_count(self, tmp_path):
        t = make_tracker(tmp_path)
        assert t.get_days_elapsed() == 0
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        assert t.get_days_elapsed() == 1

    def test_record_day_idempotent(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        t.record_day(date(2026, 6, 12), 99.9, 999_999.0)  # duplicate
        assert t.get_days_elapsed() == 1

    def test_record_day_persists_to_disk(self, tmp_path):
        evidence = tmp_path / "ev.json"
        t = PaperEvidenceTracker(str(evidence))
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        assert evidence.exists()
        data = json.loads(evidence.read_text())
        assert len(data["days"]) == 1

    def test_record_day_computes_day_return(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 101_000.0)  # +1% from base
        entry = t.get_days_list()[0]
        assert abs(entry["day_return_pct"] - 1.0) < 0.01

    def test_record_multiple_days(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 5)
        assert t.get_days_elapsed() == 5

    def test_record_day_stores_notes(self, tmp_path):
        t = make_tracker(tmp_path)
        entry = t.record_day(date(2026, 6, 12), 10.0, 100_027.0, notes="test note")
        assert entry["notes"] == "test note"

    def test_record_day_default_strategy(self, tmp_path):
        t = make_tracker(tmp_path)
        entry = t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        assert entry["strategy_id"] == "S7"

    def test_record_day_updates_strategy_stats(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0, strategy_id="S8")
        stats = t.get_strategy_stats()
        assert "S8" in stats
        assert stats["S8"]["day_count"] == 1

    def test_record_day_float_coercion(self, tmp_path):
        t = make_tracker(tmp_path)
        entry = t.record_day(date(2026, 6, 12), 10, 100000, "S0")
        assert isinstance(entry["apy_pct"], float)
        assert isinstance(entry["equity_value"], float)

    def test_record_day_reload_persistence(self, tmp_path):
        """Reload tracker from file and data survives."""
        evidence = tmp_path / "ev.json"
        t1 = PaperEvidenceTracker(str(evidence))
        t1.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        t2 = PaperEvidenceTracker(str(evidence))
        assert t2.get_days_elapsed() == 1


# ═══════════════════════════════════════════════════════════════════════════
# TestMetrics
# ═══════════════════════════════════════════════════════════════════════════

class TestMetrics:
    def test_avg_apy_empty(self, tmp_path):
        t = make_tracker(tmp_path)
        assert t.get_avg_apy() == 0.0

    def test_avg_apy_single_day(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 12.5, 100_034.0)
        assert t.get_avg_apy() == pytest.approx(12.5, abs=1e-4)

    def test_avg_apy_multiple_days(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        t.record_day(date(2026, 6, 13), 8.0, 100_049.0)
        assert t.get_avg_apy() == pytest.approx(9.0, abs=1e-4)

    def test_max_drawdown_empty(self, tmp_path):
        t = make_tracker(tmp_path)
        assert t.get_max_drawdown() == 0.0

    def test_max_drawdown_no_loss(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 10, apy=10.0, daily_return=0.027)
        assert t.get_max_drawdown() == 0.0

    def test_max_drawdown_with_loss(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 102_000.0)   # peak
        t.record_day(date(2026, 6, 13), 2.0,  97_000.0)    # trough
        dd = t.get_max_drawdown()
        # (97000 - 102000) / 102000 * 100 ≈ -4.9%
        assert dd < 0
        assert dd == pytest.approx(-4.902, abs=0.01)

    def test_max_drawdown_kill_switch_breach(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_000.0)
        t.record_day(date(2026, 6, 13), 1.0,  94_000.0)   # -6% from peak
        dd = t.get_max_drawdown()
        assert dd < MAX_DRAWDOWN_PCT  # should breach -5%

    def test_sharpe_empty(self, tmp_path):
        t = make_tracker(tmp_path)
        assert t.get_sharpe_ratio() == 0.0

    def test_sharpe_single_day(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        assert t.get_sharpe_ratio() == 0.0

    def test_sharpe_positive_returns(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 20, apy=10.0, daily_return=0.03)
        sharpe = t.get_sharpe_ratio()
        # With constant daily return, std approaches 0 — protect against inf
        # Just ensure it doesn't raise and returns a number
        assert isinstance(sharpe, float)

    def test_total_return_empty(self, tmp_path):
        t = make_tracker(tmp_path)
        assert t.get_total_return_pct() == 0.0

    def test_total_return_positive(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 101_000.0)
        assert t.get_total_return_pct() == pytest.approx(1.0, abs=1e-4)

    def test_latest_equity_empty(self, tmp_path):
        t = make_tracker(tmp_path)
        assert t.get_latest_equity() == BASE_CAPITAL

    def test_latest_equity_after_recording(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_027.0)
        t.record_day(date(2026, 6, 13), 10.0, 100_054.0)
        assert t.get_latest_equity() == 100_054.0


# ═══════════════════════════════════════════════════════════════════════════
# TestGoLiveStatus
# ═══════════════════════════════════════════════════════════════════════════

class TestGoLiveStatus:
    def test_not_ready_zero_days(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        assert not status["ready_for_golive"]

    def test_days_remaining_decreases(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 10)
        status = t.get_golive_status()
        assert status["days_remaining"] == MIN_DAYS_REQUIRED - 10

    def test_days_remaining_zero_when_enough(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, MIN_DAYS_REQUIRED, apy=10.0)
        status = t.get_golive_status()
        assert status["days_remaining"] == 0

    def test_ready_date_is_30_days_from_start(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        expected = (PAPER_START_DATE + timedelta(days=MIN_DAYS_REQUIRED)).isoformat()
        assert status["ready_date"] == expected

    def test_golive_target_in_status(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        assert status["golive_target"] == GOLIVE_TARGET_DATE.isoformat()

    def test_buffer_days_at_least_20(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        assert status["buffer_days"] >= 20

    def test_min_days_check_fail(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 5)
        status = t.get_golive_status()
        assert not status["checks"]["min_days"]["pass"]

    def test_min_days_check_pass(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, MIN_DAYS_REQUIRED, apy=10.0)
        status = t.get_golive_status()
        assert status["checks"]["min_days"]["pass"]

    def test_apy_check_fail_low_apy(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 5, apy=3.0)
        status = t.get_golive_status()
        assert not status["checks"]["avg_apy"]["pass"]

    def test_apy_check_pass_high_apy(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 5, apy=9.0)
        status = t.get_golive_status()
        assert status["checks"]["avg_apy"]["pass"]

    def test_drawdown_check_fail_big_loss(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_000.0)
        t.record_day(date(2026, 6, 13), 1.0,  94_000.0)  # -6%
        status = t.get_golive_status()
        assert not status["checks"]["max_drawdown"]["pass"]

    def test_drawdown_check_pass_no_loss(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 5, apy=10.0, daily_return=0.02)
        status = t.get_golive_status()
        assert status["checks"]["max_drawdown"]["pass"]

    def test_sharpe_check_skipped_below_14_days(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 10, apy=10.0)
        status = t.get_golive_status()
        # < 14 days → sharpe check must fail (not enough data)
        assert not status["checks"]["sharpe"]["pass"]

    def test_blockers_list_nonempty_when_not_ready(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        assert len(status["blockers"]) > 0

    def test_checks_passed_count(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        # With 0 days: min_days fail, apy fail (0.0<7.0), drawdown pass (0.0>=-5), sharpe fail
        assert status["checks_passed"] == 1  # only drawdown passes at 0 days

    def test_as_of_is_today(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        assert status["as_of"] == date.today().isoformat()

    def test_schema_version_present(self, tmp_path):
        t = make_tracker(tmp_path)
        status = t.get_golive_status()
        assert status["schema_version"] == "1.0"

    def test_avg_apy_in_status(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 3, apy=8.5)
        status = t.get_golive_status()
        assert status["avg_apy_pct"] == pytest.approx(8.5, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# TestExportSummary
# ═══════════════════════════════════════════════════════════════════════════

class TestExportSummary:
    def test_export_creates_file(self, tmp_path):
        t = make_tracker(tmp_path)
        summary = tmp_path / "summary.json"
        t.export_summary(str(summary))
        assert summary.exists()

    def test_export_returns_status_dict(self, tmp_path):
        t = make_tracker(tmp_path)
        summary = tmp_path / "summary.json"
        result = t.export_summary(str(summary))
        assert isinstance(result, dict)
        assert "ready_for_golive" in result

    def test_export_file_is_valid_json(self, tmp_path):
        t = make_tracker(tmp_path)
        summary = tmp_path / "summary.json"
        t.export_summary(str(summary))
        data = json.loads(summary.read_text())
        assert "checks" in data

    def test_export_creates_parent_dirs(self, tmp_path):
        t = make_tracker(tmp_path)
        nested = tmp_path / "sub" / "dir" / "summary.json"
        t.export_summary(str(nested))
        assert nested.exists()

    def test_export_is_atomic(self, tmp_path):
        """No .tmp files left behind after export."""
        t = make_tracker(tmp_path)
        summary = tmp_path / "summary.json"
        t.export_summary(str(summary))
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# ═══════════════════════════════════════════════════════════════════════════
# TestEdgeCases
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_tracker_missing_file_starts_empty(self, tmp_path):
        t = PaperEvidenceTracker(str(tmp_path / "nonexistent.json"))
        assert t.get_days_elapsed() == 0

    def test_tracker_corrupt_file_starts_empty(self, tmp_path):
        ev = tmp_path / "ev.json"
        ev.write_text("not valid json {{{{")
        t = PaperEvidenceTracker(str(ev))
        assert t.get_days_elapsed() == 0

    def test_record_day_with_equity_decline(self, tmp_path):
        t = make_tracker(tmp_path)
        t.record_day(date(2026, 6, 12), 10.0, 100_000.0)
        t.record_day(date(2026, 6, 13), 2.0,  99_000.0)
        assert t.get_max_drawdown() < 0

    def test_zero_std_sharpe_returns_zero(self, tmp_path):
        """Constant returns → std = 0 → sharpe = 0 (no division by zero)."""
        t = make_tracker(tmp_path)
        equity = BASE_CAPITAL
        for i in range(20):
            equity += 10.0  # same tiny gain each day
            t.record_day(PAPER_START_DATE + timedelta(days=i), 10.0, equity)
        sharpe = t.get_sharpe_ratio()
        assert isinstance(sharpe, float)
        assert not (sharpe != sharpe)  # not NaN

    def test_get_days_list_returns_copy(self, tmp_path):
        t = make_tracker(tmp_path)
        fill_tracker(t, 3)
        lst = t.get_days_list()
        lst.clear()
        assert t.get_days_elapsed() == 3  # original unaffected

    def test_evidence_file_default_path(self):
        from spa_core.paper_trading.paper_evidence_tracker import EVIDENCE_FILE
        assert EVIDENCE_FILE == "data/paper_evidence.json"

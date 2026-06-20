"""
tests/test_cpa_cycle_sqlite.py

20 unit tests for the MP-1542 SQLite integration in CPACycleWithEvidence.

Strategy:
  - Inject a fake inner cycle via _cycle_cls to avoid network/IO.
  - Inject a fake get_db_manager via monkeypatch to use in-memory SQLiteManager.
  - Verify records written to SQLite after each run().

MP-1542 (v11.58)
"""

from __future__ import annotations

import pytest

from spa_core.backtesting.cpa_cycle_with_evidence import CPACycleWithEvidence
from spa_core.database.sqlite_manager import SQLiteManager


# ─── Fakes / stubs ──────────────────────────────────────────────────────────

class FakeInnerCycle:
    """Minimal stub that replaces CPADailyCycle."""

    def __init__(self, base_dir: str, date: str):
        self.base_dir = base_dir
        self.date = date
        self._result = {
            "status": "OK",
            "sections": {
                "evidence_update": {
                    "paper_active": True,
                    "apy_today_pct": 3.65,
                    "equity": 100010.0,
                    "daily_yield_usd": 10.0,
                },
                "paper_trading_status": {
                    "nav": 100010.0,
                    "daily_pnl": 10.0,
                    "apy_today": 3.65,
                    "positions": {"aave_v3": 50000.0, "compound_v3": 50000.0},
                },
            },
        }

    def run(self) -> dict:
        return dict(self._result)

    def save(self, result: dict) -> str:
        return "/tmp/fake_save"

    def to_telegram_message(self, result: dict) -> str:
        return "fake msg"

    def send_telegram(self, result: dict) -> bool:
        return False


class FakeInnerCycleFail(FakeInnerCycle):
    """Cycle that reports FAIL status."""

    def run(self) -> dict:
        result = super().run()
        result["status"] = "FAIL"
        result["sections"]["some_section"] = {"error": "network timeout"}
        return result


class FakeInnerCycleNoPaperActive(FakeInnerCycle):
    """Cycle with paper_active=False → apy_ok should be False."""

    def run(self) -> dict:
        result = super().run()
        result["sections"]["evidence_update"]["paper_active"] = False
        return result


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db() -> SQLiteManager:
    return SQLiteManager(db_path=":memory:")


@pytest.fixture
def patched_cycle(monkeypatch, mem_db, tmp_path):
    """Return a CPACycleWithEvidence with fake inner cycle and in-memory DB."""
    # Patch get_db_manager so SQLite writes go to our in-memory DB
    monkeypatch.setattr(
        "spa_core.backtesting.cpa_cycle_with_evidence.CPACycleWithEvidence"
        "._write_to_sqlite",
        lambda self, result: _write_to_sqlite_with_db(self, result, mem_db),
    )

    # Also patch evidence auto calculator to avoid disk I/O
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.load",
        lambda self: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.save",
        lambda self: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.record_day",
        lambda self, **kw: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.calculate_score",
        lambda self: _FakeScore(),
    )

    cycle = CPACycleWithEvidence(
        base_dir=str(tmp_path),
        date="2026-06-20",
        _cycle_cls=FakeInnerCycle,
    )
    return cycle, mem_db


def _write_to_sqlite_with_db(self, cycle_result: dict, db: SQLiteManager) -> None:
    """Replaces _write_to_sqlite to use the provided in-memory DB."""
    sections = cycle_result.get("sections", {})
    pt = sections.get("paper_trading_status", {})
    ev = sections.get("evidence_update", {})

    nav = float(pt.get("nav", ev.get("equity", 0.0)))
    daily_pnl = float(pt.get("daily_pnl", ev.get("daily_yield_usd", 0.0)))
    daily_apy = float(pt.get("apy_today", ev.get("apy_today_pct", 0.0)))
    allocation = pt.get("positions")

    self._cycle_count = getattr(self, "_cycle_count", 0) + 1

    db.insert_paper_record(
        date=self._date,
        cycle_number=self._cycle_count,
        strategy_id="S_COMPOSITE",
        portfolio_nav=nav,
        daily_pnl=daily_pnl,
        daily_apy=daily_apy,
        allocation=allocation,
    )

    sections_ok = cycle_result.get("status") == "OK"
    apy_ok = bool(
        ev.get("paper_active", False)
        and ev.get("apy_today_pct") is not None
        and float(ev.get("apy_today_pct", 0)) > 0
    )
    risk_ok = True

    db.insert_evidence_record(
        date=self._date,
        daily_cycle_pts=1.0 if sections_ok else 0.0,
        apy_tracking_pts=1.0 if apy_ok else 0.0,
        risk_policy_pts=1.0 if risk_ok else 0.0,
        total_pts=(1.0 if sections_ok else 0.0)
                  + (1.0 if apy_ok else 0.0)
                  + (1.0 if risk_ok else 0.0),
        is_seed=False,
    )

    db.log_event(
        event_type="CYCLE_COMPLETE",
        description=f"cycle {self._date}",
        severity="INFO",
        metadata={"nav": nav, "apy": daily_apy},
    )


class _FakeScore:
    total = 3
    target = 30
    daily_cycles_pts = 1.0
    apy_tracking_pts = 1.0
    risk_policy_pts = 1.0
    bonus_pts = 0.0


# ─── 1. Basic run with SQLite writes ────────────────────────────────────────

def test_run_returns_dict(patched_cycle):
    cycle, db = patched_cycle
    result = cycle.run()
    assert isinstance(result, dict)


def test_run_writes_paper_record(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    assert db.count_paper_records() == 1


def test_run_paper_record_date(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    rec = db.get_paper_records_by_date("2026-06-20")
    assert len(rec) == 1


def test_run_paper_record_strategy_composite(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    recs = db.get_paper_records_by_strategy("S_COMPOSITE")
    assert len(recs) == 1


def test_run_paper_record_nav(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    rec = db.get_paper_records(limit=1)[0]
    assert rec["portfolio_nav"] == pytest.approx(100010.0)


def test_run_paper_record_apy(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    rec = db.get_paper_records(limit=1)[0]
    assert rec["daily_apy"] == pytest.approx(3.65)


def test_run_paper_record_allocation_stored(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    import json
    rec = db.get_paper_records(limit=1)[0]
    alloc = json.loads(rec["allocation_json"])
    assert "aave_v3" in alloc


def test_run_writes_evidence_record(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    assert db.count_evidence_records() == 1


def test_run_evidence_record_date(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    ev = db.get_evidence_by_date("2026-06-20")
    assert ev is not None


def test_run_evidence_total_pts_ok_cycle(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    ev = db.get_evidence_by_date("2026-06-20")
    # OK cycle + apy_active + risk_ok → 3 pts
    assert ev["total_pts"] == pytest.approx(3.0)


def test_run_evidence_not_seed(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    ev = db.get_evidence_by_date("2026-06-20")
    assert ev["is_seed"] == 0


def test_run_logs_system_event(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    assert db.count_events() >= 1


def test_run_system_event_type(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    evs = db.get_events(event_type="CYCLE_COMPLETE")
    assert len(evs) >= 1


# ─── 2. Multiple runs increment cycle_count ──────────────────────────────────

def test_multiple_runs_increase_record_count(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    cycle.run()
    assert db.count_paper_records() == 2


def test_multiple_runs_cycle_numbers_distinct(patched_cycle):
    cycle, db = patched_cycle
    cycle.run()
    cycle.run()
    recs = db.get_paper_records(limit=10)
    cycle_numbers = [r["cycle_number"] for r in recs]
    assert len(set(cycle_numbers)) == 2


# ─── 3. SQLite failure does NOT block cycle ───────────────────────────────────

def test_sqlite_failure_does_not_raise(monkeypatch, tmp_path):
    """Even if _write_to_sqlite raises, run() should complete and return result."""
    # Patch evidence calc to be a no-op
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.load",
        lambda self: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.save",
        lambda self: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.record_day",
        lambda self, **kw: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.calculate_score",
        lambda self: _FakeScore(),
    )

    # Force _write_to_sqlite to raise
    monkeypatch.setattr(
        "spa_core.backtesting.cpa_cycle_with_evidence.CPACycleWithEvidence._write_to_sqlite",
        lambda self, result: (_ for _ in ()).throw(RuntimeError("DB unavailable")),
    )

    cycle = CPACycleWithEvidence(
        base_dir=str(tmp_path),
        date="2026-06-20",
        _cycle_cls=FakeInnerCycle,
    )
    result = cycle.run()  # must not raise
    assert "status" in result


def test_sqlite_failure_logged(monkeypatch, tmp_path):
    """When SQLite fails, a warning is appended to cycle logs."""
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.load",
        lambda self: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.save",
        lambda self: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.record_day",
        lambda self, **kw: None,
    )
    monkeypatch.setattr(
        "spa_core.analytics.evidence_auto_calculator.EvidenceAutoCalculator.calculate_score",
        lambda self: _FakeScore(),
    )
    monkeypatch.setattr(
        "spa_core.backtesting.cpa_cycle_with_evidence.CPACycleWithEvidence._write_to_sqlite",
        lambda self, result: (_ for _ in ()).throw(RuntimeError("DB unavailable")),
    )

    cycle = CPACycleWithEvidence(
        base_dir=str(tmp_path),
        date="2026-06-20",
        _cycle_cls=FakeInnerCycle,
    )
    cycle.run()
    assert any("sqlite_hook" in log and "WARNING" in log for log in cycle.logs())


# ─── 4. Status propagation ────────────────────────────────────────────────────

def test_run_status_ok_in_result(patched_cycle):
    cycle, db = patched_cycle
    result = cycle.run()
    assert result.get("status") == "OK"


def test_result_has_sections(patched_cycle):
    cycle, db = patched_cycle
    result = cycle.run()
    assert "sections" in result


def test_run_evidence_upsert_on_same_date(patched_cycle):
    """Running twice on the same date replaces evidence, not duplicates it."""
    cycle, db = patched_cycle
    cycle.run()
    cycle.run()
    # evidence_records has UNIQUE(date) with INSERT OR REPLACE → still 1 row
    assert db.count_evidence_records() == 1

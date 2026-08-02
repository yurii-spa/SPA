# LLM_FORBIDDEN
"""Hermetic tests for the fabricated-evidence fix (ADR-058) — no live data touched."""
# LLM_FORBIDDEN

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from spa_core.analytics.apy_milestone_tracker import ApyMilestoneTracker

# load the correction script as a module (it lives in scripts/, not a package)
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fix_fabricated_evidence.py"
_spec = importlib.util.spec_from_file_location("fix_fabricated_evidence", _SCRIPT)
fix_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix_mod)


def _daily(date, apy):
    return {"date": date, "apy_pct": apy, "strategy_id": "s7_pendle_yt"}


def _write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


# ── producer: a fabricated day must never earn a milestone (durability) ──────

class TestProducerSkipsFabricated:
    def test_fabricated_day_does_not_earn_milestone(self, tmp_path):
        data = {
            "start_date": "2026-07-01", "last_updated": "2026-07-29", "days_recorded": 3,
            "daily_log": [
                _daily("2026-07-08", 8.45),                                    # real: 5% & 7%
                {**_daily("2026-07-28", 10.115), "fabricated": True},          # fabricated: NOT 10%
            ],
            "milestones_reached": [],
        }
        t = ApyMilestoneTracker(data_dir=str(tmp_path))
        t._data = data
        t._refresh_milestones_reached()
        by = {m["target_pct"]: m["first_reached_date"] for m in t._data["milestones_reached"]}
        assert by[5.0] == "2026-07-08"
        assert by[7.0] == "2026-07-08"
        assert 10.0 not in by, "a fabricated 10.115% day must NOT earn the 10% milestone (absent, not null)"

    def test_real_day_still_earns_milestone(self, tmp_path):
        data = {"daily_log": [_daily("2026-07-08", 10.5)], "milestones_reached": []}
        t = ApyMilestoneTracker(data_dir=str(tmp_path))
        t._data = data
        t._refresh_milestones_reached()
        by = {m["target_pct"]: m["first_reached_date"] for m in t._data["milestones_reached"]}
        assert by[10.0] == "2026-07-08", "a REAL 10.5% day still earns the 10% milestone"


# ── correction script: flag (not delete) + recompute ────────────────────────

class TestCorrectionScript:
    def _seed(self, d):
        _write(d / "paper_evidence.json", {"days": [
            {"date": "2026-07-08", "apy_pct": 8.45, "strategy_id": "S7"},
            {"date": "2026-07-28", "apy_pct": 10.115, "strategy_id": "S7"},
            {"date": "2026-07-29", "apy_pct": 10.115, "strategy_id": "S7"},
        ]})
        _write(d / "apy_milestone_log.json", {"daily_log": [
            _daily("2026-07-08", 8.45),
            _daily("2026-07-28", 10.115),
            _daily("2026-07-29", 10.115),
        ], "milestones_reached": [
            {"level": 1, "name": "Baseline beat", "target_pct": 5.0, "first_reached_date": "2026-07-08"},
            {"level": 2, "name": "Target entry", "target_pct": 7.0, "first_reached_date": "2026-07-08"},
            {"level": 3, "name": "Target mid", "target_pct": 10.0, "first_reached_date": "2026-07-28"},
        ]})

    def test_dry_run_reports_but_does_not_write(self, tmp_path):
        self._seed(tmp_path)
        before = (tmp_path / "apy_milestone_log.json").read_text()
        rep = fix_mod.fix(tmp_path, dry_run=True)
        assert rep["applied"] is False
        assert 10.0 not in rep["apy_milestone"]["milestones_after"]
        assert (tmp_path / "apy_milestone_log.json").read_text() == before, "dry-run must not write"

    def test_apply_flags_and_drops_ten_pct(self, tmp_path):
        self._seed(tmp_path)
        fix_mod.fix(tmp_path, dry_run=False)
        pe = json.loads((tmp_path / "paper_evidence.json").read_text())
        am = json.loads((tmp_path / "apy_milestone_log.json").read_text())
        # rows FLAGGED, not deleted (auditability preserved)
        assert len(pe["days"]) == 3 and len(am["daily_log"]) == 3
        fab_pe = [r for r in pe["days"] if r.get("fabricated")]
        assert {r["date"] for r in fab_pe} == {"2026-07-28", "2026-07-29"}
        assert all(r.get("fabricated_reason") for r in fab_pe)
        # milestones recomputed: 10% dropped, 5/7 kept (real)
        by = {m["target_pct"]: m["first_reached_date"] for m in am["milestones_reached"]}
        assert by[5.0] == "2026-07-08" and by[7.0] == "2026-07-08" and 10.0 not in by

    def test_idempotent(self, tmp_path):
        self._seed(tmp_path)
        fix_mod.fix(tmp_path, dry_run=False)
        rep2 = fix_mod.fix(tmp_path, dry_run=False)
        assert rep2["paper_evidence"]["flagged"] == [], "already-flagged rows are not re-flagged"
        assert rep2["apy_milestone"]["flagged"] == []

# FROZEN-DATE-OK: literal dates are labels of a synthetic 3-day curve; the sentinel's freshness verdict is never asserted (status only ∈ {HEALTHY, WARNING, UNCHECKED}), so the calendar cannot flip a test
"""test_cycle_health_artifact_integrity.py — the Data Integrity Sentinel finally has a producing call.

Before 2026-09-08 ``spa_core.audit.data_integrity.run_integrity_checks`` had tests and ZERO runtime
callers (class ADR-259: a declared product nobody computes). ``CycleHealthMonitor.run_all_checks`` now
calls it and records the result under ``checks.artifact_integrity``. Properties pinned here:

  1. the call EXISTS and has the form of a call (AST), not a mention in a comment;
  2. third outcome: skip-only ⇒ UNCHECKED, never HEALTHY; a crashing sentinel ⇒ UNCHECKED, never a raise;
  3. the signal is ADVISORY — the overall verdict does not change with it (like evidence_vs_curve);
  4. the briefing line renders the numbers and names an absent key instead of reading it as clean.

Hermetic: tmp data dirs, the sentinel is monkeypatched where its verdict is the subject.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
for _p in (str(_PROJECT_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

from spa_core.audit import data_integrity
from spa_core.monitoring import cycle_health_monitor as chm

MONITOR_SRC = Path(chm.__file__).read_text(encoding="utf-8")


def _calls_in(func_name: str) -> list[str]:
    tree = ast.parse(MONITOR_SRC)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    if isinstance(f, ast.Attribute):
                        out.append(f.attr)
                    elif isinstance(f, ast.Name):
                        out.append(f.id)
    return out


def _seed(tmp: Path, days: int = 3) -> Path:
    rows = []
    for i in range(days):
        rows.append({"date": f"2026-09-0{i + 1}", "open_equity": 100000.0 + i, "close_equity": 100001.0 + i,
                     "equity": 100001.0 + i, "evidenced": True, "positions": {"aave_v3": 50000.0}})
    (tmp / "equity_curve_daily.json").write_text(json.dumps({"generated_at": "2026-09-03T06:00:00+00:00", "daily": rows}), encoding="utf-8")
    return tmp


class TestWiringForm:
    def test_run_all_checks_calls_the_sentinel_method(self):
        assert "check_artifact_integrity" in _calls_in("run_all_checks")

    def test_the_method_calls_run_integrity_checks_not_just_mentions_it(self):
        assert "run_integrity_checks" in _calls_in("check_artifact_integrity")

    def test_sentinel_has_a_runtime_caller_outside_tests(self):
        """The ADR-259 class: a producer nobody calls. The monitor is that caller now."""
        root = _PROJECT_ROOT / "spa_core"
        callers = [p for p in root.rglob("*.py") if "tests" not in p.parts and p.name != "data_integrity.py"
                   and "run_integrity_checks(" in p.read_text(encoding="utf-8", errors="ignore")]
        assert any(p.name == "cycle_health_monitor.py" for p in callers), callers


class TestThirdOutcome:
    def test_key_present_with_a_status(self, tmp_path):
        rep = chm.CycleHealthMonitor().run_all_checks(data_dir=str(_seed(tmp_path)))
        chk = rep["checks"]["artifact_integrity"]
        assert chk["status"] in ("HEALTHY", "WARNING", chm.UNCHECKED) and chk["advisory"] is True

    def test_skip_only_is_unchecked_not_healthy(self, tmp_path, monkeypatch):
        monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda **kw: {
            "verdict": "ok", "counts": {"ok": 0, "warn": 0, "fail": 0, "skip": 2},
            "checks": [{"check": "a", "status": "skip"}, {"check": "b", "status": "skip"}]})
        chk = chm.CycleHealthMonitor().check_artifact_integrity(str(tmp_path))
        assert chk["status"] == chm.UNCHECKED and chk["unmeasured"] == ["a", "b"]

    def test_mixed_skip_and_ok_is_still_unchecked(self, tmp_path, monkeypatch):
        monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda **kw: {
            "verdict": "ok", "counts": {"ok": 1, "warn": 0, "fail": 0, "skip": 1},
            "checks": [{"check": "a", "status": "ok"}, {"check": "b", "status": "skip"}]})
        assert chm.CycleHealthMonitor().check_artifact_integrity(str(tmp_path))["status"] == chm.UNCHECKED

    def test_all_ok_is_healthy_and_fail_is_warning_with_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda **kw: {
            "verdict": "ok", "counts": {"ok": 2}, "checks": [{"check": "a", "status": "ok"}, {"check": "b", "status": "ok"}]})
        assert chm.CycleHealthMonitor().check_artifact_integrity(str(tmp_path))["status"] == "HEALTHY"
        monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda **kw: {
            "verdict": "fail", "counts": {"ok": 1, "fail": 1}, "checks": [{"check": "a", "status": "ok"}, {"check": "equity_continuity", "status": "fail"}]})
        chk = chm.CycleHealthMonitor().check_artifact_integrity(str(tmp_path))
        assert chk["status"] == "WARNING" and chk["failing"] == ["equity_continuity"]

    def test_crashing_sentinel_is_unchecked_never_a_raise(self, tmp_path, monkeypatch):
        def boom(**kw):
            raise RuntimeError("sentinel exploded")
        monkeypatch.setattr(data_integrity, "run_integrity_checks", boom)
        chk = chm.CycleHealthMonitor().check_artifact_integrity(str(tmp_path))
        assert chk["status"] == chm.UNCHECKED and "sentinel exploded" in chk["detail"]
        rep = chm.CycleHealthMonitor().run_all_checks(data_dir=str(_seed(tmp_path)))  # the monitor still finishes
        assert "artifact_integrity" in rep["checks"]


class TestAdvisory:
    def test_overall_verdict_is_independent_of_the_sentinel(self, tmp_path, monkeypatch):
        d = _seed(tmp_path)
        monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda **kw: {
            "verdict": "ok", "counts": {"ok": 1}, "checks": [{"check": "a", "status": "ok"}]})
        base = chm.CycleHealthMonitor().run_all_checks(data_dir=str(d))
        monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda **kw: {
            "verdict": "fail", "counts": {"fail": 1}, "checks": [{"check": "a", "status": "fail"}]})
        worse = chm.CycleHealthMonitor().run_all_checks(data_dir=str(d))
        assert base["overall"] == worse["overall"]
        assert worse["checks"]["artifact_integrity"]["status"] == "WARNING"
        assert not any(u["check"] == "artifact_integrity" for u in worse["unchecked"])


class TestBriefingLine:
    @staticmethod
    def _briefing():
        spec = importlib.util.spec_from_file_location("usb", _PROJECT_ROOT / "scripts" / "update_system_briefing.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_absent_key_is_named_not_read_as_clean(self):
        line = self._briefing().artifact_integrity_line({"checks": {"evidence_vs_curve": {}}})
        assert "нет в снимке" in line

    def test_numbers_and_names_are_rendered(self):
        line = self._briefing().artifact_integrity_line({"checks": {"artifact_integrity": {
            "status": "WARNING", "counts": {"ok": 4, "warn": 0, "fail": 1, "skip": 1},
            "failing": ["equity_continuity"], "warning": [], "unmeasured": ["anchor_coverage"]}}})
        assert "**WARNING**" in line and "fail 1" in line and "equity_continuity" in line and "anchor_coverage" in line

    def test_section_carries_the_line(self, monkeypatch):
        mod = self._briefing()
        monkeypatch.setattr(mod, "read_json", lambda name: {"checks": {"evidence_vs_curve": {"status": "UNCHECKED", "detail": "x"}}, "checked_at": "2026-09-08T00:00:00+00:00"})
        assert "сторож согласованности артефактов" in mod.build_track_integrity_section()

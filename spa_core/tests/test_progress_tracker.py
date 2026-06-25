#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.progress_tracker (MP-141).

≥40 unittest test cases covering:
- build_progress_report with synthetic data at 3, 7, 12, 30, 90+ days
- Correct days_remaining for each milestone
- eta_date correctness (today + days_remaining)
- summary_verdict: on_track / ahead / at_risk
- run_progress_tracker: atomicity (no *.tmp after write), idempotency
- never_raise on empty / corrupt inputs
- CLI --check / --run via subprocess
- Import hygiene (no forbidden imports)
"""
from __future__ import annotations

import ast
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Ensure the repo root is on sys.path for direct test invocation.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.progress_tracker import (
    GO_LIVE_TARGET_DATE,
    OUTPUT_FILENAME,
    build_progress_report,
    run_progress_tracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_equity_doc(n_days: int, start_date: str = "2026-06-10") -> dict:
    """Build a minimal real equity_curve_daily.json with n_days bars."""
    daily = []
    d = date.fromisoformat(start_date)
    equity = 100_000.0
    for i in range(n_days):
        bar_date = (d + timedelta(days=i)).isoformat()
        close = equity + i * 5.0
        daily.append(
            {
                "date": bar_date,
                "open_equity": round(equity + i * 4.0, 2),
                "close_equity": round(close, 2),
                "equity": round(close, 2),
                "apy_today": 3.5,
                "daily_return_pct": 0.01,
            }
        )
    return {
        "generated_at": "2026-06-12T00:00:00+00:00",
        "source": "cycle_runner",
        "is_demo": False,
        "summary": {"num_days": n_days},
        "daily": daily,
    }


def _make_status_doc(equity: float = 100_026.06, apy: float = 3.5) -> dict:
    return {
        "is_demo": False,
        "source": "cycle_runner",
        "current_equity": equity,
        "apy_today_pct": apy,
        "days_running": 3,
    }


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_to_golive() -> int:
    # Must mirror progress_tracker.build_progress_report, which anchors on the
    # UTC calendar date (datetime.now(timezone.utc)). Using local date.today()
    # here caused a 1-day off-by-one whenever local time and UTC straddle a day
    # boundary.
    from datetime import date as _date
    today_utc = _date.fromisoformat(_today())
    return (_date.fromisoformat(GO_LIVE_TARGET_DATE) - today_utc).days


# ---------------------------------------------------------------------------
# 1. Paper days counting
# ---------------------------------------------------------------------------


class TestPaperDaysCounting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _report(self, n_days):
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(n_days))
        return build_progress_report(data_dir=self.tmp)

    def test_3_days(self):
        r = self._report(3)
        self.assertEqual(r["paper_days"], 3)
        self.assertTrue(r["available"])

    def test_7_days(self):
        r = self._report(7)
        self.assertEqual(r["paper_days"], 7)

    def test_12_days(self):
        r = self._report(12)
        self.assertEqual(r["paper_days"], 12)

    def test_30_days(self):
        r = self._report(30)
        self.assertEqual(r["paper_days"], 30)

    def test_90_days(self):
        r = self._report(90)
        self.assertEqual(r["paper_days"], 90)

    def test_zero_days_no_equity_file(self):
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(r["paper_days"], 0)

    def test_demo_equity_not_counted(self):
        """An equity_curve_daily.json with source != 'cycle_runner' yields 0 days."""
        doc = _make_equity_doc(10)
        doc["source"] = "demo"
        _write_json(self.tmp / "equity_curve_daily.json", doc)
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(r["paper_days"], 0)


# ---------------------------------------------------------------------------
# 2. Paper start date extraction
# ---------------------------------------------------------------------------


class TestPaperStartDate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_start_date_from_equity_curve(self):
        _write_json(
            self.tmp / "equity_curve_daily.json",
            _make_equity_doc(5, start_date="2026-06-10"),
        )
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(r["paper_start_date"], "2026-06-10")

    def test_start_date_none_when_no_file(self):
        r = build_progress_report(data_dir=self.tmp)
        self.assertIsNone(r["paper_start_date"])


# ---------------------------------------------------------------------------
# 3. Milestone days_remaining
# ---------------------------------------------------------------------------


class TestMilestoneDaysRemaining(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _milestones(self, n_days) -> dict:
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(n_days))
        r = build_progress_report(data_dir=self.tmp)
        return {m["id"]: m for m in r["milestones"]}

    def test_3_days_all_not_reached(self):
        ms = self._milestones(3)
        for m in ms.values():
            self.assertFalse(m["reached"])

    def test_3_days_backtest_remaining_is_4(self):
        ms = self._milestones(3)
        self.assertEqual(ms["backtest_contour_min"]["days_remaining"], 4)
        self.assertEqual(ms["honest_metrics_low"]["days_remaining"], 4)

    def test_3_days_structural_break_remaining_is_9(self):
        ms = self._milestones(3)
        self.assertEqual(ms["structural_break_min"]["days_remaining"], 9)

    def test_3_days_moderate_remaining_is_27(self):
        ms = self._milestones(3)
        self.assertEqual(ms["honest_metrics_moderate"]["days_remaining"], 27)

    def test_3_days_high_remaining_is_87(self):
        ms = self._milestones(3)
        self.assertEqual(ms["honest_metrics_high"]["days_remaining"], 87)

    def test_7_days_low_reached(self):
        ms = self._milestones(7)
        self.assertTrue(ms["backtest_contour_min"]["reached"])
        self.assertTrue(ms["honest_metrics_low"]["reached"])
        self.assertFalse(ms["structural_break_min"]["reached"])

    def test_7_days_low_days_remaining_zero(self):
        ms = self._milestones(7)
        self.assertEqual(ms["honest_metrics_low"]["days_remaining"], 0)
        self.assertEqual(ms["backtest_contour_min"]["days_remaining"], 0)

    def test_12_days_structural_break_reached(self):
        ms = self._milestones(12)
        self.assertTrue(ms["structural_break_min"]["reached"])
        self.assertFalse(ms["honest_metrics_moderate"]["reached"])

    def test_30_days_moderate_reached(self):
        ms = self._milestones(30)
        self.assertTrue(ms["honest_metrics_moderate"]["reached"])
        self.assertFalse(ms["honest_metrics_high"]["reached"])

    def test_90_days_all_reached(self):
        ms = self._milestones(90)
        for m in ms.values():
            self.assertTrue(m["reached"], f"{m['id']} not reached at 90 days")

    def test_days_remaining_zero_when_exceeded(self):
        ms = self._milestones(100)
        for m in ms.values():
            self.assertEqual(m["days_remaining"], 0)


# ---------------------------------------------------------------------------
# 4. eta_date correctness
# ---------------------------------------------------------------------------


class TestEtaDate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.today = _today()

    def _ms(self, n_days) -> dict:
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(n_days))
        r = build_progress_report(data_dir=self.tmp)
        return {m["id"]: m for m in r["milestones"]}

    def test_eta_date_is_today_plus_remaining(self):
        ms = self._ms(3)
        for m in ms.values():
            if not m["reached"]:
                expected = (
                    date.fromisoformat(self.today) + timedelta(days=m["days_remaining"])
                ).isoformat()
                self.assertEqual(m["eta_date"], expected, f"eta_date wrong for {m['id']}")

    def test_eta_date_is_today_when_reached(self):
        ms = self._ms(90)
        for m in ms.values():
            self.assertEqual(m["eta_date"], self.today, f"reached milestone has wrong eta_date")


# ---------------------------------------------------------------------------
# 5. summary_verdict
# ---------------------------------------------------------------------------


class TestSummaryVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _verdict(self, n_days):
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(n_days))
        r = build_progress_report(data_dir=self.tmp)
        return r["summary_verdict"]

    def test_on_track_at_3_days(self):
        # days_to_golive is typically 30+ when running tests before 2026-07-01
        dtg = _days_to_golive()
        if dtg >= 14:
            self.assertEqual(self._verdict(3), "on_track")

    def test_ahead_when_moderate_reached(self):
        # 30 days → honest_metrics_moderate reached → verdict = ahead
        self.assertEqual(self._verdict(30), "ahead")

    def test_ahead_when_high_reached(self):
        self.assertEqual(self._verdict(90), "ahead")

    def test_on_track_at_7_days(self):
        dtg = _days_to_golive()
        if dtg >= 14:
            self.assertEqual(self._verdict(7), "on_track")


# ---------------------------------------------------------------------------
# 6. go_live_target_date and days_to_golive
# ---------------------------------------------------------------------------


class TestGoLiveFields(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_go_live_target_date_correct(self):
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(r["go_live_target_date"], GO_LIVE_TARGET_DATE)

    def test_days_to_golive_is_integer(self):
        r = build_progress_report(data_dir=self.tmp)
        self.assertIsInstance(r["days_to_golive"], int)

    def test_days_to_golive_matches_manual_calc(self):
        r = build_progress_report(data_dir=self.tmp)
        expected = _days_to_golive()
        self.assertEqual(r["days_to_golive"], expected)


# ---------------------------------------------------------------------------
# 7. current_equity and apy fallback from status
# ---------------------------------------------------------------------------


class TestEquityAndApyFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_equity_from_status_when_no_equity_file(self):
        _write_json(self.tmp / "paper_trading_status.json", _make_status_doc(equity=99_999.0))
        r = build_progress_report(data_dir=self.tmp)
        self.assertAlmostEqual(r["current_equity"], 99_999.0, places=1)

    def test_apy_from_status_when_no_equity_file(self):
        _write_json(self.tmp / "paper_trading_status.json", _make_status_doc(apy=4.2))
        r = build_progress_report(data_dir=self.tmp)
        self.assertAlmostEqual(r["apy_today_pct"], 4.2, places=2)

    def test_equity_from_equity_curve_preferred(self):
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(3))
        _write_json(self.tmp / "paper_trading_status.json", _make_status_doc(equity=88888.0))
        r = build_progress_report(data_dir=self.tmp)
        # equity_curve last bar close_equity should dominate (cycle_runner source)
        self.assertGreater(r["current_equity"], 90_000.0)


# ---------------------------------------------------------------------------
# 8. never_raise on empty / corrupt inputs
# ---------------------------------------------------------------------------


class TestNeverRaise(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_empty_directory(self):
        r = build_progress_report(data_dir=self.tmp)
        self.assertIn("available", r)
        self.assertIn("milestones", r)

    def test_corrupt_equity_file(self):
        (self.tmp / "equity_curve_daily.json").write_text("{bad json", encoding="utf-8")
        r = build_progress_report(data_dir=self.tmp)
        self.assertTrue(r["available"])  # graceful fallback, not error

    def test_equity_file_missing_daily_key(self):
        _write_json(self.tmp / "equity_curve_daily.json", {"source": "cycle_runner"})
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(r["paper_days"], 0)

    def test_corrupt_status_file(self):
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(3))
        (self.tmp / "paper_trading_status.json").write_text("{corrupt", encoding="utf-8")
        r = build_progress_report(data_dir=self.tmp)
        self.assertTrue(r["available"])

    def test_nonexistent_data_dir(self):
        r = build_progress_report(data_dir=self.tmp / "nonexistent")
        self.assertIn("milestones", r)

    def test_equity_daily_not_a_list(self):
        _write_json(
            self.tmp / "equity_curve_daily.json",
            {"source": "cycle_runner", "daily": "not-a-list"},
        )
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(r["paper_days"], 0)


# ---------------------------------------------------------------------------
# 9. run_progress_tracker atomicity and idempotency
# ---------------------------------------------------------------------------


class TestRunProgressTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(3))

    def test_output_file_created(self):
        run_progress_tracker(data_dir=self.tmp)
        self.assertTrue((self.tmp / OUTPUT_FILENAME).exists())

    def test_no_tmp_files_left(self):
        run_progress_tracker(data_dir=self.tmp)
        tmp_files = list(self.tmp.glob(f".{OUTPUT_FILENAME}.*.tmp"))
        self.assertEqual(len(tmp_files), 0, f"Stray tmp files: {tmp_files}")

    def test_output_is_valid_json(self):
        run_progress_tracker(data_dir=self.tmp)
        data = json.loads((self.tmp / OUTPUT_FILENAME).read_text(encoding="utf-8"))
        self.assertIn("paper_days", data)
        self.assertIn("milestones", data)

    def test_idempotency_same_result_twice(self):
        r1 = run_progress_tracker(data_dir=self.tmp)
        r2 = run_progress_tracker(data_dir=self.tmp)
        self.assertEqual(r1["paper_days"], r2["paper_days"])
        self.assertEqual(len(r1["milestones"]), len(r2["milestones"]))

    def test_returns_dict(self):
        result = run_progress_tracker(data_dir=self.tmp)
        self.assertIsInstance(result, dict)

    def test_custom_output_path(self):
        out = self.tmp / "custom_output.json"
        run_progress_tracker(data_dir=self.tmp, output_path=out)
        self.assertTrue(out.exists())
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("milestones", data)

    def test_generated_at_field_present(self):
        result = run_progress_tracker(data_dir=self.tmp)
        self.assertIn("generated_at", result)


# ---------------------------------------------------------------------------
# 10. Milestone structure
# ---------------------------------------------------------------------------


class TestMilestoneStructure(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(3))

    def test_5_milestones_returned(self):
        r = build_progress_report(data_dir=self.tmp)
        self.assertEqual(len(r["milestones"]), 5)

    def test_milestone_ids_present(self):
        r = build_progress_report(data_dir=self.tmp)
        ids = {m["id"] for m in r["milestones"]}
        self.assertIn("backtest_contour_min", ids)
        self.assertIn("honest_metrics_low", ids)
        self.assertIn("structural_break_min", ids)
        self.assertIn("honest_metrics_moderate", ids)
        self.assertIn("honest_metrics_high", ids)

    def test_milestone_has_required_fields(self):
        r = build_progress_report(data_dir=self.tmp)
        required = {
            "id", "label", "module", "required_days", "current_days",
            "days_remaining", "eta_date", "reached",
        }
        for m in r["milestones"]:
            missing = required - set(m.keys())
            self.assertEqual(missing, set(), f"Milestone {m.get('id')} missing: {missing}")

    def test_reached_is_bool(self):
        r = build_progress_report(data_dir=self.tmp)
        for m in r["milestones"]:
            self.assertIsInstance(m["reached"], bool)

    def test_days_remaining_non_negative(self):
        r = build_progress_report(data_dir=self.tmp)
        for m in r["milestones"]:
            self.assertGreaterEqual(m["days_remaining"], 0)

    def test_current_days_equals_paper_days(self):
        r = build_progress_report(data_dir=self.tmp)
        for m in r["milestones"]:
            self.assertEqual(m["current_days"], r["paper_days"])


# ---------------------------------------------------------------------------
# 11. CLI --check and --run
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _write_json(self.tmp / "equity_curve_daily.json", _make_equity_doc(3))

    def _run(self, *args):
        cmd = [sys.executable, "-m", "spa_core.paper_trading.progress_tracker"] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )

    def test_check_exits_zero(self):
        result = self._run("--check", "--data-dir", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_exits_zero(self):
        result = self._run("--run", "--data-dir", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_creates_output_file(self):
        self._run("--run", "--data-dir", str(self.tmp))
        self.assertTrue((self.tmp / OUTPUT_FILENAME).exists())

    def test_check_does_not_create_output_file(self):
        self._run("--check", "--data-dir", str(self.tmp))
        self.assertFalse((self.tmp / OUTPUT_FILENAME).exists())

    def test_bare_invocation_exits_zero(self):
        result = self._run("--data-dir", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# 12. Import hygiene (forbidden imports)
# ---------------------------------------------------------------------------


class TestImportHygiene(unittest.TestCase):
    _FORBIDDEN = {"numpy", "pandas", "scipy", "requests", "anthropic"}

    def test_no_forbidden_imports(self):
        """AST-scan the module for forbidden top-level import names."""
        module_path = (
            _REPO_ROOT
            / "spa_core"
            / "paper_trading"
            / "progress_tracker.py"
        )
        self.assertTrue(module_path.exists(), f"Module not found: {module_path}")
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in self._FORBIDDEN:
                        bad.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in self._FORBIDDEN:
                        bad.append(node.module)
        self.assertEqual(bad, [], f"Forbidden imports found: {bad}")

    def test_module_file_exists(self):
        path = _REPO_ROOT / "spa_core" / "paper_trading" / "progress_tracker.py"
        self.assertTrue(path.exists())

    def test_no_forbidden_execution_imports(self):
        """Ensure module does not import execution / risk domains."""
        module_path = (
            _REPO_ROOT / "spa_core" / "paper_trading" / "progress_tracker.py"
        )
        source = module_path.read_text(encoding="utf-8")
        for forbidden in ("spa_core.execution", "spa_core.risk", "spa_core.allocator"):
            self.assertNotIn(forbidden, source, f"Found forbidden import: {forbidden}")


if __name__ == "__main__":
    unittest.main()

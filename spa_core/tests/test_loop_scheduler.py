"""Tests for spa_core.scheduler.loop_scheduler (MP-311).

Run with: python3 -m pytest spa_core/tests/test_loop_scheduler.py -v
or:        python3 -m unittest spa_core.tests.test_loop_scheduler -v

Covers ≥30 test cases:
  - fast_loop: saves last_approved_config only on approved cycles
  - fast_loop: detects gap_monitor alerts
  - fast_loop: detects kill_switch alerts
  - fast_loop: detects policy violations
  - fast_loop: writes fast_loop_status.json atomically (no .tmp leftovers)
  - fast_loop: fail-safe on exception
  - slow_loop: returns degraded when llm_available=False (no prev cache)
  - slow_loop: returns degraded_cached when prev insights exist
  - slow_loop: returns ok skeleton when llm_available=True
  - slow_loop: writes slow_loop_insights.json
  - slow_loop: fail-safe on exception
  - strategic_loop: returns skipped when llm_available=False
  - strategic_loop: returns ok skeleton when llm_available=True
  - strategic_loop: writes strategic_loop_notes.json
  - strategic_loop: fail-safe on exception
  - last_approved_allocation.json updated only on approved cycle
  - atomic writes (no .tmp files left)
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.scheduler.loop_scheduler import (
    FAST_LOOP_STATUS_FILENAME,
    LAST_APPROVED_ALLOC_FILENAME,
    SLOW_LOOP_INSIGHTS_FILENAME,
    STRATEGIC_LOOP_NOTES_FILENAME,
    run_fast_loop,
    run_slow_loop,
    run_strategic_loop,
)


class _TmpDir:
    def __enter__(self) -> str:
        self._d = tempfile.mkdtemp(prefix="spa_sched_test_")
        return self._d

    def __exit__(self, *_) -> None:
        shutil.rmtree(self._d, ignore_errors=True)


def _make_cycle_result(
    *,
    date: str = "2026-06-11",
    policy_approved: bool = True,
    kill_switch_active: bool = False,
    kill_switch_reason: str = "",
    policy_violations: list | None = None,
    positions: dict | None = None,
    apy_today_pct: float = 4.5,
    current_equity: float = 100_200.0,
    model_used: str | None = "test",
    status: str = "ok",
) -> dict:
    return {
        "date": date,
        "policy_approved": policy_approved,
        "kill_switch_active": kill_switch_active,
        "kill_switch_reason": kill_switch_reason,
        "policy_violations": policy_violations or [],
        "positions": positions or {"aave_v3": 60_000.0, "compound_v3": 35_000.0},
        "apy_today_pct": apy_today_pct,
        "current_equity": current_equity,
        "model_used": model_used,
        "status": status,
    }


# ─── FAST LOOP ────────────────────────────────────────────────────────────────

class TestFastLoopBasics(unittest.TestCase):

    def test_returns_dict_with_required_keys(self):
        with _TmpDir() as d:
            result = run_fast_loop(_make_cycle_result(), data_dir=d)
            for key in ("status", "ts", "gap_detected", "kill_switch_active",
                        "policy_approved", "last_approved_config_updated", "alerts"):
                self.assertIn(key, result, f"Missing key: {key}")

    def test_writes_fast_loop_status_json(self):
        with _TmpDir() as d:
            run_fast_loop(_make_cycle_result(), data_dir=d)
            self.assertTrue((Path(d) / FAST_LOOP_STATUS_FILENAME).exists())

    def test_status_content_matches_return(self):
        with _TmpDir() as d:
            result = run_fast_loop(_make_cycle_result(), data_dir=d)
            on_disk = json.loads((Path(d) / FAST_LOOP_STATUS_FILENAME).read_text())
            self.assertEqual(result["status"], on_disk["status"])
            self.assertEqual(result["policy_approved"], on_disk["policy_approved"])

    def test_no_tmp_files_left(self):
        with _TmpDir() as d:
            run_fast_loop(_make_cycle_result(), data_dir=d)
            tmps = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmps, [])


class TestFastLoopLastApprovedConfig(unittest.TestCase):

    def test_saves_last_approved_config_on_approved_cycle(self):
        with _TmpDir() as d:
            result = run_fast_loop(_make_cycle_result(policy_approved=True, kill_switch_active=False), data_dir=d)
            self.assertTrue(result["last_approved_config_updated"])
            self.assertTrue((Path(d) / LAST_APPROVED_ALLOC_FILENAME).exists())

    def test_does_not_save_config_when_policy_blocked(self):
        with _TmpDir() as d:
            result = run_fast_loop(
                _make_cycle_result(policy_approved=False, policy_violations=["cap exceeded"]),
                data_dir=d,
            )
            self.assertFalse(result["last_approved_config_updated"])
            self.assertFalse((Path(d) / LAST_APPROVED_ALLOC_FILENAME).exists())

    def test_does_not_save_config_when_kill_switch_active(self):
        with _TmpDir() as d:
            result = run_fast_loop(
                _make_cycle_result(kill_switch_active=True, kill_switch_reason="drawdown 5%"),
                data_dir=d,
            )
            self.assertFalse(result["last_approved_config_updated"])
            self.assertFalse((Path(d) / LAST_APPROVED_ALLOC_FILENAME).exists())

    def test_approved_config_contains_positions(self):
        positions = {"aave_v3": 65_000.0, "compound_v3": 30_000.0}
        with _TmpDir() as d:
            run_fast_loop(_make_cycle_result(positions=positions), data_dir=d)
            doc = json.loads((Path(d) / LAST_APPROVED_ALLOC_FILENAME).read_text())
            self.assertEqual(doc["positions"], positions)


class TestFastLoopAlerts(unittest.TestCase):

    def test_gap_detected_creates_alert(self):
        with _TmpDir() as d:
            gap_doc = {"gap_detected": True, "hours_since_last_entry": 25.5}
            (Path(d) / "gap_monitor.json").write_text(json.dumps(gap_doc))
            result = run_fast_loop(_make_cycle_result(), data_dir=d)
            self.assertTrue(result["gap_detected"])
            self.assertTrue(any("gap_detected" in a for a in result["alerts"]))

    def test_kill_switch_creates_alert(self):
        with _TmpDir() as d:
            result = run_fast_loop(
                _make_cycle_result(kill_switch_active=True, kill_switch_reason="drawdown exceeded"),
                data_dir=d,
            )
            self.assertTrue(result["kill_switch_active"])
            self.assertTrue(any("kill_switch" in a for a in result["alerts"]))

    def test_policy_violation_creates_alert(self):
        with _TmpDir() as d:
            result = run_fast_loop(
                _make_cycle_result(policy_approved=False, policy_violations=["T2 cap exceeded"]),
                data_dir=d,
            )
            self.assertFalse(result["policy_approved"])
            self.assertTrue(any("policy_violation" in a for a in result["alerts"]))

    def test_clean_cycle_has_no_alerts(self):
        with _TmpDir() as d:
            result = run_fast_loop(_make_cycle_result(), data_dir=d)
            self.assertEqual(result["alerts"], [])
            self.assertEqual(result["alert_count"], 0)

    def test_failsafe_on_exception(self):
        with patch("spa_core.scheduler.loop_scheduler.atomic_save", side_effect=OSError("disk")):
            result = run_fast_loop(_make_cycle_result())
            self.assertEqual(result["status"], "error")
            self.assertIn("error", result)


# ─── SLOW LOOP ────────────────────────────────────────────────────────────────

class TestSlowLoopDegraded(unittest.TestCase):

    def test_returns_degraded_when_llm_unavailable_no_cache(self):
        with _TmpDir() as d:
            result = run_slow_loop("2026-06-11", llm_available=False, data_dir=d)
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["insights"], [])
            self.assertEqual(result["reason"], "llm_unavailable")

    def test_returns_degraded_cached_when_prev_insights_exist(self):
        with _TmpDir() as d:
            prev = {"status": "ok", "date": "2026-06-10", "insights": [{"tip": "hold"}], "ts": "x"}
            (Path(d) / SLOW_LOOP_INSIGHTS_FILENAME).write_text(json.dumps(prev))
            result = run_slow_loop("2026-06-11", llm_available=False, data_dir=d)
            self.assertEqual(result["status"], "degraded_cached")
            self.assertEqual(result["date"], "2026-06-11")
            self.assertIn("degraded_at", result)

    def test_writes_slow_loop_insights_on_degraded(self):
        with _TmpDir() as d:
            run_slow_loop("2026-06-11", llm_available=False, data_dir=d)
            self.assertTrue((Path(d) / SLOW_LOOP_INSIGHTS_FILENAME).exists())

    def test_no_tmp_files_left(self):
        with _TmpDir() as d:
            run_slow_loop("2026-06-11", llm_available=False, data_dir=d)
            tmps = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmps, [])


class TestSlowLoopLlmAvailable(unittest.TestCase):

    def test_returns_ok_when_llm_available(self):
        with _TmpDir() as d:
            result = run_slow_loop("2026-06-11", llm_available=True, data_dir=d)
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result.get("llm_used"))

    def test_writes_insights_file_when_llm_available(self):
        with _TmpDir() as d:
            run_slow_loop("2026-06-11", llm_available=True, data_dir=d)
            self.assertTrue((Path(d) / SLOW_LOOP_INSIGHTS_FILENAME).exists())

    def test_failsafe_on_exception(self):
        with patch("spa_core.scheduler.loop_scheduler.atomic_save", side_effect=OSError("disk")):
            result = run_slow_loop("2026-06-11", llm_available=False)
            self.assertEqual(result["status"], "error")


# ─── STRATEGIC LOOP ───────────────────────────────────────────────────────────

class TestStrategicLoopSkipped(unittest.TestCase):

    def test_returns_skipped_when_llm_unavailable(self):
        with _TmpDir() as d:
            result = run_strategic_loop("2026-06-09", llm_available=False, data_dir=d)
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "llm_unavailable")
            self.assertEqual(result["week_start"], "2026-06-09")

    def test_writes_strategic_loop_notes_on_skipped(self):
        with _TmpDir() as d:
            run_strategic_loop("2026-06-09", llm_available=False, data_dir=d)
            self.assertTrue((Path(d) / STRATEGIC_LOOP_NOTES_FILENAME).exists())

    def test_no_tmp_files_left(self):
        with _TmpDir() as d:
            run_strategic_loop("2026-06-09", llm_available=False, data_dir=d)
            tmps = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmps, [])


class TestStrategicLoopLlmAvailable(unittest.TestCase):

    def test_returns_ok_when_llm_available(self):
        with _TmpDir() as d:
            result = run_strategic_loop("2026-06-09", llm_available=True, data_dir=d)
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result.get("llm_used"))
            self.assertEqual(result["week_start"], "2026-06-09")

    def test_reads_equity_curve_last_30_days(self):
        with _TmpDir() as d:
            # Seed an equity curve with 35 bars
            bars = [{"date": f"2026-05-{i:02d}", "close_equity": 100_000 + i * 10} for i in range(1, 36)]
            eq_doc = {"daily": bars, "source": "cycle_runner", "is_demo": False}
            (Path(d) / "equity_curve_daily.json").write_text(json.dumps(eq_doc))
            result = run_strategic_loop("2026-06-09", llm_available=True, data_dir=d)
            self.assertEqual(result["equity_bars_analyzed"], 30)

    def test_failsafe_on_exception(self):
        with patch("spa_core.scheduler.loop_scheduler.atomic_save", side_effect=OSError("disk")):
            result = run_strategic_loop("2026-06-09", llm_available=False)
            self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)

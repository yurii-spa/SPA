"""
Тесты для spa_core/milestone/milestone_v2.py (MP-213).
Без сети, без внешних зависимостей.
Тесты подменяют _DATA_DIR через monkey-patching.
"""
import json
import os
import unittest
import unittest.mock

import spa_core.milestone.milestone_v2 as mv2
import tempfile


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class TestCountAdapters(unittest.TestCase):
    """Тесты _count_adapters с разными форматами файлов."""

    def _run_with_dir(self, tmpdir: str) -> int:
        with unittest.mock.patch.object(mv2, "_DATA_DIR", tmpdir):
            return mv2._count_adapters()

    def test_returns_zero_when_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            count = self._run_with_dir(tmp)
            self.assertEqual(count, 0)

    def test_counts_sdk_adapters_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"adapters": [{"protocol": "aave"}, {"protocol": "compound"}]}
            _write_json(os.path.join(tmp, "adapter_sdk_status.json"), data)
            count = self._run_with_dir(tmp)
            self.assertEqual(count, 2)

    def test_counts_orchestrator_adapters_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"adapters": [{"protocol": f"proto_{i}"} for i in range(10)]}
            _write_json(os.path.join(tmp, "adapter_orchestrator_status.json"), data)
            count = self._run_with_dir(tmp)
            self.assertEqual(count, 10)

    def test_takes_max_of_both_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk_data = {"adapters": [{"protocol": f"p{i}"} for i in range(5)]}
            orch_data = {"adapters": [{"protocol": f"p{i}"} for i in range(20)]}
            _write_json(os.path.join(tmp, "adapter_sdk_status.json"), sdk_data)
            _write_json(os.path.join(tmp, "adapter_orchestrator_status.json"), orch_data)
            count = self._run_with_dir(tmp)
            self.assertEqual(count, 20)

    def test_fifteen_plus_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"adapters": [{"protocol": f"p{i}"} for i in range(15)]}
            _write_json(os.path.join(tmp, "adapter_sdk_status.json"), data)
            count = self._run_with_dir(tmp)
            self.assertGreaterEqual(count, 15)


class TestCountTrackDays(unittest.TestCase):
    """Тесты _count_track_days."""

    def _run_with_dir(self, tmpdir: str) -> int:
        with unittest.mock.patch.object(mv2, "_DATA_DIR", tmpdir):
            return mv2._count_track_days()

    def test_returns_zero_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run_with_dir(tmp), 0)

    def test_uses_summary_num_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {
                "summary": {"num_days": 45},
                "daily": [{"date": "2026-01-01"}] * 45,
            }
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            self.assertEqual(self._run_with_dir(tmp), 45)

    def test_falls_back_to_daily_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"daily": [{"date": f"2026-0{i+1}-01"} for i in range(30)]}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            self.assertEqual(self._run_with_dir(tmp), 30)

    def test_sixty_days_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"summary": {"num_days": 61}, "daily": [{}] * 61}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            self.assertGreaterEqual(self._run_with_dir(tmp), 60)


class TestComputeAvgApy7d(unittest.TestCase):
    """Тесты _compute_avg_apy_7d."""

    def _run_with_dir(self, tmpdir: str) -> float:
        with unittest.mock.patch.object(mv2, "_DATA_DIR", tmpdir):
            return mv2._compute_avg_apy_7d()

    def test_returns_zero_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run_with_dir(tmp), 0.0)

    def test_averages_last_7_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = [{"date": f"2026-0{i+1}-01", "apy_today": 6.0} for i in range(10)]
            data = {"daily": daily}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            avg = self._run_with_dir(tmp)
            self.assertAlmostEqual(avg, 6.0, places=2)

    def test_uses_last_7_not_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            # First 23 days: 3% APY, last 7 days: 7% APY
            daily = [{"date": f"2026-01-{i+1:02d}", "apy_today": 3.0} for i in range(23)]
            daily += [{"date": f"2026-02-{i+1:02d}", "apy_today": 7.0} for i in range(7)]
            data = {"daily": daily}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            avg = self._run_with_dir(tmp)
            self.assertAlmostEqual(avg, 7.0, places=1)

    def test_zero_apy_entries_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = [{"date": "2026-01-01", "apy_today": 6.0},
                     {"date": "2026-01-02", "apy_today": 0.0},  # excluded
                     {"date": "2026-01-03", "apy_today": 6.0}]
            data = {"daily": daily}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            avg = self._run_with_dir(tmp)
            self.assertAlmostEqual(avg, 6.0, places=1)

    def test_five_point_five_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = [{"date": f"2026-01-0{i+1}", "apy_today": 5.6} for i in range(7)]
            data = {"daily": daily}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), data)
            avg = self._run_with_dir(tmp)
            self.assertGreaterEqual(avg, 5.5)


class TestCheckMilestonePhase4(unittest.TestCase):
    """Интеграционные тесты check_milestone_phase4."""

    def _run_with_dir(self, tmpdir: str) -> dict:
        with unittest.mock.patch.object(mv2, "_DATA_DIR", tmpdir):
            return mv2.check_milestone_phase4()

    def test_all_failed_when_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            self.assertFalse(result["all_passed"])
            self.assertFalse(result["ready_for_phase4"])

    def test_result_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            for key in ["milestone", "criteria", "all_passed", "ready_for_phase4",
                        "checked_at", "notes"]:
                self.assertIn(key, result)

    def test_criteria_has_five_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            criteria = result["criteria"]
            for key in ["adapters_15plus", "track_60days", "apy_5_5pct",
                        "stress_test", "backtest_done"]:
                self.assertIn(key, criteria)

    def test_all_passed_only_when_all_five_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 15+ adapters
            sdk = {"adapters": [{"protocol": f"p{i}"} for i in range(20)]}
            _write_json(os.path.join(tmp, "adapter_sdk_status.json"), sdk)
            # 60+ track days
            daily = [{"date": f"2026-{i+1:02d}-01", "apy_today": 6.0} for i in range(65)]
            eq = {"summary": {"num_days": 65}, "daily": daily}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), eq)
            # stress test NOT present → all_passed = False
            _write_json(os.path.join(tmp, "backtest_results_historical.json"), {})
            result = self._run_with_dir(tmp)
            # stress_test = False → all_passed = False
            self.assertFalse(result["all_passed"])

    def test_notes_contains_useful_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            notes = result["notes"]
            self.assertIsInstance(notes, str)
            self.assertGreater(len(notes), 0)

    def test_notes_says_more_days_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = [{"date": "2026-01-01", "apy_today": 3.0}]
            eq = {"summary": {"num_days": 1}, "daily": daily}
            _write_json(os.path.join(tmp, "equity_curve_daily.json"), eq)
            result = self._run_with_dir(tmp)
            # Should mention track days needed
            self.assertIn("track", result["notes"].lower())

    def test_backtest_done_detects_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(os.path.join(tmp, "backtest_results_historical.json"), {"x": 1})
            result = self._run_with_dir(tmp)
            self.assertTrue(result["criteria"]["backtest_done"]["passed"])

    def test_milestone_field_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            self.assertEqual(result["milestone"], "phase4_gate")

    def test_checked_at_is_iso8601(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            from datetime import datetime
            # Should be parseable as ISO-8601
            ts = result["checked_at"]
            dt = datetime.fromisoformat(ts)
            self.assertIsNotNone(dt)

    def test_adapters_required_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            self.assertEqual(result["criteria"]["adapters_15plus"]["required"], 15)

    def test_track_required_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            self.assertEqual(result["criteria"]["track_60days"]["required"], 60)

    def test_apy_required_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_with_dir(tmp)
            self.assertEqual(result["criteria"]["apy_5_5pct"]["required"], 5.5)


if __name__ == "__main__":
    unittest.main()

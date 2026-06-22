#!/usr/bin/env python3
"""
Tests for Kill-Switch Drill — MP-312
Минимум 20 тестов (unittest).
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path

# Добавляем корень репо в sys.path
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.kill_switch_drill import run_drill  # noqa: E402


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def _make_fake_data_dir(equity: float = 100_026.06) -> tempfile.TemporaryDirectory:
    """Создаёт временную data/ папку с минимальным paper_trading_status.json."""
    tmpdir = tempfile.TemporaryDirectory(prefix="spa_drill_test_")
    status = {
        "is_demo": False,
        "current_equity": equity,
        "last_cycle_status": "ok",
    }
    p = Path(tmpdir.name) / "paper_trading_status.json"
    p.write_text(json.dumps(status), encoding="utf-8")
    return tmpdir


# ─── Test cases ──────────────────────────────────────────────────────────────

class TestKillSwitchDrillStructure(unittest.TestCase):
    """Тесты структуры возвращаемого dict."""

    def setUp(self):
        self.tmpdir = _make_fake_data_dir()
        self.result = run_drill(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    # 1
    def test_result_is_dict(self):
        self.assertIsInstance(self.result, dict)

    # 2
    def test_has_passed_key(self):
        self.assertIn("passed", self.result)

    # 3
    def test_has_steps_key(self):
        self.assertIn("steps", self.result)

    # 4
    def test_has_total_time_ms(self):
        self.assertIn("total_time_ms", self.result)

    # 5
    def test_has_verdict_key(self):
        self.assertIn("verdict", self.result)

    # 6
    def test_has_drill_timestamp(self):
        self.assertIn("drill_timestamp", self.result)

    # 7
    def test_has_note_key(self):
        self.assertIn("note", self.result)

    # 8
    def test_has_mp_key(self):
        self.assertIn("mp", self.result)
        self.assertEqual(self.result["mp"], "MP-312")

    # 9
    def test_steps_is_list(self):
        self.assertIsInstance(self.result["steps"], list)

    # 10
    def test_steps_not_empty(self):
        self.assertGreater(len(self.result["steps"]), 0)

    # 11
    def test_all_steps_have_ok_key(self):
        for step in self.result["steps"]:
            self.assertIn("ok", step, f"Step missing 'ok' key: {step}")

    # 12
    def test_all_steps_have_step_name(self):
        for step in self.result["steps"]:
            self.assertIn("step", step, f"Step missing 'step' key: {step}")
            self.assertIsInstance(step["step"], str)
            self.assertGreater(len(step["step"]), 0)

    # 13
    def test_total_time_ms_is_numeric(self):
        self.assertIsInstance(self.result["total_time_ms"], (int, float))

    # 14
    def test_passed_is_bool(self):
        self.assertIsInstance(self.result["passed"], bool)


class TestKillSwitchDrillPass(unittest.TestCase):
    """Тесты прохождения drill при нормальных условиях."""

    def setUp(self):
        self.tmpdir = _make_fake_data_dir(equity=100_026.06)
        self.result = run_drill(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    # 15
    def test_drill_passes_normal_conditions(self):
        self.assertTrue(
            self.result["passed"],
            f"Drill должен PASS при нормальных условиях. Результат: {self.result}"
        )

    # 16
    def test_verdict_pass_string(self):
        self.assertIn("PASS", self.result["verdict"])

    # 17
    def test_total_time_under_1000ms(self):
        self.assertLess(
            self.result["total_time_ms"],
            1000,
            f"Drill должен завершиться < 1000ms, а занял {self.result['total_time_ms']}ms"
        )

    # 18
    def test_drill_timestamp_is_iso_format(self):
        ts = self.result["drill_timestamp"]
        self.assertIsInstance(ts, str)
        # ISO 8601 — должен содержать T и заканчиваться на Z
        self.assertIn("T", ts)
        self.assertTrue(ts.endswith("Z"), f"timestamp должен заканчиваться на Z: {ts}")

    # 19
    def test_import_step_passes(self):
        import_step = next(
            (s for s in self.result["steps"] if s["step"] == "import_risk_policy"),
            None,
        )
        self.assertIsNotNone(import_step, "Step 'import_risk_policy' не найден")
        self.assertTrue(import_step["ok"], f"import_risk_policy failed: {import_step}")

    # 20
    def test_simulate_5pct_drawdown_step_passes(self):
        drawdown_step = next(
            (s for s in self.result["steps"] if s["step"] == "simulate_5pct_drawdown"),
            None,
        )
        self.assertIsNotNone(drawdown_step, "Step 'simulate_5pct_drawdown' не найден")
        self.assertTrue(
            drawdown_step["ok"],
            f"simulate_5pct_drawdown failed: {drawdown_step}"
        )


class TestKillSwitchDrillDrawdown(unittest.TestCase):
    """Тесты логики симуляции drawdown."""

    def setUp(self):
        self.tmpdir = _make_fake_data_dir(equity=100_026.06)
        self.result = run_drill(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    # 21
    def test_drawdown_step_detects_violations(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "simulate_5pct_drawdown"),
            None,
        )
        self.assertIsNotNone(step)
        violations = step.get("violations_detected", [])
        self.assertGreater(
            len(violations), 0,
            "Симуляция 5% drawdown должна обнаружить violations"
        )

    # 22
    def test_drawdown_step_shows_5pct(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "simulate_5pct_drawdown"),
            None,
        )
        self.assertIsNotNone(step)
        drawdown = step.get("drawdown_pct", 0)
        self.assertAlmostEqual(
            drawdown, 5.0, places=2,
            msg=f"Drawdown должен быть ~5%, получено {drawdown}"
        )

    # 23
    def test_drawdown_step_kill_switch_triggered(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "simulate_5pct_drawdown"),
            None,
        )
        self.assertIsNotNone(step)
        self.assertTrue(
            step.get("kill_switch_triggered", False),
            "Kill-switch должен сработать при 5% drawdown"
        )

    # 24
    def test_check_current_drawdown_step_passes(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "check_current_drawdown"),
            None,
        )
        self.assertIsNotNone(step, "Step 'check_current_drawdown' не найден")
        self.assertTrue(step["ok"], f"check_current_drawdown failed: {step}")

    # 25
    def test_check_current_drawdown_returns_equity(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "check_current_drawdown"),
            None,
        )
        self.assertIsNotNone(step)
        self.assertIn("current_equity", step)
        self.assertIsInstance(step["current_equity"], (int, float))
        self.assertGreater(step["current_equity"], 0)

    # 26
    def test_current_drawdown_not_triggering(self):
        """При текущем equity > 95K kill-switch не должен тригериться."""
        step = next(
            (s for s in self.result["steps"] if s["step"] == "check_current_drawdown"),
            None,
        )
        self.assertIsNotNone(step)
        # Наш фиктивный equity = 100_026.06 → drawdown < 5% → не тригерит
        self.assertFalse(
            step.get("kill_switch_would_trigger", True),
            f"При equity=100026.06 kill-switch не должен тригериться: {step}"
        )


class TestKillSwitchDrillGate(unittest.TestCase):
    """Тесты проверки risk gate в cycle_runner."""

    def setUp(self):
        self.tmpdir = _make_fake_data_dir()
        self.result = run_drill(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    # 27
    def test_risk_gate_step_passes(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "verify_risk_gate_in_cycle_runner"),
            None,
        )
        self.assertIsNotNone(step, "Step 'verify_risk_gate_in_cycle_runner' не найден")
        self.assertTrue(step["ok"], f"verify_risk_gate failed: {step}")

    # 28
    def test_risk_gate_has_risk_policy(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "verify_risk_gate_in_cycle_runner"),
            None,
        )
        self.assertIsNotNone(step)
        self.assertTrue(
            step.get("has_RiskPolicy", False),
            "cycle_runner должен содержать RiskPolicy"
        )

    # 29
    def test_risk_gate_has_kill_switch(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "verify_risk_gate_in_cycle_runner"),
            None,
        )
        self.assertIsNotNone(step)
        self.assertTrue(
            step.get("has_kill_switch", False),
            "cycle_runner должен содержать kill_switch"
        )


class TestKillSwitchDrillRobustness(unittest.TestCase):
    """Тесты устойчивости — drill не должен падать при плохих данных."""

    # 30
    def test_never_raises_on_corrupt_equity(self):
        """Drill не должен падать при некорректном equity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status = {"is_demo": False, "current_equity": "not_a_number"}
            (Path(tmpdir) / "paper_trading_status.json").write_text(
                json.dumps(status), encoding="utf-8"
            )
            try:
                result = run_drill(data_dir=tmpdir)
                self.assertIsInstance(result, dict)
                self.assertIn("passed", result)
            except Exception as exc:
                self.fail(f"run_drill не должен бросать исключение: {exc}")

    # 31
    def test_never_raises_on_missing_data_dir(self):
        """Drill не должен падать если data_dir не существует."""
        nonexistent = "/tmp/spa_nonexistent_drill_dir_xyz_12345"
        try:
            result = run_drill(data_dir=nonexistent)
            self.assertIsInstance(result, dict)
            self.assertIn("passed", result)
        except Exception as exc:
            self.fail(f"run_drill не должен бросать исключение при отсутствии папки: {exc}")

    # 32
    def test_never_raises_on_empty_status_file(self):
        """Drill не должен падать при пустом paper_trading_status.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "paper_trading_status.json").write_text(
                "{}", encoding="utf-8"
            )
            try:
                result = run_drill(data_dir=tmpdir)
                self.assertIsInstance(result, dict)
            except Exception as exc:
                self.fail(f"run_drill не должен бросать исключение: {exc}")

    # 33
    def test_note_contains_time_info(self):
        """Поле note должно содержать информацию о времени."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_data_dir()  # создаём фиктивные данные
            (Path(tmpdir) / "paper_trading_status.json").write_text(
                json.dumps({"current_equity": 100_000.0}), encoding="utf-8"
            )
            result = run_drill(data_dir=tmpdir)
            note = result.get("note", "")
            self.assertIn("ms", note, f"note должен содержать 'ms': {note}")

    # 34
    def test_result_serializable_to_json(self):
        """Результат drill должен сериализоваться в JSON без ошибок."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "paper_trading_status.json").write_text(
                json.dumps({"current_equity": 100_000.0}), encoding="utf-8"
            )
            result = run_drill(data_dir=tmpdir)
            try:
                serialized = json.dumps(result, ensure_ascii=False)
                self.assertIsInstance(serialized, str)
            except (TypeError, ValueError) as exc:
                self.fail(f"Результат не сериализуется в JSON: {exc}")


class TestKillSwitchDrillRiskConfig(unittest.TestCase):
    """Тесты корректности RiskConfig параметров."""

    def setUp(self):
        self.tmpdir = _make_fake_data_dir()
        self.result = run_drill(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    # 35
    def test_risk_config_step_passes(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "verify_risk_config"),
            None,
        )
        self.assertIsNotNone(step, "Step 'verify_risk_config' не найден")
        self.assertTrue(step["ok"], f"verify_risk_config failed: {step}")

    # 36
    def test_risk_config_version_is_v1(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "verify_risk_config"),
            None,
        )
        self.assertIsNotNone(step)
        self.assertEqual(
            step.get("version"), "v1.0",
            "RiskConfig version должна быть v1.0 в paper-период"
        )

    # 37
    def test_risk_config_drawdown_threshold_is_5pct(self):
        step = next(
            (s for s in self.result["steps"] if s["step"] == "verify_risk_config"),
            None,
        )
        self.assertIsNotNone(step)
        threshold = step.get("max_drawdown_stop", 0)
        self.assertAlmostEqual(
            threshold, 0.05, places=5,
            msg=f"max_drawdown_stop должен быть 0.05 (5%), получено {threshold}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests for spa_core/governance/kill_switch.py (MP-108).

10+ unit tests covering:
- drawdown trigger (fires at 16%, doesn't fire at 14%)
- manual trigger (file-based)
- red_flags trigger (>5 flags)
- sharpe trigger (< -1.0)
- all-cash allocation (all protocols = 0.0)
- deactivate removes file
- no triggers → returns False
- run_kill_switch_check integration
- drill script passes
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# ── Ensure repo root on sys.path ──────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.kill_switch import (
    DRAWDOWN_THRESHOLD_PCT,
    RED_FLAGS_THRESHOLD,
    SHARPE_THRESHOLD,
    KillSwitchChecker,
    run_kill_switch_check,
)


def _make_equity_curve(
    peak: float = 100_000.0,
    drawdown_pct: float = 0.0,
    days: int = 10,
) -> list[dict]:
    """Helper: equity curve с заданной просадкой от peak."""
    bars = []
    current = peak
    for i in range(days - 1):
        bars.append({
            "date": f"2026-05-{i + 1:02d}",
            "close_equity": round(current, 2),
            "open_equity": round(current, 2),
        })
    final = round(peak * (1.0 - drawdown_pct / 100.0), 2)
    bars.append({
        "date": f"2026-05-{days:02d}",
        "close_equity": final,
        "open_equity": round(current, 2),
    })
    return bars


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


class TestDrawdownTrigger(unittest.TestCase):
    """Tests for check_drawdown_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.checker = KillSwitchChecker(data_dir=self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_drawdown_trigger_fires(self) -> None:
        """Просадка 16% > 15% — должна сработать."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=16.0)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"Expected trigger at 16%, got: reason={reason}")
        self.assertIn("drawdown", reason.lower())

    def test_drawdown_trigger_no_fire_14pct(self) -> None:
        """Просадка 14% ≤ 15% — НЕ должна сработать."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=14.0)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"Expected no trigger at 14%, got: reason={reason}")

    def test_drawdown_trigger_no_fire_exact_threshold(self) -> None:
        """Просадка ровно 15% — НЕ должна сработать (порог строгий >)."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=DRAWDOWN_THRESHOLD_PCT)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"Expected no trigger at exact threshold, got: {reason}")

    def test_drawdown_trigger_no_fire_empty_curve(self) -> None:
        """Пустая equity curve — не сработать."""
        triggered, reason = self.checker.check_drawdown_trigger([])
        self.assertFalse(triggered)

    def test_drawdown_trigger_no_fire_single_bar(self) -> None:
        """Один бар — нет предыдущего максимума, не сработать."""
        curve = [{"date": "2026-06-01", "close_equity": 100_000.0}]
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered)

    def test_drawdown_trigger_large_drawdown(self) -> None:
        """Просадка 50% — гарантированное срабатывание."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=50.0, days=30)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered)

    def test_drawdown_uses_last_30_days(self) -> None:
        """Окно 30 дней: пик вне окна не считается."""
        # 50 баров: первые 20 с большим пиком, последние 30 нормальные
        long_peak_bars = [
            {"date": f"2026-04-{i + 1:02d}", "close_equity": 200_000.0}
            for i in range(20)
        ]
        normal_bars = [
            {"date": f"2026-05-{i + 1:02d}", "close_equity": 99_000.0}
            for i in range(30)
        ]
        # Текущая просадка от max в 30-дневном окне: max=99000, current=99000 → 0%
        curve = long_peak_bars + normal_bars
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"Should not trigger since 30d window is flat: {reason}")


class TestManualTrigger(unittest.TestCase):
    """Tests for check_manual_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_manual_trigger_no_file(self) -> None:
        """Без файла — не срабатывает."""
        triggered, reason = self.checker.check_manual_trigger()
        self.assertFalse(triggered)

    def test_manual_trigger_file_exists(self) -> None:
        """Файл kill_switch_active.json существует — срабатывает."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "test"}), encoding="utf-8")
        triggered, reason = self.checker.check_manual_trigger()
        self.assertTrue(triggered)
        self.assertIn("manual", reason.lower())

    def test_manual_trigger_carries_reason(self) -> None:
        """Причина из файла включается в reason."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(
            json.dumps({"reason": "emergency stop by operator"}), encoding="utf-8"
        )
        triggered, reason = self.checker.check_manual_trigger()
        self.assertTrue(triggered)
        self.assertIn("emergency stop by operator", reason)

    def test_manual_trigger_empty_file(self) -> None:
        """Пустой JSON в файле — всё равно срабатывает (файл = сигнал)."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text("{}", encoding="utf-8")
        triggered, reason = self.checker.check_manual_trigger()
        self.assertTrue(triggered)


class TestRedFlagsTrigger(unittest.TestCase):
    """Tests for check_red_flags_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_flags(self, count: int) -> None:
        flags = [{"protocol": f"proto_{i}", "severity": "CRITICAL"} for i in range(count)]
        _write_json(
            self.data_dir / "red_flags.json",
            {"red_flags": flags, "generated_at": "2026-06-11T00:00:00Z"},
        )

    def test_red_flags_trigger_fires(self) -> None:
        """6 флагов > 5 — должна сработать."""
        self._write_flags(6)
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered, f"Expected trigger at 6 flags: {reason}")
        self.assertIn("6", reason)

    def test_red_flags_trigger_no_fire(self) -> None:
        """5 флагов = порог — НЕ должна сработать (строгое >)."""
        self._write_flags(RED_FLAGS_THRESHOLD)
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered, f"Expected no trigger at exact threshold: {reason}")

    def test_red_flags_trigger_no_file(self) -> None:
        """Нет файла — не сработать."""
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered)

    def test_red_flags_many_flags(self) -> None:
        """100 флагов — гарантированное срабатывание."""
        self._write_flags(100)
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered)


class TestSharpeTrigger(unittest.TestCase):
    """Tests for check_sharpe_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_analytics(self, sharpe: float, num_days: int = 30) -> None:
        _write_json(
            self.data_dir / "analytics_summary.json",
            {
                "num_days": num_days,
                "metrics": {"sharpe": sharpe},
                "source": "analytics_runner",
            },
        )

    def test_sharpe_trigger_fires(self) -> None:
        """Sharpe = -1.5 < -1.0 — должна сработать."""
        self._write_analytics(-1.5, num_days=30)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered, f"Expected trigger at sharpe=-1.5: {reason}")
        self.assertIn("-1.5", reason)

    def test_sharpe_trigger_no_fire(self) -> None:
        """Sharpe = 0.5 > -1.0 — НЕ должна сработать."""
        self._write_analytics(0.5, num_days=30)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Expected no trigger at sharpe=0.5: {reason}")

    def test_sharpe_trigger_exact_threshold(self) -> None:
        """Sharpe ровно -1.0 — НЕ должна сработать (строгое <)."""
        self._write_analytics(SHARPE_THRESHOLD, num_days=30)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Expected no trigger at exact threshold: {reason}")

    def test_sharpe_trigger_insufficient_data(self) -> None:
        """Sharpe = -2.0, но только 3 дня данных — не срабатывает."""
        self._write_analytics(-2.0, num_days=3)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Expected no trigger with 3 days: {reason}")
        self.assertIn("insufficient", reason.lower())

    def test_sharpe_trigger_no_file(self) -> None:
        """Нет файла — не сработать."""
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered)


class TestAllCashAllocation(unittest.TestCase):
    """Tests for get_kill_switch_allocation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_cash_allocation_complete(self) -> None:
        """Все протоколы = 0.0, cash = 1.0."""
        alloc = self.checker.get_kill_switch_allocation()
        self.assertIn("cash", alloc, "allocation must include 'cash'")
        self.assertEqual(alloc["cash"], 1.0, "cash must be 1.0")

        protocols = [k for k in alloc if k != "cash"]
        self.assertTrue(protocols, "Must have at least one protocol key")
        for p in protocols:
            self.assertEqual(
                alloc[p], 0.0,
                f"Protocol {p} must be 0.0 in all-cash allocation, got {alloc[p]}"
            )

    def test_all_cash_contains_known_protocols(self) -> None:
        """Аллокация содержит все известные протоколы."""
        alloc = self.checker.get_kill_switch_allocation()
        from spa_core.governance.kill_switch import _KNOWN_PROTOCOLS
        for p in _KNOWN_PROTOCOLS:
            self.assertIn(p, alloc, f"Known protocol {p} missing from kill-switch allocation")
            self.assertEqual(alloc[p], 0.0)

    def test_all_cash_reads_from_orchestrator_status(self) -> None:
        """Если adapter_orchestrator_status.json существует — читает протоколы оттуда."""
        orch_doc = {
            "adapters": [
                {"protocol": "custom_proto_1", "status": "ok"},
                {"protocol": "custom_proto_2", "status": "ok"},
            ]
        }
        _write_json(self.data_dir / "adapter_orchestrator_status.json", orch_doc)
        alloc = self.checker.get_kill_switch_allocation()
        self.assertIn("custom_proto_1", alloc)
        self.assertIn("custom_proto_2", alloc)
        self.assertEqual(alloc["custom_proto_1"], 0.0)
        self.assertEqual(alloc["custom_proto_2"], 0.0)


class TestActivateDeactivate(unittest.TestCase):
    """Tests for activate_kill_switch / deactivate_kill_switch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_activate_creates_file(self) -> None:
        """activate_kill_switch() создаёт kill_switch_active.json."""
        active_path = Path(self._tmp.name) / "kill_switch_active.json"
        self.assertFalse(active_path.exists())
        self.checker.activate_kill_switch("test activation")
        self.assertTrue(active_path.exists())
        doc = json.loads(active_path.read_text())
        self.assertEqual(doc["reason"], "test activation")
        self.assertIn("activated_at", doc)

    def test_deactivate_removes_file(self) -> None:
        """deactivate_kill_switch() удаляет файл."""
        self.checker.activate_kill_switch("reason")
        active_path = Path(self._tmp.name) / "kill_switch_active.json"
        self.assertTrue(active_path.exists())
        self.checker.deactivate_kill_switch()
        self.assertFalse(active_path.exists())

    def test_deactivate_idempotent(self) -> None:
        """Повторная деактивация без файла — не бросает исключение."""
        # Нет файла — не должно упасть
        self.checker.deactivate_kill_switch()


class TestNoTriggers(unittest.TestCase):
    """Tests for the 'all clear' case."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_triggers_returns_false(self) -> None:
        """Без триггеров is_kill_switch_active() возвращает False."""
        # Пишем нормальную equity curve (нет просадки)
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=0.0, days=10)
        # Нет red_flags файла, нет manual файла, нет analytics
        triggered, reason = self.checker.is_kill_switch_active(equity_curve=curve)
        self.assertFalse(triggered, f"Expected no trigger, got: {reason}")

    def test_run_kill_switch_check_no_triggers(self) -> None:
        """run_kill_switch_check без триггеров → triggered=False."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=5.0, days=10)
        status = run_kill_switch_check(equity_curve=curve, data_dir=self._tmp.name)
        self.assertFalse(status["triggered"])
        self.assertEqual(status["allocation"], {})


class TestRunKillSwitchCheck(unittest.TestCase):
    """Integration tests for run_kill_switch_check."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_triggered_returns_allocation(self) -> None:
        """При срабатывании возвращает allocation с cash=1.0."""
        # Создаём manual trigger
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "test"}), encoding="utf-8")
        status = run_kill_switch_check(equity_curve=[], data_dir=self.data_dir)
        self.assertTrue(status["triggered"])
        self.assertIn("allocation", status)
        alloc = status["allocation"]
        self.assertEqual(alloc.get("cash"), 1.0)

    def test_triggered_writes_status_file(self) -> None:
        """При срабатывании создаёт data/kill_switch_status.json."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "test"}), encoding="utf-8")
        run_kill_switch_check(equity_curve=[], data_dir=self.data_dir)
        status_path = self.data_dir / "kill_switch_status.json"
        self.assertTrue(status_path.exists(), "kill_switch_status.json must be written")
        doc = json.loads(status_path.read_text())
        self.assertTrue(doc["triggered"])
        self.assertIn("reason", doc)

    def test_not_triggered_writes_status_file(self) -> None:
        """Даже при отсутствии триггеров пишет kill_switch_status.json."""
        run_kill_switch_check(equity_curve=[], data_dir=self.data_dir)
        status_path = self.data_dir / "kill_switch_status.json"
        self.assertTrue(status_path.exists())
        doc = json.loads(status_path.read_text())
        self.assertFalse(doc["triggered"])


class TestDrillScript(unittest.TestCase):
    """Test that the drill script runs successfully."""

    def test_drill_script_passes(self) -> None:
        """scripts/kill_switch_drill.py должен завершиться с кодом 0."""
        drill_path = Path(__file__).resolve().parents[2] / "scripts" / "kill_switch_drill.py"
        self.assertTrue(drill_path.exists(), f"Drill script not found: {drill_path}")

        import subprocess
        result = subprocess.run(
            [sys.executable, str(drill_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Drill script failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()

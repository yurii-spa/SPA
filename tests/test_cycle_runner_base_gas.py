"""Tests for ADR-025 Base gas monitor integration in cycle_runner. MP-456."""
import os
import tempfile
import unittest


class TestCycleRunnerBaseGas(unittest.TestCase):
    def test_import_ok(self):
        from spa_core.paper_trading import cycle_runner  # noqa: F401
        self.assertTrue(True)

    def test_base_chain_monitoring_attr(self):
        from spa_core.paper_trading import cycle_runner
        self.assertTrue(hasattr(cycle_runner, "_BASE_CHAIN_MONITORING"))

    def test_base_gas_monitor_class_or_none(self):
        from spa_core.paper_trading import cycle_runner
        monitor_cls = getattr(cycle_runner, "_BASE_GAS_MONITOR_CLASS", "MISSING")
        self.assertNotEqual(monitor_cls, "MISSING")  # attr must exist

    def test_base_chain_monitoring_true(self):
        """BaseGasMonitor module is present — monitoring should be enabled."""
        from spa_core.paper_trading import cycle_runner
        self.assertTrue(cycle_runner._BASE_CHAIN_MONITORING)

    def test_base_gas_constants(self):
        from spa_core.monitoring.base_gas_monitor import (
            BASE_GAS_KILL_DAYS,
            BASE_GAS_THRESHOLD_GWEI,
        )
        self.assertEqual(BASE_GAS_THRESHOLD_GWEI, 10.0)
        self.assertEqual(BASE_GAS_KILL_DAYS, 3)

    def test_kill_switch_not_active_low_gas(self):
        """Low gas reading must NOT activate kill-switch."""
        from spa_core.monitoring.base_gas_monitor import BaseGasMonitor
        with tempfile.TemporaryDirectory() as tmpdir:
            m = BaseGasMonitor(data_dir=tmpdir)
            status = m.record_reading(gwei=0.05)  # well below 10 Gwei
            self.assertFalse(status["kill_switch_active"])
            self.assertEqual(status["action"], "OK")

    def test_kill_switch_active_high_gas_3_days(self):
        """3 consecutive days above threshold must activate kill-switch."""
        import datetime
        from spa_core.monitoring.base_gas_monitor import (
            BASE_GAS_KILL_DAYS,
            BASE_GAS_THRESHOLD_GWEI,
            BaseGasMonitor,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            m = BaseGasMonitor(data_dir=tmpdir)
            high_gwei = BASE_GAS_THRESHOLD_GWEI + 1.0
            base_date = datetime.date(2026, 6, 1)
            for i in range(BASE_GAS_KILL_DAYS):
                status = m.record_reading(
                    gwei=high_gwei,
                    today=base_date + datetime.timedelta(days=i),
                )
            self.assertTrue(status["kill_switch_active"])
            self.assertEqual(status["action"], "KILL_SWITCH_ACTIVE")

    def test_kill_switch_warn_two_days(self):
        """Two days above threshold → WARN, not active."""
        import datetime
        from spa_core.monitoring.base_gas_monitor import (
            BASE_GAS_THRESHOLD_GWEI,
            BaseGasMonitor,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            m = BaseGasMonitor(data_dir=tmpdir)
            high_gwei = BASE_GAS_THRESHOLD_GWEI + 1.0
            base_date = datetime.date(2026, 6, 1)
            for i in range(2):
                status = m.record_reading(
                    gwei=high_gwei,
                    today=base_date + datetime.timedelta(days=i),
                )
            self.assertFalse(status["kill_switch_active"])
            self.assertEqual(status["action"], "WARN")

    def test_monitor_uses_correct_data_dir(self):
        """BaseGasMonitor must write to the supplied data_dir."""
        from spa_core.monitoring.base_gas_monitor import BaseGasMonitor
        with tempfile.TemporaryDirectory() as tmpdir:
            m = BaseGasMonitor(data_dir=tmpdir)
            m.record_reading(gwei=0.01)
            expected = os.path.join(tmpdir, BaseGasMonitor.DATA_FILENAME)
            self.assertTrue(os.path.exists(expected), f"Missing: {expected}")


if __name__ == "__main__":
    unittest.main()

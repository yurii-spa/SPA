"""MP-009: тесты gap_monitor — детектор пропущенных дней paper trading цикла.

MP-101 (SPA-V415): переведены с pytest на чистый stdlib ``unittest`` —
pytest в этом репо не установлен (паттерн test_adapter_orchestrator /
test_capacity_analytics), при наличии pytest классы подхватываются им же.
Покрытие исходных 10 кейсов сохранено 1:1.

Run:  python3 -m unittest spa_core.tests.test_gap_monitor -v
"""
import json
import subprocess
import sys
import unittest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading import gap_monitor


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class GapMonitorBase(unittest.TestCase):
    """Перенаправляет ВСЕ файлы gap_monitor во временную директорию."""

    _PATCHED = ("DATA_DIR", "EQUITY_FILE", "GAP_STATUS_FILE",
                "RISK_ALERTS_FILE", "RECOVERY_LOCK_FILE")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self._saved = {k: getattr(gap_monitor, k) for k in self._PATCHED}
        self.equity = self.tmp_path / "equity_curve_daily.json"
        self.status = self.tmp_path / "gap_monitor.json"
        self.alerts = self.tmp_path / "risk_alerts.json"
        self.lock = self.tmp_path / "gap_recovery.lock"
        gap_monitor.DATA_DIR = self.tmp_path
        gap_monitor.EQUITY_FILE = self.equity
        gap_monitor.GAP_STATUS_FILE = self.status
        gap_monitor.RISK_ALERTS_FILE = self.alerts
        gap_monitor.RECOVERY_LOCK_FILE = self.lock

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(gap_monitor, k, v)
        self._tmp.cleanup()


class TestGapDetection(GapMonitorBase):
    def test_ok(self):
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(5), "is_demo": False, "equity": 100010.0},
        ]))
        r = gap_monitor.check_gaps()
        self.assertFalse(r["gap_detected"])
        self.assertEqual(r["status"], "ok")

    def test_gap(self):
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(30), "is_demo": False, "equity": 100010.0},
        ]))
        r = gap_monitor.check_gaps()
        self.assertTrue(r["gap_detected"])
        self.assertEqual(r["status"], "gap")

    def test_no_file(self):
        r = gap_monitor.check_gaps()
        self.assertTrue(r["gap_detected"])
        self.assertEqual(r["status"], "no_data")

    def test_only_demo_entries(self):
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(1), "is_demo": True},
            {"timestamp": _iso(2), "is_demo": True},
        ]))
        r = gap_monitor.check_gaps()
        self.assertTrue(r["gap_detected"])
        self.assertEqual(r["status"], "no_real_entries")

    def test_no_timestamp(self):
        # HONEST TRACK RESET (2026-06-26): an entry with no parseable date can
        # never be an evidenced track day (a track day is anchored to a real
        # calendar date with a daily_cycle log), so a date-less bar is filtered
        # out before the no_timestamp branch and the curve is reported as having
        # no evidenced entries.
        self.equity.write_text(json.dumps([
            {"is_demo": False, "equity": 100000.0},
        ]))
        r = gap_monitor.check_gaps()
        self.assertTrue(r["gap_detected"])
        self.assertEqual(r["status"], "no_real_entries")

    def test_write_atomic(self):
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(1), "is_demo": False},
        ]))
        gap_monitor.check_gaps()
        self.assertTrue(self.status.exists())
        on_disk = json.loads(self.status.read_text())
        self.assertFalse(on_disk["gap_detected"])
        self.assertFalse(self.status.with_suffix(".tmp").exists())

    def test_exit_code(self):
        """Standalone-запуск с gap → exit code 1; без gap → 0."""
        project_root = Path(gap_monitor.__file__).parent.parent.parent
        script = (
            "from pathlib import Path\n"
            "import json, sys\n"
            "from spa_core.paper_trading import gap_monitor as gm\n"
            f"gm.EQUITY_FILE = Path({str(self.tmp_path / 'eq.json')!r})\n"
            f"gm.GAP_STATUS_FILE = Path({str(self.tmp_path / 'gap.json')!r})\n"
            f"gm.RISK_ALERTS_FILE = Path({str(self.tmp_path / 'alerts.json')!r})\n"
            "r = gm.check_gaps()\n"
            "sys.exit(1 if r['gap_detected'] else 0)\n"
        )
        # gap: файла нет
        proc = subprocess.run([sys.executable, "-c", script], cwd=project_root)
        self.assertEqual(proc.returncode, 1)
        # без gap: свежий бар
        (self.tmp_path / "eq.json").write_text(json.dumps([
            {"timestamp": _iso(1), "is_demo": False},
        ]))
        proc = subprocess.run([sys.executable, "-c", script], cwd=project_root)
        self.assertEqual(proc.returncode, 0)

    def test_hours_since_calculated(self):
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(10), "is_demo": False},
            {"timestamp": _iso(34), "is_demo": False},
        ]))
        r = gap_monitor.check_gaps()
        # берётся самый свежий бар (10ч назад)
        self.assertAlmostEqual(r["hours_since_last_entry"], 10, delta=0.1)
        self.assertIsNotNone(r["last_entry_date"])
        self.assertFalse(r["gap_detected"])

    def test_cycle_runner_doc_format(self):
        """Формат документа cycle_runner: is_demo на уровне документа, бары в daily."""
        self.equity.write_text(json.dumps({
            "source": "cycle_runner",
            "is_demo": False,
            "daily": [{"date": datetime.now(timezone.utc).date().isoformat(),
                       "close_equity": 100010.09}],
        }))
        r = gap_monitor.check_gaps()
        self.assertFalse(r["gap_detected"])
        self.assertEqual(r["status"], "ok")

    def test_parse_error(self):
        self.equity.write_text("{not valid json")
        r = gap_monitor.check_gaps()
        self.assertTrue(r["gap_detected"])
        self.assertEqual(r["status"], "parse_error")


if __name__ == "__main__":
    unittest.main()

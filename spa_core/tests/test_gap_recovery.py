"""MP-101 (SPA-V415): тесты CRITICAL-алерта и auto-recovery gap_monitor.

Чистый stdlib ``unittest`` (pytest в репо не установлен — паттерн
test_capacity_analytics / test_adapter_orchestrator). Без сети: «штатный
цикл» инжектируется через cycle_fn (никаких реальных транзакций — paper only).

Run:  python3 -m unittest spa_core.tests.test_gap_recovery -v
"""
import contextlib
import io
import json
import os
import sys
import time
import unittest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading import gap_monitor


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class GapRecoveryBase(unittest.TestCase):
    """Перенаправляет все файлы gap_monitor во временную директорию."""

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

    # ── фикстуры-помощники ──────────────────────────────────────────────────
    def write_stale_equity(self, hours_ago: float = 30.0):
        """Бар старше порога 26ч → gap."""
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(hours_ago), "is_demo": False, "equity": 100010.0},
        ]))

    def write_fresh_equity(self):
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(1), "is_demo": False, "equity": 100010.0},
        ]))

    def make_cycle_fn(self, fail=False):
        """Фейковый «штатный цикл»: пишет сегодняшний бар (paper only)."""
        calls = []

        def cycle():
            calls.append(1)
            if fail:
                raise RuntimeError("orchestrator unavailable")
            self.equity.write_text(json.dumps({
                "source": "cycle_runner",
                "is_demo": False,
                "daily": [{"date": _today(), "close_equity": 100020.0}],
            }))
        cycle.calls = calls
        return cycle

    def read_alerts(self) -> dict:
        return json.loads(self.alerts.read_text())

    def gap_alerts(self) -> list:
        doc = self.read_alerts()
        return [a for a in doc["alerts"] if a.get("source") == "gap_monitor"]


# ─── CRITICAL-алерт ───────────────────────────────────────────────────────────


class TestGapAlert(GapRecoveryBase):
    def test_alert_written_on_gap(self):
        self.write_stale_equity()
        r = gap_monitor.check_gaps()
        self.assertTrue(r["gap_detected"])
        self.assertTrue(self.alerts.exists())
        doc = self.read_alerts()
        self.assertEqual(doc["status"], "critical")
        self.assertEqual(doc["count"], 1)
        a = doc["alerts"][0]
        self.assertEqual(a["severity"], "critical")
        self.assertEqual(a["source"], "gap_monitor")
        self.assertEqual(a["type"], "cycle_gap")
        self.assertEqual(a["date"], _today())

    def test_alert_not_duplicated_same_day(self):
        self.write_stale_equity()
        gap_monitor.check_gaps()
        gap_monitor.check_gaps()
        gap_monitor.check_gaps()
        self.assertEqual(len(self.gap_alerts()), 1)
        self.assertEqual(self.read_alerts()["count"], 1)

    def test_no_alert_when_ok(self):
        self.write_fresh_equity()
        r = gap_monitor.check_gaps()
        self.assertFalse(r["gap_detected"])
        self.assertFalse(self.alerts.exists())

    def test_foreign_alerts_preserved(self):
        """Чужие алерты (например, export_data concentration) не затираются."""
        self.alerts.write_text(json.dumps({
            "generated_at": _iso(2), "count": 1, "status": "warning",
            "alerts": [{"severity": "warning", "type": "concentration",
                        "protocol": "aave_v3", "message": "x"}],
        }))
        self.write_stale_equity()
        gap_monitor.check_gaps()
        doc = self.read_alerts()
        self.assertEqual(doc["count"], 2)
        self.assertEqual(doc["status"], "critical")
        types = {a["type"] for a in doc["alerts"]}
        self.assertIn("concentration", types)
        self.assertIn("cycle_gap", types)

    def test_alert_atomic_no_tmp_residue(self):
        self.write_stale_equity()
        gap_monitor.check_gaps()
        leftovers = [p for p in self.tmp_path.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])


# ─── auto-recovery ────────────────────────────────────────────────────────────


class TestAttemptRecovery(GapRecoveryBase):
    def test_no_gap_noop(self):
        """Нет gap → ничего не делает: цикл не зовётся, алертов и lock нет."""
        self.write_fresh_equity()
        cycle = self.make_cycle_fn()
        rec = gap_monitor.attempt_recovery(cycle_fn=cycle)
        self.assertFalse(rec["attempted"])
        self.assertEqual(rec["skipped_reason"], "no_gap")
        self.assertEqual(cycle.calls, [])
        self.assertFalse(self.alerts.exists())
        self.assertFalse(self.lock.exists())

    def test_recovery_success(self):
        self.write_stale_equity()
        cycle = self.make_cycle_fn()
        rec = gap_monitor.attempt_recovery(cycle_fn=cycle)
        self.assertTrue(rec["attempted"])
        self.assertTrue(rec["succeeded"])
        self.assertIsNone(rec["error"])
        self.assertEqual(len(cycle.calls), 1)
        # результат залогирован в gap_monitor.json
        on_disk = json.loads(self.status.read_text())
        self.assertTrue(on_disk["recovery"]["succeeded"])
        self.assertFalse(on_disk["gap_detected"])  # gap закрыт
        # … и прикреплён к CRITICAL-алерту
        a = self.gap_alerts()[0]
        self.assertTrue(a["recovery"]["succeeded"])
        # lock снят
        self.assertFalse(self.lock.exists())

    def test_recovery_idempotent_second_call_skipped(self):
        """Повторный вызов в тот же день — skipped, цикл не перезапускается."""
        self.write_stale_equity()
        # Цикл «отработал», но gap не закрыл (бар не записан) → failure
        noop = self.make_cycle_fn()

        def broken():
            noop.calls.append(1)  # ничего не пишет
        rec1 = gap_monitor.attempt_recovery(cycle_fn=broken)
        self.assertTrue(rec1["attempted"])
        self.assertFalse(rec1["succeeded"])
        self.assertEqual(rec1["error"], "cycle_ran_but_gap_persists")

        rec2 = gap_monitor.attempt_recovery(cycle_fn=broken)
        self.assertFalse(rec2["attempted"])
        self.assertEqual(rec2["skipped_reason"], "already_attempted_today")
        self.assertEqual(len(noop.calls), 1)  # максимум 1 попытка за день
        # skip тоже залогирован
        on_disk = json.loads(self.status.read_text())
        self.assertEqual(on_disk["recovery_skip"]["skipped_reason"],
                         "already_attempted_today")
        # в алерте остаётся результат попытки/скипа
        a = self.gap_alerts()[0]
        self.assertEqual(a["recovery"]["skipped_reason"], "already_attempted_today")

    def test_recovery_cycle_exception_recorded_honestly(self):
        """Падение цикла → attempted=True, succeeded=False, error не маскируется."""
        self.write_stale_equity()
        cycle = self.make_cycle_fn(fail=True)
        rec = gap_monitor.attempt_recovery(cycle_fn=cycle)
        self.assertTrue(rec["attempted"])
        self.assertFalse(rec["succeeded"])
        self.assertIn("RuntimeError", rec["error"])
        on_disk = json.loads(self.status.read_text())
        self.assertFalse(on_disk["recovery"]["succeeded"])
        self.assertTrue(on_disk["gap_detected"])  # gap честно остался
        a = self.gap_alerts()[0]
        self.assertFalse(a["recovery"]["succeeded"])
        self.assertFalse(self.lock.exists())  # lock снят даже после падения

    def test_lock_blocks_parallel_run(self):
        """Живой lock другого процесса → skipped 'locked', цикл не зовётся."""
        self.write_stale_equity()
        self.lock.write_text(json.dumps({"pid": 99999, "ts": _iso(0)}))
        cycle = self.make_cycle_fn()
        rec = gap_monitor.attempt_recovery(cycle_fn=cycle)
        self.assertFalse(rec["attempted"])
        self.assertEqual(rec["skipped_reason"], "locked")
        self.assertEqual(cycle.calls, [])
        self.assertTrue(self.lock.exists())  # чужой lock не тронут

    def test_stale_lock_reclaimed(self):
        """Протухший lock (упавший процесс) снимается, recovery идёт."""
        self.write_stale_equity()
        self.lock.write_text(json.dumps({"pid": 99999}))
        stale = time.time() - gap_monitor.LOCK_STALE_SECONDS - 60
        os.utime(self.lock, (stale, stale))
        cycle = self.make_cycle_fn()
        rec = gap_monitor.attempt_recovery(cycle_fn=cycle)
        self.assertTrue(rec["attempted"])
        self.assertTrue(rec["succeeded"])
        self.assertFalse(self.lock.exists())

    def test_today_bar_exists_skip(self):
        """Бар за сегодня уже есть (demo → no_real_entries) — цикл не зовётся."""
        self.equity.write_text(json.dumps([
            {"timestamp": _iso(1), "date": _today(), "is_demo": True},
        ]))
        cycle = self.make_cycle_fn()
        rec = gap_monitor.attempt_recovery(cycle_fn=cycle)
        self.assertFalse(rec["attempted"])
        self.assertEqual(rec["skipped_reason"], "today_bar_exists")
        self.assertEqual(cycle.calls, [])


# ─── CLI ──────────────────────────────────────────────────────────────────────


class TestCli(GapRecoveryBase):
    def test_default_detection_only(self):
        """Без --recover — только детекция (поведение MP-009): recovery нет."""
        self.write_stale_equity()
        with contextlib.redirect_stdout(io.StringIO()):
            code = gap_monitor.main([])
        self.assertEqual(code, 1)
        on_disk = json.loads(self.status.read_text())
        self.assertNotIn("recovery", on_disk)
        self.assertFalse(self.lock.exists())

    def test_recover_flag_runs_recovery(self):
        self.write_stale_equity()
        cycle = self.make_cycle_fn()
        saved = gap_monitor._default_cycle
        gap_monitor._default_cycle = cycle
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gap_monitor.main(["--recover"])
        finally:
            gap_monitor._default_cycle = saved
        self.assertEqual(code, 0)  # gap закрыт recovery → exit 0
        self.assertEqual(len(cycle.calls), 1)
        out = json.loads(buf.getvalue())
        self.assertTrue(out["recovery"]["succeeded"])

    def test_default_ok_exit_zero(self):
        self.write_fresh_equity()
        with contextlib.redirect_stdout(io.StringIO()):
            code = gap_monitor.main([])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

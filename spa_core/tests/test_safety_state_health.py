"""Health-surface visibility for the TWO-TIER safety state (D3-T3, ADR-034).

Pins ``SystemHealthMonitor._check_safety_state`` — the d6 gate that makes the
SOFT de-risk state (``derisk_status.json``) and the HARD all-cash kill state
(``kill_switch_active.json`` / ``kill_switch_status.json``) OBSERVABLE in the
health surface:

    no state files          → OK            ("no safety state active")
    derisk active           → WARNING       ("SOFT de-risk ACTIVE")
    kill active             → CRITICAL      ("HARD kill ACTIVE — all-cash")
    stale active derisk     → WARNING + flagged stale
    stale inactive derisk   → INFO  + flagged stale
    corrupt status file     → WARNING       (cannot verify; never silently OK)

Deterministic, stdlib-only, read-only (writes nothing).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.system_health_monitor import (  # noqa: E402
    CRITICAL,
    INFO,
    OK,
    WARNING,
    SystemHealthMonitor,
)


def _iso(hours_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class TestSafetyStateHealth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_safety_health_")
        self.data_dir = Path(self._tmp.name)
        self.mon = SystemHealthMonitor(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, obj) -> None:
        (self.data_dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def _run(self):
        return self.mon._check_safety_state("d6_risk_gates")

    # ── clear ─────────────────────────────────────────────────────────────────
    def test_no_files_is_ok(self) -> None:
        r = self._run()
        self.assertEqual(r.status, OK)
        self.assertEqual(r.id, "d6.safety_state")
        self.assertEqual(r.value, "CLEAR")

    def test_inactive_fresh_derisk_is_ok(self) -> None:
        self._write("derisk_status.json",
                    {"generated_at": _iso(0), "active": False, "tier": "NONE"})
        r = self._run()
        self.assertEqual(r.status, OK)
        self.assertEqual(r.value, "CLEAR")

    # ── SOFT de-risk → WARNING ─────────────────────────────────────────────────
    def test_soft_derisk_active_is_warning(self) -> None:
        self._write("derisk_status.json", {
            "generated_at": _iso(0), "active": True, "tier": "SOFT_DERISK",
            "reason": "drawdown 8.00% ≥ 5.0% soft de-risk",
        })
        r = self._run()
        self.assertEqual(r.status, WARNING)
        self.assertEqual(r.value, "SOFT_DERISK")
        self.assertIn("de-risk", r.title.lower())
        self.assertFalse(r.evidence["stale"])

    # ── HARD kill → CRITICAL ───────────────────────────────────────────────────
    def test_hard_kill_active_file_is_critical(self) -> None:
        self._write("kill_switch_active.json", {
            "activated_at": _iso(0),
            "reason": "drawdown 16.00% > 15.0% threshold",
            "source": "kill_switch_checker",
        })
        r = self._run()
        self.assertEqual(r.status, CRITICAL)
        self.assertEqual(r.value, "HARD_KILL")
        self.assertIn("all-cash", r.title.lower())

    def test_hard_kill_via_status_triggered(self) -> None:
        self._write("kill_switch_status.json", {
            "generated_at": _iso(0), "triggered": True,
            "reason": "manual trigger active", "allocation": {"cash": 1.0},
        })
        r = self._run()
        self.assertEqual(r.status, CRITICAL)
        self.assertEqual(r.value, "HARD_KILL")

    def test_kill_active_false_marker_is_not_kill(self) -> None:
        self._write("kill_switch_active.json",
                    {"active": False, "reason": "deactivated"})
        r = self._run()
        self.assertNotEqual(r.status, CRITICAL)
        self.assertEqual(r.value, "CLEAR")

    def test_hard_kill_wins_over_soft(self) -> None:
        self._write("derisk_status.json",
                    {"generated_at": _iso(0), "active": True, "tier": "SOFT_DERISK"})
        self._write("kill_switch_active.json",
                    {"activated_at": _iso(0), "reason": "drawdown 20%"})
        r = self._run()
        self.assertEqual(r.status, CRITICAL)
        self.assertEqual(r.value, "HARD_KILL")

    # ── staleness (edge-honesty) ───────────────────────────────────────────────
    def test_stale_active_derisk_still_warning_and_flagged(self) -> None:
        self._write("derisk_status.json", {
            "generated_at": _iso(48), "active": True, "tier": "SOFT_DERISK",
            "reason": "drawdown 7%",
        })
        r = self._run()
        self.assertEqual(r.status, WARNING)
        self.assertTrue(r.evidence["stale"])
        self.assertIn("stale", r.title.lower())

    def test_stale_inactive_derisk_is_info_flagged(self) -> None:
        self._write("derisk_status.json",
                    {"generated_at": _iso(48), "active": False, "tier": "NONE"})
        r = self._run()
        self.assertEqual(r.status, INFO)
        self.assertTrue(r.evidence["stale"])

    def test_unparseable_ts_treated_stale(self) -> None:
        self._write("derisk_status.json",
                    {"generated_at": "not-a-ts", "active": False, "tier": "NONE"})
        r = self._run()
        # inactive + stale → INFO, flagged stale
        self.assertEqual(r.status, INFO)
        self.assertTrue(r.evidence["stale"])

    # ── corrupt files: fail-loud, never silently OK ────────────────────────────
    def test_corrupt_derisk_is_warning_not_ok(self) -> None:
        (self.data_dir / "derisk_status.json").write_text("{broken", encoding="utf-8")
        r = self._run()
        self.assertEqual(r.status, WARNING)

    def test_corrupt_kill_active_is_warning_not_ok(self) -> None:
        (self.data_dir / "kill_switch_active.json").write_text("{broken", encoding="utf-8")
        r = self._run()
        self.assertEqual(r.status, WARNING)

    # ── wiring: gate appears in the d6 domain output ──────────────────────────
    def test_gate_is_wired_into_d6(self) -> None:
        self._write("derisk_status.json",
                    {"generated_at": _iso(0), "active": True, "tier": "SOFT_DERISK"})
        results = self.mon.check_d6_risk_gates()
        ids = {r.id for r in results}
        self.assertIn("d6.safety_state", ids)
        safety = [r for r in results if r.id == "d6.safety_state"][0]
        self.assertEqual(safety.status, WARNING)

    def test_check_writes_nothing(self) -> None:
        """Read-only: the safety gate must not create/modify any data file."""
        self._write("derisk_status.json",
                    {"generated_at": _iso(0), "active": True, "tier": "SOFT_DERISK"})
        before = {p.name: p.read_bytes() for p in self.data_dir.iterdir()}
        self._run()
        after = {p.name: p.read_bytes() for p in self.data_dir.iterdir()}
        self.assertEqual(before, after, "safety gate must be read-only")


if __name__ == "__main__":
    unittest.main()

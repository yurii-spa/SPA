"""Tests for spa_core.scheduler.adapter_watchdog (MP-311).

Run with: python3 -m pytest spa_core/tests/test_adapter_watchdog.py -v
or:        python3 -m unittest spa_core.tests.test_adapter_watchdog -v

Covers ≥30 test cases:
  - check_adapter_health: correctly detects unhealthy adapters
  - check_adapter_health: ignores healthy adapters
  - check_adapter_health: handles empty/bad input
  - stale fetch detection (>2h)
  - attempt_adapter_restart: writes watchdog_log.json
  - attempt_adapter_restart: writes orchestrator_trigger.json
  - attempt_adapter_restart: updates watchdog_state.json
  - attempt_adapter_restart: rate limit 3/hour
  - attempt_adapter_restart: rate limit resets on new hour
  - attempt_adapter_restart: fail-safe
  - run_watchdog_cycle: full pass with unhealthy adapters
  - run_watchdog_cycle: no restarts when all adapters healthy
  - run_watchdog_cycle: writes watchdog_cycle_result.json
  - run_watchdog_cycle: fail-safe
  - atomic writes (no .tmp files left)
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.scheduler.adapter_watchdog import (
    MAX_RESTARTS_PER_HOUR,
    ORCHESTRATOR_TRIGGER_FILENAME,
    WATCHDOG_CYCLE_RESULT_FILENAME,
    WATCHDOG_LOG_FILENAME,
    WATCHDOG_STATE_FILENAME,
    attempt_adapter_restart,
    check_adapter_health,
    run_watchdog_cycle,
    _is_stale_fetch,
    _current_hour_key,
)


class _TmpDir:
    def __enter__(self) -> str:
        self._d = tempfile.mkdtemp(prefix="spa_watchdog_test_")
        return self._d

    def __exit__(self, *_) -> None:
        shutil.rmtree(self._d, ignore_errors=True)


def _recent_ts() -> str:
    """Return a timestamp 10 minutes ago (fresh, not stale)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()


def _old_ts() -> str:
    """Return a timestamp 3 hours ago (stale)."""
    return (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()


def _make_adapter(
    name: str,
    *,
    status: str = "ok",
    apy_pct: float = 4.5,
    fetched_at: str | None = None,
) -> dict:
    return {
        "protocol": name,
        "status": status,
        "apy_pct": apy_pct,
        "fetched_at": fetched_at or _recent_ts(),
    }


def _make_orch_status(adapters: list[dict]) -> dict:
    return {"adapters": adapters, "status": "ok"}


# ─── check_adapter_health ─────────────────────────────────────────────────────

class TestCheckAdapterHealth(unittest.TestCase):

    def test_healthy_adapter_not_flagged(self):
        status = _make_orch_status([_make_adapter("aave_v3")])
        self.assertEqual(check_adapter_health(status), [])

    def test_status_error_flagged_unhealthy(self):
        status = _make_orch_status([_make_adapter("compound_v3", status="error")])
        self.assertIn("compound_v3", check_adapter_health(status))

    def test_status_timeout_flagged_unhealthy(self):
        status = _make_orch_status([_make_adapter("morpho_blue", status="timeout")])
        self.assertIn("morpho_blue", check_adapter_health(status))

    def test_apy_zero_flagged_unhealthy(self):
        status = _make_orch_status([_make_adapter("yearn_v3", apy_pct=0.0)])
        self.assertIn("yearn_v3", check_adapter_health(status))

    def test_apy_none_flagged_unhealthy(self):
        a = {"protocol": "euler_v2", "status": "ok", "apy_pct": None, "fetched_at": _recent_ts()}
        status = _make_orch_status([a])
        self.assertIn("euler_v2", check_adapter_health(status))

    def test_stale_fetch_flagged_unhealthy(self):
        status = _make_orch_status([_make_adapter("maple", fetched_at=_old_ts())])
        self.assertIn("maple", check_adapter_health(status))

    def test_partial_status_not_flagged_for_status(self):
        # partial is an acceptable status; but apy might still flag it
        a = {"protocol": "aave_v3", "status": "partial", "apy_pct": 3.5, "fetched_at": _recent_ts()}
        status = _make_orch_status([a])
        result = check_adapter_health(status)
        self.assertNotIn("aave_v3", result)

    def test_multiple_unhealthy(self):
        status = _make_orch_status([
            _make_adapter("aave_v3"),                              # healthy
            _make_adapter("compound_v3", status="error"),          # unhealthy
            _make_adapter("morpho_blue", apy_pct=0.0),            # unhealthy
        ])
        result = check_adapter_health(status)
        self.assertIn("compound_v3", result)
        self.assertIn("morpho_blue", result)
        self.assertNotIn("aave_v3", result)

    def test_empty_adapters_list(self):
        self.assertEqual(check_adapter_health({"adapters": []}), [])

    def test_non_dict_input(self):
        self.assertEqual(check_adapter_health("bad"), [])
        self.assertEqual(check_adapter_health(None), [])
        self.assertEqual(check_adapter_health([]), [])


# ─── _is_stale_fetch ──────────────────────────────────────────────────────────

class TestIsStaleFetch(unittest.TestCase):

    def test_fresh_ts_not_stale(self):
        self.assertFalse(_is_stale_fetch(_recent_ts()))

    def test_old_ts_is_stale(self):
        self.assertTrue(_is_stale_fetch(_old_ts()))

    def test_none_is_stale(self):
        self.assertTrue(_is_stale_fetch(None))

    def test_empty_string_is_stale(self):
        self.assertTrue(_is_stale_fetch(""))

    def test_bad_format_is_stale(self):
        self.assertTrue(_is_stale_fetch("not-a-date"))


# ─── attempt_adapter_restart ──────────────────────────────────────────────────

class TestAttemptAdapterRestart(unittest.TestCase):

    def test_first_restart_succeeds(self):
        with _TmpDir() as d:
            result = attempt_adapter_restart("aave_v3", data_dir=d)
            self.assertTrue(result["restarted"])

    def test_writes_watchdog_log(self):
        with _TmpDir() as d:
            attempt_adapter_restart("compound_v3", data_dir=d)
            log_path = Path(d) / WATCHDOG_LOG_FILENAME
            self.assertTrue(log_path.exists())
            log_data = json.loads(log_path.read_text())
            self.assertIsInstance(log_data, list)
            self.assertEqual(log_data[-1]["adapter"], "compound_v3")

    def test_writes_orchestrator_trigger(self):
        with _TmpDir() as d:
            attempt_adapter_restart("morpho_blue", data_dir=d)
            trigger_path = Path(d) / ORCHESTRATOR_TRIGGER_FILENAME
            self.assertTrue(trigger_path.exists())
            trigger = json.loads(trigger_path.read_text())
            self.assertIn("morpho_blue", trigger["adapter_restarted"])

    def test_updates_watchdog_state(self):
        with _TmpDir() as d:
            attempt_adapter_restart("yearn_v3", data_dir=d)
            state = json.loads((Path(d) / WATCHDOG_STATE_FILENAME).read_text())
            hour_key = _current_hour_key()
            entry = state["adapters"]["yearn_v3"]
            self.assertEqual(entry["hour_key"], hour_key)
            self.assertEqual(entry["count"], 1)

    def test_rate_limit_blocks_after_max_restarts(self):
        with _TmpDir() as d:
            for _ in range(MAX_RESTARTS_PER_HOUR):
                attempt_adapter_restart("euler_v2", data_dir=d)
            # Next should be rate-limited
            result = attempt_adapter_restart("euler_v2", data_dir=d)
            self.assertFalse(result["restarted"])
            self.assertIn("rate_limited", result["reason"])

    def test_rate_limit_count_is_per_adapter(self):
        with _TmpDir() as d:
            for _ in range(MAX_RESTARTS_PER_HOUR):
                attempt_adapter_restart("aave_v3", data_dir=d)
            # Different adapter should still succeed
            result = attempt_adapter_restart("compound_v3", data_dir=d)
            self.assertTrue(result["restarted"])

    def test_no_tmp_files_left(self):
        with _TmpDir() as d:
            attempt_adapter_restart("maple", data_dir=d)
            tmps = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmps, [])

    def test_failsafe_on_exception(self):
        with patch("spa_core.scheduler.adapter_watchdog._atomic_write_json", side_effect=OSError("no disk")):
            result = attempt_adapter_restart("bad_adapter", data_dir="/tmp")
            self.assertFalse(result["restarted"])
            self.assertIn("error", result["reason"])

    def test_rate_limit_resets_on_new_hour(self):
        """Simulating a new hour: hour_key changes → count resets → restart allowed."""
        with _TmpDir() as d:
            # Fill up the rate limit for the "old" hour.
            old_hour = "2026-06-11T07"
            state = {
                "adapters": {
                    "aave_v3": {"hour_key": old_hour, "count": MAX_RESTARTS_PER_HOUR}
                }
            }
            (Path(d) / WATCHDOG_STATE_FILENAME).write_text(json.dumps(state))
            # Mock the current hour to a new value
            new_hour = "2026-06-11T08"
            with patch("spa_core.scheduler.adapter_watchdog._current_hour_key", return_value=new_hour):
                result = attempt_adapter_restart("aave_v3", data_dir=d)
            self.assertTrue(result["restarted"])


# ─── run_watchdog_cycle ───────────────────────────────────────────────────────

class TestRunWatchdogCycle(unittest.TestCase):

    def test_no_restarts_when_all_healthy(self):
        with _TmpDir() as d:
            status = _make_orch_status([
                _make_adapter("aave_v3"),
                _make_adapter("compound_v3"),
            ])
            (Path(d) / "adapter_orchestrator_status.json").write_text(json.dumps(status))
            result = run_watchdog_cycle(data_dir=d)
            self.assertEqual(result["adapters_unhealthy"], 0)
            self.assertEqual(result["restarts_attempted"], 0)

    def test_restarts_unhealthy_adapters(self):
        with _TmpDir() as d:
            status = _make_orch_status([
                _make_adapter("aave_v3"),                              # healthy
                _make_adapter("compound_v3", status="error"),          # unhealthy
            ])
            (Path(d) / "adapter_orchestrator_status.json").write_text(json.dumps(status))
            result = run_watchdog_cycle(data_dir=d)
            self.assertEqual(result["adapters_unhealthy"], 1)
            self.assertEqual(result["restarts_attempted"], 1)
            self.assertEqual(result["restarts_succeeded"], 1)

    def test_writes_watchdog_cycle_result(self):
        with _TmpDir() as d:
            run_watchdog_cycle(data_dir=d)
            self.assertTrue((Path(d) / WATCHDOG_CYCLE_RESULT_FILENAME).exists())

    def test_adapters_checked_count(self):
        with _TmpDir() as d:
            status = _make_orch_status([
                _make_adapter("aave_v3"),
                _make_adapter("compound_v3"),
                _make_adapter("morpho_blue"),
            ])
            (Path(d) / "adapter_orchestrator_status.json").write_text(json.dumps(status))
            result = run_watchdog_cycle(data_dir=d)
            self.assertEqual(result["adapters_checked"], 3)

    def test_custom_adapter_status_path(self):
        with _TmpDir() as d:
            status_path = os.path.join(d, "custom_status.json")
            status = _make_orch_status([_make_adapter("maple", status="error")])
            Path(status_path).write_text(json.dumps(status))
            result = run_watchdog_cycle(adapter_status_path=status_path, data_dir=d)
            self.assertIn("maple", result["unhealthy_adapters"])

    def test_rate_limited_restarts_counted(self):
        with _TmpDir() as d:
            # Pre-fill rate limit for the unhealthy adapter
            hour_key = _current_hour_key()
            state = {
                "adapters": {
                    "morpho_blue": {"hour_key": hour_key, "count": MAX_RESTARTS_PER_HOUR}
                }
            }
            (Path(d) / WATCHDOG_STATE_FILENAME).write_text(json.dumps(state))
            status = _make_orch_status([_make_adapter("morpho_blue", status="error")])
            (Path(d) / "adapter_orchestrator_status.json").write_text(json.dumps(status))
            result = run_watchdog_cycle(data_dir=d)
            self.assertEqual(result["restarts_rate_limited"], 1)
            self.assertEqual(result["restarts_succeeded"], 0)

    def test_no_tmp_files_left(self):
        with _TmpDir() as d:
            run_watchdog_cycle(data_dir=d)
            tmps = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmps, [])

    def test_failsafe_on_exception(self):
        with patch("spa_core.scheduler.adapter_watchdog._atomic_write_json", side_effect=OSError("disk")):
            result = run_watchdog_cycle()
            self.assertEqual(result["status"], "error")
            self.assertIn("error", result)

    def test_missing_status_file_handled(self):
        with _TmpDir() as d:
            # No adapter_orchestrator_status.json — should not raise.
            result = run_watchdog_cycle(data_dir=d)
            self.assertEqual(result["adapters_checked"], 0)
            self.assertEqual(result["adapters_unhealthy"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

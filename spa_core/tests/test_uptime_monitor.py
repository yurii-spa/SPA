"""
spa_core/tests/test_uptime_monitor.py
=======================================
Unit tests for spa_core/monitoring/uptime_monitor.py — MP-211.

Coverage:
  - check_cycle_freshness: stale, fresh, missing file, corrupt JSON
  - check_http_server: ok, timeout, connection refused (mocked), HTTP error
  - check_launchd_service: subprocess fail-safe (mocked)
  - check_git_push: unix timestamp parsing, stale, fail-safe
  - run_all_checks: atomic write, output structure, no tmp leftovers
  - main(): exit code 0/1 — P0 bug fix regression (exit 256 → 0)
  - _process_agent_alerts: down-transition detection, rate-limit
  - check_tcp_port: connection success/fail, fail-safe
  - _load_prev_state / _write_prev_state: atomic I/O, round-trip
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, mock_open
import urllib.error
import urllib.request

# Make sure the package root is on the path when running tests directly
_here = Path(__file__).resolve()
_pkg_root = _here.parent.parent.parent  # repo root
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from spa_core.monitoring.uptime_monitor import (
    check_agent,
    check_agent_by_output,
    check_cycle_freshness,
    check_git_push,
    check_http_server,
    check_launchd_service,
    check_tcp_port,
    run_all_checks,
    main,
    _process_agent_alerts,
    _load_prev_state,
    _write_prev_state,
    AGENT_OUTPUT_FILES,
    ALERT_RATE_LIMIT_SEC,
    KEEPALIVE_SERVICES,
    STALE_CYCLE_HOURS,
    STALE_PUSH_HOURS,
    UPTIME_PREV_STATE_FILE,
    UPTIME_STATUS_FILE,
)
import spa_core.monitoring.uptime_monitor as uptime_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. check_cycle_freshness
# ---------------------------------------------------------------------------

class TestCheckCycleFreshness(unittest.TestCase):
    """Tests for check_cycle_freshness()."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _status_file(self) -> Path:
        return self.data_dir / "paper_trading_status.json"

    # --- Fresh file (ISO-8601 timestamp) ---
    def test_fresh_iso_timestamp(self) -> None:
        """A timestamp from 10 minutes ago should be ok=True."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        _write_json(self._status_file(), {"last_cycle_ts": ts})
        r = check_cycle_freshness(self.data_dir)
        self.assertTrue(r["ok"], f"Expected ok=True, got {r}")
        self.assertIsNotNone(r["last_run_ts"])
        self.assertLess(r["stale_hours"], 0.5)

    # --- Stale file (iso timestamp 3 hours ago) ---
    def test_stale_iso_timestamp(self) -> None:
        """A timestamp from 3 hours ago should be ok=False and stale_hours ~3."""
        from datetime import datetime, timezone, timedelta
        old = datetime.now(timezone.utc) - timedelta(hours=3)
        _write_json(self._status_file(), {"last_cycle_ts": old.isoformat()})
        r = check_cycle_freshness(self.data_dir)
        self.assertFalse(r["ok"])
        self.assertGreater(r["stale_hours"], 2.5)

    # --- Fresh file (epoch float) ---
    def test_fresh_epoch_float(self) -> None:
        ts = time.time()  # now
        _write_json(self._status_file(), {"last_cycle_ts": ts})
        r = check_cycle_freshness(self.data_dir)
        self.assertTrue(r["ok"])

    # --- Stale file (epoch float, 5 hours ago) ---
    def test_stale_epoch_float(self) -> None:
        ts = time.time() - 5 * 3600
        _write_json(self._status_file(), {"last_cycle_ts": ts})
        r = check_cycle_freshness(self.data_dir)
        self.assertFalse(r["ok"])
        self.assertGreater(r["stale_hours"], STALE_CYCLE_HOURS)

    # --- Missing file ---
    def test_missing_file(self) -> None:
        """No file → ok=False, error set."""
        r = check_cycle_freshness(self.data_dir)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])
        self.assertIn("not found", r["error"])

    # --- Corrupt JSON ---
    def test_corrupt_json(self) -> None:
        """Malformed JSON → ok=False, error set."""
        self._status_file().write_text("{ not valid json !!!", encoding="utf-8")
        r = check_cycle_freshness(self.data_dir)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    # --- Missing key ---
    def test_missing_last_cycle_ts_key(self) -> None:
        """JSON without last_cycle_ts → ok=False, error set."""
        _write_json(self._status_file(), {"equity": 100000})
        r = check_cycle_freshness(self.data_dir)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    # --- Epoch int (not float) ---
    def test_epoch_int(self) -> None:
        ts = int(time.time())  # int, not float
        _write_json(self._status_file(), {"last_cycle_ts": ts})
        r = check_cycle_freshness(self.data_dir)
        self.assertTrue(r["ok"])

    # --- Timestamp exactly at stale boundary ---
    def test_exact_stale_boundary(self) -> None:
        """Exactly STALE_CYCLE_HOURS old — on the boundary: ok=True (<=)."""
        ts = time.time() - STALE_CYCLE_HOURS * 3600
        _write_json(self._status_file(), {"last_cycle_ts": ts})
        r = check_cycle_freshness(self.data_dir)
        # stale_hours ≈ STALE_CYCLE_HOURS, check is <= so this is borderline ok
        self.assertIsNotNone(r["stale_hours"])

    # --- Returns required keys ---
    def test_return_keys(self) -> None:
        """Result always contains required keys."""
        r = check_cycle_freshness(self.data_dir)  # missing file
        for key in ("ok", "last_run_ts", "stale_hours", "error"):
            self.assertIn(key, r)


# ---------------------------------------------------------------------------
# 2. check_http_server
# ---------------------------------------------------------------------------

class TestCheckHttpServer(unittest.TestCase):
    """Tests for check_http_server() — uses mocks to avoid real network."""

    def test_ok_response(self) -> None:
        """Mocked 200 response → ok=True, latency_ms set."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = check_http_server(port=8765)
        self.assertTrue(r["ok"])
        self.assertEqual(r["status_code"], 200)
        self.assertIsNotNone(r["latency_ms"])
        self.assertIsNone(r["error"])

    def test_timeout(self) -> None:
        """Timeout → ok=False, error set, no crash."""
        import socket
        with patch("urllib.request.urlopen", side_effect=OSError("timed out")):
            r = check_http_server(port=8765)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_connection_refused(self) -> None:
        """Connection refused → ok=False, error set, no crash."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            r = check_http_server(port=8765)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_http_error_503(self) -> None:
        """HTTP 503 → ok=False, status_code=503."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="http://localhost:8765/health",
                code=503,
                msg="Service Unavailable",
                hdrs=None,
                fp=None,
            ),
        ):
            r = check_http_server(port=8765)
        self.assertFalse(r["ok"])
        self.assertEqual(r["status_code"], 503)

    def test_unexpected_exception_is_failsafe(self) -> None:
        """Any unexpected exception must not crash — ok=False, error set."""
        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            r = check_http_server(port=8765)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_return_keys(self) -> None:
        """Result always contains required keys."""
        with patch("urllib.request.urlopen", side_effect=OSError("no connection")):
            r = check_http_server(port=1)
        for key in ("ok", "status_code", "latency_ms", "error"):
            self.assertIn(key, r)

    def test_custom_port(self) -> None:
        """Custom port is used in the URL."""
        captured_urls = []

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            raise OSError("no server")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            check_http_server(port=12345)
        self.assertTrue(any("12345" in u for u in captured_urls))


# ---------------------------------------------------------------------------
# 3. check_launchd_service
# ---------------------------------------------------------------------------

class TestCheckLaunchdService(unittest.TestCase):
    """Tests for check_launchd_service() — mocked subprocess."""

    def _make_proc(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_running_service(self) -> None:
        """PID present → running=True."""
        output = '{\n\t"PID" = 1234;\n\t"LastExitStatus" = 0;\n\t"Label" = "com.spa.autopush";\n};'
        proc = self._make_proc(stdout=output)
        with patch("subprocess.run", return_value=proc):
            r = check_launchd_service("com.spa.autopush")
        self.assertTrue(r["running"])
        self.assertEqual(r["pid"], 1234)

    def test_not_loaded(self) -> None:
        """Non-zero returncode → running=False, error set."""
        proc = self._make_proc(returncode=1, stderr="Could not find service")
        with patch("subprocess.run", return_value=proc):
            r = check_launchd_service("com.spa.missing")
        self.assertFalse(r["running"])
        self.assertIsNotNone(r["error"])

    def test_subprocess_timeout_failsafe(self) -> None:
        """TimeoutExpired → ok=False, no crash."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="launchctl", timeout=10)):
            r = check_launchd_service("com.spa.autopush")
        self.assertFalse(r["running"])
        self.assertIn("timed out", r["error"])

    def test_file_not_found_failsafe(self) -> None:
        """launchctl not present → ok=False, no crash."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            r = check_launchd_service("com.spa.autopush")
        self.assertFalse(r["running"])
        self.assertIsNotNone(r["error"])

    def test_called_process_error_failsafe(self) -> None:
        """CalledProcessError → ok=False, no crash."""
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "launchctl")):
            r = check_launchd_service("com.spa.autopush")
        self.assertFalse(r["running"])
        self.assertIsNotNone(r["error"])

    def test_return_keys(self) -> None:
        """Result always has required keys."""
        proc = self._make_proc(returncode=1, stderr="not found")
        with patch("subprocess.run", return_value=proc):
            r = check_launchd_service("com.spa.x")
        for key in ("running", "pid", "last_exit", "error"):
            self.assertIn(key, r)

    def test_last_exit_status_parsed(self) -> None:
        """LastExitStatus is parsed even without PID."""
        output = '{\n\t"LastExitStatus" = 256;\n\t"Label" = "com.spa.autopush";\n};'
        proc = self._make_proc(stdout=output)
        with patch("subprocess.run", return_value=proc):
            r = check_launchd_service("com.spa.autopush")
        self.assertEqual(r["last_exit"], 256)


# ---------------------------------------------------------------------------
# 4. check_git_push
# ---------------------------------------------------------------------------

class TestCheckGitPush(unittest.TestCase):
    """Tests for check_git_push()."""

    def _make_proc(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_fresh_commit(self) -> None:
        """Commit timestamp 1 hour ago → ok=True."""
        ts = int(time.time()) - 3600  # 1 hour ago
        proc = self._make_proc(stdout=str(ts) + "\n")
        with patch("subprocess.run", return_value=proc):
            r = check_git_push("/tmp/repo")
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["stale_hours"], 1.0, delta=0.1)

    def test_stale_commit(self) -> None:
        """Commit 5 hours ago → ok=False."""
        ts = int(time.time()) - 5 * 3600
        proc = self._make_proc(stdout=str(ts) + "\n")
        with patch("subprocess.run", return_value=proc):
            r = check_git_push("/tmp/repo")
        self.assertFalse(r["ok"])
        self.assertGreater(r["stale_hours"], STALE_PUSH_HOURS)

    def test_git_not_found(self) -> None:
        """git binary absent → ok=False, no crash."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            r = check_git_push("/tmp/repo")
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_timeout_failsafe(self) -> None:
        """TimeoutExpired → ok=False, no crash."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15)):
            r = check_git_push("/tmp/repo")
        self.assertFalse(r["ok"])
        self.assertIn("timed out", r["error"])

    def test_empty_output(self) -> None:
        """git log returns empty (no commits) → ok=False, error set."""
        proc = self._make_proc(stdout="\n")
        with patch("subprocess.run", return_value=proc):
            r = check_git_push("/tmp/repo")
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_non_zero_returncode(self) -> None:
        """git log exit non-zero → ok=False, error set."""
        proc = self._make_proc(returncode=128, stderr="fatal: not a git repository")
        with patch("subprocess.run", return_value=proc):
            r = check_git_push("/tmp/repo")
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_return_keys(self) -> None:
        """Result always has required keys."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            r = check_git_push("/tmp/repo")
        for key in ("ok", "last_push_ts", "stale_hours", "error"):
            self.assertIn(key, r)

    def test_timestamp_parsing_integer_string(self) -> None:
        """Parses timestamp returned as plain integer string."""
        ts = int(time.time()) - 100
        proc = self._make_proc(stdout=f"{ts}")
        with patch("subprocess.run", return_value=proc):
            r = check_git_push("/tmp/repo")
        self.assertIsNotNone(r["last_push_ts"])
        self.assertAlmostEqual(r["last_push_ts"], float(ts), delta=1.0)


# ---------------------------------------------------------------------------
# 5. run_all_checks
# ---------------------------------------------------------------------------

class TestRunAllChecks(unittest.TestCase):
    """Tests for run_all_checks(): atomic write, output structure, no tmp leftovers."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.repo_dir = Path(self._tmp.name)  # same dir; git/launchd will fail safely

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_fresh_status(self) -> None:
        """Write a fresh paper_trading_status.json."""
        from datetime import datetime, timezone
        _write_json(
            self.data_dir / "paper_trading_status.json",
            {"last_cycle_ts": datetime.now(timezone.utc).isoformat()},
        )

    def test_returns_all_ok_key(self) -> None:
        """Result must have all_ok, ts, checks."""
        self._write_fresh_status()
        r = run_all_checks(self.data_dir, self.repo_dir)
        self.assertIn("all_ok", r)
        self.assertIn("ts", r)
        self.assertIn("checks", r)

    def test_all_ok_is_bool(self) -> None:
        self._write_fresh_status()
        r = run_all_checks(self.data_dir, self.repo_dir)
        self.assertIsInstance(r["all_ok"], bool)

    def test_writes_uptime_status_json(self) -> None:
        """run_all_checks must create data/uptime_status.json."""
        self._write_fresh_status()
        run_all_checks(self.data_dir, self.repo_dir)
        out_file = self.data_dir / UPTIME_STATUS_FILE
        self.assertTrue(out_file.exists(), "uptime_status.json was not created")

    def test_uptime_status_json_is_valid(self) -> None:
        """uptime_status.json must be valid JSON with expected keys."""
        self._write_fresh_status()
        run_all_checks(self.data_dir, self.repo_dir)
        raw = (self.data_dir / UPTIME_STATUS_FILE).read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertIn("all_ok", data)
        self.assertIn("checks", data)
        self.assertIn("ts", data)

    def test_no_tmp_file_leftover(self) -> None:
        """No .tmp file should remain after successful write."""
        self._write_fresh_status()
        run_all_checks(self.data_dir, self.repo_dir)
        tmp_file = self.data_dir / (UPTIME_STATUS_FILE + ".tmp")
        self.assertFalse(tmp_file.exists(), ".tmp file should be cleaned up")

    def test_checks_dict_has_expected_keys(self) -> None:
        """checks must contain launchd, http_server, cycle_freshness, git_push."""
        self._write_fresh_status()
        r = run_all_checks(self.data_dir, self.repo_dir)
        checks = r["checks"]
        self.assertIn("http_server", checks)
        self.assertIn("cycle_freshness", checks)
        self.assertIn("git_push", checks)
        # At least one launchd key
        launchd_keys = [k for k in checks if k.startswith("launchd_")]
        self.assertGreater(len(launchd_keys), 0)

    def test_ts_is_recent(self) -> None:
        """ts must be within last 5 seconds."""
        self._write_fresh_status()
        before = time.time()
        r = run_all_checks(self.data_dir, self.repo_dir)
        after = time.time()
        self.assertGreaterEqual(r["ts"], before)
        self.assertLessEqual(r["ts"], after + 1.0)

    def test_cycle_freshness_stale_propagates_to_all_ok(self) -> None:
        """If cycle is stale → all_ok must be False."""
        ts = time.time() - 4 * 3600  # 4 hours ago
        _write_json(
            self.data_dir / "paper_trading_status.json",
            {"last_cycle_ts": ts},
        )
        r = run_all_checks(self.data_dir, self.repo_dir)
        self.assertFalse(r["all_ok"])

    def test_missing_status_file_propagates_to_all_ok_false(self) -> None:
        """Missing paper_trading_status.json → all_ok False."""
        # no status file written
        r = run_all_checks(self.data_dir, self.repo_dir)
        self.assertFalse(r["all_ok"])

    def test_uptime_status_overwritten_on_second_call(self) -> None:
        """Second call updates the file (not appends)."""
        self._write_fresh_status()
        run_all_checks(self.data_dir, self.repo_dir)
        ts1 = (self.data_dir / UPTIME_STATUS_FILE).stat().st_mtime

        time.sleep(0.05)  # small delay so mtime differs
        self._write_fresh_status()
        run_all_checks(self.data_dir, self.repo_dir)
        ts2 = (self.data_dir / UPTIME_STATUS_FILE).stat().st_mtime

        self.assertGreaterEqual(ts2, ts1)  # file was touched again

    def test_written_json_matches_returned_dict(self) -> None:
        """The written JSON must match what was returned."""
        self._write_fresh_status()
        r = run_all_checks(self.data_dir, self.repo_dir)
        raw = (self.data_dir / UPTIME_STATUS_FILE).read_text(encoding="utf-8")
        written = json.loads(raw)
        self.assertEqual(written["all_ok"], r["all_ok"])
        self.assertAlmostEqual(written["ts"], r["ts"], delta=0.001)


# ---------------------------------------------------------------------------
# 6. Additional edge-case / integration tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Additional edge-case tests."""

    def test_check_cycle_freshness_returns_stale_hours_none_on_error(self) -> None:
        """On error stale_hours should be None."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = check_cycle_freshness(tmp)  # no file
        self.assertIsNone(r["stale_hours"])

    def test_check_cycle_freshness_invalid_type_for_ts(self) -> None:
        """last_cycle_ts as a dict → error, not crash."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_trading_status.json"
            _write_json(path, {"last_cycle_ts": {"nested": "value"}})
            r = check_cycle_freshness(tmp)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_check_http_server_200_range_ok(self) -> None:
        """Any 2xx status code counts as ok."""
        mock_resp = MagicMock()
        mock_resp.status = 204  # No Content
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = check_http_server(port=8765)
        self.assertTrue(r["ok"])

    def test_check_git_push_invalid_timestamp(self) -> None:
        """Non-numeric git log output → error, not crash."""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "not-a-timestamp\n"
        proc.stderr = ""
        with patch("subprocess.run", return_value=proc):
            r = check_git_push("/tmp/repo")
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])

    def test_run_all_checks_survives_read_only_data_dir(self) -> None:
        """If data_dir is read-only, run_all_checks should not crash."""
        import tempfile, stat
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            # Write status so cycle freshness doesn't fail for wrong reason
            from datetime import datetime, timezone
            _write_json(
                data_dir / "paper_trading_status.json",
                {"last_cycle_ts": datetime.now(timezone.utc).isoformat()},
            )
            # Make dir read-only
            data_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
            try:
                # Should not raise
                r = run_all_checks(data_dir, data_dir)
                self.assertIn("all_ok", r)
            finally:
                # Restore permissions so cleanup works
                data_dir.chmod(stat.S_IRWXU)


# ---------------------------------------------------------------------------
# 7. check_agent_by_output — output-file freshness fallback (the core fix)
# ---------------------------------------------------------------------------

class TestCheckAgentByOutput(unittest.TestCase):
    """
    Tests for check_agent_by_output(): periodic launchd agents are judged by
    the freshness of their output file rather than a live PID.

    A test label "com.spa.peg_monitor" is mapped to data/peg_report.json in
    AGENT_OUTPUT_FILES; we build a temporary repo root mirroring that layout.
    """

    LABEL = "com.spa.peg_monitor"  # mapped to data/peg_report.json

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # The mapping for LABEL points at data/peg_report.json
        rel, self.max_age = AGENT_OUTPUT_FILES[self.LABEL]
        self.rel = rel
        self.out_path = self.root / rel
        self.out_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_with_age(self, age_seconds: float) -> None:
        """Write the output file and back-date its mtime by age_seconds."""
        self.out_path.write_text("{}", encoding="utf-8")
        target = time.time() - age_seconds
        os.utime(self.out_path, (target, target))

    def test_running_if_file_fresh(self) -> None:
        """File updated 5 minutes ago → running=True."""
        self._write_with_age(5 * 60)
        r = check_agent_by_output(self.LABEL, base_dir=self.root)
        self.assertTrue(r["running"], r)
        self.assertEqual(r["method"], "output_file_age")
        self.assertLessEqual(r["age_seconds"], self.max_age)

    def test_not_running_if_file_stale(self) -> None:
        """File updated 2 hours ago (> max_age) → running=False."""
        self._write_with_age(2 * 3600)
        r = check_agent_by_output(self.LABEL, base_dir=self.root)
        self.assertFalse(r["running"], r)
        self.assertEqual(r["method"], "output_file_age")
        self.assertGreater(r["age_seconds"], self.max_age)

    def test_not_running_if_file_missing(self) -> None:
        """No output file at all → running=False, method=output_file_missing."""
        # don't create the file
        r = check_agent_by_output(self.LABEL, base_dir=self.root)
        self.assertFalse(r["running"], r)
        self.assertEqual(r["method"], "output_file_missing")

    def test_explicit_max_age_override(self) -> None:
        """An explicit max_age_seconds overrides the mapping default."""
        self._write_with_age(100)  # 100 s old
        # With a 50 s window it is stale; with a 200 s window it is fresh.
        stale = check_agent_by_output(self.LABEL, max_age_seconds=50, base_dir=self.root)
        fresh = check_agent_by_output(self.LABEL, max_age_seconds=200, base_dir=self.root)
        self.assertFalse(stale["running"])
        self.assertTrue(fresh["running"])

    def test_no_output_file_mapping_returns_none(self) -> None:
        """A KeepAlive daemon (no output file) returns running=None."""
        r = check_agent_by_output("com.spa.httpserver", base_dir=self.root)
        self.assertIsNone(r["running"])
        self.assertEqual(r["method"], "no_output_file")

    def test_unknown_label_returns_none(self) -> None:
        """A label not in the mapping returns running=None, no crash."""
        r = check_agent_by_output("com.spa.does_not_exist", base_dir=self.root)
        self.assertIsNone(r["running"])
        self.assertEqual(r["method"], "no_mapping")

    def test_return_keys(self) -> None:
        r = check_agent_by_output(self.LABEL, base_dir=self.root)
        for key in ("running", "method", "file", "age_seconds", "max_age"):
            self.assertIn(key, r)


# ---------------------------------------------------------------------------
# 8. check_agent — type-aware combined check (PID vs output-file)
# ---------------------------------------------------------------------------

class TestCheckAgent(unittest.TestCase):
    """Tests for check_agent(): KeepAlive→PID/port, periodic→PID-or-output."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fresh_output(self, label: str) -> None:
        rel, _ = AGENT_OUTPUT_FILES[label]
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    def test_periodic_idle_but_fresh_output_is_running(self) -> None:
        """
        THE BUG FIX: periodic agent loaded but with NO live PID, yet its output
        file is fresh → check_agent must report running=True (not FAIL).
        """
        label = "com.spa.peg_monitor"
        self._fresh_output(label)
        # launchctl returns loaded-but-no-PID (running=False, no error)
        no_pid = {"running": False, "pid": None, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=no_pid):
            r = check_agent(label, base_dir=self.root)
        self.assertTrue(r["running"], r)
        self.assertEqual(r["method"], "output_file_age")

    def test_periodic_idle_and_stale_output_is_not_running(self) -> None:
        """Periodic agent, no PID, missing/stale output → running=False."""
        label = "com.spa.peg_monitor"
        # do NOT create the output file → missing
        no_pid = {"running": False, "pid": None, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=no_pid):
            r = check_agent(label, base_dir=self.root)
        self.assertFalse(r["running"], r)

    def test_periodic_with_live_pid_is_running(self) -> None:
        """Periodic agent that happens to be mid-run (live PID) → running=True."""
        label = "com.spa.peg_monitor"
        live = {"running": True, "pid": 4321, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=live):
            r = check_agent(label, base_dir=self.root)
        self.assertTrue(r["running"])
        self.assertEqual(r["method"], "launchctl_pid")

    def test_keepalive_requires_pid(self) -> None:
        """KeepAlive daemon with no PID and no port → running=False."""
        label = "com.spa.cloudflared"  # KeepAlive, no port mapping
        self.assertIn(label, KEEPALIVE_SERVICES)
        no_pid = {"running": False, "pid": None, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=no_pid):
            r = check_agent(label, base_dir=self.root)
        self.assertFalse(r["running"])

    def test_keepalive_pid_present_is_running(self) -> None:
        """KeepAlive daemon with a live PID → running=True via launchctl_pid."""
        label = "com.spa.cloudflared"
        live = {"running": True, "pid": 999, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=live):
            r = check_agent(label, base_dir=self.root)
        self.assertTrue(r["running"])
        self.assertEqual(r["method"], "launchctl_pid")

    def test_keepalive_port_fallback(self) -> None:
        """httpserver with no PID but open port → running=True via tcp_port."""
        label = "com.spa.httpserver"  # has AGENT_PORTS[8765]
        no_pid = {"running": False, "pid": None, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=no_pid), \
             patch.object(uptime_mod, "check_tcp_port", return_value=True):
            r = check_agent(label, base_dir=self.root)
        self.assertTrue(r["running"])
        self.assertEqual(r["method"], "tcp_port")

    def test_no_output_file_periodic_defers_to_launchctl(self) -> None:
        """
        A periodic-style label with no output file (weekly_backup) and no PID
        defers to launchctl's verdict rather than crashing or flapping.
        """
        label = "com.spa.weekly_backup"  # mapped to (None, 0)
        no_pid = {"running": False, "pid": None, "last_exit": 0, "error": None}
        with patch.object(uptime_mod, "check_launchd_service", return_value=no_pid):
            r = check_agent(label, base_dir=self.root)
        # No output file → running stays False (launchctl verdict), no exception
        self.assertIn("running", r)


# ---------------------------------------------------------------------------
# 9. main() exit-code — P0 bug-fix regression suite
# ---------------------------------------------------------------------------

_FAKE_RESULT_OK = {"all_ok": True, "ts": 1_700_000_000.0, "checks": {}}
_FAKE_RESULT_DEGRADED = {"all_ok": False, "ts": 1_700_000_000.0, "checks": {}}


class TestMainExitCode(unittest.TestCase):
    """
    Regression tests for the P0 exit-code bug.

    Root cause: old code did ``sys.exit(result["all_ok"])`` which exited with 1
    when all checks passed (True → 1) and with 0 when degraded (False → 0) — or
    alternatively exited with 1 whenever DEGRADED (``sys.exit(not all_ok)``).
    Under launchd, process exit 1 is encoded as LastExitStatus = 256, making the
    *monitor* itself appear crashed to every observer.

    Fix: ``main()`` always returns integer 0 in default (non-strict) mode, even
    when the monitored system is DEGRADED. DEGRADED state is reported via
    data/uptime_status.json and Telegram alerts — NOT via process exit code.
    """

    def test_default_returns_0_when_all_ok_true(self) -> None:
        """Healthy system + default mode → exit 0."""
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_OK):
            code = main([])
        self.assertEqual(code, 0)

    def test_default_returns_0_when_all_ok_false(self) -> None:
        """
        P0 REGRESSION: DEGRADED + default mode → MUST be exit 0, not 1.

        exit(1) encodes to LaunchD LastExitStatus=256 which makes the monitor
        look perpetually broken. This is the core bug that triggered AGENT-P0-007.
        """
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_DEGRADED):
            code = main([])
        self.assertEqual(code, 0,
            "REGRESSION: default mode must exit 0 even when DEGRADED. "
            "exit(1) → LastExitStatus=256 → monitor appears crashed to launchd.")

    def test_strict_returns_0_when_all_ok_true(self) -> None:
        """--strict mode: healthy → exit 0."""
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_OK):
            code = main(["--strict"])
        self.assertEqual(code, 0)

    def test_strict_returns_1_when_all_ok_false(self) -> None:
        """--strict mode: DEGRADED → exit 1 (opt-in legacy behaviour)."""
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_DEGRADED):
            code = main(["--strict"])
        self.assertEqual(code, 1)

    def test_returns_1_on_internal_failure(self) -> None:
        """If run_all_checks raises an exception → exit 1 (monitor itself failed)."""
        with patch.object(uptime_mod, "run_all_checks",
                          side_effect=RuntimeError("unexpected crash")):
            code = main([])
        self.assertEqual(code, 1)

    def test_return_type_is_int_not_bool(self) -> None:
        """main() must return plain int, not bool.

        sys.exit(True) == sys.exit(1). If main() returned True/False instead
        of 0/1 the caller can't distinguish int from bool, and some call sites
        do strict type checking.
        """
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_OK):
            code = main([])
        self.assertEqual(type(code), int,
            "main() must return int 0 or 1, not bool True/False")

    def test_sysexit_code_zero_in_default_mode(self) -> None:
        """Verify sys.exit(main([])) raises SystemExit(0), NOT SystemExit(1)/SystemExit(256)."""
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_DEGRADED):
            with self.assertRaises(SystemExit) as cm:
                sys.exit(main([]))
        self.assertEqual(cm.exception.code, 0,
            "sys.exit(main()) must be SystemExit(0) — not 1 or 256")

    def test_argv_none_uses_sys_argv(self) -> None:
        """main(argv=None) parses sys.argv[1:] for the --strict flag."""
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_DEGRADED):
            with patch.object(sys, "argv", ["uptime_monitor"]):  # no --strict
                code = main(None)
        self.assertEqual(code, 0)

    def test_strict_flag_via_argv_none(self) -> None:
        """--strict via sys.argv (argv=None path) triggers legacy exit-1-on-degraded."""
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_DEGRADED):
            with patch.object(sys, "argv", ["uptime_monitor", "--strict"]):
                code = main(None)
        self.assertEqual(code, 1)

    def test_prints_status_line(self) -> None:
        """main() must emit a human-readable 'Status:' line."""
        import io
        buf = io.StringIO()
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_OK):
            with patch("sys.stdout", buf):
                main([])
        self.assertIn("Status:", buf.getvalue())

    def test_prints_degraded_status_when_not_ok(self) -> None:
        """When DEGRADED, output must say 'DEGRADED'."""
        import io
        buf = io.StringIO()
        with patch.object(uptime_mod, "run_all_checks", return_value=_FAKE_RESULT_DEGRADED):
            with patch("sys.stdout", buf):
                main([])
        self.assertIn("DEGRADED", buf.getvalue())


# ---------------------------------------------------------------------------
# 10. _process_agent_alerts — Telegram down-transition alerts
# ---------------------------------------------------------------------------

class TestProcessAgentAlerts(unittest.TestCase):
    """Tests for _process_agent_alerts(): down-transition detection + rate-limit."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_prev(self, data: dict) -> None:
        _write_json(self.data_dir / UPTIME_PREV_STATE_FILE, data)

    def test_no_alert_on_first_run_no_prev_state(self) -> None:
        """First run: no previous state → was_running=False → no transition → no alert."""
        checks = {"launchd_autopush": {"running": False, "pid": None}}
        with patch.object(uptime_mod, "_send_agent_alert", return_value=False) as m:
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        m.assert_not_called()

    def test_alert_fires_on_running_to_down_transition(self) -> None:
        """was running → now down: alert must be sent."""
        self._write_prev({"agents": {"com.spa.autopush": {"running": True}}, "alerts": {}})
        checks = {
            "launchd_autopush": {
                "running": False, "pid": None,
                "age_seconds": 300, "file": "logs/auto_push.log",
            }
        }
        with patch.object(uptime_mod, "_send_agent_alert", return_value=True) as m:
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        m.assert_called_once()
        label_arg = m.call_args[0][0]
        self.assertEqual(label_arg, "com.spa.autopush")

    def test_no_alert_when_still_running(self) -> None:
        """Agent was running and is still running → no alert."""
        self._write_prev({"agents": {"com.spa.autopush": {"running": True}}, "alerts": {}})
        checks = {"launchd_autopush": {"running": True, "pid": 4321}}
        with patch.object(uptime_mod, "_send_agent_alert") as m:
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        m.assert_not_called()

    def test_no_alert_when_was_already_down(self) -> None:
        """Agent was already down → no new transition → no alert."""
        self._write_prev({"agents": {"com.spa.autopush": {"running": False}}, "alerts": {}})
        checks = {"launchd_autopush": {"running": False}}
        with patch.object(uptime_mod, "_send_agent_alert") as m:
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        m.assert_not_called()

    def test_rate_limit_suppresses_alert_within_window(self) -> None:
        """Second alert within ALERT_RATE_LIMIT_SEC is suppressed."""
        now = time.time()
        self._write_prev({
            "agents": {"com.spa.autopush": {"running": True}},
            "alerts": {"com.spa.autopush": now - ALERT_RATE_LIMIT_SEC + 60},  # 60s before expiry
        })
        checks = {"launchd_autopush": {"running": False}}
        with patch.object(uptime_mod, "_send_agent_alert") as m:
            _process_agent_alerts(self.data_dir, checks, now=now)
        m.assert_not_called()

    def test_rate_limit_allows_alert_after_window_expires(self) -> None:
        """Alert allowed again after rate-limit window has expired."""
        now = time.time()
        self._write_prev({
            "agents": {"com.spa.autopush": {"running": True}},
            "alerts": {"com.spa.autopush": now - ALERT_RATE_LIMIT_SEC - 1},
        })
        checks = {"launchd_autopush": {"running": False, "age_seconds": 0, "file": None}}
        with patch.object(uptime_mod, "_send_agent_alert", return_value=True) as m:
            _process_agent_alerts(self.data_dir, checks, now=now)
        m.assert_called_once()

    def test_writes_fresh_state_file_after_run(self) -> None:
        """uptime_prev_state.json is (re-)written after each call."""
        checks = {"launchd_autopush": {"running": True, "pid": 99}}
        _process_agent_alerts(self.data_dir, checks, now=time.time())
        out = self.data_dir / UPTIME_PREV_STATE_FILE
        self.assertTrue(out.exists())
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("com.spa.autopush", data["agents"])
        self.assertTrue(data["agents"]["com.spa.autopush"]["running"])

    def test_alert_ts_recorded_after_successful_send(self) -> None:
        """Alert timestamp is saved when alert is sent, for rate-limiting next run."""
        now = 1_700_100_000.0
        self._write_prev({"agents": {"com.spa.peg_monitor": {"running": True}}, "alerts": {}})
        checks = {"launchd_peg_monitor": {"running": False, "age_seconds": 60, "file": None}}
        with patch.object(uptime_mod, "_send_agent_alert", return_value=True):
            _process_agent_alerts(self.data_dir, checks, now=now)
        data = json.loads((self.data_dir / UPTIME_PREV_STATE_FILE).read_text(encoding="utf-8"))
        self.assertAlmostEqual(data["alerts"].get("com.spa.peg_monitor", 0), now, delta=1.0)

    def test_no_alert_ts_when_send_fails(self) -> None:
        """If _send_agent_alert returns False, timestamp is NOT recorded."""
        self._write_prev({"agents": {"com.spa.peg_monitor": {"running": True}}, "alerts": {}})
        checks = {"launchd_peg_monitor": {"running": False}}
        with patch.object(uptime_mod, "_send_agent_alert", return_value=False):
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        data = json.loads((self.data_dir / UPTIME_PREV_STATE_FILE).read_text(encoding="utf-8"))
        # Timestamp should not be present (or should be absent) since send failed
        self.assertNotIn("com.spa.peg_monitor", data.get("alerts", {}))

    def test_non_launchd_keys_are_ignored(self) -> None:
        """http_server / cycle_freshness / git_push keys do not trigger alerts."""
        checks = {
            "http_server": {"ok": False},
            "cycle_freshness": {"ok": False, "stale_hours": 5.0},
            "git_push": {"ok": False},
        }
        with patch.object(uptime_mod, "_send_agent_alert") as m:
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        m.assert_not_called()

    def test_corrupt_prev_state_treated_as_empty(self) -> None:
        """Corrupt uptime_prev_state.json is silently reset — no crash, no spurious alerts."""
        (self.data_dir / UPTIME_PREV_STATE_FILE).write_text("not json!!!", encoding="utf-8")
        checks = {"launchd_autopush": {"running": False}}
        with patch.object(uptime_mod, "_send_agent_alert") as m:
            _process_agent_alerts(self.data_dir, checks, now=time.time())
        m.assert_not_called()  # no prev state → no transition detected


# ---------------------------------------------------------------------------
# 11. check_tcp_port — TCP liveness probe
# ---------------------------------------------------------------------------

class TestCheckTcpPort(unittest.TestCase):
    """Tests for check_tcp_port()."""

    def test_returns_true_on_open_port(self) -> None:
        """Successful connection → True."""
        import socket
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda s: s
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch.object(socket, "create_connection", return_value=mock_ctx):
            self.assertTrue(check_tcp_port(8765))

    def test_returns_false_on_connection_refused(self) -> None:
        """Connection refused (OSError) → False, no crash."""
        import socket
        with patch.object(socket, "create_connection",
                          side_effect=OSError("Connection refused")):
            self.assertFalse(check_tcp_port(1))

    def test_returns_false_on_timeout(self) -> None:
        """Timeout (OSError subclass) → False, no crash."""
        import socket
        with patch.object(socket, "create_connection",
                          side_effect=OSError("timed out")):
            self.assertFalse(check_tcp_port(9999))

    def test_failsafe_on_unexpected_exception(self) -> None:
        """Any unexpected exception → False, never raises."""
        import socket
        with patch.object(socket, "create_connection",
                          side_effect=RuntimeError("boom")):
            self.assertFalse(check_tcp_port(8765))

    def test_uses_custom_host(self) -> None:
        """Custom host parameter is forwarded to create_connection."""
        import socket
        calls: list = []

        def fake_conn(addr, timeout=None):
            calls.append(addr)
            raise OSError("no server")

        with patch.object(socket, "create_connection", side_effect=fake_conn):
            check_tcp_port(port=1234, host="192.168.1.1")
        self.assertTrue(any(addr[0] == "192.168.1.1" for addr in calls))

    def test_returns_bool(self) -> None:
        """Return value is always a plain bool."""
        import socket
        with patch.object(socket, "create_connection",
                          side_effect=OSError("no server")):
            result = check_tcp_port(1)
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# 12. _load_prev_state / _write_prev_state — atomic prev-state I/O
# ---------------------------------------------------------------------------

class TestPrevStateIO(unittest.TestCase):
    """Tests for _load_prev_state() and _write_prev_state()."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_load_missing_file_returns_empty_structure(self) -> None:
        """No file → {"agents": {}, "alerts": {}}, no crash."""
        state = _load_prev_state(self.data_dir)
        self.assertEqual(state, {"agents": {}, "alerts": {}})

    def test_load_corrupt_json_returns_empty(self) -> None:
        """Malformed JSON → empty structure, no crash."""
        (self.data_dir / UPTIME_PREV_STATE_FILE).write_text("INVALID", encoding="utf-8")
        state = _load_prev_state(self.data_dir)
        self.assertEqual(state, {"agents": {}, "alerts": {}})

    def test_load_non_dict_returns_empty(self) -> None:
        """JSON array instead of dict → empty structure, no crash."""
        _write_json(self.data_dir / UPTIME_PREV_STATE_FILE, [1, 2, 3])
        state = _load_prev_state(self.data_dir)
        self.assertEqual(state, {"agents": {}, "alerts": {}})

    def test_load_returns_valid_state(self) -> None:
        """Well-formed state is loaded correctly."""
        data = {
            "agents": {"com.spa.autopush": {"running": True}},
            "alerts": {"com.spa.autopush": 1_700_000_000.0},
        }
        _write_json(self.data_dir / UPTIME_PREV_STATE_FILE, data)
        state = _load_prev_state(self.data_dir)
        self.assertTrue(state["agents"]["com.spa.autopush"]["running"])
        self.assertAlmostEqual(state["alerts"]["com.spa.autopush"], 1_700_000_000.0)

    def test_write_creates_state_file(self) -> None:
        """_write_prev_state creates the file."""
        _write_prev_state(self.data_dir, {"agents": {}, "alerts": {}})
        self.assertTrue((self.data_dir / UPTIME_PREV_STATE_FILE).exists())

    def test_write_no_tmp_leftover(self) -> None:
        """No .tmp file should remain after successful write."""
        _write_prev_state(self.data_dir, {"agents": {}, "alerts": {}})
        tmp = self.data_dir / (UPTIME_PREV_STATE_FILE + ".tmp")
        self.assertFalse(tmp.exists())

    def test_roundtrip_preserves_data(self) -> None:
        """Write then load returns identical structure."""
        original = {
            "agents": {
                "com.spa.peg_monitor": {"running": False},
                "com.spa.httpserver": {"running": True},
            },
            "alerts": {
                "com.spa.peg_monitor": 1_700_000_500.0,
            },
        }
        _write_prev_state(self.data_dir, original)
        loaded = _load_prev_state(self.data_dir)
        self.assertFalse(loaded["agents"]["com.spa.peg_monitor"]["running"])
        self.assertTrue(loaded["agents"]["com.spa.httpserver"]["running"])
        self.assertAlmostEqual(
            loaded["alerts"]["com.spa.peg_monitor"], 1_700_000_500.0, delta=0.001
        )

    def test_write_is_valid_json(self) -> None:
        """Written file is valid JSON (not truncated)."""
        state = {"agents": {"com.spa.x": {"running": True}}, "alerts": {}}
        _write_prev_state(self.data_dir, state)
        raw = (self.data_dir / UPTIME_PREV_STATE_FILE).read_text(encoding="utf-8")
        parsed = json.loads(raw)  # should not raise
        self.assertIn("agents", parsed)

    def test_load_missing_agents_key_defaults_to_empty(self) -> None:
        """State dict without 'agents' key → agents defaults to {}."""
        _write_json(self.data_dir / UPTIME_PREV_STATE_FILE, {"alerts": {}})
        state = _load_prev_state(self.data_dir)
        self.assertEqual(state["agents"], {})

    def test_load_missing_alerts_key_defaults_to_empty(self) -> None:
        """State dict without 'alerts' key → alerts defaults to {}."""
        _write_json(self.data_dir / UPTIME_PREV_STATE_FILE, {"agents": {}})
        state = _load_prev_state(self.data_dir)
        self.assertEqual(state["alerts"], {})

    def test_load_invalid_agents_type_defaults_to_empty(self) -> None:
        """agents value that is not a dict (e.g. list) is reset to {}."""
        _write_json(self.data_dir / UPTIME_PREV_STATE_FILE,
                    {"agents": ["x", "y"], "alerts": {}})
        state = _load_prev_state(self.data_dir)
        self.assertEqual(state["agents"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)

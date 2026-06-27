#!/usr/bin/env python3
"""Tests for the hardened pre-deploy gate scripts/check_agent_before_deploy.sh.

Covers the three hardening fixes:

  1. SANDBOXED run-once never mutates the canonical track — proven by the
     fail-CLOSED hash guard: if the run touches data/equity_curve_daily.json the
     gate exits non-zero. (Here we assert the hash-guard *primitive* — a changed
     file is detected and rejected.)
  2. NO HANG — the macOS-safe `run_with_timeout` bash primitive kills a
     long-running command at the deadline and reports 124, in ~deadline seconds
     (NOT the command's natural duration).
  3. ACTUAL log path — the BSD-safe `find -newer <sentinel>` detection accepts a
     custom dated log (e.g. logs/daily_backup.log), unlike the old
     `find -newermt @epoch` which BSD find silently ignores.

Pure stdlib (unittest + subprocess + tempfile). Does NOT touch real launchd
agents or the real data/ track — every check runs the gate's bash primitives in
isolation. Run:
    python3 -m pytest scripts/tests/test_check_agent_before_deploy.py -v
"""
from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
GATE = _SCRIPTS_DIR / "check_agent_before_deploy.sh"

# The exact macOS-safe timeout primitive shipped in the gate. Kept in sync with
# the script; this is the no-hang mechanism (fix #2).
RUN_WITH_TIMEOUT = r"""
run_with_timeout() {
    local secs="$1"; shift
    "$@" & local cmd_pid=$!
    ( sleep "$secs"
      kill -0 "$cmd_pid" 2>/dev/null && kill -TERM "$cmd_pid" 2>/dev/null
      sleep 2
      kill -0 "$cmd_pid" 2>/dev/null && kill -KILL "$cmd_pid" 2>/dev/null ) & local wd_pid=$!
    wait "$cmd_pid" 2>/dev/null; local rc=$?
    kill "$wd_pid" 2>/dev/null; wait "$wd_pid" 2>/dev/null
    if [ "$rc" -eq 143 ] || [ "$rc" -eq 137 ]; then return 124; fi
    return "$rc"
}
"""


def _bash(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestGateExistsAndParses(unittest.TestCase):
    def test_script_present_and_syntactically_valid(self):
        self.assertTrue(GATE.is_file(), f"missing gate script: {GATE}")
        r = _bash(f"bash -n {GATE}")
        self.assertEqual(r.returncode, 0, f"syntax error:\n{r.stderr}")

    def test_does_not_use_bsd_unsafe_newermt_epoch(self):
        """Regression: BSD find silently ignores `-newermt @epoch` (fix #3).

        Allow `-newermt` to appear in an explanatory comment, but never in an
        active `find` invocation.
        """
        for ln in GATE.read_text().splitlines():
            code = ln.split("#", 1)[0]  # strip trailing comments
            if "find" in code and "-newermt" in code:
                self.fail(f"active find uses BSD-unsafe -newermt: {ln.strip()}")
        self.assertIn("-newer ", GATE.read_text(),
                      "gate must detect fresh logs via BSD-safe `find -newer <sentinel>`")

    def test_strips_live_flag_and_hash_guards_track(self):
        text = GATE.read_text()
        # fix #1 markers
        self.assertIn("--live", text)
        self.assertIn("SANDBOX VIOLATION", text)
        self.assertIn("equity_curve_daily.json", text)
        # the sandboxed inner run must NOT pass --live
        self.assertIn("no --live", text)


class TestNoHangPrimitive(unittest.TestCase):
    """Fix #2: run_with_timeout kills a hung command at the deadline."""

    def test_long_command_is_killed_at_deadline_returns_124(self):
        t0 = time.monotonic()
        r = _bash(RUN_WITH_TIMEOUT + "\nrun_with_timeout 2 sleep 30\necho rc=$?\n")
        elapsed = time.monotonic() - t0
        self.assertIn("rc=124", r.stdout, f"expected timeout rc=124, got:\n{r.stdout}")
        # Killed near the 2s deadline (+2s SIGKILL grace), NOT the 30s sleep.
        self.assertLess(elapsed, 10, f"timeout did not fire promptly (elapsed={elapsed:.1f}s)")

    def test_fast_command_passes_through_its_own_rc(self):
        r = _bash(RUN_WITH_TIMEOUT + "\nrun_with_timeout 10 bash -c 'exit 0'\necho rc=$?\n")
        self.assertIn("rc=0", r.stdout)
        r = _bash(RUN_WITH_TIMEOUT + "\nrun_with_timeout 10 bash -c 'exit 7'\necho rc=$?\n")
        self.assertIn("rc=7", r.stdout, "non-timeout exit code must propagate unchanged")


class TestHashGuardPrimitive(unittest.TestCase):
    """Fix #1: a changed track file is detected (fail-CLOSED)."""

    def test_hash_change_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "equity_curve_daily.json"
            f.write_text('{"daily": [1]}')
            script = f"""
                hash_file() {{ [ -f "$1" ] && shasum -a 256 "$1" 2>/dev/null | awk '{{print $1}}' || echo MISSING; }}
                B=$(hash_file '{f}')
                echo 'mutated' >> '{f}'   # simulate a stray live write
                A=$(hash_file '{f}')
                [ "$B" != "$A" ] && echo CHANGED || echo SAME
            """
            r = _bash(script)
            self.assertIn("CHANGED", r.stdout)

    def test_identical_file_yields_same_hash(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "equity_curve_daily.json"
            f.write_text('{"daily": [1]}')
            script = f"""
                hash_file() {{ [ -f "$1" ] && shasum -a 256 "$1" 2>/dev/null | awk '{{print $1}}' || echo MISSING; }}
                B=$(hash_file '{f}'); A=$(hash_file '{f}')
                [ "$B" = "$A" ] && echo SAME || echo CHANGED
            """
            r = _bash(script)
            self.assertIn("SAME", r.stdout)


class TestBsdSafeLogDetection(unittest.TestCase):
    """Fix #3: `find -newer <sentinel>` finds a fresh custom dated log."""

    def test_sentinel_find_detects_fresh_log(self):
        with tempfile.TemporaryDirectory() as d:
            logs = Path(d) / "logs"
            logs.mkdir()
            old = logs / "old.log"
            old.write_text("old\n")
            # Back-date the stale log well before the sentinel so the freshness
            # test is unambiguous (the gate back-dates the sentinel only ~2s, but
            # the run-start ordering guarantees real logs are written AFTER it).
            script = f"""
                touch -t 202601010000.00 '{logs}/old.log'   # clearly stale
                SENT=$(mktemp)
                touch -t "$(date -v-2S +%Y%m%d%H%M.%S 2>/dev/null || date +%Y%m%d%H%M.%S)" "$SENT"
                sleep 1
                echo 'fresh run output' > '{logs}/daily_backup.log'   # custom dated log
                find '{logs}' -type f -newer "$SENT" | sort
                rm -f "$SENT"
            """
            r = _bash(script)
            self.assertIn("daily_backup.log", r.stdout,
                          f"BSD-safe find did not detect the fresh custom log:\n{r.stdout}")
            self.assertNotIn("old.log", r.stdout,
                             "stale log must not be picked up as fresh")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""RTMR (ADR-053) tick-stage honesty — a failed stage must be VISIBLE, and must not claim liveness.

Two defects, both class #29/#31/#35–#38/#40 (a claim about a measurement that never happened):

1. ``main()`` reported a failed tick with a ``print`` that had no ``flush=True``. The service's
   stdout is a file (block-buffered, 8 KB) and the process never exits, so failure messages sat in
   the buffer; a ``launchctl`` restart (SIGKILL) discarded them entirely. Measured on the host:
   50 failure lines → 8-byte log, still 8 bytes after SIGKILL.
2. ``sense_loop._heartbeat`` writes ``alive: true`` at the end of stage 1 of 3. Stages 2 (reaction
   ladder) and 3 (posture self-clear — the ONLY way out of DEFENSIVE, which clamps every target to
   0 via ``rtmr_posture_gate``) run afterwards. Their failure left a fresh ``alive: true`` on disk
   and, per defect 1, no log line at all.

Everything here is hermetic: no network, no launchd, no live ``data/``. Thresholds, the reaction
ladder, posture semantics and the kill-switch are NOT exercised or changed — only what the service
reports about itself.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from spa_core.monitoring import rtmr_service as SVC
from spa_core.monitoring import sense_loop as SL
from spa_core.monitoring import signal as S


def _good_sensor(cfg, now_ts):
    return [S.make_signal(ts=now_ts, source="peg", scope="aave_v3:USDC", metric="depeg_pct",
                          value=0.001, severity="info", threshold_crossed=False, staleness_ok=True)]
_good_sensor.source = "peg"


class _TickBase(unittest.TestCase):
    """Redirect every sense_loop artefact into a temp dir; register exactly one healthy sensor."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._orig = (SL._LATEST, SL._LOG, SL._HEARTBEAT)
        SL._LATEST = self._tmp / "latest.json"
        SL._LOG = self._tmp / "signal_log.json"
        SL._HEARTBEAT = self._tmp / "heartbeat.json"
        self._saved_sensors = list(SL._SENSORS)
        SL._SENSORS[:] = [_good_sensor]
        SVC._STALE_STREAK.clear()

    def tearDown(self) -> None:
        SL._LATEST, SL._LOG, SL._HEARTBEAT = self._orig
        SL._SENSORS[:] = self._saved_sensors
        SVC._STALE_STREAK.clear()

    def _hb(self) -> dict:
        return json.loads(SL._HEARTBEAT.read_text())

    def _tick(self, *, react=None, reconcile=None) -> str:
        """Run one tick with stage 2/3 optionally replaced; return everything printed."""
        react = react if react is not None else (lambda *a, **k: None)
        reconcile = reconcile if reconcile is not None else (lambda *a, **k: [])
        buf = io.StringIO()
        with mock.patch.object(SVC.A, "react_and_apply", react), \
             mock.patch.object(SVC, "reconcile_and_persist", reconcile), \
             redirect_stdout(buf):
            SVC.tick({}, 1000)
        return buf.getvalue()


class TestStageFailureIsVisible(_TickBase):
    """Defect 1 — a failing stage must reach the log, flushed, and say WHICH stage died."""

    def test_react_failure_is_printed(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("ladder exploded")
        out = self._tick(react=_boom)
        self.assertIn("react", out)
        self.assertIn("ladder exploded", out)

    def test_reconcile_failure_is_printed(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("self-clear exploded")
        out = self._tick(reconcile=_boom)
        self.assertIn("reconcile", out)
        self.assertIn("self-clear exploded", out)

    def test_failure_names_the_stage_not_a_generic_message(self) -> None:
        # the old message was one opaque "tick failed (...)" for three different breakages
        def _boom(*a, **k):
            raise RuntimeError("x")
        self.assertIn("stage react failed", self._tick(react=_boom))
        self.assertIn("stage reconcile failed", self._tick(reconcile=_boom))

    def test_report_flushes_stdout(self) -> None:
        """The load-bearing bit: without flush the message never reaches a redirected log."""
        flushed: list = []

        class _Sink(io.StringIO):
            def flush(self):  # noqa: D102
                flushed.append(True)
                return super().flush()

        sink = _Sink()
        with redirect_stdout(sink):
            SVC._report_stage_failure("react", RuntimeError("boom"))
        self.assertTrue(flushed, "failure report must flush; a buffered report is a lost report")


class TestHeartbeatDoesNotOverclaim(_TickBase):
    """Defect 2 — `alive` must describe every stage, not just the one that stamps it."""

    def test_react_failure_makes_heartbeat_not_alive(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("boom")
        self._tick(react=_boom)
        hb = self._hb()
        self.assertFalse(hb["alive"])
        self.assertEqual(hb["failed_stages"], ["react"])
        self.assertIn("boom", hb["last_error"])

    def test_reconcile_failure_makes_heartbeat_not_alive(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("boom")
        self._tick(reconcile=_boom)
        self.assertFalse(self._hb()["alive"])
        self.assertEqual(self._hb()["failed_stages"], ["reconcile"])

    def test_both_stages_failing_are_both_recorded(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("boom")
        self._tick(react=_boom, reconcile=_boom)
        self.assertEqual(self._hb()["failed_stages"], ["react", "reconcile"])
        self.assertEqual(self._hb()["stages_ok"], ["sense"])

    def test_heartbeat_ts_still_reflects_sensing(self) -> None:
        """Freshness must keep its old meaning — only the CLAIM changed, not the clock."""
        def _boom(*a, **k):
            raise RuntimeError("boom")
        self._tick(react=_boom)
        self.assertEqual(self._hb()["ts"], 1000)
        self.assertEqual(SL.heartbeat_age_sec(now_ts=1010), 10.0)


class TestServiceLoopOverclaimRepro(_TickBase):
    """The decisive repro, at the level where the real system swallows the failure.

    The other tests call ``tick`` directly, so on pre-fix code the stage exception simply escapes
    and they go red by exception — true, but it does NOT show the lie. In production the exception
    is caught by ``main()``'s ``try/except`` and the loop sleeps on. What is left on disk is the
    whole operator-visible truth, so that is what this asserts: run one loop body exactly as
    ``main()`` does, then read the heartbeat file.

    Pre-fix that file reads ``{"ts": 1000, "sensors": 1, "alive": true}`` — a fresh, unqualified
    claim of liveness written after stage 1, while the reaction ladder died in stage 2 and the log
    line about it was buffered into oblivion.
    """

    def _run_loop_body(self, *, react=None, reconcile=None) -> str:
        """One iteration of main()'s body: call tick, swallow whatever escapes — never re-raise."""
        react = react if react is not None else (lambda *a, **k: None)
        reconcile = reconcile if reconcile is not None else (lambda *a, **k: [])
        buf = io.StringIO()
        with mock.patch.object(SVC.A, "react_and_apply", react), \
             mock.patch.object(SVC, "reconcile_and_persist", reconcile), \
             redirect_stdout(buf):
            try:
                SVC.tick({}, 1000)
            except Exception:  # noqa: BLE001 — exactly what main() does
                pass
        return buf.getvalue()

    def test_disk_does_not_claim_alive_after_react_died(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("ladder died")
        self._run_loop_body(react=_boom)
        self.assertFalse(self._hb()["alive"],
                         "heartbeat claimed liveness for a tick whose reaction stage never ran")

    def test_disk_does_not_claim_alive_after_selfclear_died(self) -> None:
        def _boom(*a, **k):
            raise RuntimeError("self-clear died")
        self._run_loop_body(reconcile=_boom)
        self.assertFalse(self._hb()["alive"])

    def test_operator_gets_a_log_line_from_the_loop(self) -> None:
        """Pre-fix the only trace was an unflushed print; post-fix the loop body emits it itself."""
        def _boom(*a, **k):
            raise RuntimeError("ladder died")
        self.assertIn("ladder died", self._run_loop_body(react=_boom))


class TestStageIsolation(_TickBase):
    """A dead reaction ladder must not also kill the self-clear — that combination is the
    2026-07-26→29 incident shape: the book sat DEFENSIVE (all targets clamped to 0) precisely
    because the only path back to NORMAL never ran."""

    def test_reconcile_runs_even_when_react_dies(self) -> None:
        calls: list = []

        def _boom(*a, **k):
            raise RuntimeError("boom")

        def _recon(*a, **k):
            calls.append(True)
            return []

        self._tick(react=_boom, reconcile=_recon)
        self.assertEqual(len(calls), 1, "self-clear must still run after the reaction stage dies")


class TestHealthyTickUnchanged(_TickBase):
    """Positive controls — the fix must not make a healthy service look degraded."""

    def test_healthy_tick_is_alive_with_all_stages(self) -> None:
        out = self._tick()
        hb = self._hb()
        self.assertTrue(hb["alive"])
        self.assertEqual(hb["failed_stages"], [])
        self.assertEqual(hb["stages_ok"], ["sense", "react", "reconcile"])
        self.assertIsNone(hb["last_error"])
        self.assertEqual(out, "", "a healthy tick must stay silent")

    def test_healthy_tick_returns_signals(self) -> None:
        with mock.patch.object(SVC.A, "react_and_apply", lambda *a, **k: None), \
             mock.patch.object(SVC, "reconcile_and_persist", lambda *a, **k: []):
            self.assertEqual(len(SVC.tick({}, 1000)), 1)

    def test_run_tick_alone_still_writes_the_old_shape(self) -> None:
        """`run_tick` is used outside the service; its heartbeat bytes must not change."""
        SL.run_tick([_good_sensor], {}, now_ts=1000)
        self.assertEqual(self._hb(), {"ts": 1000, "sensors": 1, "alive": True})


class TestStageHealthIsUncheckedNotFailed(unittest.TestCase):
    """A pre-fix heartbeat (the live service keeps writing one until its next restart, and
    restarts are owner-gated) must read as UNCHECKED. Escalating on a missing key would invent a
    failure nobody measured — the same lie as a fabricated OK, just louder."""

    def test_old_format_heartbeat_is_unmeasured(self) -> None:
        h = SL.stage_health({"ts": 1000, "sensors": 3, "alive": True})
        self.assertFalse(h["measured"])
        self.assertIsNone(h["alive"])
        self.assertEqual(h["failed_stages"], [])

    def test_missing_heartbeat_is_unmeasured(self) -> None:
        h = SL.stage_health(None)
        self.assertFalse(h["measured"])
        self.assertIsNone(h["alive"])

    def test_new_format_clean_is_measured_alive(self) -> None:
        h = SL.stage_health({"ts": 1, "failed_stages": [], "stages_ok": ["sense", "react"]})
        self.assertTrue(h["measured"])
        self.assertTrue(h["alive"])

    def test_new_format_failed_is_measured_not_alive(self) -> None:
        h = SL.stage_health({"ts": 1, "failed_stages": ["react"]})
        self.assertTrue(h["measured"])
        self.assertFalse(h["alive"])
        self.assertEqual(h["failed_stages"], ["react"])


class TestApiSurfaceReflectsStages(unittest.TestCase):
    """The twin one floor up: /api/rtmr/status computed `alive` from freshness ALONE, so it
    reported a healthy service while stages 2/3 failed on every tick."""

    def _status(self, hb: dict) -> dict:
        from spa_core.api.routers import rtmr

        def _fake_read(path, default):
            if path.name == "sense_heartbeat.json":
                return hb
            return default

        with mock.patch.object(rtmr, "_read", _fake_read), \
             mock.patch("time.time", lambda: 1000.0):
            return rtmr.rtmr_status()

    def test_fresh_but_failed_stage_is_not_alive(self) -> None:
        # `alive` FIRST: on pre-fix code this is the behavioural miss (freshness alone → alive),
        # and asserting a new key before it would hide that behind a KeyError.
        s = self._status({"ts": 1000, "failed_stages": ["reconcile"]})
        self.assertFalse(s["alive"])
        self.assertTrue(s["heartbeat_fresh"])       # freshness alone said "alive" before
        self.assertEqual(s["failed_stages"], ["reconcile"])
        self.assertTrue(s["stages_measured"])

    def test_fresh_and_clean_is_alive(self) -> None:
        s = self._status({"ts": 1000, "failed_stages": []})
        self.assertTrue(s["alive"])

    def test_old_format_heartbeat_still_reads_alive_but_flags_unmeasured(self) -> None:
        # no false alarm for the running service that predates stage reporting
        s = self._status({"ts": 1000, "alive": True})
        self.assertTrue(s["alive"])
        self.assertFalse(s["stages_measured"])

    def test_stale_heartbeat_is_not_alive(self) -> None:
        s = self._status({"ts": 1, "failed_stages": []})
        self.assertFalse(s["alive"])
        self.assertFalse(s["heartbeat_fresh"])


if __name__ == "__main__":
    unittest.main()

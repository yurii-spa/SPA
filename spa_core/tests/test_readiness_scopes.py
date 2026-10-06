"""Tests for spa_core.studio_os.readiness_scopes (ADR-580 §C3, RM-TRUTH-01 workstream W6).

Every test builds an isolated temp ``data/`` directory; nothing in the real repo is read or
written. ``now`` is always injected explicitly (deployment.md: time is an input, never the
wall clock) so these tests cannot flake on the calendar.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.studio_os.readiness_scopes import SCOPES, scoped_readiness

# FROZEN-DATE-OK: injected-clock — every call below passes now=NOW to
# scoped_readiness(), and every fixture stamp is _iso(NOW ± a timedelta), so both
# sides of every staleness comparison are pinned to the same anchor. The two
# literals NOT derived from NOW ("2041-11-23T19:53:29+00:00" — the INC-1 replay —
# and "2026-10-02" in the track_snapshot fixture) sit inside dict payloads scoped_
# readiness compares only against the injected NOW, never against the real wall
# clock; 2041 stays "far future" relative to NOW for the lifetime of this suite.
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class _Harness(unittest.TestCase):
    def _tmp(self) -> Path:
        """A fresh ``<unique_root>/data`` directory — never ``<unique_root>`` itself.

        ``_public_surface()`` resolves the repo root as ``data_dir.resolve().parent``. A
        bare ``tempfile.mkdtemp()`` result IS already unique, but its OWN parent is the
        shared system temp root (``/tmp`` on macOS) — identical across every test in the
        process. Using that bare dir as ``data_dir`` would make ``data_dir.parent`` the
        shared ``/tmp``, so one test's ``landing/`` fixture leaks into every other test
        whose ``data_dir`` also happens to sit directly under ``/tmp`` (measured: this
        cross-test collision was real, not hypothetical). Nesting ``data/`` under its own
        unique root fixes the parent too, and ``addCleanup`` removes the WHOLE root — so a
        ``landing/`` written next to ``data/`` is cleaned up with it, not leaked.
        """
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        data_dir = root / "data"
        data_dir.mkdir()
        return data_dir

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _by_scope(items: list[dict], scope: str) -> dict:
        for it in items:
            if it["scope"] == scope:
                return it
        raise AssertionError(f"scope {scope} missing from scoped_readiness() output")


class TestShapeAndNoRollup(_Harness):
    def test_exactly_six_scopes_no_aggregate(self):
        """ADR-580 §C3: no 'overall green'. Exactly the six named scopes, nothing extra."""
        data_dir = self._tmp()
        items = scoped_readiness(data_dir, now=NOW)
        self.assertEqual(len(items), 6)
        self.assertEqual({it["scope"] for it in items}, set(SCOPES))
        for it in items:
            self.assertEqual(
                set(it.keys()),
                {"scope", "status", "as_of", "source", "freshness", "blocking_effect", "reason"},
            )

    def test_missing_everything_is_unknown_never_ok_or_ready(self):
        """Empty data/ directory: every scope must say UNKNOWN (inv. #17), never a healthy word."""
        data_dir = self._tmp()
        items = scoped_readiness(data_dir, now=NOW)
        for it in items:
            if it["scope"] == "OWNER_CONTROL_HEALTH":
                # beacon absent -> UNKNOWN, same rule, checked separately below for clarity.
                pass
            self.assertNotIn(it["status"], ("OK", "READY"), it)
            self.assertEqual(it["status"], "UNKNOWN", it)


class TestInvestmentEngineReadiness(_Harness):
    def test_ready_for_live_false_is_not_ready(self):
        data_dir = self._tmp()
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW - timedelta(hours=1)),
            "ready_for_live": False,
            "live_blockers": ["custody/MPC not connected", "external audit pending"],
        })
        self._write(data_dir / "owner_blockers.json", {
            "generated_at": _iso(NOW - timedelta(hours=1)),
            "gates": [{"id": "custody", "status": "open"}, {"id": "audit", "status": "open"}],
        })
        self._write(data_dir / "golive_status.json", {"passed": 29, "total": 29})
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertEqual(item["status"], "NOT_READY")
        self.assertIn("29/29", item["reason"])
        self.assertIn("ready_for_live=false", item["reason"])

    def test_ready_for_live_true_is_ready(self):
        data_dir = self._tmp()
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW - timedelta(hours=1)),
            "ready_for_live": True,
            "live_blockers": [],
        })
        self._write(data_dir / "owner_blockers.json", {
            "generated_at": _iso(NOW - timedelta(hours=1)), "gates": [],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertEqual(item["status"], "READY")

    def test_ready_for_live_true_with_open_owner_blockers_is_not_ready(self):
        """F11 (integration review, 2026-10-05): the module's own docstring states
        the contract as ready_for_live ∧ owner_blockers (no open gates). Before this
        fix, READY was driven by ready_for_live ALONE — open owner_blockers gates
        were NAMED in `reason` but did not block the status itself."""
        data_dir = self._tmp()
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW - timedelta(hours=1)),
            "ready_for_live": True,
            "live_blockers": [],
        })
        self._write(data_dir / "owner_blockers.json", {
            "generated_at": _iso(NOW - timedelta(hours=1)),
            "gates": [{"id": "legal_review", "status": "open"}],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertEqual(item["status"], "NOT_READY")
        self.assertIn("legal_review", item["reason"])

    def test_missing_execution_readiness_is_unknown_not_not_ready(self):
        data_dir = self._tmp()
        self._write(data_dir / "golive_status.json", {"passed": 29, "total": 29})
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertEqual(item["status"], "UNKNOWN")

    def test_stale_execution_readiness_is_unknown_not_whatever_it_said(self):
        """A file older than its own SLO is UNKNOWN even though its content says ready=True —
        'measured once, long ago' must not collapse into 'measured, and healthy'."""
        data_dir = self._tmp()
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW - timedelta(hours=400)),  # far beyond the 26h fallback SLO
            "ready_for_live": True,
            "live_blockers": [],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertEqual(item["status"], "UNKNOWN")
        self.assertTrue(item["freshness"]["stale"])

    def test_future_timestamp_is_corrupt_the_inc1_shape(self):
        """ADR-580 §C3: generated_at > now + skew => CORRUPT. Replays INC-1 (2041 stamp)."""
        data_dir = self._tmp()
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW + timedelta(days=5000)),  # the 2041-style future leak
            "ready_for_live": True,
            "live_blockers": [],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertEqual(item["status"], "CORRUPT")

    def test_within_skew_tolerance_is_not_corrupt(self):
        """A few minutes of clock skew (<FUTURE_SKEW_MINUTES) must not false-positive CORRUPT."""
        data_dir = self._tmp()
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW + timedelta(minutes=2)),
            "ready_for_live": False,
            "live_blockers": ["x"],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "INVESTMENT_ENGINE_READINESS")
        self.assertNotEqual(item["status"], "CORRUPT")


class TestStudioOsHealth(_Harness):
    def test_critical_agent_health_maps_to_critical(self):
        data_dir = self._tmp()
        self._write(data_dir / "agent_health.json", {
            "timestamp": _iso(NOW - timedelta(minutes=10)),
            "overall_status": "CRITICAL",
            "healthy_count": 84, "warning_count": 4, "critical_count": 1, "total_agents": 89,
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "STUDIO_OS_HEALTH")
        self.assertEqual(item["status"], "CRITICAL")

    def test_missing_agent_health_is_unknown(self):
        data_dir = self._tmp()
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "STUDIO_OS_HEALTH")
        self.assertEqual(item["status"], "UNKNOWN")


class TestScopeIndependence(_Harness):
    """ADR-580 §C3: a fleet CRITICAL must not move investment readiness, and vice versa —
    this is the exact bug the six-scope design replaces (one rollup overwriting another)."""

    def _scene(self, data_dir: Path, *, agent_critical: bool, ready_for_live: bool) -> None:
        self._write(data_dir / "agent_health.json", {
            "timestamp": _iso(NOW - timedelta(minutes=5)),
            "overall_status": "CRITICAL" if agent_critical else "OK",
            "healthy_count": 88 if not agent_critical else 84,
            "warning_count": 0, "critical_count": 1 if agent_critical else 0,
            "total_agents": 89,
        })
        self._write(data_dir / "execution_readiness.json", {
            "audited_at": _iso(NOW - timedelta(minutes=5)),
            "ready_for_live": ready_for_live,
            "live_blockers": [] if ready_for_live else ["custody/MPC not connected"],
        })
        self._write(data_dir / "owner_blockers.json", {
            "generated_at": _iso(NOW - timedelta(minutes=5)), "gates": [],
        })

    def test_agent_critical_does_not_flip_investment_readiness(self):
        data_dir = self._tmp()
        self._scene(data_dir, agent_critical=True, ready_for_live=True)
        items = {it["scope"]: it for it in scoped_readiness(data_dir, now=NOW)}
        self.assertEqual(items["STUDIO_OS_HEALTH"]["status"], "CRITICAL")
        self.assertEqual(items["INVESTMENT_ENGINE_READINESS"]["status"], "READY")

    def test_investment_not_ready_does_not_flip_agent_health(self):
        data_dir = self._tmp()
        self._scene(data_dir, agent_critical=False, ready_for_live=False)
        items = {it["scope"]: it for it in scoped_readiness(data_dir, now=NOW)}
        self.assertEqual(items["INVESTMENT_ENGINE_READINESS"]["status"], "NOT_READY")
        self.assertEqual(items["STUDIO_OS_HEALTH"]["status"], "OK")


class TestPublicationHealth(_Harness):
    def test_publisher_stuck_is_critical_even_if_ok_true(self):
        data_dir = self._tmp()
        self._write(data_dir / "site_freshness_report.json", {
            "ts": _iso(NOW - timedelta(hours=1)),
            "ok": True,
            "fails": [{"code": "PUBLISHER_STUCK", "detail": "stuck", "severity": "WARN"}],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "PUBLICATION_HEALTH")
        self.assertEqual(item["status"], "CRITICAL")

    def test_ok_true_no_fails_is_ok(self):
        data_dir = self._tmp()
        self._write(data_dir / "site_freshness_report.json", {
            "ts": _iso(NOW - timedelta(hours=1)), "ok": True, "fails": [],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "PUBLICATION_HEALTH")
        self.assertEqual(item["status"], "OK")


class TestOwnerControlHealth(_Harness):
    def test_fresh_beacon_is_ok(self):
        data_dir = self._tmp()
        self._write(data_dir / "telegram_bot_capabilities.json", {
            "updated_at": _iso(NOW - timedelta(seconds=30)),
            "capabilities": ["alert_actions"],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "OWNER_CONTROL_HEALTH")
        self.assertEqual(item["status"], "OK")

    def test_stale_beacon_is_degraded_not_ok(self):
        data_dir = self._tmp()
        self._write(data_dir / "telegram_bot_capabilities.json", {
            "updated_at": _iso(NOW - timedelta(hours=2)),
            "capabilities": ["alert_actions"],
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "OWNER_CONTROL_HEALTH")
        self.assertEqual(item["status"], "DEGRADED")

    def test_missing_beacon_is_unknown(self):
        data_dir = self._tmp()
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "OWNER_CONTROL_HEALTH")
        self.assertEqual(item["status"], "UNKNOWN")

    def test_inc1_future_stamp_on_owner_decision_pending_is_corrupt(self):
        """Replays INC-1: owner_decision_pending.json generated_at = 2041-11-23."""
        data_dir = self._tmp()
        self._write(data_dir / "telegram_bot_capabilities.json", {
            "updated_at": _iso(NOW - timedelta(seconds=30)), "capabilities": ["alert_actions"],
        })
        self._write(data_dir / "owner_decision_pending.json", {
            "generated_at": "2041-11-23T19:53:29+00:00",
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "OWNER_CONTROL_HEALTH")
        self.assertEqual(item["status"], "CORRUPT")


class TestPublicSurface(_Harness):
    def test_missing_landing_data_is_unknown(self):
        data_dir = self._tmp()
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "PUBLIC_SURFACE")
        self.assertEqual(item["status"], "UNKNOWN")

    def test_present_snapshot_is_reported_verbatim(self):
        data_dir = self._tmp()
        snap_path = data_dir.parent / "landing" / "src" / "data" / "track_snapshot.json"
        self._write(snap_path, {
            "gates_passed": 29, "gates_total": 29, "as_of": "2026-10-02",
        })
        item = self._by_scope(scoped_readiness(data_dir, now=NOW), "PUBLIC_SURFACE")
        self.assertEqual(item["status"], "OK")
        self.assertIn("29/29", item["reason"])
        self.assertIn("НЕ ready_for_live", item["reason"])


if __name__ == "__main__":
    unittest.main()

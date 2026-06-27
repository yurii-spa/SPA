"""End-to-end EVALUATION-PATH tests for the SPA kill-switch (2-day sprint, Task 6).

These tests pin the kill-switch *evaluation path* end-to-end AT THE CURRENT
THRESHOLDS — they deliberately do NOT change any threshold value (the 15%
drawdown / 5 red-flags / -1.0 Sharpe constants are owner-gated). They assert the
full chain a real crisis travels:

    equity/flag/file signal
        → check_*_trigger fires
        → is_kill_switch_active() == (True, reason)        # the (bool, reason) contract
        → run_kill_switch_check() → all-cash allocation     # the "close all" intent
        → threat_reactor (intraday) activates the switch

Covered (one cohesive eval-path suite, complementing the unit tests in
spa_core/tests/test_kill_switch.py):

  1. Drawdown → kill → all-cash   — a real >threshold drawdown series fires the
     drawdown trigger, surfaces through is_kill_switch_active as (True, reason)
     AND through run_kill_switch_check as a {cash: 1.0, every protocol: 0.0}
     allocation (the documented close-all intent).
  2. File lifecycle              — kill_switch_active.json absent → (False, …);
     present → (True, reason); active=False → (False, …); the (bool, reason)
     tuple contract is pinned (callers unpack it).
  3. threat_reactor held-scoping — a CRITICAL red flag on a HELD protocol makes
     the intraday reactor activate the switch; the same flag on an EXTERNAL /
     unheld protocol does NOT (the N1 held-protocol scoping).
  4. Evidenced-bar drawdown      — drawdown is computed over EVIDENCED bars only;
     a warmup/backfill bar cannot fabricate a kill (P5-4/T10).
  5. Edge cases                  — empty / single-bar series → no spurious kill;
     a non-finite (NaN/Inf) bar fails CLOSED (P5-1) and never fabricates or masks
     a kill; the kill persists until explicitly cleared.

Deterministic, stdlib-only.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

# ── Ensure repo root on sys.path ──────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.kill_switch import (  # noqa: E402
    DRAWDOWN_THRESHOLD_PCT,
    KillSwitchChecker,
    run_kill_switch_check,
)
from spa_core.paper_trading.track_evidence import PAPER_REAL_START  # noqa: E402


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _evidenced_curve(peak: float, drawdown_pct: float, days: int = 10) -> list[dict]:
    """A flat-at-`peak` evidenced series ending with a single `drawdown_pct` drop.

    Every bar is post-anchor + source=cycle + evidenced=True so it counts as a
    REAL evidenced bar (the drawdown trigger operates strictly over the
    evidenced series).
    """
    bars: list[dict] = []
    for i in range(days - 1):
        d = PAPER_REAL_START + timedelta(days=i)
        bars.append({
            "date": d.isoformat(),
            "open_equity": round(peak, 2),
            "close_equity": round(peak, 2),
            "source": "cycle",
            "evidenced": True,
        })
    final = round(peak * (1.0 - drawdown_pct / 100.0), 2)
    bars.append({
        "date": (PAPER_REAL_START + timedelta(days=days - 1)).isoformat(),
        "open_equity": round(peak, 2),
        "close_equity": final,
        "source": "cycle",
        "evidenced": True,
    })
    return bars


# ── (1) drawdown → kill → all-cash, end-to-end ────────────────────────────────


class TestDrawdownToKillToAllCash(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_evalpath_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_real_drawdown_propagates_trigger_to_active_to_allcash(self) -> None:
        """>threshold drawdown → check_drawdown → is_kill_switch_active → all-cash."""
        curve = _evidenced_curve(100_000.0, drawdown_pct=16.0, days=12)

        # Stage 1: the trigger itself fires (current threshold).
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"drawdown trigger must fire: {reason}")
        self.assertIn("drawdown", reason.lower())

        # Stage 2: it surfaces through is_kill_switch_active as (True, reason).
        active, active_reason = self.checker.is_kill_switch_active(equity_curve=curve)
        self.assertIsInstance(active, bool)
        self.assertTrue(active, f"is_kill_switch_active must be True: {active_reason}")
        self.assertIn("drawdown", active_reason.lower())

        # Stage 3: run_kill_switch_check yields the documented close-all intent.
        status = run_kill_switch_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertTrue(status["triggered"])
        alloc = status["allocation"]
        self.assertEqual(alloc.get("cash"), 1.0, "cash must be 1.0 (all-cash)")
        protocols = [k for k in alloc if k != "cash"]
        self.assertTrue(protocols, "all-cash allocation must enumerate protocols")
        for p in protocols:
            self.assertEqual(alloc[p], 0.0, f"{p} must be flattened to 0.0")
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=9)

    def test_below_threshold_no_kill_no_allcash(self) -> None:
        """14% drawdown (< 15% current threshold) → no kill, empty allocation."""
        curve = _evidenced_curve(100_000.0, drawdown_pct=14.0, days=12)
        active, reason = self.checker.is_kill_switch_active(equity_curve=curve)
        self.assertFalse(active, f"14% must not trigger: {reason}")
        status = run_kill_switch_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertFalse(status["triggered"])
        self.assertEqual(status["allocation"], {})


# ── (2) file lifecycle + (bool, reason) contract ──────────────────────────────


class TestKillSwitchFileLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_lifecycle_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)
        self.active_path = self.data_dir / "kill_switch_active.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _assert_tuple(self, res) -> tuple:
        self.assertIsInstance(res, tuple, "must return a (bool, reason) tuple")
        self.assertEqual(len(res), 2, "tuple must be exactly (bool, reason)")
        active, reason = res
        self.assertIsInstance(active, bool)
        self.assertIsInstance(reason, str)
        return active, reason

    def test_absent_file_inactive(self) -> None:
        """File absent → is_kill_switch_active = (False, …)."""
        self.assertFalse(self.active_path.exists())
        active, _ = self._assert_tuple(self.checker.is_kill_switch_active(equity_curve=[]))
        self.assertFalse(active)

    def test_present_file_active(self) -> None:
        """File present → (True, reason carrying the manual reason)."""
        _write_json(self.active_path, {"reason": "operator stop"})
        active, reason = self._assert_tuple(
            self.checker.is_kill_switch_active(equity_curve=[])
        )
        self.assertTrue(active)
        self.assertIn("operator stop", reason)

    def test_present_but_active_false_is_inactive(self) -> None:
        """File present with active=False (overwrite-style resume) → (False, …)."""
        _write_json(self.active_path, {"active": False, "reason": "resumed"})
        active, _ = self._assert_tuple(self.checker.is_kill_switch_active(equity_curve=[]))
        self.assertFalse(active, "active=False must read as inactive")

    def test_activate_then_persists_until_cleared(self) -> None:
        """activate → file present → stays active across re-evaluations → deactivate clears."""
        self.checker.activate_kill_switch("eval-path persistence test")
        self.assertTrue(self.active_path.exists())

        # Persists across repeated checks (no auto-deactivation), even with a
        # perfectly healthy equity curve present.
        healthy = _evidenced_curve(100_000.0, drawdown_pct=0.0, days=10)
        for _ in range(3):
            active, _ = self.checker.is_kill_switch_active(equity_curve=healthy)
            self.assertTrue(active, "kill must persist until explicitly cleared")

        self.checker.deactivate_kill_switch()
        self.assertFalse(self.active_path.exists())
        active, _ = self.checker.is_kill_switch_active(equity_curve=healthy)
        self.assertFalse(active, "after deactivate, switch is clear")

    def test_run_check_does_not_clear_active_when_no_trigger(self) -> None:
        """A previously-set manual kill is NOT auto-deactivated by a clean cycle."""
        _write_json(self.active_path, {"reason": "manual"})
        status = run_kill_switch_check(
            equity_curve=_evidenced_curve(100_000.0, 0.0, 10), data_dir=self.data_dir
        )
        self.assertTrue(status["triggered"], "manual file must keep firing")
        self.assertTrue(self.active_path.exists())


# ── (3) threat_reactor intraday held-protocol scoping ─────────────────────────


class TestThreatReactorHeldScoping(unittest.TestCase):
    """The intraday reactor activates the switch ONLY for CRITICAL flags on HELD
    protocols (N1 scoping); external / advisory flags do not."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_reactor_")
        self.data_dir = Path(self._tmp.name)
        # threat_reactor binds module-level _DATA / _STATUS at import; repoint them.
        import spa_core.monitoring.threat_reactor as tr
        self._tr = tr
        self._orig_data = tr._DATA
        self._orig_status = tr._STATUS
        tr._DATA = self.data_dir
        tr._STATUS = self.data_dir / "threat_reactor_status.json"

    def tearDown(self) -> None:
        self._tr._DATA = self._orig_data
        self._tr._STATUS = self._orig_status
        self._tmp.cleanup()

    def _hold(self, *protocols: str) -> None:
        _write_json(self.data_dir / "current_positions.json",
                    {"positions": {p: 10_000.0 for p in protocols}})

    def _critical_flag(self, protocol: str) -> None:
        _write_json(self.data_dir / "red_flags.json", {
            "fallback_used": False,
            "sources": ["defillama"],
            "red_flags": [
                {"protocol": protocol, "severity": "CRITICAL", "category": "depeg",
                 "source": "defillama"},
            ],
        })

    def test_critical_on_held_detected(self) -> None:
        """A CRITICAL flag on a HELD protocol is detected as a threat."""
        self._hold("aave_v3")
        self._critical_flag("aave_v3")
        threats = self._tr._detect_threats()
        self.assertTrue(threats, "CRITICAL-on-held must be detected")
        self.assertTrue(any("aave_v3" in t.lower() for t in threats))

    def test_critical_on_external_not_detected(self) -> None:
        """A CRITICAL flag on an UNHELD/external protocol is NOT a threat."""
        self._hold("aave_v3")            # we hold aave, not pendle
        self._critical_flag("pendle_pt")
        threats = self._tr._detect_threats()
        self.assertFalse(
            any("pendle" in t.lower() for t in threats),
            f"external-protocol flag must not be a threat: {threats}",
        )

    def test_reactor_activates_kill_switch_for_held_threat(self) -> None:
        """End-to-end intraday: held CRITICAL flag → reactor ACTIVATES the switch."""
        self._hold("aave_v3")
        self._critical_flag("aave_v3")
        # Avoid the launchctl kickstart side-effect in CI/sandbox.
        self._tr._kickstart_cycle = lambda: None  # type: ignore[assignment]
        report = self._tr.run_reactor(dry_run=False)
        self.assertTrue(report["acted"], f"reactor must act: {report}")
        self.assertFalse(report["activation_failed"])
        # The authoritative kill-switch API now reads ACTIVE.
        active, _ = KillSwitchChecker(data_dir=self.data_dir).is_kill_switch_active(
            equity_curve=[]
        )
        self.assertTrue(active, "switch must be active after the reactor fires")

    def test_reactor_noop_for_external_threat(self) -> None:
        """External CRITICAL flag → reactor does NOT activate the switch."""
        self._hold("aave_v3")
        self._critical_flag("pendle_pt")
        self._tr._kickstart_cycle = lambda: None  # type: ignore[assignment]
        report = self._tr.run_reactor(dry_run=False)
        self.assertFalse(report["acted"], f"reactor must not act on external flag: {report}")
        active, _ = KillSwitchChecker(data_dir=self.data_dir).is_kill_switch_active(
            equity_curve=[]
        )
        self.assertFalse(active)

    def test_reactor_idempotent_when_already_active(self) -> None:
        """Reactor does not re-fire while the switch is already active."""
        self._hold("aave_v3")
        self._critical_flag("aave_v3")
        _write_json(self.data_dir / "kill_switch_active.json",
                    {"active": True, "reason": "already on"})
        self._tr._kickstart_cycle = lambda: None  # type: ignore[assignment]
        report = self._tr.run_reactor(dry_run=False)
        self.assertTrue(report["kill_switch_already_active"])
        self.assertFalse(report["acted"], "must not re-fire while already active")


# ── (4) evidenced-bar drawdown (warmup can't fabricate a kill) ─────────────────


class TestEvidencedBarDrawdown(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_evidenced_")
        self.checker = KillSwitchChecker(data_dir=self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_inflated_warmup_peak_does_not_fabricate_kill(self) -> None:
        """Pre-anchor $200k warmup + flat real $100k → 0% real drawdown → no kill."""
        curve = [{"date": "2026-05-01", "close_equity": 200_000.0, "is_warmup": True}]
        for i in range(6):
            curve.append({"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"warmup peak must not fabricate drawdown: {reason}")

    def test_backfill_bar_excluded_from_drawdown(self) -> None:
        """An explicitly non-evidenced backfill high is excluded from the window."""
        curve = [
            {"date": "2026-06-10", "close_equity": 200_000.0,
             "source": "backfill", "evidenced": False},
        ]
        for i in range(5):
            curve.append({"date": f"2026-06-{11 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"backfill bar must not count toward drawdown: {reason}")

    def test_real_drawdown_on_evidenced_bars_fires(self) -> None:
        """A genuine >threshold drop on EVIDENCED bars still fires (no over-suppression)."""
        curve = []
        for i in range(8):
            curve.append({"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        curve.append({"date": "2026-06-20", "close_equity": 82_000.0,
                      "source": "cycle", "evidenced": True})  # -18%
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"real -18% drawdown must fire: {reason}")


# ── (5) edge cases + non-finite fail-closed (P5-1) ────────────────────────────


class TestKillSwitchEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_edges_")
        self.checker = KillSwitchChecker(data_dir=self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_series_no_kill(self) -> None:
        triggered, _ = self.checker.check_drawdown_trigger([])
        self.assertFalse(triggered)

    def test_single_bar_no_kill(self) -> None:
        curve = [{"date": "2026-06-12", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True}]
        triggered, _ = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, "a single bar has no peak-to-trough → no kill")

    def test_nan_current_bar_fails_closed_no_fabricated_kill(self) -> None:
        """P5-1: a NaN final bar must not fabricate a kill (dropped as no-data)."""
        curve = [{"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True} for i in range(5)]
        curve.append({"date": "2026-06-20", "close_equity": float("nan"),
                      "source": "cycle", "evidenced": True})
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"NaN bar must not fabricate a kill: {reason}")
        self.assertNotIn("nan", reason.lower(), "reason must not leak a NaN drawdown")

    def test_inf_peak_fails_closed(self) -> None:
        """P5-1: an Inf peak must not yield a NaN-comparison spurious pass."""
        curve = [{"date": "2026-06-10", "close_equity": float("inf"),
                  "source": "cycle", "evidenced": True},
                 {"date": "2026-06-11", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True}]
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"Inf peak must fail closed: {reason}")
        self.assertNotIn("nan", reason.lower())

    def test_corrupt_bar_does_not_mask_real_drawdown(self) -> None:
        """A single Inf bar among good bars must not mask a real >threshold drop."""
        curve = [{"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True} for i in range(5)]
        curve.append({"date": "2026-06-18", "close_equity": float("inf"),
                      "source": "cycle", "evidenced": True})  # corrupt — dropped
        curve.append({"date": "2026-06-20", "close_equity": 80_000.0,
                      "source": "cycle", "evidenced": True})  # real -20%
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"real -20% must still fire past a corrupt bar: {reason}")

    def test_threshold_constant_unchanged(self) -> None:
        """OWNER-GATED: the eval path is pinned at the CURRENT threshold (15.0)."""
        self.assertEqual(DRAWDOWN_THRESHOLD_PCT, 15.0)


if __name__ == "__main__":
    unittest.main()

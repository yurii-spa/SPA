"""Two-tier drawdown kill-switch tests (ADR-034 + ADR-048, owner-approved 2026-06-27).

Pins the TWO-TIER drawdown ladder end-to-end (ADR-048: hard kill lowered 15→10,
boundary now inclusive `>=` so classifier and trigger AGREE at exactly 10.0%):

    drawdown < 5%            → TIER_NONE        (no action)
    5% ≤ drawdown < 10%      → TIER_SOFT_DERISK (halt new/increase, hold/reduce,
                                                 WARNING, NOT all-cash)
    drawdown ≥ 10%           → TIER_HARD_KILL   (all-cash liquidation; exactly
                                                 10.0% FIRES the kill)

Plus: boundaries (exactly 5%, exactly 10%), monotonicity, evidenced-bars-only
preserved, non-finite fail-closed preserved, and the SOFT gate semantics
(blocks NEW + INCREASE, allows HOLD + REDUCE; does NOT liquidate held book).

Deterministic, stdlib-only.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.kill_switch import (  # noqa: E402
    DRAWDOWN_THRESHOLD_PCT,
    SOFT_DERISK_THRESHOLD_PCT,
    TIER_HARD_KILL,
    TIER_NONE,
    TIER_SOFT_DERISK,
    KillSwitchChecker,
    drawdown_tier,
    evidenced_drawdown_pct,
    run_derisk_check,
    run_kill_switch_check,
)
from spa_core.paper_trading.cycle_gates import apply_soft_derisk_gate  # noqa: E402
from spa_core.paper_trading.track_evidence import PAPER_REAL_START  # noqa: E402


def _evidenced_curve(peak: float, drawdown_pct: float, days: int = 10) -> list[dict]:
    """Flat-at-`peak` evidenced series ending with a single `drawdown_pct` drop."""
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


# ── Constants pinned ──────────────────────────────────────────────────────────


class TestTierConstants(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(SOFT_DERISK_THRESHOLD_PCT, 5.0)
        self.assertEqual(DRAWDOWN_THRESHOLD_PCT, 10.0)  # ADR-048: 15→10
        self.assertLess(SOFT_DERISK_THRESHOLD_PCT, DRAWDOWN_THRESHOLD_PCT)


# ── drawdown_tier classification ──────────────────────────────────────────────


class TestDrawdownTier(unittest.TestCase):
    def _tier(self, dd: float) -> str:
        return drawdown_tier(_evidenced_curve(100_000.0, dd))[0]

    def test_4pct_none(self) -> None:
        self.assertEqual(self._tier(4.0), TIER_NONE)

    def test_5pct_boundary_is_soft(self) -> None:
        """Exactly 5% → SOFT (lower band is closed)."""
        self.assertEqual(self._tier(5.0), TIER_SOFT_DERISK)

    def test_mid_band_soft(self) -> None:
        for dd in (5.0, 6.5, 7.5, 9.0, 9.99):
            self.assertEqual(self._tier(dd), TIER_SOFT_DERISK, f"dd={dd}")

    def test_10pct_boundary_is_hard(self) -> None:
        """ADR-048: exactly 10% → HARD (upper band is closed, inclusive >=)."""
        self.assertEqual(self._tier(10.0), TIER_HARD_KILL)

    def test_above_10_hard(self) -> None:
        for dd in (10.0, 12.0, 15.0, 25.0, 50.0):
            self.assertEqual(self._tier(dd), TIER_HARD_KILL, f"dd={dd}")

    def test_monotone_ladder(self) -> None:
        """As drawdown rises, tier severity never decreases."""
        rank = {TIER_NONE: 0, TIER_SOFT_DERISK: 1, TIER_HARD_KILL: 2}
        prev = -1
        for dd in [0, 1, 4, 4.99, 5, 6, 9, 9.99, 10, 12, 15, 30]:
            r = rank[self._tier(float(dd))]
            self.assertGreaterEqual(r, prev, f"non-monotone at dd={dd}")
            prev = r

    def test_no_data_is_none(self) -> None:
        self.assertEqual(drawdown_tier([])[0], TIER_NONE)
        self.assertEqual(drawdown_tier([{"date": "2026-06-12",
                                         "close_equity": 100_000.0,
                                         "source": "cycle", "evidenced": True}])[0],
                         TIER_NONE)


# ── HARD tier (ADR-048): 10%+ → kill → all-cash; exactly 10% FIRES ────────────


class TestHardTier(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_tt_hard_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_12pct_hard_kill_allcash(self) -> None:
        curve = _evidenced_curve(100_000.0, 12.0, days=12)
        triggered, _ = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered)
        status = run_kill_switch_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertTrue(status["triggered"])
        self.assertEqual(status["allocation"].get("cash"), 1.0)

    def test_15pct_still_hard_kill_allcash(self) -> None:
        """The old 15% case still kills (now well above the 10% threshold)."""
        curve = _evidenced_curve(100_000.0, 15.0, days=12)
        triggered, _ = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered)
        status = run_kill_switch_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertTrue(status["triggered"])
        self.assertEqual(status["allocation"].get("cash"), 1.0)

    def test_exact_10pct_DOES_hard_kill(self) -> None:
        """ADR-048: boundary now INCLUSIVE — exactly 10% FIRES the all-cash kill
        (check_drawdown_trigger uses >= so it agrees with drawdown_tier)."""
        curve = _evidenced_curve(100_000.0, 10.0, days=12)
        triggered, _ = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered)
        status = run_kill_switch_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertTrue(status["triggered"])
        self.assertEqual(status["allocation"].get("cash"), 1.0)

    def test_9pct_no_hard_kill(self) -> None:
        curve = _evidenced_curve(100_000.0, 9.0, days=12)
        triggered, _ = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered)


# ── SOFT tier signal: 5–9.99% → de-risk, NOT all-cash (ADR-048) ───────────────


class TestSoftTierSignal(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_tt_soft_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_4pct_no_derisk(self) -> None:
        active, _ = self.checker.is_derisk_active(_evidenced_curve(100_000.0, 4.0))
        self.assertFalse(active)

    def test_soft_band_derisk_active(self) -> None:
        for dd in (5.0, 7.0, 9.0, 9.99):  # SOFT band [5,10) under ADR-048
            active, reason = self.checker.is_derisk_active(
                _evidenced_curve(100_000.0, dd)
            )
            self.assertTrue(active, f"dd={dd}: {reason}")

    def test_soft_does_not_hard_kill(self) -> None:
        """A 9% drawdown fires SOFT but NOT the all-cash hard kill."""
        curve = _evidenced_curve(100_000.0, 9.0, days=12)
        derisk, _ = self.checker.is_derisk_active(curve)
        self.assertTrue(derisk)
        kill, _ = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(kill, "soft band must not all-cash")
        status = run_kill_switch_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertFalse(status["triggered"])
        self.assertEqual(status["allocation"], {})

    def test_hard_band_excludes_soft(self) -> None:
        """At ≥10% the SOFT signal is False (hard owns the response)."""
        active, _ = self.checker.is_derisk_active(
            _evidenced_curve(100_000.0, 12.0)
        )
        self.assertFalse(active, "soft and hard tiers are mutually exclusive")

    def test_run_derisk_check_writes_status_and_edge_alert(self) -> None:
        curve = _evidenced_curve(100_000.0, 9.0, days=12)
        # First run: inactive→active edge → should_alert True.
        r1 = run_derisk_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertTrue(r1["active"])
        self.assertEqual(r1["tier"], TIER_SOFT_DERISK)
        self.assertTrue(r1["should_alert"], "first entry must edge-trigger alert")
        self.assertTrue((self.data_dir / "derisk_status.json").exists())
        # Second run while still in band → no repeat alert (edge-triggered).
        r2 = run_derisk_check(equity_curve=curve, data_dir=self.data_dir)
        self.assertTrue(r2["active"])
        self.assertFalse(r2["should_alert"], "must not flood while still active")

    def test_recovery_clears_derisk(self) -> None:
        run_derisk_check(
            equity_curve=_evidenced_curve(100_000.0, 9.0, days=12),
            data_dir=self.data_dir,
        )
        r = run_derisk_check(
            equity_curve=_evidenced_curve(100_000.0, 2.0, days=12),
            data_dir=self.data_dir,
        )
        self.assertFalse(r["active"])
        self.assertEqual(r["tier"], TIER_NONE)


# ── SOFT gate: blocks new + increase, allows hold + reduce, no liquidation ─────


class TestSoftDeriskGate(unittest.TestCase):
    def test_noop_when_inactive(self) -> None:
        target = {"aave_v3": 50_000.0, "compound_v3": 30_000.0}
        out = apply_soft_derisk_gate(
            dict(target), current_positions={"aave_v3": 40_000.0},
            derisk_active=False, notes=[],
        )
        self.assertEqual(out, target, "inactive → no-op")

    def test_blocks_new_position(self) -> None:
        """A protocol NOT currently held is forced to 0 (no NEW)."""
        out = apply_soft_derisk_gate(
            {"aave_v3": 40_000.0, "newpool": 20_000.0},
            current_positions={"aave_v3": 40_000.0},
            derisk_active=True, notes=[],
        )
        self.assertEqual(out["newpool"], 0.0, "new position blocked")

    def test_blocks_increase_caps_to_held(self) -> None:
        """An existing position cannot be INCREASED — clamped to held size."""
        out = apply_soft_derisk_gate(
            {"aave_v3": 60_000.0},
            current_positions={"aave_v3": 40_000.0},
            derisk_active=True, notes=[],
        )
        self.assertEqual(out["aave_v3"], 40_000.0, "increase clamped to held")

    def test_allows_hold(self) -> None:
        out = apply_soft_derisk_gate(
            {"aave_v3": 40_000.0},
            current_positions={"aave_v3": 40_000.0},
            derisk_active=True, notes=[],
        )
        self.assertEqual(out["aave_v3"], 40_000.0, "hold preserved")

    def test_allows_reduce(self) -> None:
        out = apply_soft_derisk_gate(
            {"aave_v3": 25_000.0},
            current_positions={"aave_v3": 40_000.0},
            derisk_active=True, notes=[],
        )
        self.assertEqual(out["aave_v3"], 25_000.0, "reduction left intact")

    def test_not_all_cash(self) -> None:
        """De-risk must NOT liquidate the held book to cash."""
        out = apply_soft_derisk_gate(
            {"aave_v3": 50_000.0, "compound_v3": 30_000.0},
            current_positions={"aave_v3": 40_000.0, "compound_v3": 30_000.0},
            derisk_active=True, notes=[],
        )
        deployed = sum(out.values())
        self.assertGreater(deployed, 0.0, "held book must NOT be liquidated")
        # held positions stay at their (capped) held size
        self.assertEqual(out["aave_v3"], 40_000.0)
        self.assertEqual(out["compound_v3"], 30_000.0)


# ── Evidenced-bars-only + non-finite fail-closed preserved for BOTH tiers ─────


class TestSafetyContractsPreserved(unittest.TestCase):
    def test_warmup_peak_does_not_fabricate_tier(self) -> None:
        """An inflated pre-anchor warmup peak must not fabricate a de-risk/kill."""
        curve = [{"date": "2026-05-01", "close_equity": 200_000.0, "is_warmup": True}]
        for i in range(6):
            curve.append({"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        self.assertEqual(drawdown_tier(curve)[0], TIER_NONE)

    def test_backfill_bar_excluded(self) -> None:
        curve = [{"date": "2026-06-10", "close_equity": 200_000.0,
                  "source": "backfill", "evidenced": False}]
        for i in range(5):
            curve.append({"date": f"2026-06-{11 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        self.assertEqual(drawdown_tier(curve)[0], TIER_NONE)

    def test_nan_bar_does_not_fabricate_tier(self) -> None:
        """P5-1 preserved: a NaN bar is dropped as no-data (never fabricates a
        more severe tier). Remaining flat bars → 0% drawdown → NONE."""
        curve = [{"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True} for i in range(5)]
        curve.append({"date": "2026-06-20", "close_equity": float("nan"),
                      "source": "cycle", "evidenced": True})
        dd = evidenced_drawdown_pct(curve)
        # NaN dropped → drawdown computed over the surviving flat bars = 0%.
        self.assertEqual(dd, 0.0)
        self.assertEqual(drawdown_tier(curve)[0], TIER_NONE)

    def test_inf_peak_does_not_fabricate_tier(self) -> None:
        """P5-1 preserved: an Inf bar dropped → only one usable bar → not
        computable → fail-closed to NONE (no fabricated kill/de-risk)."""
        curve = [{"date": "2026-06-10", "close_equity": float("inf"),
                  "source": "cycle", "evidenced": True},
                 {"date": "2026-06-11", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True}]
        # The Inf is dropped as no-data → only one usable bar → not computable.
        self.assertIsNone(evidenced_drawdown_pct(curve))
        self.assertEqual(drawdown_tier(curve)[0], TIER_NONE)

    def test_nan_does_not_mask_real_hard_drawdown(self) -> None:
        """A corrupt bar must not MASK a real >15% drop (drops corrupt, keeps real)."""
        curve = [{"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True} for i in range(4)]
        curve.append({"date": "2026-06-18", "close_equity": float("inf"),
                      "source": "cycle", "evidenced": True})  # corrupt → dropped
        curve.append({"date": "2026-06-20", "close_equity": 80_000.0,
                      "source": "cycle", "evidenced": True})  # real -20%
        self.assertEqual(drawdown_tier(curve)[0], TIER_HARD_KILL)

    def test_real_evidenced_soft_drawdown_still_fires(self) -> None:
        """A genuine 8% drop on EVIDENCED bars fires SOFT (no over-suppression)."""
        curve = []
        for i in range(8):
            curve.append({"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        curve.append({"date": "2026-06-20", "close_equity": 92_000.0,
                      "source": "cycle", "evidenced": True})  # -8%
        self.assertEqual(drawdown_tier(curve)[0], TIER_SOFT_DERISK)


if __name__ == "__main__":
    unittest.main()

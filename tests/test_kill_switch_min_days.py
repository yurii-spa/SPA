"""Regression tests for the Sharpe kill-switch minimum-days guard.

Background
----------
On 2026-06-14 the kill-switch fired on a false positive: with only 5 days of
paper-trading data the analytics Sharpe came out at -61.35 — an artefact of
dividing by a near-zero volatility in a tiny sample, not a real collapse. The
guard at the time only skipped Sharpe when ``num_days < 5``, so exactly 5 days
still triggered an all-cash kill-switch.

Fix: ``MIN_DAYS_FOR_SHARPE = 30``. The Sharpe trigger is only considered a
reliable signal once at least 30 days of data exist.

Tests:
- test_sharpe_kill_switch_skipped_with_few_days  (5 days, sharpe -61 -> NO kill)
- test_sharpe_kill_switch_triggers_with_enough_days (30 days, sharpe -2 -> kill)
- test_sharpe_kill_switch_skips_on_none_sharpe   (sharpe=None -> NO kill)
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path

# ── Ensure repo root on sys.path ──────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.kill_switch import (  # noqa: E402
    MIN_DAYS_FOR_SHARPE,
    SHARPE_THRESHOLD,
    KillSwitchChecker,
)


class TestKillSwitchMinDays(unittest.TestCase):
    """Sharpe trigger must require >= MIN_DAYS_FOR_SHARPE days of data."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_mindays_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=str(self.data_dir))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_analytics(self, sharpe, num_days) -> None:
        """Build an EVIDENCED equity curve whose Sharpe ≈ ``sharpe`` (WS-2.3).

        The kill-switch Sharpe trigger now reads the evidenced equity series
        (rf=0) via ``track_evidence.real_sharpe_ratio`` — not
        analytics_summary.json. ``sharpe=None`` writes an EMPTY curve (no
        evidenced returns → THIN → None → fail-closed).
        """
        from datetime import timedelta
        from spa_core.paper_trading.track_evidence import PAPER_REAL_START
        if sharpe is None:
            (self.data_dir / "equity_curve_daily.json").write_text(
                json.dumps({"daily": [], "is_demo": False}, indent=2),
                encoding="utf-8",
            )
            return
        n_returns = max(2, num_days - 1)
        ann = 365.0 ** 0.5
        if abs(sharpe) < 1e-9:
            r, d = 0.0, 0.0005
        else:
            r = -0.0001 if sharpe < 0 else 0.0001
            perturbed = 2 * (n_returns // 2)
            d = abs(r) / abs(sharpe) * ann / (perturbed / (n_returns - 1)) ** 0.5
        equity = 100_000.0
        daily = [{"date": PAPER_REAL_START.isoformat(), "equity": round(equity, 6)}]
        for i in range(n_returns):
            p = (d if i % 2 == 0 else -d) if i < 2 * (n_returns // 2) else 0.0
            equity *= (1.0 + r + p)
            daily.append({
                "date": (PAPER_REAL_START + timedelta(days=i + 1)).isoformat(),
                "equity": round(equity, 6),
            })
        (self.data_dir / "equity_curve_daily.json").write_text(
            json.dumps({"daily": daily, "is_demo": False}, indent=2),
            encoding="utf-8",
        )

    def test_sharpe_kill_switch_skipped_with_few_days(self) -> None:
        """5 evidenced days must NOT trigger (small-sample THIN artefact)."""
        self._write_analytics(sharpe=-61.3545, num_days=5)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Should skip Sharpe with 5 days: {reason}")
        self.assertTrue(
            "thin" in reason.lower() or "insufficient" in reason.lower(),
            f"Expected THIN/insufficient reason, got: {reason}",
        )

    def test_sharpe_kill_switch_triggers_with_enough_days(self) -> None:
        """30 days + sharpe -2.1 must trigger the kill-switch (strictly below early threshold -2.0)."""
        self._write_analytics(sharpe=-2.1, num_days=30)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered, f"Should trigger with 30 days, sharpe -2.1: {reason}")
        self.assertLess(-2.1, SHARPE_THRESHOLD + 0.0001)  # sanity: -2.1 < -1.0

    def test_sharpe_kill_switch_skips_on_none_sharpe(self) -> None:
        """No evidenced returns (empty curve) → THIN → NOT triggered."""
        self._write_analytics(sharpe=None, num_days=60)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Should skip when sharpe is None: {reason}")
        self.assertTrue(
            "no equity data" in reason.lower() or "thin" in reason.lower(),
            f"Expected no-data/THIN reason, got: {reason}",
        )

    # ── Boundary coverage ─────────────────────────────────────────────────────

    def test_sharpe_kill_switch_at_exact_min_days(self) -> None:
        """Exactly MIN_DAYS_FOR_SHARPE days is enough to evaluate Sharpe."""
        self._write_analytics(sharpe=-5.0, num_days=MIN_DAYS_FOR_SHARPE)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered, f"Should trigger at exactly {MIN_DAYS_FOR_SHARPE} days: {reason}")

    def test_sharpe_kill_switch_just_below_min_days(self) -> None:
        """MIN_DAYS_FOR_SHARPE - 1 days is still insufficient even at sharpe -61."""
        self._write_analytics(sharpe=-61.0, num_days=MIN_DAYS_FOR_SHARPE - 1)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Should skip just below threshold: {reason}")
        self.assertTrue(
            "thin" in reason.lower() or "insufficient" in reason.lower(),
            f"Expected THIN/insufficient reason, got: {reason}",
        )

    def test_min_days_constant_is_30(self) -> None:
        """Lock the documented threshold so it can't silently drift."""
        self.assertEqual(MIN_DAYS_FOR_SHARPE, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)

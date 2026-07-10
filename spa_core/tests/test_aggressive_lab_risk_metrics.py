#!/usr/bin/env python3
"""Tests for spa_core.strategy_lab.aggressive_lab.risk_metrics — the THIN-aware honest metrics.

Plain unittest, NO network, NO LLM, deterministic.

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_risk_metrics.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.aggressive_lab import risk_metrics as rm

INSUFFICIENT = rm.INSUFFICIENT


def _series(values, start="2026-01-01"):
    import datetime
    d0 = datetime.date.fromisoformat(start)
    return [{"date": (d0 + datetime.timedelta(days=i)).isoformat(), "equity_usd": float(v)}
            for i, v in enumerate(values)]


class TestRiskMetrics(unittest.TestCase):
    def test_thin_track_no_degenerate_sharpe(self):
        """RED-TEAM: a 6-point (thin) track → ratios INSUFFICIENT_DATA, NEVER a number."""
        m = rm.compute_track_metrics(_series([100000, 100100, 100200, 100300, 100400, 100500]))
        self.assertEqual(m["status"], "THIN")
        self.assertFalse(m["trustworthy"])
        self.assertEqual(m["sharpe"], INSUFFICIENT)
        self.assertEqual(m["sortino"], INSUFFICIENT)
        self.assertEqual(m["calmar"], INSUFFICIENT)
        # but return is still honestly reported (it's defined at ≥2 points)
        self.assertIsInstance(m["realized_apy_pct"], float)

    def test_broken_track_insufficient(self):
        """A gapped (broken-continuity) track → INSUFFICIENT_DATA, no metrics."""
        s = _series([100000, 100100])
        s.append({"date": "2026-02-01", "equity_usd": 100200.0})  # a big gap → integrity fail
        m = rm.compute_track_metrics(s)
        self.assertFalse(m["integrity_ok"])
        self.assertEqual(m["status"], INSUFFICIENT)
        self.assertEqual(m["sharpe"], INSUFFICIENT)
        self.assertIsNone(m["realized_apy_pct"])

    def test_locked_vol_no_fabricated_sharpe(self):
        """A flat (zero-dispersion) track with enough points → LOCKED_VOL, ratios INSUFFICIENT_DATA,
        NEVER a fabricated ~4.5e8 Sharpe."""
        m = rm.compute_track_metrics(_series([100000.0] * 10))
        self.assertEqual(m["status"], "LOCKED_VOL")
        self.assertFalse(m["trustworthy"])
        self.assertEqual(m["sharpe"], INSUFFICIENT)

    def test_deep_dispersed_track_trustworthy(self):
        """A deep track with REAL dispersion (ups and downs) → a trustworthy finite Sharpe."""
        vals = [100000]
        for i in range(20):
            vals.append(vals[-1] * (1.0 + (0.002 if i % 2 == 0 else -0.001)))
        m = rm.compute_track_metrics(_series(vals))
        self.assertEqual(m["status"], "OK")
        self.assertTrue(m["trustworthy"])
        self.assertIsInstance(m["sharpe"], float)

    def test_calmar_refuses_zero_drawdown(self):
        """Calmar with max-DD==0 → INSUFFICIENT_DATA, never +inf."""
        self.assertEqual(rm.calmar(10.0, 0.0), INSUFFICIENT)
        self.assertIsInstance(rm.calmar(10.0, 5.0), float)

    def test_non_finite_equity_fail_closed(self):
        """A non-finite equity → malformed, no number."""
        s = _series([100000, 100100])
        s.append({"date": "2026-01-03", "equity_usd": float("inf")})
        m = rm.compute_track_metrics(s)
        self.assertFalse(m["integrity_ok"])
        self.assertIsNone(m["realized_apy_pct"])


class TestAnnualizationGuard(unittest.TestCase):
    """Backlog #5 — a short window must NEVER surface an over-annualized APY artifact."""

    def test_short_window_apy_untrusted_but_period_return_honest(self):
        # 8-day track, small real gain → annualizing to a year is a huge artifact
        vals = [100000 * (1.005 ** i) for i in range(8)]
        m = rm.compute_track_metrics(_series(vals))
        # raw annualized figure is a big number (kept for continuity) …
        self.assertGreater(m["realized_apy_pct"], 100.0)
        # … but it is NOT trustworthy, the display is the sentinel, and the period return is honest
        self.assertFalse(m["apy_trustworthy"])
        self.assertEqual(m["realized_apy_display"], rm.INSUFFICIENT_APY)
        self.assertAlmostEqual(m["period_return_pct"], (vals[-1] / vals[0] - 1.0) * 100.0, places=3)

    def test_long_window_apy_trusted_and_displayed(self):
        # >= MIN_DAYS_FOR_APY daily steps → the annualized APY is trustworthy and shown as a number
        n = rm.MIN_DAYS_FOR_APY + 5
        vals = [100000 * (1.0003 ** i) for i in range(n + 1)]
        m = rm.compute_track_metrics(_series(vals))
        self.assertTrue(m["apy_trustworthy"])
        self.assertEqual(m["realized_apy_display"], m["realized_apy_pct"])

    def test_boundary_exactly_min_days(self):
        # exactly MIN_DAYS_FOR_APY daily steps (n_points = MIN_DAYS_FOR_APY + 1) → trustworthy
        n = rm.MIN_DAYS_FOR_APY
        vals = [100000 * (1.0004 ** i) for i in range(n + 1)]
        m = rm.compute_track_metrics(_series(vals))
        self.assertEqual(m["n_points"], n + 1)
        self.assertTrue(m["apy_trustworthy"])

    def test_broken_track_keeps_untrusted_apy_defaults(self):
        s = _series([100000, 100100])
        s.append({"date": "2026-03-01", "equity_usd": 100200.0})  # gap → integrity fail
        m = rm.compute_track_metrics(s)
        self.assertFalse(m["apy_trustworthy"])
        self.assertEqual(m["realized_apy_display"], rm.INSUFFICIENT_APY)


if __name__ == "__main__":
    unittest.main()

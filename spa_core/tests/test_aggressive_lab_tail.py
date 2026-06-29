#!/usr/bin/env python3
"""Tests for spa_core.strategy_lab.aggressive_lab.tail_overlay — THE TAIL OVERLAY.

The honest core: the tail must be surfaced PROMINENTLY next to the yield, not buried.

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_tail.py -q
"""
from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.aggressive_lab import tail_overlay as tov
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS


def _daily(start, end, drift, window_loss_total=None, window_key=None):
    """A deterministic daily backtest series with an optional front-loaded loss inside ONE window."""
    d0 = datetime.date.fromisoformat(start)
    d1 = datetime.date.fromisoformat(end)
    win = next((w for w in STRESS_WINDOWS if w["key"] == window_key), None)
    wlo = datetime.date.fromisoformat(str(win["date_from"])) if win else None
    whi = datetime.date.fromisoformat(str(win["date_to"])) if win else None
    n_win = (whi - wlo).days + 1 if win else 0
    norm = sum(0.5 ** j for j in range(n_win)) if n_win else 0.0
    series = []
    eq = 100000.0
    d = d0
    widx = 0
    while d <= d1:
        loss = 0.0
        if win and wlo <= d <= whi and window_loss_total:
            loss = window_loss_total * ((0.5 ** widx) / norm)
            widx += 1
        eq *= (1.0 + drift - loss)
        series.append({"date": d.isoformat(), "equity_usd": round(eq, 2)})
        d += datetime.timedelta(days=1)
    return series


class TestTailOverlay(unittest.TestCase):
    def test_in_sample_tail_surfaced_for_covered_window(self):
        """A backtest that passes through the Oct-2025 USDe window with a 20% loss → the in-sample
        tail (worst-DD + loss-in-stress) MUST be surfaced for that window."""
        s = _daily("2025-09-01", "2025-12-31", drift=11.0/100/365,
                   window_loss_total=0.20, window_key="usde_unwind_2025_10")
        ov = tov.build_tail_overlay(s, risk_shape="funding_flip", name="susde_dn")
        usde = next(w for w in ov["windows"] if w["key"] == "usde_unwind_2025_10")
        self.assertIsNotNone(usde["in_sample"])
        # a real, prominent in-sample drawdown is surfaced for the covered window (the loss spreads
        # multiplicatively over the window days while drift partly offsets, so the realized DD is
        # honestly LESS than the nominal 20% window-loss — but still material and clearly shown).
        self.assertGreater(usde["in_sample"]["worst_dd_pct"], 5.0)
        self.assertGreater(usde["in_sample"]["loss_in_stress_pct"], 5.0)
        # the worst tail (in-sample + the funding-flip shape shock) is prominent at the top level
        self.assertGreater(ov["worst_tail_dd_pct"], 10.0)

    def test_fat_apy_catastrophic_tail_not_buried(self):
        """RED-TEAM: a strategy with a fat headline but a CATASTROPHIC stress drawdown — the tail
        must dominate worst_tail_dd_pct (it is surfaced, not buried under the yield)."""
        s = _daily("2026-03-01", "2026-06-15", drift=13.0/100/365,
                   window_loss_total=0.30, window_key="rseth_depeg_2026_04")
        ov = tov.build_tail_overlay(s, risk_shape="depeg", name="lrt_carry")
        self.assertGreaterEqual(ov["worst_tail_dd_pct"], 15.0)  # severe — surfaced prominently
        rseth = next(w for w in ov["windows"] if w["key"] == "rseth_depeg_2026_04")
        # the in-sample depeg drawdown is real and material (honestly less than the nominal 30%
        # window-loss due to the multiplicative front-load + drift offset, but clearly surfaced)
        self.assertGreater(rseth["in_sample"]["worst_dd_pct"], 10.0)
        # and the depeg shape-shock pushes the worst tail past the severe band — NOT buried
        self.assertGreaterEqual(rseth["shape_shock"]["stressed_dd_pct"], 9.0)

    def test_shape_shock_always_applied(self):
        """Even with NO in-sample coverage, the shape-shock tail is applied per window (the SHAPE
        risk is never hidden). A liquidation shape takes the worst Oct-2025 shock."""
        s = _daily("2026-06-01", "2026-06-20", drift=15.0/100/365)  # no stress window covered
        ov = tov.build_tail_overlay(s, risk_shape="liquidation", name="leverage_loop")
        for w in ov["windows"]:
            self.assertIsNone(w["in_sample"])             # genuinely no coverage
            self.assertIn("shape_shock", w)
            self.assertGreater(w["shape_shock"]["shock_frac_pct"], 0.0)
        # the Oct-2025 liquidation shock (12%) is the worst shape shock
        self.assertGreater(ov["worst_shape_shock_dd_pct"], 10.0)

    def test_time_to_recover_not_recovered_is_honest(self):
        """A book still underwater at series end → max_time_to_recover NOT_RECOVERED (honest)."""
        # loss late in the series, never recovering before the end
        s = _daily("2026-03-01", "2026-04-30", drift=13.0/100/365,
                   window_loss_total=0.25, window_key="rseth_depeg_2026_04")
        ov = tov.build_tail_overlay(s, risk_shape="depeg", name="lrt_carry")
        self.assertEqual(ov["max_time_to_recover_days"], "NOT_RECOVERED")

    def test_broken_series_no_fabricated_in_sample(self):
        """A broken series → integrity_ok False, no in-sample tail; shape-shock still surfaced."""
        s = [{"date": "2026-04-05", "equity_usd": 100000.0},
             {"date": "2026-04-05", "equity_usd": 99000.0}]  # duplicate date → integrity fail
        ov = tov.build_tail_overlay(s, risk_shape="depeg", name="x")
        self.assertFalse(ov["integrity_ok"])
        for w in ov["windows"]:
            self.assertIsNone(w["in_sample"])
            self.assertIn("shape_shock", w)  # shape risk still shown


if __name__ == "__main__":
    unittest.main()

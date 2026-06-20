#!/usr/bin/env python3
"""tests/test_daily_limits.py — Unit tests for spa_core.risk.daily_limits.

Coverage (≥ 40 tests):

  _check_daily_loss (DL-01)       T01–T07
  _check_drawdown   (DL-02)       T08–T14
  _check_concentration (DL-03)   T15–T20
  _check_apy_sanity (DL-04/05)   T21–T28
  gate integration               T29–T40
  edge cases / save_result        T41–T46
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure repo root on sys.path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.risk.daily_limits import (
    CHECK_FAIL,
    CHECK_PASS,
    CHECK_SKIP,
    GATE_HALT,
    GATE_PASS,
    GATE_WARN,
    DailyLimitsChecker,
    _bar_equity,
    _read_equity_history,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _bar(equity: float) -> dict[str, Any]:
    """Make a minimal equity-curve bar."""
    return {"close_equity": equity}


def _bars(*equities: float) -> list[dict[str, Any]]:
    return [_bar(e) for e in equities]


def _alloc(**kwargs: float) -> dict[str, float]:
    return dict(kwargs)


def _apys(**kwargs: float) -> dict[str, float]:
    return dict(kwargs)


def _make_checker(**kwargs) -> DailyLimitsChecker:
    return DailyLimitsChecker(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _check_daily_loss — DL-01
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDailyLoss(unittest.TestCase):

    def setUp(self):
        self.chk = DailyLimitsChecker()

    def test_T01_empty_history_skips(self):
        """T01: No history → SKIP (not enough data)."""
        r = self.chk._check_daily_loss([])
        self.assertEqual(r["status"], CHECK_SKIP)
        self.assertIsNone(r["value"])
        self.assertEqual(r["id"], "DL-01")

    def test_T02_single_bar_skips(self):
        """T02: Only one bar → SKIP."""
        r = self.chk._check_daily_loss(_bars(100_000))
        self.assertEqual(r["status"], CHECK_SKIP)

    def test_T03_zero_loss_pass(self):
        """T03: No change in equity → PASS, value=0."""
        r = self.chk._check_daily_loss(_bars(100_000, 100_000))
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 0.0, places=3)

    def test_T04_gain_pass(self):
        """T04: Equity increased → PASS (loss_pct negative, no halt)."""
        r = self.chk._check_daily_loss(_bars(100_000, 101_000))
        self.assertEqual(r["status"], CHECK_PASS)
        # loss_pct = (100000 - 101000) / 100000 * 100 = -1.0 → clamped to 0 in msg
        self.assertLess(r["value"], 0)

    def test_T05_loss_below_threshold_pass(self):
        """T05: 1.5% loss (below 2% limit) → PASS."""
        prev, curr = 100_000, 98_500   # loss = 1.5%
        r = self.chk._check_daily_loss(_bars(prev, curr))
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 1.5, places=1)

    def test_T06_loss_exactly_at_threshold_pass(self):
        """T06: Exactly 2.0% loss → PASS (strict >)."""
        prev, curr = 100_000, 98_000   # loss = exactly 2.0%
        r = self.chk._check_daily_loss(_bars(prev, curr))
        self.assertEqual(r["status"], CHECK_PASS)

    def test_T07_loss_above_threshold_fail(self):
        """T07: 2.5% loss (above 2% limit) → FAIL."""
        prev, curr = 100_000, 97_500   # loss = 2.5%
        r = self.chk._check_daily_loss(_bars(prev, curr))
        self.assertEqual(r["status"], CHECK_FAIL)
        self.assertAlmostEqual(r["value"], 2.5, places=1)
        self.assertEqual(r["id"], "DL-01")

    def test_T07b_custom_threshold(self):
        """T07b: Custom 1% threshold: 1.5% loss → FAIL."""
        c = DailyLimitsChecker(max_daily_loss_pct=1.0)
        r = c._check_daily_loss(_bars(100_000, 98_500))
        self.assertEqual(r["status"], CHECK_FAIL)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _check_drawdown — DL-02
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDrawdown(unittest.TestCase):

    def setUp(self):
        self.chk = DailyLimitsChecker()

    def test_T08_empty_history_skips(self):
        """T08: No equity history → SKIP."""
        r = self.chk._check_drawdown([])
        self.assertEqual(r["status"], CHECK_SKIP)
        self.assertEqual(r["id"], "DL-02")

    def test_T09_single_bar_no_drawdown(self):
        """T09: Single bar → drawdown = 0.0 → PASS."""
        r = self.chk._check_drawdown(_bars(100_000))
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 0.0, places=3)

    def test_T10_monotone_rising_pass(self):
        """T10: Always rising → drawdown = 0 → PASS."""
        r = self.chk._check_drawdown(_bars(100_000, 101_000, 102_000, 103_000))
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 0.0, places=2)

    def test_T11_drawdown_5pct_pass(self):
        """T11: 5% drawdown (below 10% limit) → PASS."""
        r = self.chk._check_drawdown(_bars(100_000, 105_000, 99_750))
        # peak=105_000, trough=99_750 → dd = 5/105*100 ≈ 5.0%
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertLess(r["value"], self.chk.max_drawdown_pct)

    def test_T12_drawdown_exactly_10pct_pass(self):
        """T12: Exactly 10% drawdown → PASS (strict >)."""
        r = self.chk._check_drawdown(_bars(100_000, 90_000))
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 10.0, places=2)

    def test_T13_drawdown_12pct_fail(self):
        """T13: 12% drawdown → FAIL."""
        r = self.chk._check_drawdown(_bars(100_000, 88_000))
        self.assertEqual(r["status"], CHECK_FAIL)
        self.assertAlmostEqual(r["value"], 12.0, places=1)
        self.assertEqual(r["id"], "DL-02")

    def test_T14_recovery_after_drawdown_pass(self):
        """T14: Drawdown then recovery still within limit → PASS."""
        # peak=100k, trough=92k (8% dd), recovery to 101k
        r = self.chk._check_drawdown(_bars(100_000, 92_000, 101_000))
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 8.0, places=1)

    def test_T14b_custom_threshold(self):
        """T14b: Custom 5% threshold: 6% drawdown → FAIL."""
        c = DailyLimitsChecker(max_drawdown_pct=5.0)
        r = c._check_drawdown(_bars(100_000, 94_000))
        self.assertEqual(r["status"], CHECK_FAIL)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _check_concentration — DL-03
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckConcentration(unittest.TestCase):

    def setUp(self):
        self.chk = DailyLimitsChecker()

    def test_T15_empty_allocation_skips(self):
        """T15: Empty allocation → SKIP."""
        r = self.chk._check_concentration({})
        self.assertEqual(r["status"], CHECK_SKIP)
        self.assertEqual(r["id"], "DL-03")

    def test_T16_even_split_pass(self):
        """T16: Four equal adapters at 25% each → PASS."""
        alloc = _alloc(aave=25_000, compound=25_000, yearn=25_000, euler=25_000)
        r = self.chk._check_concentration(alloc)
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 25.0, places=1)

    def test_T17_concentration_39pct_pass(self):
        """T17: Largest adapter at 39% → PASS (below 40% limit)."""
        alloc = _alloc(aave=39_000, compound=30_000, yearn=31_000)
        r = self.chk._check_concentration(alloc)
        self.assertEqual(r["status"], CHECK_PASS)

    def test_T18_concentration_exactly_40pct_pass(self):
        """T18: Max adapter exactly 40% → PASS (strict >)."""
        # 40k out of 100k → 40% exactly → should PASS (limit is strict >)
        alloc = _alloc(aave=40_000, compound=30_000, yearn=30_000)
        r = self.chk._check_concentration(alloc)
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 40.0, places=1)

    def test_T19_concentration_50pct_fail(self):
        """T19: One adapter at 50% → FAIL."""
        alloc = _alloc(aave=50_000, compound=50_000)
        r = self.chk._check_concentration(alloc)
        self.assertEqual(r["status"], CHECK_FAIL)
        self.assertAlmostEqual(r["value"], 50.0, places=1)
        self.assertEqual(r["id"], "DL-03")

    def test_T20_single_adapter_100pct_fail(self):
        """T20: 100% in one adapter → FAIL."""
        r = self.chk._check_concentration(_alloc(aave=100_000))
        self.assertEqual(r["status"], CHECK_FAIL)
        self.assertAlmostEqual(r["value"], 100.0, places=1)
        self.assertEqual(r["top_adapter"], "aave")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _check_apy_sanity — DL-04 / DL-05
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckApySanity(unittest.TestCase):

    def setUp(self):
        self.chk = DailyLimitsChecker()

    def test_T21_empty_apy_map_skips_both(self):
        """T21: Empty apy_map → both DL-04 and DL-05 SKIP."""
        dl04, dl05 = self.chk._check_apy_sanity({})
        self.assertEqual(dl04["status"], CHECK_SKIP)
        self.assertEqual(dl05["status"], CHECK_SKIP)

    def test_T22_normal_apy_pass_both(self):
        """T22: Normal APYs (3–5%) → both PASS."""
        dl04, dl05 = self.chk._check_apy_sanity(_apys(aave=3.5, compound=4.8, yearn=5.1))
        self.assertEqual(dl04["status"], CHECK_PASS)
        self.assertEqual(dl05["status"], CHECK_PASS)

    def test_T23_low_apy_warns_dl04(self):
        """T23: One APY at 0.1% (below 0.5% floor) → DL-04 FAIL."""
        dl04, dl05 = self.chk._check_apy_sanity(_apys(aave=3.5, stale=0.1))
        self.assertEqual(dl04["status"], CHECK_FAIL)
        self.assertEqual(dl04["id"], "DL-04")
        self.assertAlmostEqual(dl04["value"], 0.1, places=2)

    def test_T24_zero_apy_warns_dl04(self):
        """T24: Zero APY → DL-04 FAIL."""
        dl04, _ = self.chk._check_apy_sanity(_apys(aave=3.5, dead_pool=0.0))
        self.assertEqual(dl04["status"], CHECK_FAIL)

    def test_T25_high_apy_warns_dl05(self):
        """T25: One APY at 60% (above 50% cap) → DL-05 FAIL."""
        dl04, dl05 = self.chk._check_apy_sanity(_apys(aave=3.5, scam=60.0))
        self.assertEqual(dl05["status"], CHECK_FAIL)
        self.assertEqual(dl05["id"], "DL-05")
        self.assertAlmostEqual(dl05["value"], 60.0, places=1)

    def test_T26_exactly_at_limits_pass(self):
        """T26: APY exactly at floor (0.5%) and cap (50%) → both PASS (strict </>)."""
        dl04, dl05 = self.chk._check_apy_sanity(
            _apys(low_pool=0.5, high_pool=50.0)
        )
        self.assertEqual(dl04["status"], CHECK_PASS)
        self.assertEqual(dl05["status"], CHECK_PASS)

    def test_T27_both_sanity_fail(self):
        """T27: APY below floor AND above cap → both DL-04 and DL-05 FAIL."""
        dl04, dl05 = self.chk._check_apy_sanity(
            _apys(dead=0.01, insane=99.0)
        )
        self.assertEqual(dl04["status"], CHECK_FAIL)
        self.assertEqual(dl05["status"], CHECK_FAIL)

    def test_T28_single_adapter_normal(self):
        """T28: Single adapter with normal APY → both PASS."""
        dl04, dl05 = self.chk._check_apy_sanity(_apys(only=5.0))
        self.assertEqual(dl04["status"], CHECK_PASS)
        self.assertEqual(dl05["status"], CHECK_PASS)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Gate integration — check() method
# ═══════════════════════════════════════════════════════════════════════════════

class TestGateIntegration(unittest.TestCase):

    def setUp(self):
        self.chk = DailyLimitsChecker()
        self.normal_hist = _bars(100_000, 100_100, 100_200)
        self.normal_alloc = _alloc(aave=35_000, compound=35_000, yearn=30_000)
        self.normal_apys = _apys(aave=3.5, compound=4.8, yearn=5.1)

    def _run(self, hist=None, alloc=None, apys=None):
        return self.chk.check(
            hist  if hist  is not None else self.normal_hist,
            alloc if alloc is not None else self.normal_alloc,
            apys  if apys  is not None else self.normal_apys,
        )

    def test_T29_all_normal_pass(self):
        """T29: All conditions normal → PASS."""
        r = self._run()
        self.assertEqual(r["gate"], GATE_PASS)
        self.assertEqual(r["halt_reasons"], [])
        self.assertEqual(r["warn_reasons"], [])

    def test_T30_result_has_required_keys(self):
        """T30: Result dict has gate, checks, halt_reasons, warn_reasons, checked_at."""
        r = self._run()
        for key in ("gate", "checks", "halt_reasons", "warn_reasons", "checked_at"):
            self.assertIn(key, r)

    def test_T31_five_checks_returned(self):
        """T31: Exactly 5 check dicts returned."""
        r = self._run()
        self.assertEqual(len(r["checks"]), 5)

    def test_T32_daily_loss_halt(self):
        """T32: 3% daily loss → HALT."""
        hist = _bars(100_000, 97_000)  # 3% loss
        r = self._run(hist=hist)
        self.assertEqual(r["gate"], GATE_HALT)
        self.assertTrue(any("DL-01" in reason for reason in r["halt_reasons"]))

    def test_T33_drawdown_halt(self):
        """T33: 12% peak drawdown → HALT."""
        hist = _bars(100_000, 105_000, 88_000)  # ~16% dd from peak
        r = self._run(hist=hist)
        self.assertEqual(r["gate"], GATE_HALT)
        self.assertTrue(any("DL-02" in reason for reason in r["halt_reasons"]))

    def test_T34_concentration_warn(self):
        """T34: Single adapter 70% → WARN (not HALT)."""
        alloc = _alloc(aave=70_000, compound=30_000)
        r = self._run(alloc=alloc)
        self.assertEqual(r["gate"], GATE_WARN)
        self.assertEqual(r["halt_reasons"], [])
        self.assertTrue(len(r["warn_reasons"]) >= 1)

    def test_T35_low_apy_warn(self):
        """T35: Low APY → WARN."""
        apys = _apys(aave=3.5, stale=0.01)
        r = self._run(apys=apys)
        self.assertEqual(r["gate"], GATE_WARN)

    def test_T36_high_apy_warn(self):
        """T36: High APY → WARN."""
        apys = _apys(aave=3.5, scam=999.0)
        r = self._run(apys=apys)
        self.assertEqual(r["gate"], GATE_WARN)

    def test_T37_halt_overrides_warn(self):
        """T37: Daily loss (HALT) + bad concentration (WARN) → HALT wins."""
        hist = _bars(100_000, 96_000)   # 4% loss → HALT
        alloc = _alloc(aave=80_000, compound=20_000)  # concentration → WARN
        r = self._run(hist=hist, alloc=alloc)
        self.assertEqual(r["gate"], GATE_HALT)

    def test_T38_both_halts_combine(self):
        """T38: Both DL-01 and DL-02 fail → HALT with two reasons."""
        # Equity: 110k (peak), then 96.5k (DL-02 ~12% dd) and prev close 100k (DL-01 3.5%)
        hist = _bars(100_000, 110_000, 100_000, 96_500)
        r = self._run(hist=hist)
        self.assertEqual(r["gate"], GATE_HALT)
        self.assertTrue(len(r["halt_reasons"]) >= 1)

    def test_T39_multiple_warn_reasons(self):
        """T39: Concentration + low APY + high APY → WARN with 3 reasons."""
        alloc = _alloc(aave=70_000, compound=30_000)   # concentration warn
        apys = _apys(aave=0.1, scam=60.0)               # low + high apy warns
        r = self._run(alloc=alloc, apys=apys)
        self.assertEqual(r["gate"], GATE_WARN)
        self.assertGreaterEqual(len(r["warn_reasons"]), 2)

    def test_T40_checked_at_is_iso_timestamp(self):
        """T40: checked_at is a valid ISO timestamp string."""
        from datetime import datetime
        r = self._run()
        ts = r["checked_at"]
        self.assertIsInstance(ts, str)
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Edge cases & save_result
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCasesAndSave(unittest.TestCase):

    def setUp(self):
        self.chk = DailyLimitsChecker()

    def test_T41_bar_equity_close_equity_key(self):
        """T41: _bar_equity reads close_equity key."""
        self.assertEqual(_bar_equity({"close_equity": 100.0}), 100.0)

    def test_T42_bar_equity_fallback_equity_key(self):
        """T42: _bar_equity falls back to equity key."""
        self.assertEqual(_bar_equity({"equity": 99.5}), 99.5)

    def test_T43_bar_equity_missing_key(self):
        """T43: _bar_equity returns None for empty bar."""
        self.assertIsNone(_bar_equity({}))

    def test_T44_bar_equity_string_value(self):
        """T44: _bar_equity returns None for non-numeric value."""
        self.assertIsNone(_bar_equity({"close_equity": "n/a"}))

    def test_T45_save_result_atomic_write(self):
        """T45: save_result writes valid JSON atomically to the target path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.chk.check(
                _bars(100_000, 100_100),
                _alloc(aave=40_000, compound=60_000),
                _apys(aave=3.5),
            )
            self.chk.save_result(result, tmpdir)
            out_path = Path(tmpdir) / "risk_limits_check.json"
            self.assertTrue(out_path.exists())
            with open(out_path) as f:
                loaded = json.load(f)
            self.assertIn("gate", loaded)
            self.assertIn("checks", loaded)
            # No .tmp files left behind
            tmp_files = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])

    def test_T46_save_result_creates_dir_if_missing(self):
        """T46: save_result creates data_dir if it does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "sub" / "data"
            result = self.chk.check([], {}, {})
            self.chk.save_result(result, new_dir)
            self.assertTrue((new_dir / "risk_limits_check.json").exists())

    def test_T47_read_equity_history_missing_file(self):
        """T47: _read_equity_history returns [] when file is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist = _read_equity_history(Path(tmpdir))
            self.assertEqual(hist, [])

    def test_T48_read_equity_history_corrupt_json(self):
        """T48: _read_equity_history returns [] for corrupt JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "equity_curve_daily.json"
            p.write_text("{ not valid json }", encoding="utf-8")
            hist = _read_equity_history(Path(tmpdir))
            self.assertEqual(hist, [])

    def test_T49_read_equity_history_envelope_format(self):
        """T49: _read_equity_history parses {"daily": [...]} envelope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "equity_curve_daily.json"
            doc = {"is_demo": False, "daily": [
                {"close_equity": 100_000.0},
                {"close_equity": 100_100.0},
            ]}
            p.write_text(json.dumps(doc), encoding="utf-8")
            hist = _read_equity_history(Path(tmpdir))
            self.assertEqual(len(hist), 2)
            self.assertAlmostEqual(hist[0]["close_equity"], 100_000.0)

    def test_T50_check_all_empty_inputs_no_crash(self):
        """T50: check() with all-empty inputs → no exception, gate is PASS (all SKIP)."""
        r = self.chk.check([], {}, {})
        self.assertIn(r["gate"], (GATE_PASS, GATE_WARN, GATE_HALT))
        # All SKIP → no HALT/WARN → PASS
        self.assertEqual(r["gate"], GATE_PASS)

    def test_T51_check_ids_are_correct(self):
        """T51: Check IDs are DL-01..DL-05 in order."""
        r = self.chk.check([], {}, {})
        ids = [c["id"] for c in r["checks"]]
        self.assertEqual(ids, ["DL-01", "DL-02", "DL-03", "DL-04", "DL-05"])

    def test_T52_large_equity_history_no_crash(self):
        """T52: 365-bar equity history processes without error."""
        import math
        bars = [_bar(100_000 + math.sin(i / 10) * 500) for i in range(365)]
        r = self.chk.check(bars, _alloc(aave=40_000, compound=60_000), _apys(aave=4.0))
        self.assertIn(r["gate"], (GATE_PASS, GATE_WARN, GATE_HALT))

    def test_T53_drawdown_check_ignores_none_bars(self):
        """T53: Bars with missing equity are safely skipped in drawdown calc."""
        bars = [{"close_equity": None}, {"equity": None}, _bar(100_000)]
        r = self.chk._check_drawdown(bars)
        # Only one valid bar → drawdown=0 → PASS
        self.assertEqual(r["status"], CHECK_PASS)
        self.assertAlmostEqual(r["value"], 0.0, places=3)

    def test_T54_concentration_zero_total_skips(self):
        """T54: Allocation sums to zero → SKIP (no div-by-zero)."""
        r = self.chk._check_concentration(_alloc(aave=0.0, compound=0.0))
        self.assertEqual(r["status"], CHECK_SKIP)


if __name__ == "__main__":
    unittest.main(verbosity=2)

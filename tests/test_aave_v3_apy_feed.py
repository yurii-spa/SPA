#!/usr/bin/env python3
"""tests/test_aave_v3_apy_feed.py — Aave V3 APY feed & stale-data regression.

Regression target
------------------
``paper_trading_status.json`` carried a spurious daily-limits warning:

    DL-04 APY Sanity Low: aave_v3 APY 0.00% below sanity floor 0.5% (stale data?)

Root cause: ``cycle_runner`` built the DL-04 sanity map with
``float(a.get("apy", 0))`` and did **not** filter on adapter liveness, so an
Aave V3 record whose live DeFiLlama feed was unavailable (``status="error"``,
``apy=None``) was coerced to ``0.0`` and tripped the sanity floor on every blip.

Fix: ``cycle_runner._sanity_apy_map`` includes an adapter only when it returned
a usable live APY (status ok/partial + numeric ``apy_pct``/``apy``); records
with no live data are EXCLUDED, not zeroed. A genuine live ~0% APY still fires.

Coverage (≥ 8 tests):

  _sanity_apy_map (the fix)          T01–T07
  AaveV3Adapter honest None feed     T08–T10
  DeFiLlama get_apy decimal parsing  T11–T13
  end-to-end: no false DL-04         T14
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.aave_v3 import AaveV3Adapter
from spa_core.paper_trading.cycle_runner import _sanity_apy_map
from spa_core.risk.daily_limits import CHECK_FAIL, CHECK_PASS, DailyLimitsChecker


class _FakeFeed:
    """Minimal DeFiLlamaFeed stand-in returning preset APY/TVL."""

    def __init__(self, apy=None, tvl=None, raise_on=False):
        self._apy = apy
        self._tvl = tvl
        self._raise = raise_on

    def get_apy(self, *_a, **_k):
        if self._raise:
            raise RuntimeError("feed down")
        return self._apy

    def get_tvl(self, *_a, **_k):
        if self._raise:
            raise RuntimeError("feed down")
        return self._tvl


# ── _sanity_apy_map (the fix) ───────────────────────────────────────────────


class TestSanityApyMap(unittest.TestCase):
    def test_T01_excludes_error_status_none_apy(self):
        """T01: aave_v3 with status=error/apy=None is EXCLUDED, not zeroed."""
        m = _sanity_apy_map([{"id": "aave_v3", "status": "error", "apy": None}])
        self.assertNotIn("aave_v3", m)
        self.assertEqual(m, {})

    def test_T02_includes_live_ok_adapter(self):
        """T02: a live ok adapter with apy_pct is included."""
        m = _sanity_apy_map([{"id": "compound_v3", "status": "ok", "apy_pct": 4.0}])
        self.assertEqual(m["compound_v3"], 4.0)

    def test_T03_prefers_apy_pct_over_apy(self):
        """T03: apy_pct wins when both fields are present."""
        m = _sanity_apy_map(
            [{"id": "x", "status": "ok", "apy_pct": 5.5, "apy": 9.9}]
        )
        self.assertEqual(m["x"], 5.5)

    def test_T04_falls_back_to_apy_field(self):
        """T04: when apy_pct missing, the apy field is used."""
        m = _sanity_apy_map([{"id": "x", "status": "ok", "apy": 4.2}])
        self.assertEqual(m["x"], 4.2)

    def test_T05_keeps_genuine_live_zero(self):
        """T05: a real live 0% APY (status ok) is KEPT so DL-04 can fire."""
        m = _sanity_apy_map([{"id": "dead_pool", "status": "ok", "apy_pct": 0.0}])
        self.assertIn("dead_pool", m)
        self.assertEqual(m["dead_pool"], 0.0)

    def test_T06_mixed_live_and_dead_feeds(self):
        """T06: only live adapters survive a mixed batch."""
        m = _sanity_apy_map(
            [
                {"id": "aave_v3", "status": "error", "apy": None},
                {"id": "compound_v3", "status": "ok", "apy_pct": 4.0},
                {"protocol": "morpho", "status": "partial", "apy_pct": 4.8},
            ]
        )
        self.assertEqual(set(m), {"compound_v3", "morpho"})

    def test_T07_skips_non_numeric_and_keyless(self):
        """T07: non-numeric APY and records without id/protocol are skipped."""
        m = _sanity_apy_map(
            [
                {"id": "a", "status": "ok", "apy_pct": "n/a"},
                {"status": "ok", "apy_pct": 3.0},  # no key
                "not a dict",
            ]
        )
        self.assertEqual(m, {})


# ── AaveV3Adapter honest behaviour ──────────────────────────────────────────


class TestAaveV3AdapterFeed(unittest.TestCase):
    def test_T08_none_feed_reports_error_not_zero(self):
        """T08: feed miss → status=error, apy=None (never 0.0)."""
        a = AaveV3Adapter(feed=_FakeFeed(apy=None, tvl=None))
        rec = a.fetch()
        self.assertEqual(rec["status"], "error")
        self.assertIsNone(rec["apy"])
        self.assertFalse(rec["live_data"])

    def test_T09_live_feed_returns_decimal_apy(self):
        """T09: live decimal APY flows through unchanged."""
        a = AaveV3Adapter(feed=_FakeFeed(apy=0.052, tvl=1_000_000_000.0))
        rec = a.fetch()
        self.assertEqual(rec["status"], "ok")
        self.assertAlmostEqual(rec["apy"], 0.052)
        self.assertTrue(rec["live_data"])

    def test_T10_feed_exception_is_graceful(self):
        """T10: a raising feed never propagates — honest error record."""
        a = AaveV3Adapter(feed=_FakeFeed(raise_on=True))
        rec = a.fetch()
        self.assertEqual(rec["status"], "error")
        self.assertIsNone(rec["apy"])
        self.assertIsNone(a.get_apy())


# ── DeFiLlama get_apy parsing ───────────────────────────────────────────────


class TestDeFiLlamaApyParsing(unittest.TestCase):
    def _feed_with_pools(self, pools):
        from spa_core.adapters.defillama_feed import DeFiLlamaFeed

        f = DeFiLlamaFeed(enabled=True)
        f._cache = pools
        import time as _t

        f._cache_ts = _t.monotonic()
        return f

    def test_T11_apy_returned_as_decimal(self):
        """T11: 5.2% pct → 0.052 decimal."""
        f = self._feed_with_pools(
            [{"project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
              "apy": 5.2, "tvlUsd": 1e9}]
        )
        self.assertAlmostEqual(f.get_apy("aave-v3", "USDC", "Ethereum"), 0.052)

    def test_T12_no_match_returns_none(self):
        """T12: unknown pool → None (not 0)."""
        f = self._feed_with_pools(
            [{"project": "compound-v3", "symbol": "USDC", "chain": "Ethereum",
              "apy": 4.0, "tvlUsd": 1e9}]
        )
        self.assertIsNone(f.get_apy("aave-v3", "USDC", "Ethereum"))

    def test_T13_picks_highest_tvl_match(self):
        """T13: among matches, the highest-TVL pool wins."""
        f = self._feed_with_pools(
            [
                {"project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
                 "apy": 3.0, "tvlUsd": 1e6},
                {"project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
                 "apy": 6.0, "tvlUsd": 5e9},
            ]
        )
        self.assertAlmostEqual(f.get_apy("aave-v3", "USDC", "Ethereum"), 0.06)


# ── End-to-end: the false DL-04 no longer fires ─────────────────────────────


class TestNoFalseDL04(unittest.TestCase):
    def _flat_equity(self):
        return [{"close_equity": 100_000.0} for _ in range(3)]

    def test_T14_stale_aave_no_longer_trips_dl04(self):
        """T14: with the fix, a down aave_v3 feed produces no DL-04 WARN."""
        adapters = [
            {"id": "aave_v3", "status": "error", "apy": None},
            {"id": "compound_v3", "status": "ok", "apy_pct": 4.0},
            {"id": "yearn_v3", "status": "ok", "apy_pct": 6.1},
        ]
        apy_map = _sanity_apy_map(adapters)
        checker = DailyLimitsChecker()
        result = checker.check(
            self._flat_equity(), {"aave_v3": 23_750.0, "compound_v3": 38_000.0}, apy_map
        )
        dl04 = next(c for c in result["checks"] if c["id"] == "DL-04")
        self.assertEqual(dl04["status"], CHECK_PASS)
        self.assertNotIn("0.00%", dl04.get("message", ""))

    def test_T15_old_behaviour_would_have_failed(self):
        """T15: the pre-fix map (None→0.0, unfiltered) WOULD trip DL-04 —
        proving the regression is real and the fix is what removes it."""
        # Reconstruct the buggy map: coerce None→0.0, no liveness filter.
        adapters = [
            {"id": "aave_v3", "status": "error", "apy": None},
            {"id": "compound_v3", "status": "ok", "apy": 4.0},
        ]
        buggy_map = {
            str(a.get("id")): float(a.get("apy", 0) or 0) for a in adapters
        }
        checker = DailyLimitsChecker()
        result = checker.check(self._flat_equity(), {"aave_v3": 1.0}, buggy_map)
        dl04 = next(c for c in result["checks"] if c["id"] == "DL-04")
        self.assertEqual(dl04["status"], CHECK_FAIL)


if __name__ == "__main__":
    unittest.main(verbosity=2)

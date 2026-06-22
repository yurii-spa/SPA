"""
tests/test_defillama_feed_monitor.py — 35 tests for DeFiLlamaFeedMonitor (MP-1336 v9.52)

All network calls are mocked — no real HTTP requests are made in tests.

Coverage:
  T01–T08   check_protocol() — keys, types, graceful fallback on network error
  T09–T12   check_all() — structure
  T13–T17   promotable_protocols() — list semantics
  T18–T24   monitoring_report() — all required fields
  T25–T28   save() — atomic write
  T29–T30   caching — TTL and hit/miss
  T31–T35   mocked pool data — promotion logic (can_promote_to_pending)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defillama_feed_monitor import (
    MONITORED_PROTOCOLS,
    DeFiLlamaFeedMonitor,
)

# ── Pool fixtures ─────────────────────────────────────────────────────────────

_GMX_POOL = {
    "pool":    "gmx-btc-pool-001",
    "project": "gmx",
    "symbol":  "BTC-USDC",
    "chain":   "Arbitrum",
    "apy":     12.5,
    "tvlUsd":  50_000_000,
}
_GMX_ETH_POOL = {
    "pool":    "gmx-eth-pool-001",
    "project": "gmx",
    "symbol":  "ETH-USDC",
    "chain":   "Arbitrum",
    "apy":     9.0,
    "tvlUsd":  30_000_000,
}
_PAXG_POOL = {
    "pool":    "paxg-pool-001",
    "project": "curve",
    "symbol":  "PAXG-USDC",
    "chain":   "Ethereum",
    "apy":     3.5,
    "tvlUsd":  5_000_000,
}
_DEFILLAMA_RESPONSE = {
    "status": "ok",
    "data": [_GMX_POOL, _GMX_ETH_POOL, _PAXG_POOL],
}

# ── Helper ─────────────────────────────────────────────────────────────────────

def _mock_fetch(monitor: DeFiLlamaFeedMonitor, pools_data) -> None:
    """Patch _fetch_pools to return pools_data without network calls."""
    monitor._fetch_pools = lambda: pools_data


# ══════════════════════════════════════════════════════════════════════════════
# T01–T08  check_protocol()
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckProtocol(unittest.TestCase):

    def _make_monitor(self, pools=None):
        m = DeFiLlamaFeedMonitor()
        if pools is not None:
            _mock_fetch(m, pools)
        else:
            _mock_fetch(m, [])
        return m

    def test_T01_returns_dict(self):
        """check_protocol() returns a dict."""
        m = self._make_monitor()
        result = m.check_protocol("gmx_btc_exposure")
        self.assertIsInstance(result, dict)

    def test_T02_has_defillama_found_key(self):
        """check_protocol() result has 'defillama_found' key."""
        m = self._make_monitor()
        result = m.check_protocol("gmx_btc_exposure")
        self.assertIn("defillama_found", result)

    def test_T03_has_pool_count_key(self):
        """check_protocol() result has 'pool_count' key."""
        m = self._make_monitor()
        result = m.check_protocol("gmx_btc_exposure")
        self.assertIn("pool_count", result)

    def test_T04_has_best_pool_key(self):
        """check_protocol() result has 'best_pool' key."""
        m = self._make_monitor()
        result = m.check_protocol("gmx_btc_exposure")
        self.assertIn("best_pool", result)

    def test_T05_has_can_promote_key(self):
        """check_protocol() result has 'can_promote_to_pending' key."""
        m = self._make_monitor()
        result = m.check_protocol("gmx_btc_exposure")
        self.assertIn("can_promote_to_pending", result)

    def test_T06_has_notes_key(self):
        """check_protocol() result has 'notes' key."""
        m = self._make_monitor()
        result = m.check_protocol("gmx_btc_exposure")
        self.assertIn("notes", result)

    def test_T07_no_exception_on_network_error(self):
        """check_protocol() does not raise when network is unavailable."""
        m = DeFiLlamaFeedMonitor()
        m._fetch_pools = lambda: None  # simulate network failure
        try:
            result = m.check_protocol("gmx_btc_exposure")
        except Exception as exc:
            self.fail(f"check_protocol raised on network error: {exc}")
        self.assertIsInstance(result, dict)

    def test_T08_protocol_id_preserved(self):
        """protocol_id in result matches input."""
        m = self._make_monitor()
        for pid in MONITORED_PROTOCOLS:
            result = m.check_protocol(pid)
            self.assertEqual(result["protocol_id"], pid)


# ══════════════════════════════════════════════════════════════════════════════
# T09–T12  check_all()
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckAll(unittest.TestCase):

    def _make_monitor(self):
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        return m

    def test_T09_returns_dict(self):
        """check_all() returns a dict."""
        m = self._make_monitor()
        result = m.check_all()
        self.assertIsInstance(result, dict)

    def test_T10_has_all_monitored_protocols(self):
        """check_all() keys == MONITORED_PROTOCOLS."""
        m = self._make_monitor()
        result = m.check_all()
        self.assertSetEqual(set(result.keys()), set(MONITORED_PROTOCOLS))

    def test_T11_each_value_is_dict_with_required_keys(self):
        """Each value in check_all() is a dict with required schema keys."""
        required = {
            "protocol_id", "defillama_found", "pool_count",
            "best_pool", "data_period_available",
            "can_promote_to_pending", "notes",
        }
        m = self._make_monitor()
        for pid, val in m.check_all().items():
            with self.subTest(protocol=pid):
                self.assertIsInstance(val, dict)
                for key in required:
                    self.assertIn(key, val, msg=f"Missing key '{key}' for {pid}")

    def test_T12_no_exception_on_network_unavailable(self):
        """check_all() does not raise when network is unavailable."""
        m = DeFiLlamaFeedMonitor()
        m._fetch_pools = lambda: None
        try:
            result = m.check_all()
        except Exception as exc:
            self.fail(f"check_all raised on network error: {exc}")
        self.assertIsInstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# T13–T17  promotable_protocols()
# ══════════════════════════════════════════════════════════════════════════════

class TestPromotableProtocols(unittest.TestCase):

    def test_T13_returns_list(self):
        """promotable_protocols() returns a list."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        result = m.promotable_protocols()
        self.assertIsInstance(result, list)

    def test_T14_returns_empty_when_no_pools(self):
        """promotable_protocols() returns empty list when no pools found."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        result = m.promotable_protocols()
        self.assertEqual(result, [])

    def test_T15_promotable_with_matching_pools(self):
        """promotable_protocols() includes gmx_btc_exposure when pools match."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [_GMX_POOL])
        result = m.promotable_protocols()
        self.assertIn("gmx_btc_exposure", result)

    def test_T16_not_promotable_when_empty_response(self):
        """promotable_protocols() excludes protocols with no matching pools."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        result = m.promotable_protocols()
        for pid in MONITORED_PROTOCOLS:
            self.assertNotIn(pid, result)

    def test_T17_all_items_are_valid_protocol_ids(self):
        """All items in promotable_protocols() are valid MONITORED_PROTOCOLS."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [_GMX_POOL, _GMX_ETH_POOL, _PAXG_POOL])
        result = m.promotable_protocols()
        for pid in result:
            self.assertIn(pid, MONITORED_PROTOCOLS)


# ══════════════════════════════════════════════════════════════════════════════
# T18–T24  monitoring_report()
# ══════════════════════════════════════════════════════════════════════════════

class TestMonitoringReport(unittest.TestCase):

    def _make_monitor(self):
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        return m

    def test_T18_returns_dict(self):
        """monitoring_report() returns a dict."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIsInstance(result, dict)

    def test_T19_has_checked_at(self):
        """monitoring_report() has 'checked_at' key."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIn("checked_at", result)

    def test_T20_has_total_monitored(self):
        """monitoring_report() has 'total_monitored' key."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIn("total_monitored", result)

    def test_T20b_total_monitored_equals_protocol_count(self):
        """total_monitored == len(MONITORED_PROTOCOLS)."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertEqual(result["total_monitored"], len(MONITORED_PROTOCOLS))

    def test_T21_has_found_on_defillama(self):
        """monitoring_report() has 'found_on_defillama' key."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIn("found_on_defillama", result)

    def test_T22_has_promotable(self):
        """monitoring_report() has 'promotable' key."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIn("promotable", result)

    def test_T23_has_protocols(self):
        """monitoring_report() has 'protocols' dict."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIn("protocols", result)
        self.assertIsInstance(result["protocols"], dict)

    def test_T24_has_recommendation(self):
        """monitoring_report() has non-empty 'recommendation' string."""
        m = self._make_monitor()
        result = m.monitoring_report()
        self.assertIn("recommendation", result)
        self.assertIsInstance(result["recommendation"], str)
        self.assertGreater(len(result["recommendation"]), 0)


# ══════════════════════════════════════════════════════════════════════════════
# T25–T28  save()
# ══════════════════════════════════════════════════════════════════════════════

class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _make_monitor(self):
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        return m

    def test_T25_creates_file(self):
        """save() creates file at specified path."""
        out_path = os.path.join(self.tmp_dir, "test_output.json")
        m = self._make_monitor()
        m.save(out_path)
        self.assertTrue(os.path.exists(out_path))

    def test_T26_file_exists_after_save(self):
        """File is present and non-empty after atomic save."""
        out_path = os.path.join(self.tmp_dir, "monitor.json")
        m = self._make_monitor()
        m.save(out_path)
        self.assertGreater(os.path.getsize(out_path), 0)

    def test_T27_valid_json_content(self):
        """Saved file contains valid JSON."""
        out_path = os.path.join(self.tmp_dir, "monitor.json")
        m = self._make_monitor()
        m.save(out_path)
        with open(out_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_T28_creates_parent_dirs(self):
        """save() creates parent directories if they don't exist."""
        out_path = os.path.join(self.tmp_dir, "nested", "deep", "monitor.json")
        m = self._make_monitor()
        m.save(out_path)
        self.assertTrue(os.path.exists(out_path))


# ══════════════════════════════════════════════════════════════════════════════
# T29–T30  caching
# ══════════════════════════════════════════════════════════════════════════════

class TestCaching(unittest.TestCase):

    def test_T29_cache_ttl_is_3600(self):
        """Cache TTL is set to 3600 seconds."""
        m = DeFiLlamaFeedMonitor()
        self.assertEqual(m._cache_ttl, 3600)

    def test_T30_cached_result_returned_on_second_call(self):
        """Second call to check_protocol returns cached result (fetch not called twice)."""
        m = DeFiLlamaFeedMonitor()
        call_count = [0]

        def counting_fetch():
            call_count[0] += 1
            return []

        m._fetch_pools = counting_fetch
        m.check_protocol("gmx_btc_exposure")
        m.check_protocol("gmx_btc_exposure")
        self.assertEqual(call_count[0], 1, "Expected fetch to be called only once (cache hit on second call)")


# ══════════════════════════════════════════════════════════════════════════════
# T31–T35  mocked pool data — promotion logic
# ══════════════════════════════════════════════════════════════════════════════

class TestMockedPoolData(unittest.TestCase):

    def test_T31_pool_with_data_promotes_to_pending(self):
        """can_promote_to_pending=True when matching pool with sufficient TVL and APY."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [_GMX_POOL])
        result = m.check_protocol("gmx_btc_exposure")
        self.assertTrue(result["can_promote_to_pending"])

    def test_T32_empty_response_cannot_promote(self):
        """can_promote_to_pending=False when no pools found."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [])
        result = m.check_protocol("gmx_btc_exposure")
        self.assertFalse(result["can_promote_to_pending"])

    def test_T33_low_tvl_pool_cannot_promote(self):
        """can_promote_to_pending=False when pool TVL is below threshold."""
        low_tvl_pool = {**_GMX_POOL, "tvlUsd": 1_000}  # well below min_tvl
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [low_tvl_pool])
        result = m.check_protocol("gmx_btc_exposure")
        self.assertFalse(result["can_promote_to_pending"])

    def test_T34_unknown_protocol_returns_gracefully(self):
        """check_protocol() with unknown protocol_id returns a valid dict."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [_GMX_POOL])
        result = m.check_protocol("nonexistent_protocol_xyz")
        self.assertIsInstance(result, dict)
        self.assertIn("can_promote_to_pending", result)
        self.assertFalse(result["can_promote_to_pending"])

    def test_T35_gold_proxy_promotable_with_paxg_pool(self):
        """gold_proxy is promotable when PAXG pool found with sufficient TVL."""
        m = DeFiLlamaFeedMonitor()
        _mock_fetch(m, [_PAXG_POOL])
        result = m.check_protocol("gold_proxy")
        self.assertTrue(result["defillama_found"])
        self.assertTrue(result["can_promote_to_pending"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

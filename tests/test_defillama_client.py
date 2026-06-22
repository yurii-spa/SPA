"""
tests/test_defillama_client.py

35 unit tests for spa_core.utils.defillama.DeFiLlamaClient.
MP-1379 (v9.95): Centralized DeFiLlama client.

All HTTP calls are intercepted with unittest.mock — no real network access.
"""
from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from spa_core.utils.defillama import DeFiLlamaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pools_response(pools: list) -> bytes:
    """Encode a DeFiLlama-shaped payload as bytes."""
    return json.dumps({"status": "success", "data": pools}).encode()


def _make_chart_response(apy_series: list) -> bytes:
    """Encode a /chart/{id} response as bytes."""
    data = [{"apy": a, "timestamp": i} for i, a in enumerate(apy_series)]
    return json.dumps({"status": "success", "data": data}).encode()


def _mock_urlopen(body: bytes):
    """Return a context-manager mock that yields a file-like response."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=body)))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


SAMPLE_POOLS = [
    {
        "pool": "pool-aave-usdc",
        "project": "aave-v3",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 4.5,
        "tvlUsd": 500_000_000.0,
    },
    {
        "pool": "pool-aave-eth",
        "project": "aave-v3",
        "symbol": "ETH",
        "chain": "Ethereum",
        "apy": 2.1,
        "tvlUsd": 200_000_000.0,
    },
    {
        "pool": "pool-compound-usdc",
        "project": "compound-v3",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 5.2,
        "tvlUsd": 300_000_000.0,
    },
    {
        "pool": "pool-morpho-usdc",
        "project": "morpho",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 6.8,
        "tvlUsd": 50_000_000.0,
    },
    {
        "pool": "pool-tiny",
        "project": "tiny-project",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 99.0,
        "tvlUsd": 10_000.0,        # below default min_tvl
    },
    {
        "pool": "pool-arb-aave",
        "project": "aave-v3",
        "symbol": "USDC",
        "chain": "Arbitrum",
        "apy": 3.9,
        "tvlUsd": 80_000_000.0,
    },
    {
        "pool": "pool-usdt-aave",
        "project": "aave-v3",
        "symbol": "USDT",
        "chain": "Ethereum",
        "apy": 3.3,
        "tvlUsd": 100_000_000.0,
    },
]


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------

class TestDeFiLlamaClientConstruction(unittest.TestCase):

    def test_01_client_creates_with_defaults(self):
        """DeFiLlamaClient instantiates without arguments."""
        client = DeFiLlamaClient()
        self.assertIsInstance(client, DeFiLlamaClient)

    def test_02_custom_timeout(self):
        """Timeout parameter is stored."""
        client = DeFiLlamaClient(timeout=10)
        self.assertEqual(client._timeout, 10)

    def test_03_custom_cache_ttl(self):
        """Cache TTL parameter is stored."""
        client = DeFiLlamaClient(cache_ttl=60)
        self.assertEqual(client._cache_ttl, 60)

    def test_04_cache_initially_empty(self):
        """Pool cache starts as None."""
        client = DeFiLlamaClient()
        self.assertIsNone(client._pools_cache)
        self.assertEqual(client._pools_cache_time, 0.0)


# ---------------------------------------------------------------------------
# 2. fetch_pools
# ---------------------------------------------------------------------------

class TestFetchPools(unittest.TestCase):

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_05_fetch_pools_returns_list(self, mock_urlopen):
        """fetch_pools() returns a list of pool dicts."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient()
        pools = client.fetch_pools()
        self.assertIsInstance(pools, list)
        self.assertEqual(len(pools), len(SAMPLE_POOLS))

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_06_fetch_pools_returns_empty_on_network_error(self, mock_urlopen):
        """fetch_pools() returns [] when the network call fails — never raises."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        client = DeFiLlamaClient()
        result = client.fetch_pools()
        self.assertEqual(result, [])

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_07_fetch_pools_does_not_raise(self, mock_urlopen):
        """fetch_pools() suppresses exceptions entirely."""
        mock_urlopen.side_effect = RuntimeError("unexpected")
        client = DeFiLlamaClient()
        try:
            client.fetch_pools()
        except Exception as exc:
            self.fail(f"fetch_pools raised unexpectedly: {exc}")

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_08_fetch_pools_uses_cache_on_second_call(self, mock_urlopen):
        """Second fetch_pools() call reuses cache — no extra HTTP call."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient()
        client.fetch_pools()
        client.fetch_pools()
        # urlopen should have been called exactly once
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_09_fetch_pools_force_bypasses_cache(self, mock_urlopen):
        """force=True ignores the cache and hits the network again."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient()
        client.fetch_pools()
        client.fetch_pools(force=True)
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_10_fetch_pools_refetches_after_ttl_expires(self, mock_urlopen):
        """Cache is stale after TTL; next call hits the network again."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient(cache_ttl=1)
        client.fetch_pools()
        # Artificially expire the cache
        client._pools_cache_time -= 2
        client.fetch_pools()
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_11_fetch_pools_handles_bad_json(self, mock_urlopen):
        """Malformed JSON body yields [] without raising."""
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"not-json{")))
        cm.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = cm
        client = DeFiLlamaClient()
        self.assertEqual(client.fetch_pools(), [])

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_12_fetch_pools_handles_unexpected_payload_type(self, mock_urlopen):
        """A payload that is not a list or dict yields []."""
        body = json.dumps("just a string").encode()
        mock_urlopen.return_value = _mock_urlopen(body)
        client = DeFiLlamaClient()
        self.assertEqual(client.fetch_pools(), [])

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_13_fetch_pools_handles_list_payload_directly(self, mock_urlopen):
        """If the API returns a bare list (no envelope), it is accepted."""
        body = json.dumps(SAMPLE_POOLS).encode()
        mock_urlopen.return_value = _mock_urlopen(body)
        client = DeFiLlamaClient()
        result = client.fetch_pools()
        self.assertEqual(len(result), len(SAMPLE_POOLS))

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_14_fetch_pools_caches_result(self, mock_urlopen):
        """After a successful fetch, _pools_cache is populated."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient()
        client.fetch_pools()
        self.assertIsNotNone(client._pools_cache)
        self.assertGreater(client._pools_cache_time, 0)


# ---------------------------------------------------------------------------
# 3. pool_apy
# ---------------------------------------------------------------------------

class TestPoolApy(unittest.TestCase):

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_15_pool_apy_returns_float(self, mock_urlopen):
        """pool_apy() returns a float APY for a valid pool_id."""
        mock_urlopen.return_value = _mock_urlopen(_make_chart_response([3.5, 4.0, 4.2]))
        client = DeFiLlamaClient()
        result = client.pool_apy("some-pool-uuid")
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 4.2)

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_16_pool_apy_returns_none_on_network_error(self, mock_urlopen):
        """pool_apy() returns None when the request fails."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        client = DeFiLlamaClient()
        self.assertIsNone(client.pool_apy("bad-id"))

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_17_pool_apy_returns_none_on_empty_data(self, mock_urlopen):
        """pool_apy() returns None when /chart returns empty data list."""
        body = json.dumps({"status": "success", "data": []}).encode()
        mock_urlopen.return_value = _mock_urlopen(body)
        client = DeFiLlamaClient()
        self.assertIsNone(client.pool_apy("pool-x"))

    def test_18_pool_apy_returns_none_for_empty_id(self):
        """pool_apy("") returns None immediately (no network call)."""
        client = DeFiLlamaClient()
        self.assertIsNone(client.pool_apy(""))

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_19_pool_apy_uses_last_entry(self, mock_urlopen):
        """pool_apy() picks the last element from the chart series."""
        mock_urlopen.return_value = _mock_urlopen(_make_chart_response([1.0, 2.0, 9.9]))
        client = DeFiLlamaClient()
        self.assertAlmostEqual(client.pool_apy("pid"), 9.9)

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_20_pool_apy_returns_none_for_missing_apy_field(self, mock_urlopen):
        """pool_apy() returns None if last chart entry has no 'apy'."""
        body = json.dumps({"status": "success", "data": [{"timestamp": 1}]}).encode()
        mock_urlopen.return_value = _mock_urlopen(body)
        client = DeFiLlamaClient()
        self.assertIsNone(client.pool_apy("pid"))


# ---------------------------------------------------------------------------
# 4. search
# ---------------------------------------------------------------------------

class TestSearch(unittest.TestCase):

    def _client_with_pools(self, pools=None):
        """Return a client whose cache is pre-loaded with *pools*."""
        client = DeFiLlamaClient()
        client._pools_cache = pools if pools is not None else list(SAMPLE_POOLS)
        client._pools_cache_time = time.monotonic()
        return client

    def test_21_search_by_project(self):
        """search(project=...) returns only matching pools."""
        client = self._client_with_pools()
        results = client.search(project="aave-v3")
        for p in results:
            self.assertEqual(p["project"], "aave-v3")
        # at least 3 aave pools in SAMPLE_POOLS (Ethereum USDC, ETH, Arbitrum, USDT)
        self.assertGreaterEqual(len(results), 3)

    def test_22_search_by_project_is_case_insensitive(self):
        """search(project=...) matches regardless of case."""
        client = self._client_with_pools()
        results_lower = client.search(project="aave-v3")
        results_upper = client.search(project="AAVE-V3")
        self.assertEqual(len(results_lower), len(results_upper))

    def test_23_search_by_symbol_kw(self):
        """search(symbol_kw=...) matches symbol substring."""
        client = self._client_with_pools()
        results = client.search(symbol_kw="USDC")
        for p in results:
            self.assertIn("usdc", p["symbol"].lower())

    def test_24_search_by_symbol_kw_case_insensitive(self):
        """symbol_kw match is case-insensitive."""
        client = self._client_with_pools()
        r1 = client.search(symbol_kw="usdc")
        r2 = client.search(symbol_kw="USDC")
        self.assertEqual(len(r1), len(r2))

    def test_25_search_by_chain(self):
        """search(chain=...) returns only matching chain."""
        client = self._client_with_pools()
        results = client.search(chain="Arbitrum")
        for p in results:
            self.assertEqual(p["chain"].lower(), "arbitrum")

    def test_26_search_by_min_tvl(self):
        """Pools below min_tvl are excluded."""
        client = self._client_with_pools()
        results = client.search(min_tvl=1_000_000)
        for p in results:
            self.assertGreaterEqual(p["tvlUsd"], 1_000_000)
        # pool-tiny has tvlUsd=10_000 and should be absent
        tiny_ids = [p["pool"] for p in results if p["pool"] == "pool-tiny"]
        self.assertEqual(tiny_ids, [])

    def test_27_search_with_no_criteria_returns_all_above_min_tvl(self):
        """search() with no filters returns all pools at or above default min_tvl."""
        client = self._client_with_pools()
        results = client.search()
        # Default min_tvl=1_000_000 excludes pool-tiny (tvlUsd=10_000)
        self.assertEqual(len(results), len(SAMPLE_POOLS) - 1)

    def test_28_search_combined_criteria(self):
        """Combined project + symbol_kw + chain filters all apply."""
        client = self._client_with_pools()
        results = client.search(project="aave-v3", symbol_kw="USDC", chain="Ethereum")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["pool"], "pool-aave-usdc")

    def test_29_search_returns_empty_list_on_no_match(self):
        """search() returns [] when nothing matches."""
        client = self._client_with_pools()
        results = client.search(project="nonexistent-protocol-xyz")
        self.assertEqual(results, [])

    def test_30_search_min_tvl_zero_includes_all(self):
        """min_tvl=0 disables TVL filtering."""
        client = self._client_with_pools()
        results = client.search(min_tvl=0)
        self.assertEqual(len(results), len(SAMPLE_POOLS))


# ---------------------------------------------------------------------------
# 5. top_apy
# ---------------------------------------------------------------------------

class TestTopApy(unittest.TestCase):

    def _client_with_pools(self):
        client = DeFiLlamaClient()
        client._pools_cache = list(SAMPLE_POOLS)
        client._pools_cache_time = time.monotonic()
        return client

    def test_31_top_apy_returns_sorted_list(self):
        """top_apy() returns pools sorted by APY descending."""
        client = self._client_with_pools()
        results = client.top_apy("aave-v3")
        apys = [p["apy"] for p in results]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_32_top_apy_respects_n(self):
        """top_apy() respects the n parameter."""
        client = self._client_with_pools()
        results = client.top_apy("aave-v3", n=2)
        self.assertLessEqual(len(results), 2)

    def test_33_top_apy_returns_empty_for_unknown_project(self):
        """top_apy() returns [] for projects with no pools."""
        client = self._client_with_pools()
        results = client.top_apy("no-such-project-xyz")
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# 6. clear_cache
# ---------------------------------------------------------------------------

class TestClearCache(unittest.TestCase):

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_34_clear_cache_resets_cache(self, mock_urlopen):
        """clear_cache() sets _pools_cache to None and time to 0."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient()
        client.fetch_pools()
        self.assertIsNotNone(client._pools_cache)
        client.clear_cache()
        self.assertIsNone(client._pools_cache)
        self.assertEqual(client._pools_cache_time, 0.0)

    @patch("spa_core.utils.defillama.urllib.request.urlopen")
    def test_35_clear_cache_forces_refetch(self, mock_urlopen):
        """After clear_cache(), next fetch_pools() goes to network."""
        mock_urlopen.return_value = _mock_urlopen(_make_pools_response(SAMPLE_POOLS))
        client = DeFiLlamaClient()
        client.fetch_pools()   # call 1
        client.clear_cache()
        client.fetch_pools()   # call 2 — must hit network again
        self.assertEqual(mock_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
tests/test_defillama_v2.py

Sprint v11.19 — MP-1503: DeFiLlama client v2 — 25 tests covering:
  - TTL cache (hit / miss / expiry / force-refresh)
  - Retry with exponential backoff (3 attempts)
  - Rate-limit guard (≥ 1 req/sec between calls)
  - Cache hit/miss logging and stats
  - get_yields() with chain filter
  - Backward compatibility (fetch_pools, search, top_apy, pool_apy)
"""
from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.utils.defillama import DeFiLlamaClient, CACHE_TTL_SECONDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data: object, status: str = "success") -> bytes:
    return json.dumps({"status": status, "data": data}).encode()


def _pool(project: str, chain: str = "Ethereum", apy: float = 5.0,
          tvl: float = 5_000_000, symbol: str = "USDC") -> dict:
    return {"project": project, "chain": chain, "apy": apy,
            "tvlUsd": tvl, "symbol": symbol}


# ---------------------------------------------------------------------------
# 1. TTL Cache — basic hit / miss
# ---------------------------------------------------------------------------

class TestCacheBasic(unittest.TestCase):

    def _client_with_mock_fetch(self):
        """Return client + mock that records _fetch_json call count."""
        client = DeFiLlamaClient(cache_ttl=300, min_request_interval=0)
        pools = [_pool("aave-v3")]
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        return client, pools

    def test_first_call_is_cache_miss(self):
        """First fetch_pools() must be a cache miss."""
        client, _ = self._client_with_mock_fetch()
        client.fetch_pools()
        assert client.cache_stats()["misses"] == 1

    def test_second_call_is_cache_hit(self):
        """Second fetch_pools() within TTL must be a cache hit."""
        client, _ = self._client_with_mock_fetch()
        client.fetch_pools()
        client.fetch_pools()
        stats = client.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_cache_hit_does_not_call_fetch_json(self):
        """On cache hit, _fetch_json must not be called again."""
        client, _ = self._client_with_mock_fetch()
        client.fetch_pools()
        client.fetch_pools()
        assert client._fetch_json.call_count == 1  # only 1 network call

    def test_force_refresh_bypasses_cache(self):
        """force=True must bypass cache and call _fetch_json again."""
        client, _ = self._client_with_mock_fetch()
        client.fetch_pools()
        client.fetch_pools(force=True)
        assert client._fetch_json.call_count == 2

    def test_cache_stats_initial_zeros(self):
        """Fresh client has zero hits and misses."""
        client = DeFiLlamaClient()
        stats = client.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["cached_entries"] == 0

    def test_clear_cache_resets_entries(self):
        """clear_cache() must empty _cache and _cache_timestamps."""
        client, _ = self._client_with_mock_fetch()
        client.fetch_pools()
        assert client.cache_stats()["cached_entries"] == 1
        client.clear_cache()
        assert client.cache_stats()["cached_entries"] == 0


# ---------------------------------------------------------------------------
# 2. TTL expiry
# ---------------------------------------------------------------------------

class TestCacheTTL(unittest.TestCase):

    def test_cache_expires_after_ttl(self):
        """Entry created just-past TTL must trigger a miss on next call."""
        client = DeFiLlamaClient(cache_ttl=1, min_request_interval=0)
        pools = [_pool("morpho")]
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        client.fetch_pools()
        # Simulate cache entry being older than TTL
        for key in list(client._cache_timestamps):
            client._cache_timestamps[key] -= 2  # make it 2s old
        client.fetch_pools()
        assert client._fetch_json.call_count == 2

    def test_unexpired_cache_is_used(self):
        """Entry within TTL must not trigger another network call."""
        client = DeFiLlamaClient(cache_ttl=300, min_request_interval=0)
        pools = [_pool("compound")]
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        client.fetch_pools()
        for key in list(client._cache_timestamps):
            client._cache_timestamps[key] -= 150  # 150s old — still fresh
        client.fetch_pools()
        assert client._fetch_json.call_count == 1

    def test_default_cache_ttl_is_300(self):
        """Default CACHE_TTL_SECONDS == 300 seconds."""
        assert CACHE_TTL_SECONDS == 300
        client = DeFiLlamaClient()
        assert client._cache_ttl == 300


# ---------------------------------------------------------------------------
# 3. Retry with exponential backoff
# ---------------------------------------------------------------------------

class TestRetry(unittest.TestCase):

    def test_retry_called_max_times_on_failure(self):
        """On total network failure, _fetch_json is called max_retries times."""
        client = DeFiLlamaClient(
            max_retries=3,
            retry_base_delay=0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(return_value=None)
        result = client.fetch_pools()
        assert result == []
        assert client._fetch_json.call_count == 3

    def test_retry_succeeds_on_second_attempt(self):
        """Returns data when second attempt succeeds."""
        pools = [_pool("aave-v3")]
        client = DeFiLlamaClient(
            max_retries=3,
            retry_base_delay=0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(
            side_effect=[None, {"status": "success", "data": pools}]
        )
        result = client.fetch_pools()
        assert len(result) == 1
        assert result[0]["project"] == "aave-v3"

    def test_retry_succeeds_on_third_attempt(self):
        """Returns data when third (last) attempt succeeds."""
        pools = [_pool("yearn")]
        client = DeFiLlamaClient(
            max_retries=3,
            retry_base_delay=0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(
            side_effect=[None, None, {"status": "success", "data": pools}]
        )
        result = client.fetch_pools()
        assert len(result) == 1

    def test_no_retry_on_first_success(self):
        """On immediate success, _fetch_json is called exactly once."""
        pools = [_pool("aave-v3")]
        client = DeFiLlamaClient(
            max_retries=3,
            retry_base_delay=0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        client.fetch_pools()
        assert client._fetch_json.call_count == 1

    def test_sleep_called_between_retries(self):
        """time.sleep() must be called (max_retries - 1) times on total failure."""
        client = DeFiLlamaClient(
            max_retries=3,
            retry_base_delay=1.0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(return_value=None)
        with patch("spa_core.utils.defillama.time.sleep") as mock_sleep:
            client._fetch_json_with_retry("http://fake")
        # sleep called between attempts 1→2 and 2→3
        assert mock_sleep.call_count == 2

    def test_backoff_doubles_each_retry(self):
        """Backoff delays must double: base, base*2."""
        client = DeFiLlamaClient(
            max_retries=3,
            retry_base_delay=1.0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(return_value=None)
        sleep_calls = []
        with patch("spa_core.utils.defillama.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            client._fetch_json_with_retry("http://fake")
        # First sleep = 1.0, second = 2.0
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0


# ---------------------------------------------------------------------------
# 4. Rate-limit guard
# ---------------------------------------------------------------------------

class TestRateLimit(unittest.TestCase):

    def test_rate_limit_sleeps_when_too_fast(self):
        """_rate_limit must sleep if called faster than min_request_interval."""
        client = DeFiLlamaClient(min_request_interval=1.0)
        client._last_request_time = time.monotonic()  # just now
        sleep_calls = []
        with patch("spa_core.utils.defillama.time.sleep",
                   side_effect=lambda s: sleep_calls.append(s)):
            client._rate_limit()
        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0

    def test_rate_limit_no_sleep_after_interval(self):
        """_rate_limit must not sleep if enough time has passed."""
        client = DeFiLlamaClient(min_request_interval=1.0)
        client._last_request_time = time.monotonic() - 2.0  # 2s ago
        with patch("spa_core.utils.defillama.time.sleep") as mock_sleep:
            client._rate_limit()
        mock_sleep.assert_not_called()

    def test_rate_limit_updates_last_request_time(self):
        """_rate_limit must update _last_request_time after executing."""
        client = DeFiLlamaClient(min_request_interval=0)
        before = time.monotonic()
        client._rate_limit()
        assert client._last_request_time >= before

    def test_min_request_interval_configurable(self):
        """min_request_interval is stored from constructor."""
        client = DeFiLlamaClient(min_request_interval=2.5)
        assert client._min_request_interval == 2.5


# ---------------------------------------------------------------------------
# 5. get_yields() — chain filter
# ---------------------------------------------------------------------------

class TestGetYields(unittest.TestCase):

    def _seeded_client(self) -> DeFiLlamaClient:
        client = DeFiLlamaClient(cache_ttl=300, min_request_interval=0)
        pools = [
            _pool("aave-v3", chain="Ethereum"),
            _pool("aave-v3", chain="Arbitrum"),
            _pool("compound", chain="Ethereum"),
        ]
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        return client

    def test_get_yields_no_filter_returns_all(self):
        client = self._seeded_client()
        result = client.get_yields()
        assert len(result) == 3

    def test_get_yields_chain_filter(self):
        client = self._seeded_client()
        result = client.get_yields(chain="Ethereum")
        assert len(result) == 2
        assert all(p["chain"] == "Ethereum" for p in result)

    def test_get_yields_chain_case_insensitive(self):
        client = self._seeded_client()
        result = client.get_yields(chain="arbitrum")
        assert len(result) == 1

    def test_get_yields_empty_for_unknown_chain(self):
        client = self._seeded_client()
        result = client.get_yields(chain="Polygon")
        assert result == []


# ---------------------------------------------------------------------------
# 6. Backward compatibility & edge cases
# ---------------------------------------------------------------------------

class TestBackwardCompat(unittest.TestCase):

    def test_fetch_pools_returns_list(self):
        client = DeFiLlamaClient(min_request_interval=0)
        client._fetch_json = MagicMock(return_value=None)
        assert isinstance(client.fetch_pools(), list)

    def test_pool_apy_returns_none_on_empty_id(self):
        client = DeFiLlamaClient(min_request_interval=0)
        assert client.pool_apy("") is None

    def test_pool_apy_returns_float(self):
        chart_data = {"status": "success", "data": [{"apy": 5.5}]}
        client = DeFiLlamaClient(cache_ttl=300, min_request_interval=0)
        client._fetch_json = MagicMock(return_value=chart_data)
        result = client.pool_apy("abc123")
        assert isinstance(result, float)
        assert result == 5.5

    def test_search_returns_subset(self):
        client = DeFiLlamaClient(cache_ttl=300, min_request_interval=0)
        pools = [_pool("aave-v3"), _pool("compound")]
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        result = client.search(project="aave-v3")
        assert len(result) == 1
        assert result[0]["project"] == "aave-v3"

    def test_top_apy_sorted_descending(self):
        client = DeFiLlamaClient(cache_ttl=300, min_request_interval=0)
        pools = [
            _pool("aave-v3", apy=3.0),
            _pool("aave-v3", apy=7.0),
            _pool("aave-v3", apy=5.0),
        ]
        client._fetch_json = MagicMock(
            return_value={"status": "success", "data": pools}
        )
        result = client.top_apy("aave-v3", n=2)
        assert result[0]["apy"] == 7.0
        assert result[1]["apy"] == 5.0

    def test_network_error_returns_empty_list(self):
        """Network error must return empty list, not raise."""
        client = DeFiLlamaClient(
            max_retries=1,
            retry_base_delay=0,
            min_request_interval=0,
        )
        client._fetch_json = MagicMock(return_value=None)
        result = client.fetch_pools()
        assert result == []


if __name__ == "__main__":
    unittest.main()

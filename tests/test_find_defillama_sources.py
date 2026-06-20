"""
tests/test_find_defillama_sources.py

30 unit tests for scripts/find_defillama_sources.py.
All HTTP calls are mocked — no real network requests.
"""

import json
import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock
from io import BytesIO

# Make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.find_defillama_sources import (
    fetch_pools,
    search_pools,
    format_pool,
    discover_all,
    save_discovery,
    TARGET_PROTOCOLS,
    MIN_TVL,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MOCK_POOLS = [
    {
        "pool": "aaa-bbb-ccc-111",
        "project": "gmx-v2",
        "symbol": "BTC-USD-GM",
        "chain": "Arbitrum",
        "apy": 18.5,
        "tvlUsd": 50_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-222",
        "project": "gmx-v2",
        "symbol": "ETH-USD-GM",
        "chain": "Arbitrum",
        "apy": 14.2,
        "tvlUsd": 30_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-333",
        "project": "aave-v3",
        "symbol": "USDC",
        "chain": "Arbitrum",
        "apy": 4.5,
        "tvlUsd": 200_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-444",
        "project": "morpho",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 6.8,
        "tvlUsd": 80_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-555",
        "project": "sky",
        "symbol": "sUSDS",
        "chain": "Ethereum",
        "apy": 5.0,
        "tvlUsd": 120_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-666",
        "project": "spark",
        "symbol": "sUSDS",
        "chain": "Ethereum",
        "apy": 4.9,
        "tvlUsd": 95_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-777",
        "project": "pendle",
        "symbol": "PT-eUSDE",
        "chain": "Ethereum",
        "apy": 22.0,
        "tvlUsd": 15_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-888",
        "project": "uniswap-v3",
        "symbol": "PAXG-ETH",
        "chain": "Ethereum",
        "apy": 2.1,
        "tvlUsd": 5_000_000,
    },
    {
        "pool": "aaa-bbb-ccc-999",
        "project": "ondo",
        "symbol": "OUSG",
        "chain": "Ethereum",
        "apy": 5.1,
        "tvlUsd": 10_000_000,
    },
    {
        "pool": "low-tvl-pool",
        "project": "tiny-protocol",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 99.9,
        "tvlUsd": 500_000,  # below MIN_TVL
    },
    {
        "pool": "btc-usdc-lp",
        "project": "uniswap-v3",
        "symbol": "BTC-USDC",
        "chain": "Arbitrum",
        "apy": 12.0,
        "tvlUsd": 8_000_000,
    },
]


def _make_response(data: dict) -> MagicMock:
    """Return a mock that mimics urllib.request.urlopen context manager."""
    body = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestFetchPools(unittest.TestCase):
    """Tests for fetch_pools()"""

    # 1. Returns list on success with "data" wrapper
    def test_fetch_returns_list_from_data_key(self):
        mock_resp = _make_response({"status": "ok", "data": MOCK_POOLS})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_pools(timeout=5)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(MOCK_POOLS))

    # 2. Returns list when API returns bare list
    def test_fetch_returns_list_from_bare_array(self):
        mock_resp = _make_response(MOCK_POOLS)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_pools(timeout=5)
        self.assertIsInstance(result, list)

    # 3. Returns empty list on network error (no exception raised)
    def test_fetch_returns_empty_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = fetch_pools(timeout=5)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    # 4. Returns empty list on timeout
    def test_fetch_returns_empty_on_timeout(self):
        import socket
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            result = fetch_pools(timeout=1)
        self.assertEqual(result, [])

    # 5. Returns empty list on JSON parse error
    def test_fetch_returns_empty_on_json_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not valid json {{{"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_pools(timeout=5)
        self.assertEqual(result, [])

    # 6. Returns empty list when API returns unexpected structure
    def test_fetch_returns_empty_on_unexpected_structure(self):
        mock_resp = _make_response({"status": "ok", "pools": MOCK_POOLS})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_pools(timeout=5)
        self.assertEqual(result, [])


class TestSearchPools(unittest.TestCase):
    """Tests for search_pools()"""

    # 7. Empty list input returns empty list
    def test_search_empty_input_returns_empty(self):
        result = search_pools([])
        self.assertEqual(result, [])

    # 8. Filter by project (exact, case-insensitive)
    def test_search_by_project(self):
        result = search_pools(MOCK_POOLS, project="gmx-v2")
        self.assertTrue(all(p["project"] == "gmx-v2" for p in result))
        self.assertEqual(len(result), 2)

    # 9. Project filter is case-insensitive
    def test_search_project_case_insensitive(self):
        result = search_pools(MOCK_POOLS, project="GMX-V2")
        self.assertEqual(len(result), 2)

    # 10. Filter by symbol_kw (substring, case-insensitive)
    def test_search_by_symbol_kw(self):
        result = search_pools(MOCK_POOLS, symbol_kw="USDC")
        symbols = [p["symbol"] for p in result]
        self.assertTrue(all("usdc" in s.lower() for s in symbols))
        self.assertGreater(len(result), 0)

    # 11. Symbol filter is case-insensitive
    def test_search_symbol_case_insensitive(self):
        result_upper = search_pools(MOCK_POOLS, symbol_kw="usdc")
        result_lower = search_pools(MOCK_POOLS, symbol_kw="USDC")
        self.assertEqual(len(result_upper), len(result_lower))

    # 12. Filter by chain (case-insensitive)
    def test_search_by_chain(self):
        result = search_pools(MOCK_POOLS, chain="Arbitrum")
        self.assertTrue(all(p["chain"] == "Arbitrum" for p in result))
        self.assertGreater(len(result), 0)

    # 13. Chain filter is case-insensitive
    def test_search_chain_case_insensitive(self):
        result_mixed = search_pools(MOCK_POOLS, chain="arbitrum")
        result_upper = search_pools(MOCK_POOLS, chain="ARBITRUM")
        self.assertEqual(len(result_mixed), len(result_upper))

    # 14. min_tvl filters out pools below threshold
    def test_search_min_tvl_filters_low(self):
        result = search_pools(MOCK_POOLS, min_tvl=MIN_TVL)
        self.assertTrue(all(
            (p.get("tvlUsd") or 0) >= MIN_TVL for p in result
        ))

    # 15. Pool with TVL below MIN_TVL is excluded
    def test_search_low_tvl_pool_excluded(self):
        result = search_pools(MOCK_POOLS, project="tiny-protocol", min_tvl=MIN_TVL)
        self.assertEqual(result, [])

    # 16. Low TVL pool included when min_tvl=0
    def test_search_low_tvl_pool_included_when_min_zero(self):
        result = search_pools(MOCK_POOLS, project="tiny-protocol", min_tvl=0)
        self.assertEqual(len(result), 1)

    # 17. Combined project+symbol+chain filter
    def test_search_combined_filters(self):
        result = search_pools(MOCK_POOLS, project="gmx-v2", symbol_kw="BTC", chain="Arbitrum")
        self.assertEqual(len(result), 1)
        self.assertIn("BTC", result[0]["symbol"])

    # 18. No match returns empty list (not exception)
    def test_search_no_match_returns_empty(self):
        result = search_pools(MOCK_POOLS, project="nonexistent-protocol-xyz")
        self.assertEqual(result, [])

    # 19. None project means any project
    def test_search_none_project_matches_all(self):
        result_none = search_pools(MOCK_POOLS, project=None, min_tvl=0)
        result_all  = search_pools(MOCK_POOLS, min_tvl=0)
        self.assertEqual(len(result_none), len(result_all))

    # 20. sUSDS keyword matches sky and spark pools
    def test_search_susds_finds_sky_and_spark(self):
        result = search_pools(MOCK_POOLS, symbol_kw="sUSDS", chain="Ethereum")
        projects = {p["project"] for p in result}
        self.assertIn("sky", projects)
        self.assertIn("spark", projects)


class TestFormatPool(unittest.TestCase):
    """Tests for format_pool()"""

    def _sample_pool(self):
        return {
            "pool": "abc12345-def6-789a-bcde-f01234567890",
            "project": "test-protocol",
            "symbol": "USDC",
            "chain": "Ethereum",
            "apy": 5.25,
            "tvlUsd": 42_000_000,
        }

    # 21. Returns a string
    def test_format_pool_returns_string(self):
        result = format_pool(self._sample_pool())
        self.assertIsInstance(result, str)

    # 22. Contains Pool ID
    def test_format_pool_contains_pool_id(self):
        pool = self._sample_pool()
        result = format_pool(pool)
        self.assertIn(pool["pool"], result)

    # 23. Contains project name
    def test_format_pool_contains_project(self):
        pool = self._sample_pool()
        result = format_pool(pool)
        self.assertIn(pool["project"], result)

    # 24. Contains symbol
    def test_format_pool_contains_symbol(self):
        pool = self._sample_pool()
        result = format_pool(pool)
        self.assertIn(pool["symbol"], result)

    # 25. Contains chain
    def test_format_pool_contains_chain(self):
        pool = self._sample_pool()
        result = format_pool(pool)
        self.assertIn(pool["chain"], result)

    # 26. Handles missing fields gracefully
    def test_format_pool_handles_missing_fields(self):
        result = format_pool({})
        self.assertIsInstance(result, str)
        self.assertIn("N/A", result)


class TestDiscoverAll(unittest.TestCase):
    """Tests for discover_all()"""

    # 27. Returns dict with keys from TARGET_PROTOCOLS
    def test_discover_all_returns_dict_with_all_keys(self):
        result = discover_all(MOCK_POOLS)
        expected_keys = {p["name"] for p in TARGET_PROTOCOLS}
        self.assertEqual(set(result.keys()), expected_keys)

    # 28. Values are lists
    def test_discover_all_values_are_lists(self):
        result = discover_all(MOCK_POOLS)
        for name, pools in result.items():
            self.assertIsInstance(pools, list, f"{name} should be a list")

    # 29. discover_all on empty pools returns empty lists per protocol
    def test_discover_all_empty_input(self):
        result = discover_all([])
        for name, pools in result.items():
            self.assertEqual(pools, [], f"{name} should be empty list")


class TestSaveDiscovery(unittest.TestCase):
    """Tests for save_discovery()"""

    # 30. Creates a file with valid JSON
    def test_save_discovery_creates_file(self):
        results = {"sky_susds": MOCK_POOLS[:2], "spark_susds": MOCK_POOLS[2:4]}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "source_discovery.json")
            returned_path = save_discovery(results, path=path)
            self.assertTrue(os.path.exists(returned_path))
            with open(returned_path, "r") as fh:
                data = json.load(fh)
            self.assertIn("results", data)
            self.assertIn("sky_susds", data["results"])


class TestTargetProtocols(unittest.TestCase):
    """Structural tests for TARGET_PROTOCOLS constant"""

    def test_target_protocols_is_list(self):
        self.assertIsInstance(TARGET_PROTOCOLS, list)

    def test_target_protocols_contains_sky_susds(self):
        names = [p["name"] for p in TARGET_PROTOCOLS]
        self.assertIn("sky_susds", names)

    def test_target_protocols_contains_spark_susds(self):
        names = [p["name"] for p in TARGET_PROTOCOLS]
        self.assertIn("spark_susds", names)

    def test_target_protocols_contains_gmx_v2_btc(self):
        names = [p["name"] for p in TARGET_PROTOCOLS]
        self.assertIn("gmx_v2_btc", names)

    def test_all_target_protocols_have_name_key(self):
        for proto in TARGET_PROTOCOLS:
            self.assertIn("name", proto, f"Missing 'name' in {proto}")

    def test_all_target_protocols_have_chain_key(self):
        for proto in TARGET_PROTOCOLS:
            self.assertIn("chain", proto, f"Missing 'chain' in {proto}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

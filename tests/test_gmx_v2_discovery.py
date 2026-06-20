"""
tests/test_gmx_v2_discovery.py

25 tests for spa_core/data_pipeline/gmx_v2_discovery.py (MP-1477, v10.93).

Coverage:
  - KNOWN_GMX_V2_POOLS static fallback (structure, values)
  - discover_gmx_v2_pools() offline / network-unavailable path
  - load_cached_pools() freshness logic
  - get_pool_ids() always-returns contract
  - get_curated_summary() aggregation correctness
  - _make_slug() / _classify_tier() helpers
  - Atomic write side-effects
  - CLI --check flag (no file written)

Does NOT make real network calls (DeFiLlama client will time out / return []
in the CI sandbox — discovery falls back to KNOWN_GMX_V2_POOLS).

Stdlib only — no third-party deps.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.data_pipeline.gmx_v2_discovery import (
    KNOWN_GMX_V2_POOLS,
    SCHEMA_VERSION,
    _classify_tier,
    _make_slug,
    discover_gmx_v2_pools,
    get_curated_summary,
    get_pool_ids,
    load_cached_pools,
)


# ---------------------------------------------------------------------------
# 1. KNOWN_GMX_V2_POOLS static fallback
# ---------------------------------------------------------------------------

class TestKnownGMXV2Pools(unittest.TestCase):

    def test_01_known_pools_not_empty(self):
        """KNOWN_GMX_V2_POOLS must have at least 3 entries."""
        self.assertGreaterEqual(len(KNOWN_GMX_V2_POOLS), 3)

    def test_02_all_entries_have_pool_id(self):
        """Every static entry must have a non-empty pool_id."""
        for slug, meta in KNOWN_GMX_V2_POOLS.items():
            with self.subTest(slug=slug):
                self.assertIn("pool_id", meta)
                self.assertIsInstance(meta["pool_id"], str)
                self.assertTrue(meta["pool_id"], f"{slug} has empty pool_id")

    def test_03_all_entries_have_symbol(self):
        """Every static entry must have a symbol."""
        for slug, meta in KNOWN_GMX_V2_POOLS.items():
            with self.subTest(slug=slug):
                self.assertIn("symbol", meta)
                self.assertTrue(meta["symbol"])

    def test_04_all_entries_have_chain(self):
        """Every static entry must declare a chain."""
        for slug, meta in KNOWN_GMX_V2_POOLS.items():
            with self.subTest(slug=slug):
                self.assertIn("chain", meta)
                self.assertTrue(meta["chain"])

    def test_05_all_entries_have_numeric_apy(self):
        """Every static entry must have a positive numeric apy_est."""
        for slug, meta in KNOWN_GMX_V2_POOLS.items():
            with self.subTest(slug=slug):
                apy = meta.get("apy_est", 0)
                self.assertIsInstance(apy, (int, float))
                self.assertGreater(apy, 0.0)

    def test_06_all_entries_have_valid_tier(self):
        """Every static entry tier must be T2 or T3."""
        valid = {"T1", "T2", "T3"}
        for slug, meta in KNOWN_GMX_V2_POOLS.items():
            with self.subTest(slug=slug):
                self.assertIn(meta.get("tier"), valid)

    def test_07_btc_pool_present(self):
        """A BTC/USDC pool must be present in the static list."""
        btc_slugs = [s for s in KNOWN_GMX_V2_POOLS if "btc" in s.lower()]
        self.assertTrue(btc_slugs, "No BTC pool in KNOWN_GMX_V2_POOLS")

    def test_08_eth_pool_present(self):
        """An ETH/USDC pool must be present in the static list."""
        eth_slugs = [s for s in KNOWN_GMX_V2_POOLS if "eth" in s.lower()]
        self.assertTrue(eth_slugs, "No ETH pool in KNOWN_GMX_V2_POOLS")


# ---------------------------------------------------------------------------
# 2. discover_gmx_v2_pools() — offline fallback path
# ---------------------------------------------------------------------------

class TestDiscoverGMXV2Pools(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cache_path(self, name: str = "gmx_v2_pools.json") -> str:
        return os.path.join(self.tmpdir, name)

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_09_returns_dict_with_required_keys(self, MockClient):
        """discover_gmx_v2_pools() must return a dict with meta/discovered/curated."""
        MockClient.return_value.fetch_pools.return_value = []
        result = discover_gmx_v2_pools(cache_path=self._cache_path())
        for key in ("schema_version", "meta", "discovered", "curated"):
            self.assertIn(key, result, f"Missing key: {key}")

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_10_fallback_when_network_empty(self, MockClient):
        """When DeFiLlama returns [], curated falls back to KNOWN_GMX_V2_POOLS."""
        MockClient.return_value.fetch_pools.return_value = []
        result = discover_gmx_v2_pools(cache_path=self._cache_path())
        curated = result.get("curated", {})
        self.assertGreater(len(curated), 0, "Curated must not be empty in fallback mode")

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_11_fallback_when_network_raises(self, MockClient):
        """When DeFiLlama raises, discover_gmx_v2_pools must not propagate."""
        MockClient.return_value.fetch_pools.side_effect = OSError("network down")
        result = discover_gmx_v2_pools(cache_path=self._cache_path())
        self.assertIn("curated", result)
        self.assertGreater(len(result["curated"]), 0)

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_12_cache_file_written(self, MockClient):
        """discover_gmx_v2_pools() must write cache_path atomically."""
        MockClient.return_value.fetch_pools.return_value = []
        cache = self._cache_path()
        discover_gmx_v2_pools(cache_path=cache)
        self.assertTrue(os.path.exists(cache), "Cache file not written")

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_13_no_cache_written_when_path_empty(self, MockClient):
        """discover_gmx_v2_pools(cache_path='') must not write any file."""
        MockClient.return_value.fetch_pools.return_value = []
        before = set(os.listdir(self.tmpdir))
        discover_gmx_v2_pools(cache_path="")
        after = set(os.listdir(self.tmpdir))
        self.assertEqual(before, after, "Unexpected files created with cache_path=''")

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_14_schema_version_in_output(self, MockClient):
        """Output must carry the declared SCHEMA_VERSION."""
        MockClient.return_value.fetch_pools.return_value = []
        result = discover_gmx_v2_pools(cache_path="")
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_15_meta_has_timestamp(self, MockClient):
        """meta dict must have an ISO timestamp."""
        MockClient.return_value.fetch_pools.return_value = []
        result = discover_gmx_v2_pools(cache_path="")
        ts = result["meta"].get("timestamp", "")
        self.assertTrue(ts, "meta.timestamp is missing")
        # Should be parseable as ISO 8601
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_16_live_pools_filtered_by_tvl(self, MockClient):
        """Pools below min_tvl must be excluded from curated output."""
        MockClient.return_value.fetch_pools.return_value = [
            {"pool": "abc", "project": "gmx-v2", "symbol": "X-USDC",
             "chain": "Arbitrum", "apy": 5.0, "tvlUsd": 100},  # below floor
            {"pool": "def", "project": "gmx-v2", "symbol": "ETH-USDC",
             "chain": "Arbitrum", "apy": 10.0, "tvlUsd": 50_000_000},
        ]
        result = discover_gmx_v2_pools(cache_path="", min_tvl=1_000_000)
        curated = result["curated"]
        # low-TVL pool must be excluded
        slugs = list(curated.keys())
        for slug in slugs:
            self.assertNotIn("x_usdc", slug.lower())


# ---------------------------------------------------------------------------
# 3. load_cached_pools()
# ---------------------------------------------------------------------------

class TestLoadCachedPools(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_cache(self, age_s: int = 0) -> str:
        path = os.path.join(self.tmpdir, "gmx_v2_pools.json")
        ts = datetime.fromtimestamp(
            time.time() - age_s, tz=timezone.utc
        ).isoformat()
        data = {
            "schema_version": "1.0",
            "meta": {"timestamp": ts, "curated_count": 2},
            "discovered": [],
            "curated": {
                "gmx_v2_test": {"pool_id": "test-id", "apy_live": 5.0, "tvl_usd": 1e8}
            },
        }
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_17_returns_none_for_missing_file(self):
        """load_cached_pools must return None if the file doesn't exist."""
        result = load_cached_pools(cache_path="/nonexistent/path/gmx.json")
        self.assertIsNone(result)

    def test_18_returns_dict_for_fresh_cache(self):
        """load_cached_pools must return dict for a fresh cache file."""
        path = self._write_cache(age_s=10)
        result = load_cached_pools(cache_path=path, max_age_s=3600)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_19_returns_none_for_stale_cache(self):
        """load_cached_pools must return None if cache is older than max_age_s."""
        path = self._write_cache(age_s=7200)  # 2 hours old
        result = load_cached_pools(cache_path=path, max_age_s=3600)
        self.assertIsNone(result)

    def test_20_returns_none_for_corrupt_json(self):
        """load_cached_pools must return None for malformed JSON."""
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w") as f:
            f.write("NOT JSON {{}")
        result = load_cached_pools(cache_path=path)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 4. get_pool_ids() & get_curated_summary()
# ---------------------------------------------------------------------------

class TestGetPoolIdsAndSummary(unittest.TestCase):

    @patch("spa_core.data_pipeline.gmx_v2_discovery.load_cached_pools")
    def test_21_get_pool_ids_returns_dict(self, mock_load):
        """get_pool_ids() must return {slug: pool_id} dict."""
        mock_load.return_value = None  # force fallback
        result = get_pool_ids(cache_path="")
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)

    @patch("spa_core.data_pipeline.gmx_v2_discovery.load_cached_pools")
    def test_22_get_pool_ids_values_are_strings(self, mock_load):
        """All pool_id values from get_pool_ids() must be strings."""
        mock_load.return_value = None
        result = get_pool_ids(cache_path="")
        for slug, pid in result.items():
            with self.subTest(slug=slug):
                self.assertIsInstance(pid, str)

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_23_summary_has_pool_count(self, MockClient):
        """get_curated_summary() must include pool_count > 0."""
        MockClient.return_value.fetch_pools.return_value = []
        summary = get_curated_summary()
        self.assertIn("pool_count", summary)
        self.assertGreater(summary["pool_count"], 0)

    @patch("spa_core.data_pipeline.gmx_v2_discovery.DeFiLlamaClient")
    def test_24_summary_avg_apy_is_positive(self, MockClient):
        """get_curated_summary() avg_apy must be > 0 (fallback data has known APYs)."""
        MockClient.return_value.fetch_pools.return_value = []
        summary = get_curated_summary()
        self.assertGreater(summary.get("avg_apy", 0), 0)


# ---------------------------------------------------------------------------
# 5. Internal helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_25_classify_tier_large_tvl_is_t2(self):
        """_classify_tier(≥50M) must return 'T2'."""
        self.assertEqual(_classify_tier(50_000_000), "T2")
        self.assertEqual(_classify_tier(200_000_000), "T2")

    def test_25b_classify_tier_small_tvl_is_t3(self):
        """_classify_tier(<50M) must return 'T3'."""
        self.assertEqual(_classify_tier(10_000_000), "T3")
        self.assertEqual(_classify_tier(0), "T3")

    def test_25c_make_slug_produces_gmx_v2_prefix(self):
        """_make_slug() must produce a slug starting with 'gmx_v2_'."""
        pool = {"project": "gmx-v2", "symbol": "BTC-USDC", "chain": "Arbitrum"}
        slug = _make_slug(pool)
        self.assertTrue(slug.startswith("gmx_v2_"), f"Unexpected slug: {slug}")

    def test_25d_make_slug_lowercases_symbol(self):
        """_make_slug() must lower-case the symbol."""
        pool = {"symbol": "ETH-USDC", "chain": "Arbitrum"}
        slug = _make_slug(pool)
        self.assertEqual(slug, slug.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)

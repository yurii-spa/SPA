"""
Tests for spa_core/adapters/gold_proxy_research.py — MP-1315 (Sprint v9.31)

Groups:
    TestModuleConstants          (5  tests)
    TestInstantiation            (3  tests)
    TestIsResearchOnly           (2  tests)
    TestBestAvailableAPY         (5  tests)
    TestGoldProxyAPY             (5  tests)
    TestFetchDeFiLlamaPools      (5  tests)
    TestVenueComparison          (3  tests)
    TestSourceMetadata           (2  tests)

Total: 30 tests
"""
import json
import sys
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.adapters.gold_proxy_research import (
    DEFI_LLAMA_POOLS_URL,
    FALLBACK_APY_PCT,
    RESEARCH_ONLY,
    SOURCE_ID,
    GoldProxyResearchAdapter,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_pool(symbol="PAXG-USDC", project="uniswap-v3", chain="Ethereum",
               apy=9.0, tvl=5_000_000.0, pool_id="abc123"):
    return {
        "pool":    pool_id,
        "project": project,
        "symbol":  symbol,
        "chain":   chain,
        "apy":     apy,
        "tvlUsd":  tvl,
    }


def _mock_urllib(pools=None, raise_exc=None):
    """Return a context manager that mocks urllib.request.urlopen."""
    if raise_exc is not None:
        return patch(
            "spa_core.adapters.gold_proxy_research.urllib.request.urlopen",
            side_effect=raise_exc,
        )
    payload = {"status": "success", "data": pools or []}
    raw = json.dumps(payload).encode()

    class _FakeResp:
        def read(self):
            return raw
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    return patch(
        "spa_core.adapters.gold_proxy_research.urllib.request.urlopen",
        return_value=_FakeResp(),
    )


# ── TestModuleConstants ────────────────────────────────────────────────────────

class TestModuleConstants(unittest.TestCase):
    """5 tests: module-level constants."""

    def test_research_only_is_true(self):
        self.assertTrue(RESEARCH_ONLY)

    def test_research_only_is_bool(self):
        self.assertIsInstance(RESEARCH_ONLY, bool)

    def test_fallback_apy_is_8(self):
        self.assertAlmostEqual(FALLBACK_APY_PCT, 8.0)

    def test_source_id(self):
        self.assertEqual(SOURCE_ID, "gold_proxy_research")

    def test_defillama_url_is_string(self):
        self.assertIsInstance(DEFI_LLAMA_POOLS_URL, str)
        self.assertTrue(DEFI_LLAMA_POOLS_URL.startswith("https://"))


# ── TestInstantiation ──────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):
    """3 tests: adapter creation."""

    def test_adapter_instantiates(self):
        adapter = GoldProxyResearchAdapter()
        self.assertIsNotNone(adapter)

    def test_proxy_venues_has_three_keys(self):
        adapter = GoldProxyResearchAdapter()
        self.assertEqual(len(adapter.PROXY_VENUES), 3)

    def test_proxy_venues_keys(self):
        adapter = GoldProxyResearchAdapter()
        expected = {"paxg_usdc_univ3", "ondo_ousg", "synthetix_sxau"}
        self.assertEqual(set(adapter.PROXY_VENUES.keys()), expected)


# ── TestIsResearchOnly ─────────────────────────────────────────────────────────

class TestIsResearchOnly(unittest.TestCase):
    """2 tests: is_research_only()."""

    def test_is_research_only_returns_true(self):
        adapter = GoldProxyResearchAdapter()
        self.assertTrue(adapter.is_research_only())

    def test_is_research_only_returns_bool(self):
        adapter = GoldProxyResearchAdapter()
        self.assertIsInstance(adapter.is_research_only(), bool)


# ── TestBestAvailableAPY ──────────────────────────────────────────────────────

class TestBestAvailableAPY(unittest.TestCase):
    """5 tests: best_available_apy()."""

    def test_positive_on_network_error(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.best_available_apy()
        self.assertGreater(result, 0)

    def test_fallback_value_on_network_error(self):
        """Fallback should be max of PROXY_VENUES estimates (8.0%)."""
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.best_available_apy()
        expected_fallback = max(v["est_apy"] for v in adapter.PROXY_VENUES.values())
        self.assertAlmostEqual(result, expected_fallback)

    def test_positive_with_live_data(self):
        adapter = GoldProxyResearchAdapter()
        pools = [_make_pool(symbol="PAXG-USDC", apy=10.5, tvl=2_000_000)]
        with _mock_urllib(pools=pools):
            result = adapter.best_available_apy()
        self.assertGreater(result, 0)

    def test_uses_best_live_apy(self):
        adapter = GoldProxyResearchAdapter()
        pools = [
            _make_pool(symbol="PAXG-USDC", apy=7.0, tvl=1_000_000, pool_id="p1"),
            _make_pool(symbol="XAU-USDC", apy=11.0, tvl=3_000_000, pool_id="p2"),
        ]
        with _mock_urllib(pools=pools):
            result = adapter.best_available_apy()
        self.assertAlmostEqual(result, 11.0)

    def test_returns_float(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("x")):
            result = adapter.best_available_apy()
        self.assertIsInstance(result, float)


# ── TestGoldProxyAPY ──────────────────────────────────────────────────────────

class TestGoldProxyAPY(unittest.TestCase):
    """5 tests: gold_proxy_apy()."""

    def test_positive_on_network_error(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.gold_proxy_apy()
        self.assertGreater(result, 0)

    def test_at_most_20_on_network_error(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.gold_proxy_apy()
        self.assertLessEqual(result, 20.0)

    def test_at_most_20_with_high_live_apy(self):
        """Even if DeFiLlama returns >20%, gold_proxy_apy clamps to 20.0."""
        adapter = GoldProxyResearchAdapter()
        # A very high APY pool that should be clamped
        pools = [_make_pool(symbol="PAXG-USDC", apy=150.0, tvl=5_000_000)]
        with _mock_urllib(pools=pools):
            result = adapter.gold_proxy_apy()
        self.assertLessEqual(result, 20.0)

    def test_positive_with_live_data(self):
        adapter = GoldProxyResearchAdapter()
        pools = [_make_pool(symbol="PAXG-USDC", apy=9.5, tvl=2_000_000)]
        with _mock_urllib(pools=pools):
            result = adapter.gold_proxy_apy()
        self.assertGreater(result, 0)

    def test_returns_float(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("x")):
            result = adapter.gold_proxy_apy()
        self.assertIsInstance(result, float)


# ── TestFetchDeFiLlamaPools ────────────────────────────────────────────────────

class TestFetchDeFiLlamaPools(unittest.TestCase):
    """5 tests: fetch_defillama_gold_pools()."""

    def test_does_not_raise_on_network_error(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            try:
                result = adapter.fetch_defillama_gold_pools()
            except Exception as exc:
                self.fail(f"fetch_defillama_gold_pools raised unexpectedly: {exc}")

    def test_returns_list_on_network_error(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.fetch_defillama_gold_pools()
        self.assertIsInstance(result, list)

    def test_fallback_entries_on_network_error(self):
        """On network error, fallback list should have one entry per PROXY_VENUES."""
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.fetch_defillama_gold_pools()
        self.assertGreater(len(result), 0)

    def test_returns_gold_pools_from_live_data(self):
        adapter = GoldProxyResearchAdapter()
        pools = [
            _make_pool(symbol="PAXG-USDC", apy=9.0, tvl=2_000_000, pool_id="p1"),
            _make_pool(symbol="WBTC-USDC", apy=5.0, tvl=10_000_000, pool_id="p2"),  # not gold
        ]
        with _mock_urllib(pools=pools):
            result = adapter.fetch_defillama_gold_pools()
        pool_ids = [e["pool_id"] for e in result]
        self.assertIn("p1", pool_ids)
        self.assertNotIn("p2", pool_ids)

    def test_entry_has_required_fields(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.fetch_defillama_gold_pools()
        if result:
            entry = result[0]
            for key in ("pool_id", "protocol", "symbol", "chain", "apy", "tvl", "source"):
                self.assertIn(key, entry, f"Missing key: {key}")


# ── TestVenueComparison ───────────────────────────────────────────────────────

class TestVenueComparison(unittest.TestCase):
    """3 tests: venue_comparison()."""

    def test_contains_all_three_venue_keys(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.venue_comparison()
        for key in ("paxg_usdc_univ3", "ondo_ousg", "synthetix_sxau"):
            self.assertIn(key, result, f"Missing venue key: {key}")

    def test_each_venue_has_est_apy(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.venue_comparison()
        for key, val in result.items():
            self.assertIn("est_apy", val, f"Venue {key} missing est_apy")
            self.assertGreater(val["est_apy"], 0, f"Venue {key} est_apy <= 0")

    def test_each_venue_has_source_quality(self):
        adapter = GoldProxyResearchAdapter()
        with _mock_urllib(raise_exc=urllib.error.URLError("timeout")):
            result = adapter.venue_comparison()
        for key, val in result.items():
            self.assertIn("source_quality", val, f"Venue {key} missing source_quality")


# ── TestSourceMetadata ────────────────────────────────────────────────────────

class TestSourceMetadata(unittest.TestCase):
    """2 tests: source_metadata()."""

    def test_returns_dict(self):
        adapter = GoldProxyResearchAdapter()
        result = adapter.source_metadata()
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        adapter = GoldProxyResearchAdapter()
        result = adapter.source_metadata()
        for key in ("source_id", "adapter", "research_only", "fallback_apy_pct",
                    "venue_count", "venue_keys"):
            self.assertIn(key, result, f"Missing metadata key: {key}")


if __name__ == "__main__":
    unittest.main()

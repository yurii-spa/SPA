"""Tests for spa_core/feeds/defi_llama_feed.py (v1197 — retry/backoff + CoinGecko fallback).

Covers:
    * DefiLlamaFeed.get_pool  — pool selection, substring matching, liveness filters
    * DefiLlamaFeed.get_apy   — decimal conversion (percentage / 100)
    * DefiLlamaFeed.get_tvl   — USD pass-through
    * DefiLlamaFeed caching   — TTL hit/miss, invalidate_cache
    * DefiLlamaFeed errors    — network failure, bad payload, disabled feed
    * Retry / backoff logic   — MAX_RETRIES, exponential delays, UA rotation
    * CoinGecko fallback      — called on DeFiLlama failure, known/unknown project,
                                network errors, live_apy_fallback_source field
    * live_apy_fallback_source field in get_pool() result ("defillama" / "coingecko")
    * get_apy() module function — slug resolution via PROTOCOL_MAP
    * Adapter integration     — yearn_v3, morpho_blue, euler_v2, maple with
                                injected DefiLlamaFeed mock

All tests are offline — urllib.request.urlopen / time.sleep are patched throughout.
No real network is touched.

Run:
    python3 -m pytest spa_core/tests/test_defi_llama_feed.py -v
    # or
    python3 -m unittest spa_core.tests.test_defi_llama_feed -v
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.feeds.defi_llama_feed import (  # noqa: E402
    CACHE_TTL,
    COINGECKO_COIN_IDS,
    COINGECKO_MARKETS_URL,
    DEFILLAMA_POOLS_URL,
    MAX_RETRIES,
    MIN_TVL_USD,
    PROTOCOL_MAP,
    DefiLlamaFeed,
    get_apy as module_get_apy,
)
from spa_core.adapters.yearn_v3 import YearnV3Adapter      # noqa: E402
from spa_core.adapters.morpho_blue import MorphoBlueAdapter  # noqa: E402
from spa_core.adapters.euler_v2 import EulerV2Adapter       # noqa: E402
from spa_core.adapters.maple import MapleAdapter            # noqa: E402

import pytest  # noqa: E402
import spa_core.feeds.defi_llama_feed as _dlf  # noqa: E402

# Canonical (production) retry constants. The root tests/conftest.py mutates the
# live module-level MAX_RETRIES/BACKOFF_BASE for speed in the *adapter* tests
# (which hit the network-blocked urlopen). These tests, however, mock urlopen
# directly and assert the real retry/backoff semantics, so we restore the true
# source values for the duration of every test in this module.
_REAL_MAX_RETRIES = 3
_REAL_BACKOFF_BASE = 1.0


@pytest.fixture(autouse=True)
def _restore_retry_constants():
    """Restore production MAX_RETRIES/BACKOFF_BASE for retry/backoff assertions."""
    global MAX_RETRIES  # noqa: PLW0603 — rebind the test-module snapshot used in asserts
    saved_retries = _dlf.MAX_RETRIES
    saved_backoff = _dlf.BACKOFF_BASE
    saved_module_snapshot = MAX_RETRIES
    _dlf.MAX_RETRIES = _REAL_MAX_RETRIES
    _dlf.BACKOFF_BASE = _REAL_BACKOFF_BASE
    MAX_RETRIES = _REAL_MAX_RETRIES
    try:
        yield
    finally:
        _dlf.MAX_RETRIES = saved_retries
        _dlf.BACKOFF_BASE = saved_backoff
        MAX_RETRIES = saved_module_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(
    project: str = "yearn-finance",
    symbol: str = "USDC",
    chain: str = "Ethereum",
    apy: float = 8.5,
    tvl: float = 10_000_000.0,
    pool_id: str = "uuid-test",
) -> dict:
    return {
        "project": project,
        "symbol": symbol,
        "chain": chain,
        "apy": apy,
        "tvlUsd": tvl,
        "pool": pool_id,
    }


def _mock_urlopen(pools: list, status: str = "success"):
    """Context-manager patch: make urlopen return a DeFiLlama-shaped response."""
    payload = json.dumps({"status": status, "data": pools}).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return mock.patch(
        "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
        return_value=resp,
    )


def _mock_http_error(code: int):
    """Patch urlopen to raise an HTTPError with the given status code."""
    exc = urllib.error.HTTPError(
        url="https://yields.llama.fi/pools",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    return mock.patch(
        "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
        side_effect=exc,
    )


def _mock_cg_urlopen(market_cap: int = 1_000_000_000):
    """Patch urlopen for CoinGecko /coins/markets response."""
    payload = json.dumps([{"id": "yearn-finance", "market_cap": market_cap}]).encode()
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return mock.patch(
        "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
        return_value=resp,
    )


def _fresh_feed(**kwargs) -> DefiLlamaFeed:
    """Return a new feed instance (cache is empty)."""
    return DefiLlamaFeed(**kwargs)


# ---------------------------------------------------------------------------
# 1. get_pool — pool selection & matching
# ---------------------------------------------------------------------------

class TestGetPool(unittest.TestCase):

    def test_returns_dict_with_required_keys(self):
        with _mock_urlopen([_pool()]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIsInstance(result, dict)
        self.assertIn("apy", result)
        self.assertIn("tvl_usd", result)
        self.assertIn("pool_id", result)
        self.assertIn("live_apy_fallback_source", result)

    def test_apy_is_raw_percentage_not_decimal(self):
        # get_pool returns the raw percentage (8.5), not the decimal (0.085)
        with _mock_urlopen([_pool(apy=8.5)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertAlmostEqual(result["apy"], 8.5)

    def test_tvl_usd_is_passed_through(self):
        with _mock_urlopen([_pool(tvl=42_000_000.0)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertAlmostEqual(result["tvl_usd"], 42_000_000.0)

    def test_pool_id_is_passed_through(self):
        with _mock_urlopen([_pool(pool_id="abc-123")]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertEqual(result["pool_id"], "abc-123")

    def test_project_substring_match(self):
        # "morpho" must match a pool whose project is "morpho-blue"
        with _mock_urlopen([_pool(project="morpho-blue", apy=4.4)]):
            result = _fresh_feed().get_pool("morpho", "USDC")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["apy"], 4.4)

    def test_symbol_match_is_case_insensitive(self):
        with _mock_urlopen([_pool(symbol="USDC", apy=7.0)]):
            result = _fresh_feed().get_pool("yearn-finance", "usdc")
        self.assertIsNotNone(result)

    def test_chain_mismatch_returns_none(self):
        with _mock_urlopen([_pool(chain="Polygon")]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC", "Ethereum")
        self.assertIsNone(result)

    def test_picks_highest_tvl_pool_when_multiple_match(self):
        pools = [
            _pool(apy=9.99, tvl=500_000.0, pool_id="small"),
            _pool(apy=6.00, tvl=120_000_000.0, pool_id="big"),
        ]
        with _mock_urlopen(pools):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertEqual(result["pool_id"], "big")
        self.assertAlmostEqual(result["apy"], 6.00)

    def test_returns_none_on_project_miss(self):
        with _mock_urlopen([_pool(project="aave-v3")]):
            result = _fresh_feed().get_pool("nonexistent-protocol", "USDC")
        self.assertIsNone(result)

    def test_returns_none_on_empty_pool_list(self):
        with _mock_urlopen([]):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))


# ---------------------------------------------------------------------------
# 2. Liveness filters (TVL floor + APY sanity)
# ---------------------------------------------------------------------------

class TestLivenessFilters(unittest.TestCase):

    def test_tvl_below_floor_rejected(self):
        with _mock_urlopen([_pool(apy=8.0, tvl=50_000.0)]):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))

    def test_tvl_at_exact_floor_accepted(self):
        with _mock_urlopen([_pool(apy=8.0, tvl=MIN_TVL_USD)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIsNotNone(result)

    def test_custom_tvl_threshold(self):
        # Pool has TVL $3M but caller requires $5M → rejected
        with _mock_urlopen([_pool(apy=6.0, tvl=3_000_000.0)]):
            result = _fresh_feed().get_pool(
                "yearn-finance", "USDC", min_tvl_usd=5_000_000.0
            )
        self.assertIsNone(result)

    def test_negative_apy_rejected(self):
        with _mock_urlopen([_pool(apy=-1.0, tvl=10_000_000.0)]):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))

    def test_apy_above_200_rejected(self):
        with _mock_urlopen([_pool(apy=201.0, tvl=10_000_000.0)]):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))

    def test_apy_exactly_200_accepted(self):
        with _mock_urlopen([_pool(apy=200.0, tvl=10_000_000.0)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["apy"], 200.0)

    def test_anomalous_pool_skipped_valid_pool_wins(self):
        # High-TVL pool is anomalous (APY > 200) → skip; valid pool wins
        pools = [
            _pool(apy=999.0, tvl=500_000_000.0, pool_id="anomaly"),
            _pool(apy=7.5,   tvl=8_000_000.0,   pool_id="valid"),
        ]
        with _mock_urlopen(pools):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertEqual(result["pool_id"], "valid")

    def test_missing_apy_field_skipped(self):
        p = _pool()
        del p["apy"]
        with _mock_urlopen([p]):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))


# ---------------------------------------------------------------------------
# 3. get_apy — decimal conversion
# ---------------------------------------------------------------------------

class TestGetApy(unittest.TestCase):

    def test_returns_decimal_not_percentage(self):
        # DeFiLlama pool has apy=8.5 (%)  →  get_apy returns 0.085
        with _mock_urlopen([_pool(apy=8.5)]):
            apy = _fresh_feed().get_apy("yearn-finance")
        self.assertAlmostEqual(apy, 0.085, places=6)

    def test_returns_none_on_miss(self):
        with _mock_urlopen([]):
            self.assertIsNone(_fresh_feed().get_apy("yearn-finance"))

    def test_returns_none_on_network_error(self):
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ), mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            self.assertIsNone(_fresh_feed().get_apy("yearn-finance"))

    def test_apy_zero_returns_decimal_zero(self):
        with _mock_urlopen([_pool(apy=0.0)]):
            apy = _fresh_feed().get_apy("yearn-finance")
        self.assertAlmostEqual(apy, 0.0)


# ---------------------------------------------------------------------------
# 4. get_tvl
# ---------------------------------------------------------------------------

class TestGetTvl(unittest.TestCase):

    def test_returns_usd_value(self):
        with _mock_urlopen([_pool(tvl=55_000_000.0)]):
            tvl = _fresh_feed().get_tvl("yearn-finance")
        self.assertAlmostEqual(tvl, 55_000_000.0)

    def test_returns_none_on_miss(self):
        with _mock_urlopen([]):
            self.assertIsNone(_fresh_feed().get_tvl("yearn-finance"))


# ---------------------------------------------------------------------------
# 5. Caching behaviour
# ---------------------------------------------------------------------------

class TestCaching(unittest.TestCase):

    def test_second_call_uses_cache_not_network(self):
        feed = _fresh_feed()
        with _mock_urlopen([_pool(apy=5.0)]) as m:
            feed.get_apy("yearn-finance")
            feed.get_apy("yearn-finance")
        # urlopen called exactly once despite two get_apy calls
        self.assertEqual(m.call_count, 1)

    def test_invalidate_cache_forces_refetch(self):
        feed = _fresh_feed()
        with _mock_urlopen([_pool(apy=5.0)]) as m:
            feed.get_apy("yearn-finance")
            feed.invalidate_cache()
            feed.get_apy("yearn-finance")
        self.assertEqual(m.call_count, 2)

    def test_expired_ttl_triggers_refetch(self):
        feed = _fresh_feed(cache_ttl=0)  # TTL = 0 → always expired
        with _mock_urlopen([_pool(apy=5.0)]) as m:
            feed.get_apy("yearn-finance")
            feed.get_apy("yearn-finance")
        self.assertEqual(m.call_count, 2)

    def test_default_cache_ttl_is_one_hour(self):
        self.assertEqual(CACHE_TTL, 3600)

    def test_default_api_url_is_defillama(self):
        self.assertEqual(DEFILLAMA_POOLS_URL, "https://yields.llama.fi/pools")


# ---------------------------------------------------------------------------
# 6. Graceful error handling
# ---------------------------------------------------------------------------

class TestGracefulErrors(unittest.TestCase):

    def test_network_error_returns_none(self):
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=Exception("boom"),
        ), mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))

    def test_bad_status_field_returns_none(self):
        with _mock_urlopen([_pool()], status="error"):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))

    def test_data_not_list_returns_none(self):
        payload = json.dumps({"status": "success", "data": {"oops": 1}}).encode()
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            return_value=resp,
        ):
            self.assertIsNone(_fresh_feed().get_pool("yearn-finance", "USDC"))

    def test_malformed_pool_entries_skipped(self):
        # Non-dict pool entries must be skipped; valid entry still found
        with _mock_urlopen([None, 42, "bad", _pool(apy=6.0, tvl=9_000_000.0)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["apy"], 6.0)

    def test_disabled_feed_returns_none(self):
        feed = DefiLlamaFeed(enabled=False)
        with _mock_urlopen([_pool()]) as m:
            self.assertIsNone(feed.get_pool("yearn-finance", "USDC"))
        # urlopen must NOT be called at all
        m.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Module-level get_apy() — slug resolution via PROTOCOL_MAP
# ---------------------------------------------------------------------------

class TestModuleGetApy(unittest.TestCase):

    def _run(self, slug: str, pools: list):
        """Patch the module-level singleton and call get_apy(slug)."""
        import spa_core.feeds.defi_llama_feed as _mod
        original = _mod._SINGLETON
        try:
            _mod._SINGLETON = None  # force fresh singleton
            with _mock_urlopen(pools):
                return module_get_apy(slug)
        finally:
            _mod._SINGLETON = original

    def test_yearn_v3_slug_resolves(self):
        apy = self._run("yearn_v3", [_pool(project="yearn-finance", apy=7.2)])
        self.assertAlmostEqual(apy, 0.072, places=6)

    def test_morpho_blue_slug_resolves(self):
        apy = self._run(
            "morpho_blue",
            [_pool(project="morpho-blue", apy=4.4)],
        )
        self.assertAlmostEqual(apy, 0.044, places=6)

    def test_euler_v2_slug_resolves(self):
        apy = self._run("euler_v2", [_pool(project="euler-v2", apy=5.5)])
        self.assertAlmostEqual(apy, 0.055, places=6)

    def test_maple_slug_resolves(self):
        apy = self._run("maple", [_pool(project="maple", apy=6.0)])
        self.assertAlmostEqual(apy, 0.06, places=6)

    def test_unknown_slug_forwarded_verbatim(self):
        # Unknown slug → passed to get_pool() as the project name (substring)
        apy = self._run(
            "aave-v3",
            [_pool(project="aave-v3", symbol="USDC", chain="Ethereum", apy=3.5)],
        )
        self.assertAlmostEqual(apy, 0.035, places=6)

    def test_protocol_map_covers_all_four_target_protocols(self):
        required = {"yearn_v3", "morpho_blue", "euler_v2", "maple"}
        self.assertTrue(required.issubset(PROTOCOL_MAP.keys()))

    def test_returns_none_when_no_matching_pool(self):
        apy = self._run("yearn_v3", [])
        self.assertIsNone(apy)


# ---------------------------------------------------------------------------
# 8. Retry / backoff logic (NEW — v1197)
# ---------------------------------------------------------------------------

class TestRetryBackoff(unittest.TestCase):
    """Verify exponential backoff + User-Agent rotation on 403/429."""

    def test_403_triggers_retry_up_to_max_retries(self):
        """All MAX_RETRIES attempts are made on persistent 403."""
        exc = urllib.error.HTTPError("", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=exc,
        ) as m, mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            result = _fresh_feed()._fetch_with_retry("http://test")
        self.assertIsNone(result)
        self.assertEqual(m.call_count, MAX_RETRIES)

    def test_429_triggers_retry_up_to_max_retries(self):
        """All MAX_RETRIES attempts are made on persistent 429."""
        exc = urllib.error.HTTPError("", 429, "Too Many Requests", {}, None)  # type: ignore[arg-type]
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=exc,
        ) as m, mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            result = _fresh_feed()._fetch_with_retry("http://test")
        self.assertIsNone(result)
        self.assertEqual(m.call_count, MAX_RETRIES)

    def test_non_retriable_404_does_not_retry(self):
        """HTTP 404 is not retriable — only one attempt is made."""
        exc = urllib.error.HTTPError("", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=exc,
        ) as m:
            result = _fresh_feed()._fetch_with_retry("http://test")
        self.assertIsNone(result)
        self.assertEqual(m.call_count, 1)

    def test_success_on_second_attempt_after_403(self):
        """After one 403, the second attempt succeeds and returns data."""
        payload = json.dumps({"status": "success", "data": [_pool(apy=7.0)]}).encode()
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        exc = urllib.error.HTTPError("", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        side_effects = [exc, resp]

        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=side_effects,
        ), mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            feed = _fresh_feed()
            pools = feed._load_pools()
        self.assertIsNotNone(pools)
        self.assertEqual(len(pools), 1)

    def test_backoff_delays_increase_exponentially(self):
        """sleep() is called with 1s, 2s for 3 retries with 403."""
        exc = urllib.error.HTTPError("", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        sleep_calls: list[float] = []
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=exc,
        ), mock.patch(
            "spa_core.feeds.defi_llama_feed.time.sleep",
            side_effect=lambda d: sleep_calls.append(d),
        ):
            _fresh_feed()._fetch_with_retry("http://test")
        # MAX_RETRIES=3: sleep after attempt 0→1s, attempt 1→2s; NO sleep after last attempt
        self.assertEqual(len(sleep_calls), MAX_RETRIES - 1)
        self.assertAlmostEqual(sleep_calls[0], 1.0)
        self.assertAlmostEqual(sleep_calls[1], 2.0)

    def test_user_agent_rotates_on_each_attempt(self):
        """User-Agent header cycles through _USER_AGENTS across retry attempts."""
        from spa_core.feeds.defi_llama_feed import _USER_AGENTS
        exc = urllib.error.HTTPError("", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        captured_uas: list[str] = []

        def fake_urlopen(req, timeout=None):
            # req is a urllib.request.Request object
            captured_uas.append(req.get_header("User-agent"))
            raise exc

        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            _fresh_feed()._fetch_with_retry("http://test")

        self.assertEqual(len(captured_uas), MAX_RETRIES)
        # All three User-Agents should be from _USER_AGENTS (by index mod len)
        for i, ua in enumerate(captured_uas):
            expected = _USER_AGENTS[i % len(_USER_AGENTS)]
            self.assertEqual(ua, expected)

    def test_generic_oserror_retries_all_attempts(self):
        """OSError (connection timeout, etc.) is retried up to MAX_RETRIES times."""
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=OSError("timed out"),
        ) as m, mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"):
            _fresh_feed()._fetch_with_retry("http://test")
        self.assertEqual(m.call_count, MAX_RETRIES)

    def test_max_retries_constant_is_three(self):
        self.assertEqual(MAX_RETRIES, 3)


# ---------------------------------------------------------------------------
# 9. live_apy_fallback_source field (NEW — v1197)
# ---------------------------------------------------------------------------

class TestFallbackSourceField(unittest.TestCase):
    """Verify ``live_apy_fallback_source`` is set correctly in get_pool() result."""

    def test_source_is_defillama_on_successful_fetch(self):
        with _mock_urlopen([_pool(apy=5.0)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIsNotNone(result)
        self.assertEqual(result["live_apy_fallback_source"], "defillama")

    def test_source_not_present_when_result_is_none(self):
        # No pool found → returns None (no source key)
        with _mock_urlopen([]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIsNone(result)

    def test_get_apy_still_returns_decimal_after_refactor(self):
        """get_apy backward-compat: still divides by 100 after get_pool refactor."""
        with _mock_urlopen([_pool(apy=9.0)]):
            apy = _fresh_feed().get_apy("yearn-finance")
        self.assertAlmostEqual(apy, 0.09, places=6)

    def test_get_pool_includes_fallback_source_key(self):
        """The ``live_apy_fallback_source`` key is always present in non-None results."""
        with _mock_urlopen([_pool(apy=3.5)]):
            result = _fresh_feed().get_pool("yearn-finance", "USDC")
        self.assertIn("live_apy_fallback_source", result)


# ---------------------------------------------------------------------------
# 10. CoinGecko fallback (NEW — v1197)
# ---------------------------------------------------------------------------

class TestCoinGeckoFallback(unittest.TestCase):
    """Verify CoinGecko fallback is invoked when DeFiLlama fails."""

    def _feed_with_failing_defillama(self) -> DefiLlamaFeed:
        """Return a fresh feed; callers must patch urlopen themselves."""
        return _fresh_feed()

    def test_coingecko_not_queried_when_defillama_succeeds(self):
        """When DeFiLlama returns a pool, CoinGecko is NOT called."""
        feed = _fresh_feed()
        with _mock_urlopen([_pool(apy=5.0)]):
            with mock.patch.object(
                feed, "_fetch_coingecko_fallback", return_value=None
            ) as cg_mock:
                feed.get_pool("yearn-finance", "USDC")
        cg_mock.assert_not_called()

    def test_coingecko_queried_when_defillama_returns_no_pool(self):
        """When DeFiLlama returns 200 but no matching pool, CoinGecko is tried."""
        feed = _fresh_feed()
        with _mock_urlopen([]):  # empty pool list
            with mock.patch.object(
                feed, "_fetch_coingecko_fallback", return_value=None
            ) as cg_mock:
                feed.get_pool("yearn-finance", "USDC")
        cg_mock.assert_called_once_with("yearn-finance")

    def test_coingecko_queried_when_defillama_all_retries_fail(self):
        """When DeFiLlama 403s on all retries, CoinGecko fallback is tried."""
        exc = urllib.error.HTTPError("", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        feed = _fresh_feed()
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=exc,
        ), mock.patch("spa_core.feeds.defi_llama_feed.time.sleep"), \
           mock.patch.object(
               feed, "_fetch_coingecko_fallback", return_value=None
           ) as cg_mock:
            feed.get_pool("yearn-finance", "USDC")
        cg_mock.assert_called_once_with("yearn-finance")

    def test_coingecko_returns_none_for_unknown_project(self):
        """_fetch_coingecko_fallback returns None for projects without a CG mapping."""
        feed = _fresh_feed()
        result = feed._fetch_coingecko_fallback("totally-unknown-protocol-xyz")
        self.assertIsNone(result)

    def test_coingecko_network_error_returns_none(self):
        """Network error in CoinGecko call is absorbed gracefully."""
        feed = _fresh_feed()
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            side_effect=OSError("CG timeout"),
        ):
            result = feed._fetch_coingecko_fallback("yearn-finance")
        self.assertIsNone(result)

    def test_coingecko_empty_response_returns_none(self):
        """Empty CoinGecko list response is handled gracefully."""
        payload = json.dumps([]).encode()
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        feed = _fresh_feed()
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            return_value=resp,
        ):
            result = feed._fetch_coingecko_fallback("yearn-finance")
        self.assertIsNone(result)

    def test_coingecko_coin_ids_covers_key_protocols(self):
        """COINGECKO_COIN_IDS has mappings for all whitelisted T1/T2 protocols."""
        required = {"aave-v3", "yearn-finance", "morpho-blue", "euler-v2", "maple"}
        self.assertTrue(required.issubset(COINGECKO_COIN_IDS.keys()))

    def test_coingecko_url_constant_is_correct(self):
        self.assertIn("coingecko.com", COINGECKO_MARKETS_URL)
        self.assertIn("coins/markets", COINGECKO_MARKETS_URL)

    def test_coingecko_fallback_url_injected_via_constructor(self):
        """cg_url parameter allows overriding in tests without monkey-patching globals."""
        feed = DefiLlamaFeed(cg_url="https://mock.coingecko.test/api/v3/coins/markets")
        self.assertEqual(
            feed.cg_url,
            "https://mock.coingecko.test/api/v3/coins/markets",
        )

    def test_fallback_does_not_fabricate_hardcoded_apy(self):
        """CoinGecko fallback must return None (not a hardcoded APY value)."""
        # Simulate CoinGecko returning coin data (protocol alive)
        payload = json.dumps([
            {"id": "yearn-finance", "market_cap": 500_000_000, "current_price": 8.50}
        ]).encode()
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        feed = _fresh_feed()
        with mock.patch(
            "spa_core.feeds.defi_llama_feed.urllib.request.urlopen",
            return_value=resp,
        ):
            result = feed._fetch_coingecko_fallback("yearn-finance")
        # Must return None — never a hardcoded APY estimate
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 11. Adapter integration — adapters now use DefiLlamaFeed from feeds module
# ---------------------------------------------------------------------------

ADAPTER_CLASSES = [YearnV3Adapter, MorphoBlueAdapter, EulerV2Adapter, MapleAdapter]


class TestAdapterIntegration(unittest.TestCase):

    def _make_feed(self, apy_decimal=None, tvl=None):
        """Return a MagicMock feed that behaves like DefiLlamaFeed."""
        feed = mock.MagicMock()
        feed.get_apy.return_value = apy_decimal
        feed.get_tvl.return_value = tvl
        return feed

    def test_adapters_import_from_feeds_module(self):
        """Verify all four adapters now use the feeds module feed class."""
        import spa_core.adapters.yearn_v3 as y
        import spa_core.adapters.morpho_blue as m
        import spa_core.adapters.euler_v2 as e
        import spa_core.adapters.maple as mp
        from spa_core.feeds.defi_llama_feed import DefiLlamaFeed

        for mod in (y, m, e, mp):
            self.assertIs(
                getattr(mod, "DefiLlamaFeed", None),
                DefiLlamaFeed,
                f"{mod.__name__} does not import DefiLlamaFeed from feeds module",
            )

    def test_status_ok_when_live_apy_available(self):
        for cls in ADAPTER_CLASSES:
            feed = self._make_feed(apy_decimal=0.085, tvl=10_000_000.0)
            data = cls(feed=feed).fetch()
            self.assertEqual(data["status"], "ok", cls.__name__)
            self.assertTrue(data["live_data"], cls.__name__)
            self.assertAlmostEqual(data["apy"], 0.085, msg=cls.__name__)

    def test_status_error_when_feed_returns_none(self):
        for cls in ADAPTER_CLASSES:
            feed = self._make_feed(apy_decimal=None, tvl=None)
            data = cls(feed=feed).fetch()
            self.assertEqual(data["status"], "error", cls.__name__)
            self.assertFalse(data["live_data"], cls.__name__)
            self.assertIsNone(data["apy"], cls.__name__)
            self.assertEqual(data["error"], "live_feed_unavailable", cls.__name__)

    def test_get_apy_returns_decimal_from_feed(self):
        for cls in ADAPTER_CLASSES:
            feed = self._make_feed(apy_decimal=0.065)
            apy = cls(feed=feed).get_apy()
            self.assertAlmostEqual(apy, 0.065, msg=cls.__name__)

    def test_get_apy_returns_none_when_no_live_data(self):
        for cls in ADAPTER_CLASSES:
            feed = self._make_feed(apy_decimal=None)
            self.assertIsNone(cls(feed=feed).get_apy(), cls.__name__)

    def test_tvl_propagated_into_fetch_result(self):
        for cls in ADAPTER_CLASSES:
            feed = self._make_feed(apy_decimal=0.05, tvl=25_000_000.0)
            data = cls(feed=feed).fetch()
            self.assertAlmostEqual(data["tvl"], 25_000_000.0, msg=cls.__name__)

    def test_feed_called_with_correct_defillama_project_and_symbol(self):
        expected = {
            "yearn_v3":   ("yearn-finance", "USDC"),
            "morpho_blue": ("morpho-blue",   "USDC"),
            "euler_v2":   ("euler-v2",       "USDC"),
            "maple":      ("maple",          "USDC"),
        }
        for cls in ADAPTER_CLASSES:
            feed = self._make_feed(apy_decimal=0.07, tvl=5_000_000.0)
            cls(feed=feed).fetch()
            proj, sym = expected[cls.PROTOCOL]
            feed.get_apy.assert_called_with(proj, sym)

    def test_feed_exception_is_absorbed_as_error(self):
        for cls in ADAPTER_CLASSES:
            feed = mock.MagicMock()
            feed.get_apy.side_effect = RuntimeError("network down")
            data = cls(feed=feed).fetch()
            self.assertEqual(data["status"], "error", cls.__name__)
            self.assertFalse(data["live_data"], cls.__name__)

    def test_no_mock_apy_on_any_adapter(self):
        for cls in ADAPTER_CLASSES:
            self.assertFalse(
                hasattr(cls, "MOCK_APY"),
                f"{cls.__name__} still has MOCK_APY attribute",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

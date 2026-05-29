"""
Tests for defillama_apy_feed (Sprint v3.27 / SPA-V327-001 + SPA-V327-002).

NO real network: all tests use mock pool lists + get_live_apy_from_pools,
or monkeypatch _get_pools_cached / urllib.request.urlopen.

Runner (from repo root):
    python3 -m unittest spa_core.tests.test_defillama_apy_feed -v
or self-contained:
    python3 spa_core/tests/test_defillama_apy_feed.py
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make spa_core importable when run directly
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.execution import defillama_apy_feed as feed  # noqa: E402
from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter  # noqa: E402
from spa_core.execution.adapters.euler_v2_adapter import EulerV2Adapter  # noqa: E402
from spa_core.execution.adapters.maple_adapter import MapleAdapter  # noqa: E402


# ─── Mock pool fixtures ──────────────────────────────────────────────────────

def _yearn_pool(apy=6.42, tvl=120_000_000):
    return {"project": "yearn-finance", "symbol": "USDC", "chain": "Ethereum",
            "apy": apy, "tvlUsd": tvl, "pool": "yearn-usdc"}


def _euler_pool(apy=7.40, tvl=80_000_000):
    return {"project": "euler", "symbol": "USDC", "chain": "Ethereum",
            "apy": apy, "tvlUsd": tvl, "pool": "euler-usdc"}


def _maple_pool(apy=5.60, tvl=40_000_000):
    return {"project": "maple", "symbol": "USDC", "chain": "Ethereum",
            "apy": apy, "tvlUsd": tvl, "pool": "maple-usdc"}


def _standard_pools():
    return [_yearn_pool(), _euler_pool(), _maple_pool()]


# ─── Fuzzy matching ──────────────────────────────────────────────────────────

class TestFuzzyMatch(unittest.TestCase):
    def test_match_yearn(self):
        apy = feed.get_live_apy_from_pools(_standard_pools(), "yearn-v3", "USDC", "ethereum")
        self.assertEqual(apy, 6.42)

    def test_match_euler(self):
        apy = feed.get_live_apy_from_pools(_standard_pools(), "euler-v2", "USDC", "ethereum")
        self.assertEqual(apy, 7.40)

    def test_match_maple(self):
        apy = feed.get_live_apy_from_pools(_standard_pools(), "maple", "USDC", "ethereum")
        self.assertEqual(apy, 5.60)

    def test_match_is_rounded_to_4dp(self):
        pools = [_yearn_pool(apy=6.123456789)]
        apy = feed.get_live_apy_from_pools(pools, "yearn-v3", "USDC", "ethereum")
        self.assertEqual(apy, 6.1235)

    def test_chain_case_insensitive(self):
        # pool chain is "Ethereum", query is lowercase "ethereum"
        apy = feed.get_live_apy_from_pools(_standard_pools(), "yearn-v3", "usdc", "ETHEREUM")
        self.assertEqual(apy, 6.42)


class TestMaxTvlSelection(unittest.TestCase):
    def test_picks_highest_tvl(self):
        pools = [
            _yearn_pool(apy=9.99, tvl=1_000_000),     # small TVL, juicy apy
            _yearn_pool(apy=6.42, tvl=120_000_000),   # big TVL → should win
        ]
        apy = feed.get_live_apy_from_pools(pools, "yearn-v3", "USDC", "ethereum")
        self.assertEqual(apy, 6.42)

    def test_tvl_none_treated_as_zero(self):
        p1 = _yearn_pool(apy=5.0, tvl=50_000_000)
        p2 = _yearn_pool(apy=8.0)
        p2["tvlUsd"] = None
        apy = feed.get_live_apy_from_pools([p2, p1], "yearn-v3", "USDC", "ethereum")
        self.assertEqual(apy, 5.0)


class TestNoMatch(unittest.TestCase):
    def test_unknown_protocol_returns_none(self):
        apy = feed.get_live_apy_from_pools(_standard_pools(), "aave-v3", "USDC", "ethereum")
        self.assertIsNone(apy)

    def test_no_match_on_asset(self):
        apy = feed.get_live_apy_from_pools(_standard_pools(), "yearn-v3", "DAI", "ethereum")
        self.assertIsNone(apy)

    def test_no_match_on_chain(self):
        apy = feed.get_live_apy_from_pools(_standard_pools(), "yearn-v3", "USDC", "polygon")
        self.assertIsNone(apy)

    def test_empty_pools_returns_none(self):
        self.assertIsNone(feed.get_live_apy_from_pools([], "yearn-v3", "USDC", "ethereum"))

    def test_apy_none_returns_none(self):
        p = _yearn_pool()
        p["apy"] = None
        self.assertIsNone(feed.get_live_apy_from_pools([p], "yearn-v3", "USDC", "ethereum"))

    def test_missing_apy_key_returns_none(self):
        p = _yearn_pool()
        del p["apy"]
        self.assertIsNone(feed.get_live_apy_from_pools([p], "yearn-v3", "USDC", "ethereum"))


class TestProtocolSynonyms(unittest.TestCase):
    def test_yearn_synonym(self):
        self.assertEqual(
            feed.get_live_apy_from_pools(_standard_pools(), "yearn", "USDC", "ethereum"), 6.42)

    def test_euler_synonym(self):
        self.assertEqual(
            feed.get_live_apy_from_pools(_standard_pools(), "euler", "USDC", "ethereum"), 7.40)

    def test_protocol_name_with_spaces_normalized(self):
        # "Yearn V3" → "yearn-v3"
        self.assertEqual(
            feed.get_live_apy_from_pools(_standard_pools(), "Yearn V3", "USDC", "ethereum"), 6.42)


# ─── Env gate ────────────────────────────────────────────────────────────────

class TestLiveApyEnabled(unittest.TestCase):
    def _set(self, val):
        if val is None:
            os.environ.pop("SPA_LIVE_APY", None)
        else:
            os.environ["SPA_LIVE_APY"] = val

    def tearDown(self):
        self._set(None)

    def test_default_disabled(self):
        self._set(None)
        self.assertFalse(feed.live_apy_enabled())

    def test_true(self):
        self._set("true")
        self.assertTrue(feed.live_apy_enabled())

    def test_one(self):
        self._set("1")
        self.assertTrue(feed.live_apy_enabled())

    def test_yes_mixed_case(self):
        self._set("YeS")
        self.assertTrue(feed.live_apy_enabled())

    def test_false(self):
        self._set("false")
        self.assertFalse(feed.live_apy_enabled())

    def test_zero(self):
        self._set("0")
        self.assertFalse(feed.live_apy_enabled())


# ─── TTL cache ───────────────────────────────────────────────────────────────

class TestTtlCache(unittest.TestCase):
    def setUp(self):
        feed.clear_cache()
        self.calls = {"n": 0}

        def fake_fetch():
            self.calls["n"] += 1
            return _standard_pools()

        self._patch = mock.patch.object(feed, "_fetch_pools", side_effect=fake_fetch)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        feed.clear_cache()

    def test_second_call_uses_cache(self):
        feed._get_pools_cached()
        feed._get_pools_cached()
        self.assertEqual(self.calls["n"], 1)

    def test_force_refetches(self):
        feed._get_pools_cached()
        feed._get_pools_cached(force=True)
        self.assertEqual(self.calls["n"], 2)

    def test_clear_cache_resets(self):
        feed._get_pools_cached()
        feed.clear_cache()
        feed._get_pools_cached()
        self.assertEqual(self.calls["n"], 2)

    def test_empty_fetch_not_cached(self):
        self._patch.stop()
        with mock.patch.object(feed, "_fetch_pools", return_value=[]) as m:
            feed.clear_cache()
            feed._get_pools_cached()
            feed._get_pools_cached()
            # empty result must not be cached → fetched twice
            self.assertEqual(m.call_count, 2)
        self._patch.start()  # restart so tearDown.stop() is balanced


# ─── Network error handling ──────────────────────────────────────────────────

class TestNetworkErrors(unittest.TestCase):
    def tearDown(self):
        feed.clear_cache()

    def test_fetch_pools_on_network_error_returns_empty(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            # _retry_request will sleep with backoff 2.0**attempt; patch sleep to speed up
            with mock.patch.object(feed.time, "sleep", return_value=None):
                result = feed._fetch_pools()
        self.assertEqual(result, [])

    def test_get_live_apy_on_network_error_returns_none(self):
        feed.clear_cache()
        with mock.patch.object(feed, "_fetch_pools", return_value=[]):
            self.assertIsNone(feed.get_live_apy("yearn-v3", "USDC", "ethereum"))


# ─── get_live_apy (cached path) ──────────────────────────────────────────────

class TestGetLiveApy(unittest.TestCase):
    def tearDown(self):
        feed.clear_cache()

    def test_get_live_apy_uses_cached_pools(self):
        feed.clear_cache()
        with mock.patch.object(feed, "_get_pools_cached", return_value=_standard_pools()):
            self.assertEqual(feed.get_live_apy("euler-v2", "USDC", "ethereum"), 7.40)

    def test_get_live_apy_unknown_protocol_none(self):
        with mock.patch.object(feed, "_get_pools_cached", return_value=_standard_pools()):
            self.assertIsNone(feed.get_live_apy("compound-v3", "USDC", "ethereum"))


# ─── Integration: dry-run adapters still return mock ─────────────────────────

class TestAdapterDryRunUnaffected(unittest.TestCase):
    """Live wiring must not break dry-run mock behaviour (even with SPA_LIVE_APY on)."""

    def setUp(self):
        # Even with live enabled, dry-run must short-circuit to mock before any feed call.
        os.environ["SPA_LIVE_APY"] = "true"

    def tearDown(self):
        os.environ.pop("SPA_LIVE_APY", None)

    def test_yearn_dry_run_mock(self):
        a = YearnV3Adapter(chain="ethereum", dry_run=True)
        self.assertEqual(a.get_supply_apy("USDC"), 6.8)

    def test_euler_dry_run_mock(self):
        a = EulerV2Adapter(chain="ethereum", dry_run=True)
        self.assertEqual(a.get_supply_apy("USDC"), 7.4)

    def test_maple_dry_run_mock(self):
        a = MapleAdapter(chain="ethereum", dry_run=True)
        self.assertEqual(a.get_supply_apy("USDC"), 5.6)

    def test_yearn_default_asset_fallback(self):
        # unknown asset in mock dict → fallback 5.0 (still dry-run)
        a = YearnV3Adapter(chain="arbitrum", dry_run=True)
        self.assertEqual(a.get_supply_apy("USDC"), 7.1)


class TestAdapterLiveWiring(unittest.TestCase):
    """Live (non-dry-run) path: returns live APY when available, mock otherwise."""

    def tearDown(self):
        os.environ.pop("SPA_LIVE_APY", None)

    def test_live_returns_feed_value(self):
        os.environ["SPA_LIVE_APY"] = "true"
        a = EulerV2Adapter(chain="ethereum", dry_run=False)
        with mock.patch.object(feed, "get_live_apy", return_value=9.11):
            self.assertEqual(a.get_supply_apy("USDC"), 9.11)

    def test_live_none_falls_back_to_mock(self):
        os.environ["SPA_LIVE_APY"] = "true"
        a = MapleAdapter(chain="ethereum", dry_run=False)
        with mock.patch.object(feed, "get_live_apy", return_value=None):
            self.assertEqual(a.get_supply_apy("USDC"), 5.6)

    def test_gate_off_uses_mock(self):
        os.environ["SPA_LIVE_APY"] = "false"
        a = YearnV3Adapter(chain="ethereum", dry_run=False)
        # get_live_apy must not even be consulted; mock returned
        with mock.patch.object(feed, "get_live_apy", return_value=99.0) as m:
            self.assertEqual(a.get_supply_apy("USDC"), 6.8)
            m.assert_not_called()

    def test_live_exception_falls_back_to_mock(self):
        os.environ["SPA_LIVE_APY"] = "true"
        a = YearnV3Adapter(chain="ethereum", dry_run=False)
        with mock.patch.object(feed, "get_live_apy", side_effect=RuntimeError("net down")):
            self.assertEqual(a.get_supply_apy("USDC"), 6.8)


if __name__ == "__main__":
    unittest.main(verbosity=2)

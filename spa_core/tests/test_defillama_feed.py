"""Tests for the mandatory live DeFiLlama feed and the no-mock adapters (SPA-V398).

Covers the liveness-filtered ``fetch_pool``/``fetch_apy``/``fetch_tvl`` surface of
``spa_core/adapters/defillama_feed.py`` and verifies that the read-only adapters
(morpho_blue, yearn_v3, euler_v2, maple) report an honest ``status="error"`` /
``apy=None`` when the live feed is unavailable — and never a mock value.

No real network: ``requests.get`` is patched throughout. pytest is not installed
in this repo, so these are plain ``unittest`` tests.

Run:  python3 -m unittest spa_core.tests.test_defillama_feed -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.defillama_feed import DeFiLlamaFeed  # noqa: E402
from spa_core.adapters.morpho_blue import MorphoBlueAdapter  # noqa: E402
from spa_core.adapters.yearn_v3 import YearnV3Adapter  # noqa: E402
from spa_core.adapters.euler_v2 import EulerV2Adapter  # noqa: E402
from spa_core.adapters.maple import MapleAdapter  # noqa: E402


# ─── Fixtures / helpers ──────────────────────────────────────────────────────

def _pool(project="yearn-finance", symbol="USDC", chain="Ethereum",
          apy=8.5, tvl=5_000_000.0, pool_id="uuid-x"):
    return {"project": project, "symbol": symbol, "chain": chain,
            "apy": apy, "tvlUsd": tvl, "pool": pool_id}


def _mock_get(pools, status="success"):
    """Return a patch object for urllib.request.urlopen yielding the given pools payload."""
    import json as _json
    payload_bytes = _json.dumps({"status": status, "data": pools}).encode("utf-8")
    resp_cm = mock.MagicMock()
    resp_cm.__enter__ = mock.Mock(return_value=resp_cm)
    resp_cm.__exit__ = mock.Mock(return_value=False)
    resp_cm.read.return_value = payload_bytes
    return mock.patch(
        "spa_core.adapters.defillama_feed.urllib.request.urlopen", return_value=resp_cm
    )


def _feed():
    return DeFiLlamaFeed(enabled=True, cache_ttl=300)


# ─── fetch_pool: structure & selection ───────────────────────────────────────

class TestFetchPool(unittest.TestCase):
    def test_fetch_pool_returns_dict(self):
        with _mock_get([_pool(apy=8.5, tvl=5_000_000.0, pool_id="uuid-1")]):
            out = _feed().fetch_pool("yearn-finance", "USDC")
        self.assertIsInstance(out, dict)
        self.assertEqual(set(out), {"apy", "tvl", "pool_id"})
        self.assertEqual(out["pool_id"], "uuid-1")

    def test_fetch_pool_returns_none_on_miss(self):
        with _mock_get([_pool(project="yearn-finance")]):
            self.assertIsNone(_feed().fetch_pool("nonexistent", "USDC"))

    def test_apy_returned_as_percentage(self):
        # 8.5 stays 8.5 (percentage), NOT converted to a decimal 0.085.
        with _mock_get([_pool(apy=8.5)]):
            out = _feed().fetch_pool("yearn-finance", "USDC")
        self.assertEqual(out["apy"], 8.5)

    def test_project_substring_match(self):
        # "morpho" must match the real slug "morpho-blue".
        with _mock_get([_pool(project="morpho-blue", apy=4.4)]):
            self.assertEqual(_feed().fetch_apy("morpho", "USDC"), 4.4)

    def test_symbol_match_case_insensitive(self):
        with _mock_get([_pool(symbol="USDC", apy=7.0)]):
            self.assertEqual(_feed().fetch_apy("yearn-finance", "usdc"), 7.0)

    def test_chain_filter_excludes_other_chains(self):
        with _mock_get([_pool(chain="Polygon", apy=9.0, tvl=9_000_000.0)]):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC", "Ethereum"))

    def test_picks_highest_tvl_when_multiple_matches(self):
        pools = [
            _pool(apy=9.99, tvl=1_000_000.0, pool_id="small"),
            _pool(apy=6.42, tvl=120_000_000.0, pool_id="big"),
        ]
        with _mock_get(pools):
            out = _feed().fetch_pool("yearn-finance", "USDC")
        self.assertEqual(out["pool_id"], "big")
        self.assertEqual(out["apy"], 6.42)
        self.assertEqual(out["tvl"], 120_000_000.0)


# ─── fetch_pool: liveness validation ─────────────────────────────────────────

class TestValidation(unittest.TestCase):
    def test_apy_validation_rejects_negative(self):
        with _mock_get([_pool(apy=-3.0, tvl=10_000_000.0)]):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))

    def test_apy_validation_rejects_over_200(self):
        with _mock_get([_pool(apy=250.0, tvl=10_000_000.0)]):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))

    def test_apy_200_boundary_accepted(self):
        with _mock_get([_pool(apy=200.0, tvl=10_000_000.0)]):
            self.assertEqual(_feed().fetch_apy("yearn-finance", "USDC"), 200.0)

    def test_tvl_filter_rejects_small_pools(self):
        # Below the 100k default floor → dead/spam pool → not live.
        with _mock_get([_pool(apy=8.0, tvl=50_000.0)]):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))

    def test_tvl_filter_custom_threshold(self):
        with _mock_get([_pool(apy=8.0, tvl=3_000_000.0)]):
            self.assertIsNone(
                _feed().fetch_pool("yearn-finance", "USDC", min_tvl_usd=5_000_000.0)
            )

    def test_anomalous_pool_skipped_lower_tvl_wins(self):
        # The juicy-but-anomalous high-TVL pool is rejected; the valid one wins.
        pools = [
            _pool(apy=999.0, tvl=500_000_000.0, pool_id="anomaly"),
            _pool(apy=7.0, tvl=8_000_000.0, pool_id="real"),
        ]
        with _mock_get(pools):
            out = _feed().fetch_pool("yearn-finance", "USDC")
        self.assertEqual(out["pool_id"], "real")
        self.assertEqual(out["apy"], 7.0)

    def test_missing_apy_field_skipped(self):
        p = _pool()
        del p["apy"]
        with _mock_get([p]):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))


# ─── fetch_pool: graceful failure (never raise, never mock) ──────────────────

class TestGraceful(unittest.TestCase):
    def test_graceful_on_network_error(self):
        patcher = mock.patch(
            "spa_core.adapters.defillama_feed.urllib.request.urlopen",
            side_effect=Exception("boom"),
        )
        with patcher:
            out = _feed().fetch_pool("yearn-finance", "USDC")
        self.assertIsNone(out)

    def test_graceful_on_empty_json(self):
        with _mock_get([]):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))

    def test_graceful_on_bad_status_payload(self):
        with _mock_get([_pool()], status="error"):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))

    def test_graceful_on_malformed_response(self):
        import json as _json
        bad_bytes = _json.dumps({"status": "success", "data": {"oops": 1}}).encode("utf-8")
        resp_cm = mock.MagicMock()
        resp_cm.__enter__ = mock.Mock(return_value=resp_cm)
        resp_cm.__exit__ = mock.Mock(return_value=False)
        resp_cm.read.return_value = bad_bytes
        with mock.patch(
            "spa_core.adapters.defillama_feed.urllib.request.urlopen", return_value=resp_cm
        ):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))

    def test_graceful_on_malformed_pool_entries(self):
        with _mock_get([None, 42, "x", _pool(apy=6.0, tvl=9_000_000.0)]):
            out = _feed().fetch_pool("yearn-finance", "USDC")
        self.assertIsNotNone(out)
        self.assertEqual(out["apy"], 6.0)

    def test_fetch_apy_and_tvl_none_on_failure(self):
        with mock.patch(
            "spa_core.adapters.defillama_feed.urllib.request.urlopen",
            side_effect=Exception("down"),
        ):
            f = _feed()
            self.assertIsNone(f.fetch_apy("yearn-finance", "USDC"))
            self.assertIsNone(f.fetch_tvl("yearn-finance", "USDC"))

    def test_disabled_feed_returns_none(self):
        f = DeFiLlamaFeed(enabled=False)
        self.assertIsNone(f.fetch_pool("yearn-finance", "USDC"))
        self.assertIsNone(f.fetch_apy("yearn-finance", "USDC"))


# ─── Adapters: no mock, honest error on no live data ─────────────────────────

ADAPTERS = [MorphoBlueAdapter, YearnV3Adapter, EulerV2Adapter, MapleAdapter]


class TestAdaptersNoMock(unittest.TestCase):
    def test_no_mock_apy_attribute(self):
        # The whole point of SPA-V398: MOCK_APY must be gone everywhere.
        for cls in ADAPTERS:
            self.assertFalse(
                hasattr(cls, "MOCK_APY"),
                f"{cls.__name__} still defines MOCK_APY",
            )

    def test_error_status_when_feed_unavailable(self):
        for cls in ADAPTERS:
            feed = mock.MagicMock()
            feed.get_apy.return_value = None
            feed.get_tvl.return_value = None
            data = cls(feed=feed).fetch()
            self.assertEqual(data["status"], "error", cls.__name__)
            self.assertIsNone(data["apy"], cls.__name__)
            self.assertFalse(data["live_data"], cls.__name__)
            self.assertEqual(data["error"], "live_feed_unavailable", cls.__name__)

    def test_get_apy_none_when_feed_unavailable(self):
        for cls in ADAPTERS:
            feed = mock.MagicMock()
            feed.get_apy.return_value = None
            feed.get_tvl.return_value = None
            self.assertIsNone(cls(feed=feed).get_apy(), cls.__name__)

    def test_yield_info_apy_none_when_feed_unavailable(self):
        for cls in ADAPTERS:
            feed = mock.MagicMock()
            feed.get_apy.return_value = None
            feed.get_tvl.return_value = None
            info = cls(feed=feed).get_yield_info()
            self.assertIsNone(info.apy, cls.__name__)

    def test_feed_exception_is_graceful_error(self):
        for cls in ADAPTERS:
            feed = mock.MagicMock()
            feed.get_apy.side_effect = RuntimeError("net down")
            data = cls(feed=feed).fetch()
            self.assertEqual(data["status"], "error", cls.__name__)
            self.assertIsNone(data["apy"], cls.__name__)
            self.assertFalse(data["live_data"], cls.__name__)

    def test_uses_live_value_when_available(self):
        for cls in ADAPTERS:
            feed = mock.MagicMock()
            feed.get_apy.return_value = 0.0731  # decimal
            feed.get_tvl.return_value = 9_999_999.0
            data = cls(feed=feed).fetch()
            self.assertEqual(data["status"], "ok", cls.__name__)
            self.assertTrue(data["live_data"], cls.__name__)
            self.assertAlmostEqual(data["apy"], 0.0731, msg=cls.__name__)
            info = cls(feed=feed).get_yield_info()
            self.assertAlmostEqual(info.apy, 0.0731, msg=cls.__name__)
            self.assertEqual(info.tvl_usd, 9_999_999.0, cls.__name__)
            feed.get_apy.assert_called_with(cls.DEFILLAMA_PROJECT, cls.DEFILLAMA_SYMBOL)

    def test_real_defillama_slugs(self):
        # Slugs verified against the live DeFiLlama yields API (SPA-V398).
        expected = {
            "morpho_blue": ("morpho-blue", "USDC"),
            "yearn_v3": ("yearn-finance", "USDC"),
            "euler_v2": ("euler-v2", "USDC"),
            "maple": ("maple", "USDC"),
        }
        for cls in ADAPTERS:
            proj, sym = expected[cls.PROTOCOL]
            self.assertEqual(cls.DEFILLAMA_PROJECT, proj, cls.__name__)
            self.assertEqual(cls.DEFILLAMA_SYMBOL, sym, cls.__name__)


if __name__ == "__main__":
    unittest.main(verbosity=2)

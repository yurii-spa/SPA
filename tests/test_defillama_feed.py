"""Tests for the DeFiLlama yields feed client and adapter wiring."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spa_core.adapters.defillama_feed import DeFiLlamaFeed
from spa_core.adapters.euler_v2 import EulerV2Adapter
from spa_core.adapters.maple import MapleAdapter
from spa_core.adapters.morpho_blue import MorphoBlueAdapter
from spa_core.adapters.yearn_v3 import YearnV3Adapter


def _make_payload(pools):
    return {"status": "success", "data": pools}


def _mock_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


SAMPLE_POOLS = [
    {
        "pool": "uuid-1",
        "project": "yearn-finance",
        "symbol": "USDC",
        "apy": 8.5,
        "tvlUsd": 1_000_000.0,
        "chain": "Ethereum",
    },
    {
        "pool": "uuid-2",
        "project": "yearn-finance",
        "symbol": "USDC",
        "apy": 9.9,
        "tvlUsd": 5_000_000.0,
        "chain": "Ethereum",
    },
    {
        "pool": "uuid-3",
        "project": "euler",
        "symbol": "USDC",
        "apy": 12.0,
        "tvlUsd": 2_000_000.0,
        "chain": "Ethereum",
    },
    {
        "pool": "uuid-4",
        "project": "yearn-finance",
        "symbol": "USDC",
        "apy": 50.0,
        "tvlUsd": 100.0,
        "chain": "Polygon",
    },
]


class TestDeFiLlamaFeed:
    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_parses_payload_and_returns_pool(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        pool = feed.get_pool("yearn-finance", "USDC")
        assert pool is not None
        assert pool["project"] == "yearn-finance"

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_apy_percent_to_decimal(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        # highest-TVL Ethereum yearn pool has apy 9.9% -> 0.099
        assert feed.get_apy("yearn-finance", "USDC") == pytest.approx(0.099)

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_highest_tvl_selection(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        pool = feed.get_pool("yearn-finance", "USDC")
        assert pool["pool"] == "uuid-2"
        assert pool["tvlUsd"] == 5_000_000.0

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_get_tvl(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        assert feed.get_tvl("euler", "USDC") == 2_000_000.0

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_case_insensitive_match(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        pool = feed.get_pool("YEARN-FINANCE", "usdc", "ethereum")
        assert pool is not None
        assert pool["project"] == "yearn-finance"

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_chain_filter(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        pool = feed.get_pool("yearn-finance", "USDC", "Polygon")
        assert pool["pool"] == "uuid-4"

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_miss_returns_none(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True)
        assert feed.get_pool("nonexistent", "USDC") is None
        assert feed.get_apy("nonexistent", "USDC") is None
        assert feed.get_tvl("nonexistent", "USDC") is None

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_cache_single_http_call_within_ttl(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True, cache_ttl=300)
        feed.get_apy("yearn-finance", "USDC")
        feed.get_apy("euler", "USDC")
        feed.get_tvl("yearn-finance", "USDC")
        assert mock_get.call_count == 1

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_cache_refetch_after_ttl(self, mock_get):
        mock_get.return_value = _mock_response(_make_payload(SAMPLE_POOLS))
        feed = DeFiLlamaFeed(enabled=True, cache_ttl=0)
        feed.get_apy("yearn-finance", "USDC")
        feed.get_apy("yearn-finance", "USDC")
        assert mock_get.call_count == 2

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_network_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("boom")
        feed = DeFiLlamaFeed(enabled=True)
        assert feed.get_apy("yearn-finance", "USDC") is None
        assert feed.get_pool("yearn-finance", "USDC") is None

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_bad_status_payload_returns_none(self, mock_get):
        mock_get.return_value = _mock_response({"status": "error", "data": []})
        feed = DeFiLlamaFeed(enabled=True)
        assert feed.get_pool("yearn-finance", "USDC") is None

    @patch("spa_core.adapters.defillama_feed.requests.get")
    def test_disabled_short_circuits(self, mock_get):
        feed = DeFiLlamaFeed(enabled=False)
        assert feed.get_apy("yearn-finance", "USDC") is None
        assert feed.get_pool("yearn-finance", "USDC") is None
        assert feed.get_tvl("yearn-finance", "USDC") is None
        mock_get.assert_not_called()


ALL_ADAPTERS = [MorphoBlueAdapter, YearnV3Adapter, EulerV2Adapter, MapleAdapter]


class TestAdapterWiring:
    @pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
    def test_no_mock_attribute(self, adapter_cls):
        # SPA-V398: MOCK_APY removed everywhere — feed is mandatory.
        assert not hasattr(adapter_cls, "MOCK_APY")

    @pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
    def test_no_live_data_reports_error_not_mock(self, adapter_cls):
        feed = MagicMock()
        feed.get_apy.return_value = None
        feed.get_tvl.return_value = None
        adapter = adapter_cls(feed=feed)
        # Honest "no live data": apy is None, never a hard-coded value.
        assert adapter.get_apy() is None
        info = adapter.get_yield_info()
        assert info.apy is None
        data = adapter.fetch()
        assert data["status"] == "error"
        assert data["live_data"] is False
        assert data["error"] == "live_feed_unavailable"

    @pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
    def test_uses_live_value(self, adapter_cls):
        feed = MagicMock()
        feed.get_apy.return_value = 0.1234
        feed.get_tvl.return_value = 9_999_999.0
        adapter = adapter_cls(feed=feed)
        assert adapter.get_apy() == pytest.approx(0.1234)
        info = adapter.get_yield_info()
        assert info.apy == pytest.approx(0.1234)
        assert info.tvl_usd == 9_999_999.0
        feed.get_apy.assert_called_with(
            adapter_cls.DEFILLAMA_PROJECT, adapter_cls.DEFILLAMA_SYMBOL
        )

    @pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
    def test_feed_exception_is_graceful(self, adapter_cls):
        feed = MagicMock()
        feed.get_apy.side_effect = RuntimeError("net down")
        adapter = adapter_cls(feed=feed)
        # fetch() must never propagate — it reports an error record instead.
        data = adapter.fetch()
        assert data["status"] == "error"
        assert data["apy"] is None
        assert adapter.get_apy() is None

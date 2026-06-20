"""
tests/test_yield_aggregator_v2.py

Sprint v11.20 — MP-1504: Yield Aggregator v2 — 25 tests covering:
  - Source quality registry (SOURCE_QUALITY contents, ordering)
  - get_best_apy() — selects highest-reliability successful source
  - Fallback when all sources fail
  - DeFiLlama integration path with mocked client
  - aggregate_all() — multi-protocol result shape
  - Protocol→source hint mapping
  - to_dict() schema
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.data_pipeline.yield_aggregator_v2 import (
    YieldAggregatorV2,
    SOURCE_QUALITY,
    FALLBACK_APY,
    PROTOCOL_SOURCE_HINTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(project: str, chain: str = "ethereum", apy: float = 5.0) -> dict:
    return {"project": project, "chain": chain, "apy": apy, "tvlUsd": 10_000_000}


def _mock_dl_client(pools: list[dict]):
    """Return a mocked DeFiLlamaClient that yields given pools."""
    mock = MagicMock()
    mock.get_yields.return_value = pools
    return mock


def _aggregator_with_dl(pools: list[dict]) -> YieldAggregatorV2:
    """Return aggregator backed by mocked DeFiLlama client only."""
    return YieldAggregatorV2(defillama_client=_mock_dl_client(pools))


# ---------------------------------------------------------------------------
# 1. SOURCE_QUALITY registry
# ---------------------------------------------------------------------------

class TestSourceQualityRegistry(unittest.TestCase):

    def test_required_sources_present(self):
        for src in ("defillama", "aave_api", "compound_api", "morpho_api"):
            assert src in SOURCE_QUALITY, f"Missing source: {src}"

    def test_each_source_has_reliability(self):
        for src, meta in SOURCE_QUALITY.items():
            assert "reliability" in meta, f"{src} missing reliability"
            assert 0.0 <= meta["reliability"] <= 1.0

    def test_each_source_has_freshness_weight(self):
        for src, meta in SOURCE_QUALITY.items():
            assert "freshness_weight" in meta
            assert 0.0 <= meta["freshness_weight"] <= 1.0

    def test_aave_api_highest_reliability(self):
        reliabilities = {k: v["reliability"] for k, v in SOURCE_QUALITY.items()}
        max_r = max(reliabilities.values())
        assert reliabilities["aave_api"] == max_r or reliabilities["compound_api"] == max_r

    def test_defillama_lower_reliability_than_direct_apis(self):
        dl_r = SOURCE_QUALITY["defillama"]["reliability"]
        assert dl_r < SOURCE_QUALITY["aave_api"]["reliability"]
        assert dl_r < SOURCE_QUALITY["compound_api"]["reliability"]


# ---------------------------------------------------------------------------
# 2. get_best_apy() — fallback path
# ---------------------------------------------------------------------------

class TestGetBestApyFallback(unittest.TestCase):

    def _all_fail_aggregator(self) -> YieldAggregatorV2:
        agg = YieldAggregatorV2(defillama_client=_mock_dl_client([]))
        # All direct APIs return None (stubs); DeFiLlama returns empty list
        return agg

    def test_fallback_when_no_sources_match(self):
        agg = self._all_fail_aggregator()
        result = agg.get_best_apy("unknown-protocol")
        assert result["source"] == "fallback"
        assert result["apy"] == FALLBACK_APY

    def test_fallback_quality_is_zero(self):
        agg = self._all_fail_aggregator()
        result = agg.get_best_apy("unknown-protocol")
        assert result["quality"] == 0.0

    def test_fallback_sources_tried_logged(self):
        agg = self._all_fail_aggregator()
        result = agg.get_best_apy("unknown-protocol")
        assert isinstance(result["sources_tried"], list)
        assert len(result["sources_tried"]) > 0

    def test_fallback_apy_pct_equals_fallback_times_100(self):
        agg = self._all_fail_aggregator()
        result = agg.get_best_apy("any")
        assert abs(result["apy_pct"] - FALLBACK_APY * 100) < 1e-9


# ---------------------------------------------------------------------------
# 3. get_best_apy() — DeFiLlama success path
# ---------------------------------------------------------------------------

class TestGetBestApyDefiLlama(unittest.TestCase):

    def test_defillama_returns_apy_when_matched(self):
        pools = [_pool("aave-v3", apy=3.5)]
        agg = _aggregator_with_dl(pools)
        result = agg.get_best_apy("aave-v3")
        assert result["source"] == "defillama"
        assert abs(result["apy_pct"] - 3.5) < 1e-6

    def test_apy_fraction_is_pct_divided_by_100(self):
        pools = [_pool("compound-v3", apy=4.8)]
        agg = _aggregator_with_dl(pools)
        result = agg.get_best_apy("compound-v3")
        assert abs(result["apy"] - 4.8 / 100) < 1e-9

    def test_highest_apy_selected_among_multiple_pools(self):
        pools = [
            _pool("aave-v3", apy=3.0),
            _pool("aave-v3", apy=5.5),
            _pool("aave-v3", apy=2.0),
        ]
        agg = _aggregator_with_dl(pools)
        result = agg.get_best_apy("aave-v3")
        assert abs(result["apy_pct"] - 5.5) < 1e-6

    def test_case_insensitive_protocol_match(self):
        pools = [_pool("Aave-V3", apy=4.0)]
        agg = _aggregator_with_dl(pools)
        result = agg.get_best_apy("aave-v3")
        # DeFiLlama project match is case-insensitive
        assert result["source"] == "defillama"

    def test_result_quality_is_defillama_reliability(self):
        pools = [_pool("morpho", apy=6.0)]
        agg = _aggregator_with_dl(pools)
        result = agg.get_best_apy("morpho")
        assert result["quality"] == SOURCE_QUALITY["defillama"]["reliability"]


# ---------------------------------------------------------------------------
# 4. Source injection & direct API stubs
# ---------------------------------------------------------------------------

class TestSourceInjection(unittest.TestCase):

    def test_injected_client_is_used(self):
        mock_client = _mock_dl_client([_pool("aave-v3", apy=5.0)])
        agg = YieldAggregatorV2(defillama_client=mock_client)
        agg.get_best_apy("aave-v3")
        mock_client.get_yields.assert_called()

    def test_direct_api_overrides_defillama(self):
        """If a direct API returns data, it wins over DeFiLlama (higher reliability)."""
        pools = [_pool("aave-v3", apy=3.5)]
        agg = _aggregator_with_dl(pools)
        # Inject a successful aave_api fetch
        agg._fetch_aave_api = MagicMock(return_value=6.0)
        result = agg.get_best_apy("aave-v3")
        assert result["source"] == "aave_api"
        assert abs(result["apy_pct"] - 6.0) < 1e-6

    def test_source_exception_falls_through(self):
        """Exception in one source must not propagate — next source tried."""
        agg = _aggregator_with_dl([_pool("aave-v3", apy=4.0)])
        agg._fetch_aave_api = MagicMock(side_effect=RuntimeError("API down"))
        agg._fetch_compound_api = MagicMock(side_effect=RuntimeError("API down"))
        agg._fetch_morpho_api = MagicMock(side_effect=RuntimeError("API down"))
        result = agg.get_best_apy("aave-v3")
        # Falls through to DeFiLlama
        assert result["source"] == "defillama"


# ---------------------------------------------------------------------------
# 5. aggregate_all()
# ---------------------------------------------------------------------------

class TestAggregateAll(unittest.TestCase):

    def test_aggregate_all_returns_all_protocols(self):
        pools = [_pool("aave-v3", apy=3.5), _pool("yearn", apy=7.0)]
        agg = _aggregator_with_dl(pools)
        protocols = ["aave-v3", "yearn", "unknown"]
        results = agg.aggregate_all(protocols)
        assert set(results.keys()) == set(protocols)

    def test_aggregate_all_populates_internal_data(self):
        agg = _aggregator_with_dl([_pool("aave-v3", apy=4.0)])
        agg.aggregate_all(["aave-v3"])
        d = agg.to_dict()
        assert "aggregated_apys" in d
        assert "quality_scores" in d
        assert "last_update" in d
        assert d["last_update"] is not None

    def test_aggregate_all_unknown_falls_back(self):
        agg = _aggregator_with_dl([])
        results = agg.aggregate_all(["no-such-protocol"])
        assert results["no-such-protocol"]["source"] == "fallback"


# ---------------------------------------------------------------------------
# 6. Misc / edge cases
# ---------------------------------------------------------------------------

class TestMisc(unittest.TestCase):

    def test_quality_for_source_known(self):
        agg = YieldAggregatorV2()
        q = agg.quality_for_source("defillama")
        assert q["reliability"] == SOURCE_QUALITY["defillama"]["reliability"]

    def test_quality_for_source_unknown_returns_empty(self):
        agg = YieldAggregatorV2()
        assert agg.quality_for_source("nonexistent") == {}

    def test_protocol_source_hints_populated(self):
        assert "aave-v3" in PROTOCOL_SOURCE_HINTS
        assert "compound-v3" in PROTOCOL_SOURCE_HINTS

    def test_fallback_apy_is_four_percent(self):
        """FALLBACK_APY constant should be 4% (0.04)."""
        assert abs(FALLBACK_APY - 0.04) < 1e-9

    def test_to_dict_returns_dict(self):
        agg = YieldAggregatorV2()
        assert isinstance(agg.to_dict(), dict)


if __name__ == "__main__":
    unittest.main()

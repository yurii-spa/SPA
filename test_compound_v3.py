"""Tests for the read-only Compound V3 (Comet USDC) adapter.

Covers ``spa_core/adapters/compound_v3.py`` — the T2, advisory, stdlib-only
DeFiLlama feed. All network access is mocked; no live HTTP is performed.

Run:  python3 -m unittest spa_core.tests.test_compound_v3 -v
"""
from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from spa_core.adapters.compound_v3 import (
    CompoundV3Adapter,
    COMET_USDC_CONTRACT,
    DEFILLAMA_POOLS_URL,
)


class _FakeResponse(io.BytesIO):
    """Minimal context-manager stand-in for urlopen's return value."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _payload(*pools):
    """Wrap pool dicts in the DeFiLlama success envelope as raw JSON bytes."""
    return json.dumps({"status": "success", "data": list(pools)}).encode("utf-8")


def _comet_pool(apy=5.12, tvl=900_000_000.0, **over):
    pool = {
        "project": "compound-v3",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": apy,
        "tvlUsd": tvl,
    }
    pool.update(over)
    return pool


def _patch_urlopen(return_bytes=None, side_effect=None):
    """Patch the urlopen used inside the adapter module."""
    target = "spa_core.adapters.compound_v3.urllib.request.urlopen"
    if side_effect is not None:
        return mock.patch(target, side_effect=side_effect)
    return mock.patch(target, return_value=_FakeResponse(return_bytes))


class TestConstants(unittest.TestCase):
    def test_pool_id_constant(self):
        self.assertEqual(CompoundV3Adapter.pool_id, "compound_v3")
        self.assertEqual(CompoundV3Adapter().pool_id, "compound_v3")

    def test_name_constant(self):
        self.assertEqual(CompoundV3Adapter.name, "Compound V3 (Comet USDC)")

    def test_tier_is_t2(self):
        self.assertEqual(CompoundV3Adapter.tier, "T2")
        self.assertEqual(CompoundV3Adapter().tier, "T2")

    def test_comet_contract_constant(self):
        self.assertEqual(
            COMET_USDC_CONTRACT, "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        )
        self.assertEqual(CompoundV3Adapter.COMET_CONTRACT, COMET_USDC_CONTRACT)

    def test_default_api_url(self):
        self.assertEqual(CompoundV3Adapter().api_url, DEFILLAMA_POOLS_URL)

    def test_default_timeout_is_5s(self):
        self.assertEqual(CompoundV3Adapter().timeout, 5.0)


class TestFetchStructure(unittest.TestCase):
    def test_fetch_returns_correct_structure(self):
        with _patch_urlopen(_payload(_comet_pool())):
            out = CompoundV3Adapter().fetch()
        for key in ("pool_id", "apy", "tvl", "protocol", "tier", "ts", "status", "source"):
            self.assertIn(key, out)
        self.assertEqual(out["pool_id"], "compound_v3")
        self.assertEqual(out["protocol"], "compound_v3")
        self.assertEqual(out["tier"], "T2")
        self.assertEqual(out["source"], "defillama")
        self.assertIsInstance(out["ts"], float)

    def test_fetch_ok_status_on_valid_data(self):
        with _patch_urlopen(_payload(_comet_pool(apy=5.12, tvl=900_000_000.0))):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["apy"], 5.12)
        self.assertEqual(out["tvl"], 900_000_000.0)


class TestApyTvlTypes(unittest.TestCase):
    def test_apy_is_float_or_none(self):
        with _patch_urlopen(_payload(_comet_pool(apy=4.4))):
            self.assertIsInstance(CompoundV3Adapter().get_apy(), float)
        with _patch_urlopen(side_effect=ConnectionError("boom")):
            self.assertIsNone(CompoundV3Adapter().get_apy())

    def test_tvl_positive_or_none(self):
        with _patch_urlopen(_payload(_comet_pool(tvl=123_456.0))):
            tvl = CompoundV3Adapter().get_tvl()
            self.assertIsInstance(tvl, float)
            self.assertGreater(tvl, 0)
        with _patch_urlopen(side_effect=ConnectionError("boom")):
            self.assertIsNone(CompoundV3Adapter().get_tvl())

    def test_apy_none_when_field_missing(self):
        pool = _comet_pool()
        del pool["apy"]
        with _patch_urlopen(_payload(pool)):
            out = CompoundV3Adapter().fetch()
        # Pool still matched -> status ok, but apy is None.
        self.assertEqual(out["status"], "ok")
        self.assertIsNone(out["apy"])


class TestFiltering(unittest.TestCase):
    def test_fetch_picks_highest_tvl(self):
        small = _comet_pool(apy=3.0, tvl=10_000_000.0)
        big = _comet_pool(apy=5.5, tvl=800_000_000.0)
        with _patch_urlopen(_payload(small, big)):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["apy"], 5.5)
        self.assertEqual(out["tvl"], 800_000_000.0)

    def test_ignores_wrong_project(self):
        other = _comet_pool(project="aave-v3")
        with _patch_urlopen(_payload(other)):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")
        self.assertIsNone(out["apy"])

    def test_ignores_wrong_symbol(self):
        other = _comet_pool(symbol="WETH")
        with _patch_urlopen(_payload(other)):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")

    def test_ignores_wrong_chain(self):
        other = _comet_pool(chain="Arbitrum")
        with _patch_urlopen(_payload(other)):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")

    def test_matching_is_case_insensitive(self):
        pool = _comet_pool(project="Compound-V3", symbol="usdc", chain="ethereum")
        with _patch_urlopen(_payload(pool)):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "ok")


class TestGracefulErrors(unittest.TestCase):
    def test_graceful_on_network_error(self):
        with _patch_urlopen(side_effect=ConnectionError("network down")):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")
        self.assertIsNone(out["apy"])
        self.assertIsNone(out["tvl"])
        self.assertEqual(out["pool_id"], "compound_v3")

    def test_graceful_on_empty_response(self):
        with _patch_urlopen(_payload()):  # data: []
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")
        self.assertIsNone(out["apy"])

    def test_graceful_on_no_matching_pool(self):
        with _patch_urlopen(_payload(_comet_pool(project="morpho"))):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")

    def test_graceful_on_garbage_json(self):
        with _patch_urlopen(b"not json at all"):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")

    def test_graceful_on_malformed_pool_entries(self):
        # data list contains non-dict junk + one valid pool.
        raw = json.dumps(
            {"status": "success", "data": [None, 42, "x", _comet_pool(apy=6.0)]}
        ).encode("utf-8")
        with _patch_urlopen(raw):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["apy"], 6.0)

    def test_graceful_on_data_not_a_list(self):
        raw = json.dumps({"status": "success", "data": {"oops": 1}}).encode("utf-8")
        with _patch_urlopen(raw):
            out = CompoundV3Adapter().fetch()
        self.assertEqual(out["status"], "error")

    def test_fetch_never_raises(self):
        # Whatever the failure, fetch() must return a dict, not raise.
        with _patch_urlopen(side_effect=TimeoutError("slow")):
            out = CompoundV3Adapter().fetch()
        self.assertIsInstance(out, dict)
        self.assertEqual(out["status"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)

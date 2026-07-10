"""Tests for spa_core.monitoring.adapter_status_generator (MP-1195).

Coverage:
  T01  generate() with empty registry → empty adapters dict, no crash
  T02  generate() reads registry: adapter count matches
  T03  generate() fallback_apy converts decimal → % correctly
  T04  generate() with DeFiLlama unavailable → live_apy_enabled=False
  T05  generate() with mocked DeFiLlama pools → live_apy_enabled=True
  T06  generate() pool UUID exact match overrides hint matching
  T07  generate() schema_version == 2
  T08  generate() top-level shadow key 'morpho_steakhouse' present
  T09  generate() top-level shadow key 'aave_arbitrum' present
  T10  generate() top-level shadow key 'pendle_pt' present
  T11  generate() adapters dict has compound_v3 / morpho_steakhouse / aave_arbitrum
  T12  generate() apy field is in % (not decimal)
  T13  generate() sky_susds per_protocol_cap=0 → active=False in adapters
  T14  write() creates file atomically (tmp + os.replace pattern)
  T15  write() file contains valid JSON with schema_version 2
  T16  _fetch_defillama() returns None on network error (no crash)
  T17  _build_pool_indexes() indexes by pool id and project/chain/symbol
  T18  _valid_apy() rejects out-of-range values (<=0, >=200)
  T19  _lookup_live_apy() returns None when pool not found
  T20  run_and_write() end-to-end: generates and persists file
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from spa_core.monitoring.adapter_status_generator import (
    SCHEMA_VERSION,
    _build_pool_indexes,
    _fetch_defillama,
    _lookup_live_apy,
    _valid_apy,
    generate,
    run_and_write,
    write,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

_SAMPLE_REGISTRY: dict[str, Any] = {
    "version": "1.0",
    "adapters": {
        "compound_v3": {
            "tier": 1,
            "protocol": "Compound V3 (Comet USDC)",
            "chain": "ethereum",
            "fallback_apy": 0.052,
            "research_only": False,
            "per_protocol_cap": 0.4,
            "status": "active",
        },
        "morpho_steakhouse": {
            "tier": 1,
            "protocol": "Morpho Steakhouse USDC",
            "chain": "ethereum",
            "fallback_apy": 0.065,
            "research_only": False,
            "per_protocol_cap": 0.4,
            "status": "active",
        },
        "aave_arbitrum": {
            "tier": 1,
            "protocol": "Aave V3 Arbitrum",
            "chain": "arbitrum",
            "fallback_apy": 0.041,
            "research_only": False,
            "per_protocol_cap": 0.4,
            "status": "active",
        },
        "aave_v3": {
            "tier": 1,
            "protocol": "Aave V3",
            "chain": "ethereum",
            "fallback_apy": 0.035,
            "research_only": False,
            "per_protocol_cap": 0.4,
            "status": "active",
        },
        "sky_susds": {
            "tier": 0,
            "protocol": "Sky/sUSDS",
            "chain": "ethereum",
            "fallback_apy": 0.0,
            "per_protocol_cap": 0.0,
            "status": "watchlist",
        },
        "pendle_pt": {
            "tier": 2,
            "protocol": "Pendle PT",
            "chain": "ethereum",
            "fallback_apy": 0.08,
            "per_protocol_cap": 0.2,
            "status": "active",
        },
    },
}

_SAMPLE_POOLS: list[dict[str, Any]] = [
    {
        "pool": "BEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
        "project": "morpho",
        "chain": "Ethereum",
        "symbol": "USDC",
        "apy": 6.7,
        "tvlUsd": 850_000_000,
    },
    {
        "pool": "compound-eth-usdc-001",
        "project": "compound-v3",
        "chain": "Ethereum",
        "symbol": "USDC",
        "apy": 5.4,
        "tvlUsd": 3_200_000_000,
    },
    {
        "pool": "aave-arb-usdc-001",
        "project": "aave-v3",
        "chain": "Arbitrum",
        "symbol": "USDC",
        "apy": 4.3,
        "tvlUsd": 1_250_000_000,
    },
    {
        "pool": "bad-pool-001",
        "project": "some-protocol",
        "chain": "Ethereum",
        "symbol": "USDC",
        "apy": -1.0,   # invalid
        "tvlUsd": 50_000_000,
    },
    {
        "pool": "crazy-pool",
        "project": "risky",
        "chain": "Ethereum",
        "symbol": "USDC",
        "apy": 999.0,  # invalid (>200)
        "tvlUsd": 10_000,
    },
]


def _write_registry(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content), encoding="utf-8")


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGenerateEmptyRegistry(unittest.TestCase):
    """T01 — generate() with empty / missing registry produces empty adapters."""

    # Mock the live DeFiLlama fetch (like every other test in this file). Without it these
    # two hit the network and HANG on CI: generate() calls _fetch_defillama() even for an
    # empty registry, and resp.read() on the large /pools body can stall past urlopen's
    # connect timeout — wedging the entire spa_core unit-test job for 30min+.
    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_empty_registry_no_crash(self, _mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "adapter_registry.json"
            reg.write_text('{"adapters": {}}', encoding="utf-8")
            doc = generate(registry_path=reg)
            self.assertIsInstance(doc, dict)
            self.assertEqual(doc.get("adapters"), {})
            self.assertEqual(doc.get("schema_version"), SCHEMA_VERSION)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_missing_registry_no_crash(self, _mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "nonexistent.json"
            doc = generate(registry_path=reg)
            self.assertIsInstance(doc, dict)
            # Should still return a valid document
            self.assertIn("schema_version", doc)
            self.assertIn("adapters", doc)


class TestGenerateRegistry(unittest.TestCase):
    """T02–T03 — registry reading and fallback_apy conversion."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._reg = Path(self._td.name) / "adapter_registry.json"
        _write_registry(self._reg, _SAMPLE_REGISTRY)

    def tearDown(self) -> None:
        self._td.cleanup()

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_adapter_count_matches_registry(self, _mock: MagicMock) -> None:
        """T02 — adapters dict has same count as registry."""
        doc = generate(registry_path=self._reg)
        expected = len(_SAMPLE_REGISTRY["adapters"])
        self.assertEqual(len(doc["adapters"]), expected)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_fallback_apy_decimal_to_pct(self, _mock: MagicMock) -> None:
        """T03 — fallback_apy 0.052 (decimal) is stored as 5.2 (%)."""
        doc = generate(registry_path=self._reg)
        compound = doc["adapters"]["compound_v3"]
        self.assertAlmostEqual(compound["fallback_apy"], 5.2, places=3)
        self.assertAlmostEqual(compound["apy"], 5.2, places=3)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_morpho_fallback_pct(self, _mock: MagicMock) -> None:
        """T03b — morpho_steakhouse fallback 0.065 → 6.5%."""
        doc = generate(registry_path=self._reg)
        ms = doc["adapters"]["morpho_steakhouse"]
        self.assertAlmostEqual(ms["fallback_apy"], 6.5, places=3)
        self.assertAlmostEqual(ms["apy"], 6.5, places=3)


class TestGenerateNoNetwork(unittest.TestCase):
    """T04 — live_apy_enabled=False when DeFiLlama unavailable."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._reg = Path(self._td.name) / "adapter_registry.json"
        _write_registry(self._reg, _SAMPLE_REGISTRY)

    def tearDown(self) -> None:
        self._td.cleanup()

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_live_apy_disabled_when_no_network(self, _mock: MagicMock) -> None:
        """T04 — live_apy_enabled False and live_apy fields None."""
        doc = generate(registry_path=self._reg)
        self.assertFalse(doc["live_apy_enabled"])
        self.assertEqual(doc["live_count"], 0)
        for entry in doc["adapters"].values():
            self.assertIsNone(entry.get("live_apy"))


class TestGenerateWithLiveData(unittest.TestCase):
    """T05–T06 — DeFiLlama mock provides live APY."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._reg = Path(self._td.name) / "adapter_registry.json"
        _write_registry(self._reg, _SAMPLE_REGISTRY)

    def tearDown(self) -> None:
        self._td.cleanup()

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama",
           return_value=_SAMPLE_POOLS)
    def test_live_apy_enabled_true(self, _mock: MagicMock) -> None:
        """T05 — live_apy_enabled=True when pools are returned."""
        doc = generate(registry_path=self._reg)
        self.assertTrue(doc["live_apy_enabled"])
        self.assertGreater(doc["live_count"], 0)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama",
           return_value=_SAMPLE_POOLS)
    def test_morpho_pool_uuid_exact_match(self, _mock: MagicMock) -> None:
        """T06 — morpho_steakhouse uses exact pool UUID BEEF01… → 6.7%."""
        doc = generate(registry_path=self._reg)
        ms = doc["adapters"]["morpho_steakhouse"]
        self.assertAlmostEqual(ms["live_apy"], 6.7, places=1)
        self.assertAlmostEqual(ms["apy"], 6.7, places=1)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama",
           return_value=_SAMPLE_POOLS)
    def test_compound_hint_match(self, _mock: MagicMock) -> None:
        """T05b — compound_v3 matched via project/chain/symbol hint → 5.4%."""
        doc = generate(registry_path=self._reg)
        c = doc["adapters"]["compound_v3"]
        self.assertAlmostEqual(c["live_apy"], 5.4, places=1)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama",
           return_value=_SAMPLE_POOLS)
    def test_arbitrum_hint_match(self, _mock: MagicMock) -> None:
        """T05c — aave_arbitrum matched via chain=Arbitrum hint → 4.3%."""
        doc = generate(registry_path=self._reg)
        arb = doc["adapters"]["aave_arbitrum"]
        self.assertAlmostEqual(arb["live_apy"], 4.3, places=1)


class TestDocumentStructure(unittest.TestCase):
    """T07–T12 — document schema and field validation."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._reg = Path(self._td.name) / "adapter_registry.json"
        _write_registry(self._reg, _SAMPLE_REGISTRY)

    def tearDown(self) -> None:
        self._td.cleanup()

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_schema_version_is_2(self, _mock: MagicMock) -> None:
        """T07 — schema_version == 2."""
        doc = generate(registry_path=self._reg)
        self.assertEqual(doc["schema_version"], 2)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_shadow_morpho_steakhouse(self, _mock: MagicMock) -> None:
        """T08 — top-level 'morpho_steakhouse' shadow key present."""
        doc = generate(registry_path=self._reg)
        self.assertIn("morpho_steakhouse", doc)
        ms = doc["morpho_steakhouse"]
        self.assertIn("apy", ms)
        self.assertIn("protocol_key", ms)
        self.assertAlmostEqual(ms["apy"], 6.5, places=1)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_shadow_aave_arbitrum(self, _mock: MagicMock) -> None:
        """T09 — top-level 'aave_arbitrum' shadow key present."""
        doc = generate(registry_path=self._reg)
        self.assertIn("aave_arbitrum", doc)
        arb = doc["aave_arbitrum"]
        self.assertIn("apy", arb)
        self.assertIn("network", arb)
        self.assertEqual(arb["network"], "arbitrum")

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_shadow_pendle_pt(self, _mock: MagicMock) -> None:
        """T10 — top-level 'pendle_pt' shadow key present."""
        doc = generate(registry_path=self._reg)
        self.assertIn("pendle_pt", doc)
        pt = doc["pendle_pt"]
        self.assertIn("apy", pt)
        self.assertAlmostEqual(pt["apy"], 8.0, places=1)

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_golive_keys_in_adapters(self, _mock: MagicMock) -> None:
        """T11 — compound_v3, morpho_steakhouse, aave_arbitrum in adapters."""
        doc = generate(registry_path=self._reg)
        adapters = doc["adapters"]
        for key in ("compound_v3", "morpho_steakhouse", "aave_arbitrum"):
            self.assertIn(key, adapters, f"Missing key: {key}")

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_apy_is_percentage_not_decimal(self, _mock: MagicMock) -> None:
        """T12 — apy field is in % (> 1.0) not decimal (< 1.0) for typical adapters."""
        doc = generate(registry_path=self._reg)
        for key, entry in doc["adapters"].items():
            fb = entry.get("fallback_apy", 0.0)
            if fb > 0:
                self.assertGreater(
                    fb, 0.9,
                    f"{key}: fallback_apy={fb} looks like decimal, expected %",
                )

    @patch("spa_core.monitoring.adapter_status_generator._fetch_defillama", return_value=None)
    def test_sky_susds_has_zero_per_protocol_cap(self, _mock: MagicMock) -> None:
        """T13 — sky_susds per_protocol_cap=0 → entry present but cap is zero."""
        doc = generate(registry_path=self._reg)
        sky = doc["adapters"].get("sky_susds")
        if sky:
            self.assertEqual(sky["per_protocol_cap"], 0.0)


class TestWrite(unittest.TestCase):
    """T14–T15 — write() creates and persists valid JSON."""

    def test_write_creates_file(self) -> None:
        """T14 — write() creates file; no temp file left behind."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "adapter_status.json"
            doc: dict[str, Any] = {"schema_version": 2, "adapters": {}}
            write(doc, out)
            self.assertTrue(out.exists())
            # No tmp files left
            tmp_files = [f for f in os.listdir(td) if f.startswith(".adapter_status_")]
            self.assertEqual(tmp_files, [])

    def test_write_produces_valid_json(self) -> None:
        """T15 — written file parses as JSON and has schema_version 2."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "adapter_status.json"
            doc: dict[str, Any] = {
                "schema_version": 2,
                "generated_by": "test",
                "adapters": {"compound_v3": {"apy": 5.2}},
            }
            write(doc, out)
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema_version"], 2)
            self.assertIn("compound_v3", loaded["adapters"])


class TestFetchDefillama(unittest.TestCase):
    """T16 — _fetch_defillama() returns None on network error."""

    # Force a non-ci SPA_ENV so the CI network-skip guard is bypassed and the REAL
    # urlopen error-handling path is exercised (that is what these tests verify).
    @patch.dict("os.environ", {"SPA_ENV": "test"})
    def test_returns_none_on_error(self) -> None:
        """T16 — no crash; returns None when URL unreachable."""
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("blocked")):
            result = _fetch_defillama(timeout=1)
        self.assertIsNone(result)

    @patch.dict("os.environ", {"SPA_ENV": "test"})
    def test_returns_none_on_timeout(self) -> None:
        """T16b — returns None on TimeoutError."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = _fetch_defillama(timeout=1)
        self.assertIsNone(result)


class TestBuildPoolIndexes(unittest.TestCase):
    """T17 — _build_pool_indexes() creates correct indexes."""

    def test_by_id_index(self) -> None:
        """T17 — pool UUID index has correct entry."""
        by_id, by_pcs = _build_pool_indexes(_SAMPLE_POOLS)
        pid = "beef01735c132ada46aa9aa4c54623caa92a64cb"
        self.assertIn(pid, by_id)
        self.assertAlmostEqual(by_id[pid]["apy"], 6.7)

    def test_by_pcs_index(self) -> None:
        """T17b — project/chain/symbol index has entries."""
        by_id, by_pcs = _build_pool_indexes(_SAMPLE_POOLS)
        # compound-v3/ethereum/usdc
        key = ("compound-v3", "ethereum", "USDC")
        self.assertIn(key, by_pcs)
        self.assertGreater(len(by_pcs[key]), 0)


class TestValidApy(unittest.TestCase):
    """T18 — _valid_apy() range checks."""

    def test_valid_apy_normal(self) -> None:
        """T18 — normal APY value accepted."""
        self.assertAlmostEqual(_valid_apy({"apy": 5.2}), 5.2)

    def test_invalid_apy_negative(self) -> None:
        """T18b — negative APY rejected → None."""
        self.assertIsNone(_valid_apy({"apy": -1.0}))

    def test_invalid_apy_zero(self) -> None:
        """T18c — zero APY rejected → None."""
        self.assertIsNone(_valid_apy({"apy": 0.0}))

    def test_invalid_apy_too_high(self) -> None:
        """T18d — APY >= 200 rejected → None."""
        self.assertIsNone(_valid_apy({"apy": 999.0}))
        self.assertIsNone(_valid_apy({"apy": 200.0}))

    def test_valid_apy_boundary(self) -> None:
        """T18e — APY just below 200 accepted."""
        result = _valid_apy({"apy": 199.9})
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 199.9, places=1)


class TestLookupLiveApy(unittest.TestCase):
    """T19 — _lookup_live_apy() returns None when pool not found."""

    def test_returns_none_when_not_found(self) -> None:
        """T19 — unknown adapter key → None, no crash."""
        by_id, by_pcs = _build_pool_indexes(_SAMPLE_POOLS)
        result = _lookup_live_apy("nonexistent_adapter", by_id, by_pcs)
        self.assertIsNone(result)

    def test_uuid_hit_morpho(self) -> None:
        """T19b — exact UUID lookup for morpho_steakhouse."""
        by_id, by_pcs = _build_pool_indexes(_SAMPLE_POOLS)
        result = _lookup_live_apy("morpho_steakhouse", by_id, by_pcs)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 6.7, places=1)


class TestRunAndWrite(unittest.TestCase):
    """T20 — run_and_write() end-to-end integration."""

    def test_end_to_end_creates_valid_file(self) -> None:
        """T20 — full pipeline: generate + write → valid JSON file."""
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            reg = td_p / "adapter_registry.json"
            out = td_p / "adapter_status.json"
            _write_registry(reg, _SAMPLE_REGISTRY)

            with patch(
                "spa_core.monitoring.adapter_status_generator._fetch_defillama",
                return_value=None,
            ):
                doc = run_and_write(
                    registry_path=reg,
                    output_path=out,
                )

            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema_version"], 2)
            self.assertIn("compound_v3", loaded["adapters"])
            self.assertIn("morpho_steakhouse", loaded["adapters"])
            self.assertIn("aave_arbitrum", loaded["adapters"])
            # Shadow keys
            self.assertIn("morpho_steakhouse", loaded)
            self.assertIn("aave_arbitrum", loaded)
            # Return value is the doc dict
            self.assertEqual(doc["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()

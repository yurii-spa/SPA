"""
Tests for the adapter_status backend JSON source of truth (Sprint v3.33 / SPA-V333).

All tests are deterministic and network-free.  Mock APY values are verified by
importing the real adapter modules and comparing against their ``_DRY_RUN_APY``
dicts, so the test stays in lock-step with the adapters (the whole point of the
single-source-of-truth refactor).  Pattern mirrors test_pendle_pt_adapter.py.
"""
import json
import os
from unittest import mock

import pytest

from spa_core.execution import adapter_status
from spa_core.execution.adapter_status import (
    build_status_document,
    collect_adapter_status,
    write_status_json,
)

EXPECTED_PROTOCOL_KEYS = [
    "yearn-v3",
    "euler-v2",
    "maple",
    "pendle-pt",
    "sky-susds",
]

REQUIRED_FIELDS = (
    "protocol_key",
    "name",
    "tier",
    "allocation_cap",
    "chains",
    "assets",
    "mock_apy",
    "write_state",
    "apy_source",
)


@pytest.fixture
def adapters():
    return collect_adapter_status()


@pytest.fixture
def by_key(adapters):
    return {a["protocol_key"]: a for a in adapters}


# ─── Collection: count + identity ────────────────────────────────────────────

class TestCollectAdapterStatus:
    def test_returns_five_adapters(self, adapters):
        assert len(adapters) == 5

    def test_protocol_keys(self, adapters):
        keys = [a["protocol_key"] for a in adapters]
        assert keys == EXPECTED_PROTOCOL_KEYS

    def test_all_keys_unique(self, adapters):
        keys = [a["protocol_key"] for a in adapters]
        assert len(set(keys)) == len(keys)

    def test_no_errors_on_happy_path(self, adapters):
        assert all("error" not in a for a in adapters)

    def test_collect_does_not_raise(self):
        # Idempotent / repeatable with no side effects.
        collect_adapter_status()
        collect_adapter_status()


# ─── Required fields ─────────────────────────────────────────────────────────

class TestRequiredFields:
    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_has_required_fields(self, by_key, key):
        rec = by_key[key]
        for field in REQUIRED_FIELDS:
            assert field in rec, f"{key} missing {field}"

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_apy_source_shape(self, by_key, key):
        src = by_key[key]["apy_source"]
        assert src["mode"] == "mock"
        assert "live_project" in src
        assert isinstance(src["live_enabled"], bool)

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_chains_and_assets_nonempty(self, by_key, key):
        rec = by_key[key]
        assert rec["chains"], f"{key} has empty chains"
        assert rec["assets"], f"{key} has empty assets"


# ─── Tier values ─────────────────────────────────────────────────────────────

class TestTiers:
    def test_sky_is_conditional(self, by_key):
        assert by_key["sky-susds"]["tier"] == "T2-conditional"

    @pytest.mark.parametrize(
        "key", ["yearn-v3", "euler-v2", "maple", "pendle-pt"]
    )
    def test_others_are_t2(self, by_key, key):
        assert by_key[key]["tier"] == "T2"


# ─── Write-state values ──────────────────────────────────────────────────────

class TestWriteState:
    def test_pendle_not_implemented(self, by_key):
        assert by_key["pendle-pt"]["write_state"] == "NOT_IMPLEMENTED"

    @pytest.mark.parametrize(
        "key", ["yearn-v3", "euler-v2", "maple", "sky-susds"]
    )
    def test_others_blocked(self, by_key, key):
        assert by_key[key]["write_state"] == "BLOCKED"


# ─── Allocation cap ──────────────────────────────────────────────────────────

class TestAllocationCap:
    @pytest.mark.parametrize(
        "key", ["yearn-v3", "euler-v2", "maple", "pendle-pt"]
    )
    def test_t2_cap_is_020(self, by_key, key):
        assert by_key[key]["allocation_cap"] == 0.20

    def test_sky_cap_is_zero(self, by_key):
        assert by_key["sky-susds"]["allocation_cap"] == 0.0

    def test_sky_has_allocation_note(self, by_key):
        assert "allocation_note" in by_key["sky-susds"]
        assert "0.30" in by_key["sky-susds"]["allocation_note"]


# ─── Mock APY matches the adapter modules ────────────────────────────────────

class TestMockApyMatchesModules:
    def test_mock_apy_nonempty(self, by_key):
        for key in EXPECTED_PROTOCOL_KEYS:
            assert by_key[key]["mock_apy"], f"{key} mock_apy empty"

    def test_yearn_matches_module(self, by_key):
        from spa_core.execution.adapters import yearn_v3_adapter as m
        assert by_key["yearn-v3"]["mock_apy"] == m._DRY_RUN_APY

    def test_euler_matches_module(self, by_key):
        from spa_core.execution.adapters import euler_v2_adapter as m
        assert by_key["euler-v2"]["mock_apy"] == m._DRY_RUN_APY

    def test_maple_matches_module(self, by_key):
        from spa_core.execution.adapters import maple_adapter as m
        assert by_key["maple"]["mock_apy"] == m._DRY_RUN_APY

    def test_pendle_matches_module(self, by_key):
        from spa_core.execution.adapters import pendle_pt_adapter as m
        assert by_key["pendle-pt"]["mock_apy"] == m._DRY_RUN_APY

    def test_sky_matches_module(self, by_key):
        from spa_core.execution.adapters import sky_susds_adapter as m
        assert by_key["sky-susds"]["mock_apy"] == m._DRY_RUN_APY

    def test_chains_match_module(self, by_key):
        from spa_core.execution.adapters import yearn_v3_adapter as m
        assert by_key["yearn-v3"]["chains"] == list(m.YearnV3Adapter.SUPPORTED_CHAINS)


# ─── Document assembly ───────────────────────────────────────────────────────

class TestBuildStatusDocument:
    def test_top_level_fields(self):
        doc = build_status_document()
        assert "generated_at" in doc
        assert doc["schema_version"] == 1
        assert "adapters" in doc
        assert "execution_mode" in doc
        assert "live_apy_enabled" in doc

    def test_adapters_count(self):
        assert len(build_status_document()["adapters"]) == 5

    def test_generated_at_is_iso8601_utc(self):
        from datetime import datetime
        doc = build_status_document()
        # Parses without error and carries timezone info.
        parsed = datetime.fromisoformat(doc["generated_at"])
        assert parsed.tzinfo is not None

    def test_execution_mode_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_EXECUTION_MODE", None)
            assert build_status_document()["execution_mode"] == "dry_run"

    def test_document_is_json_serialisable(self):
        # Round-trips through json without raising.
        json.dumps(build_status_document())


# ─── write_status_json ───────────────────────────────────────────────────────

class TestWriteStatusJson:
    def test_writes_valid_json(self, tmp_path):
        out = tmp_path / "adapter_status.json"
        returned = write_status_json(out)
        assert returned == str(out)
        assert out.exists()
        with out.open() as fh:
            data = json.load(fh)
        assert data["schema_version"] == 1
        assert len(data["adapters"]) == 5

    def test_creates_parent_dir(self, tmp_path):
        out = tmp_path / "nested" / "deeper" / "adapter_status.json"
        write_status_json(out)
        assert out.exists()

    def test_roundtrip_preserves_protocol_keys(self, tmp_path):
        out = tmp_path / "adapter_status.json"
        write_status_json(out)
        with out.open() as fh:
            data = json.load(fh)
        keys = [a["protocol_key"] for a in data["adapters"]]
        assert keys == EXPECTED_PROTOCOL_KEYS


# ─── live_apy_enabled gate ───────────────────────────────────────────────────

class TestLiveApyGate:
    def test_live_apy_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_LIVE_APY", None)
            doc = build_status_document()
            assert doc["live_apy_enabled"] is False
            assert all(
                a["apy_source"]["live_enabled"] is False
                for a in doc["adapters"]
            )

    def test_live_apy_enabled_via_env(self):
        with mock.patch.dict(os.environ, {"SPA_LIVE_APY": "true"}):
            doc = build_status_document()
            assert doc["live_apy_enabled"] is True
            assert all(
                a["apy_source"]["live_enabled"] is True
                for a in doc["adapters"]
            )

    def test_live_apy_gate_helper_default_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_LIVE_APY", None)
            assert adapter_status._live_apy_enabled() is False


# ─── Live APY enrichment (Sprint v3.35 / SPA-V335) ───────────────────────────

class TestLiveApyEnrichment:
    """Live APY embedding is gated on SPA_LIVE_APY and degrades gracefully."""

    def test_no_live_apy_field_when_disabled(self):
        """With the gate off, no record carries a live_apy map and mode=mock."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_LIVE_APY", None)
            for rec in collect_adapter_status():
                assert "live_apy" not in rec
                assert rec["apy_source"]["mode"] == "mock"
                assert rec["apy_source"]["live_values_present"] is False

    def test_feed_not_touched_when_disabled(self, monkeypatch):
        """The feed (network) must never be queried when the gate is off."""
        from spa_core.execution import defillama_apy_feed

        calls = []

        def _spy(protocol, asset, chain):
            calls.append((protocol, asset, chain))
            return 9.99

        monkeypatch.setattr(defillama_apy_feed, "get_live_apy", _spy)
        monkeypatch.delenv("SPA_LIVE_APY", raising=False)
        collect_adapter_status()
        assert calls == []

    def test_live_values_embedded_when_enabled(self, monkeypatch):
        """With the gate on and the feed returning a number, live_apy is embedded."""
        from spa_core.execution import defillama_apy_feed

        monkeypatch.setattr(
            defillama_apy_feed, "get_live_apy",
            lambda protocol, asset, chain: 8.25,
        )
        monkeypatch.setenv("SPA_LIVE_APY", "true")

        by_key = {a["protocol_key"]: a for a in collect_adapter_status()}
        yearn = by_key["yearn-v3"]
        assert "live_apy" in yearn
        assert yearn["apy_source"]["mode"] == "live"
        assert yearn["apy_source"]["live_values_present"] is True
        # live_apy keys are a subset of the mock_apy (chain, asset) combos.
        for chain, assets in yearn["live_apy"].items():
            assert chain in yearn["mock_apy"]
            for asset, apy in assets.items():
                assert asset in yearn["mock_apy"][chain]
                assert apy == 8.25

    def test_live_apy_omitted_when_feed_returns_none(self, monkeypatch):
        """Feed returning None for every pair → no live_apy, mode stays mock."""
        from spa_core.execution import defillama_apy_feed

        monkeypatch.setattr(
            defillama_apy_feed, "get_live_apy",
            lambda protocol, asset, chain: None,
        )
        monkeypatch.setenv("SPA_LIVE_APY", "true")

        for rec in collect_adapter_status():
            assert "live_apy" not in rec
            assert rec["apy_source"]["mode"] == "mock"
            assert rec["apy_source"]["live_values_present"] is False

    def test_live_apy_never_raises_on_feed_error(self, monkeypatch):
        """A feed that raises must not abort collection — graceful empty map."""
        from spa_core.execution import defillama_apy_feed

        def _boom(protocol, asset, chain):
            raise RuntimeError("network down")

        monkeypatch.setattr(defillama_apy_feed, "get_live_apy", _boom)
        monkeypatch.setenv("SPA_LIVE_APY", "true")

        adapters = collect_adapter_status()  # must not raise
        assert len(adapters) == 5
        for rec in adapters:
            assert "live_apy" not in rec
            assert rec["apy_source"]["mode"] == "mock"

    def test_fetch_live_apy_map_subset(self, monkeypatch):
        """_fetch_live_apy_map keeps only non-None pairs, omitting empty chains."""
        from spa_core.execution import defillama_apy_feed

        mock_apy = {
            "ethereum": {"USDC": 6.8, "USDT": 6.5},
            "arbitrum": {"USDC": 7.1},
        }

        def _selective(protocol, asset, chain):
            # Only ethereum/USDC resolves; everything else misses.
            if chain == "ethereum" and asset == "USDC":
                return 6.42
            return None

        monkeypatch.setattr(defillama_apy_feed, "get_live_apy", _selective)
        out = adapter_status._fetch_live_apy_map("yearn-v3", mock_apy)
        assert out == {"ethereum": {"USDC": 6.42}}

    def test_partial_live_flips_mode_to_live(self, monkeypatch):
        """Even a single live match flips the source to live."""
        from spa_core.execution import defillama_apy_feed

        def _one_hit(protocol, asset, chain):
            return 5.0 if (protocol == "maple") else None

        monkeypatch.setattr(defillama_apy_feed, "get_live_apy", _one_hit)
        monkeypatch.setenv("SPA_LIVE_APY", "true")
        by_key = {a["protocol_key"]: a for a in collect_adapter_status()}
        assert by_key["maple"]["apy_source"]["mode"] == "live"
        assert by_key["yearn-v3"]["apy_source"]["mode"] == "mock"

    def test_document_with_live_is_json_serialisable(self, monkeypatch):
        from spa_core.execution import defillama_apy_feed

        monkeypatch.setattr(
            defillama_apy_feed, "get_live_apy",
            lambda protocol, asset, chain: 7.0,
        )
        monkeypatch.setenv("SPA_LIVE_APY", "true")
        doc = build_status_document()
        json.dumps(doc)  # must not raise
        assert doc["live_apy_enabled"] is True
        assert any("live_apy" in a for a in doc["adapters"])


# ─── Resilience: broken adapter does not abort collection ────────────────────

class TestResilience:
    def test_broken_import_yields_error_record(self):
        broken = dict(adapter_status._ADAPTER_SPECS[0])
        broken["module"] = "spa_core.execution.adapters.does_not_exist"
        rec = adapter_status._adapter_record(broken, live_enabled=False)
        assert "error" in rec
        # Graceful defaults so downstream consumers never KeyError.
        assert rec["chains"] == []
        assert rec["assets"] == []
        assert rec["mock_apy"] == {}

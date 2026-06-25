"""
Tests for SkySUSDSAdapter (Sprint v3.29 / SPA-V329-001) — conditional T1.

All tests are deterministic with NO real network: eligibility / DeFiLlama /
env are patched via unittest.mock. Dry-run mode is the default for read paths.
"""
import os
from unittest import mock

import pytest

from spa_core.execution.adapters.sky_susds_adapter import (
    SkySUSDSAdapter,
    PositionInfo,
)

_PENDING = {
    "protocol": "Sky/sUSDS",
    "status": "PENDING",
    "eligible_for_t1": False,
    "allocation_pct": 0.0,
}
_ELIGIBLE = {
    "protocol": "Sky/sUSDS",
    "status": "ELIGIBLE",
    "eligible_for_t1": True,
    "allocation_pct": 0.30,
    "gsm_hours": 72.0,
}


def _alloc_pct(status_dict):
    """Mirror sky_monitor.get_sky_allocation_pct for patched calls."""
    return 0.30 if status_dict.get("status") == "ELIGIBLE" else 0.0


@pytest.fixture
def adapter():
    return SkySUSDSAdapter(chain="ethereum", dry_run=True)


@pytest.fixture
def patch_pending():
    """Patch sky_monitor so both manual + live return PENDING."""
    with mock.patch("spa_core.data_pipeline.sky_monitor.check_sky_status", return_value=_PENDING), \
         mock.patch("spa_core.data_pipeline.sky_monitor.check_sky_status_live", return_value=_PENDING), \
         mock.patch("spa_core.data_pipeline.sky_monitor.get_sky_allocation_pct", side_effect=_alloc_pct):
        yield


@pytest.fixture
def patch_eligible():
    """Patch sky_monitor so both manual + live return ELIGIBLE."""
    with mock.patch("spa_core.data_pipeline.sky_monitor.check_sky_status", return_value=_ELIGIBLE), \
         mock.patch("spa_core.data_pipeline.sky_monitor.check_sky_status_live", return_value=_ELIGIBLE), \
         mock.patch("spa_core.data_pipeline.sky_monitor.get_sky_allocation_pct", side_effect=_alloc_pct):
        yield


# ─── Init ─────────────────────────────────────────────────────────────────────

class TestInit:
    def test_default_chain(self):
        assert SkySUSDSAdapter().chain == "ethereum"

    def test_default_dry_run(self):
        assert SkySUSDSAdapter().dry_run is True

    def test_explicit_chain(self):
        assert SkySUSDSAdapter(chain="ethereum", dry_run=False).dry_run is False

    def test_unsupported_chain_raises(self):
        with pytest.raises(ValueError):
            SkySUSDSAdapter(chain="arbitrum")

    def test_supported_assets(self):
        assert "USDS" in SkySUSDSAdapter.SUPPORTED_ASSETS
        assert "DAI" in SkySUSDSAdapter.SUPPORTED_ASSETS


# ─── Validation ─────────────────────────────────────────────────────────────

class TestValidation:
    def test_supply_zero_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("USDS", 0.0)

    def test_supply_negative_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("USDS", -10.0)

    def test_supply_over_cap_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("USDS", 20_000_000.0)

    def test_supply_unsupported_asset_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("USDC", 100.0)

    def test_withdraw_zero_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.withdraw("USDS", 0.0)

    def test_withdraw_negative_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.withdraw("USDS", -5.0)

    def test_withdraw_unsupported_asset_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.withdraw("WBTC", 100.0)


# ─── Dry-run supply / withdraw ────────────────────────────────────────────────

class TestDryRunSupply:
    def test_supply_usds_dry_run(self, adapter, patch_pending):
        r = adapter.supply("USDS", 1000.0)
        assert r["status"] == "DRY_RUN"
        assert r["protocol"] == "sky-susds"
        assert r["asset"] == "USDS"
        assert r["amount"] == 1000.0

    def test_supply_dai_dry_run(self, adapter, patch_pending):
        r = adapter.supply("DAI", 500.0)
        assert r["status"] == "DRY_RUN"
        assert r["asset"] == "DAI"

    def test_supply_lowercase_normalised(self, adapter, patch_pending):
        r = adapter.supply("usds", 100.0)
        assert r["asset"] == "USDS"

    def test_supply_has_tx_hash(self, adapter, patch_pending):
        r = adapter.supply("USDS", 100.0)
        assert r["tx_hash"] == "0xdry_sky_supply_usds"

    def test_supply_has_shares(self, adapter, patch_pending):
        r = adapter.supply("USDS", 1000.0)
        assert r["pool_shares_minted"] > 0

    def test_supply_dryrun_includes_tier_and_eligible(self, adapter, patch_pending):
        r = adapter.supply("USDS", 100.0)
        assert "tier" in r
        assert "eligible_t1" in r
        assert r["eligible_t1"] is False

    def test_supply_dryrun_eligible_flag_true(self, adapter, patch_eligible):
        r = adapter.supply("USDS", 100.0)
        assert r["eligible_t1"] is True
        assert r["tier"] == "T1"


class TestDryRunWithdraw:
    def test_withdraw_usds_dry_run(self, adapter, patch_pending):
        r = adapter.withdraw("USDS", 500.0)
        assert r["status"] == "DRY_RUN"
        assert r["protocol"] == "sky-susds"
        assert r["tx_hash"] == "0xdry_sky_withdraw_usds"

    def test_withdraw_has_shares_burned(self, adapter, patch_pending):
        r = adapter.withdraw("USDS", 500.0)
        assert r["shares_burned"] > 0


# ─── Conditional-T1 eligibility ───────────────────────────────────────────────

class TestEligibilityPending:
    def test_get_tier_pending(self, adapter, patch_pending):
        assert adapter.get_tier() == "T2-conditional"

    def test_is_eligible_false_pending(self, adapter, patch_pending):
        assert adapter.is_eligible_t1() is False

    def test_allocation_cap_pending(self, adapter, patch_pending):
        assert adapter.get_allocation_cap() == 0.0


class TestEligibilityEligible:
    def test_get_tier_eligible(self, adapter, patch_eligible):
        assert adapter.get_tier() == "T1"

    def test_is_eligible_true_eligible(self, adapter, patch_eligible):
        assert adapter.is_eligible_t1() is True

    def test_allocation_cap_eligible(self, adapter, patch_eligible):
        assert adapter.get_allocation_cap() == 0.30


class TestEligibilitySafe:
    def test_eligibility_never_raises_on_error(self, adapter):
        with mock.patch(
            "spa_core.data_pipeline.sky_monitor.check_sky_status",
            side_effect=RuntimeError("boom"),
        ):
            assert adapter.is_eligible_t1() is False
            assert adapter.get_tier() == "T2-conditional"

    def test_allocation_cap_safe_on_error(self, adapter):
        with mock.patch(
            "spa_core.data_pipeline.sky_monitor.check_sky_status",
            side_effect=RuntimeError("boom"),
        ):
            assert adapter.get_allocation_cap() == 0.0


# ─── Conditional-T1 live gate (BLOCKED) ───────────────────────────────────────

class TestConditionalGate:
    def test_live_blocked_when_not_eligible(self, patch_pending):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_EXECUTION_MODE", None)
            r = a.supply("USDS", 1000.0)
        assert r["status"] == "BLOCKED"
        assert "ELIGIBLE" in r["reason"]
        assert r["eligible_t1"] is False

    def test_live_blocked_not_eligible_even_with_mode_live(self, patch_pending):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch.dict(os.environ, {"SPA_EXECUTION_MODE": "live"}):
            r = a.supply("USDS", 1000.0)
        # Eligibility gate fires first → still blocked on ELIGIBLE reason.
        assert r["status"] == "BLOCKED"
        assert "ELIGIBLE" in r["reason"]

    def test_live_blocked_eligible_but_mode_not_live(self, patch_eligible):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_EXECUTION_MODE", None)
            r = a.supply("USDS", 1000.0)
        assert r["status"] == "BLOCKED"
        assert r["reason"] == "SPA_EXECUTION_MODE is not 'live'"

    def test_withdraw_live_blocked_when_not_eligible(self, patch_pending):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_EXECUTION_MODE", None)
            r = a.withdraw("USDS", 500.0)
        assert r["status"] == "BLOCKED"
        assert "ELIGIBLE" in r["reason"]

    def test_withdraw_live_blocked_eligible_mode_not_live(self, patch_eligible):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPA_EXECUTION_MODE", None)
            r = a.withdraw("USDS", 500.0)
        assert r["status"] == "BLOCKED"
        assert r["reason"] == "SPA_EXECUTION_MODE is not 'live'"


# ─── APY ──────────────────────────────────────────────────────────────────────

class TestAPY:
    def test_get_supply_apy_dry_run_usds(self, adapter):
        assert adapter.get_supply_apy("USDS") == 6.5

    def test_get_supply_apy_dry_run_dai(self, adapter):
        assert adapter.get_supply_apy("DAI") == 6.5

    def test_get_apy_alias(self, adapter):
        assert adapter.get_apy("USDS") == adapter.get_supply_apy("USDS")

    def test_get_supply_apy_unknown_fallback(self, adapter):
        # Unknown asset (not validated here) → fallback mock 6.0
        assert adapter.get_supply_apy("ZZZ") == 6.0

    def test_live_apy_via_defillama(self):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch(
            "spa_core.execution.defillama_apy_feed.live_apy_enabled",
            return_value=True,
        ), mock.patch(
            "spa_core.execution.defillama_apy_feed.get_live_apy",
            return_value=7.25,
        ):
            assert a.get_supply_apy("USDS") == 7.25

    def test_live_apy_none_falls_back_to_mock(self):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch(
            "spa_core.execution.defillama_apy_feed.live_apy_enabled",
            return_value=True,
        ), mock.patch(
            "spa_core.execution.defillama_apy_feed.get_live_apy",
            return_value=None,
        ):
            assert a.get_supply_apy("USDS") == 6.5

    def test_live_apy_disabled_uses_mock(self):
        a = SkySUSDSAdapter(chain="ethereum", dry_run=False)
        with mock.patch(
            "spa_core.execution.defillama_apy_feed.live_apy_enabled",
            return_value=False,
        ):
            assert a.get_supply_apy("USDS") == 6.5


# ─── Read interface ───────────────────────────────────────────────────────────

class TestReadInterface:
    def test_get_supply_balance_dry_run(self, adapter):
        assert adapter.get_supply_balance("USDS") == 1500.0

    def test_get_position_dry_run(self, adapter):
        pos = adapter.get_position("0xabc", "USDS")
        assert isinstance(pos, PositionInfo)
        assert pos.asset == "USDS"
        assert pos.balance_tokens == 1500.0
        assert pos.protocol == "sky-susds"

    def test_is_healthy(self, adapter):
        assert adapter.is_healthy() is True

    def test_health_check_contains_tier(self, adapter, patch_pending):
        hc = adapter.health_check()
        assert hc["protocol"] == "sky-susds"
        assert "tier" in hc
        assert "eligible_t1" in hc
        assert "allocation_cap" in hc
        assert hc["is_healthy"] is True

    def test_health_check_tier_eligible(self, adapter, patch_eligible):
        hc = adapter.health_check()
        assert hc["tier"] == "T1"
        assert hc["allocation_cap"] == 0.30


# ─── engine_bridge integration ────────────────────────────────────────────────

class TestEngineBridgeIntegration:
    def test_parse_protocol_key_resolves_family(self):
        from spa_core.execution.engine_bridge import _parse_protocol_key
        parsed = _parse_protocol_key("sky-susds-usds-ethereum")
        assert parsed is not None
        assert parsed["family"] == "sky_susds"
        assert parsed["asset"] == "USDS"
        assert parsed["chain"] == "ethereum"

    def test_get_adapter_returns_sky_adapter(self):
        from spa_core.execution.engine_bridge import LiveExecutionBridge
        bridge = LiveExecutionBridge()
        adapter = bridge._get_adapter("sky_susds", "ethereum")
        assert adapter is not None
        assert isinstance(adapter, SkySUSDSAdapter)

    def test_prefix_to_family_registered(self):
        from spa_core.execution.engine_bridge import _PROTOCOL_PREFIX_TO_FAMILY
        assert _PROTOCOL_PREFIX_TO_FAMILY.get("sky-susds") == "sky_susds"


# ─── defillama_apy_feed registration ──────────────────────────────────────────

class TestDefiLlamaMatch:
    def test_sky_protocol_match_present(self):
        from spa_core.execution.defillama_apy_feed import _PROTOCOL_PROJECT_MATCH
        assert _PROTOCOL_PROJECT_MATCH.get("sky-susds") == "sky"
        assert _PROTOCOL_PROJECT_MATCH.get("sky") == "sky"
        assert _PROTOCOL_PROJECT_MATCH.get("susds") == "sky"

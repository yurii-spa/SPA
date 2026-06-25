"""
Tests for EulerV2Adapter (Sprint v3.25 / SPA-V325-002).

All tests run in dry_run=True mode — no live RPC calls.
"""
import os
import pytest
from spa_core.execution.adapters.euler_v2_adapter import EulerV2Adapter, PositionInfo


@pytest.fixture
def adapter():
    return EulerV2Adapter(chain="ethereum", dry_run=True)


class TestEulerV2AdapterInit:
    def test_default_chain_is_ethereum(self):
        assert EulerV2Adapter().chain == "ethereum"

    def test_default_dry_run_is_true(self):
        assert EulerV2Adapter().dry_run is True

    def test_unsupported_chain_raises(self):
        with pytest.raises(ValueError):
            EulerV2Adapter(chain="base")

    def test_unsupported_asset_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("DAI", 100.0)


class TestEulerV2AdapterSupply:
    def test_supply_usdc_dry_run(self, adapter):
        result = adapter.supply("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "euler-v2"
        assert result["asset"] == "USDC"

    def test_supply_usdt_dry_run(self, adapter):
        result = adapter.supply("USDT", 500.0)
        assert result["status"] == "DRY_RUN"
        assert result["asset"] == "USDT"

    def test_supply_lowercase_normalised(self, adapter):
        result = adapter.supply("usdc", 100.0)
        assert result["asset"] == "USDC"

    def test_supply_has_vault(self, adapter):
        result = adapter.supply("USDC", 100.0)
        assert result["vault"].startswith("0x")

    def test_supply_has_shares(self, adapter):
        result = adapter.supply("USDC", 1000.0)
        assert result["shares_minted"] > 0

    def test_supply_zero_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.supply("USDC", 0.0)

    def test_supply_negative_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.supply("USDC", -1.0)

    def test_supply_over_cap_raises(self, adapter):
        with pytest.raises(ValueError, match="sanity cap"):
            adapter.supply("USDC", 10_000_001.0)

    def test_supply_blocked_when_not_live(self):
        a = EulerV2Adapter(chain="ethereum", dry_run=False)
        result = a.supply("USDC", 100.0)
        assert result["status"] == "BLOCKED"


class TestEulerV2AdapterWithdraw:
    def test_withdraw_usdc_dry_run(self, adapter):
        result = adapter.withdraw("USDC", 500.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "euler-v2"

    def test_withdraw_has_shares_burned(self, adapter):
        result = adapter.withdraw("USDC", 500.0)
        assert result["shares_burned"] > 0

    def test_withdraw_zero_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.withdraw("USDC", 0.0)

    def test_withdraw_blocked_when_not_live(self):
        a = EulerV2Adapter(chain="ethereum", dry_run=False)
        result = a.withdraw("USDC", 100.0)
        assert result["status"] == "BLOCKED"


class TestEulerV2AdapterReads:
    def test_get_supply_apy_reasonable(self, adapter):
        apy = adapter.get_supply_apy("USDC")
        assert 3.0 <= apy <= 20.0

    def test_get_apy_alias(self, adapter):
        assert adapter.get_apy("USDC") == adapter.get_supply_apy("USDC")

    def test_get_supply_balance_positive(self, adapter):
        assert adapter.get_supply_balance("USDC") > 0

    def test_get_supply_balance_usdt(self, adapter):
        assert adapter.get_supply_balance("USDT") >= 0


class TestEulerV2AdapterPosition:
    WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

    def test_position_type(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert isinstance(pos, PositionInfo)

    def test_position_wallet(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.wallet_address == self.WALLET

    def test_position_protocol(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.protocol == "euler-v2"

    def test_position_vault_address(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.vault_address.startswith("0x")

    def test_position_apy_reasonable(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert 3.0 <= pos.current_apy <= 20.0


class TestEulerV2AdapterHealth:
    def test_is_healthy_true(self, adapter):
        assert adapter.is_healthy() is True

    def test_health_check_schema(self, adapter):
        hc = adapter.health_check()
        assert hc["protocol"] == "euler-v2"
        assert hc["chain"] == "ethereum"
        assert hc["is_healthy"] is True
        assert "vaults" in hc

"""
Tests for MapleAdapter (Sprint v3.25 / SPA-V325-003).

All tests run in dry_run=True mode — no live RPC calls.
"""
import pytest
from spa_core.execution.adapters.maple_adapter import MapleAdapter, PositionInfo


@pytest.fixture
def adapter():
    return MapleAdapter(chain="ethereum", dry_run=True)


class TestMapleAdapterInit:
    def test_default_chain(self):
        assert MapleAdapter().chain == "ethereum"

    def test_default_dry_run(self):
        assert MapleAdapter().dry_run is True

    def test_unsupported_chain_raises(self):
        with pytest.raises(ValueError):
            MapleAdapter(chain="arbitrum")

    def test_unsupported_asset_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("USDT", 100.0)


class TestMapleAdapterSupply:
    def test_supply_usdc_dry_run(self, adapter):
        result = adapter.supply("USDC", 2000.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "maple"
        assert result["asset"] == "USDC"
        assert result["amount"] == 2000.0

    def test_supply_lowercase_normalised(self, adapter):
        result = adapter.supply("usdc", 500.0)
        assert result["asset"] == "USDC"

    def test_supply_has_pool_address(self, adapter):
        result = adapter.supply("USDC", 500.0)
        assert result["pool"].startswith("0x")

    def test_supply_has_shares(self, adapter):
        result = adapter.supply("USDC", 1000.0)
        assert result["pool_shares_minted"] > 0

    def test_supply_has_note(self, adapter):
        result = adapter.supply("USDC", 100.0)
        assert "note" in result

    def test_supply_zero_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.supply("USDC", 0.0)

    def test_supply_negative_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.supply("USDC", -100.0)

    def test_supply_over_cap_raises(self, adapter):
        with pytest.raises(ValueError, match="sanity cap"):
            adapter.supply("USDC", 10_000_001.0)

    def test_supply_blocked_when_not_live(self):
        a = MapleAdapter(dry_run=False)
        result = a.supply("USDC", 100.0)
        assert result["status"] == "BLOCKED"


class TestMapleAdapterWithdraw:
    def test_withdraw_usdc_dry_run(self, adapter):
        result = adapter.withdraw("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "maple"

    def test_withdraw_has_shares_burned(self, adapter):
        result = adapter.withdraw("USDC", 1000.0)
        assert result["shares_burned"] > 0

    def test_withdraw_has_note(self, adapter):
        result = adapter.withdraw("USDC", 100.0)
        assert "note" in result

    def test_withdraw_zero_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.withdraw("USDC", 0.0)

    def test_withdraw_blocked_when_not_live(self):
        a = MapleAdapter(dry_run=False)
        result = a.withdraw("USDC", 100.0)
        assert result["status"] == "BLOCKED"


class TestMapleAdapterReads:
    def test_get_supply_apy_reasonable(self, adapter):
        apy = adapter.get_supply_apy("USDC")
        assert 2.0 <= apy <= 12.0

    def test_get_apy_alias(self, adapter):
        assert adapter.get_apy("USDC") == adapter.get_supply_apy("USDC")

    def test_get_supply_balance_positive(self, adapter):
        assert adapter.get_supply_balance("USDC") > 0


class TestMapleAdapterPosition:
    WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

    def test_position_type(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert isinstance(pos, PositionInfo)

    def test_position_wallet(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.wallet_address == self.WALLET

    def test_position_protocol(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.protocol == "maple"

    def test_position_pool_address(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.pool_address.startswith("0x")

    def test_position_apy_reasonable(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert 2.0 <= pos.current_apy <= 12.0


class TestMapleAdapterHealth:
    def test_is_healthy_true(self, adapter):
        assert adapter.is_healthy() is True

    def test_health_check_schema(self, adapter):
        hc = adapter.health_check()
        assert hc["protocol"] == "maple"
        assert hc["chain"] == "ethereum"
        assert hc["is_healthy"] is True
        assert "pools" in hc
        assert "note" in hc

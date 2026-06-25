"""
Tests for YearnV3Adapter (Sprint v3.25 / SPA-V325-001).

All tests run in dry_run=True mode — no live RPC calls.
Pattern mirrors test_morpho_adapter.py.
"""
import os
import pytest
from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter, PositionInfo


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def adapter_eth():
    return YearnV3Adapter(chain="ethereum", dry_run=True)


@pytest.fixture
def adapter_arb():
    return YearnV3Adapter(chain="arbitrum", dry_run=True)


# ─── Constructor ──────────────────────────────────────────────────────────────

class TestYearnV3AdapterInit:
    def test_default_chain_is_ethereum(self):
        a = YearnV3Adapter()
        assert a.chain == "ethereum"

    def test_default_dry_run_is_true(self):
        a = YearnV3Adapter()
        assert a.dry_run is True

    def test_supported_chains(self):
        for chain in ("ethereum", "arbitrum"):
            a = YearnV3Adapter(chain=chain)
            assert a.chain == chain

    def test_unsupported_chain_raises(self):
        with pytest.raises(ValueError):
            YearnV3Adapter(chain="solana")

    def test_unsupported_asset_in_supply_raises(self, adapter_eth):
        with pytest.raises(ValueError):
            adapter_eth.supply("DAI", 100.0)

    def test_unsupported_asset_on_chain_raises(self):
        # ethereum supports USDC + USDT; arbitrum too
        a = YearnV3Adapter(chain="ethereum")
        with pytest.raises(ValueError):
            a.supply("WETH", 1.0)


# ─── Supply (dry-run) ─────────────────────────────────────────────────────────

class TestYearnV3AdapterSupply:
    def test_supply_usdc_returns_dry_run(self, adapter_eth):
        result = adapter_eth.supply("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "yearn-v3"
        assert result["asset"] == "USDC"
        assert result["amount"] == 1000.0

    def test_supply_usdt_arbitrum(self, adapter_arb):
        result = adapter_arb.supply("USDT", 500.0)
        assert result["status"] == "DRY_RUN"
        assert result["chain"] == "arbitrum"

    def test_supply_lowercase_asset_normalised(self, adapter_eth):
        result = adapter_eth.supply("usdc", 100.0)
        assert result["asset"] == "USDC"

    def test_supply_includes_vault_address(self, adapter_eth):
        result = adapter_eth.supply("USDC", 100.0)
        assert result["vault"].startswith("0x")

    def test_supply_includes_shares_minted(self, adapter_eth):
        result = adapter_eth.supply("USDC", 1000.0)
        assert "shares_minted" in result
        assert result["shares_minted"] > 0

    def test_supply_zero_amount_raises(self, adapter_eth):
        with pytest.raises(ValueError, match="positive"):
            adapter_eth.supply("USDC", 0.0)

    def test_supply_negative_amount_raises(self, adapter_eth):
        with pytest.raises(ValueError, match="positive"):
            adapter_eth.supply("USDC", -50.0)

    def test_supply_over_sanity_cap_raises(self, adapter_eth):
        with pytest.raises(ValueError, match="sanity cap"):
            adapter_eth.supply("USDC", 10_000_001.0)

    def test_supply_blocked_when_not_live(self):
        a = YearnV3Adapter(chain="ethereum", dry_run=False)
        env = os.environ.copy()
        env.pop("SPA_EXECUTION_MODE", None)
        result = a.supply("USDC", 100.0)
        assert result["status"] == "BLOCKED"


# ─── Withdraw (dry-run) ───────────────────────────────────────────────────────

class TestYearnV3AdapterWithdraw:
    def test_withdraw_usdc_returns_dry_run(self, adapter_eth):
        result = adapter_eth.withdraw("USDC", 500.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "yearn-v3"

    def test_withdraw_usdt_arbitrum(self, adapter_arb):
        result = adapter_arb.withdraw("USDT", 300.0)
        assert result["status"] == "DRY_RUN"
        assert result["chain"] == "arbitrum"

    def test_withdraw_includes_shares_burned(self, adapter_eth):
        result = adapter_eth.withdraw("USDC", 500.0)
        assert "shares_burned" in result
        assert result["shares_burned"] > 0

    def test_withdraw_zero_raises(self, adapter_eth):
        with pytest.raises(ValueError, match="positive"):
            adapter_eth.withdraw("USDC", 0.0)

    def test_withdraw_blocked_when_not_live(self):
        a = YearnV3Adapter(chain="ethereum", dry_run=False)
        result = a.withdraw("USDC", 100.0)
        assert result["status"] == "BLOCKED"


# ─── APY & balance reads ──────────────────────────────────────────────────────

class TestYearnV3AdapterReads:
    def test_get_supply_apy_ethereum_usdc(self, adapter_eth):
        apy = adapter_eth.get_supply_apy("USDC")
        assert 3.0 <= apy <= 15.0

    def test_get_apy_alias(self, adapter_eth):
        assert adapter_eth.get_apy("USDC") == adapter_eth.get_supply_apy("USDC")

    def test_get_supply_balance_returns_positive(self, adapter_eth):
        bal = adapter_eth.get_supply_balance("USDC")
        assert bal > 0

    def test_get_supply_balance_arbitrum(self, adapter_arb):
        bal = adapter_arb.get_supply_balance("USDT")
        assert bal >= 0


# ─── get_position ─────────────────────────────────────────────────────────────

class TestYearnV3AdapterPosition:
    WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

    def test_get_position_returns_position_info(self, adapter_eth):
        pos = adapter_eth.get_position(self.WALLET, "USDC")
        assert isinstance(pos, PositionInfo)

    def test_position_wallet_matches(self, adapter_eth):
        pos = adapter_eth.get_position(self.WALLET, "USDC")
        assert pos.wallet_address == self.WALLET

    def test_position_asset_normalised(self, adapter_eth):
        pos = adapter_eth.get_position(self.WALLET, "usdc")
        assert pos.asset == "USDC"

    def test_position_has_vault_address(self, adapter_eth):
        pos = adapter_eth.get_position(self.WALLET, "USDC")
        assert pos.vault_address.startswith("0x")

    def test_position_apy_reasonable(self, adapter_eth):
        pos = adapter_eth.get_position(self.WALLET, "USDC")
        assert 3.0 <= pos.current_apy <= 15.0


# ─── Health check ─────────────────────────────────────────────────────────────

class TestYearnV3AdapterHealth:
    def test_is_healthy_always_true(self, adapter_eth):
        assert adapter_eth.is_healthy() is True

    def test_health_check_schema(self, adapter_eth):
        hc = adapter_eth.health_check()
        assert hc["protocol"] == "yearn-v3"
        assert hc["chain"] == "ethereum"
        assert hc["is_healthy"] is True
        assert "vaults" in hc
        assert "supported_assets" in hc

    def test_health_check_arbitrum(self, adapter_arb):
        hc = adapter_arb.health_check()
        assert hc["chain"] == "arbitrum"
        assert hc["is_healthy"] is True

"""
Tests for AaveV3Adapter (FEAT-004 Phase 1).

14 deterministic pure-Python tests. No DB, no network, no sleep.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure spa_core is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.aave_v3_adapter import AaveV3Adapter


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> AaveV3Adapter:
    return AaveV3Adapter()


@pytest.fixture
def live_adapter() -> AaveV3Adapter:
    """Adapter with dry_run=False — used to assert NOT_IMPLEMENTED paths."""
    return AaveV3Adapter(chain="ethereum", dry_run=False)


# ─── TestAdapterInit ──────────────────────────────────────────────────────────


class TestAdapterInit:

    def test_default_chain_is_ethereum(self, adapter):
        """Default chain is 'ethereum' and dry_run defaults to True."""
        assert adapter.chain == "ethereum"
        assert adapter.dry_run is True
        # Pool address matches the registered Ethereum mainnet Aave V3 Pool
        assert adapter.pool_address == "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"

    def test_custom_chain_arbitrum(self):
        """Arbitrum can be selected and resolves to the correct Pool."""
        a = AaveV3Adapter(chain="arbitrum")
        assert a.chain == "arbitrum"
        assert a.pool_address == "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
        # Three RPC endpoints registered per chain
        assert len(a.rpc_endpoints[a.chain]) == 3

    def test_invalid_chain_raises(self):
        """Unsupported chain must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported chain"):
            AaveV3Adapter(chain="polygon")


# ─── TestSupply ───────────────────────────────────────────────────────────────


class TestSupply:

    def test_dry_run_shape(self, adapter):
        """Dry-run supply returns the documented record shape."""
        result = adapter.supply("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["tx_hash"] is None
        assert result["asset"] == "USDC"
        assert result["amount"] == 1000.0
        assert result["atoken_received"] == 1000.0
        assert result["chain"] == "ethereum"
        assert "timestamp" in result and result["timestamp"]

    def test_invalid_asset_raises(self, adapter):
        """Unsupported asset must raise ValueError before any execution."""
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.supply("WBTC", 1.0)

    def test_invalid_amount_raises(self, adapter):
        """Zero and negative amounts must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.supply("USDC", 0)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.supply("USDC", -100.0)

    def test_live_mode_returns_not_implemented(self, live_adapter):
        """dry_run=False must short-circuit to NOT_IMPLEMENTED, never raise."""
        result = live_adapter.supply("USDC", 500.0)
        assert result["status"] == "NOT_IMPLEMENTED"
        assert result["tx_hash"] is None
        assert result["asset"] == "USDC"


# ─── TestWithdraw ─────────────────────────────────────────────────────────────


class TestWithdraw:

    def test_dry_run_shape(self, adapter):
        """Dry-run withdraw returns the documented record shape (neg aToken)."""
        result = adapter.withdraw("DAI", 250.0)
        assert result["status"] == "DRY_RUN"
        assert result["asset"] == "DAI"
        assert result["amount"] == 250.0
        # aToken delta is negative on withdraw
        assert result["atoken_received"] == -250.0
        assert result["tx_hash"] is None
        assert result["chain"] == "ethereum"

    def test_invalid_inputs_raise(self, adapter):
        """Invalid asset and invalid amount both raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.withdraw("ETH", 100.0)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.withdraw("USDT", 0.0)


# ─── TestBalanceAPY ───────────────────────────────────────────────────────────


class TestBalanceAPY:

    def test_balance_returns_deterministic_mock(self, adapter):
        """get_supply_balance returns the documented _MOCK_BALANCES entries."""
        assert adapter.get_supply_balance("USDC") == 10000.0
        assert adapter.get_supply_balance("USDT") == 5000.0
        assert adapter.get_supply_balance("DAI")  == 2500.0
        # Unsupported asset raises
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.get_supply_balance("FRAX")

    def test_apy_returns_deterministic_mock(self, adapter):
        """get_supply_apy returns the documented _MOCK_APYS entries (percent)."""
        assert adapter.get_supply_apy("USDC") == 4.2
        assert adapter.get_supply_apy("USDT") == 3.8
        assert adapter.get_supply_apy("DAI")  == 3.5
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.get_supply_apy("FRAX")


# ─── TestHealthCheck ──────────────────────────────────────────────────────────


class TestHealthCheck:

    def test_health_check_shape(self, adapter):
        """health_check returns every documented key with correct types."""
        hc = adapter.health_check()
        assert hc["chain"] == "ethereum"
        assert hc["dry_run"] is True
        assert hc["pool_address"] == "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
        assert hc["endpoints_configured"] == 3
        assert set(hc["supported_assets"]) == {"USDC", "USDT", "DAI"}
        assert isinstance(hc["timestamp"], str) and hc["timestamp"]

    def test_health_check_reflects_chain(self):
        """Chain switch surfaces in health_check output (Base example)."""
        a = AaveV3Adapter(chain="base", dry_run=False)
        hc = a.health_check()
        assert hc["chain"] == "base"
        assert hc["dry_run"] is False
        assert hc["pool_address"] == "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
        assert hc["endpoints_configured"] == 3

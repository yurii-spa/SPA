"""
Tests for CompoundV3Adapter (FEAT-005 Phase 1).

14 deterministic pure-Python tests. No DB, no network, no sleep.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure spa_core is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.compound_v3_adapter import CompoundV3Adapter


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> CompoundV3Adapter:
    return CompoundV3Adapter()


@pytest.fixture
def live_adapter() -> CompoundV3Adapter:
    """Adapter with dry_run=False — used to assert NOT_IMPLEMENTED paths."""
    return CompoundV3Adapter(chain="ethereum", dry_run=False)


# ─── TestAdapterInit ──────────────────────────────────────────────────────────


class TestAdapterInit:

    def test_default_chain_is_ethereum(self, adapter):
        """Default chain is 'ethereum' and dry_run defaults to True."""
        assert adapter.chain == "ethereum"
        assert adapter.dry_run is True
        # Comet address matches the registered Ethereum mainnet cUSDCv3 Comet
        assert adapter.comet_address == "0xc3d688B66703497DAA19211EEdff47f25384cdc3"

    def test_custom_chain_arbitrum(self):
        """Arbitrum can be selected and resolves to the correct Comet."""
        a = CompoundV3Adapter(chain="arbitrum")
        assert a.chain == "arbitrum"
        assert a.comet_address == "0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf"
        # Three RPC endpoints registered per chain
        assert len(a.rpc_endpoints[a.chain]) == 3

    def test_custom_chain_base(self):
        """Base can be selected and resolves to the correct Comet."""
        a = CompoundV3Adapter(chain="base")
        assert a.chain == "base"
        assert a.comet_address == "0xb125E6687d4313864e53df431d5425969c15Eb2F"
        assert len(a.rpc_endpoints[a.chain]) == 3

    def test_invalid_chain_raises(self):
        """Unsupported chain must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported chain"):
            CompoundV3Adapter(chain="polygon")

    def test_custom_rpc_endpoints_override(self):
        """Custom rpc_endpoints argument overrides the class-level table."""
        override = {
            "ethereum": ["https://custom.example.com/rpc"],
            "arbitrum": [],
            "base":     [],
        }
        a = CompoundV3Adapter(chain="ethereum", rpc_endpoints=override)
        assert a.rpc_endpoints is override
        assert a.rpc_endpoints["ethereum"] == ["https://custom.example.com/rpc"]


# ─── TestSupply ───────────────────────────────────────────────────────────────


class TestSupply:

    def test_dry_run_shape(self, adapter):
        """Dry-run supply returns the documented record shape."""
        result = adapter.supply("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["tx_hash"] is None
        assert result["asset"] == "USDC"
        assert result["amount"] == 1000.0
        assert result["ctoken_received"] == 1000.0
        assert result["chain"] == "ethereum"
        assert "timestamp" in result and result["timestamp"]

    def test_invalid_asset_raises(self, adapter):
        """Unsupported asset must raise ValueError before any execution.

        Compound V3 Phase 1 is USDC-only — USDT/DAI Comets are not in
        production scope on the three supported chains.
        """
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.supply("USDT", 1000.0)
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.supply("DAI", 1000.0)

    def test_invalid_amount_raises(self, adapter):
        """Zero and negative amounts must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.supply("USDC", 0)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.supply("USDC", -100.0)

    def test_live_mode_returns_not_implemented(self, live_adapter, monkeypatch):
        """dry_run=False without SPA_EXECUTION_MODE=live must short-circuit.

        Phase 3 contract: write methods short-circuit to BLOCKED when the
        execution-mode env flag is unset (no live tx ever attempted). The
        legacy ``NOT_IMPLEMENTED`` status is treated as an equivalent
        short-circuit for backward-compat — both signal "we did not
        broadcast a transaction".
        """
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
        result = live_adapter.supply("USDC", 500.0)
        assert result["status"] in ("NOT_IMPLEMENTED", "BLOCKED")
        assert result["asset"] == "USDC"
        # tx_hash key is gone in Phase 3; either absent or None is fine.
        assert result.get("tx_hash") is None


# ─── TestWithdraw ─────────────────────────────────────────────────────────────


class TestWithdraw:

    def test_dry_run_shape(self, adapter):
        """Dry-run withdraw returns the documented record shape (neg cToken)."""
        result = adapter.withdraw("USDC", 250.0)
        assert result["status"] == "DRY_RUN"
        assert result["asset"] == "USDC"
        assert result["amount"] == 250.0
        # cUSDCv3 delta is negative on withdraw
        assert result["ctoken_received"] == -250.0
        assert result["tx_hash"] is None
        assert result["chain"] == "ethereum"

    def test_invalid_inputs_raise(self, adapter):
        """Invalid asset and invalid amount both raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.withdraw("ETH", 100.0)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.withdraw("USDC", 0.0)

    def test_live_mode_returns_not_implemented(self, live_adapter, monkeypatch):
        """dry_run=False without SPA_EXECUTION_MODE=live must short-circuit.

        Phase 3 contract — same as supply: BLOCKED when env flag unset,
        legacy NOT_IMPLEMENTED equivalent for backward-compat.
        """
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
        result = live_adapter.withdraw("USDC", 100.0)
        assert result["status"] in ("NOT_IMPLEMENTED", "BLOCKED")
        assert result["asset"] == "USDC"


# ─── TestBalanceAPY ───────────────────────────────────────────────────────────


class TestBalanceAPY:

    def test_balance_returns_deterministic_mock(self, adapter):
        """get_supply_balance returns the documented _MOCK_BALANCES entry."""
        assert adapter.get_supply_balance("USDC") == 8000.0
        # Unsupported asset raises
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.get_supply_balance("USDT")
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.get_supply_balance("FRAX")

    def test_apy_returns_deterministic_mock(self, adapter):
        """get_supply_apy returns the documented _MOCK_APYS entry (percent)."""
        assert adapter.get_supply_apy("USDC") == 4.5
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.get_supply_apy("FRAX")

    def test_live_mode_falls_back_to_mock_when_rpc_unreachable(
        self, live_adapter, monkeypatch,
    ):
        """Phase 2: live-mode reads attempt real RPC, then degrade to mock.

        Phase 1 returned 0.0 in live mode (NOT_IMPLEMTNED). Phase 2 wires
        real eth_call; when every RPC is patched to fail, the adapter
        degrades to the deterministic _MOCK_* fixture rather than crashing
        the pipeline. ``SPA_WALLET_ADDRESS`` is unset, which short-circuits
        the balance path to the mock immediately.
        """
        monkeypatch.delenv("SPA_WALLET_ADDRESS", raising=False)

        def _always_fail(self, asset, data):  # noqa: ARG001
            raise RuntimeError("simulated RPC outage")

        # Patch the fallback router so no real network is touched.
        from unittest.mock import patch
        with patch.object(
            CompoundV3Adapter, "_call_with_fallback", new=_always_fail,
        ):
            # Balance: missing SPA_WALLET_ADDRESS → fall back to mock.
            assert (
                live_adapter.get_supply_balance("USDC")
                == CompoundV3Adapter._MOCK_BALANCES["USDC"]
                == 8000.0
            )
            # APY: every RPC raises → fall back to mock.
            assert (
                live_adapter.get_supply_apy("USDC")
                == CompoundV3Adapter._MOCK_APYS["USDC"]
                == 4.5
            )


# ─── TestHealthCheck ──────────────────────────────────────────────────────────


class TestHealthCheck:

    def test_health_check_shape(self, adapter):
        """health_check returns every documented key with correct types."""
        hc = adapter.health_check()
        assert hc["chain"] == "ethereum"
        assert hc["dry_run"] is True
        assert hc["comet_address"] == "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        assert hc["endpoints_configured"] == 3
        assert set(hc["supported_assets"]) == {"USDC"}
        assert isinstance(hc["timestamp"], str) and hc["timestamp"]

    def test_health_check_reflects_chain(self):
        """Chain switch surfaces in health_check output (Base example)."""
        a = CompoundV3Adapter(chain="base", dry_run=False)
        hc = a.health_check()
        assert hc["chain"] == "base"
        assert hc["dry_run"] is False
        assert hc["comet_address"] == "0xb125E6687d4313864e53df431d5425969c15Eb2F"
        assert hc["endpoints_configured"] == 3

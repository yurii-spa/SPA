"""
Tests for spa_core/execution/adapters/morpho_adapter.py (Sprint v3.24 / SPA-V324-002).

All tests run in dry_run=True mode (default) so no RPC calls or real signing
is needed.  Live-write path is tested using mocked env vars and patched methods.
"""
from __future__ import annotations

import os
import pytest


# ─── Basic adapter constants ──────────────────────────────────────────────────

class TestMorphoAdapterConstants:
    def test_protocol_name(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        assert MorphoAdapter.PROTOCOL == "morpho"

    def test_supported_chains(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        assert "ethereum" in MorphoAdapter.SUPPORTED_CHAINS
        assert "base" in MorphoAdapter.SUPPORTED_CHAINS

    def test_supported_assets(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        assert "USDC" in MorphoAdapter.SUPPORTED_ASSETS
        assert "USDT" in MorphoAdapter.SUPPORTED_ASSETS

    def test_morpho_blue_address_ethereum(self):
        """Morpho Blue address is 0xBBBBBbbBBb... on all EVM chains."""
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        assert MorphoAdapter.MORPHO_BLUE["ethereum"].startswith("0xBBBBBbbBBb")

    def test_morpho_blue_address_base(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        assert MorphoAdapter.MORPHO_BLUE["base"].startswith("0xBBBBBbbBBb")

    def test_vaults_configured(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        assert "USDC_ethereum" in MorphoAdapter.VAULTS
        assert "USDC_base" in MorphoAdapter.VAULTS


# ─── Constructor ──────────────────────────────────────────────────────────────

class TestMorphoAdapterInit:
    def test_default_chain_ethereum(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter()
        assert adapter.chain == "ethereum"
        assert adapter.dry_run is True

    def test_chain_base(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="base")
        assert adapter.chain == "base"

    def test_unsupported_chain_raises(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        with pytest.raises(ValueError, match="Unsupported chain"):
            MorphoAdapter(chain="solana")

    def test_morpho_blue_address_set(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="ethereum")
        assert adapter.morpho_blue_address == MorphoAdapter.MORPHO_BLUE["ethereum"]


# ─── supply() ─────────────────────────────────────────────────────────────────

class TestMorphoAdapterSupply:
    def test_supply_dry_run_returns_dict(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="ethereum", dry_run=True)
        result = adapter.supply("USDC", 5000.0)
        assert isinstance(result, dict)

    def test_supply_dry_run_status(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="ethereum", dry_run=True)
        result = adapter.supply("USDC", 5000.0)
        assert result["status"] == "DRY_RUN"

    def test_supply_dry_run_has_required_fields(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="ethereum", dry_run=True)
        result = adapter.supply("USDC", 5000.0)
        for field in ("status", "asset", "amount", "chain", "timestamp"):
            assert field in result, f"Missing field: {field}"

    def test_supply_asset_echoed(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="ethereum", dry_run=True)
        result = adapter.supply("USDT", 1000.0)
        assert result["asset"] == "USDT"
        assert result["amount"] == 1000.0

    def test_supply_unknown_asset_raises(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.supply("BTC", 1.0)

    def test_supply_negative_amount_raises(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.supply("USDC", -100.0)

    def test_supply_blocked_without_live_mode(self):
        """Without SPA_EXECUTION_MODE=live, live-write path returns BLOCKED."""
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="ethereum", dry_run=False)
        # Ensure the env var is not set
        env_backup = os.environ.pop("SPA_EXECUTION_MODE", None)
        try:
            result = adapter.supply("USDC", 100.0)
            assert result["status"] == "BLOCKED"
            assert "SPA_EXECUTION_MODE" in result["reason"]
        finally:
            if env_backup is not None:
                os.environ["SPA_EXECUTION_MODE"] = env_backup

    def test_supply_base_chain(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="base", dry_run=True)
        result = adapter.supply("USDC", 2000.0)
        assert result["status"] == "DRY_RUN"
        assert result["chain"] == "base"


# ─── withdraw() ───────────────────────────────────────────────────────────────

class TestMorphoAdapterWithdraw:
    def test_withdraw_dry_run_returns_dict(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        result = adapter.withdraw("USDC", 1000.0)
        assert isinstance(result, dict)

    def test_withdraw_dry_run_status(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        result = adapter.withdraw("USDT", 500.0)
        assert result["status"] == "DRY_RUN"

    def test_withdraw_has_required_fields(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        result = adapter.withdraw("USDC", 200.0)
        for field in ("status", "asset", "amount", "chain", "timestamp"):
            assert field in result

    def test_withdraw_blocked_without_live_mode(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=False)
        env_backup = os.environ.pop("SPA_EXECUTION_MODE", None)
        try:
            result = adapter.withdraw("USDC", 100.0)
            assert result["status"] == "BLOCKED"
        finally:
            if env_backup is not None:
                os.environ["SPA_EXECUTION_MODE"] = env_backup


# ─── get_apy() / get_supply_apy() ────────────────────────────────────────────

class TestMorphoAdapterGetApy:
    def test_get_apy_returns_float(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        apy = adapter.get_apy("USDC")
        assert isinstance(apy, float)

    def test_get_supply_apy_returns_float(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        apy = adapter.get_supply_apy("USDC")
        assert isinstance(apy, float)

    def test_get_apy_positive(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        assert adapter.get_apy("USDC") > 0

    def test_get_apy_alias_matches(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        assert adapter.get_apy("USDT") == adapter.get_supply_apy("USDT")

    def test_get_apy_unknown_asset_raises(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        with pytest.raises(ValueError):
            adapter.get_supply_apy("ETH")

    def test_mock_apy_values_reasonable(self):
        """Mock APYs should be in realistic yield range (1–20%)."""
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        for asset in MorphoAdapter.SUPPORTED_ASSETS:
            apy = adapter.get_supply_apy(asset)
            assert 1.0 <= apy <= 20.0, f"APY for {asset} out of realistic range: {apy}"


# ─── get_position() ──────────────────────────────────────────────────────────

class TestMorphoAdapterGetPosition:
    def test_returns_position_info(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter, PositionInfo
        adapter = MorphoAdapter(dry_run=True)
        pos = adapter.get_position(wallet_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                                   asset="USDC")
        assert isinstance(pos, PositionInfo)

    def test_position_has_wallet(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        wallet = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
        pos = adapter.get_position(wallet_address=wallet, asset="USDC")
        assert pos.wallet_address == wallet

    def test_position_has_balance(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        pos = adapter.get_position(asset="USDC")
        assert isinstance(pos.balance_tokens, float)
        assert pos.balance_tokens >= 0

    def test_position_protocol(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        pos = adapter.get_position(asset="USDC")
        assert pos.protocol == "morpho"

    def test_position_chain_echoed(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(chain="base", dry_run=True)
        pos = adapter.get_position(asset="USDC")
        assert pos.chain == "base"


# ─── is_healthy() ────────────────────────────────────────────────────────────

class TestMorphoAdapterIsHealthy:
    def test_always_returns_true_dry_run(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        assert adapter.is_healthy() is True

    def test_always_returns_true_live(self):
        """Vault positions have no liquidation risk — always healthy."""
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=False)
        assert adapter.is_healthy() is True

    def test_with_explicit_wallet(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        assert adapter.is_healthy(
            wallet_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        ) is True


# ─── health_check() ──────────────────────────────────────────────────────────

class TestMorphoAdapterHealthCheck:
    def test_health_check_returns_dict(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        result = adapter.health_check()
        assert isinstance(result, dict)

    def test_health_check_fields(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        result = adapter.health_check()
        for field in ("protocol", "chain", "dry_run", "morpho_blue_address",
                      "vaults_configured", "supported_assets", "timestamp"):
            assert field in result, f"Missing health_check field: {field}"

    def test_health_check_protocol(self):
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        adapter = MorphoAdapter(dry_run=True)
        assert adapter.health_check()["protocol"] == "morpho"


# ─── engine_bridge integration ────────────────────────────────────────────────

class TestEngineBridgeMorpho:
    def test_morpho_key_skipped_in_paper_mode(self):
        """engine_bridge must return SKIPPED for morpho-* in paper mode."""
        from spa_core.execution.engine_bridge import LiveExecutionBridge
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = LiveExecutionBridge(log_path=pathlib.Path(tmpdir) / "log.json")
            env_backup = os.environ.pop("SPA_EXECUTION_MODE", None)
            try:
                result = bridge.execute_supply("morpho-usdc-ethereum", 5000.0)
                assert result["status"] == "SKIPPED"
                assert result["reason"] == "execution_mode_paper"
            finally:
                if env_backup is not None:
                    os.environ["SPA_EXECUTION_MODE"] = env_backup

    def test_morpho_protocol_key_parsed(self):
        """_parse_protocol_key should handle morpho-usdc-ethereum correctly."""
        from spa_core.execution.engine_bridge import _parse_protocol_key
        parsed = _parse_protocol_key("morpho-usdc-ethereum")
        assert parsed is not None, "_parse_protocol_key returned None for morpho key"
        assert parsed["family"] == "morpho"
        assert parsed["asset"] == "USDC"
        assert parsed["chain"] == "ethereum"

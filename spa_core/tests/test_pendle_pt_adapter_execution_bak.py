"""
Tests for PendlePTAdapter (Sprint v3.28 / SPA-V328-001).

All tests run in dry_run=True mode (or with the DeFiLlama feed mocked) —
no live RPC / network calls. Pattern mirrors test_yearn_v3_adapter.py and
test_maple_adapter.py.
"""
import os
from datetime import datetime, timezone
from unittest import mock

import pytest

from spa_core.execution.adapters.pendle_pt_adapter import (
    PendlePTAdapter,
    PositionInfo,
)


@pytest.fixture
def adapter():
    return PendlePTAdapter(chain="ethereum", dry_run=True)


# ─── Constructor ──────────────────────────────────────────────────────────────

class TestPendlePTAdapterInit:
    def test_default_chain(self):
        assert PendlePTAdapter().chain == "ethereum"

    def test_default_dry_run(self):
        assert PendlePTAdapter().dry_run is True

    def test_unsupported_chain_raises(self):
        with pytest.raises(ValueError):
            PendlePTAdapter(chain="arbitrum")

    def test_unsupported_asset_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.supply("DAI", 100.0)


# ─── Supply (dry-run) ─────────────────────────────────────────────────────────

class TestPendlePTAdapterSupply:
    def test_supply_usdc_dry_run(self, adapter):
        result = adapter.supply("USDC", 2000.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "pendle-pt"
        assert result["asset"] == "USDC"
        assert result["amount"] == 2000.0

    def test_supply_usdt_dry_run(self, adapter):
        result = adapter.supply("USDT", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["asset"] == "USDT"

    def test_supply_lowercase_normalised(self, adapter):
        result = adapter.supply("usdc", 500.0)
        assert result["asset"] == "USDC"

    def test_supply_has_pt_address(self, adapter):
        result = adapter.supply("USDC", 500.0)
        assert result["pt"].startswith("0x")

    def test_supply_has_maturity(self, adapter):
        result = adapter.supply("USDC", 500.0)
        assert result["maturity"] == "2026-09-24"

    def test_supply_has_pt_minted(self, adapter):
        result = adapter.supply("USDC", 1000.0)
        assert result["pt_minted"] > 0

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
        a = PendlePTAdapter(dry_run=False)
        env = os.environ.copy()
        env.pop("SPA_EXECUTION_MODE", None)
        with mock.patch.dict(os.environ, env, clear=True):
            result = a.supply("USDC", 100.0)
        assert result["status"] == "BLOCKED"

    def test_supply_not_implemented_when_live(self):
        a = PendlePTAdapter(dry_run=False)
        with mock.patch.dict(os.environ, {"SPA_EXECUTION_MODE": "live"}):
            result = a.supply("USDC", 100.0)
        assert result["status"] == "NOT_IMPLEMENTED"


# ─── Withdraw (dry-run) ───────────────────────────────────────────────────────

class TestPendlePTAdapterWithdraw:
    def test_withdraw_usdc_dry_run(self, adapter):
        result = adapter.withdraw("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["protocol"] == "pendle-pt"

    def test_withdraw_has_matured_flag(self, adapter):
        result = adapter.withdraw("USDC", 1000.0)
        assert "matured" in result
        assert isinstance(result["matured"], bool)

    def test_withdraw_has_pt_burned(self, adapter):
        result = adapter.withdraw("USDC", 1000.0)
        assert result["pt_burned"] > 0

    def test_withdraw_zero_raises(self, adapter):
        with pytest.raises(ValueError, match="positive"):
            adapter.withdraw("USDC", 0.0)

    def test_withdraw_blocked_when_not_live(self):
        a = PendlePTAdapter(dry_run=False)
        env = os.environ.copy()
        env.pop("SPA_EXECUTION_MODE", None)
        with mock.patch.dict(os.environ, env, clear=True):
            result = a.withdraw("USDC", 100.0)
        assert result["status"] == "BLOCKED"

    def test_withdraw_not_implemented_when_live(self):
        a = PendlePTAdapter(dry_run=False)
        with mock.patch.dict(os.environ, {"SPA_EXECUTION_MODE": "live"}):
            result = a.withdraw("USDC", 100.0)
        assert result["status"] == "NOT_IMPLEMENTED"


# ─── APY (dry-run mocks) ──────────────────────────────────────────────────────

class TestPendlePTAdapterApy:
    def test_get_supply_apy_usdc_mock(self, adapter):
        assert adapter.get_supply_apy("USDC") == 6.5

    def test_get_supply_apy_usdt_mock(self, adapter):
        assert adapter.get_supply_apy("USDT") == 6.1

    def test_get_apy_alias(self, adapter):
        assert adapter.get_apy("USDC") == adapter.get_supply_apy("USDC")

    def test_implied_fixed_apy_alias(self, adapter):
        assert adapter.implied_fixed_apy("USDC") == adapter.get_supply_apy("USDC")
        assert adapter.implied_fixed_apy("USDC") == 6.5

    def test_dry_run_shortcircuits_feed(self, adapter):
        # dry_run must short-circuit to mock and never touch the live feed.
        with mock.patch(
            "spa_core.execution.defillama_apy_feed.live_apy_enabled",
            side_effect=RuntimeError("should not be called"),
        ) as lae:
            assert adapter.get_supply_apy("USDC") == 6.5
        lae.assert_not_called()


# ─── Live APY path (DeFiLlama feed mocked — no real network) ──────────────────

class TestPendlePTAdapterLiveApy:
    """Live-APY path tests.

    The adapter does ``from spa_core.execution import defillama_apy_feed`` and
    calls module functions, so we patch those functions directly on the real
    module object (deterministic regardless of import mechanics). No network.
    """

    FEED = "spa_core.execution.defillama_apy_feed"

    def _adapter_live(self):
        return PendlePTAdapter(chain="ethereum", dry_run=False)

    def test_live_apy_used_when_available(self):
        a = self._adapter_live()
        with mock.patch(f"{self.FEED}.live_apy_enabled", return_value=True), \
             mock.patch(f"{self.FEED}.get_live_apy", return_value=7.77) as gla:
            assert a.get_supply_apy("USDC") == 7.77
        gla.assert_called_once_with("pendle-pt", "USDC", "ethereum")

    def test_live_apy_falls_back_when_disabled(self):
        a = self._adapter_live()
        with mock.patch(f"{self.FEED}.live_apy_enabled", return_value=False), \
             mock.patch(f"{self.FEED}.get_live_apy", return_value=7.77) as gla:
            assert a.get_supply_apy("USDC") == 6.5
        gla.assert_not_called()

    def test_live_apy_falls_back_on_none(self):
        a = self._adapter_live()
        with mock.patch(f"{self.FEED}.live_apy_enabled", return_value=True), \
             mock.patch(f"{self.FEED}.get_live_apy", return_value=None):
            assert a.get_supply_apy("USDC") == 6.5

    def test_live_apy_falls_back_on_error(self):
        a = self._adapter_live()
        with mock.patch(f"{self.FEED}.live_apy_enabled",
                        side_effect=RuntimeError("boom")):
            assert a.get_supply_apy("USDC") == 6.5


# ─── Maturity ─────────────────────────────────────────────────────────────────

class TestPendlePTAdapterMaturity:
    def test_get_maturity_usdc(self, adapter):
        assert adapter.get_maturity("USDC") == "2026-09-24"

    def test_get_maturity_usdt(self, adapter):
        assert adapter.get_maturity("USDT") == "2026-12-31"

    def test_get_maturity_unknown(self, adapter):
        assert adapter.get_maturity("DAI") == ""

    def test_is_matured_before(self, adapter):
        before = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert adapter.is_matured("USDC", now=before) is False

    def test_is_matured_after(self, adapter):
        after = datetime(2027, 1, 1, tzinfo=timezone.utc)
        assert adapter.is_matured("USDC", now=after) is True

    def test_is_matured_exact(self, adapter):
        exact = datetime(2026, 9, 24, tzinfo=timezone.utc)
        assert adapter.is_matured("USDC", now=exact) is True

    def test_is_matured_naive_datetime(self, adapter):
        after = datetime(2027, 1, 1)  # naive → treated as UTC
        assert adapter.is_matured("USDC", now=after) is True

    def test_is_matured_unknown_asset(self, adapter):
        assert adapter.is_matured("DAI") is False


# ─── get_position ─────────────────────────────────────────────────────────────

class TestPendlePTAdapterPosition:
    WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

    def test_position_type(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert isinstance(pos, PositionInfo)

    def test_position_wallet(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.wallet_address == self.WALLET

    def test_position_protocol(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.protocol == "pendle-pt"

    def test_position_pt_address(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.pt_address.startswith("0x")

    def test_position_maturity(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.maturity == "2026-09-24"

    def test_position_apy(self, adapter):
        pos = adapter.get_position(self.WALLET, "USDC")
        assert pos.current_apy == 6.5


# ─── Health check ─────────────────────────────────────────────────────────────

class TestPendlePTAdapterHealth:
    def test_is_healthy_true(self, adapter):
        assert adapter.is_healthy() is True

    def test_health_check_schema(self, adapter):
        hc = adapter.health_check()
        assert hc["protocol"] == "pendle-pt"
        assert hc["chain"] == "ethereum"
        assert hc["is_healthy"] is True
        assert "markets" in hc
        assert "USDC" in hc["markets"]


# ─── engine_bridge integration ────────────────────────────────────────────────

class TestPendlePTEngineBridge:
    def test_protocol_key_parses_to_pendle_pt(self):
        from spa_core.execution.engine_bridge import _parse_protocol_key
        parsed = _parse_protocol_key("pendle-pt-usdc-ethereum")
        assert parsed is not None
        assert parsed["family"] == "pendle_pt"
        assert parsed["asset"] == "USDC"
        assert parsed["chain"] == "ethereum"

    def test_bridge_resolves_adapter(self):
        from spa_core.execution.engine_bridge import LiveExecutionBridge
        from spa_core.execution.adapters.pendle_pt_adapter import PendlePTAdapter
        b = LiveExecutionBridge()
        adapter = b._get_adapter("pendle_pt", "ethereum")
        assert isinstance(adapter, PendlePTAdapter)
        assert adapter.dry_run is False  # bridge constructs live adapters

    def test_bridge_supply_dispatches(self):
        # Full path through the bridge in live mode — adapter returns
        # NOT_IMPLEMENTED (Phase 3), proving dispatch reached the adapter.
        from spa_core.execution.engine_bridge import LiveExecutionBridge
        b = LiveExecutionBridge(log_path=None)
        with mock.patch.dict(os.environ, {"SPA_EXECUTION_MODE": "live"}):
            with mock.patch.object(b, "_append_log"):
                result = b.execute_supply("pendle-pt-usdc-ethereum", 1000.0)
        assert result["protocol_key"] == "pendle-pt-usdc-ethereum"
        assert result["family"] == "pendle_pt"
        assert result["status"] == "NOT_IMPLEMENTED"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))

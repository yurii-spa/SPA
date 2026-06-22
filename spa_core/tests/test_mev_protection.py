"""
Tests for MEV Protection Layer (Sprint v3.26 / SPA-V326).

All tests run without network — mock Flashbots endpoints.
"""
import unittest.mock as mock
from spa_core.execution.mev_protection import (
    is_mev_protection_enabled,
    get_protected_rpc,
    send_protected_dry_run,
    send_raw_transaction_auto,
    wait_for_receipt,
    FLASHBOTS_RPC_FAST,
    FLASHBOTS_RPC_STANDARD,
    MEV_BLOCKER_RPC_NOREV,
)


# ─── is_mev_protection_enabled ────────────────────────────────────────────────

class TestIsMevProtectionEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SPA_MEV_PROTECTION", raising=False)
        assert is_mev_protection_enabled() is False

    def test_enabled_with_true(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        assert is_mev_protection_enabled() is True

    def test_enabled_with_1(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "1")
        assert is_mev_protection_enabled() is True

    def test_enabled_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "TRUE")
        assert is_mev_protection_enabled() is True

    def test_disabled_with_false(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "false")
        assert is_mev_protection_enabled() is False

    def test_disabled_with_zero(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "0")
        assert is_mev_protection_enabled() is False


# ─── get_protected_rpc ────────────────────────────────────────────────────────

class TestGetProtectedRpc:
    def test_default_is_fast(self, monkeypatch):
        monkeypatch.delenv("SPA_FLASHBOTS_MODE", raising=False)
        assert get_protected_rpc() == FLASHBOTS_RPC_FAST

    def test_standard_mode(self, monkeypatch):
        monkeypatch.setenv("SPA_FLASHBOTS_MODE", "standard")
        assert get_protected_rpc() == FLASHBOTS_RPC_STANDARD

    def test_mevblocker_mode(self, monkeypatch):
        monkeypatch.setenv("SPA_FLASHBOTS_MODE", "mevblocker")
        assert get_protected_rpc() == MEV_BLOCKER_RPC_NOREV

    def test_unknown_mode_defaults_to_fast(self, monkeypatch):
        monkeypatch.setenv("SPA_FLASHBOTS_MODE", "unknown")
        assert get_protected_rpc() == FLASHBOTS_RPC_FAST


# ─── send_protected_dry_run ───────────────────────────────────────────────────

class TestSendProtectedDryRun:
    def test_returns_pending(self):
        result = send_protected_dry_run("0xdeadbeef")
        assert result["status"] == "PENDING"

    def test_returns_tx_hash(self):
        result = send_protected_dry_run("0xdeadbeef")
        assert result["tx_hash"].startswith("0x")
        assert len(result["tx_hash"]) == 66  # 0x + 64 hex chars

    def test_uses_flashbots_endpoint(self):
        result = send_protected_dry_run("0xdeadbeef")
        assert "flashbots" in result["endpoint"]

    def test_protection_field(self):
        result = send_protected_dry_run("0xdeadbeef")
        assert result["protection"] == "flashbots"

    def test_is_dry_run(self):
        result = send_protected_dry_run("0xdeadbeef")
        assert result["dry_run"] is True

    def test_deterministic(self):
        r1 = send_protected_dry_run("0xabc")
        r2 = send_protected_dry_run("0xabc")
        assert r1["tx_hash"] == r2["tx_hash"]


# ─── send_raw_transaction_auto ────────────────────────────────────────────────

class TestSendRawTransactionAuto:
    FAKE_TX = "0x" + "cc" * 100
    FAKE_RPC = "https://ethereum.publicnode.com"

    def test_uses_public_rpc_when_protection_off(self, monkeypatch):
        monkeypatch.delenv("SPA_MEV_PROTECTION", raising=False)
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)

        mock_result = {"status": "0x1", "transactionHash": "0x" + "aa" * 32}
        with mock.patch("spa_core.execution.eth_signer.send_raw_transaction",
                        return_value=mock_result) as m:
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
            m.assert_called_once_with(self.FAKE_TX, self.FAKE_RPC)

    def test_uses_public_rpc_when_not_live(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "paper")  # not live

        mock_result = {"status": "0x1"}
        with mock.patch("spa_core.execution.eth_signer.send_raw_transaction",
                        return_value=mock_result) as m:
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
            m.assert_called_once()

    def test_uses_flashbots_when_protection_on_and_live(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")

        mock_response = {"result": "0x" + "dd" * 32}
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value=mock_response) as m:
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
            assert result["status"] == "PENDING"
            assert result["protection"] == "flashbots"
            m.assert_called()

    def test_falls_back_to_public_when_flashbots_fails(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")

        # All Flashbots endpoints fail
        def always_fail(url, payload, timeout):
            raise ConnectionError("Flashbots unavailable")

        mock_public_result = {"status": "0x1", "transactionHash": "0x" + "ee" * 32}

        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        side_effect=always_fail):
            with mock.patch("spa_core.execution.eth_signer.send_raw_transaction",
                            return_value=mock_public_result):
                result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
                # Falls back to public — warning present
                assert "warning" in result or result["status"] in ("PENDING", "FAILED")


# ─── wait_for_receipt ─────────────────────────────────────────────────────────

class TestWaitForReceipt:
    TX_HASH = "0x" + "ab" * 32
    RPC = "https://ethereum.publicnode.com"

    def test_returns_ok_on_success(self):
        receipt = {
            "status": "0x1",
            "blockNumber": "0x123",
            "gasUsed": "0x5208",
        }
        mock_response = {"result": receipt}
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value=mock_response):
            result = wait_for_receipt(self.TX_HASH, self.RPC, max_wait=5)
            assert result["status"] == "OK"
            assert result["tx_hash"] == self.TX_HASH

    def test_returns_reverted_on_0x0(self):
        receipt = {"status": "0x0", "blockNumber": "0x124", "gasUsed": "0x5208"}
        mock_response = {"result": receipt}
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value=mock_response):
            result = wait_for_receipt(self.TX_HASH, self.RPC, max_wait=5)
            assert result["status"] == "REVERTED"

    def test_returns_timeout_when_not_included(self):
        # Always return null result (not yet included)
        mock_response = {"result": None}
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value=mock_response):
            with mock.patch("time.sleep"):  # skip actual sleep
                result = wait_for_receipt(self.TX_HASH, self.RPC,
                                          max_wait=1, poll_interval=1)
                assert result["status"] == "TIMEOUT"

    def test_timeout_includes_tx_hash(self):
        mock_response = {"result": None}
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value=mock_response):
            with mock.patch("time.sleep"):
                result = wait_for_receipt(self.TX_HASH, self.RPC,
                                          max_wait=1, poll_interval=1)
                assert result["tx_hash"] == self.TX_HASH

    def test_handles_rpc_errors_gracefully(self):
        def flaky(url, payload, timeout):
            raise ConnectionError("flaky")

        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        side_effect=flaky):
            with mock.patch("time.sleep"):
                result = wait_for_receipt(self.TX_HASH, self.RPC,
                                          max_wait=1, poll_interval=1)
                assert result["status"] == "TIMEOUT"


# ─── Integration: protection routing ─────────────────────────────────────────

class TestMevProtectionIntegration:
    """Verify the full routing decision tree."""

    def test_dry_run_never_hits_network(self):
        """send_protected_dry_run must never make HTTP calls."""
        with mock.patch("urllib.request.urlopen") as m:
            send_protected_dry_run("0xdeadbeef")
            m.assert_not_called()

    def test_env_off_routes_to_public(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "false")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        mock_result = {"status": "0x1"}
        with mock.patch("spa_core.execution.eth_signer.send_raw_transaction",
                        return_value=mock_result) as m:
            send_raw_transaction_auto("0x1234", "https://rpc.example.com")
            m.assert_called_once()

    def test_env_on_live_routes_to_flashbots(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        mock_response = {"result": "0x" + "ff" * 32}
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value=mock_response):
            result = send_raw_transaction_auto("0x1234", "https://rpc.example.com")
            assert result["protection"] == "flashbots"
            assert "flashbots" in result["endpoint"]

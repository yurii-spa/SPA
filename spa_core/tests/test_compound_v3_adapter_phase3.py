"""
Phase 3 tests for CompoundV3Adapter — live supply / withdraw via eth_account.

Mirrors ``test_aave_v3_adapter_phase3.py`` (SPA-V39-001). Deterministic,
network-free. Every test either:
  * patches ``urllib.request.urlopen`` (low-level RPC mocking), or
  * patches specific helpers (``_get_chain_id``, ``_get_nonce``,
    ``_get_gas_price``, ``_send_raw_tx``, ``_wait_for_receipt``) so the
    happy path can run without the eth_account package being installed.

Covered:
  * ExecutionMode gate: dry_run, env-flag unset → BLOCKED, env-flag set → live
  * Private-key validation: missing, malformed, address mismatch
  * Supply live path: success, approve revert, supply revert, RPC timeout
  * Withdraw live path: success, revert
  * eth_account ImportError surfaces as FAILED, not as a raised exception
  * Sanity gate: negative amount → ValueError, >10M → ERROR (structured)

Run from repo root::

    python -m pytest spa_core/tests/test_compound_v3_adapter_phase3.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure spa_core is on the path (mirrors test_compound_v3_adapter_phase2.py).
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import compound_v3_adapter as comp_mod  # noqa: E402
from execution.compound_v3_adapter import (  # noqa: E402
    CompoundV3Adapter,
    DependencyNotInstalled,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

# A real 64-char hex private key (deterministic, well-known test key — value
# 0x...01). Whichever eth_account version is installed (if any) will derive
# the same address from it; tests that need the derived address mock the
# Account.from_key path explicitly to avoid the dependency.
TEST_PRIV_KEY = (
    "0x0000000000000000000000000000000000000000000000000000000000000001"
)
TEST_ADDRESS = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"  # from key 0x...01


def _set_live_env(monkeypatch, *, with_wallet=True):
    monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
    monkeypatch.setenv("SPA_PRIVATE_KEY", TEST_PRIV_KEY)
    if with_wallet:
        monkeypatch.setenv("SPA_WALLET_ADDRESS", TEST_ADDRESS)
    else:
        monkeypatch.delenv("SPA_WALLET_ADDRESS", raising=False)


def _make_fake_account_class(address=TEST_ADDRESS):
    """Build a stand-in for eth_account.Account that works without the package."""
    fake_acct = MagicMock()
    fake_acct.address = address
    fake_signed = MagicMock()
    fake_signed.rawTransaction = b"\x02\xf8\x6b"  # arbitrary non-empty bytes
    FakeAccount = MagicMock()
    FakeAccount.from_key = MagicMock(return_value=fake_acct)
    FakeAccount.sign_transaction = MagicMock(return_value=fake_signed)
    return FakeAccount


def _patch_rpc_helpers(
    *,
    chain_id=1,
    nonce=42,
    gas_price=20_000_000_000,
    send_hashes,
    receipt_statuses,
):
    """Build a context manager stack patching all RPC-touching helpers.

    ``send_hashes`` is the list of tx hashes returned by successive
    _send_raw_tx calls. ``receipt_statuses`` is the matching list of receipts
    (dicts with ``status`` and ``blockNumber``).
    """
    send_iter = iter(send_hashes)
    receipt_iter = iter(receipt_statuses)
    return [
        patch.object(
            CompoundV3Adapter, "_get_chain_id", return_value=chain_id,
        ),
        patch.object(CompoundV3Adapter, "_get_nonce", return_value=nonce),
        patch.object(
            CompoundV3Adapter, "_get_gas_price", return_value=gas_price,
        ),
        patch.object(
            CompoundV3Adapter, "_send_raw_tx",
            side_effect=lambda raw: next(send_iter),
        ),
        patch.object(
            CompoundV3Adapter, "_wait_for_receipt",
            side_effect=lambda h: next(receipt_iter),
        ),
    ]


def _enter_all(stack):
    return [ctx.__enter__() for ctx in stack]


def _exit_all(stack):
    for ctx in stack:
        ctx.__exit__(None, None, None)


# ─── TestExecutionModeGate ────────────────────────────────────────────────────


class TestExecutionModeGate:
    """SPA_EXECUTION_MODE env-flag is a hard gate between dry-run and live."""

    def test_dry_run_true_returns_dry_run_status(self, monkeypatch):
        """dry_run=True with no env flag — Phase 1/2 happy path unchanged."""
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=True)
        result = adapter.supply("USDC", 1000.0)
        assert result["status"] == "DRY_RUN"
        assert result["ctoken_received"] == 1000.0
        assert result["chain"] == "ethereum"

    def test_live_mode_without_env_flag_blocks(self, monkeypatch):
        """dry_run=False + no SPA_EXECUTION_MODE → BLOCKED short-circuit."""
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
        monkeypatch.setenv("SPA_PRIVATE_KEY", TEST_PRIV_KEY)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        result = adapter.supply("USDC", 100.0)
        assert result["status"] == "BLOCKED"
        assert "SPA_EXECUTION_MODE" in result["reason"]
        assert result["asset"] == "USDC"
        assert result["chain"] == "ethereum"
        # Same gate applies to withdraw.
        wresult = adapter.withdraw("USDC", 50.0)
        assert wresult["status"] == "BLOCKED"

    def test_live_mode_with_env_flag_proceeds(self, monkeypatch):
        """dry_run=False + SPA_EXECUTION_MODE=live → enters live path (mocked)."""
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)

        FakeAccount = _make_fake_account_class()
        stack = [
            patch.object(
                comp_mod, "_require_eth_account", return_value=FakeAccount,
            ),
            *_patch_rpc_helpers(
                send_hashes=["0xaaa1", "0xbbb2"],
                receipt_statuses=[
                    {"status": "0x1", "blockNumber": "0x10"},
                    {"status": "0x1", "blockNumber": "0x11"},
                ],
            ),
        ]
        _enter_all(stack)
        try:
            result = adapter.supply("USDC", 100.0)
        finally:
            _exit_all(stack)
        assert result["status"] == "SUCCESS"
        assert result["approve_tx"] == "0xaaa1"
        assert result["supply_tx"] == "0xbbb2"


# ─── TestPrivateKeyValidation ─────────────────────────────────────────────────


class TestPrivateKeyValidation:

    def test_missing_private_key_returns_error(self, monkeypatch):
        """No SPA_PRIVATE_KEY → ERROR status, no tx broadcast."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        monkeypatch.delenv("SPA_PRIVATE_KEY", raising=False)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class()
        with patch.object(
            comp_mod, "_require_eth_account", return_value=FakeAccount,
        ):
            result = adapter.supply("USDC", 100.0)
        assert result["status"] == "ERROR"
        assert "SPA_PRIVATE_KEY" in result["reason"]

    def test_invalid_private_key_format_returns_error(self, monkeypatch):
        """Malformed key (not 64 hex chars) → ERROR."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        monkeypatch.setenv("SPA_PRIVATE_KEY", "0xdeadbeef")  # too short
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class()
        with patch.object(
            comp_mod, "_require_eth_account", return_value=FakeAccount,
        ):
            result = adapter.supply("USDC", 100.0)
        assert result["status"] == "ERROR"
        assert "64 hex" in result["reason"] or "SPA_PRIVATE_KEY" in result["reason"]

    def test_wallet_address_mismatch_returns_error(self, monkeypatch):
        """SPA_WALLET_ADDRESS != key-derived address → ERROR."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        monkeypatch.setenv("SPA_PRIVATE_KEY", TEST_PRIV_KEY)
        monkeypatch.setenv(
            "SPA_WALLET_ADDRESS",
            "0x1111111111111111111111111111111111111111",
        )
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class(address=TEST_ADDRESS)
        with patch.object(
            comp_mod, "_require_eth_account", return_value=FakeAccount,
        ):
            result = adapter.supply("USDC", 100.0)
        assert result["status"] == "ERROR"
        assert "does not match" in result["reason"]


# ─── TestSupplyLivePath ───────────────────────────────────────────────────────


class TestSupplyLivePath:
    """End-to-end happy/sad paths through _live_supply with mocked RPC."""

    def _run(self, monkeypatch, *, send_hashes, receipt_statuses):
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class()
        stack = [
            patch.object(
                comp_mod, "_require_eth_account", return_value=FakeAccount,
            ),
            *_patch_rpc_helpers(
                send_hashes=send_hashes,
                receipt_statuses=receipt_statuses,
            ),
        ]
        _enter_all(stack)
        try:
            return adapter.supply("USDC", 1000.0)
        finally:
            _exit_all(stack)

    def test_supply_success_returns_both_tx_hashes(self, monkeypatch):
        result = self._run(
            monkeypatch,
            send_hashes=["0xapprove", "0xsupply"],
            receipt_statuses=[
                {"status": "0x1", "blockNumber": "0x100"},
                {"status": "0x1", "blockNumber": "0x101"},
            ],
        )
        assert result["status"] == "SUCCESS"
        assert result["approve_tx"] == "0xapprove"
        assert result["supply_tx"] == "0xsupply"
        assert result["block_number"] == 0x101
        assert result["amount_usd"] == 1000.0
        assert result["wallet"] == TEST_ADDRESS

    def test_supply_approve_revert_returns_failed(self, monkeypatch):
        result = self._run(
            monkeypatch,
            send_hashes=["0xapprove", "0xsupply"],
            receipt_statuses=[
                {"status": "0x0", "blockNumber": "0x100"},  # approve revert
                {"status": "0x1", "blockNumber": "0x101"},
            ],
        )
        assert result["status"] == "FAILED"
        assert result["phase"] == "approve"
        assert result["approve_tx"] == "0xapprove"

    def test_supply_supply_revert_returns_failed(self, monkeypatch):
        result = self._run(
            monkeypatch,
            send_hashes=["0xapprove", "0xsupply"],
            receipt_statuses=[
                {"status": "0x1", "blockNumber": "0x100"},  # approve OK
                {"status": "0x0", "blockNumber": "0x101"},  # supply revert
            ],
        )
        assert result["status"] == "FAILED"
        assert result["phase"] == "supply"
        assert result["approve_tx"] == "0xapprove"
        assert result["supply_tx"] == "0xsupply"

    def test_supply_rpc_timeout_falls_back_to_failed(self, monkeypatch):
        """If sending the approve tx blows up, return FAILED — never raise."""
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class()
        with patch.object(
            comp_mod, "_require_eth_account", return_value=FakeAccount,
        ), patch.object(
            CompoundV3Adapter, "_get_chain_id", return_value=1,
        ), patch.object(
            CompoundV3Adapter, "_get_nonce", return_value=7,
        ), patch.object(
            CompoundV3Adapter, "_get_gas_price", return_value=1_000_000_000,
        ), patch.object(
            CompoundV3Adapter, "_send_raw_tx",
            side_effect=RuntimeError("RPC timeout"),
        ):
            result = adapter.supply("USDC", 500.0)
        assert result["status"] == "FAILED"
        assert result["phase"] == "approve"
        assert "RPC timeout" in result["reason"]


# ─── TestWithdrawLivePath ─────────────────────────────────────────────────────


class TestWithdrawLivePath:

    def _run(self, monkeypatch, *, send_hashes, receipt_statuses):
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class()
        stack = [
            patch.object(
                comp_mod, "_require_eth_account", return_value=FakeAccount,
            ),
            *_patch_rpc_helpers(
                send_hashes=send_hashes,
                receipt_statuses=receipt_statuses,
            ),
        ]
        _enter_all(stack)
        try:
            return adapter.withdraw("USDC", 250.0)
        finally:
            _exit_all(stack)

    def test_withdraw_success_returns_tx_hash(self, monkeypatch):
        result = self._run(
            monkeypatch,
            send_hashes=["0xwithdraw"],
            receipt_statuses=[{"status": "0x1", "blockNumber": "0xabc"}],
        )
        assert result["status"] == "SUCCESS"
        assert result["withdraw_tx"] == "0xwithdraw"
        assert result["block_number"] == 0xabc
        assert result["amount_usd"] == 250.0
        assert result["asset"] == "USDC"

    def test_withdraw_revert_returns_failed(self, monkeypatch):
        result = self._run(
            monkeypatch,
            send_hashes=["0xwithdraw"],
            receipt_statuses=[{"status": "0x0", "blockNumber": "0xabc"}],
        )
        assert result["status"] == "FAILED"
        assert result["phase"] == "withdraw"
        assert result["withdraw_tx"] == "0xwithdraw"


# ─── TestEthAccountMissing ────────────────────────────────────────────────────


class TestEthAccountMissing:

    def test_eth_account_not_installed_returns_failed(self, monkeypatch):
        """If _require_eth_account raises DependencyNotInstalled, supply must
        return a structured FAILED dict — never propagate ImportError."""
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with patch.object(
            comp_mod, "_require_eth_account",
            side_effect=DependencyNotInstalled("eth_account missing"),
        ):
            result = adapter.supply("USDC", 100.0)
        assert result["status"] == "FAILED"
        assert "eth_account" in result["reason"]
        assert result["phase"] == "approve"


# ─── TestAmountSanityGate ─────────────────────────────────────────────────────


class TestAmountSanityGate:

    def test_negative_amount_rejected(self, monkeypatch):
        """Negative / zero amount must raise ValueError BEFORE any live work."""
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.supply("USDC", -1.0)
        with pytest.raises(ValueError, match="Invalid amount"):
            adapter.withdraw("USDC", 0.0)

    def test_excessive_amount_rejected_above_10m(self, monkeypatch):
        """Amount > MAX_LIVE_AMOUNT must return ERROR — no tx attempted."""
        _set_live_env(monkeypatch)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        FakeAccount = _make_fake_account_class()
        with patch.object(
            comp_mod, "_require_eth_account", return_value=FakeAccount,
        ), patch.object(
            CompoundV3Adapter, "_send_raw_tx",
            side_effect=AssertionError("must not be called"),
        ):
            result = adapter.supply("USDC", 20_000_000.0)
        assert result["status"] == "ERROR"
        assert "MAX_LIVE_AMOUNT" in result["reason"]
        # Same gate on withdraw.
        with patch.object(
            comp_mod, "_require_eth_account", return_value=FakeAccount,
        ), patch.object(
            CompoundV3Adapter, "_send_raw_tx",
            side_effect=AssertionError("must not be called"),
        ):
            wresult = adapter.withdraw("USDC", 50_000_000.0)
        assert wresult["status"] == "ERROR"

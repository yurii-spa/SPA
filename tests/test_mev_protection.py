"""Tests for MEV protection routing in eth_signer (Sprint v3.26 / SPA-V326).

These exercise the Flashbots Protect RPC routing that ``send_raw_transaction``
performs when ``MEV_PROTECTION_ENABLED`` is set and the transaction is on
Ethereum mainnet (``chain_id == 1``). All network I/O is mocked — no real
RPC calls are made.

The eth_signer reads its MEV settings from ``spa_core.adapters.config`` at
call time, so each test patches the config module attributes directly (the
behaviour is identical to setting the corresponding env vars before import).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make ``spa_core`` importable as a top-level package from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters import config  # noqa: E402
from spa_core.execution import eth_signer  # noqa: E402


FAKE_TX = "0x" + "ab" * 64           # 0x-prefixed signed raw tx
PUBLIC_RPC = "https://ethereum.publicnode.com"
PROTECT_RPC = "https://rpc.flashbots.net/fast"
MAINNET = 1
ARBITRUM = 42161
FAKE_HASH = "0x" + "cd" * 32


@pytest.fixture
def mev_settings(monkeypatch):
    """Set MEV config attributes on the adapters config module.

    Usage: ``mev_settings(enabled=..., fallback=..., rpc=...)``.
    Defaults mirror the production defaults.
    """
    def _apply(enabled=True, fallback=True, rpc=PROTECT_RPC):
        monkeypatch.setattr(config, "MEV_PROTECTION_ENABLED", enabled, raising=False)
        monkeypatch.setattr(config, "MEV_PROTECT_FALLBACK", fallback, raising=False)
        monkeypatch.setattr(config, "FLASHBOTS_PROTECT_RPC", rpc, raising=False)
    return _apply


# ─── Protection ON + mainnet → Flashbots Protect RPC ──────────────────────────

class TestProtectionEnabledMainnet:
    def test_routes_to_flashbots_on_mainnet(self, mev_settings):
        mev_settings(enabled=True)
        with patch.object(eth_signer, "_broadcast", return_value=FAKE_HASH) as m:
            result = eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC, chain_id=MAINNET)
        assert result == FAKE_HASH
        # Sent to the Protect RPC, not the public RPC.
        m.assert_called_once_with(FAKE_TX, PROTECT_RPC)

    def test_uses_configured_protect_rpc_url(self, mev_settings):
        custom = "https://protect.example.net/fast"
        mev_settings(enabled=True, rpc=custom)
        with patch.object(eth_signer, "_broadcast", return_value=FAKE_HASH) as m:
            eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC, chain_id=MAINNET)
        m.assert_called_once_with(FAKE_TX, custom)


# ─── Protection OFF → public RPC (backwards compatible) ───────────────────────

class TestProtectionDisabled:
    def test_routes_to_public_rpc_when_disabled(self, mev_settings):
        mev_settings(enabled=False)
        with patch.object(eth_signer, "_broadcast", return_value=FAKE_HASH) as m:
            result = eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC, chain_id=MAINNET)
        assert result == FAKE_HASH
        m.assert_called_once_with(FAKE_TX, PUBLIC_RPC)

    def test_disabled_ignores_chain_and_uses_public(self, mev_settings):
        mev_settings(enabled=False)
        with patch.object(eth_signer, "_broadcast", return_value=FAKE_HASH) as m:
            # Even without chain_id, disabled path must hit the public RPC.
            eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC)
        m.assert_called_once_with(FAKE_TX, PUBLIC_RPC)


# ─── Protection ON + non-mainnet → public RPC fallback ────────────────────────

class TestNonMainnet:
    def test_non_mainnet_falls_back_to_public(self, mev_settings):
        mev_settings(enabled=True)
        with patch.object(eth_signer, "_broadcast", return_value=FAKE_HASH) as m:
            result = eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC, chain_id=ARBITRUM)
        assert result == FAKE_HASH
        m.assert_called_once_with(FAKE_TX, PUBLIC_RPC)

    def test_missing_chain_id_falls_back_to_public(self, mev_settings):
        mev_settings(enabled=True)
        with patch.object(eth_signer, "_broadcast", return_value=FAKE_HASH) as m:
            # No chain_id supplied — cannot confirm mainnet → public RPC.
            eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC)
        m.assert_called_once_with(FAKE_TX, PUBLIC_RPC)


# ─── Protect RPC error handling ───────────────────────────────────────────────

class TestProtectRpcError:
    def test_fallback_true_retries_on_public_rpc(self, mev_settings):
        mev_settings(enabled=True, fallback=True)

        calls: list[str] = []

        def _side_effect(tx, url):
            calls.append(url)
            if url == PROTECT_RPC:
                raise RuntimeError("eth_sendRawTransaction: HTTP failure — boom")
            return FAKE_HASH

        with patch.object(eth_signer, "_broadcast", side_effect=_side_effect):
            result = eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC, chain_id=MAINNET)

        assert result == FAKE_HASH
        # First attempt Protect RPC, then fall back to public RPC.
        assert calls == [PROTECT_RPC, PUBLIC_RPC]

    def test_fallback_false_reraises(self, mev_settings):
        mev_settings(enabled=True, fallback=False)

        def _always_fail(tx, url):
            raise RuntimeError("eth_sendRawTransaction: RPC error — rejected")

        with patch.object(eth_signer, "_broadcast", side_effect=_always_fail) as m:
            with pytest.raises(RuntimeError, match="rejected"):
                eth_signer.send_raw_transaction(FAKE_TX, PUBLIC_RPC, chain_id=MAINNET)

        # Only the Protect RPC was attempted — no silent public-RPC fallback.
        m.assert_called_once_with(FAKE_TX, PROTECT_RPC)

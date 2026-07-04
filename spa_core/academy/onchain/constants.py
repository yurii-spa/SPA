"""
spa_core/academy/onchain/constants.py

On-chain constants for Academy verifiers.
Source: spa_core/execution/aave_v3_adapter.py (confirmed 2026-07-04)

Event topic hashes are computed via keccak256 AT IMPORT TIME (never hard-coded)
so a copy-paste typo can never silently point a verifier at the wrong event.
The one canonical value we DO assert against in tests is the well-known ERC-20
Transfer topic 0xddf252ad… — see test_academy_onchain.py.

LLM FORBIDDEN in this module (on-chain / data-adjacent).
Academy stage 6.
"""

from __future__ import annotations

import os
from typing import List

# ── Networks ─────────────────────────────────────────────────────────────────
CHAIN_BASE = 8453
CHAIN_BASE_SEPOLIA = 84532

# ── Contracts (source: aave_v3_adapter.py) ───────────────────────────────────
# Aave v3 Base Pool — source: aave_v3_adapter.py:149
AAVE_POOL_BASE = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
# USDC (native) on Base — source: aave_v3_adapter.py:183
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def _keccak256(sig: str) -> str:
    """Compute keccak256(signature) using eth_hash (bundled with eth_account).

    Falls back to a sha3_256 approximation only when eth_hash is unavailable
    (keeps a bare test env importable); production always has eth_hash via
    eth_account, so the real keccak topics are what ship.
    """
    try:
        from eth_hash.auto import keccak
    except ImportError:  # pragma: no cover - eth_hash ships with eth_account
        import hashlib

        return "0x" + hashlib.sha3_256(sig.encode()).hexdigest()
    return "0x" + keccak(sig.encode()).hex()


# ── ERC-20 event topics (computed on import) ─────────────────────────────────
# Transfer(address,address,uint256)  → 0xddf252ad…
TOPIC_TRANSFER = _keccak256("Transfer(address,address,uint256)")
# Approval(address,address,uint256)
TOPIC_APPROVAL = _keccak256("Approval(address,address,uint256)")

# ── Aave Pool event topics (computed on import) ──────────────────────────────
# Supply(address,address,address,uint256,uint16)
TOPIC_SUPPLY = _keccak256("Supply(address,address,address,uint256,uint16)")
# Withdraw(address,address,address,uint256)
TOPIC_WITHDRAW = _keccak256("Withdraw(address,address,address,uint256)")


# ── RPC endpoints (override via env) ─────────────────────────────────────────
_BASE_RPCS_DEFAULT = [
    "https://mainnet.base.org",
    "https://base.llamarpc.com",
    "https://base-rpc.publicnode.com",
]
_SEPOLIA_RPCS_DEFAULT = [
    "https://sepolia.base.org",
    "https://base-sepolia-rpc.publicnode.com",
]


def get_rpc_list(chain: int) -> List[str]:
    """Return the RPC endpoint list for *chain*, honouring env overrides.

    ``SPA_ACADEMY_RPC_BASE`` / ``SPA_ACADEMY_RPC_SEPOLIA`` each pin the list to a
    single endpoint (used in tests and to point at a private node). An unknown
    chain id is a hard error — verifiers never fall through to a guessed network.
    """
    if chain == CHAIN_BASE:
        override = os.getenv("SPA_ACADEMY_RPC_BASE")
        return [override] if override else list(_BASE_RPCS_DEFAULT)
    if chain == CHAIN_BASE_SEPOLIA:
        override = os.getenv("SPA_ACADEMY_RPC_SEPOLIA")
        return [override] if override else list(_SEPOLIA_RPCS_DEFAULT)
    raise ValueError(f"Unknown chain: {chain}")

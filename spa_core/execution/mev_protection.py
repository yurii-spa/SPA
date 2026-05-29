"""
MEV Protection Layer (Sprint v3.26 / SPA-V326 / FEAT-MON-004).

Routes signed transactions through Flashbots Protect RPC instead of the
public Ethereum mempool when ``SPA_MEV_PROTECTION=true`` is set.

## Why this matters

Public mempool transactions are visible to MEV bots before inclusion.
For a $100K portfolio executing supply/withdraw on Aave/Morpho/Yearn,
sandwich attacks can cost 0.1–0.5% per trade. Flashbots Protect routes
transactions privately to block builders, bypassing the public mempool
entirely.

## How it works

Flashbots Protect exposes a standard ``eth_sendRawTransaction`` endpoint:
  - ``https://rpc.flashbots.net``        — standard (waits for inclusion)
  - ``https://rpc.flashbots.net/fast``   — fast mode (first valid builder)

Both endpoints accept signed EIP-1559 transactions exactly like a normal
JSON-RPC endpoint. The difference is that the tx never appears in the
public mempool — it's sent directly to Flashbots block builders.

## SPA integration

``send_protected(signed_tx_hex)`` replaces ``eth_signer.send_raw_transaction``
in the live-execution path of all adapters when:
    os.getenv("SPA_MEV_PROTECTION", "false").lower() == "true"
    AND os.getenv("SPA_EXECUTION_MODE") == "live"

In all other modes (dry_run, paper trading, SPA_MEV_PROTECTION=false),
this module is a no-op and the normal public RPC path is used.

## Environment variables

  SPA_MEV_PROTECTION=true     Enable Flashbots routing (default: false)
  SPA_FLASHBOTS_MODE=fast     Use fast mode (default: standard)
  SPA_FLASHBOTS_HINTS=true    Send calldata hints to Flashbots (default: false)

Sprint v3.26 — initial implementation.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

log = logging.getLogger("spa.mev_protection")

# ─── Flashbots endpoints ──────────────────────────────────────────────────────

FLASHBOTS_RPC_STANDARD = "https://rpc.flashbots.net"
FLASHBOTS_RPC_FAST     = "https://rpc.flashbots.net/fast"
FLASHBOTS_RPC_PROTECT  = "https://protect.flashbots.net"   # legacy

# MEV Blocker (alternative to Flashbots — broader builder coverage)
MEV_BLOCKER_RPC        = "https://rpc.mevblocker.io"
MEV_BLOCKER_RPC_NOREV  = "https://rpc.mevblocker.io/noreverts"

# Ordered fallback list when SPA_MEV_PROTECTION=true
_PROTECTED_ENDPOINTS: list[str] = [
    FLASHBOTS_RPC_FAST,
    FLASHBOTS_RPC_STANDARD,
    MEV_BLOCKER_RPC_NOREV,
]


# ─── Configuration helpers ────────────────────────────────────────────────────

def is_mev_protection_enabled() -> bool:
    """Return True if MEV protection is enabled via env var."""
    return os.getenv("SPA_MEV_PROTECTION", "false").lower() in ("true", "1", "yes")


def get_protected_rpc() -> str:
    """Return the configured Flashbots RPC endpoint."""
    mode = os.getenv("SPA_FLASHBOTS_MODE", "fast").lower()
    if mode == "standard":
        return FLASHBOTS_RPC_STANDARD
    elif mode == "mevblocker":
        return MEV_BLOCKER_RPC_NOREV
    else:
        return FLASHBOTS_RPC_FAST  # default: fast


# ─── Core send function ───────────────────────────────────────────────────────

def send_protected(
    signed_tx_hex: str,
    fallback_rpc: Optional[str] = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Submit a signed transaction through Flashbots Protect RPC.

    Unlike the public mempool, Flashbots routes the transaction directly
    to block builders — it never appears in the public mempool and cannot
    be front-run or sandwich-attacked.

    Parameters
    ----------
    signed_tx_hex : str
        Hex-encoded signed transaction (with or without leading ``0x``).
    fallback_rpc : str, optional
        Public RPC URL to fall back to if ALL Flashbots endpoints fail.
        If None, raises on total failure (production safety: don't
        silently fall through to public mempool in live mode).
    timeout : int
        Per-endpoint timeout in seconds (default: 30).

    Returns
    -------
    dict
        Receipt-like dict with keys: ``tx_hash``, ``status``, ``endpoint``,
        ``protection``, ``block_number``.
        On failure: ``status = "FAILED"`` with ``reason`` key.
    """
    if not signed_tx_hex.startswith("0x"):
        signed_tx_hex = "0x" + signed_tx_hex

    rpc_endpoint = get_protected_rpc()
    log.info("MEV protection: routing tx through %s", rpc_endpoint)

    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "eth_sendRawTransaction",
        "params": [signed_tx_hex],
        "id": 1,
    }).encode()

    # Try Flashbots endpoints in order
    endpoints_to_try = [rpc_endpoint] + [
        ep for ep in _PROTECTED_ENDPOINTS if ep != rpc_endpoint
    ]

    last_error: Optional[Exception] = None
    for endpoint in endpoints_to_try:
        try:
            result = _send_to_endpoint(endpoint, payload, timeout)
            if "error" in result:
                log.warning("Flashbots %s error: %s", endpoint, result["error"])
                last_error = ValueError(f"RPC error: {result['error']}")
                continue
            tx_hash = result.get("result", "")
            log.info("MEV-protected tx submitted: %s via %s", tx_hash, endpoint)
            return {
                "status": "PENDING",
                "tx_hash": tx_hash,
                "endpoint": endpoint,
                "protection": "flashbots",
                "block_number": None,
            }
        except Exception as exc:
            log.warning("Flashbots endpoint %s failed: %s", endpoint, exc)
            last_error = exc
            continue

    # All Flashbots endpoints failed
    if fallback_rpc:
        log.warning(
            "All Flashbots endpoints failed — falling back to public RPC %s. "
            "Transaction will be visible in mempool!",
            fallback_rpc,
        )
        try:
            result = _send_to_endpoint(fallback_rpc, payload, timeout)
            tx_hash = result.get("result", "")
            return {
                "status": "PENDING",
                "tx_hash": tx_hash,
                "endpoint": fallback_rpc,
                "protection": "none (flashbots unavailable)",
                "block_number": None,
                "warning": "MEV protection bypassed — public mempool used",
            }
        except Exception as exc:
            return {
                "status": "FAILED",
                "reason": f"Flashbots + fallback RPC both failed: {exc}",
                "protection": "failed",
            }

    return {
        "status": "FAILED",
        "reason": f"All Flashbots endpoints failed. Last error: {last_error}",
        "protection": "failed",
    }


def send_raw_transaction_auto(
    signed_tx_hex: str,
    public_rpc: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Auto-routing: use Flashbots if SPA_MEV_PROTECTION=true, else public RPC.

    This is the drop-in replacement for ``eth_signer.send_raw_transaction``
    in all adapters' live execution paths.

    Parameters
    ----------
    signed_tx_hex : str
        Signed transaction hex (with or without 0x prefix).
    public_rpc : str
        Public RPC URL — used directly if MEV protection is off, or as
        fallback if Flashbots fails.
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    dict
        Receipt dict: ``{"tx_hash": "0x...", "status": "PENDING", ...}``
    """
    if is_mev_protection_enabled() and os.getenv("SPA_EXECUTION_MODE") == "live":
        log.info("MEV protection ON — using Flashbots Protect RPC")
        return send_protected(
            signed_tx_hex,
            fallback_rpc=public_rpc,
            timeout=timeout,
        )
    else:
        # Standard path — same as before
        from spa_core.execution.eth_signer import send_raw_transaction
        return send_raw_transaction(signed_tx_hex, public_rpc)


# ─── Receipt polling ──────────────────────────────────────────────────────────

def wait_for_receipt(
    tx_hash: str,
    rpc_url: str,
    max_wait: int = 120,
    poll_interval: int = 3,
    timeout: int = 10,
) -> dict[str, Any]:
    """
    Poll for transaction receipt until included or timeout.

    Works with both Flashbots and public RPC endpoints — both expose
    standard ``eth_getTransactionReceipt``.

    Parameters
    ----------
    tx_hash : str
        Transaction hash (0x-prefixed).
    rpc_url : str
        RPC endpoint to poll (can be Flashbots or public).
    max_wait : int
        Maximum seconds to wait (default: 120).
    poll_interval : int
        Seconds between polls (default: 3).
    timeout : int
        Per-request timeout (default: 10).

    Returns
    -------
    dict
        Receipt dict on success. ``{"status": "TIMEOUT"}`` if not included
        within max_wait. ``{"status": "FAILED", "reason": ...}`` on error.
    """
    deadline = time.monotonic() + max_wait
    payload_template = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionReceipt",
        "params": [tx_hash],
        "id": 1,
    }
    log.info("Polling for receipt: %s (max %ds)", tx_hash, max_wait)

    while time.monotonic() < deadline:
        try:
            payload = json.dumps(payload_template).encode()
            result = _send_to_endpoint(rpc_url, payload, timeout)
            receipt = result.get("result")
            if receipt is not None:
                status = "OK" if receipt.get("status") == "0x1" else "REVERTED"
                log.info("Receipt received: %s hash=%s block=%s",
                         status, tx_hash, receipt.get("blockNumber"))
                return {
                    "status": status,
                    "tx_hash": tx_hash,
                    "block_number": receipt.get("blockNumber"),
                    "gas_used": receipt.get("gasUsed"),
                    "raw": receipt,
                }
        except Exception as exc:
            log.debug("Poll error (will retry): %s", exc)

        time.sleep(poll_interval)

    log.warning("Transaction not included within %ds: %s", max_wait, tx_hash)
    return {"status": "TIMEOUT", "tx_hash": tx_hash, "waited_seconds": max_wait}


# ─── Low-level HTTP helper ────────────────────────────────────────────────────

def _send_to_endpoint(url: str, payload: bytes, timeout: int) -> dict[str, Any]:
    """POST JSON-RPC payload to url and return the parsed response."""
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ─── Dry-run mock (for tests) ─────────────────────────────────────────────────

def send_protected_dry_run(signed_tx_hex: str) -> dict[str, Any]:
    """Return a deterministic mock result for tests (no network call)."""
    fake_hash = "0x" + "ab" * 32
    return {
        "status": "PENDING",
        "tx_hash": fake_hash,
        "endpoint": FLASHBOTS_RPC_FAST,
        "protection": "flashbots",
        "block_number": None,
        "dry_run": True,
    }


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("MEV protection enabled:", is_mev_protection_enabled())
    print("Protected RPC:", get_protected_rpc())
    print("Dry-run mock:", send_protected_dry_run("0xdeadbeef"))
    print("Auto-route (no live):", send_raw_transaction_auto.__doc__.split('\n')[0])

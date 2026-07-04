"""
spa_core/academy/onchain/rpc.py

Read-only JSON-RPC client for Academy verifiers.

  - stdlib urllib ONLY (NO requests / web3 / external deps).
  - 3-endpoint fallback per chain via constants.get_rpc_list; fail-CLOSED:
    if every endpoint errors, raise RPCError (a verifier turns that into
    ``status="unavailable"`` — NEVER a silent pass).
  - 10-second timeout per call.
  - Never holds private keys. Only ever issues read-only eth_* methods; the
    thin typed helpers below are the sole call sites and none is state-changing.

Adapted from spa_core/data_pipeline/sky_monitor.py::_eth_call.

LLM FORBIDDEN in this module (on-chain / data-adjacent).
Academy stage 6.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, List, Optional

from spa_core.academy.onchain.constants import get_rpc_list

# Per-call network timeout, seconds.
DEFAULT_TIMEOUT = 10

# Read-only allow-list: the client refuses to send anything state-changing
# (no eth_sendTransaction / eth_sendRawTransaction / personal_* ever).
_ALLOWED_METHODS = frozenset(
    {
        "eth_getTransactionByHash",
        "eth_getTransactionReceipt",
        "eth_getBlockByNumber",
        "eth_getBalance",
        "eth_getLogs",
        "eth_blockNumber",
        "eth_call",
        "eth_chainId",
    }
)


class RPCError(Exception):
    """Raised when a JSON-RPC call fails on every configured endpoint."""


def _call_one(rpc_url: str, method: str, params: list, *, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """Perform a single JSON-RPC call. Return ``result`` or raise RPCError."""
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise RPCError(f"{method} @ {rpc_url}: {exc}") from exc
    if not isinstance(body, dict):
        raise RPCError(f"{method} @ {rpc_url}: non-object response")
    if body.get("error"):
        raise RPCError(f"{method} @ {rpc_url}: {body['error']}")
    if "result" not in body:
        raise RPCError(f"{method} @ {rpc_url}: no result field")
    return body["result"]


def call(chain: int, method: str, params: list) -> Any:
    """Try each RPC in :func:`get_rpc_list` until one succeeds.

    Fail-CLOSED: raise RPCError if EVERY endpoint fails (or the chain is
    unknown). ``result`` may legitimately be ``None`` (e.g. an unknown tx hash);
    that is returned as-is and is NOT treated as an endpoint failure.
    """
    if method not in _ALLOWED_METHODS:
        raise RPCError(f"method not allowed (read-only client): {method}")
    endpoints = get_rpc_list(chain)
    last: Optional[RPCError] = None
    for rpc_url in endpoints:
        try:
            return _call_one(rpc_url, method, params)
        except RPCError as exc:
            last = exc
            continue
    raise RPCError(
        f"all {len(endpoints)} RPC endpoint(s) failed for {method} on chain {chain}"
        + (f": {last}" if last else "")
    )


# ── typed read-only helpers ──────────────────────────────────────────────────


def eth_get_transaction_by_hash(chain: int, tx_hash: str) -> Optional[dict]:
    """Return the transaction object, or None if the node doesn't know it."""
    result = call(chain, "eth_getTransactionByHash", [tx_hash])
    return result if isinstance(result, dict) else None


def eth_get_transaction_receipt(chain: int, tx_hash: str) -> Optional[dict]:
    """Return the transaction receipt, or None if not yet mined / unknown."""
    result = call(chain, "eth_getTransactionReceipt", [tx_hash])
    return result if isinstance(result, dict) else None


def eth_get_block_by_number(chain: int, block_number, full_tx: bool = False) -> Optional[dict]:
    """Return a block object. ``block_number`` may be an int or a tag string."""
    if isinstance(block_number, int):
        tag = hex(block_number)
    else:
        tag = block_number  # "latest" / "0x…"
    result = call(chain, "eth_getBlockByNumber", [tag, full_tx])
    return result if isinstance(result, dict) else None


def eth_block_number(chain: int) -> int:
    """Return the latest block height as an int."""
    result = call(chain, "eth_blockNumber", [])
    return int(result, 16)


def eth_get_balance(chain: int, address: str, block: str = "latest") -> int:
    """Return the account balance in wei as an int."""
    result = call(chain, "eth_getBalance", [address, block])
    return int(result, 16)


def eth_get_logs(chain: int, from_block: int, to_block: int, address: str, topics: list) -> List[dict]:
    """Return log objects matching the filter (address + topics, block range)."""
    flt = {
        "fromBlock": hex(from_block) if isinstance(from_block, int) else from_block,
        "toBlock": hex(to_block) if isinstance(to_block, int) else to_block,
        "address": address,
        "topics": topics,
    }
    result = call(chain, "eth_getLogs", [flt])
    return result if isinstance(result, list) else []

"""
eth_signer.py — Minimal EIP-1559 transaction signer for SPA.

Uses ``eth_account`` (https://github.com/ethereum/eth-account) for all
cryptographic operations (ECDSA / secp256k1 / Keccak-256).  The previous
hand-rolled implementation has been replaced to eliminate the risk of a
silent bug in bespoke cryptography code that handles real private keys.

Requires:  eth-account>=0.10.0  (already in requirements.txt).

Public API (preserved from the previous implementation)
--------------------------------------------------------
sign_transaction(private_key_hex, tx_dict) -> bytes
    Build + sign an EIP-1559 (type-2) transaction.  Returns raw tx bytes.

get_address_from_private_key(private_key_hex) -> str
    Derive the checksummed ``0x...`` Ethereum address from a hex private key.

sign_message(message, private_key_hex) -> str
    Sign an Ethereum prefixed message (EIP-191).  Returns 0x-prefixed hex
    signature string (65 bytes = r + s + v).

encode_function_call(selector_hex, *args) -> bytes
    ABI-encode a function call (uint256 / address / bool args only — enough
    for ERC-20 approve + Aave / Compound supply / withdraw).

keccak256(data) -> bytes
    Return the 32-byte Ethereum keccak-256 hash of *data*.

get_nonce(address, rpc_url) -> int
    eth_getTransactionCount("pending").

estimate_gas(tx_dict, rpc_url) -> int
    eth_estimateGas.

get_base_fee(rpc_url) -> int
    Latest block baseFeePerGas (wei).

send_raw_transaction(signed_tx_hex, rpc_url, chain_id=None) -> str
    eth_sendRawTransaction → tx hash string.  When MEV protection is enabled
    (see below) and ``chain_id == 1`` (Ethereum mainnet), the signed tx is
    routed through the Flashbots Protect RPC instead of the public RPC to
    defend against frontrunning / sandwich attacks.

MEV protection (Sprint v3.26 / SPA-V326)
----------------------------------------
Configured via :mod:`spa_core.adapters.config` (env-driven):
    MEV_PROTECTION_ENABLED   enable Flashbots routing       (default: True)
    FLASHBOTS_PROTECT_RPC    Protect RPC endpoint           (default:
                             https://rpc.flashbots.net/fast)
    MEV_PROTECT_FALLBACK     fall back to the public RPC if the Protect RPC
                             call fails                     (default: True)

Backwards compatibility: when MEV protection is disabled, or the tx is not on
Ethereum mainnet, or no ``chain_id`` is supplied, ``send_raw_transaction``
behaves exactly as before — a plain ``eth_sendRawTransaction`` to *rpc_url*.

Sprint v3.24 — replaced bespoke ECDSA/Keccak with eth_account.
Sprint v3.26 (SPA-V326) — route mainnet txs through Flashbots Protect RPC.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from spa_core.utils.errors import SourceError, ValidationError

log = logging.getLogger("spa.eth_signer")

# Ethereum mainnet chain id — MEV protection only applies here.
_ETHEREUM_MAINNET_CHAIN_ID = 1


# ─── eth_account lazy loader ──────────────────────────────────────────────────

def _get_account():
    """Lazy-import eth_account.Account.

    Returns the ``Account`` class (``eth_account.Account``).

    Raises:
        ImportError: If eth_account is not installed.
            Install with: pip install eth-account>=0.10.0
    """
    try:
        from eth_account import Account  # type: ignore
        return Account
    except ImportError as exc:
        raise ImportError(
            "eth_signer requires the 'eth-account' package. "
            "Install it with: pip install eth-account>=0.10.0"
        ) from exc


# ─── Keccak-256 via eth_hash (bundled with eth_account) ───────────────────────

def keccak256(data: bytes) -> bytes:
    """Return the 32-byte Ethereum keccak-256 hash of *data*.

    Delegates to ``eth_hash.auto.keccak`` which is bundled with eth_account
    and uses the fastest available backend (pysha3 > pycryptodome > pure Python).
    """
    try:
        from eth_hash.auto import keccak  # type: ignore
        return keccak(data)
    except ImportError:
        # Fallback: use eth_account's internal keccak
        from eth_account._utils.signing import keccak as _keccak  # type: ignore
        return _keccak(primitive=data)


# ─── Address derivation ───────────────────────────────────────────────────────

def get_address_from_private_key(private_key_hex: str) -> str:
    """Derive the Ethereum address (checksummed, 0x-prefixed) from a hex private key.

    Args:
        private_key_hex: 64-hex-char private key (``0x`` prefix optional).

    Returns:
        EIP-55 checksummed ``0x...`` address string.

    Raises:
        ValidationError: If the key length is wrong or not valid hex.
        ImportError: If eth_account is not installed.
    """
    pk_hex = private_key_hex[2:] if private_key_hex[:2].lower() == "0x" else private_key_hex
    if len(pk_hex) != 64:
        raise ValidationError("private_key", pk_hex, f"must be 64 hex chars (0x prefix optional); got {len(pk_hex)}")
    Account = _get_account()
    normalised = "0x" + pk_hex
    return Account.from_key(normalised).address


# ─── EIP-1559 transaction signing ─────────────────────────────────────────────

def sign_transaction(private_key_hex: str, tx_dict: dict) -> bytes:
    """Build and sign an EIP-1559 (type-2) transaction.

    Delegates to ``eth_account.Account.sign_transaction`` which uses
    battle-tested RFC-6979 deterministic ECDSA on secp256k1.

    Args:
        private_key_hex: 64-hex-char private key (``0x`` prefix optional).
        tx_dict: Must contain:
            ``to``                   — ``0x...`` address string
            ``data``                 — ``0x...`` hex string or ``bytes``
            ``value``                — int (wei); defaults to 0
            ``nonce``                — int
            ``chainId``              — int
            ``maxFeePerGas``         — int (wei)
            ``maxPriorityFeePerGas`` — int (wei)
            ``gas``                  — int (gas limit)

    Returns:
        Raw signed transaction bytes (EIP-2718 envelope, starts with 0x02).

    Raises:
        ValidationError: If the private key is malformed.
        ImportError: If eth_account is not installed.
    """
    pk_hex = private_key_hex[2:] if private_key_hex[:2].lower() == "0x" else private_key_hex
    if len(pk_hex) != 64:
        raise ValidationError("private_key", pk_hex, f"must be 64 hex chars; got {len(pk_hex)}")
    normalised_pk = "0x" + pk_hex

    # Normalise data field
    data_raw = tx_dict.get("data", b"")
    if isinstance(data_raw, (bytes, bytearray)):
        data_field: str | bytes = bytes(data_raw)
    else:
        data_field = str(data_raw)

    # Build a clean EIP-1559 tx dict that eth_account accepts
    tx = {
        "to":                   tx_dict["to"],
        "value":                int(tx_dict.get("value", 0)),
        "gas":                  int(tx_dict["gas"]),
        "maxFeePerGas":         int(tx_dict["maxFeePerGas"]),
        "maxPriorityFeePerGas": int(tx_dict["maxPriorityFeePerGas"]),
        "nonce":                int(tx_dict["nonce"]),
        "chainId":              int(tx_dict["chainId"]),
        "data":                 data_field,
        "type":                 2,
    }

    Account = _get_account()
    signed = Account.sign_transaction(tx, private_key=normalised_pk)

    # rawTransaction attribute may differ between eth_account versions
    raw = getattr(signed, "rawTransaction", None)
    if raw is None:
        raw = getattr(signed, "raw_transaction", None)
    if raw is None:
        raise ValidationError(
            "rawTransaction",
            None,
            "missing attribute — unexpected eth_account version",
        )
    return bytes(raw)


# ─── Message signing (EIP-191) ────────────────────────────────────────────────

def sign_message(message: str | bytes, private_key_hex: str) -> str:
    """Sign an Ethereum prefixed message (EIP-191 personal_sign).

    Wraps ``message`` in the standard Ethereum prefix
    ``"\\x19Ethereum Signed Message:\\n<len>"`` before signing.

    Args:
        message: The message payload — str (UTF-8 encoded) or raw bytes.
        private_key_hex: 64-hex-char private key (``0x`` prefix optional).

    Returns:
        0x-prefixed hex signature string (65 bytes: r + s + v).

    Raises:
        ValidationError: If the private key is malformed.
        ImportError: If eth_account is not installed.
    """
    pk_hex = private_key_hex[2:] if private_key_hex[:2].lower() == "0x" else private_key_hex
    if len(pk_hex) != 64:
        raise ValidationError("private_key", pk_hex, f"must be 64 hex chars; got {len(pk_hex)}")
    normalised_pk = "0x" + pk_hex

    from eth_account.messages import encode_defunct  # type: ignore

    if isinstance(message, str):
        msg = encode_defunct(text=message)
    else:
        msg = encode_defunct(message)

    Account = _get_account()
    signed = Account.sign_message(msg, private_key=normalised_pk)
    return "0x" + signed.signature.hex()


# ─── ABI encoding ─────────────────────────────────────────────────────────────

def encode_function_call(selector_hex: str, *args: Any) -> bytes:
    """ABI-encode a Solidity function call for uint256 / address / bool args.

    *selector_hex*: 4-byte function selector as ``0xAABBCCDD`` or ``AABBCCDD``.
    *args*: each must be one of:
        - ``int``  → encoded as uint256 (big-endian, 32 bytes)
        - ``str`` starting with ``"0x"`` → treated as an address (20-byte,
          zero-padded to 32 bytes)
        - ``bool`` → encoded as uint256 (0 or 1)

    Returns raw calldata bytes (selector + ABI-encoded args).
    """
    _sel_hex = selector_hex[2:] if selector_hex[:2].lower() == "0x" else selector_hex
    sel = bytes.fromhex(_sel_hex)
    if len(sel) != 4:
        raise ValidationError("selector_hex", selector_hex, f"must be exactly 4 bytes; got {len(sel)}")
    parts = [sel]
    for i, arg in enumerate(args):
        if isinstance(arg, bool):
            parts.append((1 if arg else 0).to_bytes(32, "big"))
        elif isinstance(arg, int):
            if arg < 0 or arg.bit_length() > 256:
                raise ValidationError(f"arg[{i}]", arg, "uint256 must be in [0, 2**256)")
            parts.append(arg.to_bytes(32, "big"))
        elif isinstance(arg, str) and arg.startswith("0x"):
            cleaned = arg[2:].lower()
            if len(cleaned) > 40:
                raise ValidationError(f"arg[{i}]", arg, "address too long for EVM (max 20 bytes)")
            parts.append(bytes.fromhex(cleaned.rjust(40, "0")).rjust(32, b"\x00"))
        else:
            raise ValidationError(f"arg[{i}]", type(arg).__name__, "unsupported type — encode_function_call accepts int, bool, '0x...' str")
    return b"".join(parts)


# ─── MEV protection config ────────────────────────────────────────────────────

# Default Flashbots Protect endpoint, used when config cannot be imported.
_DEFAULT_FLASHBOTS_PROTECT_RPC = "https://rpc.flashbots.net/fast"


def _mev_config() -> tuple[bool, str, bool]:
    """Resolve the MEV-protection settings from :mod:`spa_core.adapters.config`.

    Returns a ``(enabled, protect_rpc, fallback)`` tuple.  The config module is
    imported lazily so this file keeps working even if the adapters package is
    unavailable (in which case safe defaults are used: protection OFF, default
    Protect RPC, fallback ON).
    """
    try:
        from spa_core.adapters import config  # type: ignore
    except ImportError:
        return (False, _DEFAULT_FLASHBOTS_PROTECT_RPC, True)

    enabled = bool(getattr(config, "MEV_PROTECTION_ENABLED", False))
    protect_rpc = getattr(
        config, "FLASHBOTS_PROTECT_RPC", _DEFAULT_FLASHBOTS_PROTECT_RPC
    )
    fallback = bool(getattr(config, "MEV_PROTECT_FALLBACK", True))
    return (enabled, protect_rpc, fallback)


# ─── JSON-RPC helpers ─────────────────────────────────────────────────────────

_RPC_TIMEOUT = 8.0


def _rpc_call(rpc_url: str, method: str, params: list, timeout: float = _RPC_TIMEOUT) -> Any:
    """Post a JSON-RPC call and return the ``result`` field.

    Raises ``RuntimeError`` on HTTP error, JSON-RPC error, or missing result.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(method, f"HTTP failure — {exc}") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError(method, f"malformed JSON — {exc}") from exc

    if "error" in parsed:
        raise SourceError(method, f"RPC error — {parsed['error']}")
    if "result" not in parsed:
        raise SourceError(method, f"missing result in {parsed!r}")
    return parsed["result"]


def get_nonce(address: str, rpc_url: str) -> int:
    """Return the pending transaction count (nonce) for *address*."""
    result = _rpc_call(rpc_url, "eth_getTransactionCount", [address, "pending"])
    return int(result, 16)


def get_base_fee(rpc_url: str) -> int:
    """Return the baseFeePerGas of the latest block (wei)."""
    block = _rpc_call(rpc_url, "eth_getBlockByNumber", ["latest", False])
    if not isinstance(block, dict) or "baseFeePerGas" not in block:
        raise ValidationError(
            "baseFeePerGas",
            block,
            f"missing from block response: {block!r}",
        )
    return int(block["baseFeePerGas"], 16)


def estimate_gas(tx_dict: dict, rpc_url: str) -> int:
    """Call ``eth_estimateGas`` for *tx_dict*.  Returns gas as int."""
    rpc_tx: dict[str, Any] = {}
    for k, v in tx_dict.items():
        if isinstance(v, int):
            rpc_tx[k] = "0x" + format(v, "x")
        elif isinstance(v, bytes):
            rpc_tx[k] = "0x" + v.hex()
        else:
            rpc_tx[k] = v
    result = _rpc_call(rpc_url, "eth_estimateGas", [rpc_tx])
    return int(result, 16)


def _broadcast(signed_tx_hex: str, rpc_url: str) -> str:
    """Low-level ``eth_sendRawTransaction`` to *rpc_url*; returns the tx hash."""
    result = _rpc_call(rpc_url, "eth_sendRawTransaction", [signed_tx_hex])
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ValidationError(
            "result",
            result,
            f"eth_sendRawTransaction returned unexpected result: {result!r}",
        )
    return result


def send_raw_transaction(
    signed_tx_hex: str,
    rpc_url: str,
    chain_id: int | None = None,
) -> str:
    """Broadcast *signed_tx_hex* via ``eth_sendRawTransaction``.

    *signed_tx_hex* must include the ``0x`` prefix.

    MEV protection (Sprint v3.26 / SPA-V326)
    ----------------------------------------
    When MEV protection is enabled (``MEV_PROTECTION_ENABLED``) *and*
    ``chain_id == 1`` (Ethereum mainnet), the transaction is routed through the
    Flashbots Protect RPC (``FLASHBOTS_PROTECT_RPC``) so it never enters the
    public mempool and cannot be frontrun / sandwich-attacked.

    - If the network is not Ethereum mainnet (``chain_id`` is ``None`` or not
      ``1``), a warning is logged and the tx is sent to the public *rpc_url*.
    - If the Protect RPC call fails and ``MEV_PROTECT_FALLBACK`` is True
      (default), the tx is re-broadcast to the public *rpc_url*; otherwise the
      error is re-raised.

    Args:
        signed_tx_hex: 0x-prefixed signed raw transaction.
        rpc_url: Public RPC endpoint (used directly when protection is off, or
            as the fallback when Protect RPC fails).
        chain_id: Network chain id.  MEV routing only applies when this is
            ``1`` (mainnet).  Optional for backwards compatibility.

    Returns:
        The transaction hash string (``0x...``).

    Raises:
        RuntimeError: On broadcast failure (Protect RPC failure when fallback
            is disabled, or public RPC failure).
    """
    enabled, protect_rpc, fallback = _mev_config()

    if not enabled:
        # Protection off — original behaviour, plain public broadcast.
        return _broadcast(signed_tx_hex, rpc_url)

    if chain_id != _ETHEREUM_MAINNET_CHAIN_ID:
        # Flashbots Protect is mainnet-only — fall back to the public RPC.
        log.warning(
            "MEV protection enabled but chain_id=%r is not Ethereum mainnet "
            "(%d); broadcasting via public RPC instead.",
            chain_id,
            _ETHEREUM_MAINNET_CHAIN_ID,
        )
        return _broadcast(signed_tx_hex, rpc_url)

    # Mainnet + protection on → route through Flashbots Protect RPC.
    log.info("MEV protection: routing mainnet tx through Protect RPC %s", protect_rpc)
    try:
        return _broadcast(signed_tx_hex, protect_rpc)
    except RuntimeError as exc:
        if fallback:
            log.warning(
                "Flashbots Protect RPC failed (%s); MEV_PROTECT_FALLBACK is on, "
                "re-broadcasting via public RPC %s — tx will be visible in the "
                "public mempool.",
                exc,
                rpc_url,
            )
            return _broadcast(signed_tx_hex, rpc_url)
        log.error(
            "Flashbots Protect RPC failed (%s) and MEV_PROTECT_FALLBACK is off; "
            "not falling back to public RPC.",
            exc,
        )
        raise

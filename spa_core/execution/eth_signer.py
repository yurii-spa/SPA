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

assert_nonce_ok(intended_nonce, pending_nonce) -> int
    Fail-CLOSED nonce-gap / reuse guard (WS-3.3) — call BEFORE signing.  Raises
    ValidationError if the intended nonce is not exactly the on-chain pending
    nonce (a gap would stall the tx; a lower value is reuse).

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
                             call fails  (default: FALSE — WS-5.3 fail-CLOSED;
                             owner must EXPLICITLY opt in to public fallback)

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

from spa_core.execution.arming import assert_live_armed
from spa_core.utils.errors import SourceError, ValidationError

log = logging.getLogger("spa.eth_signer")

# Ethereum mainnet chain id — MEV protection only applies here.
_ETHEREUM_MAINNET_CHAIN_ID = 1


# ─── Key-material handling (centralised, leak-proof) ──────────────────────────
#
# SECURITY CONTRACT (WS-3.3 hardening, builds on the WS-1.1 redaction):
#   * The raw private key must NEVER appear in ANY surfaced diagnostic — not in
#     a ValidationError message, not in a log line, not in the repr() of an
#     exception raised on the signing path.
#   * All key normalisation lives in ONE place (_strip_hex_prefix / _pk_to_bytes)
#     so the redaction can't be reintroduced piecemeal by a future inline edit.
#   * Every call into the crypto backend is wrapped by ``_scrub_key`` so that
#     even if the backend echoes the key into its own exception (some
#     eth_account versions stringify ``private_key=...``), we re-raise a scrubbed
#     error rather than letting the secret propagate.

_REDACTED = "<redacted>"


def _strip_hex_prefix(value: str) -> str:
    """Strip a leading ``0x`` / ``0X`` prefix WITHOUT eating significant zeros.

    A naive ``value.lstrip("0x")`` removes ANY leading 0/x chars and so corrupts
    keys/selectors whose first nibble is zero (e.g. ``0x00ab…`` → ``ab…``). This
    helper removes ONLY the two-char prefix.
    """
    if value[:2] in ("0x", "0X"):
        return value[2:]
    return value


def _pk_to_bytes(private_key_hex: str) -> bytes:
    """Normalise a hex private key to its raw 32 bytes, fail-CLOSED on shape.

    Raises ``ValidationError`` (with the key REDACTED — never echoed) if the
    value is not exactly 64 hex chars after stripping the ``0x`` prefix.
    """
    pk_hex = _strip_hex_prefix(private_key_hex)
    if len(pk_hex) != 64:
        # SECURITY: never echo the raw key material into the error (it would
        # propagate into logs / tracebacks). Report only the redacted value + length.
        raise ValidationError(
            "private_key", _REDACTED, f"must be 64 hex chars (0x prefix optional); got {len(pk_hex)}"
        )
    try:
        raw = bytes.fromhex(pk_hex)
    except ValueError:
        # A non-hex character — report redacted, never the offending nibble.
        raise ValidationError("private_key", _REDACTED, "must be valid hex (0-9a-fA-F)")
    if len(raw) != 32:  # pragma: no cover - defensive; 64 hex chars == 32 bytes
        raise ValidationError("private_key", _REDACTED, f"must be 32 bytes; got {len(raw)}")
    return raw


def _normalised_pk(private_key_hex: str) -> str:
    """Return the canonical ``0x`` + 64-hex form of *private_key_hex*.

    Validates shape via :func:`_pk_to_bytes` (fail-CLOSED, key redacted), then
    rebuilds the canonical string from the validated bytes so leading zeros and
    case are preserved deterministically.
    """
    return "0x" + _pk_to_bytes(private_key_hex).hex()


def _scrub(text: object, secrets: tuple[str, ...]) -> str:
    """Replace every occurrence of each secret (and its 0x-variants) in *text*.

    Used to sanitise any backend-raised message before we re-surface it.
    """
    out = str(text)
    for s in secrets:
        if not s:
            continue
        for variant in (s, "0x" + s, "0X" + s, s.lower(), s.upper()):
            if variant and variant in out:
                out = out.replace(variant, _REDACTED)
    return out


def _scrub_key(fn: Any, private_key_hex: str, normalised_pk: str) -> Any:
    """Invoke ``fn()`` (a crypto-backend call) and, on ANY exception, re-raise a
    scrubbed copy so the private key can never leak through the backend's own
    error message / args / repr.

    The original exception type is preserved; only its textual content is
    scrubbed. We deliberately do NOT log the key here (nothing logs it).
    """
    # Build the set of secret forms to scrub: the raw input, the 0x-stripped
    # body, and the canonical normalised form.
    body = _strip_hex_prefix(private_key_hex)
    norm_body = _strip_hex_prefix(normalised_pk)
    secrets = tuple({private_key_hex, body, normalised_pk, norm_body})
    try:
        return fn()
    except BaseException as exc:  # noqa: BLE001 - re-raised scrubbed, never swallowed
        scrubbed_msg = _scrub(exc, secrets)
        # If the backend leaked nothing, re-raise the original untouched so the
        # traceback / type stays maximally faithful.
        original = str(exc)
        if scrubbed_msg == original and not any(
            s and (s in repr(exc.args)) for s in secrets
        ):
            raise
        # Otherwise re-raise the SAME exception type with a scrubbed message.
        try:
            raise type(exc)(scrubbed_msg) from None
        except TypeError:
            # Exception type can't be rebuilt from a single str arg → raise a
            # generic RuntimeError carrying only the scrubbed text.
            raise RuntimeError(scrubbed_msg) from None  # drill: intentional fault injection


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
    normalised = _normalised_pk(private_key_hex)  # fail-CLOSED, key redacted on bad shape
    Account = _get_account()
    return _scrub_key(
        lambda: Account.from_key(normalised).address,
        private_key_hex,
        normalised,
    )


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
        LiveTradingForbiddenError: unless SPA_EXEC_ARMED is explicitly armed
            (WS-5.1 structural guard — OFF the whole paper period).
        ValidationError: If the private key is malformed.
        ImportError: If eth_account is not installed.
    """
    # WS-5.1 STRUCTURAL guard: this capital primitive self-checks the global
    # arming flag BEFORE touching any key material. A direct call that bypasses
    # the adapter's @live_trading_forbidden wrapper is still blocked here.
    assert_live_armed("eth_signer.sign_transaction")

    normalised_pk = _normalised_pk(private_key_hex)  # fail-CLOSED, key redacted on bad shape

    # SECURITY (WS-3.3): a malformed nonce is a fail-CLOSED abort BEFORE we sign.
    # A negative or non-integer nonce can never produce a valid tx — refuse to
    # build one rather than sign garbage the chain would reject (or worse,
    # accept at an unintended slot).
    nonce_val = _coerce_nonce(tx_dict.get("nonce"))

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
        "nonce":                nonce_val,
        "chainId":              int(tx_dict["chainId"]),
        "data":                 data_field,
        "type":                 2,
    }

    Account = _get_account()
    signed = _scrub_key(
        lambda: Account.sign_transaction(tx, private_key=normalised_pk),
        private_key_hex,
        normalised_pk,
    )

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
    normalised_pk = _normalised_pk(private_key_hex)  # fail-CLOSED, key redacted on bad shape

    from eth_account.messages import encode_defunct  # type: ignore

    if isinstance(message, str):
        msg = encode_defunct(text=message)
    else:
        msg = encode_defunct(message)

    Account = _get_account()
    signed = _scrub_key(
        lambda: Account.sign_message(msg, private_key=normalised_pk),
        private_key_hex,
        normalised_pk,
    )
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
        # WS-5.3 fail-CLOSED: protection OFF, default Protect RPC, NO public
        # fallback (was True — leaked to mempool when config was unavailable).
        return (False, _DEFAULT_FLASHBOTS_PROTECT_RPC, False)

    enabled = bool(getattr(config, "MEV_PROTECTION_ENABLED", False))
    protect_rpc = getattr(
        config, "FLASHBOTS_PROTECT_RPC", _DEFAULT_FLASHBOTS_PROTECT_RPC
    )
    # WS-5.3: fail-CLOSED MEV posture. The raw path now defaults to NO public
    # fallback (matching the adapter path), so a Protect-RPC failure ABORTS
    # rather than silently leaking the tx into the public mempool. The public
    # fallback only re-enables when the owner EXPLICITLY opts in via
    # config.MEV_PROTECT_FALLBACK=True.
    fallback = bool(getattr(config, "MEV_PROTECT_FALLBACK", False))
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


# ─── Nonce safety (WS-3.3) ────────────────────────────────────────────────────

def _coerce_nonce(nonce: Any) -> int:
    """Validate + coerce a tx nonce, fail-CLOSED on anything malformed.

    A nonce must be a non-negative integer. ``bool`` is rejected explicitly
    (``True``/``False`` are ints in Python and would silently become 1/0). A
    negative, non-finite, or non-integral nonce raises ``ValidationError`` so a
    garbage tx is never signed.
    """
    if isinstance(nonce, bool):
        raise ValidationError("nonce", nonce, "must be an integer, not bool")
    if isinstance(nonce, float):
        # Reject NaN/Inf and any non-integral float (e.g. 5.5) — never round.
        if nonce != nonce or nonce in (float("inf"), float("-inf")) or not nonce.is_integer():
            raise ValidationError("nonce", nonce, "must be a non-negative integer")
        nonce = int(nonce)
    if not isinstance(nonce, int):
        raise ValidationError("nonce", nonce, "must be a non-negative integer")
    if nonce < 0:
        raise ValidationError("nonce", nonce, "must be non-negative (no nonce reuse below current)")
    return nonce


def assert_nonce_ok(intended_nonce: int, pending_nonce: int) -> int:
    """Fail-CLOSED nonce-gap / reuse guard, to be called BEFORE signing.

    The on-chain ``pending`` nonce (from :func:`get_nonce`) is the ONLY value
    that produces an immediately-includable tx. Deviations are refused:

      * ``intended < pending``  → REUSE: a tx at this nonce is already pending or
        mined; re-using it would either replace-by-fee an unrelated tx or be
        dropped. ABORT.
      * ``intended > pending``  → GAP: the tx would be stuck (the chain executes
        nonces strictly in order) until the gap is filled, leaving capital in an
        indeterminate state. ABORT.

    Returns *intended_nonce* unchanged when it exactly equals *pending_nonce*.

    Raises:
        ValidationError: on a gap or reuse, or on malformed inputs.
    """
    intended = _coerce_nonce(intended_nonce)
    pending = _coerce_nonce(pending_nonce)
    if intended < pending:
        raise ValidationError(
            "nonce",
            intended,
            f"nonce reuse: intended {intended} < on-chain pending {pending} — ABORT (no submit)",
        )
    if intended > pending:
        raise ValidationError(
            "nonce",
            intended,
            f"nonce gap: intended {intended} > on-chain pending {pending} — ABORT (tx would stall)",
        )
    return intended


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
    - WS-5.3 fail-CLOSED: if the Protect RPC call fails, the error is re-raised
      and NOTHING falls through to the public mempool — UNLESS the owner has
      EXPLICITLY opted in via ``MEV_PROTECT_FALLBACK=True`` (now defaults to
      False, matching the adapter path's fail-CLOSED MEV posture).

    Args:
        signed_tx_hex: 0x-prefixed signed raw transaction.
        rpc_url: Public RPC endpoint (used directly when protection is off, or
            as the fallback ONLY when MEV_PROTECT_FALLBACK is explicitly on).
        chain_id: Network chain id.  MEV routing only applies when this is
            ``1`` (mainnet).  Optional for backwards compatibility.

    Returns:
        The transaction hash string (``0x...``).

    Raises:
        LiveTradingForbiddenError: unless SPA_EXEC_ARMED is explicitly armed
            (WS-5.1 structural guard — OFF the whole paper period).
        RuntimeError: On broadcast failure (Protect RPC failure when fallback
            is disabled, or public RPC failure).
    """
    # WS-5.1 STRUCTURAL guard: this broadcast primitive self-checks the global
    # arming flag BEFORE any network submit. A direct call bypassing the
    # adapter's @live_trading_forbidden wrapper is still blocked here.
    assert_live_armed("eth_signer.send_raw_transaction")

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

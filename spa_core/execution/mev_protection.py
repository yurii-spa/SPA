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
Sprint v3.52 (SPA-V352) — wired into all adapter live-send paths; public path
now returns a consistent receipt-like dict; added ``broadcast_protected_hash``
for hash-consuming callers (Aave/Compound).
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from spa_core.execution.arming import assert_live_armed
from spa_core.utils.errors import SourceError

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


# ─── Gas / sandwich adversarial guard (WS-3.4) ────────────────────────────────
#
# A purely deterministic pre-broadcast gate. It NEVER touches the network and
# NEVER signs — it only DECIDES, given (a) the gas price the cycle proposes,
# (b) a (gas-oracle reading, reading-age) pair, and (c) an MEV/sandwich risk
# score, whether to:
#     * "OK"      — proceed on the public path (cheap, low MEV risk),
#     * "PROTECT" — re-route through a private/protected relay (gas spike or
#                   sandwich risk that a private route mitigates), or
#     * "ABORT"   — fail-CLOSED (oracle stale → we can't trust the price; or the
#                   gas spike is so large we refuse to overpay blindly).
#
# fail-CLOSED bias: any UNKNOWN / stale / non-finite input ⇒ ABORT, never a
# naive public submit.

# A gas oracle reading older than this is untrustworthy → ABORT.
GAS_ORACLE_MAX_STALENESS_S = 60.0
# Proposed gas price above this MULTIPLE of the oracle baseline is a "spike".
# A spike is routable privately, but…
GAS_SPIKE_PROTECT_MULT = 1.5
# …above this HARD multiple we refuse to overpay blindly → ABORT.
GAS_SPIKE_ABORT_MULT = 3.0
# Sandwich/MEV composite risk at/above this routes PRIVATE; below proceeds.
SANDWICH_PROTECT_RISK = 0.10
# …and at/above this HARD score even a private route is refused → ABORT.
SANDWICH_ABORT_RISK = 0.85

_GAS_DECISIONS = ("OK", "PROTECT", "ABORT")


def evaluate_gas_and_mev(
    proposed_gas_gwei: float,
    oracle_gas_gwei: float,
    oracle_age_s: float,
    sandwich_risk: float = 0.0,
) -> dict:
    """Deterministic, fail-CLOSED decision for a pending broadcast.

    Parameters
    ----------
    proposed_gas_gwei : float
        The gas price the cycle intends to pay (gwei).
    oracle_gas_gwei : float
        The current gas oracle baseline (gwei).
    oracle_age_s : float
        Seconds since the oracle reading was taken. A stale oracle ⇒ ABORT.
    sandwich_risk : float
        Composite MEV/sandwich risk in [0, 1] (e.g. from MEVRiskDetector).

    Returns
    -------
    dict
        ``{"decision": "OK"|"PROTECT"|"ABORT", "reason": str,
           "gas_ratio": float|None, "require_private": bool}``.

    The function NEVER raises on bad input — a non-finite / negative / stale
    reading deterministically yields ``ABORT`` (fail-CLOSED).
    """
    def _abort(reason: str) -> dict:
        return {"decision": "ABORT", "reason": reason, "gas_ratio": None,
                "require_private": True}

    # --- Input sanity → fail-CLOSED on anything we can't trust. ---
    for name, val in (("proposed_gas_gwei", proposed_gas_gwei),
                      ("oracle_gas_gwei", oracle_gas_gwei),
                      ("oracle_age_s", oracle_age_s),
                      ("sandwich_risk", sandwich_risk)):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            return _abort(f"{name} not numeric → ABORT (fail-closed)")
        if val != val or val in (float("inf"), float("-inf")):  # NaN / Inf
            return _abort(f"{name} non-finite → ABORT (fail-closed)")
    if proposed_gas_gwei < 0 or oracle_gas_gwei <= 0 or oracle_age_s < 0:
        return _abort("non-positive/negative gas or age → ABORT (fail-closed)")
    if not (0.0 <= sandwich_risk <= 1.0):
        return _abort(f"sandwich_risk {sandwich_risk} outside [0,1] → ABORT (fail-closed)")

    # --- Stale oracle: we can't trust the baseline → never submit blindly. ---
    if oracle_age_s > GAS_ORACLE_MAX_STALENESS_S:
        return _abort(
            f"gas oracle stale ({oracle_age_s:.0f}s > {GAS_ORACLE_MAX_STALENESS_S:.0f}s) "
            "→ ABORT (fail-closed)"
        )

    gas_ratio = proposed_gas_gwei / oracle_gas_gwei

    # --- Hard sandwich risk: even a private relay can't make this safe. ---
    if sandwich_risk >= SANDWICH_ABORT_RISK:
        return {"decision": "ABORT",
                "reason": f"sandwich risk {sandwich_risk:.2f} >= {SANDWICH_ABORT_RISK} → ABORT",
                "gas_ratio": round(gas_ratio, 4), "require_private": True}

    # --- Hard gas spike: refuse to overpay blindly. ---
    if gas_ratio >= GAS_SPIKE_ABORT_MULT:
        return {"decision": "ABORT",
                "reason": (f"gas spike {gas_ratio:.2f}x baseline >= "
                           f"{GAS_SPIKE_ABORT_MULT}x → ABORT (won't overpay)"),
                "gas_ratio": round(gas_ratio, 4), "require_private": True}

    # --- Routable spike or elevated sandwich risk → require PRIVATE route. ---
    if gas_ratio >= GAS_SPIKE_PROTECT_MULT:
        return {"decision": "PROTECT",
                "reason": (f"gas spike {gas_ratio:.2f}x baseline >= "
                           f"{GAS_SPIKE_PROTECT_MULT}x → route PRIVATE"),
                "gas_ratio": round(gas_ratio, 4), "require_private": True}
    if sandwich_risk >= SANDWICH_PROTECT_RISK:
        return {"decision": "PROTECT",
                "reason": (f"sandwich risk {sandwich_risk:.2f} >= "
                           f"{SANDWICH_PROTECT_RISK} → route PRIVATE"),
                "gas_ratio": round(gas_ratio, 4), "require_private": True}

    # --- Calm market, low MEV risk → public path is fine. ---
    return {"decision": "OK", "reason": "gas normal, MEV risk low",
            "gas_ratio": round(gas_ratio, 4), "require_private": False}


def guard_broadcast(
    signed_tx_hex: str,
    proposed_gas_gwei: float,
    oracle_gas_gwei: float,
    oracle_age_s: float,
    sandwich_risk: float = 0.0,
    fallback_rpc: Optional[str] = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Gas/MEV-aware broadcast: evaluate FIRST, then route protected or ABORT.

    This is the WS-3.4 fail-CLOSED entry point. It will NEVER do a naive public
    submit under a gas spike or sandwich pattern:

      * ``ABORT``   → returns ``{"status": "ABORTED", ...}`` and broadcasts
                      NOTHING (stale oracle / extreme spike / extreme sandwich).
      * ``PROTECT`` → routes through :func:`send_protected` (private relay), with
                      NO public fallback (a private-required tx must not silently
                      fall through to the mempool).
      * ``OK``      → routes through :func:`send_protected` as well, but the
                      caller-supplied ``fallback_rpc`` is permitted.

    The tx is only ever handed to a protected relay; the public path is reachable
    only as an explicit fallback on an ``OK`` decision.
    """
    verdict = evaluate_gas_and_mev(
        proposed_gas_gwei, oracle_gas_gwei, oracle_age_s, sandwich_risk
    )
    decision = verdict["decision"]
    if decision == "ABORT":
        log.error("guard_broadcast ABORT — %s (no tx submitted)", verdict["reason"])
        return {"status": "ABORTED", "reason": verdict["reason"],
                "protection": "aborted", "gas_ratio": verdict["gas_ratio"]}

    # PROTECT → private only (no public fallback). OK → may fall back to public.
    fb = None if verdict["require_private"] else fallback_rpc
    log.info("guard_broadcast %s — %s", decision, verdict["reason"])
    result = send_protected(signed_tx_hex, fallback_rpc=fb, timeout=timeout)
    result["gas_decision"] = decision
    result["gas_reason"] = verdict["reason"]
    return result


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

    Raises
    ------
    LiveTradingForbiddenError
        unless SPA_EXEC_ARMED is explicitly armed (WS-5.1 structural guard —
        OFF the whole paper period).
    """
    # WS-5.1 STRUCTURAL guard: this broadcast primitive self-checks the global
    # arming flag BEFORE any network submit. A direct call bypassing an adapter's
    # @live_trading_forbidden wrapper is still blocked here.
    assert_live_armed("mev_protection.send_protected")

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
        # Standard path — public mempool. Normalise the raw tx-hash string into
        # the same receipt-like dict shape that ``send_protected`` returns, so
        # every caller gets a consistent contract regardless of routing.
        # (Sprint v3.52 / SPA-V352 — adapters consume the result as a dict.)
        from spa_core.execution.eth_signer import send_raw_transaction
        raw = send_raw_transaction(signed_tx_hex, public_rpc)
        if isinstance(raw, dict):
            return raw
        return {
            "status": "PENDING",
            "tx_hash": raw,
            "endpoint": public_rpc,
            "protection": "none",
            "block_number": None,
        }


def broadcast_protected_hash(signed_tx_hex: str, timeout: int = 30) -> str:
    """MEV-route a signed tx through Flashbots Protect and return its tx hash.

    Thin convenience for hash-consuming callers (e.g. the Aave/Compound
    adapters, whose ``_send_raw_tx`` returns a hash string and then polls for
    the receipt separately). Routes through ``send_protected`` with NO public
    fallback — the caller decides whether to fall back to its own public RPC.

    Parameters
    ----------
    signed_tx_hex : str
        Signed transaction hex (with or without leading ``0x``).
    timeout : int
        Per-endpoint timeout in seconds (default: 30).

    Returns
    -------
    str
        The ``0x``-prefixed transaction hash.

    Raises
    ------
    RuntimeError
        If every protected endpoint fails (so the caller can fall back).
    """
    res = send_protected(signed_tx_hex, fallback_rpc=None, timeout=timeout)
    tx_hash = res.get("tx_hash")
    if res.get("status") == "FAILED" or not tx_hash:
        raise SourceError(
            "mev_protection",
            f"MEV-protected broadcast failed: {res.get('reason', res)}",
        )
    return tx_hash


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

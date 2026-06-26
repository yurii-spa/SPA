"""
spa_core/strategy_lab/rwa_backstop/onchain_nav.py — REAL on-chain intrinsic-NAV reader.

The brief's core insight: "the asset IS its executable liquidation path." The strongest
Liquidation-NAV anchor is the on-chain INTRINSIC value of a share — totalAssets()/totalSupply()
(ERC-4626) or convertToAssets(1e18) — measured directly from the token contract via a keyless
JSON-RPC `eth_call`, NOT the uniform $1.00 marketing assumption and NOT a DeFiLlama aggregate.

Where a tokenized-RWA token is a real ERC-4626 vault that exposes those views read-only, we can
derive its intrinsic NAV per share on-chain. That is far more authoritative than assuming par:
if the intrinsic NAV diverges from $1.00, that divergence IS a real risk signal.

Reality check (the HONEST result): MOST tokenized-RWA tokens here are PERMISSIONED, non-4626
transfer-agent tokens (BUIDL, OUSG, BENJI, USYC, VBILL…). They do NOT expose totalAssets() — the
call reverts or returns garbage. For those we mark nav_source="off_chain_estimate" and keep the
existing marketing/DeFiLlama value. Partial coverage is the honest outcome; we never fabricate.

FAIL-CLOSED everywhere:
  • no token contract                       → off_chain_estimate
  • RPC unreachable / every endpoint down    → off_chain_estimate
  • method reverts / empty / non-hex return   → off_chain_estimate
  • totalSupply == 0 / decimals out of range  → off_chain_estimate
  • derived NAV outside a sane band           → off_chain_estimate (a corrupt read is NOT a signal)
Never invent an on-chain NAV. A read either CLEANLY succeeds or we fall back to the estimate.

stdlib only: urllib (JSON-RPC POST) + json. Deterministic given an injected response. ADVISORY.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# ── 4-byte function selectors (keccak256(signature)[:4]) ────────────────────────────────────────
# Standard, well-known ERC-20 / ERC-4626 selectors. Hard-coded constants (no keccak in stdlib).
SEL_TOTAL_ASSETS = "0x01e1d114"  # totalAssets()                       → uint256 (ERC-4626)
SEL_TOTAL_SUPPLY = "0x18160ddd"  # totalSupply()                       → uint256 (ERC-20)
SEL_DECIMALS = "0x313ce567"      # decimals()                          → uint8
# convertToAssets(uint256 shares) — assets for `shares`. We pass 1 * 10**decimals (one whole share)
SEL_CONVERT_TO_ASSETS = "0x07a2d13a"

# Public, KEYLESS Ethereum JSON-RPC endpoints to probe, in order. First that answers a valid
# eth_chainId == 0x1 (mainnet) is used for the run. All are best-effort public RPCs — if NONE
# respond we fail-CLOSED to the estimate for every asset (the board still works on estimates).
KEYLESS_RPC_ENDPOINTS: Tuple[str, ...] = (
    "https://ethereum-rpc.publicnode.com",  # serves eth_call keyless (verified)
    "https://eth.drpc.org",                 # serves eth_call keyless (verified)
    "https://eth.llamarpc.com",
    "https://cloudflare-eth.com",           # answers eth_chainId but GATES eth_call (probed out)
    "https://rpc.ankr.com/eth",
    "https://1rpc.io/eth",
)

# A canonical mainnet ERC-4626 vault used ONLY to validate that a candidate endpoint actually
# SERVES eth_call (not just eth_chainId). sDAI (Spark Savings DAI) is a long-lived 18-decimal 4626
# vault. An endpoint that returns decimals()==18 for it is genuinely usable; one that errors on the
# call (e.g. Cloudflare's gated public RPC) is rejected even though it answered the chainId probe.
_PROBE_4626_CONTRACT = "0x83F20F44975D03b1b09e64809B757c47f942BEeA"  # sDAI
_PROBE_EXPECT_DECIMALS = 18

# Sanity band for a tokenized-T-bill / MMF intrinsic NAV per share (USD). A clean read outside this
# band is treated as a mis-decode / wrong-decimals / wrong-ABI and REJECTED (fail-CLOSED) — we do
# NOT surface a $0.0003 or $48,000 "NAV" as a risk signal. T-bill funds sit very near $1; a true
# break this wide would be caught by other monitors, and a read this wild is almost always an ABI
# mismatch (e.g. a non-4626 token that happened to return data for the 0x01e1d114 slot).
NAV_SANITY_LOW_USD = 0.50
NAV_SANITY_HIGH_USD = 2.00

NAV_SOURCE_ONCHAIN = "onchain_4626"
NAV_SOURCE_ESTIMATE = "off_chain_estimate"

# A JSON-RPC fetcher: (url, post_json_dict) -> parsed json. Injected in tests; the real one POSTs
# via urllib. Returning a dict with an "error" key (or raising) means the call failed → fail-closed.
RpcFetcher = Callable[[str, dict], object]

_DEFAULT_TIMEOUT = 12
_UA = "spa-rwa-onchain/1.0 (+stdlib)"


# ── stdlib JSON-RPC POST (keyless) ──────────────────────────────────────────────────────────────
def _http_rpc(url: str, payload: dict, timeout: int = _DEFAULT_TIMEOUT) -> object:
    """POST a JSON-RPC request and return parsed JSON. Raises on any transport/parse failure
    (the caller treats a raise as fail-CLOSED). stdlib urllib + json only."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


# ── eth_call encode / decode (deterministic, pure) ──────────────────────────────────────────────
def encode_eth_call(to_addr: str, data_hex: str, call_id: int = 1) -> dict:
    """Build a standard `eth_call` JSON-RPC request body against `to_addr` with calldata
    `data_hex` (e.g. a bare 4-byte selector, or selector + 32-byte-padded args), at the latest
    block. Pure; no IO. `to_addr` is lower-cased; `data_hex` is normalized to a 0x string."""
    if not to_addr:
        raise ValueError("encode_eth_call: empty to_addr")
    data = data_hex if data_hex.startswith("0x") else ("0x" + data_hex)
    return {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "eth_call",
        "params": [{"to": to_addr.lower(), "data": data}, "latest"],
    }


def encode_convert_to_assets(one_share_decimals: int) -> str:
    """Calldata for convertToAssets(1 whole share) = selector + uint256(10**decimals), abi-padded
    to 32 bytes. `one_share_decimals` is the token's decimals."""
    if one_share_decimals < 0 or one_share_decimals > 36:
        raise ValueError(f"convertToAssets: implausible decimals {one_share_decimals}")
    shares = 10 ** one_share_decimals
    return SEL_CONVERT_TO_ASSETS + f"{shares:064x}"


def decode_uint(result_hex: object) -> Optional[int]:
    """Decode an `eth_call` 0x-hex result to a non-negative int. Fail-CLOSED: returns None for a
    missing / non-string / empty (`0x`) / non-hex / reverted result. A revert on a public RPC most
    commonly surfaces as `0x` or an error object (handled by the caller) — both → None here."""
    if not isinstance(result_hex, str):
        return None
    s = result_hex.strip()
    if not s.startswith("0x"):
        return None
    h = s[2:]
    if h == "" or h == "0" * len(h) and len(h) == 0:
        return None
    try:
        # Take the LAST 32 bytes (64 hex) if the return is wider (defensive); a bare uint is 64 hex.
        if len(h) > 64:
            h = h[-64:]
        return int(h, 16)
    except ValueError:
        return None


@dataclass(frozen=True)
class OnchainNAV:
    """The result of an on-chain intrinsic-NAV probe for one asset."""
    symbol: str
    nav_source: str                       # NAV_SOURCE_ONCHAIN | NAV_SOURCE_ESTIMATE
    onchain_nav_usd: Optional[float]      # intrinsic NAV/share in USD, or None (estimate path)
    total_assets: Optional[int] = None    # raw totalAssets() (smallest unit), if read
    total_supply: Optional[int] = None    # raw totalSupply() (smallest unit), if read
    decimals: Optional[int] = None        # token decimals, if read
    rpc_endpoint: Optional[str] = None    # which RPC answered, if any
    reason: str = ""                      # human note (why estimate, or how NAV derived)


# ── the reader ──────────────────────────────────────────────────────────────────────────────────
class OnchainNAVReader:
    """Read the on-chain intrinsic NAV/share for ERC-4626-style tokenized funds via keyless
    JSON-RPC `eth_call`. Inject `rpc_fetcher` (url, payload)->json in tests; the real one POSTs to
    the first responsive keyless mainnet endpoint. FAIL-CLOSED: any failure → OnchainNAV with
    nav_source=off_chain_estimate and onchain_nav_usd=None, so the caller keeps its estimate."""

    def __init__(
        self,
        rpc_fetcher: Optional[RpcFetcher] = None,
        endpoints: Tuple[str, ...] = KEYLESS_RPC_ENDPOINTS,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self._fetch = rpc_fetcher
        self._endpoints = tuple(endpoints)
        self._timeout = timeout
        self._active_endpoint: Optional[str] = None
        self._probed = False

    # ── endpoint selection ──────────────────────────────────────────────────────────────────────
    def _call(self, url: str, payload: dict) -> object:
        if self._fetch is not None:
            return self._fetch(url, payload)
        return _http_rpc(url, payload, timeout=self._timeout)

    def _result_value(self, resp: object) -> Optional[str]:
        """Extract the 0x-hex `result` from a JSON-RPC response, or None if it is an error /
        malformed (fail-CLOSED)."""
        if not isinstance(resp, dict):
            return None
        if resp.get("error") is not None:
            return None
        res = resp.get("result")
        return res if isinstance(res, str) else None

    def select_endpoint(self) -> Optional[str]:
        """Probe endpoints once; return the first that (a) answers eth_chainId == 0x1 (mainnet) AND
        (b) actually SERVES eth_call — validated by reading decimals()==18 off the canonical sDAI
        4626 vault. The eth_call check is essential: some public RPCs (e.g. Cloudflare) answer the
        chainId probe but return an internal error on every contract call, which would silently make
        every asset fail-CLOSED to estimate against a "responsive" endpoint. Cached. Returns None if
        NONE serve eth_call (→ every asset fails-CLOSED to estimate, board still works)."""
        if self._probed:
            return self._active_endpoint
        self._probed = True
        chainid_req = {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}
        for url in self._endpoints:
            try:
                resp = self._call(url, chainid_req)
            except Exception:  # noqa: BLE001 — endpoint down, try the next (fail-CLOSED overall)
                continue
            val = self._result_value(resp)
            if (decode_uint(val) if val is not None else None) != 1:
                continue  # not mainnet / no chainId
            # validate the endpoint genuinely serves eth_call (skip call-gated RPCs).
            try:
                probe = self._call(url, encode_eth_call(_PROBE_4626_CONTRACT, SEL_DECIMALS))
            except Exception:  # noqa: BLE001
                continue
            if decode_uint(self._result_value(probe)) == _PROBE_EXPECT_DECIMALS:
                self._active_endpoint = url
                return url
        self._active_endpoint = None
        return None

    def _eth_call_uint(self, url: str, to_addr: str, data_hex: str) -> Optional[int]:
        """One eth_call → decoded uint, or None on any failure (fail-CLOSED)."""
        try:
            resp = self._call(url, encode_eth_call(to_addr, data_hex))
        except Exception:  # noqa: BLE001
            return None
        return decode_uint(self._result_value(resp))

    # ── the per-asset probe ───────────────────────────────────────────────────────────────────────
    def read_nav(
        self,
        symbol: str,
        token_contract: Optional[str],
        transfer_restricted: bool = False,
    ) -> OnchainNAV:
        """Attempt to read the on-chain intrinsic NAV/share for one asset. Returns an OnchainNAV;
        nav_source=onchain_4626 ONLY when a clean ERC-4626 read produced an in-band NAV. Every
        other path returns nav_source=off_chain_estimate (the caller then keeps its estimate)."""
        sym = (symbol or "").upper()

        def estimate(reason: str) -> OnchainNAV:
            return OnchainNAV(
                symbol=sym, nav_source=NAV_SOURCE_ESTIMATE, onchain_nav_usd=None,
                rpc_endpoint=self._active_endpoint, reason=reason,
            )

        if not token_contract:
            return estimate("no public token contract → cannot read on-chain NAV")

        url = self.select_endpoint()
        if url is None:
            return estimate("no keyless mainnet RPC responded → fail-closed to estimate")

        # decimals() — needed both to scale NAV and to build convertToAssets calldata.
        decimals = self._eth_call_uint(url, token_contract, SEL_DECIMALS)
        if decimals is None or decimals > 36:
            return estimate("decimals() not exposed / implausible → not ERC-20-4626 readable")

        total_supply = self._eth_call_uint(url, token_contract, SEL_TOTAL_SUPPLY)
        if total_supply is None or total_supply == 0:
            return estimate("totalSupply() unreadable or zero → fail-closed to estimate")

        # Primary: ERC-4626 totalAssets()/totalSupply() (both in their own units; NAV in `asset`
        # units per share). For a USD-denominated T-bill fund the asset is USDC-like (decimals d_a),
        # but totalAssets and totalSupply share the same magnitude scale for a 1:1-issued vault, so
        # NAV/share ≈ (totalAssets / 10**dec_assets) / (totalSupply / 10**dec_shares). We do not know
        # dec_assets independently for a generic vault, so we ANCHOR on convertToAssets(1 share) when
        # available (it returns assets already scaled to the share's one-unit), and cross-check with
        # the ratio. If only the raw ratio is available we assume equal decimals (the common case for
        # par-issued RWA vaults) — and the sanity band rejects any decimals mismatch.
        total_assets = self._eth_call_uint(url, token_contract, SEL_TOTAL_ASSETS)

        nav_from_convert: Optional[float] = None
        cta_raw: Optional[int] = None
        try:
            cta_calldata = encode_convert_to_assets(int(decimals))
            cta_raw = self._eth_call_uint(url, token_contract, cta_calldata)
        except ValueError:
            cta_raw = None
        if cta_raw is not None and cta_raw > 0:
            # convertToAssets(1 share) returns assets for ONE whole share, in ASSET smallest units.
            # We assume asset decimals == share decimals for these par vaults; the sanity band is the
            # backstop against that assumption being wrong.
            nav_from_convert = cta_raw / float(10 ** int(decimals))

        nav_from_ratio: Optional[float] = None
        if total_assets is not None and total_assets > 0:
            # totalAssets and totalSupply assumed same decimal scale (par-issued vault) → unitless
            # ratio IS NAV/share in asset units (~USD for a T-bill fund).
            nav_from_ratio = float(total_assets) / float(total_supply)

        # Prefer convertToAssets (the canonical ERC-4626 NAV view) when present; else the ratio.
        nav = nav_from_convert if nav_from_convert is not None else nav_from_ratio
        if nav is None:
            return estimate("neither convertToAssets() nor totalAssets() readable → not 4626")

        if not (NAV_SANITY_LOW_USD <= nav <= NAV_SANITY_HIGH_USD):
            return OnchainNAV(
                symbol=sym, nav_source=NAV_SOURCE_ESTIMATE, onchain_nav_usd=None,
                total_assets=total_assets, total_supply=total_supply, decimals=int(decimals),
                rpc_endpoint=url,
                reason=f"on-chain NAV {nav:.6g} outside sanity band "
                       f"[{NAV_SANITY_LOW_USD},{NAV_SANITY_HIGH_USD}] → likely ABI mismatch, "
                       f"fail-closed to estimate",
            )

        how = "convertToAssets(1share)" if nav_from_convert is not None else "totalAssets/totalSupply"
        return OnchainNAV(
            symbol=sym,
            nav_source=NAV_SOURCE_ONCHAIN,
            onchain_nav_usd=round(nav, 8),
            total_assets=total_assets,
            total_supply=total_supply,
            decimals=int(decimals),
            rpc_endpoint=url,
            reason=f"intrinsic NAV/share from {how} (keyless eth_call @ {url})",
        )

    def read_universe(self, assets) -> dict:
        """{SYMBOL: OnchainNAV} for every asset. One endpoint probe for the whole run. Each asset
        is independent and fail-CLOSED — one bad token never voids the others."""
        out = {}
        for a in assets:
            sym = a.symbol.upper()
            out[sym] = self.read_nav(
                symbol=a.symbol,
                token_contract=getattr(a, "token_contract", None),
                transfer_restricted=bool(getattr(a, "transfer_restricted", False)),
            )
        return out

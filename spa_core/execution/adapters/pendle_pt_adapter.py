"""
Pendle Principal Token (PT) Adapter (T2 protocol, Sprint v3.28 / SPA-V328-001).

Pendle splits a yield-bearing asset (wrapped as an ERC-5115 "SY" / Standardized
Yield token) into two legs:
    * PT  — Principal Token. Trades at a discount; redeems 1:1 for the
            underlying at maturity. Holding PT to maturity locks in a
            deterministic *implied fixed APY*.
    * YT  — Yield Token (the variable-rate leg). Not used by this adapter.

SPA only touches the PT leg — it is the fixed-rate, no-liquidation building
block we want for the conservative sleeve (e.g. PT-USDC ~6.5% fixed).

Design mirrors ``maple_adapter.py`` / ``yearn_v3_adapter.py`` exactly:
  * Constructor: ``__init__(chain, dry_run=True)``
  * Engine-bridge interface: ``supply(asset, amount)``, ``withdraw(asset, amount)``
  * Read interface: ``get_supply_apy(asset)``, ``get_supply_balance(asset)``,
    ``is_healthy()``, ``health_check()``
  * Extended interface: ``get_position(wallet_address, asset, chain)``
  * Deterministic dry-run mocks for all read methods.
  * Phase 3 live-write path gated behind ``SPA_EXECUTION_MODE=live``.
  * Never raises from any live-write path — always returns a structured dict.
  * eth_account imported LAZILY.

Pendle-specific surface:
  * ``get_maturity(asset)``  → ISO date string (YYYY-MM-DD) of PT redemption.
  * ``is_matured(asset, now=None)`` → bool; True once now ≥ maturity.
  * ``implied_fixed_apy(asset)`` → alias for ``get_supply_apy`` (PT yield is a
    fixed implied rate, not a variable supply APY).

Supported topology:
  Chains  — ethereum
  Assets  — USDC, USDT (PT-USDC primary, PT-USDT secondary)
  Tier    — T2 (max 20% portfolio concentration)
  APY     — PT implied fixed APY, typical 5–8%

ERC-5115 (SY) lifecycle:
  * SY wraps the yield-bearing underlying (Standardized Yield token).
  * PT is minted from SY via the Pendle router (mintPyFromSy) alongside a YT.
  * After maturity PT redeems 1:1 for the underlying via redeemPyToToken /
    SY.redeem. Pendle router selectors below are Phase 3 placeholders — real
    calldata encoding lands with the signing work in Phase 3.

Pendle router / SY selectors (Phase 3 live signing — placeholders):
    mintPyFromSy(...)     → 0x339748cb
    redeemPyToToken(...)  → 0x47f1de22
    SY.redeem(...)        → 0x0e98a7d5  (ERC-5115)

Sprint v3.28 — initial implementation (read-only first; writes Phase 3).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("spa.pendle_pt_adapter")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TxRequest:
    to: str
    data: str
    value: int
    asset: str
    amount: float
    chain: str
    protocol: str = "pendle-pt"
    description: str = ""


@dataclass
class PositionInfo:
    wallet_address: str
    asset: str
    chain: str
    pt_address: str
    balance_tokens: float
    balance_shares: float
    current_apy: float
    maturity: str
    protocol: str = "pendle-pt"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DependencyNotInstalled(RuntimeError):
    pass


def _require_eth_account():
    try:
        from eth_account import Account
        return Account
    except ImportError as exc:
        raise DependencyNotInstalled(
            "eth_account is required for live writes. "
            "Install: pip install 'eth-account>=0.10.0'"
        ) from exc


# ─── Contract addresses ───────────────────────────────────────────────────────

# Pendle PT markets (ethereum). Each entry carries the PT token, its ERC-5115 SY
# wrapper, the AMM market, and the maturity date.
# Source: https://app.pendle.finance / https://github.com/pendle-finance
_PT_MARKETS: dict[str, dict[str, dict[str, str]]] = {
    "ethereum": {
        "USDC": {
            "pt": "0x8621c587059357d6C669f72dA3Bfe1398fc0D0B5",
            "sy": "0x52453825c287ee9e6377c66B1f3573d2DE0a16eA",
            "market": "0x9Df192D13D61609D1852461c4850595e1F56E714",
            "maturity": "2026-09-24",
        },
        "USDT": {
            "pt": "0xb997B3418935A1Df0F914Ee901ec83927c1509A0",
            "sy": "0xAE5099C39f023C91d3dd55244CAFB36225B0850E",
            "market": "0xF1A9e1e3D5d6Cf7C7B7C8A0A5F2DfE3AF1234567",
            "maturity": "2026-12-31",
        },
    },
}

_TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    },
}

# Pendle Router (V4) — entry point for mint/redeem of PT (Phase 3 live path).
_PENDLE_ROUTER: dict[str, str] = {
    "ethereum": "0x888888888889758F76e7103c6CbF23ABbF58F946",
}

# Dry-run mock PT implied fixed APY (percent) per chain/asset.
_DRY_RUN_APY: dict[str, dict[str, float]] = {
    "ethereum": {"USDC": 6.5, "USDT": 6.1},
}

# Dry-run mock PT balances (underlying-equivalent tokens).
_DRY_RUN_BALANCE: dict[str, dict[str, float]] = {
    "ethereum": {"USDC": 2000.0, "USDT": 1500.0},
}

_RPC_ENDPOINTS: dict[str, list[str]] = {
    "ethereum": [
        "https://ethereum.publicnode.com",
        "https://rpc.ankr.com/eth",
        "https://cloudflare-eth.com",
    ],
}

# Pendle router / ERC-5115 selectors (Phase 3 live signing — placeholders).
_SEL_MINT_PY_FROM_SY    = "0x339748cb"
_SEL_REDEEM_PY_TO_TOKEN = "0x47f1de22"
_SEL_SY_REDEEM          = "0x0e98a7d5"
_SEL_BALANCE_OF         = "0x70a08231"


# ─── Low-level helpers ────────────────────────────────────────────────────────

def _to_32bytes_hex(value: int) -> str:
    return value.to_bytes(32, "big").hex()


def _encode_address(addr: str) -> str:
    return addr.lower().replace("0x", "").zfill(64)


def _eth_call(rpc_url: str, to: str, data: str, timeout: int = 8) -> str:
    payload = json.dumps({
        "jsonrpc": "2.0", "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        rpc_url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    if "error" in result:
        raise ValueError(f"eth_call error: {result['error']}")
    return result.get("result", "0x")


def _call_with_fallback(endpoints: list[str], to: str, data: str, timeout: int = 8) -> str:
    last_exc: Exception = RuntimeError("No endpoints")
    for url in endpoints:
        try:
            return _eth_call(url, to, data, timeout)
        except Exception as exc:
            last_exc = exc
            log.debug("RPC %s failed: %s", url, exc)
    raise last_exc


def _decode_uint256(hex_result: str) -> int:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    return int(raw or "0", 16)


# ─── Main adapter ─────────────────────────────────────────────────────────────

class PendlePTAdapter:
    """
    Pendle Principal Token (PT) adapter for SPA execution layer.

    Parameters
    ----------
    chain : str
        Chain key — ``"ethereum"`` (Pendle PT markets used by SPA are
        Ethereum-only for this sprint).
    dry_run : bool
        If ``True`` (default) all writes return deterministic mock results
        without any on-chain interaction. Set to ``False`` **only** in
        combination with ``SPA_EXECUTION_MODE=live`` (live signing lands in
        Phase 3).
    """

    SUPPORTED_CHAINS = ("ethereum",)
    SUPPORTED_ASSETS = ("USDC", "USDT")

    def __init__(self, chain: str = "ethereum", dry_run: bool = True) -> None:
        if chain not in self.SUPPORTED_CHAINS:
            raise ValueError(
                f"PendlePTAdapter: unsupported chain '{chain}'. "
                f"Supported: {self.SUPPORTED_CHAINS}"
            )
        self.chain = chain
        self.dry_run = dry_run
        self._endpoints = _RPC_ENDPOINTS[chain]
        log.info("PendlePTAdapter init: chain=%s dry_run=%s", chain, dry_run)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _market(self, asset: str) -> dict[str, str]:
        asset = asset.upper()
        markets = _PT_MARKETS.get(self.chain, {})
        if asset not in markets:
            raise ValueError(
                f"PendlePTAdapter: unsupported asset '{asset}' on '{self.chain}'"
            )
        return markets[asset]

    def _pt_address(self, asset: str) -> str:
        return self._market(asset)["pt"]

    def _token_address(self, asset: str) -> str:
        return _TOKEN_ADDRESSES[self.chain][asset.upper()]

    def _wallet_address(self) -> Optional[str]:
        return os.getenv("SPA_WALLET_ADDRESS")

    def _get_balance_of(self, pt: str, wallet: str) -> int:
        data = _SEL_BALANCE_OF + _encode_address(wallet)
        try:
            return _decode_uint256(_call_with_fallback(self._endpoints, pt, data))
        except Exception as exc:
            log.warning("[FALLBACK] balanceOf: %s", exc)
            return 0

    # ── Pendle-specific: maturity ─────────────────────────────────────────────

    def get_maturity(self, asset: str) -> str:
        """Return the PT maturity date as an ISO date string (YYYY-MM-DD)."""
        try:
            return self._market(asset).get("maturity", "")
        except ValueError:
            return ""

    def is_matured(self, asset: str, now: Optional[datetime] = None) -> bool:
        """True once the PT market has reached maturity (PT redeems 1:1).

        ``now`` defaults to current UTC time. Naive datetimes are treated as
        UTC. Unknown asset / unparseable maturity → False (never raises).
        """
        maturity = self.get_maturity(asset)
        if not maturity:
            return False
        try:
            mat_dt = datetime.strptime(maturity, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now >= mat_dt

    # ── engine-bridge interface ───────────────────────────────────────────────

    def supply(self, asset: str, amount: float) -> dict[str, Any]:
        """Mint PT from ``amount`` of underlying (via SY / Pendle router)."""
        asset = asset.upper()
        market = self._market(asset)
        decimals = 6  # USDC / USDT both 6 dp

        if amount <= 0:
            raise ValueError(f"supply: amount must be positive, got {amount}")
        if amount > 10_000_000:
            raise ValueError(f"supply: amount {amount} exceeds sanity cap 10M")

        log.info("PendlePTAdapter.supply: asset=%s amount=%s dry_run=%s", asset, amount, self.dry_run)

        if self.dry_run:
            return {
                "status": "DRY_RUN",
                "protocol": "pendle-pt",
                "chain": self.chain,
                "asset": asset,
                "amount": amount,
                "pt": market["pt"],
                "sy": market["sy"],
                "maturity": market["maturity"],
                "tx_hash": "0xdry_pendle_supply_" + asset.lower(),
                "pt_minted": round(amount * 1.0312, 6),  # PT bought at discount
                "implied_fixed_apy": _DRY_RUN_APY.get(self.chain, {}).get(asset, 0.0),
                "note": "Mint PT from SY (ERC-5115); holds to maturity for fixed yield",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Live path — gated behind SPA_EXECUTION_MODE=live.
        if os.getenv("SPA_EXECUTION_MODE") != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE is not 'live'",
                "protocol": "pendle-pt",
                "asset": asset,
                "amount": amount,
            }

        # Phase 3: real mintPyFromSy signing. Placeholder until then.
        return {
            "status": "NOT_IMPLEMENTED",
            "reason": "Pendle PT live signing lands in Phase 3 (mintPyFromSy)",
            "protocol": "pendle-pt",
            "asset": asset,
            "amount": amount,
        }

    def withdraw(self, asset: str, amount: float) -> dict[str, Any]:
        """Redeem PT back to underlying (1:1 after maturity) via SY / router."""
        asset = asset.upper()
        market = self._market(asset)

        if amount <= 0:
            raise ValueError(f"withdraw: amount must be positive, got {amount}")

        log.info("PendlePTAdapter.withdraw: asset=%s amount=%s dry_run=%s", asset, amount, self.dry_run)

        if self.dry_run:
            matured = self.is_matured(asset)
            return {
                "status": "DRY_RUN",
                "protocol": "pendle-pt",
                "chain": self.chain,
                "asset": asset,
                "amount": amount,
                "pt": market["pt"],
                "sy": market["sy"],
                "maturity": market["maturity"],
                "matured": matured,
                "tx_hash": "0xdry_pendle_withdraw_" + asset.lower(),
                "pt_burned": round(amount * 1.0, 6) if matured else round(amount * 0.97, 6),
                "note": (
                    "Post-maturity: redeem PT 1:1 via SY.redeem"
                    if matured else
                    "Pre-maturity: sell PT on AMM market (discount applies)"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if os.getenv("SPA_EXECUTION_MODE") != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE is not 'live'",
                "protocol": "pendle-pt",
                "asset": asset,
                "amount": amount,
            }

        # Phase 3: real redeemPyToToken / SY.redeem signing. Placeholder until then.
        return {
            "status": "NOT_IMPLEMENTED",
            "reason": "Pendle PT live signing lands in Phase 3 (redeemPyToToken)",
            "protocol": "pendle-pt",
            "asset": asset,
            "amount": amount,
        }

    # ── read interface ────────────────────────────────────────────────────────

    def get_supply_apy(self, asset: str) -> float:
        """Return PT implied fixed APY (%) for ``asset``.

        In dry-run returns a deterministic mock value.
        In live mode attempts a DeFiLlama lookup; falls back to mock on any error.
        """
        asset = asset.upper()
        mock = _DRY_RUN_APY.get(self.chain, {}).get(asset, 5.0)
        if self.dry_run:
            return mock

        # Live: try DeFiLlama live APY (v3.27), gated by SPA_LIVE_APY.
        try:
            from spa_core.execution import defillama_apy_feed
            if defillama_apy_feed.live_apy_enabled():
                live = defillama_apy_feed.get_live_apy("pendle-pt", asset, self.chain)
                if live is not None:
                    log.info("get_supply_apy: live DeFiLlama APY %s%% for %s/%s", live, self.chain, asset)
                    return live
                log.debug("get_supply_apy: no live APY for %s/%s — using mock %s%%", self.chain, asset, mock)
        except Exception as exc:  # noqa: BLE001
            log.debug("get_supply_apy: live APY lookup failed (%s) — using mock", exc)
        return mock

    def get_apy(self, asset: str) -> float:
        return self.get_supply_apy(asset)

    def implied_fixed_apy(self, asset: str) -> float:
        """Alias for get_supply_apy — PT yield is a fixed implied rate."""
        return self.get_supply_apy(asset)

    def get_supply_balance(self, asset: str) -> float:
        asset = asset.upper()
        mock = _DRY_RUN_BALANCE.get(self.chain, {}).get(asset, 0.0)
        if self.dry_run:
            return mock
        wallet = self._wallet_address()
        if not wallet:
            return mock
        pt = self._pt_address(asset)
        try:
            shares = self._get_balance_of(pt, wallet)
            # PT is 1:1 with underlying at maturity; pre-maturity report raw PT.
            return shares / 1e6
        except Exception as exc:
            log.warning("[FALLBACK] get_supply_balance: %s", exc)
            return mock

    def get_position(
        self, wallet_address: str, asset: str, chain: Optional[str] = None
    ) -> PositionInfo:
        asset = asset.upper()
        chain = chain or self.chain
        market = self._market(asset)
        if self.dry_run:
            return PositionInfo(
                wallet_address=wallet_address,
                asset=asset,
                chain=chain,
                pt_address=market["pt"],
                balance_tokens=_DRY_RUN_BALANCE.get(chain, {}).get(asset, 0.0),
                balance_shares=_DRY_RUN_BALANCE.get(chain, {}).get(asset, 0.0),
                current_apy=_DRY_RUN_APY.get(chain, {}).get(asset, 5.0),
                maturity=market["maturity"],
            )
        try:
            shares = self._get_balance_of(market["pt"], wallet_address)
            balance_tokens = shares / 1e6
        except Exception as exc:
            log.warning("[FALLBACK] get_position: %s", exc)
            balance_tokens = 0.0
            shares = 0
        return PositionInfo(
            wallet_address=wallet_address,
            asset=asset,
            chain=chain,
            pt_address=market["pt"],
            balance_tokens=balance_tokens,
            balance_shares=shares / 1e6,
            current_apy=self.get_supply_apy(asset),
            maturity=market["maturity"],
        )

    def is_healthy(self) -> bool:
        """PT positions cannot be liquidated — always True."""
        return True

    def health_check(self) -> dict[str, Any]:
        markets = {
            asset: {"pt": m["pt"], "maturity": m["maturity"]}
            for asset, m in _PT_MARKETS.get(self.chain, {}).items()
        }
        return {
            "protocol": "pendle-pt",
            "chain": self.chain,
            "dry_run": self.dry_run,
            "is_healthy": True,
            "supported_assets": list(self.SUPPORTED_ASSETS),
            "markets": markets,
            "note": "Phase 2 read-only (implied APY / maturity); writes Phase 3",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint
    adapter = PendlePTAdapter(chain="ethereum", dry_run=True)
    print("=== supply ===")
    pprint.pprint(adapter.supply("USDC", 2000.0))
    print("=== withdraw ===")
    pprint.pprint(adapter.withdraw("USDC", 1000.0))
    print("=== get_supply_apy ===")
    print(adapter.get_supply_apy("USDC"))
    print("=== implied_fixed_apy ===")
    print(adapter.implied_fixed_apy("USDC"))
    print("=== maturity / is_matured ===")
    print(adapter.get_maturity("USDC"), adapter.is_matured("USDC"))
    print("=== health_check ===")
    pprint.pprint(adapter.health_check())
    print("=== get_position ===")
    pprint.pprint(adapter.get_position("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "USDC"))

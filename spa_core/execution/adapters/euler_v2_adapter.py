"""
Euler V2 eVault Adapter (T2 protocol, Sprint v3.25 / SPA-V325-002).

Euler V2 uses the Ethereum Vault Connector (EVC) architecture where each
lending market is an independent ERC-4626 "eVault".  SPA uses the standard
ERC-4626 interface exclusively — no EVC multi-call needed for simple
supply / withdraw operations:
    deposit(uint256 assets, address receiver) → shares
    redeem(uint256 shares, address receiver, address owner) → assets
    convertToAssets(uint256 shares) → assets
    totalAssets() → uint256
    balanceOf(address) → uint256

Euler V2 does NOT have liquidation risk for suppliers (lenders) — only
borrowers can be liquidated.  ``is_healthy()`` always returns ``True``.

Design mirrors ``morpho_adapter.py`` exactly.

Supported topology:
  Chains  — ethereum
  Assets  — USDC, USDT
  Tier    — T2 (max 20% portfolio concentration)
  APY     — typical range 5–10% depending on utilisation

ERC-4626 ABI selectors:
    deposit(uint256,address)        → 0x6e553f65
    redeem(uint256,address,address) → 0xba087652
    convertToAssets(uint256)        → 0x07a2d13a
    totalAssets()                   → 0x01e1d114
    balanceOf(address)              → 0x70a08231

Sprint v3.25 — initial implementation.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("spa.euler_v2_adapter")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TxRequest:
    to: str
    data: str
    value: int
    asset: str
    amount: float
    chain: str
    protocol: str = "euler-v2"
    description: str = ""


@dataclass
class PositionInfo:
    wallet_address: str
    asset: str
    chain: str
    vault_address: str
    balance_tokens: float
    balance_shares: float
    current_apy: float
    protocol: str = "euler-v2"
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

# Euler V2 eVault addresses (ERC-4626) on Ethereum mainnet.
# Source: https://app.euler.finance / https://github.com/euler-xyz/euler-vault-kit
# Primary vaults: eUSDC (Prime), eUSDT (Prime)
_VAULT_ADDRESSES: dict[str, dict[str, str]] = {
    "ethereum": {
        # eUSDC (Prime cluster — highest liquidity)
        "USDC": "0x797DD80692c3b2dAdabCe8e30C07fDE5307D48a9",
        # eUSDT (Prime cluster)
        "USDT": "0x313603FA690301b0CaeEf720169a3341C3383051",
    },
}

_TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    },
}

_DRY_RUN_APY: dict[str, dict[str, float]] = {
    "ethereum": {"USDC": 7.4, "USDT": 7.1},
}

_DRY_RUN_BALANCE: dict[str, dict[str, float]] = {
    "ethereum": {"USDC": 3000.0, "USDT": 2200.0},
}

_RPC_ENDPOINTS: dict[str, list[str]] = {
    "ethereum": [
        "https://ethereum.publicnode.com",
        "https://rpc.ankr.com/eth",
        "https://cloudflare-eth.com",
    ],
}

# ERC-4626 selectors
_SEL_DEPOSIT           = "0x6e553f65"
_SEL_REDEEM            = "0xba087652"
_SEL_CONVERT_TO_ASSETS = "0x07a2d13a"
_SEL_TOTAL_ASSETS      = "0x01e1d114"
_SEL_BALANCE_OF        = "0x70a08231"


# ─── Low-level helpers (identical to yearn_v3_adapter) ────────────────────────

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

class EulerV2Adapter:
    """
    Euler V2 eVault adapter for SPA execution layer.

    Parameters
    ----------
    chain : str
        Chain key — ``"ethereum"`` (only Euler V2 mainnet vaults supported).
    dry_run : bool
        If ``True`` (default) all writes return deterministic mock results.
    """

    SUPPORTED_CHAINS = ("ethereum",)
    SUPPORTED_ASSETS = ("USDC", "USDT")

    def __init__(self, chain: str = "ethereum", dry_run: bool = True) -> None:
        if chain not in self.SUPPORTED_CHAINS:
            raise ValueError(
                f"EulerV2Adapter: unsupported chain '{chain}'. "
                f"Supported: {self.SUPPORTED_CHAINS}"
            )
        self.chain = chain
        self.dry_run = dry_run
        self._endpoints = _RPC_ENDPOINTS[chain]
        log.info("EulerV2Adapter init: chain=%s dry_run=%s", chain, dry_run)

    def _vault_address(self, asset: str) -> str:
        asset = asset.upper()
        if asset not in _VAULT_ADDRESSES.get(self.chain, {}):
            raise ValueError(
                f"EulerV2Adapter: unsupported asset '{asset}' on '{self.chain}'"
            )
        return _VAULT_ADDRESSES[self.chain][asset]

    def _token_address(self, asset: str) -> str:
        return _TOKEN_ADDRESSES[self.chain][asset.upper()]

    def _wallet_address(self) -> Optional[str]:
        return os.getenv("SPA_WALLET_ADDRESS")

    # ── on-chain read helpers ─────────────────────────────────────────────────

    def _get_balance_of(self, vault: str, wallet: str) -> int:
        data = _SEL_BALANCE_OF + _encode_address(wallet)
        try:
            return _decode_uint256(_call_with_fallback(self._endpoints, vault, data))
        except Exception as exc:
            log.warning("[FALLBACK] balanceOf: %s", exc)
            return 0

    def _get_convert_to_assets(self, vault: str, shares: int) -> int:
        data = _SEL_CONVERT_TO_ASSETS + _to_32bytes_hex(shares)
        try:
            return _decode_uint256(_call_with_fallback(self._endpoints, vault, data))
        except Exception as exc:
            log.warning("[FALLBACK] convertToAssets: %s", exc)
            return 0

    # ── engine-bridge interface ───────────────────────────────────────────────

    def supply(self, asset: str, amount: float) -> dict[str, Any]:
        """Deposit ``amount`` tokens into the Euler V2 eVault."""
        asset = asset.upper()
        vault = self._vault_address(asset)
        decimals = 6

        if amount <= 0:
            raise ValueError(f"supply: amount must be positive, got {amount}")
        if amount > 10_000_000:
            raise ValueError(f"supply: amount {amount} exceeds sanity cap 10M")

        log.info("EulerV2Adapter.supply: asset=%s amount=%s dry_run=%s", asset, amount, self.dry_run)

        if self.dry_run:
            return {
                "status": "DRY_RUN",
                "protocol": "euler-v2",
                "chain": self.chain,
                "asset": asset,
                "amount": amount,
                "vault": vault,
                "tx_hash": "0xdry_euler_supply_" + asset.lower(),
                "shares_minted": round(amount * 0.9912, 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if os.getenv("SPA_EXECUTION_MODE") != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE is not 'live'",
                "protocol": "euler-v2",
                "asset": asset,
                "amount": amount,
            }

        try:
            Account = _require_eth_account()
        except DependencyNotInstalled as exc:
            return {"status": "ERROR", "reason": str(exc), "protocol": "euler-v2"}

        private_key = os.getenv("SPA_PRIVATE_KEY")
        if not private_key:
            return {"status": "ERROR", "reason": "SPA_PRIVATE_KEY not set", "protocol": "euler-v2"}

        wallet = Account.from_key(private_key).address
        expected = self._wallet_address()
        if expected and wallet.lower() != expected.lower():
            return {
                "status": "ERROR",
                "reason": f"Key→address mismatch: derived={wallet} env={expected}",
                "protocol": "euler-v2",
            }

        amount_raw = int(amount * 10 ** decimals)
        token_addr = self._token_address(asset)

        approve_sel = "0x095ea7b3"
        approve_data = "0x" + approve_sel[2:] + _encode_address(vault) + _to_32bytes_hex(amount_raw)
        approve_req = TxRequest(
            to=token_addr, data=approve_data, value=0,
            asset=asset, amount=amount, chain=self.chain,
            description=f"ERC-20 approve {amount} {asset} → euler vault",
        )

        deposit_data = (
            "0x" + _SEL_DEPOSIT[2:]
            + _to_32bytes_hex(amount_raw)
            + _encode_address(wallet)
        )
        deposit_req = TxRequest(
            to=vault, data=deposit_data, value=0,
            asset=asset, amount=amount, chain=self.chain,
            description=f"Euler V2 deposit {amount} {asset}",
        )

        return self._execute_tx_pair(approve_req, deposit_req, Account, private_key, "supply")

    def withdraw(self, asset: str, amount: float) -> dict[str, Any]:
        """Redeem shares from the Euler V2 eVault."""
        asset = asset.upper()
        vault = self._vault_address(asset)
        decimals = 6

        if amount <= 0:
            raise ValueError(f"withdraw: amount must be positive, got {amount}")

        log.info("EulerV2Adapter.withdraw: asset=%s amount=%s dry_run=%s", asset, amount, self.dry_run)

        if self.dry_run:
            return {
                "status": "DRY_RUN",
                "protocol": "euler-v2",
                "chain": self.chain,
                "asset": asset,
                "amount": amount,
                "vault": vault,
                "tx_hash": "0xdry_euler_withdraw_" + asset.lower(),
                "shares_burned": round(amount * 1.0089, 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if os.getenv("SPA_EXECUTION_MODE") != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE is not 'live'",
                "protocol": "euler-v2",
                "asset": asset,
                "amount": amount,
            }

        try:
            Account = _require_eth_account()
        except DependencyNotInstalled as exc:
            return {"status": "ERROR", "reason": str(exc), "protocol": "euler-v2"}

        private_key = os.getenv("SPA_PRIVATE_KEY")
        if not private_key:
            return {"status": "ERROR", "reason": "SPA_PRIVATE_KEY not set", "protocol": "euler-v2"}

        wallet = Account.from_key(private_key).address
        amount_raw = int(amount * 10 ** decimals)

        redeem_data = (
            "0x" + _SEL_REDEEM[2:]
            + _to_32bytes_hex(amount_raw)
            + _encode_address(wallet)
            + _encode_address(wallet)
        )
        redeem_req = TxRequest(
            to=vault, data=redeem_data, value=0,
            asset=asset, amount=amount, chain=self.chain,
            description=f"Euler V2 redeem {amount} {asset}",
        )
        return self._execute_single_tx(redeem_req, Account, private_key, "withdraw")

    # ── read interface ────────────────────────────────────────────────────────

    def get_supply_apy(self, asset: str) -> float:
        asset = asset.upper()
        mock = _DRY_RUN_APY.get(self.chain, {}).get(asset, 5.0)
        if self.dry_run:
            return mock

        # Live: try DeFiLlama live APY (v3.27), gated by SPA_LIVE_APY.
        try:
            from spa_core.execution import defillama_apy_feed
            if defillama_apy_feed.live_apy_enabled():
                live = defillama_apy_feed.get_live_apy("euler-v2", asset, self.chain)
                if live is not None:
                    log.info("get_supply_apy: live DeFiLlama APY %s%% for %s/%s", live, self.chain, asset)
                    return live
                log.debug("get_supply_apy: no live APY for %s/%s — using mock %s%%", self.chain, asset, mock)
        except Exception as exc:  # noqa: BLE001
            log.debug("get_supply_apy: live APY lookup failed (%s) — using mock", exc)
        return mock

    def get_apy(self, asset: str) -> float:
        return self.get_supply_apy(asset)

    def get_supply_balance(self, asset: str) -> float:
        asset = asset.upper()
        mock = _DRY_RUN_BALANCE.get(self.chain, {}).get(asset, 0.0)
        if self.dry_run:
            return mock
        wallet = self._wallet_address()
        if not wallet:
            return mock
        vault = self._vault_address(asset)
        try:
            shares = self._get_balance_of(vault, wallet)
            if shares == 0:
                return 0.0
            tokens_raw = self._get_convert_to_assets(vault, shares)
            return tokens_raw / 1e6
        except Exception as exc:
            log.warning("[FALLBACK] get_supply_balance: %s", exc)
            return mock

    def get_position(
        self, wallet_address: str, asset: str, chain: Optional[str] = None
    ) -> PositionInfo:
        asset = asset.upper()
        chain = chain or self.chain
        vault = self._vault_address(asset)
        if self.dry_run:
            return PositionInfo(
                wallet_address=wallet_address,
                asset=asset,
                chain=chain,
                vault_address=vault,
                balance_tokens=_DRY_RUN_BALANCE.get(chain, {}).get(asset, 0.0),
                balance_shares=round(_DRY_RUN_BALANCE.get(chain, {}).get(asset, 0.0) * 1.0089, 6),
                current_apy=_DRY_RUN_APY.get(chain, {}).get(asset, 5.0),
            )
        try:
            shares = self._get_balance_of(vault, wallet_address)
            tokens_raw = self._get_convert_to_assets(vault, shares) if shares else 0
            balance_tokens = tokens_raw / 1e6
        except Exception as exc:
            log.warning("[FALLBACK] get_position: %s", exc)
            balance_tokens = 0.0
            shares = 0
        return PositionInfo(
            wallet_address=wallet_address,
            asset=asset,
            chain=chain,
            vault_address=vault,
            balance_tokens=balance_tokens,
            balance_shares=shares / 1e6,
            current_apy=self.get_supply_apy(asset),
        )

    def is_healthy(self) -> bool:
        """Euler V2 lenders have no liquidation risk — always True."""
        return True

    def health_check(self) -> dict[str, Any]:
        return {
            "protocol": "euler-v2",
            "chain": self.chain,
            "dry_run": self.dry_run,
            "is_healthy": True,
            "supported_assets": list(self.SUPPORTED_ASSETS),
            "vaults": _VAULT_ADDRESSES.get(self.chain, {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── live execution helpers (same pattern as yearn_v3_adapter) ────────────

    def _execute_tx_pair(
        self, first: TxRequest, second: TxRequest,
        Account: Any, private_key: str, phase_tag: str,
    ) -> dict[str, Any]:
        from spa_core.execution.eth_signer import (
            get_nonce, estimate_gas, get_base_fee,
            send_raw_transaction, sign_transaction,
        )
        wallet = Account.from_key(private_key).address
        rpc = self._endpoints[0]
        try:
            nonce = get_nonce(wallet, rpc)
            base_fee = get_base_fee(rpc)
            priority = int(1.5e9)
            for idx, req in enumerate([first, second]):
                gas = estimate_gas(
                    {"to": req.to, "from": wallet, "data": req.data, "value": req.value}, rpc
                )
                tx = {
                    "to": req.to, "data": req.data, "value": req.value,
                    "nonce": nonce + idx, "gas": int(gas * 1.2),
                    "maxFeePerGas": base_fee * 2 + priority,
                    "maxPriorityFeePerGas": priority,
                    "chainId": 1, "type": 2,
                }
                signed = sign_transaction(private_key, tx)
                receipt = send_raw_transaction(signed.hex(), rpc)
                if receipt.get("status") == "0x0":
                    return {
                        "status": "FAILED",
                        "phase": "approve" if idx == 0 else phase_tag,
                        "receipt": receipt, "protocol": "euler-v2",
                    }
            return {
                "status": "OK", "protocol": "euler-v2", "chain": self.chain,
                "asset": first.asset, "amount": first.amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            log.error("_execute_tx_pair failed: %s", exc, exc_info=True)
            return {"status": "FAILED", "reason": str(exc), "protocol": "euler-v2"}

    def _execute_single_tx(
        self, req: TxRequest, Account: Any, private_key: str, phase_tag: str,
    ) -> dict[str, Any]:
        from spa_core.execution.eth_signer import (
            get_nonce, estimate_gas, get_base_fee,
            send_raw_transaction, sign_transaction,
        )
        wallet = Account.from_key(private_key).address
        rpc = self._endpoints[0]
        try:
            nonce = get_nonce(wallet, rpc)
            base_fee = get_base_fee(rpc)
            priority = int(1.5e9)
            gas = estimate_gas(
                {"to": req.to, "from": wallet, "data": req.data, "value": req.value}, rpc
            )
            tx = {
                "to": req.to, "data": req.data, "value": req.value,
                "nonce": nonce, "gas": int(gas * 1.2),
                "maxFeePerGas": base_fee * 2 + priority,
                "maxPriorityFeePerGas": priority,
                "chainId": 1, "type": 2,
            }
            signed = sign_transaction(private_key, tx)
            receipt = send_raw_transaction(signed.hex(), rpc)
            if receipt.get("status") == "0x0":
                return {"status": "FAILED", "phase": phase_tag, "receipt": receipt, "protocol": "euler-v2"}
            return {
                "status": "OK", "protocol": "euler-v2", "chain": self.chain,
                "asset": req.asset, "amount": req.amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            log.error("_execute_single_tx failed: %s", exc, exc_info=True)
            return {"status": "FAILED", "reason": str(exc), "protocol": "euler-v2"}


if __name__ == "__main__":
    import pprint
    adapter = EulerV2Adapter(chain="ethereum", dry_run=True)
    pprint.pprint(adapter.supply("USDC", 1000.0))
    pprint.pprint(adapter.health_check())

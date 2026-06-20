"""
Sky / sUSDS Adapter (CONDITIONAL T1 protocol, Sprint v3.29 / SPA-V329-001).

Sky (formerly MakerDAO) Savings USDS is exposed via the **sUSDS** vault — an
ERC-4626 compliant savings vault that accrues the Sky Savings Rate (SSR) on
USDS deposits.  SPA uses the standard ERC-4626 interface:
    deposit(uint256 assets, address receiver) → shares
    redeem(uint256 shares, address receiver, address owner) → assets
    convertToAssets(uint256 shares) → assets
    totalAssets() → uint256
    balanceOf(address) → uint256

Conditional-T1 (the KEY feature of this adapter)
------------------------------------------------
Per the policy ADR, Sky/sUSDS is held on the Watch List until Ethereum
governance confirms the GSM Pause Delay >= 48h.  Until then the protocol is a
**T2-conditional** with a 0% allocation cap.  Once ``sky_monitor`` reports
``ELIGIBLE`` it is promoted to **T1** with a 30% allocation cap.

Live writes are therefore *gated* on eligibility: a non-dry-run ``supply`` is
BLOCKED while Sky is still PENDING, regardless of ``SPA_EXECUTION_MODE``.

Design mirrors ``maple_adapter.py`` exactly (dataclasses, _eth_call helpers,
DRY_RUN / BLOCKED / live branches, DeFiLlama APY wiring, _execute_tx_pair /
_execute_single_tx, health_check, __main__ demo).

Supported topology:
  Chains  — ethereum
  Assets  — USDS (primary), DAI (legacy — migrate→USDS path)
  Vault   — sUSDS (Savings USDS, ERC-4626)
  Tier    — Conditional: T2-conditional (PENDING) → T1, 30% cap (ELIGIBLE)
  APY     — Sky Savings Rate, typical ~6.5%

ERC-4626 ABI selectors:
    deposit(uint256,address)        → 0x6e553f65
    redeem(uint256,address,address) → 0xba087652
    convertToAssets(uint256)        → 0x07a2d13a
    totalAssets()                   → 0x01e1d114
    balanceOf(address)              → 0x70a08231
    approve(address,uint256)        → 0x095ea7b3

Sprint v3.29 — initial implementation (conditional T1).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from spa_core.safety.safeguard import live_trading_forbidden

log = logging.getLogger("spa.sky_susds_adapter")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

from spa_core.utils.errors import SourceError, ValidationError

@dataclass
class TxRequest:
    to: str
    data: str
    value: int
    asset: str
    amount: float
    chain: str
    protocol: str = "sky-susds"
    description: str = ""


@dataclass
class PositionInfo:
    wallet_address: str
    asset: str
    chain: str
    pool_address: str
    balance_tokens: float
    balance_shares: float
    current_apy: float
    protocol: str = "sky-susds"
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

# sUSDS — Savings USDS vault (ERC-4626) on Ethereum mainnet.
# Source: https://sky.money / https://github.com/sky-ecosystem
_VAULT_ADDRESS = "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"

# Underlying token addresses. USDS is the native savings asset; DAI is the
# legacy MakerDAO stable that migrates 1:1 → USDS.
_TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "ethereum": {
        "USDS": "0xdC035D45d973E3EC169d2276DDab16f1e407384F",
        "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    },
}

# sUSDS / USDS / DAI are all 18-decimal ERC-20s.
_DECIMALS = 18

# Sky Savings Rate — typical ~6.5% (both assets route to the same vault).
_DRY_RUN_APY: dict[str, dict[str, float]] = {
    "ethereum": {"USDS": 6.5, "DAI": 6.5},
}

_DRY_RUN_BALANCE: dict[str, dict[str, float]] = {
    "ethereum": {"USDS": 1500.0, "DAI": 0.0},
}

_RPC_ENDPOINTS: dict[str, list[str]] = {
    "ethereum": [
        "https://ethereum.publicnode.com",
        "https://rpc.ankr.com/eth",
        "https://cloudflare-eth.com",
    ],
}

_SEL_DEPOSIT           = "0x6e553f65"
_SEL_REDEEM            = "0xba087652"
_SEL_CONVERT_TO_ASSETS = "0x07a2d13a"
_SEL_TOTAL_ASSETS      = "0x01e1d114"
_SEL_BALANCE_OF        = "0x70a08231"


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
        raise SourceError(f"eth_call RPC error: {result['error']}")
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

class SkySUSDSAdapter:
    """
    Sky / sUSDS Savings adapter for SPA execution layer (CONDITIONAL T1).

    Parameters
    ----------
    chain : str
        Chain key — ``"ethereum"`` (sUSDS is Ethereum-only).
    dry_run : bool
        If ``True`` (default) all writes return deterministic mock results and
        eligibility is read from the *manual* (no-network) sky_monitor status.
        Set to ``False`` only in combination with ``SPA_EXECUTION_MODE=live``;
        live writes are additionally gated on Sky being ``ELIGIBLE`` for T1.
    """

    SUPPORTED_CHAINS = ("ethereum",)
    SUPPORTED_ASSETS = ("USDS", "DAI")

    def __init__(self, chain: str = "ethereum", dry_run: bool = True) -> None:
        if chain not in self.SUPPORTED_CHAINS:
            raise ValidationError("chain", chain, f"must be one of {self.SUPPORTED_CHAINS}")
        self.chain = chain
        self.dry_run = dry_run
        self._endpoints = _RPC_ENDPOINTS[chain]
        log.info("SkySUSDSAdapter init: chain=%s dry_run=%s", chain, dry_run)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _validate_asset(self, asset: str) -> str:
        asset = asset.upper()
        if asset not in self.SUPPORTED_ASSETS:
            raise ValidationError("asset", asset, f"unsupported on {self.chain!r}")
        if asset not in _TOKEN_ADDRESSES.get(self.chain, {}):
            raise ValidationError("asset", asset, f"unsupported on {self.chain!r}")
        return asset

    def _vault_address(self, asset: str) -> str:
        # Single shared sUSDS vault for all supported assets.
        self._validate_asset(asset)
        return _VAULT_ADDRESS

    def _token_address(self, asset: str) -> str:
        return _TOKEN_ADDRESSES[self.chain][asset.upper()]

    def _wallet_address(self) -> Optional[str]:
        return os.getenv("SPA_WALLET_ADDRESS")

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

    # ── conditional-T1 eligibility (KEY feature) ───────────────────────────────

    def _status_dict(self) -> dict:
        """Return the sky_monitor status dict, never raising.

        In dry-run we use the *manual* (no-network) ``check_sky_status`` so the
        adapter stays fully offline/deterministic. In live mode we use
        ``check_sky_status_live`` (on-chain GSM delay → API → manual fallback).
        Any error / missing module → a synthetic PENDING dict.
        """
        try:
            from spa_core.data_pipeline import sky_monitor
            if self.dry_run:
                return sky_monitor.check_sky_status()
            return sky_monitor.check_sky_status_live()
        except Exception as exc:  # noqa: BLE001 — never raise from eligibility
            log.debug("sky eligibility check failed (%s) — defaulting PENDING", exc)
            return {"status": "PENDING"}

    def is_eligible_t1(self) -> bool:
        """True iff Sky/sUSDS is ELIGIBLE for T1 (GSM delay >= 48h confirmed).

        Safe: in dry-run uses manual status (no network); in live mode uses the
        on-chain check. Never raises — any failure → False.
        """
        try:
            return self._status_dict().get("status") == "ELIGIBLE"
        except Exception as exc:  # noqa: BLE001
            log.debug("is_eligible_t1 failed (%s) — False", exc)
            return False

    def get_tier(self) -> str:
        """Return ``"T1"`` when ELIGIBLE, else ``"T2-conditional"``."""
        return "T1" if self.is_eligible_t1() else "T2-conditional"

    def get_allocation_cap(self) -> float:
        """Return the allocation cap: 0.30 when ELIGIBLE (T1), else 0.0."""
        try:
            from spa_core.data_pipeline import sky_monitor
            return sky_monitor.get_sky_allocation_pct(self._status_dict())
        except Exception as exc:  # noqa: BLE001
            log.debug("get_allocation_cap failed (%s) — 0.0", exc)
            return 0.0

    # ── engine-bridge interface ───────────────────────────────────────────────

    def supply(self, asset: str, amount: float) -> dict[str, Any]:
        """Deposit ``amount`` USDS/DAI into the sUSDS savings vault.

        Conditional-T1 gate: a non-dry-run supply is BLOCKED while Sky is still
        PENDING (not yet ELIGIBLE for T1), regardless of SPA_EXECUTION_MODE.
        """
        asset = self._validate_asset(asset)
        vault = self._vault_address(asset)
        decimals = _DECIMALS

        if amount <= 0:
            raise ValidationError("amount", amount, "supply: must be positive")
        if amount > 10_000_000:
            raise ValidationError("amount", amount, "supply: exceeds sanity cap 10M")

        log.info("SkySUSDSAdapter.supply: asset=%s amount=%s dry_run=%s", asset, amount, self.dry_run)

        if self.dry_run:
            return {
                "status": "DRY_RUN",
                "protocol": "sky-susds",
                "chain": self.chain,
                "asset": asset,
                "amount": amount,
                "vault": vault,
                "tier": self.get_tier(),
                "eligible_t1": self.is_eligible_t1(),
                "tx_hash": "0xdry_sky_supply_" + asset.lower(),
                "pool_shares_minted": round(amount * 0.9712, 6),  # sUSDS share price > 1
                "note": "Sky sUSDS savings vault (ERC-4626) — Sky Savings Rate accrual",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Conditional-T1 gate — UNIQUE to Sky. Block live writes until ELIGIBLE.
        if not self.is_eligible_t1():
            return {
                "status": "BLOCKED",
                "reason": "Sky not yet ELIGIBLE for T1 (GSM Pause Delay < 48h confirmed)",
                "protocol": "sky-susds",
                "tier": self.get_tier(),
                "eligible_t1": False,
                "asset": asset,
                "amount": amount,
            }

        # Eligible — now apply the standard execution-mode gate (as in maple).
        if os.getenv("SPA_EXECUTION_MODE") != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE is not 'live'",
                "protocol": "sky-susds",
                "asset": asset,
                "amount": amount,
            }

        try:
            Account = _require_eth_account()
        except DependencyNotInstalled as exc:
            return {"status": "ERROR", "reason": str(exc), "protocol": "sky-susds"}

        private_key = os.getenv("SPA_PRIVATE_KEY")
        if not private_key:
            return {"status": "ERROR", "reason": "SPA_PRIVATE_KEY not set", "protocol": "sky-susds"}

        wallet = Account.from_key(private_key).address
        expected = self._wallet_address()
        if expected and wallet.lower() != expected.lower():
            return {
                "status": "ERROR",
                "reason": f"Key→address mismatch: derived={wallet} env={expected}",
                "protocol": "sky-susds",
            }

        amount_raw = int(amount * 10 ** decimals)
        token_addr = self._token_address(asset)

        approve_sel = "0x095ea7b3"
        approve_data = "0x" + approve_sel[2:] + _encode_address(vault) + _to_32bytes_hex(amount_raw)
        approve_req = TxRequest(
            to=token_addr, data=approve_data, value=0,
            asset=asset, amount=amount, chain=self.chain,
            description=f"ERC-20 approve {amount} {asset} → sUSDS vault",
        )

        deposit_data = (
            "0x" + _SEL_DEPOSIT[2:]
            + _to_32bytes_hex(amount_raw)
            + _encode_address(wallet)
        )
        deposit_req = TxRequest(
            to=vault, data=deposit_data, value=0,
            asset=asset, amount=amount, chain=self.chain,
            description=f"sUSDS deposit {amount} {asset}",
        )

        return self._execute_tx_pair(approve_req, deposit_req, Account, private_key, "supply")

    def withdraw(self, asset: str, amount: float) -> dict[str, Any]:
        """Redeem sUSDS shares back to ``amount`` USDS/DAI from the vault."""
        asset = self._validate_asset(asset)
        vault = self._vault_address(asset)
        decimals = _DECIMALS

        if amount <= 0:
            raise ValidationError("amount", amount, "withdraw: must be positive")

        log.info("SkySUSDSAdapter.withdraw: asset=%s amount=%s dry_run=%s", asset, amount, self.dry_run)

        if self.dry_run:
            return {
                "status": "DRY_RUN",
                "protocol": "sky-susds",
                "chain": self.chain,
                "asset": asset,
                "amount": amount,
                "vault": vault,
                "tier": self.get_tier(),
                "eligible_t1": self.is_eligible_t1(),
                "tx_hash": "0xdry_sky_withdraw_" + asset.lower(),
                "shares_burned": round(amount * 0.9712, 6),
                "note": "Redeem sUSDS shares 1:1 for accrued USDS (instant, no lock)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Conditional-T1 gate — block live redemptions while still PENDING too,
        # since a PENDING Sky should hold no live position to redeem.
        if not self.is_eligible_t1():
            return {
                "status": "BLOCKED",
                "reason": "Sky not yet ELIGIBLE for T1 (GSM Pause Delay < 48h confirmed)",
                "protocol": "sky-susds",
                "tier": self.get_tier(),
                "eligible_t1": False,
                "asset": asset,
                "amount": amount,
            }

        if os.getenv("SPA_EXECUTION_MODE") != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE is not 'live'",
                "protocol": "sky-susds",
                "asset": asset,
                "amount": amount,
            }

        try:
            Account = _require_eth_account()
        except DependencyNotInstalled as exc:
            return {"status": "ERROR", "reason": str(exc), "protocol": "sky-susds"}

        private_key = os.getenv("SPA_PRIVATE_KEY")
        if not private_key:
            return {"status": "ERROR", "reason": "SPA_PRIVATE_KEY not set", "protocol": "sky-susds"}

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
            description=f"sUSDS redeem {amount} {asset}",
        )
        return self._execute_single_tx(redeem_req, Account, private_key, "withdraw")

    # ── read interface ────────────────────────────────────────────────────────

    def get_supply_apy(self, asset: str) -> float:
        asset = asset.upper()
        mock = _DRY_RUN_APY.get(self.chain, {}).get(asset, 6.0)
        if self.dry_run:
            return mock

        # Live: try DeFiLlama live APY (v3.27), gated by SPA_LIVE_APY.
        try:
            from spa_core.execution import defillama_apy_feed
            if defillama_apy_feed.live_apy_enabled():
                live = defillama_apy_feed.get_live_apy("sky", asset, self.chain)
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
        asset = self._validate_asset(asset)
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
            return tokens_raw / 1e18
        except Exception as exc:
            log.warning("[FALLBACK] get_supply_balance: %s", exc)
            return mock

    def get_position(
        self, wallet_address: str, asset: str, chain: Optional[str] = None
    ) -> PositionInfo:
        asset = self._validate_asset(asset)
        chain = chain or self.chain
        vault = self._vault_address(asset)
        if self.dry_run:
            return PositionInfo(
                wallet_address=wallet_address,
                asset=asset,
                chain=chain,
                pool_address=vault,
                balance_tokens=_DRY_RUN_BALANCE.get(chain, {}).get(asset, 0.0),
                balance_shares=round(_DRY_RUN_BALANCE.get(chain, {}).get(asset, 0.0) * 0.9712, 6),
                current_apy=_DRY_RUN_APY.get(chain, {}).get(asset, 6.0),
            )
        try:
            shares = self._get_balance_of(vault, wallet_address)
            tokens_raw = self._get_convert_to_assets(vault, shares) if shares else 0
            balance_tokens = tokens_raw / 1e18
        except Exception as exc:
            log.warning("[FALLBACK] get_position: %s", exc)
            balance_tokens = 0.0
            shares = 0
        return PositionInfo(
            wallet_address=wallet_address,
            asset=asset,
            chain=chain,
            pool_address=vault,
            balance_tokens=balance_tokens,
            balance_shares=shares / 1e18,
            current_apy=self.get_supply_apy(asset),
        )

    def is_healthy(self) -> bool:
        """Savings-vault depositors have no liquidation risk — always True."""
        return True

    def health_check(self) -> dict[str, Any]:
        return {
            "protocol": "sky-susds",
            "chain": self.chain,
            "dry_run": self.dry_run,
            "is_healthy": True,
            "tier": self.get_tier(),
            "eligible_t1": self.is_eligible_t1(),
            "allocation_cap": self.get_allocation_cap(),
            "supported_assets": list(self.SUPPORTED_ASSETS),
            "vault": _VAULT_ADDRESS,
            "note": (
                "Conditional T1: held on Watch List (0% cap) until GSM Pause "
                "Delay >= 48h confirmed → promotes to T1, 30% cap."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── live execution helpers ────────────────────────────────────────────────

    @live_trading_forbidden
    def _execute_tx_pair(
        self, first: TxRequest, second: TxRequest,
        Account: Any, private_key: str, phase_tag: str,
    ) -> dict[str, Any]:
        from spa_core.execution.eth_signer import (
            get_nonce, estimate_gas, get_base_fee,
            sign_transaction,
        )
        from spa_core.execution.mev_protection import send_raw_transaction_auto
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
                receipt = send_raw_transaction_auto(signed.hex(), rpc)
                if receipt.get("status") in ("0x0", "FAILED"):
                    return {
                        "status": "FAILED",
                        "phase": "approve" if idx == 0 else phase_tag,
                        "receipt": receipt, "protocol": "sky-susds",
                    }
            return {
                "status": "OK", "protocol": "sky-susds", "chain": self.chain,
                "asset": first.asset, "amount": first.amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            log.error("_execute_tx_pair failed: %s", exc, exc_info=True)
            return {"status": "FAILED", "reason": str(exc), "protocol": "sky-susds"}

    @live_trading_forbidden
    def _execute_single_tx(
        self, req: TxRequest, Account: Any, private_key: str, phase_tag: str,
    ) -> dict[str, Any]:
        from spa_core.execution.eth_signer import (
            get_nonce, estimate_gas, get_base_fee,
            sign_transaction,
        )
        from spa_core.execution.mev_protection import send_raw_transaction_auto
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
            receipt = send_raw_transaction_auto(signed.hex(), rpc)
            if receipt.get("status") in ("0x0", "FAILED"):
                return {"status": "FAILED", "phase": phase_tag, "receipt": receipt, "protocol": "sky-susds"}
            return {
                "status": "OK", "protocol": "sky-susds", "chain": self.chain,
                "asset": req.asset, "amount": req.amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            log.error("_execute_single_tx failed: %s", exc, exc_info=True)
            return {"status": "FAILED", "reason": str(exc), "protocol": "sky-susds"}


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint
    adapter = SkySUSDSAdapter(chain="ethereum", dry_run=True)
    print("=== supply USDS 1000 ===")
    pprint.pprint(adapter.supply("USDS", 1000.0))
    print("=== health_check ===")
    pprint.pprint(adapter.health_check())

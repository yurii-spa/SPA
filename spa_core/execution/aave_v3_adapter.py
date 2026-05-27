"""
Aave V3 Live SDK Adapter (FEAT-004 Phase 1).

Pure-Python scaffold mirroring price_feeds.py (FEAT-006):
  - Env-driven, 3-RPC fallback per chain
  - Dry-run / synthetic mode (deterministic mock balances + APYs)
  - Real Aave V3 Pool contract addresses captured for Phase 2 eth_call
  - No external deps; only stdlib (datetime, logging, json)

Phase 1 scope (this file):
  * AaveV3Adapter with dry-run supply / withdraw / balance / APY methods
  * Input validation, deterministic mock returns, health_check()
  * RPC endpoint registry — Phase 2 will plug real eth_call decoding

Phase 2 (not in this file):
  * Real web3.py Pool.supply / Pool.withdraw transaction construction
  * eth_account signing via private key from secrets manager
  * Live aToken.balanceOf reads, live getReserveData() APY decoding

Phase 3:
  * Wire AaveV3Adapter into spa_core/orchestration/engine.py to flip
    paper-trade execution paths over to live execution behind a
    feature flag (mirrors BL-008 dual-driver pattern).

Supported topology:
  Chains    — ethereum, arbitrum, base
  Assets    — USDC, USDT, DAI
  Modes     — dry_run=True (default; safe, deterministic),
              dry_run=False (returns NOT_IMPLEMENTED until Phase 2 lands).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("spa.aave_v3_adapter")


class AaveV3Adapter:
    """
    Adapter for Aave V3 supply / withdraw flows across multiple chains.

    Currently: dry-run only — every state-changing call returns a
    deterministic mock payload. Real execution (dry_run=False) returns
    NOT_IMPLEMENTED until Phase 2 wires web3.py + eth_account.

    Usage (dry-run, safe to run now)::

        adapter = AaveV3Adapter(chain="ethereum")
        adapter.supply("USDC", 1000.0)
        adapter.get_supply_balance("USDC")  # -> 10000.0 (mock)
        adapter.get_supply_apy("USDC")      # -> 4.2 (mock)

    Usage (live, NOT YET IMPLEMENTED)::

        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        adapter.supply("USDC", 1000.0)  # -> {"status": "NOT_IMPLEMENTED", ...}
    """

    # ─── Class constants ──────────────────────────────────────────────────────

    SUPPORTED_CHAINS: list[str] = ["ethereum", "arbitrum", "base"]
    SUPPORTED_ASSETS: list[str] = ["USDC", "USDT", "DAI"]

    # Real Aave V3 Pool contract addresses (verified on respective chain
    # explorers as of 2026-05). Used by Phase 2 for eth_call routing.
    POOL_ADDRESSES: dict[str, str] = {
        "ethereum": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "arbitrum": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "base":     "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
    }

    # Three RPC endpoints per chain — tried in order, first success wins.
    # Phase 1 stores the URLs only; Phase 2 will dispatch eth_call to the
    # Pool address attached as a fragment hint (mirrors price_feeds.py).
    RPC_ENDPOINTS: dict[str, list[str]] = {
        "ethereum": [
            "https://eth.llamarpc.com#aave-v3-pool:0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
            "https://rpc.ankr.com/eth#aave-v3-pool:0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
            "https://cloudflare-eth.com#aave-v3-pool:0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        ],
        "arbitrum": [
            "https://arb1.arbitrum.io/rpc#aave-v3-pool:0x794a61358D6845594F94dc1DB02A252b5b4814aD",
            "https://arbitrum.llamarpc.com#aave-v3-pool:0x794a61358D6845594F94dc1DB02A252b5b4814aD",
            "https://rpc.ankr.com/arbitrum#aave-v3-pool:0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        ],
        "base": [
            "https://mainnet.base.org#aave-v3-pool:0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
            "https://base.llamarpc.com#aave-v3-pool:0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
            "https://rpc.ankr.com/base#aave-v3-pool:0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
        ],
    }

    # Deterministic mock fixtures for dry-run mode. Match SUPPORTED_ASSETS.
    _MOCK_BALANCES: dict[str, float] = {
        "USDC": 10000.0,
        "USDT": 5000.0,
        "DAI":  2500.0,
    }

    _MOCK_APYS: dict[str, float] = {
        "USDC": 4.2,
        "USDT": 3.8,
        "DAI":  3.5,
    }

    # ─── Construction ─────────────────────────────────────────────────────────

    def __init__(
        self,
        chain: str = "ethereum",
        dry_run: bool = True,
        rpc_endpoints: dict[str, list[str]] | None = None,
    ) -> None:
        """Initialise the Aave V3 adapter.

        Args:
            chain: Target chain key. Must be one of SUPPORTED_CHAINS.
            dry_run: If True (default) every state-changing call returns
                a deterministic DRY_RUN payload. If False, calls return
                NOT_IMPLEMENTED until Phase 2 wires real execution.
            rpc_endpoints: Optional override for the RPC endpoint registry.
                Defaults to the class-level RPC_ENDPOINTS table.

        Raises:
            ValueError: If ``chain`` is not in SUPPORTED_CHAINS.
        """
        if chain not in self.SUPPORTED_CHAINS:
            raise ValueError(
                f"Unsupported chain '{chain}'. "
                f"Must be one of: {self.SUPPORTED_CHAINS}"
            )
        self.chain = chain
        self.dry_run = dry_run
        self.rpc_endpoints: dict[str, list[str]] = (
            rpc_endpoints if rpc_endpoints is not None else self.RPC_ENDPOINTS
        )
        self.pool_address: str = self.POOL_ADDRESSES[chain]
        log.debug(
            "AaveV3Adapter init: chain=%s dry_run=%s pool=%s endpoints=%d",
            self.chain, self.dry_run, self.pool_address,
            len(self.rpc_endpoints.get(self.chain, [])),
        )

    # ─── Input validation ─────────────────────────────────────────────────────

    def _validate_inputs(self, asset: str, amount: float) -> None:
        """Validate asset symbol and positive amount.

        Raises:
            ValueError: If ``asset`` is not in SUPPORTED_ASSETS or ``amount``
                is not strictly positive.
        """
        if asset not in self.SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{asset}'. "
                f"Must be one of: {self.SUPPORTED_ASSETS}"
            )
        if amount is None or amount <= 0:
            raise ValueError(
                f"Invalid amount {amount!r}: must be a positive number"
            )

    # ─── Supply / withdraw ────────────────────────────────────────────────────

    def supply(self, asset: str, amount: float) -> dict:
        """
        Supply ``amount`` of ``asset`` to the Aave V3 Pool.

        Dry-run mode (default):
            Returns a deterministic DRY_RUN record. ``atoken_received``
            is set equal to ``amount`` (1:1 mock) so callers can pipe the
            result straight into accounting tests.

        Live mode (dry_run=False):
            Returns a NOT_IMPLEMENTED record until Phase 2 wires
            web3.py Pool.supply(asset, amount, onBehalfOf, referralCode).

        Args:
            asset:  Symbol in SUPPORTED_ASSETS (USDC / USDT / DAI).
            amount: Strictly-positive supply amount in token units.

        Returns:
            dict with keys ``status``, ``tx_hash``, ``asset``, ``amount``,
            ``atoken_received``, ``chain``, ``timestamp``.

        Raises:
            ValueError: On unknown asset or non-positive amount.
        """
        self._validate_inputs(asset, amount)
        ts = datetime.now(timezone.utc).isoformat()

        if self.dry_run:
            log.info(
                "[DRY_RUN supply] chain=%s asset=%s amount=%.6f",
                self.chain, asset, amount,
            )
            return {
                "status":          "DRY_RUN",
                "tx_hash":         None,
                "asset":           asset,
                "amount":          amount,
                "atoken_received": amount,
                "chain":           self.chain,
                "timestamp":       ts,
            }

        log.warning(
            "[supply NOT_IMPLEMENTED] live mode requested for %s on %s",
            asset, self.chain,
        )
        return {
            "status":          "NOT_IMPLEMENTED",
            "tx_hash":         None,
            "asset":           asset,
            "amount":          amount,
            "atoken_received": 0.0,
            "chain":           self.chain,
            "timestamp":       ts,
        }

    def withdraw(self, asset: str, amount: float) -> dict:
        """
        Withdraw ``amount`` of ``asset`` from the Aave V3 Pool.

        Dry-run mode (default):
            Returns a deterministic DRY_RUN record with ``atoken_received``
            set to the negative of ``amount`` (aToken burn accounting).

        Live mode (dry_run=False):
            Returns a NOT_IMPLEMENTED record until Phase 2 wires
            web3.py Pool.withdraw(asset, amount, to).

        Args:
            asset:  Symbol in SUPPORTED_ASSETS.
            amount: Strictly-positive withdraw amount in token units.

        Returns:
            dict with keys ``status``, ``tx_hash``, ``asset``, ``amount``,
            ``atoken_received``, ``chain``, ``timestamp``.

        Raises:
            ValueError: On unknown asset or non-positive amount.
        """
        self._validate_inputs(asset, amount)
        ts = datetime.now(timezone.utc).isoformat()

        if self.dry_run:
            log.info(
                "[DRY_RUN withdraw] chain=%s asset=%s amount=%.6f",
                self.chain, asset, amount,
            )
            return {
                "status":          "DRY_RUN",
                "tx_hash":         None,
                "asset":           asset,
                "amount":          amount,
                "atoken_received": -amount,
                "chain":           self.chain,
                "timestamp":       ts,
            }

        log.warning(
            "[withdraw NOT_IMPLEMENTED] live mode requested for %s on %s",
            asset, self.chain,
        )
        return {
            "status":          "NOT_IMPLEMENTED",
            "tx_hash":         None,
            "asset":           asset,
            "amount":          amount,
            "atoken_received": 0.0,
            "chain":           self.chain,
            "timestamp":       ts,
        }

    # ─── Read methods ─────────────────────────────────────────────────────────

    def get_supply_balance(self, asset: str) -> float:
        """
        Return the current aToken balance for ``asset``.

        Dry-run mode: returns the deterministic _MOCK_BALANCES entry.
        Live mode: Phase 2 will route to ``aToken.balanceOf(wallet)``.

        Args:
            asset: Symbol in SUPPORTED_ASSETS.

        Returns:
            Balance in token units (float).

        Raises:
            ValueError: If ``asset`` is not in SUPPORTED_ASSETS.
        """
        if asset not in self.SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{asset}'. "
                f"Must be one of: {self.SUPPORTED_ASSETS}"
            )
        if self.dry_run:
            return self._MOCK_BALANCES[asset]
        log.warning(
            "[get_supply_balance NOT_IMPLEMENTED] live mode for %s on %s",
            asset, self.chain,
        )
        return 0.0

    def get_supply_apy(self, asset: str) -> float:
        """
        Return the current supply APY for ``asset`` (percent, not fraction).

        Dry-run mode: returns the deterministic _MOCK_APYS entry.
        Live mode: Phase 2 will decode ``Pool.getReserveData(asset)``
        liquidityRate (RAY-scaled per-second rate → annualised %).

        Args:
            asset: Symbol in SUPPORTED_ASSETS.

        Returns:
            Supply APY in percent (e.g. 4.2 means 4.2%).

        Raises:
            ValueError: If ``asset`` is not in SUPPORTED_ASSETS.
        """
        if asset not in self.SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{asset}'. "
                f"Must be one of: {self.SUPPORTED_ASSETS}"
            )
        if self.dry_run:
            return self._MOCK_APYS[asset]
        log.warning(
            "[get_supply_apy NOT_IMPLEMENTED] live mode for %s on %s",
            asset, self.chain,
        )
        return 0.0

    # ─── Health check ─────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """
        Return a snapshot of the adapter's configuration.

        Returns:
            {
                "chain":               str,         # active chain
                "dry_run":             bool,
                "pool_address":        str,         # Aave V3 Pool contract
                "endpoints_configured": int,        # count of RPC URLs for chain
                "supported_assets":    list[str],
                "timestamp":           str,         # ISO-8601 UTC
            }
        """
        endpoints = self.rpc_endpoints.get(self.chain, [])
        return {
            "chain":                self.chain,
            "dry_run":              self.dry_run,
            "pool_address":         self.pool_address,
            "endpoints_configured": len(endpoints),
            "supported_assets":     list(self.SUPPORTED_ASSETS),
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    adapter = AaveV3Adapter(chain="ethereum", dry_run=True)
    print("Health check:", json.dumps(adapter.health_check(), indent=2))
    print("Supply USDC 1000:", json.dumps(adapter.supply("USDC", 1000.0), indent=2))
    print("Withdraw DAI 250:", json.dumps(adapter.withdraw("DAI", 250.0), indent=2))
    print("USDC balance:", adapter.get_supply_balance("USDC"))
    print("USDC APY:   ", adapter.get_supply_apy("USDC"))

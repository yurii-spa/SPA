"""
SPA Wallet Interface — scaffold for v2.0 real capital deployment.
NOT YET ACTIVE — all methods return simulated results.

Real implementation requires:
  - web3.py (pip install web3)
  - Private key management (hardware wallet recommended)
  - Gnosis Safe SDK (pip install safe-eth-py)
  - Tenderly account and API key
  - ETH_RPC_URL in environment / GitHub Secrets

SECURITY WARNING:
  Never commit private keys. Use a hardware wallet (Ledger/Trezor) or
  store keys in GitHub Secrets / environment variables only. The hot
  wallet should hold ETH for gas ONLY — all USDC capital lives in the
  Gnosis Safe.

See: docs/v2_architecture.md, docs/v2_activation_checklist.md
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

log = logging.getLogger("spa.wallet")


from spa_core.utils.errors import ValidationError

class WalletMode(Enum):
    """Operating mode for SPAWallet.

    PAPER      — paper trading; execute() logs the trade and returns a record
                 without raising, mirroring the paper-trading engine behaviour.
    SIMULATION — local simulation; execute() also logs without raising, used
                 for integration tests and pre-deployment dry-runs.
    LIVE       — real capital; execute() raises NotImplementedError until the
                 activation script (spa_core/golive/activate.py) has been run
                 and all 11 go-live criteria PASS.
    """
    PAPER      = "paper"
    SIMULATION = "simulation"
    LIVE       = "live"


# ── Gas estimation constants (based on historical mainnet data) ───────────────

_GAS_UNITS: dict[str, dict[str, int]] = {
    "aave-v3":   {"supply": 250_000, "withdraw": 300_000, "borrow": 350_000},
    "compound":  {"supply": 200_000, "withdraw": 250_000, "borrow": 300_000},
    "morpho":    {"supply": 280_000, "withdraw": 320_000},
    "yearn":     {"supply": 220_000, "withdraw": 260_000},
    "maple":     {"supply": 310_000, "withdraw": 380_000},
    "euler":     {"supply": 240_000, "withdraw": 290_000},
    "spark":     {"supply": 260_000, "withdraw": 310_000},
}

_DEFAULT_GAS_UNITS = 300_000
_DEFAULT_GWEI      = 20       # conservative estimate; use real gas oracle in v2
_DEFAULT_ETH_PRICE = 3_500    # USD; use real price feed in v2


class SPAWallet:
    """
    Manages wallet interactions with DeFi protocols.

    Currently: simulation mode only — all methods return safe, non-executing results.

    v2.0 activation will wire this class to:
      - web3.py for transaction construction and submission
      - Gnosis Safe SDK for multisig routing (amounts > $500)
      - Tenderly API for pre-execution simulation
      - Flashbots RPC for MEV protection (amounts > $1,000)

    Usage (simulation, safe to run now):
        wallet = SPAWallet(mode="simulation")
        balance = wallet.get_balance("USDC")
        gas = wallet.estimate_gas("aave-v3", "supply", 1000.0)
        sim = wallet.simulate_transaction("aave-v3", "supply", 1000.0)

    Usage (real, NOT YET IMPLEMENTED):
        wallet = SPAWallet(mode="live")  # raises NotImplementedError
    """

    def __init__(self, mode: str = "simulation"):
        """Initialise SPAWallet.

        Args:
            mode: One of "paper", "simulation", or "live" (case-insensitive).
                  "paper" and "simulation" are safe to use at any time.
                  "live" is accepted without raising here, but execute() will
                  raise NotImplementedError until the activation script is run.

        Raises:
            ValueError: If mode is not a recognised WalletMode value.
        """
        try:
            self.wallet_mode = WalletMode(mode.lower())
        except ValueError:
            valid = [m.value for m in WalletMode]
            raise ValidationError("mode", mode, f"must be one of {valid}")
        self.mode = self.wallet_mode.value
        self._wallet_address: Optional[str] = os.environ.get("WALLET_ADDRESS")
        self._safe_address:   Optional[str] = os.environ.get("SAFE_ADDRESS")

    # ── Read operations ───────────────────────────────────────────────────────

    def get_balance(self, token: str = "USDC") -> dict:
        """
        Returns wallet token balance.

        Simulation: returns zero balance (paper trading balances are in data/status.json).
        v2.0: reads from on-chain via web3.py — both hot wallet and Gnosis Safe balances.

        Returns:
            {
                "token":   str,         # e.g. "USDC"
                "amount":  float,       # token balance
                "mode":    str,         # "simulation" | "live"
                "real":    bool,        # False in simulation
                "address": str | None,  # wallet address if configured
            }
        """
        return {
            "token":   token,
            "amount":  0.0,
            "mode":    self.mode,
            "real":    False,
            "address": self._wallet_address,
        }

    def get_deployed_balance(self, protocol: str, token: str = "USDC") -> dict:
        """
        Returns the current balance deployed in a given protocol.

        Simulation: returns zero (paper trading state lives in data/status.json).
        v2.0: calls protocol-specific view functions (e.g. aToken.balanceOf for Aave V3).

        Args:
            protocol: Protocol key (e.g. "aave-v3", "compound")
            token:    Token symbol (default "USDC")

        Returns:
            {
                "protocol": str,
                "token":    str,
                "amount":   float,  # current deployed balance including accrued interest
                "mode":     str,
                "real":     bool,
            }
        """
        return {
            "protocol": protocol,
            "token":    token,
            "amount":   0.0,
            "mode":     self.mode,
            "real":     False,
        }

    # ── Gas estimation ────────────────────────────────────────────────────────

    def estimate_gas(
        self,
        protocol:   str,
        action:     str,
        amount_usd: float,
        gwei:       Optional[float] = None,
        eth_price:  Optional[float] = None,
    ) -> dict:
        """
        Estimate the gas cost for a DeFi action.

        Simulation: uses historical average gas units with assumed gwei/ETH price.
        v2.0: calls eth_estimateGas via web3.py + real-time gas oracle.

        Args:
            protocol:   Protocol key (e.g. "aave-v3")
            action:     Action type ("supply", "withdraw", "borrow")
            amount_usd: Transaction value in USD (used to compute cost as % of trade)
            gwei:       Override gas price in gwei (default: 20 gwei)
            eth_price:  Override ETH price in USD (default: $3,500)

        Returns:
            {
                "gas_units":    int,    # estimated gas units
                "gwei":         float,  # gas price used
                "eth_price":    float,  # ETH price used
                "cost_usd":     float,  # estimated gas cost in USD
                "pct_of_trade": float,  # gas cost as % of transaction value
                "acceptable":   bool,   # True if cost_usd < 2% of amount_usd
                "mode":         str,
            }
        """
        units     = _GAS_UNITS.get(protocol, {}).get(action, _DEFAULT_GAS_UNITS)
        gwei_     = gwei      if gwei      is not None else _DEFAULT_GWEI
        eth_price_ = eth_price if eth_price is not None else _DEFAULT_ETH_PRICE

        cost_usd    = (units * gwei_ * 1e-9) * eth_price_
        pct_of_trade = (cost_usd / amount_usd * 100) if amount_usd > 0 else float("inf")

        return {
            "gas_units":    units,
            "gwei":         gwei_,
            "eth_price":    eth_price_,
            "cost_usd":     round(cost_usd, 4),
            "pct_of_trade": round(pct_of_trade, 3),
            "acceptable":   pct_of_trade < 2.0,
            "mode":         self.mode,
        }

    # ── Simulation ────────────────────────────────────────────────────────────

    def simulate_transaction(
        self,
        protocol:   str,
        action:     str,
        amount_usd: float,
        use_tenderly: bool = False,
    ) -> dict:
        """
        Simulate a transaction before execution.

        Simulation: local check only — validates inputs, returns success.
        v2.0: calls Tenderly simulation API with encoded calldata on a mainnet fork.

        Args:
            protocol:     Protocol key
            action:       Action type ("supply", "withdraw")
            amount_usd:   Transaction value in USD
            use_tenderly: If True (v2.0 only), use Tenderly API instead of local check

        Returns:
            {
                "success":    bool,
                "mode":       str,    # "local_simulation" | "tenderly"
                "protocol":   str,
                "action":     str,
                "amount_usd": float,
                "error":      str | None,   # error message if not success
                "sim_id":     str | None,   # Tenderly simulation ID if applicable
            }
        """
        # Basic validation even in simulation mode
        error = None
        success = True

        if protocol not in _GAS_UNITS:
            error   = f"Unknown protocol '{protocol}' — not in whitelist"
            success = False
        elif action not in ("supply", "withdraw", "borrow"):
            error   = f"Unknown action '{action}'"
            success = False
        elif amount_usd <= 0:
            error   = f"Invalid amount_usd: {amount_usd} (must be > 0)"
            success = False

        return {
            "success":    success,
            "mode":       "local_simulation",
            "protocol":   protocol,
            "action":     action,
            "amount_usd": amount_usd,
            "error":      error,
            "sim_id":     None,  # populated in v2.0 when Tenderly is wired up
        }

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(
        self,
        protocol:    str,
        action:      str,
        amount_usd:  float,
        approved_by: Optional[str] = None,
    ) -> dict:
        """
        Execute (or log) an on-chain transaction depending on WalletMode.

        PAPER / SIMULATION modes:
            Logs the trade and returns a paper trade record.  Never raises.
            Suitable for paper trading and pre-deployment integration tests.

        LIVE mode:
            Always raises NotImplementedError with an instruction to run the
            activation script.  Real execution is blocked until:
              1. All 11 go-live criteria PASS
              2. Owner types "I CONFIRM LIVE TRADING" in the activation script
            To activate: ``python -m spa_core.golive.activate``

        Args:
            protocol:    Protocol key (e.g. "aave-v3")
            action:      "supply" | "withdraw"
            amount_usd:  Amount to transact in USD
            approved_by: Safe owner signature (required for amounts > $500 in LIVE mode)

        Returns:
            Paper trade log dict in PAPER / SIMULATION modes.

        Raises:
            NotImplementedError: In LIVE mode — always, until activation.
        """
        if self.wallet_mode in (WalletMode.PAPER, WalletMode.SIMULATION):
            record = {
                "mode":        self.wallet_mode.value,
                "protocol":    protocol,
                "action":      action,
                "amount_usd":  amount_usd,
                "approved_by": approved_by,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
                "status":      "PAPER_LOGGED",
                "tx_hash":     None,
                "real":        False,
            }
            log.info(
                "[%s TRADE LOG] %s $%.2f on %s",
                self.wallet_mode.value.upper(), action, amount_usd, protocol,
            )
            return record

        # LIVE mode — hard block until activation script is run
        raise NotImplementedError(
            "LIVE mode requires manual activation. "
            "Run python -m spa_core.golive.activate"
        )

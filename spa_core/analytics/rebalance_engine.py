"""
spa_core/analytics/rebalance_engine.py

Rebalancing engine for concentrated LP positions (RS-002).

Triggers for rebalance:
  1. Position out of range > 3 consecutive days
  2. IL > 10% (excessive impermanent loss)
  3. Manual request (external trigger)

Rebalance strategy: "centre around current price" with the same ±% range
as the original position configuration.

All values are advisory — no trades are executed here.

Правила:
  - Только stdlib Python (math, dataclasses)
  - Чисто вычислительный / advisory модуль — никаких I/O, записей
  - Не импортировать из execution / feed_health / risk

MP-1372 (v9.88)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from spa_core.analytics.rs002_position_tracker import (
    LPPosition,
    RS002_SLOTS,
    RS002PositionTracker,
)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RebalanceProposal:
    """Advisory proposal to rebalance one LP position."""
    slot_id: str
    trigger: str            # "out_of_range" | "il_threshold" | "manual"
    old_lower: float
    old_upper: float
    new_lower: float
    new_upper: float
    current_price: float
    estimated_gas_usd: float
    expected_il_reset: float   # IL immediately after rebalance (≈ 0.0)
    recommendation: str        # "REBALANCE" | "WAIT" | "CLOSE"


# ── Engine ────────────────────────────────────────────────────────────────────

class RebalanceEngine:
    """Evaluates RS-002 LP positions and generates advisory rebalance proposals.

    Constants
    ---------
    GAS_ESTIMATE_ETH : float
        Estimated gas cost per rebalance transaction (0.005 ETH).
    ETH_PRICE_USD : float
        Conservative ETH price used for gas USD conversion.
    IL_THRESHOLD : float
        IL % (absolute) above which a rebalance is considered (10%).
    CLOSE_THRESHOLD : float
        IL % above which recommendation is CLOSE (20%).
    BREAKEVEN_FAST_DAYS : int
        Breakeven ≤ this → "REBALANCE"; otherwise "WAIT".
    """

    GAS_ESTIMATE_ETH: float = 0.005
    ETH_PRICE_USD: float = 3_500.0
    IL_THRESHOLD: float = 10.0
    CLOSE_THRESHOLD: float = 20.0
    BREAKEVEN_FAST_DAYS: int = 30

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = base_dir

    # ── core evaluation ───────────────────────────────────────────────────────

    def check_position(
        self, position: LPPosition
    ) -> Optional[RebalanceProposal]:
        """Evaluates a single position; returns a proposal or None.

        Returns None when:
          - The slot has no range (trader_losses, range_pct=None)
          - Position is in range AND IL < IL_THRESHOLD

        Returns a RebalanceProposal when:
          - consecutive_out_days > 3  (trigger="out_of_range")
          - |IL| > IL_THRESHOLD       (trigger="il_threshold", takes lower priority)
        """
        slot_cfg = RS002_SLOTS.get(position.slot_id)
        if slot_cfg is None:
            return None

        range_pct: Optional[float] = slot_cfg["range_pct"]
        if range_pct is None:
            # vault strategy — no concentrated range, no IL
            return None

        trigger: Optional[str] = None

        if position.consecutive_out_days > 3:
            trigger = "out_of_range"
        elif abs(position.current_il_pct) > self.IL_THRESHOLD:
            trigger = "il_threshold"

        if trigger is None:
            return None

        new_lower, new_upper = self.calculate_new_range(
            position.current_price, range_pct
        )

        return RebalanceProposal(
            slot_id=position.slot_id,
            trigger=trigger,
            old_lower=position.lower_tick,
            old_upper=position.upper_tick,
            new_lower=new_lower,
            new_upper=new_upper,
            current_price=position.current_price,
            estimated_gas_usd=self.rebalance_cost_usd(),
            expected_il_reset=0.0,  # centring on current price resets IL to ~0
            recommendation=self._recommendation(position),
        )

    # ── range calculation ─────────────────────────────────────────────────────

    def calculate_new_range(
        self, current_price: float, range_pct: float
    ) -> tuple:
        """New [lower, upper] centred on current_price ± range_pct.

        Parameters
        ----------
        current_price : float
            Current market price (new centre).
        range_pct : float
            Half-width of the range; e.g. 0.30 = ±30%.

        Returns
        -------
        (lower, upper) : tuple[float, float]
        """
        lower = current_price * (1.0 - range_pct)
        upper = current_price * (1.0 + range_pct)
        return (lower, upper)

    # ── cost helpers ──────────────────────────────────────────────────────────

    def rebalance_cost_usd(self) -> float:
        """Gas cost in USD for a single rebalance transaction."""
        return self.GAS_ESTIMATE_ETH * self.ETH_PRICE_USD

    def breakeven_days(
        self, position: LPPosition, proposal: RebalanceProposal
    ) -> int:
        """Ceiling-integer days to recover the gas cost via increased fees.

        After rebalancing, the position is back in range and earns fees at the
        gross_fee_apy rate. Before rebalancing it earned 0 (out-of-range).
        breakeven = gas_cost / daily_fee_gain.
        """
        gas_usd = proposal.estimated_gas_usd
        slot_cfg = RS002_SLOTS.get(position.slot_id, {})
        gross_fee_apy: float = slot_cfg.get("gross_fee_apy", 0.0)

        daily_fee = position.capital_usd * (gross_fee_apy / 100.0) / 365.0

        if daily_fee <= 0.0:
            return 365 * 99  # arbitrarily large

        return max(1, math.ceil(gas_usd / daily_fee))

    def monthly_rebalance_cost(self, n_rebalances: int = 2) -> float:
        """Expected monthly gas cost assuming n_rebalances rebalance events."""
        return n_rebalances * self.rebalance_cost_usd()

    # ── batch check ───────────────────────────────────────────────────────────

    def check_all(self, tracker: RS002PositionTracker) -> List[RebalanceProposal]:
        """Check every open position in the tracker; return list of proposals."""
        proposals: List[RebalanceProposal] = []
        for position in tracker.positions.values():
            proposal = self.check_position(position)
            if proposal is not None:
                proposals.append(proposal)
        return proposals

    # ── internal ──────────────────────────────────────────────────────────────

    def _recommendation(self, position: LPPosition) -> str:
        """Determine REBALANCE / WAIT / CLOSE recommendation.

        CLOSE   : |IL| > CLOSE_THRESHOLD (excessive loss, better to exit)
        REBALANCE: breakeven ≤ BREAKEVEN_FAST_DAYS (gas pays back quickly)
        WAIT    : everything else
        """
        if abs(position.current_il_pct) > self.CLOSE_THRESHOLD:
            return "CLOSE"

        # Build a dummy proposal to compute breakeven without recursion
        slot_cfg = RS002_SLOTS.get(position.slot_id, {})
        range_pct: Optional[float] = slot_cfg.get("range_pct")
        if range_pct is None:
            return "WAIT"

        new_lower, new_upper = self.calculate_new_range(
            position.current_price, range_pct
        )
        dummy_proposal = RebalanceProposal(
            slot_id=position.slot_id,
            trigger="internal",
            old_lower=position.lower_tick,
            old_upper=position.upper_tick,
            new_lower=new_lower,
            new_upper=new_upper,
            current_price=position.current_price,
            estimated_gas_usd=self.rebalance_cost_usd(),
            expected_il_reset=0.0,
            recommendation="",  # filled in by caller
        )

        be_days = self.breakeven_days(position, dummy_proposal)
        if be_days <= self.BREAKEVEN_FAST_DAYS:
            return "REBALANCE"
        return "WAIT"

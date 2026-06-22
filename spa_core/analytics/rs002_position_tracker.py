"""
spa_core/analytics/rs002_position_tracker.py

Tracks RS-002 concentrated LP positions during paper trading.

RS-002 Slots:
  btc_usd_conc_lp:   60% allocation — BTC/USDC UniV3 ±30% range
  rwa_lp:            20% allocation — RWA LP (Ondo OUSG/USDC)
  trader_losses:     10% allocation — Trader losses vault
  stablecoin_floor:  10% allocation — T1 stablecoin (Aave/Morpho/Sky)

Tracks:
  - Entry price, range bounds [lower, upper]
  - Current price (updated from paper signals)
  - Current IL (using ConcLPILModel)
  - Days in range / out of range
  - Accumulated fees estimate
  - Net APY (fees - IL)

Правила (проектные):
  - Только stdlib Python (dataclasses, json, os, math)
  - Чисто вычислительный / advisory модуль — atomic save через tmp+os.replace
  - Не импортировать из execution / feed_health / risk

MP-1371 (v9.87)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from spa_core.analytics.conc_lp_il_model import ConcLPILModel
from spa_core.base import BaseAnalytics


# ── Slot registry ─────────────────────────────────────────────────────────────

RS002_SLOTS: Dict[str, dict] = {
    "btc_usd_conc_lp": {
        "weight": 0.60,
        "fee_tier": 0.003,
        "range_pct": 0.30,
        "gross_fee_apy": 42.0,   # % gross fees at full utilisation
    },
    "rwa_lp": {
        "weight": 0.20,
        "fee_tier": 0.001,
        "range_pct": 0.05,
        "gross_fee_apy": 10.0,
    },
    "trader_losses": {
        "weight": 0.10,
        "fee_tier": 0.003,
        "range_pct": None,       # vault strategy — no IL model
        "gross_fee_apy": 14.0,
    },
    "stablecoin_floor": {
        "weight": 0.10,
        "fee_tier": 0.0005,
        "range_pct": 0.002,
        "gross_fee_apy": 5.0,
    },
}

# Blended gross APY sanity check (informational):
#   0.60*42 + 0.20*10 + 0.10*14 + 0.10*5 = 25.2+2+1.4+0.5 = 29.1% ≈ 29.2%


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LPPosition:
    """State of a single RS-002 slot position."""
    slot_id: str
    entry_price: float
    lower_tick: float
    upper_tick: float
    capital_usd: float
    entry_date: str
    current_price: float = 0.0
    days_in_range: int = 0
    days_out_of_range: int = 0
    accumulated_fees_usd: float = 0.0
    current_il_pct: float = 0.0
    # Additional tracking field needed for needs_rebalance() logic
    consecutive_out_days: int = 0


# ── Tracker ───────────────────────────────────────────────────────────────────

class RS002PositionTracker(BaseAnalytics):
    """Tracks RS-002 concentrated LP positions during paper trading."""

    OUTPUT_PATH = "data/rs002/positions.json"

    def __init__(
        self,
        tracker_path: str = "data/rs002/positions.json",
        total_capital: float = 20_000.0,   # 20% of $100K SPA capital
    ) -> None:
        super().__init__()
        self.tracker_path = tracker_path
        self.total_capital = total_capital
        self.positions: Dict[str, LPPosition] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def open_position(
        self, slot_id: str, entry_price: float, date: str
    ) -> LPPosition:
        """Opens a new position; range bounds are derived from RS002_SLOTS.

        Raises ValueError for unknown slot_id.
        """
        if slot_id not in RS002_SLOTS:
            raise ValueError(
                f"Unknown slot_id: {slot_id!r}. Valid ids: {list(RS002_SLOTS)}"
            )

        cfg = RS002_SLOTS[slot_id]
        weight: float = cfg["weight"]
        range_pct: Optional[float] = cfg["range_pct"]
        capital_usd = self.total_capital * weight

        if range_pct is not None:
            lower_tick = entry_price * (1.0 - range_pct)
            upper_tick = entry_price * (1.0 + range_pct)
        else:
            # trader_losses: nominal wide bracket (not used for IL calc)
            lower_tick = entry_price * 0.5
            upper_tick = entry_price * 2.0

        pos = LPPosition(
            slot_id=slot_id,
            entry_price=float(entry_price),
            lower_tick=lower_tick,
            upper_tick=upper_tick,
            capital_usd=capital_usd,
            entry_date=date,
            current_price=float(entry_price),
            days_in_range=0,
            days_out_of_range=0,
            accumulated_fees_usd=0.0,
            current_il_pct=0.0,
            consecutive_out_days=0,
        )
        self.positions[slot_id] = pos
        return pos

    # ── price update ─────────────────────────────────────────────────────────

    def update_price(
        self, slot_id: str, current_price: float, date: str
    ) -> None:
        """Updates current price, recalculates IL, updates in/out-range counters.

        Fees accrue only while the position is in range.
        Out-of-range → fee accrual stops (concentrated LP behaviour).
        """
        if slot_id not in self.positions:
            raise KeyError(f"No open position for slot_id: {slot_id!r}")

        pos = self.positions[slot_id]
        pos.current_price = float(current_price)

        # Recalculate IL
        pos.current_il_pct = self.current_il(slot_id)

        # In/out range classification
        in_range = pos.lower_tick <= current_price <= pos.upper_tick

        if in_range:
            pos.days_in_range += 1
            pos.consecutive_out_days = 0
            # Accrue one day of fees
            gross_fee_apy: float = RS002_SLOTS[slot_id]["gross_fee_apy"]
            daily_fee = pos.capital_usd * (gross_fee_apy / 100.0) / 365.0
            pos.accumulated_fees_usd += daily_fee
        else:
            pos.days_out_of_range += 1
            pos.consecutive_out_days += 1

    # ── IL & net APY ─────────────────────────────────────────────────────────

    def current_il(self, slot_id: str) -> float:
        """Current IL % for slot (uses ConcLPILModel).

        Returns 0.0 for:
          - trader_losses (range_pct is None)
          - positions where current_price == 0 (uninitialised)
        Otherwise returns ≤ 0 (negative = loss relative to hold).
        """
        if slot_id not in self.positions:
            raise KeyError(f"No open position for slot_id: {slot_id!r}")

        pos = self.positions[slot_id]
        range_pct: Optional[float] = RS002_SLOTS[slot_id]["range_pct"]

        if range_pct is None or pos.current_price == 0.0:
            return 0.0

        model = ConcLPILModel(
            price_lower=pos.lower_tick,
            price_upper=pos.upper_tick,
            initial_price=pos.entry_price,
            fee_tier=RS002_SLOTS[slot_id]["fee_tier"],
        )
        return model.il_pct(pos.current_price)

    def net_apy(self, slot_id: str) -> float:
        """Estimated net APY = effective_fee_apy + annualised_IL_drag.

        - In-range: fee APY = gross_fee_apy; out-of-range: fee APY = 0.
        - IL drag is annualised over the holding period (min 1 day).
        - Returns float in percent.
        """
        if slot_id not in self.positions:
            raise KeyError(f"No open position for slot_id: {slot_id!r}")

        pos = self.positions[slot_id]
        cfg = RS002_SLOTS[slot_id]
        gross_fee_apy: float = cfg["gross_fee_apy"]

        # Fee component
        in_range = pos.lower_tick <= pos.current_price <= pos.upper_tick
        effective_fee_apy = gross_fee_apy if in_range else 0.0

        # IL drag component (annualised)
        il_pct = self.current_il(slot_id)  # ≤ 0
        if il_pct == 0.0:
            il_annual_drag = 0.0
        else:
            holding_days = max(1, pos.days_in_range + pos.days_out_of_range)
            # Annualise: IL_pct / holding_years
            il_annual_drag = il_pct / (holding_days / 365.0)

        return effective_fee_apy + il_annual_drag

    # ── portfolio summary ─────────────────────────────────────────────────────

    def portfolio_summary(self) -> dict:
        """Summary across all open slots.

        Returns dict with keys:
          total_capital, total_fees_usd, weighted_il_pct,
          blended_net_apy, positions_count, slots (per-slot detail).
        """
        total_fees = sum(p.accumulated_fees_usd for p in self.positions.values())

        weighted_il = 0.0
        weighted_net_apy = 0.0

        for slot_id, pos in self.positions.items():
            w = RS002_SLOTS[slot_id]["weight"]
            weighted_il += pos.current_il_pct * w
            weighted_net_apy += self.net_apy(slot_id) * w

        slots_detail = {}
        for slot_id, pos in self.positions.items():
            slots_detail[slot_id] = {
                "capital_usd": pos.capital_usd,
                "current_il_pct": pos.current_il_pct,
                "net_apy": self.net_apy(slot_id),
                "days_in_range": pos.days_in_range,
                "days_out_of_range": pos.days_out_of_range,
                "accumulated_fees_usd": pos.accumulated_fees_usd,
                "needs_rebalance": self.needs_rebalance(slot_id),
            }

        return {
            "total_capital": self.total_capital,
            "total_fees_usd": round(total_fees, 6),
            "weighted_il_pct": round(weighted_il, 6),
            "blended_net_apy": round(weighted_net_apy, 6),
            "positions_count": len(self.positions),
            "slots": slots_detail,
        }

    # ── rebalance signal ─────────────────────────────────────────────────────

    def needs_rebalance(self, slot_id: str) -> bool:
        """True if position is out of range for >3 consecutive days."""
        if slot_id not in self.positions:
            raise KeyError(f"No open position for slot_id: {slot_id!r}")
        return self.positions[slot_id].consecutive_out_days > 3

    # ── BaseAnalytics interface ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns current tracker state as JSON-serializable dict."""
        return {
            "tracker_path": self.tracker_path,
            "total_capital": self.total_capital,
            "positions": {
                slot_id: {
                    "slot_id": pos.slot_id,
                    "entry_price": pos.entry_price,
                    "lower_tick": pos.lower_tick,
                    "upper_tick": pos.upper_tick,
                    "capital_usd": pos.capital_usd,
                    "entry_date": pos.entry_date,
                    "current_price": pos.current_price,
                    "days_in_range": pos.days_in_range,
                    "days_out_of_range": pos.days_out_of_range,
                    "accumulated_fees_usd": pos.accumulated_fees_usd,
                    "current_il_pct": pos.current_il_pct,
                    "consecutive_out_days": pos.consecutive_out_days,
                }
                for slot_id, pos in self.positions.items()
            },
        }

    # ── persistence ──────────────────────────────────────────────────────────

    def save(self) -> None:
        """Atomic save: serialise state to tracker_path via tmp+os.replace."""
        dir_path = os.path.dirname(self.tracker_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        payload: dict = {
            "tracker_path": self.tracker_path,
            "total_capital": self.total_capital,
            "positions": {
                slot_id: {
                    "slot_id": pos.slot_id,
                    "entry_price": pos.entry_price,
                    "lower_tick": pos.lower_tick,
                    "upper_tick": pos.upper_tick,
                    "capital_usd": pos.capital_usd,
                    "entry_date": pos.entry_date,
                    "current_price": pos.current_price,
                    "days_in_range": pos.days_in_range,
                    "days_out_of_range": pos.days_out_of_range,
                    "accumulated_fees_usd": pos.accumulated_fees_usd,
                    "current_il_pct": pos.current_il_pct,
                    "consecutive_out_days": pos.consecutive_out_days,
                }
                for slot_id, pos in self.positions.items()
            },
        }

        tmp_path = self.tracker_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp_path, self.tracker_path)

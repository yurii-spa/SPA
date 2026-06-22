"""
MP-684: LiquidationPriceMonitor
Monitor positions that use collateral (Aave, Morpho, Compound-style lending)
and track distance to liquidation price.
Advisory/read-only. Pure stdlib. Atomic writes.
"""
from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/liquidation_monitor_log.json")
MAX_ENTRIES = 100


@dataclass
class LendingPosition:
    position_id: str
    protocol: str
    collateral_token: str
    debt_token: str
    collateral_amount: float       # units of collateral token
    collateral_price_usd: float    # current price
    debt_amount_usd: float         # total debt in USD
    liquidation_threshold: float   # e.g. 0.80 means liquidate when LTV > 80%
    current_timestamp: float


@dataclass
class LiquidationRiskReport:
    position_id: str
    protocol: str
    collateral_value_usd: float
    current_ltv: float             # debt / collateral_value
    liquidation_ltv: float         # threshold
    ltv_buffer_pct: float          # (liq_ltv - current_ltv) / liq_ltv * 100
    liquidation_price_usd: float   # price at which collateral is liquidated
    price_drop_to_liq_pct: float   # how far price must fall to trigger liquidation
    health_factor: float           # collateral_value * threshold / debt
    status: str                    # SAFE / CAUTION / WARNING / DANGER / CRITICAL
    days_to_liq_at_trend: Optional[float]  # None if trend unknown/positive
    recommendations: List[str]


class LiquidationPriceMonitor:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------ #
    #  Core calculations                                                   #
    # ------------------------------------------------------------------ #

    def _collateral_value_usd(self, pos: LendingPosition) -> float:
        """Total collateral value in USD."""
        return pos.collateral_amount * pos.collateral_price_usd

    def _current_ltv(self, debt: float, collateral_value: float) -> float:
        """Current loan-to-value ratio."""
        if collateral_value <= 0:
            return 1.0
        return debt / collateral_value

    def _health_factor(self, collateral_value: float,
                       liquidation_threshold: float, debt: float) -> float:
        """health_factor = collateral_value * liq_threshold / debt."""
        if debt <= 0:
            return 999.0
        return (collateral_value * liquidation_threshold) / debt

    def _liquidation_price_usd(self, pos: LendingPosition) -> float:
        """
        Price at which health_factor == 1.0:
        liq_price = debt_usd / (collateral_amount * liquidation_threshold)
        Returns 0.0 when collateral_amount or threshold is zero (no liq risk).
        """
        denom = pos.collateral_amount * pos.liquidation_threshold
        if denom <= 0:
            return 0.0
        return pos.debt_amount_usd / denom

    def _price_drop_to_liq_pct(self, current_price: float,
                                 liq_price: float) -> float:
        """% the current price must fall to reach liquidation. 0 if already past."""
        if current_price <= 0 or current_price <= liq_price:
            return 0.0
        return (current_price - liq_price) / current_price * 100.0

    def _ltv_buffer_pct(self, current_ltv: float,
                         liquidation_threshold: float) -> float:
        """Buffer (as % of liq_ltv) before LTV breaches the threshold."""
        if current_ltv >= liquidation_threshold:
            return 0.0
        return (liquidation_threshold - current_ltv) / liquidation_threshold * 100.0

    def _status(self, health_factor: float) -> str:
        """Classify by health factor."""
        if health_factor < 1.05:
            return "CRITICAL"
        if health_factor < 1.2:
            return "DANGER"
        if health_factor < 1.5:
            return "WARNING"
        if health_factor < 2.0:
            return "CAUTION"
        return "SAFE"

    def _recommendations(self, status: str, health_factor: float,
                          price_drop_to_liq_pct: float) -> List[str]:
        """Build list of action recommendations."""
        recs: List[str] = []
        if status == "CRITICAL":
            recs.append("🚨 CRITICAL: Add collateral or repay debt IMMEDIATELY")
        elif status == "DANGER":
            recs.append("🚨 Danger zone — liquidation imminent, add collateral now")
        elif status == "WARNING":
            recs.append("⚠️ Warning — health factor below 1.5, consider adding collateral")

        if price_drop_to_liq_pct < 10:
            recs.append("⚠️ Liquidation price within 10% of current price")

        if status == "SAFE" and health_factor > 3.0:
            recs.append("✅ Position very safe — could take on more yield")

        return recs

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def monitor(self, pos: LendingPosition) -> LiquidationRiskReport:
        """Analyse a single lending position and return a risk report."""
        col_val = self._collateral_value_usd(pos)
        ltv = self._current_ltv(pos.debt_amount_usd, col_val)
        hf = self._health_factor(col_val, pos.liquidation_threshold,
                                  pos.debt_amount_usd)
        liq_price = self._liquidation_price_usd(pos)
        price_drop = self._price_drop_to_liq_pct(pos.collateral_price_usd,
                                                   liq_price)
        ltv_buf = self._ltv_buffer_pct(ltv, pos.liquidation_threshold)
        status = self._status(hf)
        recs = self._recommendations(status, hf, price_drop)

        return LiquidationRiskReport(
            position_id=pos.position_id,
            protocol=pos.protocol,
            collateral_value_usd=col_val,
            current_ltv=ltv,
            liquidation_ltv=pos.liquidation_threshold,
            ltv_buffer_pct=ltv_buf,
            liquidation_price_usd=liq_price,
            price_drop_to_liq_pct=price_drop,
            health_factor=hf,
            status=status,
            days_to_liq_at_trend=None,
            recommendations=recs,
        )

    def monitor_batch(self, positions: List[LendingPosition]) -> List[LiquidationRiskReport]:
        """Analyse a list of positions."""
        return [self.monitor(p) for p in positions]

    def critical_positions(
        self, reports: List[LiquidationRiskReport]
    ) -> List[LiquidationRiskReport]:
        """Return only CRITICAL or DANGER positions."""
        return [r for r in reports if r.status in ("CRITICAL", "DANGER")]

    # ------------------------------------------------------------------ #
    #  Persistence (ring-buffer, atomic)                                   #
    # ------------------------------------------------------------------ #

    def save_results(self, reports: List[LiquidationRiskReport]) -> None:
        """Append report summaries to ring-buffer JSON. Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        ts = time.time()
        for r in reports:
            existing.append({
                "timestamp": ts,
                "position_id": r.position_id,
                "protocol": r.protocol,
                "health_factor": r.health_factor,
                "status": r.status,
                "current_ltv": r.current_ltv,
                "liquidation_price_usd": r.liquidation_price_usd,
                "price_drop_to_liq_pct": r.price_drop_to_liq_pct,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load ring-buffer log. Returns [] on missing/corrupt file."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

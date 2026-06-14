# spa_core/analytics/lp_position_tracker.py
# MP-660 — LPPositionTracker (pure stdlib, advisory/read-only)
# Track LP position performance over time: entry, current value, fee accumulation, age.

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/lp_positions.json")
MAX_POSITIONS = 50  # max tracked positions


@dataclass
class LPEntry:
    position_id: str
    pool_id: str
    protocol: str           # e.g. "Uniswap V3", "Curve"
    token_pair: str         # e.g. "ETH/USDC"
    entry_timestamp: float  # unix timestamp
    entry_capital_usd: float
    current_capital_usd: float
    fees_accumulated_usd: float
    last_updated: float
    days_active: float      # (last_updated - entry_timestamp) / 86400
    status: str             # ACTIVE / CLOSED


@dataclass
class LPSummary:
    total_positions: int
    active_positions: int
    closed_positions: int
    total_capital_deployed_usd: float
    total_fees_earned_usd: float
    avg_position_age_days: float
    best_performer_id: Optional[str]   # highest (fees/capital) ratio
    worst_performer_id: Optional[str]  # lowest (fees/capital) ratio
    overall_fee_yield_pct: float       # total_fees / total_capital


class LPPositionTracker:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _fee_yield(self, entry: LPEntry) -> float:
        if entry.entry_capital_usd <= 0:
            return 0.0
        return entry.fees_accumulated_usd / entry.entry_capital_usd

    def add_position(self, position: LPEntry) -> None:
        positions = self._load_positions()
        # Update if exists, add if new
        existing = {p["position_id"]: p for p in positions}
        existing[position.position_id] = {
            "position_id": position.position_id,
            "pool_id": position.pool_id,
            "protocol": position.protocol,
            "token_pair": position.token_pair,
            "entry_timestamp": position.entry_timestamp,
            "entry_capital_usd": round(position.entry_capital_usd, 2),
            "current_capital_usd": round(position.current_capital_usd, 2),
            "fees_accumulated_usd": round(position.fees_accumulated_usd, 4),
            "last_updated": position.last_updated,
            "days_active": round(position.days_active, 2),
            "status": position.status,
        }
        positions = list(existing.values())[-MAX_POSITIONS:]
        self._save_positions(positions)

    def close_position(self, position_id: str) -> bool:
        positions = self._load_positions()
        updated = False
        for p in positions:
            if p["position_id"] == position_id:
                p["status"] = "CLOSED"
                p["last_updated"] = time.time()
                updated = True
        if updated:
            self._save_positions(positions)
        return updated

    def get_summary(self, positions: List[dict]) -> LPSummary:
        active = [p for p in positions if p.get("status") == "ACTIVE"]
        closed = [p for p in positions if p.get("status") == "CLOSED"]
        total_cap = sum(p.get("entry_capital_usd", 0) for p in active)
        total_fees = sum(p.get("fees_accumulated_usd", 0) for p in active)
        ages = [p.get("days_active", 0) for p in active]
        avg_age = sum(ages) / len(ages) if ages else 0.0

        def fee_yield(p: dict) -> float:
            cap = p.get("entry_capital_usd", 0)
            return p.get("fees_accumulated_usd", 0) / cap if cap > 0 else 0.0

        best_id = max(active, key=fee_yield)["position_id"] if active else None
        worst_id = min(active, key=fee_yield)["position_id"] if active else None
        overall_yield = total_fees / total_cap if total_cap > 0 else 0.0

        return LPSummary(
            total_positions=len(positions),
            active_positions=len(active),
            closed_positions=len(closed),
            total_capital_deployed_usd=round(total_cap, 2),
            total_fees_earned_usd=round(total_fees, 4),
            avg_position_age_days=round(avg_age, 2),
            best_performer_id=best_id,
            worst_performer_id=worst_id,
            overall_fee_yield_pct=round(overall_yield, 6),
        )

    def _load_positions(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

    def _save_positions(self, positions: List[dict]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(positions, indent=2))
        os.replace(tmp, self.data_file)

    def load_positions(self) -> List[dict]:
        return self._load_positions()

"""
PortfolioRebalancingScheduler (SPA-V593 / MP-713) — advisory / read-only.

Determines optimal rebalancing timing by comparing drift-induced opportunity
cost against transaction costs, preventing both over- and under-rebalancing.

Design constraints
------------------
* Pure stdlib only — no numpy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace.
* Ring-buffer cap: 100 entries (data/rebalancing_schedule_log.json).
* LLM_FORBIDDEN_AGENTS not applicable (analytics domain).

Urgency tiers
-------------
  CRITICAL  — drift_abs > threshold*3
  HIGH      — drift_abs > threshold*2
  MODERATE  — drift_abs > threshold
  LOW       — drift_abs > threshold*0.5
  NONE      — within tolerance

Rebalancing decision
--------------------
  IMMEDIATE   — any CRITICAL signal
  THIS_WEEK   — any HIGH signal, or days_to_break_even < 7
  NEXT_MONTH  — should_rebalance (break-even < 14)
  HOLD        — no urgency

CLI
---
  python3 -m spa_core.analytics.portfolio_rebalancing_scheduler --check
  python3 -m spa_core.analytics.portfolio_rebalancing_scheduler --run
  python3 -m spa_core.analytics.portfolio_rebalancing_scheduler --run --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "rebalancing_schedule_log.json"
_RING_BUFFER_MAX = 100

# Urgency literals
URGENCY_CRITICAL = "CRITICAL"
URGENCY_HIGH = "HIGH"
URGENCY_MODERATE = "MODERATE"
URGENCY_LOW = "LOW"
URGENCY_NONE = "NONE"

# Rebalance urgency literals
REBALANCE_IMMEDIATE = "IMMEDIATE"
REBALANCE_THIS_WEEK = "THIS_WEEK"
REBALANCE_NEXT_MONTH = "NEXT_MONTH"
REBALANCE_HOLD = "HOLD"

# Cost model
_TRADE_COST_BPS = 0.002   # 0.2% per trade

# Break-even thresholds
_BREAK_EVEN_IMMEDIATE_DAYS = 1
_BREAK_EVEN_THIS_WEEK_DAYS = 7
_BREAK_EVEN_REBALANCE_DAYS = 14

# Opportunity cost guard
_OPP_COST_FLOOR = 0.001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
def _load_json_file(path: Path) -> object:
    """Load JSON tolerantly. Returns None on any error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _load_log(path: Path) -> list:
    """Load ring-buffer JSON list. Returns [] on any error."""
    data = _load_json_file(path)
    if isinstance(data, list):
        return data
    return []


def _add_days_to_iso(iso_date: str, days: int) -> str:
    """Parse YYYY-MM-DD, add `days`, return YYYY-MM-DD."""
    d = date.fromisoformat(iso_date)
    result = d + timedelta(days=days)
    return result.isoformat()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RebalancingSignal:
    """Drift assessment for one portfolio position."""
    position_name: str
    target_weight: float    # desired weight 0–1
    current_weight: float   # actual weight
    drift_pct: float        # abs(current - target) / target * 100
    drift_abs: float        # abs(current - target)
    urgency: str            # CRITICAL | HIGH | MODERATE | LOW | NONE

    def to_dict(self) -> dict:
        return {
            "position_name": self.position_name,
            "target_weight": round(self.target_weight, 6),
            "current_weight": round(self.current_weight, 6),
            "drift_pct": round(self.drift_pct, 4),
            "drift_abs": round(self.drift_abs, 6),
            "urgency": self.urgency,
        }


@dataclass
class RebalancingSchedule:
    """Full rebalancing analysis for one portfolio snapshot."""
    portfolio_name: str
    total_value_usd: float

    signals: List[RebalancingSignal]

    # Aggregate drift
    max_drift_pct: float
    avg_drift_pct: float
    positions_out_of_band: int

    # Cost analysis
    estimated_rebalance_cost_usd: float
    opportunity_cost_daily_usd: float
    days_to_break_even: float

    # Decision
    should_rebalance: bool
    rebalance_urgency: str
    next_review_date: str
    next_review_days: int

    recommended_trades: List[dict]
    warnings: List[str]
    saved_to: str

    def to_dict(self) -> dict:
        return {
            "portfolio_name": self.portfolio_name,
            "total_value_usd": round(self.total_value_usd, 2),
            "signals": [s.to_dict() for s in self.signals],
            "max_drift_pct": round(self.max_drift_pct, 4),
            "avg_drift_pct": round(self.avg_drift_pct, 4),
            "positions_out_of_band": self.positions_out_of_band,
            "estimated_rebalance_cost_usd": round(self.estimated_rebalance_cost_usd, 4),
            "opportunity_cost_daily_usd": round(self.opportunity_cost_daily_usd, 4),
            "days_to_break_even": self.days_to_break_even
                if self.days_to_break_even != float("inf") else 1e18,
            "should_rebalance": self.should_rebalance,
            "rebalance_urgency": self.rebalance_urgency,
            "next_review_date": self.next_review_date,
            "next_review_days": self.next_review_days,
            "recommended_trades": self.recommended_trades,
            "warnings": self.warnings,
            "saved_to": self.saved_to,
            "generated_at": _now_iso(),
        }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def compute_signal(
    position_name: str,
    target_weight: float,
    current_weight: float,
    drift_threshold: float,
) -> RebalancingSignal:
    """Compute drift and urgency for one position.

    Parameters
    ----------
    position_name : str
    target_weight : float   desired weight 0–1
    current_weight : float  actual weight 0–1
    drift_threshold : float base threshold for urgency classification

    Returns
    -------
    RebalancingSignal
    """
    drift_abs = abs(current_weight - target_weight)
    # Guard against target=0 with a floor, matching spec: max(target, 0.001)
    drift_pct = drift_abs / max(abs(target_weight), 0.001) * 100.0

    if drift_abs > drift_threshold * 3:
        urgency = URGENCY_CRITICAL
    elif drift_abs > drift_threshold * 2:
        urgency = URGENCY_HIGH
    elif drift_abs > drift_threshold:
        urgency = URGENCY_MODERATE
    elif drift_abs > drift_threshold * 0.5:
        urgency = URGENCY_LOW
    else:
        urgency = URGENCY_NONE

    return RebalancingSignal(
        position_name=position_name,
        target_weight=target_weight,
        current_weight=current_weight,
        drift_pct=drift_pct,
        drift_abs=drift_abs,
        urgency=urgency,
    )


def schedule(
    portfolio_name: str,
    total_value_usd: float,
    positions: List[Tuple[str, float, float]],
    avg_apy_spread: float,
    drift_threshold: float,
    today_iso: str,
    data_dir: Optional[Path] = None,
) -> RebalancingSchedule:
    """Compute a full rebalancing schedule for the given portfolio snapshot.

    Parameters
    ----------
    portfolio_name : str
    total_value_usd : float   total portfolio value in USD
    positions : list of (name, target_weight, current_weight)
    avg_apy_spread : float    average APY spread between in/out-of-band positions (%)
    drift_threshold : float   base drift threshold for urgency classification
    today_iso : str           date string in YYYY-MM-DD format
    data_dir : Path, optional override for data directory

    Returns
    -------
    RebalancingSchedule
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR

    # Build signals
    signals: List[RebalancingSignal] = [
        compute_signal(name, target, current, drift_threshold)
        for name, target, current in positions
    ]

    # Aggregate drift
    if signals:
        max_drift_pct = max(s.drift_pct for s in signals)
        avg_drift_pct = sum(s.drift_pct for s in signals) / len(signals)
    else:
        max_drift_pct = 0.0
        avg_drift_pct = 0.0

    positions_out_of_band = sum(
        1 for s in signals if s.drift_abs > drift_threshold
    )

    # Cost analysis
    estimated_rebalance_cost_usd = total_value_usd * _TRADE_COST_BPS * positions_out_of_band
    opportunity_cost_daily_usd = (
        (max_drift_pct / 100.0) * total_value_usd * avg_apy_spread / 365.0
    )
    if opportunity_cost_daily_usd <= 0 or estimated_rebalance_cost_usd == 0:
        # Zero/negative opportunity cost OR nothing to rebalance → infinite break-even
        # (cost=0 means no trades needed; break-even concept doesn't apply)
        days_to_break_even = float("inf")
    else:
        days_to_break_even = estimated_rebalance_cost_usd / max(
            opportunity_cost_daily_usd, _OPP_COST_FLOOR
        )

    # Decision
    has_critical = any(s.urgency == URGENCY_CRITICAL for s in signals)
    has_high = any(s.urgency == URGENCY_HIGH for s in signals)
    should_rebalance = (
        has_critical
        or has_high
        or (days_to_break_even < _BREAK_EVEN_REBALANCE_DAYS)
    )

    if has_critical:
        rebalance_urgency = REBALANCE_IMMEDIATE
    elif has_high or days_to_break_even < _BREAK_EVEN_THIS_WEEK_DAYS:
        rebalance_urgency = REBALANCE_THIS_WEEK
    elif should_rebalance:
        rebalance_urgency = REBALANCE_NEXT_MONTH
    else:
        rebalance_urgency = REBALANCE_HOLD

    # Next review days
    urgency_to_days = {
        REBALANCE_IMMEDIATE: 1,
        REBALANCE_THIS_WEEK: 7,
        REBALANCE_NEXT_MONTH: 30,
        REBALANCE_HOLD: 90,
    }
    next_review_days = urgency_to_days[rebalance_urgency]
    next_review_date = _add_days_to_iso(today_iso, next_review_days)

    # Recommended trades for out-of-band positions
    recommended_trades: List[dict] = []
    for s in signals:
        if s.drift_abs > drift_threshold:
            action = "BUY" if s.current_weight < s.target_weight else "SELL"
            amount_usd = s.drift_abs * total_value_usd
            recommended_trades.append({
                "position": s.position_name,
                "action": action,
                "amount_usd": round(amount_usd, 2),
            })

    # Warnings
    warnings: List[str] = []
    if max_drift_pct > 30:
        warnings.append("severe portfolio drift")
    if days_to_break_even != float("inf") and days_to_break_even > 60:
        warnings.append("high rebalancing cost relative to benefit")
    if positions_out_of_band > 3:
        warnings.append("multiple positions drifted")

    saved_to = str(Path(data_dir) / _LOG_FILENAME)

    return RebalancingSchedule(
        portfolio_name=portfolio_name,
        total_value_usd=total_value_usd,
        signals=signals,
        max_drift_pct=max_drift_pct,
        avg_drift_pct=avg_drift_pct,
        positions_out_of_band=positions_out_of_band,
        estimated_rebalance_cost_usd=estimated_rebalance_cost_usd,
        opportunity_cost_daily_usd=opportunity_cost_daily_usd,
        days_to_break_even=days_to_break_even,
        should_rebalance=should_rebalance,
        rebalance_urgency=rebalance_urgency,
        next_review_date=next_review_date,
        next_review_days=next_review_days,
        recommended_trades=recommended_trades,
        warnings=warnings,
        saved_to=saved_to,
    )


def compare_portfolios(schedules: List[RebalancingSchedule]) -> List[RebalancingSchedule]:
    """Sort schedules by max_drift_pct descending (most drifted first)."""
    return sorted(schedules, key=lambda s: s.max_drift_pct, reverse=True)


def save_results(sched: RebalancingSchedule, data_dir: Optional[Path] = None) -> None:
    """Append schedule to ring-buffer log (cap 100 entries). Atomic write."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    log_path = Path(data_dir) / _LOG_FILENAME
    existing = _load_log(log_path)
    existing.append(sched.to_dict())
    trimmed = existing[-_RING_BUFFER_MAX:]
    _atomic_write_json(log_path, trimmed)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load the full ring-buffer log. Returns [] on any error."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    return _load_log(Path(data_dir) / _LOG_FILENAME)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_schedule(data_dir: Path) -> RebalancingSchedule:
    """Build a demo schedule for CLI --check / --run."""
    positions = [
        ("Aave V3 USDC", 0.40, 0.43),
        ("Compound USDC", 0.30, 0.28),
        ("Morpho Steakhouse", 0.20, 0.19),
        ("Cash", 0.10, 0.10),
    ]
    return schedule(
        portfolio_name="SPA Paper Portfolio",
        total_value_usd=100_000.0,
        positions=positions,
        avg_apy_spread=1.5,
        drift_threshold=0.05,
        today_iso="2026-06-13",
        data_dir=data_dir,
    )


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="PortfolioRebalancingScheduler (MP-713) — advisory/read-only"
    )
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute, print, and save")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR),
                        help="Override data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    sched = _demo_schedule(data_dir)

    print(json.dumps(sched.to_dict(), indent=2, ensure_ascii=False))

    if args.run:
        save_results(sched, data_dir=data_dir)
        print(f"\n✅ Saved to {sched.saved_to}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

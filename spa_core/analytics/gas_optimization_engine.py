"""Gas Optimization Engine (MP-700).

Recommends optimal gas parameters for DeFi transactions to minimize cost
while meeting urgency requirements.

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* All writes are atomic: ``tmp-file + os.replace``.
* Ring-buffer capped at :data:`MAX_ENTRIES` entries (100).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Data File
---------
``data/gas_optimization_log.json``::

    [<OptimizationResult dicts>, ...]   # ring-buffer ≤ 100

Public API
----------
``GasOptimizationEngine(data_dir="data")``

    build_quotes(base_fee_gwei, eth_price_usd, urgency) -> List[GasQuote]
    optimize(transaction_type, urgency, base_fee_gwei, eth_price_usd, gas_units) -> OptimizationResult
    compare_strategies(base_fee_gwei, eth_price_usd) -> dict
    save_results(result) -> None
    load_history() -> list
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE_NAME = "gas_optimization_log.json"
MAX_ENTRIES = 100

URGENCY_CRITICAL = "CRITICAL"
URGENCY_HIGH = "HIGH"
URGENCY_NORMAL = "NORMAL"
URGENCY_LOW = "LOW"

REC_USE_NOW = "USE_NOW"
REC_WAIT_LOW = "WAIT_LOW"
REC_BATCH_LATER = "BATCH_LATER"
REC_USE_L2 = "USE_L2"

# Standard gas units for a swap comparison
COMPARE_GAS_UNITS = 150_000

# Slow/normal/fast tip sizes (gwei)
TIP_SLOW = 0.5
TIP_NORMAL = 1.5
TIP_FAST = 3.0

# Block targets
BLOCK_SLOW = 2
BLOCK_NORMAL = 1
BLOCK_FAST = 1  # "next block"

# Confidence levels
CONF_SLOW = 0.70
CONF_NORMAL = 0.90
CONF_FAST = 0.99

# Base-fee thresholds (gwei)
THRESH_L2_HARD = 100      # NORMAL urgency: suggest L2
THRESH_WAIT_HIGH = 80     # HIGH urgency: wait
THRESH_WAIT_NORMAL = 50   # NORMAL urgency: wait
THRESH_BATCH_LOW = 30     # LOW urgency: batch if above
THRESH_L2_SAVINGS = 40    # L2 savings apply above this
THRESH_NOW = 20           # optimal_window = NOW
THRESH_30MIN = 50         # optimal_window = NEXT_30MIN
THRESH_4H = 100           # optimal_window = NEXT_4H


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GasQuote:
    """A single gas-price recommendation."""
    base_fee_gwei: float        # current EIP-1559 base fee
    priority_fee_gwei: float    # tip
    max_fee_gwei: float         # base_fee * 2 + priority_fee (EIP-1559 cap)
    estimated_cost_usd: float   # gas_units * max_fee * eth_price / 1e9
    block_target: int           # 1=next block, 2=within 2 blocks
    confidence: float           # 0.0–1.0 probability of inclusion
    recommendation: str         # "USE_NOW" | "WAIT_LOW" | "BATCH_LATER" | "USE_L2"


@dataclass
class OptimizationResult:
    """Full recommendation for a single transaction optimization."""
    transaction_type: str           # e.g. "swap", "deposit", "harvest", "rebalance"
    urgency: str                    # "CRITICAL" | "HIGH" | "NORMAL" | "LOW"
    selected_quote: GasQuote
    alternative_quotes: List[GasQuote]   # slow, normal, fast options
    l2_savings_pct: float           # estimated % savings if moved to L2
    batch_savings_pct: float        # estimated % savings if batched
    optimal_window: str             # "NOW" | "NEXT_30MIN" | "NEXT_4H" | "WEEKEND"
    reasoning: List[str]            # explanation bullets
    saved_to: str                   # path of saved log
    timestamp: str = ""             # ISO-8601 UTC set at save time


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class GasOptimizationEngine:
    """Advisory engine for optimal gas parameters."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_file = self.data_dir / DATA_FILE_NAME

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _make_quote(
        self,
        base_fee_gwei: float,
        tip_gwei: float,
        block_target: int,
        confidence: float,
        gas_units: int,
        eth_price_usd: float,
        recommendation: str,
    ) -> GasQuote:
        max_fee = base_fee_gwei * 2.0 + tip_gwei
        cost_usd = 0.0
        if gas_units > 0 and eth_price_usd > 0:
            cost_usd = gas_units * max_fee * eth_price_usd / 1e9
        return GasQuote(
            base_fee_gwei=base_fee_gwei,
            priority_fee_gwei=tip_gwei,
            max_fee_gwei=max_fee,
            estimated_cost_usd=round(cost_usd, 6),
            block_target=block_target,
            confidence=confidence,
            recommendation=recommendation,
        )

    def build_quotes(
        self,
        base_fee_gwei: float,
        eth_price_usd: float,
        urgency: str,
        gas_units: int = COMPARE_GAS_UNITS,
    ) -> List[GasQuote]:
        """Return three GasQuote objects: slow, normal, fast."""
        # Determine primary recommendation based on urgency + base_fee
        def rec(bf: float, tip: float) -> str:  # noqa: E501
            return self._recommendation_for(bf, urgency)

        slow = self._make_quote(
            base_fee_gwei, TIP_SLOW, BLOCK_SLOW, CONF_SLOW,
            gas_units, eth_price_usd, rec(base_fee_gwei, TIP_SLOW),
        )
        normal = self._make_quote(
            base_fee_gwei, TIP_NORMAL, BLOCK_NORMAL, CONF_NORMAL,
            gas_units, eth_price_usd, rec(base_fee_gwei, TIP_NORMAL),
        )
        fast = self._make_quote(
            base_fee_gwei, TIP_FAST, BLOCK_FAST, CONF_FAST,
            gas_units, eth_price_usd, rec(base_fee_gwei, TIP_FAST),
        )
        return [slow, normal, fast]

    def _recommendation_for(self, base_fee_gwei: float, urgency: str) -> str:
        """Derive the recommendation string from urgency + current base fee."""
        if urgency == URGENCY_CRITICAL:
            return REC_USE_NOW
        if urgency == URGENCY_HIGH:
            return REC_WAIT_LOW if base_fee_gwei > THRESH_WAIT_HIGH else REC_USE_NOW
        if urgency == URGENCY_NORMAL:
            if base_fee_gwei > THRESH_L2_HARD:
                return REC_USE_L2
            if base_fee_gwei > THRESH_WAIT_NORMAL:
                return REC_WAIT_LOW
            return REC_USE_NOW
        # LOW
        return REC_BATCH_LATER if base_fee_gwei > THRESH_BATCH_LOW else REC_USE_NOW

    def _l2_savings_pct(self, base_fee_gwei: float) -> float:
        if base_fee_gwei <= THRESH_L2_SAVINGS:
            return 0.0
        return round(min(95.0, (base_fee_gwei - 2.0) / base_fee_gwei * 100.0), 4)

    def _batch_savings_pct(self, urgency: str) -> float:
        return 15.0 if urgency in (URGENCY_NORMAL, URGENCY_LOW) else 0.0

    def _optimal_window(self, base_fee_gwei: float) -> str:
        if base_fee_gwei < THRESH_NOW:
            return "NOW"
        if base_fee_gwei < THRESH_30MIN:
            return "NEXT_30MIN"
        if base_fee_gwei < THRESH_4H:
            return "NEXT_4H"
        return "WEEKEND"

    def _build_reasoning(
        self,
        urgency: str,
        base_fee_gwei: float,
        recommendation: str,
        l2_savings: float,
        batch_savings: float,
        optimal_window: str,
    ) -> List[str]:
        reasons: List[str] = []
        reasons.append(f"Urgency level: {urgency}")
        reasons.append(f"Current base fee: {base_fee_gwei:.2f} gwei")
        reasons.append(f"Primary recommendation: {recommendation}")
        reasons.append(f"Optimal execution window: {optimal_window}")
        if l2_savings > 0:
            reasons.append(
                f"L2 migration could save approximately {l2_savings:.1f}% on gas costs"
            )
        if batch_savings > 0:
            reasons.append(
                f"Batching with other transactions could save ~{batch_savings:.0f}%"
            )
        if urgency == URGENCY_CRITICAL:
            reasons.append("Critical urgency: always execute immediately at fast gas price")
        elif urgency == URGENCY_HIGH and base_fee_gwei > THRESH_WAIT_HIGH:
            reasons.append(
                f"Base fee {base_fee_gwei:.0f} gwei exceeds HIGH threshold ({THRESH_WAIT_HIGH} gwei) — recommend waiting"
            )
        elif urgency == URGENCY_NORMAL and base_fee_gwei > THRESH_L2_HARD:
            reasons.append(
                f"Base fee {base_fee_gwei:.0f} gwei very high — L2 strongly preferred for non-urgent transactions"
            )
        elif urgency == URGENCY_LOW and base_fee_gwei > THRESH_BATCH_LOW:
            reasons.append(
                "Low urgency + elevated gas: batch this transaction with upcoming operations"
            )
        return reasons

    def optimize(
        self,
        transaction_type: str,
        urgency: str,
        base_fee_gwei: float,
        eth_price_usd: float,
        gas_units: int,
    ) -> OptimizationResult:
        """Return a full OptimizationResult for the given parameters."""
        quotes = self.build_quotes(base_fee_gwei, eth_price_usd, urgency, gas_units)
        slow_q, normal_q, fast_q = quotes

        # Pick selected quote based on urgency
        if urgency == URGENCY_CRITICAL:
            selected = fast_q
        elif urgency == URGENCY_HIGH:
            selected = normal_q
        elif urgency == URGENCY_NORMAL:
            selected = normal_q
        else:  # LOW
            selected = slow_q

        recommendation = self._recommendation_for(base_fee_gwei, urgency)
        l2_savings = self._l2_savings_pct(base_fee_gwei)
        batch_savings = self._batch_savings_pct(urgency)
        window = self._optimal_window(base_fee_gwei)

        reasoning = self._build_reasoning(
            urgency, base_fee_gwei, recommendation,
            l2_savings, batch_savings, window,
        )

        return OptimizationResult(
            transaction_type=transaction_type,
            urgency=urgency,
            selected_quote=selected,
            alternative_quotes=quotes,
            l2_savings_pct=l2_savings,
            batch_savings_pct=batch_savings,
            optimal_window=window,
            reasoning=reasoning,
            saved_to=str(self.data_file),
        )

    def compare_strategies(
        self,
        base_fee_gwei: float,
        eth_price_usd: float,
    ) -> Dict[str, object]:
        """Compare EXECUTE_NOW vs WAIT vs L2 vs BATCH for a standard swap."""
        gas_units = COMPARE_GAS_UNITS

        def cost(bf: float, tip: float) -> float:
            max_fee = bf * 2.0 + tip
            if eth_price_usd <= 0:
                return 0.0
            return gas_units * max_fee * eth_price_usd / 1e9

        now_cost = cost(base_fee_gwei, TIP_NORMAL)
        # WAIT: assume 20% base-fee reduction
        wait_bf = base_fee_gwei * 0.8
        wait_cost = cost(wait_bf, TIP_NORMAL)
        # L2: ~2 gwei effective base fee
        l2_cost = cost(2.0, 0.1)
        # BATCH: 15% discount on current cost
        batch_cost = now_cost * 0.85

        return {
            "EXECUTE_NOW": {
                "estimated_cost_usd": round(now_cost, 6),
                "base_fee_gwei": base_fee_gwei,
                "description": "Execute immediately at current gas price",
            },
            "WAIT": {
                "estimated_cost_usd": round(wait_cost, 6),
                "base_fee_gwei": round(wait_bf, 2),
                "description": "Wait for ~20% base-fee reduction (estimated)",
            },
            "L2": {
                "estimated_cost_usd": round(l2_cost, 6),
                "base_fee_gwei": 2.0,
                "description": "Execute on L2 (Arbitrum / Optimism / Base)",
            },
            "BATCH": {
                "estimated_cost_usd": round(batch_cost, 6),
                "base_fee_gwei": base_fee_gwei,
                "description": "Batch with other pending transactions (~15% saving)",
            },
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(self, result: OptimizationResult) -> None:
        """Append result to ring-buffer log (max MAX_ENTRIES)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        existing: list = []
        if self.data_file.exists():
            try:
                existing = json.loads(self.data_file.read_text())
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        entry = _result_to_dict(result)
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()

        existing.append(entry)
        # Ring-buffer cap
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> list:
        """Return list of saved optimization results."""
        if not self.data_file.exists():
            return []
        try:
            data = json.loads(self.data_file.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _quote_to_dict(q: GasQuote) -> dict:
    return asdict(q)


def _result_to_dict(r: OptimizationResult) -> dict:
    d = {
        "transaction_type": r.transaction_type,
        "urgency": r.urgency,
        "selected_quote": _quote_to_dict(r.selected_quote),
        "alternative_quotes": [_quote_to_dict(q) for q in r.alternative_quotes],
        "l2_savings_pct": r.l2_savings_pct,
        "batch_savings_pct": r.batch_savings_pct,
        "optimal_window": r.optimal_window,
        "reasoning": r.reasoning,
        "saved_to": r.saved_to,
        "timestamp": r.timestamp,
    }
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="GasOptimizationEngine CLI")
    parser.add_argument("--base-fee", type=float, default=30.0, help="Base fee in gwei")
    parser.add_argument("--eth-price", type=float, default=3000.0, help="ETH price in USD")
    parser.add_argument("--urgency", default="NORMAL",
                        choices=["CRITICAL", "HIGH", "NORMAL", "LOW"])
    parser.add_argument("--tx-type", default="rebalance")
    parser.add_argument("--gas-units", type=int, default=COMPARE_GAS_UNITS)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--check", action="store_true", help="Print without saving")
    parser.add_argument("--run", action="store_true", help="Compute and save")
    args = parser.parse_args()

    engine = GasOptimizationEngine(data_dir=args.data_dir)
    result = engine.optimize(args.tx_type, args.urgency, args.base_fee, args.eth_price, args.gas_units)
    print(json.dumps(_result_to_dict(result), indent=2))
    if args.run:
        engine.save_results(result)
        print(f"\nSaved to {engine.data_file}")

    comparison = engine.compare_strategies(args.base_fee, args.eth_price)
    print("\nStrategy Comparison:")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    _cli()

# spa_core/analytics/yield_route_optimizer.py
# MP-723 — YieldRouteOptimizer (pure stdlib, advisory/read-only)
#
# Greedy capital routing across multiple yield opportunities to maximize
# risk-adjusted return subject to per-slot min/max allocation constraints
# and a global max-concentration cap.
#
# All writes are atomic (tmp + os.replace). Ring-buffer cap: 100 entries.
# LLM_FORBIDDEN: this module must never invoke LLM agents.

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

DATA_FILE = Path("data/yield_route_log.json")
MAX_ENTRIES = 100

DEFAULT_MAX_CONCENTRATION = 0.40  # 40%
DEFAULT_RISK_BUDGET = 70.0        # weighted risk score ceiling


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AllocationSlot:
    """Describes a single yield opportunity / allocation target."""
    name: str
    apy: float
    risk_score: float           # 0–100
    min_allocation_pct: float   # minimum % of portfolio (0 if no minimum)
    max_allocation_pct: float   # maximum % of portfolio (100 if no max, but capped)
    liquidity_score: float      # 0–100 (100 = highly liquid)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RouteAllocation:
    """Single slot's allocation within an OptimalRoute."""
    slot: AllocationSlot
    allocated_pct: float
    allocated_usd: float
    expected_yield_usd: float   # allocated_usd * apy / 100
    risk_contribution: float    # (allocated_pct / 100) * risk_score

    def to_dict(self) -> dict:
        return {
            "slot": self.slot.to_dict(),
            "allocated_pct": self.allocated_pct,
            "allocated_usd": self.allocated_usd,
            "expected_yield_usd": self.expected_yield_usd,
            "risk_contribution": self.risk_contribution,
        }


@dataclass
class OptimalRoute:
    """Complete routing result for a capital allocation."""
    total_capital_usd: float
    allocations: List[RouteAllocation]

    # Portfolio metrics
    total_expected_yield_usd: float = 0.0
    weighted_apy: float = 0.0
    weighted_risk: float = 0.0
    risk_adjusted_return: float = 0.0
    portfolio_hhi: float = 0.0

    # Constraints
    all_constraints_met: bool = True
    constraint_violations: List[str] = field(default_factory=list)

    # Comparison to naive equal-weight baseline
    equal_weight_apy: float = 0.0
    improvement_vs_equal_pct: float = 0.0

    route_label: str = "OPTIMAL"
    saved_to: str = ""

    def to_dict(self) -> dict:
        return {
            "total_capital_usd": self.total_capital_usd,
            "allocations": [a.to_dict() for a in self.allocations],
            "total_expected_yield_usd": self.total_expected_yield_usd,
            "weighted_apy": self.weighted_apy,
            "weighted_risk": self.weighted_risk,
            "risk_adjusted_return": self.risk_adjusted_return,
            "portfolio_hhi": self.portfolio_hhi,
            "all_constraints_met": self.all_constraints_met,
            "constraint_violations": self.constraint_violations,
            "equal_weight_apy": self.equal_weight_apy,
            "improvement_vs_equal_pct": self.improvement_vs_equal_pct,
            "route_label": self.route_label,
            "saved_to": self.saved_to,
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_constraints(slots: List[AllocationSlot]) -> List[str]:
    """Return list of constraint violation strings (empty = all valid)."""
    violations: List[str] = []

    total_min = sum(s.min_allocation_pct for s in slots)
    if total_min > 100.0 + 1e-9:
        violations.append(
            f"Sum of min_allocation_pct ({total_min:.4f}%) exceeds 100%."
        )

    for s in slots:
        if s.max_allocation_pct < s.min_allocation_pct - 1e-9:
            violations.append(
                f"Slot '{s.name}': max_allocation_pct ({s.max_allocation_pct}%) "
                f"< min_allocation_pct ({s.min_allocation_pct}%)."
            )

    return violations


# ---------------------------------------------------------------------------
# Greedy optimizer
# ---------------------------------------------------------------------------

def optimize_route(
    slots: List[AllocationSlot],
    total_capital_usd: float,
    max_concentration: float = DEFAULT_MAX_CONCENTRATION,
    risk_budget: float = DEFAULT_RISK_BUDGET,
) -> OptimalRoute:
    """
    Greedy capital routing algorithm:

    1. Assign min_allocation_pct to every slot.
    2. Compute remaining = 100 - sum(mins).
    3. Sort slots by risk_adjusted_apy = apy / (1 + risk_score/100) descending.
    4. Fill highest-scoring slots first, up to their effective cap
       (min(max_allocation_pct, max_concentration*100)).
    5. Normalize so allocations sum exactly to 100%.
    6. Build RouteAllocation objects and portfolio metrics.
    """
    if not slots:
        return OptimalRoute(
            total_capital_usd=total_capital_usd,
            allocations=[],
            all_constraints_met=True,
            route_label="OPTIMAL",
        )

    n = len(slots)
    max_conc_pct = max_concentration * 100.0  # convert to %

    # Effective cap per slot
    effective_caps = [
        min(s.max_allocation_pct, max_conc_pct)
        for s in slots
    ]

    # Step 1: start with min allocations
    alloc = [s.min_allocation_pct for s in slots]

    # Step 2: remaining budget
    remaining = 100.0 - sum(alloc)

    # Step 3: sort indices by risk-adjusted APY descending
    def risk_adj_apy(slot: AllocationSlot) -> float:
        return slot.apy / (1.0 + slot.risk_score / 100.0)

    order = sorted(range(n), key=lambda i: risk_adj_apy(slots[i]), reverse=True)

    # Step 4: fill in order
    for i in order:
        if remaining <= 1e-12:
            break
        room = effective_caps[i] - alloc[i]
        if room <= 0:
            continue
        add = min(room, remaining)
        alloc[i] += add
        remaining -= add

    # Step 5: normalize to exactly 100%
    total_alloc = sum(alloc)
    if total_alloc > 0:
        factor = 100.0 / total_alloc
        alloc = [a * factor for a in alloc]

    # Step 6: build RouteAllocations
    route_allocs: List[RouteAllocation] = []
    for i, slot in enumerate(slots):
        pct = alloc[i]
        usd = total_capital_usd * pct / 100.0
        expected_yield = usd * slot.apy / 100.0
        risk_contrib = (pct / 100.0) * slot.risk_score
        route_allocs.append(RouteAllocation(
            slot=slot,
            allocated_pct=pct,
            allocated_usd=usd,
            expected_yield_usd=expected_yield,
            risk_contribution=risk_contrib,
        ))

    # Portfolio metrics
    total_yield = sum(a.expected_yield_usd for a in route_allocs)
    w_apy = sum(a.allocated_pct / 100.0 * a.slot.apy for a in route_allocs)
    w_risk = sum(a.risk_contribution for a in route_allocs)
    rar = w_apy / (1.0 + w_risk / 100.0)
    hhi = sum((a.allocated_pct / 100.0) ** 2 for a in route_allocs)

    # Equal-weight baseline
    eq_apy = sum(s.apy for s in slots) / n
    if eq_apy != 0:
        improvement = (w_apy - eq_apy) / eq_apy * 100.0
    else:
        improvement = 0.0

    # Constraint violations
    violations: List[str] = []
    for ra in route_allocs:
        if ra.allocated_pct > max_conc_pct + 1e-9:
            violations.append(
                f"Slot '{ra.slot.name}' allocated {ra.allocated_pct:.4f}% "
                f"> max_concentration {max_conc_pct:.1f}%."
            )
    if w_risk > risk_budget + 1e-9:
        violations.append(
            f"Weighted risk {w_risk:.4f} exceeds risk_budget {risk_budget}."
        )

    all_ok = len(violations) == 0

    # Route label
    if all_ok and improvement > 0:
        label = "OPTIMAL"
    elif all_ok:
        label = "NEAR_OPTIMAL"
    else:
        label = "CONSTRAINED"

    route = OptimalRoute(
        total_capital_usd=total_capital_usd,
        allocations=route_allocs,
        total_expected_yield_usd=total_yield,
        weighted_apy=w_apy,
        weighted_risk=w_risk,
        risk_adjusted_return=rar,
        portfolio_hhi=hhi,
        all_constraints_met=all_ok,
        constraint_violations=violations,
        equal_weight_apy=eq_apy,
        improvement_vs_equal_pct=improvement,
        route_label=label,
        saved_to="",
    )
    return route


# ---------------------------------------------------------------------------
# Persistence (atomic, ring-buffer 100)
# ---------------------------------------------------------------------------

def _resolve_data_file(data_file: Optional[Path] = None) -> Path:
    return data_file if data_file is not None else DATA_FILE


def save_results(route: OptimalRoute, data_file: Optional[Path] = None) -> str:
    """Append route result to ring-buffer log. Returns path written."""
    path = _resolve_data_file(data_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path, "r") as f:
            history = json.load(f)
        if not isinstance(history, list):
            history = []
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    entry = route.to_dict()
    entry["_saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    history.append(entry)

    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]

    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(history, f, indent=2)
    os.replace(tmp, path)

    route.saved_to = str(path)
    return str(path)


def load_history(data_file: Optional[Path] = None) -> list:
    """Load full route history from disk."""
    path = _resolve_data_file(data_file)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-723 YieldRouteOptimizer")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--max-concentration", type=float, default=0.40)
    parser.add_argument("--risk-budget", type=float, default=70.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    # Example slots
    demo_slots = [
        AllocationSlot("Aave V3",   apy=3.5,  risk_score=15, min_allocation_pct=5,  max_allocation_pct=40, liquidity_score=95),
        AllocationSlot("Compound",  apy=4.8,  risk_score=18, min_allocation_pct=5,  max_allocation_pct=40, liquidity_score=90),
        AllocationSlot("Morpho",    apy=6.5,  risk_score=25, min_allocation_pct=0,  max_allocation_pct=40, liquidity_score=85),
        AllocationSlot("Yearn V3",  apy=8.0,  risk_score=35, min_allocation_pct=0,  max_allocation_pct=25, liquidity_score=75),
        AllocationSlot("Cash",      apy=0.0,  risk_score=0,  min_allocation_pct=5,  max_allocation_pct=20, liquidity_score=100),
    ]

    route = optimize_route(
        demo_slots,
        total_capital_usd=args.capital,
        max_concentration=args.max_concentration,
        risk_budget=args.risk_budget,
    )

    print("\n=== YieldRouteOptimizer (MP-723) ===")
    print(f"Capital:         ${route.total_capital_usd:,.0f}")
    print(f"Weighted APY:    {route.weighted_apy:.4f}%")
    print(f"Risk-Adj Return: {route.risk_adjusted_return:.4f}%")
    print(f"HHI:             {route.portfolio_hhi:.4f}")
    print(f"Equal-wt APY:    {route.equal_weight_apy:.4f}%")
    print(f"Improvement:     {route.improvement_vs_equal_pct:+.2f}%")
    print(f"Label:           {route.route_label}")
    print(f"Constraints met: {route.all_constraints_met}")
    print("\nAllocations:")
    for ra in route.allocations:
        print(f"  {ra.slot.name:20s}  {ra.allocated_pct:6.2f}%  ${ra.allocated_usd:>12,.0f}  yield ${ra.expected_yield_usd:,.0f}/yr")

    if args.save:
        path = save_results(route)
        print(f"\nSaved → {path}")

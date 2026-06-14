"""MP-689 RebalanceCostOptimizer
=================================
Optimize rebalancing decisions by computing the net benefit of moving capital
from one protocol to another, weighed against the combined gas + slippage cost.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas.
* Advisory / read-only — never modifies allocator / risk / execution.
* Atomic writes: tmp-file + os.replace for all JSON persistence.
* LLM_FORBIDDEN domain: not imported from risk / execution / monitoring.
* Ring-buffer cap: MAX_ENTRIES per log file.

Break-Even Formula
------------------
::

    apy_improvement_pct = target_apy - current_apy
    annual_gain_usd     = move_amount_usd * apy_improvement_pct / 100
    total_cost_usd      = gas_cost_usd + slippage_cost_usd

    break_even_days = inf                            if annual_gain_usd <= 0
                    = total_cost / (annual_gain / 365)   otherwise

    net_annual_benefit_usd = annual_gain_usd - total_cost_usd
    roi_pct                = net_annual_benefit / total_cost * 100
                             (0.0 if total_cost == 0)

Verdict Rules
-------------
SKIP   — apy_improvement <= 0  OR  break_even_days > 180
DEFER  — 60 < break_even_days <= 180
EXECUTE— break_even_days <= 60

Priority
--------
Among EXECUTE decisions, priority 1 = highest annual_gain_usd.
DEFER and SKIP decisions carry priority 0 (not ranked).

Public API
----------
``RebalanceCostOptimizer(data_file=DATA_FILE)``

  analyze(candidate)      → RebalanceDecision
  build_plan(candidates)  → RebalancePlan
  save_results(decisions) → None  (atomic ring-buffer write)
  load_history()          → List[dict]
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/rebalance_cost_log.json")
MAX_ENTRIES = 100

# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RebalanceCandidate:
    """Input: one candidate rebalance move."""
    position_id: str
    from_protocol: str
    to_protocol: str
    move_amount_usd: float
    current_apy_pct: float       # APY currently earned (%)
    target_apy_pct: float        # APY available in target position (%)
    gas_cost_usd: float          # estimated gas cost for this move
    slippage_cost_usd: float     # estimated slippage cost
    lock_period_days: int        # days before capital can be moved again (0=liquid)


@dataclass
class RebalanceDecision:
    """Output: analysis of one rebalance candidate."""
    position_id: str
    from_protocol: str
    to_protocol: str
    move_amount_usd: float
    apy_improvement_pct: float   # target_apy - current_apy
    annual_gain_usd: float       # move_amount * apy_improvement / 100
    total_cost_usd: float        # gas + slippage
    break_even_days: float       # days to recoup costs (inf if no improvement)
    net_annual_benefit_usd: float  # annual_gain - total_cost
    roi_pct: float               # net_benefit / total_cost * 100
    verdict: str                 # EXECUTE / DEFER / SKIP
    priority: int                # 1 = highest among EXECUTE; 0 otherwise
    rationale: str


@dataclass
class RebalancePlan:
    """Aggregated output for a batch of rebalance candidates."""
    candidates: List[RebalanceDecision]
    total_cost_usd: float           # sum of EXECUTE decision costs
    total_annual_gain_usd: float    # sum of EXECUTE annual gains
    net_annual_benefit_usd: float   # total_annual_gain - total_cost
    execution_order: List[str]      # position_ids of EXECUTE decisions, by priority
    should_rebalance: bool          # True if any EXECUTE exists


# ──────────────────────────────────────────────────────────────────────────────
# Optimizer
# ──────────────────────────────────────────────────────────────────────────────

class RebalanceCostOptimizer:
    """Compute break-even rebalance decisions and build execution plans."""

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ── private helpers ───────────────────────────────────────────────────────

    def _break_even_days(
        self, annual_gain_usd: float, total_cost_usd: float
    ) -> float:
        """Days to recoup total_cost from annual yield gain.
        Returns float('inf') when gain <= 0."""
        if annual_gain_usd <= 0:
            return float("inf")
        daily_gain = annual_gain_usd / 365.0
        return total_cost_usd / daily_gain

    def _verdict(
        self, apy_improvement_pct: float, break_even_days: float
    ) -> str:
        """Classify the move decision."""
        if apy_improvement_pct <= 0 or break_even_days > 180:
            return "SKIP"
        if break_even_days > 60:
            return "DEFER"
        return "EXECUTE"

    def _rationale(
        self,
        verdict: str,
        current_apy: float,
        target_apy: float,
        apy_improvement: float,
        break_even_days: float,
        annual_gain_usd: float,
    ) -> str:
        """Generate human-readable rationale string."""
        if verdict == "SKIP":
            be_str = "∞" if break_even_days == float("inf") else f"{break_even_days:.0f}d"
            return (
                f"No benefit: {current_apy:.1f}% → {target_apy:.1f}% APY, "
                f"{be_str} break-even"
            )
        if verdict == "DEFER":
            return f"Long payback: {break_even_days:.0f} days to break even"
        # EXECUTE
        return (
            f"Execute: +{apy_improvement:.2f}% APY, "
            f"{break_even_days:.0f}d payback, "
            f"+${annual_gain_usd:.0f}/yr"
        )

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(self, candidate: RebalanceCandidate) -> RebalanceDecision:
        """Produce a RebalanceDecision from a single RebalanceCandidate."""
        improvement = candidate.target_apy_pct - candidate.current_apy_pct
        annual_gain = candidate.move_amount_usd * improvement / 100.0
        total_cost = candidate.gas_cost_usd + candidate.slippage_cost_usd
        be_days = self._break_even_days(annual_gain, total_cost)
        net_benefit = annual_gain - total_cost
        roi = (net_benefit / total_cost * 100.0) if total_cost > 0 else 0.0
        verdict = self._verdict(improvement, be_days)
        rationale = self._rationale(
            verdict,
            candidate.current_apy_pct,
            candidate.target_apy_pct,
            improvement,
            be_days,
            annual_gain,
        )
        return RebalanceDecision(
            position_id=candidate.position_id,
            from_protocol=candidate.from_protocol,
            to_protocol=candidate.to_protocol,
            move_amount_usd=candidate.move_amount_usd,
            apy_improvement_pct=improvement,
            annual_gain_usd=annual_gain,
            total_cost_usd=total_cost,
            break_even_days=be_days,
            net_annual_benefit_usd=net_benefit,
            roi_pct=roi,
            verdict=verdict,
            priority=0,      # set later by build_plan
            rationale=rationale,
        )

    def build_plan(
        self, candidates: List[RebalanceCandidate]
    ) -> RebalancePlan:
        """Analyze all candidates and produce an ordered execution plan."""
        if not candidates:
            return RebalancePlan(
                candidates=[],
                total_cost_usd=0.0,
                total_annual_gain_usd=0.0,
                net_annual_benefit_usd=0.0,
                execution_order=[],
                should_rebalance=False,
            )

        decisions = [self.analyze(c) for c in candidates]

        # Assign priority to EXECUTE decisions (1 = highest annual gain)
        execute_decisions = [d for d in decisions if d.verdict == "EXECUTE"]
        execute_decisions.sort(key=lambda d: d.annual_gain_usd, reverse=True)
        for rank, dec in enumerate(execute_decisions, start=1):
            dec.priority = rank

        # Sort all decisions: EXECUTE first (by priority), then DEFER, then SKIP
        def _sort_key(d: RebalanceDecision):
            if d.verdict == "EXECUTE":
                return (0, d.priority)
            if d.verdict == "DEFER":
                return (1, 0)
            return (2, 0)

        decisions.sort(key=_sort_key)

        # Aggregates over EXECUTE only
        total_cost = sum(d.total_cost_usd for d in execute_decisions)
        total_gain = sum(d.annual_gain_usd for d in execute_decisions)
        net_benefit = total_gain - total_cost
        execution_order = [d.position_id for d in execute_decisions]
        should_rebalance = bool(execute_decisions)

        return RebalancePlan(
            candidates=decisions,
            total_cost_usd=total_cost,
            total_annual_gain_usd=total_gain,
            net_annual_benefit_usd=net_benefit,
            execution_order=execution_order,
            should_rebalance=should_rebalance,
        )

    # ── persistence ───────────────────────────────────────────────────────────

    def save_results(self, decisions: List[RebalanceDecision]) -> None:
        """Append decisions to the ring-buffer log (capped at MAX_ENTRIES)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: List[dict] = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        for d in decisions:
            # Store float("inf") as -1 for JSON serialisability
            be = -1 if d.break_even_days == float("inf") else d.break_even_days
            existing.append(
                {
                    "timestamp": time.time(),
                    "position_id": d.position_id,
                    "from_protocol": d.from_protocol,
                    "to_protocol": d.to_protocol,
                    "move_amount_usd": d.move_amount_usd,
                    "apy_improvement_pct": d.apy_improvement_pct,
                    "annual_gain_usd": d.annual_gain_usd,
                    "total_cost_usd": d.total_cost_usd,
                    "break_even_days": be,
                    "net_annual_benefit_usd": d.net_annual_benefit_usd,
                    "roi_pct": d.roi_pct,
                    "verdict": d.verdict,
                    "priority": d.priority,
                    "rationale": d.rationale,
                }
            )

        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return persisted log entries, or [] if file is missing/corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

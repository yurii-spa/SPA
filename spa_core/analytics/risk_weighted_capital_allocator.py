"""RiskWeightedCapitalAllocator (MP-728).

Allocates capital using risk-weighted assets (RWA) approach — higher-risk
positions receive a haircut on effective capital so that total risk exposure
stays within a configurable budget.

Design constraints:
- Pure stdlib only — no external dependencies.
- Advisory / read-only (never touches allocator / risk / execution).
- Atomic JSON writes via tmp + os.replace.
- Ring-buffer history capped at 100 entries.

Public API
----------
    risk_weight(risk_score) -> float
    compute_rwa(positions, total_capital_usd, risk_budget_pct) -> RWAAllocationResult
    compare_budgets(total_capital_usd, positions, budgets) -> dict
    save_results(result, data_dir) -> str
    load_history(data_dir) -> list
"""
from __future__ import annotations

import json
import os
import tempfile
from copy import copy as _shallow_copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HISTORY_MAX: int = 100
_LOG_FILE: str = "rwa_allocation_log.json"
_DEFAULT_DATA_DIR: str = "data"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RWAPosition:
    """A single portfolio position with RWA calculations."""

    name: str
    protocol: str
    risk_score: float              # 0–100
    apy: float
    requested_allocation_pct: float  # desired % of portfolio (input)

    # Computed fields (filled by compute_rwa)
    risk_weight: float = 0.0          # 1.0 + risk_score/100
    rwa_pct: float = 0.0              # requested_allocation_pct * risk_weight
    effective_allocation_pct: float = 0.0  # actual % after risk budgeting, sums to 100
    effective_usd: float = 0.0             # effective_allocation_pct/100 * total_capital


@dataclass
class RWAAllocationResult:
    """Full result of a risk-weighted capital allocation run."""

    total_capital_usd: float
    risk_budget_pct: float               # max total RWA as % of capital
    positions: List[RWAPosition]

    # Portfolio stats
    total_rwa_pct: float = 0.0           # sum of all rwa_pct
    utilization_pct: float = 0.0         # total_rwa / risk_budget * 100
    weighted_apy: float = 0.0            # sum(effective_pct/100 * apy)
    weighted_risk: float = 0.0           # sum(effective_pct/100 * risk_score)

    # vs naive equal-weight
    rwa_apy_improvement: float = 0.0     # weighted_apy - equal_weight_apy

    # Status
    within_budget: bool = True           # total_rwa <= risk_budget
    budget_headroom_pct: float = 0.0     # risk_budget - total_rwa (can be negative)

    scaling_applied: bool = False        # True when positions were scaled to fit budget

    allocation_label: str = "OPTIMAL"   # "OPTIMAL" | "SCALED" | "OVER_BUDGET"
    recommendations: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def risk_weight(risk_score: float) -> float:
    """Return the risk-weight multiplier for a given risk score.

    Formula: 1.0 + risk_score / 100  →  range [1.0, 2.0] for scores 0–100.

    Parameters
    ----------
    risk_score:
        Risk score in [0, 100].

    Returns
    -------
    float
        Risk weight in [1.0, 2.0].
    """
    return 1.0 + float(risk_score) / 100.0


def _build_position(
    src: RWAPosition,
    requested_allocation_pct: Optional[float] = None,
) -> RWAPosition:
    """Return a fresh RWAPosition copy optionally overriding requested_allocation_pct."""
    req = src.requested_allocation_pct if requested_allocation_pct is None else requested_allocation_pct
    rw = risk_weight(src.risk_score)
    return RWAPosition(
        name=src.name,
        protocol=src.protocol,
        risk_score=src.risk_score,
        apy=src.apy,
        requested_allocation_pct=req,
        risk_weight=rw,
        rwa_pct=req * rw,
        effective_allocation_pct=0.0,
        effective_usd=0.0,
    )


def _recommendations(
    utilization_pct: float,
    positions: List[RWAPosition],
    rwa_apy_improvement: float,
) -> List[str]:
    recs: List[str] = []
    if utilization_pct > 90.0:
        recs.append("Near risk budget limit")
    if any(p.risk_score > 80 for p in positions):
        recs.append("High-risk positions present")
    if rwa_apy_improvement < 0:
        recs.append("Risk weighting reduced APY vs equal-weight")
    return recs


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_rwa(
    positions: List[RWAPosition],
    total_capital_usd: float,
    risk_budget_pct: float,
) -> RWAAllocationResult:
    """Compute risk-weighted capital allocation.

    Steps
    -----
    1. For each position compute risk_weight = 1 + score/100 and
       rwa_pct = requested_allocation_pct * risk_weight.
    2. Sum total_rwa over all positions.
    3. If total_rwa > risk_budget_pct scale all requested_allocation_pct
       uniformly by scale_factor = risk_budget_pct / total_rwa and recompute
       rwa_pct.  scaling_applied is set to True.
    4. Normalize effective_allocation_pct so that Σ = 100 %.
    5. Derive effective_usd = effective_allocation_pct / 100 * total_capital.
    6. Compute portfolio statistics and assemble result.

    Parameters
    ----------
    positions:
        List of RWAPosition objects (not mutated).
    total_capital_usd:
        Total portfolio capital in USD.
    risk_budget_pct:
        Maximum permitted aggregate RWA as a percentage (e.g. 150 means 1.5×
        the nominal capital is the risk budget).

    Returns
    -------
    RWAAllocationResult
    """
    if not positions:
        return RWAAllocationResult(
            total_capital_usd=total_capital_usd,
            risk_budget_pct=risk_budget_pct,
            positions=[],
            total_rwa_pct=0.0,
            utilization_pct=0.0,
            weighted_apy=0.0,
            weighted_risk=0.0,
            rwa_apy_improvement=0.0,
            within_budget=True,
            budget_headroom_pct=risk_budget_pct,
            scaling_applied=False,
            allocation_label="OPTIMAL",
            recommendations=[],
            saved_to="",
        )

    # Step 1 – initial copies with risk_weight and rwa_pct computed
    pos = [_build_position(p) for p in positions]

    # Step 2 – total RWA
    total_rwa = sum(p.rwa_pct for p in pos)

    # Step 3 – scaling
    scaling_applied = False
    if risk_budget_pct == 0.0:
        # Degenerate: zero budget, scale everything to zero
        for p in pos:
            p.requested_allocation_pct = 0.0
            p.rwa_pct = 0.0
        total_rwa = 0.0
        scaling_applied = True
    elif total_rwa > risk_budget_pct:
        scale_factor = risk_budget_pct / total_rwa
        for p in pos:
            p.requested_allocation_pct *= scale_factor
            p.rwa_pct = p.requested_allocation_pct * p.risk_weight
        total_rwa = sum(p.rwa_pct for p in pos)  # should ≈ risk_budget_pct
        scaling_applied = True

    # Step 4 – normalize effective_allocation_pct to sum to 100 %
    total_requested = sum(p.requested_allocation_pct for p in pos)
    n = len(pos)
    for p in pos:
        if total_requested > 0:
            p.effective_allocation_pct = p.requested_allocation_pct / total_requested * 100.0
        else:
            # Degenerate (e.g. budget=0): distribute equally so sum=100 for
            # informational purposes; effective_usd will be 0 anyway when
            # all requested_pct are 0 (total_capital effectively 0 in that context)
            p.effective_allocation_pct = 100.0 / n if n > 0 else 0.0

    # Step 5 – effective USD
    for p in pos:
        p.effective_usd = p.effective_allocation_pct / 100.0 * total_capital_usd

    # Step 6 – portfolio statistics
    weighted_apy = sum(p.effective_allocation_pct / 100.0 * p.apy for p in pos)
    weighted_risk = sum(p.effective_allocation_pct / 100.0 * p.risk_score for p in pos)
    equal_weight_apy = sum(p.apy for p in pos) / n if n > 0 else 0.0
    rwa_apy_improvement = weighted_apy - equal_weight_apy

    within_budget = total_rwa <= risk_budget_pct
    budget_headroom_pct = risk_budget_pct - total_rwa
    utilization_pct = (
        total_rwa / risk_budget_pct * 100.0 if risk_budget_pct > 0 else 0.0
    )

    # Allocation label
    if within_budget and not scaling_applied:
        allocation_label = "OPTIMAL"
    elif scaling_applied:
        allocation_label = "SCALED"
    else:
        allocation_label = "OVER_BUDGET"

    recommendations = _recommendations(utilization_pct, pos, rwa_apy_improvement)

    return RWAAllocationResult(
        total_capital_usd=total_capital_usd,
        risk_budget_pct=risk_budget_pct,
        positions=pos,
        total_rwa_pct=total_rwa,
        utilization_pct=utilization_pct,
        weighted_apy=weighted_apy,
        weighted_risk=weighted_risk,
        rwa_apy_improvement=rwa_apy_improvement,
        within_budget=within_budget,
        budget_headroom_pct=budget_headroom_pct,
        scaling_applied=scaling_applied,
        allocation_label=allocation_label,
        recommendations=recommendations,
        saved_to="",
    )


def compare_budgets(
    total_capital_usd: float,
    positions: List[RWAPosition],
    budgets: List[float],
) -> Dict[float, RWAAllocationResult]:
    """Run compute_rwa for multiple budget values and return results keyed by budget.

    Parameters
    ----------
    total_capital_usd:
        Total portfolio capital in USD.
    positions:
        Input positions (original requested allocations used for each run).
    budgets:
        List of risk_budget_pct values to test.

    Returns
    -------
    dict
        Mapping budget_pct → RWAAllocationResult.
    """
    return {b: compute_rwa(positions, total_capital_usd, b) for b in budgets}


# ---------------------------------------------------------------------------
# Persistence (advisory, atomic ring-buffer)
# ---------------------------------------------------------------------------

def _position_to_dict(p: RWAPosition) -> dict:
    return {
        "name": p.name,
        "protocol": p.protocol,
        "risk_score": p.risk_score,
        "apy": p.apy,
        "requested_allocation_pct": p.requested_allocation_pct,
        "risk_weight": p.risk_weight,
        "rwa_pct": p.rwa_pct,
        "effective_allocation_pct": p.effective_allocation_pct,
        "effective_usd": p.effective_usd,
    }


def _result_to_dict(r: RWAAllocationResult) -> dict:
    return {
        "total_capital_usd": r.total_capital_usd,
        "risk_budget_pct": r.risk_budget_pct,
        "positions": [_position_to_dict(p) for p in r.positions],
        "total_rwa_pct": r.total_rwa_pct,
        "utilization_pct": r.utilization_pct,
        "weighted_apy": r.weighted_apy,
        "weighted_risk": r.weighted_risk,
        "rwa_apy_improvement": r.rwa_apy_improvement,
        "within_budget": r.within_budget,
        "budget_headroom_pct": r.budget_headroom_pct,
        "scaling_applied": r.scaling_applied,
        "allocation_label": r.allocation_label,
        "recommendations": list(r.recommendations),
        "saved_to": r.saved_to,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(
    result: RWAAllocationResult,
    data_dir: str = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically append result to ring-buffer JSON log (max 100 entries).

    Parameters
    ----------
    result:
        The RWAAllocationResult to persist.
    data_dir:
        Directory for the log file (created if absent).

    Returns
    -------
    str
        Absolute path of the written file.
    """
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    log_path = data_path / _LOG_FILE

    history: list = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                history = json.load(fh)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []

    entry = _result_to_dict(result)
    history.append(entry)
    if len(history) > _HISTORY_MAX:
        history = history[-_HISTORY_MAX:]

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(dir=data_path, prefix=".rwa_alloc_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    result.saved_to = str(log_path.resolve())
    return result.saved_to


def load_history(data_dir: str = _DEFAULT_DATA_DIR) -> list:
    """Load the persisted allocation history.

    Parameters
    ----------
    data_dir:
        Directory containing the log file.

    Returns
    -------
    list
        List of allocation result dicts (may be empty).
    """
    log_path = Path(data_dir) / _LOG_FILE
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


__all__ = [
    "RWAPosition",
    "RWAAllocationResult",
    "risk_weight",
    "compute_rwa",
    "compare_budgets",
    "save_results",
    "load_history",
]

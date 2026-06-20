"""
MP-714: LiquidityMigrationAdvisor
Advisory/read-only module. Pure stdlib. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap: 100 entries.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "migration_advisory_log.json")

_RING_BUFFER_CAP = 100
_GAS_COST_SAME_CHAIN = 0.10   # %
_GAS_COST_CROSS_CHAIN = 0.25  # % (bridge + gas)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class PoolProfile:
    name: str
    protocol: str
    chain: str
    apy: float               # current APY %
    tvl_usd: float
    lock_period_days: int    # 0 if no lock
    exit_penalty_pct: float  # early exit penalty (0 if lock_period=0 or past lock)
    risk_score: float        # 0–100
    liquidity_depth_usd: float  # available exit liquidity (0 = illiquid)


@dataclass
class MigrationAnalysis:
    current: PoolProfile
    candidate: PoolProfile
    position_usd: float

    # Yield comparison
    apy_gain_pct: float
    risk_adjusted_gain: float

    # Cost analysis
    exit_cost_pct: float
    entry_cost_pct: float
    total_cost_pct: float
    total_cost_usd: float

    # Timing
    is_locked: bool
    breakeven_days: float

    # Liquidity check
    can_exit: bool

    # Decision
    recommendation: str   # "MIGRATE_NOW" | "WAIT_FOR_UNLOCK" | "MONITOR" | "STAY"
    confidence: str       # "HIGH" | "MEDIUM" | "LOW"
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def estimate_entry_cost(current_chain: str, candidate_chain: str) -> float:
    """Return entry cost % for same-chain (gas only) or cross-chain (bridge+gas)."""
    if current_chain.lower() == candidate_chain.lower():
        return _GAS_COST_SAME_CHAIN
    return _GAS_COST_CROSS_CHAIN


def _build_reasons(
    analysis: "MigrationAnalysis",
) -> List[str]:
    """Build 2-3 human-readable reasons explaining the recommendation."""
    rec = analysis.recommendation
    reasons: List[str] = []

    if rec == "STAY":
        if analysis.apy_gain_pct <= 0:
            reasons.append(
                f"Candidate APY ({analysis.candidate.apy:.2f}%) is not higher than "
                f"current APY ({analysis.current.apy:.2f}%); no yield gain available."
            )
        else:
            reasons.append(
                f"Migration costs ({analysis.total_cost_pct:.2f}%) outweigh the "
                f"expected yield gain over a reasonable horizon."
            )
        reasons.append("Current position remains optimal under present conditions.")

    elif rec == "MONITOR":
        if not analysis.can_exit:
            reasons.append(
                f"Insufficient exit liquidity: pool depth "
                f"(${analysis.current.liquidity_depth_usd:,.0f}) is below "
                f"90% of position size (${analysis.position_usd * 0.9:,.0f})."
            )
            reasons.append("Migration cannot proceed until liquidity improves.")
        else:
            reasons.append(
                f"Breakeven horizon ({analysis.breakeven_days:.0f} days) is "
                f"acceptable but risk-adjusted gain is marginal."
            )
            reasons.append("Continue monitoring; conditions may improve.")

    elif rec == "WAIT_FOR_UNLOCK":
        reasons.append(
            f"Current position is locked with an exit penalty of "
            f"{analysis.current.exit_penalty_pct:.2f}%; wait for the lock to expire."
        )
        reasons.append(
            f"Candidate offers +{analysis.apy_gain_pct:.2f}% APY gain; "
            f"migration is advisable once the lock clears."
        )

    elif rec == "MIGRATE_NOW":
        reasons.append(
            f"Candidate APY ({analysis.candidate.apy:.2f}%) is "
            f"{analysis.apy_gain_pct:.2f}% higher than current ({analysis.current.apy:.2f}%)."
        )
        reasons.append(
            f"Migration cost ({analysis.total_cost_pct:.2f}%) breaks even in "
            f"{analysis.breakeven_days:.0f} days — well within the threshold."
        )
        reasons.append(
            f"Risk-adjusted gain ({analysis.risk_adjusted_gain:.3f}) supports migration."
        )

    # Always have at least 2 reasons
    if len(reasons) < 2:
        reasons.append(
            f"Total migration cost: ${analysis.total_cost_usd:,.2f} "
            f"({analysis.total_cost_pct:.2f}% of position)."
        )

    return reasons


def _build_warnings(
    current: PoolProfile,
    candidate: PoolProfile,
    breakeven_days: float,
) -> List[str]:
    warnings: List[str] = []
    if candidate.risk_score > current.risk_score + 20:
        warnings.append(
            f"Significant risk increase: candidate risk score "
            f"({candidate.risk_score:.0f}) is more than 20 points higher than "
            f"current ({current.risk_score:.0f})."
        )
    if breakeven_days > 180:
        warnings.append(
            f"Very long breakeven horizon: {breakeven_days:.0f} days "
            f"(> 180 days threshold)."
        )
    if candidate.tvl_usd < 1_000_000:
        warnings.append(
            f"Low TVL destination pool: candidate TVL "
            f"(${candidate.tvl_usd:,.0f}) is below $1M."
        )
    return warnings


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze(
    current: PoolProfile,
    candidate: PoolProfile,
    position_usd: float,
) -> MigrationAnalysis:
    """Full migration analysis between current and candidate pools."""

    # Yield comparison
    apy_gain_pct = candidate.apy - current.apy
    risk_adjusted_gain = apy_gain_pct / (1 + candidate.risk_score / 100)

    # Cost analysis
    exit_cost_pct = current.exit_penalty_pct + _GAS_COST_SAME_CHAIN
    entry_cost_pct = estimate_entry_cost(current.chain, candidate.chain)
    total_cost_pct = exit_cost_pct + entry_cost_pct
    total_cost_usd = position_usd * total_cost_pct / 100

    # Timing
    is_locked = current.lock_period_days > 0 and current.exit_penalty_pct > 0

    if apy_gain_pct > 0:
        breakeven_days = (total_cost_pct / apy_gain_pct) * 365
    else:
        breakeven_days = float("inf")

    # Liquidity
    can_exit = current.liquidity_depth_usd >= position_usd * 0.9

    # Recommendation logic
    if apy_gain_pct <= 0:
        recommendation = "STAY"
    elif not can_exit:
        recommendation = "MONITOR"
    elif is_locked:
        recommendation = "WAIT_FOR_UNLOCK"
    elif breakeven_days < 30 and risk_adjusted_gain > 1:
        recommendation = "MIGRATE_NOW"
    elif breakeven_days < 90:
        recommendation = "MONITOR"
    else:
        recommendation = "STAY"

    # Confidence
    if recommendation == "MIGRATE_NOW":
        if breakeven_days < 14:
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Assemble partial analysis to build reasons/warnings
    partial = MigrationAnalysis(
        current=current,
        candidate=candidate,
        position_usd=position_usd,
        apy_gain_pct=apy_gain_pct,
        risk_adjusted_gain=risk_adjusted_gain,
        exit_cost_pct=exit_cost_pct,
        entry_cost_pct=entry_cost_pct,
        total_cost_pct=total_cost_pct,
        total_cost_usd=total_cost_usd,
        is_locked=is_locked,
        breakeven_days=breakeven_days,
        can_exit=can_exit,
        recommendation=recommendation,
        confidence=confidence,
    )

    reasons = _build_reasons(partial)
    warnings = _build_warnings(current, candidate, breakeven_days)

    partial.reasons = reasons
    partial.warnings = warnings
    return partial


# ---------------------------------------------------------------------------
# Rank candidates
# ---------------------------------------------------------------------------

def rank_candidates(
    current: PoolProfile,
    candidates: List[PoolProfile],
    position_usd: float,
) -> List[Tuple[MigrationAnalysis, PoolProfile]]:
    """Return list of (MigrationAnalysis, candidate) sorted by risk_adjusted_gain desc."""
    results = []
    for c in candidates:
        a = analyze(current, c, position_usd)
        results.append((a, c))
    results.sort(key=lambda x: x[0].risk_adjusted_gain, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _pool_to_dict(p: PoolProfile) -> dict:
    return {
        "name": p.name,
        "protocol": p.protocol,
        "chain": p.chain,
        "apy": p.apy,
        "tvl_usd": p.tvl_usd,
        "lock_period_days": p.lock_period_days,
        "exit_penalty_pct": p.exit_penalty_pct,
        "risk_score": p.risk_score,
        "liquidity_depth_usd": p.liquidity_depth_usd,
    }


def _analysis_to_dict(a: MigrationAnalysis, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "current": _pool_to_dict(a.current),
        "candidate": _pool_to_dict(a.candidate),
        "position_usd": a.position_usd,
        "apy_gain_pct": a.apy_gain_pct,
        "risk_adjusted_gain": a.risk_adjusted_gain,
        "exit_cost_pct": a.exit_cost_pct,
        "entry_cost_pct": a.entry_cost_pct,
        "total_cost_pct": a.total_cost_pct,
        "total_cost_usd": a.total_cost_usd,
        "is_locked": a.is_locked,
        "breakeven_days": a.breakeven_days if math.isfinite(a.breakeven_days) else None,
        "can_exit": a.can_exit,
        "recommendation": a.recommendation,
        "confidence": a.confidence,
        "reasons": a.reasons,
        "warnings": a.warnings,
        "saved_to": a.saved_to,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_history() -> list:
    """Load the ring-buffer log from disk. Returns empty list on error."""
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def save_results(analysis: MigrationAnalysis) -> str:
    """Append analysis to ring-buffer log (cap 100). Returns path written to."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    history = load_history()
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = _analysis_to_dict(analysis, timestamp)
    history.append(entry)
    # Ring-buffer: keep last 100
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]
    # Atomic write
    dir_path = os.path.dirname(_LOG_FILE)
    os.makedirs(dir_path, exist_ok=True)
    atomic_save(history, str(_LOG_FILE))
    analysis.saved_to = _LOG_FILE
    return _LOG_FILE


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    current = PoolProfile(
        name="USDC-Aave",
        protocol="Aave V3",
        chain="ethereum",
        apy=3.5,
        tvl_usd=50_000_000,
        lock_period_days=0,
        exit_penalty_pct=0.0,
        risk_score=10.0,
        liquidity_depth_usd=40_000_000,
    )
    candidate = PoolProfile(
        name="USDC-Morpho",
        protocol="Morpho Steakhouse",
        chain="ethereum",
        apy=6.5,
        tvl_usd=20_000_000,
        lock_period_days=0,
        exit_penalty_pct=0.0,
        risk_score=20.0,
        liquidity_depth_usd=15_000_000,
    )
    result = analyze(current, candidate, position_usd=50_000)
    print(f"Recommendation: {result.recommendation} ({result.confidence})")
    print(f"APY gain: {result.apy_gain_pct:.2f}%")
    print(f"Breakeven: {result.breakeven_days:.0f} days")
    print(f"Reasons: {result.reasons}")
    print(f"Warnings: {result.warnings}")
    save_results(result)
    print(f"Saved to: {result.saved_to}")


if __name__ == "__main__":
    _demo()

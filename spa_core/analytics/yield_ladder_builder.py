"""
MP-764: YieldLadderBuilder
Builds a tiered yield ladder across protocols (T1/T2/T3).
Allocates capital using target_allocation, computes blended APY,
ladder_score (0-100), and tier-risk-adjusted yield.
Pure stdlib, read-only advisory module.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/yield_ladder_log.json")
MAX_ENTRIES = 100

KNOWN_TIERS = ("T1", "T2", "T3")

# Risk weight per tier: T1 is safest (full credit), T3 is riskiest (30% discount)
TIER_RISK_WEIGHTS: Dict[str, float] = {
    "T1": 1.00,
    "T2": 0.85,
    "T3": 0.70,
}


@dataclass
class LadderRung:
    """One entry in the yield ladder — a single protocol/tier allocation."""
    protocol: str
    tier: str               # T1 / T2 / T3
    apy: float              # decimal, e.g. 0.05 = 5 %
    allocated_amount: float # USD allocated to this rung
    expected_yield: float   # USD/year expected from this rung


@dataclass
class LadderSnapshot:
    """Complete state of a built yield ladder."""
    timestamp: float
    capital: float
    target_allocation: Dict[str, float]   # {tier: fraction}
    rungs: List[LadderRung]
    blended_apy: float                    # capital-weighted avg APY on invested capital
    tier_risk_adjusted_yield: float       # risk-weight-adjusted blended APY
    ladder_score: float                   # 0–100 composite quality score
    tier_summary: Dict[str, dict]         # per-tier aggregated stats

    # ------------------------------------------------------------------ #
    # Convenience accessor methods                                         #
    # ------------------------------------------------------------------ #

    def get_blended_apy(self) -> float:
        """Return capital-weighted blended APY (decimal) on invested capital."""
        return self.blended_apy

    def get_tier_summary(self) -> Dict[str, dict]:
        """Return per-tier statistics: allocated, expected_yield, avg_apy, rung_count."""
        return self.tier_summary


class YieldLadderBuilder:
    """
    Builds a tiered yield ladder from a list of protocol descriptors.

    Usage::

        builder = YieldLadderBuilder()
        protocols = [
            {"protocol": "Aave V3",    "tier": "T1", "apy": 0.035},
            {"protocol": "Compound V3","tier": "T1", "apy": 0.048},
            {"protocol": "Morpho",     "tier": "T2", "apy": 0.065},
        ]
        target = {"T1": 0.5, "T2": 0.3, "T3": 0.2}
        snap = builder.build_ladder(protocols, capital=100_000, target_allocation=target)
        print(snap.get_blended_apy())
        builder.save_snapshot(snap)
    """

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file
        self._last_snapshot: Optional[LadderSnapshot] = None

    # ------------------------------------------------------------------ #
    # Core builder                                                         #
    # ------------------------------------------------------------------ #

    def build_ladder(
        self,
        protocols: List[dict],
        capital: float,
        target_allocation: Dict[str, float],
    ) -> LadderSnapshot:
        """
        Build a tiered yield ladder.

        Args:
            protocols: list of dicts with keys:
                - ``protocol`` (str) – human-readable name
                - ``tier``     (str) – "T1", "T2", or "T3"
                - ``apy``      (float) – annual yield as decimal (0.05 = 5 %)
            capital: total capital in USD (must be > 0 to produce rungs)
            target_allocation: {tier: fraction} mapping (fractions need not sum
                to 1.0; unused capital stays as a cash buffer)

        Returns:
            LadderSnapshot with all ladder metrics stored.
        """
        # Guard: empty protocols or non-positive capital → empty ladder
        if not protocols or capital <= 0:
            snap = LadderSnapshot(
                timestamp=time.time(),
                capital=max(0.0, float(capital)),
                target_allocation=dict(target_allocation),
                rungs=[],
                blended_apy=0.0,
                tier_risk_adjusted_yield=0.0,
                ladder_score=0.0,
                tier_summary={},
            )
            self._last_snapshot = snap
            return snap

        # Normalize allocation: only known tiers, non-negative fractions
        alloc: Dict[str, float] = {
            tier: max(0.0, float(frac))
            for tier, frac in target_allocation.items()
            if tier in KNOWN_TIERS
        }

        # Group input protocols by tier
        by_tier: Dict[str, List[dict]] = {t: [] for t in KNOWN_TIERS}
        for p in protocols:
            tier = p.get("tier", "")
            if tier in by_tier:
                by_tier[tier].append(p)

        # Build rungs — equal capital split within each tier
        rungs: List[LadderRung] = []
        for tier, fraction in alloc.items():
            tier_capital = float(capital) * fraction
            protos_in_tier = by_tier.get(tier, [])
            if not protos_in_tier or tier_capital <= 0.0:
                continue
            per_protocol = tier_capital / len(protos_in_tier)
            for p in protos_in_tier:
                apy = max(0.0, float(p.get("apy", 0.0)))
                expected = per_protocol * apy
                rungs.append(
                    LadderRung(
                        protocol=str(p.get("protocol", "unknown")),
                        tier=tier,
                        apy=apy,
                        allocated_amount=round(per_protocol, 6),
                        expected_yield=round(expected, 6),
                    )
                )

        # Blended APY (on invested capital, not total capital)
        total_allocated = sum(r.allocated_amount for r in rungs)
        if total_allocated > 0.0:
            blended_apy = sum(r.expected_yield for r in rungs) / total_allocated
        else:
            blended_apy = 0.0

        # Tier risk-adjusted yield
        if total_allocated > 0.0:
            risk_adj = (
                sum(
                    r.expected_yield * TIER_RISK_WEIGHTS.get(r.tier, 0.5)
                    for r in rungs
                )
                / total_allocated
            )
        else:
            risk_adj = 0.0

        ladder_score = self._compute_ladder_score(rungs, alloc, risk_adj)
        tier_summary = self._build_tier_summary(rungs)

        snap = LadderSnapshot(
            timestamp=time.time(),
            capital=float(capital),
            target_allocation=dict(target_allocation),
            rungs=rungs,
            blended_apy=round(blended_apy, 8),
            tier_risk_adjusted_yield=round(risk_adj, 8),
            ladder_score=round(ladder_score, 4),
            tier_summary=tier_summary,
        )
        self._last_snapshot = snap
        return snap

    # ------------------------------------------------------------------ #
    # Convenience accessors (operate on last built snapshot)               #
    # ------------------------------------------------------------------ #

    def get_blended_apy(self) -> float:
        """Return blended APY from the last built snapshot (0.0 if none)."""
        if self._last_snapshot is None:
            return 0.0
        return self._last_snapshot.blended_apy

    def get_tier_summary(self) -> Dict[str, dict]:
        """Return tier summary from the last built snapshot ({} if none)."""
        if self._last_snapshot is None:
            return {}
        return self._last_snapshot.tier_summary

    # ------------------------------------------------------------------ #
    # Internal computation helpers                                         #
    # ------------------------------------------------------------------ #

    def _compute_ladder_score(
        self,
        rungs: List[LadderRung],
        alloc: Dict[str, float],
        tier_risk_adjusted_yield: float,
    ) -> float:
        """
        Compute composite ladder quality score in [0, 100].

        Components:
        - Risk-adjusted yield score  (0–60): scales linearly, 20 % RAY → 60 pts
        - Tier coverage score        (0–25): fraction of targeted tiers populated
        - Protocol diversification   (0–15): 2.5 pts per unique protocol, cap 15
        """
        if not rungs:
            return 0.0

        # Component 1: risk-adjusted yield (0–60)
        # 20 % RAY maps to 60 points; above 20 % is capped
        ray_score = min(60.0, tier_risk_adjusted_yield * 300.0)

        # Component 2: tier coverage (0–25)
        tiers_targeted = {t for t, f in alloc.items() if f > 0.0}
        tiers_populated = {r.tier for r in rungs}
        coverage = (
            len(tiers_targeted & tiers_populated) / len(tiers_targeted)
            if tiers_targeted
            else 0.0
        )
        tier_score = coverage * 25.0

        # Component 3: protocol diversification (0–15)
        n_unique = len({r.protocol for r in rungs})
        div_score = min(15.0, n_unique * 2.5)

        return min(100.0, ray_score + tier_score + div_score)

    def _build_tier_summary(self, rungs: List[LadderRung]) -> Dict[str, dict]:
        """Aggregate per-tier statistics."""
        summary: Dict[str, dict] = {}
        for tier in KNOWN_TIERS:
            tier_rungs = [r for r in rungs if r.tier == tier]
            if not tier_rungs:
                continue
            total_alloc = sum(r.allocated_amount for r in tier_rungs)
            total_yield = sum(r.expected_yield for r in tier_rungs)
            avg_apy = total_yield / total_alloc if total_alloc > 0.0 else 0.0
            summary[tier] = {
                "allocated": round(total_alloc, 6),
                "expected_yield": round(total_yield, 6),
                "avg_apy": round(avg_apy, 8),
                "rung_count": len(tier_rungs),
            }
        return summary

    # ------------------------------------------------------------------ #
    # Persistence (ring-buffer, atomic write)                              #
    # ------------------------------------------------------------------ #

    def save_snapshot(self, snapshot: LadderSnapshot) -> None:
        """
        Atomically append a snapshot summary to the ring-buffer JSON log.
        The log is capped at MAX_ENTRIES (100) entries; oldest are dropped.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        entry = {
            "timestamp": snapshot.timestamp,
            "capital": snapshot.capital,
            "rung_count": len(snapshot.rungs),
            "blended_apy": snapshot.blended_apy,
            "tier_risk_adjusted_yield": snapshot.tier_risk_adjusted_yield,
            "ladder_score": snapshot.ladder_score,
            "tier_summary": snapshot.tier_summary,
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load snapshot history from disk; returns [] if file missing/invalid."""
        try:
            data = json.loads(self.data_file.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _demo_protocols() -> List[dict]:
    return [
        {"protocol": "Aave V3",         "tier": "T1", "apy": 0.035},
        {"protocol": "Compound V3",     "tier": "T1", "apy": 0.048},
        {"protocol": "Morpho Steakhouse","tier": "T2", "apy": 0.065},
        {"protocol": "Euler V2",        "tier": "T2", "apy": 0.072},
        {"protocol": "Pendle PT",       "tier": "T3", "apy": 0.120},
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-764 YieldLadderBuilder")
    parser.add_argument("--run", action="store_true", help="Compute + save to data file")
    parser.add_argument("--check", action="store_true", help="Compute + print, no save (default)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "yield_ladder_log.json"

    builder = YieldLadderBuilder(data_file=data_file)
    protocols = _demo_protocols()
    target = {"T1": 0.50, "T2": 0.30, "T3": 0.20}
    capital = 100_000.0

    snap = builder.build_ladder(protocols, capital, target)

    print(f"Capital          : ${snap.capital:,.0f}")
    print(f"Rungs            : {len(snap.rungs)}")
    print(f"Blended APY      : {snap.blended_apy:.2%}")
    print(f"Risk-Adj Yield   : {snap.tier_risk_adjusted_yield:.2%}")
    print(f"Ladder Score     : {snap.ladder_score:.1f}/100")
    print()
    for tier, info in snap.tier_summary.items():
        print(
            f"  {tier}: ${info['allocated']:>12,.0f} allocated | "
            f"avg APY {info['avg_apy']:.2%} | {info['rung_count']} rung(s)"
        )

    if args.run:
        builder.save_snapshot(snap)
        print(f"\nSaved → {data_file}")

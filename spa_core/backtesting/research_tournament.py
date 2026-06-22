"""
spa_core/backtesting/research_tournament.py

Research strategy tournament track.
RS-001 and RS-002 run in shadow mode alongside S0-S19.
They cannot be promoted to live without owner sign-off + source promotion.

Tournament output per strategy:
  {
    strategy_id: str,
    is_research: bool,
    target_apy: float,
    estimated_net_apy: float,  # after IL drag for RS-002
    strict_eligible_fraction: float,  # % of capital with clean data
    research_exclusion_count: int,
    risk_classification: str,
    rank_in_research_track: int,  # 1 = best research strategy
    vs_production_leader: float,  # delta vs best production strategy APY
    recommendation: str  # "CONTINUE_RESEARCH" | "READY_FOR_PAPER" | "REDESIGN"
  }

Promotion gating:
  - NEVER auto-promote without owner sign-off
  - NEVER deploy real or paper capital without source promotion review
  - LLM FORBIDDEN in risk / execution / monitoring path

Sprint v9.43 — MP-1327
Date: 2026-06-19
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

from spa_core.utils.atomic import atomic_save

# ─── Constants ─────────────────────────────────────────────────────────────────

RESEARCH_STRATEGIES: List[str] = ["S20", "S21"]

# Production leader reference (updated from tournament results externally)
PRODUCTION_LEADER_STRATEGY: str = "S7"
PRODUCTION_LEADER_APY: float = 10.1  # S7 current APY %

# Promotion gating thresholds
_READY_FOR_PAPER_ELIGIBLE_THRESHOLD: float = 0.5   # strict_eligible_fraction must exceed this
_REDESIGN_NET_APY_THRESHOLD: float = PRODUCTION_LEADER_APY  # below this → REDESIGN

# RS-001 (S20) reference data from AntiCrisisResearchStrategy
_RS001_TARGET_APY: float = 18.2
_RS001_STRICT_ELIGIBLE_FRACTION: float = 0.15   # only stablecoin_t1 eligible
_RS001_EXCLUSION_SLOTS = [
    "gmx_btc_exposure",
    "gmx_eth_exposure",
    "btc_stable_pool",
    "eth_aggressive_pool",
    "gold_proxy",
]
_RS001_ESTIMATED_NET_APY: float = 18.2   # assumes placeholders; no IL drag
_RS001_RISK_CLASSIFICATION: str = "BALANCED"

# RS-002 (S21) reference data from CashflowResearchStrategy
_RS002_TARGET_APY_GROSS: float = 29.24   # gross before IL
_RS002_STRICT_ELIGIBLE_FRACTION: float = 0.16   # only stablecoin_deposit eligible
_RS002_EXCLUSION_SLOTS = [
    "btc_usd_conc_liq",
    "rwa_conc_liq",
    "trader_losses_vault",
]
_RS002_ESTIMATED_NET_APY: float = 15.0   # midpoint of 12–18% sideways estimate after IL drag
_RS002_RISK_CLASSIFICATION: str = "AGGRESSIVE"

# Default save path
_DEFAULT_SAVE_PATH: str = "data/research/tournament_results.json"


# ─── ResearchTournament ────────────────────────────────────────────────────────

class ResearchTournament:
    """Shadow tournament track for research strategies RS-001 (S20) and RS-002 (S21).

    Runs alongside the main S0–S19 tournament but does NOT allocate capital.
    Tracks show metrics, eligibility for paper-trading promotion, and gap to live.

    Public API:
        run()                      → full tournament results dict
        rs001_metrics()            → RS-001 tournament metrics dict
        rs002_metrics()            → RS-002 tournament metrics dict
        rank_research_strategies() → strategies ranked by estimated net APY
        recommendation(id)         → "CONTINUE_RESEARCH" | "READY_FOR_PAPER" | "REDESIGN"
        save(path)                 → atomic write to disk

    LLM FORBIDDEN: this module must not invoke language models.
    """

    RESEARCH_STRATEGIES: List[str] = RESEARCH_STRATEGIES
    PRODUCTION_LEADER_APY: float = PRODUCTION_LEADER_APY

    def __init__(
        self,
        production_leader_apy: float = PRODUCTION_LEADER_APY,
        production_leader_strategy: str = PRODUCTION_LEADER_STRATEGY,
    ) -> None:
        """Initialise with optional override of production leader reference."""
        self._production_leader_apy = production_leader_apy
        self._production_leader_strategy = production_leader_strategy

    # ── Public methods ─────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Run the full research tournament.

        Returns:
            {
              "research_track": list[dict],          # per-strategy results
              "production_leader": {"strategy": str, "apy": float},
              "research_leader": {"strategy": str, "apy": float},
              "gap_to_live": float,                  # how far from being promotable
              "blockers_summary": list[str],
              "timestamp": str,
            }
        """
        ranked = self.rank_research_strategies()

        # Research leader = top-ranked by estimated net APY
        if ranked:
            leader_entry = ranked[0]
            research_leader: dict = {
                "strategy": leader_entry["strategy_id"],
                "apy": leader_entry["estimated_net_apy"],
            }
        else:
            research_leader = {"strategy": "none", "apy": 0.0}

        # Gap to live: fraction of capital still without strict data sources
        # = 1 - max(strict_eligible_fraction) across research strategies
        max_eligible = max(
            (e["strict_eligible_fraction"] for e in ranked), default=0.0
        )
        gap_to_live = round(1.0 - max_eligible, 4)

        blockers = self._compute_blockers(ranked)

        return {
            "research_track": ranked,
            "production_leader": {
                "strategy": self._production_leader_strategy,
                "apy": self._production_leader_apy,
            },
            "research_leader": research_leader,
            "gap_to_live": gap_to_live,
            "blockers_summary": blockers,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def rs001_metrics(self) -> dict:
        """Compute RS-001 (S20) tournament metrics.

        Returns:
            Full metric dict for S20 (see module docstring for schema).
        """
        exclusion_count = len(_RS001_EXCLUSION_SLOTS)
        vs_prod = round(_RS001_ESTIMATED_NET_APY - self._production_leader_apy, 4)
        rec = self.recommendation("S20")

        return {
            "strategy_id": "S20",
            "strategy_name": "RS-001 Anti-Crisis (Research)",
            "is_research": True,
            "target_apy": _RS001_TARGET_APY,
            "estimated_net_apy": _RS001_ESTIMATED_NET_APY,
            "strict_eligible_fraction": _RS001_STRICT_ELIGIBLE_FRACTION,
            "research_exclusion_count": exclusion_count,
            "excluded_slots": list(_RS001_EXCLUSION_SLOTS),
            "risk_classification": _RS001_RISK_CLASSIFICATION,
            "rank_in_research_track": -1,   # filled by rank_research_strategies()
            "vs_production_leader": vs_prod,
            "recommendation": rec,
        }

    def rs002_metrics(self) -> dict:
        """Compute RS-002 (S21) tournament metrics.

        Returns:
            Full metric dict for S21 (see module docstring for schema).
        """
        exclusion_count = len(_RS002_EXCLUSION_SLOTS)
        vs_prod = round(_RS002_ESTIMATED_NET_APY - self._production_leader_apy, 4)
        rec = self.recommendation("S21")

        return {
            "strategy_id": "S21",
            "strategy_name": "RS-002 Cashflow (Research)",
            "is_research": True,
            "target_apy": _RS002_TARGET_APY_GROSS,
            "estimated_net_apy": _RS002_ESTIMATED_NET_APY,
            "strict_eligible_fraction": _RS002_STRICT_ELIGIBLE_FRACTION,
            "research_exclusion_count": exclusion_count,
            "excluded_slots": list(_RS002_EXCLUSION_SLOTS),
            "risk_classification": _RS002_RISK_CLASSIFICATION,
            "rank_in_research_track": -1,   # filled by rank_research_strategies()
            "vs_production_leader": vs_prod,
            "recommendation": rec,
        }

    def rank_research_strategies(self) -> List[dict]:
        """Rank research strategies by estimated net APY (descending).

        Returns:
            List of metric dicts with rank_in_research_track set (1 = best).
        """
        metrics_list = [
            self.rs001_metrics(),
            self.rs002_metrics(),
        ]

        # Sort by estimated_net_apy descending, strategy_id ascending as tiebreaker
        metrics_list.sort(
            key=lambda m: (-m["estimated_net_apy"], m["strategy_id"])
        )

        for rank, entry in enumerate(metrics_list, start=1):
            entry["rank_in_research_track"] = rank

        return metrics_list

    def recommendation(self, strategy_id: str) -> str:
        """Return promotion recommendation for a research strategy.

        Rules:
          READY_FOR_PAPER  — if strict_eligible_fraction > 0.5 AND net APY > production leader
          REDESIGN         — if net APY estimate < production leader APY
          CONTINUE_RESEARCH — otherwise (needs more data sources)

        Args:
            strategy_id: "S20" or "S21"

        Returns:
            One of: "CONTINUE_RESEARCH", "READY_FOR_PAPER", "REDESIGN"
        """
        if strategy_id == "S20":
            eligible_fraction = _RS001_STRICT_ELIGIBLE_FRACTION
            net_apy = _RS001_ESTIMATED_NET_APY
        elif strategy_id == "S21":
            eligible_fraction = _RS002_STRICT_ELIGIBLE_FRACTION
            net_apy = _RS002_ESTIMATED_NET_APY
        else:
            return "CONTINUE_RESEARCH"

        # Check if net APY is below production leader → REDESIGN
        if net_apy < _REDESIGN_NET_APY_THRESHOLD:
            return "REDESIGN"

        # Check if enough strict-eligible capital → READY_FOR_PAPER
        if eligible_fraction > _READY_FOR_PAPER_ELIGIBLE_THRESHOLD:
            return "READY_FOR_PAPER"

        # Default: needs more data sources
        return "CONTINUE_RESEARCH"

    def save(self, path: str = _DEFAULT_SAVE_PATH) -> None:
        """Atomically save full tournament results to JSON.

        Creates parent directory if missing.
        Uses tmp-file + os.replace for atomicity.

        Args:
            path: Destination file path (absolute or relative to cwd).
        """
        results = self.run()

        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        atomic_save(results, str(dest))

    # ── Private helpers ────────────────────────────────────────────────────────

    def _compute_blockers(self, ranked: List[dict]) -> List[str]:
        """Compute human-readable blockers list for the tournament."""
        blockers: List[str] = []

        for entry in ranked:
            sid = entry["strategy_id"]
            fraction = entry["strict_eligible_fraction"]
            exclusion_count = entry["research_exclusion_count"]
            rec = entry["recommendation"]

            if rec == "CONTINUE_RESEARCH":
                blockers.append(
                    f"{sid}: {exclusion_count} excluded slots; "
                    f"strict_eligible={fraction:.0%} — needs data sources"
                )
            elif rec == "REDESIGN":
                net_apy = entry["estimated_net_apy"]
                blockers.append(
                    f"{sid}: net APY estimate {net_apy:.1f}% below production "
                    f"leader {self._production_leader_apy:.1f}% — REDESIGN"
                )
            # READY_FOR_PAPER adds no blockers

        return blockers

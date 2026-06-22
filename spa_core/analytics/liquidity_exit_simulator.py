"""Liquidity Exit Simulator — MP-630.

Models how quickly a DeFi position can be unwound.  Pure advisory;
never touches allocator / risk / execution domains.

Design constraints
------------------
* Stdlib only (no numpy, requests, web3, pandas, …).
* Pure advisory — read-only on position state; writes only the log file.
* Atomic writes: tmp + os.replace (ring-buffer 50 to data/exit_simulation_log.json).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Usage (CLI)::

    python3 -m spa_core.analytics.liquidity_exit_simulator --check
    python3 -m spa_core.analytics.liquidity_exit_simulator --run
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExitScenario:
    """Result of a single exit feasibility estimate for one adapter position."""

    adapter_id: str
    position_size_usd: float
    pool_tvl_usd: float
    estimated_exit_blocks: int
    estimated_exit_time_minutes: float
    exit_slippage_bps: float
    exit_feasibility: str  # "INSTANT" | "FAST" | "MODERATE" | "SLOW" | "RISKY"
    can_exit_in_one_block: bool


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCK_TIME_SECONDS: float = 12.0        # Ethereum mainnet
BLOCKS_PER_MINUTE: float = 60.0 / 12.0  # = 5.0
MAX_PER_BLOCK_PCT: float = 0.02         # max 2 % of TVL per block
SLIPPAGE_BPS_PER_BLOCK: float = 5.0     # 5 bps per block of delay

# Feasibility tier thresholds (blocks)
_FEASIBILITY_TIERS = [
    (1,   "INSTANT"),
    (5,   "FAST"),
    (20,  "MODERATE"),
    (100, "SLOW"),
]


def _feasibility(blocks: int) -> str:
    """Map blocks_needed → feasibility tier string."""
    for threshold, label in _FEASIBILITY_TIERS:
        if blocks <= threshold:
            return label
    return "RISKY"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class LiquidityExitSimulator:
    """Estimate time and slippage cost to unwind DeFi positions.

    All outputs are *advisory*; they do not gate or modify any trade.
    """

    # Re-expose constants as class attributes.
    BLOCK_TIME_SECONDS = BLOCK_TIME_SECONDS
    BLOCKS_PER_MINUTE = BLOCKS_PER_MINUTE
    MAX_PER_BLOCK_PCT = MAX_PER_BLOCK_PCT

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """Initialise the simulator.

        Parameters
        ----------
        data_dir:
            Path to the ``data/`` directory.  Defaults to
            ``<repo_root>/data/`` resolved relative to this file.
        """
        if data_dir is None:
            _here = Path(__file__).resolve()
            # spa_core/analytics/ → spa_core/ → repo root → data/
            data_dir = str(_here.parent.parent.parent / "data")
        self._data_dir = data_dir
        self._log_path = os.path.join(self._data_dir, "exit_simulation_log.json")

    # ------------------------------------------------------------------
    # Core estimate
    # ------------------------------------------------------------------

    def estimate_exit(
        self,
        adapter_id: str,
        position_size_usd: float,
        pool_tvl_usd: float,
    ) -> ExitScenario:
        """Estimate exit blocks, time, slippage, and feasibility.

        Formula::

            capacity_per_block = pool_tvl_usd * MAX_PER_BLOCK_PCT
            blocks_needed      = ceil(position_size_usd / capacity_per_block)
            blocks_needed      = max(1, blocks_needed)
            exit_time_minutes  = blocks_needed * BLOCK_TIME_SECONDS / 60
            exit_slippage_bps  = SLIPPAGE_BPS_PER_BLOCK * blocks_needed
            can_exit_in_one_block = (blocks_needed == 1)

        Parameters
        ----------
        adapter_id:
            Identifier for the protocol / adapter.
        position_size_usd:
            Current position size in USD to unwind.
        pool_tvl_usd:
            Total value locked in the pool, in USD.

        Returns
        -------
        ExitScenario
        """
        safe_tvl = max(pool_tvl_usd, 1.0)
        safe_pos = max(position_size_usd, 0.0)

        capacity_per_block = safe_tvl * MAX_PER_BLOCK_PCT
        if safe_pos == 0.0:
            blocks_needed = 1
        else:
            blocks_needed = max(1, math.ceil(safe_pos / capacity_per_block))

        exit_time_minutes = blocks_needed * BLOCK_TIME_SECONDS / 60.0
        exit_slippage_bps = SLIPPAGE_BPS_PER_BLOCK * blocks_needed
        can_exit_in_one_block = blocks_needed == 1
        feasibility = _feasibility(blocks_needed)

        return ExitScenario(
            adapter_id=adapter_id,
            position_size_usd=safe_pos,
            pool_tvl_usd=safe_tvl,
            estimated_exit_blocks=blocks_needed,
            estimated_exit_time_minutes=round(exit_time_minutes, 4),
            exit_slippage_bps=round(exit_slippage_bps, 4),
            exit_feasibility=feasibility,
            can_exit_in_one_block=can_exit_in_one_block,
        )

    # ------------------------------------------------------------------
    # Portfolio exit
    # ------------------------------------------------------------------

    def estimate_portfolio_exit(
        self,
        positions: Dict[str, float],
        tvl_map: Dict[str, float],
    ) -> List[ExitScenario]:
        """Estimate exit scenarios for every position in a portfolio.

        Parameters
        ----------
        positions:
            Mapping of ``adapter_id → position_size_usd``.
        tvl_map:
            Mapping of ``adapter_id → pool_tvl_usd``.

        Returns
        -------
        list of ExitScenario — one per adapter in *positions*.
        Missing TVL defaults to 0 (treated as 1 USD after guard).
        """
        results: List[ExitScenario] = []
        for adapter_id, size in positions.items():
            tvl = tvl_map.get(adapter_id, 0.0)
            results.append(self.estimate_exit(adapter_id, size, tvl))
        return results

    # ------------------------------------------------------------------
    # Worst case
    # ------------------------------------------------------------------

    @staticmethod
    def get_worst_case_exit(scenarios: List[ExitScenario]) -> Optional[ExitScenario]:
        """Return the scenario with the highest estimated_exit_blocks.

        Returns ``None`` if the list is empty.
        """
        if not scenarios:
            return None
        return max(scenarios, key=lambda s: s.estimated_exit_blocks)

    # ------------------------------------------------------------------
    # Risk score
    # ------------------------------------------------------------------

    @staticmethod
    def compute_exit_risk_score(scenarios: List[ExitScenario]) -> float:
        """Weighted average of blocks_needed, normalised to 0–100.

        Normalisation: score = min(100, mean(blocks_needed) / 100 * 100)
        i.e. 100 blocks = risk score 100, sub-100 blocks scales linearly.
        An empty list returns 0.0.
        """
        if not scenarios:
            return 0.0
        total_blocks = sum(s.estimated_exit_blocks for s in scenarios)
        mean_blocks = total_blocks / len(scenarios)
        # Normalise: 100 blocks → score 100 (cap at 100)
        score = min(100.0, mean_blocks)
        return round(score, 4)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def generate_report(
        self,
        positions: Dict[str, float],
        tvl_map: Dict[str, float],
    ) -> dict:
        """Generate a full exit simulation report.

        Parameters
        ----------
        positions:
            Mapping of ``adapter_id → position_size_usd``.
        tvl_map:
            Mapping of ``adapter_id → pool_tvl_usd``.

        Returns
        -------
        dict with keys:

        * ``scenarios`` — list of ExitScenario (as dicts)
        * ``worst_case`` — worst ExitScenario (as dict) or None
        * ``exit_risk_score`` — float 0–100
        * ``total_positions`` — number of positions
        * ``advisory`` — "Exit scenarios are estimates only."
        """
        scenarios = self.estimate_portfolio_exit(positions, tvl_map)
        worst = self.get_worst_case_exit(scenarios)
        risk_score = self.compute_exit_risk_score(scenarios)

        def _scen_to_dict(s: ExitScenario) -> dict:
            return {
                "adapter_id": s.adapter_id,
                "position_size_usd": s.position_size_usd,
                "pool_tvl_usd": s.pool_tvl_usd,
                "estimated_exit_blocks": s.estimated_exit_blocks,
                "estimated_exit_time_minutes": s.estimated_exit_time_minutes,
                "exit_slippage_bps": s.exit_slippage_bps,
                "exit_feasibility": s.exit_feasibility,
                "can_exit_in_one_block": s.can_exit_in_one_block,
            }

        return {
            "scenarios": [_scen_to_dict(s) for s in scenarios],
            "worst_case": _scen_to_dict(worst) if worst is not None else None,
            "exit_risk_score": risk_score,
            "total_positions": len(positions),
            "advisory": "Exit scenarios are estimates only.",
        }

    # ------------------------------------------------------------------
    # Log (ring-buffer 50)
    # ------------------------------------------------------------------

    def log_simulation(self, report: dict) -> None:
        """Append *report* to data/exit_simulation_log.json (ring-buffer 50).

        Uses atomic write (tmp + os.replace).
        Creates the log file and data directory if they do not exist.
        """
        os.makedirs(self._data_dir, exist_ok=True)

        # Load existing log
        existing: list = []
        if os.path.exists(self._log_path):
            try:
                with open(self._log_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        # Stamp and append
        entry = dict(report)
        entry["logged_at"] = datetime.now(timezone.utc).isoformat()

        existing.append(entry)

        # Ring-buffer: keep last 50
        if len(existing) > 50:
            existing = existing[-50:]

        # Atomic write
        dir_path = os.path.dirname(self._log_path) or "."
        atomic_save(existing, self._log_path)
# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _demo_run(write: bool = False) -> None:
    """Run a demo and print the report; optionally log it."""
    positions = {
        "aave_v3": 50_000.0,
        "compound_v3": 30_000.0,
        "morpho_steakhouse": 20_000.0,
    }
    tvl_map = {
        "aave_v3": 2_000_000_000.0,
        "compound_v3": 500_000_000.0,
        "morpho_steakhouse": 80_000_000.0,
    }
    sim = LiquidityExitSimulator()
    report = sim.generate_report(positions, tvl_map)
    print(json.dumps(report, indent=2))
    if write:
        sim.log_simulation(report)
        print(f"Logged to {sim._log_path}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: --check (print only) or --run (print + log)."""
    args = argv if argv is not None else sys.argv[1:]
    write = "--run" in args
    _demo_run(write=write)
    return 0


if __name__ == "__main__":
    sys.exit(main())

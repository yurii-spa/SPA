"""
MP-674: StakingRewardsOptimizer
Analyze staking positions to find optimal compounding frequency
and estimate net APY after gas costs.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
import math
from pathlib import Path

DATA_FILE = Path("data/staking_rewards_log.json")
MAX_ENTRIES = 100

# Candidate compounding frequencies (times per year)
CANDIDATE_FREQS = [1, 2, 4, 7, 12, 26, 52, 104, 365]


@dataclass
class StakingPosition:
    position_id: str
    protocol: str
    token: str
    staked_amount_usd: float
    base_apy_pct: float           # annual percentage yield before compounding
    compound_frequency: int       # times per year user currently compounds
    gas_cost_per_compound_usd: float  # gas cost each time rewards are claimed+restaked
    lock_up_days: int             # 0 = liquid, >0 = locked
    slash_risk_pct: float         # 0.0–100.0 slashing probability per year
    validator_uptime_pct: float   # 0.0–100.0 expected uptime


@dataclass
class StakingOptimizationReport:
    position_id: str
    current_net_apy_pct: float      # APY after gas drag at current frequency
    optimal_compound_freq: int      # times per year for max net APY
    optimal_net_apy_pct: float      # APY at optimal frequency
    apy_improvement_pct: float      # optimal - current (can be negative if over-compounding)
    slash_adjusted_apy_pct: float   # optimal_net_apy * (1 - slash_risk/100)
    uptime_adjusted_apy_pct: float  # slash_adjusted * (validator_uptime/100)
    liquidity_penalty: str          # NONE / LOW / MEDIUM / HIGH (based on lockup)
    recommendation: str             # INCREASE_FREQUENCY / DECREASE_FREQUENCY / OPTIMAL / UNSTAKE
    compound_schedule: str          # e.g. "Compound every 14 days"
    warnings: List[str]


class StakingRewardsOptimizer:
    """
    Optimizes compounding frequency and estimates net APY for staking positions.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Core math helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _net_apy_for_freq(
        base_apy_pct: float,
        freq: int,
        gas_per_compound: float,
        staked_amount: float,
    ) -> float:
        """
        Net APY (%) for a given compounding frequency.
        Periodic rate r = base_apy_pct / 100 / freq
        Compounded yearly = (1 + r)^freq - 1
        Annual gas drag = gas_per_compound * freq / staked_amount * 100  (%)
        Net APY = compounded * 100 - gas_drag_pct
        """
        if freq <= 0:
            freq = 1
        r = base_apy_pct / 100.0 / freq
        compounded = (1.0 + r) ** freq - 1.0
        if staked_amount <= 0:
            annual_gas_drag_pct = 0.0
        else:
            annual_gas = gas_per_compound * freq
            annual_gas_drag_pct = annual_gas / staked_amount * 100.0
        net_apy = compounded * 100.0 - annual_gas_drag_pct
        return round(net_apy, 4)

    @staticmethod
    def _optimal_freq(
        base_apy_pct: float,
        gas_per_compound: float,
        staked_amount: float,
    ) -> int:
        """
        Scan CANDIDATE_FREQS and return the one that maximises _net_apy_for_freq.
        If staked_amount == 0, return 1.
        """
        if staked_amount == 0:
            return 1
        best_freq = 1
        best_apy = StakingRewardsOptimizer._net_apy_for_freq(
            base_apy_pct, 1, gas_per_compound, staked_amount
        )
        for freq in CANDIDATE_FREQS:
            apy = StakingRewardsOptimizer._net_apy_for_freq(
                base_apy_pct, freq, gas_per_compound, staked_amount
            )
            if apy > best_apy:
                best_apy = apy
                best_freq = freq
        return best_freq

    @staticmethod
    def _liquidity_penalty(lock_up_days: int) -> str:
        """NONE / LOW / MEDIUM / HIGH based on lock-up duration."""
        if lock_up_days == 0:
            return "NONE"
        elif lock_up_days <= 7:
            return "LOW"
        elif lock_up_days <= 30:
            return "MEDIUM"
        else:
            return "HIGH"

    @staticmethod
    def _recommendation(
        optimal_freq: int,
        compound_frequency: int,
        uptime_adjusted_apy: float,
    ) -> str:
        """
        UNSTAKE if uptime_adjusted_apy < 0,
        INCREASE_FREQUENCY if optimal > current * 1.5,
        DECREASE_FREQUENCY if optimal < current * 0.5,
        else OPTIMAL.
        """
        if uptime_adjusted_apy < 0:
            return "UNSTAKE"
        if compound_frequency == 0:
            # edge case: avoid division; treat as if current=1
            compound_frequency = 1
        if optimal_freq > compound_frequency * 1.5:
            return "INCREASE_FREQUENCY"
        if optimal_freq < compound_frequency * 0.5:
            return "DECREASE_FREQUENCY"
        return "OPTIMAL"

    @staticmethod
    def _compound_schedule(optimal_freq: int) -> str:
        """Human-readable schedule string."""
        if optimal_freq <= 0:
            optimal_freq = 1
        if optimal_freq == 365:
            return "Compound daily"
        if optimal_freq == 1:
            return "Compound yearly"
        days = 365 // optimal_freq
        return f"Compound every {days} days"

    @staticmethod
    def _warnings(position: StakingPosition) -> List[str]:
        """Generate advisory warnings for a staking position."""
        warns: List[str] = []
        if position.slash_risk_pct > 5:
            warns.append(
                f"🚨 High slash risk {position.slash_risk_pct:.1f}% — diversify validators"
            )
        if position.validator_uptime_pct < 95:
            warns.append(
                f"⚠️ Validator uptime {position.validator_uptime_pct:.1f}% below 95% — risk of missed rewards"
            )
        if position.lock_up_days > 30:
            warns.append(
                f"🔒 Locked for {position.lock_up_days} days — illiquidity risk"
            )
        if position.staked_amount_usd > 0 and (
            position.gas_cost_per_compound_usd > position.staked_amount_usd * 0.01
        ):
            warns.append(
                "⚠️ Gas per compound >1% of position — compounding unprofitable"
            )
        return warns

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, position: StakingPosition) -> StakingOptimizationReport:
        """Compute a full StakingOptimizationReport for a single position."""
        # Net APY at current frequency
        current_net_apy = self._net_apy_for_freq(
            position.base_apy_pct,
            position.compound_frequency,
            position.gas_cost_per_compound_usd,
            position.staked_amount_usd,
        )

        # Optimal frequency
        opt_freq = self._optimal_freq(
            position.base_apy_pct,
            position.gas_cost_per_compound_usd,
            position.staked_amount_usd,
        )

        # Net APY at optimal frequency
        optimal_net_apy = self._net_apy_for_freq(
            position.base_apy_pct,
            opt_freq,
            position.gas_cost_per_compound_usd,
            position.staked_amount_usd,
        )

        apy_improvement = round(optimal_net_apy - current_net_apy, 4)

        # Slash adjustment
        slash_adjusted = round(
            optimal_net_apy * (1.0 - position.slash_risk_pct / 100.0), 4
        )

        # Uptime adjustment
        uptime_adjusted = round(
            slash_adjusted * (position.validator_uptime_pct / 100.0), 4
        )

        liquidity_penalty = self._liquidity_penalty(position.lock_up_days)
        schedule = self._compound_schedule(opt_freq)
        warns = self._warnings(position)
        rec = self._recommendation(
            opt_freq, position.compound_frequency, uptime_adjusted
        )

        return StakingOptimizationReport(
            position_id=position.position_id,
            current_net_apy_pct=current_net_apy,
            optimal_compound_freq=opt_freq,
            optimal_net_apy_pct=optimal_net_apy,
            apy_improvement_pct=apy_improvement,
            slash_adjusted_apy_pct=slash_adjusted,
            uptime_adjusted_apy_pct=uptime_adjusted,
            liquidity_penalty=liquidity_penalty,
            recommendation=rec,
            compound_schedule=schedule,
            warnings=warns,
        )

    def analyze_batch(
        self, positions: List[StakingPosition]
    ) -> List[StakingOptimizationReport]:
        """Analyze a list of positions, return list of reports."""
        return [self.analyze(p) for p in positions]

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic writes)
    # ------------------------------------------------------------------

    def save_results(
        self,
        reports: List[StakingOptimizationReport],
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append reports to ring-buffer JSON file (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        new_entries = [
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "position_id": r.position_id,
                "current_net_apy_pct": r.current_net_apy_pct,
                "optimal_compound_freq": r.optimal_compound_freq,
                "optimal_net_apy_pct": r.optimal_net_apy_pct,
                "apy_improvement_pct": r.apy_improvement_pct,
                "slash_adjusted_apy_pct": r.slash_adjusted_apy_pct,
                "uptime_adjusted_apy_pct": r.uptime_adjusted_apy_pct,
                "liquidity_penalty": r.liquidity_penalty,
                "recommendation": r.recommendation,
                "compound_schedule": r.compound_schedule,
                "warnings": r.warnings,
            }
            for r in reports
        ]

        combined = existing + new_entries
        # Keep only last MAX_ENTRIES
        combined = combined[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load history from ring-buffer JSON. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    optimizer = StakingRewardsOptimizer()
    demo_position = StakingPosition(
        position_id="demo-eth-staking",
        protocol="Lido",
        token="stETH",
        staked_amount_usd=50_000.0,
        base_apy_pct=4.5,
        compound_frequency=12,
        gas_cost_per_compound_usd=8.0,
        lock_up_days=0,
        slash_risk_pct=0.5,
        validator_uptime_pct=99.5,
    )
    report = optimizer.analyze(demo_position)
    print(f"Position:          {report.position_id}")
    print(f"Current net APY:   {report.current_net_apy_pct:.4f}%")
    print(f"Optimal freq:      {report.optimal_compound_freq}x/yr")
    print(f"Optimal net APY:   {report.optimal_net_apy_pct:.4f}%")
    print(f"APY improvement:   {report.apy_improvement_pct:+.4f}%")
    print(f"Slash-adj APY:     {report.slash_adjusted_apy_pct:.4f}%")
    print(f"Uptime-adj APY:    {report.uptime_adjusted_apy_pct:.4f}%")
    print(f"Liquidity penalty: {report.liquidity_penalty}")
    print(f"Recommendation:    {report.recommendation}")
    print(f"Schedule:          {report.compound_schedule}")
    print(f"Warnings:          {report.warnings}")


if __name__ == "__main__":
    import sys
    _demo()

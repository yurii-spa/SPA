"""MP-698: YieldRecyclerEngine — model reinvestment (recycling) of yield.

Compares simple hold vs. active recycling strategies across configurable
scenarios: recycle frequency, gas cost, reinvest percentage.

Pure stdlib, no external dependencies.
Atomic writes (tmp + os.replace).

Run:
    python3 -m spa_core.analytics.yield_recycler_engine --check
    python3 -m spa_core.analytics.yield_recycler_engine --run
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/yield_recycler_log.json")
MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RecycleScenario:
    scenario_id: str
    initial_capital: float
    base_apy_pct: float            # current yield on capital
    recycle_into_apy_pct: float    # yield on recycled rewards (can equal base_apy)
    recycle_frequency_days: int    # how often to recycle (e.g. 7 = weekly)
    simulation_days: int           # total period to simulate
    gas_cost_per_recycle: float    # USD cost each recycle
    reinvest_pct: float            # 0-100: % of rewards to reinvest (rest is withdrawn)


@dataclass
class RecycleResult:
    scenario_id: str
    strategy: str                  # "SIMPLE_HOLD" or "ACTIVE_RECYCLE"
    final_capital: float
    total_yield_usd: float
    total_gas_cost_usd: float
    net_yield_usd: float           # total_yield - total_gas
    effective_apy_pct: float       # annualized net yield
    num_recycles: int              # 0 for SIMPLE_HOLD
    improvement_over_hold_pct: float  # vs SIMPLE_HOLD (0 for SIMPLE_HOLD itself)


@dataclass
class RecycleComparison:
    scenario_id: str
    hold: RecycleResult
    recycle: RecycleResult
    winner: str                    # "RECYCLE" or "HOLD"
    net_improvement_usd: float     # recycle.net_yield - hold.net_yield
    break_even_days: float         # days until recycle beats hold (gas amortized)
    recommendation: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class YieldRecyclerEngine:
    """Simulate and compare simple-hold vs. active-recycle yield strategies."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _effective_apy(initial: float, final: float, days: int) -> float:
        """Annualize net yield: ((final/initial)^(365/days) - 1) * 100."""
        if initial <= 0 or days <= 0:
            return 0.0
        ratio = final / initial
        if ratio <= 0:
            return -100.0
        return (ratio ** (365.0 / days) - 1.0) * 100.0

    # ------------------------------------------------------------------
    # SIMPLE_HOLD simulation
    # ------------------------------------------------------------------

    def _simulate_hold(self, scenario: RecycleScenario) -> RecycleResult:
        """Continuous compound hold — no gas, no active recycling."""
        daily_rate = scenario.base_apy_pct / 100.0 / 365.0
        final = scenario.initial_capital * (1.0 + daily_rate) ** scenario.simulation_days
        total_yield = final - scenario.initial_capital
        effective_apy = self._effective_apy(
            scenario.initial_capital, final, scenario.simulation_days
        )
        return RecycleResult(
            scenario_id=scenario.scenario_id,
            strategy="SIMPLE_HOLD",
            final_capital=final,
            total_yield_usd=total_yield,
            total_gas_cost_usd=0.0,
            net_yield_usd=total_yield,
            effective_apy_pct=effective_apy,
            num_recycles=0,
            improvement_over_hold_pct=0.0,
        )

    # ------------------------------------------------------------------
    # ACTIVE_RECYCLE simulation
    # ------------------------------------------------------------------

    def _simulate_recycle(self, scenario: RecycleScenario) -> RecycleResult:
        """
        Dual-pool simulation over exactly ``sim_days // recycle_freq_days`` complete
        intervals.

        • pool_base  — original capital (fixed); earns ``base_apy_pct`` each interval.
        • pool_recycled — accumulated reinvested yield; earns ``recycle_into_apy_pct``
          each interval and grows with every recycle.

        At each recycle interval:
          1. pool_base  yields: base_capital * ((1 + base_daily)^freq - 1)
          2. pool_recycled yields: pool_recycled * ((1 + recycle_daily)^freq - 1)
          3. Of total interval yield, ``reinvest_pct/100`` added to pool_recycled.
          4. ``gas_cost_per_recycle`` deducted from pool_recycled.

        When ``recycle_into_apy_pct > base_apy_pct`` the reinvested capital grows
        faster than a simple hold, producing superior net yield.
        """
        base_daily = scenario.base_apy_pct / 100.0 / 365.0
        recycle_daily = scenario.recycle_into_apy_pct / 100.0 / 365.0
        freq = scenario.recycle_frequency_days
        n_recycles = scenario.simulation_days // freq
        reinvest_frac = scenario.reinvest_pct / 100.0

        pool_base = scenario.initial_capital      # never changes
        pool_recycled = 0.0                       # accumulates reinvestment

        total_yield = 0.0
        total_gas = 0.0

        for _ in range(n_recycles):
            # Yield from original base capital
            y_base = pool_base * ((1.0 + base_daily) ** freq - 1.0)
            # Yield from previously recycled capital (earns recycle_into_apy)
            y_recycled = pool_recycled * ((1.0 + recycle_daily) ** freq - 1.0)

            interval_yield = y_base + y_recycled
            total_yield += interval_yield

            reinvested = interval_yield * reinvest_frac
            pool_recycled += reinvested
            pool_recycled -= scenario.gas_cost_per_recycle
            total_gas += scenario.gas_cost_per_recycle

        # Final capital: base is untouched, recycled can be negative (gas-heavy)
        final_capital = pool_base + pool_recycled
        if final_capital < 0:
            final_capital = 0.0

        net_yield = total_yield - total_gas
        effective_apy = self._effective_apy(
            scenario.initial_capital,
            scenario.initial_capital + net_yield,
            scenario.simulation_days,
        )

        return RecycleResult(
            scenario_id=scenario.scenario_id,
            strategy="ACTIVE_RECYCLE",
            final_capital=final_capital,
            total_yield_usd=total_yield,
            total_gas_cost_usd=total_gas,
            net_yield_usd=net_yield,
            effective_apy_pct=effective_apy,
            num_recycles=n_recycles,
            improvement_over_hold_pct=0.0,  # filled in compare()
        )

    # ------------------------------------------------------------------
    # Break-even calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _break_even_days(
        scenario: RecycleScenario,
        hold: RecycleResult,
        recycle: RecycleResult,
    ) -> float:
        """
        Days until recycling strategy cumulative net yield overtakes hold.

        daily_advantage = recycle's per-day net yield advantage over hold.
        gas_total / daily_advantage if advantage > 0, else inf.
        """
        sim_days = scenario.simulation_days
        if sim_days <= 0:
            return math.inf

        hold_daily = hold.net_yield_usd / sim_days if sim_days > 0 else 0.0
        recycle_daily_gross = recycle.total_yield_usd / sim_days if sim_days > 0 else 0.0

        # Per-day net advantage (before subtracting gas which is a lump-sum cost)
        daily_advantage = recycle_daily_gross - hold_daily
        if daily_advantage <= 0:
            return math.inf

        # Total gas is the "upfront" cost; break-even = gas / advantage per day
        return recycle.total_gas_cost_usd / daily_advantage

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(self, scenario: RecycleScenario) -> RecycleComparison:
        """Run both strategies and return a full comparison."""
        hold = self._simulate_hold(scenario)
        recycle = self._simulate_recycle(scenario)

        net_improvement = recycle.net_yield_usd - hold.net_yield_usd
        winner = "RECYCLE" if recycle.net_yield_usd > hold.net_yield_usd else "HOLD"

        # Back-fill improvement_over_hold_pct for recycle result
        if hold.net_yield_usd != 0:
            recycle.improvement_over_hold_pct = (
                net_improvement / abs(hold.net_yield_usd) * 100.0
            )

        break_even = self._break_even_days(scenario, hold, recycle)

        if winner == "RECYCLE":
            recommendation = (
                f"✅ Recycle wins by ${net_improvement:.0f} over {scenario.simulation_days}d"
                f" — reinvest {scenario.reinvest_pct:.0f}%"
                f" {scenario.recycle_frequency_days}d"
            )
        else:
            recommendation = (
                f"📋 Simple hold wins — gas costs ${recycle.total_gas_cost_usd:.0f}"
                f" exceed recycling benefit"
            )

        return RecycleComparison(
            scenario_id=scenario.scenario_id,
            hold=hold,
            recycle=recycle,
            winner=winner,
            net_improvement_usd=net_improvement,
            break_even_days=break_even,
            recommendation=recommendation,
        )

    def compare_batch(
        self, scenarios: List[RecycleScenario]
    ) -> List[RecycleComparison]:
        """Run compare() for each scenario."""
        return [self.compare(s) for s in scenarios]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(
        self,
        comparisons: List[RecycleComparison],
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append results to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        data_file.parent.mkdir(parents=True, exist_ok=True)

        existing: List[dict] = []
        if data_file.exists():
            try:
                with open(data_file) as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        def _serialise(cmp: RecycleComparison) -> dict:
            d = asdict(cmp)
            d["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            return d

        new_entries = [_serialise(c) for c in comparisons]
        combined = existing + new_entries
        # Ring-buffer: keep last MAX_ENTRIES
        if len(combined) > MAX_ENTRIES:
            combined = combined[-MAX_ENTRIES:]

        tmp = str(data_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(combined, f, indent=2)
        os.replace(tmp, data_file)

    def load_history(
        self, data_file: Path = DATA_FILE
    ) -> List[dict]:
        """Load saved results. Returns [] if file missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_scenarios() -> List[RecycleScenario]:
    return [
        RecycleScenario(
            scenario_id="weekly-5pct-zero-gas",
            initial_capital=100_000,
            base_apy_pct=5.0,
            recycle_into_apy_pct=5.0,
            recycle_frequency_days=7,
            simulation_days=365,
            gas_cost_per_recycle=0.0,
            reinvest_pct=100.0,
        ),
        RecycleScenario(
            scenario_id="weekly-5pct-high-gas",
            initial_capital=10_000,
            base_apy_pct=5.0,
            recycle_into_apy_pct=5.0,
            recycle_frequency_days=7,
            simulation_days=365,
            gas_cost_per_recycle=50.0,
            reinvest_pct=100.0,
        ),
        RecycleScenario(
            scenario_id="monthly-10pct-low-gas",
            initial_capital=50_000,
            base_apy_pct=10.0,
            recycle_into_apy_pct=10.0,
            recycle_frequency_days=30,
            simulation_days=365,
            gas_cost_per_recycle=5.0,
            reinvest_pct=100.0,
        ),
    ]


def main(write: bool = False) -> None:
    engine = YieldRecyclerEngine()
    scenarios = _demo_scenarios()
    comparisons = engine.compare_batch(scenarios)

    for cmp in comparisons:
        print(f"\n{'=' * 60}")
        print(f"Scenario: {cmp.scenario_id}")
        print(f"  HOLD    net yield: ${cmp.hold.net_yield_usd:,.2f}  APY: {cmp.hold.effective_apy_pct:.2f}%")
        print(f"  RECYCLE net yield: ${cmp.recycle.net_yield_usd:,.2f}  APY: {cmp.recycle.effective_apy_pct:.2f}%  recycles: {cmp.recycle.num_recycles}")
        print(f"  Winner: {cmp.winner}  improvement: ${cmp.net_improvement_usd:,.2f}")
        be = cmp.break_even_days
        print(f"  Break-even: {'∞' if math.isinf(be) else f'{be:.1f}d'}")
        print(f"  → {cmp.recommendation}")

    if write:
        engine.save_results(comparisons)
        print(f"\n✅ Saved {len(comparisons)} comparisons → {DATA_FILE}")


if __name__ == "__main__":
    import sys
    write_flag = "--run" in sys.argv
    main(write=write_flag)

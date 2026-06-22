"""MP-699: CompoundingStrategySelector — select optimal compounding strategy.

Evaluates HOLD, MANUAL compound, and auto-compound platforms (Beefy, Yearn,
Convex, Aura, Concentrator) for a DeFi position, comparing net APY after
fees and gas drag.

Pure stdlib, no external dependencies.
Atomic writes (tmp + os.replace).

Run:
    python3 -m spa_core.analytics.compounding_strategy_selector --check
    python3 -m spa_core.analytics.compounding_strategy_selector --run
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/compounding_strategy_log.json")
MAX_ENTRIES = 100

# Known auto-compounder overhead
AUTO_COMPOUNDERS: Dict[str, Dict[str, float]] = {
    "beefy":        {"performance_fee_pct": 4.5,  "compound_freq_days": 1.0},
    "yearn":        {"performance_fee_pct": 2.0,  "compound_freq_days": 0.5},
    "convex":       {"performance_fee_pct": 16.0, "compound_freq_days": 0.125},
    "aura":         {"performance_fee_pct": 20.0, "compound_freq_days": 0.125},
    "concentrator": {"performance_fee_pct": 10.0, "compound_freq_days": 1.0},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrategyInput:
    position_id: str
    protocol: str
    capital_usd: float
    gross_apy_pct: float           # protocol APY before compounding fees
    manual_gas_usd: float          # gas cost for manual compound
    manual_compound_days: int      # how often user would manually compound
    lock_period_days: int          # 0 = liquid, >0 = locked (can't use auto-compound)


@dataclass
class StrategyOption:
    strategy_name: str             # "HOLD", "MANUAL", or compounder name
    net_apy_pct: float             # after fees and gas drag
    annual_cost_usd: float         # total fees + gas per year
    annual_net_yield_usd: float    # capital * net_apy / 100
    complexity: str                # LOW / MEDIUM / HIGH
    suitable: bool                 # False if locked and strategy requires liquidity


@dataclass
class StrategySelection:
    position_id: str
    options: List[StrategyOption]
    best_strategy: str             # name of highest net_apy suitable option
    best_net_apy_pct: float
    vs_hold_improvement_pct: float  # best.net_apy - hold_apy
    recommendation: str
    rationale: str


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

class CompoundingStrategySelector:
    """Evaluate and select the best compounding strategy for a position."""

    # ------------------------------------------------------------------
    # Option builders
    # ------------------------------------------------------------------

    @staticmethod
    def _hold_option(inp: StrategyInput) -> StrategyOption:
        """HOLD: no active compounding, no fees, no gas."""
        net_apy = inp.gross_apy_pct
        annual_net_yield = inp.capital_usd * net_apy / 100.0
        return StrategyOption(
            strategy_name="HOLD",
            net_apy_pct=net_apy,
            annual_cost_usd=0.0,
            annual_net_yield_usd=annual_net_yield,
            complexity="LOW",
            suitable=True,
        )

    @staticmethod
    def _manual_option(inp: StrategyInput) -> StrategyOption:
        """MANUAL: user compounds every manual_compound_days, pays gas each time."""
        daily_rate = inp.gross_apy_pct / 100.0 / 365.0
        freq = inp.manual_compound_days

        # Effective APY with periodic compounding at freq-day intervals
        periods_per_year = 365.0 / freq
        compounded_apy = (
            (1.0 + daily_rate * freq) ** periods_per_year - 1.0
        ) * 100.0

        # Annual gas cost
        annual_gas = inp.manual_gas_usd * periods_per_year
        # Gas drag as % of capital
        gas_drag_pct = (annual_gas / inp.capital_usd) * 100.0 if inp.capital_usd > 0 else 0.0

        net_apy = compounded_apy - gas_drag_pct
        annual_net_yield = inp.capital_usd * net_apy / 100.0

        return StrategyOption(
            strategy_name="MANUAL",
            net_apy_pct=net_apy,
            annual_cost_usd=annual_gas,
            annual_net_yield_usd=annual_net_yield,
            complexity="MEDIUM",
            suitable=True,
        )

    @staticmethod
    def _auto_option(inp: StrategyInput, name: str, params: Dict[str, float]) -> StrategyOption:
        """AUTO-COMPOUND: platform handles compounding but takes performance fee."""
        daily_rate = inp.gross_apy_pct / 100.0 / 365.0
        freq = params["compound_freq_days"]
        performance_fee_pct = params["performance_fee_pct"]

        # Effective APY with the compounder's frequency
        periods_per_year = 365.0 / freq
        compounded_apy = (
            (1.0 + daily_rate * freq) ** periods_per_year - 1.0
        ) * 100.0

        # Fee drag: performance fee is taken on gross APY
        fee_drag_pct = inp.gross_apy_pct * performance_fee_pct / 100.0

        net_apy = compounded_apy - fee_drag_pct

        # Annual cost = capital * (compounded_apy - net_apy) / 100
        annual_cost = inp.capital_usd * (compounded_apy - net_apy) / 100.0
        annual_net_yield = inp.capital_usd * net_apy / 100.0

        # Suitable only when position is liquid (lock_period_days == 0)
        suitable = inp.lock_period_days == 0

        return StrategyOption(
            strategy_name=name,
            net_apy_pct=net_apy,
            annual_cost_usd=annual_cost,
            annual_net_yield_usd=annual_net_yield,
            complexity="LOW",
            suitable=suitable,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, inp: StrategyInput) -> StrategySelection:
        """Build all strategy options and select the best suitable one."""
        hold = self._hold_option(inp)
        manual = self._manual_option(inp)
        auto_options = [
            self._auto_option(inp, name, params)
            for name, params in AUTO_COMPOUNDERS.items()
        ]

        all_options: List[StrategyOption] = [hold, manual] + auto_options
        suitable = [o for o in all_options if o.suitable]

        if not suitable:
            # Fallback: always return HOLD
            suitable = [hold]

        best = max(suitable, key=lambda o: o.net_apy_pct)
        vs_hold = best.net_apy_pct - hold.net_apy_pct

        annual_improvement_usd = (
            inp.capital_usd * vs_hold / 100.0
        )

        recommendation = (
            f"Use {best.strategy_name}: {best.net_apy_pct:.2f}% net APY"
            f" (+{vs_hold:.2f}% vs hold)"
        )
        rationale = (
            f"Best compounding frequency gives {vs_hold:.2f}% more yield"
            f" on ${inp.capital_usd:.0f} = ${annual_improvement_usd:.0f}/yr"
        )

        return StrategySelection(
            position_id=inp.position_id,
            options=all_options,
            best_strategy=best.strategy_name,
            best_net_apy_pct=best.net_apy_pct,
            vs_hold_improvement_pct=vs_hold,
            recommendation=recommendation,
            rationale=rationale,
        )

    def select_batch(self, inputs: List[StrategyInput]) -> List[StrategySelection]:
        """Run select() for each input."""
        return [self.select(i) for i in inputs]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(
        self,
        selections: List[StrategySelection],
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append selections to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
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

        def _serialise(sel: StrategySelection) -> dict:
            d = asdict(sel)
            d["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            return d

        new_entries = [_serialise(s) for s in selections]
        combined = existing + new_entries
        if len(combined) > MAX_ENTRIES:
            combined = combined[-MAX_ENTRIES:]

        tmp = str(data_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(combined, f, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> List[dict]:
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

def _demo_inputs() -> List[StrategyInput]:
    return [
        StrategyInput(
            position_id="aave-usdc-100k",
            protocol="Aave V3",
            capital_usd=100_000,
            gross_apy_pct=5.0,
            manual_gas_usd=20.0,
            manual_compound_days=7,
            lock_period_days=0,
        ),
        StrategyInput(
            position_id="locked-yearn-50k",
            protocol="Yearn V3",
            capital_usd=50_000,
            gross_apy_pct=8.0,
            manual_gas_usd=15.0,
            manual_compound_days=14,
            lock_period_days=30,
        ),
        StrategyInput(
            position_id="small-5k",
            protocol="Morpho",
            capital_usd=5_000,
            gross_apy_pct=6.5,
            manual_gas_usd=50.0,
            manual_compound_days=7,
            lock_period_days=0,
        ),
    ]


def main(write: bool = False) -> None:
    selector = CompoundingStrategySelector()
    inputs = _demo_inputs()
    selections = selector.select_batch(inputs)

    for sel in selections:
        print(f"\n{'=' * 60}")
        print(f"Position: {sel.position_id}  best: {sel.best_strategy}  APY: {sel.best_net_apy_pct:.2f}%")
        print(f"  vs hold: +{sel.vs_hold_improvement_pct:.2f}%")
        print(f"  → {sel.recommendation}")
        print(f"  ℹ  {sel.rationale}")
        suitable = [o for o in sel.options if o.suitable]
        for opt in sorted(suitable, key=lambda o: -o.net_apy_pct):
            print(f"     {opt.strategy_name:14s}  net {opt.net_apy_pct:6.2f}%  cost ${opt.annual_cost_usd:7.0f}/yr  [{opt.complexity}]")

    if write:
        selector.save_results(selections)
        print(f"\n✅ Saved {len(selections)} selections → {DATA_FILE}")


if __name__ == "__main__":
    import sys
    write_flag = "--run" in sys.argv
    main(write=write_flag)

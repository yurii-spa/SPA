"""Liquidity Stress Simulator — MP-649.

Simulates the impact of liquidity crises on the portfolio.
Estimates how much capital can be withdrawn in a stressed environment.

Design constraints
------------------
* Stdlib only (no numpy, requests, web3, pandas, …).
* Pure advisory — read-only; no side-effects on allocator / risk / execution.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* All writes are atomic (tmp + os.replace).

Usage (CLI)::

    python3 -m spa_core.analytics.liquidity_stress_simulator --check
    python3 -m spa_core.analytics.liquidity_stress_simulator --run
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/liquidity_stress_log.json")
MAX_ENTRIES = 100

# Stress scenarios: liquidity haircut on available (liquid) capital
SCENARIOS: Dict[str, dict] = {
    "MILD":     {"haircut": 0.10, "label": "Mild stress — 10% liquidity haircut"},
    "MODERATE": {"haircut": 0.25, "label": "Moderate stress — 25% liquidity haircut"},
    "SEVERE":   {"haircut": 0.50, "label": "Severe stress — 50% liquidity haircut"},
    "EXTREME":  {"haircut": 0.80, "label": "Extreme crisis — 80% liquidity haircut"},
}

# An adapter is considered concentrated if its deployed capital exceeds this
# fraction of the protocol's total TVL.
CONCENTRATION_TVL_PCT = 0.05  # 5 %

# Coverage ratio thresholds for verdict
SAFE_COVERAGE = 0.30
WATCH_COVERAGE = 0.15


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AdapterLiquidity:
    """Describes the liquidity profile of one deployed adapter position."""

    adapter_id: str
    capital_deployed: float          # USD value currently deployed
    tier: str                        # "T1" / "T2" / "T3"
    lock_days: int                   # 0 = immediately liquid; >0 = locked
    tvl_usd: float                   # protocol pool TVL in USD; 0 if unknown
    withdrawal_limit_pct: float      # max fraction of TVL withdrawable in one tx


@dataclass
class StressResult:
    """Output of a single stress-scenario simulation."""

    scenario: str
    scenario_label: str
    total_deployed: float
    liquid_capital: float            # capital in lock_days == 0 adapters
    locked_capital: float            # capital in lock_days  > 0 adapters
    withdrawable_stress: float       # liquid_capital * (1 − haircut)
    coverage_ratio: float            # withdrawable_stress / total_deployed
    at_risk_adapters: List[str]      # adapter_ids where capital > 5 % of TVL
    verdict: str                     # "SAFE" / "WATCH" / "CRITICAL"


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class LiquidityStressSimulator(BaseAnalytics):
    """Simulate portfolio liquidity under four crisis scenarios."""

    MODULE_NAME = "liquidity_stress_simulator"
    OUTPUT_PATH = "data/liquidity_stress_log.json"

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        super().__init__()  # BaseAnalytics: ensures data/ dir exists
        self.data_file = data_file

    def to_dict(self) -> dict:
        """Returns liquidity stress log history as JSON-serializable dict."""
        return {"history": self.load_history()}

    # ------------------------------------------------------------------
    # BaseAnalytics contract
    # ------------------------------------------------------------------

    def analyze(
        self,
        adapters: Optional[List[AdapterLiquidity]] = None,
        scenario: Optional[str] = None,
    ) -> Dict[str, object]:
        """Concrete BaseAnalytics.analyze() implementation (MP-649).

        Runs the liquidity stress simulation and returns a standard result
        envelope. When *adapters* is None a representative portfolio of the
        registry's T1/T2 protocols (aave_v3, compound_v3, morpho, euler_v2,
        maple) is used, so the daily cycle can call ``analyze()`` with no
        arguments. The production pipeline passes live position-derived
        adapters explicitly.

        Args:
            adapters: optional explicit list of AdapterLiquidity profiles.
            scenario: optional single scenario name; when None all four
                      scenarios are simulated.

        Returns:
            {module_id, status, timestamp, result} where ``result`` holds
            per-scenario coverage ratios, slippage/withdrawal estimates and
            the worst-case verdict across scenarios.
        """
        if adapters is None:
            adapters = _build_demo_adapters()

        if scenario is not None:
            key = scenario if scenario in SCENARIOS else "MODERATE"
            results = {key: self.simulate(adapters, key)}
        else:
            results = self.simulate_all(adapters)

        scenarios: Dict[str, dict] = {}
        for name, r in results.items():
            scenarios[name] = {
                "scenario": r.scenario,
                "scenario_label": r.scenario_label,
                "total_deployed": r.total_deployed,
                "liquid_capital": r.liquid_capital,
                "locked_capital": r.locked_capital,
                "withdrawable_stress": r.withdrawable_stress,
                "coverage_ratio": r.coverage_ratio,
                "at_risk_adapters": r.at_risk_adapters,
                "verdict": r.verdict,
            }

        # TVL ratio per adapter (capital / pool TVL) — concentration / slippage proxy
        tvl_ratios = {
            a.adapter_id: round(a.capital_deployed / a.tvl_usd, 6)
            for a in adapters
            if a.tvl_usd > 0
        }

        worst_coverage = min(
            (r.coverage_ratio for r in results.values()), default=0.0
        )
        status = self._verdict(worst_coverage)

        return {
            "module_id": self.MODULE_NAME,
            "status": status,
            "timestamp": time.time(),
            "result": {
                "scenarios": scenarios,
                "tvl_ratios": tvl_ratios,
                "worst_coverage_ratio": round(worst_coverage, 6),
                "adapters_analyzed": len(adapters),
            },
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _liquid_capital(self, adapters: List[AdapterLiquidity]) -> float:
        """Sum of capital in adapters with lock_days == 0."""
        return sum(a.capital_deployed for a in adapters if a.lock_days == 0)

    def _locked_capital(self, adapters: List[AdapterLiquidity]) -> float:
        """Sum of capital in adapters with lock_days > 0."""
        return sum(a.capital_deployed for a in adapters if a.lock_days > 0)

    def _at_risk(self, adapters: List[AdapterLiquidity]) -> List[str]:
        """Return adapter_ids where capital > CONCENTRATION_TVL_PCT of TVL.

        Adapters with tvl_usd <= 0 are skipped (no concentration risk can be
        computed without a valid TVL).
        """
        at_risk: List[str] = []
        for a in adapters:
            if a.tvl_usd > 0 and a.capital_deployed > CONCENTRATION_TVL_PCT * a.tvl_usd:
                at_risk.append(a.adapter_id)
        return at_risk

    def _verdict(self, coverage: float) -> str:
        """Map coverage ratio to a human-readable verdict."""
        if coverage >= SAFE_COVERAGE:
            return "SAFE"
        if coverage >= WATCH_COVERAGE:
            return "WATCH"
        return "CRITICAL"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate(
        self,
        adapters: List[AdapterLiquidity],
        scenario: str = "MODERATE",
    ) -> StressResult:
        """Run a single stress scenario and return a StressResult.

        Unknown scenario names fall back to "MODERATE".
        """
        if scenario not in SCENARIOS:
            scenario = "MODERATE"

        haircut = SCENARIOS[scenario]["haircut"]
        label   = SCENARIOS[scenario]["label"]

        total       = sum(a.capital_deployed for a in adapters)
        liquid      = self._liquid_capital(adapters)
        locked      = self._locked_capital(adapters)
        withdrawable = liquid * (1.0 - haircut)
        coverage    = withdrawable / total if total > 0 else 0.0
        at_risk     = self._at_risk(adapters)

        return StressResult(
            scenario=scenario,
            scenario_label=label,
            total_deployed=round(total, 2),
            liquid_capital=round(liquid, 2),
            locked_capital=round(locked, 2),
            withdrawable_stress=round(withdrawable, 2),
            coverage_ratio=round(coverage, 6),
            at_risk_adapters=at_risk,
            verdict=self._verdict(coverage),
        )

    def simulate_all(
        self, adapters: List[AdapterLiquidity]
    ) -> Dict[str, StressResult]:
        """Run all four scenarios and return a dict keyed by scenario name."""
        return {s: self.simulate(adapters, s) for s in SCENARIOS}

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_result(self, result: StressResult) -> None:
        """Atomically append one result to the ring-buffer log (max MAX_ENTRIES)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: list = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        existing.append({
            "timestamp": time.time(),
            "scenario": result.scenario,
            "coverage_ratio": result.coverage_ratio,
            "verdict": result.verdict,
            "withdrawable_stress": result.withdrawable_stress,
        })
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return logged history; empty list if file missing / corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_demo_adapters() -> List[AdapterLiquidity]:
    """Return a small representative portfolio for demo / smoke tests."""
    return [
        AdapterLiquidity("aave_v3",     40_000, "T1", 0,  500_000_000, 0.10),
        AdapterLiquidity("compound_v3", 30_000, "T1", 0,  300_000_000, 0.10),
        AdapterLiquidity("morpho",      20_000, "T1", 0,  100_000_000, 0.05),
        AdapterLiquidity("euler_v2",     5_000, "T2", 7,   20_000_000, 0.02),
        AdapterLiquidity("maple",        5_000, "T2", 30,  10_000_000, 0.01),
    ]


def _run(write: bool) -> None:
    adapters = _build_demo_adapters()
    sim = LiquidityStressSimulator()
    results = sim.simulate_all(adapters)

    for name, r in results.items():
        print(
            f"  [{r.verdict:8s}] {name:8s}  coverage={r.coverage_ratio:.1%}"
            f"  withdrawable=${r.withdrawable_stress:,.0f}"
            f"  at_risk={r.at_risk_adapters}"
        )

    if write:
        for r in results.values():
            sim.save_result(r)
        print(f"\n✓ Saved {len(results)} results → {sim.data_file}")


if __name__ == "__main__":
    mode = "--check"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    if mode == "--run":
        _run(write=True)
    else:
        _run(write=False)

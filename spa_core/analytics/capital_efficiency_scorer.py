"""CapitalEfficiencyScorer — MP-681.

Score how efficiently capital is deployed across the portfolio — measuring
yield per unit of risk taken and per dollar deployed.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/capital_efficiency_log.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/capital_efficiency_log.json")
MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PositionEfficiency:
    """Raw inputs for a single deployed position."""
    position_id: str
    protocol: str
    capital_deployed_usd: float
    annual_yield_usd: float        # absolute dollar yield per year
    annual_yield_pct: float        # apy as percentage
    risk_score: float              # 0.0–1.0
    gas_cost_annual_usd: float     # annual gas cost for this position
    opportunity_cost_pct: float    # what risk-free rate could earn (e.g. 4.25% US Treasury)


@dataclass
class EfficiencyReport:
    """Scored output for a single position."""
    position_id: str
    protocol: str
    net_yield_usd: float           # annual_yield - gas_cost
    net_yield_pct: float           # net_yield / capital * 100
    excess_return_pct: float       # net_yield_pct - opportunity_cost_pct (alpha)
    yield_per_risk_unit: float     # net_yield_pct / risk_score (inf if risk=0)
    capital_efficiency_score: float  # 0.0–1.0
    efficiency_grade: str          # A / B / C / D / F
    is_worth_it: bool              # True if excess_return > 1.0%
    recommendation: str


@dataclass
class PortfolioEfficiencyReport:
    """Aggregated efficiency view for all positions combined."""
    total_capital_usd: float
    total_net_yield_usd: float
    portfolio_net_yield_pct: float
    weighted_risk_score: float      # capital-weighted average risk
    portfolio_yield_per_risk: float
    portfolio_efficiency_score: float  # 0.0–1.0
    positions: List[EfficiencyReport]
    least_efficient: str            # position_id with lowest score
    most_efficient: str             # position_id with highest score
    portfolio_grade: str            # A / B / C / D / F
    recommendations: List[str]


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class CapitalEfficiencyScorer:
    """Score individual positions and portfolios for capital efficiency."""

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _net_yield_usd(self, pos: PositionEfficiency) -> float:
        """Annual yield after subtracting gas costs. Never negative."""
        return max(0.0, pos.annual_yield_usd - pos.gas_cost_annual_usd)

    def _net_yield_pct(self, pos: PositionEfficiency, net_yield: float) -> float:
        """Net yield as a percentage of deployed capital."""
        if pos.capital_deployed_usd <= 0:
            return 0.0
        return net_yield / pos.capital_deployed_usd * 100.0

    def _excess_return_pct(self, net_yield_pct: float, opp_cost: float) -> float:
        """Alpha over the risk-free opportunity cost."""
        return net_yield_pct - opp_cost

    def _yield_per_risk_unit(self, net_yield_pct: float, risk_score: float) -> float:
        """Yield earned per unit of risk taken.

        If risk_score == 0, treat as near-zero risk → multiply by 100
        (very efficient: free lunch with zero risk).
        """
        if risk_score <= 0:
            return net_yield_pct * 100.0
        return net_yield_pct / risk_score

    def _capital_efficiency_score(
        self, excess_pct: float, yield_per_risk: float
    ) -> float:
        """Combine excess return and yield-per-risk into [0.0, 1.0] score.

        excess_component  = min(1.0, max(0.0, excess_pct / 10.0))   # 10% excess = perfect
        risk_component    = min(1.0, yield_per_risk / 50.0)          # 50 yield/risk = perfect
        score = excess_component * 0.6 + risk_component * 0.4
        """
        excess_component = min(1.0, max(0.0, excess_pct / 10.0))
        risk_component = min(1.0, yield_per_risk / 50.0)
        return excess_component * 0.6 + risk_component * 0.4

    def _efficiency_grade(self, score: float) -> str:
        """Map [0, 1] score to letter grade A–F."""
        if score >= 0.8:
            return "A"
        if score >= 0.6:
            return "B"
        if score >= 0.4:
            return "C"
        if score >= 0.2:
            return "D"
        return "F"

    def _recommendation(self, grade: str, excess_pct: float, is_worth_it: bool) -> str:
        """Human-readable recommendation based on grade and worth."""
        if grade == "A":
            return "✅ Highly efficient — maintain or increase allocation"
        if grade == "B":
            return "📋 Good efficiency — suitable for core allocation"
        if grade == "C":
            return "⚠️ Average efficiency — monitor for better alternatives"
        # D or F
        base = "🚨 Poor efficiency — consider reallocation"
        if not is_worth_it:
            base += " — barely beating risk-free rate"
        return base

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_position(self, pos: PositionEfficiency) -> EfficiencyReport:
        """Score a single position and return an EfficiencyReport."""
        net_usd = self._net_yield_usd(pos)
        net_pct = self._net_yield_pct(pos, net_usd)
        excess = self._excess_return_pct(net_pct, pos.opportunity_cost_pct)
        ypr = self._yield_per_risk_unit(net_pct, pos.risk_score)
        score = self._capital_efficiency_score(excess, ypr)
        grade = self._efficiency_grade(score)
        is_worth_it = excess > 1.0
        rec = self._recommendation(grade, excess, is_worth_it)
        return EfficiencyReport(
            position_id=pos.position_id,
            protocol=pos.protocol,
            net_yield_usd=net_usd,
            net_yield_pct=net_pct,
            excess_return_pct=excess,
            yield_per_risk_unit=ypr,
            capital_efficiency_score=score,
            efficiency_grade=grade,
            is_worth_it=is_worth_it,
            recommendation=rec,
        )

    def score_portfolio(
        self, positions: List[PositionEfficiency]
    ) -> PortfolioEfficiencyReport:
        """Score all positions and aggregate into a PortfolioEfficiencyReport.

        Raises ValueError if positions list is empty.
        """
        if not positions:
            raise ValueError("Cannot score an empty portfolio")

        reports = [self.score_position(p) for p in positions]

        total_capital = sum(p.capital_deployed_usd for p in positions)
        total_net_yield = sum(r.net_yield_usd for r in reports)

        if total_capital > 0:
            port_net_yield_pct = total_net_yield / total_capital * 100.0
            weighted_risk = (
                sum(p.capital_deployed_usd * p.risk_score for p in positions)
                / total_capital
            )
        else:
            port_net_yield_pct = 0.0
            weighted_risk = 0.0

        port_efficiency_score = (
            sum(r.capital_efficiency_score for r in reports) / len(reports)
        )

        if weighted_risk > 0:
            port_yield_per_risk = port_net_yield_pct / weighted_risk
        else:
            port_yield_per_risk = 0.0

        least_id = min(reports, key=lambda r: r.capital_efficiency_score).position_id
        most_id = max(reports, key=lambda r: r.capital_efficiency_score).position_id

        port_grade = self._efficiency_grade(port_efficiency_score)

        recs: List[str] = []
        if weighted_risk > 0.5:
            recs.append(
                "⚠️ Portfolio risk-weighted score high — rebalance toward safer assets"
            )
        if port_net_yield_pct < 3.0:
            recs.append(
                "📋 Portfolio yield below 3% — underperforming risk-free rate"
            )
        if port_efficiency_score > 0.7:
            recs.append("✅ Portfolio capital efficiency excellent")

        return PortfolioEfficiencyReport(
            total_capital_usd=total_capital,
            total_net_yield_usd=total_net_yield,
            portfolio_net_yield_pct=port_net_yield_pct,
            weighted_risk_score=weighted_risk,
            portfolio_yield_per_risk=port_yield_per_risk,
            portfolio_efficiency_score=port_efficiency_score,
            positions=reports,
            least_efficient=least_id,
            most_efficient=most_id,
            portfolio_grade=port_grade,
            recommendations=recs,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(self, report: PortfolioEfficiencyReport) -> None:
        """Atomically append a portfolio report to the ring-buffer log file."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self.load_history()
        entry = {
            "timestamp": time.time(),
            "report": _report_to_dict(report),
        }
        existing.append(entry)
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]
        _atomic_write(self.data_file, existing)

    def load_history(self) -> list:
        """Load existing log entries; returns [] if file missing or corrupt."""
        if not self.data_file.exists():
            return []
        try:
            with open(self.data_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report_to_dict(report: PortfolioEfficiencyReport) -> dict:
    """Convert PortfolioEfficiencyReport to a plain dict for JSON."""
    d = asdict(report)
    return d


def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# CLI entry-point (advisory, read-only)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("CapitalEfficiencyScorer — MP-681 (advisory, read-only)")
    print("No live positions loaded; use from cycle_runner or direct API.")
    sys.exit(0)

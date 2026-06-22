"""Tokenomics Risk Analyzer (MP-701).

Analyzes token supply dynamics, inflation, vesting cliffs, and concentration
risk to surface hidden risks in DeFi protocol tokens.

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* All writes are atomic: ``tmp-file + os.replace``.
* Ring-buffer capped at :data:`MAX_ENTRIES` entries (100).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Data File
---------
``data/tokenomics_risk_log.json``::

    [<TokenomicsReport dicts>, ...]   # ring-buffer ≤ 100

Public API
----------
``TokenomicsRiskAnalyzer(data_dir="data")``

    analyze(...) -> TokenomicsReport
    compare_tokens(reports) -> dict
    save_results(report) -> None
    load_history() -> list
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE_NAME = "tokenomics_risk_log.json"
MAX_ENTRIES = 100

# Inflation risk thresholds
INFL_THRESHOLDS = [
    (0.0, 0),     # == 0 → 0
    (2.0, 10),    # ≤ 2 → 10
    (5.0, 25),    # ≤ 5 → 25
    (10.0, 45),   # ≤ 10 → 45
    (20.0, 65),   # ≤ 20 → 65
    (50.0, 80),   # ≤ 50 → 80
]
INFL_ABOVE_50_SCORE = 95
INFL_UNLIMITED_BONUS = 10

# Risk label thresholds (overall_risk)
RISK_LOW_MAX = 25.0
RISK_MEDIUM_MAX = 50.0
RISK_HIGH_MAX = 70.0

# Warning thresholds
WARN_INFLATION_PCT = 20.0
WARN_TOP10_PCT = 60.0
WARN_UPCOMING_UNLOCKS_PCT = 10.0
WARN_TEAM_ALLOC_PCT = 20.0
WARN_INVESTOR_ALLOC_PCT = 30.0

# Weighted average coefficients
W_INFLATION = 0.30
W_CONCENTRATION = 0.35
W_VESTING = 0.35


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VestingSchedule:
    """Vesting info for a single token allocation category."""
    category: str           # "team" | "investors" | "foundation" | "ecosystem"
    total_pct: float        # % of total supply allocated
    cliff_months: int       # months before any unlock
    vesting_months: int     # total vesting duration
    unlocked_pct: float     # already unlocked %


@dataclass
class TokenomicsReport:
    """Full tokenomics risk report for a single token."""
    token_symbol: str
    circulating_supply: float
    total_supply: float
    max_supply: float           # 0 if unlimited

    inflation_rate_annual: float

    # Concentration
    top10_holders_pct: float
    team_allocation_pct: float
    investor_allocation_pct: float

    # Vesting
    schedules: List[VestingSchedule]
    upcoming_unlocks_pct: float   # % of circulating supply unlocking within ~3 months
    largest_cliff_pct: float      # largest single cliff unlock as % of circ supply

    # Risk scores (0–100, higher = riskier)
    inflation_risk: float
    concentration_risk: float
    vesting_cliff_risk: float
    overall_risk: float

    risk_label: str         # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    warnings: List[str]
    saved_to: str
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class TokenomicsRiskAnalyzer:
    """Advisory analyzer for token supply and vesting risk."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_file = self.data_dir / DATA_FILE_NAME

    # ------------------------------------------------------------------
    # Risk score helpers
    # ------------------------------------------------------------------

    def _inflation_risk(self, inflation_rate: float, max_supply: float) -> float:
        """Score inflation risk 0–100."""
        if inflation_rate == 0.0:
            score = 0.0
        elif inflation_rate <= 2.0:
            score = 10.0
        elif inflation_rate <= 5.0:
            score = 25.0
        elif inflation_rate <= 10.0:
            score = 45.0
        elif inflation_rate <= 20.0:
            score = 65.0
        elif inflation_rate <= 50.0:
            score = 80.0
        else:
            score = float(INFL_ABOVE_50_SCORE)

        # Unlimited max supply adds +10
        if max_supply == 0.0:
            score += INFL_UNLIMITED_BONUS

        return min(100.0, score)

    def _concentration_risk(
        self,
        top10_holders_pct: float,
        team_allocation_pct: float,
        investor_allocation_pct: float,
    ) -> float:
        """Score concentration risk 0–100."""
        basis = (top10_holders_pct + team_allocation_pct + investor_allocation_pct) / 3.0
        return min(100.0, basis * 1.2)

    def _compute_upcoming_unlocks(
        self,
        schedules: List[VestingSchedule],
        current_month: int,
    ) -> float:
        """Sum total_pct for schedules whose cliff occurs within the next 3 months."""
        total = 0.0
        for s in schedules:
            # Include schedule if its cliff date falls within the upcoming 3-month window
            if current_month <= s.cliff_months < current_month + 3:
                total += s.total_pct
        return total

    def _compute_largest_cliff(self, schedules: List[VestingSchedule]) -> float:
        """Largest single schedule total_pct (proxy for cliff unlock impact)."""
        if not schedules:
            return 0.0
        return max(s.total_pct for s in schedules)

    def _vesting_cliff_risk(
        self,
        upcoming_unlocks_pct: float,
        largest_cliff_pct: float,
    ) -> float:
        """Score vesting/cliff risk 0–100."""
        return min(100.0, upcoming_unlocks_pct * 2.0 + largest_cliff_pct * 1.5)

    def _overall_risk(
        self,
        inflation_risk: float,
        concentration_risk: float,
        vesting_cliff_risk: float,
    ) -> float:
        """Weighted average of the three risk dimensions."""
        return (
            inflation_risk * W_INFLATION
            + concentration_risk * W_CONCENTRATION
            + vesting_cliff_risk * W_VESTING
        )

    def _risk_label(self, overall_risk: float) -> str:
        if overall_risk < RISK_LOW_MAX:
            return "LOW"
        if overall_risk < RISK_MEDIUM_MAX:
            return "MEDIUM"
        if overall_risk < RISK_HIGH_MAX:
            return "HIGH"
        return "CRITICAL"

    def _build_warnings(
        self,
        inflation_rate: float,
        top10_holders_pct: float,
        upcoming_unlocks_pct: float,
        team_allocation_pct: float,
        investor_allocation_pct: float,
    ) -> List[str]:
        warnings: List[str] = []
        if inflation_rate > WARN_INFLATION_PCT:
            warnings.append(
                f"HIGH INFLATION: annual inflation {inflation_rate:.1f}% exceeds {WARN_INFLATION_PCT:.0f}% threshold — "
                f"significant supply dilution expected"
            )
        if top10_holders_pct > WARN_TOP10_PCT:
            warnings.append(
                f"HIGH CONCENTRATION: top-10 holders control {top10_holders_pct:.1f}% of supply — "
                f"manipulation risk elevated"
            )
        if upcoming_unlocks_pct > WARN_UPCOMING_UNLOCKS_PCT:
            warnings.append(
                f"CLIFF UNLOCK RISK: {upcoming_unlocks_pct:.1f}% of supply unlocks within ~3 months — "
                f"potential sell pressure"
            )
        if team_allocation_pct > WARN_TEAM_ALLOC_PCT:
            warnings.append(
                f"TEAM ALLOCATION: {team_allocation_pct:.1f}% allocated to team exceeds {WARN_TEAM_ALLOC_PCT:.0f}% — "
                f"insider concentration risk"
            )
        if investor_allocation_pct > WARN_INVESTOR_ALLOC_PCT:
            warnings.append(
                f"INVESTOR ALLOCATION: {investor_allocation_pct:.1f}% allocated to investors exceeds "
                f"{WARN_INVESTOR_ALLOC_PCT:.0f}% — early-exit pressure possible"
            )
        return warnings

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def analyze(
        self,
        token_symbol: str,
        circulating_supply: float,
        total_supply: float,
        max_supply: float,
        inflation_rate_annual: float,
        top10_holders_pct: float,
        team_allocation_pct: float,
        investor_allocation_pct: float,
        schedules: List[VestingSchedule],
        current_month: int = 0,
    ) -> TokenomicsReport:
        """Compute a full tokenomics risk report."""
        infl_risk = self._inflation_risk(inflation_rate_annual, max_supply)
        conc_risk = self._concentration_risk(
            top10_holders_pct, team_allocation_pct, investor_allocation_pct
        )
        upcoming = self._compute_upcoming_unlocks(schedules, current_month)
        largest_cliff = self._compute_largest_cliff(schedules)
        vest_risk = self._vesting_cliff_risk(upcoming, largest_cliff)
        overall = self._overall_risk(infl_risk, conc_risk, vest_risk)
        label = self._risk_label(overall)
        warnings = self._build_warnings(
            inflation_rate_annual, top10_holders_pct,
            upcoming, team_allocation_pct, investor_allocation_pct,
        )

        return TokenomicsReport(
            token_symbol=token_symbol,
            circulating_supply=circulating_supply,
            total_supply=total_supply,
            max_supply=max_supply,
            inflation_rate_annual=inflation_rate_annual,
            top10_holders_pct=top10_holders_pct,
            team_allocation_pct=team_allocation_pct,
            investor_allocation_pct=investor_allocation_pct,
            schedules=schedules,
            upcoming_unlocks_pct=upcoming,
            largest_cliff_pct=largest_cliff,
            inflation_risk=round(infl_risk, 4),
            concentration_risk=round(conc_risk, 4),
            vesting_cliff_risk=round(vest_risk, 4),
            overall_risk=round(overall, 4),
            risk_label=label,
            warnings=warnings,
            saved_to=str(self.data_file),
        )

    def compare_tokens(self, reports: List[TokenomicsReport]) -> Dict[str, object]:
        """Rank tokens by overall_risk (lowest = safest)."""
        sorted_reports = sorted(reports, key=lambda r: r.overall_risk)
        ranking = {}
        for rank, report in enumerate(sorted_reports, start=1):
            ranking[report.token_symbol] = {
                "rank": rank,
                "overall_risk": report.overall_risk,
                "risk_label": report.risk_label,
                "inflation_risk": report.inflation_risk,
                "concentration_risk": report.concentration_risk,
                "vesting_cliff_risk": report.vesting_cliff_risk,
                "warnings_count": len(report.warnings),
            }
        return ranking

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(self, report: TokenomicsReport) -> None:
        """Append report to ring-buffer log (max MAX_ENTRIES)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        existing: list = []
        if self.data_file.exists():
            try:
                existing = json.loads(self.data_file.read_text())
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        entry = _report_to_dict(report)
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()

        existing.append(entry)
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> list:
        """Return list of saved reports."""
        if not self.data_file.exists():
            return []
        try:
            data = json.loads(self.data_file.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _schedule_to_dict(s: VestingSchedule) -> dict:
    return asdict(s)


def _report_to_dict(r: TokenomicsReport) -> dict:
    return {
        "token_symbol": r.token_symbol,
        "circulating_supply": r.circulating_supply,
        "total_supply": r.total_supply,
        "max_supply": r.max_supply,
        "inflation_rate_annual": r.inflation_rate_annual,
        "top10_holders_pct": r.top10_holders_pct,
        "team_allocation_pct": r.team_allocation_pct,
        "investor_allocation_pct": r.investor_allocation_pct,
        "schedules": [_schedule_to_dict(s) for s in r.schedules],
        "upcoming_unlocks_pct": r.upcoming_unlocks_pct,
        "largest_cliff_pct": r.largest_cliff_pct,
        "inflation_risk": r.inflation_risk,
        "concentration_risk": r.concentration_risk,
        "vesting_cliff_risk": r.vesting_cliff_risk,
        "overall_risk": r.overall_risk,
        "risk_label": r.risk_label,
        "warnings": r.warnings,
        "saved_to": r.saved_to,
        "timestamp": r.timestamp,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="TokenomicsRiskAnalyzer CLI")
    parser.add_argument("--symbol", default="TKN")
    parser.add_argument("--inflation", type=float, default=5.0)
    parser.add_argument("--top10", type=float, default=40.0)
    parser.add_argument("--team", type=float, default=15.0)
    parser.add_argument("--investor", type=float, default=20.0)
    parser.add_argument("--max-supply", type=float, default=1_000_000_000.0)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    analyzer = TokenomicsRiskAnalyzer(data_dir=args.data_dir)
    report = analyzer.analyze(
        token_symbol=args.symbol,
        circulating_supply=500_000_000.0,
        total_supply=1_000_000_000.0,
        max_supply=args.max_supply,
        inflation_rate_annual=args.inflation,
        top10_holders_pct=args.top10,
        team_allocation_pct=args.team,
        investor_allocation_pct=args.investor,
        schedules=[],
        current_month=0,
    )
    print(json.dumps(_report_to_dict(report), indent=2))
    if args.run:
        analyzer.save_results(report)
        print(f"\nSaved to {analyzer.data_file}")


if __name__ == "__main__":
    _cli()

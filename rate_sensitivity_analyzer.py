"""
MP-656: RateSensitivityAnalyzer
Estimate how sensitive portfolio APY is to interest rate changes.
DV01-style analysis for DeFi lending positions.
Advisory/read-only. Pure stdlib. Atomic writes.
"""
from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/rate_sensitivity_log.json")
MAX_ENTRIES = 100

# Rate shock scenarios (basis points)
SHOCKS_BPS = [-200, -100, -50, +50, +100, +200]


@dataclass
class AdapterRateInput:
    adapter_id: str
    capital_usd: float
    base_apy: float          # current APY (decimal, e.g. 0.05 = 5%)
    rate_beta: float         # sensitivity: APY change per 100bps rate move
                             # e.g. 0.5 → 50bps APY change per 100bps rate change
    is_variable_rate: bool   # True = floating rate, more sensitive


@dataclass
class RateShockResult:
    shock_bps: int
    shocked_apy: float       # base_apy + shock_bps/10000 * rate_beta (clamped ≥ 0)
    apy_change_bps: float    # difference from base in bps
    pnl_impact_usd: float    # capital * (shocked_apy - base_apy) annualized
    direction: str           # POSITIVE / NEGATIVE / NEUTRAL


@dataclass
class SensitivityReport:
    adapter_id: str
    capital_usd: float
    base_apy: float
    rate_beta: float
    is_variable_rate: bool
    dv01_usd: float              # dollar value of 1bp rate move (annualized)
    worst_case_pnl_usd: float    # worst shock scenario PnL impact
    best_case_pnl_usd: float     # best shock scenario PnL impact
    sensitivity_grade: str       # LOW / MEDIUM / HIGH / VERY_HIGH
    shock_results: List[RateShockResult]


class RateSensitivityAnalyzer:
    def __init__(self, data_file: Path = DATA_FILE,
                 shocks_bps: List[int] = None):
        self.data_file = data_file
        self.shocks_bps = shocks_bps if shocks_bps is not None else list(SHOCKS_BPS)

    def _shocked_apy(self, base_apy: float, rate_beta: float, shock_bps: int) -> float:
        """APY after rate shock. Clamped at 0.0 (APY cannot go negative)."""
        delta = (shock_bps / 10000) * rate_beta
        return max(0.0, round(base_apy + delta, 6))

    def _dv01(self, capital: float, rate_beta: float) -> float:
        """Dollar value of 1bp rate move (annualized)."""
        return round(capital * rate_beta * 0.0001, 4)

    def _sensitivity_grade(self, dv01: float, capital: float) -> str:
        """Grade based on DV01 as basis points of capital per year."""
        if capital <= 0:
            return "LOW"
        dv01_pct = (dv01 / capital) * 10000  # bps of capital
        if dv01_pct >= 10:
            return "VERY_HIGH"
        if dv01_pct >= 5:
            return "HIGH"
        if dv01_pct >= 2:
            return "MEDIUM"
        return "LOW"

    def analyze(self, inp: AdapterRateInput) -> SensitivityReport:
        """Produce a full sensitivity report for one adapter position."""
        shock_results = []
        for shock in self.shocks_bps:
            shocked = self._shocked_apy(inp.base_apy, inp.rate_beta, shock)
            apy_chg_bps = round((shocked - inp.base_apy) * 10000, 4)
            pnl_impact = round(inp.capital_usd * (shocked - inp.base_apy), 4)
            if pnl_impact > 0:
                direction = "POSITIVE"
            elif pnl_impact < 0:
                direction = "NEGATIVE"
            else:
                direction = "NEUTRAL"
            shock_results.append(RateShockResult(
                shock_bps=shock,
                shocked_apy=shocked,
                apy_change_bps=apy_chg_bps,
                pnl_impact_usd=pnl_impact,
                direction=direction,
            ))

        pnl_impacts = [r.pnl_impact_usd for r in shock_results]
        dv01 = self._dv01(inp.capital_usd, inp.rate_beta)
        return SensitivityReport(
            adapter_id=inp.adapter_id,
            capital_usd=round(inp.capital_usd, 2),
            base_apy=round(inp.base_apy, 6),
            rate_beta=round(inp.rate_beta, 4),
            is_variable_rate=inp.is_variable_rate,
            dv01_usd=dv01,
            worst_case_pnl_usd=round(min(pnl_impacts), 4),
            best_case_pnl_usd=round(max(pnl_impacts), 4),
            sensitivity_grade=self._sensitivity_grade(dv01, inp.capital_usd),
            shock_results=shock_results,
        )

    def analyze_batch(self, inputs: List[AdapterRateInput]) -> List[SensitivityReport]:
        """Analyze multiple adapter positions."""
        return [self.analyze(inp) for inp in inputs]

    def portfolio_dv01(self, reports: List[SensitivityReport]) -> float:
        """Sum DV01 across all reports."""
        return round(sum(r.dv01_usd for r in reports), 4)

    def save_reports(self, reports: List[SensitivityReport]) -> None:
        """Append reports to ring-buffer JSON log. Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in reports:
            existing.append({
                "timestamp": time.time(),
                "adapter_id": r.adapter_id,
                "dv01_usd": r.dv01_usd,
                "sensitivity_grade": r.sensitivity_grade,
                "worst_case_pnl_usd": r.worst_case_pnl_usd,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load ring-buffer log. Returns [] on missing/corrupt file."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

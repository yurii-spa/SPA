"""
MP-685: DebtRatioAnalyzer
Analyze debt ratios across lending protocol positions to assess overall
leverage risk and sustainability.
Advisory/read-only. Pure stdlib. Atomic writes.
"""
from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/debt_ratio_log.json")
MAX_ENTRIES = 100


@dataclass
class DebtPosition:
    position_id: str
    protocol: str
    strategy: str               # "YIELD_LOOP", "LEVERAGED_STAKING", "SIMPLE_BORROW"
    gross_assets_usd: float     # total assets including borrowed
    net_assets_usd: float       # own capital only (gross - debt)
    total_debt_usd: float       # total borrowed amount
    interest_rate_pct: float    # annual interest on debt
    gross_yield_pct: float      # yield on gross assets


@dataclass
class DebtRatioReport:
    position_id: str
    strategy: str
    leverage_ratio: float        # gross / net (1.0 = no leverage)
    debt_to_equity: float        # debt / net_assets
    interest_coverage: float     # gross_yield_income / interest_cost (999 if no debt)
    net_yield_pct: float         # (gross_yield_income - interest_cost) / net_assets * 100
    carry_spread_bps: float      # (gross_yield - interest_rate) * 100
    risk_level: str              # CONSERVATIVE / MODERATE / AGGRESSIVE / EXTREME
    is_cash_flow_positive: bool  # interest_coverage > 1.0
    recommendation: str


@dataclass
class PortfolioLeverageReport:
    total_gross_usd: float
    total_net_usd: float
    total_debt_usd: float
    portfolio_leverage: float       # total_gross / total_net
    portfolio_debt_ratio: float     # total_debt / total_gross
    weighted_carry_spread_bps: float
    highest_leverage_position: str  # position_id
    positions: List[DebtRatioReport]
    leverage_grade: str             # A / B / C / D / F
    recommendations: List[str]


class DebtRatioAnalyzer:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------ #
    #  Core calculations                                                   #
    # ------------------------------------------------------------------ #

    def _leverage_ratio(self, gross: float, net: float) -> float:
        """gross / net. Returns 999.0 when net <= 0."""
        if net <= 0:
            return 999.0
        return gross / net

    def _debt_to_equity(self, debt: float, net: float) -> float:
        """debt / net. Returns 999.0 when net <= 0."""
        if net <= 0:
            return 999.0
        return debt / net

    def _gross_yield_income(self, gross: float, gross_yield_pct: float) -> float:
        """Annual yield income in USD from gross assets."""
        return gross * gross_yield_pct / 100.0

    def _interest_cost(self, debt: float, interest_rate_pct: float) -> float:
        """Annual interest cost in USD."""
        return debt * interest_rate_pct / 100.0

    def _interest_coverage(self, gross_yield_income: float,
                            interest_cost: float) -> float:
        """Ratio of yield income to interest cost. 999.0 if no interest cost."""
        if interest_cost <= 0:
            return 999.0
        return gross_yield_income / interest_cost

    def _net_yield_pct(self, gross_yield_income: float, interest_cost: float,
                        net: float) -> float:
        """Net yield as % of net assets."""
        if net <= 0:
            return 0.0
        return (gross_yield_income - interest_cost) / net * 100.0

    def _carry_spread_bps(self, gross_yield_pct: float,
                           interest_rate_pct: float) -> float:
        """Carry spread in basis points."""
        return (gross_yield_pct - interest_rate_pct) * 100.0

    def _risk_level(self, leverage: float) -> str:
        """Classify leverage into risk bucket."""
        if leverage <= 1.0:
            return "CONSERVATIVE"
        if leverage <= 2.0:
            return "MODERATE"
        if leverage <= 3.5:
            return "AGGRESSIVE"
        return "EXTREME"

    def _recommendation(self, risk_level: str, leverage: float,
                         carry_bps: float, is_cfp: bool) -> str:
        """Build the recommendation string."""
        base: str
        if risk_level == "CONSERVATIVE":
            base = "✅ No leverage — pure yield strategy"
        elif risk_level == "MODERATE":
            base = (
                f"📋 Moderate leverage {leverage:.1f}x — "
                f"carry spread {carry_bps:.0f}bps"
            )
        elif risk_level == "AGGRESSIVE":
            base = (
                f"⚠️ High leverage {leverage:.1f}x — "
                f"carry spread {carry_bps:.0f}bps, risk elevated"
            )
        else:  # EXTREME
            base = (
                f"🚨 EXTREME leverage {leverage:.1f}x — "
                f"dangerous, consider deleveraging"
            )

        if not is_cfp:
            base += " — NEGATIVE CARRY: debt costs exceed yield"

        return base

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def analyze(self, pos: DebtPosition) -> DebtRatioReport:
        """Analyse a single debt position."""
        lev = self._leverage_ratio(pos.gross_assets_usd, pos.net_assets_usd)
        d2e = self._debt_to_equity(pos.total_debt_usd, pos.net_assets_usd)
        gyi = self._gross_yield_income(pos.gross_assets_usd, pos.gross_yield_pct)
        ic = self._interest_cost(pos.total_debt_usd, pos.interest_rate_pct)
        cov = self._interest_coverage(gyi, ic)
        ny = self._net_yield_pct(gyi, ic, pos.net_assets_usd)
        cs = self._carry_spread_bps(pos.gross_yield_pct, pos.interest_rate_pct)
        rl = self._risk_level(lev)
        cfp = cov > 1.0
        rec = self._recommendation(rl, lev, cs, cfp)

        return DebtRatioReport(
            position_id=pos.position_id,
            strategy=pos.strategy,
            leverage_ratio=lev,
            debt_to_equity=d2e,
            interest_coverage=cov,
            net_yield_pct=ny,
            carry_spread_bps=cs,
            risk_level=rl,
            is_cash_flow_positive=cfp,
            recommendation=rec,
        )

    def analyze_portfolio(self, positions: List[DebtPosition]) -> PortfolioLeverageReport:
        """
        Analyse a list of debt positions and produce a portfolio-level report.
        Raises ValueError on empty list.
        """
        if not positions:
            raise ValueError("analyze_portfolio requires at least one position")

        reports = [self.analyze(p) for p in positions]

        total_gross = sum(p.gross_assets_usd for p in positions)
        total_net = sum(p.net_assets_usd for p in positions)
        total_debt = sum(p.total_debt_usd for p in positions)

        port_lev = self._leverage_ratio(total_gross, total_net)
        port_dr = (total_debt / total_gross) if total_gross > 0 else 0.0

        # weighted carry spread by gross assets
        if total_gross > 0:
            w_cs = sum(
                p.gross_assets_usd * self._carry_spread_bps(p.gross_yield_pct,
                                                              p.interest_rate_pct)
                for p in positions
            ) / total_gross
        else:
            w_cs = 0.0

        # highest leverage position
        max_lev_pos = max(reports, key=lambda r: r.leverage_ratio)
        highest_lev_id = max_lev_pos.position_id

        # leverage grade
        if port_lev <= 1.5:
            grade = "A"
        elif port_lev <= 2.0:
            grade = "B"
        elif port_lev <= 3.0:
            grade = "C"
        elif port_lev <= 5.0:
            grade = "D"
        else:
            grade = "F"

        # portfolio recommendations
        recs: List[str] = []
        if port_lev > 2.5:
            recs.append(
                "⚠️ Portfolio leverage >2.5x — systemic risk in market downturn"
            )
        if any(not r.is_cash_flow_positive for r in reports):
            recs.append(
                "🚨 Negative carry positions detected — debt costs exceed yield"
            )
        if port_dr > 0.5:
            recs.append(
                "⚠️ Debt ratio >50% of gross assets — deleverage recommended"
            )
        if grade in ("A", "B"):
            recs.append("✅ Portfolio leverage within safe bounds")

        return PortfolioLeverageReport(
            total_gross_usd=total_gross,
            total_net_usd=total_net,
            total_debt_usd=total_debt,
            portfolio_leverage=port_lev,
            portfolio_debt_ratio=port_dr,
            weighted_carry_spread_bps=w_cs,
            highest_leverage_position=highest_lev_id,
            positions=reports,
            leverage_grade=grade,
            recommendations=recs,
        )

    # ------------------------------------------------------------------ #
    #  Persistence (ring-buffer, atomic)                                   #
    # ------------------------------------------------------------------ #

    def save_results(self, reports: List[DebtRatioReport]) -> None:
        """Append report summaries to ring-buffer JSON. Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        ts = time.time()
        for r in reports:
            existing.append({
                "timestamp": ts,
                "position_id": r.position_id,
                "strategy": r.strategy,
                "leverage_ratio": r.leverage_ratio,
                "risk_level": r.risk_level,
                "carry_spread_bps": r.carry_spread_bps,
                "net_yield_pct": r.net_yield_pct,
                "is_cash_flow_positive": r.is_cash_flow_positive,
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

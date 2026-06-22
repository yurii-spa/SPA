"""
MP-703: LiquidityIncentiveAnalyzer
Evaluates liquidity mining programs — separating real yield from token emissions —
to identify sustainable vs mercenary liquidity.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer cap: 100 entries.
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/liquidity_incentive_log.json")
MAX_ENTRIES = 100


@dataclass
class IncentiveProgram:
    protocol: str
    pool_name: str
    tvl_usd: float
    base_apy: float           # real yield from fees
    reward_apy: float         # token emissions APY
    total_apy: float          # base + reward
    reward_token_price_usd: float
    daily_emission_usd: float  # tokens emitted per day in USD

    # Quality metrics
    real_yield_ratio: float    # base_apy / total_apy (0 if total=0)
    emission_sustainability_days: float  # treasury_usd / daily_emission_usd
    mercenary_risk: float      # 0–100 (high = liquidity will leave when rewards stop)

    # Cost efficiency
    tvl_per_emission_dollar: float   # tvl / daily_emission_usd
    incentive_roi: float             # base_apy / (daily_emission_usd/tvl*365*100)

    quality_label: str   # "ORGANIC" | "HEALTHY" | "EMISSION_DEPENDENT" | "MERCENARY"
    warnings: List[str]
    saved_to: str


class LiquidityIncentiveAnalyzer:
    """
    Evaluates liquidity mining programs by separating organic (fee) yield from
    token emission rewards.

    Usage:
        analyzer = LiquidityIncentiveAnalyzer()
        program = analyzer.analyze(
            protocol="Uniswap",
            pool_name="ETH/USDC",
            tvl_usd=50_000_000,
            base_apy=8.0,
            reward_apy=5.0,
            reward_token_price_usd=2.50,
            daily_emission_usd=10_000,
            treasury_usd=1_000_000,
        )
        analyzer.save_results(program)
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _real_yield_ratio(self, base_apy: float, total_apy: float) -> float:
        """base_apy / total_apy; 0 if total_apy == 0."""
        if total_apy == 0.0:
            return 0.0
        return base_apy / total_apy

    def _emission_sustainability_days(
        self, treasury_usd: float, daily_emission_usd: float
    ) -> float:
        """treasury_usd / daily_emission_usd; 9999 if emission == 0."""
        if daily_emission_usd == 0.0:
            return 9999.0
        return treasury_usd / daily_emission_usd

    def _mercenary_risk(self, real_yield_ratio: float) -> float:
        """(1 - real_yield_ratio) * 100; 0–100."""
        return (1.0 - real_yield_ratio) * 100.0

    def _tvl_per_emission_dollar(
        self, tvl_usd: float, daily_emission_usd: float
    ) -> float:
        """tvl_usd / daily_emission_usd; 0 if emission == 0."""
        if daily_emission_usd == 0.0:
            return 0.0
        return tvl_usd / daily_emission_usd

    def _incentive_roi(
        self, base_apy: float, daily_emission_usd: float, tvl_usd: float
    ) -> float:
        """
        emission_rate_annual = daily_emission_usd / tvl_usd * 365 * 100
        roi = base_apy / emission_rate_annual
        Returns 0 if emission_rate_annual == 0 (i.e. daily_emission==0 or tvl==0).
        """
        if daily_emission_usd == 0.0 or tvl_usd == 0.0:
            return 0.0
        emission_rate_annual = daily_emission_usd / tvl_usd * 365 * 100
        if emission_rate_annual == 0.0:
            return 0.0
        return base_apy / emission_rate_annual

    def _quality_label(
        self,
        real_yield_ratio: float,
        emission_sustainability_days: float,
    ) -> str:
        """
        ORGANIC              → real_yield_ratio >= 0.7
        HEALTHY              → real_yield_ratio >= 0.4 AND sustainability > 180
        EMISSION_DEPENDENT   → real_yield_ratio >= 0.2
        MERCENARY            → else
        """
        if real_yield_ratio >= 0.7:
            return "ORGANIC"
        if real_yield_ratio >= 0.4 and emission_sustainability_days > 180:
            return "HEALTHY"
        if real_yield_ratio >= 0.2:
            return "EMISSION_DEPENDENT"
        return "MERCENARY"

    def _build_warnings(
        self,
        emission_sustainability_days: float,
        mercenary_risk: float,
        reward_apy: float,
        base_apy: float,
    ) -> List[str]:
        """Generate advisory warnings."""
        warnings = []
        if emission_sustainability_days < 30:
            warnings.append("emissions run out in <30 days")
        if mercenary_risk > 80:
            warnings.append("high mercenary risk")
        if base_apy > 0 and reward_apy > base_apy * 5:
            warnings.append("reward dominates")
        elif base_apy == 0 and reward_apy > 0:
            warnings.append("reward dominates")
        return warnings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        protocol: str,
        pool_name: str,
        tvl_usd: float,
        base_apy: float,
        reward_apy: float,
        reward_token_price_usd: float,
        daily_emission_usd: float,
        treasury_usd: float,
    ) -> IncentiveProgram:
        """
        Analyze a liquidity incentive program.

        Args:
            protocol: Protocol name (e.g. "Curve").
            pool_name: Pool identifier (e.g. "3pool").
            tvl_usd: Total value locked in pool (USD).
            base_apy: Organic APY from fees (%).
            reward_apy: Emissions APY (%).
            reward_token_price_usd: Current price of reward token.
            daily_emission_usd: Daily token emissions in USD.
            treasury_usd: Protocol treasury in USD (for sustainability calc).
        """
        total_apy = base_apy + reward_apy

        ryr = self._real_yield_ratio(base_apy, total_apy)
        esd = self._emission_sustainability_days(treasury_usd, daily_emission_usd)
        mer = self._mercenary_risk(ryr)
        tped = self._tvl_per_emission_dollar(tvl_usd, daily_emission_usd)
        iroi = self._incentive_roi(base_apy, daily_emission_usd, tvl_usd)
        ql = self._quality_label(ryr, esd)
        warnings = self._build_warnings(esd, mer, reward_apy, base_apy)

        return IncentiveProgram(
            protocol=protocol,
            pool_name=pool_name,
            tvl_usd=round(tvl_usd, 4),
            base_apy=round(base_apy, 6),
            reward_apy=round(reward_apy, 6),
            total_apy=round(total_apy, 6),
            reward_token_price_usd=round(reward_token_price_usd, 6),
            daily_emission_usd=round(daily_emission_usd, 4),
            real_yield_ratio=round(ryr, 8),
            emission_sustainability_days=round(esd, 4),
            mercenary_risk=round(mer, 6),
            tvl_per_emission_dollar=round(tped, 6),
            incentive_roi=round(iroi, 8),
            quality_label=ql,
            warnings=warnings,
            saved_to=str(self.data_file),
        )

    def compare_pools(
        self,
        programs: List[IncentiveProgram],
    ) -> List[IncentiveProgram]:
        """Return programs sorted by real_yield_ratio descending."""
        return sorted(programs, key=lambda p: p.real_yield_ratio, reverse=True)

    def find_best_risk_adjusted(
        self,
        programs: List[IncentiveProgram],
    ) -> Optional[IncentiveProgram]:
        """
        Return the program with the highest (base_apy / max(mercenary_risk, 1)).
        Returns None if programs is empty.
        """
        if not programs:
            return None
        return max(
            programs,
            key=lambda p: p.base_apy / max(p.mercenary_risk, 1.0),
        )

    def save_results(self, program: IncentiveProgram) -> None:
        """
        Append one IncentiveProgram to the ring-buffer JSON log (max MAX_ENTRIES).
        Atomic write: tmp + os.replace.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: list = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        entry = {
            "timestamp": time.time(),
            "protocol": program.protocol,
            "pool_name": program.pool_name,
            "tvl_usd": program.tvl_usd,
            "base_apy": program.base_apy,
            "reward_apy": program.reward_apy,
            "total_apy": program.total_apy,
            "reward_token_price_usd": program.reward_token_price_usd,
            "daily_emission_usd": program.daily_emission_usd,
            "real_yield_ratio": program.real_yield_ratio,
            "emission_sustainability_days": program.emission_sustainability_days,
            "mercenary_risk": program.mercenary_risk,
            "tvl_per_emission_dollar": program.tvl_per_emission_dollar,
            "incentive_roi": program.incentive_roi,
            "quality_label": program.quality_label,
            "warnings": program.warnings,
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> list:
        """Load saved ring-buffer log; returns [] on any error."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

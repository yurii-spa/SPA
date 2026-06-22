"""
MP-666: StablecoinRiskAssessor
Assess depeg risk for stablecoins used as collateral or yield sources.
Advisory/read-only. Pure stdlib. Atomic JSON writes (os.replace).
"""
from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/stablecoin_risk_log.json")
MAX_ENTRIES = 100

# Peg thresholds (fraction of $1.00)
PEG_THRESHOLDS = {
    "ON_PEG":     0.0050,   # within 0.5% of $1.00
    "SOFT_DEPEG": 0.0200,   # 0.5% to 2.0% deviation
    "HARD_DEPEG": 0.0500,   # 2.0% to 5.0% deviation
    # CRISIS: >5% deviation
}


@dataclass
class StablecoinInput:
    symbol: str                      # e.g. "USDC", "DAI", "USDT", "FRAX"
    current_price: float             # current market price in USD
    peg_target: float                # target price, usually 1.0
    collateral_ratio: float          # backing ratio (e.g. 1.50 = 150%)
    is_algorithmic: bool             # purely algo stablecoins are higher risk
    audit_count: int                 # number of security audits
    market_cap_usd: float            # current market cap
    capital_exposure_usd: float      # SPA's exposure in USD


@dataclass
class StablecoinRisk:
    symbol: str
    current_price: float
    peg_target: float
    deviation_pct: float             # abs((current - target) / target) * 100
    peg_status: str                  # ON_PEG / SOFT_DEPEG / HARD_DEPEG / CRISIS
    collateral_score: float          # 0-100 (100=200%+ collateral, 0=uncollateralized)
    algo_risk_score: float           # 0-100 (100=fully backed, 50=hybrid, 20=algo)
    audit_score: float               # 0-100
    size_score: float                # 0-100 (100=market_cap>10B)
    composite_risk_score: float      # weighted 0-100 (higher=safer)
    risk_grade: str                  # A/B/C/D
    exposure_at_risk_usd: float      # capital_exposure * (deviation_pct/100)
    recommendation: str              # HOLD / REDUCE / EXIT


class StablecoinRiskAssessor:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _deviation_pct(self, current: float, target: float) -> float:
        if target <= 0:
            return 0.0
        return round(abs((current - target) / target) * 100, 4)

    def _peg_status(self, dev_pct: float) -> str:
        if dev_pct <= PEG_THRESHOLDS["ON_PEG"] * 100:
            return "ON_PEG"
        if dev_pct <= PEG_THRESHOLDS["SOFT_DEPEG"] * 100:
            return "SOFT_DEPEG"
        if dev_pct <= PEG_THRESHOLDS["HARD_DEPEG"] * 100:
            return "HARD_DEPEG"
        return "CRISIS"

    def _collateral_score(self, ratio: float) -> float:
        """100=ratio>=2.0, 80=1.5, 60=1.2, 40=1.0, 0<1.0"""
        if ratio >= 2.0:
            return 100.0
        if ratio >= 1.5:
            return 80.0 + 20.0 * (ratio - 1.5) / 0.5
        if ratio >= 1.2:
            return 60.0 + 20.0 * (ratio - 1.2) / 0.3
        if ratio >= 1.0:
            return 40.0 + 20.0 * (ratio - 1.0) / 0.2
        return max(0.0, ratio * 40.0)

    def _algo_risk_score(self, is_algo: bool, collateral_ratio: float) -> float:
        if not is_algo:
            return 90.0            # fully backed
        if collateral_ratio >= 1.5:
            return 60.0            # hybrid (partially algo)
        return 20.0                # pure algo

    def _audit_score(self, count: int) -> float:
        mapping = {0: 0.0, 1: 25.0, 2: 50.0, 3: 75.0}
        return mapping.get(count, 100.0)

    def _size_score(self, market_cap: float) -> float:
        if market_cap >= 10_000_000_000:
            return 100.0
        if market_cap >= 1_000_000_000:
            return 80.0
        if market_cap >= 100_000_000:
            return 50.0
        if market_cap >= 10_000_000:
            return 20.0
        return 0.0

    def _recommendation(self, grade: str, peg_status: str) -> str:
        if peg_status in ("HARD_DEPEG", "CRISIS"):
            return "EXIT"
        if grade == "D" or peg_status == "SOFT_DEPEG":
            return "REDUCE"
        return "HOLD"

    def assess(self, inp: StablecoinInput) -> StablecoinRisk:
        dev = self._deviation_pct(inp.current_price, inp.peg_target)
        peg = self._peg_status(dev)
        col = self._collateral_score(inp.collateral_ratio)
        algo = self._algo_risk_score(inp.is_algorithmic, inp.collateral_ratio)
        aud = self._audit_score(inp.audit_count)
        sz = self._size_score(inp.market_cap_usd)

        # Weighted composite (higher = safer)
        composite = (
            col * 0.30
            + algo * 0.25
            + aud * 0.20
            + sz * 0.15
            + max(0, 100 - dev * 10) * 0.10
        )
        composite = round(min(100.0, max(0.0, composite)), 4)

        grade_map = [(80, "A"), (65, "B"), (50, "C"), (0, "D")]
        grade = next(g for t, g in grade_map if composite >= t)

        exposure_at_risk = round(inp.capital_exposure_usd * (dev / 100), 4)

        return StablecoinRisk(
            symbol=inp.symbol,
            current_price=round(inp.current_price, 6),
            peg_target=round(inp.peg_target, 6),
            deviation_pct=dev,
            peg_status=peg,
            collateral_score=round(col, 2),
            algo_risk_score=round(algo, 2),
            audit_score=round(aud, 2),
            size_score=round(sz, 2),
            composite_risk_score=composite,
            risk_grade=grade,
            exposure_at_risk_usd=exposure_at_risk,
            recommendation=self._recommendation(grade, peg),
        )

    def assess_batch(self, inputs: List[StablecoinInput]) -> List[StablecoinRisk]:
        return [self.assess(inp) for inp in inputs]

    def crisis_alerts(self, results: List[StablecoinRisk]) -> List[StablecoinRisk]:
        return [r for r in results if r.peg_status in ("HARD_DEPEG", "CRISIS")]

    def save_results(self, results: List[StablecoinRisk]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append({
                "timestamp": time.time(),
                "symbol": r.symbol,
                "deviation_pct": r.deviation_pct,
                "peg_status": r.peg_status,
                "composite_risk_score": r.composite_risk_score,
                "risk_grade": r.risk_grade,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

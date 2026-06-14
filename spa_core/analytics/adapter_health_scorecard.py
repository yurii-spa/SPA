"""
MP-640: AdapterHealthScorecard
Composite health score per adapter combining 5 signals.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json, time, os
from pathlib import Path

DATA_FILE = Path("data/adapter_health_scorecard.json")
MAX_ENTRIES = 100

# Weight distribution for composite score (must sum to 1.0)
WEIGHTS = {
    "apy":       0.25,
    "stability": 0.20,
    "liquidity": 0.20,
    "safety":    0.25,
    "slippage":  0.10,
}


@dataclass
class AdapterSignals:
    adapter_id: str
    apy: float                   # current APY (decimal, e.g. 0.08 = 8%)
    apy_7d_vol: float            # 7d APY stdev (from PortfolioVolatilityTracker)
    liquidity_usd: float         # available liquidity in USD
    protocol_risk_score: float   # 0-100, lower = safer
    slippage_bps: float          # expected slippage in basis points
    is_depegged: bool            # from StablecoinDepegMonitor
    days_live: int               # how long adapter has been running


@dataclass
class HealthScore:
    adapter_id: str
    timestamp: float
    # Component scores 0-100 (higher = healthier):
    apy_score: float
    stability_score: float
    liquidity_score: float
    safety_score: float
    slippage_score: float
    # Composite:
    composite_score: float
    grade: str                   # A(80-100) / B(60-79) / C(40-59) / D(<40)
    flags: List[str]             # e.g. ["DEPEGGED", "LOW_LIQUIDITY"]
    recommendation: str          # HOLD / WATCH / REDUCE / EXIT


class AdapterHealthScorecard:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Component scorers (each returns 0-100)
    # ------------------------------------------------------------------

    def _score_apy(self, apy: float) -> float:
        """Score 100 at ≥15% APY, 0 at 0%."""
        return min(100.0, max(0.0, apy / 0.15 * 100))

    def _score_stability(self, vol: float) -> float:
        """0 vol → 100, 5% vol → 0. Linear interpolation."""
        return min(100.0, max(0.0, (1 - vol / 0.05) * 100))

    def _score_liquidity(self, liquidity_usd: float) -> float:
        """$0 → 0, $10M → 100. Linear."""
        return min(100.0, max(0.0, liquidity_usd / 10_000_000 * 100))

    def _score_safety(self, protocol_risk_score: float) -> float:
        """Risk 0 → safety 100; Risk 100 → safety 0."""
        return min(100.0, max(0.0, 100.0 - protocol_risk_score))

    def _score_slippage(self, slippage_bps: float) -> float:
        """0 bps → 100, 50 bps → 0. Linear."""
        return min(100.0, max(0.0, (1 - slippage_bps / 50) * 100))

    # ------------------------------------------------------------------
    # Grade and recommendation
    # ------------------------------------------------------------------

    def _grade(self, score: float) -> str:
        if score >= 80:
            return "A"
        if score >= 60:
            return "B"
        if score >= 40:
            return "C"
        return "D"

    def _recommendation(self, grade: str, flags: List[str]) -> str:
        if "DEPEGGED" in flags or grade == "D":
            return "EXIT"
        if grade == "C" or len(flags) >= 2:
            return "REDUCE"
        if grade == "B" or len(flags) == 1:
            return "WATCH"
        return "HOLD"

    # ------------------------------------------------------------------
    # Flag detection
    # ------------------------------------------------------------------

    def _detect_flags(self, signals: AdapterSignals) -> List[str]:
        flags: List[str] = []
        if signals.is_depegged:
            flags.append("DEPEGGED")
        if signals.liquidity_usd < 500_000:
            flags.append("LOW_LIQUIDITY")
        if signals.protocol_risk_score > 60:
            flags.append("HIGH_RISK_PROTOCOL")
        if signals.apy_7d_vol > 0.02:
            flags.append("HIGH_VOLATILITY")
        if signals.slippage_bps > 30:
            flags.append("HIGH_SLIPPAGE")
        return flags

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_adapter(self, signals: AdapterSignals) -> HealthScore:
        """Compute composite health score for a single adapter."""
        apy_s  = self._score_apy(signals.apy)
        stab_s = self._score_stability(signals.apy_7d_vol)
        liq_s  = self._score_liquidity(signals.liquidity_usd)
        safe_s = self._score_safety(signals.protocol_risk_score)
        slip_s = self._score_slippage(signals.slippage_bps)

        composite = (
            apy_s  * WEIGHTS["apy"] +
            stab_s * WEIGHTS["stability"] +
            liq_s  * WEIGHTS["liquidity"] +
            safe_s * WEIGHTS["safety"] +
            slip_s * WEIGHTS["slippage"]
        )

        flags = self._detect_flags(signals)
        grade = self._grade(composite)

        return HealthScore(
            adapter_id=signals.adapter_id,
            timestamp=time.time(),
            apy_score=round(apy_s, 2),
            stability_score=round(stab_s, 2),
            liquidity_score=round(liq_s, 2),
            safety_score=round(safe_s, 2),
            slippage_score=round(slip_s, 2),
            composite_score=round(composite, 2),
            grade=grade,
            flags=flags,
            recommendation=self._recommendation(grade, flags),
        )

    def score_all(self, adapters: List[AdapterSignals]) -> List[HealthScore]:
        """Score all adapters and return sorted descending by composite score."""
        return sorted(
            [self.score_adapter(a) for a in adapters],
            key=lambda h: h.composite_score,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def get_top_adapters(self, scores: List[HealthScore], n: int = 5) -> List[HealthScore]:
        """Return top-n adapters (assumes scores already sorted descending)."""
        return scores[:n]

    def get_exit_candidates(self, scores: List[HealthScore]) -> List[HealthScore]:
        """Return all adapters with EXIT recommendation."""
        return [s for s in scores if s.recommendation == "EXIT"]

    def get_by_grade(self, scores: List[HealthScore], grade: str) -> List[HealthScore]:
        """Return adapters matching a specific grade."""
        return [s for s in scores if s.grade == grade]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_scores(self, scores: List[HealthScore]) -> None:
        """Append batch of scores to ring-buffer JSON. Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        entry = {
            "timestamp": time.time(),
            "scores": [
                {
                    "adapter_id": s.adapter_id,
                    "composite_score": s.composite_score,
                    "grade": s.grade,
                    "flags": s.flags,
                    "recommendation": s.recommendation,
                    "components": {
                        "apy":       s.apy_score,
                        "stability": s.stability_score,
                        "liquidity": s.liquidity_score,
                        "safety":    s.safety_score,
                        "slippage":  s.slippage_score,
                    },
                }
                for s in scores
            ],
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load persisted score batches from disk. Returns [] if missing/invalid."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="MP-640 AdapterHealthScorecard")
    parser.add_argument("--check", action="store_true",
                        help="Print last saved scorecard (no write)")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "adapter_health_scorecard.json"

    sc = AdapterHealthScorecard(data_file=data_file)
    history = sc.load_history()
    if not history:
        print("No scorecard history found.")
        return
    latest = history[-1]
    print(f"Latest batch — {len(latest['scores'])} adapters "
          f"(ts={latest['timestamp']:.0f}):")
    for s in latest["scores"]:
        print(f"  {s['adapter_id']:30s}  score={s['composite_score']:6.2f}  "
              f"grade={s['grade']}  rec={s['recommendation']:6s}  flags={s['flags']}")


if __name__ == "__main__":
    _main()

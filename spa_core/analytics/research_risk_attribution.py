"""
spa_core/analytics/research_risk_attribution.py

Risk attribution for research strategies RS-001 and RS-002.
Shows where risk comes from in each strategy basket.

Risk factors:
  - Market risk (crypto price exposure)
  - Liquidity risk (can exit when needed?)
  - Counterparty risk (protocol hack, rug)
  - Smart contract risk (audit status)
  - IL risk (for LP positions)
  - Source quality risk (no historical data)

Attribution:
  For each strategy slot → risk score [0-10] per factor → weighted contribution

Scope: STRICTLY READ-ONLY / advisory. Pure stdlib only.
LLM FORBIDDEN in this module.
Atomic writes via tmp + os.replace.

Date: 2026-06-19 (MP-1311, Sprint v9.27)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# ─── Constants ────────────────────────────────────────────────────────────────

RISK_FACTORS: List[str] = [
    "market_risk",          # Crypto price volatility exposure
    "liquidity_risk",       # Can exit within 24h without 5% slippage?
    "counterparty_risk",    # Protocol default, hack, rug
    "smart_contract_risk",  # Unaudited, complex, new
    "il_risk",              # Impermanent loss (LP only)
    "source_risk",          # No historical data, model-only
]

# Expected return estimates (%) for risk-vs-return comparison
RS001_EXPECTED_RETURN: float = 18.2
RS002_EXPECTED_RETURN: float = 20.0  # midpoint of net 12–28% range


# ─── RS-001 slot definitions ──────────────────────────────────────────────────
# Weights: gmx_btc=20%, gmx_eth=10%, btc_stable=35%, eth_agg=5%, gold=15%, t1=15%
RS001_WEIGHTS: Dict[str, float] = {
    "gmx_btc_exposure":    0.20,
    "gmx_eth_exposure":    0.10,
    "btc_stable_pool":     0.35,
    "eth_aggressive_pool": 0.05,
    "gold_proxy":          0.15,
    "stablecoin_t1":       0.15,
}

# RS-002 slot weights
RS002_WEIGHTS: Dict[str, float] = {
    "btc_usd_conc_liq":    0.60,
    "rwa_conc_liq":        0.10,
    "trader_losses_vault": 0.14,
    "stablecoin_deposit":  0.16,
}


# ─── SlotRiskProfile ─────────────────────────────────────────────────────────

class SlotRiskProfile:
    """Risk profile for one allocation slot.

    Stores a risk score (0–10) per factor and a capital weight.
    All computations are deterministic and offline.
    """

    def __init__(self, slot_id: str, weight: float, scores: Dict[str, float]) -> None:
        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"weight must be in [0,1], got {weight}")
        for factor in RISK_FACTORS:
            score = scores.get(factor, 0)
            if not 0 <= score <= 10:
                raise ValueError(
                    f"score for {factor!r} must be in [0,10], got {score}"
                )

        self.slot_id: str = slot_id
        self.weight: float = weight
        # Keep only known factors; fill missing with 0
        self.scores: Dict[str, float] = {
            f: float(scores.get(f, 0)) for f in RISK_FACTORS
        }

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def total_risk_score(self) -> float:
        """Simple (unweighted) average of all factor scores → [0, 10]."""
        if not self.scores:
            return 0.0
        return sum(self.scores.values()) / len(self.scores)

    def highest_risk_factor(self) -> str:
        """Return the factor name with the highest score.

        In case of a tie, the factor that appears first in RISK_FACTORS wins
        (deterministic ordering).
        """
        best_factor = RISK_FACTORS[0]
        best_score = self.scores.get(best_factor, 0.0)
        for factor in RISK_FACTORS[1:]:
            score = self.scores.get(factor, 0.0)
            if score > best_score:
                best_score = score
                best_factor = factor
        return best_factor

    def weighted_contribution(self, factor: str) -> float:
        """Slot's capital-weighted contribution to a given risk factor score."""
        return self.weight * self.scores.get(factor, 0.0)

    def to_dict(self) -> Dict:
        return {
            "slot_id": self.slot_id,
            "weight": self.weight,
            "scores": dict(self.scores),
            "total_risk_score": round(self.total_risk_score(), 4),
            "highest_risk_factor": self.highest_risk_factor(),
        }


# ─── ResearchRiskAttribution ─────────────────────────────────────────────────

class ResearchRiskAttribution:
    """Risk attribution for RS-001 and RS-002.

    All data is hard-coded (no live feeds) because these strategies are
    RESEARCH-ONLY with no point-in-time historical data.
    Strictly offline and advisory.
    """

    # ── RS-001 risk profiles ──────────────────────────────────────────────────
    RS001_PROFILES: Dict[str, Dict[str, int]] = {
        "gmx_btc_exposure": {
            "market_risk": 8, "liquidity_risk": 4, "counterparty_risk": 6,
            "smart_contract_risk": 5, "il_risk": 0, "source_risk": 9,
        },
        "gmx_eth_exposure": {
            "market_risk": 8, "liquidity_risk": 4, "counterparty_risk": 6,
            "smart_contract_risk": 5, "il_risk": 0, "source_risk": 9,
        },
        "btc_stable_pool": {
            "market_risk": 6, "liquidity_risk": 5, "counterparty_risk": 7,
            "smart_contract_risk": 6, "il_risk": 3, "source_risk": 10,
        },
        "eth_aggressive_pool": {
            "market_risk": 9, "liquidity_risk": 3, "counterparty_risk": 7,
            "smart_contract_risk": 7, "il_risk": 5, "source_risk": 10,
        },
        "gold_proxy": {
            "market_risk": 3, "liquidity_risk": 6, "counterparty_risk": 5,
            "smart_contract_risk": 4, "il_risk": 0, "source_risk": 10,
        },
        "stablecoin_t1": {
            "market_risk": 1, "liquidity_risk": 1, "counterparty_risk": 3,
            "smart_contract_risk": 2, "il_risk": 0, "source_risk": 2,
        },
    }

    # ── RS-002 risk profiles ──────────────────────────────────────────────────
    RS002_PROFILES: Dict[str, Dict[str, int]] = {
        "btc_usd_conc_liq": {
            "market_risk": 7, "liquidity_risk": 4, "counterparty_risk": 5,
            "smart_contract_risk": 5, "il_risk": 9, "source_risk": 10,
        },
        "rwa_conc_liq": {
            "market_risk": 4, "liquidity_risk": 6, "counterparty_risk": 6,
            "smart_contract_risk": 5, "il_risk": 6, "source_risk": 10,
        },
        "trader_losses_vault": {
            "market_risk": 8, "liquidity_risk": 5, "counterparty_risk": 8,
            "smart_contract_risk": 6, "il_risk": 0, "source_risk": 10,
        },
        "stablecoin_deposit": {
            "market_risk": 1, "liquidity_risk": 1, "counterparty_risk": 3,
            "smart_contract_risk": 2, "il_risk": 0, "source_risk": 2,
        },
    }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_profiles(
        profiles: Dict[str, Dict[str, int]],
        weights: Dict[str, float],
    ) -> List[SlotRiskProfile]:
        """Build SlotRiskProfile list from raw dicts."""
        result: List[SlotRiskProfile] = []
        for slot_id, scores in profiles.items():
            weight = weights.get(slot_id, 0.0)
            result.append(SlotRiskProfile(slot_id=slot_id, weight=weight, scores=scores))
        return result

    @staticmethod
    def _attribution_dict(
        profiles: List[SlotRiskProfile],
        strategy_name: str,
        expected_return: float,
    ) -> Dict:
        """Build full attribution dict for a set of slot profiles."""
        slots = [p.to_dict() for p in profiles]

        # Per-factor portfolio-level weighted score (sum of weight × factor_score)
        factor_scores: Dict[str, float] = {}
        for factor in RISK_FACTORS:
            factor_scores[factor] = round(
                sum(p.weighted_contribution(factor) for p in profiles), 4
            )

        # Portfolio-level total risk: weighted average of each slot's total_risk_score
        total_weight = sum(p.weight for p in profiles)
        if total_weight > 0:
            portfolio_total = sum(
                p.weight * p.total_risk_score() for p in profiles
            ) / total_weight
        else:
            portfolio_total = 0.0

        # Dominant factor (highest portfolio-weighted factor score)
        dominant_factor = max(factor_scores, key=lambda f: factor_scores[f])

        # Highest-risk slot
        highest_risk_slot = max(profiles, key=lambda p: p.total_risk_score())

        return {
            "strategy": strategy_name,
            "slots": slots,
            "factor_scores": factor_scores,
            "portfolio_total_risk_score": round(portfolio_total, 4),
            "dominant_factor": dominant_factor,
            "highest_risk_slot": highest_risk_slot.slot_id,
            "expected_return_pct": expected_return,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def rs001_attribution(self) -> Dict:
        """Returns full risk attribution for RS-001."""
        profiles = self._build_profiles(self.RS001_PROFILES, RS001_WEIGHTS)
        return self._attribution_dict(profiles, "RS001", RS001_EXPECTED_RETURN)

    def rs002_attribution(self) -> Dict:
        """Returns full risk attribution for RS-002."""
        profiles = self._build_profiles(self.RS002_PROFILES, RS002_WEIGHTS)
        return self._attribution_dict(profiles, "RS002", RS002_EXPECTED_RETURN)

    def portfolio_risk_score(self, strategy: str = "RS001") -> float:
        """Weighted portfolio risk [0–10] for a given strategy.

        Args:
            strategy: "RS001" or "RS002"
        Returns:
            Float in [0, 10].
        """
        s = strategy.upper()
        if s == "RS001":
            data = self.rs001_attribution()
        elif s == "RS002":
            data = self.rs002_attribution()
        else:
            raise ValueError(f"Unknown strategy {strategy!r}. Use 'RS001' or 'RS002'.")
        return data["portfolio_total_risk_score"]

    def risk_vs_return(self) -> Dict:
        """Compare risk score vs expected return for RS-001 and RS-002.

        Returns a dict with RS001 and RS002 keys, each containing:
          - risk_score: float
          - expected_return_pct: float
          - risk_return_ratio: risk / return (lower = more efficient)
          - verdict: "efficient" / "moderate" / "risk_heavy"
        """
        results: Dict[str, Dict] = {}
        for strategy in ("RS001", "RS002"):
            risk = self.portfolio_risk_score(strategy)
            ret = RS001_EXPECTED_RETURN if strategy == "RS001" else RS002_EXPECTED_RETURN
            ratio = round(risk / ret, 4) if ret > 0 else None

            if ratio is None:
                verdict = "unknown"
            elif ratio < 0.4:
                verdict = "efficient"
            elif ratio < 0.6:
                verdict = "moderate"
            else:
                verdict = "risk_heavy"

            results[strategy] = {
                "risk_score": round(risk, 4),
                "expected_return_pct": ret,
                "risk_return_ratio": ratio,
                "verdict": verdict,
            }

        return results

    def save_report(self, path: str = "data/research/risk_attribution.json") -> None:
        """Atomic save of the full attribution report.

        Uses tmp + os.replace for safety (never partial writes).
        Creates parent directories if they don't exist.
        """
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "module": "spa_core.analytics.research_risk_attribution",
            "sprint": "v9.27",
            "mp": "MP-1311",
            "rs001": self.rs001_attribution(),
            "rs002": self.rs002_attribution(),
            "risk_vs_return": self.risk_vs_return(),
        }

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(out_path))


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Research Risk Attribution — MP-1311 (Sprint v9.27)"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Compute and write report to data/research/risk_attribution.json"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Compute and print, no write (default)"
    )
    parser.add_argument(
        "--output", default="data/research/risk_attribution.json",
        help="Output path (default: data/research/risk_attribution.json)"
    )
    args = parser.parse_args()

    attr = ResearchRiskAttribution()
    rs001 = attr.rs001_attribution()
    rs002 = attr.rs002_attribution()
    rvr = attr.risk_vs_return()

    print("=== Research Risk Attribution (MP-1311, Sprint v9.27) ===")
    print(f"RS001 portfolio risk score : {rs001['portfolio_total_risk_score']:.2f}/10")
    print(f"RS002 portfolio risk score : {rs002['portfolio_total_risk_score']:.2f}/10")
    print(f"RS001 dominant factor      : {rs001['dominant_factor']}")
    print(f"RS002 dominant factor      : {rs002['dominant_factor']}")
    print(f"Risk-vs-return RS001       : {rvr['RS001']}")
    print(f"Risk-vs-return RS002       : {rvr['RS002']}")

    if args.run:
        attr.save_report(args.output)
        print(f"Report saved → {args.output}")
    else:
        print("(dry-run — use --run to save)")


if __name__ == "__main__":
    _main()

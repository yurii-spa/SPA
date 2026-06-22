"""
MP-956: DeFi Insurance Coverage Analyzer
Analyzes insurance coverage for DeFi positions.
Pure stdlib, read-only/advisory, atomic writes.
"""

import json
import os
import time

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "insurance_coverage_log.json"
)
LOG_CAP = 100


class DeFiInsuranceCoverageAnalyzer:
    """Analyzes DeFi insurance coverage for positions."""

    VALID_COVERAGE_TYPES = {
        "smart_contract", "depeg", "oracle", "liquidation", "hack"
    }
    VALID_PROVIDERS = {
        "Nexus Mutual", "InsurAce", "Uno Re", "Unslashed", "self_insured"
    }

    def analyze(self, coverages: list, config: dict) -> dict:
        """
        Analyze insurance coverage for DeFi positions.

        Args:
            coverages: list of coverage dicts with fields:
                - protocol_covered (str)
                - coverage_amount_usd (float)
                - premium_annual_pct (float)
                - coverage_type (str)
                - provider (str)
                - tvl_covered_ratio (float) coverage/position_size
                - claim_history_count (int)
                - coverage_capacity_ratio (float) 0-1
                - days_remaining (int)
                - excluded_risks (list[str])
            config: dict with optional overrides

        Returns:
            dict with analysis results
        """
        if not isinstance(coverages, list):
            raise TypeError("coverages must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        analyzed = []
        for cov in coverages:
            analyzed.append(self._analyze_coverage(cov, config))

        aggregates = self._compute_aggregates(analyzed)
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "coverages_analyzed": analyzed,
            "aggregates": aggregates,
            "total_count": len(analyzed),
        }

        self._append_log(result)
        return result

    def _analyze_coverage(self, cov: dict, config: dict) -> dict:
        """Analyze a single coverage entry."""
        protocol = cov.get("protocol_covered", "unknown")
        coverage_amount = float(cov.get("coverage_amount_usd", 0.0))
        premium_pct = float(cov.get("premium_annual_pct", 0.0))
        coverage_type = cov.get("coverage_type", "smart_contract")
        provider = cov.get("provider", "self_insured")
        tvl_ratio = float(cov.get("tvl_covered_ratio", 0.0))
        claim_count = int(cov.get("claim_history_count", 0))
        capacity_ratio = float(cov.get("coverage_capacity_ratio", 0.0))
        days_remaining = int(cov.get("days_remaining", 0))
        excluded_risks = list(cov.get("excluded_risks", []))

        # Derived metrics
        cost_per_1000 = self._cost_per_1000(coverage_amount, premium_pct)
        efficiency_score = self._efficiency_score(
            tvl_ratio, premium_pct, provider, claim_count, capacity_ratio
        )
        break_even_prob = self._break_even_probability(premium_pct)
        implied_risk = self._implied_annual_risk(premium_pct, provider)

        # Label
        label = self._coverage_label(
            tvl_ratio, premium_pct, provider, efficiency_score, coverage_amount
        )

        # Flags
        flags = self._compute_flags(
            tvl_ratio, premium_pct, capacity_ratio, days_remaining, claim_count
        )

        return {
            "protocol_covered": protocol,
            "coverage_amount_usd": coverage_amount,
            "premium_annual_pct": premium_pct,
            "coverage_type": coverage_type,
            "provider": provider,
            "tvl_covered_ratio": tvl_ratio,
            "claim_history_count": claim_count,
            "coverage_capacity_ratio": capacity_ratio,
            "days_remaining": days_remaining,
            "excluded_risks": excluded_risks,
            "derived": {
                "cost_per_1000_coverage_usd": cost_per_1000,
                "coverage_efficiency_score": efficiency_score,
                "break_even_loss_probability_pct": break_even_prob,
                "implied_annual_risk_pct": implied_risk,
            },
            "label": label,
            "flags": flags,
        }

    def _cost_per_1000(self, coverage_amount: float, premium_pct: float) -> float:
        """Cost per $1000 of coverage per year."""
        if coverage_amount <= 0:
            return 0.0
        annual_cost = coverage_amount * (premium_pct / 100.0)
        return round((annual_cost / coverage_amount) * 1000.0, 4)

    def _efficiency_score(
        self,
        tvl_ratio: float,
        premium_pct: float,
        provider: str,
        claim_count: int,
        capacity_ratio: float,
    ) -> float:
        """
        Score 0-100. Higher = better protection per cost.
        Components:
        - Coverage ratio score: tvl_ratio up to 1.0 = good
        - Premium penalty: higher premium reduces score
        - Provider quality: Nexus Mutual / InsurAce top tier
        - Claim risk: more claims = lower score
        - Capacity penalty: near-full pool = riskier
        """
        # Coverage component (0-40)
        cov_score = min(tvl_ratio, 1.5) / 1.5 * 40.0

        # Premium component (0-30): 0% premium = 30, 5% = 0, linear
        prem_score = max(0.0, (5.0 - premium_pct) / 5.0) * 30.0

        # Provider quality (0-20)
        provider_scores = {
            "Nexus Mutual": 20,
            "InsurAce": 18,
            "Unslashed": 15,
            "Uno Re": 12,
            "self_insured": 0,
        }
        prov_score = float(provider_scores.get(provider, 10))

        # Claim history penalty (0-10): 0 claims = 10, 10+ = 0
        claim_score = max(0.0, (10.0 - claim_count) / 10.0) * 10.0

        # Capacity penalty: near capacity = reduce by up to 5 pts
        cap_penalty = capacity_ratio * 5.0

        raw = cov_score + prem_score + prov_score + claim_score - cap_penalty
        return round(max(0.0, min(100.0, raw)), 2)

    def _break_even_probability(self, premium_pct: float) -> float:
        """
        Break-even annual loss probability (%).
        premium = loss_prob × 1 (full coverage) → loss_prob = premium
        """
        return round(premium_pct, 4)

    def _implied_annual_risk(self, premium_pct: float, provider: str) -> float:
        """
        Market-implied annual risk.
        Adjust for provider margin (Nexus Mutual ~30% margin, others ~20%).
        """
        margins = {
            "Nexus Mutual": 0.30,
            "InsurAce": 0.25,
            "Unslashed": 0.25,
            "Uno Re": 0.20,
            "self_insured": 0.0,
        }
        margin = margins.get(provider, 0.20)
        if premium_pct <= 0:
            return 0.0
        implied = premium_pct * (1.0 - margin)
        return round(implied, 4)

    def _coverage_label(
        self,
        tvl_ratio: float,
        premium_pct: float,
        provider: str,
        efficiency_score: float,
        coverage_amount: float,
    ) -> str:
        """
        EXCELLENT / ADEQUATE / PARTIAL / MINIMAL / UNINSURED
        """
        if coverage_amount <= 0 or provider == "self_insured":
            return "UNINSURED"
        if tvl_ratio < 0.1:
            return "MINIMAL"
        if efficiency_score >= 70 and tvl_ratio >= 0.8 and premium_pct <= 3.0:
            return "EXCELLENT"
        if efficiency_score >= 50 and tvl_ratio >= 0.5:
            return "ADEQUATE"
        if tvl_ratio >= 0.25:
            return "PARTIAL"
        return "MINIMAL"

    def _compute_flags(
        self,
        tvl_ratio: float,
        premium_pct: float,
        capacity_ratio: float,
        days_remaining: int,
        claim_count: int,
    ) -> list:
        flags = []
        if tvl_ratio > 1.5:
            flags.append("OVER_INSURED")
        if tvl_ratio < 0.5:
            flags.append("UNDER_INSURED")
        if premium_pct > 5.0:
            flags.append("PREMIUM_HIGH")
        if capacity_ratio > 0.9:
            flags.append("POOL_NEAR_CAPACITY")
        if 0 < days_remaining < 30:
            flags.append("EXPIRED_SOON")
        if claim_count > 5:
            flags.append("KNOWN_CLAIM_RISK")
        return flags

    def _compute_aggregates(self, analyzed: list) -> dict:
        if not analyzed:
            return {
                "best_value_coverage": None,
                "most_expensive": None,
                "total_coverage_usd": 0.0,
                "average_efficiency_score": 0.0,
                "uninsured_count": 0,
            }

        total_coverage = sum(a["coverage_amount_usd"] for a in analyzed)
        scores = [a["derived"]["coverage_efficiency_score"] for a in analyzed]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        uninsured = sum(1 for a in analyzed if a["label"] == "UNINSURED")

        # Best value: highest efficiency score
        best = max(analyzed, key=lambda a: a["derived"]["coverage_efficiency_score"])
        # Most expensive: highest premium_annual_pct
        most_exp = max(analyzed, key=lambda a: a["premium_annual_pct"])

        return {
            "best_value_coverage": best["protocol_covered"],
            "most_expensive": most_exp["protocol_covered"],
            "total_coverage_usd": round(total_coverage, 2),
            "average_efficiency_score": avg_score,
            "uninsured_count": uninsured,
        }

    def _append_log(self, result: dict) -> None:
        """Ring-buffer append to insurance_coverage_log.json (cap 100)."""
        log_path = LOG_PATH
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # Read existing
        existing = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        existing = data
            except (json.JSONDecodeError, OSError):
                existing = []

        # Append and cap
        entry = {
            "ts": result["timestamp"],
            "total_count": result["total_count"],
            "aggregates": result["aggregates"],
        }
        existing.append(entry)
        if len(existing) > LOG_CAP:
            existing = existing[-LOG_CAP:]

        # Atomic write
        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp_path, log_path)

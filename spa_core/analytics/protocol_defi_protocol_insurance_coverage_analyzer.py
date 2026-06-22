"""
MP-1085: Protocol DeFi Protocol Insurance Coverage Analyzer
============================================================
Read-only / advisory analytics module.
NEVER modifies trades, allocator, risk, or execution domains.
Pure Python stdlib only — no third-party imports.

Class: ProtocolDeFiProtocolInsuranceCoverageAnalyzer
Log:   data/protocol_insurance_coverage_log.json  (ring-buffer, cap=100)
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_insurance_coverage_log.json"
)
LOG_CAP = 100

VALID_COVERAGE_PROVIDERS = frozenset(
    {"nexus_mutual", "unslashed", "sherlock", "risk_harbor", "none"}
)

# Base reputation scores (0-100) per provider
_PROVIDER_BASE_SCORES: Dict[str, float] = {
    "nexus_mutual":  85.0,
    "sherlock":      80.0,
    "unslashed":     75.0,
    "risk_harbor":   70.0,
    "none":           0.0,
}

# Well-known DeFi risk categories that coverage should address
_CORE_RISKS = frozenset(
    {
        "smart_contract_bug",
        "oracle_failure",
        "governance_attack",
        "stablecoin_depeg",
        "rug_pull",
        "admin_key_compromise",
        "economic_attack",
        "bridge_exploit",
    }
)

# Scoring weight for each additional core risk covered
_RISK_SCORE_PER_CORE_RISK = 12.0  # up to 100 from 8+ risks

# Penalty per exclusion clause (capped)
_EXCLUSION_PENALTY = 5.0
_MAX_EXCLUSION_PENALTY = 30.0

# Claim-processing-day speed bonuses / penalties
_FAST_CLAIM_DAYS     = 7
_MEDIUM_CLAIM_DAYS   = 14
_SLOW_CLAIM_DAYS     = 30
_FAST_BONUS          = 10.0
_MEDIUM_BONUS        = 5.0
_SLOW_BONUS          = 0.0
_SLOW_PENALTY_RATE   = 0.5   # points per day beyond slow threshold
_MAX_SLOW_PENALTY    = 20.0

# Max single-claim coverage relative to TVL (bonus for high coverage ratio)
_MAX_CLAIM_TVL_BONUS = 10.0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiProtocolInsuranceCoverageAnalyzer:
    """
    Analyzes insurance coverage quality for a DeFi protocol position.

    Outputs
    -------
    coverage_ratio_pct    : coverage_usd / tvl_usd × 100  (0–∞, capped at display)
    premium_cost_drag_pct : premium_apy_pct  (direct yield drag)
    risk_coverage_score   : 0–100  (breadth and depth of risk coverage)
    insurance_quality_score: 0–100 (provider trustworthiness & efficiency)
    coverage_label        : FULLY_INSURED / WELL_COVERED / PARTIALLY_COVERED /
                            MINIMAL_COVERAGE / UNINSURED

    Read-only/advisory: never trades, never modifies allocator or risk.
    """

    # Coverage label thresholds (based on coverage_ratio_pct)
    _COVERAGE_LABELS: List[tuple] = [
        (80.0, "FULLY_INSURED"),
        (50.0, "WELL_COVERED"),
        (20.0, "PARTIALLY_COVERED"),
        (5.0,  "MINIMAL_COVERAGE"),
    ]
    _COVERAGE_LABEL_FLOOR = "UNINSURED"

    def __init__(
        self,
        log_file: str = DEFAULT_LOG_FILE,
        log_cap: int = LOG_CAP,
    ) -> None:
        self.log_file = os.path.abspath(log_file)
        self.log_cap = log_cap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocol: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze insurance coverage for one protocol and return scoring dict.

        Required *protocol* keys
        ------------------------
        protocol_name            str
        tvl_usd                  float > 0
        coverage_usd             float >= 0
        premium_apy_pct          float >= 0
        coverage_provider        str  ∈ {nexus_mutual, unslashed, sherlock,
                                          risk_harbor, none}
        covered_risks            list[str]
        exclusions               list[str]
        claim_processing_days    float >= 0
        historical_claims_paid_pct float  0–100
        max_single_claim_usd     float >= 0
        """
        self._validate(protocol)

        tvl          = float(protocol["tvl_usd"])
        coverage     = float(protocol["coverage_usd"])
        premium      = float(protocol["premium_apy_pct"])
        provider     = str(protocol["coverage_provider"])
        risks        = list(protocol["covered_risks"])
        exclusions   = list(protocol["exclusions"])
        claim_days   = float(protocol["claim_processing_days"])
        hist_paid    = float(protocol["historical_claims_paid_pct"])
        max_claim    = float(protocol["max_single_claim_usd"])

        # Core outputs
        coverage_ratio_pct    = (coverage / tvl * 100.0) if tvl > 0 else 0.0
        premium_cost_drag_pct = premium  # direct annual yield drag

        risk_coverage_score    = self._risk_coverage_score(
            risks, exclusions, coverage_ratio_pct
        )
        insurance_quality_score = self._insurance_quality_score(
            provider, hist_paid, claim_days, max_claim, tvl
        )
        coverage_label = self._classify_coverage(coverage_ratio_pct, provider)

        result: Dict[str, Any] = {
            "protocol_name":           protocol["protocol_name"],
            "coverage_provider":       provider,
            "tvl_usd":                 round(tvl, 2),
            "coverage_usd":            round(coverage, 2),
            "coverage_ratio_pct":      round(coverage_ratio_pct, 4),
            "premium_cost_drag_pct":   round(premium_cost_drag_pct, 4),
            "risk_coverage_score":     round(max(0.0, min(100.0, risk_coverage_score)), 4),
            "insurance_quality_score": round(max(0.0, min(100.0, insurance_quality_score)), 4),
            "coverage_label":          coverage_label,
            "covered_risks_count":     len(risks),
            "exclusions_count":        len(exclusions),
            "claim_processing_days":   claim_days,
            "historical_claims_paid_pct": round(hist_paid, 4),
            "max_single_claim_usd":    round(max_claim, 2),
            "analyzed_at":             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    @classmethod
    def _risk_coverage_score(
        cls,
        risks: List[str],
        exclusions: List[str],
        coverage_ratio_pct: float,
    ) -> float:
        """
        Score breadth and depth of risk coverage.

        Formula
        -------
        base = min(num_risks × _RISK_SCORE_PER_CORE_RISK, 90)
        bonus for covering core risk categories
        × coverage_ratio_factor  (scales with how much of TVL is insured)
        − exclusion_penalty
        """
        if not risks:
            return 0.0

        # Base score from number of risks covered
        base = min(len(risks) * _RISK_SCORE_PER_CORE_RISK, 90.0)

        # Bonus for covering recognised core risks
        core_covered = sum(1 for r in risks if r in _CORE_RISKS)
        core_bonus = min(core_covered * 2.0, 10.0)

        raw = base + core_bonus

        # Scale by coverage ratio (uncapped ratio beyond 100% = full credit)
        ratio_factor = min(coverage_ratio_pct / 100.0, 1.0)
        raw *= ratio_factor

        # Exclusion penalty
        excl_penalty = min(len(exclusions) * _EXCLUSION_PENALTY, _MAX_EXCLUSION_PENALTY)
        raw -= excl_penalty

        return max(0.0, raw)

    @classmethod
    def _insurance_quality_score(
        cls,
        provider: str,
        historical_claims_paid_pct: float,
        claim_processing_days: float,
        max_single_claim_usd: float,
        tvl_usd: float,
    ) -> float:
        """
        Score insurance quality based on provider reputation, claims history,
        and processing speed.
        """
        if provider == "none":
            return 0.0

        provider_base = _PROVIDER_BASE_SCORES.get(provider, 50.0)

        # Historical claims factor (0–1)
        claims_factor = max(0.0, min(historical_claims_paid_pct / 100.0, 1.0))
        score = provider_base * claims_factor

        # Processing speed bonus/penalty
        if claim_processing_days <= _FAST_CLAIM_DAYS:
            speed_adj = _FAST_BONUS
        elif claim_processing_days <= _MEDIUM_CLAIM_DAYS:
            speed_adj = _MEDIUM_BONUS
        elif claim_processing_days <= _SLOW_CLAIM_DAYS:
            speed_adj = _SLOW_BONUS
        else:
            excess = claim_processing_days - _SLOW_CLAIM_DAYS
            speed_adj = -min(excess * _SLOW_PENALTY_RATE, _MAX_SLOW_PENALTY)

        score += speed_adj

        # Max single claim coverage bonus (covers meaningful fraction of TVL)
        if tvl_usd > 0 and max_single_claim_usd > 0:
            claim_ratio = min(max_single_claim_usd / tvl_usd, 1.0)
            score += claim_ratio * _MAX_CLAIM_TVL_BONUS

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # Coverage label classification
    # ------------------------------------------------------------------

    @classmethod
    def _classify_coverage(
        cls, coverage_ratio_pct: float, provider: str
    ) -> str:
        """
        Assign coverage_label.
        'none' provider → UNINSURED regardless of coverage_ratio.
        """
        if provider == "none" or coverage_ratio_pct <= 0.0:
            return cls._COVERAGE_LABEL_FLOOR
        for threshold, label in cls._COVERAGE_LABELS:
            if coverage_ratio_pct >= threshold:
                return label
        return cls._COVERAGE_LABEL_FLOOR

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(p: Dict[str, Any]) -> None:
        required = [
            "protocol_name", "tvl_usd", "coverage_usd",
            "premium_apy_pct", "coverage_provider",
            "covered_risks", "exclusions",
            "claim_processing_days", "historical_claims_paid_pct",
            "max_single_claim_usd",
        ]
        for key in required:
            if key not in p:
                raise ValueError(f"Missing required key: '{key}'")

        if float(p["tvl_usd"]) <= 0.0:
            raise ValueError("'tvl_usd' must be > 0")

        if float(p["coverage_usd"]) < 0.0:
            raise ValueError("'coverage_usd' must be >= 0")

        if float(p["premium_apy_pct"]) < 0.0:
            raise ValueError("'premium_apy_pct' must be >= 0")

        if p["coverage_provider"] not in VALID_COVERAGE_PROVIDERS:
            raise ValueError(
                f"'coverage_provider' must be one of {sorted(VALID_COVERAGE_PROVIDERS)}, "
                f"got '{p['coverage_provider']}'"
            )

        if not isinstance(p["covered_risks"], list):
            raise ValueError("'covered_risks' must be a list")

        if not isinstance(p["exclusions"], list):
            raise ValueError("'exclusions' must be a list")

        if float(p["claim_processing_days"]) < 0.0:
            raise ValueError("'claim_processing_days' must be >= 0")

        hist = float(p["historical_claims_paid_pct"])
        if hist < 0.0 or hist > 100.0:
            raise ValueError(
                f"'historical_claims_paid_pct' must be 0–100, got {hist}"
            )

        if float(p["max_single_claim_usd"]) < 0.0:
            raise ValueError("'max_single_claim_usd' must be >= 0")

    # ------------------------------------------------------------------
    # Atomic ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append *entry* to JSON log; cap at self.log_cap. Atomic write."""
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        try:
            with open(self.log_file, "r") as fh:
                log: List[Dict[str, Any]] = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            log = []

        log.append(entry)
        if len(log) > self.log_cap:
            log = log[-self.log_cap:]

        atomic_save(log, str(self.log_file))

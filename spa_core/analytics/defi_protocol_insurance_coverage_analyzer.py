"""
MP-1130: DeFi Protocol Insurance Coverage Analyzer
====================================================
Read-only / advisory analytics module.
NEVER modifies trades, allocator, risk, or execution domains.
Pure Python stdlib only — no third-party imports.

Class: DeFiProtocolInsuranceCoverageAnalyzer
Log:   data/insurance_coverage_log.json  (ring-buffer, cap=100)

Purpose
-------
Analyzes how well a DeFi position is covered by insurance protocols
(Nexus Mutual, InsurAce, Sherlock, etc.). Calculates effective coverage
ratio, premium drag on yield, and whether insurance makes economic sense
given the risk profile.

Inputs
------
position_size_usd              : float   — size of the position in USD
coverage_amount_usd            : float   — insured amount (0 if uninsured)
insurance_premium_annual_pct   : float   — annual premium as % of coverage (e.g. 2.5)
protocol_risk_score            : int     — 0–100 (higher = riskier)
estimated_hack_probability_annual_pct : float — e.g. 1.0 means 1% per year
estimated_max_loss_pct         : float   — expected loss if hack occurs (e.g. 80.0)
gross_apy_pct                  : float   — gross yield before insurance costs
protocol_name                  : str

Outputs
-------
coverage_ratio                              : float — coverage / position, max 1.0
annual_premium_usd                          : float — coverage * premium_pct / 100
premium_drag_pct                            : float — premium / position * 100
expected_annual_loss_without_insurance_usd  : float
expected_annual_loss_with_insurance_usd     : float — uncovered * hack * loss + premium
insurance_net_benefit_usd                   : float — loss_without - loss_with - premium
net_apy_after_premium_pct                   : float — gross - premium_drag
insurance_label                             : str

Label logic (sequential)
------------------------
If uninsured (coverage_amount_usd == 0):
  hack_prob * max_loss / 100 > gross_apy  → INSURANCE_HIGHLY_RECOMMENDED
  else                                     → UNINSURED_ACCEPTABLE_RISK
Else (has insurance):
  net_benefit > 0 AND coverage_ratio >= 0.8  → INSURANCE_BENEFICIAL
  net_benefit > -position * 0.005            → INSURANCE_MARGINAL
  premium_drag > gross_apy * 0.3             → INSURANCE_OVERPRICED
  else                                        → UNINSURED_ACCEPTABLE_RISK
"""

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "insurance_coverage_log.json"
)
LOG_CAP = 100

_LABEL_HIGHLY_RECOMMENDED = "INSURANCE_HIGHLY_RECOMMENDED"
_LABEL_BENEFICIAL = "INSURANCE_BENEFICIAL"
_LABEL_MARGINAL = "INSURANCE_MARGINAL"
_LABEL_OVERPRICED = "INSURANCE_OVERPRICED"
_LABEL_ACCEPTABLE = "UNINSURED_ACCEPTABLE_RISK"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolInsuranceCoverageAnalyzer:
    """
    Analyzes insurance coverage economics for a DeFi position.

    Advisory/read-only — never modifies allocator, risk, or execution domains.
    Pure stdlib. Atomic ring-buffer log capped at 100 entries.
    """

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

    def analyze(
        self,
        position_size_usd: float,
        coverage_amount_usd: float,
        insurance_premium_annual_pct: float,
        protocol_risk_score: int,
        estimated_hack_probability_annual_pct: float,
        estimated_max_loss_pct: float,
        gross_apy_pct: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Run insurance coverage analysis and return a result dict.
        Appends to ring-buffer log atomically.
        """
        self._validate(
            position_size_usd=position_size_usd,
            coverage_amount_usd=coverage_amount_usd,
            insurance_premium_annual_pct=insurance_premium_annual_pct,
            protocol_risk_score=protocol_risk_score,
            estimated_hack_probability_annual_pct=estimated_hack_probability_annual_pct,
            estimated_max_loss_pct=estimated_max_loss_pct,
            gross_apy_pct=gross_apy_pct,
            protocol_name=protocol_name,
        )

        # --- Core calculations ---

        # coverage_ratio: min(coverage / position, 1.0)
        coverage_ratio: float = (
            min(coverage_amount_usd / position_size_usd, 1.0)
            if position_size_usd > 0.0
            else 0.0
        )

        # annual_premium_usd: coverage * premium_pct / 100
        annual_premium_usd: float = (
            coverage_amount_usd * insurance_premium_annual_pct / 100.0
        )

        # premium_drag_pct: annual_premium / position * 100
        premium_drag_pct: float = (
            annual_premium_usd / position_size_usd * 100.0
            if position_size_usd > 0.0
            else 0.0
        )

        # expected_annual_loss_without_insurance_usd
        expected_loss_without: float = (
            position_size_usd
            * (estimated_hack_probability_annual_pct / 100.0)
            * (estimated_max_loss_pct / 100.0)
        )

        # uncovered_portion = max(0, position - coverage)
        uncovered_portion: float = max(0.0, position_size_usd - coverage_amount_usd)

        # expected_annual_loss_with_insurance_usd
        # = uncovered_portion * hack_prob/100 * max_loss/100 + annual_premium
        expected_loss_with: float = (
            uncovered_portion
            * (estimated_hack_probability_annual_pct / 100.0)
            * (estimated_max_loss_pct / 100.0)
            + annual_premium_usd
        )

        # insurance_net_benefit_usd: loss_without - loss_with - premium
        insurance_net_benefit_usd: float = (
            expected_loss_without - expected_loss_with - annual_premium_usd
        )

        # net_apy_after_premium_pct: gross - premium_drag
        net_apy_after_premium_pct: float = gross_apy_pct - premium_drag_pct

        # --- Label classification ---
        insurance_label = self._classify(
            position_size_usd=position_size_usd,
            coverage_amount_usd=coverage_amount_usd,
            coverage_ratio=coverage_ratio,
            hack_probability_annual_pct=estimated_hack_probability_annual_pct,
            max_loss_pct=estimated_max_loss_pct,
            gross_apy_pct=gross_apy_pct,
            insurance_net_benefit_usd=insurance_net_benefit_usd,
            premium_drag_pct=premium_drag_pct,
        )

        result: Dict[str, Any] = {
            "protocol_name": protocol_name,
            "coverage_ratio": round(coverage_ratio, 6),
            "annual_premium_usd": round(annual_premium_usd, 6),
            "premium_drag_pct": round(premium_drag_pct, 6),
            "expected_annual_loss_without_insurance_usd": round(expected_loss_without, 6),
            "expected_annual_loss_with_insurance_usd": round(expected_loss_with, 6),
            "insurance_net_benefit_usd": round(insurance_net_benefit_usd, 6),
            "net_apy_after_premium_pct": round(net_apy_after_premium_pct, 6),
            "insurance_label": insurance_label,
            "protocol_risk_score": int(protocol_risk_score),
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Label classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(
        position_size_usd: float,
        coverage_amount_usd: float,
        coverage_ratio: float,
        hack_probability_annual_pct: float,
        max_loss_pct: float,
        gross_apy_pct: float,
        insurance_net_benefit_usd: float,
        premium_drag_pct: float,
    ) -> str:
        """
        Classify the insurance situation into one of five labels.

        Branch on whether the position is insured at all:
          Uninsured (coverage == 0): only two outcomes possible.
          Insured: four outcomes based on net benefit and premium drag.
        """
        uninsured = coverage_amount_usd == 0.0

        if uninsured:
            # Expected loss as % of position vs gross yield
            expected_loss_pct = hack_probability_annual_pct * max_loss_pct / 100.0
            if expected_loss_pct > gross_apy_pct:
                return _LABEL_HIGHLY_RECOMMENDED
            return _LABEL_ACCEPTABLE

        # --- Insured branch ---
        if insurance_net_benefit_usd > 0.0 and coverage_ratio >= 0.8:
            return _LABEL_BENEFICIAL

        if insurance_net_benefit_usd > -(position_size_usd * 0.005):
            return _LABEL_MARGINAL

        if premium_drag_pct > gross_apy_pct * 0.3:
            return _LABEL_OVERPRICED

        return _LABEL_ACCEPTABLE

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(
        position_size_usd: float,
        coverage_amount_usd: float,
        insurance_premium_annual_pct: float,
        protocol_risk_score: int,
        estimated_hack_probability_annual_pct: float,
        estimated_max_loss_pct: float,
        gross_apy_pct: float,
        protocol_name: str,
    ) -> None:
        if not isinstance(protocol_name, str) or not protocol_name.strip():
            raise ValueError("protocol_name must be a non-empty string")

        if float(position_size_usd) <= 0.0:
            raise ValueError("position_size_usd must be > 0")

        if float(coverage_amount_usd) < 0.0:
            raise ValueError("coverage_amount_usd must be >= 0")

        if float(insurance_premium_annual_pct) < 0.0:
            raise ValueError("insurance_premium_annual_pct must be >= 0")

        risk = int(protocol_risk_score)
        if not (0 <= risk <= 100):
            raise ValueError(
                f"protocol_risk_score must be 0–100, got {protocol_risk_score}"
            )

        if float(estimated_hack_probability_annual_pct) < 0.0:
            raise ValueError(
                "estimated_hack_probability_annual_pct must be >= 0"
            )

        max_loss = float(estimated_max_loss_pct)
        if not (0.0 <= max_loss <= 100.0):
            raise ValueError(
                f"estimated_max_loss_pct must be 0–100, got {estimated_max_loss_pct}"
            )

        if float(gross_apy_pct) < 0.0:
            raise ValueError("gross_apy_pct must be >= 0")

    # ------------------------------------------------------------------
    # Atomic ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append entry to JSON log; trim to log_cap. Atomic write via tmp+replace."""
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
            log = log[-self.log_cap :]

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=log_dir or ".", prefix=".ins_cov_log_tmp_"
        )
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                json.dump(log, fh, indent=2)
            os.replace(tmp_path, self.log_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Convenience: load log
    # ------------------------------------------------------------------

    def load_log(self) -> List[Dict[str, Any]]:
        """Return the current log contents (empty list if missing or corrupt)."""
        try:
            with open(self.log_file, "r") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    analyzer = DeFiProtocolInsuranceCoverageAnalyzer()

    scenarios = [
        {
            "desc": "High-risk uninsured",
            "kwargs": dict(
                position_size_usd=100_000.0,
                coverage_amount_usd=0.0,
                insurance_premium_annual_pct=0.0,
                protocol_risk_score=80,
                estimated_hack_probability_annual_pct=10.0,
                estimated_max_loss_pct=90.0,
                gross_apy_pct=5.0,
                protocol_name="HighRiskProtocol",
            ),
        },
        {
            "desc": "Well-covered beneficial insurance",
            "kwargs": dict(
                position_size_usd=100_000.0,
                coverage_amount_usd=95_000.0,
                insurance_premium_annual_pct=1.0,
                protocol_risk_score=30,
                estimated_hack_probability_annual_pct=5.0,
                estimated_max_loss_pct=80.0,
                gross_apy_pct=8.0,
                protocol_name="AaveV3",
            ),
        },
    ]

    for s in scenarios:
        result = analyzer.analyze(**s["kwargs"])
        print(f"\n=== {s['desc']} ===")
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    _demo()

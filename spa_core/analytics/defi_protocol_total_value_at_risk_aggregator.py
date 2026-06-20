"""
MP-1104: DeFiProtocolTotalValueAtRiskAggregator

Advisory/read-only module. Aggregates Value-at-Risk (VaR) across multiple
DeFi positions using the parametric (variance-covariance) approach.
Portfolio-level risk considers correlations between assets via a uniform
average-correlation matrix.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Default data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "total_value_at_risk_log.json"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RING_BUFFER_CAP = 100

# Correlation assumptions -> numeric values
CORR_INDEPENDENT = 0.0
CORR_MODERATE = 0.3
CORR_HIGH = 0.7

CORRELATION_MAP = {
    "independent": CORR_INDEPENDENT,
    "moderate": CORR_MODERATE,
    "high": CORR_HIGH,
}

# Z-scores for supported confidence levels
Z_SCORE_95 = 1.645
Z_SCORE_99 = 2.326

# Risk label constants
LABEL_LOW_RISK = "LOW_RISK"
LABEL_MODERATE_RISK = "MODERATE_RISK"
LABEL_ELEVATED_RISK = "ELEVATED_RISK"
LABEL_HIGH_RISK = "HIGH_RISK"
LABEL_EXTREME_RISK = "EXTREME_RISK"


# ---------------------------------------------------------------------------
# Pure math helpers (module-level, fully testable)
# ---------------------------------------------------------------------------

def get_z_score(confidence_level_pct: float) -> float:
    """Return z-score for a given confidence level percentage (95 or 99)."""
    if confidence_level_pct >= 99.0:
        return Z_SCORE_99
    return Z_SCORE_95


def get_correlation(correlation_assumption: str) -> float:
    """Return numeric correlation coefficient from string assumption."""
    return CORRELATION_MAP.get(str(correlation_assumption).lower(), CORR_MODERATE)


def compute_individual_var(
    value_usd: float,
    daily_volatility_pct: float,
    z_score: float,
    holding_days: int,
) -> float:
    """
    Parametric VaR for a single position.

    Formula: VaR = value * (volatility/100) * z_score * sqrt(days)
    """
    return value_usd * (daily_volatility_pct / 100.0) * z_score * math.sqrt(max(1, holding_days))


def compute_portfolio_var(individual_vars: List[float], corr: float) -> float:
    """
    Portfolio VaR using a uniform average-correlation matrix.

    Formula: port_var = sqrt(sum_i(var_i^2) + 2*corr * sum_{i<j}(var_i * var_j))

    With corr=0 (independent) this reduces to sqrt(sum(var_i^2)).
    With corr=1 it equals sum(var_i).
    """
    if not individual_vars:
        return 0.0
    n = len(individual_vars)
    sum_sq = sum(v * v for v in individual_vars)
    sum_cross = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            sum_cross += individual_vars[i] * individual_vars[j]
    variance = sum_sq + 2.0 * corr * sum_cross
    return math.sqrt(max(0.0, variance))


def get_risk_label(var_pct_of_portfolio: float) -> str:
    """
    Classify risk label by var_pct_of_portfolio.

    < 1%   → LOW_RISK
    1-3%   → MODERATE_RISK
    3-5%   → ELEVATED_RISK
    5-10%  → HIGH_RISK
    > 10%  → EXTREME_RISK
    """
    if var_pct_of_portfolio < 1.0:
        return LABEL_LOW_RISK
    elif var_pct_of_portfolio < 3.0:
        return LABEL_MODERATE_RISK
    elif var_pct_of_portfolio < 5.0:
        return LABEL_ELEVATED_RISK
    elif var_pct_of_portfolio < 10.0:
        return LABEL_HIGH_RISK
    return LABEL_EXTREME_RISK


def compute_risk_score(var_pct_of_portfolio: float) -> int:
    """
    Map var_pct_of_portfolio to a 0-100 risk score (higher = riskier).

    Piecewise linear interpolation across label bands:
      0-1%   → score 0-20   (LOW_RISK)
      1-3%   → score 20-40  (MODERATE_RISK)
      3-5%   → score 40-60  (ELEVATED_RISK)
      5-10%  → score 60-80  (HIGH_RISK)
      10%+   → score 80-100 (EXTREME_RISK, clamped)
    """
    v = max(0.0, var_pct_of_portfolio)
    if v < 1.0:
        raw = v / 1.0 * 20.0
    elif v < 3.0:
        raw = 20.0 + (v - 1.0) / 2.0 * 20.0
    elif v < 5.0:
        raw = 40.0 + (v - 3.0) / 2.0 * 20.0
    elif v < 10.0:
        raw = 60.0 + (v - 5.0) / 5.0 * 20.0
    else:
        raw = 80.0 + (v - 10.0) / 10.0 * 20.0
    return max(0, min(100, int(raw)))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolTotalValueAtRiskAggregator:
    """
    Aggregates Value-at-Risk across multiple DeFi positions using the
    parametric variance-covariance approach with a uniform average-correlation
    matrix. Advisory / read-only. Pure stdlib only.
    """

    def __init__(self, data_file: Optional[str] = None) -> None:
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate(
        self,
        positions: List[dict],
        confidence_level_pct: float = 95.0,
        holding_days: int = 1,
        correlation_assumption: str = "moderate",
        protocol_name: str = "portfolio",
    ) -> dict:
        """
        Compute portfolio VaR across all positions.

        Parameters
        ----------
        positions : list[dict]
            Each dict must contain:
              - asset (str)
              - value_usd (float)
              - daily_volatility_pct (float)
        confidence_level_pct : float
            Confidence level: 95.0 or 99.0.
        holding_days : int
            VaR horizon in days (minimum 1).
        correlation_assumption : str
            "independent" (0.0) / "moderate" (0.3) / "high" (0.7).
        protocol_name : str
            Label used for logging / identification.

        Returns
        -------
        dict with keys:
          protocol_name, total_portfolio_usd, individual_var_usd,
          portfolio_var_usd, diversification_benefit_usd,
          var_pct_of_portfolio, largest_risk_contributor,
          risk_level_score, risk_label, confidence_level_pct,
          holding_days, correlation_assumption, correlation_value,
          z_score, position_count, run_ts
        """
        z = get_z_score(confidence_level_pct)
        corr = get_correlation(correlation_assumption)
        days = max(1, int(holding_days))

        total_usd = sum(float(p.get("value_usd", 0.0)) for p in positions)

        individual_vars: List[float] = []
        asset_var_pairs: List[tuple] = []

        for p in positions:
            value = float(p.get("value_usd", 0.0))
            vol = float(p.get("daily_volatility_pct", 0.0))
            asset = str(p.get("asset", "UNKNOWN"))
            ivar = compute_individual_var(value, vol, z, days)
            individual_vars.append(ivar)
            asset_var_pairs.append((asset, ivar))

        individual_var_usd = sum(individual_vars)
        portfolio_var_usd = compute_portfolio_var(individual_vars, corr)
        diversification_benefit_usd = individual_var_usd - portfolio_var_usd

        var_pct = (
            portfolio_var_usd / total_usd * 100.0
            if total_usd > 0.0
            else 0.0
        )

        largest_risk_contributor = (
            max(asset_var_pairs, key=lambda x: x[1])[0]
            if asset_var_pairs
            else ""
        )

        result = {
            "protocol_name": protocol_name,
            "total_portfolio_usd": round(total_usd, 6),
            "individual_var_usd": round(individual_var_usd, 6),
            "portfolio_var_usd": round(portfolio_var_usd, 6),
            "diversification_benefit_usd": round(diversification_benefit_usd, 6),
            "var_pct_of_portfolio": round(var_pct, 6),
            "largest_risk_contributor": largest_risk_contributor,
            "risk_level_score": compute_risk_score(var_pct),
            "risk_label": get_risk_label(var_pct),
            "confidence_level_pct": confidence_level_pct,
            "holding_days": days,
            "correlation_assumption": correlation_assumption,
            "correlation_value": corr,
            "z_score": z,
            "position_count": len(positions),
            "run_ts": datetime.now(timezone.utc).isoformat(),
        }
        return result

    def save_result(self, result: dict) -> None:
        """
        Atomically append result to the ring-buffer JSON log (cap RING_BUFFER_CAP).
        Uses tmp + os.replace for atomicity.
        """
        data_dir = os.path.dirname(self._data_file)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)

        existing: list = []
        if os.path.exists(self._data_file):
            try:
                with open(self._data_file, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(result)
        existing = existing[-RING_BUFFER_CAP:]

        atomic_save(existing, str(self))

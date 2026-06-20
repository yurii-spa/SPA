"""
MP-1120: DeFiProtocolCollateralEfficiencyScorer
================================================
Advisory-only, read-only analytics module.
Scores how efficiently a DeFi protocol uses collateral to generate yield.
High collateral efficiency = high yield per unit of locked collateral.
Relevant for CDP-style protocols (MakerDAO, Liquity, Aave E-Mode).

Output file: data/collateral_efficiency_log.json (ring-buffer, cap 100)
Pure Python stdlib only. Atomic writes (tmp + os.replace).
Python 3.9 compatible.
"""

import json
import math
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Data file (relative to repo root: two levels up from spa_core/analytics/)
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "collateral_efficiency_log.json",
)

RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Label constants
# ---------------------------------------------------------------------------
LABEL_HIGHLY_EFFICIENT = "HIGHLY_EFFICIENT"
LABEL_EFFICIENT = "EFFICIENT"
LABEL_MODERATE = "MODERATE"
LABEL_UNDERUTILIZED = "UNDERUTILIZED"
LABEL_IDLE_COLLATERAL = "IDLE_COLLATERAL"

# Thresholds for risk_adjusted_efficiency (%)
THRESHOLD_HIGHLY_EFFICIENT = 15.0  # >= 15%
THRESHOLD_EFFICIENT = 10.0         # 10–15%
THRESHOLD_MODERATE = 5.0           # 5–10%
THRESHOLD_UNDERUTILIZED = 1.0      # 1–5%
# < 1% → IDLE_COLLATERAL

# ---------------------------------------------------------------------------
# Efficiency score anchor points: (rae_pct, score)
# Piecewise linear between anchors; clamped 0-100.
# ---------------------------------------------------------------------------
_SCORE_ANCHORS = [
    (0.0, 0),
    (1.0, 20),
    (5.0, 40),
    (10.0, 60),
    (15.0, 80),
    (20.0, 100),
]


# ---------------------------------------------------------------------------
# Pure math helpers — fully testable at module level
# ---------------------------------------------------------------------------

def compute_collateral_utilization_pct(
    debt_value_usd: float, collateral_value_usd: float
) -> float:
    """debt / collateral * 100.  Returns 0.0 if collateral <= 0."""
    if collateral_value_usd <= 0.0:
        return 0.0
    return debt_value_usd / collateral_value_usd * 100.0


def compute_available_borrow_headroom_pct(
    liquidation_threshold_pct: float, current_ltv_pct: float
) -> float:
    """liquidation_threshold − current_ltv.  May be negative (over-leveraged)."""
    return liquidation_threshold_pct - current_ltv_pct


def compute_capital_efficiency_ratio(
    annual_yield_earned_usd: float, collateral_value_usd: float
) -> float:
    """annual_yield / collateral * 100.  Returns 0.0 if collateral <= 0."""
    if collateral_value_usd <= 0.0:
        return 0.0
    return annual_yield_earned_usd / collateral_value_usd * 100.0


def compute_risk_adjusted_efficiency(
    capital_efficiency_ratio: float, collateral_volatility_30d_pct: float
) -> float:
    """
    efficiency / (1 + volatility / 100).
    Negative volatility is clamped to 0 (treated as zero-vol asset).
    """
    vol = max(0.0, collateral_volatility_30d_pct)
    denominator = 1.0 + vol / 100.0
    return capital_efficiency_ratio / denominator


def compute_efficiency_score(risk_adjusted_efficiency: float) -> int:
    """
    Map risk_adjusted_efficiency (%) → integer score 0-100.

    Piecewise linear between anchor points:
      rae   0% → score   0
      rae   1% → score  20
      rae   5% → score  40
      rae  10% → score  60
      rae  15% → score  80
      rae  20% → score 100

    Values below 0 → 0; above 20% → 100.
    """
    rae = risk_adjusted_efficiency
    if rae <= 0.0:
        return 0
    if rae >= 20.0:
        return 100
    for i in range(1, len(_SCORE_ANCHORS)):
        x0, s0 = _SCORE_ANCHORS[i - 1]
        x1, s1 = _SCORE_ANCHORS[i]
        if x0 <= rae < x1:
            frac = (rae - x0) / (x1 - x0)
            raw = s0 + frac * (s1 - s0)
            return max(0, min(100, int(raw)))
    return 100  # exactly 20.0 caught above; unreachable


def get_efficiency_label(risk_adjusted_efficiency: float) -> str:
    """Return efficiency label based on risk_adjusted_efficiency (%)."""
    if risk_adjusted_efficiency >= THRESHOLD_HIGHLY_EFFICIENT:
        return LABEL_HIGHLY_EFFICIENT
    if risk_adjusted_efficiency >= THRESHOLD_EFFICIENT:
        return LABEL_EFFICIENT
    if risk_adjusted_efficiency >= THRESHOLD_MODERATE:
        return LABEL_MODERATE
    if risk_adjusted_efficiency >= THRESHOLD_UNDERUTILIZED:
        return LABEL_UNDERUTILIZED
    return LABEL_IDLE_COLLATERAL


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolCollateralEfficiencyScorer:
    """
    Scores how efficiently a DeFi protocol uses collateral to generate yield.
    Advisory / read-only.  Pure stdlib only.  Python 3.9 compatible.
    """

    def __init__(self, data_file: Optional[str] = None) -> None:
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        collateral_value_usd: float,
        debt_value_usd: float,
        annual_yield_earned_usd: float,
        liquidation_threshold_pct: float,
        current_ltv_pct: float,
        collateral_volatility_30d_pct: float,
        protocol_name: str = "unknown",
    ) -> dict:
        """
        Score collateral efficiency for a single protocol position.

        Parameters
        ----------
        collateral_value_usd : float
            Total collateral posted (USD).
        debt_value_usd : float
            Total loans taken against collateral (USD).
        annual_yield_earned_usd : float
            Revenue generated on deployed capital over 1 year (USD).
        liquidation_threshold_pct : float
            Max LTV % before liquidation (e.g. 80.0 for 80 %).
        current_ltv_pct : float
            Current loan-to-value ratio (%).
        collateral_volatility_30d_pct : float
            30-day realised volatility of the collateral asset (%).
        protocol_name : str
            Label used for identification/logging.

        Returns
        -------
        dict with keys:
            protocol_name, collateral_value_usd, debt_value_usd,
            annual_yield_earned_usd, liquidation_threshold_pct,
            current_ltv_pct, collateral_volatility_30d_pct,
            collateral_utilization_pct, available_borrow_headroom_pct,
            capital_efficiency_ratio, risk_adjusted_efficiency,
            efficiency_score, efficiency_label, run_ts
        """
        collateral_value_usd = float(collateral_value_usd)
        debt_value_usd = float(debt_value_usd)
        annual_yield_earned_usd = float(annual_yield_earned_usd)
        liquidation_threshold_pct = float(liquidation_threshold_pct)
        current_ltv_pct = float(current_ltv_pct)
        collateral_volatility_30d_pct = float(collateral_volatility_30d_pct)

        utilization = compute_collateral_utilization_pct(
            debt_value_usd, collateral_value_usd
        )
        headroom = compute_available_borrow_headroom_pct(
            liquidation_threshold_pct, current_ltv_pct
        )
        cer = compute_capital_efficiency_ratio(
            annual_yield_earned_usd, collateral_value_usd
        )
        rae = compute_risk_adjusted_efficiency(cer, collateral_volatility_30d_pct)
        score_val = compute_efficiency_score(rae)
        label = get_efficiency_label(rae)

        return {
            "protocol_name": protocol_name,
            "collateral_value_usd": collateral_value_usd,
            "debt_value_usd": debt_value_usd,
            "annual_yield_earned_usd": annual_yield_earned_usd,
            "liquidation_threshold_pct": liquidation_threshold_pct,
            "current_ltv_pct": current_ltv_pct,
            "collateral_volatility_30d_pct": collateral_volatility_30d_pct,
            "collateral_utilization_pct": round(utilization, 6),
            "available_borrow_headroom_pct": round(headroom, 6),
            "capital_efficiency_ratio": round(cer, 6),
            "risk_adjusted_efficiency": round(rae, 6),
            "efficiency_score": score_val,
            "efficiency_label": label,
            "run_ts": time.time(),
        }

    def save_result(self, result: dict) -> None:
        """
        Atomically append *result* to the ring-buffer JSON log
        (capped at RING_BUFFER_CAP entries).  Uses tmp + os.replace.
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

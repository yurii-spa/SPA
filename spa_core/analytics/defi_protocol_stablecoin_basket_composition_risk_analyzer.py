"""
MP-1078: DeFiProtocolStablecoinBasketCompositionRiskAnalyzer
============================================================
Advisory-only analytics module.

Assesses the composition risk of a stablecoin basket used in a DeFi protocol —
evaluating how the mix of backing types (fiat, crypto, algorithmic, RWA, hybrid),
concentration (HHI-based), depeg history, peg deviation, and redemption mechanism
contributes to overall basket risk.

Per basket it computes:
  basket_risk_score     0–100  (higher = riskier)
  concentration_score   0–100  (HHI-based; higher = more concentrated)
  algo_exposure_pct     0–100  (total weight of algorithmic stablecoins)
  avg_peg_deviation_pct float  (weight-averaged absolute peg deviation)
  basket_label          FORTRESS_BASKET / CONSERVATIVE / BALANCED /
                        RISKY_COMPOSITION / AVOID_BASKET

Classification rules:
  - algo_exposure_pct >= 30  → forced AVOID_BASKET regardless of risk score
  - basket_risk_score < 20   → FORTRESS_BASKET
  - basket_risk_score < 40   → CONSERVATIVE
  - basket_risk_score < 60   → BALANCED
  - basket_risk_score < 80   → RISKY_COMPOSITION
  - basket_risk_score >= 80  → AVOID_BASKET

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/stablecoin_basket_composition_log.json
Atomic writes: tmp + os.replace.
"""

import json
import math
import os
import tempfile
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "stablecoin_basket_composition_log.json",
)
LOG_MAX_ENTRIES = 100

VALID_BACKING_TYPES = frozenset({
    "fiat_backed",
    "crypto_overcollateral",
    "algorithmic",
    "rwa_backed",
    "hybrid",
})

VALID_REDEMPTION_MECHANISMS = frozenset({"direct", "amm_only", "delayed"})

# Per-component base risk score by backing type (before depeg/deviation adjustments)
BACKING_TYPE_RISK = {
    "fiat_backed":           5.0,
    "rwa_backed":           10.0,
    "crypto_overcollateral": 15.0,
    "hybrid":               22.0,
    "algorithmic":          45.0,
}

# Additional basket-level risk added by redemption mechanism
REDEMPTION_RISK = {
    "direct":   0.0,
    "delayed": 10.0,
    "amm_only": 20.0,
}

# Insurance discount subtracted from basket_risk_score
INSURANCE_DISCOUNT = 8.0

# Concentration HHI penalty multiplier
CONCENTRATION_PENALTY_WEIGHT = 0.12

# Force AVOID_BASKET when algorithmic exposure exceeds this percent
ALGO_AVOID_THRESHOLD = 30.0

# Tolerance for weight sum validation (percent)
WEIGHT_SUM_TOLERANCE = 0.5

# TVL bonus capped at this value (large TVL = more liquidity = lower risk)
TVL_BONUS_CAP = 8.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_component(c: dict, idx: int) -> None:
    """Validate a single component dict."""
    if not isinstance(c, dict):
        raise ValueError(f"Component {idx} must be a dict")
    required = {
        "symbol", "weight_pct", "backing_type",
        "depeg_history_count", "current_peg_deviation_pct",
    }
    missing = required - set(c.keys())
    if missing:
        raise ValueError(
            f"Component {idx} ('{c.get('symbol', '?')}') missing fields: {missing}"
        )
    w = c["weight_pct"]
    if isinstance(w, bool) or not isinstance(w, (int, float)) or w < 0:
        raise ValueError(
            f"Component {idx}: 'weight_pct' must be a non-negative number, got {type(w).__name__}"
        )
    bt = c["backing_type"]
    if bt not in VALID_BACKING_TYPES:
        raise ValueError(
            f"Component {idx}: 'backing_type' must be one of {sorted(VALID_BACKING_TYPES)}, got '{bt}'"
        )
    dc = c["depeg_history_count"]
    if isinstance(dc, bool) or not isinstance(dc, int) or dc < 0:
        raise ValueError(
            f"Component {idx}: 'depeg_history_count' must be a non-negative int, got {type(dc).__name__}"
        )
    dev = c["current_peg_deviation_pct"]
    if isinstance(dev, bool) or not isinstance(dev, (int, float)):
        raise ValueError(
            f"Component {idx}: 'current_peg_deviation_pct' must be a number, got {type(dev).__name__}"
        )


def _validate_basket(basket: dict) -> None:
    """Validate the full basket input dict."""
    if not isinstance(basket, dict):
        raise ValueError("basket must be a dict")
    required = {
        "basket_name", "components", "total_basket_tvl_usd",
        "redemption_mechanism", "has_insurance",
    }
    missing = required - set(basket.keys())
    if missing:
        raise ValueError(f"Missing required basket fields: {sorted(missing)}")

    if not isinstance(basket["basket_name"], str) or not basket["basket_name"]:
        raise ValueError("'basket_name' must be a non-empty string")

    components = basket["components"]
    if not isinstance(components, list) or len(components) == 0:
        raise ValueError("'components' must be a non-empty list")

    for idx, c in enumerate(components):
        _validate_component(c, idx)

    total_weight = sum(float(c["weight_pct"]) for c in components)
    if abs(total_weight - 100.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"Component weights must sum to ~100% (tolerance ±{WEIGHT_SUM_TOLERANCE}%), got {total_weight:.4f}%"
        )

    tvl = basket["total_basket_tvl_usd"]
    if isinstance(tvl, bool) or not isinstance(tvl, (int, float)) or tvl < 0:
        raise ValueError("'total_basket_tvl_usd' must be a non-negative number")

    rm = basket["redemption_mechanism"]
    if rm not in VALID_REDEMPTION_MECHANISMS:
        raise ValueError(
            f"'redemption_mechanism' must be one of {sorted(VALID_REDEMPTION_MECHANISMS)}, got '{rm}'"
        )

    if not isinstance(basket["has_insurance"], bool):
        raise ValueError("'has_insurance' must be a bool (True/False)")


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _concentration_score(components: list) -> float:
    """
    HHI-based concentration score (0–100).
    0 = perfectly diversified (all equal weight), 100 = single asset.

    HHI = Σ (weight_i / 100)²
    Normalized: (HHI − 1/N) / (1 − 1/N) × 100  for N ≥ 2
    Single component always returns 100.
    """
    n = len(components)
    if n == 1:
        return 100.0
    hhi = sum((float(c["weight_pct"]) / 100.0) ** 2 for c in components)
    hhi_min = 1.0 / n        # perfectly spread
    hhi_max = 1.0            # single asset monopoly
    if hhi_max <= hhi_min:
        return 0.0
    score = (hhi - hhi_min) / (hhi_max - hhi_min) * 100.0
    return round(max(0.0, min(score, 100.0)), 2)


def _algo_exposure_pct(components: list) -> float:
    """Sum of weights for algorithmic-backed stablecoins."""
    return round(
        sum(float(c["weight_pct"]) for c in components if c["backing_type"] == "algorithmic"),
        2,
    )


def _avg_peg_deviation_pct(components: list) -> float:
    """
    Weight-averaged absolute peg deviation across components.
    Negative deviations (below peg) treated same as positive (above peg).
    """
    total_weight = sum(float(c["weight_pct"]) for c in components)
    if total_weight == 0:
        return 0.0
    weighted_dev = sum(
        abs(float(c["current_peg_deviation_pct"])) * float(c["weight_pct"])
        for c in components
    )
    return round(weighted_dev / total_weight, 4)


def _component_risk_score(c: dict) -> float:
    """
    Per-component risk score (0–100).

    Components:
      backing_type_risk  — base risk per type (5–45)
      depeg_factor       — 5 points per historical depeg event, capped at 30
      deviation_factor   — 10 points per 1% current peg deviation, capped at 25
    """
    bt_risk = BACKING_TYPE_RISK.get(c["backing_type"], 20.0)
    depeg_factor = min(float(c["depeg_history_count"]) * 5.0, 30.0)
    deviation_factor = min(abs(float(c["current_peg_deviation_pct"])) * 10.0, 25.0)
    return min(bt_risk + depeg_factor + deviation_factor, 100.0)


def _basket_risk_score(
    components: list,
    redemption_mechanism: str,
    has_insurance: bool,
    conc_score: float,
    total_basket_tvl_usd: float,
) -> float:
    """
    Composite basket risk score (0–100). Higher = riskier.

    = weighted_component_risk
      + redemption_mechanism_risk     (direct=0, delayed=10, amm_only=20)
      − insurance_discount            (has_insurance: −8)
      + concentration_penalty         (conc_score × 0.12)
      − tvl_safety_bonus              (log10 scale, capped at 8)

    Clamped to [0, 100].
    """
    weighted_risk = sum(
        _component_risk_score(c) * float(c["weight_pct"]) / 100.0
        for c in components
    )
    redemption_risk = REDEMPTION_RISK.get(redemption_mechanism, 10.0)
    insurance_adj = -INSURANCE_DISCOUNT if has_insurance else 0.0
    conc_penalty = conc_score * CONCENTRATION_PENALTY_WEIGHT

    if total_basket_tvl_usd > 0:
        tvl_bonus = min(math.log10(total_basket_tvl_usd + 1.0) * 1.5, TVL_BONUS_CAP)
    else:
        tvl_bonus = 0.0

    raw = weighted_risk + redemption_risk + insurance_adj + conc_penalty - tvl_bonus
    return round(max(0.0, min(raw, 100.0)), 2)


def _basket_label(risk_score: float, algo_exposure: float) -> str:
    """
    Classify the basket.
    Forces AVOID_BASKET when algo_exposure_pct >= ALGO_AVOID_THRESHOLD (30%).
    """
    if algo_exposure >= ALGO_AVOID_THRESHOLD:
        return "AVOID_BASKET"
    if risk_score < 20.0:
        return "FORTRESS_BASKET"
    if risk_score < 40.0:
        return "CONSERVATIVE"
    if risk_score < 60.0:
        return "BALANCED"
    if risk_score < 80.0:
        return "RISKY_COMPOSITION"
    return "AVOID_BASKET"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolStablecoinBasketCompositionRiskAnalyzer:
    """
    Analyzes stablecoin basket composition risk for DeFi protocols.
    Advisory / read-only. No execution side-effects.
    """

    def analyze(self, basket: dict, config: Optional[dict] = None) -> dict:
        """
        Parameters
        ----------
        basket : dict
            Required keys:
                basket_name              str  (non-empty)
                components               list[dict]  — each dict must have:
                    symbol               str
                    weight_pct           float  (>=0; all must sum to ~100%)
                    backing_type         str    one of: fiat_backed |
                                                crypto_overcollateral | algorithmic |
                                                rwa_backed | hybrid
                    depeg_history_count  int    (>=0)
                    current_peg_deviation_pct  float  (negative = below peg)
                total_basket_tvl_usd     float  (>=0)
                redemption_mechanism     str    one of: direct | amm_only | delayed
                has_insurance            bool

        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict with keys:
            basket_name              str
            basket_risk_score        float  0–100  (higher = riskier)
            concentration_score      float  0–100  (HHI-based)
            algo_exposure_pct        float  0–100
            avg_peg_deviation_pct    float  (weight-avg of |deviations|)
            basket_label             str    FORTRESS_BASKET | CONSERVATIVE |
                                           BALANCED | RISKY_COMPOSITION | AVOID_BASKET
            component_count          int
            analyzed_at              str    ISO-8601 UTC timestamp
        """
        if config is None:
            config = {}

        _validate_basket(basket)
        components = basket["components"]

        conc_score = _concentration_score(components)
        algo_exp = _algo_exposure_pct(components)
        avg_dev = _avg_peg_deviation_pct(components)
        risk_score = _basket_risk_score(
            components,
            basket["redemption_mechanism"],
            bool(basket["has_insurance"]),
            conc_score,
            float(basket["total_basket_tvl_usd"]),
        )
        label = _basket_label(risk_score, algo_exp)

        output = {
            "basket_name": basket["basket_name"],
            "basket_risk_score": risk_score,
            "concentration_score": conc_score,
            "algo_exposure_pct": algo_exp,
            "avg_peg_deviation_pct": avg_dev,
            "basket_label": label,
            "component_count": len(components),
            "analyzed_at": _iso_now(),
        }

        _append_log(output)
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _init_log(path: str) -> list:
    """Load existing ring-buffer log or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append a snapshot to the ring-buffer log (capped at LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    snapshot = {
        "ts": result.get("analyzed_at", _iso_now()),
        "basket_name": result.get("basket_name"),
        "basket_risk_score": result.get("basket_risk_score"),
        "basket_label": result.get("basket_label"),
        "algo_exposure_pct": result.get("algo_exposure_pct"),
        "concentration_score": result.get("concentration_score"),
        "component_count": result.get("component_count"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(basket: dict, config: Optional[dict] = None) -> dict:
    """Module-level shorthand — delegates to DeFiProtocolStablecoinBasketCompositionRiskAnalyzer."""
    return DeFiProtocolStablecoinBasketCompositionRiskAnalyzer().analyze(basket, config)

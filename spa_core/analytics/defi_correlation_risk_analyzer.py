"""
MP-835 DeFiCorrelationRiskAnalyzer
Analyzes pairwise Pearson correlation between DeFi portfolio positions to detect
concentration risk when multiple positions move together during market stress.
Advisory/read-only. Pure stdlib. Atomic writes only.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Pearson correlation (pure stdlib, no external deps)
# ---------------------------------------------------------------------------

def _pearson(a: list, b: list) -> float:
    """Compute Pearson correlation between two return series."""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a = a[:n]
    b = b[:n]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    den_a = (sum((x - mean_a) ** 2 for x in a)) ** 0.5
    den_b = (sum((x - mean_b) ** 2 for x in b)) ** 0.5
    if den_a == 0 or den_b == 0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_a * den_b)))


# ---------------------------------------------------------------------------
# Correlation risk classification
# ---------------------------------------------------------------------------

def _position_risk_label(avg_corr: float) -> str:
    """Classify correlation risk for a single position."""
    if avg_corr >= 0.8:
        return "CRITICAL"
    if avg_corr >= 0.6:
        return "HIGH"
    if avg_corr >= 0.4:
        return "MEDIUM"
    return "LOW"


def _portfolio_risk_label(avg_pairwise: float) -> str:
    """Classify overall portfolio diversification label."""
    if avg_pairwise < 0.3:
        return "WELL_DIVERSIFIED"
    if avg_pairwise < 0.5:
        return "MODERATE"
    if avg_pairwise < 0.7:
        return "CONCENTRATED"
    return "HIGHLY_CORRELATED"


def _diversification_score(avg_pairwise: float) -> int:
    """Convert avg pairwise correlation to 0-100 diversification score."""
    return max(0, min(100, int(100 - avg_pairwise * 100)))


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(positions: list, config: Optional[dict] = None) -> dict:
    """
    Analyze pairwise Pearson correlation across portfolio positions.

    Parameters
    ----------
    positions : list[dict]
        Each item:
            protocol            str
            allocation_pct      float   portfolio weight
            underlying_asset    str     e.g. "ETH", "USDC"
            category            str     e.g. "lending", "staking"
            returns_30d         list[float]   daily returns (len >= min_returns)

    config : dict, optional
        high_correlation_threshold : float  default 0.7
        min_returns                : int    default 2

    Returns
    -------
    dict  — full result structure (see module docstring).
    """
    cfg = config or {}
    high_threshold = float(cfg.get("high_correlation_threshold", 0.7))
    min_returns = int(cfg.get("min_returns", 2))

    # ---- separate valid vs skipped positions --------------------------------
    valid = []
    skipped = []
    for p in positions:
        returns = p.get("returns_30d", [])
        if not isinstance(returns, list) or len(returns) < min_returns:
            skipped.append(p.get("protocol", "unknown"))
        else:
            valid.append(p)

    # ---- build full N×N correlation matrix for valid positions --------------
    n = len(valid)
    # corr_matrix[i][j] = Pearson(valid[i], valid[j])
    corr_matrix: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                corr_matrix[i][j] = 1.0
            elif j < i:
                corr_matrix[i][j] = corr_matrix[j][i]
            else:
                corr_matrix[i][j] = _pearson(
                    valid[i]["returns_30d"], valid[j]["returns_30d"]
                )

    # ---- per-position metrics -----------------------------------------------
    position_results = []
    for i, p in enumerate(valid):
        others = [corr_matrix[i][j] for j in range(n) if j != i]
        if others:
            avg_corr = sum(others) / len(others)
            max_corr = max(others)
            max_j = max(range(n), key=lambda j: corr_matrix[i][j] if j != i else -2.0)
            max_partner = valid[max_j]["protocol"]
        else:
            # Only one valid position
            avg_corr = 0.0
            max_corr = 0.0
            max_partner = ""

        position_results.append({
            "protocol": p["protocol"],
            "avg_correlation": round(avg_corr, 6),
            "max_correlation": round(max_corr, 6),
            "max_corr_partner": max_partner,
            "correlation_risk": _position_risk_label(avg_corr),
        })

    # ---- portfolio-level metrics --------------------------------------------
    unique_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            unique_pairs.append((i, j, corr_matrix[i][j]))

    if unique_pairs:
        avg_pairwise = sum(c for _, _, c in unique_pairs) / len(unique_pairs)
    else:
        avg_pairwise = 0.0

    high_corr_pairs = [
        {
            "protocol_a": valid[i]["protocol"],
            "protocol_b": valid[j]["protocol"],
            "correlation": round(c, 6),
        }
        for i, j, c in unique_pairs
        if c >= high_threshold
    ]
    high_corr_pairs.sort(key=lambda x: x["correlation"], reverse=True)

    div_score = _diversification_score(avg_pairwise)
    risk_label = _portfolio_risk_label(avg_pairwise)

    # ---- breakdowns ---------------------------------------------------------
    all_positions = positions  # include skipped for breakdowns
    category_breakdown: dict = {}
    asset_breakdown: dict = {}
    for p in all_positions:
        cat = p.get("category", "unknown")
        asset = p.get("underlying_asset", "unknown")
        category_breakdown[cat] = category_breakdown.get(cat, 0) + 1
        asset_breakdown[asset] = asset_breakdown.get(asset, 0) + 1

    return {
        "positions": position_results,
        "portfolio_metrics": {
            "avg_pairwise_correlation": round(avg_pairwise, 6),
            "high_correlation_pairs": high_corr_pairs,
            "portfolio_diversification_score": div_score,
            "risk_label": risk_label,
        },
        "category_breakdown": category_breakdown,
        "asset_breakdown": asset_breakdown,
        "skipped_protocols": skipped,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log (capped at 100 entries, atomic write)
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "correlation_risk_log.json"
)
LOG_PATH = os.path.normpath(LOG_PATH)
_LOG_CAP = 100


def _init_log(path: str) -> None:
    """Create log file as [] if it does not exist."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, [])


def _atomic_write(path: str, data) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(path) or "."
    atomic_save(data, str(path))
def log_result(result: dict, log_path: str = LOG_PATH) -> None:
    """Append result to ring-buffer log (max 100 entries)."""
    _init_log(log_path)
    try:
        with open(log_path) as f:
            entries = json.load(f)
    except (OSError, json.JSONDecodeError):
        entries = []
    entries.append(result)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]
    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _init_log(LOG_PATH)

    # Quick self-test with synthetic positions
    _positions = [
        {
            "protocol": "Aave",
            "allocation_pct": 40.0,
            "underlying_asset": "USDC",
            "category": "lending",
            "returns_30d": [0.01, 0.02, -0.01, 0.03, 0.01] * 6,
        },
        {
            "protocol": "Compound",
            "allocation_pct": 35.0,
            "underlying_asset": "USDC",
            "category": "lending",
            "returns_30d": [0.01, 0.02, -0.01, 0.03, 0.01] * 6,
        },
        {
            "protocol": "Morpho",
            "allocation_pct": 25.0,
            "underlying_asset": "ETH",
            "category": "lending",
            "returns_30d": [0.02, -0.01, 0.03, 0.01, 0.02] * 6,
        },
    ]
    result = analyze(_positions)
    print(json.dumps(result, indent=2))

    if "--run" in sys.argv:
        log_result(result)
        print(f"\n✅ Logged to {LOG_PATH}")

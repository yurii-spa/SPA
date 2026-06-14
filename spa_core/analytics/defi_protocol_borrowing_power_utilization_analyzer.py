"""
MP-1048 DeFiProtocolBorrowingPowerUtilizationAnalyzer
------------------------------------------------------
Analyzes how efficiently a user/position uses their borrowing power in DeFi
lending protocols (Aave, Compound, Morpho, etc.).

Computes:
  - current_ltv_pct          : effective LTV of the position
  - volatility_adjusted_safe_ltv : max safe LTV given collateral volatility
  - optimal_borrow_pct       : recommended target LTV (advisory)
  - safety_buffer_pct        : % points until liquidation threshold
  - risk_adjusted_capacity_usd : additional safe borrowing headroom (USD)
  - utilization_efficiency_score : 0-100 (how close to optimal use)
  - label                    : OPTIMALLY_UTILIZED / WELL_MANAGED /
                               CONSERVATIVE / UNDERUTILIZED / OVER_LEVERAGED

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "borrowing_power_utilization_log.json"
)
_LOG_CAP = 100

# Scoring thresholds (utilization ratio = current_ltv / optimal_ltv)
_RATIO_UNDERUTILIZED_HIGH = 0.20   # below → UNDERUTILIZED
_RATIO_CONSERVATIVE_HIGH  = 0.55   # 0.20–0.55 → CONSERVATIVE
_RATIO_WELL_MANAGED_HIGH  = 0.85   # 0.55–0.85 → WELL_MANAGED
_RATIO_OPTIMAL_HIGH       = 1.10   # 0.85–1.10 → OPTIMALLY_UTILIZED
# above 1.10 → trending OVER_LEVERAGED


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _current_ltv_pct(borrowed_value_usd: float, collateral_value_usd: float) -> float:
    """Return effective LTV % (0 if no collateral)."""
    if collateral_value_usd <= 0:
        return 0.0
    return max(0.0, borrowed_value_usd / collateral_value_usd * 100.0)


def _volatility_adjusted_safe_ltv(
    liquidation_ltv_pct: float,
    asset_volatility_30d_pct: float,
) -> float:
    """
    Return the maximum safe LTV after accounting for a potential collateral
    drawdown equal to asset_volatility_30d_pct.

    Logic: if collateral drops by V%, new effective LTV = old_LTV / (1 - V/100).
    To survive liquidation: old_LTV ≤ liquidation_ltv * (1 - V/100).
    """
    haircut = min(max(asset_volatility_30d_pct, 0.0), 99.0) / 100.0
    return max(0.0, liquidation_ltv_pct * (1.0 - haircut))


def _optimal_borrow_pct(
    max_ltv_pct: float,
    liquidation_ltv_pct: float,
    asset_volatility_30d_pct: float,
    strategy_target_ltv_pct: float,
) -> float:
    """
    Compute the advisory optimal LTV percentage.

    Derives from the volatility-adjusted safe LTV, applies a conservative
    safety margin, respects max_ltv, then aligns with the strategy target
    when that target is within the safe band.
    """
    vol_safe = _volatility_adjusted_safe_ltv(liquidation_ltv_pct, asset_volatility_30d_pct)
    # Conservative cap: 85% of max_ltv AND 90% of vol_safe
    conservative_cap = min(max_ltv_pct * 0.85, vol_safe * 0.90)
    conservative_cap = max(0.0, conservative_cap)

    # Align with strategy target if it is within the conservative cap
    if 0.0 < strategy_target_ltv_pct <= conservative_cap:
        return strategy_target_ltv_pct

    return conservative_cap


def _safety_buffer_pct(current_ltv: float, liquidation_ltv_pct: float) -> float:
    """Return % points of headroom before the liquidation threshold (≥0)."""
    return max(0.0, liquidation_ltv_pct - current_ltv)


def _risk_adjusted_capacity_usd(
    collateral_value_usd: float,
    optimal_borrow_pct: float,
    borrowed_value_usd: float,
) -> float:
    """
    Additional safe borrowing capacity (USD) relative to the optimal LTV.
    Negative means the position already exceeds the advisory optimal.
    """
    optimal_borrow_usd = collateral_value_usd * optimal_borrow_pct / 100.0
    return optimal_borrow_usd - borrowed_value_usd


def _utilization_efficiency_score(
    current_ltv: float,
    optimal_ltv: float,
    vol_safe_ltv: float,
    liquidation_ltv: float,
) -> float:
    """
    Return 0-100 efficiency score.

    Score peaks (~100) when current_ltv ≈ optimal_ltv and decays on either
    side.  Being above the volatility-adjusted safe LTV or above liquidation
    forces the score to 0-20.
    """
    # Immediate liquidation risk
    if liquidation_ltv > 0 and current_ltv >= liquidation_ltv:
        return 0.0

    # Over volatility-adjusted safe limit (but not yet liquidated)
    if vol_safe_ltv > 0 and current_ltv > vol_safe_ltv:
        window = max(liquidation_ltv - vol_safe_ltv, 1.0)
        over_ratio = min((current_ltv - vol_safe_ltv) / window, 1.0)
        return max(0.0, 20.0 * (1.0 - over_ratio))

    # Within safe limits but no optimal defined
    if optimal_ltv <= 0:
        return 10.0

    ratio = current_ltv / optimal_ltv

    if ratio <= 0:
        return 10.0
    elif ratio <= _RATIO_UNDERUTILIZED_HIGH:         # 0–0.20  → score 10–22
        return 10.0 + 12.0 * (ratio / _RATIO_UNDERUTILIZED_HIGH)
    elif ratio <= _RATIO_CONSERVATIVE_HIGH:          # 0.20–0.55
        t = (ratio - _RATIO_UNDERUTILIZED_HIGH) / (
            _RATIO_CONSERVATIVE_HIGH - _RATIO_UNDERUTILIZED_HIGH
        )
        return 22.0 + 28.0 * t                       # 22–50
    elif ratio <= _RATIO_WELL_MANAGED_HIGH:          # 0.55–0.85
        t = (ratio - _RATIO_CONSERVATIVE_HIGH) / (
            _RATIO_WELL_MANAGED_HIGH - _RATIO_CONSERVATIVE_HIGH
        )
        return 50.0 + 35.0 * t                       # 50–85
    elif ratio <= _RATIO_OPTIMAL_HIGH:               # 0.85–1.10
        # Peak at ratio=1.0 → 100, tapers to 85 at both ends of the band
        mid = (_RATIO_WELL_MANAGED_HIGH + _RATIO_OPTIMAL_HIGH) / 2.0  # ~0.975
        half_band = (_RATIO_OPTIMAL_HIGH - _RATIO_WELL_MANAGED_HIGH) / 2.0
        dist = abs(ratio - mid) / half_band
        return 85.0 + 15.0 * max(0.0, 1.0 - dist)
    elif ratio <= 1.30:                              # 1.10–1.30  over-optimal
        t = (ratio - _RATIO_OPTIMAL_HIGH) / (1.30 - _RATIO_OPTIMAL_HIGH)
        return max(50.0, 85.0 - 35.0 * t)
    else:                                            # > 1.30  → approaching OVER_LEVERAGED
        return max(0.0, 50.0 - (ratio - 1.30) * 100.0)


def _label(
    current_ltv: float,
    optimal_ltv: float,
    vol_safe_ltv: float,
    liquidation_ltv: float,
    score: float,
) -> str:
    """
    Classify the borrowing power utilization state.

    Labels (in priority order):
      OVER_LEVERAGED    – at or above liquidation, or above volatility-safe LTV
      OPTIMALLY_UTILIZED – score ≥ 85
      WELL_MANAGED      – score ≥ 50
      CONSERVATIVE      – score ≥ 22
      UNDERUTILIZED     – below 22 and not over-leveraged
    """
    # Dangerous states take priority
    if liquidation_ltv > 0 and current_ltv >= liquidation_ltv:
        return "OVER_LEVERAGED"
    if vol_safe_ltv > 0 and current_ltv > vol_safe_ltv:
        return "OVER_LEVERAGED"

    if score >= 85.0:
        return "OPTIMALLY_UTILIZED"
    if score >= 50.0:
        return "WELL_MANAGED"
    if score >= 22.0:
        return "CONSERVATIVE"
    return "UNDERUTILIZED"


def _build_recommendations(
    label: str,
    current_ltv: float,
    optimal_ltv: float,
    safety_buffer_pct: float,
    risk_adjusted_capacity_usd: float,
    asset_volatility_30d_pct: float,
) -> list[str]:
    """Return advisory recommendations based on the utilization verdict."""
    recs: list[str] = []

    if label == "OVER_LEVERAGED":
        recs.append(
            f"Position is over-leveraged: current LTV {current_ltv:.1f}% "
            f"exceeds the volatility-adjusted safe limit.  Reduce debt "
            f"immediately to restore adequate safety buffer."
        )
        if safety_buffer_pct < 5.0:
            recs.append(
                f"Critical: only {safety_buffer_pct:.1f}% buffer before "
                f"liquidation.  Urgent deleveraging required."
            )
    elif label == "OPTIMALLY_UTILIZED":
        recs.append(
            f"Borrowing power is optimally used: LTV {current_ltv:.1f}% "
            f"near advisory target {optimal_ltv:.1f}%.  Monitor volatility."
        )
    elif label == "WELL_MANAGED":
        recs.append(
            f"LTV {current_ltv:.1f}% is within a healthy range. "
            f"Advisory optimal is {optimal_ltv:.1f}%."
        )
    elif label == "CONSERVATIVE":
        recs.append(
            f"LTV {current_ltv:.1f}% is conservative. "
            f"Up to {risk_adjusted_capacity_usd:,.0f} USD of additional "
            f"safe borrowing capacity remains."
        )
    else:  # UNDERUTILIZED
        recs.append(
            f"Significant borrowing capacity unused (LTV {current_ltv:.1f}% "
            f"vs advisory optimal {optimal_ltv:.1f}%).  Consider deploying "
            f"idle capital for additional yield."
        )

    if asset_volatility_30d_pct > 25.0:
        recs.append(
            f"High collateral volatility ({asset_volatility_30d_pct:.1f}% "
            f"30d) warrants a wider safety buffer."
        )

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DeFiProtocolBorrowingPowerUtilizationAnalyzer:
    """
    Analyzes borrowing power utilization efficiency for a DeFi lending position.

    Usage
    -----
    analyzer = DeFiProtocolBorrowingPowerUtilizationAnalyzer()
    result   = analyzer.analyze(position)
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._log_path: str = cfg.get("log_path", _LOG_PATH)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(self, position: dict) -> dict[str, Any]:
        """
        Analyze borrowing power utilization for a lending position.

        Parameters
        ----------
        position : dict
            - protocol            : str   (informational)
            - collateral_value_usd: float (total collateral in USD)
            - borrowed_value_usd  : float (total debt in USD)
            - max_ltv_pct         : float (protocol maximum LTV %, e.g. 80.0)
            - liquidation_ltv_pct : float (liquidation threshold %, e.g. 85.0)
            - asset_volatility_30d_pct : float (30-day collateral volatility %)
            - position_size_usd   : float (optional, same as collateral if omitted)
            - strategy_target_ltv_pct  : float (target LTV from strategy, e.g. 65.0)

        Returns
        -------
        dict with full analysis results including score, label, recommendations.
        """
        protocol = position.get("protocol", "UNKNOWN")
        collateral_value_usd   = float(position.get("collateral_value_usd", 0.0))
        borrowed_value_usd     = float(position.get("borrowed_value_usd", 0.0))
        max_ltv_pct            = float(position.get("max_ltv_pct", 80.0))
        liquidation_ltv_pct    = float(position.get("liquidation_ltv_pct", 85.0))
        asset_volatility_30d_pct = float(position.get("asset_volatility_30d_pct", 15.0))
        position_size_usd      = float(position.get("position_size_usd", collateral_value_usd))
        strategy_target_ltv_pct = float(position.get("strategy_target_ltv_pct", 0.0))

        # Clamp inputs
        max_ltv_pct           = max(0.0, min(max_ltv_pct, 100.0))
        liquidation_ltv_pct   = max(max_ltv_pct, liquidation_ltv_pct)
        asset_volatility_30d_pct = max(0.0, asset_volatility_30d_pct)
        strategy_target_ltv_pct  = max(0.0, min(strategy_target_ltv_pct, 100.0))

        # Core metrics
        current_ltv = _current_ltv_pct(borrowed_value_usd, collateral_value_usd)
        vol_safe_ltv = _volatility_adjusted_safe_ltv(
            liquidation_ltv_pct, asset_volatility_30d_pct
        )
        optimal_ltv = _optimal_borrow_pct(
            max_ltv_pct, liquidation_ltv_pct,
            asset_volatility_30d_pct, strategy_target_ltv_pct
        )
        buf = _safety_buffer_pct(current_ltv, liquidation_ltv_pct)
        capacity = _risk_adjusted_capacity_usd(
            collateral_value_usd, optimal_ltv, borrowed_value_usd
        )
        score = _utilization_efficiency_score(
            current_ltv, optimal_ltv, vol_safe_ltv, liquidation_ltv_pct
        )
        lbl = _label(current_ltv, optimal_ltv, vol_safe_ltv, liquidation_ltv_pct, score)
        recs = _build_recommendations(
            lbl, current_ltv, optimal_ltv, buf, capacity, asset_volatility_30d_pct
        )

        ts = time.time()
        result: dict[str, Any] = {
            "protocol": protocol,
            "collateral_value_usd": collateral_value_usd,
            "borrowed_value_usd": borrowed_value_usd,
            "position_size_usd": position_size_usd,
            "current_ltv_pct": round(current_ltv, 4),
            "max_ltv_pct": max_ltv_pct,
            "liquidation_ltv_pct": liquidation_ltv_pct,
            "asset_volatility_30d_pct": asset_volatility_30d_pct,
            "strategy_target_ltv_pct": strategy_target_ltv_pct,
            "volatility_adjusted_safe_ltv": round(vol_safe_ltv, 4),
            "optimal_borrow_pct": round(optimal_ltv, 4),
            "safety_buffer_pct": round(buf, 4),
            "risk_adjusted_capacity_usd": round(capacity, 4),
            "utilization_efficiency_score": round(score, 4),
            "label": lbl,
            "recommendations": recs,
            "timestamp": ts,
        }

        try:
            _atomic_log(self._log_path, result)
        except Exception:
            pass  # advisory: never crash caller

        return result


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------

def analyze(position: dict, config: dict | None = None) -> dict:
    """Module-level shortcut for DeFiProtocolBorrowingPowerUtilizationAnalyzer.analyze."""
    return DeFiProtocolBorrowingPowerUtilizationAnalyzer(config).analyze(position)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "protocol": "Aave V3 USDC/ETH",
        "collateral_value_usd": 100_000.0,
        "borrowed_value_usd": 62_000.0,
        "max_ltv_pct": 80.0,
        "liquidation_ltv_pct": 85.0,
        "asset_volatility_30d_pct": 18.0,
        "position_size_usd": 100_000.0,
        "strategy_target_ltv_pct": 65.0,
    }

    r = analyze(_demo)
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)

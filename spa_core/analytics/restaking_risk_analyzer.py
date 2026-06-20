"""
MP-873 RestakingRiskAnalyzer
----------------------------
Assesses the risk of a liquid restaking (LRT) / EigenLayer-style restaking
position.  Considers slashing exposure, the number of AVS (actively validated
services) delegated to, operator concentration, withdrawal delay and LRT depeg.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
import math
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_AVS_SAFE_THRESHOLD: int = 5          # AVS count above this is considered high
_OPERATOR_CONC_THRESHOLD: float = 50.0  # operator concentration % considered high
_DEPEG_THRESHOLD: float = 1.0         # LRT depeg % considered material
_DELAY_THRESHOLD_DAYS: float = 14.0   # withdrawal delay days considered long

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "restaking_risk_log.json"
)
_LOG_CAP = 100


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
    atomic_save(data, str(abs_path))
def _slashing_component(slashing_exposure_pct: float) -> float:
    """0-100 risk contribution from slashing exposure (share of capital)."""
    pct = max(0.0, min(100.0, slashing_exposure_pct))
    return pct


def _avs_component(avs_count: int) -> float:
    """0-100 risk contribution from AVS count (more AVS = more attack surface)."""
    if avs_count <= 0:
        return 0.0
    # Saturating curve: each AVS adds slashing surface; plateau near many AVS.
    return min(100.0, 100.0 * (1.0 - math.exp(-avs_count / 6.0)))


def _operator_component(operator_concentration_pct: float) -> float:
    """0-100 risk contribution from top-operator capital concentration."""
    return max(0.0, min(100.0, operator_concentration_pct))


def _delay_component(withdrawal_delay_days: float) -> float:
    """0-100 risk contribution from withdrawal/unbonding delay."""
    if withdrawal_delay_days <= 0:
        return 0.0
    # 30+ days delay → saturates toward 100.
    return min(100.0, withdrawal_delay_days / 30.0 * 100.0)


def _depeg_component(lrt_depeg_pct: float) -> float:
    """0-100 risk contribution from LRT depeg (abs deviation from base asset)."""
    dev = abs(lrt_depeg_pct)
    # 5% depeg → saturates toward 100.
    return min(100.0, dev / 5.0 * 100.0)


def _restaking_risk_score(
    slashing_exposure_pct: float,
    avs_count: int,
    operator_concentration_pct: float,
    withdrawal_delay_days: float,
    lrt_depeg_pct: float,
) -> float:
    """Return 0-100 weighted restaking risk score (higher = more dangerous)."""
    s = _slashing_component(slashing_exposure_pct)
    a = _avs_component(avs_count)
    o = _operator_component(operator_concentration_pct)
    d = _delay_component(withdrawal_delay_days)
    p = _depeg_component(lrt_depeg_pct)

    score = (
        0.30 * s
        + 0.20 * a
        + 0.20 * o
        + 0.10 * d
        + 0.20 * p
    )
    return max(0.0, min(100.0, score))


def _risk_label(score: float) -> str:
    """Classify restaking_risk_score into LOW / MODERATE / ELEVATED / CRITICAL."""
    if score >= 75.0:
        return "CRITICAL"
    if score >= 50.0:
        return "ELEVATED"
    if score >= 25.0:
        return "MODERATE"
    return "LOW"


def _build_recommendations(
    slashing_exposure_pct: float,
    avs_count: int,
    operator_concentration_pct: float,
    withdrawal_delay_days: float,
    lrt_depeg_pct: float,
    label: str,
) -> list[str]:
    """Return advisory recommendations triggered by high factor values."""
    recs: list[str] = []

    if operator_concentration_pct > _OPERATOR_CONC_THRESHOLD:
        recs.append(
            f"Operator concentration {operator_concentration_pct:.0f}% > "
            f"{_OPERATOR_CONC_THRESHOLD:.0f}%. Diversify across more operators."
        )
    if avs_count > _AVS_SAFE_THRESHOLD:
        recs.append(
            f"Delegated to {avs_count} AVS (> {_AVS_SAFE_THRESHOLD}). "
            f"Reduce AVS exposure to shrink slashing surface."
        )
    if slashing_exposure_pct >= 50.0:
        recs.append(
            f"Slashing exposure {slashing_exposure_pct:.0f}% of capital is high. "
            f"Lower the share of restaked capital."
        )
    if abs(lrt_depeg_pct) >= _DEPEG_THRESHOLD:
        recs.append(
            f"LRT depeg {lrt_depeg_pct:+.2f}%. Consider exiting or hedging the "
            f"LRT token vs base asset."
        )
    if withdrawal_delay_days > _DELAY_THRESHOLD_DAYS:
        recs.append(
            f"Withdrawal delay {withdrawal_delay_days:.0f}d is long. "
            f"Keep liquidity buffer outside the position."
        )

    if label == "CRITICAL" and not recs:
        recs.append("Critical aggregate risk. Reduce position size.")
    if not recs:
        recs.append("Restaking risk within acceptable bounds. Monitor periodically.")

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(position: dict, config: dict | None = None) -> dict:
    """
    Analyze the risk of a liquid restaking position.

    Parameters
    ----------
    position : dict
        Expected keys:
        - protocol: str  (informational)
        - slashing_exposure_pct: float  (share of capital under slashing, 0-100)
        - avs_count: int  (number of AVS delegated to)
        - operator_concentration_pct: float  (capital share at top operator, 0-100)
        - withdrawal_delay_days: float  (unbonding/unlock period)
        - lrt_depeg_pct: float  (LRT price deviation from base asset, signed %)
    config : dict, optional
        - log_path: str  (override default log path)

    Returns
    -------
    dict
        Full restaking risk analysis result.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    protocol = position.get("protocol", "UNKNOWN")
    slashing_exposure_pct = float(position.get("slashing_exposure_pct", 0.0))
    avs_count = int(position.get("avs_count", 0))
    operator_concentration_pct = float(position.get("operator_concentration_pct", 0.0))
    withdrawal_delay_days = float(position.get("withdrawal_delay_days", 0.0))
    lrt_depeg_pct = float(position.get("lrt_depeg_pct", 0.0))

    components = {
        "slashing": _slashing_component(slashing_exposure_pct),
        "avs": _avs_component(avs_count),
        "operator": _operator_component(operator_concentration_pct),
        "delay": _delay_component(withdrawal_delay_days),
        "depeg": _depeg_component(lrt_depeg_pct),
    }

    score = _restaking_risk_score(
        slashing_exposure_pct,
        avs_count,
        operator_concentration_pct,
        withdrawal_delay_days,
        lrt_depeg_pct,
    )
    label = _risk_label(score)
    recommendations = _build_recommendations(
        slashing_exposure_pct,
        avs_count,
        operator_concentration_pct,
        withdrawal_delay_days,
        lrt_depeg_pct,
        label,
    )

    ts = time.time()
    result: dict[str, Any] = {
        "protocol": protocol,
        "slashing_exposure_pct": slashing_exposure_pct,
        "avs_count": avs_count,
        "operator_concentration_pct": operator_concentration_pct,
        "withdrawal_delay_days": withdrawal_delay_days,
        "lrt_depeg_pct": lrt_depeg_pct,
        "components": components,
        "restaking_risk_score": score,
        "label": label,
        "recommendations": recommendations,
        "timestamp": ts,
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


if __name__ == "__main__":
    import sys

    _demo = {
        "protocol": "EtherFi eETH",
        "slashing_exposure_pct": 60.0,
        "avs_count": 8,
        "operator_concentration_pct": 65.0,
        "withdrawal_delay_days": 21.0,
        "lrt_depeg_pct": -1.8,
    }

    r = analyze(_demo)
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)

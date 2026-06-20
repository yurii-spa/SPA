"""
MP-1107  ProtocolDeFiCollateralHealthFactorSimulator
----------------------------------------------------
Simulates Aave-style health factor under various market scenarios
(price drops, rate changes).  Helps users understand margin of safety.

Inputs
------
- collateral_usd                        : float
- collateral_liquidation_threshold_pct  : float  (e.g. 85.0)
- total_debt_usd                        : float
- debt_interest_rate_annual_pct         : float
- scenario_price_drop_pcts              : list[float]  (e.g. [10, 20, 30, 50])
- days_to_simulate                      : int
- protocol_name                         : str

Outputs
-------
- current_health_factor             : float  (collateral * threshold / debt)
- current_ltv_pct                   : float
- debt_with_interest_usd            : float  (after days_to_simulate of accrual)
- scenario_results                  : list[dict]  (per-drop: adj_collateral,
                                        new_hf, is_liquidated)
- safe_price_drop_pct               : float  (max drop before HF < 1.0)
- days_to_liquidation_at_flat_rate  : float  (inf if never)
- health_factor_label               : str    (FORTRESS / HEALTHY / CAUTION /
                                              DANGER / LIQUIDATED)

Labels by current_health_factor
--------------------------------
  HF > 2.0        → FORTRESS
  1.5 ≤ HF ≤ 2.0  → HEALTHY
  1.2 ≤ HF < 1.5  → CAUTION
  1.0 ≤ HF < 1.2  → DANGER
  HF < 1.0        → LIQUIDATED

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "collateral_health_factor_log.json",
)
_LOG_CAP = 100
_EPS = 1e-9

# Health-factor label constants
LABEL_FORTRESS = "FORTRESS"
LABEL_HEALTHY = "HEALTHY"
LABEL_CAUTION = "CAUTION"
LABEL_DANGER = "DANGER"
LABEL_LIQUIDATED = "LIQUIDATED"

ALL_HF_LABELS = (
    LABEL_FORTRESS,
    LABEL_HEALTHY,
    LABEL_CAUTION,
    LABEL_DANGER,
    LABEL_LIQUIDATED,
)

# HF boundary thresholds
_HF_FORTRESS = 2.0
_HF_HEALTHY = 1.5
_HF_CAUTION = 1.2
_HF_DANGER = 1.0

# Sentinel for "never liquidated" days
_NEVER = float("inf")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce *val* to float; return *default* on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Coerce *val* to int; return *default* on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap = _LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, list):
                data = []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = []
    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Metric computation functions (all pure, testable independently)
# ---------------------------------------------------------------------------

def _compute_health_factor(
    collateral_usd: float,
    threshold_pct: float,
    debt_usd: float,
) -> float:
    """
    HF = (collateral * threshold / 100) / debt.
    Returns inf when debt ≈ 0 (no debt = perfectly safe).
    """
    if debt_usd < _EPS:
        return _NEVER
    return collateral_usd * threshold_pct / 100.0 / debt_usd


def _compute_ltv_pct(collateral_usd: float, debt_usd: float) -> float:
    """LTV = debt / collateral * 100.  Returns 0 when collateral ≈ 0."""
    if collateral_usd < _EPS:
        return 0.0
    return debt_usd / collateral_usd * 100.0


def _compute_debt_with_interest(
    debt_usd: float,
    annual_rate_pct: float,
    days: int,
) -> float:
    """
    Simple interest accrual: debt * (1 + rate * days / 365).
    Returns debt unchanged when days ≤ 0.
    """
    if days <= 0:
        return debt_usd
    return debt_usd * (1.0 + annual_rate_pct / 100.0 * days / 365.0)


def _compute_safe_price_drop_pct(
    collateral_usd: float,
    threshold_pct: float,
    debt_usd: float,
) -> float:
    """
    Maximum percentage collateral price drop before HF < 1.0.

    After a drop of p%:
        HF = collateral * (1 - p/100) * threshold/100 / debt = 1
        => p = (1 - debt / (collateral * threshold/100)) * 100

    Result clamped to [0, 100].
    Returns 100.0 when there is no debt (never liquidated).
    Returns 0.0 when already liquidated.
    """
    if debt_usd < _EPS:
        return 100.0
    adj = collateral_usd * threshold_pct / 100.0
    if adj < _EPS:
        return 0.0
    p = (1.0 - debt_usd / adj) * 100.0
    return max(0.0, min(100.0, p))


def _compute_days_to_liquidation_at_flat_rate(
    collateral_usd: float,
    threshold_pct: float,
    debt_usd: float,
    annual_rate_pct: float,
) -> float:
    """
    Days until interest *alone* causes HF to drop below 1.0, assuming
    collateral value stays fixed and only debt grows via simple interest.

    Formula:
        debt * (1 + rate * t / 365) = collateral * threshold / 100
        t = 365 * (HF - 1) / (rate / 100)

    Returns inf  when rate ≈ 0 or no debt (never liquidated by interest alone).
    Returns 0.0  when already liquidated (HF < 1.0).
    """
    if debt_usd < _EPS:
        return _NEVER
    adj = collateral_usd * threshold_pct / 100.0
    hf = adj / debt_usd if debt_usd > _EPS else _NEVER
    if hf < 1.0:
        return 0.0
    if annual_rate_pct < _EPS:
        return _NEVER
    t = 365.0 * (hf - 1.0) / (annual_rate_pct / 100.0)
    return t


def _compute_scenario_results(
    collateral_usd: float,
    threshold_pct: float,
    debt_usd: float,
    scenario_price_drop_pcts: list,
) -> list:
    """
    For each price-drop scenario, compute:
      - price_drop_pct   : the scenario input
      - adj_collateral   : collateral after the drop
      - new_hf           : health factor after the drop
      - is_liquidated    : new_hf < 1.0
    """
    results = []
    for raw_drop in scenario_price_drop_pcts:
        drop = max(0.0, min(100.0, _safe_float(raw_drop, 0.0)))
        adj_collateral = collateral_usd * (1.0 - drop / 100.0)
        if debt_usd < _EPS:
            new_hf = _NEVER
        else:
            new_hf = adj_collateral * threshold_pct / 100.0 / debt_usd
        results.append({
            "price_drop_pct": drop,
            "adj_collateral": adj_collateral,
            "new_hf": new_hf,
            "is_liquidated": new_hf < 1.0,
        })
    return results


def _compute_hf_label(hf: float) -> str:
    """
    Classify health factor into a risk label.

    HF > 2.0        → FORTRESS
    1.5 ≤ HF ≤ 2.0  → HEALTHY
    1.2 ≤ HF < 1.5  → CAUTION
    1.0 ≤ HF < 1.2  → DANGER
    HF < 1.0        → LIQUIDATED
    """
    if hf > _HF_FORTRESS:
        return LABEL_FORTRESS
    elif hf >= _HF_HEALTHY:
        return LABEL_HEALTHY
    elif hf >= _HF_CAUTION:
        return LABEL_CAUTION
    elif hf >= _HF_DANGER:
        return LABEL_DANGER
    else:
        return LABEL_LIQUIDATED


# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------

def analyze(
    data: dict | None = None,
    config: dict | None = None,
    *,
    collateral_usd: float | None = None,
    collateral_liquidation_threshold_pct: float | None = None,
    total_debt_usd: float | None = None,
    debt_interest_rate_annual_pct: float | None = None,
    scenario_price_drop_pcts: list | None = None,
    days_to_simulate: int | None = None,
    protocol_name: str | None = None,
) -> dict:
    """
    Simulate Aave-style health factor and liquidation risk for a position.

    Inputs may be supplied as a *data* dict and/or via keyword arguments
    (keywords take precedence over dict values).

    Returns a complete result dict.  Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)
    d = data if isinstance(data, dict) else {}

    def _pick(kw: Any, key: str, default: float = 0.0) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(d.get(key, default), default)

    def _pick_int(kw: Any, key: str, default: int = 0) -> int:
        if kw is not None:
            return _safe_int(kw, default)
        return _safe_int(d.get(key, default), default)

    def _pick_list(kw: Any, key: str) -> list:
        if kw is not None:
            return list(kw) if hasattr(kw, "__iter__") else []
        val = d.get(key, [])
        return list(val) if hasattr(val, "__iter__") else []

    name = (
        protocol_name
        if protocol_name is not None
        else str(d.get("protocol_name", "UNKNOWN"))
    )

    collateral = max(0.0, _pick(collateral_usd, "collateral_usd"))
    threshold = max(0.0, min(100.0, _pick(
        collateral_liquidation_threshold_pct,
        "collateral_liquidation_threshold_pct",
        80.0,
    )))
    debt = max(0.0, _pick(total_debt_usd, "total_debt_usd"))
    rate = max(0.0, _pick(debt_interest_rate_annual_pct, "debt_interest_rate_annual_pct"))
    drops = _pick_list(scenario_price_drop_pcts, "scenario_price_drop_pcts")
    days = max(0, _pick_int(days_to_simulate, "days_to_simulate", 30))

    hf = _compute_health_factor(collateral, threshold, debt)
    ltv = _compute_ltv_pct(collateral, debt)
    debt_with_interest = _compute_debt_with_interest(debt, rate, days)
    scenario_res = _compute_scenario_results(collateral, threshold, debt, drops)
    safe_drop = _compute_safe_price_drop_pct(collateral, threshold, debt)
    days_liq = _compute_days_to_liquidation_at_flat_rate(collateral, threshold, debt, rate)
    label = _compute_hf_label(hf)

    # Serialise inf as null for JSON log compatibility
    days_liq_json = None if days_liq == _NEVER else days_liq
    hf_json = None if hf == _NEVER else hf

    log_scenario = []
    for s in scenario_res:
        log_scenario.append({
            "price_drop_pct": s["price_drop_pct"],
            "adj_collateral": s["adj_collateral"],
            "new_hf": None if s["new_hf"] == _NEVER else s["new_hf"],
            "is_liquidated": s["is_liquidated"],
        })

    result: dict[str, Any] = {
        "protocol_name": name,
        "collateral_usd": collateral,
        "collateral_liquidation_threshold_pct": threshold,
        "total_debt_usd": debt,
        "debt_interest_rate_annual_pct": rate,
        "days_to_simulate": days,
        "current_health_factor": hf,
        "current_ltv_pct": ltv,
        "debt_with_interest_usd": debt_with_interest,
        "scenario_results": scenario_res,
        "safe_price_drop_pct": safe_drop,
        "days_to_liquidation_at_flat_rate": days_liq,
        "health_factor_label": label,
        "timestamp": time.time(),
    }

    log_entry = dict(result)
    log_entry["current_health_factor"] = hf_json
    log_entry["days_to_liquidation_at_flat_rate"] = days_liq_json
    log_entry["scenario_results"] = log_scenario

    try:
        _atomic_log(log_path, log_entry)
    except Exception:
        pass  # advisory — never crash caller

    return result


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiCollateralHealthFactorSimulator:
    """
    Object-oriented wrapper around the functional ``analyze`` function.

    >>> sim = ProtocolDeFiCollateralHealthFactorSimulator()
    >>> result = sim.analyze({
    ...     "protocol_name": "Aave-V3",
    ...     "collateral_usd": 100_000,
    ...     "collateral_liquidation_threshold_pct": 85.0,
    ...     "total_debt_usd": 60_000,
    ...     "debt_interest_rate_annual_pct": 5.0,
    ...     "scenario_price_drop_pcts": [10, 20, 30, 50],
    ...     "days_to_simulate": 90,
    ... })
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, data: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(data, config=self._config, **kwargs)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    import sys

    _sample = {
        "protocol_name": "Aave-V3-WETH",
        "collateral_usd": 150_000.0,
        "collateral_liquidation_threshold_pct": 82.5,
        "total_debt_usd": 80_000.0,
        "debt_interest_rate_annual_pct": 4.5,
        "scenario_price_drop_pcts": [10.0, 20.0, 30.0, 40.0, 50.0],
        "days_to_simulate": 90,
    }
    r = analyze(_sample)
    # Pretty-print with inf → string
    print(_json.dumps(r, indent=2, default=str))
    sys.exit(0)

"""
MP-1112  DeFiProtocolLeverageAdjustedAPYCalculator
====================================================
Calculates the **true leveraged APY** for looping/leverage strategies:
borrow → supply → borrow again (recursive loop). Accounts for borrow
costs and liquidation risk at each leverage level.

Math (geometric series, per $1 of initial equity)
--------------------------------------------------
With per-loop LTV ``l`` (0 < l < 1) and ``n`` loops the cumulative
supplied-exposure multiplier is the finite geometric sum::

    effective_leverage = (1 - l**n) / (1 - l)

For n = 1 (no leverage): (1 - l) / (1 - l) = 1.0  ✓
For n = 2:  1 + l
For n → ∞: 1 / (1 - l)

Special case l = 1.0 → effective_leverage = n  (limit of the series).

Derived quantities
------------------
::

    total_exposure_usd        = initial_capital_usd * effective_leverage
    total_debt_usd            = total_exposure_usd - initial_capital_usd
    current_composite_ltv_pct = total_debt_usd / total_exposure_usd * 100
                               (= 0 when leverage == 1, i.e. no debt)
    leveraged_supply_apy_pct  = base_supply_apy_pct * effective_leverage
    leveraged_borrow_cost_pct = borrow_apy_pct * (effective_leverage - 1)
    net_leveraged_apy_pct     = leveraged_supply_apy_pct - leveraged_borrow_cost_pct
    safety_margin_pct         = liquidation_ltv_pct - current_composite_ltv_pct

Leverage label (by safety_margin_pct)
--------------------------------------
  safety > 20 %          → SAFE_LEVERAGE
  10 % < safety ≤ 20 %   → MODERATE_LEVERAGE
   5 % < safety ≤ 10 %   → AGGRESSIVE_LEVERAGE
   0 % < safety ≤  5 %   → DANGEROUS_LEVERAGE
  safety ≤ 0 %           → LIQUIDATION_IMMINENT

Log file: data/leverage_adjusted_apy_log.json (ring-buffer, cap 100).

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "leverage_adjusted_apy_log.json"
)
_LOG_CAP = 100

# Label thresholds (safety_margin_pct)
_SAFE_THRESHOLD = 20.0
_MODERATE_THRESHOLD = 10.0
_AGGRESSIVE_THRESHOLD = 5.0
_DANGEROUS_THRESHOLD = 0.0

# Max sensible loops
_MAX_LOOPS_HARD_CAP = 1_000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float, high: float) -> float:
    """Clamp value to [low, high]."""
    return max(low, min(high, value))


def _compute_effective_leverage(ltv_ratio: float, num_loops: int) -> float:
    """
    Geometric series: (1 - ltv^n) / (1 - ltv).

    Special cases:
    * num_loops == 1          → 1.0  (no leverage)
    * ltv_ratio == 1.0        → float(num_loops)
    * ltv_ratio == 0.0        → 1.0  (first deposit only, all subsequent = 0)
    """
    if num_loops <= 1:
        return 1.0
    if math.isclose(ltv_ratio, 1.0, rel_tol=1e-9):
        return float(num_loops)
    if math.isclose(ltv_ratio, 0.0, rel_tol=1e-9):
        return 1.0
    # Standard geometric sum
    return (1.0 - ltv_ratio ** num_loops) / (1.0 - ltv_ratio)


def _label_from_safety_margin(safety_margin_pct: float) -> str:
    """Return leverage label based on safety margin."""
    if safety_margin_pct > _SAFE_THRESHOLD:
        return "SAFE_LEVERAGE"
    if safety_margin_pct > _MODERATE_THRESHOLD:
        return "MODERATE_LEVERAGE"
    if safety_margin_pct > _AGGRESSIVE_THRESHOLD:
        return "AGGRESSIVE_LEVERAGE"
    if safety_margin_pct > _DANGEROUS_THRESHOLD:
        return "DANGEROUS_LEVERAGE"
    return "LIQUIDATION_IMMINENT"


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
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
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolLeverageAdjustedAPYCalculator:
    """
    Calculates the true leveraged APY for looping/leverage strategies.

    Usage
    -----
    ::

        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        result = calc.calculate({
            "base_supply_apy_pct": 5.0,
            "borrow_apy_pct": 2.5,
            "ltv_ratio": 0.75,
            "num_loops": 4,
            "liquidation_ltv_pct": 80.0,
            "initial_capital_usd": 10_000.0,
            "protocol_name": "Aave V3",
        })
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        data: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate leverage-adjusted APY metrics for a single position.

        Parameters
        ----------
        data : dict
            Required keys:
                base_supply_apy_pct   float  APY earned on collateral (%)
                borrow_apy_pct        float  Cost of borrowing (%)
                ltv_ratio             float  Loan-to-value per loop, e.g. 0.75
                num_loops             int    Times to recurse (1 = no leverage)
                liquidation_ltv_pct   float  LTV threshold before liquidation (%)
                initial_capital_usd   float  Starting capital in USD
                protocol_name         str    Protocol identifier

        config : dict, optional
            write_log  bool  Whether to write to log file (default True)
            log_path   str   Override log file path

        Returns
        -------
        dict with the following keys:
            protocol_name            str
            base_supply_apy_pct      float
            borrow_apy_pct           float
            ltv_ratio                float
            num_loops                int
            liquidation_ltv_pct      float
            initial_capital_usd      float
            effective_leverage_x     float
            total_exposure_usd       float
            total_debt_usd           float
            current_composite_ltv_pct float
            leveraged_supply_apy_pct float
            leveraged_borrow_cost_pct float
            net_leveraged_apy_pct    float
            safety_margin_pct        float
            leverage_label           str
            timestamp                float
        """
        if config is None:
            config = {}

        # -- Validate and extract inputs --------------------------------
        base_supply_apy_pct = float(data.get("base_supply_apy_pct", 0.0))
        borrow_apy_pct = float(data.get("borrow_apy_pct", 0.0))
        ltv_ratio = float(data.get("ltv_ratio", 0.0))
        num_loops = int(data.get("num_loops", 1))
        liquidation_ltv_pct = float(data.get("liquidation_ltv_pct", 80.0))
        initial_capital_usd = float(data.get("initial_capital_usd", 0.0))
        protocol_name = str(data.get("protocol_name", "unknown"))

        # Basic sanity guards
        if num_loops < 1:
            num_loops = 1
        if num_loops > _MAX_LOOPS_HARD_CAP:
            num_loops = _MAX_LOOPS_HARD_CAP
        if ltv_ratio < 0.0:
            ltv_ratio = 0.0
        if ltv_ratio > 1.0:
            ltv_ratio = 1.0
        if initial_capital_usd < 0.0:
            initial_capital_usd = 0.0

        # -- Core calculations ------------------------------------------
        effective_leverage_x = _compute_effective_leverage(ltv_ratio, num_loops)

        total_exposure_usd = initial_capital_usd * effective_leverage_x
        total_debt_usd = total_exposure_usd - initial_capital_usd

        # Composite LTV of the whole stack
        if total_exposure_usd > 0.0:
            current_composite_ltv_pct = (total_debt_usd / total_exposure_usd) * 100.0
        else:
            current_composite_ltv_pct = 0.0

        # APY components
        leveraged_supply_apy_pct = base_supply_apy_pct * effective_leverage_x
        leveraged_borrow_cost_pct = borrow_apy_pct * (effective_leverage_x - 1.0)
        net_leveraged_apy_pct = leveraged_supply_apy_pct - leveraged_borrow_cost_pct

        # Safety margin
        safety_margin_pct = liquidation_ltv_pct - current_composite_ltv_pct

        # Label
        leverage_label = _label_from_safety_margin(safety_margin_pct)

        # -- Build result -----------------------------------------------
        ts = time.time()
        result: Dict[str, Any] = {
            "protocol_name": protocol_name,
            "base_supply_apy_pct": round(base_supply_apy_pct, 6),
            "borrow_apy_pct": round(borrow_apy_pct, 6),
            "ltv_ratio": round(ltv_ratio, 6),
            "num_loops": num_loops,
            "liquidation_ltv_pct": round(liquidation_ltv_pct, 6),
            "initial_capital_usd": round(initial_capital_usd, 6),
            "effective_leverage_x": round(effective_leverage_x, 6),
            "total_exposure_usd": round(total_exposure_usd, 6),
            "total_debt_usd": round(total_debt_usd, 6),
            "current_composite_ltv_pct": round(current_composite_ltv_pct, 6),
            "leveraged_supply_apy_pct": round(leveraged_supply_apy_pct, 6),
            "leveraged_borrow_cost_pct": round(leveraged_borrow_cost_pct, 6),
            "net_leveraged_apy_pct": round(net_leveraged_apy_pct, 6),
            "safety_margin_pct": round(safety_margin_pct, 6),
            "leverage_label": leverage_label,
            "timestamp": ts,
        }

        # -- Ring-buffer log -------------------------------------------
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "protocol_name": protocol_name,
                        "num_loops": num_loops,
                        "ltv_ratio": round(ltv_ratio, 4),
                        "effective_leverage_x": round(effective_leverage_x, 4),
                        "net_leveraged_apy_pct": round(net_leveraged_apy_pct, 4),
                        "safety_margin_pct": round(safety_margin_pct, 4),
                        "leverage_label": leverage_label,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return result

    # ------------------------------------------------------------------
    # Convenience: batch mode
    # ------------------------------------------------------------------

    def calculate_batch(
        self,
        positions: list,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate leverage-adjusted APY for a list of positions.

        Parameters
        ----------
        positions : list[dict]
            Each element is a ``data`` dict as accepted by ``calculate()``.
        config : dict, optional
            Same as ``calculate()``; write_log controls logging per call.

        Returns
        -------
        dict with keys:
            results     list[dict]  per-position results
            summary     dict        aggregated stats
            timestamp   float
        """
        if config is None:
            config = {}
        if not isinstance(positions, list):
            raise TypeError("positions must be a list")

        results = [self.calculate(p, config) for p in positions]

        if results:
            net_apys = [r["net_leveraged_apy_pct"] for r in results]
            leverages = [r["effective_leverage_x"] for r in results]
            margins = [r["safety_margin_pct"] for r in results]
            labels = [r["leverage_label"] for r in results]

            summary: Dict[str, Any] = {
                "count": len(results),
                "avg_net_apy_pct": round(sum(net_apys) / len(net_apys), 6),
                "max_net_apy_pct": round(max(net_apys), 6),
                "min_net_apy_pct": round(min(net_apys), 6),
                "avg_leverage_x": round(sum(leverages) / len(leverages), 6),
                "max_leverage_x": round(max(leverages), 6),
                "min_safety_margin_pct": round(min(margins), 6),
                "liquidation_imminent_count": labels.count("LIQUIDATION_IMMINENT"),
                "dangerous_count": labels.count("DANGEROUS_LEVERAGE"),
                "safe_count": labels.count("SAFE_LEVERAGE"),
            }
        else:
            summary = {
                "count": 0,
                "avg_net_apy_pct": 0.0,
                "max_net_apy_pct": 0.0,
                "min_net_apy_pct": 0.0,
                "avg_leverage_x": 0.0,
                "max_leverage_x": 0.0,
                "min_safety_margin_pct": 0.0,
                "liquidation_imminent_count": 0,
                "dangerous_count": 0,
                "safe_count": 0,
            }

        return {
            "results": results,
            "summary": summary,
            "timestamp": time.time(),
        }

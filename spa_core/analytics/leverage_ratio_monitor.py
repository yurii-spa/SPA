"""
MP-793: LeverageRatioMonitor
Monitors portfolio leverage and margin safety across leveraged positions.

Read-only analytics module — stdlib only, atomic writes, ring buffer 100.
"""

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARGIN_STATUS_SAFE = "SAFE"
MARGIN_STATUS_WARNING = "WARNING"
MARGIN_STATUS_DANGER = "DANGER"
MARGIN_STATUS_LIQUIDATING = "LIQUIDATING"

_AT_RISK_STATUSES = {MARGIN_STATUS_DANGER, MARGIN_STATUS_LIQUIDATING}

_DEFAULT_LOG_PATH = "data/leverage_ratio_log.json"
_DEFAULT_MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_margin_status(margin_safety_pct: float) -> str:
    """Classify position safety based on margin_safety_pct."""
    if margin_safety_pct > 10.0:
        return MARGIN_STATUS_SAFE
    elif margin_safety_pct > 5.0:
        return MARGIN_STATUS_WARNING
    elif margin_safety_pct > 0.0:
        return MARGIN_STATUS_DANGER
    else:
        return MARGIN_STATUS_LIQUIDATING


def _compute_position_metrics(pos: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute leverage and margin metrics for a single position.

    Inputs (dict keys):
      protocol             – str
      position_value_usd   – float
      collateral_usd       – float
      debt_usd             – float
      maintenance_margin_pct – float (e.g. 5.0 for 5 %)

    Computed outputs:
      leverage_ratio          = position_value / collateral
      margin_ratio            = (collateral − debt) / position_value × 100
      margin_safety_pct       = margin_ratio − maintenance_margin_pct
      liquidation_distance_pct= margin_safety_pct / leverage_ratio
      margin_status           = SAFE | WARNING | DANGER | LIQUIDATING
    """
    protocol = str(pos.get("protocol", "unknown"))
    position_value = float(pos.get("position_value_usd", 0.0))
    collateral = float(pos.get("collateral_usd", 0.0))
    debt = float(pos.get("debt_usd", 0.0))
    maintenance_margin_pct = float(pos.get("maintenance_margin_pct", 0.0))

    # Leverage ratio — guard against zero collateral
    if collateral > 0.0:
        leverage_ratio = position_value / collateral
    elif position_value > 0.0:
        leverage_ratio = 9999.0  # effectively infinite leverage
    else:
        leverage_ratio = 0.0

    # Margin ratio — guard against zero position_value
    if position_value > 0.0:
        margin_ratio = (collateral - debt) / position_value * 100.0
    else:
        margin_ratio = 0.0

    # Margin safety
    margin_safety_pct = margin_ratio - maintenance_margin_pct

    # Liquidation distance — guard against zero leverage
    if leverage_ratio > 0.0:
        liquidation_distance_pct = margin_safety_pct / leverage_ratio
    else:
        liquidation_distance_pct = 0.0

    margin_status = _classify_margin_status(margin_safety_pct)

    return {
        "protocol": protocol,
        "position_value_usd": round(position_value, 6),
        "collateral_usd": round(collateral, 6),
        "debt_usd": round(debt, 6),
        "maintenance_margin_pct": round(maintenance_margin_pct, 6),
        "leverage_ratio": round(leverage_ratio, 6),
        "margin_ratio": round(margin_ratio, 6),
        "margin_safety_pct": round(margin_safety_pct, 6),
        "liquidation_distance_pct": round(liquidation_distance_pct, 6),
        "margin_status": margin_status,
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LeverageRatioMonitor:
    """
    Monitors leverage ratios and margin safety for leveraged DeFi positions.

    Usage::

        monitor = LeverageRatioMonitor()
        result  = monitor.monitor(positions)
        at_risk = monitor.get_at_risk_positions()
        summary = monitor.get_portfolio_leverage_summary()

    Ring-buffer log is written atomically (tmp + os.replace) to *log_path*,
    capped at *max_entries* entries.
    """

    AT_RISK_STATUSES = _AT_RISK_STATUSES

    def __init__(
        self,
        log_path: str = _DEFAULT_LOG_PATH,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.log_path = log_path
        self.max_entries = int(max_entries)
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def monitor(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compute leverage metrics for *positions*, persist to ring-buffer log,
        and return the result dict.

        Each element of *positions* must be a dict with keys:
          protocol, position_value_usd, collateral_usd, debt_usd,
          maintenance_margin_pct
        """
        computed = [_compute_position_metrics(p) for p in positions]

        leverage_ratios = [p["leverage_ratio"] for p in computed]

        if leverage_ratios:
            portfolio_max_leverage = max(leverage_ratios)
            portfolio_avg_leverage = sum(leverage_ratios) / len(leverage_ratios)
        else:
            portfolio_max_leverage = 0.0
            portfolio_avg_leverage = 0.0

        positions_at_risk = sum(
            1 for p in computed if p["margin_status"] in _AT_RISK_STATUSES
        )

        result: Dict[str, Any] = {
            "timestamp": time.time(),
            "positions": computed,
            "portfolio_max_leverage": round(portfolio_max_leverage, 6),
            "portfolio_avg_leverage": round(portfolio_avg_leverage, 6),
            "positions_at_risk": positions_at_risk,
            "total_positions": len(computed),
        }

        self._last_result = result
        self._append_to_log(result)
        return result

    def get_at_risk_positions(self) -> List[Dict[str, Any]]:
        """
        Return positions from the last *monitor()* call with status
        DANGER or LIQUIDATING.  Returns [] if *monitor()* hasn't been
        called yet.
        """
        if self._last_result is None:
            return []
        return [
            p
            for p in self._last_result.get("positions", [])
            if p["margin_status"] in _AT_RISK_STATUSES
        ]

    def get_portfolio_leverage_summary(self) -> Dict[str, Any]:
        """
        Return portfolio-level leverage summary from the last *monitor()* call.
        Returns zeroed dict if *monitor()* hasn't been called yet.
        """
        if self._last_result is None:
            return {
                "portfolio_max_leverage": 0.0,
                "portfolio_avg_leverage": 0.0,
                "positions_at_risk": 0,
                "total_positions": 0,
            }
        return {
            "portfolio_max_leverage": self._last_result["portfolio_max_leverage"],
            "portfolio_avg_leverage": self._last_result["portfolio_avg_leverage"],
            "positions_at_risk": self._last_result["positions_at_risk"],
            "total_positions": self._last_result["total_positions"],
        }

    # ------------------------------------------------------------------
    # Persistence helpers (atomic ring-buffer)
    # ------------------------------------------------------------------

    def _load_log(self) -> List[Dict[str, Any]]:
        try:
            with open(self.log_path, "r") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def _append_to_log(self, entry: Dict[str, Any]) -> None:
        log = self._load_log()
        log.append(entry)
        if len(log) > self.max_entries:
            log = log[-self.max_entries :]
        self._atomic_write(log)

    def _atomic_write(self, data: Any) -> None:
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(path) + ".tmp"
        try:
            with open(tmp_path, "w") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            # Best-effort cleanup on failure
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

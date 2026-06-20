"""
MP-1072: DeFiProtocolLeverageLoopRiskAnalyzer
==============================================
Advisory-only analytics module.

Analyzes the risk profile of DeFi leverage-looping strategies — recursive
collateral-borrow loops commonly used to amplify yield on lending protocols
(e.g. E-mode on Aave, Compound, Euler V2).

For a single position it computes:
  effective_leverage_x        — actual leverage from ltv + loop_count (geometric series)
  net_apy_pct                 — supply_apy * leverage − borrow_apy * (leverage − 1)
  liquidation_price_drop_pct  — maximum collateral drop (%) before liquidation triggers
  margin_of_safety_pct        — liq_drop_pct − price_drop_trigger_pct (positive = headroom)
  leverage_risk_label         — CONSERVATIVE_LEVERAGE / MODERATE_LEVERAGE /
                                AGGRESSIVE_LEVERAGE / LIQUIDATION_PRONE /
                                LIQUIDATION_IMMINENT

Math notes
----------
Effective leverage via recursive loop (LTV = l, n loops):
    L = sum_{k=0}^{n} l^k = (1 − l^(n+1)) / (1 − l)   for l < 1
    L = 1 when n = 0 (no recursion).

Liquidation price-drop threshold:
    Total collateral = C·L, total debt = C·(L−1).
    Liquidation when  C·L·(1−d)·(LT/100) < C·(L−1)
    → d_max = 1 − (L−1) / (L · LT/100)   [clamped to 0…100 %]

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/leverage_loop_risk_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "leverage_loop_risk_log.json",
)
LOG_MAX_ENTRIES = 100

# Risk-label thresholds on margin_of_safety_pct (percentage points)
_THRESHOLD_LIQ_IMMINENT = 0.0    # margin < 0      → LIQUIDATION_IMMINENT
_THRESHOLD_LIQ_PRONE    = 10.0   # margin 0..10    → LIQUIDATION_PRONE
_THRESHOLD_AGGRESSIVE   = 20.0   # margin 10..20   → AGGRESSIVE_LEVERAGE
_THRESHOLD_MODERATE     = 40.0   # margin 20..40   → MODERATE_LEVERAGE
                                  # margin >= 40    → CONSERVATIVE_LEVERAGE

# Maximum loop count accepted (sanity cap)
_MAX_LOOP_COUNT = 20

_VALID_RISK_LABELS = frozenset({
    "CONSERVATIVE_LEVERAGE",
    "MODERATE_LEVERAGE",
    "AGGRESSIVE_LEVERAGE",
    "LIQUIDATION_PRONE",
    "LIQUIDATION_IMMINENT",
})

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "protocol_name",
    "collateral_asset",
    "borrow_asset",
    "initial_capital_usd",
    "target_leverage_x",
    "ltv_pct",
    "liquidation_threshold_pct",
    "supply_apy_pct",
    "borrow_apy_pct",
    "price_drop_trigger_pct",
    "loop_count",
}


def _validate_input(p: dict) -> None:
    """Validate a position input dict; raises ValueError on any violation."""
    missing = REQUIRED_FIELDS - set(p.keys())
    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")

    if not isinstance(p["protocol_name"], str) or not p["protocol_name"].strip():
        raise ValueError("protocol_name must be a non-empty string")
    if not isinstance(p["collateral_asset"], str) or not p["collateral_asset"].strip():
        raise ValueError("collateral_asset must be a non-empty string")
    if not isinstance(p["borrow_asset"], str) or not p["borrow_asset"].strip():
        raise ValueError("borrow_asset must be a non-empty string")

    if p["initial_capital_usd"] <= 0:
        raise ValueError("initial_capital_usd must be > 0")
    if p["target_leverage_x"] < 1.0:
        raise ValueError("target_leverage_x must be >= 1.0")

    ltv = p["ltv_pct"]
    lt  = p["liquidation_threshold_pct"]
    if not (0 < ltv < 100):
        raise ValueError("ltv_pct must be in (0, 100)")
    if not (0 < lt <= 100):
        raise ValueError("liquidation_threshold_pct must be in (0, 100]")
    if ltv >= lt:
        raise ValueError("ltv_pct must be strictly less than liquidation_threshold_pct")

    if p["supply_apy_pct"] < 0:
        raise ValueError("supply_apy_pct must be >= 0")
    if p["borrow_apy_pct"] < 0:
        raise ValueError("borrow_apy_pct must be >= 0")

    trig = p["price_drop_trigger_pct"]
    if not (0 <= trig <= 100):
        raise ValueError("price_drop_trigger_pct must be in [0, 100]")

    lc = p["loop_count"]
    if not isinstance(lc, int) or isinstance(lc, bool):
        raise ValueError("loop_count must be a non-negative integer")
    if lc < 0:
        raise ValueError("loop_count must be >= 0")
    if lc > _MAX_LOOP_COUNT:
        raise ValueError(f"loop_count must be <= {_MAX_LOOP_COUNT}")


# ---------------------------------------------------------------------------
# Core computations (pure functions, fully unit-testable)
# ---------------------------------------------------------------------------

def _effective_leverage(ltv_pct: float, loop_count: int) -> float:
    """
    Geometric-series leverage from recursive borrow loops.

    L = sum_{k=0}^{n} (ltv/100)^k = (1 − l^(n+1)) / (1 − l)

    n=0 → L = 1.0 (no amplification).
    """
    ltv = ltv_pct / 100.0
    if loop_count == 0:
        return 1.0
    # Geometric partial sum: numerically stable for ltv < 1
    return round((1.0 - ltv ** (loop_count + 1)) / (1.0 - ltv), 6)


def _net_apy(supply_apy_pct: float, borrow_apy_pct: float, leverage: float) -> float:
    """
    Net leveraged APY:
        net = supply_apy × L − borrow_apy × (L − 1)

    Positive when the yield spread covers the borrowing cost at the given leverage.
    """
    return round(
        supply_apy_pct * leverage - borrow_apy_pct * (leverage - 1.0),
        4,
    )


def _liquidation_price_drop(leverage: float, liquidation_threshold_pct: float) -> float:
    """
    Maximum collateral price drop (%) before liquidation is triggered.

    Derivation: liquidation when
        C·L·(1 − d) · (LT/100) < C·(L − 1)
    Solving: d_max = 1 − (L − 1) / (L · LT/100)

    L = 1 → can never liquidate (no debt) → returns 100.0.
    Clamped to [0, 100].
    """
    if leverage <= 1.0:
        return 100.0
    lt = liquidation_threshold_pct / 100.0
    drop = (1.0 - (leverage - 1.0) / (leverage * lt)) * 100.0
    return round(max(0.0, min(100.0, drop)), 4)


def _margin_of_safety(liq_drop_pct: float, price_drop_trigger_pct: float) -> float:
    """
    Safety headroom = liquidation threshold − anticipated stress drop.
    Negative → the stress drop would already trigger liquidation.
    """
    return round(liq_drop_pct - price_drop_trigger_pct, 4)


def _risk_label(margin_of_safety_pct: float) -> str:
    """Map margin-of-safety to a 5-level risk label."""
    if margin_of_safety_pct < _THRESHOLD_LIQ_IMMINENT:
        return "LIQUIDATION_IMMINENT"
    if margin_of_safety_pct < _THRESHOLD_LIQ_PRONE:
        return "LIQUIDATION_PRONE"
    if margin_of_safety_pct < _THRESHOLD_AGGRESSIVE:
        return "AGGRESSIVE_LEVERAGE"
    if margin_of_safety_pct < _THRESHOLD_MODERATE:
        return "MODERATE_LEVERAGE"
    return "CONSERVATIVE_LEVERAGE"


# ---------------------------------------------------------------------------
# Single-position analysis helper
# ---------------------------------------------------------------------------

def _analyze_position(p: dict) -> dict:
    """Validate + compute all outputs for one position dict."""
    _validate_input(p)

    eff_lev = _effective_leverage(p["ltv_pct"], p["loop_count"])
    # If the user's target leverage is lower than the loop series achieves, cap it.
    actual_lev = min(eff_lev, p["target_leverage_x"])

    net     = _net_apy(p["supply_apy_pct"], p["borrow_apy_pct"], actual_lev)
    liq     = _liquidation_price_drop(actual_lev, p["liquidation_threshold_pct"])
    margin  = _margin_of_safety(liq, p["price_drop_trigger_pct"])
    label   = _risk_label(margin)

    return {
        "protocol_name":             p["protocol_name"],
        "collateral_asset":          p["collateral_asset"],
        "borrow_asset":              p["borrow_asset"],
        "initial_capital_usd":       p["initial_capital_usd"],
        "target_leverage_x":         p["target_leverage_x"],
        "effective_leverage_x":      round(actual_lev, 4),
        "net_apy_pct":               net,
        "liquidation_price_drop_pct": liq,
        "margin_of_safety_pct":      margin,
        "leverage_risk_label":       label,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolLeverageLoopRiskAnalyzer:
    """
    Analyzes risk of DeFi leverage-looping positions.
    Advisory / read-only. No execution side-effects.
    """

    def analyze(self, position: dict, config: Optional[dict] = None) -> dict:
        """
        Analyze a single leverage-loop position.

        Parameters
        ----------
        position : dict
            Required keys — see module docstring for full spec.

        Returns
        -------
        dict
            protocol_name, collateral_asset, borrow_asset, initial_capital_usd,
            target_leverage_x, effective_leverage_x, net_apy_pct,
            liquidation_price_drop_pct, margin_of_safety_pct,
            leverage_risk_label, analyzed_at
        """
        if config is None:
            config = {}
        result = _analyze_position(position)
        result["analyzed_at"] = _iso_now()
        _append_log(result)
        return result

    def analyze_batch(self, positions: list, config: Optional[dict] = None) -> dict:
        """
        Analyze a list of positions and return per-position results + aggregates.

        Returns
        -------
        dict
            positions, count, avg_effective_leverage, avg_net_apy_pct,
            min_margin_of_safety_pct, liquidation_imminent_count, analyzed_at
        """
        if config is None:
            config = {}
        if not isinstance(positions, list) or len(positions) == 0:
            raise ValueError("positions must be a non-empty list")

        ts = _iso_now()
        results = [_analyze_position(p) for p in positions]
        for r in results:
            r["analyzed_at"] = ts

        avg_lev = round(
            sum(r["effective_leverage_x"] for r in results) / len(results), 4
        )
        avg_apy = round(
            sum(r["net_apy_pct"] for r in results) / len(results), 4
        )
        min_margin = min(r["margin_of_safety_pct"] for r in results)
        liq_imm = sum(
            1 for r in results if r["leverage_risk_label"] == "LIQUIDATION_IMMINENT"
        )

        output = {
            "positions":                 results,
            "count":                     len(results),
            "avg_effective_leverage":    avg_lev,
            "avg_net_apy_pct":           avg_apy,
            "min_margin_of_safety_pct":  min_margin,
            "liquidation_imminent_count": liq_imm,
            "analyzed_at":               ts,
        }
        _append_log({"batch": True, "count": len(results), "analyzed_at": ts})
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
    """JSON-dump *data* to *path* via a sibling tmp file → os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    """Load existing ring-buffer from *path* or return an empty list."""
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
    """Append a snapshot of *result* to the ring-buffer log (≤ LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    ts = result.get("analyzed_at") or _iso_now()
    snapshot = {
        "ts":                       ts,
        "protocol_name":            result.get("protocol_name"),
        "effective_leverage_x":     result.get("effective_leverage_x"),
        "net_apy_pct":              result.get("net_apy_pct"),
        "liquidation_price_drop_pct": result.get("liquidation_price_drop_pct"),
        "margin_of_safety_pct":     result.get("margin_of_safety_pct"),
        "leverage_risk_label":      result.get("leverage_risk_label"),
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

def analyze(position: dict, config: Optional[dict] = None) -> dict:
    """Module-level shorthand → DeFiProtocolLeverageLoopRiskAnalyzer().analyze()."""
    return DeFiProtocolLeverageLoopRiskAnalyzer().analyze(position, config)

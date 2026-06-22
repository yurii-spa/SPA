"""
MP-1050 DeFiProtocolYieldBearingCollateralAnalyzer
----------------------------------------------------
Analyzes the economics of using yield-bearing tokens (stETH, aUSDC, sDAI)
as collateral in lending protocols.

Computes net carry, yield offset ratio, carry-trade score, oracle-risk score,
and emits an advisory label.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap=100).
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
    os.path.dirname(__file__), "..", "..", "data", "yield_bearing_collateral_log.json"
)
_LOG_CAP = 100

# Oracle lag thresholds (seconds)
_ORACLE_LAG_LOW    = 30.0    # below: negligible risk
_ORACLE_LAG_MEDIUM = 300.0   # 5 min: moderate
_ORACLE_LAG_HIGH   = 1800.0  # 30 min: high

# Carry score thresholds
_SCORE_OPTIMAL  = 75.0
_SCORE_POSITIVE = 50.0
_SCORE_NEUTRAL  = 25.0

# Labels
LABEL_OPTIMAL_CARRY  = "OPTIMAL_CARRY"
LABEL_POSITIVE_CARRY = "POSITIVE_CARRY"
LABEL_NEUTRAL        = "NEUTRAL"
LABEL_NEGATIVE_CARRY = "NEGATIVE_CARRY"
LABEL_CARRY_TRAP     = "CARRY_TRAP"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _net_carry(underlying_apy_pct: float, borrow_rate_pct: float) -> float:
    """Net carry = underlying APY − borrow rate (both in %)."""
    return underlying_apy_pct - borrow_rate_pct


def _yield_offset_ratio(underlying_apy_pct: float, borrow_rate_pct: float) -> float:
    """Fraction of borrow cost offset by collateral yield.

    Returns 0.0 when borrow_rate_pct == 0 (no borrow cost).
    Capped at 1.0 (can't offset more than 100 % with this metric).
    """
    if borrow_rate_pct <= 0:
        return 1.0
    ratio = underlying_apy_pct / borrow_rate_pct
    return min(ratio, 2.0)   # cap at 2× to keep score meaningful


def _carry_trade_score(
    net_carry_pct: float,
    yield_offset_ratio: float,
    ltv_pct: float,
    collateral_rebasing: bool,
) -> float:
    """Composite carry-trade score 0-100.

    Higher is better:
    - Positive net carry contributes up to 50 pts
    - High yield offset adds up to 25 pts
    - Rebasing collateral bonus: up to 10 pts
    - LTV utilisation: up to 15 pts (higher LTV → more leverage but capped)
    """
    # --- net carry component (0-50)
    # Clamp net carry to [-10, +20] then normalise
    nc_clamped = max(-10.0, min(20.0, net_carry_pct))
    nc_score = ((nc_clamped + 10.0) / 30.0) * 50.0   # 0→0 pts, 20→50 pts

    # --- yield offset component (0-25)
    yo_score = min(yield_offset_ratio / 2.0, 1.0) * 25.0

    # --- rebasing bonus (0-10)
    reb_score = 10.0 if collateral_rebasing else 0.0

    # --- LTV component (0-15)
    ltv_frac = max(0.0, min(1.0, ltv_pct / 100.0))
    ltv_score = ltv_frac * 15.0

    raw = nc_score + yo_score + reb_score + ltv_score
    return max(0.0, min(100.0, raw))


def _oracle_risk_score(
    oracle_lag_seconds: float,
    ltv_pct: float,
    liquidation_premium_pct: float,
) -> float:
    """Oracle-risk score 0-100 (higher = more risk).

    Combines lag-based raw risk with LTV amplifier and liquidation-premium
    discount (higher liq premium = more buffer = lower effective risk).
    """
    # Lag component: 0-60 pts
    if oracle_lag_seconds <= _ORACLE_LAG_LOW:
        lag_pts = 0.0
    elif oracle_lag_seconds <= _ORACLE_LAG_MEDIUM:
        t = (oracle_lag_seconds - _ORACLE_LAG_LOW) / (_ORACLE_LAG_MEDIUM - _ORACLE_LAG_LOW)
        lag_pts = t * 30.0
    elif oracle_lag_seconds <= _ORACLE_LAG_HIGH:
        t = (oracle_lag_seconds - _ORACLE_LAG_MEDIUM) / (_ORACLE_LAG_HIGH - _ORACLE_LAG_MEDIUM)
        lag_pts = 30.0 + t * 30.0
    else:
        lag_pts = 60.0

    # LTV amplifier: 0-30 pts (higher LTV = closer to liquidation)
    ltv_frac = max(0.0, min(1.0, ltv_pct / 100.0))
    ltv_pts = ltv_frac * 30.0

    # Liquidation premium discount: reduces risk (0-10 pts discount)
    lp_discount = min(liquidation_premium_pct / 20.0, 1.0) * 10.0

    raw = lag_pts + ltv_pts - lp_discount
    return max(0.0, min(100.0, raw))


def _carry_label(carry_trade_score: float, net_carry_pct: float) -> str:
    """Map score + net_carry into a human label."""
    if net_carry_pct < -5.0:
        return LABEL_CARRY_TRAP
    if carry_trade_score >= _SCORE_OPTIMAL:
        return LABEL_OPTIMAL_CARRY
    if carry_trade_score >= _SCORE_POSITIVE:
        return LABEL_POSITIVE_CARRY
    if carry_trade_score >= _SCORE_NEUTRAL:
        return LABEL_NEUTRAL
    if net_carry_pct < 0.0:
        return LABEL_NEGATIVE_CARRY
    return LABEL_NEUTRAL


def _build_recommendations(
    label: str,
    net_carry_pct: float,
    oracle_risk_score: float,
    ltv_pct: float,
    collateral_rebasing: bool,
) -> list[str]:
    recs: list[str] = []
    if label == LABEL_CARRY_TRAP:
        recs.append("Avoid: borrow costs far exceed collateral yield.")
    if label == LABEL_NEGATIVE_CARRY:
        recs.append("Consider reducing LTV or switching to higher-yield collateral.")
    if oracle_risk_score >= 70:
        recs.append("High oracle lag — reduce LTV or use a faster oracle feed.")
    if ltv_pct > 80:
        recs.append("LTV > 80 %: liquidation risk is elevated; maintain buffer.")
    if collateral_rebasing and net_carry_pct > 0:
        recs.append("Rebasing collateral auto-compounds — monitor balance after each rebase.")
    if label in (LABEL_OPTIMAL_CARRY, LABEL_POSITIVE_CARRY) and oracle_risk_score < 30:
        recs.append("Favourable carry trade. Monitor borrow-rate spikes.")
    if not recs:
        recs.append("Neutral position. Review periodically.")
    return recs


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=100), atomic write."""
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
# ---------------------------------------------------------------------------
# Main analyser class
# ---------------------------------------------------------------------------

class DeFiProtocolYieldBearingCollateralAnalyzer:
    """Analyze economics of yield-bearing collateral in lending protocols."""

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    def analyze(
        self,
        collateral_token: str,
        underlying_apy_pct: float,
        borrow_rate_pct: float,
        ltv_pct: float,
        position_size_usd: float,
        collateral_rebasing: bool = True,
        liquidation_premium_pct: float = 5.0,
        oracle_lag_seconds: float = 0.0,
        log: bool = False,
    ) -> dict[str, Any]:
        """Run analysis and return result dict.

        Parameters
        ----------
        collateral_token        : token symbol, e.g. "stETH"
        underlying_apy_pct      : native yield of the collateral token (%)
        borrow_rate_pct         : borrow cost of the borrowed asset (%)
        ltv_pct                 : loan-to-value ratio used (%)
        position_size_usd       : position size in USD
        collateral_rebasing     : True if token auto-rebases (e.g. stETH)
        liquidation_premium_pct : protocol's liquidation bonus/penalty (%)
        oracle_lag_seconds      : price oracle update lag (seconds)
        log                     : if True, append result to JSON ring-buffer
        """
        # Validate
        if not (0 < ltv_pct <= 100):
            raise ValueError(f"ltv_pct must be in (0, 100], got {ltv_pct}")
        if position_size_usd < 0:
            raise ValueError(f"position_size_usd must be ≥ 0, got {position_size_usd}")
        if oracle_lag_seconds < 0:
            raise ValueError(f"oracle_lag_seconds must be ≥ 0, got {oracle_lag_seconds}")

        # Core metrics
        nc     = _net_carry(underlying_apy_pct, borrow_rate_pct)
        yo     = _yield_offset_ratio(underlying_apy_pct, borrow_rate_pct)
        ct_sc  = _carry_trade_score(nc, yo, ltv_pct, collateral_rebasing)
        or_sc  = _oracle_risk_score(oracle_lag_seconds, ltv_pct, liquidation_premium_pct)
        label  = _carry_label(ct_sc, nc)

        # Annual P&L estimate
        borrow_usd   = position_size_usd * (ltv_pct / 100.0)
        annual_yield = position_size_usd * (underlying_apy_pct / 100.0)
        annual_borrow_cost = borrow_usd * (borrow_rate_pct / 100.0)
        annual_net_pnl = annual_yield - annual_borrow_cost

        recs = _build_recommendations(label, nc, or_sc, ltv_pct, collateral_rebasing)

        result: dict[str, Any] = {
            "collateral_token":         collateral_token,
            "underlying_apy_pct":       round(underlying_apy_pct, 4),
            "borrow_rate_pct":          round(borrow_rate_pct, 4),
            "ltv_pct":                  round(ltv_pct, 4),
            "position_size_usd":        round(position_size_usd, 2),
            "collateral_rebasing":      collateral_rebasing,
            "liquidation_premium_pct":  round(liquidation_premium_pct, 4),
            "oracle_lag_seconds":       round(oracle_lag_seconds, 2),
            # Outputs
            "net_carry_pct":            round(nc, 4),
            "yield_offset_ratio":       round(yo, 4),
            "carry_trade_score":        round(ct_sc, 2),
            "oracle_risk_score":        round(or_sc, 2),
            "label":                    label,
            "borrow_usd":               round(borrow_usd, 2),
            "annual_yield_usd":         round(annual_yield, 2),
            "annual_borrow_cost_usd":   round(annual_borrow_cost, 2),
            "annual_net_pnl_usd":       round(annual_net_pnl, 2),
            "recommendations":          recs,
            "ts":                       int(time.time()),
        }

        if log:
            _atomic_log(self._log_path, result)

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(
    collateral_token: str,
    underlying_apy_pct: float,
    borrow_rate_pct: float,
    ltv_pct: float,
    position_size_usd: float,
    collateral_rebasing: bool = True,
    liquidation_premium_pct: float = 5.0,
    oracle_lag_seconds: float = 0.0,
    log: bool = False,
    log_path: str | None = None,
) -> dict[str, Any]:
    """Module-level shortcut for DeFiProtocolYieldBearingCollateralAnalyzer.analyze()."""
    a = DeFiProtocolYieldBearingCollateralAnalyzer(log_path=log_path)
    return a.analyze(
        collateral_token=collateral_token,
        underlying_apy_pct=underlying_apy_pct,
        borrow_rate_pct=borrow_rate_pct,
        ltv_pct=ltv_pct,
        position_size_usd=position_size_usd,
        collateral_rebasing=collateral_rebasing,
        liquidation_premium_pct=liquidation_premium_pct,
        oracle_lag_seconds=oracle_lag_seconds,
        log=log,
    )

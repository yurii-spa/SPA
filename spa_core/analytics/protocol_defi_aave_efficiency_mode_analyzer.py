"""
MP-1051 ProtocolDeFiAaveEfficiencyModeAnalyzer
-----------------------------------------------
Analyzes Aave V3 eMode (efficiency mode) opportunities.
eMode allows higher LTV for correlated assets, enabling more efficient
capital deployment.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap=100).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "aave_emode_analyzer_log.json"
)
_LOG_CAP = 100

# eMode categories
EMODE_STABLECOINS   = "stablecoins"
EMODE_ETH_CORR      = "eth_correlated"
EMODE_BTC_CORR      = "btc_correlated"
EMODE_CUSTOM        = "custom"

_VALID_EMODE_CATEGORIES = {
    EMODE_STABLECOINS,
    EMODE_ETH_CORR,
    EMODE_BTC_CORR,
    EMODE_CUSTOM,
}

# Base depegging risk by category (0-100)
_CATEGORY_BASE_DEPEG_RISK: dict[str, float] = {
    EMODE_STABLECOINS: 20.0,   # Stablecoin depeg risk (SVB etc.)
    EMODE_ETH_CORR:    10.0,   # ETH / stETH / rETH correlation generally high
    EMODE_BTC_CORR:    12.0,   # BTC / wBTC risk of custody / bridge
    EMODE_CUSTOM:      35.0,   # Unknown/custom category — higher uncertainty
}

# Labels
LABEL_IDEAL_EMODE           = "IDEAL_EMODE"
LABEL_EFFICIENT             = "EFFICIENT"
LABEL_MODERATE_RISK         = "MODERATE_RISK"
LABEL_HIGH_CORRELATION_RISK = "HIGH_CORRELATION_RISK"
LABEL_NOT_RECOMMENDED       = "EMODE_NOT_RECOMMENDED"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ltv_boost(emode_ltv_pct: float, standard_ltv_pct: float) -> float:
    """Absolute LTV boost in percentage points."""
    return max(0.0, emode_ltv_pct - standard_ltv_pct)


def _leverage_multiplier(emode_ltv_pct: float) -> float:
    """Maximum recursive leverage multiplier: 1 / (1 - LTV).

    E.g. 90 % LTV → 10× leverage.
    """
    ltv = max(0.0, min(99.9, emode_ltv_pct)) / 100.0
    return 1.0 / (1.0 - ltv)


def _net_yield(
    supply_apy_pct: float,
    borrow_rate_pct: float,
    emode_ltv_pct: float,
) -> float:
    """Net yield assuming single-loop leverage at eMode LTV.

    net_yield = supply_apy + (LTV/(1-LTV)) * (supply_apy - borrow_rate)
    """
    ltv = max(0.0, min(99.9, emode_ltv_pct)) / 100.0
    loop_factor = ltv / (1.0 - ltv)
    return supply_apy_pct + loop_factor * (supply_apy_pct - borrow_rate_pct)


def _depegging_risk_score(
    emode_category: str,
    correlation_score: float,
    emode_ltv_pct: float,
    supply_asset: str,
    borrow_asset: str,
) -> float:
    """Composite depegging risk 0-100 (higher = more risky).

    Base risk from category + LTV amplifier + low-correlation penalty.
    """
    base = _CATEGORY_BASE_DEPEG_RISK.get(emode_category, 35.0)

    # Correlation discount: very high correlation (≥0.99) → minimal extra risk
    # Low correlation (< 0.8) → significant additional risk
    corr = max(0.0, min(1.0, correlation_score))
    if corr >= 0.99:
        corr_penalty = 0.0
    elif corr >= 0.95:
        corr_penalty = (0.99 - corr) / 0.04 * 15.0
    elif corr >= 0.80:
        corr_penalty = 15.0 + (0.95 - corr) / 0.15 * 25.0
    else:
        corr_penalty = 40.0 + (0.80 - corr) * 100.0   # steep cliff

    # LTV amplifier: higher LTV at risk → more damage if depeg
    ltv_amp = (emode_ltv_pct / 100.0) * 20.0

    # Same-asset supply/borrow (loop) gets a small bonus (no price spread risk)
    same_asset = supply_asset.lower() == borrow_asset.lower()
    same_bonus = -5.0 if same_asset else 0.0

    raw = base + corr_penalty + ltv_amp + same_bonus
    return max(0.0, min(100.0, raw))


def _emode_label(
    net_yield_pct: float,
    depegging_risk_score: float,
    ltv_boost_pct: float,
    leverage_multiplier: float,
) -> str:
    """Derive advisory label."""
    if depegging_risk_score >= 70:
        return LABEL_NOT_RECOMMENDED
    if depegging_risk_score >= 50:
        return LABEL_HIGH_CORRELATION_RISK
    # Positive net yield required for anything above MODERATE
    if net_yield_pct < 0:
        return LABEL_NOT_RECOMMENDED
    if depegging_risk_score >= 30:
        return LABEL_MODERATE_RISK
    if ltv_boost_pct >= 10 and net_yield_pct > 0:
        return LABEL_IDEAL_EMODE
    return LABEL_EFFICIENT


def _build_recommendations(
    label: str,
    net_yield_pct: float,
    depegging_risk_score: float,
    leverage_multiplier: float,
    emode_category: str,
    correlation_score: float,
) -> list[str]:
    recs: list[str] = []
    if label == LABEL_NOT_RECOMMENDED:
        recs.append("eMode not advisable: either depeg risk is too high or yield is negative.")
    if label == LABEL_HIGH_CORRELATION_RISK:
        recs.append("Correlation risk elevated — ensure assets remain correlated under stress.")
    if label == LABEL_MODERATE_RISK:
        recs.append("Moderate risk: monitor correlation closely, keep position sized conservatively.")
    if depegging_risk_score >= 50:
        recs.append("High depeg risk: set tight liquidation buffers.")
    if leverage_multiplier >= 5:
        recs.append(f"Leverage ~{leverage_multiplier:.1f}× — small depeg event causes outsized losses.")
    if emode_category == EMODE_STABLECOINS and correlation_score < 0.95:
        recs.append("Stablecoin pair with low correlation; consider USDC/USDT only pairs.")
    if label in (LABEL_IDEAL_EMODE, LABEL_EFFICIENT):
        recs.append("Favourable eMode. Confirm oracle and liquidation mechanism support eMode pair.")
    if net_yield_pct > 0 and label == LABEL_IDEAL_EMODE:
        recs.append(f"Expected net yield {net_yield_pct:.2f} % — attractive capital efficiency gain.")
    if not recs:
        recs.append("Review eMode parameters before committing capital.")
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


# ---------------------------------------------------------------------------
# Main analyser class
# ---------------------------------------------------------------------------

class ProtocolDeFiAaveEfficiencyModeAnalyzer:
    """Analyze Aave V3 eMode opportunities for correlated asset pairs."""

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    def analyze(
        self,
        emode_category: str,
        supply_asset: str,
        borrow_asset: str,
        emode_ltv_pct: float,
        standard_ltv_pct: float,
        supply_apy_pct: float,
        borrow_rate_pct: float,
        position_size_usd: float,
        correlation_score: float,
        log: bool = False,
    ) -> dict[str, Any]:
        """Run eMode analysis and return result dict.

        Parameters
        ----------
        emode_category      : one of stablecoins/eth_correlated/btc_correlated/custom
        supply_asset        : asset supplied as collateral (e.g. "wstETH")
        borrow_asset        : asset borrowed (e.g. "ETH")
        emode_ltv_pct       : LTV allowed in eMode (%)
        standard_ltv_pct    : LTV in standard mode (%)
        supply_apy_pct      : APY on supplied asset (%)
        borrow_rate_pct     : borrow rate on borrowed asset (%)
        position_size_usd   : notional position size (USD)
        correlation_score   : price correlation between supply/borrow (0-1)
        log                 : if True, append result to JSON ring-buffer
        """
        # Validate
        if emode_category not in _VALID_EMODE_CATEGORIES:
            raise ValueError(
                f"emode_category must be one of {sorted(_VALID_EMODE_CATEGORIES)}, "
                f"got {emode_category!r}"
            )
        if not (0 < emode_ltv_pct <= 100):
            raise ValueError(f"emode_ltv_pct must be in (0, 100], got {emode_ltv_pct}")
        if not (0 <= standard_ltv_pct <= 100):
            raise ValueError(f"standard_ltv_pct must be in [0, 100], got {standard_ltv_pct}")
        if emode_ltv_pct < standard_ltv_pct:
            raise ValueError(
                f"emode_ltv_pct ({emode_ltv_pct}) must be ≥ standard_ltv_pct ({standard_ltv_pct})"
            )
        if position_size_usd < 0:
            raise ValueError(f"position_size_usd must be ≥ 0, got {position_size_usd}")
        if not (0.0 <= correlation_score <= 1.0):
            raise ValueError(f"correlation_score must be in [0, 1], got {correlation_score}")

        # Core metrics
        ltv_boost   = _ltv_boost(emode_ltv_pct, standard_ltv_pct)
        lev_mult    = _leverage_multiplier(emode_ltv_pct)
        net_yld     = _net_yield(supply_apy_pct, borrow_rate_pct, emode_ltv_pct)
        dep_risk    = _depegging_risk_score(
            emode_category, correlation_score, emode_ltv_pct, supply_asset, borrow_asset
        )
        label       = _emode_label(net_yld, dep_risk, ltv_boost, lev_mult)

        # P&L estimate (single loop)
        borrow_usd          = position_size_usd * (emode_ltv_pct / 100.0)
        annual_supply_yield = position_size_usd * (supply_apy_pct / 100.0)
        annual_borrow_cost  = borrow_usd * (borrow_rate_pct / 100.0)
        annual_net_pnl      = annual_supply_yield - annual_borrow_cost

        # LTV boost impact on collateral capacity
        extra_borrow_capacity = position_size_usd * (ltv_boost / 100.0)

        recs = _build_recommendations(
            label, net_yld, dep_risk, lev_mult, emode_category, correlation_score
        )

        result: dict[str, Any] = {
            "emode_category":           emode_category,
            "supply_asset":             supply_asset,
            "borrow_asset":             borrow_asset,
            "emode_ltv_pct":            round(emode_ltv_pct, 4),
            "standard_ltv_pct":         round(standard_ltv_pct, 4),
            "supply_apy_pct":           round(supply_apy_pct, 4),
            "borrow_rate_pct":          round(borrow_rate_pct, 4),
            "position_size_usd":        round(position_size_usd, 2),
            "correlation_score":        round(correlation_score, 4),
            # Outputs
            "ltv_boost_pct":            round(ltv_boost, 4),
            "leverage_multiplier":      round(lev_mult, 4),
            "net_yield_pct":            round(net_yld, 4),
            "depegging_risk_score":     round(dep_risk, 2),
            "label":                    label,
            "borrow_usd":               round(borrow_usd, 2),
            "annual_supply_yield_usd":  round(annual_supply_yield, 2),
            "annual_borrow_cost_usd":   round(annual_borrow_cost, 2),
            "annual_net_pnl_usd":       round(annual_net_pnl, 2),
            "extra_borrow_capacity_usd": round(extra_borrow_capacity, 2),
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
    emode_category: str,
    supply_asset: str,
    borrow_asset: str,
    emode_ltv_pct: float,
    standard_ltv_pct: float,
    supply_apy_pct: float,
    borrow_rate_pct: float,
    position_size_usd: float,
    correlation_score: float,
    log: bool = False,
    log_path: str | None = None,
) -> dict[str, Any]:
    """Module-level shortcut for ProtocolDeFiAaveEfficiencyModeAnalyzer.analyze()."""
    a = ProtocolDeFiAaveEfficiencyModeAnalyzer(log_path=log_path)
    return a.analyze(
        emode_category=emode_category,
        supply_asset=supply_asset,
        borrow_asset=borrow_asset,
        emode_ltv_pct=emode_ltv_pct,
        standard_ltv_pct=standard_ltv_pct,
        supply_apy_pct=supply_apy_pct,
        borrow_rate_pct=borrow_rate_pct,
        position_size_usd=position_size_usd,
        correlation_score=correlation_score,
        log=log,
    )

"""
MP-1033: ProtocolDeFiLiquidationCascadeRiskAnalyzer

Analyzes risk of a liquidation cascade in lending protocols: an initial
price drop triggers mass liquidations, which increase sell pressure, causing
further price drops (reflexive feedback loop — "death spiral" risk).

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/liquidation_cascade_risk_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/liquidation_cascade_risk_log.json")
MAX_ENTRIES = 100

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# Label thresholds (cascade_risk_score 0-100)
_LABEL_THRESHOLDS = [
    (85, "DEATH_SPIRAL"),
    (65, "HIGH_CASCADE"),
    (45, "MODERATE_CASCADE"),
    (25, "LOW_CASCADE"),
    (0,  "STABLE"),
]

# Market impact coefficient: liquidation volume relative to daily volume
# maps to % market impact on the collateral asset price
_MARKET_IMPACT_COEFF = 0.08   # 8% price impact per 100% of daily volume liquidated


# ─────────────────────────────────────────────────────────────────
# Internal computation helpers (exposed for unit tests)
# ─────────────────────────────────────────────────────────────────

def _compute_cascade_risk_score(
    ltv_ratio: float,
    liquidation_threshold: float,
    price_drop_trigger_pct: float,
    concentrated_positions_pct: float,
    total_collateral_usd: float,
    daily_volume_usd: float,
) -> float:
    """
    Compute cascade risk score in [0.0, 100.0].

    Higher LTV, lower liquidation threshold buffer, severe price drop,
    concentration, and illiquidity all increase cascade risk.

    Parameters
    ----------
    ltv_ratio : float
        Current average LTV across the protocol (0-1).
    liquidation_threshold : float
        LTV at which liquidation is triggered (0-1), must be ≥ ltv_ratio.
    price_drop_trigger_pct : float
        Hypothetical price drop (%) that initiates liquidations (0-100).
    concentrated_positions_pct : float
        Percentage (0-100) of total collateral in top-10 concentrated positions.
    total_collateral_usd : float
        Total collateral value at risk, in USD.
    daily_volume_usd : float
        Average daily on-market trading volume for the collateral asset, in USD.
    """
    score = 0.0

    # 1. LTV proximity to liquidation threshold — how close to breach
    #    Buffer = (threshold - current ltv) / threshold
    liq_thresh = max(float(liquidation_threshold), 0.001)
    ltv = max(0.0, min(float(ltv_ratio), 1.0))
    buffer_ratio = max(0.0, (liq_thresh - ltv) / liq_thresh)
    # Small buffer → high risk. buffer=0 → +35, buffer=1 → 0
    score += (1.0 - buffer_ratio) * 35.0

    # 2. Price drop trigger magnitude
    pdrop = max(0.0, min(float(price_drop_trigger_pct), 100.0))
    if pdrop >= 50.0:
        score += 25.0
    elif pdrop >= 30.0:
        score += 18.0
    elif pdrop >= 15.0:
        score += 12.0
    elif pdrop >= 5.0:
        score += 6.0
    elif pdrop >= 1.0:
        score += 2.0

    # 3. Concentration risk
    conc = max(0.0, min(float(concentrated_positions_pct), 100.0))
    score += (conc / 100.0) * 20.0

    # 4. Liquidity depth: ratio of collateral to daily volume
    #    Large collateral vs. thin volume = hard to liquidate without price impact
    vol = max(float(daily_volume_usd), 1.0)
    collateral = max(0.0, float(total_collateral_usd))
    liquidity_ratio = collateral / vol  # > 1 means collateral > daily volume
    if liquidity_ratio >= 5.0:
        score += 20.0
    elif liquidity_ratio >= 2.0:
        score += 12.0
    elif liquidity_ratio >= 1.0:
        score += 6.0
    elif liquidity_ratio >= 0.5:
        score += 2.0

    return max(0.0, min(100.0, score))


def _compute_estimated_liquidation_volume_usd(
    total_collateral_usd: float,
    ltv_ratio: float,
    liquidation_threshold: float,
    price_drop_trigger_pct: float,
    concentrated_positions_pct: float,
) -> float:
    """
    Estimate volume of collateral that would be liquidated after the price drop.

    Methodology:
    - Price drop moves effective LTV up by: new_ltv = ltv / (1 - pdrop/100)
    - Positions breaching liquidation_threshold must be liquidated
    - Concentration amplifies the at-risk fraction
    """
    pdrop = max(0.0, min(float(price_drop_trigger_pct), 100.0))
    ltv = max(0.0, min(float(ltv_ratio), 1.0))
    liq_thresh = max(0.001, float(liquidation_threshold))
    collateral = max(0.0, float(total_collateral_usd))
    conc = max(0.0, min(float(concentrated_positions_pct), 100.0)) / 100.0

    if pdrop >= 100.0:
        return collateral  # total wipeout

    # Effective LTV after price drop
    price_retention = 1.0 - (pdrop / 100.0)
    if price_retention <= 0:
        return collateral
    effective_ltv = ltv / price_retention

    if effective_ltv <= liq_thresh:
        # Below liquidation threshold even after drop — no liquidations
        return 0.0

    # Fraction of collateral that is now underwater
    breach_fraction = min((effective_ltv - liq_thresh) / max(effective_ltv, 0.001), 1.0)

    # Concentrated positions are more likely to be fully underwater simultaneously
    concentration_amplifier = 1.0 + conc * 0.5
    at_risk_fraction = min(breach_fraction * concentration_amplifier, 1.0)

    return round(collateral * at_risk_fraction, 2)


def _compute_market_impact_pct(
    estimated_liquidation_volume_usd: float,
    daily_volume_usd: float,
) -> float:
    """
    Estimate additional price impact (%) from liquidation sell pressure.

    Uses a square-root market impact model common in execution research:
    impact = coeff × sqrt(liquidation_volume / daily_volume)
    """
    vol = max(float(daily_volume_usd), 1.0)
    liq_vol = max(0.0, float(estimated_liquidation_volume_usd))
    ratio = liq_vol / vol
    # Square root model caps extreme scenarios gracefully
    raw_impact = _MARKET_IMPACT_COEFF * (ratio ** 0.5) * 100.0
    return round(max(0.0, min(100.0, raw_impact)), 4)


def _compute_recovery_time_days(
    cascade_risk_score: float,
    market_impact_pct: float,
    daily_volume_usd: float,
    total_collateral_usd: float,
) -> int:
    """
    Estimate recovery time (days) for the protocol to stabilise post-cascade.

    Model: higher scores + bigger market impact + larger position relative
    to volume = longer recovery.
    """
    score = max(0.0, float(cascade_risk_score))
    impact = max(0.0, float(market_impact_pct))
    vol = max(float(daily_volume_usd), 1.0)
    collateral = max(0.0, float(total_collateral_usd))

    # Base days from cascade score
    base_days = score / 10.0  # 100-score → 10 days base

    # Market impact adds extra days
    base_days += impact * 0.3

    # Liquidity ratio: more collateral relative to volume → slower recovery
    liquidity_ratio = min(collateral / vol, 20.0)
    base_days += liquidity_ratio * 0.5

    return max(0, int(round(base_days)))


def _cascade_label(cascade_risk_score: float) -> str:
    """Map cascade_risk_score to a risk label."""
    score = float(cascade_risk_score)
    for threshold, label in _LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "STABLE"


def _compute_flags(
    ltv_ratio: float,
    liquidation_threshold: float,
    price_drop_trigger_pct: float,
    concentrated_positions_pct: float,
    total_collateral_usd: float,
    daily_volume_usd: float,
) -> list:
    """Return list of active risk flag strings."""
    flags: list[str] = []
    ltv = float(ltv_ratio)
    thresh = float(liquidation_threshold)
    pdrop = float(price_drop_trigger_pct)
    conc = float(concentrated_positions_pct)
    vol = max(float(daily_volume_usd), 1.0)
    collateral = float(total_collateral_usd)

    # Near-breach
    if thresh > 0 and (thresh - ltv) / thresh < 0.10:
        flags.append("NEAR_LIQUIDATION_THRESHOLD")

    # Severe drop scenario
    if pdrop >= 30.0:
        flags.append("SEVERE_PRICE_DROP_SCENARIO")

    # Concentration
    if conc >= 60.0:
        flags.append("HIGHLY_CONCENTRATED_POSITIONS")

    # Illiquid market
    if collateral >= vol * 2.0:
        flags.append("ILLIQUID_MARKET")

    # High LTV overall
    if ltv >= 0.75:
        flags.append("HIGH_PORTFOLIO_LTV")

    # Thin collateral buffer
    if thresh > 0 and ltv / thresh >= 0.95:
        flags.append("CRITICAL_LTV_BUFFER")

    return flags


# ─────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────

class ProtocolDeFiLiquidationCascadeRiskAnalyzer:
    """
    Advisory analyzer for DeFi liquidation cascade risk.

    Models how a price drop in the collateral asset can trigger a
    self-reinforcing cycle of liquidations and further price declines,
    estimating cascade risk score, liquidation volume, market impact,
    and protocol recovery time.

    Pure stdlib, read-only/advisory. Ring-buffer log to
    data/liquidation_cascade_risk_log.json (cap 100, atomic writes).
    """

    def analyze(
        self,
        collateral_asset: str,
        ltv_ratio: float,
        liquidation_threshold: float,
        total_collateral_usd: float,
        daily_volume_usd: float,
        concentrated_positions_pct: float,
        price_drop_trigger_pct: float,
        data_dir: str | None = None,
    ) -> dict:
        """
        Analyze liquidation cascade risk for a lending protocol position.

        Parameters
        ----------
        collateral_asset : str
            Name/ticker of the collateral asset (e.g. 'ETH', 'wBTC').
        ltv_ratio : float
            Current average loan-to-value across the protocol (0-1).
        liquidation_threshold : float
            LTV ratio at which liquidations are triggered (0-1).
        total_collateral_usd : float
            Total collateral value at risk, in USD.
        daily_volume_usd : float
            Average daily on-market trading volume of the collateral, in USD.
        concentrated_positions_pct : float
            Percentage (0-100) of total collateral in the largest 10 positions.
        price_drop_trigger_pct : float
            Hypothetical price drop (0-100%) that triggers the cascade analysis.
        data_dir : str, optional
            Override directory for log file (tests use temp dirs).

        Returns
        -------
        dict
            {
              "collateral_asset": str,
              "ltv_ratio": float,
              "liquidation_threshold": float,
              "total_collateral_usd": float,
              "daily_volume_usd": float,
              "concentrated_positions_pct": float,
              "price_drop_trigger_pct": float,
              "cascade_risk_score": float,
              "estimated_liquidation_volume_usd": float,
              "market_impact_pct": float,
              "recovery_time_days": int,
              "label": str,
              "flags": list[str],
              "timestamp": float,
            }
        """
        asset = str(collateral_asset)
        ltv = max(0.0, min(1.0, float(ltv_ratio)))
        liq_thresh = max(ltv, min(1.0, float(liquidation_threshold)))  # thresh ≥ ltv
        collateral = max(0.0, float(total_collateral_usd))
        daily_vol = max(0.0, float(daily_volume_usd))
        conc = max(0.0, min(100.0, float(concentrated_positions_pct)))
        pdrop = max(0.0, min(100.0, float(price_drop_trigger_pct)))

        cascade_risk_score = _compute_cascade_risk_score(
            ltv, liq_thresh, pdrop, conc, collateral, daily_vol
        )
        liq_volume = _compute_estimated_liquidation_volume_usd(
            collateral, ltv, liq_thresh, pdrop, conc
        )
        market_impact = _compute_market_impact_pct(liq_volume, daily_vol)
        recovery_days = _compute_recovery_time_days(
            cascade_risk_score, market_impact, daily_vol, collateral
        )
        label = _cascade_label(cascade_risk_score)
        flags = _compute_flags(
            ltv, liq_thresh, pdrop, conc, collateral, daily_vol
        )

        result = {
            "collateral_asset": asset,
            "ltv_ratio": ltv,
            "liquidation_threshold": liq_thresh,
            "total_collateral_usd": collateral,
            "daily_volume_usd": daily_vol,
            "concentrated_positions_pct": conc,
            "price_drop_trigger_pct": pdrop,
            "cascade_risk_score": round(cascade_risk_score, 4),
            "estimated_liquidation_volume_usd": liq_volume,
            "market_impact_pct": market_impact,
            "recovery_time_days": recovery_days,
            "label": label,
            "flags": flags,
            "timestamp": time.time(),
        }

        _append_log(result, data_dir=data_dir)
        return result


# ─────────────────────────────────────────────────────────────────
# Ring-buffer log
# ─────────────────────────────────────────────────────────────────

def _append_log(entry: dict, data_dir: str | None = None) -> None:
    """Atomically append *entry* to the log file, capped at MAX_ENTRIES."""
    if data_dir is not None:
        log_path = Path(data_dir) / "liquidation_cascade_risk_log.json"
    else:
        log_path = DATA_FILE

    log_path.parent.mkdir(parents=True, exist_ok=True)

    existing: list = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp = log_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, log_path)


# ─────────────────────────────────────────────────────────────────
# CLI demo
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    analyzer = ProtocolDeFiLiquidationCascadeRiskAnalyzer()

    scenarios = [
        {
            "collateral_asset": "ETH",
            "ltv_ratio": 0.72,
            "liquidation_threshold": 0.80,
            "total_collateral_usd": 8_000_000_000,
            "daily_volume_usd": 15_000_000_000,
            "concentrated_positions_pct": 25.0,
            "price_drop_trigger_pct": 20.0,
        },
        {
            "collateral_asset": "wBTC",
            "ltv_ratio": 0.68,
            "liquidation_threshold": 0.75,
            "total_collateral_usd": 3_500_000_000,
            "daily_volume_usd": 2_000_000_000,
            "concentrated_positions_pct": 60.0,
            "price_drop_trigger_pct": 30.0,
        },
        {
            "collateral_asset": "LUNA",
            "ltv_ratio": 0.78,
            "liquidation_threshold": 0.80,
            "total_collateral_usd": 18_000_000_000,
            "daily_volume_usd": 300_000_000,
            "concentrated_positions_pct": 80.0,
            "price_drop_trigger_pct": 50.0,
        },
    ]

    for scenario in scenarios:
        result = analyzer.analyze(**scenario)
        print(
            f"{result['collateral_asset']}: score={result['cascade_risk_score']:.1f}  "
            f"label={result['label']}  "
            f"liq_vol=${result['estimated_liquidation_volume_usd']:,.0f}  "
            f"market_impact={result['market_impact_pct']:.2f}%  "
            f"recovery={result['recovery_time_days']}d"
        )

"""
MP-942: DeFiNFTCollateralValuationModel
Models NFT value as collateral in DeFi protocols.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import os
import math
import time
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "nft_collateral_log.json")
LOG_CAP = 100

LABEL_EXCELLENT = "EXCELLENT"
LABEL_GOOD = "GOOD"
LABEL_ACCEPTABLE = "ACCEPTABLE"
LABEL_RISKY = "RISKY"
LABEL_UNSUITABLE = "UNSUITABLE"

FLAG_ILLIQUID = "ILLIQUID"
FLAG_RARE_TRAIT = "RARE_TRAIT"
FLAG_STALE_PRICE = "STALE_PRICE"
FLAG_LOW_LTV = "LOW_LTV_RECOMMENDED"
FLAG_BLUE_CHIP = "BLUE_CHIP"

DEFAULT_CONFIG = {
    "illiquid_volume_threshold_eth": 1.0,     # volume_7d < this → ILLIQUID
    "rare_trait_threshold": 80,               # rarity_score > this → RARE_TRAIT
    "stale_days_threshold": 30,               # days_since_sale > this → STALE_PRICE
    "blue_chip_threshold": 75,                # blue_chip_score > this → BLUE_CHIP
    "low_ltv_threshold_pct": 30.0,            # recommended_ltv < this → LOW_LTV
    "max_rarity_premium_pct": 50.0,           # cap on rarity premium
    "max_liquidity_discount_pct": 40.0,       # cap on liquidity discount
    "base_ltv_pct": 60.0,                     # LTV for a perfect NFT
    "min_ltv_pct": 5.0,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_liquidity_discount(nft: dict, config: dict) -> float:
    """
    Higher listing_count relative to holder_count → more liquid → smaller discount.
    Low volume also inflates discount.
    """
    holder_count = max(1, float(nft.get("holder_count", 100)))
    listing_count = max(0, float(nft.get("listing_count", 0)))
    volume_7d = max(0.0, float(nft.get("volume_7d_eth", 0.0)))
    volume_30d = max(0.0, float(nft.get("volume_30d_eth", 0.0)))

    # Listing ratio: 0 listings = most illiquid, many listings = liquid
    listing_ratio = listing_count / holder_count  # 0 → 1+

    # Volume component: log-scaled, capped at 100 ETH → 0 discount
    vol_score = _clamp(math.log1p(volume_30d) / math.log1p(100.0), 0.0, 1.0)

    # Liquidity score 0-1: 1 = very liquid
    liquidity_score = _clamp(0.5 * listing_ratio + 0.5 * vol_score, 0.0, 1.0)

    # Discount: low liquidity → high discount
    # discount = max_discount * (1 - liquidity_score)
    max_discount = float(config.get("max_liquidity_discount_pct", 40.0))
    discount = max_discount * (1.0 - liquidity_score)

    # Extra penalty if volume_7d is very low (illiquid market)
    illiquid_threshold = float(config.get("illiquid_volume_threshold_eth", 1.0))
    if volume_7d < illiquid_threshold:
        extra = (1.0 - volume_7d / max(illiquid_threshold, 1e-9)) * 10.0
        discount = _clamp(discount + extra, 0.0, max_discount)

    return round(discount, 4)


def _compute_rarity_premium(nft: dict, config: dict) -> float:
    """
    trait_rarity_score 0-100; higher → rarer → premium above floor.
    """
    rarity = _clamp(float(nft.get("trait_rarity_score", 0)), 0.0, 100.0)
    max_premium = float(config.get("max_rarity_premium_pct", 50.0))

    # Non-linear: rarity^2 / 100 → 0 at rarity=0, max at rarity=100
    premium = max_premium * (rarity ** 2) / 10000.0
    return round(premium, 4)


def _compute_adjusted_value(nft: dict, rarity_premium: float, liquidity_discount: float) -> float:
    floor = max(0.0, float(nft.get("floor_price_eth", 0.0)))
    adjusted = floor * (1.0 + rarity_premium / 100.0) * (1.0 - liquidity_discount / 100.0)
    return round(max(0.0, adjusted), 6)


def _compute_ltv(nft: dict, rarity_premium: float, liquidity_discount: float, config: dict) -> float:
    """
    Conservative LTV: starts at base_ltv, reduced by:
    - High liquidity discount (illiquid = riskier collateral)
    - Stale price
    - Low blue_chip_score
    """
    base_ltv = float(config.get("base_ltv_pct", 60.0))
    min_ltv = float(config.get("min_ltv_pct", 5.0))

    days_since_sale = float(nft.get("days_since_last_sale", 0))
    stale_threshold = float(config.get("stale_days_threshold", 30))
    blue_chip = _clamp(float(nft.get("blue_chip_score", 0)), 0.0, 100.0)

    # Penalties
    penalty = 0.0

    # Liquidity discount penalty: each % of discount → 0.5% LTV reduction
    penalty += liquidity_discount * 0.5

    # Stale price penalty
    if days_since_sale > stale_threshold:
        stale_ratio = _clamp((days_since_sale - stale_threshold) / stale_threshold, 0.0, 3.0)
        penalty += stale_ratio * 5.0

    # Blue chip bonus/penalty: score 0-100, 50 = neutral
    # below 50 → penalty, above 50 → bonus (capped at 10)
    bc_delta = (blue_chip - 50.0) / 100.0
    penalty -= bc_delta * 10.0  # negative penalty = bonus

    # Rarity can slightly improve LTV (rare NFTs have stronger collector bid)
    rarity_bonus = rarity_premium * 0.1
    penalty -= rarity_bonus

    ltv = _clamp(base_ltv - penalty, min_ltv, base_ltv)
    return round(ltv, 2)


def _compute_liquidation_risk(nft: dict, liquidity_discount: float, ltv: float, config: dict) -> float:
    """
    Liquidation risk 0-100:
    - High discount (illiquid) → harder to liquidate → higher risk
    - Low LTV already accounts for this, but risk is about speed of execution
    - Stale price → price uncertainty → risk
    - Low volume_7d → risk
    """
    volume_7d = max(0.0, float(nft.get("volume_7d_eth", 0.0)))
    days_since_sale = float(nft.get("days_since_last_sale", 0))
    blue_chip = _clamp(float(nft.get("blue_chip_score", 0)), 0.0, 100.0)
    stale_threshold = float(config.get("stale_days_threshold", 30))

    risk = 0.0

    # Liquidity discount component (0-40 → risk 0-40)
    risk += liquidity_discount

    # Low volume
    illiquid_threshold = float(config.get("illiquid_volume_threshold_eth", 1.0))
    if volume_7d < illiquid_threshold:
        risk += 20.0 * (1.0 - volume_7d / max(illiquid_threshold, 1e-9))

    # Stale price
    if days_since_sale > stale_threshold:
        risk += _clamp((days_since_sale / stale_threshold - 1.0) * 10.0, 0.0, 20.0)

    # Blue chip reduces risk
    risk -= blue_chip * 0.2

    risk = _clamp(risk, 0.0, 100.0)
    return round(risk, 2)


def _get_flags(nft: dict, ltv: float, config: dict) -> list:
    flags = []
    volume_7d = float(nft.get("volume_7d_eth", 0.0))
    rarity = float(nft.get("trait_rarity_score", 0))
    days_since_sale = float(nft.get("days_since_last_sale", 0))
    blue_chip = float(nft.get("blue_chip_score", 0))

    if volume_7d < float(config.get("illiquid_volume_threshold_eth", 1.0)):
        flags.append(FLAG_ILLIQUID)
    if rarity > float(config.get("rare_trait_threshold", 80)):
        flags.append(FLAG_RARE_TRAIT)
    if days_since_sale > float(config.get("stale_days_threshold", 30)):
        flags.append(FLAG_STALE_PRICE)
    if ltv < float(config.get("low_ltv_threshold_pct", 30.0)):
        flags.append(FLAG_LOW_LTV)
    if blue_chip > float(config.get("blue_chip_threshold", 75)):
        flags.append(FLAG_BLUE_CHIP)

    return flags


def _get_label(ltv: float, liq_risk: float, flags: list) -> str:
    if ltv >= 50 and liq_risk <= 20 and FLAG_ILLIQUID not in flags and FLAG_STALE_PRICE not in flags:
        return LABEL_EXCELLENT
    if ltv >= 40 and liq_risk <= 40 and FLAG_STALE_PRICE not in flags:
        return LABEL_GOOD
    if ltv >= 25 and liq_risk <= 60:
        return LABEL_ACCEPTABLE
    if ltv >= 10 and liq_risk <= 80:
        return LABEL_RISKY
    return LABEL_UNSUITABLE


def _value_single(nft: dict, config: dict) -> dict:
    rarity_premium = _compute_rarity_premium(nft, config)
    liquidity_discount = _compute_liquidity_discount(nft, config)
    adjusted_value = _compute_adjusted_value(nft, rarity_premium, liquidity_discount)
    ltv = _compute_ltv(nft, rarity_premium, liquidity_discount, config)
    liq_risk = _compute_liquidation_risk(nft, liquidity_discount, ltv, config)
    flags = _get_flags(nft, ltv, config)
    label = _get_label(ltv, liq_risk, flags)

    return {
        "collection_name": nft.get("collection_name", ""),
        "token_id": nft.get("token_id", ""),
        "floor_price_eth": float(nft.get("floor_price_eth", 0.0)),
        "rarity_premium_pct": rarity_premium,
        "liquidity_discount_pct": liquidity_discount,
        "adjusted_value_eth": adjusted_value,
        "ltv_recommended_pct": ltv,
        "liquidation_risk_score": liq_risk,
        "collateral_label": label,
        "flags": flags,
    }


def _atomic_log_write(entry: dict, log_path: str, cap: int) -> None:
    """Append entry to ring-buffer log JSON file atomically."""
    log_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    existing = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    if len(existing) > cap:
        existing = existing[-cap:]

    tmp_path = log_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp_path, log_path)


class DeFiNFTCollateralValuationModel:
    """
    Models NFT assets as collateral in DeFi lending protocols.
    Computes adjusted value, recommended LTV, liquidation risk,
    and collateral quality label per NFT.
    """

    def __init__(self, log_path: Optional[str] = None, log_cap: int = LOG_CAP):
        self._log_path = log_path or LOG_PATH
        self._log_cap = log_cap

    def value(self, nfts: list, config: Optional[dict] = None) -> dict:
        """
        Valuates a list of NFTs as DeFi collateral.

        Args:
            nfts: List of NFT dicts with keys:
                collection_name, token_id, floor_price_eth,
                trait_rarity_score (0-100), volume_7d_eth, volume_30d_eth,
                holder_count, listing_count, blue_chip_score (0-100),
                last_sale_price_eth, days_since_last_sale
            config: Optional config overrides.

        Returns:
            dict with per-NFT valuations and portfolio aggregates.
        """
        if config is None:
            config = {}
        cfg = {**DEFAULT_CONFIG, **config}

        if not nfts:
            return {
                "nfts": [],
                "aggregates": {
                    "total_portfolio_value_eth": 0.0,
                    "average_recommended_ltv": 0.0,
                    "excellent_count": 0,
                    "best_collateral": None,
                    "worst_collateral": None,
                    "nft_count": 0,
                },
                "timestamp": time.time(),
            }

        results = []
        for nft in nfts:
            r = _value_single(nft, cfg)
            results.append(r)

        # Aggregates
        total_value = sum(r["adjusted_value_eth"] for r in results)
        avg_ltv = sum(r["ltv_recommended_pct"] for r in results) / len(results)
        excellent_count = sum(1 for r in results if r["collateral_label"] == LABEL_EXCELLENT)

        # Best = highest LTV, least liquidation risk
        best = max(results, key=lambda r: (r["ltv_recommended_pct"], -r["liquidation_risk_score"]))
        worst = min(results, key=lambda r: (r["ltv_recommended_pct"], -r["liquidation_risk_score"]))

        output = {
            "nfts": results,
            "aggregates": {
                "total_portfolio_value_eth": round(total_value, 6),
                "average_recommended_ltv": round(avg_ltv, 4),
                "excellent_count": excellent_count,
                "best_collateral": {
                    "collection": best["collection_name"],
                    "token_id": best["token_id"],
                    "label": best["collateral_label"],
                    "ltv": best["ltv_recommended_pct"],
                },
                "worst_collateral": {
                    "collection": worst["collection_name"],
                    "token_id": worst["token_id"],
                    "label": worst["collateral_label"],
                    "ltv": worst["ltv_recommended_pct"],
                },
                "nft_count": len(results),
            },
            "timestamp": time.time(),
        }

        # Ring-buffer log (atomic write)
        try:
            _atomic_log_write(
                {
                    "timestamp": output["timestamp"],
                    "nft_count": len(results),
                    "total_portfolio_value_eth": output["aggregates"]["total_portfolio_value_eth"],
                    "average_recommended_ltv": output["aggregates"]["average_recommended_ltv"],
                    "excellent_count": excellent_count,
                },
                self._log_path,
                self._log_cap,
            )
        except OSError:
            pass  # Never crash analytics

        return output

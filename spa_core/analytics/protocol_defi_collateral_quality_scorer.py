"""
MP-1003: ProtocolDeFiCollateralQualityScorer
Scores quality of collateral assets in DeFi lending protocols.
Pure stdlib, read-only analytics, atomic ring-buffer log.
"""

import json
import os
import time
from typing import Any, Dict, List


class ProtocolDeFiCollateralQualityScorer:
    """
    Scores the quality of collateral assets in DeFi lending protocols.
    """

    LOG_FILE = "data/collateral_quality_log.json"
    LOG_CAP = 100

    # Quality labels
    PRISTINE_COLLATERAL = "PRISTINE_COLLATERAL"
    HIGH_QUALITY = "HIGH_QUALITY"
    STANDARD = "STANDARD"
    RISKY = "RISKY"
    UNACCEPTABLE = "UNACCEPTABLE"

    # Flags
    FLAG_ORACLE_MANIPULATION_HISTORY = "ORACLE_MANIPULATION_HISTORY"
    FLAG_LOW_LIQUIDITY_DEPTH = "LOW_LIQUIDITY_DEPTH"
    FLAG_HIGH_COMPOSABILITY_RISK = "HIGH_COMPOSABILITY_RISK"
    FLAG_REGULATORY_UNCERTAINTY = "REGULATORY_UNCERTAINTY"
    FLAG_LIQUID_STAKING_DISCOUNT = "LIQUID_STAKING_DISCOUNT"
    FLAG_PRISTINE_ORACLE = "PRISTINE_ORACLE"

    def score(
        self,
        collateral_assets: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Scores collateral assets in DeFi lending protocols.

        Args:
            collateral_assets: List of asset dicts with quality metrics.
            config: Configuration dict (optional overrides).

        Returns:
            dict with per-asset scoring and aggregates.
        """
        if not collateral_assets:
            return {
                "results": [],
                "aggregates": {
                    "highest_quality": None,
                    "lowest_quality": None,
                    "avg_quality_score": 0.0,
                    "pristine_count": 0,
                    "unacceptable_count": 0,
                    "total_assets": 0,
                },
                "meta": {
                    "scorer": "ProtocolDeFiCollateralQualityScorer",
                    "version": "1.0.0",
                },
            }

        results = []
        for asset in collateral_assets:
            result = self._score_asset(asset, config)
            results.append(result)

        aggregates = self._compute_aggregates(results)

        output = {
            "results": results,
            "aggregates": aggregates,
            "meta": {
                "scorer": "ProtocolDeFiCollateralQualityScorer",
                "version": "1.0.0",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        self._write_log(output)
        return output

    # ------------------------------------------------------------------
    # Per-asset scoring
    # ------------------------------------------------------------------

    def _score_asset(
        self, asset: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        name = asset.get("name", "unknown")
        asset_type = asset.get("asset_type", "defi_token")
        market_cap_usd = float(asset.get("market_cap_usd", 0))
        daily_volume_usd = float(asset.get("daily_volume_usd", 0))
        price_volatility_30d_pct = float(asset.get("price_volatility_30d_pct", 0))
        max_drawdown_90d_pct = float(asset.get("max_drawdown_90d_pct", 0))
        oracle_count = int(asset.get("oracle_count", 1))
        oracle_manipulation_incidents = int(asset.get("oracle_manipulation_incidents", 0))
        correlation_with_eth = float(asset.get("correlation_with_eth", 0.5))
        is_liquid_staking = bool(asset.get("is_liquid_staking", False))
        underlying_collateral_ratio_pct = float(
            asset.get("underlying_collateral_ratio_pct", 100.0)
        )
        defi_dependency_count = int(asset.get("defi_dependency_count", 0))
        regulatory_classification = asset.get("regulatory_classification", "undefined")
        liquidity_depth_1pct_usd = float(asset.get("liquidity_depth_1pct_usd", 0))

        # Component scores
        liquidity_score = self._compute_liquidity_score(
            market_cap_usd, daily_volume_usd, liquidity_depth_1pct_usd
        )
        volatility_score = self._compute_volatility_score(
            price_volatility_30d_pct, max_drawdown_90d_pct
        )
        oracle_reliability_score = self._compute_oracle_score(
            oracle_count, oracle_manipulation_incidents
        )
        composability_risk_score = self._compute_composability_score(
            defi_dependency_count
        )

        # Overall quality:
        # 40% liquidity + 25% volatility + 20% oracle + 15% (100 - composability_risk)
        overall_quality_score = (
            0.40 * liquidity_score
            + 0.25 * volatility_score
            + 0.20 * oracle_reliability_score
            + 0.15 * (100.0 - composability_risk_score)
        )
        overall_quality_score = max(0.0, min(100.0, overall_quality_score))

        # Quality label
        quality_label = self._compute_quality_label(
            overall_quality_score,
            oracle_reliability_score,
            oracle_manipulation_incidents,
            defi_dependency_count,
        )

        # Flags
        flags = self._compute_flags(
            oracle_manipulation_incidents,
            liquidity_depth_1pct_usd,
            defi_dependency_count,
            regulatory_classification,
            market_cap_usd,
            is_liquid_staking,
            underlying_collateral_ratio_pct,
            oracle_count,
        )

        return {
            "name": name,
            "asset_type": asset_type,
            "market_cap_usd": market_cap_usd,
            "daily_volume_usd": daily_volume_usd,
            "price_volatility_30d_pct": price_volatility_30d_pct,
            "max_drawdown_90d_pct": max_drawdown_90d_pct,
            "oracle_count": oracle_count,
            "oracle_manipulation_incidents": oracle_manipulation_incidents,
            "correlation_with_eth": correlation_with_eth,
            "is_liquid_staking": is_liquid_staking,
            "underlying_collateral_ratio_pct": underlying_collateral_ratio_pct,
            "defi_dependency_count": defi_dependency_count,
            "regulatory_classification": regulatory_classification,
            "liquidity_depth_1pct_usd": liquidity_depth_1pct_usd,
            "liquidity_score": round(liquidity_score, 2),
            "volatility_score": round(volatility_score, 2),
            "oracle_reliability_score": round(oracle_reliability_score, 2),
            "composability_risk_score": round(composability_risk_score, 2),
            "overall_quality_score": round(overall_quality_score, 2),
            "quality_label": quality_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Component score helpers
    # ------------------------------------------------------------------

    def _compute_liquidity_score(
        self,
        market_cap_usd: float,
        daily_volume_usd: float,
        liquidity_depth_1pct_usd: float,
    ) -> float:
        """
        Liquidity score 0-100.
        60% from depth_ratio (depth / market_cap), 40% from volume_ratio.
        """
        if market_cap_usd <= 0:
            return 0.0

        # depth_ratio: 10% depth/market_cap ≈ score 100
        depth_ratio = liquidity_depth_1pct_usd / market_cap_usd
        depth_component = min(100.0, depth_ratio * 1000.0)

        # volume_ratio: 20% daily turnover ≈ score 100
        volume_ratio = daily_volume_usd / market_cap_usd
        volume_component = min(100.0, volume_ratio * 500.0)

        return depth_component * 0.6 + volume_component * 0.4

    def _compute_volatility_score(
        self,
        price_volatility_30d_pct: float,
        max_drawdown_90d_pct: float,
    ) -> float:
        """
        Volatility score 0-100 (inverted — low vol = high score).
        60% from price_volatility, 40% from max_drawdown.
        """
        vol_score = max(0.0, 100.0 - price_volatility_30d_pct * 2.0)
        dd_score = max(0.0, 100.0 - max_drawdown_90d_pct * 2.0)
        return vol_score * 0.6 + dd_score * 0.4

    def _compute_oracle_score(
        self, oracle_count: int, incidents: int
    ) -> float:
        """Oracle reliability score 0-100: oracle_count×25 − incidents×10."""
        base = min(100.0, oracle_count * 25.0)
        penalty = incidents * 10.0
        return max(0.0, base - penalty)

    def _compute_composability_score(self, defi_dependency_count: int) -> float:
        """Composability risk score 0-100: dependency_count × 10, cap 100."""
        return min(100.0, defi_dependency_count * 10.0)

    # ------------------------------------------------------------------
    # Label / flag helpers
    # ------------------------------------------------------------------

    def _compute_quality_label(
        self,
        overall_quality_score: float,
        oracle_reliability_score: float,
        oracle_manipulation_incidents: int,
        defi_dependency_count: int,
    ) -> str:
        # UNACCEPTABLE: score < 40 OR oracle_incidents > 2 OR defi_deps > 5
        if (
            overall_quality_score < 40
            or oracle_manipulation_incidents > 2
            or defi_dependency_count > 5
        ):
            return self.UNACCEPTABLE

        # PRISTINE_COLLATERAL: score > 85 AND oracle_score > 80
        if overall_quality_score > 85 and oracle_reliability_score > 80:
            return self.PRISTINE_COLLATERAL

        if overall_quality_score > 70:
            return self.HIGH_QUALITY

        if overall_quality_score > 55:
            return self.STANDARD

        if overall_quality_score > 40:
            return self.RISKY

        return self.UNACCEPTABLE

    def _compute_flags(
        self,
        oracle_manipulation_incidents: int,
        liquidity_depth_1pct_usd: float,
        defi_dependency_count: int,
        regulatory_classification: str,
        market_cap_usd: float,
        is_liquid_staking: bool,
        underlying_collateral_ratio_pct: float,
        oracle_count: int,
    ) -> List[str]:
        flags: List[str] = []

        if oracle_manipulation_incidents > 0:
            flags.append(self.FLAG_ORACLE_MANIPULATION_HISTORY)

        if liquidity_depth_1pct_usd < 1_000_000:
            flags.append(self.FLAG_LOW_LIQUIDITY_DEPTH)

        if defi_dependency_count > 4:
            flags.append(self.FLAG_HIGH_COMPOSABILITY_RISK)

        if regulatory_classification == "undefined" and market_cap_usd > 100_000_000:
            flags.append(self.FLAG_REGULATORY_UNCERTAINTY)

        if is_liquid_staking and underlying_collateral_ratio_pct < 99.0:
            flags.append(self.FLAG_LIQUID_STAKING_DISCOUNT)

        if oracle_count >= 3 and oracle_manipulation_incidents == 0:
            flags.append(self.FLAG_PRISTINE_ORACLE)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(
        self, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not results:
            return {
                "highest_quality": None,
                "lowest_quality": None,
                "avg_quality_score": 0.0,
                "pristine_count": 0,
                "unacceptable_count": 0,
                "total_assets": 0,
            }

        sorted_by_score = sorted(
            results, key=lambda r: r["overall_quality_score"], reverse=True
        )
        highest_quality = sorted_by_score[0]["name"]
        lowest_quality = sorted_by_score[-1]["name"]

        avg_quality_score = (
            sum(r["overall_quality_score"] for r in results) / len(results)
        )

        pristine_count = sum(
            1 for r in results if r["quality_label"] == self.PRISTINE_COLLATERAL
        )
        unacceptable_count = sum(
            1 for r in results if r["quality_label"] == self.UNACCEPTABLE
        )

        return {
            "highest_quality": highest_quality,
            "lowest_quality": lowest_quality,
            "avg_quality_score": round(avg_quality_score, 2),
            "pristine_count": pristine_count,
            "unacceptable_count": unacceptable_count,
            "total_assets": len(results),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _write_log(self, output: Dict[str, Any]) -> None:
        """Atomic ring-buffer write to collateral_quality_log.json (cap 100)."""
        log_path = self.LOG_FILE
        dir_name = os.path.dirname(log_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        existing: List[Dict[str, Any]] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []

        entry = {
            "timestamp": output["meta"].get("timestamp", ""),
            "total_assets": output["aggregates"]["total_assets"],
            "avg_quality_score": output["aggregates"]["avg_quality_score"],
            "pristine_count": output["aggregates"]["pristine_count"],
            "unacceptable_count": output["aggregates"]["unacceptable_count"],
        }
        existing.append(entry)

        if len(existing) > self.LOG_CAP:
            existing = existing[-self.LOG_CAP :]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp_path, log_path)

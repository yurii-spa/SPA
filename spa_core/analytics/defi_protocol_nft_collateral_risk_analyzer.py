"""
MP-1016: DeFiProtocolNFTCollateralRiskAnalyzer
Advisory read-only module — stdlib-only, atomic log writes.
Evaluates risks of using NFTs as collateral in DeFi protocols.
"""

import json
import os
from typing import List, Dict, Any, Optional
from spa_core.utils.atomic import atomic_save
from spa_core.utils import clock

_DEFAULT_CONFIG: Dict[str, Any] = {
    "ring_buffer_cap": 100,
    "log_file": "data/nft_collateral_risk_log.json",
    "low_risk_threshold": 30.0,
    "moderate_risk_threshold": 60.0,
    "liquidation_imminent_buffer": 10.0,
    "near_liquidation_buffer": 15.0,
    "high_risk_ltv": 70.0,
    "high_ltv_nft_threshold": 60.0,
    "high_risk_volatility": 30.0,
    "wash_suspected_threshold": 60.0,
    "low_liquidity_volume_threshold": 10.0,
    "fortress_ltv_threshold": 30.0,
}

# Oracle type → risk score (0-100). Higher = riskier.
ORACLE_RISK_MAP: Dict[str, float] = {
    "floor_price": 80.0,
    "twap_floor": 40.0,
    "appraisal": 20.0,
    "chainlink": 10.0,
}


class DeFiProtocolNFTCollateralRiskAnalyzer:
    """
    Evaluates per-position and aggregate NFT collateral risk in DeFi lending.

    Each position represents an NFT used as collateral for a DeFi loan.
    The analyzer computes liquidation metrics, liquidity risk, oracle risk, and
    a composite NFT risk score, then assigns a risk label and flags.

    Input position fields:
        name (str): Position identifier
        collection (str): NFT collection name
        floor_price_eth (float): Current floor price in ETH
        loan_to_value_pct (float): Current LTV %
        loan_amount_eth (float): Outstanding loan in ETH
        liquidation_threshold_pct (float): LTV % at which liquidation triggers
        collection_volume_30d_eth (float): 30-day trading volume in ETH
        collection_listings_count (float): Active listings (supply on market)
        days_to_maturity (float): Days until loan matures (0 = open-ended)
        oracle_type (str): floor_price | twap_floor | appraisal | chainlink
        floor_price_volatility_30d_pct (float): 30-day floor price volatility %
        blue_chip_collection (bool): True for BAYC/CryptoPunks/Azuki etc.
        wash_trading_score (float): 0-100; higher = more suspected manipulation
        royalty_enforced (bool): Whether royalties are contract-enforced

    Output per position:
        liquidation_buffer_pct: liquidation_threshold - current_ltv
        floor_drop_to_liquidation_pct: % floor drop that triggers liquidation
        liquidity_risk_score (0-100)
        oracle_risk_score (0-100)
        composite_nft_risk_score (0-100): weighted risk score
        risk_label: NFT_FORTRESS | LOW_RISK | MODERATE_RISK | HIGH_RISK | LIQUIDATION_IMMINENT
        flags: list of active flag strings
    """

    NAME = "DeFiProtocolNFTCollateralRiskAnalyzer"
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self.name = self.NAME
        self.version = self.VERSION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        nft_positions: List[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze NFT collateral positions.

        Args:
            nft_positions: List of position dicts (see class docstring).
            config: Optional config overrides (merged over _DEFAULT_CONFIG).

        Returns:
            Result dict with keys: analyzer, version, timestamp,
            position_count, positions, aggregates.
        """
        cfg: Dict[str, Any] = {**_DEFAULT_CONFIG, **(config or {})}

        if not nft_positions:
            return self._empty_result(cfg)

        results = [self._analyze_position(pos, cfg) for pos in nft_positions]

        composites = [r["composite_nft_risk_score"] for r in results]
        avg_composite = sum(composites) / len(composites)
        imminent_count = sum(1 for r in results if r["risk_label"] == "LIQUIDATION_IMMINENT")
        fortress_count = sum(1 for r in results if r["risk_label"] == "NFT_FORTRESS")
        safest = min(results, key=lambda x: x["composite_nft_risk_score"])
        riskiest = max(results, key=lambda x: x["composite_nft_risk_score"])

        output: Dict[str, Any] = {
            "analyzer": self.name,
            "version": self.version,
            "timestamp": clock.utcnow().isoformat(),
            "position_count": len(results),
            "positions": results,
            "aggregates": {
                "safest": safest["name"],
                "riskiest": riskiest["name"],
                "avg_composite_risk": round(avg_composite, 4),
                "imminent_liquidation_count": imminent_count,
                "fortress_count": fortress_count,
            },
        }

        self._append_log(output, cfg)
        return output

    # ------------------------------------------------------------------
    # Per-position logic
    # ------------------------------------------------------------------

    def _analyze_position(
        self, pos: Dict[str, Any], cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        name = str(pos.get("name", "UNKNOWN"))
        collection = str(pos.get("collection", "UNKNOWN"))
        floor_price_eth = float(pos.get("floor_price_eth", 0.0))
        ltv = float(pos.get("loan_to_value_pct", 0.0))
        loan_amount_eth = float(pos.get("loan_amount_eth", 0.0))
        threshold = float(pos.get("liquidation_threshold_pct", 80.0))
        volume_30d = float(pos.get("collection_volume_30d_eth", 0.0))
        listings = float(pos.get("collection_listings_count", 0.0))
        days_to_maturity = float(pos.get("days_to_maturity", 0.0))
        oracle_type = str(pos.get("oracle_type", "floor_price"))
        floor_volatility = float(pos.get("floor_price_volatility_30d_pct", 0.0))
        blue_chip = bool(pos.get("blue_chip_collection", False))
        wash_score = float(pos.get("wash_trading_score", 0.0))
        royalty_enforced = bool(pos.get("royalty_enforced", False))

        # Core computed metrics
        liquidation_buffer_pct = threshold - ltv
        floor_drop_to_liq_pct = (
            (threshold - ltv) / threshold * 100.0 if threshold > 0 else 0.0
        )
        liquidity_risk = self._calc_liquidity_risk(volume_30d, listings, wash_score)
        oracle_risk = ORACLE_RISK_MAP.get(oracle_type, 80.0)

        # Composite: invert buffer → risk direction, clamp to [0,100]
        buffer_risk = max(0.0, min(100.0, 100.0 - liquidation_buffer_pct))
        composite = (
            buffer_risk * 0.30
            + floor_volatility * 0.25
            + liquidity_risk * 0.25
            + oracle_risk * 0.20
        )
        composite = max(0.0, min(100.0, composite))

        risk_label = self._assign_label(
            ltv, liquidation_buffer_pct, floor_volatility, blue_chip, oracle_type, composite, cfg
        )

        flags: List[str] = []
        if liquidation_buffer_pct < cfg["near_liquidation_buffer"]:
            flags.append("NEAR_LIQUIDATION")
        if oracle_type == "floor_price":
            flags.append("FLOOR_PRICE_ORACLE")
        if ltv > cfg["high_ltv_nft_threshold"]:
            flags.append("HIGH_LTV_NFT")
        if blue_chip:
            flags.append("BLUE_CHIP_PREMIUM")
        if wash_score > cfg["wash_suspected_threshold"]:
            flags.append("WASH_TRADING_SUSPECTED")
        if volume_30d < cfg["low_liquidity_volume_threshold"]:
            flags.append("LOW_LIQUIDITY_COLLECTION")

        return {
            "name": name,
            "collection": collection,
            "floor_price_eth": floor_price_eth,
            "loan_to_value_pct": ltv,
            "loan_amount_eth": loan_amount_eth,
            "liquidation_threshold_pct": threshold,
            "days_to_maturity": days_to_maturity,
            "oracle_type": oracle_type,
            "floor_price_volatility_30d_pct": floor_volatility,
            "blue_chip_collection": blue_chip,
            "wash_trading_score": wash_score,
            "royalty_enforced": royalty_enforced,
            "liquidation_buffer_pct": round(liquidation_buffer_pct, 4),
            "floor_drop_to_liquidation_pct": round(floor_drop_to_liq_pct, 4),
            "liquidity_risk_score": round(liquidity_risk, 4),
            "oracle_risk_score": oracle_risk,
            "composite_nft_risk_score": round(composite, 4),
            "risk_label": risk_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------

    def _calc_liquidity_risk(
        self, volume_30d: float, listings: float, wash_score: float
    ) -> float:
        """
        Liquidity risk score 0-100.
        Components:
          - volume_risk: low volume → high risk (caps at 20 ETH for 0 risk)
          - listings_risk: many listings → supply overhang (caps at 1000 = 100)
          - wash_component: wash_trading_score passed through

        Weights: volume 40 %, listings 30 %, wash 30 %.
        """
        volume_risk = max(0.0, min(100.0, 100.0 - volume_30d * 5.0))
        listings_risk = min(100.0, listings / 10.0)
        wash_component = max(0.0, min(100.0, wash_score))
        return volume_risk * 0.40 + listings_risk * 0.30 + wash_component * 0.30

    def _assign_label(
        self,
        ltv: float,
        buffer: float,
        volatility: float,
        blue_chip: bool,
        oracle: str,
        composite: float,
        cfg: Dict[str, Any],
    ) -> str:
        """Priority order (most dangerous first)."""
        if buffer < cfg["liquidation_imminent_buffer"]:
            return "LIQUIDATION_IMMINENT"
        if ltv > cfg["high_risk_ltv"] or volatility > cfg["high_risk_volatility"]:
            return "HIGH_RISK"
        if blue_chip and ltv < cfg["fortress_ltv_threshold"] and oracle == "twap_floor":
            return "NFT_FORTRESS"
        if composite < cfg["low_risk_threshold"]:
            return "LOW_RISK"
        if composite < cfg["moderate_risk_threshold"]:
            return "MODERATE_RISK"
        return "HIGH_RISK"

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _empty_result(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analyzer": self.name,
            "version": self.version,
            "timestamp": clock.utcnow().isoformat(),
            "position_count": 0,
            "positions": [],
            "aggregates": {
                "safest": None,
                "riskiest": None,
                "avg_composite_risk": 0.0,
                "imminent_liquidation_count": 0,
                "fortress_count": 0,
            },
        }

    def _append_log(self, output: Dict[str, Any], cfg: Dict[str, Any]) -> None:
        """Atomically append a summary entry to the ring-buffer log (cap 100)."""
        log_file: str = str(cfg.get("log_file", "data/nft_collateral_risk_log.json"))
        cap: int = int(cfg.get("ring_buffer_cap", 100))

        try:
            if os.path.exists(log_file):
                with open(log_file, "r") as fh:
                    existing = json.load(fh)
                log: List[Dict] = existing if isinstance(existing, list) else []
            else:
                log = []
        except Exception:
            log = []

        log.append(
            {
                "timestamp": output["timestamp"],
                "position_count": output["position_count"],
                "aggregates": output["aggregates"],
            }
        )
        log = log[-cap:]

        dir_name = os.path.dirname(log_file)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        write_dir = dir_name if dir_name else "."
        atomic_save(log, str(log_file))

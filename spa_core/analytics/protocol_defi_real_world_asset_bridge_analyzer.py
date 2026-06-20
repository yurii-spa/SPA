"""
MP-1017: ProtocolDeFiRealWorldAssetBridgeAnalyzer
Advisory read-only module — stdlib-only, atomic log writes.
Analyzes RWA tokenization protocols and quality of the DeFi bridge to on-chain assets.
"""

import json
import os
import datetime
from typing import List, Dict, Any, Optional
from spa_core.utils.atomic import atomic_save

_DEFAULT_CONFIG: Dict[str, Any] = {
    "ring_buffer_cap": 100,
    "log_file": "data/rwa_bridge_quality_log.json",
    "tbill_benchmark_pct": 5.25,
    "yield_premium_positive_threshold": 1.0,
    "institutional_accessible_min_usd": 100_000.0,
    "institutional_grade_score_threshold": 80.0,
    "high_quality_score_threshold": 65.0,
    "standard_score_threshold": 40.0,
    "below_standard_score_threshold": 20.0,
    "high_risk_score_threshold": 40.0,
}

# redemption_mechanism → redemption risk score (0-100). Higher = harder to exit.
REDEMPTION_RISK_MAP: Dict[str, float] = {
    "daily": 10.0,
    "t+1": 15.0,
    "t+3": 25.0,
    "weekly": 40.0,
    "monthly": 60.0,
    "quarterly": 80.0,
}

# on_chain_audit_frequency → transparency score (0-100). Higher = more transparent.
TRANSPARENCY_MAP: Dict[str, float] = {
    "realtime": 100.0,
    "daily": 80.0,
    "weekly": 50.0,
    "monthly": 20.0,
}

# on_chain_audit_frequency → audit risk component (0-100). Used in custody_risk calc.
AUDIT_RISK_MAP: Dict[str, float] = {
    "realtime": 0.0,
    "daily": 20.0,
    "weekly": 50.0,
    "monthly": 80.0,
}


class ProtocolDeFiRealWorldAssetBridgeAnalyzer:
    """
    Analyzes RWA tokenization protocols and quality of the on-chain bridge.

    Each protocol entry describes a real-world asset (e.g. US Treasuries,
    corporate bonds, real estate) that has been tokenized and made accessible
    on-chain. The analyzer scores custodian safety, on-chain transparency,
    redemption risk, and computes an overall bridge quality score.

    Input protocol fields:
        name (str): Protocol identifier
        rwa_category (str): us_treasuries | corporate_bonds | real_estate |
            trade_finance | private_credit | commodities
        total_tvl_usd (float): Total value locked in USD
        underlying_yield_pct (float): Gross yield from underlying asset %
        protocol_fee_pct (float): Protocol fee %
        net_yield_pct (float): Net yield after fees %
        custodian_name (str): Name of off-chain custodian
        custodian_regulated (bool): Whether custodian is regulated
        redemption_mechanism (str): daily | t+1 | t+3 | weekly | monthly | quarterly
        on_chain_audit_frequency (str): realtime | daily | weekly | monthly
        legal_wrapper (str): spv | trust | fund | direct
        jurisdiction (str): us | cayman | luxembourg | bermuda | other
        kyc_required (bool): KYC required to participate
        min_investment_usd (float): Minimum investment in USD
        secondary_market_liquidity_score (float): 0-100 secondary market liquidity
        counterparty_default_risk_score (float): 0-100 counterparty default risk

    Output per protocol:
        redemption_risk_score (0-100): How hard/slow to exit
        custody_risk_score (0-100): Custodian + audit risk
        on_chain_transparency_score (0-100): How verifiable on-chain
        yield_premium_over_tbill_pct: net_yield - 5.25% T-bill benchmark
        overall_bridge_quality_score (0-100): Weighted composite quality score
        quality_label: INSTITUTIONAL_GRADE | HIGH_QUALITY | STANDARD |
            BELOW_STANDARD | HIGH_RISK_RWA
        flags: list of active flag strings
    """

    NAME = "ProtocolDeFiRealWorldAssetBridgeAnalyzer"
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self.name = self.NAME
        self.version = self.VERSION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        rwa_protocols: List[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze RWA bridge protocols.

        Args:
            rwa_protocols: List of protocol dicts (see class docstring).
            config: Optional config overrides.

        Returns:
            Result dict with keys: analyzer, version, timestamp,
            protocol_count, protocols, aggregates.
        """
        cfg: Dict[str, Any] = {**_DEFAULT_CONFIG, **(config or {})}

        if not rwa_protocols:
            return self._empty_result(cfg)

        results = [self._analyze_protocol(proto, cfg) for proto in rwa_protocols]

        scores = [r["overall_bridge_quality_score"] for r in results]
        avg_quality = sum(scores) / len(scores)
        institutional_count = sum(
            1 for r in results if r["quality_label"] == "INSTITUTIONAL_GRADE"
        )
        total_tvl = sum(r["total_tvl_usd"] for r in results)
        highest = max(results, key=lambda x: x["overall_bridge_quality_score"])
        lowest = min(results, key=lambda x: x["overall_bridge_quality_score"])

        output: Dict[str, Any] = {
            "analyzer": self.name,
            "version": self.version,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "protocol_count": len(results),
            "protocols": results,
            "aggregates": {
                "highest_quality": highest["name"],
                "lowest_quality": lowest["name"],
                "avg_bridge_quality": round(avg_quality, 4),
                "institutional_grade_count": institutional_count,
                "total_rwa_tvl_usd": round(total_tvl, 2),
            },
        }

        self._append_log(output, cfg)
        return output

    # ------------------------------------------------------------------
    # Per-protocol logic
    # ------------------------------------------------------------------

    def _analyze_protocol(
        self, proto: Dict[str, Any], cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        name = str(proto.get("name", "UNKNOWN"))
        rwa_category = str(proto.get("rwa_category", "unknown"))
        total_tvl_usd = float(proto.get("total_tvl_usd", 0.0))
        underlying_yield_pct = float(proto.get("underlying_yield_pct", 0.0))
        protocol_fee_pct = float(proto.get("protocol_fee_pct", 0.0))
        # net_yield_pct may be provided explicitly; fall back to computation
        net_yield_pct = float(
            proto.get("net_yield_pct", underlying_yield_pct - protocol_fee_pct)
        )
        custodian_name = str(proto.get("custodian_name", "UNKNOWN"))
        custodian_regulated = bool(proto.get("custodian_regulated", False))
        redemption_mechanism = str(proto.get("redemption_mechanism", "monthly"))
        on_chain_audit_frequency = str(proto.get("on_chain_audit_frequency", "monthly"))
        legal_wrapper = str(proto.get("legal_wrapper", "other"))
        jurisdiction = str(proto.get("jurisdiction", "other"))
        kyc_required = bool(proto.get("kyc_required", False))
        min_investment_usd = float(proto.get("min_investment_usd", 0.0))
        liquidity_score = float(proto.get("secondary_market_liquidity_score", 0.0))
        counterparty_risk = float(proto.get("counterparty_default_risk_score", 50.0))

        # Computed metrics
        redemption_risk = REDEMPTION_RISK_MAP.get(redemption_mechanism, 60.0)
        transparency_score = TRANSPARENCY_MAP.get(on_chain_audit_frequency, 20.0)
        custody_risk = self._calc_custody_risk(custodian_regulated, on_chain_audit_frequency)
        yield_premium = net_yield_pct - float(cfg["tbill_benchmark_pct"])

        # Overall bridge quality score (0-100, higher = better quality)
        # Uses inverted risk scores for custody and counterparty
        quality_score = (
            transparency_score * 0.30
            + (100.0 - custody_risk) * 0.30
            + liquidity_score * 0.20
            + (100.0 - counterparty_risk) * 0.20
        )
        quality_score = max(0.0, min(100.0, quality_score))

        quality_label = self._assign_quality_label(
            quality_score, custodian_regulated, redemption_mechanism, cfg
        )

        flags: List[str] = []
        if redemption_mechanism == "daily":
            flags.append("DAILY_REDEMPTION")
        if not custodian_regulated:
            flags.append("UNREGULATED_CUSTODIAN")
        if on_chain_audit_frequency in ("monthly", "quarterly"):
            flags.append("OPAQUE_REPORTING")
        if yield_premium > float(cfg["yield_premium_positive_threshold"]):
            flags.append("YIELD_PREMIUM_POSITIVE")
        if kyc_required:
            flags.append("KYC_BARRIER")
        if min_investment_usd < float(cfg["institutional_accessible_min_usd"]):
            flags.append("INSTITUTIONAL_ACCESSIBLE")

        return {
            "name": name,
            "rwa_category": rwa_category,
            "total_tvl_usd": total_tvl_usd,
            "underlying_yield_pct": underlying_yield_pct,
            "protocol_fee_pct": protocol_fee_pct,
            "net_yield_pct": net_yield_pct,
            "custodian_name": custodian_name,
            "custodian_regulated": custodian_regulated,
            "redemption_mechanism": redemption_mechanism,
            "on_chain_audit_frequency": on_chain_audit_frequency,
            "legal_wrapper": legal_wrapper,
            "jurisdiction": jurisdiction,
            "kyc_required": kyc_required,
            "min_investment_usd": min_investment_usd,
            "secondary_market_liquidity_score": liquidity_score,
            "counterparty_default_risk_score": counterparty_risk,
            "redemption_risk_score": redemption_risk,
            "custody_risk_score": round(custody_risk, 4),
            "on_chain_transparency_score": transparency_score,
            "yield_premium_over_tbill_pct": round(yield_premium, 4),
            "overall_bridge_quality_score": round(quality_score, 4),
            "quality_label": quality_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------

    def _calc_custody_risk(self, regulated: bool, audit_freq: str) -> float:
        """
        Custody risk score 0-100. Higher = riskier.
        Components:
          - regulation_risk: unregulated adds 50 points
          - audit_risk: realtime=0, daily=20, weekly=50, monthly=80
        Weighted 50/50, capped at 100.
        """
        audit_risk = AUDIT_RISK_MAP.get(audit_freq, 80.0)
        regulation_risk = 0.0 if regulated else 50.0
        return min(100.0, audit_risk * 0.50 + regulation_risk)

    def _assign_quality_label(
        self,
        score: float,
        regulated: bool,
        redemption: str,
        cfg: Dict[str, Any],
    ) -> str:
        """
        Priority order:
        1. INSTITUTIONAL_GRADE: score>80 AND regulated AND daily redemption
        2. HIGH_RISK_RWA: unregulated OR (quarterly + score<40)
        3. HIGH_QUALITY: score>65
        4. STANDARD: score>40
        5. BELOW_STANDARD: score>20
        6. HIGH_RISK_RWA (fallback)
        """
        if (
            score > float(cfg["institutional_grade_score_threshold"])
            and regulated
            and redemption == "daily"
        ):
            return "INSTITUTIONAL_GRADE"
        if not regulated or (
            redemption == "quarterly"
            and score < float(cfg["high_risk_score_threshold"])
        ):
            return "HIGH_RISK_RWA"
        if score > float(cfg["high_quality_score_threshold"]):
            return "HIGH_QUALITY"
        if score > float(cfg["standard_score_threshold"]):
            return "STANDARD"
        if score > float(cfg["below_standard_score_threshold"]):
            return "BELOW_STANDARD"
        return "HIGH_RISK_RWA"

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _empty_result(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analyzer": self.name,
            "version": self.version,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "protocol_count": 0,
            "protocols": [],
            "aggregates": {
                "highest_quality": None,
                "lowest_quality": None,
                "avg_bridge_quality": 0.0,
                "institutional_grade_count": 0,
                "total_rwa_tvl_usd": 0.0,
            },
        }

    def _append_log(self, output: Dict[str, Any], cfg: Dict[str, Any]) -> None:
        """Atomically append a summary entry to the ring-buffer log (cap 100)."""
        log_file: str = str(cfg.get("log_file", "data/rwa_bridge_quality_log.json"))
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
                "protocol_count": output["protocol_count"],
                "aggregates": output["aggregates"],
            }
        )
        log = log[-cap:]

        dir_name = os.path.dirname(log_file)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        write_dir = dir_name if dir_name else "."
        atomic_save(log, str(log_file))

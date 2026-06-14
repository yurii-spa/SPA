"""
MP-1028: DeFiProtocolSystemicRiskContagionModeler

Models systemic risk and cascade contagion potential in DeFi ecosystems.
Read-only analytics module. Writes ring-buffer log to
data/systemic_risk_contagion_log.json (cap 100, atomic write).

stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

LOG_CAP = 100
_LOG_FILENAME = "systemic_risk_contagion_log.json"

VALID_LABELS = frozenset({
    "SYSTEMIC_CORNERSTONE",
    "HIGH_SYSTEMIC",
    "MODERATE_SYSTEMIC",
    "LOW_SYSTEMIC",
    "ISOLATED",
})

VALID_FLAGS = frozenset({
    "COLLATERAL_CONTAGION_RISK",
    "ORACLE_SINGLE_SOURCE",
    "HISTORICALLY_CONTAGIOUS",
    "INSURANCE_BUFFERED",
    "LIQUIDITY_CLIFF",
    "TOO_BIG_TO_FAIL",
})


class DeFiProtocolSystemicRiskContagionModeler:
    """
    Models systemic risk and contagion cascade potential for DeFi protocols.

    Each protocol dict keys:
        name                       str
        tvl_usd                    float
        interconnection_score      float  0-100
        debt_exposure_usd          float
        collateral_accepted        list[str]
        tokens_issued              list[str]
        historical_contagion_events int
        oracle_dependencies        list[str]
        liquidity_in_crisis_pct    float  0-100
        insurance_coverage_usd     float
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def model(self, protocols: list, config: dict) -> dict:
        """
        Model systemic risk for a list of DeFi protocols.

        Args:
            protocols: list[dict] — each dict describes one protocol.
            config:    dict — optional overrides:
                         log_enabled (bool, default True)
                         data_dir    (str, overrides self.data_dir)

        Returns:
            dict with keys: timestamp, module, mp,
                            protocol_count, protocols, aggregates
        """
        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        data_dir = config.get("data_dir", self.data_dir)
        log_enabled = config.get("log_enabled", True)

        results = [self._analyze_protocol(p) for p in protocols]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "DeFiProtocolSystemicRiskContagionModeler",
            "mp": "MP-1028",
            "protocol_count": len(results),
            "protocols": results,
            "aggregates": aggregates,
        }

        if log_enabled:
            self._append_log(output, data_dir)

        return output

    # ------------------------------------------------------------------
    # Per-protocol analysis
    # ------------------------------------------------------------------

    def _analyze_protocol(self, protocol: dict) -> dict:
        name = str(protocol.get("name", "unknown"))
        tvl = float(protocol.get("tvl_usd", 0.0))
        interconnection = float(protocol.get("interconnection_score", 0.0))
        debt_exposure = float(protocol.get("debt_exposure_usd", 0.0))
        tokens_issued = list(protocol.get("tokens_issued", []))
        historical_contagion = int(protocol.get("historical_contagion_events", 0))
        oracle_dependencies = list(protocol.get("oracle_dependencies", []))
        liquidity_crisis_pct = float(protocol.get("liquidity_in_crisis_pct", 0.0))
        insurance_coverage = float(protocol.get("insurance_coverage_usd", 0.0))

        # Clamp range-bound inputs
        interconnection = max(0.0, min(100.0, interconnection))
        liquidity_crisis_pct = max(0.0, min(100.0, liquidity_crisis_pct))
        historical_contagion = max(0, historical_contagion)

        safe_tvl = max(tvl, 1.0)

        # --- Contagion amplification factor ---
        contagion_amp = 1.0 + (interconnection / 100.0) * (debt_exposure / safe_tvl)

        # --- TVL score: log-scaled 0-100 ($1M → 0, $10B → 100) ---
        tvl_score = self._compute_tvl_score(tvl)

        # --- Collateral usage score (own tokens used as collateral elsewhere) ---
        collateral_usage_score = min(100.0, len(tokens_issued) * 33.3)

        # --- Systemic importance score (0-100) ---
        systemic_importance = (
            tvl_score * 0.3
            + interconnection * 0.4
            + collateral_usage_score * 0.3
        )
        systemic_importance = max(0.0, min(100.0, systemic_importance))

        # --- Cascade risk score (0-100) ---
        debt_ratio = debt_exposure / safe_tvl
        cascade_risk = (
            interconnection * 0.5
            + min(50.0, debt_ratio * 50.0)
            + min(10.0, historical_contagion * 5.0)
        )
        cascade_risk = max(0.0, min(100.0, cascade_risk))

        # --- Resilience score (0-100) ---
        resilience = self._compute_resilience(
            insurance_coverage, safe_tvl, liquidity_crisis_pct, interconnection
        )

        # --- Net systemic risk ---
        net_systemic_risk = (
            systemic_importance * cascade_risk * (100.0 - resilience) / 100.0
        )

        # --- Label ---
        label = self._determine_label(systemic_importance, interconnection, tvl_score)

        # --- Flags ---
        flags = self._compute_flags(
            tokens_issued,
            oracle_dependencies,
            historical_contagion,
            insurance_coverage,
            tvl,
            liquidity_crisis_pct,
            systemic_importance,
        )

        return {
            "name": name,
            "tvl_usd": tvl,
            "contagion_amplification_factor": round(contagion_amp, 4),
            "systemic_importance_score": round(systemic_importance, 4),
            "cascade_risk_score": round(cascade_risk, 4),
            "resilience_score": round(resilience, 4),
            "net_systemic_risk": round(net_systemic_risk, 4),
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Sub-computations (exposed for unit testing)
    # ------------------------------------------------------------------

    def _compute_tvl_score(self, tvl: float) -> float:
        """Log-scaled 0-100 TVL score. $1M → 0, $10B → 100."""
        if tvl <= 0:
            return 0.0
        log_tvl = math.log10(max(1.0, tvl))
        return max(0.0, min(100.0, (log_tvl - 6.0) / (10.0 - 6.0) * 100.0))

    def _compute_resilience(
        self,
        insurance_coverage: float,
        safe_tvl: float,
        liquidity_crisis_pct: float,
        interconnection: float,
    ) -> float:
        """Resilience score 0-100."""
        insurance_ratio = insurance_coverage / safe_tvl
        # insurance contributes up to 40 points (100% coverage → 40)
        insurance_score = min(40.0, insurance_ratio * 100.0 * 0.4)
        # liquidity contributes up to 40 points
        liquidity_score = liquidity_crisis_pct * 0.4
        # low interconnection contributes up to 20 points
        low_interconnect_score = (100.0 - interconnection) * 0.2
        resilience = insurance_score + liquidity_score + low_interconnect_score
        return max(0.0, min(100.0, resilience))

    def _determine_label(
        self,
        importance: float,
        interconnection: float,
        tvl_score: float,
    ) -> str:
        """Assign systemic risk label based on importance and isolation criteria."""
        if importance > 80.0:
            return "SYSTEMIC_CORNERSTONE"
        if importance > 60.0:
            return "HIGH_SYSTEMIC"
        if importance > 40.0:
            return "MODERATE_SYSTEMIC"
        # Below 40: check isolation
        if interconnection < 10.0 and tvl_score < 10.0:
            return "ISOLATED"
        if importance > 20.0:
            return "LOW_SYSTEMIC"
        return "ISOLATED"

    def _compute_flags(
        self,
        tokens_issued: list,
        oracle_dependencies: list,
        historical_contagion: int,
        insurance_coverage: float,
        tvl: float,
        liquidity_crisis_pct: float,
        systemic_importance: float,
    ) -> list:
        flags = []
        if len(tokens_issued) > 0:
            flags.append("COLLATERAL_CONTAGION_RISK")
        if len(oracle_dependencies) == 1:
            flags.append("ORACLE_SINGLE_SOURCE")
        if historical_contagion > 1:
            flags.append("HISTORICALLY_CONTAGIOUS")
        if insurance_coverage > 0.10 * max(tvl, 1.0):
            flags.append("INSURANCE_BUFFERED")
        if liquidity_crisis_pct < 10.0:
            flags.append("LIQUIDITY_CLIFF")
        if systemic_importance > 85.0:
            flags.append("TOO_BIG_TO_FAIL")
        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "highest_systemic_risk": None,
                "lowest_systemic_risk": None,
                "total_systemic_tvl_at_risk": 0.0,
                "cornerstone_count": 0,
                "isolated_count": 0,
            }

        highest = max(results, key=lambda r: r["net_systemic_risk"])
        lowest = min(results, key=lambda r: r["net_systemic_risk"])

        high_risk_labels = {"SYSTEMIC_CORNERSTONE", "HIGH_SYSTEMIC"}
        tvl_at_risk = sum(
            r["tvl_usd"] for r in results if r["label"] in high_risk_labels
        )
        cornerstone_count = sum(
            1 for r in results if r["label"] == "SYSTEMIC_CORNERSTONE"
        )
        isolated_count = sum(1 for r in results if r["label"] == "ISOLATED")

        return {
            "highest_systemic_risk": highest["name"],
            "lowest_systemic_risk": lowest["name"],
            "total_systemic_tvl_at_risk": tvl_at_risk,
            "cornerstone_count": cornerstone_count,
            "isolated_count": isolated_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, record: dict, data_dir: str) -> None:
        """Append compact entry to ring-buffer log (cap=LOG_CAP). Atomic."""
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, _LOG_FILENAME)

        try:
            with open(log_path, "r") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        entry = {
            "timestamp": record["timestamp"],
            "protocol_count": record["protocol_count"],
            "aggregates": record["aggregates"],
        }
        log.append(entry)
        log = log[-LOG_CAP:]  # ring-buffer trim

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1028 DeFiProtocolSystemicRiskContagionModeler"
    )
    parser.add_argument("--check", action="store_true", help="Compute and print, no write")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    _sample = [
        {
            "name": "Aave V3",
            "tvl_usd": 10_000_000_000,
            "interconnection_score": 90,
            "debt_exposure_usd": 5_000_000_000,
            "collateral_accepted": ["ETH", "wBTC", "USDC"],
            "tokens_issued": ["aUSDC", "aETH"],
            "historical_contagion_events": 0,
            "oracle_dependencies": ["Chainlink", "TWAP"],
            "liquidity_in_crisis_pct": 25.0,
            "insurance_coverage_usd": 500_000_000,
        },
        {
            "name": "SmallProtocol",
            "tvl_usd": 500_000,
            "interconnection_score": 5,
            "debt_exposure_usd": 10_000,
            "collateral_accepted": ["USDC"],
            "tokens_issued": [],
            "historical_contagion_events": 0,
            "oracle_dependencies": ["Chainlink"],
            "liquidity_in_crisis_pct": 80.0,
            "insurance_coverage_usd": 0,
        },
    ]

    _modeler = DeFiProtocolSystemicRiskContagionModeler(data_dir=args.data_dir)
    _log_enabled = args.run and not args.check
    _result = _modeler.model(_sample, config={"log_enabled": _log_enabled})

    import json as _json
    print(_json.dumps(_result, indent=2))

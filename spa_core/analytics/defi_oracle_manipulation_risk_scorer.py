"""
MP-962: DeFi Oracle Manipulation Risk Scorer
Scores price-oracle manipulation risk for DeFi protocols.
Pure stdlib, offline, read-only/advisory.
Atomic log writes: tmp + os.replace.
"""
from __future__ import annotations

import json
import os
import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_CAP = 100
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
LOG_PATH_DEFAULT = os.path.join(_REPO_ROOT, "data", "oracle_manipulation_log.json")

RISK_THRESHOLDS = [
    (0.0,  20.0, "SAFE"),
    (20.0, 40.0, "LOW_RISK"),
    (40.0, 60.0, "MODERATE_RISK"),
    (60.0, 80.0, "HIGH_RISK"),
    (80.0, 101.0, "CRITICAL"),
]

TWAP_TYPES = {"uniswap_twap"}
AGGREGATOR_BONUS_TYPES = {"chainlink", "pyth"}

# TWAP cost multiplier baseline (seconds)
_TWAP_BASELINE_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_label(score: float) -> str:
    for lo, hi, label in RISK_THRESHOLDS:
        if lo <= score < hi:
            return label
    return "CRITICAL"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiOracleManipulationRiskScorer:
    """
    Scores the risk of price-oracle manipulation for a list of DeFi oracles.

    Usage
    -----
    scorer = DeFiOracleManipulationRiskScorer()
    result = scorer.score(oracles=[...], config={})
    """

    def __init__(self, log_path: str | None = None) -> None:
        self.log_path: str = log_path or LOG_PATH_DEFAULT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, oracles: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict:
        """
        Score a list of oracle dicts.

        Returns
        -------
        dict with keys:
            timestamp, oracle_count, results (list), aggregates (dict)
        """
        if config is None:
            config = {}

        results = [self._score_single(o) for o in oracles]

        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "oracle_count": len(oracles),
            "results": results,
            "aggregates": aggregates,
        }

        log_path = config.get("log_path", self.log_path)
        if log_path:
            self._append_log(output, log_path)

        return output

    # ------------------------------------------------------------------
    # Per-oracle scoring
    # ------------------------------------------------------------------

    def _score_single(self, oracle: dict) -> dict:
        manip_cost = self.compute_manipulation_cost(oracle)
        diversity   = self.compute_source_diversity_score(oracle)
        freshness   = self.compute_freshness_score(oracle)
        flags       = self.compute_flags(oracle)
        composite   = self.compute_composite_risk_score(
            manip_cost, diversity, freshness, flags, oracle
        )
        label = _risk_label(composite)

        return {
            "name":                         oracle.get("name", "unknown"),
            "protocol":                     oracle.get("protocol", "unknown"),
            "oracle_type":                  oracle.get("oracle_type", "custom"),
            "manipulation_cost_estimate_usd": round(manip_cost, 2),
            "source_diversity_score":       round(diversity, 2),
            "freshness_score":              round(freshness, 2),
            "composite_risk_score":         round(composite, 2),
            "risk_label":                   label,
            "flags":                        flags,
        }

    # ------------------------------------------------------------------
    # Computation methods (public for testability)
    # ------------------------------------------------------------------

    def compute_manipulation_cost(self, oracle: dict) -> float:
        """
        Estimate USD cost to manipulate this oracle.

        For TWAP oracles the cost is amplified by the window duration, since
        the attacker must sustain the price deviation across the entire window.

        Base cost = 10 % of underlying liquidity.
        TWAP factor = twap_window_seconds / 300  (5-min baseline).
        """
        liquidity    = float(oracle.get("liquidity_of_underlying_usd", 0.0))
        oracle_type  = oracle.get("oracle_type", "custom").lower()
        twap_window  = float(oracle.get("twap_window_seconds", 0.0))

        base_cost = liquidity * 0.10

        if oracle_type in TWAP_TYPES and twap_window > 0.0:
            twap_factor = max(1.0, twap_window / _TWAP_BASELINE_SECONDS)
            return base_cost * twap_factor

        return base_cost

    def compute_source_diversity_score(self, oracle: dict) -> float:
        """
        0–100: more independent price sources → higher score.
        Trusted aggregator types (chainlink, pyth) receive a +10 bonus.
        """
        num_sources  = int(oracle.get("num_price_sources", 1))
        oracle_type  = oracle.get("oracle_type", "custom").lower()

        if num_sources >= 7:
            base = 95.0
        elif num_sources >= 5:
            base = 80.0
        elif num_sources >= 3:
            base = 60.0
        elif num_sources >= 2:
            base = 35.0
        else:
            base = 5.0

        if oracle_type in AGGREGATOR_BONUS_TYPES:
            base += 10.0

        return _clamp(base)

    def compute_freshness_score(self, oracle: dict) -> float:
        """
        0–100: recently updated → score closer to 100.
        Staleness ratio = last_update_seconds_ago / heartbeat_seconds.
        """
        last_update = float(oracle.get("last_update_seconds_ago", 0.0))
        heartbeat   = float(oracle.get("heartbeat_seconds", 3600.0))
        if heartbeat <= 0.0:
            heartbeat = 3600.0

        ratio = last_update / heartbeat

        if ratio <= 1.0:
            return 100.0
        elif ratio <= 1.5:
            return 80.0
        elif ratio <= 2.0:
            return 50.0
        else:
            # Linear decay below 50 for ratios > 2
            return _clamp(50.0 - (ratio - 2.0) * 20.0)

    def compute_flags(self, oracle: dict) -> list[str]:
        """Return list of risk flag strings for this oracle."""
        flags: list[str] = []

        num_sources = int(oracle.get("num_price_sources", 1))
        if num_sources < 2:
            flags.append("SINGLE_SOURCE")

        last_update = float(oracle.get("last_update_seconds_ago", 0.0))
        heartbeat   = float(oracle.get("heartbeat_seconds", 3600.0))
        if heartbeat <= 0.0:
            heartbeat = 3600.0
        if last_update > heartbeat * 2.0:
            flags.append("STALE_DATA")

        oracle_type  = oracle.get("oracle_type", "custom").lower()
        twap_window  = float(oracle.get("twap_window_seconds", 0.0))
        if oracle_type in TWAP_TYPES and twap_window < 900.0:
            flags.append("SHORT_TWAP")

        liquidity = float(oracle.get("liquidity_of_underlying_usd", 0.0))
        if liquidity < 500_000.0:
            flags.append("LOW_LIQUIDITY_RISK")

        incidents = int(oracle.get("manipulation_incidents_count", 0))
        if incidents > 0:
            flags.append("PRIOR_MANIPULATION")

        if not oracle.get("has_circuit_breaker", False):
            flags.append("NO_CIRCUIT_BREAKER")

        return flags

    def compute_composite_risk_score(
        self,
        manipulation_cost: float,
        source_diversity_score: float,
        freshness_score: float,
        flags: list[str],
        oracle: dict,
    ) -> float:
        """
        Weighted composite risk (0–100, higher = riskier).

        Weights:
          40 % manipulation cost risk
          25 % source diversity risk
          20 % freshness risk
          15 % flag / incident risk
        """
        # --- Manipulation cost risk (0-100) ---
        if manipulation_cost < 1_000_000.0:
            cost_risk = 100.0
        elif manipulation_cost < 5_000_000.0:
            cost_risk = 75.0
        elif manipulation_cost < 10_000_000.0:
            cost_risk = 50.0
        elif manipulation_cost < 50_000_000.0:
            cost_risk = 25.0
        else:
            cost_risk = 0.0

        source_risk   = 100.0 - source_diversity_score
        freshness_risk = 100.0 - freshness_score

        # --- Flag / incident risk ---
        flag_risk = 0.0
        if "NO_CIRCUIT_BREAKER" in flags:
            flag_risk += 10.0
        incidents = int(oracle.get("manipulation_incidents_count", 0))
        flag_risk += min(30.0, incidents * 15.0)
        if "SHORT_TWAP" in flags:
            flag_risk += 10.0
        if not oracle.get("audited", True):
            flag_risk += 10.0
        flag_risk = min(60.0, flag_risk)

        composite = (
            0.40 * cost_risk
            + 0.25 * source_risk
            + 0.20 * freshness_risk
            + 0.15 * flag_risk
        )
        return _clamp(composite)

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list[dict]) -> dict:
        if not results:
            return {
                "highest_risk":       None,
                "lowest_risk":        None,
                "average_risk_score": 0.0,
                "critical_count":     0,
                "safe_count":         0,
            }

        scores = [r["composite_risk_score"] for r in results]
        highest = max(results, key=lambda r: r["composite_risk_score"])
        lowest  = min(results, key=lambda r: r["composite_risk_score"])

        return {
            "highest_risk":       highest["name"],
            "lowest_risk":        lowest["name"],
            "average_risk_score": round(sum(scores) / len(scores), 2),
            "critical_count":     sum(1 for r in results if r["risk_label"] == "CRITICAL"),
            "safe_count":         sum(1 for r in results if r["risk_label"] == "SAFE"),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict, log_path: str) -> None:
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []

        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        dir_path = os.path.dirname(log_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)

"""
MP-963: Protocol DeFi Depeg Contagion Modeler
Models chain-reaction depeg risk for stablecoins and the contagion that
spreads through DeFi protocols that hold them as collateral.
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
LOG_PATH_DEFAULT = os.path.join(_REPO_ROOT, "data", "depeg_contagion_log.json")

CONTAGION_THRESHOLDS = [
    (0.0,  20.0, "CONTAINED"),
    (20.0, 40.0, "MODERATE_SPILLOVER"),
    (40.0, 60.0, "SIGNIFICANT_CONTAGION"),
    (60.0, 80.0, "SYSTEMIC_RISK"),
    (80.0, 101.0, "COLLAPSE_SCENARIO"),
]

ALGO_PEG_TYPES = {"algo"}
SYSTEMIC_LABELS = {"SYSTEMIC_RISK", "COLLAPSE_SCENARIO"}

# Penalty table for peg_type on stability_score
_PEG_TYPE_PENALTY: dict[str, float] = {
    "algo":          25.0,
    "crypto_backed": 10.0,
    "hybrid":         5.0,
    "fiat_backed":    0.0,
}

# High protocol exposure threshold
_HIGH_PROTOCOL_EXPOSURE_THRESHOLD = 5

# Over/under collateral thresholds
_OVER_COLLAT_THRESHOLD  = 150.0
_UNDER_COLLAT_THRESHOLD = 100.0

# Death-spiral imminence fraction
_DEATH_SPIRAL_FRACTION = 0.80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contagion_label(score: float) -> str:
    for lo, hi, label in CONTAGION_THRESHOLDS:
        if lo <= score < hi:
            return label
    return "COLLAPSE_SCENARIO"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiDepegContagionModeler:
    """
    Models stablecoin depeg contagion risk across DeFi protocols.

    Usage
    -----
    modeler = ProtocolDeFiDepegContagionModeler()
    result  = modeler.model(stablecoins=[...], config={})
    """

    def __init__(self, log_path: str | None = None) -> None:
        self.log_path: str = log_path or LOG_PATH_DEFAULT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def model(
        self,
        stablecoins: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> dict:
        """
        Model depeg contagion for a list of stablecoin dicts.

        Returns
        -------
        dict with keys:
            timestamp, stablecoin_count, results (list), aggregates (dict)
        """
        if config is None:
            config = {}

        results = [self._model_single(sc) for sc in stablecoins]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp":        datetime.datetime.utcnow().isoformat(),
            "stablecoin_count": len(stablecoins),
            "results":          results,
            "aggregates":       aggregates,
        }

        log_path = config.get("log_path", self.log_path)
        if log_path:
            self._append_log(output, log_path)

        return output

    # ------------------------------------------------------------------
    # Per-stablecoin modelling
    # ------------------------------------------------------------------

    def _model_single(self, sc: dict) -> dict:
        stability     = self.compute_stability_score(sc)
        contagion_usd = self.compute_contagion_spread_usd(sc)
        redemp_hours  = self.compute_redemption_run_hours(sc)
        cascade_risk  = self.compute_cascade_risk_score(sc)
        flags         = self.compute_flags(sc)
        label         = _contagion_label(cascade_risk)

        return {
            "name":                                sc.get("name", "unknown"),
            "peg_type":                            sc.get("peg_type", "fiat_backed"),
            "stability_score":                     round(stability, 2),
            "contagion_spread_usd":                round(contagion_usd, 2),
            "redemption_run_hours":                round(redemp_hours, 2),
            "cascade_risk_score":                  round(cascade_risk, 2),
            "contagion_label":                     label,
            "flags":                               flags,
            "current_peg_deviation_pct":           float(sc.get("current_peg_deviation_pct", 0.0)),
            "collateral_ratio_pct":                float(sc.get("collateral_ratio_pct", 100.0)),
            "tvl_as_collateral_in_protocols_usd":  float(sc.get("tvl_as_collateral_in_protocols_usd", 0.0)),
        }

    # ------------------------------------------------------------------
    # Computation methods (public for testability)
    # ------------------------------------------------------------------

    def compute_stability_score(self, sc: dict) -> float:
        """
        0–100: higher = more stable.

        Components
        ----------
        * Peg type penalty  (algo is worst)
        * Collateral ratio  (under-collat hurts, over-collat helps)
        * Peg deviation vs death-spiral threshold
        * Redemption capacity relative to market cap
        """
        base = 60.0

        peg_type = sc.get("peg_type", "fiat_backed").lower()
        base -= _PEG_TYPE_PENALTY.get(peg_type, 0.0)

        collat_ratio = float(sc.get("collateral_ratio_pct", 100.0))
        if collat_ratio < _UNDER_COLLAT_THRESHOLD:
            base -= 30.0
        elif collat_ratio < 120.0:
            base -= 10.0
        elif collat_ratio >= 200.0:
            base += 15.0
        elif collat_ratio >= _OVER_COLLAT_THRESHOLD:
            base += 10.0
        # 120–149: neutral

        deviation  = float(sc.get("current_peg_deviation_pct", 0.0))
        threshold  = float(sc.get("death_spiral_threshold_pct", 5.0))
        if threshold > 0.0:
            dev_ratio = deviation / threshold
            if dev_ratio >= _DEATH_SPIRAL_FRACTION:
                base -= 40.0
            elif dev_ratio >= 0.5:
                base -= 20.0
            elif dev_ratio >= 0.2:
                base -= 10.0

        redemption  = float(sc.get("daily_redemption_capacity_usd", 0.0))
        market_cap  = float(sc.get("market_cap_usd", 1.0))
        if market_cap > 0.0:
            redemp_ratio = redemption / market_cap
            if redemp_ratio >= 0.5:
                base += 10.0
            elif redemp_ratio < 0.01:
                base -= 10.0

        return _clamp(base)

    def compute_contagion_spread_usd(self, sc: dict) -> float:
        """
        USD value of collateral at risk if this stablecoin depegs.
        Equals the TVL locked as collateral in exposed protocols.
        """
        return float(sc.get("tvl_as_collateral_in_protocols_usd", 0.0))

    def compute_redemption_run_hours(self, sc: dict) -> float:
        """
        Hours required to fully redeem the entire market cap at maximum
        daily redemption capacity.

        Formula: market_cap / daily_capacity × 24
        A shorter period → bank-run pressure is resolved faster but also
        means the exit is more feasible, compressing the run timeline.
        """
        market_cap     = float(sc.get("market_cap_usd", 0.0))
        daily_capacity = float(sc.get("daily_redemption_capacity_usd", 0.0))

        if daily_capacity <= 0.0:
            return float("inf")

        return round(market_cap / daily_capacity * 24.0, 4)

    def compute_cascade_risk_score(self, sc: dict) -> float:
        """
        0–100: higher = greater contagion risk.

        Components (weighted)
        ---------------------
        60 % TVL fraction  (tvl_as_collateral / market_cap, capped at 1.0)
        40 % Protocol exposure count
        """
        tvl_collat  = float(sc.get("tvl_as_collateral_in_protocols_usd", 0.0))
        market_cap  = float(sc.get("market_cap_usd", 1.0))
        protocols   = sc.get("protocols_exposed", [])
        n_protocols = len(protocols)

        tvl_fraction = min(1.0, tvl_collat / market_cap) if market_cap > 0.0 else 0.0

        if n_protocols >= 10:
            protocol_risk = 100.0
        elif n_protocols >= 5:
            protocol_risk = 70.0
        elif n_protocols >= 3:
            protocol_risk = 50.0
        elif n_protocols >= 1:
            protocol_risk = 30.0
        else:
            protocol_risk = 0.0

        cascade = 0.60 * (tvl_fraction * 100.0) + 0.40 * protocol_risk
        return _clamp(cascade)

    def compute_flags(self, sc: dict) -> list[str]:
        """Return list of risk flag strings for this stablecoin."""
        flags: list[str] = []

        peg_type = sc.get("peg_type", "fiat_backed").lower()
        if peg_type in ALGO_PEG_TYPES:
            flags.append("ALGO_RISK")

        collat_ratio = float(sc.get("collateral_ratio_pct", 100.0))
        if collat_ratio > _OVER_COLLAT_THRESHOLD:
            flags.append("OVER_COLLATERALIZED")
        if collat_ratio < _UNDER_COLLAT_THRESHOLD:
            flags.append("UNDER_COLLATERALIZED")

        deviation  = float(sc.get("current_peg_deviation_pct", 0.0))
        threshold  = float(sc.get("death_spiral_threshold_pct", 5.0))
        if threshold > 0.0 and deviation > threshold * _DEATH_SPIRAL_FRACTION:
            flags.append("DEATH_SPIRAL_IMMINENT")

        protocols = sc.get("protocols_exposed", [])
        if len(protocols) > _HIGH_PROTOCOL_EXPOSURE_THRESHOLD:
            flags.append("HIGH_PROTOCOL_EXPOSURE")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list[dict]) -> dict:
        if not results:
            return {
                "most_stable":            None,
                "highest_contagion_risk": None,
                "total_tvl_at_risk_usd":  0.0,
                "systemic_risk_count":    0,
                "average_stability_score": 0.0,
            }

        most_stable  = max(results, key=lambda r: r["stability_score"])
        highest_cont = max(results, key=lambda r: r["cascade_risk_score"])

        total_tvl = sum(r["contagion_spread_usd"] for r in results)
        systemic  = sum(1 for r in results if r["contagion_label"] in SYSTEMIC_LABELS)
        avg_stab  = sum(r["stability_score"] for r in results) / len(results)

        return {
            "most_stable":             most_stable["name"],
            "highest_contagion_risk":  highest_cont["name"],
            "total_tvl_at_risk_usd":   round(total_tvl, 2),
            "systemic_risk_count":     systemic,
            "average_stability_score": round(avg_stab, 2),
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

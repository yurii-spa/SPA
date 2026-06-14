"""
MP-986: DeFiLiquidityConcentrationRiskScorer
Evaluates liquidity concentration risk in DeFi pools.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import math
import os
import time
import tempfile
from typing import Any

# ---------------------------------------------------------------------------
# Risk labels
# ---------------------------------------------------------------------------
LABEL_WELL_DISTRIBUTED   = "WELL_DISTRIBUTED"
LABEL_LOW_CONCENTRATION  = "LOW_CONCENTRATION"
LABEL_MODERATE_RISK      = "MODERATE_RISK"
LABEL_HIGH_CONCENTRATION = "HIGH_CONCENTRATION"
LABEL_SINGLE_LP_RISK     = "SINGLE_LP_RISK"

# Flags
FLAG_SINGLE_LP_DOMINANT    = "SINGLE_LP_DOMINANT"
FLAG_INCENTIVE_DEPENDENT   = "INCENTIVE_DEPENDENT"
FLAG_PROTOCOL_OWNED_MAJORITY = "PROTOCOL_OWNED_MAJORITY"
FLAG_STICKY_MAJORITY       = "STICKY_MAJORITY"
FLAG_CL_RANGE_RISK         = "CL_RANGE_RISK"

# Ring-buffer cap
_LOG_CAP = 100
_LOG_PATH_DEFAULT = "data/liquidity_concentration_log.json"


def _atomic_write(path: str, obj: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _compute_hhi(shares: list[float]) -> float:
    """Herfindahl-Hirschman Index from fractional shares (0-1). Returns 0-10000."""
    return sum((s * 100) ** 2 for s in shares)


def _score_pool(pool: dict) -> dict:
    """Score a single pool and return its result dict."""
    protocol = pool.get("protocol", "unknown")
    pair     = pool.get("pair", "unknown")
    total_tvl = float(pool.get("total_tvl_usd", 0.0))
    lp_positions = pool.get("top_lp_positions", [])
    is_cl    = bool(pool.get("is_concentrated_liquidity", False))
    active_range_pct   = float(pool.get("active_range_pct", 100.0))
    incentive_dep_pct  = float(pool.get("incentive_dependent_pct", 0.0))
    sticky_lp_pct      = float(pool.get("sticky_lp_pct", 0.0))
    geo_conc           = pool.get("geographic_concentration", "unknown")
    pol_pct            = float(pool.get("protocol_owned_liquidity_pct", 0.0))

    # Sort LP positions descending by tvl_usd
    positions_sorted = sorted(
        lp_positions,
        key=lambda p: float(p.get("tvl_usd", 0.0)),
        reverse=True
    )

    lp_tvl_values = [float(p.get("tvl_usd", 0.0)) for p in positions_sorted]
    total_lp_tvl  = sum(lp_tvl_values) if lp_tvl_values else total_tvl

    # Avoid division by zero
    denom = total_lp_tvl if total_lp_tvl > 0 else max(total_tvl, 1.0)

    lp_shares = [v / denom for v in lp_tvl_values]

    # top3_concentration_pct
    top3_pct = sum(lp_shares[:3]) * 100.0

    # top1 share
    top1_pct = (lp_shares[0] * 100.0) if lp_shares else 0.0

    # lp_hhi
    lp_hhi = _compute_hhi(lp_shares)

    # withdrawal_scenario_10pct_impact: what fraction of TVL leaves if top LP exits
    withdrawal_impact = (lp_tvl_values[0] / denom * 100.0) if lp_tvl_values else 0.0

    # sticky_ratio
    sticky_ratio_pct = sticky_lp_pct  # passed directly

    # concentration_risk_score (0-100)
    # Weighted composite:
    #   40% top1_pct (normalised to 100 when top1=100)
    #   25% lp_hhi (normalised: 10000 → 100)
    #   15% incentive_dep_pct
    #   10% CL range risk (inverted active_range when CL)
    #   10% geographic (single_entity→100, diverse→0, unknown→50)
    hhi_norm = min(lp_hhi / 100.0, 100.0)
    geo_score = {"single_entity": 80.0, "diverse": 10.0, "unknown": 40.0}.get(geo_conc, 40.0)
    cl_range_risk = max(0.0, 100.0 - active_range_pct) if is_cl else 0.0

    concentration_risk_score = (
        0.40 * min(top1_pct, 100.0)
        + 0.25 * hhi_norm
        + 0.15 * min(incentive_dep_pct, 100.0)
        + 0.10 * cl_range_risk
        + 0.10 * geo_score
    )
    concentration_risk_score = round(min(max(concentration_risk_score, 0.0), 100.0), 2)

    # Risk label
    if top1_pct > 60.0:
        risk_label = LABEL_SINGLE_LP_RISK
    elif concentration_risk_score >= 70.0:
        risk_label = LABEL_HIGH_CONCENTRATION
    elif concentration_risk_score >= 45.0:
        risk_label = LABEL_MODERATE_RISK
    elif concentration_risk_score >= 20.0:
        risk_label = LABEL_LOW_CONCENTRATION
    else:
        risk_label = LABEL_WELL_DISTRIBUTED

    # Flags
    flags = []
    if top1_pct > 50.0:
        flags.append(FLAG_SINGLE_LP_DOMINANT)
    if incentive_dep_pct > 50.0:
        flags.append(FLAG_INCENTIVE_DEPENDENT)
    if pol_pct > 40.0:
        flags.append(FLAG_PROTOCOL_OWNED_MAJORITY)
    if sticky_lp_pct > 60.0:
        flags.append(FLAG_STICKY_MAJORITY)
    if is_cl and active_range_pct < 50.0:
        flags.append(FLAG_CL_RANGE_RISK)

    return {
        "protocol": protocol,
        "pair": pair,
        "total_tvl_usd": total_tvl,
        "top3_concentration_pct": round(top3_pct, 2),
        "lp_hhi": round(lp_hhi, 2),
        "withdrawal_scenario_10pct_impact": round(withdrawal_impact, 2),
        "sticky_ratio_pct": round(sticky_ratio_pct, 2),
        "concentration_risk_score": concentration_risk_score,
        "risk_label": risk_label,
        "flags": flags,
        "top1_pct": round(top1_pct, 2),
        "incentive_dependent_pct": incentive_dep_pct,
        "protocol_owned_liquidity_pct": pol_pct,
        "is_concentrated_liquidity": is_cl,
        "active_range_pct": active_range_pct,
    }


class DeFiLiquidityConcentrationRiskScorer:
    """
    Scores liquidity concentration risk across a list of DeFi pools.

    score(pools, config) -> dict
    """

    def __init__(self, log_path: str = _LOG_PATH_DEFAULT):
        self._log_path = log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, pools: list, config: dict | None = None) -> dict:
        """
        Score all pools and return aggregate analysis.

        Parameters
        ----------
        pools : list[dict]  — pool descriptors (see module docstring)
        config : dict       — optional overrides (log_path, thresholds)

        Returns
        -------
        dict with keys: pools (list of scored results), aggregates, timestamp
        """
        if config is None:
            config = {}

        log_path = config.get("log_path", self._log_path)

        if not pools:
            result = {
                "pools": [],
                "aggregates": {
                    "most_concentrated": None,
                    "least_concentrated": None,
                    "average_concentration_score": 0.0,
                    "high_concentration_count": 0,
                    "total_tvl_analyzed_usd": 0.0,
                    "total_pools": 0,
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._append_log(result, log_path)
            return result

        scored = [_score_pool(p) for p in pools]

        # Aggregates
        scores   = [s["concentration_risk_score"] for s in scored]
        avg_score = round(sum(scores) / len(scores), 2)
        high_count = sum(1 for s in scored
                         if s["risk_label"] in (LABEL_HIGH_CONCENTRATION, LABEL_SINGLE_LP_RISK))
        total_tvl = sum(s["total_tvl_usd"] for s in scored)

        most_conc  = max(scored, key=lambda s: s["concentration_risk_score"])
        least_conc = min(scored, key=lambda s: s["concentration_risk_score"])

        result = {
            "pools": scored,
            "aggregates": {
                "most_concentrated": {
                    "protocol": most_conc["protocol"],
                    "pair":     most_conc["pair"],
                    "concentration_risk_score": most_conc["concentration_risk_score"],
                    "risk_label": most_conc["risk_label"],
                },
                "least_concentrated": {
                    "protocol": least_conc["protocol"],
                    "pair":     least_conc["pair"],
                    "concentration_risk_score": least_conc["concentration_risk_score"],
                    "risk_label": least_conc["risk_label"],
                },
                "average_concentration_score": avg_score,
                "high_concentration_count": high_count,
                "total_tvl_analyzed_usd": round(total_tvl, 2),
                "total_pools": len(scored),
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        self._append_log(result, log_path)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_log(self, result: dict, log_path: str) -> None:
        """Append entry to ring-buffer log (cap=100, atomic write)."""
        log = _load_log(log_path)
        entry = {
            "timestamp": result.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S")),
            "total_pools": result["aggregates"].get("total_pools", 0),
            "average_concentration_score": result["aggregates"].get("average_concentration_score", 0.0),
            "high_concentration_count": result["aggregates"].get("high_concentration_count", 0),
            "total_tvl_analyzed_usd": result["aggregates"].get("total_tvl_analyzed_usd", 0.0),
        }
        log.append(entry)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        _atomic_write(log_path, log)

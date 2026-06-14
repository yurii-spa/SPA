"""
MP-1032: DeFiProtocolDepegContagionRiskAnalyzer

Analyzes the risk of a stablecoin or LST depeg spreading as contagion to
connected DeFi protocols. Models direct loss, cascading multipliers, and
estimates affected protocol count based on interconnection scores.

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/depeg_contagion_risk_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/depeg_contagion_risk_log.json")
MAX_ENTRIES = 100

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# Base contagion spread score by asset type (0-100 range contribution)
ASSET_TYPE_BASE_SPREAD = {
    "stablecoin": 35,
    "lst":        28,
    "wrapped":    20,
}

# Cascading loss multiplier base by asset type
ASSET_TYPE_CASCADE_MULTIPLIER = {
    "stablecoin": 2.5,
    "lst":        2.0,
    "wrapped":    1.6,
}

# Label thresholds (contagion_spread_score 0-100)
_LABEL_THRESHOLDS = [
    (85, "SYSTEMIC_MELTDOWN"),
    (65, "HIGH_CONTAGION"),
    (45, "MODERATE_CONTAGION"),
    (25, "LOW_CONTAGION"),
    (0,  "CONTAINED"),
]


# ─────────────────────────────────────────────────────────────────
# Internal computation helpers (exposed for unit tests)
# ─────────────────────────────────────────────────────────────────

def _compute_contagion_spread_score(
    asset_type: str,
    collateral_usage_pct: float,
    depeg_magnitude_pct: float,
    protocol_interconnection_score: float,
    insurance_coverage_pct: float,
) -> float:
    """
    Compute contagion spread score in [0.0, 100.0].

    Parameters
    ----------
    asset_type : str
        One of 'stablecoin', 'lst', 'wrapped'.
    collateral_usage_pct : float
        Percentage (0-100) of DeFi protocols using this asset as collateral.
    depeg_magnitude_pct : float
        Size of depeg in percentage points (e.g. 10.0 = 10% depeg).
    protocol_interconnection_score : float
        0-1 measure of how interconnected protocols are (1 = fully connected).
    insurance_coverage_pct : float
        Percentage (0-100) of exposure covered by insurance/backstops.
    """
    base = float(ASSET_TYPE_BASE_SPREAD.get(asset_type.lower(), 25))

    # Collateral usage drives spread — more protocols using as collateral = more contagion
    # Scale: 0-100% maps to 0-30 points
    base += (min(float(collateral_usage_pct), 100.0) / 100.0) * 30.0

    # Depeg magnitude amplifies contagion
    mag = min(float(depeg_magnitude_pct), 100.0)
    if mag >= 30.0:
        base += 20.0
    elif mag >= 15.0:
        base += 13.0
    elif mag >= 5.0:
        base += 7.0
    elif mag >= 1.0:
        base += 2.0

    # Protocol interconnection score (0-1) adds up to 15 points
    interconnect = max(0.0, min(1.0, float(protocol_interconnection_score)))
    base += interconnect * 15.0

    # Insurance coverage reduces spread (up to -20 points)
    coverage = max(0.0, min(100.0, float(insurance_coverage_pct)))
    base -= (coverage / 100.0) * 20.0

    return max(0.0, min(100.0, base))


def _compute_direct_loss_usd(
    tvl_exposed_usd: float,
    depeg_magnitude_pct: float,
    collateral_usage_pct: float,
) -> float:
    """
    Estimate direct USD loss from the initial depeg.

    Direct loss = TVL at risk × depeg fraction × collateral utilisation fraction.
    """
    tvl = max(0.0, float(tvl_exposed_usd))
    depeg_frac = min(float(depeg_magnitude_pct), 100.0) / 100.0
    collateral_frac = min(float(collateral_usage_pct), 100.0) / 100.0
    return tvl * depeg_frac * collateral_frac


def _compute_cascading_loss_multiplier(
    asset_type: str,
    protocol_interconnection_score: float,
    depeg_magnitude_pct: float,
    insurance_coverage_pct: float,
) -> float:
    """
    Compute cascading loss multiplier (≥ 1.0).

    Represents how many times worse total losses are vs. direct loss alone,
    due to second- and third-order effects (forced liquidations, oracle
    failures, bank-run dynamics).
    """
    base_mult = float(ASSET_TYPE_CASCADE_MULTIPLIER.get(asset_type.lower(), 1.8))

    interconnect = max(0.0, min(1.0, float(protocol_interconnection_score)))
    base_mult += interconnect * 1.5   # high interconnection amplifies cascades

    mag = min(float(depeg_magnitude_pct), 100.0)
    if mag >= 30.0:
        base_mult += 1.0
    elif mag >= 15.0:
        base_mult += 0.5
    elif mag >= 5.0:
        base_mult += 0.2

    # Insurance damps cascading (up to -1.0 multiplier reduction)
    coverage = max(0.0, min(100.0, float(insurance_coverage_pct)))
    base_mult -= (coverage / 100.0) * 1.0

    return max(1.0, round(base_mult, 3))


def _compute_affected_protocols_estimate(
    collateral_usage_pct: float,
    protocol_interconnection_score: float,
    depeg_magnitude_pct: float,
) -> int:
    """
    Estimate number of protocols meaningfully affected by the contagion.

    Uses a model of 200 hypothetical DeFi protocols as a reference universe.
    """
    universe = 200
    collateral_frac = min(float(collateral_usage_pct), 100.0) / 100.0
    interconnect = max(0.0, min(1.0, float(protocol_interconnection_score)))
    mag = min(float(depeg_magnitude_pct), 100.0)

    # Directly exposed: protocols using the asset as collateral
    directly_exposed = universe * collateral_frac

    # Indirectly affected: driven by interconnection and depeg severity
    indirect_factor = interconnect * (mag / 100.0) * 0.5
    indirectly_affected = (universe - directly_exposed) * indirect_factor

    return max(0, int(round(directly_exposed + indirectly_affected)))


def _contagion_label(contagion_spread_score: float) -> str:
    """Map contagion_spread_score to a risk label."""
    score = float(contagion_spread_score)
    for threshold, label in _LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "CONTAINED"


def _compute_flags(
    asset_type: str,
    depeg_magnitude_pct: float,
    protocol_interconnection_score: float,
    collateral_usage_pct: float,
    insurance_coverage_pct: float,
) -> list:
    """Return list of active risk flag strings."""
    flags: list[str] = []
    mag = float(depeg_magnitude_pct)
    interconnect = float(protocol_interconnection_score)
    collateral = float(collateral_usage_pct)
    coverage = float(insurance_coverage_pct)

    if mag >= 20.0:
        flags.append("SEVERE_DEPEG")
    if interconnect >= 0.75:
        flags.append("HIGH_INTERCONNECTION")
    if collateral >= 50.0:
        flags.append("WIDESPREAD_COLLATERAL_USE")
    if coverage < 10.0:
        flags.append("MINIMAL_INSURANCE")
    if asset_type.lower() == "stablecoin" and mag >= 5.0:
        flags.append("STABLECOIN_PEG_BREAK")
    if asset_type.lower() == "lst" and mag >= 3.0:
        flags.append("LST_SLASHING_EVENT")

    return flags


# ─────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────

class DeFiProtocolDepegContagionRiskAnalyzer:
    """
    Advisory analyzer for DeFi depeg contagion risk.

    Analyzes how a stablecoin, LST, or wrapped asset depeg can spread
    contagion across connected DeFi protocols, estimating direct losses,
    cascading multipliers, and the number of affected protocols.

    Pure stdlib, read-only/advisory. Ring-buffer log to
    data/depeg_contagion_risk_log.json (cap 100, atomic writes).
    """

    def analyze(
        self,
        asset_type: str,
        collateral_usage_pct: float,
        depeg_magnitude_pct: float,
        protocol_interconnection_score: float,
        insurance_coverage_pct: float,
        tvl_exposed_usd: float,
        asset_name: str = "UNKNOWN",
        data_dir: str | None = None,
    ) -> dict:
        """
        Analyze depeg contagion risk for a single asset event.

        Parameters
        ----------
        asset_type : str
            Type of depegged asset: 'stablecoin', 'lst', or 'wrapped'.
        collateral_usage_pct : float
            Percentage (0-100) of protocols using this asset as collateral.
        depeg_magnitude_pct : float
            Depeg size in percentage points (0-100).
        protocol_interconnection_score : float
            How interconnected DeFi protocols are (0-1, 1 = fully connected).
        insurance_coverage_pct : float
            Percentage of TVL covered by insurance/backstops (0-100).
        tvl_exposed_usd : float
            Total value locked exposed to this asset, in USD.
        asset_name : str, optional
            Human-readable name for the asset (e.g. 'USDC', 'stETH').
        data_dir : str, optional
            Override directory for log file (tests use temp dirs).

        Returns
        -------
        dict
            {
              "asset_name": str,
              "asset_type": str,
              "collateral_usage_pct": float,
              "depeg_magnitude_pct": float,
              "protocol_interconnection_score": float,
              "insurance_coverage_pct": float,
              "tvl_exposed_usd": float,
              "contagion_spread_score": float,
              "direct_loss_usd": float,
              "cascading_loss_multiplier": float,
              "total_estimated_loss_usd": float,
              "affected_protocols_estimate": int,
              "label": str,
              "flags": list[str],
              "timestamp": float,
            }
        """
        atype = str(asset_type).lower()
        col_pct = max(0.0, min(100.0, float(collateral_usage_pct)))
        dep_mag = max(0.0, min(100.0, float(depeg_magnitude_pct)))
        interconnect = max(0.0, min(1.0, float(protocol_interconnection_score)))
        ins_cov = max(0.0, min(100.0, float(insurance_coverage_pct)))
        tvl = max(0.0, float(tvl_exposed_usd))

        contagion_spread_score = _compute_contagion_spread_score(
            atype, col_pct, dep_mag, interconnect, ins_cov
        )
        direct_loss = _compute_direct_loss_usd(tvl, dep_mag, col_pct)
        cascade_mult = _compute_cascading_loss_multiplier(
            atype, interconnect, dep_mag, ins_cov
        )
        total_loss = direct_loss * cascade_mult
        affected = _compute_affected_protocols_estimate(col_pct, interconnect, dep_mag)
        label = _contagion_label(contagion_spread_score)
        flags = _compute_flags(atype, dep_mag, interconnect, col_pct, ins_cov)

        result = {
            "asset_name": str(asset_name),
            "asset_type": atype,
            "collateral_usage_pct": col_pct,
            "depeg_magnitude_pct": dep_mag,
            "protocol_interconnection_score": interconnect,
            "insurance_coverage_pct": ins_cov,
            "tvl_exposed_usd": tvl,
            "contagion_spread_score": round(contagion_spread_score, 4),
            "direct_loss_usd": round(direct_loss, 2),
            "cascading_loss_multiplier": cascade_mult,
            "total_estimated_loss_usd": round(total_loss, 2),
            "affected_protocols_estimate": affected,
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
        log_path = Path(data_dir) / "depeg_contagion_risk_log.json"
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
    analyzer = DeFiProtocolDepegContagionRiskAnalyzer()

    scenarios = [
        {
            "asset_name": "USDC",
            "asset_type": "stablecoin",
            "collateral_usage_pct": 60.0,
            "depeg_magnitude_pct": 5.0,
            "protocol_interconnection_score": 0.7,
            "insurance_coverage_pct": 15.0,
            "tvl_exposed_usd": 50_000_000_000,
        },
        {
            "asset_name": "stETH",
            "asset_type": "lst",
            "collateral_usage_pct": 35.0,
            "depeg_magnitude_pct": 3.0,
            "protocol_interconnection_score": 0.5,
            "insurance_coverage_pct": 10.0,
            "tvl_exposed_usd": 15_000_000_000,
        },
        {
            "asset_name": "USTC",
            "asset_type": "stablecoin",
            "collateral_usage_pct": 80.0,
            "depeg_magnitude_pct": 95.0,
            "protocol_interconnection_score": 0.9,
            "insurance_coverage_pct": 0.0,
            "tvl_exposed_usd": 18_000_000_000,
        },
    ]

    for scenario in scenarios:
        result = analyzer.analyze(**scenario)
        print(
            f"{result['asset_name']}: score={result['contagion_spread_score']:.1f}  "
            f"label={result['label']}  "
            f"cascade_mult={result['cascading_loss_multiplier']:.2f}x  "
            f"affected={result['affected_protocols_estimate']} protocols"
        )

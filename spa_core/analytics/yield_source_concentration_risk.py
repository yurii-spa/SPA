"""
MP-871 YieldSourceConcentrationRisk
------------------------------------
Measures how concentrated a portfolio's yield sources are across four risk
dimensions: protocol, chain, asset_type, and yield_type.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_HHI_WARNING: float = 0.25
_DEFAULT_HHI_CRITICAL: float = 0.50
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_concentration_log.json"
)
_LOG_CAP = 100

_VALID_ASSET_TYPES = {
    "STABLECOIN", "ETH_LST", "BTC_DERIVATIVE", "LP_TOKEN",
    "GOVERNANCE_TOKEN", "OTHER",
}
_VALID_YIELD_TYPES = {
    "LENDING", "LP_FEES", "STAKING", "FARMING", "RESTAKING", "REAL_WORLD",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hhi(shares: list[float]) -> float:
    """Return Herfindahl-Hirschman Index from a list of fractional shares (sum=1)."""
    return sum(s * s for s in shares)


def _compute_dimension(
    positions: list[dict],
    total: float,
    key: str,
) -> tuple[float, str | None, float, dict[str, float]]:
    """
    Group positions by *key*, compute HHI, top group name/share.

    Returns (hhi, top_name, top_share_pct, group_allocs_dict)
    """
    if total <= 0 or not positions:
        return 0.0, None, 0.0, {}

    groups: dict[str, float] = {}
    for p in positions:
        label = p.get(key, "UNKNOWN") or "UNKNOWN"
        groups[label] = groups.get(label, 0.0) + float(p.get("allocation_usd", 0.0))

    shares = {g: alloc / total for g, alloc in groups.items()}
    hhi_val = _hhi(list(shares.values()))

    top_name = max(shares, key=shares.__getitem__)
    top_share_pct = shares[top_name] * 100.0

    return hhi_val, top_name, top_share_pct, groups


def _risk_level(hhi: float, warning: float, critical: float) -> str:
    if hhi > critical:
        return "CRITICAL"
    if hhi > warning:
        return "HIGH"
    if hhi > 0.15:
        return "MODERATE"
    return "LOW"


def _overall_label(score: int) -> str:
    if score >= 60:
        return "HIGHLY_CONCENTRATED"
    if score >= 35:
        return "CONCENTRATED"
    if score >= 20:
        return "MODERATE"
    return "WELL_DIVERSIFIED"


def _recommendations(
    proto_hhi: float, top_proto: str | None, top_proto_pct: float,
    chain_hhi: float, top_chain: str | None, top_chain_pct: float,
    asset_hhi: float, top_asset: str | None, top_asset_pct: float,
    yield_hhi: float, top_yield: str | None, top_yield_pct: float,
) -> list[str]:
    recs: list[str] = []
    threshold = 0.4

    if proto_hhi > threshold and top_proto is not None:
        recs.append(
            f"Reduce {top_proto} from {top_proto_pct:.0f}% to under 40%"
        )
    if chain_hhi > threshold and top_chain is not None:
        recs.append(
            f"Diversify across chains — {top_chain} holds {top_chain_pct:.0f}%"
        )
    if asset_hhi > threshold and top_asset is not None:
        recs.append(
            f"Reduce {top_asset} exposure — {top_asset_pct:.0f}% concentration"
        )
    if yield_hhi > threshold and top_yield is not None:
        recs.append(
            f"Mix yield types — {top_yield} is {top_yield_pct:.0f}% of portfolio"
        )

    if not recs:
        recs = ["Diversification is adequate across all dimensions"]

    return recs


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(positions: list[dict], config: dict | None = None) -> dict:
    """
    Analyze yield-source concentration across protocol, chain, asset_type,
    and yield_type dimensions.

    Parameters
    ----------
    positions : list[dict]
        Each entry must have keys:
        - protocol: str
        - chain: str
        - asset_type: str  (one of _VALID_ASSET_TYPES)
        - yield_type: str  (one of _VALID_YIELD_TYPES)
        - allocation_usd: float
        - apy_pct: float
    config : dict, optional
        - hhi_warning_threshold: float  (default 0.25)
        - hhi_critical_threshold: float (default 0.50)

    Returns
    -------
    dict
        Full concentration analysis result (see module docstring).
    """
    cfg = config or {}
    hhi_warning: float = float(cfg.get("hhi_warning_threshold", _DEFAULT_HHI_WARNING))
    hhi_critical: float = float(cfg.get("hhi_critical_threshold", _DEFAULT_HHI_CRITICAL))

    # -----------------------------------------------------------------------
    # Totals
    # -----------------------------------------------------------------------
    total_alloc: float = sum(float(p.get("allocation_usd", 0.0)) for p in positions)

    # -----------------------------------------------------------------------
    # Per-dimension HHI
    # -----------------------------------------------------------------------
    proto_hhi, top_proto, top_proto_pct, _ = _compute_dimension(
        positions, total_alloc, "protocol"
    )
    chain_hhi, top_chain, top_chain_pct, _ = _compute_dimension(
        positions, total_alloc, "chain"
    )
    asset_hhi, top_asset, top_asset_pct, _ = _compute_dimension(
        positions, total_alloc, "asset_type"
    )
    yield_hhi, top_yield, top_yield_pct, _ = _compute_dimension(
        positions, total_alloc, "yield_type"
    )

    # -----------------------------------------------------------------------
    # Weighted-average APY
    # -----------------------------------------------------------------------
    weighted_apy: float = 0.0
    if total_alloc > 0:
        weighted_apy = (
            sum(
                float(p.get("allocation_usd", 0.0)) * float(p.get("apy_pct", 0.0))
                for p in positions
            )
            / total_alloc
        )

    # -----------------------------------------------------------------------
    # Overall score & label
    # -----------------------------------------------------------------------
    avg_hhi = (proto_hhi + chain_hhi + asset_hhi + yield_hhi) / 4.0
    overall_score = int(avg_hhi * 100)
    overall_label = _overall_label(overall_score)

    # -----------------------------------------------------------------------
    # Recommendations
    # -----------------------------------------------------------------------
    recs = _recommendations(
        proto_hhi, top_proto, top_proto_pct,
        chain_hhi, top_chain, top_chain_pct,
        asset_hhi, top_asset, top_asset_pct,
        yield_hhi, top_yield, top_yield_pct,
    )

    ts = time.time()
    result: dict[str, Any] = {
        "protocol_concentration": {
            "hhi": proto_hhi,
            "top_protocol": top_proto,
            "top_protocol_share_pct": top_proto_pct,
            "risk_level": _risk_level(proto_hhi, hhi_warning, hhi_critical),
        },
        "chain_concentration": {
            "hhi": chain_hhi,
            "top_chain": top_chain,
            "top_chain_share_pct": top_chain_pct,
            "risk_level": _risk_level(chain_hhi, hhi_warning, hhi_critical),
        },
        "asset_type_concentration": {
            "hhi": asset_hhi,
            "top_asset_type": top_asset,
            "top_asset_type_share_pct": top_asset_pct,
            "risk_level": _risk_level(asset_hhi, hhi_warning, hhi_critical),
        },
        "yield_type_concentration": {
            "hhi": yield_hhi,
            "top_yield_type": top_yield,
            "top_yield_type_share_pct": top_yield_pct,
            "risk_level": _risk_level(yield_hhi, hhi_warning, hhi_critical),
        },
        "overall_concentration_score": overall_score,
        "overall_risk_label": overall_label,
        "weighted_avg_apy_pct": weighted_apy,
        "total_allocation_usd": total_alloc,
        "diversification_recommendations": recs,
        "timestamp": ts,
    }

    # -----------------------------------------------------------------------
    # Persist to ring-buffer log
    # -----------------------------------------------------------------------
    try:
        _atomic_log(_LOG_PATH, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


if __name__ == "__main__":
    import sys

    _demo_positions = [
        {
            "protocol": "Aave V3",
            "chain": "Ethereum",
            "asset_type": "STABLECOIN",
            "yield_type": "LENDING",
            "allocation_usd": 40_000.0,
            "apy_pct": 3.5,
        },
        {
            "protocol": "Compound V3",
            "chain": "Ethereum",
            "asset_type": "STABLECOIN",
            "yield_type": "LENDING",
            "allocation_usd": 30_000.0,
            "apy_pct": 4.8,
        },
        {
            "protocol": "Morpho Steakhouse",
            "chain": "Ethereum",
            "asset_type": "STABLECOIN",
            "yield_type": "LENDING",
            "allocation_usd": 20_000.0,
            "apy_pct": 6.5,
        },
        {
            "protocol": "Aave V3 Arbitrum",
            "chain": "Arbitrum",
            "asset_type": "STABLECOIN",
            "yield_type": "LENDING",
            "allocation_usd": 10_000.0,
            "apy_pct": 4.6,
        },
    ]

    r = analyze(_demo_positions)
    print(json.dumps(r, indent=2))
    sys.exit(0)

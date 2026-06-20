"""
MP-1044  ProtocolDeFiWrappedAssetBackingVerifier
-------------------------------------------------
Verify that a wrapped / bridged token (e.g. wBTC, bridged USDC.e, bridged
weETH) is actually backed 1:1 by underlying reserves held in custody / bridge.

A wrapped token is only as good as the reserves that back it. This module
asks: is the circulating wrapped supply genuinely collateralised, and how
concentrated and fresh is the proof of those reserves?

The module returns:
- backing_ratio_pct              – reserve / wrapped_supply * 100 (100 = 1:1)
- collateral_shortfall_pct       – how far below 1:1 the backing sits
- custodian_concentration_score  – 0-100, higher = more concentrated custody
- attestation_freshness_score    – 0-100, higher = fresher proof-of-reserve
- backing_risk_score             – 0-100, higher = riskier
- classification                 – FULLY_BACKED .. CRITICAL_SHORTFALL
- grade                          – A-F
- flags                          – advisory flags
- recommendations                – advisory strings

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
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

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "wrapped_asset_backing_log.json",
)
_LOG_CAP = 100

# Classifications
CLASS_FULLY_BACKED = "FULLY_BACKED"
CLASS_WELL_BACKED = "WELL_BACKED"
CLASS_PARTIALLY_BACKED = "PARTIALLY_BACKED"
CLASS_UNDERBACKED = "UNDERBACKED"
CLASS_CRITICAL_SHORTFALL = "CRITICAL_SHORTFALL"

ALL_CLASSIFICATIONS = (
    CLASS_FULLY_BACKED,
    CLASS_WELL_BACKED,
    CLASS_PARTIALLY_BACKED,
    CLASS_UNDERBACKED,
    CLASS_CRITICAL_SHORTFALL,
)

# Flags
FLAG_UNDERBACKED = "UNDERBACKED"
FLAG_OVERCOLLATERALIZED = "OVERCOLLATERALIZED"
FLAG_SINGLE_CUSTODIAN = "SINGLE_CUSTODIAN"
FLAG_HIGH_CUSTODIAN_CONCENTRATION = "HIGH_CUSTODIAN_CONCENTRATION"
FLAG_STALE_ATTESTATION = "STALE_ATTESTATION"
FLAG_NO_REDEMPTION = "NO_REDEMPTION"
FLAG_REDEMPTION_FEE = "REDEMPTION_FEE"
FLAG_UNAUDITED = "UNAUDITED"
FLAG_FULLY_BACKED = "FULLY_BACKED"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_GRADES = ("A", "B", "C", "D", "F")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert *value* to float, falling back to *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert *value* to int, falling back to *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Sub-calculators
# ---------------------------------------------------------------------------

def _backing_ratio_pct(wrapped_supply: float, reserve_balance: float) -> float:
    """
    reserve_balance / wrapped_supply * 100.

    100 = exactly 1:1; <100 underbacked; >100 overcollateralised.
    Defensive: returns 0.0 when wrapped_supply <= 0 (no meaningful ratio).
    """
    if wrapped_supply <= 0:
        return 0.0
    return reserve_balance / wrapped_supply * 100.0


def _collateral_shortfall_pct(backing_ratio_pct: float) -> float:
    """How far below a 1:1 (100%) backing the asset sits; clamped to >= 0."""
    return max(0.0, 100.0 - backing_ratio_pct)


def _custodian_concentration_score(
    custodian_count: int,
    largest_custodian_share_pct: float,
) -> float:
    """
    0-100: higher = more concentrated custody (riskier).

    Blends the largest custodian's share with a penalty for having very few
    custodians. A single custodian pushes the score near 100; many small,
    even custodians push it toward 0.
    """
    share = _clamp(largest_custodian_share_pct)

    # Few-custodian penalty: 1 → 100, 2 → 50, 3 → ~33, ... → small.
    if custodian_count <= 0:
        count_penalty = 100.0
    else:
        count_penalty = _clamp(100.0 / custodian_count)

    # Blend: weight the observed largest share more heavily, but let the
    # structural count penalty raise the floor when custodians are few.
    score = 0.6 * share + 0.4 * count_penalty
    return _clamp(score)


def _attestation_freshness_score(attestation_age_days: float) -> float:
    """
    0-100: higher = fresher proof-of-reserve attestation.

    0 days → 100, 30 days → ~67, >= 90 days → 0. Linear decay from a fresh
    attestation down to a 90-day staleness horizon.
    """
    age = max(0.0, attestation_age_days)
    if age >= 90.0:
        return 0.0
    return _clamp(100.0 * (1.0 - age / 90.0))


def _backing_risk_score(
    collateral_shortfall_pct: float,
    custodian_concentration_score: float,
    attestation_freshness_score: float,
    can_redeem: bool,
    is_audited: bool,
) -> float:
    """
    0-100: higher = riskier.

    Shortfall is the dominant driver; custodian concentration and stale
    attestation add structural risk; missing redemption and missing audit
    add fixed penalties.
    """
    # Shortfall dominant (a 50% shortfall already contributes ~50).
    shortfall_component = _clamp(collateral_shortfall_pct) * 1.0

    # Concentration contributes up to ~20.
    concentration_component = custodian_concentration_score * 0.20

    # Stale attestation: (100 - freshness) up to ~15.
    staleness_component = (100.0 - _clamp(attestation_freshness_score)) * 0.15

    # Fixed penalties.
    redemption_penalty = 0.0 if can_redeem else 15.0
    audit_penalty = 0.0 if is_audited else 10.0

    score = (
        shortfall_component
        + concentration_component
        + staleness_component
        + redemption_penalty
        + audit_penalty
    )
    return _clamp(score)


def _classification(backing_ratio_pct: float, backing_risk_score: float,
                    has_data: bool) -> str:
    """
    Classify the asset, driven primarily by backing ratio with the risk
    score used to nudge borderline cases.

    Bands (on backing_ratio_pct):
      >= 100  → FULLY_BACKED
      99-100  → WELL_BACKED
      90-99   → PARTIALLY_BACKED
      75-90   → UNDERBACKED
      < 75    → CRITICAL_SHORTFALL
    A high risk score downgrades a notch even when the ratio looks healthy.
    """
    if not has_data:
        return CLASS_CRITICAL_SHORTFALL

    if backing_ratio_pct >= 100.0:
        base = CLASS_FULLY_BACKED
    elif backing_ratio_pct >= 99.0:
        base = CLASS_WELL_BACKED
    elif backing_ratio_pct >= 90.0:
        base = CLASS_PARTIALLY_BACKED
    elif backing_ratio_pct >= 75.0:
        base = CLASS_UNDERBACKED
    else:
        base = CLASS_CRITICAL_SHORTFALL

    # Risk-based downgrade for otherwise-healthy-looking assets.
    order = list(ALL_CLASSIFICATIONS)
    idx = order.index(base)
    if backing_risk_score >= 60.0 and idx < len(order) - 1:
        idx += 1
    return order[idx]


def _grade(backing_risk_score: float) -> str:
    """Map backing_risk_score (higher = riskier) to a letter grade A-F."""
    s = backing_risk_score
    if s < 10.0:
        return "A"
    if s < 25.0:
        return "B"
    if s < 45.0:
        return "C"
    if s < 70.0:
        return "D"
    return "F"


def _flags(
    backing_ratio_pct: float,
    custodian_count: int,
    custodian_concentration_score: float,
    attestation_freshness_score: float,
    can_redeem: bool,
    redemption_fee_pct: float,
    is_audited: bool,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags for this asset."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if backing_ratio_pct < 100.0:
        flags.append(FLAG_UNDERBACKED)
    else:
        flags.append(FLAG_FULLY_BACKED)

    if backing_ratio_pct > 105.0:
        flags.append(FLAG_OVERCOLLATERALIZED)

    if custodian_count == 1:
        flags.append(FLAG_SINGLE_CUSTODIAN)

    if custodian_concentration_score >= 70.0:
        flags.append(FLAG_HIGH_CUSTODIAN_CONCENTRATION)

    if attestation_freshness_score <= 40.0:
        flags.append(FLAG_STALE_ATTESTATION)

    if not can_redeem:
        flags.append(FLAG_NO_REDEMPTION)

    if redemption_fee_pct > 0.0:
        flags.append(FLAG_REDEMPTION_FEE)

    if not is_audited:
        flags.append(FLAG_UNAUDITED)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    backing_ratio_pct: float,
    collateral_shortfall_pct: float,
    custodian_concentration_score: float,
    attestation_freshness_score: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: wrapped supply and/or reserve balance are "
            "missing or invalid. Backing cannot be verified."
        )
        return recs

    if classification == CLASS_CRITICAL_SHORTFALL:
        recs.append(
            f"CRITICAL: backing ratio {backing_ratio_pct:.1f}% leaves a "
            f"{collateral_shortfall_pct:.1f}% shortfall. Reserves do not cover "
            "circulating wrapped supply — avoid or exit."
        )
    elif classification == CLASS_UNDERBACKED:
        recs.append(
            f"Underbacked: backing ratio {backing_ratio_pct:.1f}% "
            f"({collateral_shortfall_pct:.1f}% shortfall). Size positions small "
            "and monitor reserve attestations closely."
        )
    elif classification == CLASS_PARTIALLY_BACKED:
        recs.append(
            f"Partially backed: backing ratio {backing_ratio_pct:.1f}%. Backing "
            "is close to but below 1:1; verify whether the gap is transient."
        )
    elif classification == CLASS_WELL_BACKED:
        recs.append(
            f"Well backed: backing ratio {backing_ratio_pct:.1f}%, essentially "
            "1:1. Backing risk is low subject to custody and attestation quality."
        )
    else:  # FULLY_BACKED
        recs.append(
            f"Fully backed: backing ratio {backing_ratio_pct:.1f}% covers "
            "circulating wrapped supply. Backing risk is minimal."
        )

    if FLAG_SINGLE_CUSTODIAN in flags:
        recs.append(
            "Single custodian holds all reserves — a single point of failure. "
            "Prefer wrapped assets with diversified, multi-custodian backing."
        )
    elif FLAG_HIGH_CUSTODIAN_CONCENTRATION in flags:
        recs.append(
            f"High custodian concentration ({custodian_concentration_score:.0f}/100). "
            "One actor controls most reserves; monitor custodian solvency."
        )

    if FLAG_STALE_ATTESTATION in flags:
        recs.append(
            f"Proof-of-reserve attestation is stale (freshness "
            f"{attestation_freshness_score:.0f}/100). Treat the stated reserve "
            "balance with caution until a fresh attestation is published."
        )

    if FLAG_NO_REDEMPTION in flags:
        recs.append(
            "Redemption to the underlying asset is unavailable — the wrapped "
            "token cannot be reliably unwound at par."
        )

    if FLAG_REDEMPTION_FEE in flags:
        recs.append(
            "A redemption fee applies; effective redemption value is below the "
            "nominal 1:1 backing."
        )

    if FLAG_UNAUDITED in flags:
        recs.append(
            "Reserves are unaudited. Independent attestation materially reduces "
            "backing uncertainty."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(asset: dict, config: dict | None = None) -> dict:
    """
    Verify the reserve backing of a single wrapped / bridged token.

    Parameters
    ----------
    asset : dict
        Recognised keys (all with safe defaults):
        - name / symbol               : str
        - wrapped_supply              : float (units in circulation)
        - reserve_balance             : float (units of underlying held)
        - custodian_count             : int   (>= 0)
        - largest_custodian_share_pct : float (0-100)
        - attestation_age_days        : float (age of latest proof-of-reserve)
        - can_redeem                  : bool  (default True)
        - redemption_fee_pct          : float (default 0)
        - is_audited                  : bool  (default False)
    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    if not isinstance(asset, dict):
        asset = {}

    name = str(asset.get("name", asset.get("symbol", "UNKNOWN")))
    symbol = str(asset.get("symbol", asset.get("name", "UNKNOWN")))

    wrapped_supply = _safe_float(asset.get("wrapped_supply", 0.0))
    reserve_balance = _safe_float(asset.get("reserve_balance", 0.0))
    custodian_count = max(0, _safe_int(asset.get("custodian_count", 0)))
    largest_share = _clamp(_safe_float(asset.get("largest_custodian_share_pct", 0.0)))
    attestation_age_days = max(0.0, _safe_float(asset.get("attestation_age_days", 0.0)))
    can_redeem = bool(asset.get("can_redeem", True))
    redemption_fee_pct = max(0.0, _safe_float(asset.get("redemption_fee_pct", 0.0)))
    is_audited = bool(asset.get("is_audited", False))

    # Data sufficiency: need a positive wrapped supply and non-negative reserve.
    has_data = wrapped_supply > 0 and reserve_balance >= 0

    backing_ratio = _backing_ratio_pct(wrapped_supply, reserve_balance)
    shortfall = _collateral_shortfall_pct(backing_ratio)
    concentration = _custodian_concentration_score(custodian_count, largest_share)
    freshness = _attestation_freshness_score(attestation_age_days)
    risk = _backing_risk_score(
        shortfall, concentration, freshness, can_redeem, is_audited
    )
    classification = _classification(backing_ratio, risk, has_data)
    grade = _grade(risk)
    flags = _flags(
        backing_ratio,
        custodian_count,
        concentration,
        freshness,
        can_redeem,
        redemption_fee_pct,
        is_audited,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        backing_ratio,
        shortfall,
        concentration,
        freshness,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name,
        "symbol": symbol,
        "wrapped_supply": wrapped_supply,
        "reserve_balance": reserve_balance,
        "custodian_count": custodian_count,
        "largest_custodian_share_pct": largest_share,
        "attestation_age_days": attestation_age_days,
        "can_redeem": can_redeem,
        "redemption_fee_pct": redemption_fee_pct,
        "is_audited": is_audited,
        "backing_ratio_pct": backing_ratio,
        "collateral_shortfall_pct": shortfall,
        "custodian_concentration_score": concentration,
        "attestation_freshness_score": freshness,
        "backing_risk_score": risk,
        "classification": classification,
        "grade": grade,
        "flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


def analyze_portfolio(assets: list, config: dict | None = None) -> dict:
    """
    Verify backing across a batch of wrapped assets and summarise.

    Returns
    -------
    dict
        - total_assets           : int
        - avg_backing_risk_score : float
        - underbacked_count      : int  (backing_ratio_pct < 100)
        - safest_asset           : dict | None (lowest backing_risk_score)
        - riskiest_asset         : dict | None (highest backing_risk_score)
        - results                : list[dict]  (per-asset analysis)
        - timestamp              : float
    """
    if not isinstance(assets, list):
        assets = []

    results = [analyze(a, config=config) for a in assets]
    total = len(results)

    if total == 0:
        return {
            "total_assets": 0,
            "avg_backing_risk_score": 0.0,
            "underbacked_count": 0,
            "safest_asset": None,
            "riskiest_asset": None,
            "results": [],
            "timestamp": time.time(),
        }

    avg_risk = sum(r["backing_risk_score"] for r in results) / total
    underbacked = sum(1 for r in results if r["backing_ratio_pct"] < 100.0)
    safest = min(results, key=lambda r: r["backing_risk_score"])
    riskiest = max(results, key=lambda r: r["backing_risk_score"])

    return {
        "total_assets": total,
        "avg_backing_risk_score": avg_risk,
        "underbacked_count": underbacked,
        "safest_asset": safest,
        "riskiest_asset": riskiest,
        "results": results,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiWrappedAssetBackingVerifier:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> v = ProtocolDeFiWrappedAssetBackingVerifier()
    >>> r = v.analyze({"symbol": "wBTC", "wrapped_supply": 1000, ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, asset: dict) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(asset, config=self._config)

    def analyze_portfolio(self, assets: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(assets, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "name": "Wrapped BTC",
        "symbol": "wBTC",
        "wrapped_supply": 130_000.0,
        "reserve_balance": 129_500.0,
        "custodian_count": 1,
        "largest_custodian_share_pct": 100.0,
        "attestation_age_days": 45.0,
        "can_redeem": True,
        "redemption_fee_pct": 0.0,
        "is_audited": True,
    }

    import json as _json
    print(_json.dumps(analyze(_demo), indent=2, default=str))
    sys.exit(0)

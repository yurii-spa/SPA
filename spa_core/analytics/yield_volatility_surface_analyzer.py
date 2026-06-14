"""
MP-864 YieldVolatilitySurfaceAnalyzer
Advisory/read-only. Pure stdlib. No external dependencies.

Builds a volatility surface for DeFi yields — shows how yield volatility
behaves across different protocols and time horizons (short / medium / long
term), helping identify stable vs. volatile yield sources.

Data log: data/yield_volatility_surface_log.json (ring-buffer 100, atomic write)
"""

import json
import math
import os
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_volatility_surface_log.json"
)
_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _mean(samples: list) -> float:
    """Population mean; 0.0 for empty list."""
    if not samples:
        return 0.0
    return sum(samples) / len(samples)


def _population_std(samples: list) -> float:
    """Population std dev; 0.0 if fewer than 2 samples."""
    if len(samples) < 2:
        return 0.0
    mu = _mean(samples)
    variance = sum((x - mu) ** 2 for x in samples) / len(samples)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Term-structure classifier
# ---------------------------------------------------------------------------

def _vol_term_structure(vol_7d: float, vol_30d: float, vol_90d: float) -> str:
    """
    Classify the shape of the volatility term structure.

    Precedence (highest first):
    1. HUMPED  — vol_30d > vol_7d AND vol_30d > vol_90d
    2. FLAT    — max - min < 0.2
    3. NORMAL  — vol_7d > vol_90d (short > long)
    4. INVERTED— vol_90d > vol_7d (long > short)
    """
    # 1. Humped: middle tenor is the most volatile
    if vol_30d > vol_7d and vol_30d > vol_90d:
        return "HUMPED"

    # 2. Flat: all tenors are nearly equal
    max_vol = max(vol_7d, vol_30d, vol_90d)
    min_vol = min(vol_7d, vol_30d, vol_90d)
    if (max_vol - min_vol) < 0.2:
        return "FLAT"

    # 3. Normal vs Inverted
    if vol_7d > vol_90d:
        return "NORMAL"
    return "INVERTED"


# ---------------------------------------------------------------------------
# Stability scoring
# ---------------------------------------------------------------------------

def _stability_score(vol_30d_pct: float) -> int:
    """0-100; higher = more stable (lower 30d vol)."""
    if vol_30d_pct <= 0.1:
        return 100
    if vol_30d_pct <= 0.3:
        return 85
    if vol_30d_pct <= 0.5:
        return 70
    if vol_30d_pct <= 1.0:
        return 50
    if vol_30d_pct <= 2.0:
        return 30
    if vol_30d_pct <= 5.0:
        return 15
    return 5


def _yield_category(score: int) -> str:
    if score >= 80:
        return "STABLE"
    if score >= 50:
        return "MODERATE"
    if score >= 20:
        return "VOLATILE"
    return "HIGHLY_VOLATILE"


# ---------------------------------------------------------------------------
# risk_adjusted metric
# ---------------------------------------------------------------------------

def _risk_adjusted_7d(mean_7d: float, vol_7d: float) -> float:
    """Sharpe-like: mean / vol; if vol == 0 treat as mean itself."""
    if vol_7d > 0:
        return mean_7d / vol_7d
    return mean_7d


# ---------------------------------------------------------------------------
# Surface label
# ---------------------------------------------------------------------------

def _surface_label(protocol: str, asset: str, yield_cat: str,
                   vol_30d: float, mean_30d: float) -> str:
    return (
        f"{protocol}/{asset}: {yield_cat} yield, "
        f"{vol_30d:.2f}% 30d vol, mean APY {mean_30d:.2f}%"
    )


# ---------------------------------------------------------------------------
# Log helper
# ---------------------------------------------------------------------------

def _log_result(result: dict) -> None:
    """Append result to ring-buffer log (cap 100), atomic write."""
    log_path = os.path.normpath(_LOG_PATH)
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        else:
            entries = []
    except Exception:
        entries = []

    entries.append(result)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    tmp_path = log_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(tmp_path, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(yield_series: list, config: dict = None) -> dict:
    """
    Build a volatility surface for DeFi yields across protocols.

    Parameters
    ----------
    yield_series : list of dicts with keys:
        protocol, asset, apy_7d_samples, apy_30d_samples, apy_90d_samples
    config : unused (reserved for future extension)

    Returns
    -------
    dict with protocols, most_stable, most_volatile, stable_protocols,
    average_stability_score, timestamp
    """
    protocols_out = []

    for entry in yield_series:
        protocol = str(entry.get("protocol", ""))
        asset = str(entry.get("asset", ""))
        s7 = list(entry.get("apy_7d_samples", []))
        s30 = list(entry.get("apy_30d_samples", []))
        s90 = list(entry.get("apy_90d_samples", []))

        vol_7d = _population_std(s7)
        vol_30d = _population_std(s30)
        vol_90d = _population_std(s90)

        mean_7d = _mean(s7)
        mean_30d = _mean(s30)
        mean_90d = _mean(s90)

        term_structure = _vol_term_structure(vol_7d, vol_30d, vol_90d)
        ra_7d = _risk_adjusted_7d(mean_7d, vol_7d)
        score = _stability_score(vol_30d)
        category = _yield_category(score)
        label = _surface_label(protocol, asset, category, vol_30d, mean_30d)

        protocols_out.append({
            "protocol": protocol,
            "asset": asset,
            "vol_7d_pct": round(vol_7d, 6),
            "vol_30d_pct": round(vol_30d, 6),
            "vol_90d_pct": round(vol_90d, 6),
            "mean_7d_apy": round(mean_7d, 6),
            "mean_30d_apy": round(mean_30d, 6),
            "mean_90d_apy": round(mean_90d, 6),
            "vol_term_structure": term_structure,
            "risk_adjusted_7d": round(ra_7d, 6),
            "stability_score": score,
            "yield_category": category,
            "surface_label": label,
        })

    # Aggregate
    most_stable: Optional[str] = None
    most_volatile: Optional[str] = None
    stable_protocols: list = []
    avg_stability = 0.0

    if protocols_out:
        best = max(protocols_out, key=lambda x: x["stability_score"])
        worst = min(protocols_out, key=lambda x: x["stability_score"])
        most_stable = f"{best['protocol']} ({best['asset']})"
        most_volatile = f"{worst['protocol']} ({worst['asset']})"

        stable_protocols = [
            f"{p['protocol']} ({p['asset']})"
            for p in protocols_out
            if p["yield_category"] in ("STABLE", "MODERATE")
        ]

        avg_stability = round(
            sum(p["stability_score"] for p in protocols_out) / len(protocols_out), 2
        )

    result = {
        "protocols": protocols_out,
        "most_stable": most_stable,
        "most_volatile": most_volatile,
        "stable_protocols": stable_protocols,
        "average_stability_score": avg_stability,
        "timestamp": time.time(),
    }

    _log_result(result)
    return result

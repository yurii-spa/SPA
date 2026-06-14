"""
MP-891 DeFiYieldSourceVerifier
Verifies legitimacy of yield sources — distinguishes real protocol revenue
from token emission inflation.

Advisory / read-only. Pure stdlib. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
import tempfile
from typing import Any

_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_source_verification_log.json"
)
_DEFAULT_DATA_FILE = os.path.normpath(_DEFAULT_DATA_FILE)

_RING_BUFFER_CAP = 100
_DEFAULT_MIN_REAL_YIELD = 3.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sell_pressure_penalty(sell_pressure: str) -> int:
    """Return penalty for emission_token_sell_pressure."""
    return {
        "LOW": 0,
        "MODERATE": 10,
        "HIGH": 25,
        "EXTREME": 45,
    }.get(str(sell_pressure).upper(), 0)


def _price_penalty(token_price_change_90d_pct: float) -> int:
    """Return penalty based on token price change over 90 days."""
    if token_price_change_90d_pct < -50:
        return 30
    if token_price_change_90d_pct < -20:
        return 20
    if token_price_change_90d_pct < 0:
        return 10
    return 0


def _emission_sustainability_score(
    sell_pressure: str, token_price_change_90d_pct: float
) -> int:
    """Compute emission sustainability score 0-100 (higher = more sustainable)."""
    base = 100 - _sell_pressure_penalty(sell_pressure) - _price_penalty(token_price_change_90d_pct)
    return max(0, min(100, base))


def _yield_authenticity(real_yield_ratio: float) -> str:
    """Classify yield authenticity based on real_yield_ratio (0-100)."""
    if real_yield_ratio >= 70:
        return "GENUINE"
    if real_yield_ratio >= 40:
        return "MIXED"
    if real_yield_ratio >= 20:
        return "EMISSION_DRIVEN"
    return "UNSUSTAINABLE"


def _sustainability_risk(score: int) -> str:
    """Derive sustainability_risk from emission_sustainability_score."""
    if score >= 70:
        return "LOW"
    if score >= 50:
        return "MODERATE"
    if score >= 30:
        return "HIGH"
    return "CRITICAL"


def _build_flags(
    real_revenue_apy_pct: float,
    min_real_yield_pct: float,
    sell_pressure: str,
    token_price_change_90d_pct: float,
    revenue_yield_pct: float,
    real_revenue_apy_pct_raw: float,
    total_tvl_usd: float,
) -> list:
    flags = []
    if real_revenue_apy_pct < min_real_yield_pct:
        flags.append("BELOW_MIN_REAL_YIELD")
    if str(sell_pressure).upper() == "EXTREME":
        flags.append("EXTREME_SELL_PRESSURE")
    if token_price_change_90d_pct < -20:
        flags.append("FALLING_TOKEN_PRICE")
    # REVENUE_MISMATCH: abs(revenue_yield_pct - real_revenue_apy_pct) > 5 and tvl > 0
    if total_tvl_usd > 0 and abs(revenue_yield_pct - real_revenue_apy_pct_raw) > 5:
        flags.append("REVENUE_MISMATCH")
    return flags


def _build_recommendation(
    authenticity: str,
    sustainability_risk: str,
    real_revenue_apy_pct: float,
    real_yield_ratio: float,
) -> str:
    if authenticity == "GENUINE":
        if real_revenue_apy_pct >= 5:
            return (
                f"Strong genuine yield. {real_revenue_apy_pct:.1f}% real revenue APY."
            )
        return (
            f"Yield verified. Mostly fee-based. Real: {real_revenue_apy_pct:.1f}%."
        )
    if authenticity == "MIXED":
        return (
            f"Partial emission reliance. Real yield: {real_revenue_apy_pct:.1f}%. "
            f"Monitor token price."
        )
    if authenticity == "EMISSION_DRIVEN":
        return (
            f"Emission-dependent. Risk: {sustainability_risk}. "
            f"Real yield only {real_revenue_apy_pct:.1f}%."
        )
    # UNSUSTAINABLE
    emission_pct = 100 - real_yield_ratio
    return (
        f"Avoid. Yield is {emission_pct:.0f}% emission-based. HIGH exit risk."
    )


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze yield source legitimacy for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list[dict]
        Each entry must contain:
        - name (str)
        - claimed_apy_pct (float)
        - real_revenue_apy_pct (float)
        - token_emission_apy_pct (float)
        - token_price_change_90d_pct (float)
        - protocol_revenue_30d_usd (float)
        - total_tvl_usd (float)
        - emission_token_sell_pressure (str): "LOW" | "MODERATE" | "HIGH" | "EXTREME"
    config : dict, optional
        - min_real_yield_pct (float): default 3.0

    Returns
    -------
    dict with keys: protocols, average_real_yield_pct, genuine_count,
                    unsustainable_count, timestamp
    """
    if config is None:
        config = {}
    min_real_yield_pct = float(config.get("min_real_yield_pct", _DEFAULT_MIN_REAL_YIELD))

    if not protocols:
        return {
            "protocols": [],
            "average_real_yield_pct": 0.0,
            "genuine_count": 0,
            "unsustainable_count": 0,
            "timestamp": time.time(),
        }

    results = []
    for p in protocols:
        name = str(p.get("name", ""))
        claimed_apy = float(p.get("claimed_apy_pct", 0.0))
        real_revenue_apy = float(p.get("real_revenue_apy_pct", 0.0))
        emission_apy = float(p.get("token_emission_apy_pct", 0.0))
        token_price_change = float(p.get("token_price_change_90d_pct", 0.0))
        revenue_30d = float(p.get("protocol_revenue_30d_usd", 0.0))
        tvl = float(p.get("total_tvl_usd", 0.0))
        sell_pressure = str(p.get("emission_token_sell_pressure", "LOW"))

        # Core metrics
        real_yield_ratio = (
            real_revenue_apy / claimed_apy * 100 if claimed_apy > 0 else 0.0
        )
        revenue_yield_pct = (
            revenue_30d * 12 / tvl * 100 if tvl > 0 else 0.0
        )
        ess = _emission_sustainability_score(sell_pressure, token_price_change)
        authenticity = _yield_authenticity(real_yield_ratio)
        sust_risk = _sustainability_risk(ess)
        flags = _build_flags(
            real_revenue_apy,
            min_real_yield_pct,
            sell_pressure,
            token_price_change,
            revenue_yield_pct,
            real_revenue_apy,
            tvl,
        )
        recommendation = _build_recommendation(
            authenticity, sust_risk, real_revenue_apy, real_yield_ratio
        )

        results.append({
            "name": name,
            "claimed_apy_pct": claimed_apy,
            "real_yield_pct": real_revenue_apy,
            "emission_yield_pct": emission_apy,
            "real_yield_ratio": real_yield_ratio,
            "revenue_yield_pct": revenue_yield_pct,
            "emission_sustainability_score": ess,
            "yield_authenticity": authenticity,
            "sustainability_risk": sust_risk,
            "flags": flags,
            "recommendation": recommendation,
        })

    # Aggregates
    avg_real_yield = (
        sum(r["real_yield_pct"] for r in results) / len(results)
        if results else 0.0
    )
    genuine_count = sum(1 for r in results if r["yield_authenticity"] == "GENUINE")
    unsustainable_count = sum(
        1 for r in results if r["yield_authenticity"] == "UNSUSTAINABLE"
    )

    return {
        "protocols": results,
        "average_real_yield_pct": avg_real_yield,
        "genuine_count": genuine_count,
        "unsustainable_count": unsustainable_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_log(path: str) -> list:
    """Load existing JSON log; return [] on missing/corrupt."""
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _atomic_write(path: str, data: Any) -> None:
    """Write data to path atomically via tmp file + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def log_result(result: dict, data_file: str = None) -> None:
    """Append an analyze() result to the ring-buffer log (max 100 entries)."""
    path = data_file or _DEFAULT_DATA_FILE
    log = _load_log(path)
    log.append(result)
    if len(log) > _RING_BUFFER_CAP:
        log = log[-_RING_BUFFER_CAP:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo():
    sample = [
        {
            "name": "Aave V3",
            "claimed_apy_pct": 5.5,
            "real_revenue_apy_pct": 4.8,
            "token_emission_apy_pct": 0.7,
            "token_price_change_90d_pct": 5.0,
            "protocol_revenue_30d_usd": 4_000_000,
            "total_tvl_usd": 1_000_000_000,
            "emission_token_sell_pressure": "LOW",
        },
        {
            "name": "FarmCoin",
            "claimed_apy_pct": 120.0,
            "real_revenue_apy_pct": 2.0,
            "token_emission_apy_pct": 118.0,
            "token_price_change_90d_pct": -60.0,
            "protocol_revenue_30d_usd": 50_000,
            "total_tvl_usd": 30_000_000,
            "emission_token_sell_pressure": "EXTREME",
        },
    ]
    result = analyze(sample)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _demo()

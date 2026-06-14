"""
MP-892 ProtocolMarketCapToTVLAnalyzer
Analyzes market cap / TVL ratio to identify DeFi tokens that are
over/undervalued relative to the capital they manage.

Advisory / read-only. Pure stdlib. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
import tempfile
from typing import Any, Optional

_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "mcap_tvl_log.json"
)
_DEFAULT_DATA_FILE = os.path.normpath(_DEFAULT_DATA_FILE)

_RING_BUFFER_CAP = 100
_DEFAULT_UNDERVALUED_THRESHOLD = 0.5
_DEFAULT_OVERVALUED_THRESHOLD = 3.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _valuation_label(mc_to_tvl: float, undervalued_threshold: float, overvalued_threshold: float) -> str:
    """Classify protocol valuation based on mc_to_tvl ratio."""
    if mc_to_tvl < 0:  # -1 signals no TVL data
        return "UNANALYZABLE"
    if mc_to_tvl < 0.25:
        return "DEEPLY_UNDERVALUED"
    if mc_to_tvl < undervalued_threshold:
        return "UNDERVALUED"
    if mc_to_tvl < overvalued_threshold:
        return "FAIR_VALUE"
    if mc_to_tvl < 10.0:
        return "OVERVALUED"
    return "EXTREMELY_OVERVALUED"


def _dilution_risk(token_circulating_pct: float) -> str:
    """Classify dilution risk based on circulating supply percentage."""
    if token_circulating_pct > 80:
        return "LOW"
    if token_circulating_pct > 50:
        return "MODERATE"
    if token_circulating_pct > 30:
        return "HIGH"
    return "CRITICAL"


def _revenue_multiple_label(price_to_revenue: float) -> str:
    """Classify price/revenue multiple."""
    if price_to_revenue < 0:  # -1 signals no revenue data
        return "NO_REVENUE"
    if price_to_revenue < 10:
        return "CHEAP"
    if price_to_revenue < 25:
        return "FAIR"
    if price_to_revenue < 50:
        return "EXPENSIVE"
    return "VERY_EXPENSIVE"


def _valuation_score(label: str) -> int:
    """Return valuation component for composite attractiveness."""
    return {
        "DEEPLY_UNDERVALUED": 100,
        "UNDERVALUED": 80,
        "FAIR_VALUE": 60,
        "OVERVALUED": 30,
        "EXTREMELY_OVERVALUED": 10,
        "UNANALYZABLE": 50,
    }.get(label, 50)


def _dilution_score(risk: str) -> int:
    """Return dilution component for composite attractiveness."""
    return {
        "LOW": 30,
        "MODERATE": 20,
        "HIGH": 10,
        "CRITICAL": 0,
    }.get(risk, 0)


def _revenue_score(label: str) -> int:
    """Return revenue component for composite attractiveness."""
    return {
        "CHEAP": 20,
        "FAIR": 15,
        "EXPENSIVE": 8,
        "VERY_EXPENSIVE": 3,
        "NO_REVENUE": 0,
    }.get(label, 0)


def _composite_attractiveness(val_label: str, dil_risk: str, rev_label: str) -> int:
    """Compute composite attractiveness score 0-100."""
    score = _valuation_score(val_label) + _dilution_score(dil_risk) + _revenue_score(rev_label)
    return min(100, score)


def _build_recommendation(
    composite: int,
    valuation_label: str,
    mc_to_tvl: float,
    revenue_multiple_label: str,
    dilution_risk: str,
) -> str:
    """Build human-readable recommendation string."""
    if valuation_label == "UNANALYZABLE":
        return "Insufficient TVL data for valuation analysis."
    if composite >= 85:
        return (
            f"Highly attractive. {mc_to_tvl:.2f}x MC/TVL with "
            f"{revenue_multiple_label} revenue multiple."
        )
    if composite >= 65:
        return (
            f"Solid value. MC/TVL: {mc_to_tvl:.2f}x. "
            f"Consider for portfolio exposure."
        )
    if composite >= 45:
        return (
            f"Fair valuation. {valuation_label}. "
            f"Watch dilution: {dilution_risk} risk."
        )
    return (
        f"Avoid. {valuation_label} at {mc_to_tvl:.2f}x MC/TVL. "
        f"{dilution_risk} dilution risk."
    )


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze market cap / TVL ratio for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list[dict]
        Each entry must contain:
        - name (str)
        - market_cap_usd (float)
        - fully_diluted_valuation_usd (float)
        - tvl_usd (float)
        - revenue_30d_usd (float)
        - token_circulating_pct (float)  — % of total supply in circulation
        - sector (str): "LENDING" | "DEX" | "YIELD" | "BRIDGE" | "STAKING" | "OTHER"
    config : dict, optional
        - undervalued_threshold (float): default 0.5
        - overvalued_threshold (float): default 3.0

    Returns
    -------
    dict with keys: protocols, by_sector, most_attractive, most_overvalued,
                    market_avg_mc_to_tvl, timestamp
    """
    if config is None:
        config = {}
    undervalued_thr = float(config.get("undervalued_threshold", _DEFAULT_UNDERVALUED_THRESHOLD))
    overvalued_thr = float(config.get("overvalued_threshold", _DEFAULT_OVERVALUED_THRESHOLD))

    if not protocols:
        return {
            "protocols": [],
            "by_sector": {},
            "most_attractive": None,
            "most_overvalued": None,
            "market_avg_mc_to_tvl": 0.0,
            "timestamp": time.time(),
        }

    results = []
    for p in protocols:
        name = str(p.get("name", ""))
        market_cap = float(p.get("market_cap_usd", 0.0))
        fdv = float(p.get("fully_diluted_valuation_usd", 0.0))
        tvl = float(p.get("tvl_usd", 0.0))
        revenue_30d = float(p.get("revenue_30d_usd", 0.0))
        circulating_pct = float(p.get("token_circulating_pct", 100.0))
        sector = str(p.get("sector", "OTHER"))

        # Core ratios
        mc_to_tvl = market_cap / tvl if tvl > 0 else -1.0
        fdv_to_tvl = fdv / tvl if tvl > 0 else -1.0
        price_to_revenue = market_cap / (revenue_30d * 12) if revenue_30d > 0 else -1.0

        # Labels
        val_label = _valuation_label(mc_to_tvl, undervalued_thr, overvalued_thr)
        dil_risk = _dilution_risk(circulating_pct)
        rev_label = _revenue_multiple_label(price_to_revenue)

        # Composite score
        composite = _composite_attractiveness(val_label, dil_risk, rev_label)

        # Recommendation
        recommendation = _build_recommendation(
            composite, val_label, mc_to_tvl, rev_label, dil_risk
        )

        results.append({
            "name": name,
            "sector": sector,
            "mc_to_tvl": mc_to_tvl,
            "fdv_to_tvl": fdv_to_tvl,
            "price_to_revenue": price_to_revenue,
            "valuation_label": val_label,
            "dilution_risk": dil_risk,
            "revenue_multiple_label": rev_label,
            "composite_attractiveness": composite,
            "recommendation": recommendation,
        })

    # Aggregates
    # by_sector
    sector_data: dict = {}
    for r in results:
        sec = r["sector"]
        if sec not in sector_data:
            sector_data[sec] = {"ratios": [], "attractiveness": []}
        if r["mc_to_tvl"] > 0:
            sector_data[sec]["ratios"].append(r["mc_to_tvl"])
        sector_data[sec]["attractiveness"].append(r["composite_attractiveness"])

    by_sector = {}
    for sec, vals in sector_data.items():
        avg_mc = sum(vals["ratios"]) / len(vals["ratios"]) if vals["ratios"] else 0.0
        avg_att = sum(vals["attractiveness"]) / len(vals["attractiveness"])
        count = sum(1 for r in results if r["sector"] == sec)
        by_sector[sec] = {
            "avg_mc_to_tvl": avg_mc,
            "count": count,
            "avg_attractiveness": avg_att,
        }

    # most_attractive — highest composite_attractiveness
    most_attractive: Optional[str] = None
    if results:
        best = max(results, key=lambda r: r["composite_attractiveness"])
        most_attractive = best["name"]

    # most_overvalued — highest mc_to_tvl among those > 0
    positive_ratio = [r for r in results if r["mc_to_tvl"] > 0]
    most_overvalued: Optional[str] = None
    if positive_ratio:
        worst = max(positive_ratio, key=lambda r: r["mc_to_tvl"])
        most_overvalued = worst["name"]

    # market_avg_mc_to_tvl — mean of positive mc_to_tvl
    market_avg = (
        sum(r["mc_to_tvl"] for r in positive_ratio) / len(positive_ratio)
        if positive_ratio else 0.0
    )

    return {
        "protocols": results,
        "by_sector": by_sector,
        "most_attractive": most_attractive,
        "most_overvalued": most_overvalued,
        "market_avg_mc_to_tvl": market_avg,
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
            "name": "Aave",
            "market_cap_usd": 1_500_000_000,
            "fully_diluted_valuation_usd": 2_000_000_000,
            "tvl_usd": 15_000_000_000,
            "revenue_30d_usd": 10_000_000,
            "token_circulating_pct": 75.0,
            "sector": "LENDING",
        },
        {
            "name": "InflatedToken",
            "market_cap_usd": 5_000_000_000,
            "fully_diluted_valuation_usd": 20_000_000_000,
            "tvl_usd": 200_000_000,
            "revenue_30d_usd": 100_000,
            "token_circulating_pct": 25.0,
            "sector": "DEX",
        },
    ]
    result = analyze(sample)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _demo()

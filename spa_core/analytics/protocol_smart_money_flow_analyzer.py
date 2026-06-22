"""
MP-900 ProtocolSmartMoneyFlowAnalyzer  🏆 MILESTONE: 900th analytics module
Advisory/read-only analytics module.
Tracks "smart money" (large whale wallets, known funds) flow patterns into/out
of protocols to generate contrarian and momentum signals.

Data log: data/smart_money_flow_log.json (ring-buffer, max 100 entries)
Pure stdlib. No external dependencies.
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_CAP = 100

_DEFAULT_CONFIG = {
    "flow_significance_usd": 1_000_000.0,
}

# ---------------------------------------------------------------------------
# Scoring tables
# ---------------------------------------------------------------------------

_SMART_CONVICTION_SCORES = {
    "VERY_HIGH": 40,
    "HIGH":      30,
    "MODERATE":  20,
    "LOW":       10,
    "NEGATIVE":   0,
}

_RECENCY_SCORES = {
    "VERY_RECENT": 20,
    "RECENT":      15,
    "COOLING":      8,
    "COLD":         0,
}

_ALIGNMENT_SCORES = {
    "ALIGNED":     20,
    "NEUTRAL":     10,
    "CONTRARIAN":   0,
}

_CONCENTRATION_SCORES = {
    "HIGH":     20,
    "MODERATE": 15,
    "LOW":       8,
    "MINIMAL":   3,
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float) -> float:
    """Return numerator / denominator; 0.0 when denominator is zero."""
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _safe_mean(values: list) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _divergence_signal(
    net_smart: float,
    net_retail: float,
    flow_significance: float,
) -> str:
    """Classify flow divergence between smart and retail money."""
    abs_smart  = abs(net_smart)
    abs_retail = abs(net_retail)

    # Both flows are below the significance threshold → neutral noise
    if abs_smart < flow_significance and abs_retail < flow_significance:
        return "NEUTRAL"

    if net_smart > 0 and net_retail < 0:
        return "SMART_ACCUMULATING_RETAIL_EXITING"
    if net_smart < 0 and net_retail > 0:
        return "SMART_EXITING_RETAIL_BUYING"
    if net_smart > 0 and net_retail > 0:
        return "BOTH_ACCUMULATING"
    if net_smart < 0 and net_retail < 0:
        return "BOTH_EXITING"
    # One side is below significance, other side may be positive/negative
    return "NEUTRAL"


def _smart_money_conviction(smart_flow_ratio: float) -> str:
    """Classify conviction strength based on smart flow as % of TVL."""
    if smart_flow_ratio > 5:
        return "VERY_HIGH"
    if smart_flow_ratio > 2:
        return "HIGH"
    if smart_flow_ratio > 0.5:
        return "MODERATE"
    if smart_flow_ratio > 0:
        return "LOW"
    return "NEGATIVE"


def _large_wallet_concentration(smart_money_tvl_pct: float) -> str:
    """Classify concentration of smart wallets in protocol TVL."""
    if smart_money_tvl_pct > 50:
        return "HIGH"
    if smart_money_tvl_pct > 25:
        return "MODERATE"
    if smart_money_tvl_pct > 10:
        return "LOW"
    return "MINIMAL"


def _recency_signal(days_since: int) -> str:
    """Classify how recent the last large deposit was."""
    if days_since < 3:
        return "VERY_RECENT"
    if days_since < 14:
        return "RECENT"
    if days_since < 30:
        return "COOLING"
    return "COLD"


def _price_alignment(correlation: float) -> str:
    """Classify whether smart-flow correlates with price moves."""
    if correlation > 0.3:
        return "ALIGNED"
    if correlation > -0.3:
        return "NEUTRAL"
    return "CONTRARIAN"


def _composite_score(
    conviction: str,
    recency: str,
    alignment: str,
    concentration: str,
) -> int:
    score = (
        _SMART_CONVICTION_SCORES[conviction]
        + _RECENCY_SCORES[recency]
        + _ALIGNMENT_SCORES[alignment]
        + _CONCENTRATION_SCORES[concentration]
    )
    return max(0, min(100, score))


def _signal_label(composite: int) -> str:
    if composite >= 75:
        return "STRONG_BUY"
    if composite >= 60:
        return "BUY"
    if composite >= 40:
        return "NEUTRAL"
    if composite >= 25:
        return "CAUTION"
    return "SELL"


def _build_flags(
    conviction: str,
    net_smart_flow: float,
    divergence: str,
    recency: str,
    flow_significance: float,
) -> list:
    flags = []
    if conviction in ("VERY_HIGH", "HIGH") and net_smart_flow > 0:
        flags.append("WHALE_ACCUMULATION")
    if net_smart_flow < -flow_significance:
        flags.append("SMART_EXIT")
    if divergence == "SMART_EXITING_RETAIL_BUYING":
        flags.append("DIVERGENCE_WARNING")
    if recency == "COLD":
        flags.append("STALE_SIGNAL")
    return flags


def _recommendation(
    signal: str,
    net_smart_flow: float,
    conviction: str,
    composite: int,
    alignment: str,
) -> str:
    if signal == "STRONG_BUY":
        return (
            f"Strong smart money accumulation. "
            f"Net flow: ${net_smart_flow:,.0f}. "
            f"Conviction: {conviction}."
        )
    if signal == "BUY":
        return (
            f"Positive smart money signal. "
            f"Score: {composite}. "
            f"Consider entry."
        )
    if signal == "NEUTRAL":
        return (
            f"Mixed signals. Monitor for clearer direction. "
            f"Price alignment: {alignment}."
        )
    if signal == "CAUTION":
        return (
            f"Smart money cautious or exiting. "
            f"Net flow: ${net_smart_flow:,.0f}."
        )
    # SELL
    return (
        "Negative signal. Smart money exiting, stale activity. "
        "Review position."
    )


def _analyse_protocol(proto: dict, flow_significance: float) -> dict:
    name                         = proto.get("name", "")
    smart_inflow                 = float(proto.get("smart_wallet_inflow_30d_usd", 0.0))
    smart_outflow                = float(proto.get("smart_wallet_outflow_30d_usd", 0.0))
    retail_inflow                = float(proto.get("retail_inflow_30d_usd", 0.0))
    retail_outflow               = float(proto.get("retail_outflow_30d_usd", 0.0))
    large_wallet_count           = int(proto.get("large_wallet_count", 0))
    total_tvl_usd                = float(proto.get("total_tvl_usd", 0.0))
    smart_money_tvl_pct          = float(proto.get("smart_money_tvl_pct", 0.0))
    days_since_last_large_deposit = int(proto.get("days_since_last_large_deposit", 999))
    price_correlation_30d        = float(proto.get("price_correlation_30d", 0.0))

    net_smart_flow  = smart_inflow  - smart_outflow
    net_retail_flow = retail_inflow - retail_outflow

    smart_flow_ratio  = _safe_div(net_smart_flow,  total_tvl_usd) * 100
    retail_flow_ratio = _safe_div(net_retail_flow, total_tvl_usd) * 100

    divergence   = _divergence_signal(net_smart_flow, net_retail_flow, flow_significance)
    conviction   = _smart_money_conviction(smart_flow_ratio)
    concentration = _large_wallet_concentration(smart_money_tvl_pct)
    recency      = _recency_signal(days_since_last_large_deposit)
    alignment    = _price_alignment(price_correlation_30d)

    composite = _composite_score(conviction, recency, alignment, concentration)
    signal    = _signal_label(composite)
    flags     = _build_flags(conviction, net_smart_flow, divergence,
                              recency, flow_significance)
    recom     = _recommendation(signal, net_smart_flow, conviction, composite, alignment)

    return {
        "name":                       name,
        "net_smart_flow_usd":         net_smart_flow,
        "net_retail_flow_usd":        net_retail_flow,
        "smart_flow_ratio":           smart_flow_ratio,
        "retail_flow_ratio":          retail_flow_ratio,
        "divergence_signal":          divergence,
        "smart_money_conviction":     conviction,
        "large_wallet_concentration": concentration,
        "recency_signal":             recency,
        "price_alignment":            alignment,
        "composite_bullish_score":    composite,
        "signal_label":               signal,
        "flags":                      flags,
        "recommendation":             recom,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyse smart money flow patterns across a list of protocols.

    Parameters
    ----------
    protocols : list[dict]
        Each dict has keys: name, smart_wallet_inflow_30d_usd,
        smart_wallet_outflow_30d_usd, retail_inflow_30d_usd,
        retail_outflow_30d_usd, large_wallet_count, total_tvl_usd,
        smart_money_tvl_pct, days_since_last_large_deposit,
        price_correlation_30d.
    config : dict, optional
        Accepts ``flow_significance_usd`` (default 1_000_000).

    Returns
    -------
    dict
        Full analysis with per-protocol signals and aggregates.
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    flow_significance = float(cfg.get("flow_significance_usd", 1_000_000.0))

    if not protocols:
        return {
            "protocols":            [],
            "strongest_buy_signal": None,
            "strongest_sell_signal": None,
            "average_bullish_score": 0.0,
            "accumulation_count":   0,
            "timestamp":            time.time(),
        }

    analysed = [_analyse_protocol(p, flow_significance) for p in protocols]

    scores = [p["composite_bullish_score"] for p in analysed]
    best_idx  = scores.index(max(scores))
    worst_idx = scores.index(min(scores))

    average_bullish_score = _safe_mean(scores)
    accumulation_count = sum(
        1 for p in analysed
        if p["smart_money_conviction"] in ("VERY_HIGH", "HIGH")
    )

    return {
        "protocols":            analysed,
        "strongest_buy_signal":  analysed[best_idx]["name"],
        "strongest_sell_signal": analysed[worst_idx]["name"],
        "average_bullish_score": average_bullish_score,
        "accumulation_count":   accumulation_count,
        "timestamp":            time.time(),
    }


def log_result(result: dict, data_dir: str = None) -> None:
    """
    Append an analysis result to the ring-buffer log.

    Parameters
    ----------
    result : dict
        Return value of ``analyze()``.
    data_dir : str, optional
        Directory for the log file.  Defaults to ``data/`` next to repo root.
    """
    if data_dir is None:
        _here = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(_here, "..", "..", "data")

    log_path = os.path.join(data_dir, "smart_money_flow_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    os.makedirs(data_dir, exist_ok=True)
    atomic_save(log, str(log_path))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-900 ProtocolSmartMoneyFlowAnalyzer (MILESTONE)"
    )
    parser.add_argument("--check", action="store_true",
                        help="Compute and print without writing (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and write to data/smart_money_flow_log.json")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory")
    args = parser.parse_args()

    _DEMO = [
        {
            "name": "Aave V3",
            "smart_wallet_inflow_30d_usd": 8_000_000.0,
            "smart_wallet_outflow_30d_usd": 2_000_000.0,
            "retail_inflow_30d_usd": 500_000.0,
            "retail_outflow_30d_usd": 800_000.0,
            "large_wallet_count": 42,
            "total_tvl_usd": 120_000_000.0,
            "smart_money_tvl_pct": 35.0,
            "days_since_last_large_deposit": 5,
            "price_correlation_30d": 0.55,
        },
        {
            "name": "Compound V3",
            "smart_wallet_inflow_30d_usd": 500_000.0,
            "smart_wallet_outflow_30d_usd": 3_000_000.0,
            "retail_inflow_30d_usd": 2_000_000.0,
            "retail_outflow_30d_usd": 400_000.0,
            "large_wallet_count": 8,
            "total_tvl_usd": 40_000_000.0,
            "smart_money_tvl_pct": 12.0,
            "days_since_last_large_deposit": 45,
            "price_correlation_30d": -0.6,
        },
    ]

    result = analyze(_DEMO)
    print(json.dumps(result, indent=2))

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print("[MP-900] Result written to smart_money_flow_log.json")

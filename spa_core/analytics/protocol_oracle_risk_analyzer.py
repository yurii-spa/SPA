"""
MP-888 ProtocolOracleRiskAnalyzer
Advisory/read-only analytics module.
Analyzes oracle risk for DeFi protocols — manipulation resistance,
TWAP vs spot, staleness risk, circuit breakers.

Data log: data/oracle_risk_log.json (ring-buffer, max 100 entries)
Pure stdlib. No external dependencies.
"""

import json
import os
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_CAP = 100

_DEFAULT_CONFIG = {
    "large_tvl_threshold_usd": 50_000_000.0,
}

# oracle_type → base manipulation resistance score
_ORACLE_TYPE_BASE = {
    "CHAINLINK": 80,
    "PYTH":      70,
    "REDSTONE":  65,
    "TWAP":      60,
    "INTERNAL":  30,
    "CUSTOM":    20,
}

_RISK_LABELS = [
    (20,  "MINIMAL"),
    (35,  "LOW"),
    (55,  "MODERATE"),
    (75,  "HIGH"),
]   # > 75 → "CRITICAL"

_TVL_LABELS = [
    (10_000_000.0,  "LOW"),
    (50_000_000.0,  "MEDIUM"),
    (200_000_000.0, "HIGH"),
]   # >= 200M → "CRITICAL"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _manipulation_resistance_score(
    oracle_type: str,
    oracle_count: int,
    twap_window_minutes: int,
    uses_spot_price: bool,
) -> int:
    base = _ORACLE_TYPE_BASE.get(oracle_type.upper(), 20)

    # oracle_count bonus
    cnt = max(oracle_count, 1)   # treat 0 as 1
    if cnt >= 3:
        cnt_bonus = 15
    elif cnt == 2:
        cnt_bonus = 8
    else:
        cnt_bonus = 0

    # TWAP bonus
    if twap_window_minutes >= 60:
        twap_bonus = 10
    elif twap_window_minutes >= 30:
        twap_bonus = 5
    else:
        twap_bonus = 0

    # spot price penalty
    spot_penalty = 20 if uses_spot_price else 0

    return max(0, min(100, base + cnt_bonus + twap_bonus - spot_penalty))


def _staleness_risk_score(staleness_threshold_minutes: int) -> int:
    t = staleness_threshold_minutes
    if t <= 1:
        return 0
    elif t <= 5:
        return 10
    elif t <= 60:
        return 30
    elif t <= 360:
        return 60
    else:
        return 90


def _circuit_breaker_score(deviation_threshold_pct: float) -> int:
    d = deviation_threshold_pct
    if d == 0:
        return 0
    elif d <= 2:
        return 100
    elif d <= 5:
        return 80
    elif d <= 10:
        return 60
    elif d <= 20:
        return 40
    else:
        return 20


def _diversification_score(oracle_count: int, has_fallback: bool) -> int:
    cnt = max(oracle_count, 1)   # treat 0 as 1
    if cnt >= 3 and has_fallback:
        return 100
    elif cnt >= 3:
        return 80
    elif cnt == 2 and has_fallback:
        return 70
    elif cnt == 2:
        return 55
    elif has_fallback:
        return 40
    else:
        return 20


def _overall_risk_score(
    manip_resistance: int,
    staleness_risk: int,
    circuit_breaker: int,
    diversification: int,
) -> int:
    raw = (
        (100 - manip_resistance) * 0.35
        + staleness_risk          * 0.25
        + (100 - circuit_breaker) * 0.20
        + (100 - diversification) * 0.20
    )
    return max(0, min(100, int(raw)))


def _risk_label(score: int) -> str:
    for threshold, label in _RISK_LABELS:
        if score <= threshold:
            return label
    return "CRITICAL"


def _tvl_at_risk_label(tvl: float) -> str:
    for threshold, label in _TVL_LABELS:
        if tvl < threshold:
            return label
    return "CRITICAL"


def _build_flags(
    uses_spot_price: bool,
    deviation_threshold_pct: float,
    oracle_count: int,
    last_manipulation_incident_days: int,
    has_fallback_oracle: bool,
) -> list:
    flags = []
    if uses_spot_price:
        flags.append("SPOT_PRICE_RISK")
    if deviation_threshold_pct == 0:
        flags.append("NO_CIRCUIT_BREAKER")
    if max(oracle_count, 1) == 1:
        flags.append("SINGLE_ORACLE")
    if last_manipulation_incident_days < 180:
        flags.append("RECENT_MANIPULATION")
    if not has_fallback_oracle:
        flags.append("NO_FALLBACK")
    return flags


def _recommendation(risk_lbl: str, oracle_type: str, oracle_count: int, flags: list) -> str:
    cnt = max(oracle_count, 1)
    if risk_lbl in ("MINIMAL", "LOW"):
        return (
            f"Oracle configuration adequate. "
            f"{oracle_type} with {cnt} source(s)."
        )
    elif risk_lbl == "MODERATE":
        issue = ", ".join(flags[:2]) if flags else "review configuration"
        return f"Moderate oracle risk. Address: {issue}."
    elif risk_lbl == "HIGH":
        return (
            f"High oracle risk. {len(flags)} flags. "
            f"Requires mitigation before large capital deployment."
        )
    else:   # CRITICAL
        issue = ", ".join(flags[:2]) if flags else "issues"
        return f"Critical oracle risk. Avoid until {issue} resolved."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze oracle risk for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list of dict
        Each entry must have: name, oracle_type, twap_window_minutes,
        staleness_threshold_minutes, deviation_threshold_pct, oracle_count,
        has_fallback_oracle, last_manipulation_incident_days,
        protocol_tvl_usd, uses_spot_price.
    config : dict, optional
        Supported keys:
          - large_tvl_threshold_usd (float, default 50_000_000)

    Returns
    -------
    dict
        Full oracle risk analysis (see module docstring for schema).
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}

    enriched = []

    for p in protocols:
        name                  = str(p.get("name", ""))
        oracle_type           = str(p.get("oracle_type", "CUSTOM")).upper()
        twap_window           = int(p.get("twap_window_minutes", 0))
        staleness_threshold   = int(p.get("staleness_threshold_minutes", 60))
        deviation_threshold   = float(p.get("deviation_threshold_pct", 0.0))
        oracle_count          = int(p.get("oracle_count", 1))
        has_fallback          = bool(p.get("has_fallback_oracle", False))
        last_manip_days       = int(p.get("last_manipulation_incident_days", 9999))
        tvl_usd               = float(p.get("protocol_tvl_usd", 0.0))
        uses_spot             = bool(p.get("uses_spot_price", False))

        manip_res  = _manipulation_resistance_score(oracle_type, oracle_count, twap_window, uses_spot)
        stale_risk = _staleness_risk_score(staleness_threshold)
        cb_score   = _circuit_breaker_score(deviation_threshold)
        div_score  = _diversification_score(oracle_count, has_fallback)
        overall    = _overall_risk_score(manip_res, stale_risk, cb_score, div_score)

        rlbl  = _risk_label(overall)
        tvlbl = _tvl_at_risk_label(tvl_usd)
        flags = _build_flags(uses_spot, deviation_threshold, oracle_count, last_manip_days, has_fallback)
        rec   = _recommendation(rlbl, oracle_type, oracle_count, flags)

        enriched.append({
            "name":                          name,
            "oracle_type":                   oracle_type,
            "manipulation_resistance_score": manip_res,
            "staleness_risk_score":          stale_risk,
            "circuit_breaker_score":         cb_score,
            "diversification_score":         div_score,
            "overall_risk_score":            overall,
            "risk_label":                    rlbl,
            "tvl_at_risk_label":             tvlbl,
            "flags":                         flags,
            "recommendation":                rec,
        })

    # Aggregations
    if enriched:
        scores = [e["overall_risk_score"] for e in enriched]
        avg_score = sum(scores) / len(scores)

        highest = max(enriched, key=lambda e: e["overall_risk_score"])["name"]
        lowest  = min(enriched, key=lambda e: e["overall_risk_score"])["name"]
        critical_count = sum(1 for e in enriched if e["risk_label"] == "CRITICAL")
    else:
        avg_score      = 0.0
        highest        = None
        lowest         = None
        critical_count = 0

    return {
        "protocols":              enriched,
        "highest_risk_protocol":  highest,
        "lowest_risk_protocol":   lowest,
        "average_risk_score":     avg_score,
        "critical_count":         critical_count,
        "timestamp":              time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer, 100 entries)
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def log_result(result: dict, log_path: str = "data/oracle_risk_log.json") -> None:
    """Append result snapshot to ring-buffer log (max 100 entries)."""
    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True)
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entry = {
        "timestamp":             result.get("timestamp", time.time()),
        "protocol_count":        len(result.get("protocols", [])),
        "average_risk_score":    result.get("average_risk_score", 0.0),
        "critical_count":        result.get("critical_count", 0),
        "highest_risk_protocol": result.get("highest_risk_protocol"),
        "lowest_risk_protocol":  result.get("lowest_risk_protocol"),
    }

    entries.append(entry)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="MP-888 ProtocolOracleRiskAnalyzer")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run",   action="store_true", help="Compute + write to log")
    parser.add_argument("--data-dir", default="data", help="Directory for JSON state files")
    args = parser.parse_args()

    demo_protocols = [
        {
            "name": "Aave V3",
            "oracle_type": "CHAINLINK",
            "twap_window_minutes": 0,
            "staleness_threshold_minutes": 60,
            "deviation_threshold_pct": 5.0,
            "oracle_count": 3,
            "has_fallback_oracle": True,
            "last_manipulation_incident_days": 9999,
            "protocol_tvl_usd": 8_000_000_000.0,
            "uses_spot_price": False,
        },
        {
            "name": "UniswapV3Pool",
            "oracle_type": "TWAP",
            "twap_window_minutes": 30,
            "staleness_threshold_minutes": 1,
            "deviation_threshold_pct": 0.0,
            "oracle_count": 1,
            "has_fallback_oracle": False,
            "last_manipulation_incident_days": 9999,
            "protocol_tvl_usd": 500_000_000.0,
            "uses_spot_price": False,
        },
    ]

    result = analyze(demo_protocols)
    import json as _json
    print(_json.dumps({
        "average_risk_score":    result["average_risk_score"],
        "highest_risk_protocol": result["highest_risk_protocol"],
        "lowest_risk_protocol":  result["lowest_risk_protocol"],
        "critical_count":        result["critical_count"],
        "protocols": [
            {
                "name":               p["name"],
                "risk_label":         p["risk_label"],
                "overall_risk_score": p["overall_risk_score"],
                "flags":              p["flags"],
            }
            for p in result["protocols"]
        ],
    }, indent=2))

    if args.run:
        log_path = os.path.join(args.data_dir, "oracle_risk_log.json")
        log_result(result, log_path)
        print(f"[MP-888] Result logged to {log_path}")


if __name__ == "__main__":
    _cli()

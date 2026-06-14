"""
MP-839 DeFiLiquidityCrisisPredictor
Predicts likelihood of a liquidity crisis across DeFi protocols by combining
TVL trend, utilization rate, redemption queue pressure, and market stress signals.

Advisory / read-only. Pure stdlib. Atomic writes via tmp + os.replace.
"""

import json
import os
import time
import tempfile

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "liquidity_crisis_log.json")
LOG_MAX = 100

_DEFAULT_CONFIG = {
    "crisis_threshold": 70.0,
    "tvl_drop_alert_pct": 20.0,
}


def _merge_config(user_config: dict | None) -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if user_config:
        cfg.update(user_config)
    return cfg


# ---------------------------------------------------------------------------
# Risk component calculators
# ---------------------------------------------------------------------------

def _tvl_trend_risk(tvl_change_7d_pct: float) -> float:
    """0-30 points based on 7-day TVL change percentage."""
    if tvl_change_7d_pct < -30:
        return 30.0
    elif tvl_change_7d_pct < -20:
        return 22.0
    elif tvl_change_7d_pct < -10:
        return 15.0
    elif tvl_change_7d_pct < 0:
        return 8.0
    else:
        return 0.0


def _utilization_risk(utilization_rate_pct: float) -> float:
    """0-25 points based on utilization rate."""
    if utilization_rate_pct >= 95:
        return 25.0
    elif utilization_rate_pct >= 90:
        return 20.0
    elif utilization_rate_pct >= 80:
        return 15.0
    elif utilization_rate_pct >= 70:
        return 8.0
    else:
        return 0.0


def _redemption_risk(redemption_coverage_ratio: float) -> float:
    """0-25 points based on redemption coverage ratio (tvl / pending_redemptions)."""
    if redemption_coverage_ratio < 1.1:
        return 25.0
    elif redemption_coverage_ratio < 1.5:
        return 18.0
    elif redemption_coverage_ratio < 2.0:
        return 10.0
    elif redemption_coverage_ratio < 5.0:
        return 4.0
    else:
        return 0.0


def _collateral_risk(stablecoin_collateral_pct: float) -> float:
    """0-10 points based on stablecoin collateral percentage."""
    if stablecoin_collateral_pct <= 10:
        return 10.0
    elif stablecoin_collateral_pct <= 30:
        return 7.0
    elif stablecoin_collateral_pct <= 50:
        return 4.0
    else:
        return 0.0


def _market_stress_risk(market_stress_score: int) -> float:
    """0-10 points: market_stress_score / 10."""
    return min(10.0, market_stress_score / 10.0)


def _crisis_probability_label(risk_score: float) -> str:
    if risk_score >= 75:
        return "CRITICAL"
    elif risk_score >= 50:
        return "HIGH"
    elif risk_score >= 25:
        return "MODERATE"
    else:
        return "LOW"


def _recommendation(crisis_probability: str) -> str:
    mapping = {
        "CRITICAL": "EXIT position immediately — high risk of liquidity crisis",
        "HIGH": "Reduce exposure significantly — prepare exit strategy",
        "MODERATE": "Monitor closely — consider partial reduction",
        "LOW": "Continue monitoring — no immediate action required",
    }
    return mapping[crisis_probability]


def _analyze_protocol(p: dict, cfg: dict) -> dict:
    name = p["name"]
    tvl = float(p["tvl_usd"])
    tvl_7d = float(p["tvl_7d_ago_usd"])
    utilization = float(p["utilization_rate_pct"])
    pending_redemptions = float(p["pending_redemptions_usd"])
    daily_outflow = float(p["daily_outflow_usd"])
    stablecoin_pct = float(p["stablecoin_collateral_pct"])
    market_stress = int(p["market_stress_score"])

    # TVL change
    if tvl_7d == 0:
        tvl_change_7d_pct = 0.0
    else:
        tvl_change_7d_pct = (tvl - tvl_7d) / tvl_7d * 100.0

    # Redemption coverage
    if pending_redemptions <= 0:
        redemption_coverage_ratio = 999.0
    else:
        redemption_coverage_ratio = tvl / pending_redemptions

    # Runway
    runway_days = (tvl / daily_outflow) if daily_outflow > 0 else None

    # Risk components
    tvl_risk = _tvl_trend_risk(tvl_change_7d_pct)
    util_risk = _utilization_risk(utilization)
    red_risk = _redemption_risk(redemption_coverage_ratio)
    col_risk = _collateral_risk(stablecoin_pct)
    mkt_risk = _market_stress_risk(market_stress)

    risk_score = min(100.0, tvl_risk + util_risk + red_risk + col_risk + mkt_risk)

    crisis_probability = _crisis_probability_label(risk_score)
    recommendation = _recommendation(crisis_probability)

    # Key risks
    key_risks = []
    tvl_drop_alert_pct = cfg["tvl_drop_alert_pct"]
    if tvl_change_7d_pct < -tvl_drop_alert_pct:
        key_risks.append(f"TVL dropped {abs(tvl_change_7d_pct):.1f}% in 7 days")
    if utilization >= 90:
        key_risks.append(f"Utilization at {utilization:.1f}% — near capacity")
    if redemption_coverage_ratio < 1.5:
        key_risks.append("Redemption queue exceeds TVL buffer")
    if stablecoin_pct < 30:
        key_risks.append("Low stablecoin collateral backing")
    if runway_days is not None and runway_days < 30:
        key_risks.append(f"Only {runway_days:.0f} days runway at current outflow")

    return {
        "name": name,
        "risk_score": round(risk_score, 4),
        "crisis_probability": crisis_probability,
        "tvl_change_7d_pct": round(tvl_change_7d_pct, 4),
        "runway_days": round(runway_days, 4) if runway_days is not None else None,
        "redemption_coverage_ratio": round(redemption_coverage_ratio, 4),
        "key_risks": key_risks,
        "recommendation": recommendation,
    }


def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze liquidity crisis risk across DeFi protocols.

    Parameters
    ----------
    protocols : list of dict
        Each dict must contain: name, tvl_usd, tvl_7d_ago_usd,
        utilization_rate_pct, pending_redemptions_usd, daily_outflow_usd,
        stablecoin_collateral_pct, market_stress_score.
    config : dict, optional
        crisis_threshold (default 70.0), tvl_drop_alert_pct (default 20.0).

    Returns
    -------
    dict with per-protocol analysis and portfolio-level summary.
    """
    cfg = _merge_config(config)
    crisis_threshold = cfg["crisis_threshold"]

    if not protocols:
        return {
            "protocols": [],
            "crisis_count": 0,
            "at_risk_protocols": [],
            "safest_protocol": None,
            "highest_risk_protocol": None,
            "portfolio_crisis_risk": "LOW",
            "timestamp": time.time(),
        }

    results = [_analyze_protocol(p, cfg) for p in protocols]

    crisis_count = sum(
        1 for r in results if r["crisis_probability"] in ("CRITICAL", "HIGH")
    )
    at_risk_protocols = [r["name"] for r in results if r["risk_score"] > crisis_threshold]

    scores = [(r["risk_score"], r["name"]) for r in results]
    safest_protocol = min(scores, key=lambda x: x[0])[1]
    highest_risk_protocol = max(scores, key=lambda x: x[0])[1]

    max_score = max(r["risk_score"] for r in results)
    portfolio_crisis_risk = _crisis_probability_label(max_score)

    return {
        "protocols": results,
        "crisis_count": crisis_count,
        "at_risk_protocols": at_risk_protocols,
        "safest_protocol": safest_protocol,
        "highest_risk_protocol": highest_risk_protocol,
        "portfolio_crisis_risk": portfolio_crisis_risk,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistent log
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=os.path.dirname(path), delete=False, suffix=".tmp"
    ) as fh:
        json.dump(data, fh, indent=2)
        tmp_path = fh.name
    os.replace(tmp_path, path)


def _load_log(path: str) -> list:
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def run_and_log(protocols: list, config: dict = None, data_file: str = None) -> dict:
    """Run analysis and append result to ring-buffer log (capped at LOG_MAX)."""
    result = analyze(protocols, config)
    path = data_file or DATA_FILE
    log = _load_log(path)
    log.append(result)
    if len(log) > LOG_MAX:
        log = log[-LOG_MAX:]
    _atomic_write(path, log)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-839 DeFiLiquidityCrisisPredictor")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute and write to data file")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    # Demo data
    demo_protocols = [
        {
            "name": "Aave V3",
            "tvl_usd": 5_000_000,
            "tvl_7d_ago_usd": 5_500_000,
            "utilization_rate_pct": 72,
            "pending_redemptions_usd": 500_000,
            "daily_outflow_usd": 50_000,
            "stablecoin_collateral_pct": 60,
            "market_stress_score": 30,
        },
        {
            "name": "Compound V3",
            "tvl_usd": 3_000_000,
            "tvl_7d_ago_usd": 4_000_000,
            "utilization_rate_pct": 91,
            "pending_redemptions_usd": 2_500_000,
            "daily_outflow_usd": 200_000,
            "stablecoin_collateral_pct": 20,
            "market_stress_score": 65,
        },
    ]

    if args.run:
        data_file = None
        if args.data_dir:
            data_file = os.path.join(args.data_dir, "liquidity_crisis_log.json")
        result = run_and_log(demo_protocols, data_file=data_file)
        print(json.dumps(result, indent=2))
    else:
        result = analyze(demo_protocols)
        print(json.dumps(result, indent=2))

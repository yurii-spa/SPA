"""
MP-827 DeFiPortfolioHealthScorer
Advisory-only analytics. Pure stdlib, no external deps.
Logs to data/portfolio_health_log.json (ring-buffer 100, atomic writes).
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))

LOG_PATH = os.path.join(_PROJECT_ROOT, "data", "portfolio_health_log.json")
LOG_RING_SIZE = 100

_DEFAULT_CONFIG = {
    "max_single_position_pct": 30.0,
    "max_liquidity_days": 7.0,
}


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path, obj):
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _append_log(path, entry):
    log = _load_log(path)
    log.append(entry)
    if len(log) > LOG_RING_SIZE:
        log = log[-LOG_RING_SIZE:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Scoring sub-functions
# ---------------------------------------------------------------------------

def _yield_score(weighted_avg_apy):
    """0-25: 20 % APY = full 25 pts. Capped at 25."""
    return min(25, int(weighted_avg_apy / 20.0 * 25))


def _risk_score_dim(weighted_avg_risk):
    """0-25: risk 0 = 25 pts, risk 100 = 0 pts."""
    return max(0, 25 - int(weighted_avg_risk / 4.0))


def _liquidity_score(liquid_value, total_value):
    """0-25: fraction of portfolio with liquidity_days <= 1."""
    if total_value <= 0:
        return 0
    return int(liquid_value / total_value * 25)


def _diversification_score(values, position_count):
    """0-25: HHI-based + position count bonus, capped at 25."""
    if not values:
        return 0
    total = sum(values)
    if total <= 0:
        return 0
    hhi = sum((v / total) ** 2 for v in values)
    raw = int((1.0 - hhi) * 20) + min(5, position_count)
    return min(25, raw)


def _grade(score):
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(positions, config=None):
    """
    Compute comprehensive portfolio health score.

    Parameters
    ----------
    positions : list of dict
        Each dict: {protocol, value_usd, apy, risk_score, liquidity_days,
                    audit_count, is_stablecoin}
    config : dict, optional
        {max_single_position_pct (default 30.0),
         max_liquidity_days (default 7.0)}

    Returns
    -------
    dict
        {total_value_usd, position_count, dimensions, total_health_score,
         grade, portfolio_stats, alerts, recommendations, timestamp}
    """
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    max_single_pct = float(cfg.get("max_single_position_pct", 30.0))
    max_liq_days = float(cfg.get("max_liquidity_days", 7.0))

    # ---- Empty positions ----
    if not positions:
        result = _empty_result()
        _append_log(LOG_PATH, result)
        return result

    total_value = sum(float(p.get("value_usd", 0.0)) for p in positions)

    # ---- Per-position pass ----
    weighted_avg_apy = 0.0
    weighted_avg_risk = 0.0
    stablecoin_value = 0.0
    illiquid_value = 0.0
    liquid_value = 0.0

    most_audited_protocol = ""
    max_audits = -1
    highest_risk_protocol = ""
    max_risk_seen = -1

    values = []

    for pos in positions:
        val = float(pos.get("value_usd", 0.0))
        apy = float(pos.get("apy", 0.0))
        risk = float(pos.get("risk_score", 0.0))
        liq_days = float(pos.get("liquidity_days", 0.0))
        audits = int(pos.get("audit_count", 0))
        is_stable = bool(pos.get("is_stablecoin", False))
        protocol = str(pos.get("protocol", ""))

        values.append(val)

        if total_value > 0:
            w = val / total_value
            weighted_avg_apy += w * apy
            weighted_avg_risk += w * risk

        if is_stable:
            stablecoin_value += val
        if liq_days > max_liq_days:
            illiquid_value += val
        if liq_days <= 1.0:
            liquid_value += val

        if audits > max_audits:
            max_audits = audits
            most_audited_protocol = protocol
        if risk > max_risk_seen:
            max_risk_seen = risk
            highest_risk_protocol = protocol

    stablecoin_pct = (stablecoin_value / total_value * 100.0) if total_value > 0 else 0.0
    illiquid_pct = (illiquid_value / total_value * 100.0) if total_value > 0 else 0.0

    # ---- Dimension scores ----
    ys = _yield_score(weighted_avg_apy)
    rs = _risk_score_dim(weighted_avg_risk)
    ls = _liquidity_score(liquid_value, total_value)
    ds = _diversification_score(values, len(positions))

    total_health = ys + rs + ls + ds

    # HHI for recommendations
    hhi = (
        sum((v / total_value) ** 2 for v in values)
        if total_value > 0
        else 1.0
    )

    # ---- Alerts ----
    alerts = []
    for pos in positions:
        val = float(pos.get("value_usd", 0.0))
        protocol = str(pos.get("protocol", ""))
        liq_days = float(pos.get("liquidity_days", 0.0))
        risk = float(pos.get("risk_score", 0.0))

        pct = (val / total_value * 100.0) if total_value > 0 else 0.0
        if pct > max_single_pct:
            alerts.append(
                f"Position >{max_single_pct:.0f}%: {protocol} ({pct:.1f}%)"
            )
        if liq_days > max_liq_days:
            alerts.append(
                f"Illiquid position: {protocol} ({liq_days:.0f} days)"
            )
        if risk > 70:
            alerts.append(
                f"High-risk position: {protocol} (risk={int(risk)})"
            )

    if weighted_avg_risk > 60:
        alerts.append("Portfolio average risk is HIGH")

    # ---- Recommendations ----
    recommendations = []
    if stablecoin_pct < 10:
        recommendations.append(
            "Consider adding stablecoin positions for stability"
        )
    if illiquid_pct > 50:
        recommendations.append("Reduce illiquid exposure")
    if hhi > 0.5:
        recommendations.append("Diversify — portfolio too concentrated")
    recommendations = recommendations[:3]

    result = {
        "total_value_usd": float(total_value),
        "position_count": len(positions),
        "dimensions": {
            "yield_score": ys,
            "risk_score": rs,
            "liquidity_score": ls,
            "diversification_score": ds,
        },
        "total_health_score": total_health,
        "grade": _grade(total_health),
        "portfolio_stats": {
            "weighted_avg_apy": round(weighted_avg_apy, 4),
            "weighted_avg_risk": round(weighted_avg_risk, 4),
            "stablecoin_pct": round(stablecoin_pct, 2),
            "illiquid_pct": round(illiquid_pct, 2),
            "most_audited_protocol": most_audited_protocol,
            "highest_risk_protocol": highest_risk_protocol,
        },
        "alerts": alerts,
        "recommendations": recommendations,
        "timestamp": time.time(),
    }

    _append_log(LOG_PATH, result)
    return result


def _empty_result():
    return {
        "total_value_usd": 0.0,
        "position_count": 0,
        "dimensions": {
            "yield_score": 0,
            "risk_score": 0,
            "liquidity_score": 0,
            "diversification_score": 0,
        },
        "total_health_score": 0,
        "grade": "F",
        "portfolio_stats": {
            "weighted_avg_apy": 0.0,
            "weighted_avg_risk": 0.0,
            "stablecoin_pct": 0.0,
            "illiquid_pct": 0.0,
            "most_audited_protocol": "",
            "highest_risk_protocol": "",
        },
        "alerts": [],
        "recommendations": [],
        "timestamp": time.time(),
    }

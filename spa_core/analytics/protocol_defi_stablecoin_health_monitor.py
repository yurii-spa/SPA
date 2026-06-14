"""
MP-993: ProtocolDeFiStablecoinHealthMonitor
Monitors peg stability, collateral quality, and redemption pressure for stablecoins.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import math
import os
import tempfile
import time
from typing import Any

# ── Health labels ──────────────────────────────────────────────────────────
LABEL_ROCK_SOLID  = "ROCK_SOLID"
LABEL_STABLE      = "STABLE"
LABEL_CAUTIOUS    = "CAUTIOUS"
LABEL_AT_RISK     = "AT_RISK"
LABEL_DEPEGGING   = "DEPEGGING"
LABEL_COLLAPSED   = "COLLAPSED"

# ── Flags ─────────────────────────────────────────────────────────────────
FLAG_ACTIVE_DEPEG              = "ACTIVE_DEPEG"
FLAG_ALGO_CONCENTRATION        = "ALGO_CONCENTRATION"
FLAG_UNAUDITED_RESERVES        = "UNAUDITED_RESERVES"
FLAG_REDEMPTION_PRESSURE       = "REDEMPTION_PRESSURE"
FLAG_REDEMPTION_SUSPENDED      = "REDEMPTION_SUSPENDED"
FLAG_NET_OUTFLOW_ACCELERATING  = "NET_OUTFLOW_ACCELERATING"

# ── Constants ──────────────────────────────────────────────────────────────
_LOG_CAP          = 100
_LOG_PATH_DEFAULT = "data/stablecoin_health_log.json"


# ── Helpers ────────────────────────────────────────────────────────────────

def _atomic_write(path: str, obj: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _stddev(values: list) -> float:
    """Population std dev for a list of floats. Returns 0 if <2 elements."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


# ── Per-stablecoin metrics ─────────────────────────────────────────────────

def _peg_deviation_pct(coin: dict) -> float:
    """abs(current - target) / target * 100"""
    target  = float(coin.get("peg_target_usd", 1.0))
    current = float(coin.get("current_price_usd", 1.0))
    if target == 0:
        return 0.0
    return abs(current - target) / target * 100.0


def _peg_volatility_30d(coin: dict) -> float:
    """Std dev of daily prices in price_history_30d."""
    history = coin.get("price_history_30d", [])
    floats  = [float(v) for v in history if v is not None]
    return round(_stddev(floats), 6)


def _max_depeg_30d(coin: dict) -> float:
    """Max absolute deviation from peg target in 30-day history."""
    history = coin.get("price_history_30d", [])
    target  = float(coin.get("peg_target_usd", 1.0))
    if not history:
        return _peg_deviation_pct(coin)
    floats  = [float(v) for v in history if v is not None]
    if not floats:
        return 0.0
    max_dev = max(abs(v - target) for v in floats)
    if target == 0:
        return 0.0
    return round(max_dev / target * 100.0, 6)


def _redemption_pressure_ratio(coin: dict) -> float:
    """daily_redemptions / circulating_supply * 100 (%)"""
    redemptions    = float(coin.get("daily_redemptions_usd_7d_avg", 0.0))
    circ_supply    = float(coin.get("circulating_supply_usd", 0.0))
    if circ_supply <= 0:
        return 0.0
    return round(redemptions / circ_supply * 100.0, 6)


def _net_flow_7d(coin: dict) -> float:
    """(mints - redemptions) / circulating_supply * 100 (%)
    Negative = outflow, positive = inflow."""
    mints       = float(coin.get("daily_mints_usd_7d_avg", 0.0))
    redemptions = float(coin.get("daily_redemptions_usd_7d_avg", 0.0))
    circ_supply = float(coin.get("circulating_supply_usd", 0.0))
    if circ_supply <= 0:
        return 0.0
    return round((mints - redemptions) / circ_supply * 100.0, 6)


# ── Health label logic ─────────────────────────────────────────────────────

def _health_label(coin: dict, deviation: float, algo_pct: float,
                  coll_ratio: float) -> str:
    audited   = bool(coin.get("issuer_reserves_audited", False))
    suspended = bool(coin.get("redemption_suspended", False))

    # COLLAPSED: extreme depeg
    if deviation > 10.0:
        return LABEL_COLLAPSED

    # DEPEGGING: significant depeg or suspended redemptions
    if deviation > 3.0 or suspended:
        return LABEL_DEPEGGING

    # AT_RISK: moderate depeg or under-collateralized
    if deviation > 1.0 or coll_ratio < 110.0:
        return LABEL_AT_RISK

    # CAUTIOUS: mild depeg or high algo component
    if deviation >= 0.5 or algo_pct > 20.0:
        return LABEL_CAUTIOUS

    # ROCK_SOLID: minimal deviation, well-over-collateralized, audited
    if deviation < 0.1 and coll_ratio >= 150.0 and audited:
        return LABEL_ROCK_SOLID

    # STABLE: everything else within bounds
    return LABEL_STABLE


# ── Flags ─────────────────────────────────────────────────────────────────

def _compute_flags(coin: dict, deviation: float, redemption_ratio: float,
                   net_flow: float, algo_pct: float) -> list:
    flags      = []
    audited    = bool(coin.get("issuer_reserves_audited", False))
    suspended  = bool(coin.get("redemption_suspended", False))
    mechanism  = coin.get("peg_mechanism", "")

    if deviation > 1.0:
        flags.append(FLAG_ACTIVE_DEPEG)

    if algo_pct > 30.0:
        flags.append(FLAG_ALGO_CONCENTRATION)

    if not audited and mechanism == "fiat_backed":
        flags.append(FLAG_UNAUDITED_RESERVES)

    if redemption_ratio > 2.0:
        flags.append(FLAG_REDEMPTION_PRESSURE)

    if suspended:
        flags.append(FLAG_REDEMPTION_SUSPENDED)

    if net_flow < -5.0:
        flags.append(FLAG_NET_OUTFLOW_ACCELERATING)

    return flags


# ── Per-stablecoin monitor ─────────────────────────────────────────────────

def _monitor_coin(coin: dict) -> dict:
    name       = coin.get("name", "unknown")
    algo_pct   = float(coin.get("algo_component_pct", 0.0))
    coll_ratio = float(coin.get("collateral_ratio_pct", 100.0))

    deviation         = round(_peg_deviation_pct(coin), 6)
    volatility_30d    = _peg_volatility_30d(coin)
    max_depeg         = _max_depeg_30d(coin)
    redemption_ratio  = _redemption_pressure_ratio(coin)
    net_flow          = _net_flow_7d(coin)

    label = _health_label(coin, deviation, algo_pct, coll_ratio)
    flags = _compute_flags(coin, deviation, redemption_ratio, net_flow, algo_pct)

    return {
        "name":                    name,
        "peg_deviation_pct":       deviation,
        "peg_volatility_30d":      volatility_30d,
        "max_depeg_30d":           max_depeg,
        "redemption_pressure_ratio": redemption_ratio,
        "net_flow_7d":             net_flow,
        "collateral_ratio_pct":    coll_ratio,
        "algo_component_pct":      algo_pct,
        "health_label":            label,
        "flags":                   flags,
        "peg_mechanism":           coin.get("peg_mechanism", "unknown"),
        "issuer_reserves_audited": bool(coin.get("issuer_reserves_audited", False)),
        "redemption_suspended":    bool(coin.get("redemption_suspended", False)),
        "blacklist_enabled":       bool(coin.get("blacklist_enabled", False)),
    }


# ── Main class ─────────────────────────────────────────────────────────────

class ProtocolDeFiStablecoinHealthMonitor:
    """
    Monitors health of stablecoin protocols (peg stability, collateral quality,
    redemption pressure).

    monitor(stablecoins, config) -> dict with per-stablecoin results + aggregates.
    Optionally writes a ring-buffer log entry to data/stablecoin_health_log.json.
    """

    def monitor(self, stablecoins: list, config: dict = None) -> dict:
        if config is None:
            config = {}

        log_path  = config.get("log_path", _LOG_PATH_DEFAULT)
        write_log = config.get("write_log", True)

        if not stablecoins:
            result = {
                "stablecoins":      [],
                "most_stable":      None,
                "most_at_risk":     None,
                "avg_deviation":    0.0,
                "depegging_count":  0,
                "rock_solid_count": 0,
                "timestamp":        time.time(),
            }
            if write_log:
                self._append_log(result, log_path)
            return result

        monitored = [_monitor_coin(c) for c in stablecoins]

        deviations     = [m["peg_deviation_pct"] for m in monitored]
        avg_deviation  = round(sum(deviations) / len(deviations), 6)

        most_stable    = min(monitored, key=lambda x: x["peg_deviation_pct"])
        most_at_risk   = max(monitored, key=lambda x: x["peg_deviation_pct"])

        depegging_count  = sum(1 for m in monitored
                               if m["health_label"] in (LABEL_DEPEGGING, LABEL_COLLAPSED))
        rock_solid_count = sum(1 for m in monitored
                               if m["health_label"] == LABEL_ROCK_SOLID)

        result = {
            "stablecoins":      monitored,
            "most_stable":      most_stable["name"],
            "most_at_risk":     most_at_risk["name"],
            "avg_deviation":    avg_deviation,
            "depegging_count":  depegging_count,
            "rock_solid_count": rock_solid_count,
            "timestamp":        time.time(),
        }

        if write_log:
            self._append_log(result, log_path)

        return result

    # ── Log helpers ────────────────────────────────────────────────────────

    def _append_log(self, result: dict, path: str) -> None:
        """Append to ring-buffer log (cap _LOG_CAP), atomic write."""
        log = _load_log(path)
        log.append(result)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        _atomic_write(path, log)

    def load_log(self, path: str = _LOG_PATH_DEFAULT) -> list:
        """Public method to read the log."""
        return _load_log(path)


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    _DEMO_COINS = [
        {
            "name": "USDC",
            "peg_target_usd": 1.0,
            "current_price_usd": 1.0002,
            "price_history_30d": [1.0 + (i % 3) * 0.0001 for i in range(30)],
            "collateral_ratio_pct": 200.0,
            "collateral_types": ["cash", "treasuries"],
            "algo_component_pct": 0.0,
            "total_supply_usd": 40_000_000_000.0,
            "circulating_supply_usd": 38_000_000_000.0,
            "daily_redemptions_usd_7d_avg": 100_000_000.0,
            "daily_mints_usd_7d_avg": 120_000_000.0,
            "peg_mechanism": "fiat_backed",
            "issuer_reserves_audited": True,
            "redemption_suspended": False,
            "blacklist_enabled": True,
        },
        {
            "name": "LUSD",
            "peg_target_usd": 1.0,
            "current_price_usd": 1.032,
            "price_history_30d": [0.98 + i * 0.002 for i in range(30)],
            "collateral_ratio_pct": 130.0,
            "collateral_types": ["eth"],
            "algo_component_pct": 0.0,
            "total_supply_usd": 500_000_000.0,
            "circulating_supply_usd": 490_000_000.0,
            "daily_redemptions_usd_7d_avg": 20_000_000.0,
            "daily_mints_usd_7d_avg": 5_000_000.0,
            "peg_mechanism": "overcollateralized",
            "issuer_reserves_audited": False,
            "redemption_suspended": False,
            "blacklist_enabled": False,
        },
    ]

    monitor = ProtocolDeFiStablecoinHealthMonitor()
    mode    = sys.argv[1] if len(sys.argv) > 1 else "--check"

    if mode == "--run":
        result = monitor.monitor(_DEMO_COINS, {"write_log": True})
    else:
        result = monitor.monitor(_DEMO_COINS, {"write_log": False})

    for c in result["stablecoins"]:
        print(f"  {c['name']:10s}  dev={c['peg_deviation_pct']:6.3f}%"
              f"  {c['health_label']:<12}  flags={c['flags']}")

    print(f"\nMost stable  : {result['most_stable']}")
    print(f"Most at risk : {result['most_at_risk']}")
    print(f"Avg deviation: {result['avg_deviation']}%")
    print(f"Depegging    : {result['depegging_count']}")
    print(f"Rock solid   : {result['rock_solid_count']}")

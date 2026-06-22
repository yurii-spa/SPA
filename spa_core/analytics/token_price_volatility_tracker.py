"""
MP-807: TokenPriceVolatilityTracker
Computes price volatility metrics for tokens in a DeFi portfolio —
annualized volatility, drawdown, Value at Risk (VaR) — to inform
position sizing and risk limits.

Advisory / read-only analytics module.
Pure stdlib only. Atomic JSON writes. Ring-buffer 100 entries.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ── Paths ────────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "token_volatility_log.json")

_RING_BUFFER_CAP = 100

# ── Regime thresholds (annualised %) ────────────────────────────────────────

_REGIME_THRESHOLDS = [
    ("EXTREME", 100.0),
    ("HIGH",    60.0),
    ("MEDIUM",  30.0),
    ("LOW",     0.0),
]


# ── Public API ───────────────────────────────────────────────────────────────

def analyze(token: str, prices: List[float], config: Optional[dict] = None) -> dict:
    """
    Compute price-volatility metrics for *token* given a list of daily close
    *prices* (oldest first, minimum 2 entries required for full metrics).

    config keys (all optional):
        var_confidence    float  default 0.95  — confidence level for VaR
        annualize_factor  int    default 365   — trading days per year

    Returns a result dict (see module docstring for full schema).
    """
    if config is None:
        config = {}

    var_confidence: float = float(config.get("var_confidence", 0.95))
    annualize_factor: int = int(config.get("annualize_factor", 365))
    ts: float = time.time()

    # ── Edge case: empty / single price ─────────────────────────────────────
    if not prices or len(prices) < 1:
        result = _empty_result(token, ts)
        _append_log(result)
        return result

    price_current: float = float(prices[-1])

    if len(prices) == 1:
        result = {
            "token": token,
            "price_current": price_current,
            "price_7d_ago": None,
            "price_30d_ago": None,
            "return_7d_pct": None,
            "return_30d_pct": None,
            "daily_returns": [],
            "volatility_daily_pct": 0.0,
            "volatility_annual_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "var_95_daily_pct": 0.0,
            "volatility_regime": "LOW",
            "sharpe_proxy": None,
            "timestamp": ts,
        }
        _append_log(result)
        return result

    # ── Daily returns ────────────────────────────────────────────────────────
    daily_returns: List[float] = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] != 0.0
    ]

    # ── Look-back prices ─────────────────────────────────────────────────────
    price_7d_ago: Optional[float] = float(prices[-8]) if len(prices) >= 8 else None
    price_30d_ago: Optional[float] = float(prices[-31]) if len(prices) >= 31 else None

    return_7d_pct: Optional[float] = (
        (price_current / price_7d_ago - 1) * 100 if price_7d_ago is not None else None
    )
    return_30d_pct: Optional[float] = (
        (price_current / price_30d_ago - 1) * 100 if price_30d_ago is not None else None
    )

    # ── Volatility ───────────────────────────────────────────────────────────
    vol_daily_pct: float = _stdev(daily_returns) * 100
    vol_annual_pct: float = vol_daily_pct * math.sqrt(annualize_factor)

    # ── Volatility regime ────────────────────────────────────────────────────
    regime: str = _classify_regime(vol_annual_pct)

    # ── Max drawdown ─────────────────────────────────────────────────────────
    max_drawdown_pct: float = _max_drawdown(prices)

    # ── VaR (5th-percentile of daily returns) ───────────────────────────────
    var_pct: float = _var(daily_returns, var_confidence)

    # ── Sharpe proxy ─────────────────────────────────────────────────────────
    vol_raw = _stdev(daily_returns)
    if vol_raw == 0.0:
        sharpe_proxy: Optional[float] = None
    else:
        mean_ret = sum(daily_returns) / len(daily_returns)
        sharpe_proxy = mean_ret / vol_raw

    result = {
        "token": token,
        "price_current": price_current,
        "price_7d_ago": price_7d_ago,
        "price_30d_ago": price_30d_ago,
        "return_7d_pct": return_7d_pct,
        "return_30d_pct": return_30d_pct,
        "daily_returns": daily_returns,
        "volatility_daily_pct": vol_daily_pct,
        "volatility_annual_pct": vol_annual_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "var_95_daily_pct": var_pct,
        "volatility_regime": regime,
        "sharpe_proxy": sharpe_proxy,
        "timestamp": ts,
    }

    _append_log(result)
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _empty_result(token: str, ts: float) -> dict:
    return {
        "token": token,
        "price_current": 0.0,
        "price_7d_ago": None,
        "price_30d_ago": None,
        "return_7d_pct": None,
        "return_30d_pct": None,
        "daily_returns": [],
        "volatility_daily_pct": 0.0,
        "volatility_annual_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "var_95_daily_pct": 0.0,
        "volatility_regime": "LOW",
        "sharpe_proxy": None,
        "timestamp": ts,
    }


def _stdev(values: List[float]) -> float:
    """Population standard deviation (n denominator when n==1, else sample)."""
    n = len(values)
    if n == 0:
        return 0.0
    if n == 1:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def _classify_regime(vol_annual_pct: float) -> str:
    if vol_annual_pct >= 100.0:
        return "EXTREME"
    if vol_annual_pct >= 60.0:
        return "HIGH"
    if vol_annual_pct >= 30.0:
        return "MEDIUM"
    return "LOW"


def _max_drawdown(prices: List[float]) -> float:
    """Peak-to-trough max drawdown as a positive percentage."""
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        if peak > 0:
            dd = (peak - p) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _var(daily_returns: List[float], var_confidence: float) -> float:
    """
    Historical VaR at *var_confidence* level.
    Returns the (1-confidence) percentile of daily_returns * 100.
    Negative value = potential loss.
    """
    if not daily_returns:
        return 0.0
    sorted_returns = sorted(daily_returns)
    idx = int(math.floor(len(sorted_returns) * (1 - var_confidence)))
    # clamp to valid range
    idx = max(0, min(idx, len(sorted_returns) - 1))
    return sorted_returns[idx] * 100


# ── Log persistence (ring-buffer, atomic) ────────────────────────────────────

def _load_log() -> list:
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(entry: dict) -> None:
    """Append *entry* to the ring-buffer log, capped at _RING_BUFFER_CAP."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    log = _load_log()
    # Serialisable copy — strip large daily_returns lists to keep log compact
    compact = {k: v for k, v in entry.items() if k != "daily_returns"}
    compact["daily_returns_len"] = len(entry.get("daily_returns", []))
    log.append(compact)
    if len(log) > _RING_BUFFER_CAP:
        log = log[-_RING_BUFFER_CAP:]
    _atomic_write(_LOG_FILE, log)


def _atomic_write(path: str, obj) -> None:
    atomic_save(obj, str(path))

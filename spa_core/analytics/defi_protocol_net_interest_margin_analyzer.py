"""
MP-1110  DeFiProtocolNetInterestMarginAnalyzer
-----------------------------------------------
Analyzes the Net Interest Margin (NIM) of DeFi lending protocols — the spread
between lending APY earned by suppliers and borrowing APY paid by borrowers.

Narrow NIM signals a less sustainable protocol; negative NIM (inverted spread)
means the protocol pays suppliers more than it earns from borrowers — a red flag.

Outputs
-------
gross_spread_pct             : borrow_apy - supply_apy
net_interest_margin_pct      : gross_spread * utilization / 100
protocol_revenue_usd_annual  : total_borrowed * borrow_apy/100 * reserve_factor/100
supplier_effective_yield_pct : supply_apy * utilization/100  (actual yield on total capital)
nim_efficiency_score         : int 0-100
nim_label                    : HEALTHY_SPREAD / ADEQUATE_SPREAD / THIN_SPREAD /
                                COMPRESSED_SPREAD / INVERTED_SPREAD

Label logic (by gross_spread_pct)
----------------------------------
> 3%      → HEALTHY_SPREAD
2–3%     → ADEQUATE_SPREAD
1–2%     → THIN_SPREAD
0–1%     → COMPRESSED_SPREAD
<= 0%    → INVERTED_SPREAD

Log file : data/net_interest_margin_log.json  (ring-buffer 100, atomic write)

Advisory / read-only.  Pure Python stdlib.  No external dependencies.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "net_interest_margin_log.json",
)
_LOG_CAP = 100

# NIM label constants
NIM_HEALTHY_SPREAD    = "HEALTHY_SPREAD"
NIM_ADEQUATE_SPREAD   = "ADEQUATE_SPREAD"
NIM_THIN_SPREAD       = "THIN_SPREAD"
NIM_COMPRESSED_SPREAD = "COMPRESSED_SPREAD"
NIM_INVERTED_SPREAD   = "INVERTED_SPREAD"

ALL_NIM_LABELS = (
    NIM_HEALTHY_SPREAD,
    NIM_ADEQUATE_SPREAD,
    NIM_THIN_SPREAD,
    NIM_COMPRESSED_SPREAD,
    NIM_INVERTED_SPREAD,
)

# Spread thresholds (gross_spread_pct)
_HEALTHY_THRESHOLD    = 3.0   # > 3%   → HEALTHY_SPREAD
_ADEQUATE_THRESHOLD   = 2.0   # 2-3%   → ADEQUATE_SPREAD
_THIN_THRESHOLD       = 1.0   # 1-2%   → THIN_SPREAD
_COMPRESSED_THRESHOLD = 0.0   # 0-1%   → COMPRESSED_SPREAD
                               # <= 0%  → INVERTED_SPREAD

# Score boundaries for nim_efficiency_score
_EFFICIENCY_SCORE_CAP_SPREAD = 10.0   # gross_spread saturates at 10% for score


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
def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Sub-calculators
# ---------------------------------------------------------------------------

def _gross_spread_pct(borrow_apy_pct: float, supply_apy_pct: float) -> float:
    """
    Gross interest spread.

    gross_spread = borrow_apy - supply_apy

    Positive → protocol is in normal operation.
    Zero or negative → inverted / compressed.
    """
    return borrow_apy_pct - supply_apy_pct


def _net_interest_margin_pct(
    gross_spread_pct: float,
    utilization_rate_pct: float,
) -> float:
    """
    Net Interest Margin (NIM).

    NIM = gross_spread * utilization / 100

    The utilization rate scales down the effective NIM because not all supplied
    capital is earning the borrow rate — only the utilised portion is.
    """
    return gross_spread_pct * utilization_rate_pct / 100.0


def _protocol_revenue_usd_annual(
    total_borrowed_usd: float,
    borrow_apy_pct: float,
    reserve_factor_pct: float,
) -> float:
    """
    Annual revenue diverted to the protocol treasury.

    revenue = total_borrowed * borrow_apy% * reserve_factor%

    Only the fraction of borrow interest designated by the reserve factor
    flows to the protocol; the remainder goes to suppliers.
    """
    if total_borrowed_usd <= 0:
        return 0.0
    return (
        total_borrowed_usd
        * max(0.0, borrow_apy_pct) / 100.0
        * _clamp(reserve_factor_pct, 0.0, 100.0) / 100.0
    )


def _supplier_effective_yield_pct(
    supply_apy_pct: float,
    utilization_rate_pct: float,
) -> float:
    """
    Effective yield a supplier actually earns on *total* capital deployed.

    effective_yield = supply_apy * utilization / 100

    The unutilised portion of supplied capital earns 0, so the blended yield
    across all supplied capital is proportionally reduced.
    """
    return supply_apy_pct * _clamp(utilization_rate_pct, 0.0, 100.0) / 100.0


def _nim_efficiency_score(
    gross_spread_pct: float,
    net_interest_margin_pct: float,
    utilization_rate_pct: float,
) -> int:
    """
    Composite NIM efficiency score, 0–100.

    Components:
    - Spread component (0-50): how wide and positive the gross spread is.
      Saturates at _EFFICIENCY_SCORE_CAP_SPREAD (10 %).
    - Utilization component (0-30): how well deployed the capital is.
      Saturates at 100 % utilization.
    - NIM component (0-20): bonus for a high *effective* NIM
      (spread actually realized given utilization).

    Inverted or zero spread floors the score at 0.
    """
    if gross_spread_pct <= 0:
        return 0

    # Spread component (0-50)
    spread_frac = _clamp(gross_spread_pct / _EFFICIENCY_SCORE_CAP_SPREAD, 0.0, 1.0)
    spread_component = spread_frac * 50.0

    # Utilization component (0-30)
    util_frac = _clamp(utilization_rate_pct / 100.0, 0.0, 1.0)
    util_component = util_frac * 30.0

    # NIM component (0-20): effective NIM scaled by cap_spread
    nim_frac = _clamp(net_interest_margin_pct / _EFFICIENCY_SCORE_CAP_SPREAD, 0.0, 1.0)
    nim_component = nim_frac * 20.0

    raw = spread_component + util_component + nim_component
    return int(_clamp(round(raw), 0, 100))


def _nim_label(gross_spread_pct: float) -> str:
    """
    Advisory NIM label based on gross spread.

    > 3%     → HEALTHY_SPREAD
    2–3%    → ADEQUATE_SPREAD
    1–2%    → THIN_SPREAD
    0–1%    → COMPRESSED_SPREAD
    <= 0%   → INVERTED_SPREAD
    """
    if gross_spread_pct > _HEALTHY_THRESHOLD:
        return NIM_HEALTHY_SPREAD
    if gross_spread_pct > _ADEQUATE_THRESHOLD:
        return NIM_ADEQUATE_SPREAD
    if gross_spread_pct > _THIN_THRESHOLD:
        return NIM_THIN_SPREAD
    if gross_spread_pct > _COMPRESSED_THRESHOLD:
        return NIM_COMPRESSED_SPREAD
    return NIM_INVERTED_SPREAD


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(protocol: dict, config: dict | None = None) -> dict:
    """
    Analyze the Net Interest Margin of a DeFi lending protocol.

    Parameters
    ----------
    protocol : dict
        supply_apy_pct          : float  (APY paid to suppliers, %)
        borrow_apy_pct          : float  (APY charged to borrowers, %)
        utilization_rate_pct    : float  (% of supplied capital being borrowed, 0-100)
        reserve_factor_pct      : float  (% of borrow interest to protocol treasury, 0-100)
        total_supplied_usd      : float  (total USD supplied to the protocol)
        total_borrowed_usd      : float  (total USD borrowed from the protocol)
        protocol_name           : str

    config : dict, optional
        log_path : str  (override default log path)

    Returns
    -------
    dict
        Full NIM analysis result.  Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    protocol_name       = str(protocol.get("protocol_name", "UNKNOWN"))
    supply_apy_pct      = max(0.0, _safe_float(protocol.get("supply_apy_pct", 0.0)))
    borrow_apy_pct      = max(0.0, _safe_float(protocol.get("borrow_apy_pct", 0.0)))
    utilization_pct     = _clamp(
        _safe_float(protocol.get("utilization_rate_pct", 0.0)), 0.0, 100.0
    )
    reserve_factor_pct  = _clamp(
        _safe_float(protocol.get("reserve_factor_pct", 0.0)), 0.0, 100.0
    )
    total_supplied_usd  = max(0.0, _safe_float(protocol.get("total_supplied_usd", 0.0)))
    total_borrowed_usd  = max(0.0, _safe_float(protocol.get("total_borrowed_usd", 0.0)))

    gross_spread        = _gross_spread_pct(borrow_apy_pct, supply_apy_pct)
    nim_pct             = _net_interest_margin_pct(gross_spread, utilization_pct)
    revenue_annual      = _protocol_revenue_usd_annual(
        total_borrowed_usd, borrow_apy_pct, reserve_factor_pct
    )
    supplier_yield      = _supplier_effective_yield_pct(supply_apy_pct, utilization_pct)
    eff_score           = _nim_efficiency_score(gross_spread, nim_pct, utilization_pct)
    label               = _nim_label(gross_spread)

    result: dict[str, Any] = {
        "protocol_name":                protocol_name,
        "supply_apy_pct":               supply_apy_pct,
        "borrow_apy_pct":               borrow_apy_pct,
        "utilization_rate_pct":         utilization_pct,
        "reserve_factor_pct":           reserve_factor_pct,
        "total_supplied_usd":           total_supplied_usd,
        "total_borrowed_usd":           total_borrowed_usd,
        "gross_spread_pct":             gross_spread,
        "net_interest_margin_pct":      nim_pct,
        "protocol_revenue_usd_annual":  revenue_annual,
        "supplier_effective_yield_pct": supplier_yield,
        "nim_efficiency_score":         eff_score,
        "nim_label":                    label,
        "timestamp":                    time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(protocols: list, config: dict | None = None) -> dict:
    """
    Analyze a list of lending protocols and produce a summary.

    Parameters
    ----------
    protocols : list[dict]
        List of protocol dicts (see :func:`analyze`).
    config : dict, optional
        Forwarded to :func:`analyze`.

    Returns
    -------
    dict
        Summary with keys:
        - total_protocols
        - results                       – list of per-protocol analyses
        - best_nim_protocol             – name of protocol with highest NIM (or None)
        - worst_nim_protocol            – name of protocol with lowest NIM (or None)
        - avg_nim_pct
        - inverted_count                – number of protocols with INVERTED_SPREAD
        - avg_efficiency_score
    """
    if not isinstance(protocols, list):
        protocols = []

    results: list[dict] = [
        analyze(p if isinstance(p, dict) else {}, config=config)
        for p in protocols
    ]

    total = len(results)
    if total == 0:
        return {
            "total_protocols":      0,
            "results":              [],
            "best_nim_protocol":    None,
            "worst_nim_protocol":   None,
            "avg_nim_pct":          0.0,
            "inverted_count":       0,
            "avg_efficiency_score": 0.0,
        }

    best  = max(results, key=lambda r: r["net_interest_margin_pct"])
    worst = min(results, key=lambda r: r["net_interest_margin_pct"])
    avg_nim   = sum(r["net_interest_margin_pct"] for r in results) / total
    avg_score = sum(r["nim_efficiency_score"] for r in results) / total
    inverted  = sum(1 for r in results if r["nim_label"] == NIM_INVERTED_SPREAD)

    return {
        "total_protocols":      total,
        "results":              results,
        "best_nim_protocol":    best["protocol_name"],
        "worst_nim_protocol":   worst["protocol_name"],
        "avg_nim_pct":          avg_nim,
        "inverted_count":       inverted,
        "avg_efficiency_score": avg_score,
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolNetInterestMarginAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolNetInterestMarginAnalyzer()
    >>> r = a.analyze({"protocol_name": "Aave V3", "supply_apy_pct": 3.5, ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, protocol: dict) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(protocol, config=self._config)

    def analyze_portfolio(self, protocols: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(protocols, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = [
        {
            "protocol_name":        "Aave V3 USDC",
            "supply_apy_pct":       3.5,
            "borrow_apy_pct":       5.8,
            "utilization_rate_pct": 80.0,
            "reserve_factor_pct":   10.0,
            "total_supplied_usd":   2_000_000_000.0,
            "total_borrowed_usd":   1_600_000_000.0,
        },
        {
            "protocol_name":        "Morpho Steakhouse",
            "supply_apy_pct":       5.5,
            "borrow_apy_pct":       7.2,
            "utilization_rate_pct": 92.0,
            "reserve_factor_pct":   5.0,
            "total_supplied_usd":   500_000_000.0,
            "total_borrowed_usd":   460_000_000.0,
        },
        {
            "protocol_name":        "Inverted Market",
            "supply_apy_pct":       6.0,
            "borrow_apy_pct":       5.5,
            "utilization_rate_pct": 70.0,
            "reserve_factor_pct":   0.0,
            "total_supplied_usd":   50_000_000.0,
            "total_borrowed_usd":   35_000_000.0,
        },
    ]

    import json as _json
    for p in _demo:
        r = analyze(p)
        print(_json.dumps(
            {k: v for k, v in r.items() if k != "timestamp"},
            indent=2, default=str
        ))
        print()

    print("---- portfolio ----")
    summary = analyze_portfolio(_demo)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)

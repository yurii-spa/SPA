"""Rebalance Cost Model (MP-583).

Estimates the *cost* of executing a portfolio rebalance (gas + slippage)
and judges whether the rebalance is worthwhile, given the projected APY
gain.  This is the missing cost-benefit link between
``spa_core/paper_trading/rebalance_trigger.py`` (decides *when* to
rebalance) and ``spa_core/analytics/yield_optimizer.py`` (decides the
*target* weights).

Design constraints
------------------
* Pure stdlib + math — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* Strictly read-only except :meth:`save_report` which writes atomically
  (tmp + ``os.replace``) to ``data/rebalance_cost_report.json``.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Gas Cost
--------
Each conceptual "trade" comprises two on-chain legs (exit + entry)::

    gas_cost_usd = n_trades · 2 · GAS_PER_LEG · gas_price_gwei · 1e-9 · eth_price_usd

Defaults: ``GAS_PER_LEG = 180_000``, ``DEFAULT_GAS_PRICE_GWEI = 20.0``,
``DEFAULT_ETH_PRICE_USD = 3000.0``.

Slippage Cost
-------------
Per trade, a slippage rate (in basis points) is derived from the
adapter tier and the *utilisation* (notional / TVL)::

    base_bps    = {T1: 2, T2: 5, T3: 10}      (default T2 = 5)
    premium     = min(utilisation / 0.10, 1.0) · (MAX_SLIPPAGE_BPS - base)
    bps         = clamp(base + premium [+ lock_penalty], base, MAX_SLIPPAGE_BPS)
    cost_usd    = notional_usd · bps / 1e4

``redemption_type == 'lock'`` adds a flat ``+25`` bps penalty before the
final clamp; ``'instant'`` adds nothing.

Break-Even Horizon
------------------
::
    daily_gain      = portfolio_value · (apy_gain_pct / 100) / 365
    break_even_days = cost_usd / daily_gain      (inf if daily_gain ≤ 0)

Worthwhile Verdict
------------------
* ``WORTHWHILE``     — break_even_days ≤ 0.5 × max_break_even_days
* ``MARGINAL``       — break_even_days ≤ max_break_even_days
* ``NOT_WORTHWHILE`` — otherwise (also if apy_gain ≤ 0 / break-even ∞)

Public API
----------
``RebalanceCostModel(data_dir="data")``

Module-level functions:

    estimate_gas_cost(n_trades, gas_price_gwei=None, eth_price_usd=None) → float
    estimate_slippage_cost(trades) → float
    compute_rebalance_cost(current_weights, target_weights, portfolio_value,
                           adapters=None, gas_price_gwei=None,
                           eth_price_usd=None) → dict
    compute_break_even_days(cost_usd, apy_gain_pct, portfolio_value) → float
    is_rebalance_worthwhile(...) → dict
    get_cost_report(...) → dict
    save_report(report, label=None) → str
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Gas model
GAS_PER_LEG: int = 180_000               # gas units per on-chain leg
LEGS_PER_TRADE: int = 2                   # exit + entry
DEFAULT_GAS_PRICE_GWEI: float = 20.0
DEFAULT_ETH_PRICE_USD: float = 3000.0
GWEI_TO_ETH: float = 1e-9

# Slippage model
_BASE_BPS_BY_TIER: Dict[str, float] = {
    "T1": 2.0,
    "T2": 5.0,
    "T3": 10.0,
}
_DEFAULT_TIER: str = "T2"
_DEFAULT_BASE_BPS: float = 5.0
MAX_SLIPPAGE_BPS: float = 300.0
# Utilisation at which the slippage premium saturates (10% of TVL)
_UTILISATION_SATURATION: float = 0.10
# Flat penalty (bps) applied before clamp for lock-up redemption
_LOCK_PENALTY_BPS: float = 25.0

# Rebalance trade detection
MIN_TRADE_USD: float = 10.0               # ignore dust trades below this notional
BPS_DENOMINATOR: float = 1e4

# Report / persistence
SCHEMA_VERSION: str = "1.0"
_REPORT_FILE: str = "rebalance_cost_report.json"
RING_BUFFER: int = 180

# Verdict labels
VERDICT_WORTHWHILE: str = "WORTHWHILE"
VERDICT_MARGINAL: str = "MARGINAL"
VERDICT_NOT_WORTHWHILE: str = "NOT_WORTHWHILE"

# Report warning thresholds
_HIGH_TURNOVER_PCT: float = 50.0
_HIGH_COST_BPS: float = 100.0

# Recognised redemption types
_REDEMPTION_TYPES = ("instant", "batched", "lock")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(
    value: Any,
    default: float = 0.0,
    min_value: Optional[float] = None,
) -> float:
    """Coerce *value* to float; return *default* on failure.

    Parameters
    ----------
    value:
        Anything float-coercible (None / non-numeric → *default*).
    default:
        Value returned when coercion fails.
    min_value:
        If provided, the result is clamped to be ≥ ``min_value`` (after a
        successful coercion *and* for the default path).
    """
    if value is None:
        result = default
    else:
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = default
    if not math.isfinite(result):
        result = default
    if min_value is not None and result < min_value:
        result = min_value
    return result


def _normalise_weights(d: Dict[str, float]) -> Dict[str, float]:
    """Return normalised weights (sum → 1.0); negatives treated as 0.

    Returns an empty dict if the total positive weight is ≤ 0.
    """
    pos: Dict[str, float] = {}
    for k, v in (d or {}).items():
        fv = _safe_float(v, 0.0)
        if fv > 0.0:
            pos[str(k)] = fv
    total = sum(pos.values())
    if total <= 0.0:
        return {}
    return {k: v / total for k, v in pos.items()}


def _normalise_tier(tier: Any) -> str:
    """Return a canonical tier string (T1/T2/T3); fall back to default T2."""
    s = str(tier).strip().upper() if tier is not None else ""
    return s if s in _BASE_BPS_BY_TIER else _DEFAULT_TIER


def _normalise_redemption(redemption_type: Any) -> str:
    """Return a canonical redemption string; fall back to 'instant'."""
    s = str(redemption_type).strip().lower() if redemption_type is not None else ""
    return s if s in _REDEMPTION_TYPES else "instant"


def _adapter_field(adapter: Any, *names: str) -> Any:
    """Read the first present field from an adapter (dict key or object attr).

    Returns ``None`` when none of *names* resolve to a non-None value.
    """
    if adapter is None:
        return None
    for name in names:
        if isinstance(adapter, dict):
            if name in adapter and adapter[name] is not None:
                return adapter[name]
        else:
            val = getattr(adapter, name, None)
            if val is not None:
                return val
    return None


# ---------------------------------------------------------------------------
# Gas
# ---------------------------------------------------------------------------

def estimate_gas_cost(
    n_trades: int,
    gas_price_gwei: Optional[float] = None,
    eth_price_usd: Optional[float] = None,
) -> float:
    """Estimate the total USD gas cost of executing *n_trades* trades.

    Each trade = one exit leg + one entry leg = 2 legs::

        cost_usd = n_trades · 2 · GAS_PER_LEG · gas_price_gwei · 1e-9 · eth_price_usd

    Parameters
    ----------
    n_trades:
        Number of rebalance trades (≤ 0 → 0.0).
    gas_price_gwei:
        Gas price in gwei (None → :data:`DEFAULT_GAS_PRICE_GWEI`; negatives
        clamped to 0).
    eth_price_usd:
        ETH price in USD (None → :data:`DEFAULT_ETH_PRICE_USD`; negatives
        clamped to 0).

    Returns
    -------
    float
        Total gas cost in USD (≥ 0).
    """
    try:
        n = int(n_trades)
    except (TypeError, ValueError):
        return 0.0
    if n <= 0:
        return 0.0

    gwei = _safe_float(
        gas_price_gwei if gas_price_gwei is not None else DEFAULT_GAS_PRICE_GWEI,
        DEFAULT_GAS_PRICE_GWEI,
        min_value=0.0,
    )
    eth = _safe_float(
        eth_price_usd if eth_price_usd is not None else DEFAULT_ETH_PRICE_USD,
        DEFAULT_ETH_PRICE_USD,
        min_value=0.0,
    )

    cost = n * LEGS_PER_TRADE * GAS_PER_LEG * gwei * GWEI_TO_ETH * eth
    return round(max(cost, 0.0), 8)


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------

def _slippage_bps_for_trade(trade: Dict[str, Any]) -> float:
    """Return the slippage rate (basis points) for a single *trade*.

    Trade fields (all optional except ``notional_usd``)::

        notional_usd      float — trade size in USD
        tvl_usd           float — adapter TVL in USD (utilisation denominator)
        tier              str   — "T1" / "T2" / "T3" (default T2)
        redemption_type   str   — "instant" / "batched" / "lock"

    Logic::

        base       = base_bps_by_tier(tier)
        util       = notional / tvl    (0 when tvl ≤ 0)
        premium    = min(util / 0.10, 1.0) · (MAX_SLIPPAGE_BPS - base)
        bps        = base + premium [+ lock_penalty]
        bps        = clamp(bps, base, MAX_SLIPPAGE_BPS)
    """
    trade = trade or {}
    tier = _normalise_tier(trade.get("tier"))
    base = _BASE_BPS_BY_TIER.get(tier, _DEFAULT_BASE_BPS)

    notional = _safe_float(trade.get("notional_usd"), 0.0, min_value=0.0)
    tvl = _safe_float(trade.get("tvl_usd"), 0.0, min_value=0.0)

    utilisation = (notional / tvl) if tvl > 0.0 else 0.0
    util_frac = min(utilisation / _UTILISATION_SATURATION, 1.0) if utilisation > 0 else 0.0
    premium = util_frac * (MAX_SLIPPAGE_BPS - base)

    bps = base + premium

    redemption = _normalise_redemption(trade.get("redemption_type"))
    if redemption == "lock":
        bps += _LOCK_PENALTY_BPS

    # Final clamp to [base, MAX_SLIPPAGE_BPS]
    bps = max(base, min(bps, MAX_SLIPPAGE_BPS))
    return round(bps, 6)


def estimate_slippage_cost(trades: List[Dict[str, Any]]) -> float:
    """Estimate the total USD slippage cost across *trades*.

    Parameters
    ----------
    trades:
        List of trade dicts ``{adapter_id, notional_usd, tvl_usd(optional),
        tier(optional), redemption_type(optional)}``.

    Returns
    -------
    float
        Total slippage cost in USD (≥ 0).
    """
    total = 0.0
    for trade in (trades or []):
        notional = _safe_float((trade or {}).get("notional_usd"), 0.0, min_value=0.0)
        if notional <= 0.0:
            continue
        bps = _slippage_bps_for_trade(trade)
        total += notional * bps / BPS_DENOMINATOR
    return round(max(total, 0.0), 8)


# ---------------------------------------------------------------------------
# Core rebalance cost
# ---------------------------------------------------------------------------

def compute_rebalance_cost(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    portfolio_value: float,
    adapters: Optional[Dict[str, Any]] = None,
    gas_price_gwei: Optional[float] = None,
    eth_price_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute the gas + slippage cost of rebalancing from *current* to *target*.

    Parameters
    ----------
    current_weights, target_weights:
        ``{adapter_id: weight_fraction}`` — normalised independently
        (negatives → 0).
    portfolio_value:
        Total portfolio value in USD (≤ 0 → no trades, zero cost).
    adapters:
        Optional ``{adapter_id: adapter dict/obj}`` used to enrich each
        trade with ``tvl_usd`` / ``tier`` / ``redemption_type`` for the
        slippage model.
    gas_price_gwei, eth_price_usd:
        Optional overrides for the gas model.

    Returns
    -------
    dict with keys::

        n_trades          int
        turnover_pct      float
        gas_cost_usd      float
        slippage_cost_usd float
        total_cost_usd    float
        cost_bps          float
        trades            list[dict]  — {adapter_id, notional_usd,
                                         slippage_bps, direction}
    """
    pv = _safe_float(portfolio_value, 0.0)
    cur = _normalise_weights(current_weights)
    tgt = _normalise_weights(target_weights)
    adapters = adapters or {}

    all_ids = set(cur.keys()) | set(tgt.keys())

    trades: List[Dict[str, Any]] = []
    sum_abs_delta = 0.0

    for adapter_id in sorted(all_ids):
        delta = tgt.get(adapter_id, 0.0) - cur.get(adapter_id, 0.0)
        sum_abs_delta += abs(delta)

        notional = abs(delta) * pv if pv > 0.0 else 0.0
        if notional < MIN_TRADE_USD:
            continue

        adapter = adapters.get(adapter_id)
        tvl = _safe_float(_adapter_field(adapter, "tvl_usd", "tvl"), 0.0, min_value=0.0)
        tier = _normalise_tier(_adapter_field(adapter, "tier"))
        redemption = _normalise_redemption(
            _adapter_field(adapter, "redemption_type", "redemption")
        )
        direction = "enter" if delta > 0.0 else "exit"

        trade = {
            "adapter_id": adapter_id,
            "notional_usd": round(notional, 8),
            "tvl_usd": tvl,
            "tier": tier,
            "redemption_type": redemption,
            "direction": direction,
        }
        trade["slippage_bps"] = _slippage_bps_for_trade(trade)
        trades.append(trade)

    n_trades = len(trades)
    gas_cost = estimate_gas_cost(n_trades, gas_price_gwei, eth_price_usd)
    slippage_cost = estimate_slippage_cost(trades)
    total_cost = round(gas_cost + slippage_cost, 8)

    turnover_pct = round((sum_abs_delta / 2.0) * 100.0, 6)
    cost_bps = round(total_cost / pv * BPS_DENOMINATOR, 6) if pv > 0.0 else 0.0

    # Public trade view (slim)
    trade_view = [
        {
            "adapter_id": t["adapter_id"],
            "notional_usd": t["notional_usd"],
            "slippage_bps": t["slippage_bps"],
            "direction": t["direction"],
        }
        for t in trades
    ]

    return {
        "n_trades": n_trades,
        "turnover_pct": turnover_pct,
        "gas_cost_usd": gas_cost,
        "slippage_cost_usd": slippage_cost,
        "total_cost_usd": total_cost,
        "cost_bps": cost_bps,
        "trades": trade_view,
    }


# ---------------------------------------------------------------------------
# Break-even
# ---------------------------------------------------------------------------

def compute_break_even_days(
    cost_usd: float,
    apy_gain_pct: float,
    portfolio_value: float,
) -> float:
    """Days required for the APY gain to recoup *cost_usd*.

    ::
        daily_gain      = portfolio_value · (apy_gain_pct / 100) / 365
        break_even_days = cost_usd / daily_gain

    Parameters
    ----------
    cost_usd:
        One-time rebalance cost in USD (≤ 0 → 0.0 days).
    apy_gain_pct:
        Expected APY improvement in percentage points.
    portfolio_value:
        Portfolio value in USD.

    Returns
    -------
    float
        Break-even horizon in days; ``float('inf')`` when the daily gain
        is non-positive.
    """
    cost = _safe_float(cost_usd, 0.0)
    if cost <= 0.0:
        return 0.0

    pv = _safe_float(portfolio_value, 0.0)
    gain_pct = _safe_float(apy_gain_pct, 0.0)
    daily_gain = pv * (gain_pct / 100.0) / 365.0
    if daily_gain <= 0.0:
        return float("inf")
    return round(cost / daily_gain, 6)


# ---------------------------------------------------------------------------
# Worthwhile verdict
# ---------------------------------------------------------------------------

def is_rebalance_worthwhile(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    portfolio_value: float,
    current_apy_pct: float,
    target_apy_pct: float,
    adapters: Optional[Dict[str, Any]] = None,
    max_break_even_days: float = 30.0,
    gas_price_gwei: Optional[float] = None,
    eth_price_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Decide whether rebalancing is worth the cost.

    Combines :func:`compute_rebalance_cost` and
    :func:`compute_break_even_days`, then classifies the result.

    Verdict::

        WORTHWHILE     — break_even_days ≤ 0.5 × max_break_even_days
        MARGINAL       — break_even_days ≤ max_break_even_days
        NOT_WORTHWHILE — otherwise (or apy_gain ≤ 0 / break-even ∞)

    Returns
    -------
    dict
        The :func:`compute_rebalance_cost` summary merged with
        ``{apy_gain_pct, break_even_days, max_break_even_days, verdict,
        recommendation}``.
    """
    cost = compute_rebalance_cost(
        current_weights,
        target_weights,
        portfolio_value,
        adapters=adapters,
        gas_price_gwei=gas_price_gwei,
        eth_price_usd=eth_price_usd,
    )

    apy_gain_pct = round(
        _safe_float(target_apy_pct, 0.0) - _safe_float(current_apy_pct, 0.0), 6
    )
    break_even_days = compute_break_even_days(
        cost["total_cost_usd"], apy_gain_pct, portfolio_value
    )

    max_days = _safe_float(max_break_even_days, 30.0, min_value=0.0)

    if apy_gain_pct <= 0.0 or math.isinf(break_even_days):
        verdict = VERDICT_NOT_WORTHWHILE
    elif break_even_days <= max_days * 0.5:
        verdict = VERDICT_WORTHWHILE
    elif break_even_days <= max_days:
        verdict = VERDICT_MARGINAL
    else:
        verdict = VERDICT_NOT_WORTHWHILE

    if cost["n_trades"] == 0:
        recommendation = "No trades required — portfolio already at target."
    elif verdict == VERDICT_WORTHWHILE:
        recommendation = (
            f"Rebalance: cost ${cost['total_cost_usd']:.2f} recouped in "
            f"{break_even_days:.1f}d (< {max_days * 0.5:.0f}d)."
        )
    elif verdict == VERDICT_MARGINAL:
        recommendation = (
            f"Marginal: break-even {break_even_days:.1f}d near limit "
            f"{max_days:.0f}d — rebalance only if APY gain is reliable."
        )
    elif apy_gain_pct <= 0.0:
        recommendation = (
            f"Skip: target APY gain is {apy_gain_pct:.2f}pp (no improvement)."
        )
    else:
        be_str = "never" if math.isinf(break_even_days) else f"{break_even_days:.0f}d"
        recommendation = (
            f"Skip: break-even {be_str} exceeds limit {max_days:.0f}d."
        )

    result = dict(cost)
    result.update(
        {
            "apy_gain_pct": apy_gain_pct,
            "break_even_days": break_even_days,
            "max_break_even_days": max_days,
            "verdict": verdict,
            "recommendation": recommendation,
        }
    )
    return result


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def get_cost_report(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    portfolio_value: float,
    current_apy_pct: float,
    target_apy_pct: float,
    adapters: Optional[Dict[str, Any]] = None,
    max_break_even_days: float = 30.0,
    gas_price_gwei: Optional[float] = None,
    eth_price_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a full, advisory rebalance-cost report.

    Returns
    -------
    dict with keys::

        schema_version     str    — :data:`SCHEMA_VERSION`
        generated_at       str    — ISO-8601 UTC timestamp
        portfolio_value    float
        n_trades           int
        turnover_pct       float
        gas_cost_usd       float
        slippage_cost_usd  float
        total_cost_usd     float
        cost_bps           float
        apy_gain_pct       float
        break_even_days    float  (may be inf)
        verdict            str
        recommendation     str
        trades             list[dict]
        warnings           list[str]
    """
    pv = _safe_float(portfolio_value, 0.0)
    verdict_info = is_rebalance_worthwhile(
        current_weights,
        target_weights,
        portfolio_value,
        current_apy_pct,
        target_apy_pct,
        adapters=adapters,
        max_break_even_days=max_break_even_days,
        gas_price_gwei=gas_price_gwei,
        eth_price_usd=eth_price_usd,
    )

    warnings: List[str] = []
    if pv <= 0.0:
        warnings.append(
            f"portfolio_value {pv:.2f} ≤ 0 — costs/break-even are undefined."
        )
    if verdict_info["turnover_pct"] > _HIGH_TURNOVER_PCT:
        warnings.append(
            f"High turnover {verdict_info['turnover_pct']:.1f}% "
            f"(> {_HIGH_TURNOVER_PCT:.0f}%) — large rebalance."
        )
    if verdict_info["cost_bps"] > _HIGH_COST_BPS:
        warnings.append(
            f"High cost {verdict_info['cost_bps']:.1f} bps "
            f"(> {_HIGH_COST_BPS:.0f} bps) of portfolio value."
        )
    be = verdict_info["break_even_days"]
    if math.isinf(be):
        warnings.append("Break-even horizon is infinite (no positive APY gain).")
    elif be > verdict_info["max_break_even_days"]:
        warnings.append(
            f"Break-even {be:.1f}d exceeds threshold "
            f"{verdict_info['max_break_even_days']:.0f}d."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_value": round(pv, 8),
        "n_trades": verdict_info["n_trades"],
        "turnover_pct": verdict_info["turnover_pct"],
        "gas_cost_usd": verdict_info["gas_cost_usd"],
        "slippage_cost_usd": verdict_info["slippage_cost_usd"],
        "total_cost_usd": verdict_info["total_cost_usd"],
        "cost_bps": verdict_info["cost_bps"],
        "apy_gain_pct": verdict_info["apy_gain_pct"],
        "break_even_days": verdict_info["break_even_days"],
        "verdict": verdict_info["verdict"],
        "recommendation": verdict_info["recommendation"],
        "trades": verdict_info["trades"],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# RebalanceCostModel
# ---------------------------------------------------------------------------

class RebalanceCostModel:
    """Deterministic, advisory rebalance cost-benefit model.

    All computation is pure (no IO except :meth:`save_report`).
    No external dependencies — stdlib + math only.

    Parameters
    ----------
    data_dir:
        Directory containing ``rebalance_cost_report.json`` (write target
        for :meth:`save_report`).  Defaults to ``"data"`` relative to CWD.
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Thin instance wrappers over the module-level functions
    # ------------------------------------------------------------------

    def estimate_gas_cost(
        self,
        n_trades: int,
        gas_price_gwei: Optional[float] = None,
        eth_price_usd: Optional[float] = None,
    ) -> float:
        """See :func:`estimate_gas_cost`."""
        return estimate_gas_cost(n_trades, gas_price_gwei, eth_price_usd)

    def estimate_slippage_cost(self, trades: List[Dict[str, Any]]) -> float:
        """See :func:`estimate_slippage_cost`."""
        return estimate_slippage_cost(trades)

    def compute_rebalance_cost(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        portfolio_value: float,
        adapters: Optional[Dict[str, Any]] = None,
        gas_price_gwei: Optional[float] = None,
        eth_price_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """See :func:`compute_rebalance_cost`."""
        return compute_rebalance_cost(
            current_weights,
            target_weights,
            portfolio_value,
            adapters=adapters,
            gas_price_gwei=gas_price_gwei,
            eth_price_usd=eth_price_usd,
        )

    def compute_break_even_days(
        self,
        cost_usd: float,
        apy_gain_pct: float,
        portfolio_value: float,
    ) -> float:
        """See :func:`compute_break_even_days`."""
        return compute_break_even_days(cost_usd, apy_gain_pct, portfolio_value)

    def is_rebalance_worthwhile(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        portfolio_value: float,
        current_apy_pct: float,
        target_apy_pct: float,
        adapters: Optional[Dict[str, Any]] = None,
        max_break_even_days: float = 30.0,
        gas_price_gwei: Optional[float] = None,
        eth_price_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """See :func:`is_rebalance_worthwhile`."""
        return is_rebalance_worthwhile(
            current_weights,
            target_weights,
            portfolio_value,
            current_apy_pct,
            target_apy_pct,
            adapters=adapters,
            max_break_even_days=max_break_even_days,
            gas_price_gwei=gas_price_gwei,
            eth_price_usd=eth_price_usd,
        )

    def get_cost_report(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        portfolio_value: float,
        current_apy_pct: float,
        target_apy_pct: float,
        adapters: Optional[Dict[str, Any]] = None,
        max_break_even_days: float = 30.0,
        gas_price_gwei: Optional[float] = None,
        eth_price_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """See :func:`get_cost_report`."""
        return get_cost_report(
            current_weights,
            target_weights,
            portfolio_value,
            current_apy_pct,
            target_apy_pct,
            adapters=adapters,
            max_break_even_days=max_break_even_days,
            gas_price_gwei=gas_price_gwei,
            eth_price_usd=eth_price_usd,
        )

    # ------------------------------------------------------------------
    # save_report
    # ------------------------------------------------------------------

    def save_report(self, report: Dict[str, Any], label: Optional[str] = None) -> str:
        """Atomically save *report* to ``<data_dir>/rebalance_cost_report.json``.

        Maintains a ``history`` ring-buffer of the last :data:`RING_BUFFER`
        reports inside the file.  Uses ``tmp-file + os.replace`` for crash
        safety.

        Parameters
        ----------
        report:
            The dict returned by :meth:`get_cost_report` (or any valid
            rebalance-cost report dict).
        label:
            Optional human label attached to this report entry.

        Returns
        -------
        str
            The path of the written report file.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._data_dir / _REPORT_FILE

        entry = dict(report or {})
        if label is not None:
            entry["label"] = str(label)

        # Load existing history
        history: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                history = existing.get("history", [])
                if not isinstance(history, list):
                    history = []
            except (json.JSONDecodeError, OSError):
                history = []

        history.append(entry)
        if len(history) > RING_BUFFER:
            history = history[-RING_BUFFER:]

        doc = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "latest": entry,
            "history": history,
            "history_depth": len(history),
        }

        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(out_path))

        return str(out_path)


# ---------------------------------------------------------------------------
# Module-level convenience exports
# ---------------------------------------------------------------------------

__all__ = [
    "RebalanceCostModel",
    "estimate_gas_cost",
    "estimate_slippage_cost",
    "compute_rebalance_cost",
    "compute_break_even_days",
    "is_rebalance_worthwhile",
    "get_cost_report",
    "_slippage_bps_for_trade",
    "_safe_float",
    "_normalise_weights",
    "_normalise_tier",
    "_normalise_redemption",
    "_adapter_field",
    "GAS_PER_LEG",
    "DEFAULT_GAS_PRICE_GWEI",
    "DEFAULT_ETH_PRICE_USD",
    "MAX_SLIPPAGE_BPS",
    "MIN_TRADE_USD",
    "RING_BUFFER",
    "SCHEMA_VERSION",
    "VERDICT_WORTHWHILE",
    "VERDICT_MARGINAL",
    "VERDICT_NOT_WORTHWHILE",
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _synthetic_scenario():
    """Return a small synthetic (current, target, pv, apys, adapters) tuple."""
    current_weights = {
        "aave_v3": 0.40,
        "morpho_blue": 0.30,
        "moonwell": 0.20,
        "extra_finance": 0.10,
    }
    target_weights = {
        "aave_v3": 0.25,
        "morpho_blue": 0.45,
        "moonwell": 0.10,
        "pendle_yt": 0.20,
    }
    adapters = {
        "aave_v3": {"tvl_usd": 1_200_000_000, "tier": "T1", "redemption_type": "instant"},
        "morpho_blue": {"tvl_usd": 400_000_000, "tier": "T1", "redemption_type": "instant"},
        "moonwell": {"tvl_usd": 80_000_000, "tier": "T2", "redemption_type": "instant"},
        "extra_finance": {"tvl_usd": 12_000_000, "tier": "T3", "redemption_type": "batched"},
        "pendle_yt": {"tvl_usd": 25_000_000, "tier": "T3", "redemption_type": "lock"},
    }
    portfolio_value = 1_000_000.0
    current_apy_pct = 6.5
    target_apy_pct = 8.2
    return (
        current_weights,
        target_weights,
        portfolio_value,
        current_apy_pct,
        target_apy_pct,
        adapters,
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry-point: run a small self-test and optionally persist a report."""
    parser = argparse.ArgumentParser(
        description="Rebalance Cost Model (MP-583) — estimate rebalance cost & worth"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Run a synthetic self-test and print a summary (default; no write).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Run the self-test and atomically save the report.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="PATH",
        help="Path to the data/ directory (default: data).",
    )
    args = parser.parse_args(argv)

    (
        current_weights,
        target_weights,
        portfolio_value,
        current_apy_pct,
        target_apy_pct,
        adapters,
    ) = _synthetic_scenario()

    model = RebalanceCostModel(data_dir=args.data_dir)
    report = model.get_cost_report(
        current_weights,
        target_weights,
        portfolio_value,
        current_apy_pct,
        target_apy_pct,
        adapters=adapters,
    )

    print("=== Rebalance Cost Model (MP-583) — self-test ===")
    print(f"  portfolio_value   : ${report['portfolio_value']:,.2f}")
    print(f"  n_trades          : {report['n_trades']}")
    print(f"  turnover_pct      : {report['turnover_pct']:.2f}%")
    print(f"  gas_cost_usd      : ${report['gas_cost_usd']:,.2f}")
    print(f"  slippage_cost_usd : ${report['slippage_cost_usd']:,.2f}")
    print(f"  total_cost_usd    : ${report['total_cost_usd']:,.2f}")
    print(f"  cost_bps          : {report['cost_bps']:.2f} bps")
    print(f"  apy_gain_pct      : {report['apy_gain_pct']:+.2f} pp")
    be = report["break_even_days"]
    be_str = "inf" if math.isinf(be) else f"{be:.2f}d"
    print(f"  break_even_days   : {be_str}")
    print(f"  verdict           : {report['verdict']}")
    print(f"  recommendation    : {report['recommendation']}")
    for t in report["trades"]:
        print(
            f"    - {t['adapter_id']:<16s} {t['direction']:<5s} "
            f"${t['notional_usd']:>12,.2f}  {t['slippage_bps']:>6.1f} bps"
        )
    for w in report["warnings"]:
        print(f"  [warn] {w}")

    if args.run:
        path = model.save_report(report, label="cli-self-test")
        print(f"\nSaved → {path}")
    else:
        print("\n(--check mode: not saved. Use --run to persist.)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

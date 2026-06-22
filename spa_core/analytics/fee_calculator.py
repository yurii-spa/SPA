"""spa_core/analytics/fee_calculator.py — MP-584.

FeeCalculator: deterministic computation of all fees (management, performance,
gas, slippage) for DeFi yield adapter operations.

Design constraints
------------------
* Stdlib + math only — no external dependencies.
* Pure advisory/read-only — never touches allocator, risk, execution, or I/O.
* LLM_FORBIDDEN: NOT imported from risk / execution / monitoring modules.
* All public methods are deterministic given their inputs.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reference ETH price in USD used for gas cost estimation.
_ETH_PRICE_USD: float = 3_000.0

# Gas units consumed by (operation, chain) pairs.
# L1 Ethereum costs are based on typical Aave/Compound interaction gas usage.
# L2 estimates reflect higher opcode counts but much lower effective gwei.
_GAS_UNITS: Dict[tuple, int] = {
    # ── Ethereum L1 ─────────────────────────────────────────────────────────
    ("deposit",   "ethereum"):   200_000,
    ("withdraw",  "ethereum"):   250_000,
    ("rebalance", "ethereum"):   500_000,
    # ── Arbitrum L2 ─────────────────────────────────────────────────────────
    ("deposit",   "arbitrum"):   450_000,
    ("withdraw",  "arbitrum"):   550_000,
    ("rebalance", "arbitrum"):   900_000,
    # ── Base L2 ─────────────────────────────────────────────────────────────
    ("deposit",   "base"):       450_000,
    ("withdraw",  "base"):       550_000,
    ("rebalance", "base"):       900_000,
    # ── Optimism L2 ─────────────────────────────────────────────────────────
    ("deposit",   "optimism"):   450_000,
    ("withdraw",  "optimism"):   550_000,
    ("rebalance", "optimism"):   900_000,
    # ── Polygon PoS ─────────────────────────────────────────────────────────
    ("deposit",   "polygon"):    200_000,
    ("withdraw",  "polygon"):    250_000,
    ("rebalance", "polygon"):    500_000,
}

# Fallback for unknown (operation, chain) combinations.
_DEFAULT_GAS_UNITS: int = 300_000

# Known operations and chains (used for normalisation).
_KNOWN_OPERATIONS = frozenset({"deposit", "withdraw", "rebalance"})
_KNOWN_CHAINS = frozenset({"ethereum", "arbitrum", "base", "optimism", "polygon"})

# Base slippage / price-impact rates by tier (as fractions of amount_usd).
_SLIPPAGE_RATES: Dict[str, float] = {
    "T1": 0.001,   # 0.1% — deep, battle-tested pools (Aave, Compound, Morpho)
    "T2": 0.003,   # 0.3% — mid-tier, reasonable depth (sFRAX, wUSDM, sDAI)
    "T3": 0.008,   # 0.8% — thin or specialised markets (Pendle YT, delta-neutral)
}
_DEFAULT_SLIPPAGE_RATE: float = _SLIPPAGE_RATES["T2"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float; return *default* on failure or non-finite."""
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _get_attr(obj: Any, *keys: str, default: Any = None) -> Any:
    """Try each key as a dict lookup then as an object attribute.

    Returns the value for the *first* key that resolves, or *default*.
    """
    for k in keys:
        if isinstance(obj, dict):
            if k in obj:
                return obj[k]
        else:
            v = getattr(obj, k, _SENTINEL)
            if v is not _SENTINEL:
                return v
    return default


class _Sentinel:
    """Private sentinel for missing attribute detection."""
    __slots__ = ()


_SENTINEL = _Sentinel()


def _normalise_tier(tier: Any) -> str:
    """Return a canonical tier string ('T1', 'T2', or 'T3').

    Falls back to 'T2' for any unrecognised value.
    """
    t = str(tier).strip().upper()
    return t if t in ("T1", "T2", "T3") else "T2"


def _normalise_apy_pct(raw: Any) -> float:
    """Normalise an APY value to percent (e.g. 0.05 → 5.0, 5.0 → 5.0)."""
    v = _safe_float(raw, 0.0)
    # If value is in (0, 1] it looks like a decimal fraction — convert.
    if 0.0 < v <= 1.0:
        return v * 100.0
    return v


# ---------------------------------------------------------------------------
# FeeCalculator
# ---------------------------------------------------------------------------

class FeeCalculator:
    """Deterministic fee & cost estimator for DeFi yield positions.

    All six public methods are pure functions of their arguments — no I/O,
    no network calls, no randomness.  The class carries no mutable state;
    multiple instances are equivalent.

    Usage
    -----
    ::

        calc = FeeCalculator()

        # One-shot cost breakdown for a $50 k Aave deposit held 30 days:
        cost = calc.compute_total_cost(
            amount_usd=50_000,
            operation="deposit",
            adapter={"apy_pct": 3.5, "tvl_usd": 10e9, "tier": "T1"},
            period_days=30,
        )
        # → {"management": 0.0, "performance": 0.0, "gas": 12.0,
        #     "slippage": 5.0, "total_usd": 17.0, "total_pct": 0.034}

        # Portfolio-level report:
        report = calc.get_fee_report(adapters, weights, portfolio_value=100_000)
    """

    # ------------------------------------------------------------------
    # 1. Management fee
    # ------------------------------------------------------------------

    def compute_management_fee(
        self,
        amount_usd: float,
        apy_pct: float,
        management_fee_pct: float = 0.0,
    ) -> float:
        """Annual management fee in USD charged on AUM.

        The fee is computed on the *full* position size regardless of yield.
        Callers should scale the result by ``period_days / 365`` when computing
        a sub-annual cost in :meth:`compute_total_cost`.

        Parameters
        ----------
        amount_usd:
            Position size (AUM) in USD.
        apy_pct:
            Gross APY in percent (e.g. ``5.0`` = 5 %).  Included for
            documentation / downstream calculations; the management fee is
            charged on AUM, not on yield.
        management_fee_pct:
            Annual management fee as a percentage of AUM (e.g. ``1.0`` = 1 %).
            Must be ≥ 0; negative values are treated as 0.

        Returns
        -------
        float
            Annual management fee in USD.
        """
        amount = max(0.0, _safe_float(amount_usd))
        fee_pct = max(0.0, _safe_float(management_fee_pct))
        return amount * (fee_pct / 100.0)

    # ------------------------------------------------------------------
    # 2. Performance fee
    # ------------------------------------------------------------------

    def compute_performance_fee(
        self,
        gross_pnl_usd: float,
        performance_fee_pct: float = 0.0,
        hurdle_rate: float = 0.04,
    ) -> float:
        """Performance fee on returns above the hurdle rate.

        The hurdle is applied as a fraction of ``gross_pnl_usd``: the first
        ``hurdle_rate × gross_pnl_usd`` is the "risk-free equivalent" that
        belongs entirely to the investor.  The manager charges
        ``performance_fee_pct`` only on the *excess* above that hurdle.

        Formula::

            hurdle_amount = gross_pnl_usd × hurdle_rate
            excess        = max(0, gross_pnl_usd − hurdle_amount)
            fee           = excess × (performance_fee_pct / 100)

        Parameters
        ----------
        gross_pnl_usd:
            Gross profit in USD for the measurement period.  Returns 0 when
            ``gross_pnl_usd ≤ 0`` (no fee on losses or zero return).
        performance_fee_pct:
            Performance fee charged on excess returns (e.g. ``20.0`` = 20 %).
            Negative values are clamped to 0.
        hurdle_rate:
            Minimum return fraction before the performance fee applies
            (e.g. ``0.04`` = 4 %).  Negative values are clamped to 0.

        Returns
        -------
        float
            Performance fee in USD.
        """
        pnl = _safe_float(gross_pnl_usd)
        fee_pct = max(0.0, _safe_float(performance_fee_pct))
        hurdle = max(0.0, _safe_float(hurdle_rate))

        if pnl <= 0.0:
            return 0.0

        hurdle_amount = pnl * hurdle
        excess = max(0.0, pnl - hurdle_amount)
        return excess * (fee_pct / 100.0)

    # ------------------------------------------------------------------
    # 3. Gas fee
    # ------------------------------------------------------------------

    def estimate_gas_fee_usd(
        self,
        operation: str,
        chain: str = "ethereum",
        gas_price_gwei: float = 20.0,
    ) -> float:
        """Estimate gas cost in USD for a single on-chain operation.

        Uses a static gas-units table (see module-level ``_GAS_UNITS``) and a
        reference ETH price of ${ETH_PRICE_USD} USD.  Unknown
        ``(operation, chain)`` pairs fall back to {DEFAULT_GAS} gas units.

        Formula::

            gas_eth = gas_units × gas_price_gwei × 1e-9
            gas_usd = gas_eth × ETH_PRICE_USD

        Parameters
        ----------
        operation:
            One of ``"deposit"``, ``"withdraw"``, ``"rebalance"``
            (case-insensitive).
        chain:
            One of ``"ethereum"``, ``"arbitrum"``, ``"base"``, ``"optimism"``,
            ``"polygon"`` (case-insensitive).  Unknown chains use the fallback.
        gas_price_gwei:
            Effective gas price in Gwei.  Negative values are clamped to 0.

        Returns
        -------
        float
            Estimated gas fee in USD.
        """.format(ETH_PRICE_USD=_ETH_PRICE_USD, DEFAULT_GAS=_DEFAULT_GAS_UNITS)
        op = str(operation).strip().lower()
        ch = str(chain).strip().lower()
        gwei = max(0.0, _safe_float(gas_price_gwei))

        gas_units = _GAS_UNITS.get((op, ch), _DEFAULT_GAS_UNITS)
        gas_eth = gas_units * gwei * 1e-9
        return gas_eth * _ETH_PRICE_USD

    # ------------------------------------------------------------------
    # 4. Slippage cost
    # ------------------------------------------------------------------

    def estimate_slippage_cost(
        self,
        amount_usd: float,
        adapter_tvl_usd: float,
        tier: str,
    ) -> float:
        """Estimate price-impact / slippage cost in USD.

        Base rate by tier:

        * T1 → 0.1 %  (Aave, Compound, Morpho — very deep pools)
        * T2 → 0.3 %  (sFRAX, wUSDM, sDAI, scrvUSD — moderate depth)
        * T3 → 0.8 %  (Pendle YT, delta-neutral — specialised / thin)

        The effective rate scales *linearly* with ``size_ratio = amount / TVL``
        (clamped to [0, 1])::

            effective_rate = base_rate × (1 + size_ratio)
            slippage_usd   = amount_usd × effective_rate

        A position of 0 % of TVL pays the base rate; a position equal to 100 %
        of TVL pays 2 × the base rate.

        Parameters
        ----------
        amount_usd:
            Trade or position size in USD.  Negative values → 0.
        adapter_tvl_usd:
            Protocol total-value-locked in USD.  If ≤ 0 the size-ratio is
            clamped to 1.0 (maximum slippage scaling).
        tier:
            Protocol risk tier (``"T1"``, ``"T2"``, or ``"T3"``).  Unknown
            tiers fall back to T2.

        Returns
        -------
        float
            Estimated slippage cost in USD.
        """
        amount = max(0.0, _safe_float(amount_usd))
        tvl = _safe_float(adapter_tvl_usd)
        t = _normalise_tier(tier)

        base_rate = _SLIPPAGE_RATES.get(t, _DEFAULT_SLIPPAGE_RATE)

        if tvl > 0:
            size_ratio = min(1.0, amount / tvl)
        else:
            size_ratio = 1.0  # worst-case when TVL is unknown / zero

        effective_rate = base_rate * (1.0 + size_ratio)
        return amount * effective_rate

    # ------------------------------------------------------------------
    # 5. Total cost breakdown
    # ------------------------------------------------------------------

    def compute_total_cost(
        self,
        amount_usd: float,
        operation: str,
        adapter: Any,
        period_days: int = 365,
    ) -> Dict[str, float]:
        """Full fee breakdown for a position over a given holding period.

        Reads the following fields from *adapter* (as dict keys or object
        attributes, in priority order):

        ========================  ====================  ==========
        Field                     Fallback key          Default
        ========================  ====================  ==========
        ``apy_pct``               ``apy``               0.0
        ``tvl_usd``               ``tvl``               0.0
        ``tier``                  —                     "T2"
        ``management_fee_pct``    —                     0.0
        ``performance_fee_pct``   —                     0.0
        ``hurdle_rate``           —                     0.04
        ``chain``                 —                     "ethereum"
        ========================  ====================  ==========

        APY normalisation: if the raw value is in ``(0, 1]`` it is assumed to
        be a decimal fraction and is multiplied by 100.

        Parameters
        ----------
        amount_usd:
            Position size in USD.  Negative values → 0.
        operation:
            One of ``"deposit"``, ``"withdraw"``, ``"rebalance"``.
        adapter:
            Dict or object describing the protocol (see table above).
        period_days:
            Number of days the position is held.  Default 365 (full year).

        Returns
        -------
        dict
            ``{management, performance, gas, slippage, total_usd, total_pct}``
            All values in USD except ``total_pct`` (% of ``amount_usd``).
        """
        amount = max(0.0, _safe_float(amount_usd))
        days = max(0, int(_safe_float(period_days)))
        year_frac = days / 365.0

        # ── Read adapter fields ────────────────────────────────────────────
        apy_pct = _normalise_apy_pct(_get_attr(adapter, "apy_pct", "apy", default=0.0))
        tvl = max(0.0, _safe_float(_get_attr(adapter, "tvl_usd", "tvl", default=0.0)))
        tier = _normalise_tier(_get_attr(adapter, "tier", default="T2"))
        mgmt_fee_pct = _safe_float(_get_attr(adapter, "management_fee_pct", default=0.0))
        perf_fee_pct = _safe_float(_get_attr(adapter, "performance_fee_pct", default=0.0))
        hurdle = _safe_float(_get_attr(adapter, "hurdle_rate", default=0.04))
        chain_raw = _get_attr(adapter, "chain", default="ethereum") or "ethereum"
        chain = str(chain_raw).strip().lower()

        # ── Fee components ────────────────────────────────────────────────
        # Management fee: annual × year_frac
        annual_mgmt = self.compute_management_fee(amount, apy_pct, mgmt_fee_pct)
        mgmt_fee = annual_mgmt * year_frac

        # Gross P&L for the period: AUM × APY × (days/365)
        gross_pnl = amount * (apy_pct / 100.0) * year_frac

        # Performance fee: on period P&L above hurdle
        perf_fee = self.compute_performance_fee(gross_pnl, perf_fee_pct, hurdle)

        # Gas fee: one-time, chain-aware, default 20 gwei
        gas_fee = self.estimate_gas_fee_usd(operation, chain, gas_price_gwei=20.0)

        # Slippage: one-time at entry (or exit for withdraw)
        slippage = self.estimate_slippage_cost(amount, tvl, tier)

        total_usd = mgmt_fee + perf_fee + gas_fee + slippage
        total_pct = (total_usd / amount * 100.0) if amount > 0 else 0.0

        return {
            "management": round(mgmt_fee, 6),
            "performance": round(perf_fee, 6),
            "gas":         round(gas_fee, 6),
            "slippage":    round(slippage, 6),
            "total_usd":   round(total_usd, 6),
            "total_pct":   round(total_pct, 6),
        }

    # ------------------------------------------------------------------
    # 6. Portfolio fee report
    # ------------------------------------------------------------------

    def get_fee_report(
        self,
        adapters: Sequence[Any],
        weights: Sequence[float],
        portfolio_value: float,
    ) -> Dict[str, Any]:
        """Fee & drag report across an entire portfolio of adapters.

        Weights are normalised internally (negative values zeroed, then
        divided by the total).  If all weights are zero or *adapters* is empty,
        equal weights are used.

        The report computes annual costs (``period_days=365``) for a
        ``"deposit"`` operation at each allocation.

        Parameters
        ----------
        adapters:
            Sequence of adapter dicts or objects (same schema as
            :meth:`compute_total_cost`).
        weights:
            Allocation weights (fractions).  Need not sum to 1.
        portfolio_value:
            Total portfolio value in USD.  Negative → 0.

        Returns
        -------
        dict
            ::

                {
                  "total_drag_usd":  float,   # absolute annual fee drag
                  "total_drag_pct":  float,   # drag as % of portfolio
                  "gross_apy":       float,   # weighted-average gross APY
                  "net_apy":         float,   # weighted-average net APY
                  "adapters": [               # per-adapter breakdown
                    {
                      "name":          str,
                      "weight":        float,
                      "amount_usd":    float,
                      "apy_pct":       float,
                      "management":    float,
                      "performance":   float,
                      "gas":           float,
                      "slippage":      float,
                      "total_cost_usd":float,
                      "net_return_usd":float,
                    }
                  ]
                }
        """
        pv = max(0.0, _safe_float(portfolio_value))
        n = len(adapters)

        # Normalise weights
        raw_weights = [max(0.0, _safe_float(w)) for w in weights]
        total_w = sum(raw_weights)
        if total_w <= 0 or n == 0:
            norm_weights = [1.0 / n] * n if n > 0 else []
        else:
            norm_weights = [w / total_w for w in raw_weights]

        adapter_rows: List[Dict[str, Any]] = []
        total_drag_usd = 0.0
        weighted_gross_apy = 0.0
        weighted_net_apy = 0.0

        for idx, (adapter, weight) in enumerate(zip(adapters, norm_weights)):
            amount = pv * weight

            # APY
            apy_pct = _normalise_apy_pct(
                _get_attr(adapter, "apy_pct", "apy", default=0.0)
            )

            # Name / protocol identifier
            name = str(
                _get_attr(adapter, "protocol", "name", "PROTOCOL", default=f"adapter_{idx}")
                or f"adapter_{idx}"
            )

            cost = self.compute_total_cost(amount, "deposit", adapter, period_days=365)

            gross_return_usd = amount * (apy_pct / 100.0)
            net_return_usd = gross_return_usd - cost["total_usd"]

            total_drag_usd += cost["total_usd"]
            weighted_gross_apy += apy_pct * weight
            net_apy_this = ((net_return_usd / amount) * 100.0) if amount > 0 else 0.0
            weighted_net_apy += net_apy_this * weight

            adapter_rows.append({
                "name":           name,
                "weight":         round(weight, 6),
                "amount_usd":     round(amount, 4),
                "apy_pct":        round(apy_pct, 4),
                "management":     cost["management"],
                "performance":    cost["performance"],
                "gas":            cost["gas"],
                "slippage":       cost["slippage"],
                "total_cost_usd": cost["total_usd"],
                "net_return_usd": round(net_return_usd, 4),
            })

        total_drag_pct = (total_drag_usd / pv * 100.0) if pv > 0 else 0.0

        return {
            "total_drag_usd": round(total_drag_usd, 4),
            "total_drag_pct": round(total_drag_pct, 6),
            "gross_apy":      round(weighted_gross_apy, 6),
            "net_apy":        round(weighted_net_apy, 6),
            "adapters":       adapter_rows,
        }

"""
MP-1119 ProtocolDeFiStrategyRebalancingCostAnalyzer
----------------------------------------------------
Calculates the true cost of periodic rebalancing for DeFi yield strategies —
including gas, slippage, and opportunity cost. Determines whether the target
APY improvement justifies the rebalancing cost.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "strategy_rebalancing_cost_log.json"
)
_LOG_CAP = 100

# Label thresholds by net_annual_gain_pct
_EFFICIENT_THRESHOLD  = 1.0
_ACCEPTABLE_THRESHOLD = 0.25
_MARGINAL_THRESHOLD   = 0.0
_COSTLY_THRESHOLD     = -0.5

# Minimum weight delta to count a position as needing rebalancing
_TRADE_DELTA_EPSILON = 1e-9


# ---------------------------------------------------------------------------
# Internal helpers (module-level for direct unit testing)
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
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
def _num_trades_needed(
    current_weights: list,
    target_weights: list,
) -> int:
    """Count positions requiring adjustment (|delta_weight| > epsilon).

    Uses min(len(current), len(target)) to avoid index errors on mismatched lists.
    """
    n = min(len(current_weights), len(target_weights))
    count = 0
    for i in range(n):
        if abs(float(target_weights[i]) - float(current_weights[i])) > _TRADE_DELTA_EPSILON:
            count += 1
    return count


def _total_slippage_cost_usd(
    current_weights: list,
    target_weights: list,
    asset_values_usd: list,
    slippage_per_trade_pct: float,
) -> float:
    """Total slippage cost for all required trades (USD).

    For each position with |delta_weight| > epsilon:
        trade_value_usd = |delta_weight_pct| / 100 * total_portfolio_usd
        slippage_usd    = trade_value_usd * slippage_per_trade_pct / 100

    Returns 0.0 when total portfolio is empty.
    """
    total_portfolio = sum(float(v) for v in asset_values_usd) if asset_values_usd else 0.0
    if total_portfolio <= 0.0:
        return 0.0

    n = min(len(current_weights), len(target_weights))
    total_slip = 0.0
    for i in range(n):
        delta = abs(float(target_weights[i]) - float(current_weights[i]))
        if delta > _TRADE_DELTA_EPSILON:
            trade_value = delta / 100.0 * total_portfolio
            total_slip += trade_value * float(slippage_per_trade_pct) / 100.0
    return round(total_slip, 6)


def _total_gas_cost_usd(num_trades: int, gas_per_trade_usd: float) -> float:
    """Total gas cost: num_trades * gas_per_trade_usd."""
    return round(float(num_trades) * float(gas_per_trade_usd), 6)


def _total_rebalance_cost_usd(slippage_cost_usd: float, gas_cost_usd: float) -> float:
    """Total rebalancing cost: slippage + gas."""
    return round(float(slippage_cost_usd) + float(gas_cost_usd), 6)


def _rebalance_cost_pct(total_cost_usd: float, total_portfolio_usd: float) -> float:
    """Rebalancing cost as % of portfolio value.

    Returns 0.0 when total_portfolio_usd <= 0.
    """
    if total_portfolio_usd <= 0.0:
        return 0.0
    return round(float(total_cost_usd) / float(total_portfolio_usd) * 100.0, 6)


def _annual_rebalance_cost_pct(
    cost_pct: float,
    rebalance_frequency_days: int,
) -> float:
    """Annualized rebalancing cost: cost_pct * 365 / frequency_days.

    Returns 0.0 when rebalance_frequency_days <= 0.
    """
    freq = int(rebalance_frequency_days)
    if freq <= 0:
        return 0.0
    return round(float(cost_pct) * 365.0 / float(freq), 6)


def _net_annual_gain_pct(
    target_apy_improvement_pct: float,
    annual_rebalance_cost_pct: float,
) -> float:
    """Net annual gain: target APY improvement minus annual rebalancing cost."""
    return round(
        float(target_apy_improvement_pct) - float(annual_rebalance_cost_pct),
        6,
    )


def _rebalance_label(net_annual_gain_pct: float) -> str:
    """Map net_annual_gain_pct → rebalance recommendation label.

    >  1.0 %        → EFFICIENT_REBALANCE
    >= 0.25 %       → ACCEPTABLE_COST
    >= 0.0 %        → MARGINAL_BENEFIT
    >= -0.5 %       → COSTLY_REBALANCE
    <  -0.5 %       → DONT_REBALANCE
    """
    g = float(net_annual_gain_pct)
    if g > _EFFICIENT_THRESHOLD:
        return "EFFICIENT_REBALANCE"
    if g >= _ACCEPTABLE_THRESHOLD:
        return "ACCEPTABLE_COST"
    if g >= _MARGINAL_THRESHOLD:
        return "MARGINAL_BENEFIT"
    if g >= _COSTLY_THRESHOLD:
        return "COSTLY_REBALANCE"
    return "DONT_REBALANCE"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolDeFiStrategyRebalancingCostAnalyzer:
    """
    Calculates the true cost of periodic rebalancing for DeFi yield strategies.

    Considers gas, slippage, and opportunity cost. Returns the net annual gain
    from rebalancing (APY improvement minus annualized costs) and a label
    indicating whether rebalancing is economically justified.

    Advisory / read-only — never modifies positions, risk policy, or trades.

    Usage
    -----
    analyzer = ProtocolDeFiStrategyRebalancingCostAnalyzer()
    result   = analyzer.analyze(data)
    """

    def analyze(self, data: dict, config: dict | None = None) -> dict:
        """
        Analyze whether rebalancing is cost-effective.

        Parameters
        ----------
        data : dict
            protocol_name                : str
            current_weights              : list[float] — current allocation % (must sum ~100)
            target_weights               : list[float] — desired allocation %
            asset_values_usd             : list[float] — current USD value per position
            slippage_per_trade_pct       : float — estimated slippage per swap (e.g. 0.1)
            gas_per_trade_usd            : float — gas cost per swap (USD)
            portfolio_apy_pct            : float — current blended APY (%)
            target_apy_improvement_pct   : float — APY gain achieved by rebalancing (%)
            rebalance_frequency_days     : int   — how often this rebalance would run

        config : dict, optional
            log_path  : str  — override default log file path
            write_log : bool — write to log (default True)

        Returns
        -------
        dict
            protocol_name, num_trades_needed, total_slippage_cost_usd,
            total_gas_cost_usd, total_rebalance_cost_usd, rebalance_cost_pct,
            annual_rebalance_cost_pct, net_annual_gain_pct, rebalance_label,
            total_portfolio_usd, timestamp
        """
        cfg       = config or {}
        log_path  = cfg.get("log_path", _LOG_PATH)
        write_log = cfg.get("write_log", True)

        name        = str(data.get("protocol_name", "UNKNOWN"))
        cur_w       = list(data.get("current_weights", []))
        tgt_w       = list(data.get("target_weights", []))
        asset_vals  = list(data.get("asset_values_usd", []))
        slip_pct    = float(data.get("slippage_per_trade_pct", 0.0))
        gas_usd     = float(data.get("gas_per_trade_usd", 0.0))
        port_apy    = float(data.get("portfolio_apy_pct", 0.0))
        improvement = float(data.get("target_apy_improvement_pct", 0.0))
        freq_days   = int(data.get("rebalance_frequency_days", 1))

        total_portfolio = sum(float(v) for v in asset_vals) if asset_vals else 0.0

        num_trades   = _num_trades_needed(cur_w, tgt_w)
        slip_cost    = _total_slippage_cost_usd(cur_w, tgt_w, asset_vals, slip_pct)
        gas_cost     = _total_gas_cost_usd(num_trades, gas_usd)
        total_cost   = _total_rebalance_cost_usd(slip_cost, gas_cost)
        cost_pct     = _rebalance_cost_pct(total_cost, total_portfolio)
        annual_cost  = _annual_rebalance_cost_pct(cost_pct, freq_days)
        net_gain     = _net_annual_gain_pct(improvement, annual_cost)
        label        = _rebalance_label(net_gain)

        ts: str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        result: dict[str, Any] = {
            "protocol_name":             name,
            "num_trades_needed":         num_trades,
            "total_slippage_cost_usd":   slip_cost,
            "total_gas_cost_usd":        gas_cost,
            "total_rebalance_cost_usd":  total_cost,
            "rebalance_cost_pct":        cost_pct,
            "annual_rebalance_cost_pct": annual_cost,
            "net_annual_gain_pct":       net_gain,
            "rebalance_label":           label,
            "total_portfolio_usd":       total_portfolio,
            "timestamp":                 ts,
        }

        if write_log:
            _atomic_log(log_path, {
                "timestamp":               ts,
                "protocol_name":           name,
                "num_trades_needed":       num_trades,
                "total_rebalance_cost_usd": total_cost,
                "net_annual_gain_pct":     net_gain,
                "rebalance_label":         label,
            })

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(data: dict, config: dict | None = None) -> dict:
    """Module-level convenience wrapper around ProtocolDeFiStrategyRebalancingCostAnalyzer."""
    return ProtocolDeFiStrategyRebalancingCostAnalyzer().analyze(data, config)

"""
MP-1100: DeFiProtocolFundingRateArbitrageAnalyzer
==================================================
Advisory-only analytics module.

Analyzes funding rate arbitrage opportunities between perpetual DEX funding rates
and spot yield protocols. Positive funding = shorts earn, negative = longs earn.
Delta-neutral strategies capture funding without directional exposure.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/funding_rate_arbitrage_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_FILENAME = "funding_rate_arbitrage_log.json"
LOG_MAX_ENTRIES = 100

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")


# ---------------------------------------------------------------------------
# Internal computation helpers
# ---------------------------------------------------------------------------

def _annualize_funding_rate(perp_funding_rate_8h_pct: float) -> float:
    """Convert 8-hour funding rate % to annualized %. 3 periods/day × 365 days."""
    return perp_funding_rate_8h_pct * 3.0 * 365.0


def _compute_net_arb_spread(
    funding_rate_annual_pct: float,
    spot_borrow_rate_annual_pct: float,
    spot_yield_annual_pct: float,
) -> float:
    """Net arbitrage spread = funding_annual - borrow_rate + spot_yield."""
    return funding_rate_annual_pct - spot_borrow_rate_annual_pct + spot_yield_annual_pct


def _compute_capital_required(
    position_size_usd: float,
    margin_requirement_pct: float,
    liquidation_buffer_pct: float,
) -> float:
    """Capital required = (margin_pct + buffer_pct) / 100 * position_size."""
    if position_size_usd <= 0:
        return 0.0
    return (margin_requirement_pct + liquidation_buffer_pct) / 100.0 * position_size_usd


def _compute_gas_drag(gas_cost_usd: float, capital_required_usd: float) -> float:
    """Gas drag expressed as % of capital. Returns 0 if capital is zero."""
    if capital_required_usd <= 0:
        return 0.0
    return gas_cost_usd / capital_required_usd * 100.0


def _compute_annualized_return_on_capital(
    net_arb_spread_pct: float,
    position_size_usd: float,
    capital_required_usd: float,
    gas_drag_pct: float,
) -> float:
    """
    Annualized return on capital.
    = net_spread * (position / capital) - gas_drag
    Returns 0 if capital is zero.
    """
    if capital_required_usd <= 0:
        return 0.0
    leverage = position_size_usd / capital_required_usd
    return net_arb_spread_pct * leverage - gas_drag_pct


def _compute_quality_score(annualized_return_on_capital_pct: float) -> int:
    """
    Quality score 0-100 based on annualized return on capital.
    Linear scale: 0% ROC → 0, 20%+ ROC → 100. Clamped to [0, 100].
    """
    if annualized_return_on_capital_pct <= 0:
        return 0
    raw = annualized_return_on_capital_pct / 20.0 * 100.0
    return min(100, int(raw))


def _classify_arb(annualized_return_on_capital_pct: float) -> str:
    """
    Classify arbitrage quality by annualized return on capital.

    > 15%  → PREMIUM_ARB
    8-15%  → GOOD_ARB
    3-8%   → MARGINAL_ARB
    0-3%   → BREAK_EVEN
    <= 0%  → NEGATIVE_ARB
    """
    roc = annualized_return_on_capital_pct
    if roc > 15.0:
        return "PREMIUM_ARB"
    elif roc >= 8.0:
        return "GOOD_ARB"
    elif roc >= 3.0:
        return "MARGINAL_ARB"
    elif roc >= 0.0:
        return "BREAK_EVEN"
    else:
        return "NEGATIVE_ARB"


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(data, path: str, data_dir: str) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _read_log(log_path: str) -> list:
    """Read existing log or return empty list."""
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(entry: dict, data_dir: str) -> None:
    """Append entry to ring-buffer log (max LOG_MAX_ENTRIES). Atomic write."""
    log_path = os.path.join(data_dir, LOG_FILENAME)
    entries = _read_log(log_path)
    entries.append(entry)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    _atomic_write_json(entries, log_path, data_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    perp_funding_rate_8h_pct: float,
    spot_borrow_rate_annual_pct: float,
    spot_yield_annual_pct: float,
    position_size_usd: float,
    margin_requirement_pct: float,
    liquidation_buffer_pct: float,
    gas_cost_usd: float,
    protocol_name: str,
) -> dict:
    """
    Analyze a funding rate arbitrage opportunity.

    Parameters
    ----------
    perp_funding_rate_8h_pct : float
        8-hour perpetual funding rate in percent (e.g. 0.01 means 0.01%).
        Positive = longs pay shorts (shorts earn). Negative = shorts pay longs.
    spot_borrow_rate_annual_pct : float
        Annual borrow rate (%) to finance the spot leg of the trade.
    spot_yield_annual_pct : float
        Annual yield (%) earned from holding the spot asset (e.g. stETH staking yield).
    position_size_usd : float
        Notional size of the full position in USD.
    margin_requirement_pct : float
        Initial margin requirement for the perpetual position (%).
    liquidation_buffer_pct : float
        Extra collateral buffer (%) added on top of margin to avoid liquidation.
    gas_cost_usd : float
        Estimated total gas cost in USD for setup and ongoing maintenance.
    protocol_name : str
        Identifier for the protocol pair (e.g. "dYdX+Aave").

    Returns
    -------
    dict with keys:
        protocol_name, perp_funding_rate_8h_pct, spot_borrow_rate_annual_pct,
        spot_yield_annual_pct, position_size_usd, margin_requirement_pct,
        liquidation_buffer_pct, gas_cost_usd,
        funding_rate_annual_pct, net_arb_spread_pct, capital_required_usd,
        annualized_return_on_capital_pct, gas_drag_pct,
        arb_quality_score, arb_label, timestamp
    """
    funding_rate_annual_pct = _annualize_funding_rate(perp_funding_rate_8h_pct)

    net_arb_spread_pct = _compute_net_arb_spread(
        funding_rate_annual_pct,
        spot_borrow_rate_annual_pct,
        spot_yield_annual_pct,
    )

    capital_required_usd = _compute_capital_required(
        position_size_usd,
        margin_requirement_pct,
        liquidation_buffer_pct,
    )

    gas_drag_pct = _compute_gas_drag(gas_cost_usd, capital_required_usd)

    annualized_return_on_capital_pct = _compute_annualized_return_on_capital(
        net_arb_spread_pct,
        position_size_usd,
        capital_required_usd,
        gas_drag_pct,
    )

    arb_quality_score = _compute_quality_score(annualized_return_on_capital_pct)
    arb_label = _classify_arb(annualized_return_on_capital_pct)

    return {
        "protocol_name": protocol_name,
        "perp_funding_rate_8h_pct": perp_funding_rate_8h_pct,
        "spot_borrow_rate_annual_pct": spot_borrow_rate_annual_pct,
        "spot_yield_annual_pct": spot_yield_annual_pct,
        "position_size_usd": position_size_usd,
        "margin_requirement_pct": margin_requirement_pct,
        "liquidation_buffer_pct": liquidation_buffer_pct,
        "gas_cost_usd": gas_cost_usd,
        "funding_rate_annual_pct": funding_rate_annual_pct,
        "net_arb_spread_pct": net_arb_spread_pct,
        "capital_required_usd": capital_required_usd,
        "annualized_return_on_capital_pct": annualized_return_on_capital_pct,
        "gas_drag_pct": gas_drag_pct,
        "arb_quality_score": arb_quality_score,
        "arb_label": arb_label,
        "timestamp": time.time(),
    }


def analyze_and_log(
    perp_funding_rate_8h_pct: float,
    spot_borrow_rate_annual_pct: float,
    spot_yield_annual_pct: float,
    position_size_usd: float,
    margin_requirement_pct: float,
    liquidation_buffer_pct: float,
    gas_cost_usd: float,
    protocol_name: str,
    data_dir: Optional[str] = None,
) -> dict:
    """Run analyze() and append result to the ring-buffer log."""
    result = analyze(
        perp_funding_rate_8h_pct=perp_funding_rate_8h_pct,
        spot_borrow_rate_annual_pct=spot_borrow_rate_annual_pct,
        spot_yield_annual_pct=spot_yield_annual_pct,
        position_size_usd=position_size_usd,
        margin_requirement_pct=margin_requirement_pct,
        liquidation_buffer_pct=liquidation_buffer_pct,
        gas_cost_usd=gas_cost_usd,
        protocol_name=protocol_name,
    )
    _append_log(result, data_dir or _DEFAULT_DATA_DIR)
    return result


def init_log(data_dir: Optional[str] = None) -> None:
    """Initialize log file as empty list if it does not exist."""
    d = data_dir or _DEFAULT_DATA_DIR
    os.makedirs(d, exist_ok=True)
    log_path = os.path.join(d, LOG_FILENAME)
    if not os.path.exists(log_path):
        _atomic_write_json([], log_path, d)


# ---------------------------------------------------------------------------
# Main class (wraps module-level functions)
# ---------------------------------------------------------------------------

class DeFiProtocolFundingRateArbitrageAnalyzer:
    """
    Analyzes funding rate arbitrage opportunities between perpetual DEX funding
    rates and spot yield protocols.

    Positive funding → shorts earn → long spot + short perp captures spread.
    Negative funding → longs earn → short spot + long perp (less common).
    Delta-neutral strategies isolate funding income from directional exposure.

    Usage
    -----
    >>> analyzer = DeFiProtocolFundingRateArbitrageAnalyzer()
    >>> result = analyzer.analyze(
    ...     perp_funding_rate_8h_pct=0.01,
    ...     spot_borrow_rate_annual_pct=3.0,
    ...     spot_yield_annual_pct=4.5,
    ...     position_size_usd=100_000,
    ...     margin_requirement_pct=10.0,
    ...     liquidation_buffer_pct=5.0,
    ...     gas_cost_usd=50.0,
    ...     protocol_name="dYdX+Aave",
    ... )
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or _DEFAULT_DATA_DIR

    def analyze(
        self,
        perp_funding_rate_8h_pct: float,
        spot_borrow_rate_annual_pct: float,
        spot_yield_annual_pct: float,
        position_size_usd: float,
        margin_requirement_pct: float,
        liquidation_buffer_pct: float,
        gas_cost_usd: float,
        protocol_name: str,
    ) -> dict:
        """Analyze funding rate arbitrage opportunity. Does not write to disk."""
        return analyze(
            perp_funding_rate_8h_pct=perp_funding_rate_8h_pct,
            spot_borrow_rate_annual_pct=spot_borrow_rate_annual_pct,
            spot_yield_annual_pct=spot_yield_annual_pct,
            position_size_usd=position_size_usd,
            margin_requirement_pct=margin_requirement_pct,
            liquidation_buffer_pct=liquidation_buffer_pct,
            gas_cost_usd=gas_cost_usd,
            protocol_name=protocol_name,
        )

    def analyze_and_log(
        self,
        perp_funding_rate_8h_pct: float,
        spot_borrow_rate_annual_pct: float,
        spot_yield_annual_pct: float,
        position_size_usd: float,
        margin_requirement_pct: float,
        liquidation_buffer_pct: float,
        gas_cost_usd: float,
        protocol_name: str,
    ) -> dict:
        """Analyze and append to ring-buffer log."""
        return analyze_and_log(
            perp_funding_rate_8h_pct=perp_funding_rate_8h_pct,
            spot_borrow_rate_annual_pct=spot_borrow_rate_annual_pct,
            spot_yield_annual_pct=spot_yield_annual_pct,
            position_size_usd=position_size_usd,
            margin_requirement_pct=margin_requirement_pct,
            liquidation_buffer_pct=liquidation_buffer_pct,
            gas_cost_usd=gas_cost_usd,
            protocol_name=protocol_name,
            data_dir=self._data_dir,
        )

    def init_log(self) -> None:
        """Initialize log file if it does not exist."""
        init_log(self._data_dir)

    @property
    def log_path(self) -> str:
        return os.path.join(self._data_dir, LOG_FILENAME)

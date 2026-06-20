"""
MP-853: DeFiPortfolioAttributionAnalyzer

Decomposes portfolio performance into return contributions from each source:
yield income, price appreciation/depreciation, impermanent loss, and
protocol-specific fees. Identifies top/bottom contributors.

Advisory / read-only. Pure stdlib. Atomic JSON writes (tmp + os.replace).
Ring-buffer log capped at 100 entries in data/portfolio_attribution_log.json.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RING_BUFFER_CAP = 100
LOG_FILE = "portfolio_attribution_log.json"
DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data"
)

# Return label thresholds (total_return_pct)
LABEL_STRONG = 10.0
LABEL_BREAKEVEN_EPS = 0.01


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _data_dir(data_dir: Optional[str]) -> str:
    return os.path.abspath(data_dir or DEFAULT_DATA_DIR)


def _log_path(data_dir: Optional[str]) -> str:
    return os.path.join(_data_dir(data_dir), LOG_FILE)


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    atomic_save(data, str(path))
def _load_log(data_dir: Optional[str]) -> List[dict]:
    path = _log_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError, TypeError):
        return []


def _save_log(entry: dict, data_dir: Optional[str]) -> None:
    """Append entry to ring-buffer log (cap at RING_BUFFER_CAP)."""
    history = _load_log(data_dir)
    history.append(entry)
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]
    _atomic_write(_log_path(data_dir), history)


def _return_label(total_return_pct: float) -> str:
    """Map return percentage to a human-readable label."""
    if total_return_pct >= LABEL_STRONG:
        return "STRONG"
    if total_return_pct <= -LABEL_STRONG:
        return "LOSS"
    if abs(total_return_pct) < LABEL_BREAKEVEN_EPS:
        return "BREAKEVEN"
    if total_return_pct > 0:
        return "POSITIVE"
    return "NEGATIVE"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze(
    positions: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    data_dir: Optional[str] = None,
    save: bool = False,
) -> Dict[str, Any]:
    """
    Decompose portfolio performance into per-source return contributions.

    Parameters
    ----------
    positions : list of dict
        Each dict must contain:
          - protocol (str)
          - allocation_usd (float)
          - yield_income_usd (float)   — interest/rewards earned
          - price_pnl_usd (float)      — unrealized gain/loss (pos or neg)
          - il_loss_usd (float)        — impermanent loss (positive = loss amt)
          - fees_paid_usd (float)      — gas + protocol fees (positive = cost)
          - holding_days (int)
    config : dict, optional
        - annualize (bool, default True) — annualize return metrics

    Returns
    -------
    dict with keys:
        positions, portfolio_summary, attribution_breakdown, timestamp
    """
    cfg = config or {}
    annualize: bool = bool(cfg.get("annualize", True))

    # -----------------------------------------------------------------------
    # Per-position analysis
    # -----------------------------------------------------------------------
    analyzed_positions: List[Dict[str, Any]] = []

    total_allocation: float = 0.0
    total_return: float = 0.0
    total_yield: float = 0.0
    total_price_pnl: float = 0.0
    total_il_loss: float = 0.0
    total_fees: float = 0.0

    for pos in positions:
        protocol: str = str(pos.get("protocol", ""))
        alloc: float = float(pos.get("allocation_usd", 0.0))
        yield_inc: float = float(pos.get("yield_income_usd", 0.0))
        price_pnl: float = float(pos.get("price_pnl_usd", 0.0))
        il_loss: float = float(pos.get("il_loss_usd", 0.0))
        fees_paid: float = float(pos.get("fees_paid_usd", 0.0))
        holding_days: int = int(pos.get("holding_days", 0))

        # Core formula
        total_ret_usd: float = yield_inc + price_pnl - il_loss - fees_paid

        # Percentage metrics
        if alloc > 0:
            total_ret_pct = total_ret_usd / alloc * 100.0
            yield_contrib_pct = yield_inc / alloc * 100.0
            price_contrib_pct = price_pnl / alloc * 100.0
            il_drag_pct = -il_loss / alloc * 100.0
            fee_drag_pct = -fees_paid / alloc * 100.0
        else:
            total_ret_pct = 0.0
            yield_contrib_pct = 0.0
            price_contrib_pct = 0.0
            il_drag_pct = 0.0
            fee_drag_pct = 0.0

        # Annualized
        if annualize and holding_days > 0 and alloc > 0:
            annualized_ret_pct: Optional[float] = total_ret_pct / holding_days * 365.0
        else:
            annualized_ret_pct = None

        label = _return_label(total_ret_pct)

        analyzed_positions.append(
            {
                "protocol": protocol,
                "allocation_usd": alloc,
                "total_return_usd": total_ret_usd,
                "total_return_pct": total_ret_pct,
                "annualized_return_pct": annualized_ret_pct,
                "yield_contribution_pct": yield_contrib_pct,
                "price_contribution_pct": price_contrib_pct,
                "il_drag_pct": il_drag_pct,
                "fee_drag_pct": fee_drag_pct,
                "return_label": label,
            }
        )

        # Accumulate portfolio totals
        total_allocation += alloc
        total_return += total_ret_usd
        total_yield += yield_inc
        total_price_pnl += price_pnl
        total_il_loss += il_loss
        total_fees += fees_paid

    # -----------------------------------------------------------------------
    # Portfolio summary
    # -----------------------------------------------------------------------
    if total_allocation > 0:
        total_ret_pct_port = total_return / total_allocation * 100.0
    else:
        total_ret_pct_port = 0.0

    # yield_share_pct: if total_return > 0 use ratio, else 0.0
    if total_return > 0:
        yield_share_pct = total_yield / total_return * 100.0
    else:
        yield_share_pct = 0.0

    # best / worst contributor by total_return_usd
    best_contributor: Optional[str] = None
    worst_contributor: Optional[str] = None
    if analyzed_positions:
        best_pos = max(analyzed_positions, key=lambda p: p["total_return_usd"])
        worst_pos = min(analyzed_positions, key=lambda p: p["total_return_usd"])
        best_contributor = best_pos["protocol"]
        worst_contributor = worst_pos["protocol"]

    portfolio_summary: Dict[str, Any] = {
        "total_allocation_usd": total_allocation,
        "total_return_usd": total_return,
        "total_return_pct": total_ret_pct_port,
        "total_yield_usd": total_yield,
        "total_price_pnl_usd": total_price_pnl,
        "total_il_loss_usd": total_il_loss,
        "total_fees_usd": total_fees,
        "yield_share_pct": yield_share_pct,
        "best_contributor": best_contributor,
        "worst_contributor": worst_contributor,
    }

    # -----------------------------------------------------------------------
    # Attribution breakdown (portfolio-level)
    # -----------------------------------------------------------------------
    if total_allocation > 0:
        ab_yield = total_yield / total_allocation * 100.0
        ab_price = total_price_pnl / total_allocation * 100.0
        ab_il = -total_il_loss / total_allocation * 100.0
        ab_fee = -total_fees / total_allocation * 100.0
        ab_net = total_return / total_allocation * 100.0
    else:
        ab_yield = ab_price = ab_il = ab_fee = ab_net = 0.0

    attribution_breakdown: Dict[str, float] = {
        "yield_contribution_pct": ab_yield,
        "price_contribution_pct": ab_price,
        "il_drag_pct": ab_il,
        "fee_drag_pct": ab_fee,
        "net_return_pct": ab_net,
    }

    # -----------------------------------------------------------------------
    # Assemble result
    # -----------------------------------------------------------------------
    ts = time.time()
    result: Dict[str, Any] = {
        "positions": analyzed_positions,
        "portfolio_summary": portfolio_summary,
        "attribution_breakdown": attribution_breakdown,
        "timestamp": ts,
    }

    if save:
        _save_log(result, data_dir)

    return result


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------


def load_history(data_dir: Optional[str] = None) -> List[dict]:
    """Load the portfolio attribution log. Returns [] if missing/corrupt."""
    return _load_log(data_dir)


def init_log(data_dir: Optional[str] = None) -> None:
    """Initialise an empty log file if it doesn't exist yet."""
    path = _log_path(data_dir)
    if not os.path.exists(path):
        _atomic_write(path, [])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _demo_run() -> None:
    positions = [
        {
            "protocol": "Aave V3",
            "allocation_usd": 40_000.0,
            "yield_income_usd": 1_400.0,
            "price_pnl_usd": 0.0,
            "il_loss_usd": 0.0,
            "fees_paid_usd": 20.0,
            "holding_days": 365,
        },
        {
            "protocol": "Morpho Steakhouse",
            "allocation_usd": 35_000.0,
            "yield_income_usd": 2_275.0,
            "price_pnl_usd": 0.0,
            "il_loss_usd": 0.0,
            "fees_paid_usd": 15.0,
            "holding_days": 365,
        },
        {
            "protocol": "Curve 3Pool",
            "allocation_usd": 25_000.0,
            "yield_income_usd": 500.0,
            "price_pnl_usd": 0.0,
            "il_loss_usd": 250.0,
            "fees_paid_usd": 30.0,
            "holding_days": 180,
        },
    ]
    result = analyze(positions, config={"annualize": True})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import sys

    if "--run" in sys.argv:
        data_dir_arg = None
        if "--data-dir" in sys.argv:
            idx = sys.argv.index("--data-dir")
            data_dir_arg = sys.argv[idx + 1]
        result = analyze([], data_dir=data_dir_arg, save=True)
        print("Saved attribution log.")
    else:
        _demo_run()

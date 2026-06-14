"""
MP-1047 ProtocolDeFiYieldFarmingROICalculator
---------------------------------------------
Calculates the true ROI of yield farming including all material costs:
  - Base protocol yield
  - Reward token APY (adjusted for token price change)
  - Gas / transaction costs
  - Impermanent loss estimate
  - Opportunity cost of capital

Produces gross/net/token-adjusted APY percentages, ROI vs hodl, and an
advisory label.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_farming_roi_log.json"
)
_LOG_CAP = 100

_WEEKS_PER_YEAR: float = 52.0

# Default reference position used for converting absolute gas costs to a %
# when no position_usd is supplied.
_DEFAULT_POSITION_USD: float = 10_000.0

# Label thresholds on roi_vs_hodl_pct (annualized)
_LABEL_THRESHOLDS = [
    (15.0, "EXCEPTIONAL_ROI"),
    (5.0, "GOOD_ROI"),
    (0.0, "MARGINAL"),
    (-10.0, "UNDERPERFORMING"),
]
_LABEL_BOTTOM = "YIELD_FARMING_TRAP"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _gross_apy_pct(base_yield_apy_pct: float, reward_token_apy_pct: float) -> float:
    """
    Gross APY before any price adjustment, IL, or cost deductions.
    Simply the sum of base yield and nominal reward token APY.
    """
    return max(0.0, base_yield_apy_pct) + max(0.0, reward_token_apy_pct)


def _token_price_ratio(
    reward_token_price_usd: float,
    reward_token_entry_price_usd: float,
) -> float:
    """
    Ratio of current reward token price to entry price.
    Returns 1.0 (no change) when entry price is zero or negative.
    """
    if reward_token_entry_price_usd <= 0:
        return 1.0
    return max(0.0, reward_token_price_usd) / reward_token_entry_price_usd


def _token_adjusted_apy_pct(
    base_yield_apy_pct: float,
    reward_token_apy_pct: float,
    reward_token_price_usd: float,
    reward_token_entry_price_usd: float,
) -> float:
    """
    APY after adjusting the reward token component for price movement.

    Only the reward token component is affected by price change;
    the base yield (denominated in stablecoin/principal) is unaffected.
    """
    ratio = _token_price_ratio(reward_token_price_usd, reward_token_entry_price_usd)
    adjusted_reward_apy = max(0.0, reward_token_apy_pct) * ratio
    return max(0.0, base_yield_apy_pct) + adjusted_reward_apy


def _gas_cost_annual_pct(
    gas_cost_usd_per_week: float,
    position_usd: float,
) -> float:
    """
    Annualised gas cost as a percentage of position size.
    Returns 0 when position_usd <= 0.
    """
    if position_usd <= 0:
        return 0.0
    annual_gas_usd = max(0.0, gas_cost_usd_per_week) * _WEEKS_PER_YEAR
    return annual_gas_usd / position_usd * 100.0


def _net_apy_pct(
    token_adjusted_apy: float,
    il_estimate_pct: float,
    gas_cost_pct: float,
) -> float:
    """
    Net APY after subtracting impermanent loss and gas costs.
    """
    return token_adjusted_apy - max(0.0, il_estimate_pct) - max(0.0, gas_cost_pct)


def _roi_vs_hodl_pct(net_apy: float, opportunity_cost_apy_pct: float) -> float:
    """
    Annualised return advantage of farming vs. the opportunity-cost alternative.
    Positive means farming outperforms; negative means it underperforms.
    """
    return net_apy - max(0.0, opportunity_cost_apy_pct)


def _label(roi_vs_hodl: float) -> str:
    """Map roi_vs_hodl_pct → advisory label."""
    if roi_vs_hodl >= 15.0:
        return "EXCEPTIONAL_ROI"
    if roi_vs_hodl >= 5.0:
        return "GOOD_ROI"
    if roi_vs_hodl >= 0.0:
        return "MARGINAL"
    if roi_vs_hodl >= -10.0:
        return "UNDERPERFORMING"
    return "YIELD_FARMING_TRAP"


def _effective_weeks_farmed(weeks_farmed: float) -> float:
    """Clamp weeks_farmed to a positive value."""
    return max(0.0, weeks_farmed)


def _period_return_pct(apy_pct: float, weeks: float) -> float:
    """Convert APY % to actual return % over the given number of weeks."""
    if weeks <= 0:
        return 0.0
    return apy_pct * weeks / _WEEKS_PER_YEAR


def _build_recommendations(
    label: str,
    net_apy: float,
    opportunity_cost_apy_pct: float,
    gas_cost_pct: float,
    il_estimate_pct: float,
    token_price_ratio: float,
    management_overhead_hrs_per_week: float,
) -> list[str]:
    """Return advisory recommendations based on the farming result."""
    recs: list[str] = []

    if label == "EXCEPTIONAL_ROI":
        recs.append(
            f"Exceptional farming ROI: net APY {net_apy:.1f}% vs "
            f"opportunity cost {opportunity_cost_apy_pct:.1f}%. "
            f"Continue and consider scaling within risk limits."
        )
    elif label == "GOOD_ROI":
        recs.append(
            f"Good ROI: net APY {net_apy:.1f}% clears opportunity cost "
            f"({opportunity_cost_apy_pct:.1f}%). Strategy is working."
        )
    elif label == "MARGINAL":
        recs.append(
            f"Marginal advantage over opportunity cost "
            f"({opportunity_cost_apy_pct:.1f}%). "
            f"Evaluate whether gas/IL drag can be reduced."
        )
    elif label == "UNDERPERFORMING":
        recs.append(
            f"Farming underperforms the alternative yield "
            f"({opportunity_cost_apy_pct:.1f}%). "
            f"Consider reallocating to the opportunity-cost strategy."
        )
    else:  # YIELD_FARMING_TRAP
        recs.append(
            f"Yield farming trap: net APY {net_apy:.1f}% severely lags "
            f"the opportunity cost ({opportunity_cost_apy_pct:.1f}%). "
            f"Exit and redeploy to safer yield."
        )

    if token_price_ratio < 0.7:
        recs.append(
            f"Reward token has lost {(1 - token_price_ratio) * 100:.0f}% "
            f"of its entry value — heavily eroding farming returns."
        )
    elif token_price_ratio > 1.5:
        recs.append(
            f"Reward token is up {(token_price_ratio - 1) * 100:.0f}% "
            f"vs entry — significant boost to actual returns."
        )

    if gas_cost_pct > 5.0:
        recs.append(
            f"Gas costs annualise to {gas_cost_pct:.1f}% of position — "
            f"consider batching claims or moving to a lower-fee chain."
        )

    if il_estimate_pct > 10.0:
        recs.append(
            f"High IL estimate ({il_estimate_pct:.1f}% p.a.) is a major "
            f"drag; favour single-sided or stable-pair pools."
        )

    if management_overhead_hrs_per_week > 5.0:
        recs.append(
            f"Management overhead {management_overhead_hrs_per_week:.1f} hrs/week "
            f"is significant; factor in your own time cost."
        )

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldFarmingROICalculator:
    """
    Calculates true ROI of yield farming including all material costs and
    token price risk.

    Usage
    -----
    calc = ProtocolDeFiYieldFarmingROICalculator()
    result = calc.calculate(farming_params)
    """

    def __init__(self, log_path: str = _LOG_PATH, log_cap: int = _LOG_CAP) -> None:
        self._log_path = log_path
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def calculate(self, params: dict, config: dict | None = None) -> dict[str, Any]:
        """
        Calculate yield farming ROI.

        Parameters
        ----------
        params : dict
            - protocol: str                         (informational, optional)
            - base_yield_apy_pct: float             (stable base yield, e.g. lending)
            - reward_token_apy_pct: float           (reward APY at entry token price)
            - reward_token_price_usd: float         (current reward token price)
            - reward_token_entry_price_usd: float   (token price when you entered)
            - gas_cost_usd_per_week: float          ($ cost of claiming/compounding)
            - il_estimate_pct: float                (annualised IL estimate %)
            - management_overhead_hrs_per_week: float
            - opportunity_cost_apy_pct: float       (safe alternative APY %)
            - weeks_farmed: float                   (farming duration)
            - position_usd: float                   (optional; default 10 000)
        config : dict, optional
            - log_path: str  (override default log path)
            - skip_log: bool (default False)

        Returns
        -------
        dict
            Full ROI analysis with all intermediate metrics and advisory label.
        """
        cfg = config or {}
        log_path = cfg.get("log_path", self._log_path)
        skip_log = bool(cfg.get("skip_log", False))

        protocol = str(params.get("protocol", "UNKNOWN"))
        base_yield_apy = max(0.0, float(params.get("base_yield_apy_pct", 0.0)))
        reward_token_apy = max(0.0, float(params.get("reward_token_apy_pct", 0.0)))
        reward_price = max(0.0, float(params.get("reward_token_price_usd", 0.0)))
        reward_entry_price = max(0.0, float(params.get("reward_token_entry_price_usd", 0.0)))
        gas_per_week = max(0.0, float(params.get("gas_cost_usd_per_week", 0.0)))
        il_pct = max(0.0, float(params.get("il_estimate_pct", 0.0)))
        overhead_hrs = max(0.0, float(params.get("management_overhead_hrs_per_week", 0.0)))
        opp_cost_apy = max(0.0, float(params.get("opportunity_cost_apy_pct", 0.0)))
        weeks = max(0.0, float(params.get("weeks_farmed", 0.0)))
        position_usd = max(0.0, float(params.get("position_usd", _DEFAULT_POSITION_USD)))
        if position_usd <= 0:
            position_usd = _DEFAULT_POSITION_USD

        # Core calculations
        gross_apy = _gross_apy_pct(base_yield_apy, reward_token_apy)
        tok_ratio = _token_price_ratio(reward_price, reward_entry_price)
        tok_adj_apy = _token_adjusted_apy_pct(
            base_yield_apy, reward_token_apy, reward_price, reward_entry_price
        )
        gas_pct = _gas_cost_annual_pct(gas_per_week, position_usd)
        net_apy = _net_apy_pct(tok_adj_apy, il_pct, gas_pct)
        roi_vs_hodl = _roi_vs_hodl_pct(net_apy, opp_cost_apy)
        lbl = _label(roi_vs_hodl)

        # Period (realised) returns over weeks_farmed
        period_net_return_pct = _period_return_pct(net_apy, weeks)
        period_opp_return_pct = _period_return_pct(opp_cost_apy, weeks)
        period_advantage_pct = period_net_return_pct - period_opp_return_pct

        recommendations = _build_recommendations(
            lbl,
            net_apy,
            opp_cost_apy,
            gas_pct,
            il_pct,
            tok_ratio,
            overhead_hrs,
        )

        result: dict[str, Any] = {
            "protocol": protocol,
            "position_usd": position_usd,
            "weeks_farmed": weeks,
            # APY metrics
            "gross_apy_pct": gross_apy,
            "token_adjusted_apy_pct": tok_adj_apy,
            "gas_cost_annual_pct": gas_pct,
            "net_apy_pct": net_apy,
            "opportunity_cost_apy_pct": opp_cost_apy,
            "roi_vs_hodl_pct": roi_vs_hodl,
            # Breakdown factors
            "reward_token_price_ratio": tok_ratio,
            "il_estimate_pct": il_pct,
            "management_overhead_hrs_per_week": overhead_hrs,
            # Period returns
            "period_net_return_pct": period_net_return_pct,
            "period_opp_return_pct": period_opp_return_pct,
            "period_advantage_pct": period_advantage_pct,
            # Advisory
            "label": lbl,
            "recommendations": recommendations,
            "timestamp": time.time(),
        }

        if not skip_log:
            try:
                _atomic_log(log_path, result)
            except Exception:
                pass  # advisory: never crash caller

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def calculate(params: dict, config: dict | None = None) -> dict[str, Any]:
    """Module-level shortcut — delegates to ProtocolDeFiYieldFarmingROICalculator."""
    return ProtocolDeFiYieldFarmingROICalculator().calculate(params, config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "protocol": "Uniswap V3 USDC/ETH",
        "base_yield_apy_pct": 8.0,
        "reward_token_apy_pct": 12.0,
        "reward_token_price_usd": 1.50,
        "reward_token_entry_price_usd": 2.00,
        "gas_cost_usd_per_week": 25.0,
        "il_estimate_pct": 5.0,
        "management_overhead_hrs_per_week": 2.0,
        "opportunity_cost_apy_pct": 5.0,
        "weeks_farmed": 12.0,
        "position_usd": 10_000.0,
    }

    r = calculate(_demo, config={"skip_log": True})
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)

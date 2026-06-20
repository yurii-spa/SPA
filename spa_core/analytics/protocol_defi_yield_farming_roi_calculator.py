"""
MP-1097 ProtocolDeFiYieldFarmingROICalculator
----------------------------------------------
Full ROI calculator for yield farming positions accounting for:
  - Gross yield from stated APY over holding period
  - Impermanent loss risk (applied to principal)
  - Reward token price decay (applied to gross yield)
  - Protocol fee drag (applied to gross yield)
  - Gas / transaction entry and exit costs

Produces gross_yield_usd, il_loss_usd, reward_decay_loss_usd, net_yield_usd,
net_roi_pct, annualized_net_roi_pct, and an advisory roi_label.

Inputs (via calculate(params)):
    initial_investment_usd  float  principal deployed
    gross_apy_pct           float  advertised gross APY %
    il_risk_pct             float  estimated impermanent loss % of principal
    reward_token_decay_pct  float  expected reward token price drop % (decay)
    entry_cost_usd          float  gas + swap fees to enter position
    exit_cost_usd           float  gas + swap fees to exit position
    holding_days            int    number of days holding the position
    protocol_fee_pct        float  ongoing protocol fee % (annualized, on gross yield)
    protocol_name           str    human-readable label

Outputs (returned dict):
    gross_yield_usd         float  initial_investment * gross_apy * holding_days/365
    il_loss_usd             float  initial_investment * il_risk_pct/100
    reward_decay_loss_usd   float  gross_yield * reward_token_decay_pct/100
    net_yield_usd           float  gross - il - decay - fees - entry - exit
    net_roi_pct             float  net_yield / initial_investment * 100
    annualized_net_roi_pct  float  net_roi * 365 / holding_days  (0 if holding_days<=0)
    roi_label               str    EXCELLENT_ROI / GOOD_ROI / BREAKEVEN /
                                   MARGINAL_LOSS / SIGNIFICANT_LOSS

Label logic (by net_roi_pct for holding period):
    > 5%          => EXCELLENT_ROI
    1% to 5%      => GOOD_ROI
    -1% to 1%     => BREAKEVEN
    -5% to -1%    => MARGINAL_LOSS
    < -5%         => SIGNIFICANT_LOSS

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap=100).
Log file: data/yield_farming_roi_log.json
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

_LOG_FILENAME = "yield_farming_roi_log.json"
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", _LOG_FILENAME
)
_LOG_CAP = 100

_DAYS_PER_YEAR: float = 365.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gross_yield_usd(
    initial_investment_usd: float,
    gross_apy_pct: float,
    holding_days: int,
) -> float:
    """
    Gross yield = principal × (gross_apy / 100) × (holding_days / 365).
    Negative APY or negative principal → 0.
    """
    if holding_days <= 0 or initial_investment_usd <= 0 or gross_apy_pct <= 0:
        return 0.0
    return initial_investment_usd * (gross_apy_pct / 100.0) * (holding_days / _DAYS_PER_YEAR)


def _il_loss_usd(
    initial_investment_usd: float,
    il_risk_pct: float,
) -> float:
    """
    Impermanent-loss dollar amount = principal × (il_risk_pct / 100).
    Negative risk → 0.
    """
    if initial_investment_usd <= 0 or il_risk_pct <= 0:
        return 0.0
    return initial_investment_usd * (il_risk_pct / 100.0)


def _reward_decay_loss_usd(
    gross_yield: float,
    reward_token_decay_pct: float,
) -> float:
    """
    Reward token decay erodes the gross yield:
    decay_loss = gross_yield × (reward_token_decay_pct / 100).
    Capped at gross_yield (can't lose more than gross yield through token decay).
    Negative decay → 0 (price appreciation is not counted here).
    """
    if gross_yield <= 0 or reward_token_decay_pct <= 0:
        return 0.0
    return gross_yield * min(1.0, reward_token_decay_pct / 100.0)


def _protocol_fee_usd(
    gross_yield: float,
    protocol_fee_pct: float,
) -> float:
    """
    Protocol fee drag on the yield = gross_yield × (protocol_fee_pct / 100).
    Negative fee → 0.
    """
    if gross_yield <= 0 or protocol_fee_pct <= 0:
        return 0.0
    return gross_yield * (protocol_fee_pct / 100.0)


def _net_yield_usd(
    gross_yield: float,
    il_loss: float,
    reward_decay_loss: float,
    protocol_fee: float,
    entry_cost_usd: float,
    exit_cost_usd: float,
) -> float:
    """
    Net yield = gross − IL − decay − protocol_fee − entry_cost − exit_cost.
    Can be negative (loss scenario).
    """
    entry = max(0.0, entry_cost_usd)
    exit_ = max(0.0, exit_cost_usd)
    return gross_yield - il_loss - reward_decay_loss - protocol_fee - entry - exit_


def _net_roi_pct(net_yield: float, initial_investment_usd: float) -> float:
    """
    Net ROI % = (net_yield / initial_investment) × 100.
    Returns 0 when investment is 0 or negative.
    """
    if initial_investment_usd <= 0:
        return 0.0
    return (net_yield / initial_investment_usd) * 100.0


def _annualized_net_roi_pct(net_roi: float, holding_days: int) -> float:
    """
    Annualise the holding-period ROI: net_roi × 365 / holding_days.
    Returns 0 when holding_days <= 0.
    """
    if holding_days <= 0:
        return 0.0
    return net_roi * (_DAYS_PER_YEAR / holding_days)


def _roi_label(net_roi: float) -> str:
    """Map net_roi_pct to an advisory label.

    Thresholds (inclusive lower bound of each range):
        > 5%       -> EXCELLENT_ROI
        1% to 5%   -> GOOD_ROI   (includes exactly 1%)
        -1% to 1%  -> BREAKEVEN  (includes exactly -1%, excludes 1%)
        -5% to -1% -> MARGINAL_LOSS (includes -5%, excludes -1%)
        < -5%      -> SIGNIFICANT_LOSS
    """
    if net_roi > 5.0:
        return "EXCELLENT_ROI"
    if net_roi >= 1.0:
        return "GOOD_ROI"
    if net_roi >= -1.0:
        return "BREAKEVEN"
    if net_roi >= -5.0:
        return "MARGINAL_LOSS"
    return "SIGNIFICANT_LOSS"


def _atomic_log(log_path: str, entry: dict, log_cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array (capped at log_cap), atomic write."""
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
    if len(data) > log_cap:
        data = data[-log_cap:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldFarmingROICalculator:
    """
    Full ROI calculator for DeFi yield farming positions, accounting for
    entry/exit costs, IL risk, reward token price decay, and protocol fees.

    Usage
    -----
    calc = ProtocolDeFiYieldFarmingROICalculator()
    result = calc.calculate(params)
    """

    def __init__(
        self,
        log_path: str = _LOG_PATH,
        log_cap: int = _LOG_CAP,
    ) -> None:
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
            initial_investment_usd  : float  (principal, USD)
            gross_apy_pct           : float  (gross APY %)
            il_risk_pct             : float  (estimated IL % of principal)
            reward_token_decay_pct  : float  (expected reward token drop %)
            entry_cost_usd          : float  (gas + swap fees on entry)
            exit_cost_usd           : float  (gas + swap fees on exit)
            holding_days            : int    (days in position)
            protocol_fee_pct        : float  (protocol fee on gross yield %)
            protocol_name           : str

        config : dict, optional
            log_path : str   override log path
            skip_log : bool  skip writing to log (default False)

        Returns
        -------
        dict with keys:
            protocol_name, initial_investment_usd, gross_apy_pct,
            il_risk_pct, reward_token_decay_pct, entry_cost_usd,
            exit_cost_usd, holding_days, protocol_fee_pct,
            gross_yield_usd, il_loss_usd, reward_decay_loss_usd,
            protocol_fee_usd, net_yield_usd, net_roi_pct,
            annualized_net_roi_pct, roi_label, timestamp
        """
        cfg = config or {}
        log_path = cfg.get("log_path", self._log_path)
        skip_log = bool(cfg.get("skip_log", False))

        # -- Parse inputs -----------------------------------------------
        protocol_name = str(params.get("protocol_name", "UNKNOWN"))
        initial_investment = max(0.0, float(params.get("initial_investment_usd", 0.0)))
        gross_apy = max(0.0, float(params.get("gross_apy_pct", 0.0)))
        il_risk = max(0.0, float(params.get("il_risk_pct", 0.0)))
        reward_decay = max(0.0, float(params.get("reward_token_decay_pct", 0.0)))
        entry_cost = max(0.0, float(params.get("entry_cost_usd", 0.0)))
        exit_cost = max(0.0, float(params.get("exit_cost_usd", 0.0)))
        holding_days = max(0, int(float(params.get("holding_days", 0))))
        protocol_fee = max(0.0, float(params.get("protocol_fee_pct", 0.0)))

        # -- Core calculations ------------------------------------------
        gross = _gross_yield_usd(initial_investment, gross_apy, holding_days)
        il_loss = _il_loss_usd(initial_investment, il_risk)
        decay_loss = _reward_decay_loss_usd(gross, reward_decay)
        fee = _protocol_fee_usd(gross, protocol_fee)
        net_yield = _net_yield_usd(gross, il_loss, decay_loss, fee, entry_cost, exit_cost)
        roi_pct = _net_roi_pct(net_yield, initial_investment)
        ann_roi_pct = _annualized_net_roi_pct(roi_pct, holding_days)
        label = _roi_label(roi_pct)

        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            # echoed inputs
            "initial_investment_usd": initial_investment,
            "gross_apy_pct": gross_apy,
            "il_risk_pct": il_risk,
            "reward_token_decay_pct": reward_decay,
            "entry_cost_usd": entry_cost,
            "exit_cost_usd": exit_cost,
            "holding_days": holding_days,
            "protocol_fee_pct": protocol_fee,
            # computed outputs
            "gross_yield_usd": round(gross, 6),
            "il_loss_usd": round(il_loss, 6),
            "reward_decay_loss_usd": round(decay_loss, 6),
            "protocol_fee_usd": round(fee, 6),
            "net_yield_usd": round(net_yield, 6),
            "net_roi_pct": round(roi_pct, 6),
            "annualized_net_roi_pct": round(ann_roi_pct, 6),
            "roi_label": label,
            "timestamp": time.time(),
        }

        if not skip_log:
            try:
                _atomic_log(log_path, result, self._log_cap)
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
        "protocol_name": "Uniswap V3 USDC/ETH",
        "initial_investment_usd": 50_000.0,
        "gross_apy_pct": 18.0,
        "il_risk_pct": 8.0,
        "reward_token_decay_pct": 30.0,
        "entry_cost_usd": 40.0,
        "exit_cost_usd": 35.0,
        "holding_days": 90,
        "protocol_fee_pct": 0.3,
    }

    r = calculate(_demo, config={"skip_log": True})
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)

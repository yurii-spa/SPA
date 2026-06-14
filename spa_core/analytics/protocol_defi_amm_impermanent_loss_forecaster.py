"""
MP-1071: ProtocolDeFiAmmImpermanentLossForecaster
Forecasts impermanent loss (IL) and net PnL for AMM positions across multiple
price scenarios.  Supports constant-product (Uniswap V2/V3) and stable-swap
pool types.

Constant-product IL formula:
    IL = 2 * sqrt(k) / (1 + k) - 1
    where k = price_ratio_multiplier (final price / initial price)
    IL is always ≤ 0 (a loss vs. just holding).

Stable-swap pools experience much lower IL; this module approximates it as
STABLE_SWAP_REDUCTION_FACTOR × constant-product IL.

Pure stdlib, read-only analytics, atomic ring-buffer log (cap 100).
"""

import json
import math
import os
import datetime

# --------------------------------------------------------------------------- #
# Log config
# --------------------------------------------------------------------------- #
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "amm_impermanent_loss_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Pool-type constants
# --------------------------------------------------------------------------- #
POOL_TYPE_CONSTANT_PRODUCT = "constant_product"
POOL_TYPE_STABLE_SWAP = "stable_swap"

# Stable-swap pools have substantially less IL than constant-product
STABLE_SWAP_REDUCTION_FACTOR = 0.1

# --------------------------------------------------------------------------- #
# IL risk labels
# --------------------------------------------------------------------------- #
LABEL_IL_NEGLIGIBLE = "IL_NEGLIGIBLE"
LABEL_LOW_IL_RISK = "LOW_IL_RISK"
LABEL_MODERATE_IL = "MODERATE_IL"
LABEL_HIGH_IL = "HIGH_IL"
LABEL_SEVERE_IL = "SEVERE_IL"


# --------------------------------------------------------------------------- #
# Pure helpers (importable for testing)
# --------------------------------------------------------------------------- #

def constant_product_il(price_multiplier: float) -> float:
    """
    Impermanent loss for a constant-product AMM (e.g. Uniswap V2).

    Parameters
    ----------
    price_multiplier : float
        Ratio of final price to initial price (e.g. 2.0 = price doubled).
        Must be > 0; values ≤ 0 are treated as total loss (-1.0).

    Returns
    -------
    float
        IL as a fraction (≤ 0).  Multiply by 100 to get percent.
    """
    if price_multiplier <= 0:
        return -1.0
    k = price_multiplier
    return 2.0 * math.sqrt(k) / (1.0 + k) - 1.0


def stable_swap_il(price_multiplier: float) -> float:
    """
    Approximate IL for a stable-swap AMM pool.
    Uses STABLE_SWAP_REDUCTION_FACTOR × constant-product IL.
    """
    if price_multiplier <= 0:
        return -STABLE_SWAP_REDUCTION_FACTOR
    cp = constant_product_il(price_multiplier)
    return round(cp * STABLE_SWAP_REDUCTION_FACTOR, 8)


def compute_il(price_multiplier: float, pool_type: str) -> float:
    """
    Dispatch IL computation by pool type.
    Any pool_type containing 'stable' (case-insensitive) uses stable_swap_il;
    everything else uses constant_product_il.
    """
    if isinstance(pool_type, str) and "stable" in pool_type.lower():
        return stable_swap_il(price_multiplier)
    return constant_product_il(price_multiplier)


def compute_fee_income(
    fee_tier_bps: float,
    expected_volume_usd_per_day: float,
    position_usd: float,
    holding_period_days: int,
) -> float:
    """
    Estimate fee income as a fraction of position USD over the holding period.

    fee_income_fraction = (fee_tier_bps / 10_000) × volume_per_day × days / position_usd

    Returns 0.0 if position_usd ≤ 0.
    """
    if position_usd <= 0:
        return 0.0
    fee_rate = fee_tier_bps / 10_000.0
    total_fees = fee_rate * expected_volume_usd_per_day * holding_period_days
    return total_fees / position_usd


def price_ratio_change_pct(price_multiplier: float) -> float:
    """Convert a price multiplier to a percentage change (e.g. 1.5 → 50.0)."""
    return round((price_multiplier - 1.0) * 100.0, 4)


def compute_scenario(
    price_multiplier: float,
    fee_income_fraction: float,
    pool_type: str,
) -> dict:
    """
    Compute a single price scenario dict.

    Returns
    -------
    dict with keys:
        price_ratio_change_pct  (float)
        il_pct                  (float, ≤ 0)
        fee_income_pct          (float, ≥ 0)
        net_pnl_pct             (float)
        break_even              (bool)
    """
    il_ratio = compute_il(price_multiplier, pool_type)
    il_pct = round(il_ratio * 100.0, 6)
    fee_pct = round(fee_income_fraction * 100.0, 6)
    net_pnl = round(il_pct + fee_pct, 6)
    return {
        "price_ratio_change_pct": price_ratio_change_pct(price_multiplier),
        "il_pct": il_pct,
        "fee_income_pct": fee_pct,
        "net_pnl_pct": net_pnl,
        "break_even": net_pnl >= 0.0,
    }


def il_risk_label(worst_case_il_pct: float) -> str:
    """
    Classify IL risk from worst-case IL percentage.

    Thresholds (absolute value of IL):
        < 0.5%  → IL_NEGLIGIBLE
        < 2.0%  → LOW_IL_RISK
        < 5.0%  → MODERATE_IL
        < 15.0% → HIGH_IL
        ≥ 15.0% → SEVERE_IL
    """
    abs_il = abs(worst_case_il_pct)
    if abs_il < 0.5:
        return LABEL_IL_NEGLIGIBLE
    if abs_il < 2.0:
        return LABEL_LOW_IL_RISK
    if abs_il < 5.0:
        return LABEL_MODERATE_IL
    if abs_il < 15.0:
        return LABEL_HIGH_IL
    return LABEL_SEVERE_IL


def _atomic_log_append(entry: dict, log_path: str, cap: int) -> None:
    """Append one entry to ring-buffer JSON log atomically (tmp + os.replace)."""
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    records.append(entry)
    if len(records) > cap:
        records = records[-cap:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(records, fh, indent=2)
    os.replace(tmp, log_path)


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class ProtocolDeFiAmmImpermanentLossForecaster:
    """
    Forecasts impermanent loss and net PnL for an AMM liquidity position
    across a configurable set of price scenarios.

    Input dict keys (``pool``):
        pool_name                  (str)
        token_a_symbol             (str)
        token_b_symbol             (str)
        initial_price_ratio        (float)  — price of token_a in token_b at entry
        price_scenarios            (list[float]) — price_ratio multipliers to model
                                                   (e.g. [0.5, 1.0, 2.0])
        fee_tier_bps               (float)  — pool fee in basis points (e.g. 30 = 0.3%)
        expected_volume_usd_per_day (float) — average daily trading volume in USD
        position_usd               (float)  — initial position size in USD
        holding_period_days        (int)    — number of days the position is held
        pool_type                  (str)    — "constant_product" or "stable_swap"

    Output keys:
        pool_name                  (str)
        token_a_symbol             (str)
        token_b_symbol             (str)
        initial_price_ratio        (float)
        pool_type                  (str)
        fee_tier_bps               (float)
        holding_period_days        (int)
        position_usd               (float)
        scenarios                  (list[dict]) — one per price scenario
            price_ratio_change_pct (float)
            il_pct                 (float, ≤ 0)
            fee_income_pct         (float)
            net_pnl_pct            (float)
            break_even             (bool)
        worst_case_il_pct          (float)
        best_case_net_pnl_pct      (float)
        il_risk_label              (str) — IL_NEGLIGIBLE / LOW_IL_RISK / MODERATE_IL /
                                          HIGH_IL / SEVERE_IL
        timestamp                  (str, ISO-8601 UTC)

    Usage::

        forecaster = ProtocolDeFiAmmImpermanentLossForecaster()
        result = forecaster.forecast({
            "pool_name": "ETH/USDC 0.3%",
            "token_a_symbol": "ETH",
            "token_b_symbol": "USDC",
            "initial_price_ratio": 3000.0,
            "price_scenarios": [0.5, 0.75, 1.0, 1.5, 2.0],
            "fee_tier_bps": 30,
            "expected_volume_usd_per_day": 10_000_000,
            "position_usd": 100_000,
            "holding_period_days": 30,
            "pool_type": "constant_product",
        })
    """

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    def forecast(self, pool: dict) -> dict:
        """
        Forecast IL and net PnL for a pool across multiple price scenarios.

        Parameters
        ----------
        pool : dict
            See class docstring for required keys.

        Returns
        -------
        dict
            See class docstring for output keys.
        """
        pool_name = str(pool.get("pool_name", "unknown"))
        token_a = str(pool.get("token_a_symbol", "TOKEN_A"))
        token_b = str(pool.get("token_b_symbol", "TOKEN_B"))
        initial_price_ratio = float(pool.get("initial_price_ratio", 1.0))
        price_scenarios_raw = pool.get("price_scenarios", [1.0])
        fee_tier_bps = float(pool.get("fee_tier_bps", 30))
        expected_volume_usd_per_day = float(pool.get("expected_volume_usd_per_day", 0.0))
        position_usd = float(pool.get("position_usd", 10_000.0))
        holding_period_days = int(pool.get("holding_period_days", 30))
        pool_type = str(pool.get("pool_type", POOL_TYPE_CONSTANT_PRODUCT))

        price_scenarios = [float(p) for p in price_scenarios_raw]

        fee_income_fraction = compute_fee_income(
            fee_tier_bps, expected_volume_usd_per_day, position_usd, holding_period_days
        )

        scenarios = [
            compute_scenario(pm, fee_income_fraction, pool_type)
            for pm in price_scenarios
        ]

        if scenarios:
            worst_case_il_pct = min(s["il_pct"] for s in scenarios)
            best_case_net_pnl_pct = max(s["net_pnl_pct"] for s in scenarios)
        else:
            worst_case_il_pct = 0.0
            best_case_net_pnl_pct = 0.0

        label = il_risk_label(worst_case_il_pct)
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"

        result = {
            "pool_name": pool_name,
            "token_a_symbol": token_a,
            "token_b_symbol": token_b,
            "initial_price_ratio": initial_price_ratio,
            "pool_type": pool_type,
            "fee_tier_bps": fee_tier_bps,
            "holding_period_days": holding_period_days,
            "position_usd": position_usd,
            "scenarios": scenarios,
            "worst_case_il_pct": round(worst_case_il_pct, 4),
            "best_case_net_pnl_pct": round(best_case_net_pnl_pct, 4),
            "il_risk_label": label,
            "timestamp": timestamp,
        }

        log_entry = {
            "timestamp": timestamp,
            "pool_name": pool_name,
            "worst_case_il_pct": round(worst_case_il_pct, 4),
            "il_risk_label": label,
            "scenario_count": len(scenarios),
            "pool_type": pool_type,
        }
        _atomic_log_append(log_entry, self._log_path, self._log_cap)

        return result

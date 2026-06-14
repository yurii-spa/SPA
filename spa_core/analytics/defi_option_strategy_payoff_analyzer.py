"""
MP-936: DeFiOptionStrategyPayoffAnalyzer
==========================================
Advisory-only analytics module.
Analyzes payoff profiles of DeFi option strategies including covered calls,
protective puts, straddles, strangles, bull/bear spreads, and iron condors.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/option_strategy_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
import tempfile
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "option_strategy_log.json",
)
LOG_MAX_ENTRIES = 100

VALID_STRATEGY_TYPES = {
    "covered_call",
    "protective_put",
    "straddle",
    "strangle",
    "bull_spread",
    "bear_spread",
    "iron_condor",
}

VALID_OPTION_TYPES = {"call", "put"}
VALID_DIRECTIONS = {"long", "short"}

# Strategy type → label mapping
STRATEGY_LABELS = {
    "covered_call": "INCOME",
    "protective_put": "HEDGING",
    "straddle": "SPECULATIVE",
    "strangle": "SPECULATIVE",
    "bull_spread": "DIRECTIONAL",
    "bear_spread": "DIRECTIONAL",
    "iron_condor": "NEUTRAL",
}


# ---------------------------------------------------------------------------
# Helpers: single-leg payoff
# ---------------------------------------------------------------------------

def _leg_payoff_at_price(leg: dict, underlying_price: float) -> float:
    """
    Calculate the payoff of one option leg at expiry for a given underlying price.
    Returns net P&L in USD per unit.
    """
    opt_type = leg["option_type"]
    strike = float(leg["strike"])
    premium = float(leg["premium_usd"])
    qty = float(leg["quantity"])
    direction = leg["direction"]

    if opt_type == "call":
        intrinsic = max(0.0, underlying_price - strike)
    else:  # put
        intrinsic = max(0.0, strike - underlying_price)

    if direction == "long":
        pnl_per_unit = intrinsic - premium
    else:  # short
        pnl_per_unit = premium - intrinsic

    return pnl_per_unit * qty


def _strategy_payoff_at_price(legs: list, underlying_price: float) -> float:
    """Sum payoffs of all legs at a given price."""
    return sum(_leg_payoff_at_price(leg, underlying_price) for leg in legs)


# ---------------------------------------------------------------------------
# Helpers: breakeven finder (binary search on payoff curve)
# ---------------------------------------------------------------------------

def _find_breakevens(
    legs: list,
    underlying_price: float,
    price_range_factor: float = 3.0,
    num_points: int = 2000,
) -> list:
    """
    Find breakeven prices where total payoff crosses zero.
    Uses a linear scan + linear interpolation between sign changes.
    """
    lo = max(0.01, underlying_price * (1.0 / price_range_factor))
    hi = underlying_price * price_range_factor
    step = (hi - lo) / num_points

    breakevens = []
    prev_price = lo
    prev_pnl = _strategy_payoff_at_price(legs, prev_price)

    price = lo + step
    while price <= hi:
        pnl = _strategy_payoff_at_price(legs, price)
        if prev_pnl * pnl < 0:
            # Linear interpolation for crossing
            t = abs(prev_pnl) / (abs(prev_pnl) + abs(pnl))
            be = prev_price + t * step
            # Avoid duplicates (within 0.01 tolerance)
            if not breakevens or abs(breakevens[-1] - be) > 0.01:
                breakevens.append(round(be, 4))
        prev_price = price
        prev_pnl = pnl
        price += step

    return sorted(breakevens)


# ---------------------------------------------------------------------------
# Helpers: max profit / max loss estimation
# ---------------------------------------------------------------------------

def _estimate_max_profit_loss(
    legs: list,
    underlying_price: float,
    price_range_factor: float = 5.0,
    num_points: int = 5000,
) -> tuple:
    """
    Scan payoff over a wide price range to estimate max profit and max loss.
    Returns (max_profit_usd, max_loss_usd).
    max_profit_usd is None if payoff is still increasing at the upper boundary
    (i.e., profit is potentially unlimited).
    """
    lo = 0.0
    hi = underlying_price * price_range_factor
    step = (hi - lo) / num_points

    payoffs = []
    price = lo
    while price <= hi:
        payoffs.append(_strategy_payoff_at_price(legs, price))
        price += step

    max_p = max(payoffs)
    min_p = min(payoffs)

    # Detect unlimited profit: check if payoff is still rising at the upper boundary.
    # Compare payoff in the last 1% of the range vs the payoff at 80% of the range.
    idx_80 = int(num_points * 0.80)
    idx_99 = int(num_points * 0.99)
    pnl_80 = payoffs[min(idx_80, len(payoffs) - 1)]
    pnl_99 = payoffs[min(idx_99, len(payoffs) - 1)]

    # Also check the downside (for long puts with no hedge)
    boundary_pnl_low = _strategy_payoff_at_price(legs, max(0.01, underlying_price * 0.01))
    pnl_10 = payoffs[min(int(num_points * 0.10), len(payoffs) - 1)]
    pnl_5 = payoffs[min(int(num_points * 0.05), len(payoffs) - 1)]

    # Profit is unlimited if payoff is still meaningfully increasing at top boundary
    still_rising_high = (pnl_99 - pnl_80) > max(0.01, abs(max_p) * 0.01)
    # Also check: profit growing as price falls to near-zero (long put unlimited downside)
    still_rising_low = (pnl_5 - pnl_10) > max(0.01, abs(max_p) * 0.01)

    unlimited_profit = still_rising_high or still_rising_low

    return (
        None if unlimited_profit else round(max_p, 4),
        round(min_p, 4),
    )


# ---------------------------------------------------------------------------
# Helpers: net premium
# ---------------------------------------------------------------------------

def _compute_net_premium(legs: list) -> float:
    """
    Positive = net debit (cost), negative = net credit (received).
    """
    total = 0.0
    for leg in legs:
        premium = float(leg["premium_usd"]) * float(leg["quantity"])
        if leg["direction"] == "long":
            total += premium   # paid
        else:
            total -= premium   # received
    return round(total, 4)


# ---------------------------------------------------------------------------
# Helpers: probability of profit (simplified)
# ---------------------------------------------------------------------------

def _probability_of_profit(
    breakevens: list,
    underlying_price: float,
    price_range_factor: float = 2.0,
) -> float:
    """
    Simplified: fraction of price range [0, underlying*factor] where payoff > 0.
    Uses breakeven prices to divide the range into profitable / unprofitable zones.
    """
    if not breakevens:
        # Check if always profitable or always unprofitable
        test_pnl = _strategy_payoff_at_price([], underlying_price)
        return 100.0  # edge case: empty breakeven list means always one sign

    lo = 0.0
    hi = underlying_price * price_range_factor
    total_range = hi - lo
    if total_range <= 0:
        return 0.0

    # Determine sign at lo
    test_legs = []  # needed to call helper, but we don't have legs here
    # We pass legs separately → refactor needed; keep interface simple via closure workaround
    return 0.0  # placeholder; real impl uses legs directly below


def _probability_of_profit_v2(
    legs: list,
    breakevens: list,
    underlying_price: float,
    price_range_factor: float = 2.5,
    num_points: int = 1000,
) -> float:
    """
    Measure what fraction of the scan range yields positive payoff.
    """
    lo = max(0.01, underlying_price * 0.01)
    hi = underlying_price * price_range_factor
    step = (hi - lo) / num_points

    profitable_range = 0.0
    price = lo
    while price <= hi:
        if _strategy_payoff_at_price(legs, price) > 0:
            profitable_range += step
        price += step

    total_range = hi - lo
    if total_range <= 0:
        return 0.0
    return round(min(100.0, profitable_range / total_range * 100.0), 2)


# ---------------------------------------------------------------------------
# Helpers: risk-reward ratio
# ---------------------------------------------------------------------------

def _risk_reward_ratio(
    max_profit: Optional[float], max_loss: float
) -> Optional[float]:
    """
    risk_reward = max_profit / abs(max_loss).
    Returns None if max_profit is None (unlimited) or max_loss is 0.
    """
    if max_profit is None:
        return None
    if abs(max_loss) < 0.01:
        return None
    return round(max_profit / abs(max_loss), 4)


# ---------------------------------------------------------------------------
# Helpers: flags
# ---------------------------------------------------------------------------

def _compute_flags(
    max_profit: Optional[float],
    max_loss: float,
    net_premium: float,
    expiry_days: int,
    legs: list,
) -> list:
    flags = []
    if max_profit is None:
        flags.append("UNLIMITED_PROFIT")
    if max_loss > -1e9 and max_loss >= -abs(net_premium) * 2.0:
        # Heuristic: loss bounded by premium paid or close to it
        flags.append("LIMITED_LOSS")
    if net_premium < 0:
        flags.append("NET_CREDIT")
    if expiry_days < 7:
        flags.append("NEAR_EXPIRY")
    if len(legs) > 2:
        flags.append("COMPLEX")
    return flags


# ---------------------------------------------------------------------------
# Validate input
# ---------------------------------------------------------------------------

def _validate_strategy(strategy: dict) -> None:
    required = {"name", "strategy_type", "legs", "underlying_price_usd", "expiry_days"}
    missing = required - set(strategy.keys())
    if missing:
        raise ValueError(f"Strategy missing fields: {missing}")

    st = strategy["strategy_type"]
    if st not in VALID_STRATEGY_TYPES:
        raise ValueError(f"Unknown strategy_type: {st!r}")

    if not isinstance(strategy["legs"], list) or len(strategy["legs"]) == 0:
        raise ValueError("legs must be a non-empty list")

    for i, leg in enumerate(strategy["legs"]):
        for field in ("option_type", "strike", "premium_usd", "quantity", "direction"):
            if field not in leg:
                raise ValueError(f"Leg {i} missing field: {field!r}")
        if leg["option_type"] not in VALID_OPTION_TYPES:
            raise ValueError(f"Leg {i}: invalid option_type {leg['option_type']!r}")
        if leg["direction"] not in VALID_DIRECTIONS:
            raise ValueError(f"Leg {i}: invalid direction {leg['direction']!r}")
        if float(leg["strike"]) <= 0:
            raise ValueError(f"Leg {i}: strike must be positive")
        if float(leg["premium_usd"]) < 0:
            raise ValueError(f"Leg {i}: premium_usd must be non-negative")
        if float(leg["quantity"]) <= 0:
            raise ValueError(f"Leg {i}: quantity must be positive")

    if float(strategy["underlying_price_usd"]) <= 0:
        raise ValueError("underlying_price_usd must be positive")
    if int(strategy["expiry_days"]) < 0:
        raise ValueError("expiry_days must be non-negative")


# ---------------------------------------------------------------------------
# Per-strategy analysis
# ---------------------------------------------------------------------------

def _analyze_single_strategy(strategy: dict, config: dict) -> dict:
    _validate_strategy(strategy)

    name = strategy["name"]
    stype = strategy["strategy_type"]
    legs = strategy["legs"]
    underlying = float(strategy["underlying_price_usd"])
    expiry_days = int(strategy["expiry_days"])

    price_range_factor = float(config.get("price_range_factor", 3.0))

    net_premium = _compute_net_premium(legs)
    breakevens = _find_breakevens(legs, underlying, price_range_factor)
    max_profit, max_loss = _estimate_max_profit_loss(
        legs, underlying, price_range_factor
    )
    prob_profit = _probability_of_profit_v2(legs, breakevens, underlying, price_range_factor)
    rr = _risk_reward_ratio(max_profit, max_loss)
    label = STRATEGY_LABELS.get(stype, "NEUTRAL")
    flags = _compute_flags(max_profit, max_loss, net_premium, expiry_days, legs)

    return {
        "name": name,
        "strategy_type": stype,
        "label": label,
        "net_premium_usd": net_premium,
        "max_profit_usd": max_profit,
        "max_loss_usd": max_loss,
        "breakeven_prices": breakevens,
        "probability_of_profit_pct": prob_profit,
        "risk_reward_ratio": rr,
        "flags": flags,
        "expiry_days": expiry_days,
        "underlying_price_usd": underlying,
        "leg_count": len(legs),
    }


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def _compute_aggregates(results: list) -> dict:
    if not results:
        return {
            "best_risk_reward": None,
            "best_risk_reward_name": None,
            "highest_profit_potential": None,
            "highest_profit_name": None,
            "total_premium_deployed_usd": 0.0,
            "average_probability_of_profit": 0.0,
            "net_credit_count": 0,
        }

    best_rr = None
    best_rr_name = None
    highest_profit = None
    highest_profit_name = None
    total_premium = 0.0
    prob_sum = 0.0
    net_credit_count = 0

    for r in results:
        rr = r.get("risk_reward_ratio")
        if rr is not None and (best_rr is None or rr > best_rr):
            best_rr = rr
            best_rr_name = r["name"]

        mp = r.get("max_profit_usd")
        if mp is not None and (highest_profit is None or mp > highest_profit):
            highest_profit = mp
            highest_profit_name = r["name"]
        elif mp is None:
            # Unlimited profit — mark
            if highest_profit is None:
                highest_profit_name = r["name"]

        npm = r.get("net_premium_usd", 0.0)
        if npm > 0:
            total_premium += npm

        prob_sum += r.get("probability_of_profit_pct", 0.0)

        if "NET_CREDIT" in r.get("flags", []):
            net_credit_count += 1

    return {
        "best_risk_reward": round(best_rr, 4) if best_rr is not None else None,
        "best_risk_reward_name": best_rr_name,
        "highest_profit_potential": round(highest_profit, 4) if highest_profit is not None else None,
        "highest_profit_name": highest_profit_name,
        "total_premium_deployed_usd": round(total_premium, 4),
        "average_probability_of_profit": round(prob_sum / len(results), 2),
        "net_credit_count": net_credit_count,
    }


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data) -> None:
    dir_ = os.path.dirname(path)
    if dir_ and not os.path.exists(dir_):
        os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_ or ".", prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_log(result: dict, log_path: str, cap: int = LOG_MAX_ENTRIES) -> None:
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        else:
            log = []
    except (json.JSONDecodeError, OSError):
        log = []

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "result": result,
    }
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]

    _atomic_write(log_path, log)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiOptionStrategyPayoffAnalyzer:
    """
    MP-936: Analyzes payoff profiles of DeFi option strategies.

    Supported strategy types:
      covered_call, protective_put, straddle, strangle,
      bull_spread, bear_spread, iron_condor

    Usage:
        analyzer = DeFiOptionStrategyPayoffAnalyzer()
        result = analyzer.analyze(strategies, config)
    """

    def __init__(self, log_path: str = LOG_PATH):
        self.log_path = log_path

    def analyze(self, strategies: list, config: dict) -> dict:
        """
        Analyze a list of option strategies.

        Args:
            strategies: list of strategy dicts, each containing:
                - name (str)
                - strategy_type (str): covered_call/protective_put/straddle/
                                       strangle/bull_spread/bear_spread/iron_condor
                - legs (list): each leg has option_type, strike, premium_usd,
                               quantity, direction (long/short)
                - underlying_price_usd (float)
                - expiry_days (int)
            config: dict with optional keys:
                - price_range_factor (float, default 3.0)
                - write_log (bool, default True)

        Returns:
            dict with 'strategies' (list of per-strategy results)
            and 'aggregates' (summary stats).
        """
        if not isinstance(strategies, list):
            raise TypeError("strategies must be a list")

        write_log = config.get("write_log", True)

        strategy_results = []
        errors = []

        for s in strategies:
            try:
                res = _analyze_single_strategy(s, config)
                strategy_results.append(res)
            except (ValueError, KeyError, TypeError) as e:
                errors.append({
                    "name": s.get("name", "<unknown>"),
                    "error": str(e),
                })

        aggregates = _compute_aggregates(strategy_results)

        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "module": "DeFiOptionStrategyPayoffAnalyzer",
            "mp": "MP-936",
            "strategies": strategy_results,
            "aggregates": aggregates,
            "errors": errors,
            "total_analyzed": len(strategy_results),
            "total_errors": len(errors),
        }

        if write_log:
            try:
                _append_log(result, self.log_path)
            except OSError:
                pass  # advisory — never crash on log write failure

        return result

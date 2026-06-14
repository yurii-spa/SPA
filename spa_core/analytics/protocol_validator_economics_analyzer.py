"""
MP-947: ProtocolValidatorEconomicsAnalyzer
Analyzes PoS validator economics: profitability, delegator APY, cost structure.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import os
import time
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "validator_economics_log.json"
)
LOG_CAP = 100

# Economics labels
LABEL_HIGHLY_PROFITABLE = "HIGHLY_PROFITABLE"
LABEL_PROFITABLE = "PROFITABLE"
LABEL_BREAK_EVEN = "BREAK_EVEN"
LABEL_LOSS_MAKING = "LOSS_MAKING"
LABEL_UNSUSTAINABLE = "UNSUSTAINABLE"

# Flags
FLAG_HIGH_SLASHING_RISK = "HIGH_SLASHING_RISK"
FLAG_LOW_UPTIME = "LOW_UPTIME"
FLAG_HIGH_COMMISSION = "HIGH_COMMISSION"
FLAG_UNDERDELEGATED = "UNDERDELEGATED"
FLAG_INFLATION_DEPENDENT = "INFLATION_DEPENDENT"

DEFAULT_CONFIG = {
    "highly_profitable_margin_pct": 50.0,   # profit_margin >= this → HIGHLY_PROFITABLE
    "profitable_margin_pct": 20.0,          # profit_margin >= this → PROFITABLE
    "break_even_margin_pct": 0.0,           # profit_margin >= this → BREAK_EVEN
    "loss_making_margin_pct": -50.0,        # profit_margin >= this → LOSS_MAKING else UNSUSTAINABLE
    "unsustainable_net_apy_pct": -10.0,     # net_apy <= this also marks UNSUSTAINABLE
    "low_uptime_threshold_pct": 99.0,       # uptime < this → LOW_UPTIME
    "high_commission_threshold_pct": 20.0,  # commission > this → HIGH_COMMISSION
    "inflation_dependent_ratio": 0.8,       # reward/inflation_yield > this → INFLATION_DEPENDENT
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_gross_apy(annual_reward_usd: float, stake_usd: float) -> float:
    """Gross APY = annual_reward / stake * 100."""
    if stake_usd <= 0:
        return 0.0
    return round(annual_reward_usd / stake_usd * 100.0, 6)


def _compute_net_apy(
    annual_reward_usd: float,
    operating_cost_usd_monthly: float,
    stake_usd: float,
) -> float:
    """Net APY = (annual_reward - annual_costs) / stake * 100."""
    if stake_usd <= 0:
        return 0.0
    annual_cost = operating_cost_usd_monthly * 12.0
    return round((annual_reward_usd - annual_cost) / stake_usd * 100.0, 6)


def _compute_profit_margin(
    annual_reward_usd: float, operating_cost_usd_monthly: float
) -> float:
    """Profit margin = (reward - annual_cost) / reward * 100."""
    if annual_reward_usd <= 0:
        annual_cost = operating_cost_usd_monthly * 12.0
        if annual_cost > 0:
            return -100.0  # spending with no reward
        return 0.0
    annual_cost = operating_cost_usd_monthly * 12.0
    return round((annual_reward_usd - annual_cost) / annual_reward_usd * 100.0, 6)


def _compute_delegator_apy(gross_apy_pct: float, commission_pct: float) -> float:
    """Delegator APY = gross_apy * (1 - commission/100)."""
    return round(gross_apy_pct * (1.0 - commission_pct / 100.0), 6)


def _compute_marginal_cost_per_stake(
    operating_cost_usd_monthly: float, stake_usd: float
) -> float:
    """Annual operating cost as % of stake."""
    if stake_usd <= 0:
        return 0.0
    return round(operating_cost_usd_monthly * 12.0 / stake_usd * 100.0, 6)


def _compute_market_share(stake_usd: float, total_stake_usd: float) -> float:
    """Market share = stake / total_stake * 100."""
    if total_stake_usd <= 0:
        return 0.0
    return round(stake_usd / total_stake_usd * 100.0, 6)


def _determine_label(
    profit_margin_pct: float, net_apy_pct: float, config: dict
) -> str:
    """HIGHLY_PROFITABLE / PROFITABLE / BREAK_EVEN / LOSS_MAKING / UNSUSTAINABLE."""
    highly_prof = float(config.get("highly_profitable_margin_pct", 50.0))
    prof = float(config.get("profitable_margin_pct", 20.0))
    break_even = float(config.get("break_even_margin_pct", 0.0))
    loss_making_floor = float(config.get("loss_making_margin_pct", -50.0))
    unsustainable_net = float(config.get("unsustainable_net_apy_pct", -10.0))

    if profit_margin_pct < loss_making_floor or net_apy_pct <= unsustainable_net:
        return LABEL_UNSUSTAINABLE
    if profit_margin_pct >= highly_prof:
        return LABEL_HIGHLY_PROFITABLE
    if profit_margin_pct >= prof:
        return LABEL_PROFITABLE
    if profit_margin_pct >= break_even:
        return LABEL_BREAK_EVEN
    return LABEL_LOSS_MAKING


def _compute_flags(
    validator: dict,
    annual_reward_usd: float,
    config: dict,
) -> list:
    """Compute all applicable flags for this validator."""
    flags = []

    slashing_events = int(validator.get("slashing_events_count", 0))
    uptime_pct = float(validator.get("uptime_pct", 100.0))
    commission_pct = float(validator.get("commission_pct", 0.0))
    delegated_stake_usd = float(validator.get("delegated_stake_usd", 0.0))
    stake_usd = float(validator.get("stake_usd", 0.0))
    self_stake_pct = float(validator.get("self_stake_pct", 100.0))
    chain_inflation_rate_pct = float(validator.get("chain_inflation_rate_pct", 0.0))

    low_uptime_thresh = float(config.get("low_uptime_threshold_pct", 99.0))
    high_comm_thresh = float(config.get("high_commission_threshold_pct", 20.0))
    inflation_ratio = float(config.get("inflation_dependent_ratio", 0.8))

    if slashing_events > 0:
        flags.append(FLAG_HIGH_SLASHING_RISK)

    if uptime_pct < low_uptime_thresh:
        flags.append(FLAG_LOW_UPTIME)

    if commission_pct > high_comm_thresh:
        flags.append(FLAG_HIGH_COMMISSION)

    # UNDERDELEGATED: delegated < self_stake_amount
    self_stake_amount = stake_usd * self_stake_pct / 100.0
    if delegated_stake_usd < self_stake_amount:
        flags.append(FLAG_UNDERDELEGATED)

    # INFLATION_DEPENDENT: annual_reward / (stake * inflation_rate) > threshold
    if chain_inflation_rate_pct > 0 and stake_usd > 0:
        inflation_yield = stake_usd * chain_inflation_rate_pct / 100.0
        if inflation_yield > 0 and annual_reward_usd / inflation_yield > inflation_ratio:
            flags.append(FLAG_INFLATION_DEPENDENT)

    return flags


def _analyze_validator(
    validator: dict, total_stake_usd: float, config: dict
) -> dict:
    """Compute all per-validator analytics."""
    protocol = validator.get("protocol", "UNKNOWN")
    stake_usd = float(validator.get("stake_usd", 0.0))
    annual_reward_usd = float(validator.get("annual_reward_usd", 0.0))
    operating_cost_usd_monthly = float(validator.get("operating_cost_usd_monthly", 0.0))
    uptime_pct = float(validator.get("uptime_pct", 100.0))
    slashing_events_count = int(validator.get("slashing_events_count", 0))
    commission_pct = float(validator.get("commission_pct", 0.0))
    delegated_stake_usd = float(validator.get("delegated_stake_usd", 0.0))
    self_stake_pct = float(validator.get("self_stake_pct", 100.0))
    chain_inflation_rate_pct = float(validator.get("chain_inflation_rate_pct", 0.0))
    validator_count_total = int(validator.get("validator_count_total", 1))

    gross_apy_pct = _compute_gross_apy(annual_reward_usd, stake_usd)
    net_apy_pct = _compute_net_apy(annual_reward_usd, operating_cost_usd_monthly, stake_usd)
    profit_margin_pct = _compute_profit_margin(annual_reward_usd, operating_cost_usd_monthly)
    delegator_apy_pct = _compute_delegator_apy(gross_apy_pct, commission_pct)
    marginal_cost_per_stake_usd = _compute_marginal_cost_per_stake(
        operating_cost_usd_monthly, stake_usd
    )
    market_share_pct = _compute_market_share(stake_usd, total_stake_usd)

    label = _determine_label(profit_margin_pct, net_apy_pct, config)
    flags = _compute_flags(validator, annual_reward_usd, config)

    return {
        "protocol": protocol,
        "stake_usd": stake_usd,
        "annual_reward_usd": annual_reward_usd,
        "operating_cost_usd_monthly": operating_cost_usd_monthly,
        "uptime_pct": uptime_pct,
        "slashing_events_count": slashing_events_count,
        "commission_pct": commission_pct,
        "delegated_stake_usd": delegated_stake_usd,
        "self_stake_pct": self_stake_pct,
        "chain_inflation_rate_pct": chain_inflation_rate_pct,
        "validator_count_total": validator_count_total,
        # Computed
        "gross_apy_pct": gross_apy_pct,
        "net_apy_pct": net_apy_pct,
        "profit_margin_pct": profit_margin_pct,
        "delegator_apy_pct": delegator_apy_pct,
        "marginal_cost_per_stake_usd": marginal_cost_per_stake_usd,
        "market_share_pct": market_share_pct,
        "economics_label": label,
        "flags": flags,
    }


def _compute_aggregates(results: list) -> dict:
    """Compute portfolio-level aggregates."""
    if not results:
        return {
            "most_profitable_validator": None,
            "least_profitable": None,
            "average_net_apy": 0.0,
            "average_delegator_apy": 0.0,
            "profitable_count": 0,
        }

    net_apys = [r["net_apy_pct"] for r in results]
    best_idx = net_apys.index(max(net_apys))
    worst_idx = net_apys.index(min(net_apys))

    avg_net = round(sum(net_apys) / len(net_apys), 6)
    del_apys = [r["delegator_apy_pct"] for r in results]
    avg_del = round(sum(del_apys) / len(del_apys), 6)
    profitable = sum(1 for r in results if r["net_apy_pct"] > 0)

    return {
        "most_profitable_validator": results[best_idx]["protocol"],
        "least_profitable": results[worst_idx]["protocol"],
        "average_net_apy": avg_net,
        "average_delegator_apy": avg_del,
        "profitable_count": profitable,
    }


def _write_log(entry: dict) -> None:
    """Append entry to ring-buffer log (atomic write, cap LOG_CAP)."""
    log_path = os.path.normpath(LOG_PATH)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    existing: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    existing = data
        except Exception:
            existing = []

    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]

    tmp_path = log_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp_path, log_path)


class ProtocolValidatorEconomicsAnalyzer:
    """
    Analyzes PoS validator economics including gross/net APY,
    profit margins, delegator returns, and risk flags.
    """

    def analyze(self, validators: list, config: Optional[dict] = None) -> dict:
        """
        Main entry point.

        Args:
            validators: list of validator dicts
            config: optional config overrides

        Returns:
            dict with 'validators' (per-validator analytics) and 'aggregates'.
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}

        # Compute total stake for market share calculation
        total_stake_usd = sum(
            float(v.get("stake_usd", 0.0)) for v in validators
        )

        analyzed = []
        for val in validators:
            result = _analyze_validator(val, total_stake_usd, cfg)
            analyzed.append(result)

        aggregates = _compute_aggregates(analyzed)

        output = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "validator_count": len(analyzed),
            "total_stake_usd": round(total_stake_usd, 4),
            "validators": analyzed,
            "aggregates": aggregates,
        }

        log_entry = {
            "timestamp": output["timestamp"],
            "validator_count": len(analyzed),
            "total_stake_usd": output["total_stake_usd"],
            "average_net_apy": aggregates["average_net_apy"],
            "profitable_count": aggregates["profitable_count"],
        }
        try:
            _write_log(log_entry)
        except Exception:
            pass  # analytics never raises

        return output

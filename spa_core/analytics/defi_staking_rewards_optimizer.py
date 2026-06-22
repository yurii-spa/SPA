"""
MP-843 DeFiStakingRewardsOptimizer
===================================
Advisory-only analytics module. Compares lockup periods, compounding frequencies,
and reward token stability across staking options to find the best risk-adjusted
staking approach.

Output: data/staking_rewards_log.json  (ring-buffer, cap 100, atomic write)
CLI:
    python3 -m spa_core.analytics.defi_staking_rewards_optimizer --check
    python3 -m spa_core.analytics.defi_staking_rewards_optimizer --run [--data-dir DIR]
"""

from __future__ import annotations

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_CAP = 100
_DEFAULT_MAX_LOCKUP_DAYS = 365
_DEFAULT_RISK_TOLERANCE = 50

_STABILITY_PENALTY: dict[str, float] = {
    "STABLE": 0.0,
    "VOLATILE": 0.1,
    "HIGHLY_VOLATILE": 0.3,
}

_STAKE_SCORE_THRESHOLD = 5.0
_STAKE_APY_THRESHOLD = 3.0

# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compound_apy(total_apy: float, compound_frequency: int) -> float:
    """Effective APY after compounding (returns %)."""
    if compound_frequency == 0:
        return total_apy
    r = total_apy / 100.0
    n = compound_frequency
    return ((1 + r / n) ** n - 1) * 100.0


def _stability_penalty(reward_token_stability: str) -> float:
    """Return reduction factor (0.0 / 0.1 / 0.3)."""
    return _STABILITY_PENALTY.get(reward_token_stability, 0.0)


def _lockup_penalty_factor(lockup_days: int) -> float:
    """Lockup-based score multiplier: 0 days → 1.0; 3650 days → 0.0."""
    return max(0.0, 1.0 - lockup_days / 3650.0)


def _skip_reason(
    lockup_days: int,
    risk_score: int,
    capital_usd: float,
    min_stake_usd: float,
    max_lockup_days: int,
    risk_tolerance: int,
) -> str | None:
    """Return first applicable skip reason, or None."""
    if lockup_days > max_lockup_days:
        return f"Lockup {lockup_days}d exceeds max {max_lockup_days}d"
    if risk_score > risk_tolerance:
        return f"Risk score {risk_score} exceeds tolerance {risk_tolerance}"
    if capital_usd < min_stake_usd:
        return f"Capital ${capital_usd:.0f} below minimum ${min_stake_usd:.0f}"
    return None


def _recommendation(
    final_score: float,
    risk_adjusted_apy: float,
    reason: str | None,
) -> str:
    if reason is not None:
        return "SKIP"
    if final_score >= _STAKE_SCORE_THRESHOLD and risk_adjusted_apy >= _STAKE_APY_THRESHOLD:
        return "STAKE"
    return "CONSIDER"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    staking_options: list[dict],
    capital_usd: float,
    config: dict | None = None,
) -> dict:
    """
    Analyze staking options and return risk-adjusted rankings.

    Parameters
    ----------
    staking_options : list of dicts describing each staking opportunity.
    capital_usd     : available capital in USD.
    config          : optional overrides for max_lockup_days, risk_tolerance.

    Returns
    -------
    dict with keys: options, best_option, filtered_count, viable_count, timestamp.
    """
    cfg = config or {}
    max_lockup_days: int = int(cfg.get("max_lockup_days", _DEFAULT_MAX_LOCKUP_DAYS))
    risk_tolerance: int = int(cfg.get("risk_tolerance", _DEFAULT_RISK_TOLERANCE))

    results: list[dict] = []
    filtered_count = 0
    viable_count = 0

    for opt in staking_options:
        protocol: str = opt.get("protocol", "")
        base_apy: float = float(opt.get("base_apy", 0.0))
        bonus_apy: float = float(opt.get("bonus_apy", 0.0))
        lockup_days: int = int(opt.get("lockup_days", 0))
        compound_frequency: int = int(opt.get("compound_frequency", 1))
        reward_token_stability: str = opt.get("reward_token_stability", "STABLE")
        min_stake_usd: float = float(opt.get("min_stake_usd", 0.0))
        risk_score: int = int(opt.get("risk_score", 0))

        total_apy = base_apy + bonus_apy
        effective_apy = _compound_apy(total_apy, compound_frequency)

        penalty = _stability_penalty(reward_token_stability)
        adjusted_apy_after_stability = effective_apy * (1.0 - penalty)

        risk_factor = 1.0 - risk_score / 100.0
        risk_adjusted_apy = adjusted_apy_after_stability * risk_factor

        annual_yield_usd = risk_adjusted_apy / 100.0 * capital_usd

        final_score = max(0.0, risk_adjusted_apy * _lockup_penalty_factor(lockup_days))

        reason = _skip_reason(
            lockup_days, risk_score, capital_usd,
            min_stake_usd, max_lockup_days, risk_tolerance,
        )

        rec = _recommendation(final_score, risk_adjusted_apy, reason)

        if rec == "SKIP":
            filtered_count += 1
        elif rec == "STAKE":
            viable_count += 1

        results.append({
            "protocol": protocol,
            "total_apy": total_apy,
            "effective_apy": effective_apy,
            "risk_adjusted_apy": risk_adjusted_apy,
            "annual_yield_usd": annual_yield_usd,
            "lockup_days": lockup_days,
            "reward_stability_penalty": penalty,
            "final_score": final_score,
            "recommendation": rec,
            "skip_reason": reason,
        })

    # Best option: highest final_score among STAKE
    best_option: str | None = None
    stake_results = [r for r in results if r["recommendation"] == "STAKE"]
    if stake_results:
        best_option = max(stake_results, key=lambda r: r["final_score"])["protocol"]

    return {
        "options": results,
        "best_option": best_option,
        "filtered_count": filtered_count,
        "viable_count": viable_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _log_result(result: dict, data_dir: str) -> None:
    """Append result to the ring-buffer log (atomic write)."""
    log_path = os.path.join(data_dir, "staking_rewards_log.json")
    tmp_path = log_path + ".tmp"

    entries: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(result)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_demo_options() -> list[dict]:
    return [
        {
            "protocol": "Aave V3",
            "base_apy": 3.5,
            "bonus_apy": 0.5,
            "lockup_days": 0,
            "compound_frequency": 365,
            "reward_token_stability": "STABLE",
            "min_stake_usd": 1000.0,
            "risk_score": 20,
        },
        {
            "protocol": "Compound V3",
            "base_apy": 4.8,
            "bonus_apy": 0.0,
            "lockup_days": 30,
            "compound_frequency": 12,
            "reward_token_stability": "STABLE",
            "min_stake_usd": 500.0,
            "risk_score": 25,
        },
        {
            "protocol": "Morpho Steakhouse",
            "base_apy": 6.0,
            "bonus_apy": 0.5,
            "lockup_days": 0,
            "compound_frequency": 365,
            "reward_token_stability": "VOLATILE",
            "min_stake_usd": 100.0,
            "risk_score": 35,
        },
        {
            "protocol": "HighRisk Protocol",
            "base_apy": 25.0,
            "bonus_apy": 5.0,
            "lockup_days": 400,
            "compound_frequency": 1,
            "reward_token_stability": "HIGHLY_VOLATILE",
            "min_stake_usd": 0.0,
            "risk_score": 80,
        },
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-843 DeFiStakingRewardsOptimizer")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    # Resolve data dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    data_dir = args.data_dir or os.path.join(repo_root, "data")

    options = _default_demo_options()
    result = analyze(options, capital_usd=100_000.0)

    print(json.dumps(result, indent=2))

    if args.run:
        _log_result(result, data_dir)
        print(f"\n[MP-843] Log written → {os.path.join(data_dir, 'staking_rewards_log.json')}")
    elif not args.check:
        # Default: just print
        pass


if __name__ == "__main__":
    main()


# =============================================================================
# MP-954: DeFiStakingRewardsOptimizer (class-based, gas-aware)
# Added to this module to share the staking_rewards_log.json log file.
# Advisory-only. Pure stdlib. Atomic ring-buffer log.
# =============================================================================

import math as _math_mp954
import tempfile as _tempfile_mp954


class DeFiStakingRewardsOptimizer:
    """
    MP-954: Optimizes staking positions by computing optimal compound frequency
    and net APY after gas costs. Uses sqrt(2*gas/daily_reward) formula.

    Advisory-only. Pure stdlib. Ring-buffer log → data/staking_rewards_log.json.
    """

    _LOG_CAP = 100
    _VERSION = "mp954-1.0"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, staking_positions: list, config: dict = None) -> dict:
        """
        Analyze each staking position for optimal compound frequency and net APY.

        Parameters
        ----------
        staking_positions : list[dict]
            Each dict: protocol, asset, staked_amount_usd, base_apy_pct,
            bonus_apy_pct, reward_token_price_usd,
            reward_emission_rate_per_day_usd, gas_cost_per_claim_usd,
            lock_period_days, days_staked, auto_compound_available (bool),
            min_claim_threshold_usd
        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict with keys: positions, aggregates, metadata
        """
        cfg = config or {}
        results = [self._analyze_position(pos, cfg) for pos in staking_positions]
        aggregates = self._compute_aggregates(results)
        ts = time.time()
        return {
            "positions": results,
            "aggregates": aggregates,
            "metadata": {
                "timestamp": ts,
                "version": self._VERSION,
                "positions_analyzed": len(results),
                "run_id": f"mp954_{int(ts)}",
            },
        }

    def write_log(self, result: dict, data_dir: str) -> None:
        """Append result to ring-buffer log (atomic write, cap 100)."""
        log_path = os.path.join(data_dir, "staking_rewards_log.json")
        os.makedirs(data_dir, exist_ok=True)

        entries: list = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    entries = json.load(fh)
                if not isinstance(entries, list):
                    entries = []
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(result)
        if len(entries) > self._LOG_CAP:
            entries = entries[-self._LOG_CAP:]

        dir_name = os.path.dirname(log_path) or "."
        tmp_fd, tmp_path = _tempfile_mp954.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                json.dump(entries, fh, indent=2)
            os.replace(tmp_path, log_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _analyze_position(self, pos: dict, cfg: dict) -> dict:
        protocol = pos.get("protocol", "")
        asset = pos.get("asset", "")
        staked_amount_usd = float(pos.get("staked_amount_usd", 0.0))
        base_apy_pct = float(pos.get("base_apy_pct", 0.0))
        bonus_apy_pct = float(pos.get("bonus_apy_pct", 0.0))
        daily_reward_usd = float(pos.get("reward_emission_rate_per_day_usd", 0.0))
        gas_cost_per_claim_usd = float(pos.get("gas_cost_per_claim_usd", 0.0))
        lock_period_days = float(pos.get("lock_period_days", 0.0))
        days_staked = float(pos.get("days_staked", 0.0))
        auto_compound_available = bool(pos.get("auto_compound_available", False))
        min_claim_threshold_usd = float(pos.get("min_claim_threshold_usd", 0.0))

        # ---- optimal compound frequency (sqrt formula) ----
        if auto_compound_available and daily_reward_usd > 0 and gas_cost_per_claim_usd > 0:
            optimal_cf = _math_mp954.sqrt(2.0 * gas_cost_per_claim_usd / daily_reward_usd)
            optimal_cf = max(1.0, optimal_cf)
        elif auto_compound_available and daily_reward_usd > 0:
            optimal_cf = 1.0  # free gas → compound daily
        else:
            optimal_cf = 365.0  # no auto-compound → once per year

        # ---- compound APY ----
        total_apy_pct = base_apy_pct + bonus_apy_pct
        if auto_compound_available and optimal_cf > 0:
            n = max(1.0, 365.0 / optimal_cf)
            r = total_apy_pct / 100.0
            compound_apy_pct = ((1.0 + r / n) ** n - 1.0) * 100.0
        else:
            compound_apy_pct = total_apy_pct

        # ---- annual gas cost as pct of staked ----
        if staked_amount_usd > 0 and optimal_cf > 0:
            claims_per_year = 365.0 / optimal_cf
            annual_gas_usd = gas_cost_per_claim_usd * claims_per_year
            annual_gas_pct = (annual_gas_usd / staked_amount_usd) * 100.0
        else:
            annual_gas_pct = 0.0

        net_apy_after_gas_pct = compound_apy_pct - annual_gas_pct

        # ---- gas efficiency ratio ----
        if gas_cost_per_claim_usd > 0 and daily_reward_usd > 0:
            rewards_per_claim = daily_reward_usd * optimal_cf
            gas_efficiency_ratio = rewards_per_claim / gas_cost_per_claim_usd
        elif gas_cost_per_claim_usd == 0.0 and daily_reward_usd > 0:
            gas_efficiency_ratio = None   # "infinite" — gas is free
        else:
            gas_efficiency_ratio = 0.0

        # ---- days to break even gas ----
        if daily_reward_usd > 0 and gas_cost_per_claim_usd > 0:
            days_to_break_even_gas = gas_cost_per_claim_usd / daily_reward_usd
        elif gas_cost_per_claim_usd == 0.0:
            days_to_break_even_gas = 0.0
        else:
            days_to_break_even_gas = None  # no rewards → never breaks even

        # ---- flags ----
        flags: list = []

        # GAS_TRAP flag: gas_per_claim > 50% of daily reward
        is_gas_trap_flag = (
            daily_reward_usd > 0
            and gas_cost_per_claim_usd > 0
            and gas_cost_per_claim_usd > 0.5 * daily_reward_usd
        )

        # Label GAS_TRAP: gas > 50% of rewards per claim period
        rewards_per_period = daily_reward_usd * max(1.0, optimal_cf)
        is_label_gas_trap = (
            daily_reward_usd > 0
            and gas_cost_per_claim_usd > 0
            and gas_cost_per_claim_usd > 0.5 * rewards_per_period
        )

        # AUTO_COMPOUND_OPTIMAL: compounding provides net gain (not gas-trap)
        if auto_compound_available and compound_apy_pct > total_apy_pct and not is_label_gas_trap:
            flags.append("AUTO_COMPOUND_OPTIMAL")

        if is_gas_trap_flag:
            flags.append("GAS_TRAP")

        if days_staked < lock_period_days:
            flags.append("LOCK_PERIOD_ACTIVE")

        if bonus_apy_pct > 0:
            flags.append("BONUS_APY_AVAILABLE")

        # MIN_THRESHOLD_NOT_MET: daily reward < min_claim_threshold / 7
        if min_claim_threshold_usd > 0 and daily_reward_usd < min_claim_threshold_usd / 7.0:
            flags.append("MIN_THRESHOLD_NOT_MET")

        # ---- label ----
        gas_efficient = (gas_efficiency_ratio is None) or (
            isinstance(gas_efficiency_ratio, float) and gas_efficiency_ratio >= 2.0
        )
        if is_label_gas_trap:
            label = "GAS_TRAP"
        elif net_apy_after_gas_pct > 15.0 and gas_efficient:
            label = "EXCELLENT"
        elif net_apy_after_gas_pct >= 8.0:
            label = "GOOD"
        elif net_apy_after_gas_pct >= 3.0:
            label = "ADEQUATE"
        else:
            label = "POOR"

        return {
            "protocol": protocol,
            "asset": asset,
            "staked_amount_usd": staked_amount_usd,
            "daily_reward_usd": daily_reward_usd,
            "optimal_compound_frequency_days": round(optimal_cf, 6),
            "compound_apy_pct": round(compound_apy_pct, 6),
            "net_apy_after_gas_pct": round(net_apy_after_gas_pct, 6),
            "gas_efficiency_ratio": (
                round(gas_efficiency_ratio, 6)
                if isinstance(gas_efficiency_ratio, float)
                else gas_efficiency_ratio
            ),
            "days_to_break_even_gas": (
                round(days_to_break_even_gas, 6)
                if isinstance(days_to_break_even_gas, float)
                else days_to_break_even_gas
            ),
            "label": label,
            "flags": flags,
        }

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_net_apy_position": None,
                "worst_net_apy_position": None,
                "total_daily_rewards_usd": 0.0,
                "average_gas_efficiency": None,
                "gas_trap_count": 0,
            }

        best = max(results, key=lambda r: r["net_apy_after_gas_pct"])
        worst = min(results, key=lambda r: r["net_apy_after_gas_pct"])
        total_daily = sum(r["daily_reward_usd"] for r in results)

        efficiencies = [
            r["gas_efficiency_ratio"] for r in results
            if isinstance(r["gas_efficiency_ratio"], float)
        ]
        avg_efficiency = (sum(efficiencies) / len(efficiencies)) if efficiencies else None

        gas_trap_count = sum(1 for r in results if "GAS_TRAP" in r["flags"])

        return {
            "best_net_apy_position": best["protocol"],
            "worst_net_apy_position": worst["protocol"],
            "total_daily_rewards_usd": round(total_daily, 8),
            "average_gas_efficiency": (
                round(avg_efficiency, 6) if avg_efficiency is not None else None
            ),
            "gas_trap_count": gas_trap_count,
        }

"""
MP-911 YieldDilutionAnalyzer
-------------------------------------
Advisory / read-only analytics module.
When capital flows into a yield pool, APY dilutes because fees/rewards are
split across a larger TVL base. This module models post-deposit APY, scores
"crowding" risk, and computes the largest deposit that keeps APY above a
floor — helping decide how much to deposit and which pools resist crowding.

Per-pool input keys (dict):
    name              (str)   pool name
    current_tvl_usd   (float) current total value locked, USD
    current_apy_pct   (float) current total APY, percent
    reward_apy_pct    (float) APY from token emissions (dilutes ~ 1/TVL)
    base_apy_pct      (float) APY from organic fees/lending (see assumption)
    expected_inflow_usd (float) anticipated near-term inflow from OTHERS
    your_deposit_usd  (float) the deposit you are considering

Dilution model (see _diluted_apy):
    added_tvl = your_deposit + expected_inflow
    reward component scales by current_tvl / (current_tvl + added_tvl)
        (fixed emission budget split over a larger TVL → inverse dilution)
    base/fee component scales by sqrt(current_tvl / (current_tvl + added_tvl))
        ASSUMPTION: fee/lending yield is partially TVL-elastic (utilisation
        and fee volume do not grow as fast as deposits), modelled as a mild
        square-root dilution rather than fully TVL-stable.

CLI:
    python3 -m spa_core.analytics.yield_dilution_analyzer --check
    python3 -m spa_core.analytics.yield_dilution_analyzer --run
    python3 -m spa_core.analytics.yield_dilution_analyzer --run --data-dir <dir>
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_APY_FLOOR_PCT = 5.0
_LOG_CAP = 100
_THIN_TVL_USD = 1_000_000.0          # below this, pool is "thin"
_HIGH_REWARD_SHARE_PCT = 60.0        # reward share above this → emission-dependent
_LARGE_REL_DEPOSIT_RATIO = 0.25      # added_tvl/current_tvl above this → large
_SEVERE_DILUTION_PCT = 20.0          # marginal impact (% of APY lost) above this
_MAX_DEPOSIT_CAP_USD = 1_000_000_000.0  # sane upper bound for floor inversion
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "yield_dilution_log.json",
)

# ---------------------------------------------------------------------------
# Core dilution math (all divisions zero-guarded)
# ---------------------------------------------------------------------------

def _dilution_factor(current_tvl: float, added_tvl: float) -> float:
    """current_tvl / (current_tvl + added_tvl), clamped to (0, 1]."""
    denom = current_tvl + added_tvl
    if denom <= 0:
        return 1.0
    factor = current_tvl / denom
    if factor < 0.0:
        return 0.0
    if factor > 1.0:
        return 1.0
    return factor


def _diluted_apy(
    reward_apy: float,
    base_apy: float,
    current_tvl: float,
    added_tvl: float,
) -> float:
    """
    Post-deposit total APY.

    reward component scales linearly by the dilution factor (fixed emission
    split over larger TVL); base/fee component scales by sqrt of the dilution
    factor (mild documented elasticity, see module docstring).
    """
    if added_tvl <= 0:
        return reward_apy + base_apy
    factor = _dilution_factor(current_tvl, added_tvl)
    diluted_reward = reward_apy * factor
    diluted_base = base_apy * math.sqrt(factor)
    return diluted_reward + diluted_base


def _marginal_apy_impact_pct(current_apy: float, diluted_apy: float) -> float:
    """
    Percentage-point drop in APY attributable to entering (current - diluted).
    Never negative (a non-diluting deposit yields 0 impact).
    """
    drop = current_apy - diluted_apy
    return drop if drop > 0 else 0.0


def _reward_share_pct(reward_apy: float, base_apy: float) -> float:
    """Reward emissions as a percentage of total APY. Zero-guarded."""
    total = reward_apy + base_apy
    if total <= 0:
        return 0.0
    share = (reward_apy / total) * 100.0
    if share < 0.0:
        return 0.0
    if share > 100.0:
        return 100.0
    return share


# ---------------------------------------------------------------------------
# Crowding risk scoring (0–100)
# ---------------------------------------------------------------------------

def _reward_dependence_signal(reward_share_pct: float) -> float:
    """0–40: higher when more of the APY comes from dilutable emissions."""
    return max(0.0, min(40.0, (reward_share_pct / 100.0) * 40.0))


def _relative_size_signal(current_tvl: float, added_tvl: float) -> float:
    """
    0–40: higher when added TVL is large relative to current TVL.
    Saturates at ratio >= 1.0 (added equals current pool size).
    """
    if current_tvl <= 0:
        return 40.0 if added_tvl > 0 else 0.0
    ratio = added_tvl / current_tvl
    if ratio < 0.0:
        ratio = 0.0
    return max(0.0, min(40.0, min(ratio, 1.0) * 40.0))


def _thin_tvl_signal(current_tvl: float) -> float:
    """0–20: higher when the pool TVL is small (less able to absorb inflow)."""
    if current_tvl <= 0:
        return 20.0
    if current_tvl >= _THIN_TVL_USD:
        return 0.0
    # linear: 0 at threshold, 20 at zero TVL
    return max(0.0, min(20.0, (1.0 - current_tvl / _THIN_TVL_USD) * 20.0))


def _crowding_risk_score(
    reward_share_pct: float,
    current_tvl: float,
    added_tvl: float,
) -> int:
    total = (
        _reward_dependence_signal(reward_share_pct)
        + _relative_size_signal(current_tvl, added_tvl)
        + _thin_tvl_signal(current_tvl)
    )
    return int(max(0, min(100, round(total))))


def _max_deposit_for_floor(
    reward_apy: float,
    base_apy: float,
    current_tvl: float,
    expected_inflow: float,
    apy_floor_pct: float,
) -> float:
    """
    Largest your_deposit (USD) such that the diluted APY stays >= floor,
    given the expected inflow from others is already present.

    Returns 0.0 if even a zero deposit is below floor. Caps the result at
    _MAX_DEPOSIT_CAP_USD when the floor is so low it is effectively always met.
    All divisions guarded; monotone search via the dilution model.
    """
    if apy_floor_pct <= 0:
        return _MAX_DEPOSIT_CAP_USD

    inflow = expected_inflow if expected_inflow > 0 else 0.0
    tvl = current_tvl if current_tvl > 0 else 0.0

    # APY achievable with zero additional deposit (inflow only present).
    apy_at_zero = _diluted_apy(reward_apy, base_apy, tvl, inflow)
    if apy_at_zero < apy_floor_pct:
        return 0.0

    # Bisect on your_deposit in [0, _MAX_DEPOSIT_CAP_USD]; diluted APY is
    # monotone decreasing in deposit.
    lo = 0.0
    hi = _MAX_DEPOSIT_CAP_USD
    apy_at_cap = _diluted_apy(reward_apy, base_apy, tvl, inflow + hi)
    if apy_at_cap >= apy_floor_pct:
        return _MAX_DEPOSIT_CAP_USD

    for _ in range(80):
        mid = (lo + hi) / 2.0
        apy_mid = _diluted_apy(reward_apy, base_apy, tvl, inflow + mid)
        if apy_mid >= apy_floor_pct:
            lo = mid
        else:
            hi = mid
    return lo if lo > 0 else 0.0


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _risk_label(score: int) -> str:
    if score <= 20:
        return "LOW"
    if score <= 40:
        return "MODERATE"
    if score <= 60:
        return "ELEVATED"
    if score <= 80:
        return "HIGH"
    return "SEVERE"


def _grade(score: int) -> str:
    """Higher crowding risk → worse grade."""
    if score <= 20:
        return "A"
    if score <= 40:
        return "B"
    if score <= 60:
        return "C"
    if score <= 80:
        return "D"
    return "F"


def _reward_share_label(reward_share_pct: float) -> str:
    if reward_share_pct >= 75.0:
        return "EMISSION_HEAVY"
    if reward_share_pct >= 40.0:
        return "MIXED"
    if reward_share_pct > 0.0:
        return "FEE_HEAVY"
    return "FEE_ONLY"


def _classification(
    reward_share_pct: float,
    crowding_score: int,
    current_tvl: float,
) -> str:
    if current_tvl <= 0:
        return "SATURATED"
    if reward_share_pct >= _HIGH_REWARD_SHARE_PCT:
        return "EMISSION_DEPENDENT"
    if crowding_score >= 60:
        return "DILUTION_SENSITIVE"
    if current_tvl < _THIN_TVL_USD:
        return "SATURATED"
    return "CROWD_RESISTANT"


def _build_flags(
    reward_share_pct: float,
    current_tvl: float,
    added_tvl: float,
    marginal_impact_pct: float,
    current_apy: float,
    base_apy: float,
    has_data: bool,
) -> list[str]:
    flags: list[str] = []
    if not has_data:
        flags.append("INSUFFICIENT_DATA")
        return flags
    if reward_share_pct > _HIGH_REWARD_SHARE_PCT:
        flags.append("HIGH_REWARD_DEPENDENCE")
    if current_tvl > 0 and (added_tvl / current_tvl) > _LARGE_REL_DEPOSIT_RATIO:
        flags.append("LARGE_RELATIVE_DEPOSIT")
    elif current_tvl <= 0 and added_tvl > 0:
        flags.append("LARGE_RELATIVE_DEPOSIT")
    if current_tvl < _THIN_TVL_USD:
        flags.append("THIN_TVL")
    # severe dilution: marginal impact as a fraction of current APY
    if current_apy > 0 and (marginal_impact_pct / current_apy) * 100.0 > _SEVERE_DILUTION_PCT:
        flags.append("SEVERE_DILUTION")
    if base_apy < 0:
        flags.append("NEGATIVE_BASE_YIELD")
    return flags


def _recommendation(
    risk_lbl: str,
    classification: str,
    max_deposit_for_floor_usd: float,
    flags: list[str],
) -> str:
    if "INSUFFICIENT_DATA" in flags:
        return "Insufficient data. Provide TVL and APY breakdown before deciding."
    if risk_lbl in ("LOW", "MODERATE"):
        return (
            f"{classification}. Crowding risk {risk_lbl.lower()}; "
            f"room for ~${max_deposit_for_floor_usd:,.0f} before APY floor."
        )
    if risk_lbl == "ELEVATED":
        flag_str = ", ".join(flags[:2]) if flags else "rising dilution"
        return (
            f"{classification}. Elevated crowding ({flag_str}). "
            f"Size deposit under ~${max_deposit_for_floor_usd:,.0f}."
        )
    if risk_lbl == "HIGH":
        concern = ", ".join(flags[:2]) if flags else "dilution"
        return f"{classification}. High crowding risk ({concern}). Deposit small or wait."
    # SEVERE
    return f"{classification}. Severe dilution risk. Avoid or deposit minimally."


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(pools: list[dict], apy_floor_pct: float = _DEFAULT_APY_FLOOR_PCT) -> dict:
    """
    Assess yield-dilution / crowding risk for a list of pools.

    Parameters
    ----------
    pools : list[dict]
        Each dict per the module docstring's input keys.
    apy_floor_pct : float
        Minimum acceptable diluted APY used by _max_deposit_for_floor.

    Returns
    -------
    dict with keys: pools, most_crowd_resistant, highest_dilution_pool,
                    average_crowding_risk, count, apy_floor_pct, timestamp.
    """
    floor = float(apy_floor_pct)
    result_pools: list[dict] = []

    for p in pools:
        name: str = p.get("name", "")
        current_tvl: float = float(p.get("current_tvl_usd", 0.0))
        current_apy: float = float(p.get("current_apy_pct", 0.0))
        reward_apy: float = float(p.get("reward_apy_pct", 0.0))
        base_apy: float = float(p.get("base_apy_pct", 0.0))
        expected_inflow: float = float(p.get("expected_inflow_usd", 0.0))
        your_deposit: float = float(p.get("your_deposit_usd", 0.0))

        # If current_apy not given, derive from components.
        if current_apy == 0.0 and (reward_apy != 0.0 or base_apy != 0.0):
            current_apy = reward_apy + base_apy

        has_data = current_tvl > 0 and (reward_apy + base_apy) > 0

        added_tvl = max(0.0, your_deposit) + max(0.0, expected_inflow)

        diluted = _diluted_apy(reward_apy, base_apy, current_tvl, added_tvl)
        marginal = _marginal_apy_impact_pct(current_apy, diluted)
        reward_share = _reward_share_pct(reward_apy, base_apy)
        crowding = _crowding_risk_score(reward_share, current_tvl, added_tvl)
        risk_lbl = _risk_label(crowding)
        grade = _grade(crowding)
        classification = _classification(reward_share, crowding, current_tvl)
        max_dep = _max_deposit_for_floor(
            reward_apy, base_apy, current_tvl, expected_inflow, floor
        )
        flags = _build_flags(
            reward_share, current_tvl, added_tvl, marginal,
            current_apy, base_apy, has_data,
        )
        rec = _recommendation(risk_lbl, classification, max_dep, flags)

        result_pools.append(
            {
                "name": name,
                "current_tvl_usd": round(current_tvl, 2),
                "current_apy_pct": round(current_apy, 2),
                "diluted_apy_pct": round(diluted, 2),
                "marginal_apy_impact_pct": round(marginal, 2),
                "crowding_risk_score": crowding,
                "risk_label": risk_lbl,
                "grade": grade,
                "classification": classification,
                "reward_share_pct": round(reward_share, 1),
                "reward_share_label": _reward_share_label(reward_share),
                "max_deposit_for_floor_usd": round(max_dep, 2),
                "flags": flags,
                "recommendation": rec,
            }
        )

    # Summary
    most_crowd_resistant: str | None = None
    highest_dilution_pool: str | None = None
    if result_pools:
        most_crowd_resistant = min(
            result_pools, key=lambda x: x["crowding_risk_score"]
        )["name"]
        highest_dilution_pool = max(
            result_pools, key=lambda x: x["marginal_apy_impact_pct"]
        )["name"]

    avg_crowding = (
        sum(rp["crowding_risk_score"] for rp in result_pools) / len(result_pools)
        if result_pools
        else 0.0
    )

    return {
        "pools": result_pools,
        "most_crowd_resistant": most_crowd_resistant,
        "highest_dilution_pool": highest_dilution_pool,
        "average_crowding_risk": round(avg_crowding, 2),
        "count": len(result_pools),
        "apy_floor_pct": round(floor, 2),
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(data, str(path))
def _read_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, entry: dict) -> None:
    log = _read_log(path)
    log.append(entry)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_pools() -> list[dict]:
    return [
        {
            # Thin high-emission farm: small TVL, mostly reward APY → fragile.
            "name": "TurboFarm USDC",
            "current_tvl_usd": 400_000.0,
            "current_apy_pct": 85.0,
            "reward_apy_pct": 78.0,
            "base_apy_pct": 7.0,
            "expected_inflow_usd": 300_000.0,
            "your_deposit_usd": 100_000.0,
        },
        {
            # Deep stable lending pool: large TVL, fee-driven → crowd resistant.
            "name": "Aave USDC",
            "current_tvl_usd": 800_000_000.0,
            "current_apy_pct": 4.2,
            "reward_apy_pct": 0.5,
            "base_apy_pct": 3.7,
            "expected_inflow_usd": 5_000_000.0,
            "your_deposit_usd": 1_000_000.0,
        },
        {
            # Mid-size mixed pool: balanced reward/fee, moderate inflow.
            "name": "Curve TriCrypto",
            "current_tvl_usd": 25_000_000.0,
            "current_apy_pct": 18.0,
            "reward_apy_pct": 11.0,
            "base_apy_pct": 7.0,
            "expected_inflow_usd": 4_000_000.0,
            "your_deposit_usd": 500_000.0,
        },
        {
            # Negative-base distressed pool: emissions mask a fee drag.
            "name": "Distressed LP",
            "current_tvl_usd": 2_000_000.0,
            "current_apy_pct": 12.0,
            "reward_apy_pct": 14.0,
            "base_apy_pct": -2.0,
            "expected_inflow_usd": 1_000_000.0,
            "your_deposit_usd": 200_000.0,
        },
    ]


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-911 YieldDilutionAnalyzer — advisory analytics"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run on sample data, print results, do NOT write to disk (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run on sample data and append result to data/yield_dilution_log.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override directory for log file.",
    )
    args = parser.parse_args(argv)

    pools = _sample_pools()
    result = analyze(pools)

    print(json.dumps(result, indent=2))
    print(f"\n[MP-911] most_crowd_resistant  = {result['most_crowd_resistant']}")
    print(f"[MP-911] highest_dilution_pool = {result['highest_dilution_pool']}")
    print(f"[MP-911] average_crowding_risk = {result['average_crowding_risk']:.1f}")

    if args.run:
        if args.data_dir:
            log_path = os.path.join(args.data_dir, "yield_dilution_log.json")
        else:
            log_path = _DEFAULT_LOG_PATH
        _append_log(log_path, result)
        print(f"[MP-911] Appended to {log_path}")


if __name__ == "__main__":
    main()

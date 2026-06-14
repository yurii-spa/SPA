"""
MP-801: StakingAPYRanker
Ranks staking opportunities across protocols by risk-adjusted APY,
factoring in lock-up duration, slashing risk, and token inflation.

Pure stdlib only. Advisory/read-only. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap: 100 entries.
"""
from __future__ import annotations

import json
import math
import os
import time
import tempfile
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "staking_apy_ranking_log.json")

_RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Tier thresholds (risk_adjusted_apy %)
# ---------------------------------------------------------------------------
_TIER_S = 15.0
_TIER_A = 8.0
_TIER_B = 4.0
_TIER_C = 1.0

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_LOCK_PENALTY_PER_DAY = 0.01
_DEFAULT_SLASHING_WEIGHT = 2.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assign_tier(risk_adjusted_apy: float) -> str:
    """Return S/A/B/C/D tier based on risk-adjusted APY."""
    if risk_adjusted_apy >= _TIER_S:
        return "S"
    if risk_adjusted_apy >= _TIER_A:
        return "A"
    if risk_adjusted_apy >= _TIER_B:
        return "B"
    if risk_adjusted_apy >= _TIER_C:
        return "C"
    return "D"


def _round2(value: float) -> float:
    """Round to 2 decimal places."""
    return round(value, 2)


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path or ".", suffix=".tmp")
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


def _append_to_ring_buffer(path: str, entry: Any, cap: int = _RING_BUFFER_CAP) -> None:
    """Append entry to ring-buffer JSON file, keeping at most `cap` entries."""
    try:
        with open(path, "r") as f:
            existing: list = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing.append(entry)
    if len(existing) > cap:
        existing = existing[-cap:]

    _atomic_write_json(path, existing)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    staking_options: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    *,
    save: bool = False,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Rank staking opportunities by risk-adjusted APY.

    Parameters
    ----------
    staking_options : list of dicts with keys:
        protocol, token, base_apy, lock_days, slashing_risk_pct,
        token_inflation_pct, validator_count
    config : optional dict with:
        lock_penalty_per_day  (default 0.01)
        slashing_weight       (default 2.0)
    save : if True, append result to ring-buffer log file.
    data_dir : override directory for log file (useful in tests).

    Returns
    -------
    dict with rankings, top_pick, liquid_top_pick, summary, timestamp
    """
    cfg = config or {}
    lock_penalty_per_day: float = float(cfg.get("lock_penalty_per_day", _DEFAULT_LOCK_PENALTY_PER_DAY))
    slashing_weight: float = float(cfg.get("slashing_weight", _DEFAULT_SLASHING_WEIGHT))

    timestamp = time.time()

    # Edge case: empty list
    if not staking_options:
        result: Dict[str, Any] = {
            "rankings": [],
            "top_pick": None,
            "liquid_top_pick": None,
            "summary": {
                "avg_base_apy": 0.0,
                "avg_risk_adjusted_apy": 0.0,
                "options_count": 0,
            },
            "timestamp": timestamp,
        }
        if save:
            _log_path = os.path.join(data_dir or _DATA_DIR, "staking_apy_ranking_log.json")
            _append_to_ring_buffer(_log_path, result)
        return result

    ranked: List[Dict[str, Any]] = []
    sum_base_apy = 0.0
    sum_risk_apy = 0.0

    for opt in staking_options:
        protocol: str = str(opt.get("protocol", ""))
        token: str = str(opt.get("token", ""))
        base_apy: float = float(opt.get("base_apy", 0.0))
        lock_days: int = int(opt.get("lock_days", 0))
        slashing_risk_pct: float = float(opt.get("slashing_risk_pct", 0.0))
        token_inflation_pct: float = float(opt.get("token_inflation_pct", 0.0))
        validator_count: int = int(opt.get("validator_count", 0))

        # Derived metrics
        real_apy: float = base_apy - token_inflation_pct
        lock_penalty: float = lock_days * lock_penalty_per_day
        slashing_penalty: float = slashing_risk_pct * slashing_weight
        risk_adjusted_apy: float = max(0.0, real_apy - lock_penalty - slashing_penalty)
        decentralization_score: int = min(validator_count, 100)
        tier: str = _assign_tier(risk_adjusted_apy)

        sum_base_apy += base_apy
        sum_risk_apy += risk_adjusted_apy

        ranked.append({
            "rank": 0,  # assigned after sorting
            "protocol": protocol,
            "token": token,
            "base_apy": _round2(base_apy),
            "real_apy": _round2(real_apy),
            "lock_penalty": _round2(lock_penalty),
            "slashing_penalty": _round2(slashing_penalty),
            "risk_adjusted_apy": _round2(risk_adjusted_apy),
            "decentralization_score": decentralization_score,
            "tier": tier,
            # keep lock_days for liquid_top_pick filtering (not in output spec but needed)
            "_lock_days": lock_days,
        })

    # Sort descending by risk_adjusted_apy
    ranked.sort(key=lambda x: x["risk_adjusted_apy"], reverse=True)

    # Assign ranks and strip internal key
    for idx, item in enumerate(ranked, 1):
        item["rank"] = idx

    top_pick: Optional[str] = ranked[0]["protocol"] if ranked else None

    # liquid_top_pick: best with lock_days == 0
    liquid_candidates = [r for r in ranked if r["_lock_days"] == 0]
    liquid_top_pick: Optional[str] = liquid_candidates[0]["protocol"] if liquid_candidates else None

    n = len(staking_options)
    summary = {
        "avg_base_apy": _round2(sum_base_apy / n),
        "avg_risk_adjusted_apy": _round2(sum_risk_apy / n),
        "options_count": n,
    }

    # Remove internal key from output
    clean_ranked = []
    for item in ranked:
        clean = {k: v for k, v in item.items() if not k.startswith("_")}
        clean_ranked.append(clean)

    result = {
        "rankings": clean_ranked,
        "top_pick": top_pick,
        "liquid_top_pick": liquid_top_pick,
        "summary": summary,
        "timestamp": timestamp,
    }

    if save:
        _log_path = os.path.join(data_dir or _DATA_DIR, "staking_apy_ranking_log.json")
        _append_to_ring_buffer(_log_path, result)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_options() -> List[Dict[str, Any]]:
    return [
        {
            "protocol": "Lido",
            "token": "stETH",
            "base_apy": 4.5,
            "lock_days": 0,
            "slashing_risk_pct": 0.5,
            "token_inflation_pct": 0.0,
            "validator_count": 300000,
        },
        {
            "protocol": "RocketPool",
            "token": "rETH",
            "base_apy": 3.8,
            "lock_days": 0,
            "slashing_risk_pct": 0.3,
            "token_inflation_pct": 0.0,
            "validator_count": 3000,
        },
        {
            "protocol": "Cosmos",
            "token": "ATOM",
            "base_apy": 19.0,
            "lock_days": 21,
            "slashing_risk_pct": 1.0,
            "token_inflation_pct": 7.0,
            "validator_count": 150,
        },
        {
            "protocol": "Ethereum",
            "token": "ETH",
            "base_apy": 4.2,
            "lock_days": 0,
            "slashing_risk_pct": 0.2,
            "token_inflation_pct": 0.0,
            "validator_count": 800000,
        },
        {
            "protocol": "Polkadot",
            "token": "DOT",
            "base_apy": 14.0,
            "lock_days": 28,
            "slashing_risk_pct": 2.0,
            "token_inflation_pct": 5.0,
            "validator_count": 297,
        },
    ]


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="MP-801 StakingAPYRanker")
    parser.add_argument("--run", action="store_true", help="Compute and save to log")
    parser.add_argument("--check", action="store_true", help="Compute only, no save (default)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    save_flag = args.run and not args.check
    options = _sample_options()
    result = analyze(options, save=save_flag, data_dir=args.data_dir)

    print(json.dumps(result, indent=2))
    if save_flag:
        print(f"\n[MP-801] Logged to staking_apy_ranking_log.json", file=sys.stderr)
    sys.exit(0)

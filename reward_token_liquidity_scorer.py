"""
MP-817 RewardTokenLiquidityScorer
Scores how easily harvested reward tokens can be sold back to stables without excessive
slippage — i.e. the exit-liquidity quality of the reward token. Helps decide whether
emission yield is actually realizable.

Advisory/read-only module. Pure stdlib. Atomic writes via tmp + os.replace.
Data: data/reward_token_liquidity_log.json (ring-buffer 100)
"""

import json
import math
import os
import time
import tempfile

_DEFAULT_CONFIG = {
    "grade_a_threshold": 80.0,    # composite >= this → A
    "grade_b_threshold": 60.0,    # composite >= this → B
    "grade_c_threshold": 40.0,    # composite >= this → C
    "grade_d_threshold": 20.0,    # composite >= this → D (else F)
    "thin_liquidity_usd": 100000.0,  # token_liquidity_usd < this → thin-liquidity flag
}

_LOG_RING_SIZE = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "reward_token_liquidity_log.json"
)


def _liquidity_score(token_liquidity_usd: float) -> float:
    """Log-scale 0-100 score: $10k → 0, $100M → 100, clamped."""
    safe_liq = max(token_liquidity_usd, 1.0)
    raw = (math.log10(safe_liq) - 4.0) * 25.0
    return max(0.0, min(100.0, raw))


def _volume_subscore(volume_ratio: float) -> float:
    """0-100 sub-score from how many times daily sell pressure the market absorbs.
    ratio>=20 → 100, ratio<=1 → ~0, log-scaled in between."""
    if volume_ratio <= 1.0:
        return max(0.0, volume_ratio * 0.0)  # at/below 1x absorption → 0
    raw = (math.log10(volume_ratio) / math.log10(20.0)) * 100.0
    return max(0.0, min(100.0, raw))


def _depth_subscore(depth_ratio: float) -> float:
    """0-100 sub-score from liquidity depth vs daily emissions.
    depth>=1000x → 100, depth<=10x → ~0, log-scaled in between."""
    if depth_ratio <= 10.0:
        return 0.0
    raw = ((math.log10(depth_ratio) - 1.0) / (3.0 - 1.0)) * 100.0
    return max(0.0, min(100.0, raw))


def _liquidity_grade(
    composite: float,
    grade_a_threshold: float,
    grade_b_threshold: float,
    grade_c_threshold: float,
    grade_d_threshold: float,
) -> str:
    """Return letter grade from composite score."""
    if composite >= grade_a_threshold:
        return "A"
    if composite >= grade_b_threshold:
        return "B"
    if composite >= grade_c_threshold:
        return "C"
    if composite >= grade_d_threshold:
        return "D"
    return "F"


def _exit_feasibility(sell_pressure_pct: float, liquidity_score: float) -> str:
    """Classify how easy it is to exit the reward token position."""
    if sell_pressure_pct < 5.0 and liquidity_score >= 60.0:
        return "EASY"
    if sell_pressure_pct < 20.0:
        return "MODERATE"
    if sell_pressure_pct < 50.0:
        return "DIFFICULT"
    return "ILLIQUID"


def _compute_risk_flags(
    sell_pressure_pct: float,
    token_liquidity_usd: float,
    daily_emission_usd: float,
    market_cap_usd: float,
    thin_liquidity_usd: float,
) -> list:
    """Return list of risk flag strings."""
    flags = []

    if sell_pressure_pct > 20.0:
        flags.append("Daily emissions large vs market volume")

    if token_liquidity_usd < thin_liquidity_usd:
        flags.append("Thin reward-token liquidity")

    if market_cap_usd > 0.0 and (daily_emission_usd / market_cap_usd) * 100.0 > 1.0:
        flags.append("High inflation vs market cap")

    return flags


def _recommendation(exit_feasibility: str) -> str:
    """Map exit feasibility to human-readable recommendation."""
    return {
        "EASY": "Favorable — rewards can be sold to stables with minimal slippage",
        "MODERATE": "Acceptable — exit liquidity adequate, sell in measured tranches",
        "DIFFICULT": "Caution — emissions strain market depth, expect slippage on exit",
        "ILLIQUID": "Avoid — reward token cannot be exited at scale, emission yield not realizable",
    }[exit_feasibility]


def score(protocol: str, params: dict, config: dict = None) -> dict:
    """
    Score exit-liquidity quality of a protocol's reward token.

    Parameters
    ----------
    protocol : str
        Protocol name (e.g. "GMX").
    params : dict
        {
            "reward_token": str,
            "token_liquidity_usd": float,    # on-chain DEX liquidity depth
            "daily_volume_usd": float,       # 24h trading volume
            "daily_emission_usd": float,     # USD of rewards emitted per day to sell
            "market_cap_usd": float          # optional, default 0
        }
    config : dict, optional
        Overrides for _DEFAULT_CONFIG thresholds.

    Returns
    -------
    dict with keys:
        protocol, reward_token, token_liquidity_usd, daily_volume_usd,
        daily_emission_usd, market_cap_usd, liquidity_score, volume_ratio,
        sell_pressure_pct, depth_ratio, volume_subscore, depth_subscore,
        composite_score, liquidity_grade, exit_feasibility, risk_flags,
        recommendation, timestamp
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    grade_a_threshold = float(cfg.get("grade_a_threshold", _DEFAULT_CONFIG["grade_a_threshold"]))
    grade_b_threshold = float(cfg.get("grade_b_threshold", _DEFAULT_CONFIG["grade_b_threshold"]))
    grade_c_threshold = float(cfg.get("grade_c_threshold", _DEFAULT_CONFIG["grade_c_threshold"]))
    grade_d_threshold = float(cfg.get("grade_d_threshold", _DEFAULT_CONFIG["grade_d_threshold"]))
    thin_liquidity_usd = float(cfg.get("thin_liquidity_usd", _DEFAULT_CONFIG["thin_liquidity_usd"]))

    reward_token = str(params.get("reward_token", ""))
    token_liquidity_usd = float(params.get("token_liquidity_usd", 0.0))
    daily_volume_usd = float(params.get("daily_volume_usd", 0.0))
    daily_emission_usd = float(params.get("daily_emission_usd", 0.0))
    market_cap_usd = float(params.get("market_cap_usd", 0.0))

    # Core ratios (all divisions guarded)
    liquidity_score = _liquidity_score(token_liquidity_usd)
    volume_ratio = daily_volume_usd / max(daily_emission_usd, 1e-9)
    sell_pressure_pct = daily_emission_usd / max(daily_volume_usd, 1e-9) * 100.0
    depth_ratio = token_liquidity_usd / max(daily_emission_usd, 1e-9)

    volume_subscore = _volume_subscore(volume_ratio)
    depth_subscore = _depth_subscore(depth_ratio)

    composite_score = (
        liquidity_score * 0.5
        + volume_subscore * 0.3
        + depth_subscore * 0.2
    )

    liquidity_grade = _liquidity_grade(
        composite_score,
        grade_a_threshold,
        grade_b_threshold,
        grade_c_threshold,
        grade_d_threshold,
    )

    exit_feasibility = _exit_feasibility(sell_pressure_pct, liquidity_score)

    risk_flags = _compute_risk_flags(
        sell_pressure_pct,
        token_liquidity_usd,
        daily_emission_usd,
        market_cap_usd,
        thin_liquidity_usd,
    )

    result = {
        "protocol": protocol,
        "reward_token": reward_token,
        "token_liquidity_usd": token_liquidity_usd,
        "daily_volume_usd": daily_volume_usd,
        "daily_emission_usd": daily_emission_usd,
        "market_cap_usd": market_cap_usd,
        "liquidity_score": liquidity_score,
        "volume_ratio": volume_ratio,
        "sell_pressure_pct": sell_pressure_pct,
        "depth_ratio": depth_ratio,
        "volume_subscore": volume_subscore,
        "depth_subscore": depth_subscore,
        "composite_score": composite_score,
        "liquidity_grade": liquidity_grade,
        "exit_feasibility": exit_feasibility,
        "risk_flags": risk_flags,
        "recommendation": _recommendation(exit_feasibility),
        "timestamp": time.time(),
    }

    return result


def log_result(result: dict, log_path: str = None) -> None:
    """Append result to ring-buffer JSON log (max 100 entries). Atomic write."""
    if log_path is None:
        log_path = _DEFAULT_LOG_PATH

    # Load existing log
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(result)

    # Ring-buffer cap
    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    # Atomic write
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=log_dir or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def score_and_log(protocol: str, params: dict, config: dict = None, log_path: str = None) -> dict:
    """score() + log_result(). Returns the result dict."""
    result = score(protocol, params, config)
    log_result(result, log_path)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    _example_params = {
        "reward_token": "ARB",
        "token_liquidity_usd": 25_000_000.0,
        "daily_volume_usd": 80_000_000.0,
        "daily_emission_usd": 500_000.0,
        "market_cap_usd": 2_000_000_000.0,
    }

    result = score("Radiant V2", _example_params)
    json.dump(result, sys.stdout, indent=2)
    print()

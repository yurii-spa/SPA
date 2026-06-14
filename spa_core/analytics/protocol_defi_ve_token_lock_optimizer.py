"""
MP-1099  ProtocolDeFiVeTokenLockOptimizer
==========================================
Advisory-only module. Optimizes veToken lock duration (Curve/Convex/Balancer
style). Longer lock = more voting power + higher yield boost, but less
liquidity. Calculates optimal lock period given user's time horizon and yield
targets.

Pure Python stdlib only — no external dependencies.
Atomic writes: tmp-file + os.replace().
Advisory read-only: never modifies allocator / risk / execution.
Ring-buffer log capped at 100 entries.
"""

import json
import os
import tempfile
import time
from typing import Any, Optional

# ── Data file ────────────────────────────────────────────────────────────────

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DATA_FILE = os.path.normpath(
    os.path.join(
        _MODULE_DIR, "..", "..", "data", "ve_token_lock_optimizer_log.json"
    )
)
_LOG_CAP = 100

# ── Label constants ───────────────────────────────────────────────────────────

LABEL_OPTIMAL_LOCK = "OPTIMAL_LOCK"
LABEL_GOOD_LOCK = "GOOD_LOCK"
LABEL_SHORT_LOCK = "SHORT_LOCK"
LABEL_OVER_LOCKED = "OVER_LOCKED"
LABEL_LOCK_NOT_RECOMMENDED = "LOCK_NOT_RECOMMENDED"

# ── I/O helpers ──────────────────────────────────────────────────────────────


def _atomic_write(path: str, obj: Any) -> None:
    """Write *obj* as JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_velock_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    """Load ring-buffer log from *path*. Returns [] on any error."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, record: dict) -> None:
    """Append *record* to ring-buffer log at *path* (cap: _LOG_CAP)."""
    entries = _load_log(path)
    entries.append(record)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]
    _atomic_write(path, entries)


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_inputs(
    token_amount: float,
    max_lock_weeks: int,
    candidate_lock_weeks: int,
    base_apy_pct: float,
    max_boost_multiplier: float,
    token_price_usd: float,
    weekly_rewards_usd: float,
    total_ve_supply: float,
    user_time_horizon_weeks: int,
    protocol_name: str,
) -> None:
    """Validate all inputs. Raises ValueError on bad values."""
    if not isinstance(protocol_name, str) or not protocol_name.strip():
        raise ValueError("protocol_name must be a non-empty string")
    if token_amount < 0:
        raise ValueError(f"token_amount must be >= 0, got {token_amount}")
    if not isinstance(max_lock_weeks, int) or max_lock_weeks <= 0:
        raise ValueError(f"max_lock_weeks must be a positive int, got {max_lock_weeks}")
    if not isinstance(candidate_lock_weeks, int) or candidate_lock_weeks < 0:
        raise ValueError(
            f"candidate_lock_weeks must be a non-negative int, got {candidate_lock_weeks}"
        )
    if candidate_lock_weeks > max_lock_weeks:
        raise ValueError(
            f"candidate_lock_weeks ({candidate_lock_weeks}) cannot exceed "
            f"max_lock_weeks ({max_lock_weeks})"
        )
    if base_apy_pct < 0:
        raise ValueError(f"base_apy_pct must be >= 0, got {base_apy_pct}")
    if max_boost_multiplier < 1.0:
        raise ValueError(
            f"max_boost_multiplier must be >= 1.0, got {max_boost_multiplier}"
        )
    if token_price_usd < 0:
        raise ValueError(f"token_price_usd must be >= 0, got {token_price_usd}")
    if weekly_rewards_usd < 0:
        raise ValueError(
            f"weekly_rewards_usd must be >= 0, got {weekly_rewards_usd}"
        )
    if total_ve_supply < 0:
        raise ValueError(f"total_ve_supply must be >= 0, got {total_ve_supply}")
    if not isinstance(user_time_horizon_weeks, int) or user_time_horizon_weeks < 0:
        raise ValueError(
            f"user_time_horizon_weeks must be a non-negative int, got {user_time_horizon_weeks}"
        )


# ── Core computation helpers ─────────────────────────────────────────────────


def _compute_ve_tokens_received(
    token_amount: float,
    candidate_lock_weeks: int,
    max_lock_weeks: int,
) -> float:
    """
    Linear veToken model: ve_tokens = token_amount * candidate_lock / max_lock.
    Returns 0.0 if max_lock_weeks is zero (safety guard).
    """
    if max_lock_weeks == 0:
        return 0.0
    return token_amount * (candidate_lock_weeks / max_lock_weeks)


def _compute_boost_multiplier(
    max_boost_multiplier: float,
    candidate_lock_weeks: int,
    max_lock_weeks: int,
) -> float:
    """
    Boost multiplier at candidate lock duration.

    boost = 1 + (max_boost - 1) * candidate_lock / max_lock

    At max lock → max_boost_multiplier.
    At zero lock → 1.0 (no boost).
    """
    if max_lock_weeks == 0:
        return 1.0
    return 1.0 + (max_boost_multiplier - 1.0) * (
        candidate_lock_weeks / max_lock_weeks
    )


def _compute_boosted_apy_pct(
    base_apy_pct: float, boost_multiplier: float
) -> float:
    """boosted_apy = base_apy * boost_multiplier."""
    return base_apy_pct * boost_multiplier


def _compute_vote_power_share_pct(
    ve_tokens_received: float, total_ve_supply: float
) -> float:
    """
    User's share of total voting power after their lock.

    share = ve_tokens / (total_ve_supply + ve_tokens) * 100

    Returns 0.0 if both are zero.
    """
    denom = total_ve_supply + ve_tokens_received
    if denom == 0.0:
        return 0.0
    return (ve_tokens_received / denom) * 100.0


def _compute_break_even_weeks(
    token_amount: float,
    token_price_usd: float,
    base_apy_pct: float,
    boosted_apy_pct: float,
) -> Optional[float]:
    """
    Weeks to recover the opportunity cost of locking (illiquidity premium).

    The opportunity cost is approximated as the yield difference between
    the boosted position and holding tokens without any lock (base APY).

    Incremental weekly yield = token_value * (boosted_apy - base_apy) / 100 / 52

    Break-even = lock duration offset by capital at stake / incremental weekly yield.

    Returns None if any required input is zero or undefined (division by zero).
    """
    if token_price_usd <= 0 or token_amount <= 0:
        return None
    token_value = token_amount * token_price_usd
    apy_diff = boosted_apy_pct - base_apy_pct
    if apy_diff <= 0:
        # No incremental yield → lock doesn't pay off (return sentinel)
        return None
    incremental_weekly = token_value * (apy_diff / 100.0) / 52.0
    if incremental_weekly <= 0:
        return None
    # Break-even: how many weeks until the extra yield covers the illiquidity cost?
    # We model illiquidity cost as missing base yield for the lock period.
    # Cost = token_value * base_apy_pct/100 * candidate_lock / 52
    # But in this simpler model we define break-even as: how many weeks of
    # incremental yield equal one year's base yield?
    annual_base = token_value * base_apy_pct / 100.0
    if annual_base <= 0:
        # If base APY is 0, any boost pays off immediately
        return 0.0
    be_weeks = annual_base / incremental_weekly
    return round(be_weeks, 4)


def _compute_lock_efficiency_score(
    candidate_lock_weeks: int,
    max_lock_weeks: int,
    user_time_horizon_weeks: int,
    boost_multiplier: float,
    max_boost_multiplier: float,
    ve_tokens_received: float,
    total_ve_supply: float,
) -> int:
    """
    Lock efficiency score (0–100).

    Components:
    1. Lock duration ratio (0–40): candidate/max * 40 — longer = better
    2. Horizon alignment (0–30): min(candidate, horizon)/max(candidate, horizon)*30
       — penalises over-lock and under-use relative to horizon
    3. Boost utilisation (0–20): (boost-1)/(max_boost-1)*20 if max_boost>1
    4. Vote power capture (0–10): proportional to vote_power_share (capped at 5%)
    """
    # Component 1: lock duration ratio
    lock_ratio = candidate_lock_weeks / max_lock_weeks if max_lock_weeks > 0 else 0.0
    c1 = lock_ratio * 40.0

    # Component 2: horizon alignment
    if candidate_lock_weeks == 0 or user_time_horizon_weeks == 0:
        c2 = 0.0
    else:
        alignment = min(candidate_lock_weeks, user_time_horizon_weeks) / max(
            candidate_lock_weeks, user_time_horizon_weeks
        )
        c2 = alignment * 30.0

    # Component 3: boost utilisation
    boost_range = max_boost_multiplier - 1.0
    if boost_range <= 0:
        c3 = 20.0  # nothing to optimise; max credit
    else:
        c3 = ((boost_multiplier - 1.0) / boost_range) * 20.0

    # Component 4: vote power capture (capped at 5% share = full 10 pts)
    vote_share = _compute_vote_power_share_pct(ve_tokens_received, total_ve_supply)
    c4 = min(10.0, (vote_share / 5.0) * 10.0)

    raw = c1 + c2 + c3 + c4
    return int(round(max(0.0, min(100.0, raw))))


def _compute_lock_label(
    candidate_lock_weeks: int,
    max_lock_weeks: int,
    user_time_horizon_weeks: int,
    token_price_usd: float,
    base_apy_pct: float,
) -> str:
    """
    Determine the lock recommendation label.

    Priority order (first match wins):
    1. token_price_usd == 0 OR base_apy_pct == 0 → LOCK_NOT_RECOMMENDED
    2. candidate_lock > user_time_horizon * 1.5  → OVER_LOCKED
    3. candidate_lock < max_lock * 0.25          → SHORT_LOCK
    4. candidate_lock >= max_lock * 0.75 AND
       user_time_horizon >= candidate_lock        → OPTIMAL_LOCK
    5. candidate_lock >= max_lock * 0.5 AND
       user_time_horizon >= candidate_lock        → GOOD_LOCK
    6. Otherwise                                  → SHORT_LOCK
    """
    if token_price_usd == 0 or base_apy_pct == 0:
        return LABEL_LOCK_NOT_RECOMMENDED
    if candidate_lock_weeks > user_time_horizon_weeks * 1.5:
        return LABEL_OVER_LOCKED
    if candidate_lock_weeks < max_lock_weeks * 0.25:
        return LABEL_SHORT_LOCK
    if candidate_lock_weeks >= max_lock_weeks * 0.75 and user_time_horizon_weeks >= candidate_lock_weeks:
        return LABEL_OPTIMAL_LOCK
    if candidate_lock_weeks >= max_lock_weeks * 0.5 and user_time_horizon_weeks >= candidate_lock_weeks:
        return LABEL_GOOD_LOCK
    return LABEL_SHORT_LOCK


def _optimize(
    token_amount: float,
    max_lock_weeks: int,
    candidate_lock_weeks: int,
    base_apy_pct: float,
    max_boost_multiplier: float,
    token_price_usd: float,
    weekly_rewards_usd: float,
    total_ve_supply: float,
    user_time_horizon_weeks: int,
    protocol_name: str,
) -> dict:
    """Core computation — validates and computes all output fields."""
    _validate_inputs(
        token_amount=token_amount,
        max_lock_weeks=max_lock_weeks,
        candidate_lock_weeks=candidate_lock_weeks,
        base_apy_pct=base_apy_pct,
        max_boost_multiplier=max_boost_multiplier,
        token_price_usd=token_price_usd,
        weekly_rewards_usd=weekly_rewards_usd,
        total_ve_supply=total_ve_supply,
        user_time_horizon_weeks=user_time_horizon_weeks,
        protocol_name=protocol_name,
    )

    ve_tokens = _compute_ve_tokens_received(
        token_amount, candidate_lock_weeks, max_lock_weeks
    )
    boost = _compute_boost_multiplier(
        max_boost_multiplier, candidate_lock_weeks, max_lock_weeks
    )
    boosted_apy = _compute_boosted_apy_pct(base_apy_pct, boost)
    vote_share = _compute_vote_power_share_pct(ve_tokens, total_ve_supply)
    break_even = _compute_break_even_weeks(
        token_amount, token_price_usd, base_apy_pct, boosted_apy
    )
    score = _compute_lock_efficiency_score(
        candidate_lock_weeks,
        max_lock_weeks,
        user_time_horizon_weeks,
        boost,
        max_boost_multiplier,
        ve_tokens,
        total_ve_supply,
    )
    label = _compute_lock_label(
        candidate_lock_weeks,
        max_lock_weeks,
        user_time_horizon_weeks,
        token_price_usd,
        base_apy_pct,
    )

    return {
        "protocol_name": protocol_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Inputs echoed
        "token_amount": token_amount,
        "max_lock_weeks": max_lock_weeks,
        "candidate_lock_weeks": candidate_lock_weeks,
        "base_apy_pct": base_apy_pct,
        "max_boost_multiplier": max_boost_multiplier,
        "token_price_usd": token_price_usd,
        "weekly_rewards_usd": weekly_rewards_usd,
        "total_ve_supply": total_ve_supply,
        "user_time_horizon_weeks": user_time_horizon_weeks,
        # Outputs
        "ve_tokens_received": round(ve_tokens, 8),
        "boost_multiplier": round(boost, 8),
        "boosted_apy_pct": round(boosted_apy, 8),
        "vote_power_share_pct": round(vote_share, 8),
        "break_even_weeks": break_even,
        "lock_efficiency_score": score,
        "lock_label": label,
    }


# ── Main class ────────────────────────────────────────────────────────────────


class ProtocolDeFiVeTokenLockOptimizer:
    """
    Optimizes veToken lock duration (Curve/Convex/Balancer style).

    Longer lock = more voting power + higher yield boost, but less liquidity.
    Calculates optimal lock period given user's time horizon and yield targets.

    Usage
    -----
    ::
        opt = ProtocolDeFiVeTokenLockOptimizer()
        result = opt.optimize(
            token_amount=10_000.0,
            max_lock_weeks=208,       # 4 years = Curve max
            candidate_lock_weeks=104, # 2 years
            base_apy_pct=5.0,
            max_boost_multiplier=2.5,
            token_price_usd=1.0,
            weekly_rewards_usd=100_000.0,
            total_ve_supply=50_000_000.0,
            user_time_horizon_weeks=104,
            protocol_name="Curve",
        )

    Outputs
    -------
    - ``ve_tokens_received`` (float): candidate_lock/max_lock * token_amount
    - ``boost_multiplier`` (float): 1 + (max_boost-1) * candidate_lock/max_lock
    - ``boosted_apy_pct`` (float): base_apy * boost_multiplier
    - ``vote_power_share_pct`` (float): ve_tokens/(total_ve+ve_tokens)*100
    - ``break_even_weeks`` (float|None): weeks to recover opportunity cost
    - ``lock_efficiency_score`` (int 0–100)
    - ``lock_label`` (str): OPTIMAL_LOCK / GOOD_LOCK / SHORT_LOCK /
      OVER_LOCKED / LOCK_NOT_RECOMMENDED

    Log file
    --------
    Each call appends to ring-buffer JSON log (cap: 100 entries) at
    ``data/ve_token_lock_optimizer_log.json``.
    """

    def __init__(self, data_file: str = _DEFAULT_DATA_FILE) -> None:
        self.data_file = data_file

    def optimize(
        self,
        token_amount: float,
        max_lock_weeks: int,
        candidate_lock_weeks: int,
        base_apy_pct: float,
        max_boost_multiplier: float,
        token_price_usd: float,
        weekly_rewards_usd: float,
        total_ve_supply: float,
        user_time_horizon_weeks: int,
        protocol_name: str,
        *,
        write_log: bool = True,
    ) -> dict:
        """
        Optimize a veToken lock configuration.

        Parameters
        ----------
        token_amount : float
            Number of tokens to lock (>= 0).
        max_lock_weeks : int
            Protocol maximum lock duration in weeks (e.g. 208 for 4 years).
        candidate_lock_weeks : int
            User's proposed lock period in weeks (0 <= x <= max_lock_weeks).
        base_apy_pct : float
            Base yield without any boost (>= 0).
        max_boost_multiplier : float
            Maximum boost at max lock (e.g. 2.5 for Curve; >= 1.0).
        token_price_usd : float
            Current token price in USD (>= 0).
        weekly_rewards_usd : float
            Protocol weekly reward pool in USD (>= 0).
        total_ve_supply : float
            Current total veTokens outstanding (>= 0).
        user_time_horizon_weeks : int
            How long the user plans to hold (>= 0).
        protocol_name : str
            Protocol name (non-empty string).
        write_log : bool
            If True (default), append result to ring-buffer log.

        Returns
        -------
        dict
            All inputs echoed plus computed outputs.

        Raises
        ------
        ValueError
            On invalid inputs.
        """
        result = _optimize(
            token_amount=token_amount,
            max_lock_weeks=max_lock_weeks,
            candidate_lock_weeks=candidate_lock_weeks,
            base_apy_pct=base_apy_pct,
            max_boost_multiplier=max_boost_multiplier,
            token_price_usd=token_price_usd,
            weekly_rewards_usd=weekly_rewards_usd,
            total_ve_supply=total_ve_supply,
            user_time_horizon_weeks=user_time_horizon_weeks,
            protocol_name=protocol_name,
        )
        if write_log:
            _append_log(self.data_file, result)
        return result

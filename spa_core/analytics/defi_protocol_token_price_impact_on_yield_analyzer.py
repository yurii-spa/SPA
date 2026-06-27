"""
MP-1108: DeFi Protocol Token Price Impact on Yield Analyzer
============================================================
Analyzes how changes in reward token price affect effective USD yield.
When reward tokens drop in price, nominal APY collapses even if emission
rates stay constant.

Pure stdlib, no external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer log capped at 100 entries.
"""

import json
import os
from typing import Any, Dict
from spa_core.utils import clock

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_LOG_PATH: str = "data/token_price_impact_on_yield_log.json"
LOG_CAP: int = 100

VALID_LABELS = frozenset(
    {
        "PRICE_RESILIENT",
        "MILD_IMPACT",
        "MODERATE_IMPACT",
        "HIGH_IMPACT",
        "APY_DESTROYED",
    }
)

# Label boundary constants
_RESILIENT_THRESHOLD = 0.30   # token_apy < 30% of total → PRICE_RESILIENT
_MILD_MAX_RATIO = 0.50        # token_apy 30-50% of total (upper bound)
_MILD_MAX_CHANGE = 20.0       # |price_change| < 20% for MILD_IMPACT
_MODERATE_MIN_CHANGE = 20.0   # |price_change| >= 20% → MODERATE at minimum
_HIGH_MIN_CHANGE = 40.0       # |price_change| >= 40% → HIGH_IMPACT
_DESTROYED_MIN_CHANGE = 70.0  # |price_change| > 70% → APY_DESTROYED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a value into [lo, hi]."""
    return max(lo, min(hi, value))


def _atomic_write(path: str, data: Any) -> None:
    """Write *data* to *path* atomically via a temp file + os.replace."""
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DeFiProtocolTokenPriceImpactOnYieldAnalyzer:
    """
    Analyzes how a change in reward-token price impacts effective USD yield.

    Key metrics
    -----------
    token_apy_current_pct  = emission_per_day * price_current * 365 / tvl * 100
    token_apy_30d_ago_pct  = emission_per_day * price_30d     * 365 / tvl * 100
    token_price_change_pct = (price_current - price_30d) / price_30d * 100
    apy_impact_pct         = token_apy_current - token_apy_30d_ago
    total_apy_current_pct  = base_apy + token_apy_current
    daily_yield_usd        = position * total_apy / 365 / 100
    price_sensitivity_score (0-100): fraction of total APY from token reward
    price_impact_label     : PRICE_RESILIENT / MILD_IMPACT / MODERATE_IMPACT
                             / HIGH_IMPACT / APY_DESTROYED
    """

    def __init__(
        self,
        log_path: str = DEFAULT_LOG_PATH,
        log_cap: int = LOG_CAP,
    ) -> None:
        self.log_path = log_path
        self.log_cap = log_cap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        reward_token_emission_per_day: float,
        reward_token_current_price_usd: float,
        reward_token_price_30d_ago_usd: float,
        pool_tvl_usd: float,
        base_protocol_apy_pct: float,
        position_size_usd: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Run the analysis and return a result dict (no I/O side-effects).

        Raises
        ------
        ValueError
            If any required numeric input is out of valid range.
        TypeError
            If *protocol_name* is not a string.
        """
        # --- Validate inputs ---
        if not isinstance(protocol_name, str):
            raise TypeError("protocol_name must be a str")
        if pool_tvl_usd <= 0:
            raise ValueError("pool_tvl_usd must be > 0")
        if reward_token_price_30d_ago_usd <= 0:
            raise ValueError("reward_token_price_30d_ago_usd must be > 0")
        if reward_token_emission_per_day < 0:
            raise ValueError("reward_token_emission_per_day must be >= 0")
        if reward_token_current_price_usd < 0:
            raise ValueError("reward_token_current_price_usd must be >= 0")
        if position_size_usd < 0:
            raise ValueError("position_size_usd must be >= 0")

        # --- Token APY ---
        token_apy_current_pct: float = (
            reward_token_emission_per_day
            * reward_token_current_price_usd
            * 365
            / pool_tvl_usd
            * 100
        )
        token_apy_30d_ago_pct: float = (
            reward_token_emission_per_day
            * reward_token_price_30d_ago_usd
            * 365
            / pool_tvl_usd
            * 100
        )

        # --- Price change ---
        token_price_change_pct: float = (
            (reward_token_current_price_usd - reward_token_price_30d_ago_usd)
            / reward_token_price_30d_ago_usd
            * 100
        )

        # --- APY impact ---
        apy_impact_pct: float = token_apy_current_pct - token_apy_30d_ago_pct

        # --- Total APY ---
        total_apy_current_pct: float = base_protocol_apy_pct + token_apy_current_pct

        # --- Daily yield ---
        daily_yield_usd: float = position_size_usd * total_apy_current_pct / 365 / 100

        # --- Sensitivity score ---
        price_sensitivity_score: int = self._compute_sensitivity_score(
            token_apy_current_pct, total_apy_current_pct
        )

        # --- Label ---
        price_impact_label: str = self._compute_label(
            token_apy_current_pct=token_apy_current_pct,
            token_apy_30d_ago_pct=token_apy_30d_ago_pct,
            base_protocol_apy_pct=base_protocol_apy_pct,
            token_price_change_pct=token_price_change_pct,
        )

        return {
            "protocol_name": protocol_name,
            "token_apy_current_pct": round(token_apy_current_pct, 6),
            "token_apy_30d_ago_pct": round(token_apy_30d_ago_pct, 6),
            "token_price_change_pct": round(token_price_change_pct, 6),
            "apy_impact_pct": round(apy_impact_pct, 6),
            "total_apy_current_pct": round(total_apy_current_pct, 6),
            "daily_yield_usd": round(daily_yield_usd, 6),
            "price_sensitivity_score": price_sensitivity_score,
            "price_impact_label": price_impact_label,
            "timestamp": clock.utcnow().isoformat() + "Z",
        }

    def analyze_and_log(
        self,
        reward_token_emission_per_day: float,
        reward_token_current_price_usd: float,
        reward_token_price_30d_ago_usd: float,
        pool_tvl_usd: float,
        base_protocol_apy_pct: float,
        position_size_usd: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Analyze and append the result to the ring-buffer log (capped at
        ``self.log_cap`` entries). Writes atomically.
        """
        result = self.analyze(
            reward_token_emission_per_day=reward_token_emission_per_day,
            reward_token_current_price_usd=reward_token_current_price_usd,
            reward_token_price_30d_ago_usd=reward_token_price_30d_ago_usd,
            pool_tvl_usd=pool_tvl_usd,
            base_protocol_apy_pct=base_protocol_apy_pct,
            position_size_usd=position_size_usd,
            protocol_name=protocol_name,
        )

        log: list = []
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path) as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(result)
        if len(log) > self.log_cap:
            log = log[-self.log_cap :]

        _atomic_write(self.log_path, log)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_sensitivity_score(
        self,
        token_apy_current_pct: float,
        total_apy_current_pct: float,
    ) -> int:
        """
        Price sensitivity score (0–100).

        Measures what fraction of the total current APY is attributable to
        token-price-driven reward yield. 0 = fully base yield, 100 = all
        yield is token-price-dependent.
        """
        if total_apy_current_pct <= 0:
            if token_apy_current_pct > 0:
                return 100
            return 0
        token_fraction = token_apy_current_pct / total_apy_current_pct
        return int(_clamp(token_fraction * 100))

    def _compute_label(
        self,
        token_apy_current_pct: float,
        token_apy_30d_ago_pct: float,
        base_protocol_apy_pct: float,
        token_price_change_pct: float,
    ) -> str:
        """
        Determine the price-impact label.

        Uses the **30-day-ago** token fraction to classify a pool's original
        exposure, so that a severe token crash cannot retroactively make the
        pool look "resilient" just because the token APY is now tiny.

        Decision tree
        -------------
        1. token_apy_current <= 0                            → APY_DESTROYED
        2. token_ratio_30d < 30% of total_30d                → PRICE_RESILIENT
        3. |price_change| > 70%                              → APY_DESTROYED
        4. token_ratio_30d in [30%, 50%] AND |change| < 20% → MILD_IMPACT
        5. |price_change| >= 40%                             → HIGH_IMPACT
        6. |price_change| >= 20%                             → MODERATE_IMPACT
        7. (any remaining: token dominates, small change)    → MILD_IMPACT
        """
        abs_change = abs(token_price_change_pct)

        # Rule 1: token yield completely wiped out
        if token_apy_current_pct <= 0:
            return "APY_DESTROYED"

        # Original (30d-ago) token fraction — measures the pool's true exposure
        total_30d = base_protocol_apy_pct + token_apy_30d_ago_pct
        if total_30d > 0:
            token_ratio_30d = token_apy_30d_ago_pct / total_30d
        else:
            token_ratio_30d = 1.0 if token_apy_30d_ago_pct > 0 else 0.0

        # Rule 2: pool was originally base-yield dominant → resilient
        if token_ratio_30d < _RESILIENT_THRESHOLD:
            return "PRICE_RESILIENT"

        # Rule 3: severe crash in a token-dependent pool → destroyed
        if abs_change >= _DESTROYED_MIN_CHANGE:
            return "APY_DESTROYED"

        # Rule 4: moderate exposure + small change → mild
        if token_ratio_30d <= _MILD_MAX_RATIO and abs_change < _MILD_MAX_CHANGE:
            return "MILD_IMPACT"

        # Rules 5-6: magnitude-driven for significant token pools
        if abs_change >= _HIGH_MIN_CHANGE:
            return "HIGH_IMPACT"
        if abs_change >= _MODERATE_MIN_CHANGE:
            return "MODERATE_IMPACT"

        # Rule 7: token dominates (>50%) with small change
        return "MILD_IMPACT"

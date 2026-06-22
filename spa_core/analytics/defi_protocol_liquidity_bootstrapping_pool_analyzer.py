"""
MP-1098  DeFiProtocolLiquidityBootstrappingPoolAnalyzer
========================================================
Advisory-only module. Analyzes Balancer-style Liquidity Bootstrapping Pool
(LBP) price discovery mechanics. LBPs shift token weights over time to
gradually sell tokens; price should decline toward fair value. Detects
manipulation and optimal buy timing.

Pure Python stdlib only — no external dependencies.
Atomic writes: tmp-file + os.replace().
Advisory read-only: never modifies allocator / risk / execution.
Ring-buffer log capped at 100 entries.
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ── Data file ────────────────────────────────────────────────────────────────

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DATA_FILE = os.path.normpath(
    os.path.join(
        _MODULE_DIR, "..", "..", "data", "liquidity_bootstrapping_pool_log.json"
    )
)
_LOG_CAP = 100

# ── Label thresholds ─────────────────────────────────────────────────────────

LABEL_WAIT_FOR_LOWER = "WAIT_FOR_LOWER"
LABEL_APPROACHING_FV = "APPROACHING_FV"
LABEL_NEAR_FAIR_VALUE = "NEAR_FAIR_VALUE"
LABEL_BELOW_FV_BUY = "BELOW_FV_BUY"
LABEL_PANIC_SELL_OPPORTUNITY = "PANIC_SELL_OPPORTUNITY"

# ── I/O helpers ──────────────────────────────────────────────────────────────


def _atomic_write(path: str, obj: Any) -> None:
    """Write *obj* as JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path: str) -> list:
    """Load the ring-buffer log from *path*. Returns [] on any error."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, record: dict) -> None:
    """Append *record* to the ring-buffer log at *path* (cap: _LOG_CAP)."""
    entries = _load_log(path)
    entries.append(record)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]
    _atomic_write(path, entries)


# ── Core computation helpers ─────────────────────────────────────────────────


def _validate_inputs(
    start_weight_token_pct: float,
    end_weight_token_pct: float,
    start_price_usd: float,
    current_price_usd: float,
    fair_value_estimate_usd: float,
    elapsed_hours: float,
    total_duration_hours: float,
    total_liquidity_usd: float,
    volume_24h_usd: float,
    protocol_name: str,
) -> None:
    """Validate all input parameters. Raises ValueError/TypeError on bad input."""
    if not isinstance(protocol_name, str) or not protocol_name.strip():
        raise ValueError("protocol_name must be a non-empty string")
    if not (0.0 < start_weight_token_pct <= 100.0):
        raise ValueError(
            f"start_weight_token_pct must be in (0, 100], got {start_weight_token_pct}"
        )
    if not (0.0 < end_weight_token_pct <= 100.0):
        raise ValueError(
            f"end_weight_token_pct must be in (0, 100], got {end_weight_token_pct}"
        )
    if start_price_usd <= 0:
        raise ValueError(f"start_price_usd must be > 0, got {start_price_usd}")
    if current_price_usd < 0:
        raise ValueError(
            f"current_price_usd must be >= 0, got {current_price_usd}"
        )
    if fair_value_estimate_usd <= 0:
        raise ValueError(
            f"fair_value_estimate_usd must be > 0, got {fair_value_estimate_usd}"
        )
    if elapsed_hours < 0:
        raise ValueError(f"elapsed_hours must be >= 0, got {elapsed_hours}")
    if total_duration_hours <= 0:
        raise ValueError(
            f"total_duration_hours must be > 0, got {total_duration_hours}"
        )
    if total_liquidity_usd < 0:
        raise ValueError(
            f"total_liquidity_usd must be >= 0, got {total_liquidity_usd}"
        )
    if volume_24h_usd < 0:
        raise ValueError(f"volume_24h_usd must be >= 0, got {volume_24h_usd}")


def _compute_progress_pct(elapsed_hours: float, total_duration_hours: float) -> float:
    """Progress as percentage of total duration (clamped 0–100)."""
    raw = (elapsed_hours / total_duration_hours) * 100.0
    return max(0.0, min(100.0, raw))


def _compute_current_weight_pct(
    start_weight_token_pct: float,
    end_weight_token_pct: float,
    progress_pct: float,
) -> float:
    """
    Linearly interpolate the token weight at the current LBP progress.

    weight(t) = start_weight + (end_weight - start_weight) * progress_pct/100
    """
    return start_weight_token_pct + (
        end_weight_token_pct - start_weight_token_pct
    ) * (progress_pct / 100.0)


def _compute_price_vs_fair_value_pct(
    current_price_usd: float, fair_value_estimate_usd: float
) -> float:
    """
    Signed deviation of current price from fair value.

    (current - fair) / fair * 100
    Positive means price is ABOVE fair value (expensive).
    Negative means price is BELOW fair value (cheap).
    """
    return (current_price_usd - fair_value_estimate_usd) / fair_value_estimate_usd * 100.0


def _compute_volume_to_liquidity_ratio(
    volume_24h_usd: float, total_liquidity_usd: float
) -> float:
    """24h volume / total liquidity. Returns 0.0 if liquidity is zero."""
    if total_liquidity_usd == 0:
        return 0.0
    return volume_24h_usd / total_liquidity_usd


def _compute_lbp_label(price_vs_fv_pct: float) -> str:
    """
    Assign an LBP opportunity label based on price deviation from fair value.

    > +30%  → WAIT_FOR_LOWER
    +10% to +30% → APPROACHING_FV
    ±10%   → NEAR_FAIR_VALUE
    -10% to -30% → BELOW_FV_BUY
    < -30% → PANIC_SELL_OPPORTUNITY
    """
    if price_vs_fv_pct > 30.0:
        return LABEL_WAIT_FOR_LOWER
    elif price_vs_fv_pct > 10.0:
        return LABEL_APPROACHING_FV
    elif price_vs_fv_pct >= -10.0:
        return LABEL_NEAR_FAIR_VALUE
    elif price_vs_fv_pct >= -30.0:
        return LABEL_BELOW_FV_BUY
    else:
        return LABEL_PANIC_SELL_OPPORTUNITY


def _compute_opportunity_score(
    price_vs_fv_pct: float,
    progress_pct: float,
    volume_to_liquidity_ratio: float,
) -> int:
    """
    Compute an LBP opportunity score (0–100, 100 = best buying opportunity).

    Score components:
    1. Price component (0–60): higher when price is closer to or below FV.
       Below FV is rewarded strongly; above FV penalises.
    2. Progress component (0–25): more progress = closer to fair discovery
       (weights have shifted more); reward later-stage LBPs.
    3. Volume/liquidity component (0–15): moderate vol/liq (organic interest)
       is positive; extremely high (manipulation) is neutral/negative.
    """
    # --- Price component ---
    # Map price_vs_fv_pct to [0, 60]:
    # +50% above FV → 0 pts; at FV → 30 pts; -50% below FV → 60 pts
    price_raw = 30.0 - price_vs_fv_pct * 0.6
    price_score = max(0.0, min(60.0, price_raw))

    # --- Progress component ---
    # 0% progress → 0 pts; 100% progress → 25 pts
    progress_score = progress_pct * 0.25

    # --- Volume/liquidity component ---
    # Optimal vol/liq ≈ 0.1–0.5 (healthy organic buying)
    # < 0.05 → low interest; > 2.0 → possible manipulation
    vl = volume_to_liquidity_ratio
    if vl < 0.05:
        vl_score = 5.0
    elif vl <= 0.5:
        vl_score = 15.0
    elif vl <= 2.0:
        vl_score = 10.0
    else:
        vl_score = 3.0  # Very high vol/liq may indicate manipulation

    raw = price_score + progress_score + vl_score
    return int(round(max(0.0, min(100.0, raw))))


def _analyze(
    start_weight_token_pct: float,
    end_weight_token_pct: float,
    start_price_usd: float,
    current_price_usd: float,
    fair_value_estimate_usd: float,
    elapsed_hours: float,
    total_duration_hours: float,
    total_liquidity_usd: float,
    volume_24h_usd: float,
    protocol_name: str,
) -> dict:
    """
    Core computation returning all output fields.

    Parameters and returns are documented on
    :class:`DeFiProtocolLiquidityBootstrappingPoolAnalyzer`.
    """
    _validate_inputs(
        start_weight_token_pct,
        end_weight_token_pct,
        start_price_usd,
        current_price_usd,
        fair_value_estimate_usd,
        elapsed_hours,
        total_duration_hours,
        total_liquidity_usd,
        volume_24h_usd,
        protocol_name,
    )

    progress_pct = _compute_progress_pct(elapsed_hours, total_duration_hours)
    current_weight_pct = _compute_current_weight_pct(
        start_weight_token_pct, end_weight_token_pct, progress_pct
    )
    price_vs_fv_pct = _compute_price_vs_fair_value_pct(
        current_price_usd, fair_value_estimate_usd
    )
    volume_to_liquidity_ratio = _compute_volume_to_liquidity_ratio(
        volume_24h_usd, total_liquidity_usd
    )
    lbp_label = _compute_lbp_label(price_vs_fv_pct)
    lbp_opportunity_score = _compute_opportunity_score(
        price_vs_fv_pct, progress_pct, volume_to_liquidity_ratio
    )

    return {
        "protocol_name": protocol_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Inputs echo
        "start_weight_token_pct": start_weight_token_pct,
        "end_weight_token_pct": end_weight_token_pct,
        "start_price_usd": start_price_usd,
        "current_price_usd": current_price_usd,
        "fair_value_estimate_usd": fair_value_estimate_usd,
        "elapsed_hours": elapsed_hours,
        "total_duration_hours": total_duration_hours,
        "total_liquidity_usd": total_liquidity_usd,
        "volume_24h_usd": volume_24h_usd,
        # Outputs
        "progress_pct": round(progress_pct, 6),
        "current_weight_pct": round(current_weight_pct, 6),
        "price_vs_fair_value_pct": round(price_vs_fv_pct, 6),
        "volume_to_liquidity_ratio": round(volume_to_liquidity_ratio, 8),
        "lbp_opportunity_score": lbp_opportunity_score,
        "lbp_label": lbp_label,
    }


# ── Main class ────────────────────────────────────────────────────────────────


class DeFiProtocolLiquidityBootstrappingPoolAnalyzer:
    """
    Analyzes Balancer-style Liquidity Bootstrapping Pool (LBP) price discovery
    mechanics. LBPs shift weights over time to gradually sell tokens; price
    should decline to fair value. Detects manipulation and optimal buy timing.

    Usage
    -----
    ::
        analyzer = DeFiProtocolLiquidityBootstrappingPoolAnalyzer()
        result = analyzer.analyze(
            start_weight_token_pct=96.0,
            end_weight_token_pct=50.0,
            start_price_usd=10.0,
            current_price_usd=7.5,
            fair_value_estimate_usd=5.0,
            elapsed_hours=24.0,
            total_duration_hours=72.0,
            total_liquidity_usd=500_000.0,
            volume_24h_usd=50_000.0,
            protocol_name="ExampleDAO",
        )

    Outputs
    -------
    - ``progress_pct`` (float): elapsed / total * 100
    - ``current_weight_pct`` (float): linearly interpolated token weight
    - ``price_vs_fair_value_pct`` (float): (current-fair)/fair*100, signed
    - ``volume_to_liquidity_ratio`` (float): 24h volume / total liquidity
    - ``lbp_opportunity_score`` (int 0–100): 100 = best buying opportunity
    - ``lbp_label`` (str): one of WAIT_FOR_LOWER / APPROACHING_FV /
      NEAR_FAIR_VALUE / BELOW_FV_BUY / PANIC_SELL_OPPORTUNITY

    Log file
    --------
    Each call appends to a ring-buffer JSON log (cap: 100 entries) at
    ``data/liquidity_bootstrapping_pool_log.json``.
    """

    def __init__(self, data_file: str = _DEFAULT_DATA_FILE) -> None:
        self.data_file = data_file

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        start_weight_token_pct: float,
        end_weight_token_pct: float,
        start_price_usd: float,
        current_price_usd: float,
        fair_value_estimate_usd: float,
        elapsed_hours: float,
        total_duration_hours: float,
        total_liquidity_usd: float,
        volume_24h_usd: float,
        protocol_name: str,
        *,
        write_log: bool = True,
    ) -> dict:
        """
        Analyze a single LBP state.

        Parameters
        ----------
        start_weight_token_pct : float
            Starting weight of the project token in the pool (e.g. 96.0).
        end_weight_token_pct : float
            Ending weight of the project token (e.g. 50.0).
        start_price_usd : float
            Token price at LBP start in USD (> 0).
        current_price_usd : float
            Current token price in USD (>= 0).
        fair_value_estimate_usd : float
            Analyst's fair value estimate in USD (> 0).
        elapsed_hours : float
            Hours since LBP started (>= 0).
        total_duration_hours : float
            Total planned LBP duration in hours (> 0).
        total_liquidity_usd : float
            Total USD liquidity in the pool (>= 0).
        volume_24h_usd : float
            24-hour trading volume in USD (>= 0).
        protocol_name : str
            Protocol or project name.
        write_log : bool
            If True (default), append result to ring-buffer log file.

        Returns
        -------
        dict
            All input echoes plus computed outputs.

        Raises
        ------
        ValueError
            On invalid input parameters.
        """
        result = _analyze(
            start_weight_token_pct=start_weight_token_pct,
            end_weight_token_pct=end_weight_token_pct,
            start_price_usd=start_price_usd,
            current_price_usd=current_price_usd,
            fair_value_estimate_usd=fair_value_estimate_usd,
            elapsed_hours=elapsed_hours,
            total_duration_hours=total_duration_hours,
            total_liquidity_usd=total_liquidity_usd,
            volume_24h_usd=volume_24h_usd,
            protocol_name=protocol_name,
        )
        if write_log:
            _append_log(self.data_file, result)
        return result

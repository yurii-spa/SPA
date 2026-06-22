"""
MP-978: DeFiProtocolExitLiquidityAnalyzer

Advisory/read-only module. Analyzes real exit liquidity from DeFi positions
under different scenarios: instant withdrawals, vesting unlocks, pool exits,
bond redemptions. Computes exit friction scores and time-to-exit estimates.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "exit_liquidity_log.json"
)

# ---------------------------------------------------------------------------
# Exit label constants
# ---------------------------------------------------------------------------
LABEL_INSTANT_EXIT = "INSTANT_EXIT"
LABEL_EASY_EXIT = "EASY_EXIT"
LABEL_MODERATE_EXIT = "MODERATE_EXIT"
LABEL_DIFFICULT_EXIT = "DIFFICULT_EXIT"
LABEL_TRAPPED = "TRAPPED"

# ---------------------------------------------------------------------------
# Flag constants
# ---------------------------------------------------------------------------
FLAG_WITHDRAWAL_QUEUE = "WITHDRAWAL_QUEUE"
FLAG_LOCKED = "LOCKED"
FLAG_LARGE_RELATIVE_TO_MARKET = "LARGE_RELATIVE_TO_MARKET"
FLAG_FEE_BARRIER = "FEE_BARRIER"
FLAG_SINGLE_TX_CONSTRAINED = "SINGLE_TX_CONSTRAINED"

# ---------------------------------------------------------------------------
# Friction weights
# ---------------------------------------------------------------------------
_FRICTION_LOCK_WEIGHT = 0.30
_FRICTION_QUEUE_WEIGHT = 0.25
_FRICTION_SLIPPAGE_WEIGHT = 0.25
_FRICTION_FEE_WEIGHT = 0.20


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    return num / denom if denom != 0.0 else default


class DeFiProtocolExitLiquidityAnalyzer:
    """Analyze real exit liquidity from DeFi positions."""

    def __init__(self, data_file: Optional[str] = None):
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, positions: List[dict], config: Optional[dict] = None) -> dict:
        """
        Analyze exit liquidity for a list of DeFi positions.

        Parameters
        ----------
        positions : list[dict]
            Each dict must contain:
              protocol, asset, position_size_usd,
              available_exit_liquidity_usd, daily_volume_usd,
              exit_type (instant_withdraw/vesting_unlock/pool_exit/bond_redemption),
              lock_remaining_days, withdrawal_queue_usd,
              slippage_model (linear/sqrt/constant),
              withdrawal_fee_pct, max_exit_in_single_tx_usd

        config : dict, optional
            Optional overrides: instant_exit_max_days, easy_exit_max_days,
            moderate_exit_max_days, trapped_min_days, large_market_ratio_threshold

        Returns
        -------
        dict with keys: results (list), aggregates (dict), run_ts (str), position_count (int)
        """
        if config is None:
            config = {}

        instant_max_days = float(config.get("instant_exit_max_days", 1.0))
        easy_max_days = float(config.get("easy_exit_max_days", 7.0))
        moderate_max_days = float(config.get("moderate_exit_max_days", 30.0))
        trapped_min_days = float(config.get("trapped_min_days", 30.0))
        large_ratio_thresh = float(config.get("large_market_ratio_threshold", 0.1))

        results = []
        for pos in positions:
            r = self._analyze_position(
                pos,
                instant_max_days=instant_max_days,
                easy_max_days=easy_max_days,
                moderate_max_days=moderate_max_days,
                trapped_min_days=trapped_min_days,
                large_ratio_thresh=large_ratio_thresh,
            )
            results.append(r)

        aggregates = self._compute_aggregates(results)

        run_ts = datetime.now(timezone.utc).isoformat()
        output = {
            "results": results,
            "aggregates": aggregates,
            "run_ts": run_ts,
            "position_count": len(positions),
        }

        self._append_log({"run_ts": run_ts, "position_count": len(positions), "aggregates": aggregates})
        return output

    # ------------------------------------------------------------------
    # Per-position analysis
    # ------------------------------------------------------------------

    def _analyze_position(
        self,
        pos: dict,
        *,
        instant_max_days: float,
        easy_max_days: float,
        moderate_max_days: float,
        trapped_min_days: float,
        large_ratio_thresh: float,
    ) -> dict:
        protocol = str(pos.get("protocol", ""))
        asset = str(pos.get("asset", ""))
        size = float(pos.get("position_size_usd", 0.0))
        avail_liq = float(pos.get("available_exit_liquidity_usd", 0.0))
        daily_vol = float(pos.get("daily_volume_usd", 0.0))
        exit_type = str(pos.get("exit_type", "instant_withdraw"))
        lock_days = float(pos.get("lock_remaining_days", 0.0))
        queue_usd = float(pos.get("withdrawal_queue_usd", 0.0))
        slippage_model = str(pos.get("slippage_model", "linear"))
        fee_pct = float(pos.get("withdrawal_fee_pct", 0.0))
        max_single_tx = float(pos.get("max_exit_in_single_tx_usd", size))

        # Liquidity ratio
        liquidity_ratio = _safe_div(size, avail_liq, default=float("inf") if avail_liq == 0 else 0.0)
        if avail_liq <= 0:
            liquidity_ratio = 999.0

        # Slippage at full exit
        slippage_1pct = self._compute_slippage(size, avail_liq, slippage_model, impact_pct=1.0)
        slippage_10pct = self._compute_slippage(size, avail_liq, slippage_model, impact_pct=10.0)

        # Days to exit at 1% / 10% slippage impact
        exit_1pct_days = self._compute_exit_days(size, avail_liq, daily_vol, slippage_model, target_impact=0.01)
        exit_10pct_days = self._compute_exit_days(size, avail_liq, daily_vol, slippage_model, target_impact=0.10)

        # Full exit days (accounts for lock + queue + single-tx constraint + liquidity)
        full_exit_days = self._compute_full_exit_days(
            size=size,
            avail_liq=avail_liq,
            daily_vol=daily_vol,
            slippage_model=slippage_model,
            lock_days=lock_days,
            queue_usd=queue_usd,
            max_single_tx=max_single_tx,
            exit_type=exit_type,
        )

        # Friction score 0-100
        friction_score = self._compute_friction_score(
            lock_days=lock_days,
            queue_usd=queue_usd,
            size=size,
            avail_liq=avail_liq,
            slippage_model=slippage_model,
            fee_pct=fee_pct,
        )

        # Exit label
        label = self._compute_label(
            full_exit_days=full_exit_days,
            queue_usd=queue_usd,
            size=size,
            slippage_at_full=self._compute_slippage_at_full(size, avail_liq, slippage_model),
            instant_max_days=instant_max_days,
            easy_max_days=easy_max_days,
            moderate_max_days=moderate_max_days,
            trapped_min_days=trapped_min_days,
        )

        # Flags
        flags = self._compute_flags(
            queue_usd=queue_usd,
            lock_days=lock_days,
            liquidity_ratio=liquidity_ratio,
            fee_pct=fee_pct,
            max_single_tx=max_single_tx,
            size=size,
            large_ratio_thresh=large_ratio_thresh,
        )

        return {
            "protocol": protocol,
            "asset": asset,
            "position_size_usd": round(size, 2),
            "liquidity_ratio": round(liquidity_ratio, 4),
            "exit_1pct_days": round(exit_1pct_days, 2),
            "exit_10pct_days": round(exit_10pct_days, 2),
            "full_exit_days": round(full_exit_days, 2),
            "exit_friction_score": round(friction_score, 2),
            "slippage_at_1pct_impact": round(slippage_1pct, 4),
            "slippage_at_10pct_impact": round(slippage_10pct, 4),
            "label": label,
            "flags": flags,
            "exit_type": exit_type,
            "lock_remaining_days": lock_days,
            "withdrawal_queue_usd": queue_usd,
            "withdrawal_fee_pct": fee_pct,
        }

    # ------------------------------------------------------------------
    # Slippage model
    # ------------------------------------------------------------------

    def _compute_slippage_at_full(self, size: float, avail_liq: float, model: str) -> float:
        """Slippage % when exiting the full position."""
        if avail_liq <= 0:
            return 100.0
        ratio = _safe_div(size, avail_liq, default=1.0)
        if model == "constant":
            return 0.5
        elif model == "sqrt":
            return _clamp(10.0 * math.sqrt(ratio), 0.0, 100.0)
        else:  # linear (default)
            return _clamp(ratio * 10.0, 0.0, 100.0)

    def _compute_slippage(self, size: float, avail_liq: float, model: str, impact_pct: float) -> float:
        """Return slippage % given a target impact pct."""
        return self._compute_slippage_at_full(size, avail_liq, model)

    def _compute_exit_days(
        self,
        size: float,
        avail_liq: float,
        daily_vol: float,
        model: str,
        target_impact: float,
    ) -> float:
        """Days to exit size while keeping market impact ≤ target_impact."""
        if size <= 0:
            return 0.0
        if avail_liq <= 0 or daily_vol <= 0:
            return 365.0

        # Max daily sell = target_impact * avail_liq (linear model) or derived
        if model == "constant":
            # Constant slippage: just constrain to fraction of daily volume
            safe_daily = daily_vol * target_impact * 10.0
        elif model == "sqrt":
            # sqrt: impact = 10 * sqrt(sold/avail) → sold = (impact/10)^2 * avail
            safe_daily = (target_impact ** 2) * avail_liq
        else:
            # linear: impact = (sold/avail)*10 → sold = impact/10 * avail
            safe_daily = target_impact * avail_liq

        safe_daily = max(safe_daily, daily_vol * 0.001)  # floor: 0.1% of daily vol

        if safe_daily <= 0:
            return 365.0

        return min(size / safe_daily, 365.0)

    def _compute_full_exit_days(
        self,
        *,
        size: float,
        avail_liq: float,
        daily_vol: float,
        slippage_model: str,
        lock_days: float,
        queue_usd: float,
        max_single_tx: float,
        exit_type: str,
    ) -> float:
        """Realistic time to fully exit position (days)."""
        # Start with lock
        days = lock_days

        # Queue delay: queue / daily_vol
        if queue_usd > 0 and daily_vol > 0:
            days += queue_usd / daily_vol
        elif queue_usd > 0:
            days += 30.0  # no volume data, assume 30d

        # Single-tx constraint
        if max_single_tx > 0 and max_single_tx < size:
            n_txs = math.ceil(size / max_single_tx)
            # Assume 1 tx per day if constrained
            days += max(0.0, n_txs - 1)

        # Liquidity constraint: sell at most some fraction of daily vol per day
        if daily_vol > 0 and avail_liq > 0:
            # Limit to 5% of daily vol to avoid excessive market impact
            safe_daily = min(daily_vol * 0.05, avail_liq * 0.1)
            safe_daily = max(safe_daily, 1.0)
            liq_days = size / safe_daily
            days += max(0.0, liq_days - 1.0)
        elif avail_liq <= 0:
            days += 365.0

        # Bond/vesting adds fixed delay
        if exit_type == "bond_redemption":
            days += 1.0  # settlement
        elif exit_type == "vesting_unlock":
            pass  # lock_days already covers it

        return min(days, 730.0)  # cap at 2 years

    # ------------------------------------------------------------------
    # Friction score
    # ------------------------------------------------------------------

    def _compute_friction_score(
        self,
        *,
        lock_days: float,
        queue_usd: float,
        size: float,
        avail_liq: float,
        slippage_model: str,
        fee_pct: float,
    ) -> float:
        """Compute exit friction score 0-100 (higher = harder to exit)."""

        # Lock component: 30 days → 100
        lock_score = _clamp(lock_days / 30.0 * 100.0)

        # Queue component: queue / size ratio
        if size > 0:
            queue_ratio = _safe_div(queue_usd, size, default=0.0)
            queue_score = _clamp(queue_ratio * 50.0)
        else:
            queue_score = 0.0

        # Slippage component: slippage at full exit
        slip_pct = self._compute_slippage_at_full(size, avail_liq, slippage_model)
        slip_score = _clamp(slip_pct * 2.0)  # 50% slippage → 100

        # Fee component: fee_pct
        fee_score = _clamp(fee_pct * 20.0)  # 5% fee → 100

        combined = (
            _FRICTION_LOCK_WEIGHT * lock_score
            + _FRICTION_QUEUE_WEIGHT * queue_score
            + _FRICTION_SLIPPAGE_WEIGHT * slip_score
            + _FRICTION_FEE_WEIGHT * fee_score
        )
        return _clamp(combined)

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def _compute_label(
        self,
        *,
        full_exit_days: float,
        queue_usd: float,
        size: float,
        slippage_at_full: float,
        instant_max_days: float,
        easy_max_days: float,
        moderate_max_days: float,
        trapped_min_days: float,
    ) -> str:
        # Trapped: queue > position OR >30d to exit
        if queue_usd >= size > 0:
            return LABEL_TRAPPED
        if full_exit_days > trapped_min_days:
            return LABEL_TRAPPED

        if full_exit_days <= instant_max_days and slippage_at_full <= 1.0:
            return LABEL_INSTANT_EXIT
        if full_exit_days <= easy_max_days:
            return LABEL_EASY_EXIT
        if full_exit_days <= moderate_max_days:
            return LABEL_MODERATE_EXIT
        return LABEL_DIFFICULT_EXIT

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        *,
        queue_usd: float,
        lock_days: float,
        liquidity_ratio: float,
        fee_pct: float,
        max_single_tx: float,
        size: float,
        large_ratio_thresh: float,
    ) -> List[str]:
        flags = []

        if queue_usd > 0:
            flags.append(FLAG_WITHDRAWAL_QUEUE)

        if lock_days > 0:
            flags.append(FLAG_LOCKED)

        if liquidity_ratio > large_ratio_thresh:
            flags.append(FLAG_LARGE_RELATIVE_TO_MARKET)

        if fee_pct > 2.0:
            flags.append(FLAG_FEE_BARRIER)

        if size > 0 and max_single_tx < size * 0.1:
            flags.append(FLAG_SINGLE_TX_CONSTRAINED)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: List[dict]) -> dict:
        if not results:
            return {
                "most_liquid": None,
                "least_liquid": None,
                "total_trapped_usd": 0.0,
                "easy_exit_count": 0,
                "average_exit_friction": 0.0,
            }

        sorted_by_friction = sorted(results, key=lambda r: r["exit_friction_score"])
        most_liquid = sorted_by_friction[0]["protocol"]
        least_liquid = sorted_by_friction[-1]["protocol"]

        trapped_labels = {LABEL_TRAPPED}
        total_trapped = sum(
            r["position_size_usd"] for r in results if r["label"] in trapped_labels
        )

        easy_labels = {LABEL_INSTANT_EXIT, LABEL_EASY_EXIT}
        easy_exit_count = sum(1 for r in results if r["label"] in easy_labels)

        frictions = [r["exit_friction_score"] for r in results]
        avg_friction = sum(frictions) / len(frictions)

        return {
            "most_liquid": most_liquid,
            "least_liquid": least_liquid,
            "total_trapped_usd": round(total_trapped, 2),
            "easy_exit_count": easy_exit_count,
            "average_exit_friction": round(avg_friction, 4),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, record: dict) -> None:
        """Atomically append record to ring-buffer log (cap 100)."""
        try:
            log = []
            if os.path.exists(self._data_file):
                try:
                    with open(self._data_file, "r", encoding="utf-8") as fh:
                        log = json.load(fh)
                    if not isinstance(log, list):
                        log = []
                except (json.JSONDecodeError, OSError):
                    log = []

            log.append(record)
            if len(log) > 100:
                log = log[-100:]

            dir_name = os.path.dirname(self._data_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            atomic_save(log, str(self._data_file))
        except Exception:
            # Advisory module — never crash the caller
            pass

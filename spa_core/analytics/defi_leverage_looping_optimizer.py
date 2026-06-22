"""
MP-948 DeFiLeverageLoopingOptimizer
===================================
Models recursive "looping" / leveraged-yield strategies, where a position is
built by repeatedly depositing collateral, borrowing against it at a fixed
loan-to-value (LTV), and re-depositing the borrowed funds, N times. This is
the canonical pattern behind stETH/AAVE leverage loops, Pendle PT loops and
similar recursive-leverage vaults.

Looping amplifies a thin native carry (supply_apy + reward_apy - borrow_apy)
by the leverage multiplier, but it also raises liquidation risk and, when the
borrow cost exceeds the earned yield, can turn a positive carry negative.

Math (geometric series, per $1 of initial equity)
-------------------------------------------------
With a per-loop LTV ``l`` (0 < l < 1), after ``k`` loops the cumulative
supplied exposure (collateral) multiplier is the geometric sum::

    supplied_mult(k) = (1 - l**(k + 1)) / (1 - l)

The total borrowed multiplier is::

    borrowed_mult(k) = supplied_mult(k) - 1

As k -> inf the effective leverage approaches 1 / (1 - l). We report
``leverage_ratio = supplied_mult`` at the optimal number of loops.

Net APY (per $1 initial equity), at loop count k::

    net_apy = supply_apy * supplied_mult
            + reward_apy * supplied_mult
            - borrow_apy * borrowed_mult

``optimal_loops`` is the k in [0, max_loops] that MAXIMISES net_apy. Each
extra loop adds a marginal contribution; when borrow_apy exceeds
supply_apy + reward_apy the marginal contribution is negative, so 0 loops
(no leverage) can be optimal.

Risk
----
    current_ltv          = borrowed_mult / supplied_mult
    health_factor        = liquidation_ltv / current_ltv   (cap 999.0 when no debt)
    liquidation_buffer   = (liquidation_ltv - current_ltv) / liquidation_ltv * 100

Classification:
  HIGHLY_PROFITABLE | PROFITABLE | MARGINAL | UNPROFITABLE | NEGATIVE_CARRY

Flags:
  INSUFFICIENT_DATA        ltv <= 0 or ltv >= 1, or supply_apy <= 0 with no reward
  NEGATIVE_CARRY           borrow_apy > supply_apy + reward_apy (looping hurts)
  THIN_LIQUIDATION_BUFFER  liquidation_buffer_pct < 10
  HIGH_LEVERAGE            leverage_ratio > 5
  NO_PROFITABLE_LOOP       optimal_loops == 0
  AGGRESSIVE_LTV           ltv > 0.85

Input pool keys (all optional with sensible defaults):
  name / symbol       str
  supply_apy_pct      float   yield on supplied/collateral (staking + lending)
  borrow_apy_pct      float   cost to borrow
  ltv                 float   loan-to-value used per loop (0..1)
  liquidation_ltv     float   LTV at which liquidation occurs (default ltv+0.05, <1)
  max_loops           int     cap on iterations (default 10)
  reward_apy_pct      float   extra incentive APY on the leveraged position (default 0)

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "leverage_looping_log.json"
)
_LOG_CAP = 100

_DEFAULT_MAX_LOOPS = 10
_DEFAULT_LIQ_LTV_BUFFER = 0.05
_MAX_HEALTH_FACTOR = 999.0

# Flag thresholds
_THIN_BUFFER_PCT = 10.0
_HIGH_LEVERAGE_RATIO = 5.0
_AGGRESSIVE_LTV = 0.85

# Score grade thresholds
_GRADE_A = 85.0
_GRADE_B = 70.0
_GRADE_C = 55.0
_GRADE_D = 40.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _grade_from_score(score: float) -> str:
    if score >= _GRADE_A:
        return "A"
    if score >= _GRADE_B:
        return "B"
    if score >= _GRADE_C:
        return "C"
    if score >= _GRADE_D:
        return "D"
    return "F"


def _classify(net_apy_pct: float, supply_apy_pct: float) -> str:
    """
    Classify the looped position from its net APY versus the unlevered
    base supply APY.
    """
    if net_apy_pct < 0.0:
        return "NEGATIVE_CARRY"
    if net_apy_pct <= supply_apy_pct:
        return "UNPROFITABLE"
    uplift = net_apy_pct - supply_apy_pct
    if uplift >= supply_apy_pct and uplift > 0.0:
        return "HIGHLY_PROFITABLE"
    if uplift >= 1.0:
        return "PROFITABLE"
    return "MARGINAL"


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiLeverageLoopingOptimizer:
    """
    Models recursive leveraged-yield ("looping") strategies and finds the
    loop count that maximises net APY per unit of initial equity.

    Usage::

        opt = DeFiLeverageLoopingOptimizer()
        result = opt.analyze(pools, config)

    config keys (all optional):
        log_path   str   override default log file location
        write_log  bool  default True; set False to skip disk write
    """

    # ------------------------------------------------------------------
    # Geometric-series multipliers
    # ------------------------------------------------------------------

    def _supplied_mult(self, ltv: float, k: int) -> float:
        """Cumulative supplied (collateral) multiplier after k loops."""
        if ltv <= 0.0:
            return 1.0
        if ltv >= 1.0:
            # Degenerate; avoid division by zero, fall back to count.
            return float(k + 1)
        return (1.0 - ltv ** (k + 1)) / (1.0 - ltv)

    def _net_apy_at(
        self,
        supply_apy: float,
        reward_apy: float,
        borrow_apy: float,
        ltv: float,
        k: int,
    ) -> float:
        """Net APY (per $1 initial equity) at loop count k."""
        supplied_mult = self._supplied_mult(ltv, k)
        borrowed_mult = supplied_mult - 1.0
        return (
            supply_apy * supplied_mult
            + reward_apy * supplied_mult
            - borrow_apy * borrowed_mult
        )

    def _optimal_loops(
        self,
        supply_apy: float,
        reward_apy: float,
        borrow_apy: float,
        ltv: float,
        max_loops: int,
    ) -> int:
        """Return the k in [0, max_loops] that maximises net APY."""
        best_k = 0
        best_net = self._net_apy_at(supply_apy, reward_apy, borrow_apy, ltv, 0)
        for k in range(1, max_loops + 1):
            net = self._net_apy_at(supply_apy, reward_apy, borrow_apy, ltv, k)
            if net > best_net:
                best_net = net
                best_k = k
        return best_k

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(
        self,
        net_apy: float,
        supply_apy: float,
        liquidation_buffer_pct: float,
        leverage_ratio: float,
    ) -> float:
        """
        0-100 (higher = better). Rewards net_apy uplift over the base
        supply APY, penalises a thin liquidation buffer and very high
        leverage.
        """
        # Base 50, each 1pp of uplift over base ~ +6 points.
        uplift = net_apy - supply_apy
        score = 50.0 + uplift * 6.0

        # Thin-buffer penalty (steeper the thinner the buffer).
        if liquidation_buffer_pct < _THIN_BUFFER_PCT:
            score -= (_THIN_BUFFER_PCT - liquidation_buffer_pct) * 2.0

        # High-leverage penalty.
        if leverage_ratio > _HIGH_LEVERAGE_RATIO:
            score -= (leverage_ratio - _HIGH_LEVERAGE_RATIO) * 3.0

        return round(_clamp(score, 0.0, 100.0), 4)

    def _compute_flags(
        self,
        ltv: float,
        supply_apy: float,
        reward_apy: float,
        borrow_apy: float,
        liquidation_buffer_pct: float,
        leverage_ratio: float,
        optimal_loops: int,
        valid: bool,
    ) -> list:
        """Return list of applicable flag strings."""
        flags: list[str] = []

        if not valid:
            flags.append("INSUFFICIENT_DATA")
            return flags

        if borrow_apy > supply_apy + reward_apy:
            flags.append("NEGATIVE_CARRY")

        if liquidation_buffer_pct < _THIN_BUFFER_PCT:
            flags.append("THIN_LIQUIDATION_BUFFER")

        if leverage_ratio > _HIGH_LEVERAGE_RATIO:
            flags.append("HIGH_LEVERAGE")

        if optimal_loops == 0:
            flags.append("NO_PROFITABLE_LOOP")

        if ltv > _AGGRESSIVE_LTV:
            flags.append("AGGRESSIVE_LTV")

        return flags

    # ------------------------------------------------------------------
    # Single-pool analysis
    # ------------------------------------------------------------------

    def _analyze_pool(self, pool: dict) -> dict:
        """Analyse one looping opportunity and return result dict."""
        name = pool.get("name", pool.get("symbol", "unknown"))
        supply_apy = float(pool.get("supply_apy_pct", 0.0))
        borrow_apy = float(pool.get("borrow_apy_pct", 0.0))
        ltv = float(pool.get("ltv", 0.0))
        reward_apy = float(pool.get("reward_apy_pct", 0.0))
        max_loops = int(pool.get("max_loops", _DEFAULT_MAX_LOOPS))
        if max_loops < 0:
            max_loops = 0

        liquidation_ltv = float(
            pool.get("liquidation_ltv", ltv + _DEFAULT_LIQ_LTV_BUFFER)
        )
        # Clamp liquidation LTV strictly below 1.
        liquidation_ltv = _clamp(liquidation_ltv, 0.0, 0.999999)

        valid = (
            0.0 < ltv < 1.0
            and (supply_apy > 0.0 or reward_apy > 0.0)
        )

        if valid:
            optimal_loops = self._optimal_loops(
                supply_apy, reward_apy, borrow_apy, ltv, max_loops
            )
            supplied_mult = self._supplied_mult(ltv, optimal_loops)
            borrowed_mult = supplied_mult - 1.0
            leverage_ratio = round(supplied_mult, 6)
            net_apy = round(
                self._net_apy_at(
                    supply_apy, reward_apy, borrow_apy, ltv, optimal_loops
                ),
                6,
            )

            if borrowed_mult <= 0.0:
                current_ltv = 0.0
                health_factor = _MAX_HEALTH_FACTOR
            else:
                current_ltv = borrowed_mult / supplied_mult
                if current_ltv <= 0.0:
                    health_factor = _MAX_HEALTH_FACTOR
                else:
                    health_factor = min(
                        liquidation_ltv / current_ltv, _MAX_HEALTH_FACTOR
                    )

            if liquidation_ltv > 0.0:
                liquidation_buffer_pct = (
                    (liquidation_ltv - current_ltv) / liquidation_ltv * 100.0
                )
            else:
                liquidation_buffer_pct = 0.0

            current_ltv = round(current_ltv, 6)
            health_factor = round(health_factor, 6)
            liquidation_buffer_pct = round(liquidation_buffer_pct, 6)

            score = self._score(
                net_apy, supply_apy, liquidation_buffer_pct, leverage_ratio
            )
            classification = _classify(net_apy, supply_apy)
            grade = _grade_from_score(score)
        else:
            optimal_loops = 0
            supplied_mult = 1.0
            borrowed_mult = 0.0
            leverage_ratio = 1.0
            net_apy = round(supply_apy, 6)
            current_ltv = 0.0
            health_factor = _MAX_HEALTH_FACTOR
            liquidation_buffer_pct = 0.0
            score = 0.0
            classification = "NEGATIVE_CARRY"
            grade = "F"

        flags = self._compute_flags(
            ltv,
            supply_apy,
            reward_apy,
            borrow_apy,
            liquidation_buffer_pct,
            leverage_ratio,
            optimal_loops,
            valid,
        )

        return {
            "name": name,
            "supply_apy_pct": supply_apy,
            "borrow_apy_pct": borrow_apy,
            "reward_apy_pct": reward_apy,
            "ltv": ltv,
            "liquidation_ltv": round(liquidation_ltv, 6),
            "max_loops": max_loops,
            "optimal_loops": optimal_loops,
            "leverage_ratio": leverage_ratio,
            "net_apy_pct": net_apy,
            "current_ltv": current_ltv,
            "health_factor": health_factor,
            "liquidation_buffer_pct": liquidation_buffer_pct,
            "score": score,
            "classification": classification,
            "grade": grade,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, pools: list, config: dict | None = None) -> dict:
        """
        Analyse a list of leverage-looping opportunities.

        Parameters
        ----------
        pools : list[dict]
            Each dict describes one looping opportunity (see module docstring).
        config : dict, optional
            Optional overrides:
                log_path  str   custom log file path
                write_log bool  set False to skip log write (default True)

        Returns
        -------
        dict with keys:
            results     list[dict]  per-pool analysis
            aggregates  dict        portfolio-level summary
            timestamp   float       unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(pools, list):
            raise TypeError("pools must be a list")

        results = [self._analyze_pool(p) for p in pools]

        # -- Aggregates --------------------------------------------------
        if results:
            scores = [r["score"] for r in results]
            net_apys = [r["net_apy_pct"] for r in results]
            leverages = [r["leverage_ratio"] for r in results]

            best_idx = scores.index(max(scores))
            worst_idx = scores.index(min(scores))
            highest_lev_idx = leverages.index(max(leverages))

            best_loop_opportunity = results[best_idx]["name"]
            worst_loop_opportunity = results[worst_idx]["name"]
            average_net_apy_pct = sum(net_apys) / len(net_apys)
            highest_leverage_pool = results[highest_lev_idx]["name"]
            negative_carry_count = sum(
                1 for r in results if "NEGATIVE_CARRY" in r["flags"]
            )
            profitable_count = sum(
                1
                for r in results
                if r["classification"]
                in ("HIGHLY_PROFITABLE", "PROFITABLE", "MARGINAL")
            )
        else:
            best_loop_opportunity = None
            worst_loop_opportunity = None
            average_net_apy_pct = 0.0
            highest_leverage_pool = None
            negative_carry_count = 0
            profitable_count = 0

        aggregates = {
            "best_loop_opportunity": best_loop_opportunity,
            "worst_loop_opportunity": worst_loop_opportunity,
            "average_net_apy_pct": round(average_net_apy_pct, 6),
            "highest_leverage_pool": highest_leverage_pool,
            "negative_carry_count": negative_carry_count,
            "profitable_count": profitable_count,
        }

        ts = time.time()
        output: dict[str, Any] = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": ts,
        }

        # -- Ring-buffer log --------------------------------------------
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "item_count": len(results),
                        "aggregates": aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output

"""
MP-912  DeFiAMMImpermanentLossSimulator
=======================================
Advisory-only module. Simulates Impermanent Loss (IL) for AMM liquidity
pools (xy constant-product, concentrated-liquidity, stable-swap) under
various price scenarios.

Pure Python stdlib only — no external dependencies.
Atomic writes: tmp-file + os.replace().
Advisory read-only: never modifies allocator / risk / execution.
"""

import json
import math
import os
import time
from typing import Any, Optional
from spa_core.utils.atomic import atomic_save

# ── Data file ────────────────────────────────────────────────────────────────

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DATA_FILE = os.path.normpath(
    os.path.join(_MODULE_DIR, "..", "..", "data", "amm_il_simulation_log.json")
)
_LOG_CAP = 100

# ── I/O helpers ──────────────────────────────────────────────────────────────


def _atomic_write(path: str, obj: Any) -> None:
    """Write *obj* as JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, record: dict) -> None:
    log = _load_log(path)
    log.append(record)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ── IL formula helpers ────────────────────────────────────────────────────────


def _il_xy(price_ratio: float) -> float:
    """
    Standard constant-product (xy=k) IL formula.
    IL = 2*sqrt(r)/(1+r) - 1   where r = P_current / P_initial.
    Returns a value in [-1, 0].  IL is always non-positive.
    """
    if price_ratio <= 0:
        raise ValueError(f"price_ratio must be positive, got {price_ratio}")
    r = price_ratio
    return (2.0 * math.sqrt(r) / (1.0 + r)) - 1.0


def _il_stable(price_ratio: float) -> float:
    """
    Stable-swap AMM (e.g. Curve).  IL is dramatically reduced because the
    bonding curve is nearly flat near the peg.  Approximated as 10 % of the
    standard xy IL — a conservative upper-bound for minor de-peg scenarios.
    """
    return _il_xy(price_ratio) * 0.1


def _il_concentrated(
    initial_price_ratio: float,
    current_price_ratio: float,
    lower_bound: float,
    upper_bound: float,
) -> tuple:
    """
    Concentrated-liquidity (Uniswap V3-style) IL.

    Returns ``(il_fraction, out_of_range)``.

    - In-range: IL is amplified relative to a full-range position.
      Amplification ≈ sqrt(upper / lower) normalised.
    - Out-of-range: position is fully one-sided.  IL is capped at the
      value at whichever boundary the price breached.
    """
    if lower_bound <= 0 or upper_bound <= 0:
        raise ValueError("lower_bound and upper_bound must be positive")
    if lower_bound >= upper_bound:
        raise ValueError("lower_bound must be strictly less than upper_bound")
    if initial_price_ratio <= 0:
        raise ValueError("initial_price_ratio must be positive")
    if current_price_ratio <= 0:
        raise ValueError("current_price_ratio must be positive")

    # Normalise bounds relative to initial price so lb & ub are multipliers
    lb = lower_bound / initial_price_ratio
    ub = upper_bound / initial_price_ratio
    # price ratio relative to initial
    r = current_price_ratio / initial_price_ratio

    out_of_range = r < lb or r > ub

    if out_of_range:
        # Position is frozen at the boundary it breached: IL no longer changes
        if r < lb:
            boundary_r = lb
        else:
            boundary_r = ub
        il = _il_xy(boundary_r) if boundary_r > 0 else -1.0
        return il, True

    # In range — amplified IL
    # Amplification factor: sqrt(ub/lb).
    # Narrower range → higher amplification, consistent with Uniswap V3
    # intuition that capital is leveraged.
    amp = math.sqrt(ub / lb) if lb > 0 else 1.0
    base_il = _il_xy(r)
    amplified = max(-1.0, base_il * amp)
    return amplified, False


# ── Label & flag helpers ──────────────────────────────────────────────────────


def _il_label(il_abs_pct: float) -> str:
    """
    Categorise absolute IL percentage:
      MINIMAL  < 0.1 %
      LOW      < 0.5 %
      MODERATE < 2.0 %
      HIGH     < 5.0 %
      SEVERE   ≥ 5.0 %
    """
    if il_abs_pct < 0.1:
        return "MINIMAL"
    if il_abs_pct < 0.5:
        return "LOW"
    if il_abs_pct < 2.0:
        return "MODERATE"
    if il_abs_pct < 5.0:
        return "HIGH"
    return "SEVERE"


# ── Per-pool computation ──────────────────────────────────────────────────────


def _compute_pool(pool: dict, config: dict) -> dict:
    """Compute IL metrics for a single pool descriptor."""
    name = pool.get("name", "unknown")
    token_a = pool.get("token_a", "TOKEN_A")
    token_b = pool.get("token_b", "TOKEN_B")
    initial_price_ratio = float(pool.get("initial_price_ratio", 1.0))
    current_price_ratio = float(pool.get("current_price_ratio", 1.0))
    liquidity_usd = float(pool.get("liquidity_usd", 0.0))
    fee_tier_pct = float(pool.get("fee_tier_pct", 0.3))
    fee_income_30d_usd = float(pool.get("fee_income_30d_usd", 0.0))
    pool_type = str(pool.get("pool_type", "xy")).lower()
    price_range = pool.get("price_range") or {}

    if initial_price_ratio <= 0:
        raise ValueError(f"Pool '{name}': initial_price_ratio must be positive")
    if current_price_ratio <= 0:
        raise ValueError(f"Pool '{name}': current_price_ratio must be positive")

    # Price ratio (dimensionless: current / initial)
    r = current_price_ratio / initial_price_ratio
    out_of_range = False

    if pool_type == "stable":
        il_fraction = _il_stable(r)
    elif pool_type == "concentrated":
        lb = float(price_range.get("lower_bound", initial_price_ratio * 0.5))
        ub = float(price_range.get("upper_bound", initial_price_ratio * 2.0))
        il_fraction, out_of_range = _il_concentrated(
            initial_price_ratio, current_price_ratio, lb, ub
        )
    else:
        # Default: xy constant-product
        pool_type = "xy"
        il_fraction = _il_xy(r)

    il_pct = il_fraction * 100.0          # percentage, ≤ 0
    il_abs_pct = abs(il_pct)
    il_usd = il_fraction * liquidity_usd  # USD loss (≤ 0)
    il_abs_usd = abs(il_usd)

    # Fee offset & net P&L
    fee_offset_usd = fee_income_30d_usd
    net_pnl_usd = fee_offset_usd + il_usd  # il_usd is negative

    # Break-even: days of fees needed to cover IL loss
    daily_fee = fee_income_30d_usd / 30.0 if fee_income_30d_usd > 0 else 0.0
    if il_abs_usd == 0.0:
        break_even_days: Optional[float] = 0.0
    elif daily_fee > 0:
        break_even_days = il_abs_usd / daily_fee
    else:
        break_even_days = None  # infinite / not reachable

    label = _il_label(il_abs_pct)

    # Flags
    flags = []
    if fee_income_30d_usd > il_abs_usd:
        flags.append("FEE_COVERS_IL")
    if out_of_range:
        flags.append("OUT_OF_RANGE")
    if il_abs_pct >= 5.0:
        flags.append("HIGH_IL")
    if break_even_days is not None and 0 < break_even_days < 30:
        flags.append("SHORT_BREAKEVEN")

    return {
        "name": name,
        "token_a": token_a,
        "token_b": token_b,
        "pool_type": pool_type,
        "initial_price_ratio": initial_price_ratio,
        "current_price_ratio": current_price_ratio,
        "price_ratio_change": round(r, 8),
        "liquidity_usd": liquidity_usd,
        "fee_tier_pct": fee_tier_pct,
        "fee_income_30d_usd": fee_income_30d_usd,
        "il_pct": round(il_pct, 6),
        "il_usd": round(il_usd, 4),
        "fee_offset_usd": round(fee_offset_usd, 4),
        "net_pnl_usd": round(net_pnl_usd, 4),
        "break_even_days": round(break_even_days, 4) if break_even_days is not None else None,
        "il_label": label,
        "flags": flags,
        "out_of_range": out_of_range,
    }


# ── Main class ────────────────────────────────────────────────────────────────


class DeFiAMMImpermanentLossSimulator:
    """
    Advisory-only simulator for Impermanent Loss in DeFi AMM pools.

    Supported pool types
    --------------------
    - ``"xy"``           — Uniswap V2 constant-product (default)
    - ``"stable"``       — Curve-style stable-swap (≈10 % of xy IL)
    - ``"concentrated"`` — Uniswap V3 concentrated liquidity

    Usage
    -----
    ::
        sim = DeFiAMMImpermanentLossSimulator()
        result = sim.simulate(pools=[...], config={})

    The ``config`` dict accepts:
    - ``"write_log"`` (bool, default ``True``) — whether to append to the
      ring-buffer log file.
    """

    def __init__(self, data_file: str = _DEFAULT_DATA_FILE) -> None:
        self.data_file = data_file

    # ── public API ────────────────────────────────────────────────────────────

    def simulate(self, pools: list, config: dict) -> dict:
        """
        Simulate IL for each pool in *pools*.

        Parameters
        ----------
        pools : list[dict]
            Each dict must contain at minimum:
            ``name``, ``initial_price_ratio``, ``current_price_ratio``,
            ``liquidity_usd``, ``fee_income_30d_usd``.
            Optional: ``pool_type``, ``fee_tier_pct``, ``price_range``.
        config : dict
            Runtime configuration.

        Returns
        -------
        dict
            Keys: ``timestamp``, ``pools`` (list of results), ``errors``,
            ``aggregates``.
        """
        if not isinstance(pools, list):
            raise TypeError(f"pools must be a list, got {type(pools).__name__}")
        if not isinstance(config, dict):
            raise TypeError(f"config must be a dict, got {type(config).__name__}")

        write_log = config.get("write_log", True)
        results = []
        errors = []

        for pool in pools:
            if not isinstance(pool, dict):
                errors.append({"pool": str(pool), "error": "not a dict"})
                continue
            try:
                results.append(_compute_pool(pool, config))
            except Exception as exc:
                errors.append({"pool": pool.get("name", "unknown"), "error": str(exc)})

        # Aggregates
        total_il_usd = sum(r["il_usd"] for r in results)
        total_fee_income_usd = sum(r["fee_income_30d_usd"] for r in results)

        valid_be = [r["break_even_days"] for r in results if r["break_even_days"] is not None]
        avg_be = sum(valid_be) / len(valid_be) if valid_be else None

        worst_il_pool = None
        best_net_pool = None
        if results:
            worst_il_pool = min(results, key=lambda r: r["il_pct"])["name"]
            best_net_pool = max(results, key=lambda r: r["net_pnl_usd"])["name"]

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        output = {
            "timestamp": timestamp,
            "pools": results,
            "errors": errors,
            "aggregates": {
                "worst_il_pool": worst_il_pool,
                "best_net_pool": best_net_pool,
                "total_il_usd": round(total_il_usd, 4),
                "total_fee_income_usd": round(total_fee_income_usd, 4),
                "average_break_even_days": round(avg_be, 4) if avg_be is not None else None,
                "pool_count": len(results),
                "error_count": len(errors),
            },
        }

        if write_log:
            _append_log(
                self.data_file,
                {
                    "timestamp": timestamp,
                    "pool_count": len(results),
                    "total_il_usd": output["aggregates"]["total_il_usd"],
                    "total_fee_income_usd": output["aggregates"]["total_fee_income_usd"],
                    "error_count": len(errors),
                },
            )

        return output

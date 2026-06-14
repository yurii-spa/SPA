"""
MP-1019: ProtocolDeFiPriceImpactDepthAnalyzer
Analyzes market depth and price impact for various DeFi pool types across
multiple trade sizes.
"""

import json
import os
import time
import tempfile
from typing import Any

# --- constants -----------------------------------------------------------

# Pool types
POOL_V2 = "uniswap_v2"
POOL_V3 = "uniswap_v3_concentrated"
POOL_CURVE = "curve_stable"
POOL_BALANCER = "balancer_weighted"

# Default amplification for Curve if not provided
DEFAULT_CURVE_AMP = 100.0

# Default trade sizes if not provided in pool
DEFAULT_TRADE_SIZES = [1_000.0, 10_000.0, 100_000.0, 1_000_000.0]

# Impact thresholds (percent)
IMPACT_HALF_PERCENT = 0.5
IMPACT_ONE_PERCENT = 1.0
IMPACT_THREE_PERCENT = 3.0

# Depth label thresholds (impact % at the given trade_size)
INSTITUTIONAL_DEPTH_IMPACT_MAX = 0.5   # 1M with <0.5% impact
DEEP_MARKET_IMPACT_MAX = 0.5           # 100K with <0.5% impact
MEDIUM_DEPTH_IMPACT_MAX = 0.5          # 10K with <0.5% impact
RETAIL_ONLY_IMPACT_MIN = 1.0           # 10K with >1% impact
SHALLOW_IMPACT_MIN = 0.5               # 1K with >0.5% impact

# Concentrated liquidity advantage: v3 depth_100k better than some threshold score
CONCENTRATED_ADVANTAGE_SCORE_MIN = 70.0

LOG_CAP = 100

# --- helpers -------------------------------------------------------------

def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den != 0.0 else default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _impact_to_depth_score(impact_pct: float) -> float:
    """Convert price impact % → depth score 0-100. Lower impact → higher score."""
    safe_impact = max(0.0, impact_pct)  # guard against negative values
    return _clamp(100.0 / (1.0 + safe_impact), 0.0, 100.0)


def _atomic_write(path: str, data: Any) -> None:
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
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


def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


# --- price impact formulas -----------------------------------------------

def _impact_v2(trade_size: float, token_a_reserve: float, token_b_reserve: float) -> float:
    """
    Uniswap V2 (x*y=k) price impact.
    Sells trade_size worth of token_a.
    impact = trade_size / (token_a_reserve + trade_size)
    """
    if token_a_reserve <= 0 or trade_size <= 0:
        return 0.0
    return _clamp(trade_size / (token_a_reserve + trade_size) * 100.0, 0.0, 99.99)


def _impact_v3(trade_size: float, active_liquidity: float) -> float:
    """
    Uniswap V3 concentrated: use active_liquidity/2 as effective reserve per side.
    """
    if active_liquidity <= 0 or trade_size <= 0:
        return 0.0
    effective_reserve = active_liquidity / 2.0
    return _clamp(trade_size / (effective_reserve + trade_size) * 100.0, 0.0, 99.99)


def _impact_curve(trade_size: float, tvl: float, amp: float) -> float:
    """
    Curve stableswap approximation.
    Higher A factor → lower impact (curve is flatter).
    impact ≈ trade_size / (tvl * amp_factor + trade_size)
    where amp_factor is scaled: high A → low slippage.
    """
    if tvl <= 0 or trade_size <= 0:
        return 0.0
    amp_effective = max(amp, 1.0)
    return _clamp(trade_size / (tvl * amp_effective + trade_size) * 100.0, 0.0, 99.99)


def _impact_balancer(trade_size: float, token_a_reserve: float) -> float:
    """
    Balancer weighted (50/50 assumption): same formula as V2 using token_a_reserve.
    """
    return _impact_v2(trade_size, token_a_reserve, token_a_reserve)


def _compute_pool_impact(pool: dict, trade_size: float) -> float:
    """Route to correct impact formula based on pool_type."""
    pool_type = pool.get("pool_type", POOL_V2)
    tvl = float(pool.get("tvl_usd", 0.0))
    active_liq = float(pool.get("active_liquidity_usd", tvl))
    res_a = float(pool.get("token_a_reserve_usd", tvl / 2.0))
    res_b = float(pool.get("token_b_reserve_usd", tvl / 2.0))
    amp = float(pool.get("curve_amplification", DEFAULT_CURVE_AMP))

    if pool_type == POOL_V3:
        return _impact_v3(trade_size, active_liq)
    elif pool_type == POOL_CURVE:
        return _impact_curve(trade_size, tvl, amp)
    elif pool_type == POOL_BALANCER:
        return _impact_balancer(trade_size, res_a)
    else:  # default: uniswap_v2
        return _impact_v2(trade_size, res_a, res_b)


# --- main class ----------------------------------------------------------

class ProtocolDeFiPriceImpactDepthAnalyzer:
    """
    Analyzes DeFi pool depth through price impact at multiple trade sizes.

    Usage:
        analyzer = ProtocolDeFiPriceImpactDepthAnalyzer()
        result = analyzer.analyze(pools, config)
    """

    def __init__(self, log_path: str = "data/price_impact_depth_log.json"):
        self.log_path = log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, pools: list, config: dict) -> dict:
        """
        Analyze market depth and price impact for each pool.

        Args:
            pools:  list of pool dicts
            config: optional overrides (trade_sizes, etc.)

        Returns:
            dict with 'pools' (scored entries) and 'aggregates'.
        """
        global_trade_sizes = config.get("trade_sizes_usd", DEFAULT_TRADE_SIZES)

        analyzed = []
        for pool in pools:
            analyzed.append(self._analyze_pool(pool, config, global_trade_sizes))

        aggregates = self._compute_aggregates(analyzed)

        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pools": analyzed,
            "aggregates": aggregates,
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Per-pool analysis
    # ------------------------------------------------------------------

    def _analyze_pool(self, pool: dict, config: dict, global_trade_sizes: list) -> dict:
        name = pool.get("name", "unknown")
        protocol = pool.get("protocol", "unknown")
        token_pair = pool.get("token_pair", "UNKNOWN/UNKNOWN")
        pool_type = pool.get("pool_type", POOL_V2)
        fee_tier_bps = float(pool.get("fee_tier_bps", 30))

        # Use pool-level trade sizes, fall back to global
        trade_sizes = pool.get("trade_sizes_usd", global_trade_sizes)
        if not trade_sizes:
            trade_sizes = DEFAULT_TRADE_SIZES

        # Compute impact for each trade size
        impact_details = []
        for size in trade_sizes:
            impact_pct = _compute_pool_impact(pool, float(size))
            depth_score = _impact_to_depth_score(impact_pct)
            slippage_cost = impact_pct / 100.0 * float(size)
            # effective_execution_price is a factor: 1 - impact
            effective_execution_price = 1.0 - impact_pct / 100.0
            impact_details.append({
                "trade_size_usd": float(size),
                "price_impact_pct": round(impact_pct, 6),
                "effective_execution_price": round(effective_execution_price, 6),
                "slippage_cost_usd": round(slippage_cost, 4),
                "market_depth_score": round(depth_score, 4),
            })

        # Map from standard sizes to scores/impacts
        size_impact_map = {int(d["trade_size_usd"]): d for d in impact_details}
        impact_1k = size_impact_map.get(1_000, {})
        impact_10k = size_impact_map.get(10_000, {})
        impact_100k = size_impact_map.get(100_000, {})
        impact_1m = size_impact_map.get(1_000_000, {})

        depth_1k_score = impact_1k.get("market_depth_score", 0.0)
        depth_10k_score = impact_10k.get("market_depth_score", 0.0)
        depth_100k_score = impact_100k.get("market_depth_score", 0.0)
        depth_1m_score = impact_1m.get("market_depth_score", 0.0)

        pct_1k = impact_1k.get("price_impact_pct", 99.0)
        pct_10k = impact_10k.get("price_impact_pct", 99.0)
        pct_100k = impact_100k.get("price_impact_pct", 99.0)
        pct_1m = impact_1m.get("price_impact_pct", 99.0)

        # best_size_tier: max standard size with < 0.5% impact
        best_size_tier = self._best_size_tier(pct_1k, pct_10k, pct_100k, pct_1m)

        # large_trade_viability: max standard size with < 1% impact
        large_trade_viability = self._large_trade_viability(pct_1k, pct_10k, pct_100k, pct_1m)

        # depth label
        depth_label = self._depth_label(pct_1k, pct_10k, pct_100k, pct_1m)

        # flags
        flags = self._compute_flags(
            pool_type=pool_type,
            pct_10k=pct_10k,
            pct_100k=pct_100k,
            pct_1m=pct_1m,
            depth_100k_score=depth_100k_score,
            best_size_tier=best_size_tier,
            amp=float(pool.get("curve_amplification", DEFAULT_CURVE_AMP)),
        )

        return {
            "name": name,
            "protocol": protocol,
            "token_pair": token_pair,
            "pool_type": pool_type,
            "tvl_usd": float(pool.get("tvl_usd", 0.0)),
            "fee_tier_bps": fee_tier_bps,
            # per-size breakdown
            "impact_details": impact_details,
            # summary scores at standard sizes
            "depth_1k_score": depth_1k_score,
            "depth_10k_score": depth_10k_score,
            "depth_100k_score": depth_100k_score,
            "depth_1m_score": depth_1m_score,
            # viability
            "best_size_tier": best_size_tier,
            "large_trade_viability": large_trade_viability,
            # classification
            "depth_label": depth_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Tier helpers
    # ------------------------------------------------------------------

    def _best_size_tier(self, p1k: float, p10k: float, p100k: float, p1m: float) -> float:
        """Max standard size with < 0.5% impact."""
        if p1m < IMPACT_HALF_PERCENT:
            return 1_000_000.0
        if p100k < IMPACT_HALF_PERCENT:
            return 100_000.0
        if p10k < IMPACT_HALF_PERCENT:
            return 10_000.0
        if p1k < IMPACT_HALF_PERCENT:
            return 1_000.0
        return 0.0

    def _large_trade_viability(self, p1k: float, p10k: float, p100k: float, p1m: float) -> float:
        """Max standard size with < 1% impact."""
        if p1m < IMPACT_ONE_PERCENT:
            return 1_000_000.0
        if p100k < IMPACT_ONE_PERCENT:
            return 100_000.0
        if p10k < IMPACT_ONE_PERCENT:
            return 10_000.0
        if p1k < IMPACT_ONE_PERCENT:
            return 1_000.0
        return 0.0

    def _depth_label(self, p1k: float, p10k: float, p100k: float, p1m: float) -> str:
        if p1m < INSTITUTIONAL_DEPTH_IMPACT_MAX:
            return "INSTITUTIONAL_DEPTH"
        if p100k < DEEP_MARKET_IMPACT_MAX:
            return "DEEP_MARKET"
        if p10k < MEDIUM_DEPTH_IMPACT_MAX:
            return "MEDIUM_DEPTH"
        if p10k > RETAIL_ONLY_IMPACT_MIN:
            return "RETAIL_ONLY"
        if p1k > SHALLOW_IMPACT_MIN:
            return "SHALLOW"
        return "MEDIUM_DEPTH"

    def _compute_flags(
        self,
        pool_type: str,
        pct_10k: float,
        pct_100k: float,
        pct_1m: float,
        depth_100k_score: float,
        best_size_tier: float,
        amp: float,
    ) -> list:
        flags = []

        # CONCENTRATED_LIQUIDITY_ADVANTAGE: v3 AND good 100k depth
        if pool_type == POOL_V3 and depth_100k_score >= CONCENTRATED_ADVANTAGE_SCORE_MIN:
            flags.append("CONCENTRATED_LIQUIDITY_ADVANTAGE")

        # STABLE_CURVE_EFFICIENCY: curve AND 1M impact < 0.3%
        if pool_type == POOL_CURVE and pct_1m < 0.3:
            flags.append("STABLE_CURVE_EFFICIENCY")

        # WHALE_FRIENDLY: 1M impact < 1%
        if pct_1m < IMPACT_ONE_PERCENT:
            flags.append("WHALE_FRIENDLY")

        # RETAIL_ONLY_POOL: 10K > 1% impact
        if pct_10k > RETAIL_ONLY_IMPACT_MIN:
            flags.append("RETAIL_ONLY_POOL")

        # DEEP_FOR_SIZE: best_size_tier > 100K
        if best_size_tier > 100_000.0:
            flags.append("DEEP_FOR_SIZE")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, analyzed: list) -> dict:
        if not analyzed:
            return {
                "deepest_pool": None,
                "shallowest_pool": None,
                "avg_depth_score": 0.0,
                "institutional_depth_count": 0,
                "shallow_count": 0,
                "total_pools": 0,
            }

        # Sort by 1M depth score for "deepest"
        by_depth = sorted(analyzed, key=lambda p: p["depth_1m_score"], reverse=True)
        deepest_pool = by_depth[0]["name"]
        shallowest_pool = by_depth[-1]["name"]

        avg_depth = sum(p["depth_1m_score"] for p in analyzed) / len(analyzed)
        institutional_count = sum(1 for p in analyzed if p["depth_label"] == "INSTITUTIONAL_DEPTH")
        shallow_count = sum(1 for p in analyzed if p["depth_label"] in ("SHALLOW", "RETAIL_ONLY"))

        return {
            "deepest_pool": deepest_pool,
            "shallowest_pool": shallowest_pool,
            "avg_depth_score": round(avg_depth, 4),
            "institutional_depth_count": institutional_count,
            "shallow_count": shallow_count,
            "total_pools": len(analyzed),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        log = _load_log(self.log_path)
        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]
        _atomic_write(self.log_path, log)

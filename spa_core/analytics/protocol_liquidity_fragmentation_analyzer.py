"""
MP-923 ProtocolLiquidityFragmentationAnalyzer
----------------------------------------------
Analyzes liquidity fragmentation of a token across DEX pools and chains.

Input per pool:
  token_pair, dex, chain, tvl_usd, volume_24h_usd, fee_tier_pct,
  price_usd, slippage_1k_usd

Per-pair outputs:
  total_tvl_usd, hhi_by_dex, hhi_by_chain, dominant_pool,
  fragmentation_score (0-100, high = more fragmented),
  best_execution_pool (lowest slippage_1k_usd),
  price_deviation_pct (max price spread across pools),
  fragmentation_label (UNIFIED / SLIGHTLY_FRAGMENTED / FRAGMENTED /
                       HIGHLY_FRAGMENTED / CHAOTIC),
  flags (PRICE_DEVIATION, CHAIN_FRAGMENTED, DEX_MONOPOLY,
         LOW_CROSS_CHAIN_BRIDGE)

Aggregate outputs (across all pairs):
  most_fragmented_pair, most_unified_pair, total_tvl, average_fragmentation,
  chaotic_count

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import math
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "liquidity_fragmentation_log.json"
)
_LOG_CAP = 100

# Flag thresholds
_PRICE_DEVIATION_THRESHOLD_PCT = 0.5   # >0.5% max price spread → PRICE_DEVIATION
_CHAIN_FRAGMENTED_THRESHOLD    = 3     # >3 unique chains → CHAIN_FRAGMENTED
_DEX_MONOPOLY_SHARE_PCT        = 80.0  # one DEX >80% TVL share → DEX_MONOPOLY
_LOW_BRIDGE_TVL_SHARE_PCT      = 1.0   # a secondary chain <1% total TVL → LOW_CROSS_CHAIN_BRIDGE

# Fragmentation label bands [upper_bound, label]
_FRAG_BANDS = [
    (20.0,  "UNIFIED"),
    (40.0,  "SLIGHTLY_FRAGMENTED"),
    (60.0,  "FRAGMENTED"),
    (80.0,  "HIGHLY_FRAGMENTED"),
    (101.0, "CHAOTIC"),
]

# Composite weight for fragmentation score
_W_DEX_FRAG    = 0.45  # contribution from DEX spread
_W_CHAIN_FRAG  = 0.30  # contribution from chain spread
_W_CHAIN_COUNT = 0.15  # bonus for many chains
_W_POOL_COUNT  = 0.10  # bonus for many pools


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_hhi(shares_pct: list[float]) -> float:
    """
    Compute Herfindahl-Hirschman Index from list of percentage shares.

    Parameters
    ----------
    shares_pct : list[float]
        Each element is a share in [0, 100].

    Returns
    -------
    float
        HHI in range [0, 10000].
          10000 = pure monopoly (one player 100%)
          0     = theoretically infinite players, each 0%
    """
    return sum(s * s for s in shares_pct)


def _fragmentation_label(score: float) -> str:
    """Convert fragmentation score (0-100) to label."""
    for upper, label in _FRAG_BANDS:
        if score < upper:
            return label
    return "CHAOTIC"


def _atomic_append_log(log_path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array; atomic write via tmp+replace."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > cap:
        data = data[-cap:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Analyzer class
# ---------------------------------------------------------------------------

class ProtocolLiquidityFragmentationAnalyzer:
    """
    Analyzes how liquidity for a token pair is fragmented across pools,
    DEXes, and chains.

    Usage::

        analyzer = ProtocolLiquidityFragmentationAnalyzer()
        result = analyzer.analyze(pools, config)
    """

    def __init__(
        self,
        log_path: str | None = None,
        log_cap: int = _LOG_CAP,
    ) -> None:
        self._log_path = log_path or _LOG_PATH_DEFAULT
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    # Per-pair analysis helpers (static, testable individually)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_hhi_by_dex(pools: list[dict]) -> float:
        """
        Compute HHI of TVL concentration by DEX.

        Returns HHI in [0, 10000]; higher = more concentrated on one DEX.
        """
        if not pools:
            return 0.0

        total = sum(max(0.0, float(p.get("tvl_usd", 0))) for p in pools)
        if total == 0:
            return 0.0

        dex_tvl: dict[str, float] = {}
        for p in pools:
            dex = str(p.get("dex", ""))
            dex_tvl[dex] = dex_tvl.get(dex, 0.0) + max(0.0, float(p.get("tvl_usd", 0)))

        shares = [(v / total * 100.0) for v in dex_tvl.values()]
        return _compute_hhi(shares)

    @staticmethod
    def compute_hhi_by_chain(pools: list[dict]) -> float:
        """
        Compute HHI of TVL concentration by chain.

        Returns HHI in [0, 10000]; higher = more concentrated on one chain.
        """
        if not pools:
            return 0.0

        total = sum(max(0.0, float(p.get("tvl_usd", 0))) for p in pools)
        if total == 0:
            return 0.0

        chain_tvl: dict[str, float] = {}
        for p in pools:
            chain = str(p.get("chain", ""))
            chain_tvl[chain] = chain_tvl.get(chain, 0.0) + max(0.0, float(p.get("tvl_usd", 0)))

        shares = [(v / total * 100.0) for v in chain_tvl.values()]
        return _compute_hhi(shares)

    @staticmethod
    def compute_price_deviation_pct(pools: list[dict]) -> float:
        """
        Compute max price deviation across pools (%).

        Returns ((max_price - min_price) / min_price) * 100
        or 0.0 if fewer than 2 pools or all prices are zero.
        """
        prices = [
            float(p.get("price_usd", 0))
            for p in pools
            if float(p.get("price_usd", 0)) > 0
        ]
        if len(prices) < 2:
            return 0.0
        min_p = min(prices)
        max_p = max(prices)
        if min_p == 0:
            return 0.0
        return ((max_p - min_p) / min_p) * 100.0

    @staticmethod
    def compute_fragmentation_score(
        hhi_by_dex: float,
        hhi_by_chain: float,
        unique_chains: int,
        pool_count: int,
    ) -> float:
        """
        Compute fragmentation score (0-100).

        High score = more fragmented (liquidity spread many places).
        Low score  = unified (liquidity concentrated on one DEX/chain).

        Components:
        - DEX fragmentation: 1 - (HHI_dex / 10000) → 0-1 scaled to 0-45
        - Chain fragmentation: 1 - (HHI_chain / 10000) → 0-1 scaled to 0-30
        - Chain count bonus: more chains = more fragmented → 0-15
        - Pool count bonus: many pools = more fragmented → 0-10
        """
        hhi_dex   = max(0.0, min(10000.0, hhi_by_dex))
        hhi_chain = max(0.0, min(10000.0, hhi_by_chain))

        dex_frag   = (1.0 - hhi_dex   / 10000.0) * 100.0 * _W_DEX_FRAG
        chain_frag = (1.0 - hhi_chain / 10000.0) * 100.0 * _W_CHAIN_FRAG

        # chain count: 1 chain → 0, 2 → ~5, 4 → ~10, 6+ → 15
        chain_bonus = min(15.0, max(0.0, unique_chains - 1) * 4.0) * (_W_CHAIN_COUNT / 0.15)
        # pool count: 1 → 0, 5 → ~5, 10+ → 10
        pool_bonus = min(10.0, max(0.0, pool_count - 1) * 1.5) * (_W_POOL_COUNT / 0.10)

        return min(100.0, max(0.0, dex_frag + chain_frag + chain_bonus + pool_bonus))

    @staticmethod
    def compute_flags(
        pools: list[dict],
        price_deviation_pct: float,
        hhi_by_dex: float,
    ) -> list:
        """Compute fragmentation warning flags for a token pair."""
        flags: list[str] = []

        # Price deviation flag
        if price_deviation_pct > _PRICE_DEVIATION_THRESHOLD_PCT:
            flags.append("PRICE_DEVIATION")

        # Chain fragmentation flag
        unique_chains = len({str(p.get("chain", "")) for p in pools})
        if unique_chains > _CHAIN_FRAGMENTED_THRESHOLD:
            flags.append("CHAIN_FRAGMENTED")

        # DEX monopoly flag: one DEX holds >80% of TVL
        total = sum(max(0.0, float(p.get("tvl_usd", 0))) for p in pools)
        if total > 0:
            dex_tvl: dict[str, float] = {}
            for p in pools:
                dex = str(p.get("dex", ""))
                dex_tvl[dex] = dex_tvl.get(dex, 0.0) + max(0.0, float(p.get("tvl_usd", 0)))
            max_dex_share = max(v / total * 100.0 for v in dex_tvl.values())
            if max_dex_share > _DEX_MONOPOLY_SHARE_PCT:
                flags.append("DEX_MONOPOLY")

        # Low cross-chain bridge flag: multiple chains, but at least one chain
        # has < 1% of total TVL (thin cross-chain liquidity)
        if unique_chains > 1 and total > 0:
            chain_tvl: dict[str, float] = {}
            for p in pools:
                chain = str(p.get("chain", ""))
                chain_tvl[chain] = chain_tvl.get(chain, 0.0) + max(0.0, float(p.get("tvl_usd", 0)))
            chain_shares = [v / total * 100.0 for v in chain_tvl.values()]
            if any(s < _LOW_BRIDGE_TVL_SHARE_PCT for s in chain_shares):
                flags.append("LOW_CROSS_CHAIN_BRIDGE")

        return flags

    # ------------------------------------------------------------------
    # Per-pair analysis
    # ------------------------------------------------------------------

    def _analyze_pair(self, token_pair: str, pools: list[dict]) -> dict:
        """Analyze one token pair's liquidity fragmentation."""
        if not pools:
            return {
                "token_pair":           token_pair,
                "pool_count":           0,
                "total_tvl_usd":        0.0,
                "hhi_by_dex":           0.0,
                "hhi_by_chain":         0.0,
                "dominant_pool":        None,
                "fragmentation_score":  0.0,
                "best_execution_pool":  None,
                "price_deviation_pct":  0.0,
                "fragmentation_label":  "UNIFIED",
                "flags":                [],
            }

        total_tvl    = sum(max(0.0, float(p.get("tvl_usd", 0))) for p in pools)
        hhi_dex      = self.compute_hhi_by_dex(pools)
        hhi_chain    = self.compute_hhi_by_chain(pools)
        price_dev    = self.compute_price_deviation_pct(pools)

        # Dominant pool = highest TVL
        dominant = max(pools, key=lambda p: float(p.get("tvl_usd", 0)))
        dominant_id = f"{dominant.get('dex','?')}@{dominant.get('chain','?')}"

        # Best execution pool = lowest slippage_1k_usd (tie-break: higher TVL)
        valid_slip = [p for p in pools if float(p.get("slippage_1k_usd", math.inf)) >= 0]
        if valid_slip:
            best = min(valid_slip,
                       key=lambda p: (float(p.get("slippage_1k_usd", math.inf)),
                                      -float(p.get("tvl_usd", 0))))
            best_id = f"{best.get('dex','?')}@{best.get('chain','?')}"
        else:
            best_id = None

        unique_chains = len({str(p.get("chain", "")) for p in pools})
        frag_score    = self.compute_fragmentation_score(hhi_dex, hhi_chain, unique_chains, len(pools))
        frag_label    = _fragmentation_label(frag_score)
        flags         = self.compute_flags(pools, price_dev, hhi_dex)

        return {
            "token_pair":           token_pair,
            "pool_count":           len(pools),
            "total_tvl_usd":        round(total_tvl, 2),
            "hhi_by_dex":           round(hhi_dex, 2),
            "hhi_by_chain":         round(hhi_chain, 2),
            "dominant_pool":        dominant_id,
            "fragmentation_score":  round(frag_score, 4),
            "best_execution_pool":  best_id,
            "price_deviation_pct":  round(price_dev, 6),
            "fragmentation_label":  frag_label,
            "flags":                flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, pools: list, config: dict) -> dict:
        """
        Analyze liquidity fragmentation across all token pairs in *pools*.

        Parameters
        ----------
        pools : list[dict]
            List of pool dicts. Multiple pools can share the same token_pair.
        config : dict
            Optional config:
              - log_enabled (bool, default True): write to ring-buffer log
              - log_path (str): override default log path

        Returns
        -------
        dict with keys:
          - pairs: list of per-pair analysis dicts
          - aggregates: most_fragmented_pair, most_unified_pair, total_tvl,
                        average_fragmentation, chaotic_count
          - timestamp: ISO-8601 UTC string
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not pools:
            result = {
                "pairs": [],
                "aggregates": {
                    "most_fragmented_pair": None,
                    "most_unified_pair":    None,
                    "total_tvl":            0.0,
                    "average_fragmentation": 0.0,
                    "chaotic_count":        0,
                },
                "timestamp": timestamp,
            }
            if config.get("log_enabled", True):
                self._try_log(result, config)
            return result

        # Group pools by token_pair
        pair_pools: dict[str, list] = {}
        for pool in pools:
            pair = str(pool.get("token_pair", "UNKNOWN"))
            pair_pools.setdefault(pair, []).append(pool)

        analyzed_pairs = [
            self._analyze_pair(token_pair, grp_pools)
            for token_pair, grp_pools in pair_pools.items()
        ]

        total_tvl       = sum(p["total_tvl_usd"] for p in analyzed_pairs)
        chaotic_count   = sum(1 for p in analyzed_pairs if p["fragmentation_label"] == "CHAOTIC")
        avg_frag        = (
            sum(p["fragmentation_score"] for p in analyzed_pairs) / len(analyzed_pairs)
        )

        most_frag  = max(analyzed_pairs, key=lambda p: p["fragmentation_score"])
        most_unif  = min(analyzed_pairs, key=lambda p: p["fragmentation_score"])

        result = {
            "pairs": analyzed_pairs,
            "aggregates": {
                "most_fragmented_pair":  most_frag["token_pair"],
                "most_unified_pair":     most_unif["token_pair"],
                "total_tvl":             round(total_tvl, 2),
                "average_fragmentation": round(avg_frag, 4),
                "chaotic_count":         chaotic_count,
            },
            "timestamp": timestamp,
        }

        if config.get("log_enabled", True):
            self._try_log(result, config)

        return result

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _try_log(self, result: dict, config: dict) -> None:
        """Ring-buffer log write; silently swallow errors (advisory)."""
        log_path = config.get("log_path", self._log_path)
        try:
            _atomic_append_log(log_path, result, self._log_cap)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample_pools = [
        # WETH/USDC
        {"token_pair": "WETH/USDC", "dex": "Uniswap V3", "chain": "Ethereum",
         "tvl_usd": 80_000_000, "volume_24h_usd": 5_000_000,
         "fee_tier_pct": 0.05, "price_usd": 3820.10, "slippage_1k_usd": 0.002},
        {"token_pair": "WETH/USDC", "dex": "Curve", "chain": "Ethereum",
         "tvl_usd": 15_000_000, "volume_24h_usd": 800_000,
         "fee_tier_pct": 0.04, "price_usd": 3820.25, "slippage_1k_usd": 0.003},
        {"token_pair": "WETH/USDC", "dex": "Uniswap V3", "chain": "Arbitrum",
         "tvl_usd": 12_000_000, "volume_24h_usd": 600_000,
         "fee_tier_pct": 0.05, "price_usd": 3819.80, "slippage_1k_usd": 0.004},
        {"token_pair": "WETH/USDC", "dex": "Velodrome", "chain": "Optimism",
         "tvl_usd": 3_000_000, "volume_24h_usd": 150_000,
         "fee_tier_pct": 0.03, "price_usd": 3821.50, "slippage_1k_usd": 0.012},
        # stETH/ETH
        {"token_pair": "stETH/ETH", "dex": "Curve", "chain": "Ethereum",
         "tvl_usd": 500_000_000, "volume_24h_usd": 20_000_000,
         "fee_tier_pct": 0.04, "price_usd": 0.9998, "slippage_1k_usd": 0.0001},
    ]

    analyzer = ProtocolLiquidityFragmentationAnalyzer()
    result = analyzer.analyze(sample_pools, {"log_enabled": False})
    print(json.dumps(result, indent=2))
    sys.exit(0)

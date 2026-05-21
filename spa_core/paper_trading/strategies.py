"""
SPA Strategy Registry — v0.10
Реестр торговых стратегий для paper trading.

Каждая стратегия задаёт:
  - целевой диапазон APY
  - предпочтительные тиеры (T1/T2)
  - лимит позиций
  - кэш-буфер
  - порог ребалансировки
"""

STRATEGIES: dict[str, dict] = {
    "v1_passive": {
        "name": "v1 — Conservative Passive",
        "description": (
            "T1-only allocations, max 40% per protocol, "
            "5% cash buffer, APY 1-10% target range"
        ),
        "config": {
            "target_apy_min": 1.0,
            "target_apy_max": 10.0,
            "preferred_tiers": ["T1"],
            "max_positions": 5,
            "rebalance_threshold_pct": 0.5,   # rebalance if allocation drifts >0.5%
            "cash_buffer_pct": 0.05,
            # Per-protocol concentration caps (fraction of total capital)
            "max_concentration_t1": 0.40,
            "max_concentration_t2": 0.20,
        },
    },
    "v2_aggressive": {
        "name": "v2 — Growth Aggressive",
        "description": (
            "T1+T2 allocations, chases higher APY, "
            "3% cash buffer, APY 3-20% target range"
        ),
        "config": {
            "target_apy_min": 3.0,
            "target_apy_max": 20.0,
            "preferred_tiers": ["T1", "T2"],
            "max_positions": 8,
            "rebalance_threshold_pct": 1.0,
            "cash_buffer_pct": 0.03,
            # Per-protocol concentration caps (fraction of total capital)
            "max_concentration_t1": 0.30,
            "max_concentration_t2": 0.15,
        },
    },
}

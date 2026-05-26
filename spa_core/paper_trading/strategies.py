"""
SPA Strategy Registry — v0.12 (Sprint v2.3)
Реестр торговых стратегий для paper trading.

Каждая стратегия стратегии задаёт:
  - целевой диапазон APY
  - предпочтительные тиеры (T1/T2)
  - лимит позиций
  - кэшбуфер
  - порог ребалансировки

Стратегии:
  v1_passive        — консервативная, только T1 пулы
  v2_aggressive     — рост, T1+T2, выше APY
  v3_pendle_focused — максимизация APY через Pendle PT (до 20% T2)
                      Цель: закрыть APY gap (~4.2% → 7.3%)
"""

# Import v3 config from its dedicated module
try:
    from paper_trading.v3_pendle_focused import get_strategy_config as _v3_config
    _v3_entry = _v3_config()
except Exception:
    # Fallback if module not available (e.g., during bootstrapping)
    _v3_entry = {
        "name": "v3 — Pendle-Focused Yield Maximiser",
        "description": "Pendle PT focus, up to 20% T2, maturity > 30d, rotation at +0.5pp",
        "config": {
            "target_apy_min": 6.0, "target_apy_max": 25.0,
            "preferred_tiers": ["T2", "T1"], "max_positions": 9,
            "rebalance_threshold_pct": 0.5, "cash_buffer_pct": 0.05,
            "max_concentration_t1": 0.40, "max_concentration_t2": 0.20,
            "pendle_max_pct": 0.20, "pendle_min_maturity_days": 30,
            "pendle_rotation_threshold": 0.5, "pendle_min_apy": 6.0,
        },
        "handler_module": "paper_trading.v3_pendle_focused",
        "handler_class": "V3PendleFocusedStrategy",
    }

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
    # v3: Pendle-Focused — targets APY gap closure via Pendle PT positions
    # Added in Sprint v2.3 (2026-05-26). Handler: paper_trading.v3_pendle_focused
    "v3_pendle_focused": _v3_entry,
}

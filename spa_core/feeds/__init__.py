"""spa_core/feeds — live data feed layer.

Provides real-time market data (APY, TVL) from external sources.
Feeds are strictly read-only and never modify adapter, risk, or execution state.

Public modules:
    defi_llama_feed — DeFiLlama yields API with 1-hour cache
"""

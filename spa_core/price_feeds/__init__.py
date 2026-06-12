"""spa_core/price_feeds — live APY feed modules (stdlib only, read-only).

Modules
-------
protocol_direct_feed Tier 1 oracle (ADR-028 Phase 2): direct APY from protocol APIs
                     (Aave V3, Compound V3, Morpho Blue). Fallback + 150 bps divergence
                     alarm vs. DeFiLlama. stdlib-only, never raises.
defi_llama_apy_feed  Tier 2 oracle: unified APY map for all SPA whitelisted protocols
                     (11 adapters) via DeFiLlama /pools. stdlib-only, never raises.
pendle_yt_feed       Pendle YT APY via DeFiLlama + Pendle V2 API, fallback=28.4
"""

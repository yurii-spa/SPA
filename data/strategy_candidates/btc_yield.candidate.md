# Strategy Candidate — BTC-denominated yield (cbBTC lending + BTC basis) → NO-EDGE / REFUSE

> Auto-sprint batch (research agent, 2026-07-02, live DeFiLlama + Binance API). Non-Ethena, non-stablecoin.
> Confirms + quantifies the desk's existing advisory-only BTC stance (btc_lending.py / btc_neutral).

- **candidate_id:** `CAND-BTC-001` · chains: Ethereum/Base
- **(1) cbBTC/tBTC lending → NO-EDGE:** live supply APY ~0-1.5% (Morpho-Base cbBTC 0.00%, Aave-ETH cbBTC 0.10%, Aave-Base cbBTC 1.53%; TVL-wtd ~0.15%). BTC is collateral not borrow-demand → utilization ~0-6% → yield floored near zero. **Spread over floor = −1.9 to −3.4pp (NEGATIVE).** Risk bounded (contract+custody, cbBTC=Coinbase/tBTC=Threshold, WBTC excluded) but ZERO yield. `reason_code: negative_spread_structural_low_borrow`. Deep ($3.4B) but irrelevant.
- **(2) BTC basis (long cbBTC + short BTC perp) → REFUSE:** income = perp funding, **~2.3% annualized realized (30d Binance), 23% of intervals NEGATIVE**. Same risk class as Ethena/ETH-DN: unbounded funding-flip + CEX-counterparty. Doesn't even beat the floor on average. `reason_code: unbounded_funding_flip + cex_counterparty`.
- **verdict:** cbBTC-lending **NO-EDGE** (advisory-only, as coded); BTC-basis **REFUSE**. Neither fundable.

*sources: DeFiLlama yields (L4 live 2026-07-02), Binance funding API (L4), Morpho cbBTC markets, CoinGlass. Forward funding UNKNOWN (30d small sample, calm regime) — use 5-venue median before any re-eval.*

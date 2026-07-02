# 23 — Data Architecture (§31)

**Status: STUB.** This document is a Priority-3 placeholder. It defines the *shape* of the Yield
Lab data-architecture spec — the external and on-chain data sources the research layer will consume,
and the per-source contract (what data, how often, how validated, what fallback, what MVP priority).
It intentionally contains no detail beyond the outline below.

**Scope discipline.** Research-layer only. This document does not alter any runtime data flow, the
deterministic RiskPolicy, the public dashboard, or deployment. Runtime `data/*.json` formats are
untouched (see `06_spa_core_invariants.md`, invariant D-10).

**Cross-references (already built — do not duplicate):**
- `spa_core/adapters/defillama_feed.py` — existing DeFiLlama APY/TVL feed (TTL-cached, keyless).
- `spa_core/data_trust/` — existing source-reliability / freshness / validation culture.
- `spa_core/data_pipeline/` — existing ingestion/normalization plumbing.
- `docs/40_data_quality_framework.md` — the data-quality gating this architecture feeds into.

## Planned contents (outline only)

- **Data-flow topology** — source → ingestion → normalization → validation → research store →
  card/evidence consumers. Where each existing module sits on that path.
- **Source catalogue** — one row per source, each with: *data needed · refresh cadence · validation
  method · fallback behavior · MVP priority*. Availability of every third-party source is marked
  **"requires verification"** (access model, keys, rate limits, terms).
  - DeFiLlama — protocol APY/TVL/yields (existing feed).
  - CoinGecko — asset prices, market caps.
  - Dune — custom on-chain analytics queries.
  - Etherscan (+ chain explorers) — contract/txn/holder verification.
  - Token Terminal — protocol fundamentals/revenue.
  - Glassnode — on-chain market-cycle metrics (BTC/ETH).
  - CryptoQuant — exchange-flow / on-chain cycle metrics.
  - Coinglass — funding rates, open interest, liquidations.
  - CEX APIs — spot/perp/funding reference (Binance, Bybit, OKX, KuCoin, Hyperliquid — cross-ref
    existing `data/funding_feed.py`).
  - DEX / AMM data — pool depth, liquidity, slippage.
  - Protocol APIs — protocol-native yield/position/parameter endpoints.
  - Governance sources — proposals, parameter changes, timelock/pause status.
  - Audit sources — audit reports, coverage, findings.
  - GitHub — repo activity, commit velocity, contributor signal.
  - News / social — qualitative event feed (advisory only).
  - Macro — rates, TradFi benchmarks (RWA floor context).
  - ETF data — BTC/ETH ETF flows (decision-support).
- **Per-source refresh & caching policy** — cadence, TTL, staleness thresholds.
- **Validation & fallback** — cross-source agreement, fail-closed defaults, "unknown = requires
  verification" rule (never invent APY/TVL).
- **Lineage & provenance** — how each data point traces back to source + last-verified timestamp.
- **MVP prioritization** — which sources are MVP-1 vs MVP-2/3 vs later.
- **Secrets & access** — keys via Keychain only; no credentials in files (cross-ref secrets policy).

TODO: expand at MVP 2-3 stage.

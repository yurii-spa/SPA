# 23 — Data Architecture (§31)

**Purpose.** Define the Yield Lab research-layer data architecture: the external and on-chain sources
the research layer consumes, the path each data point travels (source → ingestion → normalization →
validation → research store → card/evidence consumers), and the per-source contract (what data, how
often, how validated, what fallback, what MVP priority). This is the source catalogue that the data
quality framework ([`40`](40_data_quality_framework.md)) grades and the database schema
([`24`](24_database_schema.md)) persists.

**Scope discipline.** Research-layer only. This document does not alter any runtime data flow, the
deterministic RiskPolicy, the public dashboard, or deployment. Runtime `data/*.json` formats are
untouched ([`06_spa_core_invariants.md`](06_spa_core_invariants.md), invariant D-10). **Never invent
APY/TVL** — availability of every third-party source is `requires verification` (access model, keys,
rate limits, terms of service must be confirmed before reliance).

**Cross-references (already built — do not duplicate):**
- `spa_core/adapters/defillama_feed.py` — existing DeFiLlama APY/TVL feed (TTL-cached ~300s, keyless).
- `data/funding_feed.py` — existing 5-venue funding feed (median Binance/Bybit/OKX/KuCoin/Hyperliquid).
- `data/rwa_feed.py` — existing live tokenized-T-bill floor feed (fail-closed to committed literal).
- `spa_core/data_trust/` — existing source-reliability / freshness / validation culture.
- `spa_core/data_pipeline/` — existing ingestion / normalization plumbing.
- [`40_data_quality_framework.md`](40_data_quality_framework.md) — the quality gating this feeds.

---

## 1. Data-flow topology

```
  external / on-chain sources
        │  (fetch: keyless where possible; keys via Keychain only)
        ▼
  ingestion  ──────────────  spa_core/data_pipeline/  (fetch, retry, TTL cache)
        │
        ▼
  normalization  ─────────  unit/label harmonization (APY %-vs-decimal, chain labels)
        │
        ▼
  validation / quality gate  ──  spa_core/data_trust/ + docs/40 (freshness, cross-source, outlier)
        │        │
        │        └── fail-closed → mark "unknown / requires verification" (never fabricate)
        ▼
  research store  ────────  runtime data/*.json today → future PostgreSQL (docs/24)
        │
        ▼
  consumers  ─────────────  Strategy/Protocol/Stablecoin cards · evidence records (docs/37) ·
                            Risk Scoring v2 (advisory, docs/14) · research API (docs/25) ·
                            internal dashboard (docs/26) · IC memos (docs/39) · reports (docs/41)
```

Each existing module's place on the path: `defillama_feed.py` / `funding_feed.py` / `rwa_feed.py` sit
at **ingestion**; `data_pipeline/` handles **ingestion + normalization**; `data_trust/` and doc 40 own
the **validation/quality gate**; the **research store** is JSON today (a relational store is a later
concern, doc 24).

---

## 2. Source catalogue

One row per source. Every third-party availability, key requirement, rate limit, and ToS is
**`requires verification`**; no source is assumed reachable until confirmed. MVP priority: **1** =
needed for first research pass, **2** = MVP 2-3, **L** = later.

| Source | Data needed | Refresh cadence | Validation method | Fallback | MVP |
|---|---|---|---|---|---|
| **DeFiLlama** (existing) | Protocol APY / TVL / yields | ~300s TTL | Schema + freshness check; cross-check vs protocol API | Cached last-good; else unknown | 1 |
| **CoinGecko** | Asset prices, market caps | Minutes (`requires verification`) | Cross-check vs CEX ref price; outlier flag | Cached; else unknown | 1 |
| **CEX APIs** (Binance/Bybit/OKX/KuCoin/Hyperliquid, existing) | Spot/perp price, funding, OI | Existing feed cadence | Median across ≥3 venues (`funding_feed.py`) | Median of available venues; fail-closed | 1 |
| **RWA / T-bill feed** (existing) | Tokenized-T-bill rate (the floor) | Existing cadence | TVL-weighted; fail-closed literal flagged | Committed literal (flagged) | 1 |
| **Chain explorers** (Etherscan + others) | Contract/txn/holder verification | On demand | Verified-bytecode + address match | None → mark unverified | 2 |
| **Dune** | Custom on-chain analytics queries | Query-dependent | Query provenance + re-run reproducibility | Cached query result | 2 |
| **DEX / AMM data** | Pool depth, liquidity, slippage | Minutes–hours | Depth cross-check; exit-slippage model | Cached; else unknown | 2 |
| **Protocol APIs** | Native yield / position / parameters | Protocol-dependent | Cross-check vs DeFiLlama | DeFiLlama value | 2 |
| **Governance sources** | Proposals, param changes, timelock/pause | Event-driven | Source = official governance portal/chain | Manual note | 2 |
| **Audit sources** | Audit reports, coverage, findings | On publication | Named auditor + report link | Mark "no audit found" | 2 |
| **Token Terminal** | Protocol fundamentals / revenue | Daily (`requires verification`) | Cross-check revenue vs on-chain | Cached | L |
| **Glassnode** | On-chain BTC/ETH cycle metrics | Daily | Provenance + sanity range | Cached | L |
| **CryptoQuant** | Exchange-flow / cycle metrics | Daily | Provenance | Cached | L |
| **Coinglass** | Funding, open interest, liquidations | Minutes | Cross-check vs CEX APIs | CEX-API value | L |
| **GitHub** | Repo activity, commit velocity | Daily | API provenance | Cached | L |
| **News / social** | Qualitative event feed | Continuous | **Advisory only**, never a number source | Ignore | L |
| **Macro / TradFi** | Rates, benchmarks (floor context) | Daily | Official source | Cached | L |
| **ETF data** | BTC/ETH ETF flows | Daily | Official issuer/aggregator | Cached | L |

---

## 3. Per-source refresh, validation, fallback, lineage

- **Refresh & caching.** Each source carries a cadence + TTL + staleness threshold. Beyond the
  staleness threshold the value is **downgraded to unknown** (fail-closed), not silently reused (doc 40).
- **Validation.** Where two independent sources exist (e.g. APY from a protocol API vs DeFiLlama),
  agreement is checked; divergence beyond tolerance flags the point for review (doc 40 cross-source).
- **Fallback.** Deterministic and explicit: cached last-good (with age shown) → committed literal only
  where one exists and it is clearly flagged (as `rwa_feed.py` does) → otherwise **unknown / requires
  verification**. Never fabricate a number to fill a gap.
- **Lineage & provenance.** Every data point records its source, fetch timestamp, and last-verified
  date so any card/evidence figure traces back to origin (persisted per doc 24 `data_lineage`).

---

## 4. MVP prioritization & secrets

- **MVP-1** (already reachable): DeFiLlama, CoinGecko, CEX funding feed, RWA floor feed — the sources
  the first research pass and the existing sleeves already depend on.
- **MVP 2-3**: explorers, Dune, DEX depth, protocol/governance/audit sources — needed for full
  protocol/stablecoin cards.
- **Later**: fundamentals, on-chain-cycle, ETF/macro/news — decision-support enrichment.
- **Secrets & access.** API keys via **Keychain only**; no credentials in files (SPA secrets policy,
  [`06`](06_spa_core_invariants.md)). Keyless endpoints preferred where available (as with the existing
  funding feed).

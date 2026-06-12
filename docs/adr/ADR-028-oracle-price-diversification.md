# ADR-028: Oracle Price Diversification

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** Owner
**Related:** ADR-002 (Go-live transfer rule), ADR-019 (T2 cap), ADR-021 (Pendle YT T3-SPEC)

---

## Context

SPA currently relies on a single data source — DeFiLlama (`yields.llama.fi/pools`) — for all
APY and TVL readings used in allocation decisions. This creates a single point of failure: if
DeFiLlama experiences an outage, returns stale data, or is manipulated, the cycle runner has
no fallback and may either halt or rebalance based on corrupted inputs.

The Moonwell incident (November 2025, ~$1M loss) demonstrated the systemic risk of oracle
monoculture. In that case, a misconfigured Chainlink price feed for a collateral asset went
unchecked because there was no secondary source to cross-validate against. The protocol had
no divergence alarm — it trusted one feed unconditionally. SPA's current architecture
reproduces the same structural flaw at the APY layer.

Additional risks of single-source dependency:

- **Availability:** DeFiLlama API has had intermittent outages (HTTP 503, rate-limiting).
  During such windows, `defillama_feed.py` falls back to a TTL-expired local cache, which
  may be hours or days stale by the time the cycle fires.
- **Data drift:** Aggregators compute APY from on-chain events with varying methodologies.
  DeFiLlama's `apyBase` for Aave V3 has historically diverged from Aave's own
  `getLiquidityRate()` by 30–200 bps due to different averaging windows.
- **Feed manipulation:** While DeFiLlama aggregates across sources, any aggregator is a
  potential target for MEV or off-chain manipulation at the indexing layer.

As SPA approaches go-live (target 2026-08-01, ADR-002), the data integrity requirements
tighten. GoLiveChecker criterion `data_fresh_48h` already guards staleness, but there is no
consensus validation across independent sources.

---

## Decision

Implement a **3-tier oracle hierarchy** for APY/TVL data ingestion. All tiers operate
read-only and have no execution authority (LLM_FORBIDDEN_AGENTS rule is unaffected).

### Tier 1 — Protocol Direct API (primary, highest trust)

Fetch APY/TVL directly from each protocol's own on-chain or official off-chain endpoint.
These values are authoritative by definition and have the lowest latency to rate changes.

| Protocol | Endpoint | Field |
|---|---|---|
| Aave V3 (Ethereum) | `https://aave.com/api/data/markets` | `liquidityRate` (RAY units) |
| Compound V3 | `https://api.compound.finance/v2/ctoken` | `supply_rate.value` |
| Morpho Blue | Subgraph (`api.thegraph.com/…`) + RPC `getMarketParams` | weighted `supplyAPY` |
| Morpho Steakhouse | ERC-4626 `convertToAssets` delta / 365d extrapolation | vault APY |

Tier 1 requires RPC access and is **disabled in Phase 1** (paper trading). Enabled in Phase 2.

### Tier 2 — Aggregators (reliable fallback)

Aggregators are used when Tier 1 is unavailable or when Tier 1 returns a value outside
plausible bounds (APY < 0.1% or APY > 100% after outlier filter).

| Source | URL | Notes |
|---|---|---|
| DeFiLlama | `https://yields.llama.fi/pools` | **current primary** — becomes Tier 2 in Phase 2 |
| Token Terminal | `https://api.tokenterminal.com/v2/metrics` | requires API key; optional |

### Tier 3 — Static Fallback (stale guard)

Hard-coded values from `PROTOCOL_POOL_MAP` in `defillama_feed.py`, used only when both
Tier 1 and Tier 2 are unavailable. Data is tagged `data_quality: "stale"` and must not
drive new allocations if age exceeds `stale_threshold_days` (default: 7 days).

When Tier 3 activates, the cycle runner sets `approved: false` in the RiskPolicy gate
(see `data/risk_policy_blocks.json`) and sends a Telegram alert.

### Consensus Rules

1. **Divergence alarm:** If Tier 1 and Tier 2 readings for the same pool differ by more than
   **150 bps**, write an alarm entry to `data/market_regime.json` with fields
   `{pool, tier1_apy, tier2_apy, delta_bps, ts}`. Do not halt the cycle; use Tier 1 value
   but flag the position as `data_quality: "divergence"`.
2. **Dual outage:** If both Tier 1 and Tier 2 are unavailable, fall through to Tier 3 with
   `data_quality: "stale"`. Stop new allocations; existing positions held unchanged.
3. **Stale threshold breach:** If Tier 3 data age exceeds 7 days, emit a Telegram alert and
   block cycle completion (`approved: false` from RiskPolicy gate).
4. **Cross-tier validation** is advisory only — it cannot override `approved: false` from
   `RiskPolicy`. The RiskPolicy gate remains the final authority.

---

## Rejection: Chainlink for APY Data

Chainlink is purpose-built for **spot price feeds** (e.g., ETH/USD), not for lending APY.
There are no Chainlink feeds for protocol supply rates on Ethereum mainnet — APY is a
computed metric derived from utilization curves, not a traded price observable. Using
Chainlink for APY would require either (a) a custom oracle network SPA does not operate,
or (b) wrapping a third-party aggregator in a Chainlink adapter, which adds latency and
a trust assumption without reducing the single-source problem. The Moonwell hack involved
a **price feed** (collateral valuation), not an APY feed — the lesson is about
cross-validation, not about migrating to Chainlink specifically.

---

## Consequences

**Positive:**
- Eliminates the single point of failure for APY data; divergence between sources becomes
  a detectable, auditable signal rather than a silent failure.
- Tier 3 static fallback ensures the cycle always has a path to completion, preventing
  artificial gaps in `gap_monitor.json` due to data unavailability.
- Consensus alarm in `market_regime.json` provides early warning for feed anomalies before
  they affect allocation.

**Negative:**
- Tier 1 (Phase 2) requires RPC access, introducing a network dependency not present today.
  Must be scoped to read-only calls and covered by the `FORBIDDEN` import boundary between
  `adapters/` and `execution/`.
- Maintaining divergence logic adds complexity to `defillama_feed.py` / adapter layer.
  Risk of false alarms during legitimate APY spike events (e.g., liquidity crunch).
- Token Terminal (Tier 2, optional) requires an API key — a secret that must be stored in
  macOS Keychain per SECRETS POLICY; never hardcoded.

---

## Implementation Plan

| Phase | Date | Scope | Status |
|---|---|---|---|
| **Phase 1** | Now (paper trading) | DeFiLlama as sole Tier 2 source; static Tier 3 fallback with `stale` flag; consensus alarm scaffolded but inactive | ✅ Current state |
| **Phase 2** | 2026-07-01 | Enable Tier 1 direct API for Aave V3 + Compound V3; activate divergence alarm (150 bps threshold); write to `market_regime.json` | Planned |
| **Phase 3** | 2026-08-01 (go-live) | Full 3-tier consensus for all T1 protocol adapters; Morpho Subgraph integration; `data_quality` field propagated to all position records | Planned |

Phase 3 completion is a prerequisite for GoLiveChecker criterion `adapter_audit` (criterion #22).
Progress tracked in `KANBAN.json` under MP-532 (oracle diversification).

---

*Document owner: Owner. Next review: 2026-08-01 or upon any oracle incident.*

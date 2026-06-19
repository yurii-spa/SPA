# SPA Data Sources Registry

**Version:** v1.1  
**Updated:** 2026-06-19 (MP-1417)  
**Authority:** `data/backtest/source_pipeline.json`  

---

## 1. Overview

This registry documents all data sources used by SPA adapters, their pipeline status,
tier classification, and point-in-time (PIT) evidence availability.

The canonical machine-readable registry is `data/backtest/source_pipeline.json`.
This document provides human-readable context and is kept in sync manually.

**Pipeline statuses:**

| Status | Meaning |
|--------|---------|
| `clean_included` | Source is in the clean backtest universe; data validated |
| `manual_proxy` | Using a proxy rate; acceptable for paper trading |
| `pending` | Under review; not yet validated |
| `review` | Data quality review in progress |
| `source_needed` | No live data source identified yet |
| `research_only` | Conceptual; not suitable for live allocation |

---

## 2. T1 Sources — Included (clean_included)

These sources form the primary paper-trading universe.

| Source ID | Protocol | Asset | APY (est.) | Adapter | Notes |
|-----------|----------|-------|-----------|---------|-------|
| `aave_v2_usdc` | Aave V2 | USDC | ~2.5% | `aave_v3.py` (compat) | Mainnet |
| `compound_v2_usdc` | Compound V2 | USDC | ~3.0% | `compound_v3.py` (compat) | Mainnet |
| `aave_v3_usdc` | Aave V3 | USDC | ~3.5% | `aave_v3.py` | Mainnet, T1 |
| `compound_v3_usdc` | Compound V3 Comet | USDC | ~4.8% | `compound_v3.py` | Mainnet, T1 |
| `aave_v3_base` | Aave V3 | USDC | ~4.6% | `aave_v3_arbitrum.py` | Base chain |
| `morpho_blue` | Morpho Blue | USDC | ~5.0% | `morpho_blue.py` | Mainnet |
| `sky_susds` | Sky (MakerDAO) | sUSDS | 0% current | monitor only | GSM Pause Delay rule |
| `sfrax` | Frax Finance | sFRAX | ~4.5% | yield feed | Research |

---

## 3. T2 Sources

| Source ID | Protocol | Asset | Status | Notes |
|-----------|----------|-------|--------|-------|
| `morpho_steakhouse` | Morpho Steakhouse | USDC | `pending` | High APY ~6.5% |
| `yearn_v3_yvusdc` | Yearn V3 | USDC | `pending` | ERC-4626 |
| `euler_v2_usdc` | Euler V2 | USDC | `pending` | ERC-4626 |
| `maple_syrupusdc` | Maple Finance | USDC | `review` | Private credit, ADR-020 |

---

## 4. T3-SPEC Sources (Advisory Only)

| Source ID | Protocol | Strategy | Notes |
|-----------|----------|----------|-------|
| `pendle_pt_susde` | Pendle PT | PT-sUSDe | ADR-021; advisory only |
| `ethena_usde` | Ethena | USDe | Manual proxy; research |
| `delta_neutral` | Synthetic delta-neutral | sUSDe hedge | S8 strategy; paper only |

---

## 5. Out-of-Scope Sources (source_needed)

The following sources are identified but not yet have a live data feed:

| Source ID | Asset Class | Priority |
|-----------|------------|---------|
| `btc_yield` | BTC yield | Low |
| `eth_staking` | ETH staking | Low |
| `gmx_btc`, `gmx_eth` | GMX perps | Low |
| `btc_stable_pool`, `gold_proxy` | Stable pools | Low |
| `btc_usd_conc_liq`, `rwa_conc_liq` | Concentrated liquidity | Research |
| `trader_losses_vault` | MEV/trader losses | Research |

---

## 6. Primary APY Feed

All live APY/TVL data flows through:

- **DeFiLlama Yields API** — `spa_core/adapters/defillama_feed.py`
- Cache TTL: 300 seconds
- Config: `spa_core/adapters/config.py`
- Fallback: `data/adapter_status.json` (execution domain — read-only for adapters)

---

## 7. Source Promotion Process

To promote a source from `pending` → `clean_included`:

1. Obtain ≥90 days of historical APY data with no gaps
2. Run data quality checks (drift, outlier detection)
3. Update `data/backtest/source_pipeline.json`
4. Create ADR documenting the promotion rationale
5. Re-run GoLiveChecker to verify `data_quality` criterion

---

## 8. PIT Evidence

Point-in-time data integrity is tracked in `data/paper/evidence_v2.json`.
Each paper-trading day accumulates evidence points (0.3–1.5 pts/day).
Target: 30 evidence points before go-live.

---

*Registry maintained by SPA Engineering. Machine-readable version: `data/backtest/source_pipeline.json`.*

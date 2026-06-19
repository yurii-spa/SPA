# ADR-029: Research Strategies Framework

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** SPA Architecture Team  
**MP:** MP-1332 (Sprint v9.48)

---

## Context

The CPA (Capital Preservation Algorithm) pre-paper backtest handoff identified two
candidate strategies that could potentially enhance portfolio yield:

- **RS-001 Anti-Crisis** — Targets 18.2% APY using GMX exposure, gold proxy, stablecoin core  
- **RS-002 Cashflow** — Targets 29.24% gross APY via concentrated LP positions on BTC/USD pairs

Both strategies have components without point-in-time historical data, which prevents
them from entering strict evidence mode. In strict PIT backtest (2022–2026), both
strategies produce ~86.97% cash drag because the majority of their allocation slots
have no eligible DeFiLlama historical series.

The SourcePipeline (`spa_core/backtesting/source_pipeline.py`) classifies these
components as `source_needed` — meaning no data source has been connected yet.

---

## Decision

Implement both strategies as **RESEARCH_ONLY** tracks with the following constraints:

### 1. Strict separation

`RESEARCH_ONLY = True` is hard-coded at the module level in both strategy files.
This flag **cannot** be overridden by configuration, runtime parameters, or
any downstream caller. Any refactor that changes this flag requires a new ADR.

### 2. Shadow-only operation

Shadow trackers (`RS001ShadowTracker`, `RS002ShadowTracker`) record daily
performance projections using placeholder APYs. No capital allocation occurs until
all `SOURCE_NEEDED` slots are promoted to `CLEAN_INCLUDED`.

Shadow data files:
- `data/research/rs001_shadow.json`
- `data/research/rs002_shadow.json`

### 3. Source quality gating

Each strategy slot is labeled with its SourceState:

| Slot | Strategy | Weight | State |
|---|---|---|---|
| `gmx_btc_exposure` | RS-001 | 20% | SOURCE_NEEDED |
| `gmx_eth_exposure` | RS-001 | 10% | SOURCE_NEEDED |
| `btc_stable_pool` | RS-001 | 35% | SOURCE_NEEDED |
| `eth_aggressive_pool` | RS-001 | 5% | SOURCE_NEEDED |
| `gold_proxy` | RS-001 | 15% | SOURCE_NEEDED |
| `stablecoin_t1` | RS-001 | 15% | CLEAN_INCLUDED (live data eligible) |
| `btc_usd_conc_liq` | RS-002 | 60% | SOURCE_NEEDED |
| `rwa_conc_liq` | RS-002 | 10% | SOURCE_NEEDED |
| `trader_losses_vault` | RS-002 | 14% | SOURCE_NEEDED |
| `stablecoin_deposit` | RS-002 | 16% | CLEAN_INCLUDED (live data eligible) |

Only `CLEAN_INCLUDED` slots contribute to strict backtest results (ADR-030).
In strict mode: RS-001 has 15% eligible weight; RS-002 has 16% eligible weight.

### 4. Promotion pathway

RS-001 and RS-002 may graduate to production via the following process:

a. **Source Promotion Engine** (`spa_core/backtesting/source_promotion_engine.py`):
   each `SOURCE_NEEDED` component promoted to `CLEAN_INCLUDED` by the engine  
b. **Owner acceptance** signed via `spa_core/backtesting/owner_acceptance.py`  
c. **30-day paper trading** with `evidence_points >= 30`  
d. **Architect review sign-off** documented in a new ADR

All four steps must complete before either strategy can be activated for capital
allocation. A `GoLiveChecker` criterion blocks promotion if any step is incomplete.

### 5. Risk labeling

- `RS-002` `risk_classification = "AGGRESSIVE"` — permanent. The 29.24% target
  is **gross** of impermanent loss. In trending BTC markets, concentrated LP
  positions can suffer significant IL; net realized returns may reach 0% or
  negative. This label cannot be changed without a new ADR.

- `RS-001` `risk_classification = "MODERATE-HIGH"` — permanent until evidence
  requirements are met and a new ADR is filed.

---

## Consequences

### Positive

- Clear pathway from research to production with explicit checkpoints
- IL risk quantified and disclosed via `ConcLPILModel` (MP-1308)
- 120 stress scenarios documented in `ResearchScenarioMatrix` (spa_core/backtesting/)
- Users see clear **RESEARCH ONLY** labeling on earn-defi.com dashboard
- Audit trail: `spa_core/analytics/protocol_data_audit.py` tracks acquisition progress

### Negative

- Both strategies effectively shelved until data sources are found
- 86.97% cash drag in strict backtest means low near-term yield contribution
- Acquisition roadmap requires 90–180+ engineering days (per MP-1331 audit)
- `stablecoin_deposit` / `stablecoin_t1` slots contribute only 15–16% of the
  research APY, making the research strategies nearly invisible in strict mode

---

## Alternatives Considered

### 1. Reject RS-001/RS-002 entirely

Simpler — eliminates research overhead. Rejected because the strategies represent
potentially high-yield pathways (18.2% and 12–18% net APY) that warrant tracking
even in shadow mode.

### 2. Deploy with placeholder data

Rejected — violates CPA strict evidence standard (ADR-030). Placeholder APYs
would inflate performance metrics with unverifiable assumptions.

### 3. Deploy with manual proxy APYs

Rejected — opens the door to cherry-picking. Manual proxies are classified as
`MANUAL_PROXY` in SourcePipeline, not `CLEAN_INCLUDED`, and cannot affect strict
backtest results per ADR-030.

---

## Implementation Files

| File | Role |
|---|---|
| `spa_core/strategies/s20_anticrisis_research.py` | RS-001 strategy, `RESEARCH_ONLY = True` |
| `spa_core/strategies/s21_cashflow_research.py` | RS-002 strategy, `RESEARCH_ONLY = True` |
| `spa_core/analytics/conc_lp_il_model.py` | IL math for RS-002 (MP-1308) |
| `spa_core/analytics/rs001_live_apy_engine.py` | Live APY engine for RS-001 |
| `spa_core/analytics/rs002_live_apy_engine.py` | Live APY engine for RS-002 |
| `spa_core/analytics/protocol_data_audit.py` | Acquisition roadmap and priority scores (MP-1331) |
| `spa_core/backtesting/source_pipeline.py` | SourceState machine |
| `spa_core/backtesting/research_scenario_matrix.py` | 120 stress scenarios |
| `data/research/rs001_shadow.json` | Daily shadow performance log |
| `data/research/rs002_shadow.json` | Daily shadow performance log |

---

## References

- CPA pre-paper backtest handoff package (2026-06-19)
- `spa_core/backtesting/source_pipeline.py` — SourceState machine
- `spa_core/strategies/s20_anticrisis_research.py`
- `spa_core/strategies/s21_cashflow_research.py`
- ADR-030 — Point-in-Time Backtest Standard
- MP-1331 — Protocol Data Audit (`spa_core/analytics/protocol_data_audit.py`)
- MP-1308 — ConcLPILModel (`spa_core/analytics/conc_lp_il_model.py`)

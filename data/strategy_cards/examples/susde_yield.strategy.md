# Strategy Card — sUSDe Basis Yield (Ethena)

> **EXAMPLE CARD — ILLUSTRATIVE ONLY.** Every APY/TVL/capacity number below is
> **illustrative — requires verification** and is NOT a real claim. Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution.
> Cross-refs: docs/11, docs/07, docs/37, docs/14, docs/34, and the existing
> `spa_core/strategy_lab/aggressive_lab/` (paper-tests refused 10–15%+ strategies).
> **RISK-COMPENSATION FLAG:** much of this yield may be compensation for basis/funding tail risk,
> not free carry — treat as risk-comp, not preservation.

## Identity
- **strategy_id:** `SC-EX-003`
- **name:** `sUSDe Basis Yield (Ethena)`
- **version:** `1.0`
- **category:** `basis`
- **product_line:** `MaxYield`  <!-- targeted; also assessable as Enhanced depending on regime -->
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["USDe","sUSDe"]`
- **protocols_used:** `["ethena"]`  <!-- Protocol Card required (docs/12) -->
- **chains_used:** `["Ethereum"]`

## Yield source (the honesty core)
- **yield_source:** Staked USDe (sUSDe) accruing the protocol's delta-neutral basis + staking yield.
- **yield_mechanism:** Funding basis — long spot ETH/LST hedged with short perp; positive funding + staking is distributed to sUSDe.
- **who_pays_the_yield:** Perp longs paying funding to the short-side hedge (plus underlying staking).
- **why_yield_exists:** Persistent positive perp funding in bullish/leveraged regimes.
- **why_yield_can_disappear:** Funding turns negative, hedge slippage, collateral/custody stress, or USDe depeg — yield can go to zero or negative.

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **observed_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **base_apy:** `illustrative — requires verification`
- **incentive_apy:** `illustrative — requires verification`
- **sustainable_apy_estimate:** `illustrative — requires verification (regime-dependent; can be << headline)`
- **apy_evidence_level:** `L1`  <!-- illustrative: historical public APY observed only; NOT paper-passed here -->

## Spread over floor (ADR-YL-008 — judgment is spread over the LIVE RWA floor)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: illustrative — requires verification, fallback_used: requires verification }`
- **spread_over_floor_bps:** `illustrative — requires verification (sUSDe staking yield over floor; funding-driven and regime-dependent, can compress hard when perp funding turns negative)`
- **spread_risk_explanation:** the spread pays for Ethena counterparty/custody risk, negative-funding/basis-flip risk, and USDe peg/redemption risk. **Per-risk bps split NOT computed** (L1 historical-observed only, no paper track) → each `bps` is `requires attribution`.
- **unexplained_spread_bps:** `requires attribution — at L1 the observed spread is undecomposed; the funding-flip + Ethena-unwind tail is treated as UNPRICED tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- illustrative: L1 observed only, spread not decomposed → cannot advance to Enhanced/MaxYield under ADR-YL-008 -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `illustrative — requires verification`
- **risk_score:** `illustrative — requires verification (high — risk-comp yield)`
- **liquidity_score:** `illustrative — requires verification (cooldown on unstake)`
- **complexity_score:** `illustrative — requires verification (high)`

## Capacity & capital
- **capacity_estimate:** `illustrative — requires verification`
- **min_capital:** `illustrative — requires verification`
- **max_capital:** `illustrative — requires verification`
- **suitable_capital_tiers:** `["$100k","$1M"]`  <!-- illustrative; isolated high-risk sleeve only (docs/34) -->
- **lockup_period:** `unstake cooldown (variable)`
- **withdrawal_time:** `cooldown period + secondary-market exit`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** Ethena minting/staking contracts.
- **stablecoin_risk:** USDe depeg risk — synthetic dollar, not fiat-reserve backed.
- **counterparty_risk:** CEX custody of hedge collateral + perp venue solvency — material.
- **bridge_risk:** Low (mainnet).
- **oracle_risk:** Collateral/perp pricing.
- **liquidation_risk:** Hedge leg liquidation under extreme moves.
- **regulatory_risk:** Synthetic-dollar regulatory surface.
- **operational_risk:** Delta-neutral rebalancing / custody operations (protocol-side).
- **concentration_risk:** Single-protocol, single-mechanism.
- **correlation_risk:** Funding correlates with ETH/BTC leverage regime.
- **market_regime_risk:** High — negative-funding regimes erode or invert the yield.

## Dependencies, assumptions, conditions
- **key_dependencies:** `["positive perp funding","CEX custody solvency","USDe peg","hedge integrity"]`
- **assumptions:** `["funding stays net-positive on average","hedge holds through stress"]`
- **entry_conditions:** `["funding-regime check passes","refused if funding negative / depeg risk elevated"]`
- **exit_conditions:** `["funding turns persistently negative","better risk-adjusted allocation"]`
- **emergency_exit_conditions:** `["USDe depeg","CEX/counterparty failure","hedge breakdown"]`
- **monitoring_requirements:** `["perp funding (multi-venue)","USDe peg","collateral/custody status","unstake queue"]`
- **data_sources_required:** `["multi-venue funding feed","DeFiLlama","peg oracle"]`

## Validation & approval (promotion ledger)
- **validation_status:** `research (risk-comp yield — Red Team mandatory before any advance)`
- **paper_test_status:** `not_started (illustrative — aggressive_lab may refuse in stress)`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `not_started (MANDATORY — basis/counterparty/new-stablecoin triggers)`
- **approved_for_product_line:** `null`  <!-- NOT approved — research-only, risk-comp flagged -->
- **final_recommendation:** `research-only (flag as risk-compensation; require Red Team + paper track)`
- **max_allocation:** `illustrative — requires verification (never overrides RiskPolicy caps)`
- **review_frequency:** `weekly`

## Provenance
- **owner:** `<desk owner>`
- **created_at:** `2026-07-02T00:00:00Z`
- **updated_at:** `2026-07-02T00:00:00Z`
- **status:** `research`  <!-- honest: NOT approved; risk-comp yield -->

---

### Promotion gate checklist (docs/11 §5 — MaxYield requires all + ≥ L4)
- [x] Clear yield source (all 5 yield_* fields substantive)
- [ ] APY evidence level ≥ L4 (currently illustrative L1 — far below bar)
- [ ] Protocol review — Ethena Protocol Card (docs/12)
- [ ] Stablecoin review — USDe Stablecoin Card (docs/13)
- [ ] Risk review — advisory Risk Scoring v2 (illustrative; high)
- [ ] Red-team review — NOT started (mandatory: basis/counterparty/new-stablecoin)
- [ ] Capacity estimate sourced (currently illustrative)
- [ ] Liquidity review — exit-liquidity-by-size from dfb/risk_overlay.py
- [ ] Paper testing — not started
- [ ] Human approval — NOT set (approved_for_product_line = null)

# Strategy Card — ETH LST/LRT Staking (hedged-neutral option)

> **EXAMPLE CARD — ILLUSTRATIVE ONLY.** Every APY/TVL/capacity number below is
> **illustrative — requires verification** and is NOT a real claim. Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution.
> Cross-refs: docs/11, docs/07, docs/37, docs/14, docs/34, docs/16 (ETH yield), and the existing
> `spa_core/strategy_lab/` **eth_lst_neutral** sleeve (plain LST + short perp, β≈0). BTC/ETH modules
> are decision-support only (ADR-YL-007).

## Identity
- **strategy_id:** `SC-EX-005`
- **name:** `ETH LST/LRT Staking (hedged-neutral option)`
- **version:** `1.0`
- **category:** `restaking`
- **product_line:** `Enhanced`
- **asset_type:** `ETH`

## What it touches
- **assets_used:** `["ETH","stETH/rETH (LST) or eETH (LRT)","short ETH-perp (if hedged)"]`
- **protocols_used:** `["<Lido/Rocketpool/EtherFi>","<hedge venue if neutral>"]`  <!-- Protocol Cards (docs/12) -->
- **chains_used:** `["Ethereum","<hedge venue>"]`

## Yield source (the honesty core)
- **yield_source:** ETH staking rewards (LST) plus restaking/AVS rewards (LRT); optionally hedged to β≈0.
- **yield_mechanism:** Staking consensus rewards + (LRT) restaking incentives; hedge strips ETH price exposure.
- **who_pays_the_yield:** The Ethereum protocol (issuance + priority fees); AVS incentive programs for LRT.
- **why_yield_exists:** Validators are paid to secure the network; restaking pays for extra security services.
- **why_yield_can_disappear:** Staking yield compresses as stake grows; LRT incentives/points end; LST/LRT depeg; hedge cost exceeds carry.

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **observed_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **base_apy:** `illustrative — requires verification (plain staking)`
- **incentive_apy:** `illustrative — requires verification (restaking/points — often unsustainable)`
- **sustainable_apy_estimate:** `illustrative — requires verification (base staking net of hedge cost)`
- **apy_evidence_level:** `L2`  <!-- illustrative: data-source verified; hedged variant paper-tested in strategy_lab -->

## Spread over floor (ADR-YL-008 — judgment is spread over the LIVE RWA floor)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: illustrative — requires verification, fallback_used: requires verification }`
- **spread_over_floor_bps:** `illustrative — requires verification (staking + restaking yield over floor; directional β≈1 unhedged carries ETH-price and depeg tail)`
- **spread_risk_explanation:** the spread pays for LRT depeg/withdrawal-queue risk, restaking (AVS/slashing) exposure, and smart-contract risk of the LRT stack. **Per-risk bps split NOT computed** (data-source verified only, no full attribution) → each `bps` is `requires attribution`.
- **unexplained_spread_bps:** `requires attribution — spread not decomposed point-by-point; the LRT-depeg + slashing tail is treated as UNPRICED tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- illustrative: directional LRT sleeve, spread not fully risk-explained → cannot advance to Enhanced/MaxYield under ADR-YL-008 -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `illustrative — requires verification`
- **risk_score:** `illustrative — requires verification (LRT > LST; hedge reduces price β not depeg)`
- **liquidity_score:** `illustrative — requires verification (unstake queue / LST secondary depth)`
- **complexity_score:** `illustrative — requires verification (moderate; higher if hedged)`

## Capacity & capital
- **capacity_estimate:** `illustrative — requires verification`
- **min_capital:** `illustrative — requires verification`
- **max_capital:** `illustrative — requires verification`
- **suitable_capital_tiers:** `["$100k","$1M","$10M"]`  <!-- illustrative; deep LST market (docs/34) -->
- **lockup_period:** `unstake/withdrawal queue (variable)`
- **withdrawal_time:** `exit queue or LST secondary sale (slippage)`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** LST/LRT contracts + (LRT) restaking/AVS contracts — LRT materially higher.
- **stablecoin_risk:** N/A (ETH-denominated) — but LST/LRT/ETH peg residual matters when hedged.
- **counterparty_risk:** Operator set (LST) / AVS operators (LRT) / hedge-venue solvency (if neutral).
- **bridge_risk:** If LST/LRT is bridged to the hedge venue.
- **oracle_risk:** LST/LRT pricing; hedge index.
- **liquidation_risk:** Short-perp leg liquidation on an ETH rally if hedged and margin thin.
- **regulatory_risk:** Staking/securities surface.
- **operational_risk:** Hedge rebalancing, queue management (higher for neutral variant).
- **concentration_risk:** Operator/AVS concentration.
- **correlation_risk:** Unhedged β≈1 to ETH; hedged variant β≈0 (residual = LST-vs-ETH peg drift).
- **market_regime_risk:** Restaking incentives regime-dependent; hedge cost varies with funding.

## Dependencies, assumptions, conditions
- **key_dependencies:** `["LST/LRT peg to ETH","staking rewards continue","(hedged) funding cheaper than carry"]`
- **assumptions:** `["plain LST tracks ETH closely (lower depeg-residual than LRT)","unstake feasible"]`
- **entry_conditions:** `["prefer plain LST over LRT for neutral sleeve","APY within RiskPolicy band"]`
- **exit_conditions:** `["restaking incentives end","hedge cost > carry","better allocation"]`
- **emergency_exit_conditions:** `["LST/LRT depeg","slashing/AVS incident","hedge breakdown"]`
- **monitoring_requirements:** `["LST/LRT peg","staking/restaking APY","unstake queue","(hedged) funding"]`
- **data_sources_required:** `["DeFiLlama ETH/LST/restaking feed","multi-venue funding (if hedged)"]`

## Validation & approval (promotion ledger)
- **validation_status:** `paper_testing (hedged eth_lst_neutral sleeve — strategy_lab; LRT unhedged higher-risk)`
- **paper_test_status:** `running (illustrative — cross-ref strategy_lab eth_lst_neutral)`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `not_started (MANDATORY for LRT — restaking/opaque/lockup triggers)`
- **approved_for_product_line:** `null`  <!-- NOT approved — research/paper; human approval pending -->
- **final_recommendation:** `research-only (prefer plain-LST neutral; Red Team required for LRT)`
- **max_allocation:** `illustrative — requires verification (never overrides RiskPolicy caps)`
- **review_frequency:** `weekly`

## Provenance
- **owner:** `<desk owner>`
- **created_at:** `2026-07-02T00:00:00Z`
- **updated_at:** `2026-07-02T00:00:00Z`
- **status:** `paper_testing`  <!-- honest: NOT approved for live -->

---

### Promotion gate checklist (docs/11 §5 — Enhanced requires all + ≥ L3)
- [x] Clear yield source (all 5 yield_* fields substantive)
- [ ] APY evidence level ≥ L3 (currently illustrative L2 — below bar)
- [ ] Protocol review — LST/LRT + hedge-venue Protocol Cards (docs/12)
- [ ] Stablecoin review — N/A (ETH-denominated)
- [ ] Risk review — advisory Risk Scoring v2 (illustrative)
- [ ] Red-team review — NOT started (mandatory for LRT: restaking/opaque/lockup)
- [ ] Capacity estimate sourced (currently illustrative)
- [ ] Liquidity review — exit-liquidity-by-size from dfb/risk_overlay.py
- [~] Paper testing (hedged variant running — not yet passed)
- [ ] Human approval — NOT set (approved_for_product_line = null)

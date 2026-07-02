# Strategy Card — Core Stablecoin Lending (Aave / Compound USDC)

> **EXAMPLE CARD — ILLUSTRATIVE ONLY.** Every APY/TVL/capacity number below is
> **illustrative — requires verification** and is NOT a real claim. Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution.
> Cross-refs: docs/11 (card system), docs/07 (lifecycle), docs/37 (APY evidence L0–L6),
> docs/14 (advisory Risk Scoring v2), docs/34 (capital tiers).

## Identity
- **strategy_id:** `SC-EX-001`
- **name:** `Core Stablecoin Lending (Aave/Compound USDC)`
- **version:** `1.0`
- **category:** `lending`
- **product_line:** `Core`
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["USDC"]`
- **protocols_used:** `["aave_v3","compound_v3"]`  <!-- each needs a reviewed Protocol Card (docs/12) -->
- **chains_used:** `["Ethereum","Arbitrum","Base"]`

## Yield source (the honesty core)
- **yield_source:** Interest paid by overcollateralized borrowers of USDC.
- **yield_mechanism:** Lending spread — supply APY driven by pool utilization.
- **who_pays_the_yield:** Borrowers who post volatile collateral and pay variable borrow rates.
- **why_yield_exists:** Demand to borrow stablecoins against crypto collateral exceeds passive supply.
- **why_yield_can_disappear:** Utilization falls, borrow demand drops, or incentive programs end → APY compresses.

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **observed_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **base_apy:** `illustrative — requires verification`
- **incentive_apy:** `illustrative — requires verification`
- **sustainable_apy_estimate:** `illustrative — requires verification`
- **apy_evidence_level:** `L3`  <!-- illustrative: this is the desk's real held style, paper-tracked; still verify per-cycle -->

## Spread over floor (ADR-YL-008 — judgment is spread over the LIVE RWA floor)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: illustrative — requires verification, fallback_used: requires verification }`
- **spread_over_floor_bps:** `illustrative — requires verification (lending supply APY minus live RWA floor; thin and utilization-driven for a conservative core book)`
- **spread_risk_explanation:** the small spread pays for accepted, measurable risks — smart-contract exposure of mature lending markets, USDC issuer/depeg surface, and pool-utilization/withdrawal-liquidity risk. **Per-risk bps split NOT computed** (scorecard yields one realized number, not a per-risk decomposition) → each `bps` is `requires attribution`.
- **unexplained_spread_bps:** `requires attribution — the realized spread is not yet decomposed point-by-point into the named risks; residual treated as UNPRICED tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- illustrative: spread not decomposed point-by-point → held/advisory at Core, cannot advance to Enhanced/MaxYield under ADR-YL-008 until fully risk-explained -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `illustrative — requires verification`
- **risk_score:** `illustrative — requires verification (low, relative to book)`
- **liquidity_score:** `illustrative — requires verification (high)`
- **complexity_score:** `illustrative — requires verification (low)`

## Capacity & capital
- **capacity_estimate:** `illustrative — requires verification`
- **min_capital:** `illustrative — requires verification`
- **max_capital:** `illustrative — requires verification`
- **suitable_capital_tiers:** `["$100k","$1M","$10M","$100M+"]`  <!-- illustrative; deep core scales far (docs/34) -->
- **lockup_period:** `none`
- **withdrawal_time:** `near-instant (subject to pool utilization at exit)`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** Mature, audited, heavily used lending markets — non-zero but low relative to DeFi.
- **stablecoin_risk:** USDC depeg / issuer / redemption risk (Circle reserves).
- **counterparty_risk:** Diffuse borrower base; low single-counterparty reliance.
- **bridge_risk:** L2 deployments rely on canonical bridges — low but present.
- **oracle_risk:** Collateral pricing oracles; manipulation could impair the pool, not the USDC supply directly.
- **liquidation_risk:** N/A for the supplier (no leverage taken by this strategy).
- **regulatory_risk:** Stablecoin/issuer regulatory surface.
- **operational_risk:** Low — deposit/withdraw only, no active management.
- **concentration_risk:** Managed by RiskPolicy caps (40% T1 per-protocol).
- **correlation_risk:** Low direct correlation to BTC/ETH price; indirect via borrow-demand cycles.
- **market_regime_risk:** APY sensitive to borrow-demand regime (compresses in risk-off).

## Dependencies, assumptions, conditions
- **key_dependencies:** `["USDC peg","pool utilization","protocol solvency"]`
- **assumptions:** `["overcollateralization holds","withdrawals remain open"]`
- **entry_conditions:** `["TVL ≥ $5M","APY within RiskPolicy 1–30% band"]`
- **exit_conditions:** `["better risk-adjusted allocation available","rebalance threshold"]`
- **emergency_exit_conditions:** `["USDC depeg","protocol exploit","utilization spike freezing withdrawals"]`
- **monitoring_requirements:** `["USDC peg","pool utilization/APY","protocol incident feeds"]`
- **data_sources_required:** `["DeFiLlama APY/TVL feed","on-chain utilization"]`

## Validation & approval (promotion ledger)
- **validation_status:** `held — desk's real conservative core style`
- **paper_test_status:** `passed (illustrative — reflects live paper track; verify per data/)`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `not_required at this tier (mandatory only for Enhanced/Max/leverage/etc.)`
- **approved_for_product_line:** `Core`  <!-- illustrative: this is the desk's held style -->
- **final_recommendation:** `approve (Core — conservative held book)`
- **max_allocation:** `illustrative — requires verification (never overrides RiskPolicy caps)`
- **review_frequency:** `weekly`

## Provenance
- **owner:** `<desk owner>`
- **created_at:** `2026-07-02T00:00:00Z`
- **updated_at:** `2026-07-02T00:00:00Z`
- **status:** `approved_for_core`  <!-- illustrative example; real approval is owner-set -->

---

### Promotion gate checklist (docs/11 §5)
- [x] Clear yield source (all 5 yield_* fields substantive)
- [x] APY evidence level ≥ L3 (illustrative — paper-tracked core style)
- [ ] Protocol review — Protocol Cards for aave_v3 / compound_v3 (docs/12)
- [ ] Stablecoin review — USDC Stablecoin Card (docs/13)
- [x] Risk review — advisory Risk Scoring v2 (illustrative)
- [ ] Red-team review — not required at Core tier
- [ ] Capacity estimate sourced (currently illustrative)
- [ ] Liquidity review — exit-liquidity-by-size from dfb/risk_overlay.py
- [x] Paper testing (real paper track)
- [x] Human approval — owner set approved_for_product_line

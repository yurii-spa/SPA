# Strategy Card — BTC Cash-and-Carry Basis

> **EXAMPLE CARD — ILLUSTRATIVE ONLY.** Every APY/TVL/capacity number below is
> **illustrative — requires verification** and is NOT a real claim. Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution.
> **DECISION-SUPPORT ONLY (ADR-YL-007):** BTC modules are decision-support, not auto-trading.
> This card describes a *yield* structure for research; no directional/automated execution.
> Cross-refs: docs/11, docs/07, docs/37, docs/14, docs/34, docs/15 (BTC cycle), docs/16.

## Identity
- **strategy_id:** `SC-EX-004`
- **name:** `BTC Cash-and-Carry Basis`
- **version:** `1.0`
- **category:** `basis`
- **product_line:** `MaxYield`
- **asset_type:** `BTC`

## What it touches
- **assets_used:** `["BTC","short BTC-perp/future"]`
- **protocols_used:** `["<CEX or on-chain perp venue>"]`  <!-- Protocol/venue Card required (docs/12) -->
- **chains_used:** `["Bitcoin","<hedge venue>"]`

## Yield source (the honesty core)
- **yield_source:** Long spot BTC hedged with a short BTC future/perp; capture the basis / funding.
- **yield_mechanism:** Funding basis / futures premium — market pays a premium to be long leveraged BTC.
- **who_pays_the_yield:** Leveraged perp/future longs paying funding to the short-side hedge.
- **why_yield_exists:** Structural demand for leveraged long BTC exposure in bullish regimes.
- **why_yield_can_disappear:** Funding flips negative (backwardation), basis compresses, or venue/counterparty stress.

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **observed_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **base_apy:** `illustrative — requires verification`
- **incentive_apy:** `illustrative — requires verification (none — pure basis)`
- **sustainable_apy_estimate:** `illustrative — requires verification (regime-dependent)`
- **apy_evidence_level:** `L0`  <!-- illustrative: idea/decision-support only; no paper track here -->

## Spread over floor (ADR-YL-008 — judgment is spread over the LIVE RWA floor)
- **floor_baseline_pct:** `{ value: illustrative — requires verification, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: illustrative — requires verification, fallback_used: requires verification }`
- **spread_over_floor_bps:** `illustrative — requires verification (basis carry over floor is regime-dependent; can invert on negative funding)`
- **spread_risk_explanation:** the spread pays for venue/counterparty solvency, funding-flip and margin/liquidation tail. **Per-risk bps split NOT computed** (L0 idea, no paper track) → each `bps` is `requires attribution`.
- **unexplained_spread_bps:** `requires attribution — at L0 the spread is undecomposed; residual funding/counterparty tail is treated as UNPRICED tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- L0 idea, spread not decomposed → cannot advance to Enhanced/MaxYield under ADR-YL-008 -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `illustrative — requires verification`
- **risk_score:** `illustrative — requires verification (moderate-high — counterparty/basis)`
- **liquidity_score:** `illustrative — requires verification`
- **complexity_score:** `illustrative — requires verification (high — two-leg, custody)`

## Capacity & capital
- **capacity_estimate:** `illustrative — requires verification`
- **min_capital:** `illustrative — requires verification`
- **max_capital:** `illustrative — requires verification`
- **suitable_capital_tiers:** `["$1M","$10M","$100M+"]`  <!-- illustrative; deep futures markets (docs/34) -->
- **lockup_period:** `none (subject to margin/roll mechanics)`
- **withdrawal_time:** `unwind both legs — near-instant on liquid venues`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** Only if on-chain perp venue is used; otherwise N/A.
- **stablecoin_risk:** Margin stablecoin depeg (if margined in stablecoin).
- **counterparty_risk:** CEX / venue solvency and custody of the hedge collateral — the dominant risk.
- **bridge_risk:** If collateral is bridged to the venue.
- **oracle_risk:** Funding/index pricing.
- **liquidation_risk:** Short-leg liquidation on a sharp BTC rally if margin is thin.
- **regulatory_risk:** Derivatives venue regulatory surface.
- **operational_risk:** Two-leg management, funding roll, margin top-ups — high, human-in-the-loop.
- **concentration_risk:** Single-venue counterparty concentration.
- **correlation_risk:** Designed β≈0 to BTC price if hedged 1:1, but basis correlates with leverage regime.
- **market_regime_risk:** High — negative funding erodes/inverts the carry.

## Dependencies, assumptions, conditions
- **key_dependencies:** `["positive funding / futures premium","venue solvency","margin sufficiency"]`
- **assumptions:** `["hedge stays 1:1 delta-neutral","funding net-positive on average"]`
- **entry_conditions:** `["funding/basis positive","human approval — decision-support, not auto (ADR-YL-007)"]`
- **exit_conditions:** `["basis compresses","funding turns negative"]`
- **emergency_exit_conditions:** `["venue/counterparty failure","funding deeply negative","margin call risk"]`
- **monitoring_requirements:** `["BTC funding/basis (multi-venue)","margin ratio","venue health"]`
- **data_sources_required:** `["multi-venue BTC funding/basis feed","index price"]`

## Validation & approval (promotion ledger)
- **validation_status:** `research (decision-support; no automated execution — ADR-YL-007)`
- **paper_test_status:** `not_started`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `not_started (MANDATORY — basis/counterparty triggers)`
- **approved_for_product_line:** `null`  <!-- NOT approved — decision-support only, human-in-the-loop -->
- **final_recommendation:** `research-only / decision-support (no auto-trading; human approval required to act)`
- **max_allocation:** `illustrative — requires verification (never overrides RiskPolicy caps)`
- **review_frequency:** `weekly`

## Provenance
- **owner:** `<desk owner>`
- **created_at:** `2026-07-02T00:00:00Z`
- **updated_at:** `2026-07-02T00:00:00Z`
- **status:** `research`  <!-- honest: NOT approved; decision-support only -->

---

### Promotion gate checklist (docs/11 §5 — MaxYield requires all + ≥ L4)
- [x] Clear yield source (all 5 yield_* fields substantive)
- [ ] APY evidence level ≥ L4 (currently illustrative L0 — idea only)
- [ ] Protocol/venue review — venue Card (docs/12)
- [ ] Stablecoin review — margin-stablecoin Card if applicable (docs/13)
- [ ] Risk review — advisory Risk Scoring v2 (illustrative)
- [ ] Red-team review — NOT started (mandatory: basis/counterparty)
- [ ] Capacity estimate sourced (currently illustrative)
- [ ] Liquidity review — exit-liquidity-by-size (venue depth)
- [ ] Paper testing — not started
- [ ] Human approval — NOT set (approved_for_product_line = null); decision-support only

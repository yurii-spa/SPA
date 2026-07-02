# Strategy Card — Pendle PT Fixed-Rate Stablecoin Carry

> **EXAMPLE CARD — ILLUSTRATIVE ONLY.** Every APY/TVL/capacity number below is
> **illustrative — requires verification** and is NOT a real claim. Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution.
> Cross-refs: docs/11, docs/07, docs/37 (APY evidence), docs/14, docs/34, and the existing
> Rates Desk `spa_core/strategy_lab/rates_desk/` FixedCarry sleeve (validated thesis #1).

## Identity
- **strategy_id:** `SC-EX-002`
- **name:** `Pendle PT Fixed-Rate Stablecoin Carry`
- **version:** `1.0`
- **category:** `carry`
- **product_line:** `Enhanced`
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["USDC","PT-<stablecoin-underlying>"]`
- **protocols_used:** `["pendle"]`  <!-- Protocol Card required (docs/12) -->
- **chains_used:** `["Ethereum","Arbitrum"]`

## Yield source (the honesty core)
- **yield_source:** Fixed rate locked in by buying a Pendle Principal Token (PT) at a discount, held to maturity.
- **yield_mechanism:** Fixed-rate carry — PT accretes to par (1.0 of underlying) at maturity; the discount is the yield.
- **who_pays_the_yield:** The YT (yield-token) buyers / the underlying yield source that the PT strips fixed.
- **why_yield_exists:** Market prices a discount for locking a fixed rate vs. an uncertain variable rate.
- **why_yield_can_disappear:** Discount compresses (fair-value converges), underlying yield collapses, or the underlying depegs before maturity.

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **observed_apy_range:** `{ low: illustrative — requires verification, high: illustrative — requires verification }`
- **base_apy:** `illustrative — requires verification`
- **incentive_apy:** `illustrative — requires verification`
- **sustainable_apy_estimate:** `illustrative — requires verification`
- **apy_evidence_level:** `L3`  <!-- illustrative: rates_desk FixedCarry is live-paper; verify per surface -->

## Spread over floor (ADR-YL-008 — judgment is spread over the LIVE RWA floor)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: illustrative — requires verification, fallback_used: requires verification }`
- **spread_over_floor_bps:** `illustrative — requires verification (fixed PT-to-maturity implied yield minus live RWA floor; refusal-first fair-value gate rejects tail-comp carry)`
- **spread_risk_explanation:** the spread pays for the underlying yield-bearing stablecoin's peg/redemption risk, Pendle AMM/PT smart-contract risk, and exit-liquidity-by-size at maturity. **Per-risk bps split NOT computed** (paper-tracked, not fully attributed) → each `bps` is `requires attribution`.
- **unexplained_spread_bps:** `requires attribution — realized carry not yet decomposed point-by-point; residual peg/liquidity tail treated as UNPRICED tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- illustrative: spread not decomposed point-by-point → cannot advance to Enhanced/MaxYield under ADR-YL-008 until fully risk-explained -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `illustrative — requires verification`
- **risk_score:** `illustrative — requires verification (moderate)`
- **liquidity_score:** `illustrative — requires verification (thinner — PT depth-limited)`
- **complexity_score:** `illustrative — requires verification (moderate)`

## Capacity & capital
- **capacity_estimate:** `illustrative — requires verification (thin — limited by PT liquidity depth)`
- **min_capital:** `illustrative — requires verification`
- **max_capital:** `illustrative — requires verification`
- **suitable_capital_tiers:** `["$100k","$1M"]`  <!-- illustrative; carry depth is sleeve-limited (docs/34) -->
- **lockup_period:** `until maturity (PT to par) — early exit only via secondary sale`
- **withdrawal_time:** `held-to-maturity or slippage-bearing secondary exit`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** Pendle AMM + PT/YT contract complexity.
- **stablecoin_risk:** Depeg of the PT underlying stablecoin before maturity.
- **counterparty_risk:** Underlying yield source counterparty (varies by PT).
- **bridge_risk:** L2 deployment bridge exposure.
- **oracle_risk:** Pricing of PT/underlying.
- **liquidation_risk:** N/A unlevered (levered PT is a different, higher-risk card).
- **regulatory_risk:** Stablecoin + structured-product surface.
- **operational_risk:** Maturity management, roll timing.
- **concentration_risk:** Per-PT market thinness.
- **correlation_risk:** Low to BTC/ETH; sensitive to rates regime.
- **market_regime_risk:** Fixed rate can be underwater vs. rising variable rates.

## Dependencies, assumptions, conditions
- **key_dependencies:** `["underlying stablecoin peg to maturity","Pendle solvency","PT exit liquidity"]`
- **assumptions:** `["discount reflects real carry, not tail-risk compensation","hold to maturity feasible"]`
- **entry_conditions:** `["refusal-first fair-value gate passes (rates_desk rate_policy)","APY within RiskPolicy band"]`
- **exit_conditions:** `["maturity reached","fair-value convergence"]`
- **emergency_exit_conditions:** `["underlying depeg","Pendle incident","liquidity vanish"]`
- **monitoring_requirements:** `["underlying peg","implied vs fair rate","time-to-maturity","PT depth"]`
- **data_sources_required:** `["Pendle markets + historical-data feed","DeFiLlama","rates_desk RateSurface"]`

## Validation & approval (promotion ledger)
- **validation_status:** `paper_testing (rates_desk FixedCarry — thesis #1 GO, live-paper advisory)`
- **paper_test_status:** `running (illustrative — cross-ref rates_desk paper track)`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `passed (illustrative — rates_desk refusal-first vetoed toxic LRT PT books)`
- **approved_for_product_line:** `null`  <!-- NOT approved — advisory/research-only, human approval pending -->
- **final_recommendation:** `research-only (advance paper track; owner approval pending)`
- **max_allocation:** `illustrative — requires verification (never overrides RiskPolicy caps)`
- **review_frequency:** `weekly`

## Provenance
- **owner:** `<desk owner>`
- **created_at:** `2026-07-02T00:00:00Z`
- **updated_at:** `2026-07-02T00:00:00Z`
- **status:** `paper_testing`  <!-- honest: NOT approved for live -->

---

### Promotion gate checklist (docs/11 §5 — Enhanced requires all)
- [x] Clear yield source (all 5 yield_* fields substantive)
- [~] APY evidence level ≥ L3 (illustrative — rates_desk live-paper; verify)
- [ ] Protocol review — Pendle Protocol Card (docs/12)
- [ ] Stablecoin review — underlying Stablecoin Card (docs/13)
- [x] Risk review — advisory Risk Scoring v2 (illustrative)
- [x] Red-team review — passed (refusal-first, illustrative)
- [ ] Capacity estimate sourced (currently illustrative — thin)
- [ ] Liquidity review — exit-liquidity-by-size from dfb/risk_overlay.py
- [~] Paper testing (running — not yet passed)
- [ ] Human approval — NOT set (approved_for_product_line = null)

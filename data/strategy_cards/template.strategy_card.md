# Strategy Card — <NAME>

> Fill-in template mirroring `schema.strategy_card.json`. One card per strategy.
> Research-layer artifact — NOT runtime data, never read by RiskPolicy or execution.
> **Never invent APY/TVL/capacity. Unknown numbers = `TBD — requires verification`.**
> Cross-refs: docs/11 (this system), docs/07 (lifecycle), docs/37 (APY evidence L0–L6),
> docs/14 (advisory Risk Scoring v2), docs/34 (capital tiers).

## Identity
- **strategy_id:** `SC-XXXX`  <!-- stable unique id, never reused -->
- **name:** `<name>`  <!-- human-readable -->
- **version:** `1.0`  <!-- bumps on material edits -->
- **category:** `<lending|rwa|basis|carry|lp|restaking|leverage|options|...>`
- **product_line:** `<Preserve|Core|Enhanced|MaxYield|Experimental>`  <!-- TARGETED line; approval is separate -->
- **asset_type:** `<stablecoin|BTC|ETH|mixed>`

## What it touches
- **assets_used:** `[]`  <!-- e.g. ["USDC","sUSDe"] -->
- **protocols_used:** `[]`  <!-- cross-ref Protocol Cards (docs/12) -->
- **chains_used:** `[]`

## Yield source (the honesty core)
- **yield_source:** `<one line: where the yield comes from>`
- **yield_mechanism:** `<lending spread / funding basis / RWA coupon / emissions / points / ...>`
- **who_pays_the_yield:** `<the counterparty actually paying>`
- **why_yield_exists:** `<economic reason the yield is available>`
- **why_yield_can_disappear:** `<compression / incentive end / funding flip / depeg / capacity>`

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: TBD — requires verification, high: TBD — requires verification }`
- **observed_apy_range:** `{ low: TBD — requires verification, high: TBD — requires verification }`
- **base_apy:** `TBD — requires verification`
- **incentive_apy:** `TBD — requires verification`
- **sustainable_apy_estimate:** `TBD — requires verification`
- **apy_evidence_level:** `L0`  <!-- L0 idea .. L6 multi-cycle validated (docs/37); no APY treated as verified below this -->

## Spread over the floor (the mandate — ADR-YL-008: judged as spread over the live floor, not absolute APY)
- **floor_baseline_pct:** `{ value: TBD — live from data/rwa_feed.py (NEVER hardcode), source: rwa_feed, as_of: TBD, fallback_used: false }`
- **spread_over_floor_bps:** `TBD — requires verification`  <!-- (sustainable/observed APY − live floor) in bps -->
- **spread_risk_explanation:** `[ { risk: TBD, bps: TBD, evidence: TBD } ]`  <!-- each point of spread → a specific accepted measurable risk; bps should sum to spread_over_floor_bps -->
- **unexplained_spread_bps:** `TBD`  <!-- residual = spread − Σ explained; unpriced tail risk, NOT alpha -->
- **spread_fully_explained:** `false`  <!-- must be true to advance to Enhanced/MaxYield; false ⇒ REJECT + refusal-log entry -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `TBD`  <!-- 0–100, confidence in the card's own inputs -->
- **risk_score:** `TBD`  <!-- 0–100, higher = riskier -->
- **liquidity_score:** `TBD`  <!-- 0–100 -->
- **complexity_score:** `TBD`  <!-- 0–100 -->

## Capacity & capital
- **capacity_estimate:** `TBD — requires verification`  <!-- capital absorbable before compression/slippage -->
- **min_capital:** `TBD — requires verification`
- **max_capital:** `TBD — requires verification`
- **suitable_capital_tiers:** `[]`  <!-- subset of $100k / $1M / $10M / $100M+ (docs/34) -->
- **lockup_period:** `<none|7d|variable|...>`
- **withdrawal_time:** `<expected time to exit to cash>`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** `<contract/exploit exposure>`
- **stablecoin_risk:** `<depeg/redemption/reserve risk, or N/A>`
- **counterparty_risk:** `<CEX/issuer/market-maker reliance>`
- **bridge_risk:** `<bridged-asset / cross-chain messaging exposure>`
- **oracle_risk:** `<oracle manipulation/staleness exposure>`
- **liquidation_risk:** `<forced-liquidation exposure>`
- **regulatory_risk:** `<legal/sanctions/securities surface>`
- **operational_risk:** `<ops/keys/monitoring/human-process risk>`
- **concentration_risk:** `<single-protocol/single-asset concentration>`
- **correlation_risk:** `<correlation to BTC/ETH/rates/other book positions>`
- **market_regime_risk:** `<sensitivity to bull/bear/high-vol/low-funding>`

## Dependencies, assumptions, conditions
- **key_dependencies:** `[]`  <!-- a peg, a CEX leg, an oracle, an incentive program -->
- **assumptions:** `[]`
- **entry_conditions:** `[]`
- **exit_conditions:** `[]`
- **emergency_exit_conditions:** `[]`
- **monitoring_requirements:** `[]`
- **data_sources_required:** `[]`  <!-- must be real, cited feeds -->

## Validation & approval (promotion ledger)
- **validation_status:** `<mirrors lifecycle>`
- **paper_test_status:** `<not_started|running|passed|failed — cross-ref strategy_lab/tournament>`
- **small_capital_test_status:** `<not_started|running|passed|failed>`
- **red_team_status:** `<not_started|passed|failed — cross-ref spa_core/redteam/>`
- **approved_for_product_line:** `null`  <!-- set only by human approval; may lag product_line target -->
- **final_recommendation:** `<approve|reject|defer|research-only>`
- **max_allocation:** `TBD — requires verification`  <!-- advisory; never overrides RiskPolicy caps -->
- **review_frequency:** `<weekly|monthly|...>`

## Provenance
- **owner:** `<human accountable for the card>`
- **created_at:** `<ISO-8601 UTC>`
- **updated_at:** `<ISO-8601 UTC>`
- **status:** `idea`  <!-- idea|research|rejected|paper_testing|paper_passed|small_capital_testing|small_capital_passed|approved_for_preserve|approved_for_core|approved_for_enhanced|approved_for_max_yield|frozen|retired -->

---

### Promotion gate checklist (docs/11 §5 — all required for Enhanced/MaxYield)
- [ ] Clear yield source (all 5 yield_* fields substantive, no TBD)
- [ ] APY evidence level ≥ L3 (Enhanced) / ≥ L4 (MaxYield)
- [ ] Protocol review — every protocol has a reviewed Protocol Card (docs/12)
- [ ] Stablecoin review (if applicable) — reviewed Stablecoin Card (docs/13)
- [ ] Risk review — advisory Risk Scoring v2 complete (docs/14), no hard-rejection sub-score
- [ ] Red-team review passed (spa_core/redteam/)
- [ ] Capacity estimate + suitable_capital_tiers sourced (not TBD)
- [ ] Liquidity review — exit-liquidity-by-size cited from dfb/risk_overlay.py
- [ ] Paper testing passed (real paper track, not backtest-only)
- [ ] Human approval — owner set approved_for_product_line + final_recommendation

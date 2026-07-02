# Strategy Card — Leverage Loop (REFUSED — spread is pure risk-comp)

> Real card mapped from `leverage_loop` in `spa_core/strategy_lab/aggressive_lab/`
> (data/aggressive_lab/scorecard.json: risk_class C, headline 15.0%, **realized −8.95%**). This card is
> the ADR-YL-008 **rejection demonstration**: a large nominal spread over the floor that is NOT
> explained by accepted measurable risk — it is compensation for a liquidation tail that materialized.
> **REFUSED; a positive result recorded in the refusal log; never live-eligible.** Numbers from the
> aggressive-lab scorecard (advisory, outside RiskPolicy). Cross-refs: docs/11, docs/07, docs/adr/ADR-YL-008, docs/33, docs/43.

## Identity
- **strategy_id:** `SC-LEVLOOP-001`  <!-- maps to aggressive_lab strategy `leverage_loop` -->
- **name:** `Leverage Loop (recursive lending/looping)`
- **version:** `1.0`
- **category:** `leverage`
- **product_line:** `MaxYield` (TARGET, as a nominal ~15% strategy) — **REFUSED, not approved**
- **asset_type:** `mixed`

## What it touches
- **assets_used:** `["looped collateral (LST/stable) + borrowed asset"]`
- **protocols_used:** `["lending venue(s) for the loop"]`
- **chains_used:** `["Ethereum (+ verify)"]`

## Yield source (the honesty core)
- **yield_source:** `Recursive looping — deposit, borrow, redeposit N× to amplify a base yield.`
- **yield_mechanism:** `Leverage on a lending/carry spread; the "yield" is N× a thin base minus borrow cost.`
- **who_pays_the_yield:** `No one durably — it is borrowed amplification; the "extra" is compensation for taking liquidation risk.`
- **why_yield_exists:** `Leverage multiplies a small spread into a large headline number.`
- **why_yield_can_disappear:** `A rate/price move triggers liquidation; the loss is realized and cannot be "undone" by a kill switch.`

## APY (never presented without an evidence level)
- **expected_apy_range:** `headline ~15.0% (the LURE)`
- **observed_apy_range:** `realized **−8.95%** (aggressive-lab backtest, class C); max drawdown ~27.94% (earlier lab run)`
- **base_apy:** `thin (pre-leverage) — requires verification`
- **incentive_apy:** `variable`
- **sustainable_apy_estimate:** `negative in the realized track — the headline is not sustainable`
- **apy_evidence_level:** `L3` (paper/backtest in the aggressive lab) — and it FAILED

## Spread over the floor (the mandate — ADR-YL-008)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live), as_of: 2026-07-01, fallback_used: requires verification }`
- **spread_over_floor_bps:** `NOMINAL ~1160 bps (headline 15.0% − floor 3.4%). REALIZED ~−1235 bps (realized −8.95% − floor 3.4%) — the realized spread is NEGATIVE.`
- **spread_risk_explanation:** the nominal spread is **NOT** accounted for by accepted, measurable risk — it is compensation for a liquidation tail:
  - `{ risk: "liquidation / forced-unwind tail (recursive leverage on correlated collateral)", bps: "explains ~all of it — and it materialized (realized −8.95%, maxdd ~27.94%)", evidence: "aggressive_lab scorecard leverage_loop, class C" }`
- **unexplained_spread_bps:** `The entire nominal ~1160 bps is UNPRICED tail risk, not alpha — proven by the negative realized return.`
- **spread_fully_explained:** `false` → **REJECT.** Under ADR-YL-008 this cannot be held: the spread is pure risk-compensation for a tail that fires. Logged in the refusal log as a positive result.

## Advisory scores (0–100; docs/14 — ADVISORY ONLY)
- **confidence_score:** `high that it should be refused` (realized loss + large drawdown)
- **risk_score:** `HIGH (class C; liquidation tail) — requires Risk Scoring v2 run`
- **liquidity_score:** `degrades under stress (unwind at the worst time)`
- **complexity_score:** `high (recursive positions + liquidation management)`

## Capacity & capital
- **capacity_estimate:** `N/A — refused; not deployed`
- **min_capital:** `N/A` · **max_capital:** `N/A`
- **suitable_capital_tiers:** `[]` (none — refused)
- **lockup_period:** `none, but exit during a liquidation cascade is the risk`
- **withdrawal_time:** `fast nominally; catastrophic if a liquidation has already fired`

## Risk dimensions (qualitative)
- **smart_contract_risk:** `lending venue(s)`
- **stablecoin_risk:** `depends on collateral leg`
- **counterparty_risk:** `venue`
- **bridge_risk:** `per chain`
- **oracle_risk:** `HIGH — an oracle blip can cascade liquidations`
- **liquidation_risk:** `THE defining risk — recursive leverage; realized −8.95% / ~27.94% drawdown`
- **regulatory_risk:** `moderate`
- **operational_risk:** `high (must actively manage health factor)`
- **concentration_risk:** `recursive same-asset concentration`
- **correlation_risk:** `HIGH — correlated collateral amplifies the tail`
- **market_regime_risk:** `HIGH — breaks in high-vol / rate-shock regimes`

## Dependencies, assumptions, conditions
- **key_dependencies:** `["lending venue liquidity", "stable rates/prices (the fragile assumption)", "oracle integrity"]`
- **assumptions:** `["no adverse move large enough to liquidate — falsified in the realized track"]`
- **entry_conditions:** `["N/A — refused"]`
- **exit_conditions:** `["N/A — refused"]`
- **emergency_exit_conditions:** `["a liquidation that already fired cannot be exited — the loss is realized"]`
- **monitoring_requirements:** `["N/A — not deployed"]`
- **data_sources_required:** `["aggressive_lab scorecard (advisory)"]`

## Validation & approval (promotion ledger)
- **validation_status:** `rejected` (refused under ADR-YL-008 — unexplained spread = risk-comp tail)
- **paper_test_status:** `failed` (aggressive-lab: realized −8.95%, class C)
- **small_capital_test_status:** `not_started (blocked)`
- **red_team_status:** `refused` (spread-attribution Q19: the whole spread is unpriced liquidation tail)
- **approved_for_product_line:** `null`
- **final_recommendation:** `reject` — hold in the aggressive lab as a documented refusal; **NEVER live-eligible.**
- **max_allocation:** `0` (refused; aggressive lab is outside RiskPolicy, advisory, moves no capital)
- **review_frequency:** `n/a (retained as a refusal example)`

## Provenance
- **owner:** `owner / IC`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **status:** `rejected`

---

### Promotion gate checklist (docs/11 §5)
- [ ] **Spread fully explained (ADR-YL-008)** — **FALSE**: nominal ~1160 bps spread is unpriced liquidation tail (realized −8.95%). **REJECT → refusal log.**
- [x] Clear yield source (recursive leverage — honestly, no durable payer)
- [ ] APY evidence — L3 realized is NEGATIVE (failed)
- [ ] all other gates — moot (refused)

> **Role in ADR-YL-008:** the canonical **rejection = positive result** example. A ~15% headline is
> exactly the risk-compensation the desk REFUSES: the entire spread over the floor is compensation for
> a liquidation tail that *materialized* (realized −8.95%, ~27.94% drawdown). The card documents the
> refusal so the reasoning is auditable — the refusal is the product, not a failure.

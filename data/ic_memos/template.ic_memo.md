# Investment Committee Memo — <STRATEGY NAME>

> Fill-in IC memo template (§38 reporting set). Research-layer artifact — advisory; the deterministic
> RiskPolicy remains the sole hard execution gate (ADR-YL-004) and Execution Support is non-custodial
> (ADR-YL-005). **Never invent APY/TVL. Unknown = `TBD — requires verification`.**
> Cross-refs: `docs/11_strategy_card_system.md`, `docs/37_apy_realism_and_evidence_standard.md`,
> `docs/14_risk_scoring_v2.md`, `docs/34_capital_tiers_strategy.md`, `docs/07_yield_lab_architecture.md`.

- **memo_id:** `IM-XXXX`  ·  **strategy_id:** `SC-XXXX`  ·  **research_report:** `RR-XXXX`
- **product_line (targeted):** `<Preserve|Core|Enhanced|MaxYield|Experimental>`
- **author:** `<name>`  ·  **date:** `<ISO-8601 UTC>`  ·  **decision_status:** `<pending|approved|rejected|deferred>`

## 1. Strategy summary
_One paragraph: what it is, the edge, and the honest one-line "how it can fail"._

## 2. Yield source
- source / mechanism / who pays / why it exists / why it can disappear — `<fill each; no TBD for Enhanced+>`

## 3. APY evidence level
| Figure | Value | Kind | Evidence level (L0–L6) | Source | Last verified |
|---|---|---|---|---|---|
| Expected APY | `TBD — requires verification` | | `L0` | | |
| Observed APY | `TBD — requires verification` | | | | |
> Evidence bar for promotion: Enhanced ≥ L3, MaxYield ≥ L4 (ADR-YL-006, docs/11 §5).

## 4. Risk summary (advisory Risk Scoring v2)
- risk `TBD` / liquidity `TBD` / complexity `TBD` / confidence `TBD` — **advisory only (ADR-YL-004).**
- Key risk dimensions triggered: `<smart-contract / stablecoin / counterparty / bridge / oracle /
  liquidation / regulatory / operational / concentration / correlation / market-regime>`

## 5. Capacity
- **capacity_estimate:** `TBD — requires verification`  ·  compression point: `<...>`

## 6. Liquidity
- withdrawal_time / lockup: `<...>`  ·  exit-liquidity-by-size (cite `dfb/risk_overlay.py`): `<...>`

## 7. Red Team objections
_Summarize the Red Team review (`data/red_team_reviews/`). List the strongest objections and whether
each is mitigated._
- `<objection → mitigation status>`

## 8. Paper / small-capital test status
- **paper_test_status:** `<not_started|running|passed|failed — cite strategy_lab/tournament>`
- **small_capital_test_status:** `<not_started|running|passed|failed>`
- forward track vs RWA floor: `<cite; requires verification>`

## 9. Recommended allocation (advisory)
- **recommended_allocation:** `TBD — requires verification`  <!-- advisory; never overrides RiskPolicy caps -->
- **suitable_capital_tiers:** `[]`

## 10. Approval decision
- **decision:** `<approve | reject | defer | research-only>`
- **approved_for_product_line:** `null`  <!-- set only by named human owner -->
- **approver (human):** `<name>`  ·  **date:** `<ISO-8601 UTC>`

## 11. Conditions of approval
- `<caps, monitoring cadence, review frequency, staged sizing — all conditions the approval depends on>`

## 12. Monitoring
- **monitoring_requirements:** `[]`  ·  **review_frequency:** `<weekly|monthly>`
- feeds/alerts required: `[]`

## 13. Exit triggers
- **normal exit:** `<...>`
- **emergency exit:** `<depeg / exploit / liquidity freeze / funding flip / counterparty failure / drawdown>`
- Note: SPA Core two-tier kill-switch (SOFT −5% / HARD −10%) is orthogonal and always binds.

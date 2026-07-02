# Strategy Research Report — <STRATEGY NAME>

> Fill-in template (§38 reporting set). Research-layer artifact — never read by RiskPolicy or the
> execution path. **Never invent APY/TVL. Unknown numbers = `TBD — requires verification`.**
> Cross-refs: `docs/11_strategy_card_system.md`, `docs/37_apy_realism_and_evidence_standard.md`
> (APY evidence L0–L6), `docs/14_risk_scoring_v2.md` (advisory scoring), `docs/07_yield_lab_architecture.md`
> (lifecycle). Feeds → IC memo (`data/ic_memos/`) and Strategy Card (`data/strategy_cards/`).

- **report_id:** `RR-XXXX`
- **strategy_id:** `SC-XXXX`  <!-- links to the Strategy Card -->
- **product_line:** `<Preserve|Core|Enhanced|MaxYield|Experimental>`
- **lifecycle_status:** `<idea|research|paper_testing|paper_passed|...>`
- **author:** `<name>`
- **date:** `<ISO-8601 UTC>`
- **status:** `<draft|in-review|final>`

## 1. Thesis (one paragraph)
_What is the strategy, in one honest paragraph? What is the edge and why does it exist?_

## 2. Yield source
- **yield_source:** `<one line>`
- **yield_mechanism:** `<lending spread / basis / RWA coupon / emissions / points / ...>`
- **who_pays_the_yield:** `<counterparty actually paying>`
- **why_yield_exists:** `<economic reason>`
- **why_yield_can_disappear:** `<compression / incentive end / funding flip / depeg / capacity>`

## 3. APY analysis (with evidence levels)
| Figure | Value | Kind (advertised/observed/executable/net/sustainable/risk-adj) | Evidence level (L0–L6) | Source | Last verified |
|---|---|---|---|---|---|
| Headline APY | `TBD — requires verification` | | `L0` | | |
| Base APY | `TBD — requires verification` | | | | |
| Incentive APY | `TBD — requires verification` | | | | |
| Sustainable estimate | `TBD — requires verification` | | | | |

> No figure above may be treated as verified above its stated evidence level (ADR-YL-006).

## 4. Protocols & assets
- **protocols_used:** `[]`  <!-- each needs a Protocol Card (docs/12) before Enhanced/Max -->
- **assets_used:** `[]`
- **chains_used:** `[]`

## 5. Capacity & liquidity
- **capacity_estimate:** `TBD — requires verification`
- **suitable_capital_tiers:** `[]`  <!-- $100k / $1M / $10M / $100M+ (docs/34) -->
- **lockup / withdrawal_time:** `<...>`
- **exit-liquidity-by-size:** `<cite dfb/risk_overlay.py; do not synthesize>`

## 6. Risk summary (advisory)
_Top risks in plain language; note which trigger the Red Team requirement (leverage/credit/counterparty/
bridge/opaque/new-stablecoin/lockup/options/basis)._
- Advisory Risk Scoring v2 (docs/14): risk `TBD` / liquidity `TBD` / complexity `TBD` / confidence `TBD`
  — **advisory only, never an execution gate (ADR-YL-004).**

## 7. Data sources required
- `[]`  <!-- real, cited feeds only -->

## 8. Open questions / requires verification
- `<list every unknown; do not paper over gaps>`

## 9. Recommendation
- **recommendation:** `<research-only | advance to paper_testing | reject | defer>`
- **next gate:** `<what evidence is needed next>`
- **feeds:** IC memo `IM-XXXX` / Strategy Card `SC-XXXX`

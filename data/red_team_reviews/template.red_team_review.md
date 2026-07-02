# Red Team Review — <STRATEGY NAME>

> Fill-in Red Team review (§38 reporting set). **Mandatory** for Enhanced / MaxYield / Experimental
> and for any strategy involving leverage / credit / counterparty / bridge / opaque mechanism /
> new-stablecoin / lockup / options / basis. Adversarial by design — the reviewer's job is to make the
> strategy lose money on paper. Research-layer, advisory. **Never invent APY/TVL. Unknown =
> `TBD — requires verification`.** Cross-refs: `docs/11_strategy_card_system.md`,
> `spa_core/redteam/`, `docs/14_risk_scoring_v2.md`.

- **review_id:** `RT-XXXX`  ·  **strategy_id:** `SC-XXXX`
- **red_teamer:** `<name — should not be the strategy author>`  ·  **date:** `<ISO-8601 UTC>`
- **verdict:** `<passed | failed | conditional>`

## 1. How do we lose money? (loss scenarios — fill EVERY row)
| Scenario | Can it happen here? | Mechanism | Est. loss | Mitigated? |
|---|---|---|---|---|
| **Depeg** (stablecoin / LST / wrapped asset off peg) | | | `TBD — requires verification` | |
| **Exploit** (contract hack, bug, admin key) | | | `TBD — requires verification` | |
| **Liquidity freeze** (withdrawals halted / queue / gated redemptions) | | | `TBD — requires verification` | |
| **APY compression** (rate falls / incentives end / capacity dilutes yield) | | | `TBD — requires verification` | |
| **Market crash** (BTC/ETH −50%, correlated de-risk, funding flip) | | | `TBD — requires verification` | |
| **Counterparty failure** (CEX / issuer / market-maker / bridge default) | | | `TBD — requires verification` | |

## 2. Additional adversarial checks
- **Oracle failure / manipulation:** `<...>`
- **Governance attack / malicious upgrade:** `<...>`
- **Gas spike / congestion during exit:** `<...>`
- **Basis / funding reverses:** `<...>`
- **Exit slower than expected (size vs depth):** `<...>`

## 3. Hidden assumptions
_List every assumption the thesis silently relies on. The most fragile one first._
- `<hidden leverage? assumed peg? assumed a CEX leg stays solvent? assumed incentives persist?>`

## 4. Most-fragile assumption
- **single point of failure:** `<the one thing that, if false, breaks the strategy>`

## 5. Final objections
_The strongest reasons NOT to approve, stated plainly._
- `<objection 1>`
- `<objection 2>`

## 6. Minimum mitigations (required before advancing)
- `<mitigation 1 — e.g. cap, monitor, hedge, staged sizing, kill trigger>`
- `<mitigation 2>`

## 7. Verdict & conditions
- **verdict:** `<passed | failed | conditional>`
- **conditions (if conditional):** `<...>`
- feeds → IC memo `IM-XXXX`, Strategy Card `red_team_status`.

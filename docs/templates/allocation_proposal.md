# Allocation Proposal — <STRATEGY / PORTFOLIO NAME>

> **Task:** PORT-002. **Advisory / recommendation-only (L0/L1).** This proposal **does not execute**,
> does not move capital, and does not override RiskPolicy. It requires a human approval signature
> (below) before any action. Copy this file per proposal. Fill unknowns with `REQUIRES VERIFICATION`
> — never invent floor / APY / TVL / capacity numbers.
> **Related:** `docs/17_portfolio_construction.md`, `docs/34` (capital tiers), `docs/06` (invariants),
> `docs/adr/ADR-YL-008` (spread-over-floor).

## 1. Summary

- **Proposal id:** PROP-YYYY-MM-DD-NN
- **Prepared by / date:** <session/agent> · <UTC date>
- **Portfolio model:** <Preserve | Core | Enhanced | MaxYield> (+ sleeve: <BTC-cycle | ETH-yield | Experimental | none>)
- **Capital tier (`docs/34`):** <tier> · **Sizing basis:** $<amount or notional> (paper)
- **Action:** <new allocation | rebalance | de-risk to floor>

## 2. Line items (proposed)

| # | Strategy / card id | Lifecycle state | `spread_fully_explained` | Proposed weight % | Proposed $ | Tier (T1/T2) |
|---|---|---|---|---|---|---|
| 1 |  |  | yes/no |  |  |  |
|   | **Cash buffer** | — | — |  |  | — |
|   | **Total** | — | — | 100% |  | — |

> Every line item **must** have cleared the Yield Lab lifecycle (`docs/07`) and have
> `spread_fully_explained = true`. A `no` in that column ⇒ **remove the line** — do not submit.

## 3. Spread-over-floor basis (ADR-YL-008)

- **Live RWA floor used:** <value> % · **source:** `data/rwa_feed.py` · **as-of:** <UTC ts>
  (fail-closed literal fallback? yes/no — if yes, flag it) · **hardcoded?** NO
- Per line item:

| Strategy | Observed/sustainable APY | Spread over floor (bps) | Itemized risk explanation (each bp → named accepted risk) | Unexplained spread (bps) |
|---|---|---|---|---|
|  |  |  |  | **0** (required) |

> If any line shows `unexplained_spread > 0` (beyond documented tolerance) ⇒ that line is **REJECTED**
> (record in the refusal log) and removed from this proposal.

## 4. Cap-check (must ALL pass — most restrictive wins)

### 4a. RiskPolicy hard caps (authoritative — `docs/06` A.1, `spa_core/risk/policy.py` v1.0)

| Cap | Requirement | This proposal | Pass? |
|---|---|---|---|
| TVL floor / pool | ≥ $5M |  |  |
| Per-protocol (T1) | ≤ 40% |  |  |
| Per-protocol (T2) | ≤ 20% |  |  |
| T2 total | ≤ 50% |  |  |
| APY gate | 1%–30% |  |  |
| Min cash buffer | ≥ 5% |  |  |

> Any RiskPolicy `Fail` ⇒ **do not submit**. RiskPolicy `approved=False` is final and non-overridable.

### 4b. Capital-tier caps (`docs/34` — the tier wins over the model)

| Tier constraint | Requirement | This proposal | Pass? |
|---|---|---|---|
| Allowed strategies for tier |  |  |  |
| Per-strategy cap for tier |  |  |  |
| Capacity / liquidity for tier |  |  |  |

### 4c. Model / sleeve caps (`docs/17`)

| Constraint | Requirement | This proposal | Pass? |
|---|---|---|---|
| Model eligible set |  |  |  |
| Sleeve isolated + capped |  |  |  |
| Experimental → paper only (no live/public capital) |  |  |  |

## 5. De-risk / stop deference

- Two-tier kill-switch is authoritative (SOFT ∈ [5%,10%); HARD ≥10% → all-cash). This proposal
  **defers** to it and proposes nothing looser. Advisory stricter trigger (if any): <describe / none>.

## 6. Risk Scoring v2 (advisory, `docs/14`)

- Advisory verdict / notable sub-scores: <…> (advisory only — never a gate). Low
  `spread_attribution_score` ⇒ human-review + red-team already required (§3).

## 7. Human approval (required before any action)

> This proposal is **inert** until signed. No execution, no capital movement occurs from this file.

- [ ] Reviewed spread-over-floor basis (§3) — no unexplained spread
- [ ] All cap-checks pass (§4)
- [ ] Defers to kill-switch (§5)
- **Approved by (human):** ________________  **Date (UTC):** ____________  **Decision:** APPROVE / REJECT / REVISE
- **Notes:**

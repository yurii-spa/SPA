# 39 — Investment Committee Workflow (§37)

**Status: STUB.** This document is a Priority-3 placeholder for the investment-committee (IC) memo
and approval workflow — the gated path a candidate strategy travels from discovery to allocation.
It lists the stages only; per-stage detail is deferred.

**Scope discipline.** Research / decision-support only. This workflow produces memos and approval
records; it does not move capital, sign, or override the deterministic RiskPolicy (see
`06_spa_core_invariants.md`, invariants A/B). Human approval is mandatory; default autonomy is
L0/L1.

**Cross-references:** `docs/07_yield_lab_lifecycle.md` (lifecycle statuses this workflow gates),
`docs/14_risk_scoring_v2.md` (advisory scores consumed at review stages), `docs/37` (APY evidence
levels required to advance).

## Planned contents (outline only)

- **19-stage flow (candidate → allocation), each stage to specify: owner · required docs ·
  pass/fail criteria.** Indicative stages (to be finalized at MVP 2-3):
  1. Candidate intake
  2. Initial screen
  3. Yield-source verification
  4. Protocol due-diligence review
  5. Stablecoin due-diligence review (if applicable)
  6. Liquidity / capacity review
  7. Risk Scoring v2 (advisory)
  8. Red-team review (mandatory for higher-risk lines)
  9. Capital-tier fit review
  10. Paper-test plan definition
  11. Paper-test execution
  12. Paper-test results review
  13. IC memo drafting
  14. IC review / discussion
  15. Human approval decision
  16. Small-capital-test plan
  17. Small-capital-test results review
  18. Allocation approval (per product line / tier)
  19. Post-allocation monitoring & review
- **Per-stage template** — owner, inputs, required docs, pass/fail gate, artifacts produced.
- **Decision-log linkage** — every stage outcome recorded in the hash-chained decision log.
- **Escalation & refusal paths** — when a stage fails, freezes, or triggers red-team.

TODO: expand at MVP 2-3 stage.

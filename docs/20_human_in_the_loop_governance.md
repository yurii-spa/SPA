# 20 — Human-in-the-Loop Governance (autonomy ladder L0–L5)

> Research-layer document. This is the **charter-central autonomy ladder** for the Yield Lab /
> AI Investment OS. It defines, per level, what is allowed, what is forbidden, the limits, the
> approvals required, and the criteria to transition up. **The default now is Level 0 / Level 1.**
> Charter: [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md) (autonomy).
> Related: [`06_spa_core_invariants.md`](06_spa_core_invariants.md) (E.19),
> [`19_execution_support.md`](19_execution_support.md), [`21_security_and_custody_rules.md`](21_security_and_custody_rules.md),
> [`adr/ADR-YL-005-execution-support-is-non-custodial.md`](adr/ADR-YL-005-execution-support-is-non-custodial.md),
> [`adr/ADR-YL-007-btc-eth-cycle-modules-are-decision-support-not-autotrading.md`](adr/ADR-YL-007-btc-eth-cycle-modules-are-decision-support-not-autotrading.md).

---

## 0. Principle

Autonomy is a **ladder, not a switch.** Each rung up narrows the human's role and must be justified by
evidence, approved by the owner, and recorded in an ADR. **No rung ever removes the deterministic
RiskPolicy or the two-tier kill-switch as the sole hard gate, and no rung ever grants the AI custody,
keys, or signing authority** (invariants A.1–A.4, B.5–B.6). The transition up a level is a deliberate
owner decision — never an emergent behavior.

## 1. The ladder

### L0 — Research (default)
- **Allowed:** discovery, analysis, due diligence, risk memos, red-team reviews, IC drafts, reporting.
- **Forbidden:** any recommendation presented as an instruction to act; any capital effect.
- **Limits:** produces knowledge only.
- **Approvals:** none needed to research; nothing actionable is emitted.
- **Transition ↑:** n/a (baseline).

### L1 — Recommendation (default)
- **Allowed:** explicit recommendations with rationale, evidence level, risk category, and spread
  attribution (ADR-YL-008); Strategy Card proposals; portfolio suggestions.
- **Forbidden:** preparing or executing transactions; moving capital; any custody.
- **Limits:** advisory output only; a human decides and acts entirely separately.
- **Approvals:** IC/owner decides whether to act on any recommendation.
- **Transition ↑ to L2:** owner decision + ADR; recommendations demonstrably reliable and evidenced.

### L2 — Assisted (checklists)
- **Allowed:** producing the Execution Support artifacts of [`19`](19_execution_support.md) —
  transaction checklists, pre-execution risk/slippage/liquidity/gas checks, runbooks — for a human to
  execute manually.
- **Forbidden:** signing, key handling, fund movement, unsigned-tx auto-assembly into a signing flow.
- **Limits:** every step is performed by a human; the layer only prepares human-readable checklists.
- **Approvals:** owner enables L2 by ADR; each action still human-executed.
- **Transition ↑ to L3:** owner decision + ADR; checklists proven accurate over a track record;
  multisig topology + wallet separation defined ([`21`](21_security_and_custody_rules.md)).

### L3 — Semi-automated (unsigned tx + multisig)
- **Allowed:** assembling **unsigned** transaction drafts / approval packets routed to a human
  multisig for review and signing.
- **Forbidden:** holding keys, signing, broadcasting, or moving funds; straight-through processing.
- **Limits:** the AI is never a signer; a human multisig threshold reviews and executes; strict caps.
- **Approvals:** owner + ADR; multisig signers are humans; RiskPolicy + kill-switch unchanged.
- **Transition ↑ to L4:** owner decision + ADR; extensive live-with-human evidence; legal review if
  external capital is involved (invariant 18).

### L4 — Limited automation
- **Allowed:** narrowly-scoped, capped automated actions **only** within owner-approved bounds and
  **only** after L3 track record — still under the deterministic RiskPolicy and kill-switch.
- **Forbidden:** custody of keys/seeds by the AI; any action outside pre-approved caps; overriding the
  hard gate.
- **Limits:** tightly bounded scope, caps, and rollback; extensive monitoring and audit.
- **Approvals:** owner + ADR + (if external capital) legal review.
- **Transition ↑ to L5:** far-future; not contemplated in the current program.

### L5 — Full autonomy (far future only)
- **Allowed:** reserved as a far-future possibility; **not enabled**, no design committed.
- **Forbidden:** everything that would violate the permanent invariants — which L5 does **not** relax.
- **Limits:** would still never grant AI custody/keys/signing outside a human-controlled boundary, and
  would still keep the deterministic RiskPolicy as the hard gate.
- **Approvals:** owner + ADR + legal; explicitly out of current scope.
- **Transition ↑:** n/a.

## 2. Cross-level invariants (never relaxed by any rung)

- Deterministic **RiskPolicy v1.0** is the sole hard execution gate; **Risk Scoring v2 is advisory
  only** (ADR-YL-004), never a gate.
- **No LLM** in risk/execution/monitoring/kill. **No AI custody, keys, seeds, signing, or fund
  movement** at any level (invariants B.5–B.6, ADR-YL-005).
- **BTC/ETH cycle modules stay decision-support** at every level (ADR-YL-007).
- **External capital requires legal review** (invariant 18).
- Every level change is an **owner decision recorded in an ADR** — never emergent.

## 3. Current state

**Default = L0 / L1.** L2+ are documented targets only and are not enabled. Any move above L1 is
out of scope for the research layer and must be **escalated to the owner** before proceeding
([`security_review.md`](security_review.md) §4).
</content>

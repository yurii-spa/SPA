# 19 — Execution Support (non-custodial, human-in-the-loop)

> Research-layer document. Execution Support is **layer 5** of the target architecture. This doc
> specifies its workflow and its hard boundaries. It does **not** add any execution, signing, or
> custody capability — it describes how a **human** acts on an approved recommendation.
> Authoritative decision: [`adr/ADR-YL-005-execution-support-is-non-custodial.md`](adr/ADR-YL-005-execution-support-is-non-custodial.md).
> Related: [`06_spa_core_invariants.md`](06_spa_core_invariants.md) (B.5–B.6, E.18–19),
> [`20_human_in_the_loop_governance.md`](20_human_in_the_loop_governance.md),
> [`21_security_and_custody_rules.md`](21_security_and_custody_rules.md), [`security_review.md`](security_review.md).

---

## 0. Definition

**Execution Support prepares; it never acts.** It produces the operational artifacts a human needs to
review and execute an *already-approved* recommendation through their **own** custody / multisig. It is
strictly **non-custodial** and **human-in-the-loop**.

## 1. Hard rules (non-negotiable — invariants B.5–B.6, ADR-YL-005)

The AI / research layer, and every agent in it, **MUST NOT**:

1. **Hold private keys or see seed phrases / mnemonics** — ever, anywhere.
2. **Sign transactions** — no signing logic of any kind.
3. **Move, withdraw, or transfer funds** — no fund-movement logic of any kind.
4. **Bypass or weaken the deterministic RiskPolicy** or the two-tier kill-switch — these remain the
   sole hard gate (invariants A.1, A.3–A.4).
5. **Import `spa_core/execution/`** from any read-only / paper / research module, or write
   execution-owned state (e.g. `data/adapter_status.json`) (invariant B.6).
6. **Run straight-through processing** — there is deliberately no automated path from recommendation
   to on-chain action.

Default autonomy is **Level 0 / Level 1** (research / recommendation). Assisted checklists (L2) and
unsigned-tx + multisig (L3) are documented as **future, owner-gated** states, not enabled here
([`20_human_in_the_loop_governance.md`](20_human_in_the_loop_governance.md)).

## 2. What Execution Support MAY produce

- **Transaction checklists** (human-readable, step-by-step).
- **Unsigned transaction drafts / approval packets** — data for a human to review and sign in their
  own wallet/multisig. Never signed, never broadcast by this layer.
- **Operational runbooks** for the human operator.
- **Post-execution verification** procedures and **audit-log** entries.
- **Emergency-exit checklists.**

## 3. Transaction checklist (per action)

A prepared action packet contains, at minimum:

1. **What & why** — the approved recommendation, its Strategy Card id, and IC/owner approval reference.
2. **Pre-execution risk check** — confirmation the action is within deterministic RiskPolicy caps
   (TVL ≥ $5M/pool; per-protocol 40% T1 / 20% T2; T2 total ≤ 50%; APY 1–30%; min cash ≥ 5%) and that
   the kill-switch is not armed against the target.
3. **Slippage & liquidity check** — expected slippage vs a stated max; exit depth / horizon confirmed.
4. **Gas check** — current gas estimate vs an acceptable ceiling; chain state sane.
5. **Counterparty / protocol check** — protocol card current; no open CRITICAL alert
   ([`18_monitoring_and_alerting.md`](18_monitoring_and_alerting.md)).
6. **Unsigned draft** — target contract(s), method, parameters, and amounts, for human review.
7. **Approval line** — which human/multisig signers are required (see §4).

## 4. Multisig approval workflow (human-executed)

1. Execution Support assembles the packet (§3) and routes it for review.
2. Required human signers review the **unsigned** draft against the checklist.
3. Signers sign **in their own custody / multisig** — the research layer holds no keys and observes no
   secrets.
4. The multisig threshold executes the transaction. The research layer is never a signer.

> Wallet separation and the specific multisig threshold/topology are **future, owner-gated** design
> ([`21_security_and_custody_rules.md`](21_security_and_custody_rules.md)); parameters are marked as
> **requiring verification** until an owner decision + ADR set them.

## 5. Post-execution verification

- Confirm on-chain result matches the approved draft (target, amount, resulting position).
- Reconcile against expected portfolio state; flag any deviation for human review.
- Confirm no unexpected side effects (approvals left open, residual balances, wrong chain).

## 6. Audit log

Every prepared packet, approval, and post-execution verification is recorded in an append-only audit
trail (consistent with the existing hash-chained decision/refusal machinery — cf. `data/audit_trail.jsonl`
and the rates-desk decision log). The log captures: packet id, recommendation/card id, checklist
results, approvers, execution reference, and verification outcome. **No secrets are ever written to the
log or any file** ([`21_security_and_custody_rules.md`](21_security_and_custody_rules.md)).

## 7. Emergency-exit checklist

For a CRITICAL event (depeg / exploit / freeze / oracle / liquidation — [`18`](18_monitoring_and_alerting.md)):

1. Confirm the event and affected positions.
2. Note the deterministic kill-switch state (SOFT/HARD) — it acts independently on drawdown; do not
   assume this layer triggered it.
3. Assemble the exit packet (unsigned) with priority ordering by exit depth/urgency.
4. Route to required signers for immediate human review and execution.
5. Verify exits post-execution and update the audit log; escalate residual exposure to owner.

> External capital, when contemplated, additionally requires **legal review** before acceptance
> (invariant 18) — orthogonal to and on top of this custody boundary.
</content>

# ADR-YL-005: Execution Support is non-custodial and human-in-the-loop

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab)                                  |
| **References**  | `docs/06_spa_core_invariants.md` (B.5–B.6, 18–19), `prompts/claude_code/yield_lab_master.md` (layer 5, autonomy), `spa_core/execution/` |

---

## Context

The layered architecture includes an **Execution Support** layer (layer 5) that prepares the
operational steps to act on an approved recommendation. The security-critical risk is that such a
layer accretes custody: private keys, seed phrases, auto-signing, or fund-movement authority. SPA
Core invariants B.5–B.6 forbid all of these anywhere in the codebase or any agent, and require that
`spa_core/execution/` is never imported from read-only/paper/research code.

## Decision

**Execution Support is strictly non-custodial and human-in-the-loop.** It prepares; it never acts.

- No private-key handling, no seed phrases, no auto-signing, no fund movement, no withdrawals — in any
  module or agent (invariant B.5). This is a hard, permanent boundary.
- Execution Support may produce **checklists, unsigned transaction drafts, approval packets, and
  operational runbooks** for a human to review and execute through their own custody/multisig. It
  never holds keys or controls funds.
- Default autonomy stays **Level 0 / Level 1** (research / recommendation). Higher levels (L2 assisted
  checklists, L3 unsigned-tx + multisig) are documented as future, owner-gated states — not enabled by
  this ADR.
- Research-layer and paper code must **not import `spa_core/execution/`** (invariant B.6). Execution-
  owned state (e.g. `data/adapter_status.json`) is never written by read-only/research code.

## Consequences

- **Positive:** the AI/research layer can never move money; a compromise of the research layer cannot
  reach custody; the trust boundary is auditable and singular.
- **Negative / cost:** every live action requires a human in the loop — deliberately no
  straight-through processing.
- **Neutral:** external capital, when contemplated, additionally requires legal review before
  acceptance (invariant 18) — orthogonal to this custody boundary.

## Alternatives considered

- **Semi-automated signing behind a policy engine** — rejected: introduces custody and an
  auto-signing surface; violates B.5 and the master prompt's non-negotiable trust invariants.
- **Let an agent hold a hot wallet with tight caps** — rejected: any key custody by an agent is
  forbidden regardless of caps; caps do not make custody safe here.

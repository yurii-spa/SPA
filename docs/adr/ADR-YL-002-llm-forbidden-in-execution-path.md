# ADR-YL-002: LLM is forbidden in the risk / execution / monitoring / kill path

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab)                                  |
| **References**  | `docs/06_spa_core_invariants.md` (A.2), `spa-lint.yml`, `spa_core/risk/policy.py`, `spa_core/governance/kill_switch.py`, `docs/14_risk_scoring_v2.md` |

---

## Context

The Yield Lab introduces LLM-assisted research, memos, red-team reviews, and decision-support. There
is a standing temptation to let an LLM "just decide" allocation, tune the kill-switch, or gate
execution. SPA Core invariant A.2 forbids any LLM in the risk, execution, monitoring, or kill path;
this is enforced by the LLM-forbidden lint (`spa-lint.yml`). The determinism of these paths is the
reason the desk's decisions are reproducible and auditable.

## Decision

**No LLM output may enter the risk, execution, monitoring, or kill path — directly or indirectly.**

- The deterministic RiskPolicy (`spa_core/risk/policy.py`) and the two-tier kill-switch
  (`spa_core/governance/kill_switch.py`) remain LLM-free and deterministic.
- LLM/AI is permitted only for **research and recommendation** outputs: due-diligence, risk memos,
  red-team reviews, IC memos, cycle/market analysis, reporting, and planning.
- No LLM-produced value may be imported into or read by any execution, risk-gate, monitoring, or
  kill-switch code path. Advisory Risk Scoring v2 (`docs/14`) is likewise deterministic and advisory
  (see ADR-YL-004); it is not an exception to this rule.
- The LLM-forbidden lint stays authoritative; a research module that would trip it belongs in the
  research layer, not the runtime core.

## Consequences

- **Positive:** every money-adjacent decision remains reproducible, testable, and auditable; no
  prompt-injection or model-drift surface exists on the execution path.
- **Negative / cost:** LLM insight can inform a human decision but can never *be* the decision;
  recommendations require a deterministic gate + human approval to act.
- **Neutral:** research velocity is high because the research layer is unconstrained by determinism,
  while the core stays boring on purpose.

## Alternatives considered

- **LLM-in-the-loop risk gate with guardrails** — rejected: any LLM on the execution path breaks
  determinism and the "don't trust us, check us" proof model; guardrails cannot restore
  reproducibility.
- **LLM tunes RiskPolicy parameters offline, humans rubber-stamp** — rejected: parameter changes
  must go through an ADR + owner decision (invariant A.1 / E.14), not model output.

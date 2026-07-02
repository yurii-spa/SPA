# ADR-YL-004: Risk Scoring v2 is advisory, not an execution gate

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab)                                  |
| **References**  | `docs/14_risk_scoring_v2.md`, `docs/06_spa_core_invariants.md` (A.1–A.4, 17), `spa_core/risk/policy.py`, `docs/11_strategy_card_system.md` (§3.5) |

---

## Context

The Yield Lab introduces **Risk Scoring v2** — a 0–100 multi-sub-score advisory scorecard
(green/yellow/red, hard-reject / human-review / red-team triggers) used to compare candidate
strategies on the Strategy Card. There is a natural temptation to wire this score to allocation
("score ≥ X ⇒ allocate"). SPA Core invariant A.1 makes the deterministic RiskPolicy the *sole* hard
execution gate; A.2 keeps LLM/heuristic scoring out of the execution path.

## Decision

**Risk Scoring v2 is advisory only.** It informs human review and Strategy Card comparison; it is
**never** an execution gate.

- The deterministic RiskPolicy (`spa_core/risk/policy.py`, `version: v1.0`) remains the **only** hard
  execution gate. An `approved=False` from RiskPolicy cannot be overridden by any advisory score.
- Risk Scoring v2 is **not imported into** and **not read by** the execution path, the RiskPolicy, the
  monitoring path, or the kill-switch. It is deterministic (not LLM — see ADR-YL-002) and lives in the
  research/scoring layer.
- Its outputs (`risk_score`, `liquidity_score`, `complexity_score`, `confidence_score` on a Strategy
  Card) can *trigger* human review or a red-team requirement, and can *block a promotion decision*,
  but cannot *approve* or *size* any live position.
- In the first pass it is not wired to live execution at all.

## Consequences

- **Positive:** candidate strategies get a consistent, comparable risk read without creating a second,
  softer execution gate that could contradict the deterministic one.
- **Negative / cost:** a "good" advisory score never authorizes capital by itself — RiskPolicy caps
  and human approval still bind.
- **Neutral:** the score is free to be richer/heuristic than the deterministic gate, because it never
  touches money.

## Alternatives considered

- **Promote Risk Scoring v2 to a soft gate feeding the allocator** — rejected: creates a competing
  gate, breaks the single-authoritative-gate invariant (A.1), and risks LLM/heuristic drift on the
  money path.
- **Drop advisory scoring entirely, rely only on RiskPolicy** — rejected: the deterministic gate is
  intentionally coarse; comparable per-strategy scoring is needed for research and promotion decisions.

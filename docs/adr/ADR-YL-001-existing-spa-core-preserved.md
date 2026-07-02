# ADR-YL-001: Existing SPA Core is preserved, not replaced

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab) — independent of `docs/adr/ADR-0xx` |
| **References**  | `docs/06_spa_core_invariants.md`, `prompts/claude_code/yield_lab_master.md`, `docs/07_yield_lab_architecture.md` |

---

## Context

The Yield Lab / AI Investment OS is being added on top of a live, paper-tracked SPA Core:
deterministic RiskPolicy (`spa_core/risk/policy.py`, `version: v1.0`), a running paper cycle
(`spa_core/paper_trading/cycle_runner.py`), GoLiveChecker (29 criteria), a public dashboard, and a
launchd agent fleet. That core is the desk's *trust foundation* — its value is the honest, continuous
paper track and the conservative, verifiable book behind it.

A common failure mode when adding a research/AI layer is a big-bang rewrite that silently breaks the
track, weakens the risk gate, or drifts the architecture. The master prompt (STEP 0, operating mode)
forbids this explicitly.

## Decision

SPA Core is **preserved as-is** and treated as an immutable trust foundation. The Yield Lab is built
*around* it, never *through* it. Specifically:

- No existing runtime module, RiskPolicy value, paper-cycle behavior, dashboard, or deploy path is
  modified by Yield Lab work.
- All Yield Lab artifacts (research docs, Strategy Cards, reporting templates, advisory scoring,
  decision-support modules) are **new files in new directories** (`docs/NN_*.md`,
  `data/strategy_cards/`, `data/research_reports/`, `data/ic_memos/`, `data/risk_reviews/`,
  `data/red_team_reviews/`, and non-runtime `spa_core/strategy_lab/*` research modules).
- Runtime `data/*.json` formats are not broken without a migration plan (invariant D.10).
- Any change that would touch the execution path, RiskPolicy, public dashboard, or deployment is
  out of scope for the research layer and must be escalated to the owner.

## Consequences

- **Positive:** the paper track and go-live evidence stay intact and honest; the research layer can
  iterate fast with zero blast radius on production; a reviewer can verify each SPA Core invariant
  against its named enforcement point (`docs/06`).
- **Negative / cost:** some duplication of read-only concepts across the research layer; research
  outputs cannot directly move capital (by design — see ADR-YL-004, ADR-YL-005).
- **Neutral:** the two layers evolve on separate cadences.

## Alternatives considered

- **Refactor SPA Core to host the Yield Lab natively** — rejected: high risk to the live track and
  the deterministic gate; violates the master prompt's no-big-bang-rewrite rule.
- **Fork the repo for the Yield Lab** — rejected: fragments the single source of truth and the
  proof chain; the desk's differentiator is one auditable repo, not two.

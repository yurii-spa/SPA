# ADR-YL-### — <short decision title>

> **Task:** CCW-003. Template for **Yield Lab** Architecture Decision Records. ADRs are namespaced
> **`ADR-YL-###`** to avoid collision with the existing `docs/adr/ADR-0xx` series (do not renumber or
> touch those). Copy this file to `docs/adr/ADR-YL-<next-number>-<slug>.md`, pick the next unused
> `ADR-YL` number, and fill every section. Invent no numbers; unknown = "requires verification".
> **Related:** `docs/06` (invariants), `docs/28` §7 (docs-first / ADR namespacing).

**Status:** Proposed | Accepted | Superseded (by ADR-YL-###) | Rejected  
**Date:** <UTC date>  
**Deciders:** <owner / session>  
**Related:** <docs/…, ADR-YL-…, prompts/…> · **Preserves:** SPA Core invariants (`docs/06`)

## Context

<The forces at play: the problem, the constraint, the tension being resolved. Cite the invariants
(`docs/06`) and any prior ADR-YL this touches. State facts you know; mark unknowns "requires
verification" — do not invent figures.>

## Decision

<The decision, stated plainly and unambiguously. If it resolves an open question (`docs/31`), say so.
The decision must **preserve** all SPA Core invariants — it may only make gates stricter, never
looser; it may not touch RiskPolicy `version`, the kill-switch, custody/keys, or the execution path
unless it is an explicit, owner-gated ADR that says exactly that.>

## Consequences

- **Positive:** <…>
- **Negative / trade-offs:** <…>
- **Invariant impact (`docs/06`):** <confirm none violated; if an invariant changes, this must be an
  owner-gated decision and stated here explicitly — RiskPolicy stays v1.0 unless the ADR changes it by
  name.>
- **Follow-up work / affected docs & schemas:** <…>

## Alternatives considered

- **A — <name>.** <what it was; why rejected/deferred.>
- **B — <name>.** <what it was; why rejected/deferred.>

## Status notes

<Adoption / supersession trail. If Superseded, link the replacing ADR-YL-###.>

# P1 — ADR number allocation race (separate from the production-boundary task)

**Recorded 2026-09-28. NOT implemented here — a future deterministic allocation mechanism is recommended.**

## Observed
`origin/main` has multiple automatic writers (director cycles push via the GitHub API). During the Studio OS
promotion, an automatic cycle (`603b3007`) allocated **ADR-498** for its own topic at nearly the same time the
promoted set intended ADR-498 — a concurrent allocation of the same number. It was caught because the promotion
pre-check reads the base INDEX, and the proposal here was renumbered 498 → 499. But the collision is structural:
two writers can pick the same next number because "next free number" is read-then-written without a lock.

## Why it matters
ADR numbers are identity. A silent collision puts two different decisions under one number (invariant-17 class:
two meanings, one name), and only a lucky pre-check caught it. As automatic writers increase, the race widens.

## Recommendation (future work, not now)
A deterministic ADR allocation that does not depend on read-then-write of "highest + 1":
- allocate from a monotonic counter committed atomically with the ADR (compare-and-set on push), or
- namespace automatic-writer ADRs (e.g. a reserved band) vs human/owner ADRs, or
- a pre-push interlock that re-reads the remote INDEX and refuses on collision (extend the existing
  `scripts/adr_number.py` + `push_to_github.py --allow-adr-collision` guard to be mandatory and server-checked).

No code changes in this task. Filed for a dedicated cycle.

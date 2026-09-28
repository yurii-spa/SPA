# ADR-496: Should the studio_shell visual-layer test suite be wired into the canonical CI c

- **Status:** ACCEPTED (Owner explicitly confirmed 2026-09-28: «I explicitly accept wiring the mandatory Studio OS safety/core tests into canonical CI») · owner: @yurii · project: studio-os
  > Renumbered before canonical promotion because origin/main already occupied the old ADR number (was ADR-492). Owner-authorized 2026-09-28; numbering change only — decision substance unchanged.
  > History: initially agent-drafted, then downgraded to OWNER_REVIEW (AI must not infer acceptance). The
  > Owner then EXPLICITLY accepted wiring the mandatory Studio OS safety/core tests into canonical CI
  > (2026-09-28), so this is now ACCEPTED. The CI implementation already validated on the candidate.

## Problem
Should the studio_shell visual-layer test suite be wired into the canonical CI command?

## Decision
Wire studio_shell/ into the prescribed CI run (CLAUDE.md + both workflows) so its projector/parity/CSRF tests gate CI

## Rationale
Every test dir must run in CI (test_ci_covers). studio_shell tests are CI-compatible (python + node available in Actions). Currently excluded via _ALLOWED_UNCOVERED pending owner approval because it edits the protected prescribed-run line + test_prescribed_run_matches_ci parity.

## Alternatives
Keep manual-only (risk: rot); move tests into spa_core/tests (import churn)

## Consequences
studio_shell tests become gating; CI slightly longer; needs node in CI (present)

## Evidence


## Related tasks


> PROPOSED — not an accepted decision. Owner confirmation promotes this to a numbered ADR.

> Promoted from DRAFT-wire-studio-shell-tests-into-ci on 2026-09-28T00:00:00Z by Owner confirmation (ADR-495 decision seam).

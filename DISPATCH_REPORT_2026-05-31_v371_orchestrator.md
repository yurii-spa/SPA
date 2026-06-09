# SPA Dispatch Report — v3.71 (orchestrator)

**Date:** 2026-05-31
**Sprint:** SPA-V371 — APY gap report persisted into the 4h export pipeline
**Mode:** autonomous scheduled run (`spa-dev-continue`)

## Decision

Last completed sprint per KANBAN was **v3.70** (`orchestrator-v370`). Status pass forbidden.
v3.70 ends in `0` → periodic architect review due. The LLM architect
(`spa_core.dev_agents.architect`) cannot run in this sandbox (no `ANTHROPIC_API_KEY`,
proxied network), so a **manual backlog review** was performed:

- The task file's starter candidate list **SPA-V326..V332** is fully complete
  (sprints v3.26–v3.32 in the log: MEV Protection, DeFiLlama live APY, Pendle PT,
  Sky/sUSDS, architect review + KANBAN housekeeping, PostgreSQL migration prep,
  go-live dashboard update).
- No unblocked HIGH code work remains. The critical path to go-live (2026-07-15)
  is **user-action-blocked** (SPA-BL-012; secrets SPA-BL-007/008/009, BL-004/005/006).
- Feed-health monitor is **frozen** (SPA-BL-011). Money-moving is out of autonomous scope.

Selected a genuinely useful, safe, read-only analytics surface: the existing
`data_pipeline/apy_gap_report.py` module (current weighted APY vs the 7.3% target,
plus Pendle/Sky lever estimates) was only used in tests/`github_pusher` and was
**never emitted to `data/`**. Wired it into the 4h export pipeline so the gap-to-target
analysis becomes a durable, dashboard-visible artefact.

## Changes

- `spa_core/export_data.py` — new guarded block "APY gap report (SPA-V371)" right
  after the `golive_combined_verdict` block (SPA-V367). Runs `apy_gap_report(trader.get_status())`,
  wraps the result with `schema_version`+`generated_at`, writes `data/apy_gap_report.json`,
  registers it in the `files_written` manifest and section-health. Mirrors the
  SPA-V362/V367 pattern exactly; try/except so it never aborts the cycle.
- `spa_core/tests/test_apy_gap_export.py` — new, 13 tests.
- Backend module `apy_gap_report.py` **unchanged** (already correct).
- NOT money-moving (eth_signer/mev_protection/adapters untouched); NOT a new
  feed-health monitor (SPA-BL-011 respected).

## Tests

- `test_apy_gap_export.py` — **13 passed** (report contract + export wiring).
- Regression `test_readiness_score.py` + `test_covariance_export.py` — **116 passed, 0 failed**.
- `py_compile` OK; synthetic smoke arithmetic verified (weighted 3.9% / gap 3.4%);
  KANBAN.json round-trip OK.

## Escalations (require user action)

1. ⚠️ **GitHub PAT is stored in plaintext** in the scheduled-task body and in every
   `push_v*.html`. This is a secret leak — recommend revoking the token and moving
   it to a secret store.
2. The autonomous loop has been in steady-state "useful surface/analytics" mode
   since ≈v3.61. The go-live critical path stays user-action-blocked.
3. Housekeeping debt (NOT done autonomously to avoid unconfirmed destructive
   actions): ~100 `*.bak.*` files, dozens of `push_v*.html`, and a 7 MB
   `httpserver.log` can be cleaned on confirmation.

## Next sprint (SPA-V372) candidates

(a) Surface `apy_gap_report.json` as an index.html dashboard widget;
(b) persist apy-gap history + sparkline trend of `current_weighted_apy`;
(c) housekeeping cleanup on user confirmation;
(d) FEAT-001 Phase 3 live execution once SPA-BL-012 is unblocked (out of autonomous scope).

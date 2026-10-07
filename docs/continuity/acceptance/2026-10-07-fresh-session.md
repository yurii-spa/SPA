# Fresh-session acceptance — ARB-CONTINUITY-01 (2026-10-07)

> Dated evidence record (not a living document). Method: `docs/continuity/FRESH_SESSION_PROMPT.md`.
> Each run: a NEW model session with no chat history and no project memory, read-only access to a
> `git archive` export of `docs/ architecture/ spa_core/studio_os/ nimbalyst-local/tracker/_BOARD.md README.md`
> at the named commit, no code execution. Grading: a separate independent session (Opus) opened the cited
> canonical files and compared with production facts measured the same night. A wrong confident answer fails.

| Run | Commit read | Model (answering) | Duration | Files opened | Result |
|---|---|---|---|---|---|
| 1 | `3106fdc78bad` | Claude Sonnet 5, fresh subagent | ~190 s | 8 | **FAIL** — 30 correct · 3 correct-UNKNOWN · 2 stale-source · **1 wrong-confident** |
| 2 | `058957d5c` | Claude Sonnet 5, fresh subagent (new instance) | ~203 s | 14 | **PASS** — 34 correct · 2 correct-UNKNOWN · 0 stale · 0 wrong |

## Run 1 — why it failed

- **#36 (wrong-confident):** «read-only Capital commands are a planned gap, not delivered». Cause: curated
  text lagged the delivery — `docs/ROADMAP.md` item 10 debt list and `OWNER_INTENT_LEDGER.md` INT-08
  `known_gaps` still named the commands as missing although ADR-612 was in the tree. ADR outranks ROADMAP
  (ARCHITECT_CONTEXT §5), and the session asserted a negative while calling its own context stale.
- **#25, #30 (stale-source):** same stale ROADMAP debt list / «next safe action: deliver waves A–C».
- **Freshness rule defect:** the no-machine rule «STALE when `origin_commit` ≠ head» fires on every committed
  snapshot (a commit cannot contain its own hash).

Fixed in `6189f13a`: ROADMAP items 10–11, INT-01/INT-08, ADR-612 decision topic, BOOTSTRAP four-step
no-machine rule (snapshot-only commits pass; ADR canon check before any negative claim), recovery pointer
to `docs/DISASTER_RECOVERY.md` + ADR-611; snapshot regenerated in `058957d5c`.

## Run 2 — passed

- Freshness applied correctly: step 2 passed (only `docs/continuity/` changed between `6189f13a` and head),
  step 3 read ADR-613/614, verdict «trust as CONTEXT_PARTIAL» = `verdict_at_generation`.
- UNKNOWN/PARTIAL used honestly: #10 real capital (no observation time), #29 production one code commit
  behind origin.
- The session itself surfaced a coverage gap: origin/main test health (ADR-613) is not in CURRENT_STATE.

## Follow-ups from the grader (handled in the next generator change)

1. CURRENT_STATE header still printed the old freshness rule.
2. A COMMITTED_SNAPSHOT must be generated from a clean root (dirty inputs cannot be proven off-machine).
3. Header `adr_max_considered` so step 3 triggers only on genuinely new ADRs.
4. New section «origin/main test health» (MEASURED / MEASURED_ZERO / NOT_MEASURED from a machine artifact).
5. Open (debt, not fixed here): shelf `next_publication` 2026-10-08 vs site freshness monitor 2026-10-12.

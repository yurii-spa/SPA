# Release CI v4 — run 40465677790 on `release/task-prep-20261026` = `4a326236bc0ce6a0afd13b684ac3e7e5586aff54`

- Branch fast-forwarded 6ca0ce2a8 → 4a326236b (no force); no earlier run for this SHA; ONE dispatch.
- Report/manifest SHA = `4a326236b…`; RED.

| population | passed | failed | error | skipped | not obtained | collect errors | shards complete |
|---|---|---|---|---|---|---|---|
| 136309 | 135532 | 57 | 1 | 719 | 0 | 0 | 12/12 |

## Against the exact parent 6ca0ce2a8 / 40353173933
`ci_control.py compare`: **fixed 9 · new 1 · pre-existing 57 · not obtained 0**.
- The 9 problem outcomes of the parent (7 timeouts in `Resolver.enter → ast.walk`, 2 internal errors) are FIXED:
  `test_python_git_ref_provenance.py` here = 45 passed + 4 failure (exactly the four pre-existing IDs), slowest test 23.7 s
  (was ≥180 s). None became skipped.
- **NEW 1:** `spa_core/tests/test_tracker_board_matches_cards.py::test_live_board_matches_live_cards` — 7 cards read
  `done` while `_BOARD.md` says `in-progress`. Reported from `junit-resume-1.xml`: shard 7 CRASHED on
  `test_run_identity_key_price.py::BatteryHoleTests::test_the_instrument_excludes_itself_by_naming_the_reason`
  (the 1 error) and resumed in the same checkout (attempts 2). The tracker files of v3 and v4 are byte-identical
  (the release delta is one scanner file). A resumed shard reading a tracker modified by the interrupted attempt is the
  leading hypothesis — NOT established; a bounded local rerun of the two tests on this exact SHA is recorded below.
- Package tests executed and passed (same cohorts as the parent run).

Not green; not NO_REGRESSION. Criterion «no new failed/error» is NOT met by this run.

## Bounded check of the NEW board failure (27.10, local)
- On a clean tree of exactly `4a326236b`: `test_live_board_matches_live_cards` **fails the same way** (7 cards `done`, board
  `in-progress`); the tracker is unchanged after the run ⇒ the «resumed-shard pollution» hypothesis above is REFUTED.
- On a clean tree of `6ca0ce2a8` (which PASSED this test in CI 40353173933 on 26.10) the same test **fails today** too.
  Same bytes, different verdict by date ⇒ the test outcome depends on the date, not on the package (mechanism not
  identified). Today's scheduled main CI 40454032149 passes it — main's tracker/board is newer.
- `test_run_identity_key_price::BatteryHoleTests` (the shard-7 crash point): 37 passed locally in a clean tree (41 min).
- Consequence: the delivery gate is evaluated on a candidate built on CURRENT main (`d8baff308`, CI 40469786128), not by
  relabelling this run.

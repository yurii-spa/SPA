# Release CI — run 40353173933 on `release/task-prep-20261026` = `6ca0ce2a8cff3b2d44aa94e9e32f7b3c499736b7`

- Report/manifest SHA = `6ca0ce2a8cff3b2d44aa94e9e32f7b3c499736b7` (exact published release commit). RED.

| population | passed | failed | error | skipped | not obtained | collect errors | shards complete |
|---|---|---|---|---|---|---|---|
| 136309 | 135524 | 63 | 3 | 719 | 0 | 0 | 12/12 |

## Base for comparison
No ci-control run exists on the exact base `main` `37e06e185`. Nearest available: scheduled run **40328594274** on
`d0c3c59ed` — an ancestor of `37e06e185` by ONE commit (ADR-820: `slo_keepability.py`, `slo_proposal.py`,
`test_write_attribution_census.py` + docs). Comparable but not identical — stated, not hidden.
Base result: 136042 total · 135266 passed · 57 failed · 0 error · 12/12.

`ci_control.py compare 40328594274 → 40353173933`: **new 9 · pre-existing 57 · not obtained 0 · fixed 0**.

## The 9 new — all in `spa_core/tests/test_python_git_ref_provenance.py`, shard 8, one cascade
- Trigger: `TestRatchet::test_a_baseline_without_the_schema_is_unmeasured_not_clean` — **Timeout (>180 s)**;
  on the base run the same test PASSED in 135.8 s, and the file's tests there take 140–165 s each (near the limit).
- After the timeout the shard harness crashed three times on tests of this file (`crashed_on`, 4 attempts, wall 3613 s);
  the rest of the file is `failed`/`error` "pytest internal error … not re-run" — a cascade, not separate assertions.
- Cause of the slowdown NOT established by one run. The package adds 23 paths (~4.8k lines, incl. 7 modules with git
  calls) to the tree this whole-tree census walks; an effect of the package is NOT excluded. On the base, this file's
  real-tree test is already red (+28 subjects of main's own code) — pre-existing.

## Previous integration errors
`test_foreign_markup_reader_census.py::test_the_live_tree_is_measured_and_the_custodian_is_in_the_class` — **passed**
(105.1 s); `::test_the_tree_agrees_with_the_live_measurement_of_adr_594` — **passed**. The red integration CI
40317312101 is kept as it was; this pass is a different tree (release), not a retroactive change of that result.

## Package tests in this CI (executed, all passed)
test_task_prep_record 38 · test_task_prep 43 · test_model_roles_contract 27 · test_model_roles_review 19 ·
test_model_roles_probe 78 · test_role_pack 15 · test_owner_view 104 · test_cockpit_loop 26. No failure in any package or
cockpit test file.

Not green; not NO_REGRESSION. No further full run was started automatically.

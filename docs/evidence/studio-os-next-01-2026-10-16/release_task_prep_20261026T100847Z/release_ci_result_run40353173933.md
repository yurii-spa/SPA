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

## The 9 new — `spa_core/tests/test_python_git_ref_provenance.py`, shard 8 (corrected per ARB 27.10)
- **Seven** new IDs failed with an explicit JUnit `Timeout (>180 s)`, each stopped in `Resolver.enter → ast.walk(fn)`;
  **two** new IDs are `pytest internal error … not re-run`. (A third internal error belongs to an ID already failed on the
  base.) In this file the run recorded ten timeouts and three internal errors in total, including its four pre-existing
  failed IDs. Exact IDs and JUnit attribution: `arb_new_failures_20261027.json`.
- The earlier wording here («one timeout, then an eight-test cascade») was wrong: these are several real timeout
  observations of one repeated expensive code path.
- On the base run the tests of this file took 140–165 s each (limit 180 s). How much the added package versus runner load
  contributed is NOT established separately. Pre-existing: the real-tree test is red on the base (+28 subjects of main's
  own code).

## Previous integration errors
`test_foreign_markup_reader_census.py::test_the_live_tree_is_measured_and_the_custodian_is_in_the_class` — **passed**
(105.1 s); `::test_the_tree_agrees_with_the_live_measurement_of_adr_594` — **passed**. The red integration CI
40317312101 is kept as it was; this pass is a different tree (release), not a retroactive change of that result.

## Package tests in this CI (executed, all passed)
test_task_prep_record 38 · test_task_prep 43 · test_model_roles_contract 27 · test_model_roles_review 19 ·
test_model_roles_probe 78 · test_role_pack 15 · test_owner_view 104 · test_cockpit_loop 26. No failure in any package or
cockpit test file.

Not green; not NO_REGRESSION. No further full run was started automatically.

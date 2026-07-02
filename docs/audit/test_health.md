# AUDIT-003 — Test-Suite Health Snapshot

> Read-only snapshot. No test mutates live `data/`; the research-layer tests import nothing from
> `spa_core.execution`/`spa_core.risk` and never run the cycle. Numbers below are from this session's
> runs — re-run to refresh (they drift as the tree evolves).

## Research-layer harness (this branch, `yield-lab-scaffolding`)
- Command: `python3 -m pytest research/ tests/test_schemas_valid.py tests/test_cards_complete.py
  tests/test_lifecycle_transitions.py tests/test_evidence_levels.py tests/test_no_secrets_in_research.py
  tests/test_no_execution_import.py -p no:randomly -q`
- Result: **100 passed, 0 failed** (deterministic across runs).
- Coverage: schema validity (5 docs/schemas + 3 card schemas parse), card completeness (10/10 strategy
  cards carry the 5 ADR-YL-008 spread fields; protocol/stablecoin cards carry required fields), lifecycle
  legality (illegal transitions rejected), evidence-level guard (no APY without L0–L6), no-secrets scan,
  no-execution-import guard.

## Full repo suite (baseline, from earlier this session on the mainline tree)
- `python3 -m pytest spa_core/tests/ tests/` → **101,194 passed / 0 failed / 0 errors** (after the
  test-hygiene fixes committed to origin). No-network / no-live-mutation confirmed (hermetic fixtures;
  the flaky live-data-reading tests were made hermetic).
- Note: that run is on the mainline tree; this branch adds only docs + research-layer tests, so it does
  not change runtime test outcomes.

## Guarantees
- No runtime/RiskPolicy/execution/dashboard code changed on this branch (verified: `git diff --name-only
  main..HEAD` contains no such path).
- Research tests are read-only and stdlib+pytest only.

## To refresh
Re-run the two commands above. If a research-layer test fails, fix the artifact to the honest reality
(or the test's expectation) — never weaken a security guard (no-secrets / no-execution-import) to pass.

*Snapshot date: this session (2026-07-02). Re-run to update.*

# 10 — TESTING & VERIFICATION

- Tests: `spa_core/tests/` (unit, ~1160 files) + `tests/` (root, ~340). Run: `python3 -m pytest spa_core/tests/ -q`.
- **CI is stdlib-first**: the main CI installs a test-dep set for the full suite; data/env-dependent tests carry `@pytest.mark.skipif(GITHUB_ACTIONS)` (run locally, skip in the data-less CI). `spa_core/tests/conftest.py` import-aware `collect_ignore` skips dep-heavy files when a dep is absent.
- Doc-drift guard: `spa_core/tests/test_doc_drift.py` pins state numbers to `golive_status.json`.
- **Deploy verification (mandatory before claiming a deploy):** run the freshness check in `15_CANONICAL_COMMANDS`; check the GitHub Actions run conclusion + real live content — NEVER a bare `curl` status code (a 404.html can return HTTP 200).

# 11 — CHANGELOG (append newest on top; every meaningful change)

- 2026-07-05 — CI FULLY GREEN, officially confirmed by real runs. Fixed `pre_deploy_check.py` 4 stale checks (LiveTradingGate `is_unlocked`→`is_active`; equity_curve accepts dict-with-`daily`; secret-scanner now matches real token formats — bare `sk-` was matching `risk-` in comments; landing build skips when npm/node_modules absent — real build is verified by Cloudflare Pages) + updated its unit tests. Disabled the redundant native **GitHub Pages** build (was `branch:main path:/` legacy-Jekyll, always red; Cloudflare Pages is canonical, github.io dashboard already removed). Green: ci.yml, test.yml (3.11+3.12), lint, lint-llm-forbidden, Proof Gate, Cloudflare Pages. Added `is_site_fresh.sh` + AUDIT_08. spa_core/tests = 88741 passed, 0 failed.

- 2026-07-04 — PROJECT_CONTROL created (audit PHASE 0-13); AUDIT_00-07 + PROJECT_PROBLEM_MAP written. Consolidates existing docs, does not replace them.
- 2026-07-04 — Academy merged to main + LIVE on earn-defi.com (PR #1, sha 4456fb1d0); bilingual theory+quizzes M0-M8; backend up.
- 2026-07-04 — CI hardening (option-A): lint + Proof Gate green; test job unblocked (pythonpath + collect_ignore) + full test-dep-set + data/env skip-guards.
- (older entries: see git history via `push_to_github_batch` commits on origin/main + `PROGRESS.md`)

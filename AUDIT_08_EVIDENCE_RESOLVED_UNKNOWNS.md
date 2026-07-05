# AUDIT_08 — EVIDENCE-RESOLVED UNKNOWNS

**Generated:** 2026-07-04 (overnight stabilization pass) · read-only · resolves the UNKNOWNs flagged in AUDIT_02/03/04 + PROJECT_PROBLEM_MAP §3 with real evidence.

---

## UNKNOWN-1 — Legacy github.io dashboard artifacts (were they removed?)

**RESOLVED: YES, removed.** Verified via GitHub API on `origin/main`:

| Artifact | `main` status |
|---|---|
| root `index.html` (756KB blob) | **HTTP 404 — gone ✓** |
| `spa_frontend/` | **HTTP 404 — gone ✓** |
| `.github/workflows/deploy-pages.yml` | **HTTP 404 — gone ✓** |

The CLAUDE.md claim ("legacy github.io dashboard removed 2026-06-28") is **confirmed true**. No action needed.

## UNKNOWN-2 — Investor cabinet (`app.earn-defi.com`) — is it live?

**RESOLVED: NOT live.** `curl app.earn-defi.com` → **HTTP 404**. The `cabinet/` app + its `wrangler.toml`/`.env.production` exist in the repo, but the domain is not serving. So the cabinet is **dev-config-present but NOT deployed** — do not describe it as a live production surface. (Owner: decide whether to deploy it or mark it dormant.)

## UNKNOWN-3 — Legacy deploy/push scripts — dead or alive?

**RESOLVED: the whole legacy chain is effectively DEAD** (not invoked by any agent). Evidence:

| Script | Has a code caller? | In any launchd/cron plist? | Verdict |
|---|---|---|---|
| `git_autopush.sh` | NO | NO | **DEAD** |
| `do_git_push.command` | NO | NO | **DEAD** |
| `fix_and_push.command` | NO | NO | **DEAD** |
| `install_auto_push.sh` | NO | NO | **DEAD** |
| `diagnose_push.sh` | NO | NO | **DEAD** |
| `git_push.sh` | `secure_git_push.sh` | NO | dead chain (only legacy cross-ref) |
| `DEPLOY.sh` | `push_final.sh` | NO | dead chain |
| `deploy_all.sh` | `DEPLOY.sh` | NO | dead chain |
| `secure_git_push.sh` / `push_final.sh` | each other | NO | dead chain |

**The REAL autopush** (`com.spa.autopush` → `scripts/auto_push.sh`) invokes **`push_to_github.py` + `push_v*.sh`** — confirmed by reading `auto_push.sh`. None of the legacy chain is referenced by any launchd/plist. → They are safe **archival** candidates (move to `scripts/legacy/`, don't delete), owner-gated. See `FILES_PROPOSED_FOR_DELETION.md`.

## UNKNOWN-4 — Duplicate test trees (`tests/` vs `spa_core/tests/`) — RE-INVESTIGATED, hazard was OVERSTATED

Initial scan flagged 25 same-named files as a "structural hazard / root of CI path confusion." **Careful follow-up (2026-07-05) downgraded this:** it is NOT a collision hazard and mostly not even duplication.

Breakdown of the 25:
- **8 were dead `# MOVED — SPA-D003` tombstones** in `tests/` (4-line comment files, `pytest --collect-only` = 0 tests, leftover guardrails from a past consolidation). **Removed** (safe; the real tests live in `spa_core/tests/`). → 25 down to 17.
- **1 (`test_doc_drift.py`)** is an intentional **re-export shim**: `from spa_core.tests.test_doc_drift import (…)` — single source of truth, no divergent logic. **Keep as-is** (good pattern).
- **1 (`conftest.py`)** is not a test file — every test dir legitimately owns a `conftest.py`. **Not a duplicate.**
- **15 are genuinely PARALLEL, INDEPENDENT test suites** for the same module, written by different sessions/sprints with different test names (the smaller suite's tests are ~100% unique names, not a subset). Both provide REAL, additive coverage.

**No actual collision:** `spa_core/tests/` is a proper package (`__init__.py` present; so is `spa_core/__init__.py`), while `tests/` is rootdir-based. Fully-qualified module names differ (`spa_core.tests.test_X` vs `test_X`), so the same basenames **coexist cleanly** — verified: `pytest tests/test_mev_protection.py spa_core/tests/test_mev_protection.py --collect-only` collects all 36 with **no "import file mismatch."** The "CI path confusion" I hit during the green-up was a *log-readability* annoyance (a failure printed as `tests/test_X.py` when it was the `spa_core/tests/` one), **not a functional bug.**

**Verdict:** the sharp real duplication was the 8 tombstones (now gone). The remaining 15 parallel suites are safe, coexist correctly, and each adds coverage — **merging them is cosmetic-only with real risk of dropping tests, and is NOT recommended.** Canonical primary tree = **`spa_core/tests/`** (the package, richer suites); `tests/` is the rootdir/integration tree; both run in CI by design. If ever merged, do it per-file as a union (never a blind delete of the smaller copy).

## Consequences for the audit

- AUDIT_02 "obsolete artifacts" → github.io confirmed gone; legacy deploy chain confirmed dead-but-present.
- AUDIT_03 cabinet → confirmed NOT live.
- AUDIT_04 "duplicate pages/components" → the sharpest real duplication is the **25 divergent same-named test files**, not app code.
- PROJECT_PROBLEM_MAP §11 (dead/duplicate) → hardened with the evidence above.
- `FILES_PROPOSED_FOR_DELETION.md` updated with the caller/launchd evidence (risk downgraded to LOW-archive for the 5 zero-caller scripts; MED for the cross-ref chain; the 25 test dupes stay HIGH/owner-gated).

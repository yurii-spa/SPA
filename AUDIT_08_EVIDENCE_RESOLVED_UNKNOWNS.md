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

## UNKNOWN-4 — Duplicate test trees (`tests/` vs `spa_core/tests/`)

**RESOLVED: real divergent duplication.** **25 files share the SAME name in BOTH `tests/` and `spa_core/tests/`, and ALL 25 are DIFFERENT content (0 identical).** Examples: `conftest.py`, `test_adapter_registry.py`, `test_apy_tracker.py`, `test_ceo_agent_v2.py`, `test_concurrent_fetch.py`, `test_cycle_health_monitor.py`, …

**This is the root of the CI path confusion** documented during the CI-green work (a failure logged as `tests/test_X.py` might actually be `spa_core/tests/test_X.py`; two same-named `conftest.py` behave differently). It is a genuine structural hazard (module-name collisions, ambiguous ownership) — but **NOT safe to delete** (they are different tests). **Owner decision required:** designate one canonical tree per test, diff-merge the 25 pairs, or namespace them. Until then, treat `spa_core/tests/` as the primary product test tree and `tests/` as the integration/root tree (both are run by CI).

## Consequences for the audit

- AUDIT_02 "obsolete artifacts" → github.io confirmed gone; legacy deploy chain confirmed dead-but-present.
- AUDIT_03 cabinet → confirmed NOT live.
- AUDIT_04 "duplicate pages/components" → the sharpest real duplication is the **25 divergent same-named test files**, not app code.
- PROJECT_PROBLEM_MAP §11 (dead/duplicate) → hardened with the evidence above.
- `FILES_PROPOSED_FOR_DELETION.md` updated with the caller/launchd evidence (risk downgraded to LOW-archive for the 5 zero-caller scripts; MED for the cross-ref chain; the 25 test dupes stay HIGH/owner-gated).

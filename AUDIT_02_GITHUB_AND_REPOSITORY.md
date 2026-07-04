# AUDIT_02 — GITHUB & REPOSITORY

**Generated:** 2026-07-04 · read-only · PHASE 2
**Verification:** `git ls-remote` (via Keychain PAT), GitHub API, `git ls-tree`. No branches deleted/merged.

---

## Repository identity

| Field | Value |
|---|---|
| Canonical repo | **`yurii-spa/SPA`** (`https://github.com/yurii-spa/SPA.git`) |
| Canonical branch | **`main`** |
| Remotes (local) | single `origin` → the repo above |

## Branch map (remote `origin`, verified)

| Branch | Role | Last commit (verified) | Status |
|---|---|---|---|
| **`main`** | **CANONICAL** — production source; CF Pages builds from it | continuously updated (API-push) | Active, authoritative |
| `feature/academy-course` | Academy Real-Money Onboarding (PR #1) | 2026-07-04 | **Merged into `main`** 2026-07-04 (sha `4456fb1d0`); can be retired post-merge (owner-gated) |
| `claude/project-code-audit-9jyi9l` | Old Dispatch/agent audit branch | **2026-06-22** | ⚠ **STALE** (~2 wks) — candidate for archival (Phase 12), not deletion now |
| `claude/project-overview-hcvh2k` | Old Dispatch/agent onboarding branch ("Mac mini launcher to run Claude Code") | **2026-06-22** | ⚠ **STALE** — candidate for archival |

**Finding:** the two `claude/*` branches are leftovers from earlier Claude Dispatch / agent sessions (June 22). They are not part of the live flow. Do **not** delete yet — confirm with owner, then archive.

## Remote / push model (⚠ NON-STANDARD — key to the recurring problems)

- Code reaches `origin/main` via **`push_to_github_batch.py`** (and `push_to_github.py`), which write file **contents** through the GitHub API **directly to `main`**, one commit per push.
- This **bypasses** normal `git commit` + `git push`. Therefore:
  - The **local `.git` is not authoritative** (135 ahead / 239 behind `origin/main`; see AUDIT_00).
  - "Verify `local == main` before editing shared files" (a rule in the loop prompts) really means **fetch `origin/main` and diff against it**, not trust the working tree.
  - There is **no traditional PR-merge flow for day-to-day work** — parallel sessions push files straight to `origin/main`. (PRs like #1 are the exception, used for large contours.)

## GitHub Actions / workflow map (10 workflows on `main`)

| Workflow | Purpose | Deployment-connected? |
|---|---|---|
| `ci.yml` | Full CI: import smoke, `pytest tests/`, guards (LLM-forbidden, SSOT, redirect-shadowing), lint | Build/test only |
| `ci-lite.yml` | Lighter CI | Build/test only |
| `test.yml` | Test + lint jobs | Build/test only |
| `spa-lint.yml` | LLM-forbidden lint | Lint only |
| `proof-gate.yml` | **Proof Gate** — `verify_spa.py` re-derives published proofs, DD-pack head, stdlib guard | Integrity gate (not deploy) |
| `site_freshness.yml` | Site Custodian block 2 — every 6h, independent site↔snapshot↔API freshness check | Verifies prod; can degrade snapshot |
| `site_content_audit.yml` | Site Custodian block 4 — weekly content-drift audit | Verifies prod content |
| `deploy-landing.yml` | **GitHub Pages MIRROR** — `workflow_dispatch`-only (manual) | ⚠ **NOT canonical** — GH Pages does **not** serve `earn-defi.com` (see AUDIT_03) |
| `spa-run.yml` | Cloud cron for daily cycle (per memory: **disabled** in favor of Mac-Mini launchd) | Not deploy |
| `spa_alerts.yml` | Alerts | Not deploy |

**Key:** **NO GitHub Action deploys production.** Production is deployed by **Cloudflare Pages' own git-integration** on push to `main` (AUDIT_03). `deploy-landing.yml` is a manual GitHub-Pages mirror that does not serve the live domain (its "Deploy to GitHub Pages" step historically failed → false CI-red).

## Committed-artifact / obsolete-content check

| Item | Finding |
|---|---|
| `landing/dist/` (build output) | **NOT tracked** (in `.gitignore`) on `main` — good, no committed build blobs |
| Legacy github.io dashboard (root `index.html` 756KB blob + `spa_frontend/` + `deploy-pages.yml`) | **Removed 2026-06-28** per CLAUDE.md — verify absence on `main` (Phase 12) |
| Volatile `data/*.json` (equity, golive, evidence snapshots) | Some intentionally tracked (owner-gated), most now `.gitignore`d; `git rm --cached` backlog is owner-manual |

## Unclear areas requiring owner confirmation

1. Retire/archive the 2 stale `claude/*` branches? (owner-gated)
2. Retire `feature/academy-course` now that PR #1 is merged? (owner-gated)
3. Confirm the legacy github.io dashboard artifacts are fully gone from `main`.
4. `SPA_PAT` GitHub secret is **401/invalid in CI** (distinct from the working Keychain PAT) — breaks the freshness workflow's degrade-push; owner must set a valid token.

## Do NOT (this phase)

Do not delete or merge any branch; do not `git rm`; do not change workflows. All of the above are **findings**, resolved in later (owner-gated) phases.

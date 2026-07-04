# 03 — REPOSITORY & GITHUB

Canonical deep source: `AUDIT_02_GITHUB_AND_REPOSITORY.md`.

- Repo **`yurii-spa/SPA`**, canonical branch **`main`**.
- Branches: `main` (canonical), `feature/academy-course` (merged 2026-07-04), `claude/project-code-audit-*` + `claude/project-overview-*` (STALE June-22 Dispatch branches — archive candidates, owner-gated).
- **Push model:** `push_to_github_batch.py` (GitHub API) → `main` directly. Local git drifts — `origin/main` is truth (read via API).
- 10 workflows; **none deploy production** (build/test/gate only). `deploy-landing.yml` = GH-Pages MIRROR (`workflow_dispatch`).
- Build artifacts NOT committed (`landing/dist` gitignored).

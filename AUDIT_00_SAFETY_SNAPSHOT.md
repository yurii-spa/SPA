# AUDIT_00 — SAFETY SNAPSHOT

**Generated:** 2026-07-04 (Claude Code CLI, read-only investigation)
**Scope:** PHASE 0 of the stabilization audit. No files changed except this audit doc.
**Verification method:** live `git` + filesystem commands (not memory/assumption).

---

## Current working tree

| Field | Value | Verified by |
|---|---|---|
| Working directory | `/Users/yuriikulieshov/Documents/SPA_Claude` | `pwd` |
| Current branch | **`feature/academy-course`** (NOT `main`) | `git branch --show-current` |
| Remote | `origin` = `https://github.com/yurii-spa/SPA.git` (fetch+push) | `git remote -v` |
| Local HEAD | `51ed24b45` — "fix(site-custodian): map freshness workflow PAT env…" | `git log` |
| Tree type | **Development / heavily-drifted working tree — NOT the production tree** | see below |

## ⚠️ CRITICAL FINDING — the local git tree is NOT a source of truth

| Metric | Value |
|---|---|
| Uncommitted changes | **282** (240 modified `M`, 42 untracked `??`) |
| Local **ahead** of `origin/main` | **135 commits** |
| Local **behind** `origin/main` | **239 commits** |

The local working tree is on `feature/academy-course`, **135 ahead / 239 behind `origin/main`**, with **282 uncommitted files**. This is the expected (but dangerous) result of this project's **API-push model**: code is pushed to `origin/main` file-by-file via `push_to_github_batch.py` (GitHub Contents/Git-Data API) **directly**, bypassing normal `git commit`/`git push`. Consequently the **local `.git` drifts massively from `origin`** and must **not** be treated as authoritative.

> **SOURCE OF TRUTH = `origin/main` on GitHub (queried via API), NOT the local tree.**

## Latest 10 LOCAL commits (⚠ local line, diverged — not origin history)

```
51ed24b45 fix(site-custodian): map freshness workflow PAT env to existing secrets.SPA_PAT
1c7c4bfce feat(site-custodian): block-5 ADR-YL-011 + CURRENT_STATE section
c1c8c274f feat(site-custodian): block-4 weekly content-consistency audit
3c9eadd01 feat(site-custodian): block-2/3 independent freshness monitor + degraded kill-rule
61ddc635c feat(site-custodian): block-1 auto-deploy fresh snapshot after each daily cycle
b577aa9c6 fix(audit): P2-8 repo hygiene — untrack node_modules + settings.local
… (site-custodian / external-audit work of one Claude Code session)
```
These are one session's commits sitting on the local branch pointer; they are **not** what `origin/main` looks like.

## Environment / config files found (names only — NO secret values read)

- `wrangler.toml` (root) — Cloudflare Pages config
- `cabinet/wrangler.toml`, `cabinet/.env.production`, `cabinet/.env.development` — investor-cabinet app
- `landing/.env.example` — landing template (example only)
- `.claude/` (directory) — Claude Code local state (contains `settings.local.json`; per prior remediation a leaked `ghp_` token was found here — **treat as sensitive, never expose/commit**)
- Secrets live in **macOS Keychain** (`GITHUB_PAT_SPA`, `TELEGRAM_*_SPA`, `FAMILY_FUND_JWT_SECRET`) — **not** in files (per repo SECRETS POLICY).

## Immediate risks

1. **Do NOT run `git reset --hard`, `git checkout .`, or `git clean` in this tree** — it holds 282 uncommitted files. Most are already on `origin/main` via API-push, but not verifiably all. A hard reset could silently discard un-pushed work.
2. **Do NOT `git push` this local branch** — it is 135 ahead / 239 behind `origin/main`; a normal push would be rejected (non-ff) or, if forced, would corrupt `origin`. This tree publishes **only** via `push_to_github_batch.py` (per-file, to `main`).
3. **`.claude/settings.local.json` previously contained a leaked `ghp_` token** — must stay untracked/ignored; never print or commit it.
4. The branch name (`feature/academy-course`) is misleading: the tree actually carries a **different** session's site-custodian/audit commits, not (only) the academy work. Branch pointer ≠ branch content here. (The real academy work is on `origin`, PR #1, now merged to `main`.)

## Dangerous-uncommitted-changes gate (PHASE 0 requirement)

**Report:** There ARE 282 uncommitted changes, but they are the ambient state of this API-push development tree, not a pending hand-edit at risk from *this* audit (this audit only writes `AUDIT_0x.md` docs). **No destructive git operation is proposed.** The safe posture for any future work: treat `origin/main` as truth, sync read-only via `git fetch` + API queries, and never destructively reset this tree. Recommend a clean re-clone or `git fetch && git reset --hard origin/main` **only** once the owner confirms nothing local is un-pushed — that is a separate owner-gated decision, not part of this audit.

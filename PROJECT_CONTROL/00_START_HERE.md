# 00 — START HERE  (every agent reads this FIRST)

**Audience:** every future Claude Code CLI session, every Claude Dispatch session, and every automated agent that modifies, pushes, deploys, checks, or documents this project.

This project (SPA — Smart Passive Aggregator / earn-defi.com) is developed through **parallel systems** (Claude Code + Claude Dispatch + Mac-Mini launchd agents). Silent drift between them is the #1 source of recurring problems. This folder is the single control system. **Do not create a parallel one.**

---

## The 5 truths you must hold (or you WILL cause a recurring bug)

1. **`origin/main` on GitHub is the source of truth — NOT the local working tree.**
   Code is pushed to `main` via `push_to_github_batch.py` (GitHub API), bypassing `git push`. The local `.git` drifts massively (was 135 ahead / 239 behind). **Read origin files via the GitHub API, not `git show origin/main` (a stale local ref). NEVER `git reset --hard` / `git push` / `git clean` this tree without owner sign-off** — see `01_MASTER_RULES`.
2. **GitHub ≠ production.** `earn-defi.com` is served by **Cloudflare Pages** (builds `landing/dist` from `landing/` on push to `main`). A push to `main` does NOT guarantee the site updated — CF's build can lag/pause (opaque from the Mac). **Verify the live site; never claim "deployed" without checking** (`15_CANONICAL_COMMANDS`).
3. **There are TWO agent layers, kept separate:** product-DeFi agents (write `data/*.json`, never code) and dev/ops agents (touch code/docs/deploy, never RiskPolicy/strategy). See `05_` + `06_`. Do not mix them.
4. **RiskPolicy is deterministic and LLM-FORBIDDEN.** Never put an LLM in risk/execution/monitoring/kill. Never import `spa_core/execution/` from read-only/paper code. Never move funds / handle keys.
5. **Secrets live in macOS Keychain, never in files.** (`GITHUB_PAT_SPA`, `TELEGRAM_*_SPA`, `FAMILY_FUND_JWT_SECRET`.) `.claude/settings.local.json` once leaked a `ghp_` token — keep it ignored, never print/commit it.

## Before doing ANY work

1. Read this file + `01_MASTER_RULES.md`.
2. Read `docs/SYSTEM_BRIEFING.md` (auto-updated 30 min) for live state — **required before saying anything about "what works".**
3. Read the control file(s) for your task: `03` GitHub · `04` hosting · `05` product agents · `06` dev agents · `07` data/paper · `08` deploy/autopush · `09` code structure · `10` testing.
4. Read the deep audits behind them: `AUDIT_00`…`AUDIT_07` + `PROJECT_PROBLEM_MAP.md` (repo root).
5. **Inspect the actual files** (via API for origin state) before editing.
6. Make the **smallest safe change**; one task per iteration; no big-bang rewrites.
7. Run the verification checklist (`10_` + `15_`).
8. **Update `11_CHANGELOG.md`.**
9. Report changed files + verification results. If deploy-related, report the live-site verification, not just the push.

## Canonical facts (verify, don't assume)

| Thing | Value | Verify with |
|---|---|---|
| Repo / branch | `yurii-spa/SPA` / `main` | `git ls-remote` |
| Production site | `earn-defi.com` (Cloudflare Pages, builds `landing/`) | `curl -I` (server: cloudflare) |
| Backend API | `api.earn-defi.com:8765` (FastAPI, Mac Mini + cloudflared) | `curl api.earn-defi.com/api/v1/golive` |
| Push to GitHub | `push_to_github_batch.py --files <abs> --message` (→ `main`) | — |
| Deploy to prod | Cloudflare Pages auto-build on push to `main` (owner-gated dashboard) | live-content check |
| Paper day (truth) | `data/golive_status.json:real_track_days` | — |
| Agents (truth) | `launchctl list | grep spa` + `docs/SYSTEM_BRIEFING.md` | — |
| Python | `/Users/yuriikulieshov/miniconda3/bin/python3` | — |

## If something is UNKNOWN

Write UNKNOWN + how to verify. Do not guess. Do not "fix" a symptom before finding the source-of-truth/deployment root (`PROJECT_PROBLEM_MAP.md`).

> This control system CONSOLIDATES existing docs; it does not replace them. Authoritative deep docs remain: `CLAUDE.md` (Claude-Code charter), `docs/00_index.md` (research layer), `MASTER_PLAN_v1.md`, `docs/adr/*`, `docs/SYSTEM_BRIEFING.md`. This folder tells you WHICH to read and the invariants that bind them.

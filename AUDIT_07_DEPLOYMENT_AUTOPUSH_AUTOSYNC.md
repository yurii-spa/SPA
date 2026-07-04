# AUDIT_07 — DEPLOYMENT / AUTOPUSH / AUTOSYNC

**Generated:** 2026-07-04 · read-only · PHASE 7 · no automation changed

---

## The 17 PHASE-7 questions

| # | Question | Answer |
|---|---|---|
| 1 | What runs every 90 min? | **`com.spa.autopush`** (launchd LaunchAgent) |
| 2 | Does it exist? | **YES** — running (`launchctl list | grep autopush` = 1); plist at `~/Library/LaunchAgents/com.spa.autopush.plist` |
| 3 | Where configured? | that plist → `scripts/auto_push.sh` (via the bash-wrapper standard) |
| 4 | What command? | `auto_push.sh` scans `push_v*.sh` scripts and runs `push_to_github.py` for each |
| 5 | Updates data? | **No** — it only pushes files already staged by producers; the DATA is written by `daily_cycle` etc. |
| 6 | Commits? | **Via the GitHub API** (`push_to_github.py`) — one commit per push, NOT local `git commit` |
| 7 | Pushes to GitHub? | **YES → `origin/main`** |
| 8 | Deploys to production? | **Indirectly** — the push to `main` triggers Cloudflare Pages' own build (the deploy is CF's, not autopush's) |
| 9 | Verifies prod after deploy? | **No** (autopush itself) — verification is the separate **Site Custodian** (`site_freshness.yml`, 6h) |
| 10 | Where are logs? | `logs/auto_push.log` (heartbeat); launchd wrapper also writes `/tmp/spa_autopush.log` |
| 11 | On failure? | Silent `pushed=0` is the classic failure (see gotchas); no hard alert from autopush itself |
| 12 | Notifies anyone? | Not reliably (autopush). Health is caught by `agent_health` / `rules_watchdog` Telegram |
| 13 | Wrong folder? | Possible historically — mitigated by absolute paths in the plist wrapper (`WorkingDirectory` set) |
| 14 | Pushes GitHub but NOT domain? | **YES — this is the #1 recurring failure**: push lands on `main` but Cloudflare Pages doesn't rebuild (opaque). GitHub fresh, domain stale. |
| 15 | Updates domain but NOT GitHub? | **No** — CF only builds from `main`, so the domain can't be ahead of GitHub. |
| 16 | Blocked by uncommitted changes? | The API-push model does **not** use the local working tree, so local uncommitted changes don't block it. (But the local tree drifts — see AUDIT_00.) |
| 17 | Silently failing? | **YES, historically** — the documented autopush gotchas below. |

## Known autopush gotchas (from prior incidents — these are the "repeated problems")

- **Silent `pushed=0` from launchd PATH** — under launchd, `pytest`/tools may be absent → the push guard skips silently. Fix: the wrapper + `/tmp` logging.
- **Missing `--branch` arg** — pushes could target the wrong ref.
- **TWO copies of `push_to_github.py`** (root + `scripts/`) that must stay in sync.
- **409 stale-sha** on multi-file pushes → retry or push one file at a time (`push_to_github_batch.py` mitigates with a single Git-Data-API commit).
- **Heartbeat = `logs/auto_push.log`** — if it stops advancing, autopush is dead.

## The full push/deploy/sync inventory (many overlapping — canonical vs legacy)

| Category | CANONICAL (in use) | LEGACY / suspect (verify in PHASE 12) |
|---|---|---|
| API push to GitHub | **`push_to_github_batch.py`** (Git-Data-API, 1 commit) · `push_to_github.py` | `git_autopush.sh`, `git_push.sh`, `do_git_push.command`, `fix_and_push.command`, `install_auto_push.sh`, `diagnose_push.sh` |
| Site snapshot deploy | **`scripts/deploy_site_snapshot.py`** (Step 3 of `run_daily_paper_cycle.sh`) | — |
| Prod build/deploy | **Cloudflare Pages git-integration** (no repo script) | `DEPLOY.sh`, `deploy_all.sh`, `deploy-landing.yml` (GH-Pages MIRROR, `workflow_dispatch`) |
| Scheduled cloud cron | — | `spa-run.yml` (cloud daily cycle — **disabled** in favor of Mac-Mini launchd) |

## Root cause of "fixes are made but the same problem returns"

1. **Opaque CF build** — the true stale-site cause is outside the repo (CF dashboard). Repo-side "fixes" don't stick because the fault isn't repo-side. → The durable fix is **verification** (Site Custodian + the daily freshness command), not another push script.
2. **Local git drift + API-push model** — agents/sessions that assume normal `git push`/`git pull` fight the local↔origin drift (135/239). → The rule "treat `origin/main` as truth, never `git reset` the tree" must be canonical (PROJECT_CONTROL).
3. **Script sprawl** — many overlapping deploy scripts mean different actors use different (some broken) paths. → Consolidate to ONE canonical push path (PHASE 12 proposal).

## Do NOT (this phase)

No automation modified. All above are findings; consolidation/fix is proposed in PROJECT_PROBLEM_MAP + PROJECT_CONTROL + PHASE 12.

# 16 · MULTI-SESSION PROTOCOL — how parallel Claude sessions coexist without clobbering

> **READ THIS before any audit, change, or documentation edit.** Multiple Claude sessions
> (Claude Code CLI, terminal, project/code windows) work this repo IN PARALLEL, on the SAME Mac,
> pushing to the SAME `origin/main`. Without discipline they overwrite each other's docs and races
> corrupt state. This file is the coordination contract. It does not replace the rules in
> `CLAUDE.md` / `00_START_HERE.md` — it governs how several agents apply them at once.

---

## 0. The golden rule
**Partition the work by FILE. Never have two sessions editing the same file at the same time.**
Delivery is by pushing specific files to `origin` — there is NO traditional branch merge, so a
collision is silent **last-writer-wins ON ORIGIN**. Before you start, state (in the announce log,
§4) which files you own this session; if another active session already owns them, pick different
work or hand off.

## 1. SPA git is API-push only — NEVER touch local git history
- Push with `python3 push_to_github_batch.py --files <ABS paths> --message "…"` (commits file BYTES
  from the worktree straight to `origin/main` via the GitHub API — independent of local git).
- **NEVER** `git commit` / `git push` / `git reset --hard` / `git checkout .` on SPA `main`.
  - Local git HISTORY drifts thousands of commits behind (API pushes + the autopush fleet advance
    origin without touching local git). `git status` shows hundreds of "modified" files — that is the
    DRIFT ARTIFACT, not your work.
  - `git reset --hard origin/main` is **doubly dangerous**: (a) it reverts live-agent-written
    `data/*.json` (paper_state, equity_curve, golive_status…) to a staler committed version →
    **track corruption** (happened 2026-06-25); (b) it clobbers another session's / the owner's
    uncommitted worktree edits. Only ever reset if you are CERTAIN there is zero local/parallel
    uncommitted work — normally you never need to.
  - To pick up a specific file another session pushed: `git fetch origin` then
    `git checkout origin/main -- <that file>` (surgical, touches nothing else).
  - **Read origin state via the GitHub API, or `git fetch origin` FIRST** — a bare
    `git show origin/main:PATH` uses the local tracking ref, which is stale until you fetch
    (see `00_START_HERE` truth #1).
- **Checkup repo is DIFFERENT** (`~/Documents/Claude/Projects/DeFi Checkup`): there you DO use normal
  `git commit` + `git push HEAD:master` (its own remote). The API-push rule is SPA-only.

## 2. Shared, high-contention docs — re-read fresh, append, don't clobber
`CLAUDE.md`, `PROJECT_CONTROL/*`, `KANBAN.json`, `docs/ROADMAP_*.md`, `docs/00_index.md`,
`README.md`, `CURRENT_STATE.md` are edited by many sessions. Before editing one:
1. Re-read the CURRENT origin version (`git show origin/main:PATH`) — a concurrent session may have
   changed it since your worktree copy.
2. Make a MINIMAL, ADDITIVE edit (append a row / a section). Do not rewrite whole files.
3. Prefer creating a NEW file over editing a shared one when you can.
4. `KANBAN.json`: reload from disk immediately before writing (an hourly agent also writes it).

## 2b. Ship a ROADMAP/backlog item → mark it DONE in the SAME push (stop stale-marker re-scouting)
Recurring failure mode: a session ships an item's CODE but leaves the `docs/ROADMAP_2MONTH_EISENHOWER_v2.md` / `docs/SITE_UIUX_BACKLOG.md` row UNMARKED, so every later session re-scouts it, re-discovers "already done", and burns a firing (this happened repeatedly — two reconcile passes were needed 2026-07-15). Rule: when you finish a roadmap/backlog item, add a `✅ SHIPPED <date> (<commit>: <one-line evidence>)` prefix to its row IN THE SAME PUSH as the code (minimal additive edit per §2). If you only VERIFY an already-shipped-but-unmarked item, mark it `🔎 VERIFIED <date> (evidence you actually checked — test passed / file:line renders)` — NEVER mark `✅` on faith. Accurate markers are the difference between "backlog exhausted" being true vs. re-litigated.

## 3. Never touch these in parallel without owner sign-off
- **Live paper track** (`data/equity_curve_daily.json`, `paper_trading/…`), **RiskPolicy v1.0**
  (`spa_core/risk/policy.py`), **`spa_core/execution/`**, and the **launchd agent fleet**
  (`install_all_agents.sh`, `*.plist`, `launchctl`). One session owns any fleet change at a time;
  deploy only through `scripts/check_agent_before_deploy.sh`, ≤3 agents per batch. Monitor-only
  otherwise.

## 3b. Owner-gated decisions → write them to the shared questions file (don't lose them in chat)
When you hit something the owner must decide (a **public number / naming / legal / infra / secret /
brand narrative** — anything in §3 or the invariants), do NOT block and do NOT invent. Append it to
**`docs/OWNER_DECISIONS_NEEDED.md`** as a `Q-OWN-NN` block (priority, context, options, recommendation,
empty **ОТВЕТ:**). The owner answers there in batches (directive 2026-07-12: chat questions get lost
between loop firings). Every session **re-reads this file at start**: if the owner filled an **ОТВЕТ:**,
execute it and mark the block RESOLVED (never delete it). Keep the "УЖЕ РЕШЕНО" section current so a
settled decision (e.g. tier names = Conservative/Balanced/Aggressive; APY display = "up to {max}%") is
never re-litigated. This is how owner-gated backlog items stay actionable instead of silently dropped.

## 4. ANNOUNCE every change — the shared session-activity log
After you finish a change (and before/after pushing), record it so other sessions and the owner see
what moved:
```bash
python3 scripts/log_session_change.py \
  --summary "what you changed + why" \
  --files <abs paths> \
  --verified "pytest 66 green / landing build exit 0 / vitest 374"
```
This appends one atomic line to `data/session_changes.jsonl` (append-only → no clobber; all local
sessions share it). Read recent activity any time with `python3 scripts/log_session_change.py --tail`.
At session start, `--tail` first to see what other sessions have been doing.

## 5. The audit / change procedure (every session, every time)
1. **Orient:** read `docs/SYSTEM_BRIEFING.md`, then `00_START_HERE.md`, then this file, then
   `--tail` the announce log.
2. **Scope + claim:** decide the files you'll own; announce your claim (§4) if the work is non-trivial.
3. **Change** only your files; keep money-path/fleet/RiskPolicy untouched unless owner-signed.
4. **VERIFY, gated on exit code** — SPA: `pytest`; landing: `cd landing && npm run build`; checkup:
   `npx vitest run` + `npm run build -w @spa/web`. Never push on a red gate.
5. **Announce** the change (§4).
6. **Push** — SPA via `push_to_github_batch.py`; checkup via `git push HEAD:master`.
7. **Verify the deploy by real content**, not HTTP status (CF build is opaque from the Mac).

---
*Created 2026-07-11 (owner directive: strict multi-session coordination so parallel audits/edits
don't overwrite docs or race state). Companion: [`03_REPOSITORY_AND_GITHUB.md`],
[`10_TESTING_AND_VERIFICATION.md`], memory `git-push-api-drift`, `track-corruption-hazard`.*

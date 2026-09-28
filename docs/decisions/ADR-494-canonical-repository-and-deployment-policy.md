# ADR-494: Canonical repository, branch, and deployment/promotion policy (P0)

- **Status:** ACCEPTED (Owner explicitly confirmed 2026-09-28: «ACCEPT ADR-494 and ADR-495») · drafted 2026-09-27 · owner: @yurii
  > Renumbered before canonical promotion because origin/main already occupied the old ADR number (was ADR-490). Owner-authorized 2026-09-28; numbering change only — decision substance unchanged.
- **Why now:** the Studio OS Core work exposed an ambiguity that a *persistent* company brain cannot
  tolerate — feature work lives in a scratch worktree while production runs from a different tree.
  This ADR declares the ONE canonical path so no future AI session guesses (or copies between random
  directories). Consolidates and does not contradict `PROJECT_CONTROL/03` and `/08`.

## The three trees (measured 2026-09-27)

| Tree | Path | Role | Git |
|---|---|---|---|
| **Canonical remote** | `github.com/yurii-spa/SPA` (branch `main`) | THE source of truth | remote |
| Development worktree | `~/studio-os-scratch/v03` | where AI sessions edit/commit feature branches | tracks origin; index drifts (normal) |
| **Production runtime** | `~/Documents/SPA_Claude` | launchd fleet + Telegram bot execute HERE | synced from `origin/main` |
| Read-only mirror | `~/Documents/SPA_mirror` | §1 canonical-source reads (ADR-152) | synced from `origin/main` |

## Decision

1. **Canonical source of truth = `origin/main` on `yurii-spa/SPA`.** Local git indexes drift by
   construction (pushes go through the GitHub API, bypassing the index); `origin/main` read via API is
   truth. A commit that is not on `origin/main` is **not delivered**, regardless of which tree it sits in.
2. **Development happens in a worktree** (currently `~/studio-os-scratch/v03`); feature branches there are
   **candidates**, not canonical, until promoted.
3. **Promotion path (the only accepted one):** working tree → `push_to_github.py` (GitHub API) → `origin/main`
   → autosync pulls into `~/Documents/SPA_Claude` (and the mirror) → **agent restart for long-lived
   processes is a separate owner-gated step** (deployment rules §6; the Telegram bot holds code from start
   and does not pick up new code until restarted). Push to `main` ≠ live: Cloudflare Pages / agent restart
   are distinct downstream events.
4. **Never deliver by copying files between trees.** `cp` between `v03` and `~/Documents/SPA_Claude` outside
   an explicit, owner-approved deployment is forbidden — it is the exact drift this ADR exists to end. The
   one exception is an **owner-assisted deploy** explicitly authorized for a specific change (whole
   directories, backup first, `deployment_acceptance` before/after — deployment rules §2/§3/§5).
5. **Rollback** = revert the commit on `origin/main` (new commit, never history rewrite — the pre-push hook
   forbids force-push, per the 2026-08-29 incident) and let autosync propagate; for a hot agent, restore
   the backed-up file and restart.

## Consequences
- The current Owner-Remote / Studio-OS-Core work on `feature/mobile-owner-remote` in `v03` is a **candidate**;
  it reaches production only via push to `origin/main` (owner-authorized) + sync + restart.
- Studio OS's Project Registry records, per project, the canonical repo + the production source + the
  promotion path, so a fresh session reads ownership rather than inferring it.
- No second canonical repo, no per-tree truth. One remote, one branch, one promotion path, one rollback.

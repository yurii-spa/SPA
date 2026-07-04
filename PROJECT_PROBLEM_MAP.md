# PROJECT PROBLEM MAP

**Generated:** 2026-07-04 · synthesis of AUDIT_00–07 · precise diagnosis, not a rewrite

---

## 1. Main problem statement

The project is technically healthy but **hard to reason about** because three things drift silently: (a) the **local git tree vs `origin/main`** (an API-push model, not normal git), (b) **`origin/main` vs the live site** (opaque Cloudflare Pages build), and (c) **documentation vs reality** (206 docs, some duplicated/pinned/stale). Every recurring "stale site / broken autopush" incident traces to one of these three drifts — not to broken product code.

## 2. Confirmed facts

- Canonical repo **`yurii-spa/SPA`**, canonical branch **`main`**.
- Production **earn-defi.com = Cloudflare Pages** (builds `landing/dist` from `landing/` on push to `main`). API **api.earn-defi.com = FastAPI on the Mac Mini** via cloudflared. `deploy-landing.yml` (GitHub Pages) is a **non-canonical mirror**.
- Code reaches `main` via **`push_to_github_batch.py` (GitHub API), directly — bypassing `git push`.** Local `.git` drifts (135 ahead / 239 behind).
- **47 running `com.spa.*` agents**, cleanly splittable into product-DeFi vs dev/ops (AUDIT_05); 0 retired-set agents running.
- Paper-day is **date-derived** from `data/golive_status.json:real_track_days` (=13), not a manual counter.
- **At audit time the live site is FRESH** (live 13d == main snapshot 13d).

## 3. Unknowns (with how to verify)

- Is CF Pages auto-build-on-push currently ENABLED? → **CF Pages dashboard** (owner-only; not visible from repo/Mac).
- Is the investor cabinet (`app.earn-defi.com`) live? → `curl -I https://app.earn-defi.com`.
- Which `scripts/*deploy*`/`*push*` helpers are dead? → grep for callers (PHASE 12).
- Are there duplicate test trees (`tests/` vs `spa_core/tests/`)? → the CI path confusion suggests it; enumerate in PHASE 12.

## 4. Contradictions

- **Docs say "08:00/09:00 UTC" cycle; reality is 06:00/07:00 UTC** (plist Hour is LOCAL/CEST; evidenced by `last_cycle_ts`). Partially corrected on the site this session.
- **CLAUDE.md admits its own state numbers drift** (pinned to `golive_status.json`, but the prose table can lag).
- **"stdlib-only runtime" vs deps in tests/API/academy** — reconciled by documenting the exceptions (FastAPI/argon2/etc. are API/academy/cabinet-only, never in the paper/risk runtime).

## 5. GitHub vs production mismatch — explained

`main` fresh + site stale = **Cloudflare Pages did not rebuild** (build paused/failing on the CF side). The repo cannot fix a paused CF build; the fix is the CF dashboard (owner). The *detection* is in-repo (Site Custodian, every 6h). **Never assume "pushed to GitHub" = "live on the domain" — verify.**

## 6. Product vs dev agents — separation problem

The two layers exist and are separable, but there is **no single enforced control doc** both obey. Risk: a dev/deploy agent or a Claude session touching product data, or a product change bypassing the RiskPolicy/`execution/` boundary. → PROJECT_CONTROL must encode the separation (AUDIT_05 §D).

## 7. Documentation problems

Not absence — **drift + duplication + no unified entrypoint**. `CLAUDE.md` (Claude Code, auto-loaded) has no Dispatch-equivalent mandatory read; `RULES.md`/`CLAUDE.md FORBIDDEN`/`docs/06` triplicate hard rules. Good existing controls: `test_doc_drift.py` (pins numbers), `docs/00_index.md` (research index), Site Custodian.

## 8. Deployment / autopush problems

Opaque CF build (dominant), silent-`pushed=0` autopush failure modes, and **script sprawl** (one canonical push path buried among ~8 legacy helpers). Fixes returned because they addressed symptoms, not the opaque-build root or the verification gap.

## 9. Data-freshness problems

Two lag points (snapshot-not-pushed, CF-build-lag) + API-vs-static confusion. Mitigated by Site Custodian; blocked by an invalid `SPA_PAT` CI secret (owner must set).

## 10. Code-structure problems

Minimal — `spa_core/` is large but intentionally (analyzer breadth is canonical, confirmed by a prior audit). Real fragmentation = **deploy scripts**, not product code.

## 11. Dead / duplicate file problems

Candidates (verify, don't delete yet): legacy `scripts/*push*.sh|*.command`, stale `claude/*` branches (June 22), possible duplicate test trees, owner-gated tracked `data/*.json`. → PHASE 12.

## 12. Highest-risk areas

1. **Opaque CF build** (owner-gated) — the recurring stale-site root.
2. **Local git drift** — a `git reset --hard`/`push` on this tree could corrupt work or `origin`. **NEVER do it without owner sign-off.**
3. **`.claude/settings.local.json` held a leaked `ghp_` token** — must stay ignored, never exposed.
4. **`SPA_PAT` CI secret invalid** — breaks the freshness auto-degrade.

## 13. What should NOT be touched yet

RiskPolicy, `cycle_runner`, the proof-pipeline, agent schedules, the go-live track, product strategy/DeFi logic, branch deletions, `git rm --cached` of owner-gated data.

## 14. What can be safely fixed first (low risk)

- Add the freshness-check command + a "GitHub-latest vs live-visible" script.
- Consolidate the rule triplication into one canonical file (reference, don't delete).
- Mark legacy deploy scripts as archived (don't delete).
- Add a `PROJECT_CONTROL/00_START_HERE.md` that BOTH Claude Code + Dispatch must read.
- Correct remaining doc time-labels (06:00 UTC) under the existing drift test.

## 15. Proposed stabilization roadmap

1. **Canonicalize entry** → `PROJECT_CONTROL/00_START_HERE.md` (points to existing docs, encodes: `origin/main`=truth, CF=prod, freshness command, two-agent separation).
2. **Verification-first** → make the freshness command + a daily "is the site fresh?" gate the norm; keep Site Custodian green (fix `SPA_PAT`).
3. **Consolidate deploy path** → one canonical push (`push_to_github_batch.py`), archive the rest.
4. **Resolve owner-gated items** → CF-build enablement, stale branches, tracked-data decision, `SPA_PAT`.
5. **Then** (only then) consider structural cleanup (PHASE 12 proposals), never before references are proven.

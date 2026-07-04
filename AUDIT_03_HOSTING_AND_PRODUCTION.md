# AUDIT_03 — HOSTING & PRODUCTION

**Generated:** 2026-07-04 · read-only · PHASE 3
**Verification:** `wrangler.toml`, `landing/package.json`, live `curl` to `earn-defi.com`, `git ls-tree origin/main`, GitHub API. Nothing deployed/changed.

---

## The 10 PHASE-3 questions, answered

| # | Question | Answer | Confidence |
|---|---|---|---|
| 1 | Production domain? | **`earn-defi.com`** (site) · **`api.earn-defi.com`** (backend API) · `app.earn-defi.com` (investor cabinet, per docs) | Verified (site+api), cabinet UNKNOWN-live |
| 2 | Where is production hosted? | **Cloudflare** (live `server: cloudflare` header) | Verified |
| 3 | GH Pages / Vercel / Netlify / CF / VPS / Mac Mini? | **Cloudflare Pages** for the site; **Mac Mini** (via `cloudflared` tunnel) for the API backend. NOT GitHub Pages, NOT Vercel/Netlify. | Verified |
| 4 | What files does production USE? | The **`landing/`** Astro app → built to **`landing/dist/`** → served as `earn-defi.com`. Canonical dashboard = `landing/src/pages/dashboard.astro` (+ `DashboardLive.jsx` island). | Verified |
| 5 | What builds production? | `cd landing && npm run build` (`astro build`), with `prebuild` = `python3 ../scripts/generate_track_snapshot.py` + `check_snapshot_freshness.py`. Output → `landing/dist`. | Verified (`package.json`) |
| 6 | What deploys production? | **Cloudflare Pages git-integration builds `landing/dist` itself on every push to `main`.** No local deploy command, no wrangler-from-Mac, no GitHub Action. | Verified (`wrangler.toml name="earn-defi" pages_build_output_dir="landing/dist"` + `server: cloudflare` + no `CNAME`) |
| 7 | Deploy triggered by? | **GitHub push to `main` → CF Pages auto-build.** (Cron/local scripts only produce the *data snapshot* that gets pushed; they do not deploy.) | Verified topology; CF build enablement is OPAQUE from Mac |
| 8 | Same GitHub repo as production? | Yes — CF Pages is connected to `yurii-spa/SPA`, builds `landing/` on `main`. | Verified topology |
| 9 | Could production serve an OLD build? | **YES — this is the recurring "stale site" root cause.** If CF Pages git-integration pauses/fails/lags, `earn-defi.com` keeps serving a previous build even though `main` is fresh. CF build logs are **not reachable from the Mac** (no CF API token). | Verified as a real, prior incident (2026-07-04 CF-lag) |
| 10 | How to check production freshness? | Compare **live `/status` day count** vs **`origin/main:landing/src/data/track_snapshot.json`**. Automated by Site Custodian (`site_freshness.yml`, every 6h). | Verified (commands below) |

## LIVE FRESHNESS CHECK (run during this audit)

| Source | Value |
|---|---|
| `curl earn-defi.com/status/` → track days | **13** |
| `origin/main:landing/src/data/track_snapshot.json` | **13 days, `as_of` 2026-07-04** |
| Verdict | **✅ PRODUCTION IS FRESH RIGHT NOW** (site == `origin/main`) |

So at audit time the stale-site problem is **not** currently manifesting — but the *mechanism* that causes it (opaque CF build) is real and recurs.

## Deploy / data pipeline (canonical, one path)

```
Mac Mini launchd daily cycle (06:00 UTC*)                     [*plist Hour=8 CEST = 06:00 UTC]
  → writes data/golive_status.json, equity_curve_daily.json, etc.
  → run_daily_paper_cycle.sh Step 3: scripts/deploy_site_snapshot.py
        regenerates landing/src/data/track_snapshot.json
        pushes it (push_to_github_batch.py) → origin/main  (only if changed)
  → Cloudflare Pages git-integration sees the push to main
        runs `cd landing && npm run build` → landing/dist
        deploys to earn-defi.com                              (≤ ~30 min target)
  → Site Custodian (site_freshness.yml, 6h) verifies site == snapshot == API,
        degrades the snapshot to a plaque if it ever OVERSTATES.
API backend (api.earn-defi.com): FastAPI apiserver (:8765) on the Mac Mini,
        exposed via cloudflared tunnel — separate from the CF Pages static site.
```

## The MANY deploy/push scripts (a "several parallel systems" smell)

`scripts/` contains a large, overlapping set: `DEPLOY.sh`, `deploy_all.sh`, `deploy_site_snapshot.py`, `auto_push.sh`, `git_autopush.sh`, `git_push.sh`, `do_git_push.command`, `fix_and_push.command`, `install_auto_push.sh`, `diagnose_push.sh`, `com.spa.autopush.plist`, + `push_to_github.py` / `push_to_github_batch.py` (root). **Which are canonical vs legacy is UNKNOWN and must be mapped in PHASE 7** (this phase does not touch them). Canonical-appearing today: `push_to_github_batch.py` (API push) + `deploy_site_snapshot.py` (snapshot regen) + `com.spa.autopush.plist` (launchd, 90-min). The `*.command`/`*.sh` git-push helpers look like **legacy** from the pre-API-push era.

## GitHub Pages mirror (NOT production — clarified)

`deploy-landing.yml` publishes to **GitHub Pages**, which does **not** serve `earn-defi.com`. It is now `workflow_dispatch`-only (manual mirror). Any belief that "GitHub Pages = production" is **false** for this project. (This confusion is likely a contributor to the "site looks stale" reports — people checked the wrong surface.)

## Known production risks (recurring)

1. **Opaque CF Pages build** — when the git-integration build pauses/fails, the site silently serves an old build. **Resolution is owner-gated in the Cloudflare Pages dashboard** (confirm auto-build-on-push is enabled, repo still linked, build command not failing). Nothing in the repo can fix a paused CF build.
2. **`SPA_PAT` GitHub secret invalid (401)** — the freshness workflow's auto-degrade push fails; owner must set a valid token.
3. **API backend is single-host (Mac Mini)** — if the Mac/tunnel is down, `api.earn-defi.com` (live dashboard data) goes stale/unavailable while the static site still serves.

## Concrete production-freshness commands (for the owner / future agents)

```bash
# 1. What day does the LIVE site show?
curl -s https://earn-defi.com/status/ | grep -oE 'id="st-days"[^>]*>[0-9]+' | grep -oE '[0-9]+$'
# 2. What day does origin/main (what CF SHOULD build) show?
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w)
curl -s -H "Authorization: token $PAT" \
  "https://api.github.com/repos/yurii-spa/SPA/contents/landing/src/data/track_snapshot.json?ref=main" \
  | python3 -c "import sys,json,base64;print(json.loads(base64.b64decode(json.load(sys.stdin)['content']))['real_track_days'])"
# 3. If (1) < (2) for >30 min → CF build is lagging → check the Cloudflare Pages dashboard (owner).
# 4. Automated equivalent: data/site_freshness_report.json (Site Custodian, committed to main).
```

**UNKNOWNs to verify later:** cabinet (`app.earn-defi.com`) live-hosting details; exact CF Pages project build settings (owner-dashboard-only); which of the many `scripts/*deploy*` are dead.

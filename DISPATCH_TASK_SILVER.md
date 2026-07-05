# DISPATCH TASK — "Silver" unblocks (SPA_PAT secret + Cloudflare Pages auto-build)

**For:** Claude Dispatch. **Owner-approved.** Two independent tasks; do Task 1 fully, Task 2 as far as credentials allow, then report.

## Before you start (mandatory)
1. Read `PROJECT_CONTROL/00_START_HERE.md` + `PROJECT_CONTROL/01_MASTER_RULES.md`.
2. Hard rules that apply: `origin/main` is truth (read via GitHub API, not `git show origin/main`); push only via `push_to_github_batch.py`; **never** touch RiskPolicy / `cycle_runner` / execution / go-live track / agent schedules; secrets live in macOS Keychain, never write them into any file or commit; verify deploys by live content, never a bare curl status.
3. Python: `/Users/yuriikulieshov/miniconda3/bin/python3`.

---

## TASK 1 — Fix the `SPA_PAT` GitHub Actions secret (you CAN fully do this)

**Why:** the `SPA_PAT` Actions secret exists but is invalid (401), so the Site Custodian freshness workflow (`.github/workflows/site_freshness.yml`) can't auto-degrade an overstated site. A valid `GITHUB_PAT_SPA` already lives in Keychain and has the needed Contents:write scope — reuse it as the quick fix.

**Steps (do exactly):**
```bash
# 1. Confirm the valid token is readable (do NOT print it):
security find-generic-password -s GITHUB_PAT_SPA -w >/dev/null && echo "token present"

# 2. Ensure gh is authenticated (skip if `gh auth status` is already green):
gh auth status 2>/dev/null || security find-generic-password -s GITHUB_PAT_SPA -w | gh auth login --with-token

# 3. Set the SPA_PAT Actions secret to the valid token (gh encrypts it; value never hits a file):
security find-generic-password -s GITHUB_PAT_SPA -w | gh secret set SPA_PAT --repo yurii-spa/SPA --body -
# (if your gh version rejects `--body -`, use:  gh secret set SPA_PAT --repo yurii-spa/SPA  and paste when prompted,
#  or the REST API with libsodium encryption — never echo the token to a file/log.)
```

**Verify (must do):**
```bash
# Re-run the freshness workflow and confirm it no longer 401s:
gh workflow run site_freshness.yml --repo yurii-spa/SPA   # if it has workflow_dispatch; else wait for its 6h cron
sleep 60
gh run list --repo yurii-spa/SPA --workflow site_freshness.yml -L 1
# Open the latest run's log; the step that reads the repo via SPA_PAT should succeed (no "Bad credentials"/401).
```
**Report:** secret updated (yes/no) + the freshness run conclusion. **Hygiene note for the owner (state it, don't act):** reusing `GITHUB_PAT_SPA` works now but couples the two; a dedicated fine-grained PAT (repo `yurii-spa/SPA`, Contents:read-write + Actions:read) is cleaner long-term — owner can swap it in later the same way.

---

## TASK 2 — Cloudflare Pages auto-build-on-push (needs a Cloudflare credential you may not have)

**Why:** `earn-defi.com` is built by **Cloudflare Pages** (project `earn-defi`, builds `landing/` → `landing/dist` on push to `main`). The recurring "site shows stale data" problem is a paused/failing CF build. This is a Cloudflare-account setting — **not in the repo.**

**First, check whether you even have a Cloudflare credential:**
```bash
for n in CLOUDFLARE_API_TOKEN CF_API_TOKEN CLOUDFLARE_TOKEN CF_TOKEN CLOUDFLARE_PAGES_TOKEN; do
  security find-generic-password -s "$n" -w >/dev/null 2>&1 && echo "have: $n"
done
```

**If NO token is found (expected):** you cannot change CF settings. Do the read-only verification instead and hand the config back to the owner:
```bash
bash scripts/is_site_fresh.sh    # PASS = site currently fresh; CF-LAG = build is paused/behind (the real problem)
```
Report the result. Tell the owner the config is theirs to do (Cloudflare dashboard → Workers & Pages → project `earn-defi` → Settings → Builds & deployments: Production branch `main`, Build command `npm run build`, Output dir `landing/dist`, **Automatic deployments = On**; check latest Deployments row is **Success**). If they want you to do it, they must add a Cloudflare API token (Pages:Edit) to Keychain under `CLOUDFLARE_API_TOKEN` and re-run you.

**If a token IS present:** verify config via the CF API (read-only first — list the `earn-defi` Pages project and confirm `production_branch=main`, build config present, deployments not failing). Only change settings if the owner explicitly asked; report findings first.

---

## Done criteria
- Task 1: `SPA_PAT` set to a valid token + freshness workflow no longer 401 → **report done**.
- Task 2: either configured via CF token, or (no token) `is_site_fresh.sh` result reported + the exact dashboard steps handed back to the owner.
- Update `PROJECT_CONTROL/11_CHANGELOG.md` with what you changed, and report changed files + verification results. Do not claim the site is fixed unless `is_site_fresh.sh` returns PASS.

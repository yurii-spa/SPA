# Production Deployment Policy

## Current Setup
- Repository: github.com/yurii-spa/SPA (private)
- Landing: Cloudflare Pages project `earn-defi` → earn-defi.com
- Cabinet: Cloudflare Pages project `earn-defi-cabinet` → app.earn-defi.com
- Python backend: macOS launchd (Family Fund API, port 8766)

## Deployment Triggers
### Landing (earn-defi.com)
- Push to main branch → CF Pages auto-builds `landing/` directory
- Build command: `npm run build`
- Output dir: `dist`
- Node version: 20
- Build time: ~700ms

### Cabinet (app.earn-defi.com)
- Manual deploy: `bash scripts/cf_deploy_cabinet.command`
- Uses wrangler 4.x with OAuth token stored at ~/.wrangler/config/default.toml
- Build: `cd cabinet && npm run build` first

### Python API (127.0.0.1:8766)
- Managed by launchd: com.spa.familyfund
- Auto-starts on login, auto-restarts on crash
- Logs: ~/Documents/SPA_Claude/logs/familyfund_api.log
- Manual restart: `launchctl kickstart -k gui/$(id -u)/com.spa.familyfund`

## Pre-Deploy Checklist
1. [ ] npm run build passes locally
2. [ ] No TypeScript/Astro errors
3. [ ] No forbidden words in content (safe, guaranteed, protected, risk-free)
4. [ ] New pages added to Footer nav
5. [ ] APY figures have "variable, not guaranteed" qualifier

## Rollback
- CF Pages: previous deployment accessible in CF Dashboard → Pages → Deployments
- Instant rollback: click "Rollback to this deployment"
- Python API: git revert + restart launchd service

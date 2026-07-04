# 04 — HOSTING & PRODUCTION

Canonical deep source: `AUDIT_03_HOSTING_AND_PRODUCTION.md` + `docs/adr/ADR-YL-011-site-custodian.md` ("Deploy path").

- **earn-defi.com = Cloudflare Pages** (`wrangler.toml name=earn-defi pages_build_output_dir=landing/dist`), builds `landing/` on push to `main`. NOT GitHub Pages, NOT Vercel.
- **api.earn-defi.com = FastAPI on the Mac Mini** (:8765) via `cloudflared` tunnel.
- Deploy trigger = CF auto-build on push to `main` (**opaque from the Mac — owner-gated CF dashboard**).
- **Stale-site root cause = CF build lag/pause.** Detect with `15_CANONICAL_COMMANDS` freshness check + Site Custodian (`site_freshness.yml`, 6h). Never claim "deployed" without a live-content check.

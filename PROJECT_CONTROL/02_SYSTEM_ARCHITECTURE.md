# 02 — SYSTEM ARCHITECTURE

Canonical deep source: `CLAUDE.md` (Архитектура runtime) + `docs/04_layered_architecture.md` + `AUDIT_04_APPLICATION_STRUCTURE.md`.

**One-paragraph map:** Mac Mini runs launchd `com.spa.daily_cycle` (06:00 UTC) → `cycle_runner` (adapters→strategies→RiskPolicy→virtual rebalance→equity→GoLive) writing `data/*.json`; `com.spa.apiserver` serves FastAPI (:8765) at `api.earn-defi.com` via `cloudflared`; the daily cycle regenerates `landing/src/data/track_snapshot.json` and pushes to `main`; **Cloudflare Pages** builds `landing/` → **earn-defi.com**. Three apps: `landing/` (Astro site+dashboard), `cabinet/` (Vite/React investor cabinet), `spa_core/api/` (FastAPI). Product brain = `spa_core/` (stdlib-only runtime).

See AUDIT_04 for the full page/router/data map.

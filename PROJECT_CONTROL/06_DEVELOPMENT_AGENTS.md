# 06 — DEVELOPMENT / ENGINEERING AGENTS

Canonical deep source: `AUDIT_05_AGENT_SYSTEMS.md` §B + `AUDIT_07`.

Dev/ops agents maintain/push/deploy/verify — they **MUST NOT invent or change DeFi strategy/risk rules**. Key: `autopush` (90 min → `push_to_github.py` → `main`), `system_briefing` (30 min doc), `agent_health`, `rules_watchdog`, `self_heal`, `cycle_health`/`cycle_gap_monitor`, `system_health_morning`/`evening`, `uptime_monitor`/`watchdog`/`dashboard_watcher`, `daily_backup`/`weekly_backup`. **Site Custodian** (GitHub Actions `site_freshness.yml` + `site_content_audit.yml`) verifies prod. Human Claude Code + Dispatch push directly via `push_to_github_batch.py`. Deploy agents ONLY via `check_agent_before_deploy.sh`, bash-wrapper, `/tmp` logs (rule 11).

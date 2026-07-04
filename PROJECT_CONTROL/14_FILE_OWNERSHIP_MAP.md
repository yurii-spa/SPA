# 14 — FILE OWNERSHIP MAP (who writes what — do not cross)

| Path | Written by | Others may |
|---|---|---|
| `data/*.json` (state) | PRODUCT agents (daily_cycle etc.) | read only — never hand-edit the track |
| `landing/src/data/track_snapshot.json` | `deploy_site_snapshot.py` (post-cycle) | read only |
| `spa_core/risk/policy.py` | ADR-gated only | never edit without ADR |
| `spa_core/**` runtime | Claude Code / Dispatch (code tasks) | product agents NEVER |
| `docs/SYSTEM_BRIEFING.md` | `com.spa.system_briefing` (auto) | never hand-edit |
| `KANBAN.json` | concurrent hourly writer + humans | re-read before write |
| `.github/workflows/*` | dev tasks | product agents never |
| `launchd/*.plist`, `~/Library/LaunchAgents/com.spa.*` | deploy via `check_agent_before_deploy.sh` | never direct-load |
| Secrets | macOS Keychain | never a file |

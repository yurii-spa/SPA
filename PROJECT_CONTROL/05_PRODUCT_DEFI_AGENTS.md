# 05 — PRODUCT DeFi AGENTS

Canonical deep source: `AUDIT_05_AGENT_SYSTEMS.md` §A + `CLAUDE.md` (LaunchAgents) + live `launchctl list | grep spa` + `docs/SYSTEM_BRIEFING.md`.

Product agents monitor/decide DeFi and write `data/*.json` — they **MUST NOT modify code, docs, or deploy config**. Key: `daily_cycle` (06:00 UTC, the track), `tournament_engine`/`mass_tournament`, `strategy_lab_paper`, `rates_desk_paper`, `rwa_safety_board`, `refusal`, `hy_cycle`/`lp_cycle`, `red_flag_monitor`/`peg_monitor`/`sky_monitor`/`base_gas_monitor`/`bts-*`, `threat_reactor`, `governance_watcher`, `portfolio_monitor`. RiskPolicy is deterministic + LLM-forbidden; all new strategies `IS_ADVISORY=True`.

# AUDIT_05 — AGENT SYSTEMS (two layers)

**Generated:** 2026-07-04 · read-only · PHASE 5
**Verified:** `launchctl list | grep com.spa` → **47 running** agents; 54 unique plists; **0 retired-set agents running** (good). Source of truth = `launchctl` + `docs/SYSTEM_BRIEFING.md`, NOT any static count.

> This project has **TWO agent layers that must not be mixed**: (A) product DeFi agents, (B) dev/engineering agents. Below plus a third **infra/UI** group that is neither.

---

## Section A — PRODUCT DeFi agents (monitor/decide DeFi; may write DATA, must NOT write code)

| Agent (`com.spa.*`) | Purpose | Schedule | Writes | Website impact |
|---|---|---|---|---|
| `daily_cycle` | THE daily paper cycle → adapters → strategies → RiskPolicy → virtual rebalance → equity accrual → GoLive check | **06:00 UTC** (plist Hour=8 CEST) | `trades.json`, `equity_curve_daily.json`, `golive_status.json`, evidence | drives the site's track numbers |
| `tournament_engine` / `mass_tournament` | Strategy tournament (backtest→paper→live ladder) | 09:00 UTC / daily | `strategy_tournament.json`, `mass_tournament_results.json` | `/api/tournament` page |
| `strategy_lab_paper` / `rates_desk_paper` | Sleeve + Rates-Desk live-paper (advisory, no capital) | hourly | `data/rates_desk/paper/`, forward series | `/rates-desk` |
| `rwa_safety_board` / `refusal` | RWA collateral safety board / daily refusal scorer | daily / 05:45 | `refusal_status.json` | `/refusals` |
| `hy_cycle` / `lp_cycle` | Engine B (HY) / Engine C (LP) sleeve accrual | hourly | sleeve JSONs | dashboard sleeves |
| `red_flag_monitor` / `peg_monitor` / `sky_monitor` / `base_gas_monitor` / `bts-feed`/`bts-monitor` / `realized_at_size` | Market-intel monitors (spikes, pegs, gas, size-realization) | 5-15 min | advisory logs | advisory badges |
| `threat_reactor` | Auto-kill-switch on CRITICAL threat to a held protocol | 5 min | kill-switch state | risk gate |
| `governance_watcher` | On-chain governance proposals | daily | `governance_proposals.json` | — |
| `portfolio_monitor` / `dfb_capture` / `tier1_digest` / `tier1_governance` | Portfolio health / DFB capture / Tier-1 digest+governance | varied | health/digest JSONs | dashboard |

**Product-agent rules (enforced by design):** RiskPolicy is **deterministic, LLM-FORBIDDEN**; product agents **do NOT modify code**; `execution/` is never imported from read-only/paper code; all new strategies `IS_ADVISORY=True` until go-live.

## Section B — DEV / ENGINEERING agents (maintain/push/deploy/verify; may write CODE/DOCS/deploy)

| Agent | Purpose | Schedule | Pushes GitHub? | Deploys prod? |
|---|---|---|---|---|
| **`autopush`** | Processes `push_v*.sh` → GitHub via `push_to_github.py` | **every 90 min** | **YES** (→ `origin/main`) | Indirectly (push triggers CF build) |
| `system_briefing` | Regenerates `docs/SYSTEM_BRIEFING.md` | every 30 min | via autopush | no |
| `agent_health` | Heartbeat over all `com.spa.*` + system checks | hourly | no | no |
| `rules_watchdog` | Rules/invariant watchdog + Telegram | 5 min | no | no |
| `self_heal` | Revives dead agents + recovers missed cycle | 5 min | no | no |
| `cycle_health` / `cycle_gap_monitor` | Track continuity / gap | 15 min / daily | no | no |
| `system_health_morning`/`_evening` | E2E/semantic health monitor | 08:30/20:30 UTC | no | no |
| `uptime_monitor` / `watchdog` / `dashboard_watcher` | Uptime / watchdog / dashboard poll→Telegram | 5 min | no | no |
| `daily_backup` / `weekly_backup` | DB + critical-file backups | daily/weekly | no | no |
| **Site Custodian** (`site_freshness.yml`, `site_content_audit.yml` — GitHub Actions, not launchd) | Freshness + content-drift guard (ADR-YL-011) | 6h / weekly | degrade-push (needs valid `SPA_PAT`) | verifies prod |
| **Human-driven Claude Code CLI + Claude Dispatch** | Author code/docs, push via `push_to_github_batch.py` | ad-hoc | **YES** (directly to `main`) | Indirectly |

## Section C — Infra / UI (neither product-logic nor dev-tooling)

`apiserver` (FastAPI :8765), `cloudflared` (tunnel), `dashboard`, `familyfund` (:8766), `telegram_bot`, `telegram_milestone`, `digest_daily`/`digest_weekly`, `checkpoint-7day`, `analytics_tier_b`/`_c`.

## Section D — Separation rules (PROPOSED — for PROJECT_CONTROL)

1. **Product agents MUST NOT modify code, docs, or deploy config.** They read live sources + write `data/*.json` only.
2. **Dev agents MUST NOT invent/alter DeFi strategy or risk rules.** They touch code/docs/deploy, never RiskPolicy thresholds or strategy logic (that requires an ADR).
3. **Deployment automation MUST NOT change investment logic.** `autopush`/deploy scripts move bytes, they don't decide.
4. **Documentation automation (`system_briefing`) MUST NOT change behavior** — it mirrors state, read-only.
5. **Claude Dispatch and Claude Code CLI MUST both obey the same control file** (proposed `PROJECT_CONTROL/00_START_HERE.md`) — neither may bypass RiskPolicy, the `execution/` boundary, or the secrets policy.
6. **RETIRED agents must never revive:** `bot_commands`, `httpserver`, `telegram_daily`, `telegram_weekly`, `morning_digest`, `daily-paper-report` (revival → Telegram-409/duplicate-flood). `RETIRED_LABELS` in `agent_health_monitor.py` is the source of truth. (Verified: 0 running now.)

**UNKNOWNs:** exact per-agent log paths (mostly `/tmp/spa_<name>.log` by the wrapper convention) + failure modes per agent — enumerate in PROJECT_CONTROL/05+06 (canonical list = `launchctl list | grep spa` + `docs/SYSTEM_BRIEFING.md`, which drift-proof themselves).

# SPA — Smart Passive Aggregator

## Project Overview

SPA is a multi-agent DeFi yield management system that automatically fetches APY/TVL data
from whitelisted lending protocols (Aave, Compound, Morpho, Yearn, Pendle, Maple, Euler),
applies deterministic Risk Policy rules, and allocates a $100K virtual portfolio to maximise
stable stablecoin yield. The system runs exclusively in **paper trading mode** until a
separate ADR is accepted — go-live decision date is **2026-07-15**.

---

## Current Status (always keep updated)

| Field | Value |
|---|---|
| Sprint | **v1.6** (2026-05-22) |
| Paper trading | **Day 2 / 56** (started 2026-05-20, go-live decision 2026-07-15) |
| Virtual capital | **$100,000 USDC** |
| Current APY | **~4.2%** |
| Target APY | **7.3%** (at $100K) |
| APY gap | ~3.1 pp — closes as Pendle PT positions accumulate |
| Tests passing | **~140** |
| Files | **116+** in repo (manifest 136 entries) |
| GitHub repo | `github.com/yurii-spa/SPA` — branch `main` |
| Dashboard | `index.html` (open locally or GitHub Pages) — **v1.6, 6 tabs** |
| Kanban | `kanban.html` |
| Go-live verdict | **NOT_READY** — 5/11 criteria passing; blocked by paper duration (2/50 days) |

---

## Architecture

```
DeFiLlama API ──┐
                ├──► data_pipeline/ ──► data/*.json ──► index.html (GitHub Pages)
Pendle API ─────┘         │
                          ▼
                    export_data.py  (runs every 4h via GitHub Actions)
                          │
                    ┌─────┴──────┐
                    │  Risk Policy│  (deterministic — LLM FORBIDDEN)
                    └─────┬──────┘
                          │
                    paper_trading/engine.py  →  trades.json, status.json
                          │
                    golive/checklist.py  →  golive_readiness.json
                          │
                    FastAPI server (run_server.py)  →  /api/* endpoints
                          │
                    WebSocket /ws/agents  →  live agent thought bubbles
```

**Stack:**
- Python 3.11+ monorepo, zero external state (SQLite + JSON files)
- GitHub Actions: 4h cron → `export_data.py` → commit data files → Pages deploy
- FastAPI + uvicorn for local API server
- Pure HTML/JS dashboard (no React build step required)
- SQLite for decision log, message bus, paper trades
- ReportLab for PDF reports (every 4h)

---

## Key Constraints (NEVER violate)

1. **Risk Agent and Execution Agent are STRICTLY DETERMINISTIC — LLM FORBIDDEN.**
   Prompt injection into capital-touching code is a critical attack vector. Any change
   to `spa_core/risk/policy.py` requires: ADR → Owner approval → snapshot → 2-week paper test.

2. **LIVE mode requires ALL of the following:**
   - All 11 go-live criteria PASS (or ≤1 WARN on performance criteria, no FAIL/PENDING)
   - Owner types `"I CONFIRM LIVE TRADING"` manually in `golive/activate.py`
   - Paper trading completed ≥ 50 days (criterion 1)
   - ADR accepted by Yurii

3. **Only whitelisted protocols:**
   - **Tier 1 (T1):** Aave V3, Compound V3, Morpho — max 40% each
   - **Tier 2 (T2):** Yearn V3, Pendle PT, Maple Finance, Euler V2 — max 20% each, 35% total T2
   - **Watch List:** Sky/sUSDS — **PENDING, 0% allocation** (GSM Pause Delay = 24h, need ≥48h)

4. **Sky/sUSDS allocation is 0% until GSM Pause Delay ≥48h is confirmed on-chain.**
   The `sky_monitor.py` checks 3 fallback RPC sources. When 48h is confirmed, Sky moves to T1
   at 30% weight. Documentation v0.4.5 describes the post-confirmation state.

5. **Paper trading must run ≥ 50 days before go-live decision** (not 56 — checklist uses 50;
   the 56-day figure in the dashboard is the full planned paper trading window to 2026-07-15).

6. **Risk Policy version must stay at `"v1.0"`** throughout paper trading. Any change → new ADR.

---

## Two-Layer Agent Architecture

### Layer 1 — Dev Agents (`spa_core/dev_agents/`)

Development tooling. LLM-powered OK. Not part of the product runtime.

| Agent | File | Role |
|---|---|---|
| Architect | `architect.py` | Sprint planning, roadmap, backlog review, idea evaluation |
| Tester | `tester.py` | Runs pytest, sends Telegram pass/fail digest |

```bash
python -m spa_core.dev_agents.architect --command review-backlog
python -m spa_core.dev_agents.tester
```

### Layer 2 — Product Agents (`spa_core/agents/`)

Runtime agents that touch capital decisions.

| Agent | Model | LLM? | Role |
|---|---|---|---|
| CEO Agent | Claude Sonnet 4.6 | ✅ OK | Strategy, orchestration, final approval, Owner Q&A |
| Strategy Agent | Gemini 2.5 Flash | ✅ OK | Strategy selection, edge case analysis |
| Data Agent | Gemini 2.5 Flash-Lite | ✅ OK | Data fetch, anomaly classification |
| Monitoring Agent | Claude Haiku 4.5 | ✅ OK | Heartbeat, incident classification |
| Risk Agent | — | ❌ FORBIDDEN | VaR, concentration limits, circuit breakers |
| Execution Agent | — | ❌ FORBIDDEN | Paper trade execution |

Model assignments are in `spa_core/agents/model_config.py` (decoupled from agent code).
Estimated LLM cost: ~$6.60/month at 10 calls/agent/day.

---

## File Structure

| File / Directory | Purpose |
|---|---|
| `index.html` | Main dashboard — 6 tabs: Home, Paper Trading, Analytics, Go-Live, Agents, System |
| `kanban.html` | Kanban board UI |
| `KANBAN.json` | Kanban source of truth (updated by Architect agent or manually) |
| `run_server.py` | Quick-start: `python run_server.py` → FastAPI at localhost:8000 |
| `spa_core/export_data.py` | Master export script — runs all 20 pipeline sections, writes data/*.json |
| `spa_core/paper_trading/engine.py` | `PaperTradingEngine`, `auto_allocate()` — core trading logic |
| `spa_core/paper_trading/strategies.py` | Strategy registry (`v1_passive`, `v2_aggressive`) |
| `spa_core/paper_trading/pendle_strategy.py` | `PendlePosition` dataclass, `pendle_allocation_size()` |
| `spa_core/risk/policy.py` | `RiskConfig`, `RiskPolicy`, `Position`, `PortfolioState` — **deterministic only** |
| `spa_core/risk/versions/v1_0_passive.py` | Frozen snapshot of RiskConfig v1.0 (rollback target) |
| `spa_core/data_pipeline/defillama_fetcher.py` | DeFiLlama API: 12 whitelisted pools (Arbitrum+Base), `retry_request()` |
| `spa_core/data_pipeline/pendle_fetcher.py` | Pendle PT pools with 7 quality gates, concurrent fetch |
| `spa_core/data_pipeline/sky_monitor.py` | Sky/sUSDS GSM Pause Delay checker (3 fallback RPCs) |
| `spa_core/data_pipeline/apy_gap_report.py` | APY gap analysis vs 7.3% target |
| `spa_core/golive/checklist.py` | 11-criteria go-live readiness checker |
| `spa_core/golive/report_card.py` | ASCII report card (prints on every export run) |
| `spa_core/golive/activate.py` | Live-capital activation flow (requires manual confirmation) |
| `spa_core/golive/daily_check.py` | Daily go-live health check |
| `spa_core/api/server.py` | FastAPI: 17 REST endpoints + WebSocket |
| `spa_core/api/agent_broadcaster.py` | WebSocket thought-bubble broadcaster |
| `spa_core/agents/model_config.py` | Pluggable LLM model assignments per agent |
| `spa_core/agents/decision_logger.py` | SQLite-backed audit log for every agent decision |
| `spa_core/alerts/daily_report.py` | `DailyReportBuilder` — Telegram digest (day X/56, PnL, risk flags) |
| `spa_core/alerts/risk_monitor.py` | `RiskMonitor` — real-time alerts (drawdown, stale data, kill-switch) |
| `spa_core/alerts/email_sender.py` | Gmail SMTP alerts |
| `spa_core/alerts/telegram_sender.py` | Telegram bot alerts |
| `spa_core/backtesting/engine.py` | `BacktestEngine` — replays `auto_allocate()` on historical/synthetic APY |
| `spa_core/backtesting/metrics.py` | `BacktestMetrics` — Sharpe, drawdown, win rate, annualised return |
| `spa_core/backtesting/tournament.py` | `StrategyTournament` — weighted scoring across strategies |
| `spa_core/backtesting/data_loader.py` | DeFiLlama historical + `generate_synthetic_history()` (OU process) |
| `spa_core/analytics/portfolio_stats.py` | Calmar, Sortino, Ulcer Index, rolling Sharpe/drawdown |
| `spa_core/analytics/apy_tracker.py` | APY history tracker with 90-day rolling store |
| `spa_core/optimization/kelly.py` | Kelly criterion position sizing |
| `spa_core/optimization/markowitz.py` | Pure-Python Markowitz MVO (projected gradient descent) |
| `spa_core/optimization/recommender.py` | `AllocationRecommender` — Kelly → MVO → RiskPolicy pipeline |
| `spa_core/reports/pdf_generator.py` | ReportLab PDF report generator (every 4h) |
| `spa_core/message_bus/bus.py` | In-process SQLite-backed pub/sub message bus |
| `spa_core/orchestrator/graph.py` | LangGraph agent orchestration graph |
| `spa_core/tools/github_pusher.py` | Multi-file GitHub pusher (136 files in PUSH_MANIFEST) |
| `spa_core/tools/seed_demo_data.py` | Demo data seeder for dashboard testing |
| `spa_core/dev_agents/architect.py` | Architect agent (Layer 1) |
| `spa_core/dev_agents/tester.py` | Tester agent (Layer 1) |
| `data/*.json` | All live data files (written by export_data.py) |
| `docs/` | API reference, data schema, architecture, operator runbook, ADRs |
| `tests/` | Top-level integration tests (e2e, retry logic, concurrent fetch, rebalancing) |
| `spa_core/tests/` | Unit tests per module |
| `.github/workflows/spa-run.yml` | 4h cron: install deps → pytest → export → commit → Pages deploy |
| `push_to_github.command` | Double-click to push all 136 files (uses `repo` scope token) |
| `push_workflow.command` | Push `.github/workflows/` files (requires `workflow` scope token) |

---

## Key Data Files (`data/*.json`)

| File | Contents | Written by |
|---|---|---|
| `status.json` | Portfolio summary: capital, PnL, positions, current APY, drawdown | `export_data.py` |
| `protocols.json` | Live whitelist pools with APY, TVL, tier, chain | `defillama_fetcher.py` |
| `trades.json` | All paper trade records with strategy_id, timestamps | `engine.py` |
| `risk_alerts.json` | Active risk alerts by severity (INFO/WARN/CRITICAL) | `risk_monitor.py` |
| `alerts.json` | Historical alert log | `export_data.py` |
| `backtest_results.json` | Backtest metrics per strategy (Sharpe, drawdown, win rate, APY) | `backtesting/engine.py` |
| `golive_readiness.json` | 11 criteria results + verdict (READY/ALMOST_READY/NOT_READY/BLOCKED) | `checklist.py` |
| `strategy_state.json` | v1_passive live state | `engine.py` |
| `strategy_v2.json` | v2_aggressive live state | `engine.py` |
| `strategy_comparison.json` | Side-by-side strategy metrics | `export_data.py` |
| `historical_apy.json` | 90-day APY history per protocol | `data_loader.py` |
| `optimization_recommendations.json` | Kelly fractions, Markowitz weights, efficient frontier | `recommender.py` |
| `decision_log.json` | Chronological agent decision audit log | `decision_logger.py` |
| `pipeline_health.json` | Sections OK/FAIL counts, pool counts, fetch duration | `export_data.py` |
| `pnl_history.json` | Daily PnL time series | `export_data.py` |
| `latest_report.json` | PDF report metadata (path, timestamp) | `report_scheduler.py` |
| `bus_stats.json` | Message bus statistics | `message_bus/bus.py` |
| `chains_status.json` | Per-chain allocation and health | `export_data.py` |
| `meta.json` | Export timestamp, version, sprint | `export_data.py` |

---

## Risk Policy (from `spa_core/risk/policy.py` — `RiskConfig` v1.0)

| Parameter | Value | Meaning |
|---|---|---|
| `version` | `"v1.0"` | Policy version — must match for go-live criterion 5 |
| `version_date` | `"2026-05-20"` | Date of policy activation |
| `max_concentration_t1` | `0.40` | Max 40% of portfolio in any single T1 protocol |
| `max_concentration_t2` | `0.20` | Max 20% of portfolio in any single T2 protocol |
| `max_single_protocol` | `0.40` | Absolute cap on any single protocol |
| `max_total_t2_allocation` | `0.35` | T2 protocols combined ≤ 35% |
| `max_apy_for_new_position` | `30.0` | APY > 30% → reject (risk too high) |
| `min_apy_for_new_position` | `1.0` | APY < 1% → reject (not attractive) |
| `min_tvl_usd` | `5_000_000` | Pool TVL must be ≥ $5M |
| `max_drawdown_stop` | `0.05` | 5% portfolio drawdown → kill switch, close all positions |
| `max_single_position_drawdown` | `0.03` | 3% per-position drawdown → close that position |
| `var_confidence` | `0.95` | VaR confidence level (95%) |
| `var_horizon_days` | `7` | VaR horizon: 7 days |
| `max_var_pct` | `0.05` | VaR must not exceed 5% of portfolio |
| `min_cash_pct` | `0.05` | Always keep ≥ 5% cash buffer |
| `max_single_chain_allocation` | `0.70` | Max 70% on any single chain |
| `max_l2_total_allocation` | `0.50` | Arbitrum + Base combined ≤ 50% |
| `preferred_chains` | `["ethereum", "arbitrum", "base"]` | Only these chains allowed |

`approved=False` from `RiskPolicy` **cannot be overridden by any agent**.

---

## Go-Live Criteria (11 total, from `spa_core/golive/checklist.py`)

```
GO_LIVE_DATE     = "2026-07-15"
PAPER_START_DATE = "2026-05-20"
MIN_PAPER_DAYS   = 50
APY_TARGET       = 7.3  (%)
APY_GAP_MAX      = 2.0  (pp)
```

| # | Criterion | Threshold | Status (2026-05-22) |
|---|---|---|---|
| 1 | Paper Duration | ≥ 50 days elapsed | PENDING (2/50 days) |
| 2 | PnL Positive | total_pnl_usd > 0 | accumulating |
| 3 | No Critical Alerts | 0 CRITICAL severity alerts | — |
| 4 | Strategy Sharpe | backtest Sharpe ≥ 1.0 | — |
| 5 | Policy Unchanged | RiskConfig.version == "v1.0" | PASS |
| 6 | Max Drawdown | portfolio drawdown < 3% (WARN 3–4%, FAIL > 4%) | — |
| 7 | Diversification | ≥ 2 protocols, none > 45% | ramping up |
| 8 | Data Freshness | last export < 6h ago (WARN 6–12h, FAIL > 12h) | PASS |
| 9 | Wallet Ready | Gnosis Safe + hot wallet setup — manual; PENDING never blocks READY | PENDING (manual) |
| 10 | Strategy Tournament | v1_passive WINNING or TIED vs v2_aggressive | — |
| 11 | APY Gap | current APY within 2 pp of 7.3% target (WARN 2–3 pp, FAIL > 3 pp) | FAIL (gap ~3.1 pp) |

**Verdict logic:**
- `READY` — ≤1 WARN on criteria 1–8, 10–11; no FAIL, no PENDING (criterion 9 PENDING is OK)
- `ALMOST_READY` — ≤2 WARN on performance criteria, no FAIL, no PENDING
- `NOT_READY` — any FAIL or PENDING on performance criteria
- `BLOCKED` — negative PnL OR any CRITICAL alert

---

## GitHub Push Process

```
Token (repo scope):  stored in macOS Keychain — NEVER write it into any file.
                     Retrieve at runtime: security find-generic-password -s GITHUB_PAT_SPA -w
                     Save/rotate: bash setup_pat.sh  (interactive, hidden input)
Token (workflow scope): needed separately for .github/workflows/ files
Repo:  github.com/yurii-spa/SPA   branch: main
```

**SECRETS POLICY (incident 2026-06-10 — PAT leaked into 90+ generated files):**
1. NEVER write tokens, keys, or passwords into ANY file — including CLAUDE.md, HTML
   pushers, .command scripts, docs, or generated artifacts. No exceptions.
2. Scripts must read the PAT at runtime from Keychain (`GITHUB_PAT_SPA`) or an env var.
3. Never generate `push_*.html`-style artifacts with embedded credentials.
4. If a secret ever lands in a file: revoke it immediately at github.com/settings/tokens,
   then clean the files and git history.
5. Token expired / pushes return 401? → follow **docs/TOKEN_ROTATION_RUNBOOK.md**
   (token inventory, expiry dates, 2-minute rotation procedure). Current main token
   `spa-claude-fg` expires **2026-09-08**; GitHub emails a warning ~1 week before.

| Script | Scope | Use |
|---|---|---|
| `push_to_github.command` | `repo` | Double-click — pushes all 136 PUSH_MANIFEST files |
| `push_workflow.command` | `workflow` | Pushes `.github/workflows/` files only |
| `trigger_workflow.command` | `repo` | Manually triggers GitHub Actions run |

Push is sequential with retry on HTTP 429 (60s wait). A dry-run mode lists present/missing files
without pushing: `python -m spa_core.tools.github_pusher --token ghp_xxx --dry-run`

The PUSH_MANIFEST currently has **136 entries** (all agents, tests, docs, API modules, and CLAUDE.md).

---

## Development Workflow

### Sprint cycle
1. Yurii describes a feature or issue in chat
2. Architect agent reviews backlog and proposes sprint tasks
3. Tasks are implemented, tested, committed locally
4. `push_to_github.command` syncs to GitHub
5. GitHub Actions runs pytest + export pipeline + Pages deploy
6. Sprint log entry added to `SPA_sprint_log.md`
7. `MEMORY_FACTS.md` updated with any changed metrics/status
8. `KANBAN.json` updated (Architect agent or manually)

### Updating KANBAN.json
- Source of truth: `KANBAN.json` at project root
- Columns: `ideas → features → backlog → in_progress → review → done`
- Architect agent can update it via `--command update-kanban`
- Dashboard `kanban.html` reads it directly (no server needed)

### Running tests
```bash
# All tests (both test directories)
python -m pytest tests/ spa_core/tests/ -v

# Specific suite
python -m pytest spa_core/tests/test_risk_policy.py -v
python -m pytest spa_core/tests/test_golive.py -v
python -m pytest tests/test_integration_e2e.py -v
```

---

## Common Commands

```bash
# Run the full export pipeline (writes all data/*.json)
python -m spa_core.export_data

# Start local FastAPI server (port 8000)
python run_server.py

# Daily go-live health check (prints ASCII report card)
python -m spa_core.golive.daily_check

# Seed demo data for dashboard testing
python -m spa_core.tools.seed_demo_data

# Architect agent — review backlog
python -m spa_core.dev_agents.architect --command review-backlog

# Tester agent — run tests + Telegram report
python -m spa_core.dev_agents.tester

# Dry-run GitHub push (lists present/missing files)
python -m spa_core.tools.github_pusher --token ghp_xxx --dry-run

# Full GitHub push (reads PAT from Keychain)
python -m spa_core.tools.github_pusher --token "$(security find-generic-password -s GITHUB_PAT_SPA -w)"

# Check Sky/sUSDS GSM Pause Delay on-chain
python -m spa_core.data_pipeline.sky_monitor

# Run backtesting
python -m spa_core.backtesting.engine

# Generate strategy tournament results
python -m spa_core.backtesting.tournament
```

---

## API Endpoints

Base URL: `http://localhost:8000` (run `python run_server.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check — server alive, version |
| GET | `/api/status` | Full system status (portfolio, APY, paper trading day, go-live verdict) |
| GET | `/api/portfolio` | Portfolio summary: capital, PnL, deployed %, drawdown |
| GET | `/api/positions` | All open positions with protocol, tier, APY, PnL |
| GET | `/api/pools` | Live whitelisted pools from DeFiLlama + Pendle |
| GET | `/api/risk` | Current risk metrics: VaR, drawdown, alerts |
| GET | `/api/trades` | All paper trade records |
| GET | `/api/backtest` | Backtest results for active strategies |
| GET | `/api/backtest/replay` | Replay data for backtesting UI (equity curve day-by-day) |
| GET | `/api/backtest/summary` | Backtest summary table |
| GET | `/api/backtest/compare` | Strategy comparison metrics |
| GET | `/api/optimization` | Kelly fractions + Markowitz weights + efficient frontier |
| GET | `/api/events` | Recent agent thought-bubble events |
| GET | `/api/events/history` | Full agent event history |
| GET | `/api/apy/trends` | APY trend analysis across all protocols |
| GET | `/api/apy/history/{protocol_key}` | 90-day APY history for one protocol |
| POST | `/api/chat` | Chat with CEO Agent (text in → CEO response out) |
| POST | `/api/agent/thought` | Inject agent thought event (internal use) |
| WS | `/ws/agents` | WebSocket stream — live agent thought bubbles |

---

## Kanban Board

- **Source of truth:** `KANBAN.json` (root of project)
- **Dashboard:** `kanban.html` (open locally — no server needed)
- **Updated by:** Architect agent (`python -m spa_core.dev_agents.architect --command update-kanban`) or manually
- **Columns:** `ideas → features → backlog → in_progress → review → done`
- **GitHub Pages:** same file auto-deployed at `yurii-spa.github.io/SPA/kanban.html`

---

## Known Issues / Watch Points

1. **Sky/sUSDS at 0%** — GSM Pause Delay is 24h on-chain; requirement is ≥48h.
   `sky_monitor.py` checks automatically with 3 RPC fallbacks.
   When 48h is confirmed: upgrade Sky to T1 at 30% weight → expect APY to jump ~2–3 pp.

2. **Workflow scope token** — `.github/workflows/` files require a GitHub token with `workflow`
   scope. The standard `repo`-scope token (in Keychain as `GITHUB_PAT_SPA`) cannot
   push these. Use `push_workflow.command` with a separate workflow-scope token.

3. **APY gap** — Current ~4.2% vs 7.3% target (gap ~3.1 pp). Primary closure lever: Pendle PT
   pools accumulating positions over the paper trading period. If Sky/sUSDS 48h timelock
   activates, the gap closes faster. Criterion 11 is currently FAIL.

4. **Paper duration** — Go-live criterion 1 remains PENDING until 2026-07-09 (50 days from
   2026-05-20). The overall verdict cannot reach READY before this date regardless of other criteria.

5. **GitHub Pages** — Must be enabled manually in repo Settings → Pages → branch: `main` / `/(root)`.
   This is a user action tracked in the Kanban backlog.

6. **Telegram bot** — Setup requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars.
   Guide: `docs/setup_telegram_alerts.md`. Also a pending Kanban item.

---

## Sprint History Summary

| Sprint | Date | Key Deliverables |
|---|---|---|
| v0.1–v0.7 | 2026-05 (early) | Scaffolding, SQLite schema, 7-protocol whitelist, paper trading engine, Risk Policy (Kelly, concentration, kill switch), CEO/Data/Strategy/Monitoring agents, Message Bus, FastAPI REST API |
| v0.8 | 2026-05 | Agent thought bubbles, in-app chat, WebSocket agent stream |
| v0.9 | 2026-05 | Backtest engine (`BacktestMetrics`: Sharpe, drawdown, win rate), synthetic APY history (OU process), ADR governance |
| v0.10 | 2026-05 | Dual-strategy runtime (v1_passive + v2_aggressive), strategy comparison dashboard |
| v0.11 | 2026-05 | Gmail SMTP alerts (`email_sender.py`), GitHub Actions secrets |
| v0.12 | 2026-05 | Real DeFiLlama 90-day historical APY, APY charts, correlation matrix |
| v0.13 | 2026-05 | Portfolio optimisation (Kelly + Markowitz pure Python), `AllocationRecommender` |
| v0.14 | 2026-05 | PDF report generator (ReportLab, every 4h) |
| v0.15 | 2026-05 | Full FastAPI backend + WebSocket agent stream, `run_server.py` |
| v0.16 | 2026-05 | Agent decision log (SQLite-backed, `decision_log.json`) |
| v0.17 | 2026-05 | Go-live readiness checker (8 criteria at the time), ASCII report card |
| v1.0 | 2026-05-21 | 5-tab dashboard, full integration; 90/90 tests passing |
| v1.1 | 2026-05-21 | DeFiLlama whitelist corrected (12 pools, Arbitrum+Base only), v2_aggressive tournament fix |
| v1.2 | 2026-05-21 | Pendle PT integration (`pendle_fetcher.py`, 7 quality gates, `pendle_strategy.py`, ADR-002) |
| v1.3 | 2026-05-21 | Advanced analytics (Calmar, Sortino, Ulcer), tournament fix, APY Gap Tracker panel |
| v1.4 | 2026-05-22 | Daily report builder, real-time risk monitor, Sky monitor 3-RPC fallback, `model_config.py` |
| v1.5 | 2026-05-22 | Dashboard v2: APY Gap Tracker, Pendle panel, Day X/56 counter, live badge |
| v1.6 | 2026-05-22 | Dashboard v3+v4: Backtesting Replay UI, System Health tab; 4-file docs suite; GitHub Actions hardening (retry, pipeline_health.json, Telegram on failure); concurrent pool fetch + 1h cache; dev agents (Architect + Tester); Kanban board + kanban.html; manifest → 136 files; ~140 tests |

---

## Next Priorities (from Kanban backlog)

These are the top items in the `backlog` and `features` columns of `KANBAN.json`:

1. **Enable GitHub Pages** *(user action)* — repo Settings → Pages → branch: main / root
2. **Telegram Bot Setup** *(user action)* — set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; test daily digest
3. **Workflow Scope Token Push** *(user action)* — push `deploy-pages.yml` with workflow-scope token
4. **Sky/sUSDS T1 Upgrade** *(conditional)* — activate when on-chain GSM Pause Delay ≥48h confirmed
5. **Mac Mini Server Setup** — run export pipeline 24/7 locally instead of relying solely on GitHub Actions
6. **PostgreSQL Migration** — replace SQLite for multi-process safety before live capital
7. **Phase 3: Real Capital Execution (v2.0)** — Aave V3 live SDK integration, real wallet, safety checks
8. **Full 2-Year DeFiLlama Backtest** — replay on real historical data from 2022

---

## Protocol Whitelist (v0.4.5 operational state)

| ID | Protocol | Tier | Chains | Assets | Allocation limit | Status |
|---|---|---|---|---|---|---|
| T1-01 | Aave V3 | Tier 1 | Ethereum, Arbitrum, Base | USDC, USDT | ≤ 40% | Active |
| T1-02 | Compound V3 | Tier 1 | Ethereum, Arbitrum | USDC, USDT | ≤ 40% | Active |
| T1-03 | Morpho | Tier 1 | Ethereum, Base | USDC, USDT | ≤ 40% | Active |
| T2-01 | Yearn V3 | Tier 2 | Ethereum | USDC, USDT | ≤ 20% | Active |
| T2-02 | Pendle PT | Tier 2 | Ethereum, Arbitrum | PT-stablecoin | ≤ 20% | Active |
| T2-03 | Maple Finance | Tier 2 | Ethereum | USDC | ≤ 20% | Active |
| T2-04 | Euler V2 | Tier 2 | Ethereum | USDC, USDT | ≤ 20% | Active |
| WL-01 | Sky/sUSDS | Watch List | Ethereum | USDS | **0%** | PENDING 48h GSM |

---

## Financial Targets (ADR-009)

| Capital | Target Net APY | Annual net income |
|---|---|---|
| $10,000 | 4.0% | $400 |
| $25,000 | 6.2% | $1,545 |
| $50,000 | 6.9% | $3,452 |
| **$100,000** | **7.3%** | **$7,266** |
| $250,000 | 7.5% | $18,707 |

Aspirational target at > $250K: ≥ 9% (upside, not baseline).
Gross weighted APY across whitelist v0.4.5: **7.4%**.

---

## Paper Trading Timeline

```
2026-05-20  Paper trading starts (Day 0)
2026-05-22  Day 2 — current (Sprint v1.6)
2026-07-09  Day 50 — paper duration criterion 1 becomes PASS
2026-07-15  Go-live decision date — Owner reviews all 11 criteria
            → if READY: activate.py flow with manual "I CONFIRM LIVE TRADING"
            → if NOT_READY: extend paper trading; set new review date
```

---

*CLAUDE.md is automatically loaded by Claude Code CLI into every conversation.*
*Update the "Current Status" table after each sprint.*
*Last updated: 2026-05-22 (Sprint v1.6)*

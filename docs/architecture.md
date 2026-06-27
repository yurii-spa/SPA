# SPA System Architecture

**Version:** v0.16 (paper trading phase)  
**Status:** Active paper trading since 2026-05-20  
**Go-live target:** 2026-07-15

---

## 1. Overview

SPA (Smart Passive Aggregator) is a DeFi yield management system that monitors APY across a whitelist of 7 Ethereum protocols, allocates a virtual $100K portfolio using a deterministic risk policy, and publishes results to a GitHub Pages dashboard. All decisions run in a Python backend orchestrated by GitHub Actions.

The system has three hard constraints embedded in its design:

1. **Paper trading hard block** — no real capital can be deployed during the 8-week paper phase.
2. **LLM forbidden for risk/execution** — all risk checks and trade execution use deterministic code only.
3. **Risk Policy is immutable by agents** — a `RiskPolicy.approved=False` result cannot be overridden by any agent.

---

## 2. Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL DATA                                │
│                                                                     │
│   DeFiLlama API  →  APY, TVL for 7 whitelisted pools               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP (every 4h, --fetch flag)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PYTHON BACKEND (spa_core/)                      │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  GitHub Actions  (spa-run.yml, cron: 0 */4 * * *)           │   │
│  │                                                             │   │
│  │   1. export_data.py --fetch                                 │   │
│  │       ├── DeFiLlamaFetcher  → SQLite (spa.db)               │   │
│  │       ├── CEOAgent          → reads MessageBus              │   │
│  │       │    ├── MonitoringAgent  → publishes HEALTH_ALERT    │   │
│  │       │    ├── StrategyAgent   → publishes STRATEGY_SIGNAL  │   │
│  │       │    └── CEOAgent        → publishes TRADE_DECISION   │   │
│  │       ├── PaperTrader       → executes paper positions      │   │
│  │       │    └── RiskPolicy   → mandatory pre-trade check     │   │
│  │       ├── ReplayEngine      → computes backtest metrics     │   │
│  │       ├── GoLiveChecklist   → evaluates 8 go-live criteria  │   │
│  │       ├── Alerts            → Telegram / email dispatch     │   │
│  │       └── ReportAgent       → writes all data/*.json        │   │
│  │                                                             │   │
│  │   2. git add data/*.json spa.db && git commit && git push   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  FastAPI server (optional, localhost:8765)                    │  │
│  │   GET /api/status   GET /api/risk   POST /api/chat           │  │
│  │   GET /api/backtest/*   GET /api/events   WS /ws/agents      │  │
│  └──────────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ git push → data/*.json committed
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  CLOUDFLARE PAGES (earn-defi.com)                   │
│                                                                     │
│   Astro site (landing/, deploy-landing.yml)                        │
│   /dashboard  ←  DashboardLive.jsx island, polls api.earn-defi.com │
│                  (the SINGLE canonical dashboard, real-time ~15s)  │
└─────────────────────────────────────────────────────────────────────┘
```

> **Note (2026-06-28):** the legacy GitHub Pages dashboard (root `index.html`,
> `deploy-pages.yml`, `spa_frontend/` React source) has been **removed**. The single
> canonical dashboard is now `earn-defi.com/dashboard` (Astro page, real-time via the
> live API). `deploy-landing.yml` is the only remaining frontend deploy.

**Data flow summary:**
1. GitHub Actions triggers `export_data.py` every 4 hours.
2. `DeFiLlamaFetcher` fetches live APY/TVL and stores in SQLite.
3. Agents run their decision cycle via the `MessageBus`.
4. `PaperTrader` executes approved allocations (paper only).
5. All output is serialised to `data/*.json`.
6. A bot commit pushes the updated JSON files to the repo.
7. GitHub Pages serves the static files; `index.html` reads them.
8. If the user runs the local FastAPI server, the dashboard switches to live API mode.

---

## 3. Module Structure

```
spa_core/
├── agents/
│   ├── ceo_agent.py         # Orchestrator — final decision maker
│   ├── strategy_agent.py    # Generates STRATEGY_SIGNAL recommendations
│   ├── monitoring_agent.py  # Publishes HEALTH_ALERT from risk state
│   ├── data_agent.py        # Reads market data from DB
│   ├── chat_handler.py      # Routes /api/chat to the right agent
│   ├── decision_logger.py   # Append-only audit log
│   ├── llm_agent.py         # Claude API wrapper (optional)
│   └── base.py              # BaseAgent with MessageBus integration
├── api/
│   ├── server.py            # FastAPI app (all endpoints)
│   └── agent_broadcaster.py # WebSocket fan-out
├── backtesting/
│   ├── replay.py            # ReplayEngine: real/synthetic equity curve
│   └── scenario_runner.py   # compare_scenarios() for /api/backtest/compare
├── data_pipeline/
│   └── defillama_fetcher.py # DeFiLlama HTTP client + Pendle PT support
├── database/
│   └── init_db.py           # SQLite schema init, connection helper
├── golive/
│   └── checklist.py         # 8-criterion go-live gate evaluation
├── message_bus/
│   ├── bus.py               # In-process pub/sub with SQLite persistence
│   └── topics.py            # Topic enum: MARKET_DATA, HEALTH_ALERT, etc.
├── optimization/            # Mean-variance optimiser
├── paper_trading/
│   ├── engine.py            # PaperTrader: open/close/rebalance positions
│   ├── strategies.py        # auto_allocate() strategy logic
│   └── pendle_strategy.py   # Pendle PT position builder
├── reports/                 # PDF report generator
├── risk/
│   ├── policy.py            # RiskPolicy (deterministic, LLM-free)
│   └── versions/            # Snapshotted historical policy versions
├── alerts/
│   ├── telegram_sender.py   # Telegram Bot API
│   └── email_sender.py      # SMTP email alerts
└── export_data.py           # Entry point: orchestrates one export cycle
```

---

## 4. Agent Hierarchy

Agents communicate via a `MessageBus` (pub/sub with SQLite-backed persistence). Each agent only reads its input topics and writes its output topics — no direct agent-to-agent calls.

```
                    ┌─────────────────────┐
                    │     CEOAgent         │
                    │  (final decision)    │
                    │                     │
                    │  reads:             │
                    │    HEALTH_ALERT     │
                    │    STRATEGY_SIGNAL  │
                    │  writes:            │
                    │    TRADE_DECISION   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
   ┌──────────────────┐  ┌────────────┐  ┌─────────────────┐
   │  MonitoringAgent │  │StrategyAgent│  │    DataAgent    │
   │                  │  │            │  │                 │
   │  reads:          │  │ reads:     │  │ reads:          │
   │    MARKET_DATA   │  │ MARKET_DATA│  │  (DB directly)  │
   │  writes:         │  │ writes:    │  │ writes:         │
   │    HEALTH_ALERT  │  │ STRATEGY_  │  │  MARKET_DATA    │
   │                  │  │   SIGNAL   │  │                 │
   └──────────────────┘  └────────────┘  └─────────────────┘
```

**CEOAgent** is the only agent that can publish `TRADE_DECISION`. It does not bypass `RiskPolicy` — the final check happens inside `PaperTrader.open_position()` which the engine calls when processing each `TRADE_DECISION`.

**LLM usage:** `StrategyAgent` and `CEOAgent` can optionally use Claude Sonnet 4.6 for reasoning (when `ANTHROPIC_API_KEY` is set). `RiskPolicy`, `MonitoringAgent`, and `PaperTrader` are always deterministic.

---

## 5. Risk Policy Governance Flow

The `RiskPolicy` (`spa_core/risk/policy.py`) is the single source of truth for all capital-safety rules. It is deterministic, LLM-free, and cannot be overridden by any agent.

```
  Propose change
        │
        ▼
  ┌──────────────────────────────┐
  │  1. Write ADR                │
  │     docs/adr/ADR_XXX_*.md   │
  │     Describe: what changes,  │
  │     why, risk analysis       │
  └──────────────┬───────────────┘
                 │
                 ▼
  ┌──────────────────────────────┐
  │  2. Owner approval           │
  │     (Yurii reviews ADR)      │
  └──────────────┬───────────────┘
                 │ Approved
                 ▼
  ┌──────────────────────────────┐
  │  3. Snapshot current policy  │
  │     spa_core/risk/versions/  │
  │     vX_Y_<name>.py           │
  │     (enables rollback)       │
  └──────────────┬───────────────┘
                 │
                 ▼
  ┌──────────────────────────────┐
  │  4. Paper test ≥ 2 weeks     │
  │     New policy runs against  │
  │     paper portfolio; must    │
  │     not breach its own rules │
  └──────────────┬───────────────┘
                 │ No violations
                 ▼
  ┌──────────────────────────────┐
  │  5. Owner sign-off → merge   │
  └──────────────────────────────┘
```

**Rollback:** Load `RiskConfig` from the appropriate versioned file in `spa_core/risk/versions/`.

**Active version:** v1.0 (2026-05-20). Key parameters:
- T1 protocols: max 40% concentration per protocol
- T2 protocols: max 20% per protocol, max 35% total
- Kill switch: 5% portfolio drawdown halts all new positions
- Min TVL: $5M (safety floor for pool liquidity)
- APY range: 1%–30% (outside this range = no entry)

---

## 6. Security Model

### Paper trading hard block

`PaperTrader` is the only execution engine. It maintains a virtual balance in SQLite — no wallet connections, no on-chain calls. The `wallet.py` module (v2.0 scaffold) is not imported during the paper phase.

### LLM forbidden for risk/execution agents

`RiskPolicy`, `MonitoringAgent`, and `PaperTrader` contain no LLM calls. They import no `llm_agent.py`. LLM is permitted only in `StrategyAgent` and `CEOAgent` for reasoning/summarisation, never for final numeric decisions or policy checks.

### Wallet activation guard (v2.0)

When real capital deployment begins (2026-07-15), a `PreExecutionSafety` pipeline gates every transaction through 8 sequential blocking checks before any web3 call. No check can be skipped. See `docs/v2_architecture.md` for the full pipeline.

### GitHub Actions secret isolation

| Secret | Used by | Never in |
|---|---|---|
| `ANTHROPIC_API_KEY` | LLM agent reasoning (optional) | Risk/execution code |
| `SPA_TELEGRAM_TOKEN` | Alert dispatch | Committed code |
| `SPA_TELEGRAM_CHAT_ID` | Alert dispatch | Committed code |
| `SPA_ALERT_EMAIL` | Email alerts | Committed code |

The GitHub Actions runner has write access to the repo (for data commits) but no access to any wallet or on-chain infrastructure during the paper phase.

### CORS policy

The FastAPI server allows requests from `localhost:*` (development) and `earn-defi.com` (production dashboard, via the `api.earn-defi.com` Cloudflare Tunnel). No wildcard origin. Credentials are not allowed.

---

## 7. Database

**Engine:** SQLite (`spa_core/database/spa.db`)  
**Init:** `spa_core/database/init_db.py` — idempotent schema creation

Key tables:
- `protocols` — whitelisted pools with tier and active flag
- `apy_snapshots` — time-series APY/TVL from DeFiLlama
- `positions` — paper trading positions (open/closed)
- `trades` — trade history
- `strategy_states` — per-cycle portfolio snapshots
- `message_bus` — pub/sub message queue

The DB file is committed to git by the GitHub Actions bot after each export cycle. This means the full paper trading history is version-controlled alongside the code.

---

## 8. Dashboard (earn-defi.com/dashboard)

The single canonical dashboard is an Astro page — `landing/src/pages/dashboard.astro` — served by Cloudflare Pages at `earn-defi.com/dashboard` (deployed by `deploy-landing.yml`). It renders inside the unified site `<Layout>` (canonical header/footer/design tokens), so it is a first-class page of the site, not a separate app.

The live, real-time surface is the `<DashboardLive />` React island (`landing/src/components/DashboardLive.jsx`, `client:load`), which polls `api.earn-defi.com` every ~15s (SSOT facts + fleet + status + go-live) and renders an honest **LIVE** / **"snapshot — live API offline"** state. No fabricated numbers when the API is offline. Bilingual (EN|RU).

> The legacy single-file `index.html` dashboard served by GitHub Pages (`yurii-spa.github.io`), its `deploy-pages.yml` workflow, and its `spa_frontend/` React source were **removed on 2026-06-28**. Their committed `data/*.json` static fallback is no longer read by any consumer.

---

## 9. Related Documents

- `docs/v2_architecture.md` — v2.0 real-capital execution design (Gnosis Safe, Tenderly, Flashbots)
- `docs/api_reference.md` — full FastAPI endpoint documentation
- `docs/data_schema.md` — JSON file schemas
- `docs/paper_trading_guide.md` — paper trading operations guide
- `docs/emergency.md` — kill switch and emergency recovery procedures
- `docs/adr/` — Architecture Decision Records
- `spa_core/risk/policy.py` — RiskPolicy source (authoritative)

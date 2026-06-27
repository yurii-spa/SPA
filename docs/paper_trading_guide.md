# Paper Trading Guide

**Started:** 2026-05-20  
**Duration:** 8 weeks minimum (56 days)  
**Capital:** $100,000 virtual USDC  
**Decision date:** 2026-07-15  
**Dashboard:** https://earn-defi.com/dashboard (single canonical live dashboard)

Paper trading is the mandatory validation phase before any real capital is deployed. The system runs fully automated — you observe, it trades.

---

## What runs every 4 hours

GitHub Actions triggers `spa_core/export_data.py` at `0 */4 * * *` UTC (00:00, 04:00, 08:00, 12:00, 16:00, 20:00).

Each cycle does the following in order:

1. **Fetch APY data** — `DeFiLlamaFetcher` queries DeFiLlama for current APY and TVL across all 7 whitelisted pools. Results are stored in SQLite.

2. **Agent decision cycle** — agents run via the `MessageBus`:
   - `DataAgent` reads new APY snapshots from the DB and publishes `MARKET_DATA`
   - `MonitoringAgent` evaluates portfolio health against risk thresholds and publishes `HEALTH_ALERT` if violations exist
   - `StrategyAgent` analyses `MARKET_DATA` and recommends allocations, publishing `STRATEGY_SIGNAL`
   - `CEOAgent` reads both `HEALTH_ALERT` and `STRATEGY_SIGNAL`, approves or rejects each recommendation, and publishes `TRADE_DECISION`

3. **Paper execution** — `PaperTrader` processes each `TRADE_DECISION`:
   - Calls `RiskPolicy.check_new_position()` — if this returns `approved=False`, the trade is blocked unconditionally
   - If approved, updates the virtual position in SQLite

4. **Backtest** — `ReplayEngine` recomputes the equity curve from `pnl_history`

5. **Go-live check** — `GoLiveChecklist` evaluates all 8 criteria and writes `golive_readiness.json`

6. **Alerts** — Telegram and/or email notifications are dispatched (risk alerts immediately; digest once per day)

7. **Export** — all output is serialised to `data/*.json`

8. **Git commit** — the bot commits and pushes the updated JSON files to the repo, which triggers a GitHub Pages update

The full cycle takes approximately 60–90 seconds. If a step fails, the job continues (using `continue-on-error: true` for tests) and the remaining steps still run.

---

## How positions are opened and closed

### Opening a position

Positions are opened by `auto_allocate()` in `spa_core/paper_trading/strategies.py`. The allocator:

1. Fetches the current pool list sorted by risk-adjusted APY
2. For each candidate pool, calls `RiskPolicy.check_new_position()` with the proposed amount
3. If approved, calls `PaperTrader.open_position(protocol_key, amount_usd, current_apy, tvl_usd)`
4. The position is recorded in the `positions` table with a timestamp and entry APY

The initial allocation targets ~95% deployment across 4–6 protocols, keeping a 5% cash buffer (configurable in `RiskConfig`).

### Closing a position

Positions are closed when:
- A protocol's APY falls below `RiskConfig.min_apy_for_new_position` (1%)
- A position's individual drawdown exceeds `RiskConfig.max_single_position_drawdown` (3%)
- The overall portfolio drawdown hits `RiskConfig.max_drawdown_stop` (5% kill switch — closes all positions)
- A better opportunity exists and rebalancing is triggered

Use `PaperTrader` directly from the CLI for manual operations:

```bash
cd spa_core
# Open a position manually
python -m paper_trading.engine --open aave-v3-usdc-ethereum --amount 40000 --apy 4.23 --tvl 138000000

# Close a position
python -m paper_trading.engine --close maple-usdc-ethereum

# Check current status
python -m paper_trading.engine --status

# Trigger rebalance
python -m paper_trading.engine --rebalance
```

### Paper trading safeguards

The `PaperTrader` has no wallet connection — it cannot touch real funds. The class only reads from and writes to SQLite. The `wallet.py` module (v2.0 real execution) is never imported during the paper phase.

---

## How to read the dashboard

Open https://earn-defi.com/dashboard (the single canonical live dashboard, real-time from `api.earn-defi.com`).

### Portfolio panel

Shows the current NAV, deployed capital, cash buffer, and cumulative PnL since paper trading began. All values are virtual.

**What to watch:**
- `PnL %` — cumulative return since 2026-05-20; target is positive after 2 weeks
- `Cash %` — should stay between 3–10%; below 3% triggers an alert
- `Drawdown %` — distance from the portfolio's peak value; kill switch fires at 5%

### Positions panel

Lists every open position with protocol, asset, deployed amount, current APY, and unrealised PnL (computed as `amount × apy_at_entry × days_held / 365`).

### Risk panel

Shows the current `risk_alerts.json` output:
- 🟢 Green = no violations
- 🟡 Yellow = warnings (non-blocking)
- 🔴 Red = critical violation (new positions blocked)

### Backtest panel

Displays the synthetic 90-day backtest metrics (Sharpe, max drawdown, annualised return). These are computed from a mean-reverting APY simulation, not from the live paper trading history. The metrics will switch to real history after ~14 days of trading data.

### Go-live readiness panel

Shows the 8-criterion gate:

| Criterion | Threshold | Notes |
|---|---|---|
| Paper Duration | ≥ 50 days | Passes on 2026-07-09 |
| PnL Positive | > $0 | After first allocation |
| No Critical Alerts | 0 critical | Cleared immediately once data flows |
| Strategy Sharpe | ≥ 1.0 | Computed from real history |
| Policy v1.0 active | Must match | No unapproved policy changes |
| Max Drawdown | < 3% | Kill switch at 5% |
| Diversification | ≥ 2 protocols | Clears after first allocation |
| Data Freshness | < 6h old | Clears after first GitHub Actions run |

The verdict changes from `NOT_READY` → `ALMOST_READY` → `READY` as criteria accumulate passes.

---

## Go-live criteria and timeline

### Day-by-day milestones

| Timeframe | Milestone |
|---|---|
| Day 1 (2026-05-20) | Paper trading starts; portfolio at $100K cash |
| Day 2–3 | First allocation expected (after first DeFiLlama fetch with live data) |
| Day 7 | Early PnL and Sharpe signal available |
| Day 14 | Backtest switches from synthetic to real history |
| Day 50 (2026-07-09) | Paper Duration criterion passes |
| Day 56 (2026-07-15) | **Decision date** — owner reviews all 8 criteria |

### Decision logic on 2026-07-15

| Verdict | Outcome |
|---|---|
| `READY` (all 8 pass) | Proceed to v2.0 Seed Deployment ($1,000 to Aave V3 only) |
| `ALMOST_READY` (6–7 pass) | Owner discretion — may extend by 2 weeks or accept limited deployment |
| `NOT_READY` (<6 pass) | Extend paper trading; set new review date |

No automatic transition — the owner must take an explicit action to activate `wallet.py` and the real execution pipeline. See `docs/v2_architecture.md` and `docs/v2_activation_checklist.md`.

### After go-live: phased capital deployment

| Phase | Capital | Condition |
|---|---|---|
| Seed | $1,000 | Aave V3 only, first 30 days live |
| Phase 1 | $2,000 | PnL > 0, no issues after seed |
| Phase 2 | $5,000 | Sharpe > 1.0, drawdown < 2% for 30 days |
| Full | Per strategy passport | All phase criteria met |

---

## Setting up Telegram alerts

Telegram alerts are the primary notification channel during paper trading. Full setup is in `docs/setup_telegram_alerts.md`. Quick summary:

**Step 1 — Create a bot**
1. Open Telegram, message **@BotFather**
2. Send `/newbot`, choose a name (e.g., `SPA Alerts`) and username ending in `bot`
3. Copy the token: `123456789:ABC-DEF...`

**Step 2 — Get your chat_id**
1. Send any message to your new bot
2. Visit `https://api.telegram.org/bot{TOKEN}/getUpdates`
3. Find `"chat": {"id": 123456789}` — that number is your chat_id

**Step 3 — Add GitHub Secrets**

Go to your repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret name | Value |
|---|---|
| `SPA_TELEGRAM_TOKEN` | Your bot token |
| `SPA_TELEGRAM_CHAT_ID` | Your numeric chat_id |

**Step 4 — Verify**

Trigger a manual run: Actions → `SPA — Run & Export` → Run workflow. You should receive a `📊 SPA 4h Report` message within seconds.

### What the bot sends

**Immediate (every 4h run if triggered):** risk alerts when any threshold is breached — concentration >45%, drawdown >2%, APY drop >1pp, cash <3%.

**Daily digest (first run of each UTC day):** full portfolio summary with APY vs target, positions, Sharpe, drawdown, and go-live status.

**4h cycle summary (every run):** compact snapshot — NAV, PnL%, weighted APY, position list, alert count.

**Weekly go-live update (Monday):** full readiness verdict with criterion-by-criterion breakdown.

---

## Running locally

To run the export cycle manually (without waiting for the GitHub Actions schedule):

```bash
cd spa_core
# Export only (uses cached DB data):
python export_data.py

# Fetch fresh DeFiLlama data first, then export:
python export_data.py --fetch
```

To start the live API server:

```bash
python run_server.py
# → http://localhost:8765/docs
```

The dashboard at `index.html` (opened locally) will auto-detect the server and switch to live mode.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `golive_readiness.json` shows `NOT_READY` with 8/8 failing | No trades executed yet | Trigger manual run with `--fetch` |
| `protocols.json` has null APY values | DeFiLlama fetch not run | Add `--fetch` flag or run with `FETCH=true` |
| No Telegram messages | Secrets not set | Check GitHub Secrets spelling |
| Dashboard shows stale data | Actions job failed | Check Actions tab for errors |
| Position didn't open | Risk Policy rejected | Check `decision_log.json` for rejection reason |
| `spa.db` missing | First run | `init_database()` creates it automatically on next run |

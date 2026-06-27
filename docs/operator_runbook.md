> ⚠️ **SUPERSEDED — SEVERELY STALE, DO NOT FOLLOW.** This document describes a
> long-gone GitHub-Actions-every-4-hours architecture (11 go-live criteria,
> `ANTHROPIC_API_KEY` secret, `push_workflow.command`) that no longer matches
> reality (SPA now runs on local launchd agents on the Mac Mini). For recovery,
> use the **canonical** **[`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md)**.
> Retained for history only.

---

# SPA Operator Runbook

**System:** Smart Passive Aggregator (SPA) — DeFi Yield Management, Paper Trading  
**Started:** 2026-05-20 | **Go-Live Decision Date:** 2026-07-15 | **Version:** v1.5

This runbook tells you everything you need to manage SPA day-to-day. No coding knowledge required. It covers setup, daily monitoring, incident response, and the go-live decision process.

---

## 1. Day 1 Setup Checklist (one-time)

### Step 1 — Push the code to GitHub

Double-click the file `push_workflow.command` in the project folder. This opens a Terminal window and pushes all source files to the GitHub repo (`yurii-spa/SPA`). The script runs automatically — wait for it to finish and show "Push complete."

If you need to push code changes later, double-click `push_workflow.command` again.

### Step 2 — Set GitHub Secrets

Secrets are environment variables that GitHub Actions uses to send your Telegram alerts. You set them once and never touch them again.

Go to: `https://github.com/yurii-spa/SPA` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | What it is | How to get it |
|---|---|---|
| `SPA_TELEGRAM_TOKEN` | Your Telegram bot's API key | See Step 3 |
| `SPA_TELEGRAM_CHAT_ID` | Your personal Telegram chat ID | See Step 3 |
| `SPA_ALERT_EMAIL` | Gmail address to send alerts from | Your Gmail address |
| `SPA_ALERT_PASSWORD` | Gmail app password (not your login password) | Gmail → Security → App passwords |
| `SPA_NOTIFY_EMAIL` | Email address to receive alerts | Where you want alerts sent |
| `ANTHROPIC_API_KEY` | Anthropic API key for LLM agents | console.anthropic.com |

Email alerts are optional — Telegram is the primary notification channel.

### Step 3 — Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts (pick any name/username)
3. BotFather gives you a token like `7123456789:AAFxxx...` — this is your `SPA_TELEGRAM_TOKEN`
4. Start a chat with your new bot (click Start)
5. Open this URL in a browser (replace `TOKEN` with yours):  
   `https://api.telegram.org/botTOKEN/getUpdates`
6. Send any message to your bot, then reload the URL
7. Find `"chat":{"id":123456789}` in the response — that number is your `SPA_TELEGRAM_CHAT_ID`

### Step 4 — Enable GitHub Actions

Go to `https://github.com/yurii-spa/SPA` → **Actions** tab → click **"I understand my workflows, go ahead and enable them"** if prompted.

### Step 5 — First manual run

Go to **Actions** tab → click **"SPA — Run & Export"** in the left sidebar → click **"Run workflow"** → **"Run workflow"** (green button).

Watch the run complete (takes ~90 seconds). When it turns green, check that new files appeared under the `data/` folder in the repo — you should see `status.json`, `risk_alerts.json`, `golive_readiness.json`, and others.

**From this point the system runs automatically every 4 hours.** You don't need to do anything.

### Step 6 — Verify Telegram is working

After the first run completes, you should receive a Telegram message from your bot. If not, check Section 6 ("Telegram not sending") in this runbook.

---

## 2. Daily Monitoring (2 minutes/day)

### What to expect in Telegram

The system sends two types of Telegram messages:

**Daily digest** — sent once per day (triggered by the first run each UTC calendar day). It looks like this:

```
📊 SPA Daily Report — 2026-05-22

💰 Portfolio: $100,000 (+0.02% / +$20)
📈 APY (weighted): 4.2%  Target: 7.30%
🎯 Gap: -3.10%

📍 Positions:
  Aave V3                  $35,000  3.8% APY
  Compound V3              $30,000  4.1% APY
  Morpho                   $20,000  4.8% APY
  Cash buffer              $15,000  (15.0%)

⚠️  Risk Alerts: 0 critical
📊 Sharpe: 1.85  MaxDD: 0.4%

⏱  Paper trading: Day 2/56
🔴 Go-live: NOT_READY (4/11 criteria)
```

**Risk alerts** — sent immediately when a threshold is crossed (concentration, drawdown, APY drop). These are urgent and appear any time of day.

### How to read the dashboard

Open `https://yurii-spa.github.io/SPA/` in your browser (or open `index.html` locally). The key numbers to check:

- **APY (weighted):** should trend toward 7.3% over the 8 weeks. Currently ~4.2% — the gap closes as Pendle positions accumulate.
- **Max drawdown:** should stay below 3%. Anything above 4% is a problem.
- **Sharpe ratio:** target ≥ 2.0 by go-live. A Sharpe of 2.0 means consistent returns with low volatility.
- **Go-live criteria count:** rises from 4/11 toward 11/11 as the paper trading period progresses.
- **Day counter:** Day X/56 — the 8-week test ends around Day 50 when the duration criterion passes.

### What "normal" looks like

- Small positive PnL each day (a few dollars, sometimes zero)
- No Telegram risk alerts
- GitHub Actions runs show green checkmarks every 4 hours
- APY slowly drifting upward as Pendle PT pools accumulate yield
- Go-live criteria count increasing week-by-week

---

## 3. Weekly Review (15 minutes/week)

Once a week, open a Terminal in the project folder (`/Users/yuriikulieshov/Documents/SPA_Claude`) and run these checks:

### Check go-live readiness

```bash
python -m spa_core.golive.daily_check
```

This prints a report card showing all 11 criteria and their current status. Look for any `FAIL` or `WARN` items and compare to last week.

### Run the strategy tournament

```bash
python -m spa_core.backtesting.tournament
```

This compares `v1_passive` (conservative, T1-only) vs `v2_aggressive` (includes T2 protocols). For go-live, `v1_passive` must be winning or tied. A loss here means the conservative strategy is underperforming — not a crisis, just something to monitor.

### Review the Analytics tab in the dashboard

Open the dashboard and look at:
- **Equity curve:** should slope gently upward. A flat line means no yield is accruing (investigate). A sharp dip means a risk event occurred.
- **Sharpe trend:** should be rising. If it's falling, volatility is increasing relative to returns.
- **APY gap tracker:** the gap between current APY (~4.2%) and the 7.3% target. The two main levers to close it:
  - **Sky/sUSDS:** currently at 0% allocation pending the GSM 48-hour timelock confirmation. If confirmed, it moves to T1 at 30% allocation automatically.
  - **Pendle PT:** newly integrated, ramps up over the 8-week period as more PT positions accumulate.

---

## 4. Sky/sUSDS Upgrade (when GSM delay confirmed ≥ 48h)

Sky/sUSDS is currently on the Watch List at 0% allocation because the on-chain governance timelock (GSM Pause Delay) hasn't been confirmed at ≥ 48 hours yet.

**What you need to check on-chain:** The `DSPause.delay()` contract value must equal or exceed `172800` seconds (48 hours). You can check this on Etherscan by looking at the MakerDAO DSPause contract.

**What happens automatically:** The `sky_monitor.py` script runs on every GitHub Actions cycle and checks this value via three fallback RPC endpoints. When it detects `delay() ≥ 172800`, it updates `data/sky_status.json` with `"status": "ELIGIBLE"` and the allocation engine automatically moves Sky to 30% of the portfolio in the next run.

**What you need to do manually:** Nothing. The detection and reallocation are fully automatic.

**How to verify it happened:** After a run, check `data/sky_status.json` in the GitHub repo. Look for `"status": "ELIGIBLE"` and `"allocation_pct": 0.30`. The daily Telegram digest will also show Sky appearing in the Positions section.

---

## 5. Go-Live Decision Process

**Timeline:** The paper trading period started 2026-05-20. The go-live decision date is **2026-07-15** (Day 56).

### The 11 Go-Live Criteria

All 11 must show PASS before the activation script will proceed. Here's what each one means in plain English:

| # | Criterion | What it checks | Pass condition |
|---|---|---|---|
| 1 | Paper Duration | Enough time has passed | ≥ 50 days of paper trading |
| 2 | PnL Positive | The strategy is making money | Total virtual profit > $0 |
| 3 | No Critical Alerts | No active emergencies | Zero critical risk alerts |
| 4 | Strategy Sharpe | Risk-adjusted returns are good | Backtest Sharpe ratio ≥ 1.0 |
| 5 | Policy v1.0 | Risk rules haven't been changed | RiskConfig still on version v1.0 |
| 6 | Max Drawdown | Losses are contained | Portfolio drawdown < 3% |
| 7 | Diversification | Capital isn't too concentrated | ≥ 2 protocols, no single one > 45% |
| 8 | Data Freshness | The system is running | Last data export < 6 hours ago |
| 9 | Wallet Ready | Manual infrastructure setup | Gnosis Safe + hot wallet configured (manual) |
| 10 | Strategy Tournament | Conservative strategy is competitive | v1_passive winning or tied vs v2_aggressive |
| 11 | APY Gap | Returns are close to target | Current APY within 2 percentage points of 7.3% |

Criterion 9 (Wallet Ready) is always PENDING — it's a manual step that the system can't verify automatically. This alone doesn't block the READY verdict.

### Running the go-live check

```bash
python -m spa_core.golive.activate
```

This runs all 11 criteria checks and prints their status. If any criteria are not PASS, the script stops and tells you what's blocking activation.

### What activation looks like

If all 11 criteria pass, the script shows:

```
============================================================
  SPA GO-LIVE ACTIVATION — Phase 6
============================================================

[1/3] Checking all 11 go-live criteria…

  ✅  [PASS   ]  Paper Duration
  ✅  [PASS   ]  PnL Positive
  ✅  [PASS   ]  No Critical Alerts
  ... (all 11 pass)

Result: 11/11 criteria PASS — Verdict: READY

[2/3] Owner confirmation required.

⚠️  WARNING: After activation, SPAWallet.execute() will be able to
    submit REAL on-chain transactions that move REAL capital.

    Type exactly:  I CONFIRM LIVE TRADING

Confirmation: 
```

You must type `I CONFIRM LIVE TRADING` exactly (case-sensitive, no extra spaces).

If you type it correctly, the script writes `data/activation_record.json` and prints `✅ LIVE MODE ACTIVATED`.

### What happens after activation

The activation record is a JSON file that unlocks the LIVE mode guard in the wallet code. **However — this does NOT immediately move real money.** The wallet's `execute()` function still needs real protocol SDK integrations (Aave SDK, Compound SDK, etc.) which are not yet implemented. See Section 9 for the full v2.0 upgrade path.

To re-lock the system: delete `data/activation_record.json`.

**Who approves:** You (the owner) must type the confirmation phrase interactively. No automated script or agent can do this for you — it's an intentional human-in-the-loop gate.

---

## 6. Incident Response

### "No data in dashboard / dashboard looks frozen"

The dashboard reads from the `data/*.json` files in the GitHub repo. If they're not updating, the GitHub Actions job is not running.

1. Go to `https://github.com/yurii-spa/SPA/actions` and check the last run
2. If it shows a red ✗, click it and read the log — look for `ERROR` lines
3. If it shows no recent runs, the schedule may have been disabled — re-enable Actions in repo Settings
4. **Quick fix:** click **Run workflow** manually to force a run

---

### "Risk alert: concentration > 45%"

**What it means:** A single protocol has more than 45% of the total portfolio. This violates the diversification limit.

**What the system does automatically:** On the next 4-hour cycle, `auto_allocate()` rebalances positions. The overly-concentrated position is trimmed and capital is shifted to other protocols.

**When to act manually:** If the alert persists for 3+ consecutive cycles (12+ hours), the auto-rebalancer may be stuck. Open a Terminal and run:

```bash
python -m spa_core.golive.daily_check
```

Look at the Diversification criterion. If it still shows FAIL, check `data/status.json` → `positions` to see the current allocation manually.

---

### "Risk alert: daily PnL drop > 2%"

**What it means:** The portfolio lost more than $2,000 in a single day. In paper trading this is a virtual loss, but it signals a real protocol risk event.

**What to check:** Open `data/pnl_history.json` and find the entry for the affected day. Look at which positions were open. Then check `data/protocols.json` for any protocol with a sudden APY drop or TVL collapse.

**What the engine does:** The RiskPolicy `check_new_position()` gates all new allocations. If a protocol looks dangerous, new trades into it are blocked on the next cycle. Capital gradually shifts to safer protocols.

**When to intervene:** If you see a protocol on the whitelist that has had a public security incident (exploit, hack), note it for manual review. The whitelist is updated via the `spa_core/risk/policy.py` file — open it and change the relevant protocol status to `"Active": False`. Push the change to GitHub via `push_workflow.command`.

---

### "APY dropped below 5%"

**Likely cause:** One or more protocols have compressed their lending rates (common when DeFi borrowing demand drops).

**What to check:** Open `data/protocols.json` and look at the `current_apy` field for each protocol. Compare to previous days by looking at `data/pnl_history.json` for APY trends.

**What the engine does:** `auto_allocate()` ranks protocols by net APY every cycle. If a protocol's rate drops significantly, the strategy shifts capital to higher-yielding alternatives automatically on the next run.

**Note:** The current APY gap (~3.1 pp below the 7.3% target) is expected at this stage. It closes as Pendle PT positions mature and if Sky/sUSDS is confirmed eligible. This is not an alert condition.

---

### "GitHub Actions failing"

1. Go to `https://github.com/yurii-spa/SPA/actions`
2. Click the failed run → expand the failing step
3. Common causes and fixes:

| Error in log | Cause | Fix |
|---|---|---|
| `Connection timeout` or `HTTPError` | DeFiLlama API temporarily unavailable | Retry logic handles it — re-run workflow |
| `sky_monitor` timeout | Ethereum RPC endpoints overloaded | Retry logic handles it — re-run workflow |
| `ModuleNotFoundError` | Python dependency issue | Check `spa_core/requirements.txt` |
| `SPA_TELEGRAM_TOKEN not set` | Secret missing | Re-add the secret in repo Settings |

For any persistent failure, re-run the workflow manually. If it fails 3+ times in a row, open the log and read the full error message.

---

### "Telegram not sending"

**Step 1 — Verify secrets are set:**  
Go to `https://github.com/yurii-spa/SPA/settings/secrets/actions` and confirm `SPA_TELEGRAM_TOKEN` and `SPA_TELEGRAM_CHAT_ID` are listed (you can't see the values, just that they exist).

**Step 2 — Test locally:**  
Open a Terminal in the project folder and run:

```bash
SPA_TELEGRAM_TOKEN=your_token SPA_TELEGRAM_CHAT_ID=your_chat_id \
  python -c "
import sys; sys.path.insert(0, 'spa_core')
from alerts.telegram_sender import TelegramSender
s = TelegramSender()
print(s.send('SPA test message'))
"
```

Replace `your_token` and `your_chat_id` with actual values. If it prints `True`, Telegram is working. If it prints `False` or raises an error, the token or chat ID is wrong — re-create the bot in @BotFather.

**Step 3 — Check bot was started:**  
Open Telegram, find your bot, and make sure you pressed Start. Bots can't send messages to users who haven't started them.

---

## 7. Configuration Reference

Key constants you might want to adjust. Change them in the file listed, then push to GitHub.

| Parameter | File | Default | What it controls |
|---|---|---|---|
| `TARGET_APY` | `spa_core/alerts/daily_report.py` | `7.30` | The APY target used in the daily digest gap calculation |
| `PAPER_TOTAL_DAYS` | `spa_core/alerts/daily_report.py` | `56` | 8-week paper trading period length |
| `PAPER_START_DATE` | `spa_core/golive/checklist.py` | `2026-05-20` | When paper trading started (determines duration criterion) |
| `GO_LIVE_DATE` | `spa_core/golive/checklist.py` | `2026-07-15` | Target go-live date (shown in reports) |
| `MIN_PAPER_DAYS` | `spa_core/golive/checklist.py` | `50` | Minimum days before duration criterion passes |
| `APY_GAP_MAX` | `spa_core/golive/checklist.py` | `2.0` | Max allowed APY deviation from target (pp) |
| `CONCENTRATION_CRITICAL_PCT` | `spa_core/alerts/risk_monitor.py` | `45.0` | Single-protocol limit before critical alert fires |
| `CONCENTRATION_WARNING_PCT` | `spa_core/alerts/risk_monitor.py` | `35.0` | Single-protocol limit before warning alert fires |
| `DAILY_DRAWDOWN_PCT` | `spa_core/alerts/risk_monitor.py` | `2.0` | Single-day loss (%) that triggers a critical alert |
| `APY_DROP_THRESHOLD` | `spa_core/alerts/risk_monitor.py` | `1.0` | APY drop (pp vs prior run) that triggers a warning alert |
| `CASH_BUFFER_MIN_PCT` | `spa_core/alerts/risk_monitor.py` | `3.0` | Minimum cash buffer; below this triggers a warning |
| Cron schedule | `.github/workflows/spa-run.yml` | `0 */4 * * *` | How often the system runs (every 4 hours) |

**Risk policy limits** (in `spa_core/risk/policy.py` → `RiskConfig`):
- `max_single_protocol_pct`: maximum allocation to any single protocol (default 45%)
- `max_t2_allocation_pct`: maximum total allocation to Tier 2 protocols combined
- `version`: must remain `"v1.0"` to pass go-live criterion 5

Do not change `RiskConfig.version` unless you've reviewed the full risk policy and intend to update it. Changing it will make criterion 5 show WARN.

---

## 8. File Structure Reference

```
SPA_Claude/
├── index.html                    Dashboard (open in browser or served via GitHub Pages)
├── README.md                     Project overview
├── DEV_STRATEGY_v1.0.md          Development strategy and phase plan
├── push_workflow.command         Double-click to push all files to GitHub
├── trigger_workflow.command      Double-click to trigger a GitHub Actions run
├── data/                         Live output files (updated every 4h by GitHub Actions)
│   ├── status.json               Current portfolio, positions, strategy state
│   ├── risk_alerts.json          Active risk alerts
│   ├── pnl_history.json          Daily PnL snapshots
│   ├── golive_readiness.json     All 11 criteria + verdict
│   ├── backtest_results.json     Backtest metrics (Sharpe, drawdown)
│   ├── tournament_results.json   v1_passive vs v2_aggressive comparison
│   ├── advanced_analytics.json   Calmar ratio, Sortino, rolling metrics
│   ├── sky_status.json           Sky/sUSDS GSM check result
│   └── activation_record.json   Written by activate.py when go-live is confirmed
├── spa_core/                     All Python source code
│   ├── export_data.py            Main script run by GitHub Actions (all 20 sections)
│   ├── paper_trading/            Paper trading engine and strategies
│   ├── risk/                     Risk policy (RiskConfig, circuit breakers)
│   ├── data_pipeline/            DeFiLlama fetcher, Sky monitor, Pendle fetcher
│   ├── alerts/                   Telegram sender, daily report, risk monitor
│   ├── golive/                   Go-live checklist, activate script, daily check
│   ├── backtesting/              Backtest engine, tournament, replay
│   ├── analytics/                Portfolio statistics (Sharpe, Sortino, etc.)
│   ├── agents/                   LLM agent stubs (CEO, Data, Strategy, Monitoring)
│   ├── execution/                Wallet scaffold (LIVE mode, safety checks)
│   └── tests/                   120+ automated tests
├── docs/                         Documentation
│   ├── operator_runbook.md       This file
│   ├── paper_trading_guide.md    Detailed paper trading guide
│   ├── setup_telegram_alerts.md  Telegram setup walkthrough
│   ├── emergency.md              Emergency procedures
│   └── v2_activation_checklist.md  Checklist for real capital deployment
└── .github/workflows/
    └── spa-run.yml               GitHub Actions schedule and job definition
```

---

## 9. Upgrade Path to v2.0 (Real Capital)

**Do not attempt with real capital until all 11 go-live criteria show PASS.**

### What's already built (ready now)

- The wallet scaffold (`spa_core/execution/wallet.py`) has a LIVE mode with a hard `NotImplementedError` guard that is unlocked only by `activation_record.json`
- Pre-execution safety checks (`spa_core/execution/safety_checks.py`) run before every transaction
- The go-live activation flow (`spa_core/golive/activate.py`) with owner confirmation
- Kill switch: `PreExecutionSafety.activate_kill_switch()` — halts all trades immediately
- Gnosis Safe integration scaffold in `docs/v2_activation_checklist.md`

### What needs to be added (v2.0 scope, ~3–4 weeks of development)

- **Protocol SDK integrations:** The actual on-chain deposit/withdraw calls for each protocol:
  - Aave V3 SDK (supply USDC, withdraw USDC)
  - Compound V3 SDK (supply USDC, withdraw USDC)
  - Morpho SDK
  - Yearn V3 SDK
  - Pendle SDK (buy/sell PT tokens)
  - Euler V2 SDK
- **Gnosis Safe signing:** Hot wallet signs transactions, Gnosis Safe executes them
- **Gas estimation:** Dynamic gas pricing before each transaction
- **PostgreSQL migration:** Replace SQLite with PostgreSQL for production durability
- **Security audit:** VPN-only API access, audit log review, private key verification

### Manual setup required before v2.0

See `docs/v2_activation_checklist.md` Section B for the complete wallet setup steps:
1. Create a Gnosis Safe at app.safe.global (use Ethereum mainnet)
2. Test it with a $10 transaction
3. Create a hot wallet in MetaMask (fund with ETH for gas, no USDC on it)
4. Add the hot wallet as a Safe delegate
5. Set `SAFE_ADDRESS` and `WALLET_ADDRESS` in GitHub Secrets
6. Verify: private key is NOT in any git commit history

### Estimated timeline

| Step | Duration |
|---|---|
| Protocol SDK integrations (6 protocols) | 2–3 weeks |
| Gnosis Safe signing integration | 1 week |
| Gas estimation + safety testing | 3–5 days |
| PostgreSQL migration | 3–5 days |
| Security audit | 1 week |
| **Total** | **~5–6 weeks after go-live decision** |

The 8-week paper trading period ends around 2026-07-09 (Day 50, when the duration criterion passes). The go-live decision meeting is 2026-07-15. If all criteria pass and you confirm activation, v2.0 development starts immediately after — earliest real capital deployment would be around **late August 2026**.

---

## 10. Enable GitHub Pages (one-time)

The dashboard auto-deploys to GitHub Pages after every paper trading run.

**Setup:**
1. Go to your repo → Settings → Pages
2. Source: GitHub Actions (not "Deploy from branch")  
3. Wait for the first deploy_pages workflow to run
4. Your dashboard URL: `https://yurii-spa.github.io/SPA/`

**After setup:**
- Every `SPA — Run & Export` completion triggers a dashboard redeploy
- Manual push to `index.html` or `data/` also triggers redeploy
- Access from any device — no local server needed

---

*Last updated: 2026-05-22 | System version: v1.5 | Paper trading day: 2/56*

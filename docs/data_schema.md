# SPA Data Schema

All files live in `data/` at the project root. They are written by `spa_core/export_data.py` on every GitHub Actions run (every 4 hours) and committed to the repo so GitHub Pages can serve them as static JSON.

The FastAPI server also reads these files as a fallback when the live `PaperTrader` DB is unavailable.

---

## status.json

**Purpose:** Master portfolio snapshot — the single source of truth for the dashboard's portfolio panel when the live API is not available.  
**Producer:** `spa_core/export_data.py` → `PaperTrader.get_status()`

### Schema

```json
{
  "timestamp": "2026-05-21T18:24:07.227356+00:00",
  "portfolio": {
    "total_capital_usd": 100000.0,
    "deployed_usd": 0,
    "cash_usd": 100000.0,
    "cash_pct": 1.0,
    "total_pnl_usd": 0,
    "total_drawdown_pct": 0.0
  },
  "positions": [],
  "risk": {
    "health_approved": true,
    "violations": [],
    "warnings": [],
    "var_usd": 0.0,
    "var_pct": 0.0,
    "var_breach": false
  },
  "paper_trading": {
    "days_elapsed": 0,
    "weeks_elapsed": 0.0,
    "min_weeks_required": 8,
    "go_live_ready": false,
    "first_trade": null
  },
  "strategy": {
    "id": 4,
    "strategy_id": "paper-v1",
    "timestamp": "2026-05-21 06:39:39",
    "total_capital_usd": 100000.0,
    "deployed_capital_usd": 0.0,
    "cash_usd": 100000.0,
    "total_pnl_usd": 0.0,
    "total_pnl_pct": 0.0,
    "current_apy": null,
    "sharpe_to_date": 0.0,
    "max_drawdown_pct": 0.0,
    "trade_count": 0,
    "state_json": null
  }
}
```

| Key path | Type | Description |
|---|---|---|
| `timestamp` | ISO 8601 | When this snapshot was generated |
| `portfolio.total_capital_usd` | float | Total portfolio value |
| `portfolio.deployed_usd` | float | Capital in open positions |
| `portfolio.cash_pct` | float | Fraction held as cash (0–1) |
| `portfolio.total_pnl_usd` | float | Cumulative PnL |
| `portfolio.total_drawdown_pct` | float | Drawdown from peak (0.05 = 5%) |
| `positions` | array | See `/api/positions` schema |
| `risk.health_approved` | bool | False if any critical violation |
| `risk.violations` | array | Active policy violations |
| `risk.var_usd` | float | Value-at-Risk (95%, 7d) in USD |
| `paper_trading.days_elapsed` | int | Days since first trade |
| `paper_trading.go_live_ready` | bool | True only if all 8 go-live criteria pass |
| `strategy.strategy_id` | string | Active strategy (`paper-v1` or `paper-v2`) |
| `strategy.sharpe_to_date` | float | Sharpe ratio since paper trading began |

---

## protocols.json

**Purpose:** Whitelisted DeFi protocols with their latest APY and TVL snapshots from DeFiLlama.  
**Producer:** `spa_core/data_pipeline/defillama_fetcher.py`

### Schema — array of pool objects

```json
[
  {
    "key": "aave-v3-usdc-ethereum",
    "protocol": "Aave V3",
    "asset": "USDC",
    "chain": "Ethereum",
    "tier": "T1",
    "is_active": 1,
    "apy_total": 4.23,
    "apy_base": 3.80,
    "apy_reward": 0.43,
    "tvl_usd": 138000000.0,
    "last_snapshot": "2026-05-21T18:00:00+00:00"
  }
]
```

| Key | Type | Description |
|---|---|---|
| `key` | string | Unique pool identifier, format `{protocol_slug}-{asset}-{chain}` |
| `tier` | string | Risk tier: `T1` (Aave, Compound, Morpho, Yearn) or `T2` (Maple, Euler, Spark) |
| `is_active` | int | 1 = in whitelist; 0 = disabled |
| `apy_total` | float\|null | Current APY (base + rewards); null if no snapshot yet |
| `apy_reward` | float\|null | Incentive portion of APY |
| `tvl_usd` | float\|null | Total value locked; null until first fetch |
| `last_snapshot` | ISO 8601\|null | Timestamp of last DeFiLlama fetch |

**Note:** null values appear when the GitHub Actions job has not yet fetched live data (e.g., `ANTHROPIC_API_KEY` not set or first run).

---

## pnl_history.json

**Purpose:** Time-series of portfolio state — one record per export cycle. Used to build the equity curve in the dashboard and to compute real-time backtest metrics.  
**Producer:** `spa_core/export_data.py` (appends on each run)

### Schema — array of snapshot objects

```json
[
  {
    "timestamp": "2026-05-21 06:39:39",
    "total_capital_usd": 100000.0,
    "deployed_capital_usd": 0.0,
    "cash_usd": 100000.0,
    "total_pnl_usd": 0.0,
    "total_pnl_pct": 0.0,
    "current_apy": null,
    "trade_count": 0
  }
]
```

| Key | Type | Description |
|---|---|---|
| `timestamp` | string | Local datetime of snapshot |
| `total_capital_usd` | float | Portfolio NAV at this point |
| `deployed_capital_usd` | float | Capital in open positions |
| `total_pnl_usd` | float | Cumulative PnL in USD |
| `total_pnl_pct` | float | PnL as percent of initial capital |
| `current_apy` | float\|null | Weighted average APY across positions |
| `trade_count` | int | Total trades executed so far |

Array grows over time — one entry per 4h cycle. The `ReplayEngine` reads this to build day-by-day frames for `/api/backtest/replay`.

---

## risk_alerts.json

**Purpose:** Active risk policy violations at last export time.  
**Producer:** `spa_core/risk/policy.py` via `export_data.py`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07.363538+00:00",
  "count": 0,
  "status": "ok",
  "alerts": []
}
```

| Key | Type | Description |
|---|---|---|
| `generated_at` | ISO 8601 | Timestamp |
| `count` | int | Number of active alerts |
| `status` | string | `"ok"` or `"alert"` |
| `alerts` | array | Alert objects (see below) |

**Alert object:**
```json
{
  "severity": "CRITICAL",
  "event_type": "CONCENTRATION",
  "protocol_key": "maple-usdc-ethereum",
  "message": "Maple concentration 48% exceeds 45% limit",
  "details": { "concentration": 0.48, "limit": 0.45 },
  "timestamp": "2026-05-21T18:24:07+00:00"
}
```

Severity levels: `CRITICAL`, `WARNING`. Event types: `CONCENTRATION`, `DRAWDOWN`, `APY_DROP`, `LOW_CASH`, `NO_DATA`, `VaR_BREACH`.

---

## alerts.json

**Purpose:** Alerting system output — records which Telegram/email alerts were sent in the last run.  
**Producer:** `spa_core/alerts/` module

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "count": 1,
  "alerts": [
    {
      "severity": "CRITICAL",
      "event_type": "NO_DATA",
      "protocol_key": null,
      "message": "No snapshots in database — data pipeline may be down",
      "details": { "expected_protocols": 7 },
      "timestamp": "2026-05-21T18:24:07+00:00"
    }
  ]
}
```

Similar schema to `risk_alerts.json` but represents alerts that were dispatched externally.

---

## backtest_results.json

**Purpose:** Pre-computed backtest metrics and equity curve from the most recent simulation run.  
**Producer:** `spa_core/backtesting/` module via `export_data.py`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "data_source": "synthetic",
  "policy_version": "v1.0",
  "metrics": {
    "sharpe_ratio": 24.76,
    "max_drawdown_pct": 0.0,
    "total_return_pct": 1.38,
    "annualised_return_pct": 5.71,
    "win_rate": 1.0,
    "total_trades": 14,
    "avg_position_size_usd": 24466.4,
    "initial_capital_usd": 100000.0,
    "final_capital_usd": 101378.69,
    "total_interest_usd": 1378.69,
    "backtest_days": 90
  },
  "equity_curve": [
    {
      "date": "2026-04-22",
      "total_capital": 100970.93,
      "deployed": 95739.42,
      "cash": 5231.51,
      "pnl_pct": 0.97,
      "open_positions": 5
    }
  ]
}
```

`data_source` is `"synthetic"` until enough real paper-trading history accumulates (typically ~14 days). After that, the replay engine switches to `"real"`.

---

## strategy_v2.json

**Purpose:** Portfolio state and risk snapshot for the `paper-v2` (Growth Aggressive) strategy, which runs in parallel with `paper-v1` for comparison.  
**Producer:** `spa_core/export_data.py` via `PaperTrader` with `strategy_id="paper-v2"`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "strategy_id": "paper-v2",
  "strategy_name": "v2 — Growth Aggressive",
  "portfolio": { ... },
  "positions": [],
  "trades": [],
  "risk": { ... },
  "paper_trading": { ... }
}
```

Identical sub-schema to `status.json`. Used by `/api/optimization` as the primary source.

---

## strategy_comparison.json

**Purpose:** Side-by-side comparison metrics for `v1_passive` vs `v2_aggressive`.  
**Producer:** `spa_core/export_data.py`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "strategies": {
    "v1_passive": {
      "total_return_pct": 0.0,
      "current_apy": 0.0,
      "positions_count": 0,
      "cash_pct": 1.0,
      "total_pnl_usd": 0,
      "deployed_usd": 0
    },
    "v2_aggressive": { ... }
  }
}
```

---

## strategy_state.json

**Purpose:** Historical strategy state log — time-series used for performance trend charts.  
**Producer:** `spa_core/export_data.py` (appends on each run, same shape as `pnl_history.json`)

Array of the same snapshot objects as `pnl_history.json`.

---

## optimization_recommendations.json

**Purpose:** Mean-variance optimisation output — recommended target allocation and expected improvement over the current portfolio.  
**Producer:** `spa_core/optimization/` module

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "policy_version": "v1.0",
  "recommendations": [],
  "portfolio_metrics": {
    "expected_return_pct": 0.0,
    "sharpe": 0.0
  },
  "vs_current": {
    "return_improvement_pct": 0.0
  },
  "efficient_frontier": []
}
```

`recommendations` contains reallocation suggestions per protocol when the optimiser finds a better Sharpe-efficient frontier point. `efficient_frontier` is an array of `{risk, return}` points for chart rendering.

---

## golive_readiness.json

**Purpose:** Automated go-live gate evaluation — 8 criteria that must all pass before transitioning to real capital on 2026-07-15.  
**Producer:** `spa_core/golive/checklist.py`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "verdict": "NOT_READY",
  "verdict_emoji": "🔴",
  "days_remaining": 54,
  "go_live_date": "2026-07-15",
  "paper_start_date": "2026-05-20",
  "min_paper_days": 50,
  "summary": "5/8 criteria passing; 1 failing; 2 warning",
  "criteria": [
    {
      "name": "Paper Duration",
      "status": "FAIL",
      "value": 1,
      "threshold": 50,
      "note": "Only 1 days elapsed — too early to evaluate"
    }
  ],
  "recommendation": "Continue paper trading. Next milestone: 2026-07-09.",
  "owner_action_required": false
}
```

| Key | Type | Description |
|---|---|---|
| `verdict` | string | `READY`, `ALMOST_READY`, or `NOT_READY` |
| `criteria[].name` | string | Criterion name |
| `criteria[].status` | string | `PASS`, `WARN`, or `FAIL` |
| `criteria[].value` | any | Current measured value |
| `criteria[].threshold` | any | Required threshold |

**The 8 criteria:** Paper Duration (≥50 days), PnL Positive, No Critical Alerts, Strategy Sharpe (≥1.0), Policy v1.0 active, Max Drawdown (<3%), Diversification (≥2 protocols), Data Freshness (<6h old).

---

## historical_apy.json

**Purpose:** 90-day APY and TVL history per protocol. Used for trend charts and the backtesting engine.  
**Producer:** `spa_core/export_data.py` / `data_pipeline/defillama_fetcher.py`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "data_source": "synthetic",
  "days": 90,
  "protocols": {
    "aave-v3-usdc-ethereum": [
      { "date": "2026-02-21", "apy": 6.05, "tvl_usd": 138742941.0 }
    ]
  }
}
```

`data_source` is `"synthetic"` until real DeFiLlama data has been collected for the full 90-day window.

---

## decision_log.json

**Purpose:** Append-only audit log of every agent decision — allocations, risk checks, and report events.  
**Producer:** `spa_core/agents/decision_logger.py`

### Schema

```json
{
  "generated_at": "2026-05-21T18:24:07+00:00",
  "total_decisions": 2,
  "decisions": [
    {
      "id": 5,
      "timestamp": "2026-05-21T18:24:07+00:00",
      "agent_name": "ReportAgent",
      "decision_type": "REPORT",
      "protocol_key": null,
      "amount_usd": null,
      "reasoning": "Export cycle complete: all JSON files written",
      "data_snapshot": { "files_written": ["status.json", "..."] },
      "policy_version": "v1.0",
      "strategy_id": "paper-v1",
      "risk_check_result": null,
      "outcome": null
    }
  ]
}
```

| Key | Type | Description |
|---|---|---|
| `decision_type` | string | `OPEN`, `CLOSE`, `REBALANCE`, `REPORT`, `HOLD`, `RISK_CHECK` |
| `protocol_key` | string\|null | Target protocol (null for non-trade decisions) |
| `amount_usd` | float\|null | Position size (null for non-trade decisions) |
| `risk_check_result` | object\|null | Full `RiskCheckResult` if a check was performed |
| `outcome` | string\|null | `SUCCESS`, `FAILED`, or null if pending |

---

## trades.json

**Purpose:** Full trade history — every OPEN and CLOSE action executed by `PaperTrader`.  
**Producer:** `spa_core/paper_trading/engine.py` via `export_data.py`

Array of trade records. Returns `[]` until the first allocation is triggered by `auto_allocate`.

```json
[
  {
    "id": 1,
    "timestamp": "2026-05-20T00:00:00+00:00",
    "action": "OPEN",
    "protocol_key": "aave-v3-usdc-ethereum",
    "amount_usd": 40000.0,
    "apy_at_entry": 4.23,
    "reasoning": "Highest risk-adjusted yield in T1 tier"
  }
]
```

---

## bus_stats.json

**Purpose:** Message bus queue statistics — pending, consumed, acked, and dead-letter counts per topic.  
**Producer:** `spa_core/message_bus/bus.py` via `export_data.py`

### Schema

```json
{
  "MARKET_DATA":      { "pending": 0, "consumed": 0, "acked": 0, "dead": 0 },
  "HEALTH_ALERT":     { "pending": 0, "consumed": 0, "acked": 0, "dead": 0 },
  "STRATEGY_SIGNAL":  { "pending": 0, "consumed": 0, "acked": 0, "dead": 0 },
  "TRADE_DECISION":   { "pending": 0, "consumed": 0, "acked": 0, "dead": 0 },
  "EXECUTION_RESULT": { "pending": 0, "consumed": 0, "acked": 0, "dead": 0 }
}
```

Used for internal observability. Non-zero `dead` counts indicate messages that exceeded retry limits.

---

## meta.json

**Purpose:** Metadata about the last export run — version, timestamp, and data source.  
**Producer:** `spa_core/export_data.py` (written last in each cycle)

### Schema

```json
{
  "updated_at": "2026-05-21T18:24:07.277244+00:00",
  "version": "1.0.0",
  "source": "local"
}
```

| Key | Type | Description |
|---|---|---|
| `updated_at` | ISO 8601 | Timestamp of the export that wrote all data files |
| `version` | string | SPA schema version |
| `source` | string | `"local"` (dev run) or `"github_actions"` (CI run) |

The dashboard reads `meta.json` to display the "last updated" time and to detect stale data (>6h triggers a warning).

---

## Files not yet active

These files are referenced in the codebase but not yet written by the current export pipeline (they will appear once paper trading positions exist):

| File | Expected when |
|---|---|
| `pools.json` | DeFiLlama fetch returns data (requires `--fetch` flag or live CI) |
| `latest_report.json` | Weekly PDF report is generated |

The API server gracefully handles missing files by returning empty defaults.

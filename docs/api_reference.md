# SPA API Reference

**Base URL (local):** `http://localhost:8765`  
**Version:** v0.16  
**Framework:** FastAPI (Python)  
**Start:** `python run_server.py` or `uvicorn spa_core.api.server:app --reload --port 8765`  
**Swagger UI:** `http://localhost:8765/docs`

The dashboard auto-detects the server: if `GET /health` returns 200, it switches from static JSON polling to the live API. If the server is not running, the dashboard falls back to reading `data/*.json` directly.

---

## Authentication

None. The server is for local development and GitHub Actions only. CORS is open for `localhost:*` and `yurii-spa.github.io`.

---

## Endpoints

### GET /health

Liveness check. The dashboard polls this on page load to decide between live API and JSON fallback mode.

**Response 200**
```json
{
  "status": "ok",
  "version": "v0.16",
  "timestamp": "2026-05-22T10:00:00+00:00"
}
```

---

### GET /api/portfolio

Current portfolio state — live from `PaperTrader` if the DB is available, otherwise reads `data/status.json`.

**Response 200**
```json
{
  "total_capital_usd": 100000.0,
  "deployed_usd": 35000.0,
  "cash_usd": 65000.0,
  "cash_pct": 0.65,
  "total_pnl_usd": 247.50,
  "total_drawdown_pct": 0.0
}
```

| Field | Type | Description |
|---|---|---|
| `total_capital_usd` | float | Total portfolio value (cash + deployed) |
| `deployed_usd` | float | Capital currently in open positions |
| `cash_usd` | float | Uninvested cash |
| `cash_pct` | float | Cash as a fraction of total capital |
| `total_pnl_usd` | float | Cumulative unrealised + realised PnL |
| `total_drawdown_pct` | float | Current drawdown from peak (0.05 = 5%) |

---

### GET /api/positions

Open positions — live from `PaperTrader`, falling back to `data/status.json`.

**Response 200** — array of position objects
```json
[
  {
    "protocol_key": "aave-v3-usdc-ethereum",
    "protocol": "Aave V3",
    "asset": "USDC",
    "chain": "Ethereum",
    "amount_usd": 40000.0,
    "current_apy": 4.23,
    "unrealised_pnl_usd": 138.40,
    "opened_at": "2026-05-20T00:00:00+00:00"
  }
]
```

Returns `[]` when no positions are open.

---

### GET /api/pools

Latest DeFiLlama APY pool data. Reads `data/pools.json`; falls back to `data/protocols.json` if pools.json is absent.

**Response 200** — array of pool objects (matches `protocols.json` schema)
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
    "last_snapshot": "2026-05-22T10:00:00+00:00"
  }
]
```

| Field | Type | Description |
|---|---|---|
| `key` | string | Unique pool identifier (`{protocol}-{asset}-{chain}`) |
| `tier` | string | Risk tier: `T1` (blue chip) or `T2` (higher risk) |
| `is_active` | int | 1 = whitelisted and active |
| `apy_total` | float\|null | Combined APY (base + reward) in percent |
| `tvl_usd` | float\|null | Total value locked |

---

### GET /api/risk

Risk alerts and VaR metrics. Live from `PaperTrader`; falls back to `data/risk_alerts.json`.

**Response 200**
```json
{
  "generated_at": "2026-05-22T10:00:00+00:00",
  "status": "ok",
  "count": 0,
  "alerts": [],
  "warnings": [],
  "var_usd": 0.0,
  "var_pct": 0.0,
  "var_breach": false
}
```

| Field | Type | Description |
|---|---|---|
| `status` | string | `"ok"` or `"alert"` |
| `count` | int | Number of active violations |
| `alerts` | array | Critical risk policy violations |
| `warnings` | array | Non-blocking warnings |
| `var_usd` | float | Value-at-Risk in USD (95% confidence, 7-day horizon) |
| `var_pct` | float | VaR as % of portfolio |
| `var_breach` | bool | True if VaR exceeds policy limit |

---

### GET /api/trades

Recent paper trades from `data/trades.json`.

**Query parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 20 | Number of most recent trades to return (1–500) |

**Example:** `GET /api/trades?limit=5`

**Response 200** — array of trade records
```json
[
  {
    "id": 1,
    "timestamp": "2026-05-21T12:00:00+00:00",
    "action": "OPEN",
    "protocol_key": "aave-v3-usdc-ethereum",
    "amount_usd": 40000.0,
    "apy_at_entry": 4.23,
    "reasoning": "Highest risk-adjusted yield in T1 tier"
  }
]
```

Returns `[]` if no trades have been executed.

---

### GET /api/backtest

Backtest results from the last synthetic simulation. Reads `data/backtest_results.json`.

**Response 200**
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
    { "date": "2026-04-22", "total_capital": 100970.93, "deployed": 95739.42, "cash": 5231.51, "pnl_pct": 0.97, "open_positions": 5 }
  ]
}
```

---

### GET /api/backtest/replay

Full day-by-day replay of real paper-trading history, or a synthetic simulation if history is unavailable.

**Query parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `days` | int | 90 | Synthetic window length if real history unavailable (1–365) |

**Response 200**
```json
{
  "generated_at": "2026-05-22T10:00:00+00:00",
  "source": "real",
  "total_days": 2,
  "frames": [
    {
      "day": 1,
      "date": "2026-05-20",
      "portfolio_value": 100000.0,
      "deployed": 0.0,
      "cash": 100000.0,
      "pnl_usd": 0.0,
      "pnl_pct": 0.0
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `source` | string | `"real"` (from pnl_history) or `"synthetic"` (simulated) |
| `total_days` | int | Number of frames |
| `frames` | array | One entry per day |

**Errors:** 500 if `ReplayEngine` fails.

---

### GET /api/backtest/summary

Summary metrics computed from the full equity curve in `data/pnl_history.json`.

**Response 200**
```json
{
  "generated_at": "2026-05-22T10:00:00+00:00",
  "total_days": 2,
  "total_return_pct": 0.0,
  "annualized_return": 0.0,
  "sharpe_ratio": 0.0,
  "max_drawdown": 0.0,
  "win_rate": 1.0,
  "best_day": 0.0,
  "worst_day": 0.0,
  "data_source": "real"
}
```

**Errors:** 500 if `ReplayEngine` fails.

---

### GET /api/backtest/compare

Side-by-side comparison of `v1_passive` vs `v2_aggressive` strategies on the same synthetic dataset.

**Query parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `days` | int | 90 | Backtest window length (1–365) |
| `seed` | int | 42 | Random seed for reproducibility |

**Response 200**
```json
{
  "generated_at": "2026-05-22T10:00:00+00:00",
  "winner": "v2_aggressive",
  "delta": 0.45,
  "v1_passive": {
    "total_return_pct": 1.10,
    "sharpe_ratio": 1.20,
    "max_drawdown_pct": 0.5
  },
  "v2_aggressive": {
    "total_return_pct": 1.55,
    "sharpe_ratio": 1.45,
    "max_drawdown_pct": 0.8
  }
}
```

Note: `equity_curve` arrays are stripped from the response to keep payload size small.

**Errors:** 500 if `compare_scenarios` fails.

---

### GET /api/optimization

Latest strategy optimisation recommendations. Reads `data/strategy_v2.json`, falling back to `data/strategy_comparison.json`.

**Response 200**
```json
{
  "generated_at": "2026-05-22T10:00:00+00:00",
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

Returns `{"recommendations": [], "status": "no_data"}` if neither file is present.

---

### GET /api/status

Aggregated status — all sections in a single response. Used by the dashboard in single-fetch mode.

**Response 200** (live source)
```json
{
  "timestamp": "2026-05-22T10:00:00+00:00",
  "data_source": "live",
  "portfolio": { ... },
  "positions": [ ... ],
  "risk": { ... },
  "paper_trading": {
    "days_elapsed": 2,
    "weeks_elapsed": 0.28,
    "min_weeks_required": 8,
    "go_live_ready": false,
    "first_trade": null
  },
  "strategy": { ... },
  "backtest_summary": { ... },
  "pools_count": 7,
  "server_timestamp": "2026-05-22T10:00:00+00:00"
}
```

When `PaperTrader` is unavailable, `data_source` is `"json"` and the response also includes `risk_alerts` and `recent_trades` (last 5).

---

### POST /api/chat

Ask an LLM agent a question about the portfolio. Routes to the appropriate sub-agent by keyword in the question. Falls back to canned responses when `ANTHROPIC_API_KEY` is not set.

**Request body**
```json
{ "question": "why did you buy maple?" }
```

| Field | Type | Required | Description |
|---|---|---|---|
| `question` | string | yes | Free-text question; must not be empty |

**Response 200**
```json
{
  "agent": "TraderAgent",
  "response": "Maple Finance was selected because its 4.8% APY offered the best risk-adjusted yield...",
  "used_llm": true,
  "timestamp": "2026-05-22T10:00:00+00:00"
}
```

**Errors:** 400 if `question` is empty.

**Agent routing** (keyword-based):
- "risk", "alert", "drawdown" → `RiskAgent`
- "data", "apy", "pool", "llama" → `DataAgent`  
- "report", "summary", "week" → `ReportAgent`
- everything else → `TraderAgent`

---

### POST /api/agent/thought

Push a structured agent event into the SSE ring buffer and broadcast to all WebSocket clients. Called by `export_data.py` during its 4h GitHub Actions run.

**Request body**
```json
{
  "agent": "DataAgent",
  "message": "Fetching DeFiLlama APY for 7 whitelisted pools…",
  "type": "agent_thought",
  "data": { "pools_fetched": 7 }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `agent` | string | yes | Agent name |
| `message` | string | yes | Human-readable event description |
| `type` | string | no | Event type (default: `agent_thought`) |
| `data` | object | no | Arbitrary structured payload |

**Supported types:** `agent_thought`, `agent_action`, `portfolio_update`, `risk_alert`

**Response 200**
```json
{ "ok": true, "event_count": 12 }
```

**Errors:** 400 if `message` is empty.

---

### GET /api/events

Server-Sent Events stream for real-time agent activity. Sends the last 5 historical events on connect, then streams new events as they arrive. A keepalive comment is sent every 25 seconds.

**Connect via EventSource:**
```js
const es = new EventSource('http://localhost:8765/api/events');
es.onmessage = (e) => console.log(JSON.parse(e.data));
```

**Event payload**
```json
{
  "agent": "RiskAgent",
  "message": "Portfolio health OK — no violations",
  "type": "activity",
  "timestamp": "2026-05-22T10:00:00+00:00",
  "data": {}
}
```

**Response headers:** `Content-Type: text/event-stream`, `Cache-Control: no-cache`

---

### GET /api/events/history

Returns the last 50 agent events from the in-memory ring buffer as JSON. Use this for page-load catch-up when SSE is not practical.

**Response 200**
```json
{
  "events": [
    {
      "agent": "DataAgent",
      "message": "Export cycle starting…",
      "type": "agent_thought",
      "timestamp": "2026-05-22T10:00:00+00:00",
      "data": {}
    }
  ],
  "count": 1
}
```

---

### WS /ws/agents

Real-time WebSocket stream of agent activity.

**Connect:**
```js
const ws = new WebSocket('ws://localhost:8765/ws/agents');
```

**On connect** — receives a portfolio snapshot immediately:
```json
{
  "agent": "PortfolioAgent",
  "message": "Connected to SPA agent stream — sending portfolio snapshot",
  "timestamp": "2026-05-22T10:00:00+00:00",
  "type": "snapshot",
  "data": {
    "portfolio": { ... },
    "positions": [ ... ],
    "risk": { ... }
  }
}
```

**Ongoing messages** — rotating agent activity every ~5 seconds:
```json
{
  "agent": "DataAgent",
  "message": "Fetching Aave V3 APY from DeFiLlama…",
  "timestamp": "2026-05-22T10:05:00+00:00",
  "type": "activity"
}
```

**Alert messages** — pushed immediately on risk events:
```json
{
  "agent": "RiskAgent",
  "message": "Concentration limit breached: Maple 48% > 45% max",
  "timestamp": "2026-05-22T10:05:00+00:00",
  "type": "alert",
  "data": { "protocol": "Maple Finance", "concentration": 0.48 }
}
```

**Client ping:** send `"ping"` to receive `{"type": "pong", "timestamp": "..."}`.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SPA_DATA_DIR` | `./data` | Path to the data directory |
| `ANTHROPIC_API_KEY` | — | Enables real LLM responses in `/api/chat` |

---

## Error format

All errors return a JSON body:
```json
{ "detail": { "error": "question must not be empty" } }
```

HTTP 400 — bad request (missing/invalid params)  
HTTP 500 — internal error (engine failure, decode error)

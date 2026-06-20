# SPA REST API Reference

> MP-1530 (v11.46) — Read-Only API for dashboard and Telegram bot.
> All write operations go through the normal CLI/file interface.

## Base URL

| Environment | URL |
|---|---|
| Local (uvicorn) | `http://localhost:8765` |
| Production (future) | `https://api.earn-defi.com` |

## Running locally

```bash
pip install fastapi uvicorn
uvicorn spa_core.api.server:app --port 8765 --reload
```

Or via the existing launchd daemon `com.spa.httpserver` (already configured).

## Authentication

All `GET /api/v1/*` and `GET /api/*` endpoints are **public** (read-only, no auth required).

Admin endpoints (`/admin/*`, `/api/v1/admin/*`) require:

```
Authorization: Bearer <timestamp>.<hmac_sha256_signature>
```

Token generation:
```python
from spa_core.api.auth import get_auth
token = get_auth().generate_token()
```

Key source: `SPA_API_KEY` environment variable → macOS Keychain `SPA_API_KEY`.

## API Client (recommended)

Use `SPAApiClient` — it automatically falls back to file reads if the server is down:

```python
from spa_core.api.client import SPAApiClient

client = SPAApiClient()
status   = client.get_status()     # dict
golive   = client.get_golive()     # dict
adapters = client.get_adapters()   # list[dict]
evidence = client.get_evidence()   # list[dict]
```

---

## Endpoints

### GET /health

Liveness check. Dashboard polls this to decide between live API vs JSON fallback.

**Response**
```json
{
  "status": "ok",
  "version": "v0.17",
  "timestamp": "2026-06-20T08:00:00+00:00"
}
```

---

### GET /api/v1/status

Sprint / KANBAN summary. Reads `done_count` and `sprint_completed` from `KANBAN.json`.

**Response**
```json
{
  "done_count": 1193,
  "sprint": "v11.46",
  "version": "11.46.0",
  "timestamp": "2026-06-20T08:00:00+00:00"
}
```

---

### GET /api/v1/golive

GoLive readiness report — 26 criteria from `GoLiveChecker`.
Reads from `data/golive_status.json` (fast path) or runs inline.

**Response**
```json
{
  "pass_count": 16,
  "total": 26,
  "ready": false,
  "blockers": ["gap_monitor_30d", "autopush_installed"],
  "source": "file",
  "timestamp": "2026-06-20T08:00:00+00:00"
}
```

---

### GET /api/v1/adapters

All registered adapters with tier and live APY.

**Response**
```json
{
  "adapters": [
    {"name": "aave_v3",            "tier": "T1", "apy": 3.5,  "research_only": false},
    {"name": "compound_v3",        "tier": "T1", "apy": 4.8,  "research_only": false},
    {"name": "morpho_steakhouse",  "tier": "T1", "apy": 6.5,  "research_only": false},
    {"name": "pendle_pt",          "tier": "T3", "apy": 12.0, "research_only": true}
  ],
  "count": 20,
  "timestamp": "2026-06-20T08:00:00+00:00"
}
```

---

### GET /api/v1/evidence

Paper trading evidence history. Reads from `data/paper_evidence_history.json`.

**Response**
```json
{
  "data": [
    {"date": "2026-06-10", "apy": 5.2, "capital": 100000},
    {"date": "2026-06-11", "apy": 5.4, "capital": 100512}
  ],
  "source": "file",
  "timestamp": "2026-06-20T08:00:00+00:00"
}
```

---

### GET /api/v1/strategies _(future — v11.50+)_

Strategy tournament leaderboard (Sharpe / Calmar / Ulcer / Rachev).

---

## Legacy Endpoints (v0.x, still active)

| Endpoint | Description |
|---|---|
| `GET /api/portfolio` | Current portfolio state |
| `GET /api/positions` | Open positions |
| `GET /api/pools` | DeFiLlama APY pool data |
| `GET /api/risk` | Risk alerts |
| `GET /api/trades?limit=N` | Recent paper trades |
| `GET /api/backtest` | Backtest results |
| `GET /api/backtest/replay?days=N` | Historical replay frames |
| `GET /api/backtest/summary` | Replay summary metrics |
| `GET /api/backtest/compare` | Strategy comparison |
| `GET /api/optimization` | Strategy optimisation recommendations |
| `GET /api/status` | All sections merged (single-fetch) |
| `GET /api/events` | Server-Sent Events stream |
| `GET /api/events/history` | Last 50 events as JSON |
| `GET /api/apy/trends` | 7-day APY trends |
| `GET /api/apy/history/{key}` | 30-day single-protocol trend |
| `POST /api/chat` | LLM agent chat |
| `WS  /ws/agents` | Real-time agent WebSocket |

---

## Error Format

All endpoints return `200 OK` even on internal errors (defensive design).
Errors are signalled via the `"error"` key in the JSON body:

```json
{"error": "KANBAN.json not found", "timestamp": "2026-06-20T08:00:00+00:00"}
```

HTTP 4xx / 5xx are only returned by FastAPI's built-in validation (e.g., 422 for
wrong query param types, 400 for empty chat body).

---

## OpenAPI / Swagger UI

When the server is running:

- Swagger UI: `http://localhost:8765/docs`
- ReDoc: `http://localhost:8765/redoc`
- OpenAPI JSON: `http://localhost:8765/openapi.json`

---

## Rate Limiting _(stub — v11.45, enforcement in v11.50+)_

Sliding-window: 100 requests / 60 seconds per IP.
Currently advisory only; will be wired as FastAPI middleware in v11.50+.

---

*Updated: 2026-06-20 (MP-1530 v11.46)*

# Running SPA Locally with the Real-Time API

The SPA dashboard works in two modes:

- **Production (GitHub Pages):** reads static JSON files from `data/`
- **Local development:** connects to the FastAPI server for live data and a WebSocket agent activity stream

The server is optional — the dashboard detects it automatically via `GET /health` and falls back to JSON if it isn't running.

---

## Quick Start

### 1. Navigate to the project root

```bash
cd /Users/yuriikulieshov/Documents/SPA_Claude
```

### 2. Install Python dependencies

```bash
pip install fastapi uvicorn websockets
```

Or with the `--break-system-packages` flag if your system Python restricts installs:

```bash
pip install fastapi uvicorn websockets --break-system-packages
```

### 3. Start the server

```bash
python run_server.py
```

The server starts on `http://localhost:8765` with auto-reload enabled. You should see:

```
INFO:     SPA API v0.15 starting — data dir: .../data
INFO:     Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit)
```

### 4. Explore the API (Swagger UI)

Open in your browser:

```
http://localhost:8765/docs
```

All endpoints are listed with try-it-out support.

### 5. Open the dashboard

Open `index.html` directly in your browser (file:// or via a local HTTP server). The dashboard polls `http://localhost:8765/health` on load — if it gets a 200 response, it switches to the live API automatically.

### 6. Connect to the WebSocket agent stream

The agent activity feed streams to:

```
ws://localhost:8765/ws/agents
```

On connect you receive a portfolio snapshot. Afterwards, agent activity messages arrive every 5 seconds:

```json
{"agent": "DataAgent", "message": "Fetching Aave V3 APY from DeFiLlama…", "timestamp": "2026-05-21T17:00:00Z", "type": "activity"}
{"agent": "RiskAgent", "message": "Portfolio health OK — no violations", "timestamp": "2026-05-21T17:00:05Z", "type": "activity"}
```

Risk alerts are pushed immediately with `"type": "alert"`.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness check — returns version and timestamp |
| `GET` | `/api/portfolio` | Current portfolio (capital, PnL, drawdown) |
| `GET` | `/api/positions` | Open positions with unrealised PnL |
| `GET` | `/api/pools` | Latest DeFiLlama APY pool data |
| `GET` | `/api/risk` | Risk alerts and VaR metrics |
| `GET` | `/api/trades?limit=20` | Recent paper trades |
| `GET` | `/api/backtest` | Backtest results and equity curve |
| `GET` | `/api/optimization` | Optimisation recommendations |
| `GET` | `/api/status` | All of the above merged (single-fetch mode) |
| `WS` | `/ws/agents` | Real-time agent activity stream |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPA_DATA_DIR` | `./data` | Path to the data directory containing JSON files |

Example with a custom data directory:

```bash
SPA_DATA_DIR=/path/to/data python run_server.py
```

---

## Notes

- The server is **stateless** — it reads from `data/*.json` and the PaperTrader DB on every request.
- It starts cleanly even if `data/*.json` files don't exist yet (returns empty defaults).
- No authentication is required — this is for local development only.
- CORS is enabled for `localhost:*` and `earn-defi.com` (the production dashboard, via the `api.earn-defi.com` tunnel).

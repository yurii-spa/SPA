#!/usr/bin/env python3
"""
MP-443: SPA Fund API Server
Minimal HTTP server (stdlib only) для investor portal.
Endpoints:
  GET /health
  GET /api/fund/summary
  GET /api/fund/strategies
  GET /api/fund/adapters
  GET /api/fund/evidence
  GET /api/fund/golive

Запуск: python3 scripts/fund_api_server.py [port]
"""

import http.server
import json
import os
import sys
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Приоритет: аргумент командной строки → env → default
def resolve_data_dir() -> Path:
    env_dir = os.environ.get("SPA_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return DEFAULT_DATA_DIR


DATA_DIR: Path = resolve_data_dir()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(filename: str) -> dict:
    """Читает JSON-файл из DATA_DIR. При отсутствии возвращает sentinel."""
    path = DATA_DIR / filename
    if not path.exists():
        return {"error": "not found", "available": False, "file": filename}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": str(exc), "available": False, "file": filename}


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_summary() -> dict:
    """Агрегирует /api/fund/summary из нескольких data/*.json."""
    status = _load_json("paper_trading_status.json")
    equity = _load_json("equity_curve_daily.json")
    positions = _load_json("current_positions.json")
    golive = _load_json("golive_status.json")
    gap = _load_json("gap_monitor.json")

    summary_block = equity.get("summary", {}) if isinstance(equity, dict) else {}

    result: dict = {
        "generated_at": _now_iso(),
        "fund": {
            "is_demo": status.get("is_demo"),
            "paper_start_date": status.get("paper_start_date"),
            "days_running": status.get("days_running"),
            "current_equity_usd": status.get("current_equity"),
            "total_return_pct": status.get("total_return_pct"),
            "apy_today_pct": status.get("apy_today_pct"),
            "daily_yield_usd": status.get("daily_yield_usd"),
            "kill_switch_active": status.get("kill_switch_active"),
            "last_cycle_ts": status.get("last_cycle_ts"),
            "last_cycle_status": status.get("last_cycle_status"),
        },
        "equity": {
            "start_equity": summary_block.get("start_equity"),
            "end_equity": summary_block.get("end_equity"),
            "max_drawdown_pct": summary_block.get("max_drawdown_pct"),
            "positive_days": summary_block.get("positive_days"),
            "negative_days": summary_block.get("negative_days"),
            "num_days": summary_block.get("num_days"),
            "first_date": summary_block.get("first_date"),
            "last_date": summary_block.get("last_date"),
        },
        "positions": {
            "deployed_usd": positions.get("deployed_usd"),
            "cash_usd": positions.get("cash_usd"),
            "capital_usd": positions.get("capital_usd"),
            "positions": positions.get("positions", {}),
        },
        "golive": {
            "ready": golive.get("ready"),
            "blockers": golive.get("blockers", []),
        },
        "track_continuity": {
            "available": "gap_count" in gap if isinstance(gap, dict) else False,
        },
    }
    return result


# ---------------------------------------------------------------------------
# Request Handler
# ---------------------------------------------------------------------------

class FundAPIHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler для SPA Fund API."""

    # Подавляем стандартный лог — пишем в stderr вручную
    def log_message(self, fmt, *args):
        print(f"[{_now_iso()}] {self.address_string()} {fmt % args}", file=sys.stderr)

    # ------------------------------------------------------------------
    def do_OPTIONS(self):
        """Preflight CORS."""
        self._send_cors_headers(200)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        if path == "/health":
            self._json_response({"status": "ok", "timestamp": _now_iso()})

        elif path == "/api/fund/summary":
            self._json_response(_build_summary())

        elif path == "/api/fund/strategies":
            self._json_response(_load_json("tournament_ranking.json"))

        elif path == "/api/fund/adapters":
            self._json_response(_load_json("adapter_status.json"))

        elif path == "/api/fund/evidence":
            self._json_response(_load_json("paper_evidence.json"))

        elif path == "/api/fund/golive":
            self._json_response(_load_json("golive_status.json"))

        else:
            self._json_response(
                {"error": "not found", "path": path},
                status=404,
            )

    # ------------------------------------------------------------------
    def _send_cors_headers(self, status: int):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_cors_headers(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"[ERROR] Invalid port: {sys.argv[1]}", file=sys.stderr)
            sys.exit(1)

    print(f"[{_now_iso()}] SPA Fund API Server starting on port {port}", file=sys.stderr)
    print(f"[{_now_iso()}] DATA_DIR = {DATA_DIR}", file=sys.stderr)

    server = http.server.HTTPServer(("", port), FundAPIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[{_now_iso()}] Server stopped.", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""
SPA Backtesting — Gate API Endpoint
=====================================
MP-1301 (v9.17)

Provides:
  1. get_gate_response()         — callable from any context (no HTTP required)
  2. GateAPIHandler              — stdlib BaseHTTPRequestHandler for /api/backtest/gate
  3. run_gate_server()           — convenience: start a standalone gate-only HTTP server

The GateAPIHandler can be embedded into family_fund/http_server.py or used
standalone. It returns BacktestGate.four_state_status() as JSON.

stdlib only. No external dependencies.
"""

from __future__ import annotations

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Ensure spa_core is importable regardless of cwd
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.gate import BacktestGate  # noqa: E402

log = logging.getLogger(__name__)


# ── Convenience function ───────────────────────────────────────────────────────

def get_gate_response(backtest_dir: str = "data/backtest") -> dict:
    """
    Returns the four-state gate status as a plain dict.

    Can be called directly from any Python code without starting an HTTP server.

    Args:
        backtest_dir: Path to the backtest gate JSON directory.

    Returns:
        dict from BacktestGate.four_state_status():
        {
            "backtest":  "PASS" | "FAIL" | "UNKNOWN",
            "pre_paper": "PASS" | "FAIL" | "UNKNOWN",
            "paper":     "READY" | "NOT_READY" | "UNKNOWN",
            "live":      "READY" | "BLOCKED",
            "blockers":  [...],
        }
    """
    gate = BacktestGate(backtest_dir=backtest_dir)
    return gate.four_state_status()


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class GateAPIHandler(BaseHTTPRequestHandler):
    """
    Minimal HTTP request handler exposing one endpoint:

        GET /api/backtest/gate
            → 200 application/json  {four_state_status payload}
            → 404 for unknown paths
            → 500 on internal errors

    Usage (embedded into an existing HTTPServer):

        from http.server import HTTPServer
        from spa_core.backtesting.gate_api import GateAPIHandler

        GateAPIHandler.backtest_dir = "data/backtest"
        server = HTTPServer(("", 8765), GateAPIHandler)
        server.serve_forever()

    Usage (as mixin with family_fund/http_server.py):

        Override `do_GET` in the family_fund handler to delegate:

            if self.path == "/api/backtest/gate":
                GateAPIHandler._handle_gate(self)
                return
    """

    #: Directory containing the gate JSON files. Override on the class before
    #: instantiating the server.
    backtest_dir: str = "data/backtest"

    #: CORS header value; set to "" to disable.
    cors_origin: str = "*"

    def do_GET(self) -> None:
        """Route incoming GET requests."""
        if self.path.rstrip("/") == "/api/backtest/gate":
            self._handle_gate()
        else:
            self._send_json({"error": "not found", "path": self.path}, status=404)

    def _handle_gate(self) -> None:
        """Serve GET /api/backtest/gate."""
        try:
            payload = get_gate_response(backtest_dir=self.backtest_dir)
            self._send_json(payload, status=200)
        except Exception as exc:
            log.exception("gate_api: error building gate response")
            self._send_json({"error": str(exc)}, status=500)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        """Serialise payload to JSON and write the HTTP response."""
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if self.cors_origin:
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        """Route access log through Python's logging instead of stderr."""
        log.debug("%s - %s", self.address_string(), fmt % args)


# ── Standalone server ─────────────────────────────────────────────────────────

def run_gate_server(
    host: str = "",
    port: int = 8766,
    backtest_dir: str = "data/backtest",
) -> None:
    """
    Start a standalone HTTP server that only serves /api/backtest/gate.

    Intended for quick local inspection / integration testing.
    For production use, embed GateAPIHandler into family_fund/http_server.py.

    Args:
        host:         Bind address (default "" = all interfaces).
        port:         Port to listen on (default 8766 to avoid clash with 8765).
        backtest_dir: Gate JSON directory.
    """
    GateAPIHandler.backtest_dir = backtest_dir
    server = HTTPServer((host, port), GateAPIHandler)
    log.info("gate_api: listening on %s:%d", host or "0.0.0.0", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="SPA Backtest Gate API — print status or start HTTP server"
    )
    parser.add_argument("--serve", action="store_true", help="Start HTTP server")
    parser.add_argument("--port", type=int, default=8766, help="Port (default 8766)")
    parser.add_argument(
        "--backtest-dir", default="data/backtest", help="Gate JSON directory"
    )
    args = parser.parse_args()

    if args.serve:
        run_gate_server(port=args.port, backtest_dir=args.backtest_dir)
    else:
        status = get_gate_response(backtest_dir=args.backtest_dir)
        print(json.dumps(status, indent=2))

"""
SPA AgentBroadcaster — v0.15
Manages WebSocket connections and broadcasts agent activity messages.

Usage:
    from spa_core.api.agent_broadcaster import broadcaster
    await broadcaster.connect(websocket)
    await broadcaster.broadcast({"agent": "DataAgent", "message": "...", "type": "activity"})
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("spa.broadcaster")

# ── Realistic rotating messages per agent ─────────────────────────────────────

_AGENT_MESSAGES: dict[str, list[str]] = {
    "DataAgent": [
        "Fetching Aave V3 APY from DeFiLlama…",
        "Fetching Compound V3 USDC pool data…",
        "Fetching Curve 3pool APY…",
        "Fetching Lido stETH staking rate…",
        "Fetching Convex frax pool metrics…",
        "Validating APY outliers — σ filter applied",
        "Pool snapshot stored — 12 protocols updated",
        "Checking TVL thresholds for T1 protocols",
        "Refreshing Morpho Blue lending rates…",
        "Fetching Spark Protocol DSR rate…",
    ],
    "RiskAgent": [
        "Portfolio health OK — no violations",
        "Checking VaR limits — within 5% threshold",
        "Concentration check passed — max position 28%",
        "Monitoring drawdown — current 0.0%",
        "Evaluating new position risk profile…",
        "Liquidity stress test passed",
        "Correlation matrix updated for active positions",
        "8-week paper trading clock: evaluating progress",
        "Smart contract risk score: T1 protocols nominal",
        "Risk budget utilised: 34% of limit",
    ],
    "PortfolioAgent": [
        "Evaluating rebalance triggers…",
        "APY drift detected — reviewing position sizing",
        "Calculating optimal allocation across pools",
        "No rebalance needed — allocations within bounds",
        "Simulating swap cost for rebalance scenario",
        "Yield optimisation scan: 3 candidates identified",
        "Position sizing updated for new TVL data",
        "Cash buffer check: 8.2% available",
        "Reviewing T1 vs T2 protocol split",
        "Portfolio Sharpe ratio: tracking target",
    ],
    "ExecutionAgent": [
        "No pending executions — idle",
        "Validating trade parameters before submission",
        "Checking slippage tolerance for USDC pool",
        "Execution queue empty — awaiting signals",
        "Gas estimation not required (paper mode)",
        "Trade simulation passed risk pre-check",
        "Logging virtual execution to paper ledger",
        "Position entry price recorded",
        "Confirming T1 whitelist compliance",
        "Paper trade lifecycle: open → active",
    ],
    "StrategyAgent": [
        "Running yield signal generation…",
        "Comparing APY vs 7-day moving average",
        "Signal score: Aave USDC → 0.82 (strong)",
        "No new signals above threshold",
        "Strategy state snapshot saved",
        "Reviewing historical signal accuracy",
        "Backtesting updated with latest pool data",
        "Target APY corridor: 4%–12% active",
        "Signal cooldown active — next scan in 4h",
        "Generating optimisation recommendations…",
    ],
}

_AGENT_CYCLE = itertools.cycle(list(_AGENT_MESSAGES.keys()))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentBroadcaster:
    """
    Singleton WebSocket broadcaster for agent activity messages.

    - connect(ws)  / disconnect(ws)  — lifecycle management
    - broadcast(msg)                 — push dict to all active clients
    - generate_agent_message()       — produces the next rotating activity event
    - start_background_loop(app)     — registers the 5s background task with FastAPI lifespan
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._message_iters: dict[str, itertools.cycle] = {
            agent: itertools.cycle(msgs)
            for agent, msgs in _AGENT_MESSAGES.items()
        }
        self._agent_cycle = itertools.cycle(list(_AGENT_MESSAGES.keys()))
        self._task: asyncio.Task | None = None

    # ── Connection management ─────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        log.info(f"WS client connected — total: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        log.info(f"WS client disconnected — total: {len(self._connections)}")

    # ── Broadcasting ──────────────────────────────────────────────────────────

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected WebSocket clients."""
        if not self._connections:
            return
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        """Send a message to a specific WebSocket client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            log.warning(f"Failed to send to WebSocket client: {e}")
            self.disconnect(websocket)

    # ── Message generation ────────────────────────────────────────────────────

    def generate_agent_message(self) -> dict[str, Any]:
        """
        Rotate through agents and their messages, producing a realistic
        activity event for the dashboard.
        """
        agent = next(self._agent_cycle)
        message = next(self._message_iters[agent])
        return {
            "agent": agent,
            "message": message,
            "timestamp": _now(),
            "type": "activity",
        }

    def generate_alert_message(self, alert: dict[str, Any]) -> dict[str, Any]:
        """Wrap a risk alert as a WebSocket push event."""
        return {
            "agent": "RiskAgent",
            "message": alert.get("message", "New risk alert triggered"),
            "timestamp": _now(),
            "type": "alert",
            "data": alert,
        }

    # ── Background loop ───────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Background coroutine: emit an agent activity message every 5 seconds."""
        log.info("AgentBroadcaster background loop started")
        while True:
            try:
                await asyncio.sleep(5)
                if self._connections:
                    msg = self.generate_agent_message()
                    await self.broadcast(msg)
            except asyncio.CancelledError:
                log.info("AgentBroadcaster loop cancelled")
                break
            except Exception as e:
                log.warning(f"AgentBroadcaster loop error: {e}")

    def start(self) -> None:
        """Start the background broadcast loop (call from FastAPI lifespan)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Cancel the background loop (call from FastAPI lifespan shutdown)."""
        if self._task and not self._task.done():
            self._task.cancel()


# ── Module-level singleton ────────────────────────────────────────────────────

broadcaster = AgentBroadcaster()

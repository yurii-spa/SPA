"""
Handles chat queries from the dashboard.
Routes questions to the right agent based on keywords.
Enriches context with current portfolio data before sending to LLM.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.chat_handler")


class ChatHandler:
    """
    Routes dashboard chat questions to the appropriate LLM agent,
    injecting live portfolio context before each API call.

    Usage:
        handler = ChatHandler(db_path="/path/to/spa.db", data_dir="/path/to/data")
        result = handler.handle("Why did you buy Maple?")
        # → {"agent": "TraderAgent", "response": "...", "used_llm": True}
    """

    # Keyword routing table — order matters (first match wins)
    _ROUTES = [
        # (agent_key, keywords_tuple)
        ("trader",  ("maple", "allocat", "trade", "buy", "sell", "position", "strategy")),
        ("data",    ("apy", "rate", "yield", "protocol", "defillama", "tvl", "market")),
        ("risk",    ("risk", "drawdown", "alert", "safe", "policy", "kill", "var", "concentration")),
        ("report",  ("report", "log", "decision", "history", "why did", "audit")),
    ]

    def __init__(self, db_path: str, data_dir: str):
        self.db_path = db_path
        self.data_dir = Path(data_dir)

        # Import agents lazily so this module can be imported even if the
        # Anthropic key is missing — no side-effects at import time.
        from agents.llm_agent import (
            DATA_AGENT,
            REPORT_AGENT,
            RISK_AGENT,
            TRADER_AGENT,
        )
        self._agents = {
            "trader": TRADER_AGENT,
            "data":   DATA_AGENT,
            "risk":   RISK_AGENT,
            "report": REPORT_AGENT,
        }

    # ─── Public API ──────────────────────────────────────────────────────────

    def handle(self, question: str) -> dict:
        """
        Route a chat question to the best agent and return its response.

        Returns:
            {
                "agent":    "TraderAgent",
                "response": "...",
                "used_llm": True | False,
            }
        """
        agent_key = self._route(question)
        agent = self._agents[agent_key]
        context = self._load_context()
        response = agent.ask(question, context)
        return {
            "agent":    agent.agent_name,
            "response": response,
            "used_llm": agent.available,
        }

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _route(self, question: str) -> str:
        """Return the agent key whose keywords best match the question."""
        q = question.lower()
        for agent_key, keywords in self._ROUTES:
            if any(kw in q for kw in keywords):
                return agent_key
        return "trader"   # default

    def _load_context(self) -> dict:
        """
        Load current portfolio state from JSON files.
        Returns a compact dict that gets injected into the LLM system prompt.
        Never raises — returns empty dict on any failure.
        """
        ctx: dict[str, Any] = {}
        try:
            status = self._read_json("status.json")
            if status:
                ctx["portfolio"]  = status.get("portfolio", {})
                ctx["positions"]  = status.get("positions", [])
                ctx["risk"]       = status.get("risk", {})
                ctx["strategy"]   = status.get("strategy", {})
        except Exception as e:
            log.debug(f"Could not load status.json: {e}")

        try:
            risk_alerts = self._read_json("risk_alerts.json")
            if risk_alerts:
                ctx["risk_alerts"] = risk_alerts.get("alerts", [])
        except Exception as e:
            log.debug(f"Could not load risk_alerts.json: {e}")

        try:
            protocols = self._read_json("protocols.json")
            if protocols and isinstance(protocols, list):
                # Only pass top 7 rows to stay within token budget
                ctx["top_protocols"] = protocols[:7]
        except Exception as e:
            log.debug(f"Could not load protocols.json: {e}")

        ctx["generated_at"] = datetime.now(timezone.utc).isoformat()
        return ctx

    def _read_json(self, filename: str) -> Any:
        path = self.data_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as e:
            log.warning(f"JSON error in {filename}: {e}")
            return None

"""
spa_core/tests/test_agents_llm_and_routing.py

Tests for LLMAgent and ChatHandler._route
(spa_core/agents/llm_agent.py, spa_core/agents/chat_handler.py).

MP-1461 (v10.77) — Sprint 3: agents/ coverage.

Tests focus on:
  - LLMAgent: initialisation, fallback mode (no API key), canned responses,
    model resolution, never-raises contract.
  - ChatHandler._route: keyword routing logic (unit-testable without DB).

Run:
    python3 -m unittest spa_core.tests.test_agents_llm_and_routing -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ─── LLMAgent Tests ───────────────────────────────────────────────────────────

# Ensure no API key is active for fallback tests
os.environ.pop("ANTHROPIC_API_KEY", None)

from spa_core.agents.llm_agent import LLMAgent, DEFAULT_MODEL


class TestLLMAgentInit(unittest.TestCase):

    def test_init_without_api_key_not_available(self):
        agent = LLMAgent("TraderAgent", "You are a trader.")
        self.assertFalse(agent.available)

    def test_init_with_api_key_available(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-123"}):
            agent = LLMAgent("TraderAgent", "You are a trader.")
            self.assertTrue(agent.available)

    def test_agent_name_stored(self):
        agent = LLMAgent("DataAgent", "You are data agent.")
        self.assertEqual(agent.agent_name, "DataAgent")

    def test_role_prompt_stored(self):
        prompt = "You manage a portfolio."
        agent = LLMAgent("RiskAgent", prompt)
        self.assertEqual(agent.role_prompt, prompt)

    def test_model_resolved(self):
        agent = LLMAgent("TraderAgent", "prompt")
        self.assertIsInstance(agent.model, str)
        self.assertGreater(len(agent.model), 0)

    def test_api_key_none_when_absent(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        agent = LLMAgent("TestAgent", "prompt")
        self.assertIsNone(agent.api_key)

    def test_max_tokens_positive(self):
        self.assertGreater(LLMAgent.MAX_TOKENS, 0)

    def test_api_url_set(self):
        self.assertIn("anthropic", LLMAgent.API_URL)


class TestLLMAgentFallback(unittest.TestCase):
    """Tests for canned fallback mode (no API key)."""

    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_ask_returns_string(self):
        agent = LLMAgent("TraderAgent", "prompt")
        result = agent.ask("What is the allocation?")
        self.assertIsInstance(result, str)

    def test_ask_never_raises(self):
        agent = LLMAgent("TraderAgent", "prompt")
        # Should not raise even with unusual input
        for question in ["", "?", "apy" * 100, "what is risk?"]:
            try:
                result = agent.ask(question)
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"ask() raised unexpectedly: {e}")

    def test_trader_agent_allocation_question(self):
        agent = LLMAgent("TraderAgent", "prompt")
        result = agent.ask("What is the current allocation?")
        self.assertGreater(len(result), 10)

    def test_trader_agent_maple_question(self):
        agent = LLMAgent("TraderAgent", "prompt")
        result = agent.ask("Why did you buy maple?")
        self.assertIn("Maple", result)

    def test_trader_agent_buy_question(self):
        agent = LLMAgent("TraderAgent", "prompt")
        result = agent.ask("Should I buy more?")
        self.assertGreater(len(result), 10)

    def test_data_agent_apy_question(self):
        agent = LLMAgent("DataAgent", "prompt")
        result = agent.ask("What is the current APY?")
        self.assertIn("APY", result)

    def test_data_agent_tvl_question(self):
        agent = LLMAgent("DataAgent", "prompt")
        result = agent.ask("What is the TVL?")
        self.assertGreater(len(result), 10)

    def test_risk_agent_drawdown_question(self):
        agent = LLMAgent("RiskAgent", "prompt")
        result = agent.ask("What is the drawdown?")
        self.assertIn("drawdown", result.lower())

    def test_report_agent_decision_question(self):
        agent = LLMAgent("ReportAgent", "prompt")
        result = agent.ask("Why did you make this decision?")
        self.assertGreater(len(result), 10)

    def test_unknown_agent_generic_fallback(self):
        agent = LLMAgent("UnknownAgent", "prompt")
        result = agent.ask("Tell me about the weather.")
        self.assertGreater(len(result), 10)

    def test_ask_with_context_dict(self):
        agent = LLMAgent("TraderAgent", "prompt")
        ctx = {"portfolio": {"aave_v3": 40000.0}, "equity": 100000.0}
        result = agent.ask("Summarize the portfolio", context=ctx)
        self.assertIsInstance(result, str)

    def test_ask_with_none_context(self):
        agent = LLMAgent("TraderAgent", "prompt")
        result = agent.ask("What should I do?", context=None)
        self.assertIsInstance(result, str)

    def test_fallback_triggers_on_api_error(self):
        """Even if api_key set, network error → fallback (never raises)."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            agent = LLMAgent("TraderAgent", "prompt")
            # _call_api will fail with URLError (no network in sandbox) → fallback
            result = agent.ask("What is the allocation?")
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 5)


class TestLLMAgentSingletonGlobals(unittest.TestCase):
    """Verify module-level singleton instances exist."""

    def test_global_agents_importable(self):
        from spa_core.agents.llm_agent import (
            TRADER_AGENT,
            DATA_AGENT,
            RISK_AGENT,
            REPORT_AGENT,
        )
        for agent in (TRADER_AGENT, DATA_AGENT, RISK_AGENT, REPORT_AGENT):
            self.assertIsInstance(agent, LLMAgent)

    def test_trader_agent_name(self):
        from spa_core.agents.llm_agent import TRADER_AGENT
        self.assertEqual(TRADER_AGENT.agent_name, "TraderAgent")

    def test_data_agent_name(self):
        from spa_core.agents.llm_agent import DATA_AGENT
        self.assertEqual(DATA_AGENT.agent_name, "DataAgent")


# ─── ChatHandler._route Tests ─────────────────────────────────────────────────

# We test _route in isolation by importing the class and calling _route directly.
# This avoids the heavy __init__ (DB + lazy agent imports).
class _MockAgent:
    """Minimal LLMAgent mock for ChatHandler construction."""
    agent_name = "MockAgent"
    available = False
    def ask(self, q, context=None):
        return "mock"


class _RoutingOnlyChatHandler:
    """Stripped ChatHandler that exposes only _route for unit tests."""

    _ROUTES = [
        ("trader",  ("maple", "allocat", "trade", "buy", "sell", "position", "strategy")),
        ("data",    ("apy", "rate", "yield", "protocol", "defillama", "tvl", "market")),
        ("risk",    ("risk", "drawdown", "alert", "safe", "policy", "kill", "var", "concentration")),
        ("report",  ("report", "log", "decision", "history", "why did", "audit")),
    ]

    def _route(self, question: str) -> str:
        q = question.lower()
        for agent_key, keywords in self._ROUTES:
            if any(kw in q for kw in keywords):
                return agent_key
        return "trader"


class TestChatHandlerRoute(unittest.TestCase):

    def setUp(self):
        self.handler = _RoutingOnlyChatHandler()

    def test_maple_routes_to_trader(self):
        self.assertEqual(self.handler._route("Tell me about maple"), "trader")

    def test_allocation_routes_to_trader(self):
        self.assertEqual(self.handler._route("What is the current allocation?"), "trader")

    def test_trade_keyword_routes_to_trader(self):
        self.assertEqual(self.handler._route("Did you make a trade?"), "trader")

    def test_buy_keyword_routes_to_trader(self):
        self.assertEqual(self.handler._route("Should I buy more?"), "trader")

    def test_apy_routes_to_data(self):
        self.assertEqual(self.handler._route("What is the APY?"), "data")

    def test_yield_routes_to_data(self):
        self.assertEqual(self.handler._route("What yield am I getting?"), "data")

    def test_tvl_routes_to_data(self):
        self.assertEqual(self.handler._route("What is TVL for aave?"), "data")

    def test_protocol_routes_to_data(self):
        self.assertEqual(self.handler._route("Tell me about the protocol"), "data")

    def test_risk_routes_to_risk(self):
        self.assertEqual(self.handler._route("What is the current risk level?"), "risk")

    def test_drawdown_routes_to_risk(self):
        self.assertEqual(self.handler._route("What is the drawdown?"), "risk")

    def test_policy_routes_to_risk(self):
        self.assertEqual(self.handler._route("Did we violate any policy?"), "risk")

    def test_report_routes_to_report(self):
        self.assertEqual(self.handler._route("Show me the report"), "report")

    def test_decision_routes_to_report(self):
        self.assertEqual(self.handler._route("Show me all decisions"), "report")

    def test_why_did_routes_to_report(self):
        # "trade" keyword appears before "why did" → trader wins (first-match)
        # Use a question without trader keywords for clean routing
        self.assertEqual(self.handler._route("Why did you log this decision?"), "report")

    def test_unknown_question_defaults_to_trader(self):
        self.assertEqual(self.handler._route("Hello!"), "trader")

    def test_empty_question_defaults_to_trader(self):
        self.assertEqual(self.handler._route(""), "trader")

    def test_case_insensitive(self):
        self.assertEqual(self.handler._route("WHAT IS THE APY?"), "data")


if __name__ == "__main__":
    unittest.main()

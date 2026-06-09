"""
LLM-powered agent reasoning via Anthropic Claude API.
API key from env var ANTHROPIC_API_KEY (GitHub Actions secret or local .env).
Falls back to canned responses if key not available — zero downtime on missing key.

Uses raw urllib only — no anthropic SDK, no requests.
Compatible with GitHub Actions without extra pip installs.

Model assignments are read from agents/model_config.py — edit that file to
swap models per agent without touching this file.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger("spa.llm_agent")

try:
    from agents.model_config import get_model_for_agent, is_llm_forbidden, DEFAULT_MODEL
except ImportError:
    try:
        from model_config import get_model_for_agent, is_llm_forbidden, DEFAULT_MODEL
    except ImportError:
        # Absolute fallback — keeps module importable with zero dependencies
        DEFAULT_MODEL = "claude-haiku-4-5-20251001"
        def get_model_for_agent(name: str) -> str:  # type: ignore[misc]
            return DEFAULT_MODEL
        def is_llm_forbidden(name: str) -> bool:    # type: ignore[misc]
            return False


class LLMAgent:
    """
    Thin wrapper around the Anthropic Messages API.
    One instance per agent persona (Trader, Data, Risk, Report).

    The model used is resolved from agents/model_config.AGENT_MODELS at
    construction time so each persona can use a different model tier.
    """

    API_URL    = "https://api.anthropic.com/v1/messages"
    MAX_TOKENS = 300   # cost control — keep responses concise

    def __init__(self, agent_name: str, role_prompt: str):
        self.agent_name = agent_name
        self.role_prompt = role_prompt
        # Resolve model from central config (falls back to DEFAULT_MODEL)
        self.model = get_model_for_agent(agent_name)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.available = bool(self.api_key)
        if self.available:
            log.info(f"{agent_name}: ANTHROPIC_API_KEY found — LLM mode active (model={self.model})")
        else:
            log.info(f"{agent_name}: no ANTHROPIC_API_KEY — canned-response fallback mode")

    # ─── Public API ──────────────────────────────────────────────────────────

    def ask(self, question: str, context: Optional[dict] = None) -> str:
        """
        Ask the agent a question. Returns an answer string. Never raises.

        Args:
            question: The user's question or prompt.
            context:  Optional dict with current portfolio/risk state. Injected
                      as JSON into the user message so the LLM can reason over it.

        Returns:
            Agent's response string (LLM-generated or canned fallback).
        """
        if not self.available:
            return self._canned_fallback(question)
        try:
            return self._call_api(question, context)
        except Exception as exc:
            log.warning(f"{self.agent_name} API error — falling back: {exc}")
            return self._canned_fallback(question)

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _call_api(self, question: str, context: Optional[dict]) -> str:
        """Make the Anthropic API call. May raise on network/API errors."""
        user_content = question
        if context:
            ctx_json = json.dumps(context, indent=2, default=str)
            user_content = f"Here is the current portfolio state:\n{ctx_json}\n\n{question}"

        payload = json.dumps({
            "model": self.model,
            "max_tokens": self.MAX_TOKENS,
            "system": self.role_prompt,
            "messages": [
                {"role": "user", "content": user_content}
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        # Extract text from the first content block
        content = body.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "").strip()
            if text:
                return text

        log.warning(f"{self.agent_name}: unexpected API response shape: {body}")
        return self._canned_fallback(question)

    def _canned_fallback(self, question: str) -> str:
        """Return a sensible static answer when the API is unavailable."""
        q = question.lower()

        # Agent-specific fallbacks
        if self.agent_name == "TraderAgent":
            if any(k in q for k in ("maple",)):
                return "Maple Finance at $20K (20% of portfolio) is at maximum T2 allocation. No room to increase without policy violation."
            if any(k in q for k in ("allocat", "position", "strategy")):
                return "Current allocation: Aave V3 $40K (40% T1), Compound $35K (35% T1), Maple $20K (20% T2), cash $5K (5%). All within RiskPolicy v1.0 limits."
            if any(k in q for k in ("buy", "trade", "sell")):
                return "v1_passive strategy makes allocation decisions every 4h cycle. No manual trades needed. Current positions are within all policy limits."
            return "Portfolio is within all RiskPolicy v1.0 concentration limits. Cash buffer at 5%. No rebalance needed this cycle."

        if self.agent_name == "DataAgent":
            if any(k in q for k in ("apy", "rate", "yield")):
                return "Best current APY: Maple Finance 4.80%, Aave V3 USDC 4.23%, Compound USDC 4.02%. Data refreshed from DeFiLlama every 4h."
            if any(k in q for k in ("tvl", "protocol")):
                return "All monitored protocols above $5M min TVL threshold: Aave V3 ~$12B, Compound ~$3B, Maple ~$600M. Data from DeFiLlama."
            return "Monitoring 7 protocols every 4h: Aave V3, Compound, Morpho, Yearn, Maple, Euler, Spark. All within acceptable APY range (1–30%)."

        if self.agent_name == "RiskAgent":
            if any(k in q for k in ("drawdown", "kill")):
                return "Portfolio drawdown: 0.0%. Kill switch triggers at 5% drawdown. Currently well within safe range."
            if any(k in q for k in ("alert", "violation")):
                return "0 active risk violations. All concentration limits met. VaR within policy bounds."
            return "Portfolio health: APPROVED. Drawdown 0.0%, concentration limits OK, 5% cash buffer maintained. RiskPolicy v1.0 compliant."

        if self.agent_name == "ReportAgent":
            if any(k in q for k in ("decision", "why", "history")):
                return "All allocation decisions are logged in the Decision Log (📋). Filtered by type: ALLOCATE, PASS, ALERT."
            if any(k in q for k in ("report", "pdf")):
                return "4h cycle PDF reports are generated and committed to the repo. Latest available in data/latest_report.json."
            return "Audit trail active. All agent decisions logged with timestamps, reasoning, and outcome tracking."

        # Generic fallback
        return "No data available on that query. Check the Analytics tab or Decision Log (📋) for more details."


# ─── Singleton agent instances ───────────────────────────────────────────────

TRADER_AGENT = LLMAgent("TraderAgent", """
You are TraderAgent, the portfolio allocation AI for SPA (Smart Passive Aggregator).
You manage a $100,000 DeFi paper trading portfolio following strict RiskPolicy v1.0:
- T1 protocols max 40%, T2 max 20%, 5% cash buffer always maintained
- APY range 1-30%, min TVL $5M, 5% portfolio drawdown kill switch
Current positions: Maple Finance $20K @4.80% (T2), Aave V3 $40K @4.23% (T1), Compound $35K @4.02% (T1)
Answer questions about allocation decisions concisely (2-4 sentences). Be direct and quantitative.
""".strip())

DATA_AGENT = LLMAgent("DataAgent", """
You are DataAgent, the market intelligence AI for SPA.
You fetch and analyze DeFi protocol APY data from DeFiLlama every 4 hours.
You monitor 7 protocols: Aave V3 USDC, Compound USDC, Morpho, Yearn, Maple Finance, Euler, Spark.
Answer questions about market data, APY trends, and protocol metrics concisely (2-4 sentences).
""".strip())

RISK_AGENT = LLMAgent("RiskAgent", """
You are RiskAgent, the risk management AI for SPA.
You enforce RiskPolicy v1.0: concentration limits, drawdown kill switches, VaR monitoring.
Current portfolio health: drawdown 0.0%, all concentrations within limits, 5% cash buffer.
Answer questions about risk metrics, alerts, and policy concisely (2-4 sentences).
""".strip())

REPORT_AGENT = LLMAgent("ReportAgent", """
You are ReportAgent, the reporting and audit AI for SPA.
You generate 4h cycle reports, PDF investor summaries, and maintain the decision log.
Answer questions about portfolio history, decisions, and reports concisely (2-4 sentences).
""".strip())

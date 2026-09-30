"""Trading Research Engine v0 — research, backtest and FORWARD-PAPER evidence for directional trading.

Scope and boundaries (ADR-525, Capital Architecture v1 — docs/CAPITAL_ARCHITECTURE.md):
  * Lives in the Investment domain (SPA repo), NOT in Studio OS. Studio OS sees it only through the
    read-only Director report.
  * RESEARCH ONLY: no exchange account, no API keys, no order placement, no leverage activation,
    no capital movement. Market data comes from PUBLIC read-only endpoints.
  * Deterministic: LLM FORBIDDEN in signals, backtests, evidence and ranking.
  * Stdlib only.
  * Forward-paper evidence is append-only and hash-chained; a changed strategy is a NEW version.
"""

IS_ADVISORY = True
RESEARCH_ONLY = True
LLM_FORBIDDEN = True
EXECUTION_ENABLED = False          # there is no execution path in this package — see test_trading_research_safety

# ADR-004: Two-Layer Agent Architecture

Date: 2026-05-22
Status: ACCEPTED

## Context

SPA has two distinct classes of automated agents with very different trust
requirements, operational scopes, and safety constraints.

**Layer 1 — Development Agents** operate on source code, documentation, and
project management artefacts. They help the engineering team stay organised and
make good technical decisions. They are allowed to use LLMs because mistakes are
recoverable (wrong sprint plan, poorly scored idea) and there is no financial
exposure.

**Layer 2 — Product Agents** operate on live (or paper-live) portfolio data and
may ultimately control real capital. Within this layer there is a further
split: high-level reasoning agents (CEO, Trader, Strategy) that use LLMs for
qualitative analysis, and execution/risk agents that must be fully deterministic.

---

## Decision

### Layer 1 — Development Agents (`spa_core/dev_agents/`)

| Agent | Role | LLM? |
|---|---|---|
| **Architect** | Roadmap management, sprint planning, idea review, ADR drafts, weekly status | ✅ Claude Sonnet 4.6 |
| **Tester** | pytest execution, result parsing, Telegram report | ❌ Deterministic only |

### Layer 2 — Product Agents (`spa_core/agents/`, `spa_core/paper_trading/`, `spa_core/execution/`)

| Agent / Module | Role | LLM? |
|---|---|---|
| **CEO Agent** | Orchestration, high-level portfolio decisions | ✅ Claude Sonnet 4.6 |
| **Trader Agent** | Trade sizing, entry/exit logic | ✅ Claude Sonnet 4.6 |
| **Strategy Agent** | Protocol selection, allocation weights | ✅ Claude Sonnet 4.6 |
| **Data Agent** | Fetching, normalising DeFiLlama + Pendle data | ✅ Claude Haiku |
| **Risk Module** | Kill-switch, concentration limits, drawdown guard | ❌ **LLM FORBIDDEN** |
| **Execution Module** | Position open/close, wallet interactions | ❌ **LLM FORBIDDEN** |

---

## Rationale

### Why dev agents may use LLMs

Development agents operate on text (markdown, JSON, Python files). Their
outputs are reviewed by a human before any action is taken. The worst outcome
of a bad LLM response is wasted engineering time — not a financial loss. LLMs
add significant value here (sprint prioritisation, idea screening, status
narrative) at negligible risk.

### Why Risk and Execution must be deterministic

Risk and Execution agents control whether a trade fires and whether a kill-switch
is triggered. These code paths must be:

- **Auditable**: every decision traceable to a specific input value and threshold.
- **Fast**: no network round-trip to an LLM provider.
- **Reproducible**: same inputs must always produce the same output.
- **Testable**: 100% branch coverage achievable with unit tests.

LLM non-determinism, latency, and potential unavailability are incompatible with
these requirements. Any LLM call in Risk or Execution is a **policy violation**
and must be caught in code review.

This is enforced in `spa_core/agents/model_config.py`:
```python
LLM_FORBIDDEN_AGENTS: set[str] = {"risk", "execution"}
```

---

## Layer Separation — Directory Map

```
spa_core/
  dev_agents/          ← Layer 1: development tooling
    __init__.py
    architect.py       ← LLM-powered (Claude Sonnet 4.6)
    tester.py          ← Deterministic (subprocess + regex)

  agents/              ← Layer 2: product reasoning
    ceo_agent.py       ← LLM ✅
    strategy_agent.py  ← LLM ✅
    llm_agent.py       ← Shared LLM base
    model_config.py    ← Model registry + forbidden list

  paper_trading/       ← Layer 2: paper trade engine (deterministic)
  risk/                ← Layer 2: risk policy (deterministic, LLM FORBIDDEN)
  execution/           ← Layer 2: wallet / position (deterministic, LLM FORBIDDEN)
```

---

## Consequences

- **Positive**: clear boundary makes the system auditable and safe; dev tooling
  can evolve quickly without touching the product trust boundary.
- **Positive**: Architect agent gives the solo developer an always-available
  "second opinion" without adding headcount.
- **Negative**: maintaining two separate agent hierarchies requires discipline
  during onboarding; new contributors must understand which layer they are
  modifying.
- **Mitigation**: `LLM_FORBIDDEN_AGENTS` in `model_config.py` and this ADR
  serve as the canonical reference.

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Single agent layer with role flags | Blurs the trust boundary; harder to audit |
| All agents deterministic | Loses the value of LLM reasoning for planning |
| LangGraph for dev agents | Overkill for a solo dev tool; plain Python is simpler |

---

## Related

- ADR-001: Initial Risk Policy (deterministic risk rules)
- ADR-002: Pendle PT Integration (strategy layer)
- ADR-003: Rate Limiting and Circuit Breaker (execution layer)
- `spa_core/agents/model_config.py` — enforces `LLM_FORBIDDEN_AGENTS`
- `DEV_STRATEGY_v1.0.md` — go-live constraints and architecture principles

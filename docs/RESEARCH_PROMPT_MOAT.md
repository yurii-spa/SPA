# Research prompt — find a non-obvious DeFi edge that can scale to $10M

> Forward this verbatim to a strong AI researcher / deep-research model.

---

## Your role
You are a senior DeFi quant strategist + protocol-mechanism researcher. I run a real, working DeFi
yield system (described below). I want you to design **ONE non-obvious, defensible way to earn money
in DeFi that could realistically scale to ~$10M/year of value** — an edge that does **not already
exist as a turnkey product**, that a solo operator + an AI coding agent (Claude Code) can actually
build on top of what I already have. Not "another yield aggregator." Not "farm the highest APY." I
want a genuine **moat** — something where the edge persists because it's structurally hard for
others to copy, not just a temporary APY.

## What I already have (build on this, don't reinvent it)
**SPA** — a deterministic, transparency-first DeFi yield system, currently in paper trading (virtual
$100k), building an honest 30-day track record before any real capital. Stack: **Python stdlib only**
in runtime, deterministic, **no LLM in risk/execution** (risk is a hard-coded policy gate). 

Capabilities already built and running:
- **Read-only data layer** over DeFiLlama (yields + token prices via `coins.llama.fi`), CEX perp
  **funding rates from 5 venues** (Binance/Bybit/OKX/KuCoin/Hyperliquid, median, ~2yr history via
  pagination), tokenized-T-bill (RWA) yields, ETH/BTC/LST/LRT prices + staking/restaking APYs. All
  schema-validated, fail-closed (never fabricates a datapoint).
- **~35 protocol adapters** (Aave/Compound/Morpho/Euler/Maple/Yearn/Pendle/Spark + read-only
  tBTC/cbBTC lending). Deterministic **RiskPolicy** gate (TVL floor, concentration caps, drawdown
  kill-switch, min cash) that cannot be overridden.
- A **"Strategy Lab"**: a pluggable strategy interface where any sleeve runs through ONE shared
  backtest harness + ONE live paper-trading service (restart-survival, accumulates a forward track).
  Existing sleeves span stablecoin / ETH / BTC / RWA × neutral(β≈0, funding-hedged) / directional /
  stable. A **promotion engine** scores each sleeve (beats-risk-free-floor, drawdown, walk-forward
  consistency, capacity, tail behavior) and gates promotion RESEARCH→BACKTEST→PAPER→CANARY→FULL.
- **Tier-1 validation**: deflated Sharpe / PSR, out-of-sample, Monte-Carlo, VaR/CVaR, reverse stress,
  net-of-cost, capacity-at-AUM, correlation, **verifiable NAV / proof-of-reserves** (tamper-evident
  hash chain), regime detection.
- Honest finding from our own deep backtest (2024-06→2026-06, real data incl. the Aug-2024 crash):
  **plain crypto-yield sleeves are diversifiers, not edge** — neutral books are low-vol but don't
  beat the ~3.4% tokenized-T-bill floor risk-adjusted; directional books eat the full drawdown; LRT
  restaking dies in crashes (ezETH depeg). So "more APY" is a dead end. The edge must be elsewhere.

What I can build fast with the AI agent: new read-only data feeds, new deterministic strategies in
the Lab, new validation/risk modules, a website + dashboards, on-chain read logic (RPC), API
integrations (anything reachable by stdlib `urllib`). What I do NOT yet have: real custody/execution
(paper only), proprietary order flow, exchange relationships, or large capital.

## The ask
Propose **one** specific, non-banal DeFi money-making strategy/product with a **structural moat**,
targeting ~**$10M/year** at scale. The edge must come from one of: a **mispricing/inefficiency**
others overlook, a **data or measurement advantage** we can uniquely build, a **mechanism/structural
position** (e.g. being the counterparty/router/insurer/aggregator of a flow), a **new primitive**, or
a **cross-protocol/cross-domain arbitrage** that requires real engineering to capture. It must SURVIVE
once known (defensible), fit a deterministic + risk-first + transparency-first operator, and be
buildable incrementally (start tiny in paper, prove it, scale capital).

## Hard filters (reject ideas that fail these)
- **Not already a turnkey product** (no "be a yield aggregator / vault / robo-allocator" — those exist).
- **Edge persists when copied** — explain *why* it doesn't get arbitraged to zero (capital limits,
  complexity, data moat, relationship, regulatory/credibility moat, winner-take-most network effect).
- **Buildable by solo + AI** on the stack above; no need for a 20-person team or exchange license on day 1.
- **Risk-bounded + honest** — no Ponzi/points-farming/ape strategies; must have a real, explainable
  source of yield and a deterministic kill condition.
- **Path from $0→$10M is concrete**, not hand-waved.

## Required output (be specific, quantified, sourced)
1. **The idea** in one paragraph — the edge + the source of the $.
2. **Mechanism** — exactly how it earns, step by step, with a worked numeric example at small + large size.
3. **Why it's a moat** — why it persists when known; what specifically is hard to copy.
4. **Why it doesn't exist yet** (or only crudely) — the gap, and why now (what changed in 2025-2026
   that opens it: new primitives, new data, new venues, regulation, etc.).
5. **Economics to $10M** — the unit economics, capital required, capacity ceiling, realistic
   timeline, and what fraction is fee/spread/yield vs principal-at-risk.
6. **Risks + the deterministic kill conditions** — what breaks it, tail scenarios, and how we'd
   detect/exit (we need hard, codifiable rules — no judgment calls).
7. **Fit to our architecture** — which of our existing pieces it reuses; what NEW feeds/strategies/
   modules we'd build; a phased build roadmap (paper → canary → scale).
8. **The single hardest part** — what's the one thing that, if it works, makes the whole thing real;
   and how to de-risk that first, cheaply, in paper.

Give me 1 deeply-developed primary idea + 2 shorter alternatives. Prioritize **novelty + defensibility
over comfort**. If the honest answer is "the real edge in DeFi at $10M scale is X structural position
that almost nobody occupies," say that and design around it. Cite current (2025-2026) protocols,
numbers, and sources.

# 08 — AI Investment OS Architecture (16 Investment Agents)

> **This is the deep per-agent specification for the AI Investment OS.**
> [`docs/10_agent_architecture.md`](10_agent_architecture.md) is the combined *index* (a one-row
> summary of every agent); this doc is the *detail* for the 16 Investment agents. The Builder OS
> (9 dev-support agents) has its own deep doc, [`docs/09_builder_os_architecture.md`](09_builder_os_architecture.md).
>
> **State of the world (honest).** There are **no autonomous production agents.** This layer is
> **prompts + schemas + architecture only**, at default autonomy **L0 (research) / L1
> (recommendation)**. Every agent is decision-support: it produces documents, scores, and memos for a
> human, never execution. It **builds on existing** `spa_core/{agents,dev_agents,agent_runtime,redteam}`
> and `spa_core/riskwire/` — it does not rebuild them (`docs/02` §2). Per-agent prompt templates live
> in [`prompts/agents/`](../prompts/agents/) (several already exist; the rest are pending — noted
> per-agent below).

---

## 1. Universal contract (applies to every one of the 16)

Read [`docs/06`](06_spa_core_invariants.md) before touching anything here. Every Investment agent
inherits, without exception:

- **Autonomy L0/L1 only.** Output is research or a recommendation for a human. No agent decides an
  allocation, sizes a live position, moves capital, or executes.
- **Universal FORBIDDEN** (superset of `docs/10`): hold private keys / seed phrases, sign, move or
  withdraw funds; bypass, weaken, or override the deterministic **RiskPolicy `v1.0`** or the two-tier
  kill-switch; change allocation without human approval; run autonomous execution; alter strategy
  logic silently; present unverified APY as verified or market guaranteed returns; write secrets to
  files; import `spa_core/execution/`.
- **Deterministic hard gate is elsewhere.** RiskPolicy `v1.0` (`spa_core/risk/policy.py`) is the sole
  hard execution gate. Everything these agents produce — including **Risk Scoring v2** — is
  **advisory only** and is never wired to execution (`docs/06` A2/A4, ADR-YL-004).
- **No LLM in risk/execution/monitoring/kill.** LLM agents may read and reason *around* those paths;
  they may never sit *in* them.
- **Error mode = abstain.** On missing / stale / unverified input, emit **UNKNOWN** (or L0) and stop —
  never fabricate a number, an APY, a TVL, or an on-chain fact. Unknown = "requires verification."
- **Evidence discipline.** Any APY / performance figure carries an evidence level **L0–L6**
  (`docs/37`) plus yield source, risk category, and last-verified date.
- **Storage in NEW research dirs.** Advisory output lands in new research directories, never in the
  runtime `data/*.json` state files or existing `data/*/` subdirs (`docs/06` D10).

The tables below give each agent its **role, inputs, outputs, downstream consumers, allowed actions,
agent-specific FORBIDDEN, validation/error behaviour, human-approval point, and run frequency.** The
"agent-specific FORBIDDEN" line is *in addition to* the universal FORBIDDEN above.

---

## 2. The 16 Investment agents

### 2.1 Chief Investment Agent
Synthesises the house view: reads every downstream agent's output plus Risk Scoring v2 and IC memos,
and produces a **house-view memo and an allocation *proposal*** for the Investment Committee / owner.
It is the top of the recommendation funnel and the last agent before a human decides. It never
resolves conflicting inputs silently — disagreement between, say, Market Regime and Red Team is
surfaced, not averaged away.

| Field | Value |
|---|---|
| Role | Synthesise a house view + allocation **recommendation** |
| Inputs | All 15 other agents' outputs, Risk Scoring v2, IC memos, product-line/tier rules (`docs/34`) |
| Outputs | House-view memo; allocation proposal (advisory) |
| Downstream | Investment Committee (`docs/39`), owner |
| Allowed | Recommend, rank, flag conflicts |
| Agent-specific FORBIDDEN | Decide or set any allocation; execute; auto-resolve conflicting inputs |
| Validation / error | Conflicting inputs → flag and hold, no auto-resolution; stale input → mark UNKNOWN |
| Human approval | **Required** for any proposal to advance |
| Frequency | Weekly (or on IC request) |
| Prompt / code | Prompt *pending*; leans on IC prompt [`prompts/agents/investment_committee_agent.md`](../prompts/agents/investment_committee_agent.md); builds on `spa_core/agents/` (ceo/alpha classes) |

### 2.2 Stablecoin Yield Agent
Searches for and analyses **stablecoin yield mechanisms ≥10%** (the founder mandate; `docs/07` §1a),
explaining *where each yield comes from* and attributing the spread over the live RWA floor to named,
measurable risks. Unexplained spread is treated as unpriced tail risk and the candidate is flagged
for rejection, not promoted.

| Field | Value |
|---|---|
| Role | Find / analyse stablecoin yield mechanisms (≥10%), attribute spread over floor |
| Inputs | DeFiLlama feed, protocol data, Stablecoin Cards (`docs/13`), live RWA floor (`data/rwa_feed.py`, dynamic — never hardcoded) |
| Outputs | Candidate list; yield-source notes; spread-attribution draft |
| Downstream | Yield Lab (`docs/07`), Chief Investment |
| Allowed | Research, candidate generation |
| Agent-specific FORBIDDEN | Claim APY without evidence; treat unexplained spread as alpha |
| Validation / error | Unverifiable APY → L0/UNKNOWN; residual spread → flag as unpriced risk |
| Human approval | At start of any paper test |
| Frequency | Daily |
| Prompt / code | [`prompts/agents/stablecoin_yield_agent.md`](../prompts/agents/stablecoin_yield_agent.md); builds on `strategy_lab/`, `dfb/`, `defillama_feed.py` |

### 2.3 BTC Cycle Agent
Provides **BTC capital-cycle decision-support** — a read on cycle state (accumulate / hold / rotate /
distribute) and a laddered suggestion for a human. It is explicitly **not** a trading signal engine
and is **decision-support only** (ADR-YL-007, `docs/06` E18).

| Field | Value |
|---|---|
| Role | BTC capital-cycle **decision-support** (accumulate / rotate ladder) |
| Inputs | Price / on-chain / macro feeds, BTC cycle framework (`docs/15`, `docs/36`) |
| Outputs | Cycle-state read; ladder suggestion (advisory) |
| Downstream | Chief Investment, owner |
| Allowed | Research, decision-support read |
| Agent-specific FORBIDDEN | Auto-trade; emit an execution signal; present a suggestion as a directive |
| Validation / error | Feed gap → UNKNOWN, no cycle call |
| Human approval | Recommendation only (no capital action without owner) |
| Frequency | Daily |
| Prompt / code | [`prompts/agents/btc_cycle_agent.md`](../prompts/agents/btc_cycle_agent.md) |

### 2.4 ETH Yield Agent
Due-diligence on **ETH staking / restaking / yield** — LST vs LRT, slashing, depeg, points-vs-realised
yield. It must model depeg and slashing explicitly and must never present restaking points or airdrop
speculation as realised yield.

| Field | Value |
|---|---|
| Role | ETH staking / restaking / yield due diligence |
| Inputs | LST/LRT feeds, protocol data, ETH yield framework (`docs/16`) |
| Outputs | ETH yield map; risk notes (depeg/slashing scenarios) |
| Downstream | Yield Lab, Chief Investment |
| Allowed | Research |
| Agent-specific FORBIDDEN | Present restaking points / airdrops as realised yield |
| Validation / error | Depeg & slashing modelled explicitly; missing data → UNKNOWN |
| Human approval | At start of any paper test |
| Frequency | Daily |
| Prompt / code | [`prompts/agents/eth_yield_agent.md`](../prompts/agents/eth_yield_agent.md) |

### 2.5 Market Regime Agent
Classifies the **market regime** (risk-on/off, funding sign, volatility band) with a confidence label,
feeding context to every other agent. It is a *context* signal, never a driver of execution.

| Field | Value |
|---|---|
| Role | Classify regime (risk-on/off, funding, vol) |
| Inputs | Funding / vol / rate feeds |
| Outputs | Regime label + confidence |
| Downstream | All agents (context) |
| Allowed | Research |
| Agent-specific FORBIDDEN | Drive execution directly; over-state confidence on thin history |
| Validation / error | Insufficient history → UNKNOWN |
| Human approval | Advisory (no approval gate) |
| Frequency | Daily |
| Prompt / code | [`prompts/agents/market_regime_agent.md`](../prompts/agents/market_regime_agent.md) |

### 2.6 DeFi Protocol Agent
Runs **protocol due diligence** and produces a **Protocol Card** (`docs/12`) — docs, audits, TVL,
governance, upgradeability. It never certifies a protocol as safe for live use; a Card is an input to
review, not an approval.

| Field | Value |
|---|---|
| Role | Protocol due diligence → Protocol Card |
| Inputs | Protocol docs, audits, TVL, governance data |
| Outputs | Protocol Card (`docs/12` schema) |
| Downstream | Yield Lab, Smart Contract Risk, Red Team |
| Allowed | Research |
| Agent-specific FORBIDDEN | Approve a protocol for live use |
| Validation / error | Missing audit → hard-flag on the Card |
| Human approval | Card review before any paper test |
| Frequency | On demand |
| Prompt / code | [`prompts/agents/protocol_risk_agent.md`](../prompts/agents/protocol_risk_agent.md); builds on `dfb/` overlay, `adapters/` |

### 2.7 Smart Contract Risk Agent
Scores **contract / exploit / upgrade risk** (upgradeability, admin keys, incident history) as an
advisory sub-score feeding Risk Scoring v2 and Red Team. It is explicitly **not** a hard gate.

| Field | Value |
|---|---|
| Role | Contract / exploit / upgradeability risk |
| Inputs | Audits, upgradeability, admin-key config, incident history |
| Outputs | Contract-risk sub-score (advisory) |
| Downstream | Risk Scoring v2 (`docs/14`), Red Team |
| Allowed | Research |
| Agent-specific FORBIDDEN | Act as a hard gate |
| Validation / error | Unknown upgradeability / admin keys → red |
| Human approval | Advisory |
| Frequency | On demand |
| Prompt / code | [`prompts/agents/smart_contract_risk_agent.md`](../prompts/agents/smart_contract_risk_agent.md) |

### 2.8 Stablecoin Risk Agent
Assesses **peg / backing / redemption / depeg** risk and produces a **Stablecoin Card** (`docs/13`)
with depeg scenarios. It never certifies a peg as safe; opaque backing is a hard-flag, not a pass.

| Field | Value |
|---|---|
| Role | Peg / backing / redemption / depeg risk |
| Inputs | Reserve attestations, peg history, redemption terms |
| Outputs | Stablecoin Card + depeg scenarios |
| Downstream | Yield Lab, Red Team, Stablecoin Yield |
| Allowed | Research |
| Agent-specific FORBIDDEN | Certify a peg as safe |
| Validation / error | Opaque / unverifiable backing → hard-flag |
| Human approval | Card review |
| Frequency | On demand |
| Prompt / code | [`prompts/agents/stablecoin_risk_agent.md`](../prompts/agents/stablecoin_risk_agent.md) |

### 2.9 Liquidity Agent
Models **exit liquidity, capacity, and slippage by size** — the capital-tier reality that yield
compression and thin depth impose (`docs/34`, and the capital-scale ceiling finding). It recommends
capacity caps; it never waves capacity concerns away at scale.

| Field | Value |
|---|---|
| Role | Exit-liquidity / capacity / slippage by position size |
| Inputs | Pool depth, exit-NAV models, capital-tier rules |
| Outputs | Liquidity / capacity report + cap recommendation |
| Downstream | Capital Allocation, Chief Investment, Capital Tiers (`docs/34`) |
| Allowed | Research |
| Agent-specific FORBIDDEN | Ignore capacity limits at scale |
| Validation / error | Thin depth → conservative cap recommendation |
| Human approval | Advisory |
| Frequency | On demand |
| Prompt / code | [`prompts/agents/liquidity_agent.md`](../prompts/agents/liquidity_agent.md); relates to exit-NAV / liquidator work |

### 2.10 On-chain Agent
Reads **on-chain signals** — flows, utilisation, whale movement, contract activity — as sourced
observations. It never fabricates an on-chain fact; missing indexer/RPC data yields UNKNOWN.

| Field | Value |
|---|---|
| Role | On-chain signals (flows, utilisation, whales) |
| Inputs | RPC / indexer / DeFiLlama data |
| Outputs | On-chain signal notes (sourced) |
| Downstream | Market Regime, Discovery (`docs/35`) |
| Allowed | Research |
| Agent-specific FORBIDDEN | Fabricate on-chain facts |
| Validation / error | Missing data → UNKNOWN |
| Human approval | Advisory |
| Frequency | Daily |
| Prompt / code | Prompt *pending* |

### 2.11 News & Narrative Agent
Scans **narrative, catalyst, and incident** flow (news, governance forums) and produces a **sourced**
digest. Every claim is cited; an uncited claim is dropped, not repeated as fact.

| Field | Value |
|---|---|
| Role | Narrative / catalyst / incident scan |
| Inputs | News feeds, governance forums |
| Outputs | Narrative digest (every item sourced) |
| Downstream | Chief Investment, Red Team |
| Allowed | Research |
| Agent-specific FORBIDDEN | Present rumour as fact |
| Validation / error | Uncited claim → dropped |
| Human approval | Advisory |
| Frequency | Daily |
| Prompt / code | Prompt *pending* |

### 2.12 Quant & Backtesting Agent
**Backtests candidates on real history** (net-of-cost, risk-adjusted) via the existing backtest
harness. It never presents a backtest as live (that requires L3+), and it flags degenerate metrics on
mock or thin data — a standing lesson from the tournament (mock data → degenerate Sharpe).

| Field | Value |
|---|---|
| Role | Backtest candidates on real history |
| Inputs | Historical feeds, backtest harness (`spa_core/backtesting/`, `strategy_lab/` harness) |
| Outputs | Backtest report (net, risk-adjusted) |
| Downstream | Yield Lab, IC |
| Allowed | Research |
| Agent-specific FORBIDDEN | Present a backtest as live (L3+) |
| Validation / error | Mock / thin data → flag degenerate metrics, mark data quality |
| Human approval | Before any paper test |
| Frequency | On demand |
| Prompt / code | Prompt *pending*; builds on existing backtest harness + `tournament/` |

### 2.13 Red Team Agent
Runs the **adversarial teardown** — "how do we lose money" — against a candidate and all its cards,
answering the mandatory failure-mode questions (`docs/07` §, charter Red-Team list). Red Team is
**mandatory** for Enhanced / Max / Experimental / leverage / credit / counterparty / bridge / opaque /
new-stablecoin / lockup / options / basis strategies. Any unanswered failure mode blocks advancement.

| Field | Value |
|---|---|
| Role | Adversarial teardown (how we lose money / how yield disappears) |
| Inputs | Candidate + Strategy / Protocol / Stablecoin Cards, all risk sub-scores |
| Outputs | Red-Team memo answering the mandatory questions + spread check |
| Downstream | Yield Lab, IC |
| Allowed | Research; **block** advancement on an unanswered failure mode |
| Agent-specific FORBIDDEN | Approve anything (Red Team can block, never approve) |
| Validation / error | Any unanswered failure mode → block |
| Human approval | **Mandatory review** for the triggering categories above |
| Frequency | Per candidate |
| Prompt / code | [`prompts/agents/red_team_agent.md`](../prompts/agents/red_team_agent.md); builds on `spa_core/redteam/` (scenarios, registry, runner, rotation) |

### 2.14 Capital Allocation Agent
Produces **sizing recommendations within caps** (capital tiers, per-protocol / T2 caps, Risk Scoring).
It recommends; it never sets a live allocation. A recommendation that breaches a cap must reject
itself.

| Field | Value |
|---|---|
| Role | Size **recommendations** within caps |
| Inputs | Capital tiers (`docs/34`), RiskPolicy caps, Risk Scoring v2 |
| Outputs | Sizing proposal (advisory) |
| Downstream | Chief Investment, IC, owner |
| Allowed | Recommend |
| Agent-specific FORBIDDEN | Set an allocation live |
| Validation / error | Cap breach → reject own proposal |
| Human approval | **Required** |
| Frequency | Weekly (or on IC request) |
| Prompt / code | [`prompts/agents/capital_allocation_agent.md`](../prompts/agents/capital_allocation_agent.md); relates to `optimization/`, `allocator/` (both advisory here) |

### 2.15 Portfolio Monitoring Agent
Watches **approved sleeves** on the live paper track for drift and breach and raises alerts. It never
triggers the kill-switch or a de-risk itself — the kill path stays **deterministic** in
`spa_core/governance/kill_switch.py` (`docs/06` A2/A3).

| Field | Value |
|---|---|
| Role | Watch approved sleeves for drift / breach |
| Inputs | Live paper track, red-flag monitor (read-only) |
| Outputs | Alerts, drift report |
| Downstream | Reporting, owner |
| Allowed | Research / alert |
| Agent-specific FORBIDDEN | Trigger kill / de-risk itself; write execution-owned state |
| Validation / error | Kill path stays deterministic; agent only observes and alerts |
| Human approval | Alert only (no gate) |
| Frequency | Continuous (paper track) |
| Prompt / code | Prompt *pending*; builds on `monitoring/`, `alerts/` (read-only) |

### 2.16 Reporting Agent
Writes **IC memos and performance / attribution reports** with evidence levels attached to every
number (`docs/41`). It never publishes an unverified figure — missing evidence is marked UNKNOWN, and
nothing paper/backtest is presented as live.

| Field | Value |
|---|---|
| Role | IC memos, performance / attribution reports |
| Inputs | Paper track, attribution, cards, evidence levels |
| Outputs | Reports / memos with per-number evidence levels |
| Downstream | Owner, IC, (future) investors |
| Allowed | Research / drafting |
| Agent-specific FORBIDDEN | Publish an unverified number; present paper/backtest as live |
| Validation / error | Missing evidence → mark UNKNOWN |
| Human approval | Review before publish |
| Frequency | Scheduled |
| Prompt / code | [`prompts/agents/reporting_agent.md`](../prompts/agents/reporting_agent.md); builds on `reporting/`, `riskwire/` (facade, proof) |

---

## 3. How the 16 compose (recommendation funnel)

```
Discovery / feeds
   │
   ├─ Stablecoin Yield · BTC Cycle · ETH Yield · On-chain · News & Narrative  (find / observe)
   │        │
   ├─ Market Regime  (context to all)
   │        ▼
   ├─ DeFi Protocol · Smart Contract Risk · Stablecoin Risk · Liquidity  (due diligence → Cards + sub-scores)
   │        ▼
   ├─ Quant & Backtesting  (net, risk-adjusted evidence)  ──►  Risk Scoring v2 (advisory, docs/14)
   │        ▼
   ├─ Red Team  (adversarial teardown — can BLOCK, never approve)
   │        ▼
   ├─ Capital Allocation  (sizing recommendation within caps)
   │        ▼
   ├─ Chief Investment  (house-view memo + allocation PROPOSAL)
   │        ▼
   │   ┌─────────────────────────────┐
   │   │  HUMAN / IC (docs/39)  ◄── the only place a decision is made
   │   └─────────────────────────────┘
   │        ▼
   └─ Portfolio Monitoring · Reporting  (observe approved sleeves; report with evidence levels)
```

Nothing in this funnel touches the deterministic RiskPolicy `v1.0` gate or the kill-switch. The
Yield Lab lifecycle (`docs/07`) is the state machine these agents feed; the human approval points in
that lifecycle (analyst sign-off → paper test; owner/IC approval → small capital; owner/IC per line →
approved) are the gates, not any agent.

---

## 4. Existing code these agents build on (do not duplicate)

- `spa_core/agents/` — existing agent classes (ceo/alpha/architect/audit-reader/reporting/… + `base.py`).
- `spa_core/agent_runtime/` — `runtime.py`, `budget.py`, `mandate.py` (+ `mandates/`) — the runtime,
  budget, and **mandate** scaffolding that constrains what an agent may do.
- `spa_core/redteam/` — `scenarios.py`, `registry.py`, `runner.py`, `rotation.py`, `base.py` — the
  Red Team agent's engine.
- `spa_core/riskwire/` — `facade.py`, `subjects.py`, `proof.py`, `day30_review.py` — measurement-as-a-
  product surface the Reporting / measurement agents lean on.
- Per-agent prompt templates in [`prompts/agents/`](../prompts/agents/). Existing today:
  `stablecoin_yield_agent`, `btc_cycle_agent`, `eth_yield_agent`, `market_regime_agent`,
  `protocol_risk_agent`, `smart_contract_risk_agent`, `stablecoin_risk_agent`, `liquidity_agent`,
  `red_team_agent`, `capital_allocation_agent`, `reporting_agent`, `investment_committee_agent`.
  **Pending** (no prompt file yet): Chief Investment, On-chain, News & Narrative, Quant & Backtesting,
  Portfolio Monitoring.

---

**Cross-reference:** [`docs/10`](10_agent_architecture.md) (index),
[`docs/09`](09_builder_os_architecture.md) (Builder OS), [`docs/06`](06_spa_core_invariants.md)
(invariants), [`docs/07`](07_yield_lab_architecture.md) (lifecycle these feed),
[`docs/14`](14_risk_scoring_v2.md) (Risk Scoring v2, advisory), [`docs/37`](37_apy_realism_and_evidence_standard.md)
(evidence levels), [`docs/39`](39_investment_committee_workflow.md) (IC workflow),
[`docs/34`](34_capital_tiers_strategy.md) (capital tiers), [`docs/29`](29_backlog.md) (backlog),
[`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md) (charter §22).
